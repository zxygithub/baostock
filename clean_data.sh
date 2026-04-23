#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_FILE="${SCRIPT_DIR}/data/baostock.db"
PYTHON="${SCRIPT_DIR}/.venv/bin/python"

if [ ! -f "$DB_FILE" ]; then
    echo "Database not found: $DB_FILE"
    exit 1
fi

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -a, --all           Clear ALL tables (requires confirmation)
  -t, --table NAME    Clear specific table (can be repeated)
  -l, --list          List all tables with row counts
  -h, --help          Show this help

Examples:
  $(basename "$0") --all
  $(basename "$0") --table all_stock_daily --table index_daily
  $(basename "$0") --list
EOF
}

run_python() {
    local mode="$1"
    shift
    $PYTHON - "$mode" "$DB_FILE" "$@" <<'PYEOF'
import sys, sqlite3

mode = sys.argv[1]
db_path = sys.argv[2]
tables_arg = sys.argv[3:]

TABLES = [
    "adjust_factor", "all_stock", "all_stock_15min", "all_stock_30min", "all_stock_5min",
    "all_stock_60min", "all_stock_daily", "all_stock_monthly", "all_stock_weekly",
    "balance_data", "cash_flow_data", "deposit_rate", "dividend", "dupont_data",
    "forecast_report", "growth_data", "hs300_stocks", "index_daily", "index_monthly",
    "index_weekly", "loan_rate", "money_supply_month", "money_supply_year",
    "operation_data", "performance_express", "profit_data", "request_count", "reserve_ratio",
    "stock_basic", "stock_industry", "sz50_stocks", "trade_dates",
    "zz500_stocks",
]

conn = sqlite3.connect(db_path)

if mode == "list":
    print(f"Available tables ({len(TABLES)}):")
    for t in TABLES:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except:
            cnt = "?"
        print(f"  {t:<30s} {cnt} rows")

elif mode == "clear":
    targets = tables_arg if tables_arg else TABLES
    count = 0
    for t in targets:
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (t,)
        ).fetchone()[0]
        if not exists:
            print(f"  SKIP: {t} (not found)")
            continue
        before = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.execute(f"DELETE FROM {t}")
        conn.commit()
        print(f"  CLEARED: {t} ({before} rows deleted)")
        count += 1
    print(f"\nDone. Cleared {count} tables.")

    total = conn.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()").fetchone()[0]
    print(f"Database size before VACUUM: {total / 1024 / 1024:.1f} MB")
    conn.close()

    print("Checkpointing WAL and VACUUM (requires exclusive access)...")
    try:
        vconn = sqlite3.connect(db_path, isolation_level=None, timeout=30)
        vconn.execute("PRAGMA busy_timeout=30000")
        vconn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        vconn.execute("PRAGMA journal_mode=DELETE")
        vconn.execute("VACUUM")
        vconn.execute("PRAGMA journal_mode=WAL")
        vconn.close()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            print(f"  WARNING: Another process is holding the database lock.")
            print(f"  VACUUM skipped. Close other DB viewers and re-run to reclaim space.")
        else:
            raise
        sys.exit(0)

    final = sqlite3.connect(db_path)
    total_after = final.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()").fetchone()[0]
    saved = total - total_after
    print(f"Database size after VACUUM: {total_after / 1024 / 1024:.1f} MB (reclaimed {saved / 1024 / 1024:.1f} MB)")
    final.close()

conn.close()
PYEOF
}

if [ $# -eq 0 ]; then
    usage
    exit 0
fi

case "$1" in
    -a|--all)
        echo "This will clear ALL 33 tables."
        echo "Database: $DB_FILE"
        echo ""
        read -rp "Are you sure? (y/N) " confirm
        if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
            echo "Cancelled."
            exit 0
        fi
        echo ""
        run_python clear
        ;;
    -t|--table)
        shift
        if [ $# -eq 0 ]; then
            echo "Error: --table requires at least one table name"
            exit 1
        fi
        run_python clear "$@"
        ;;
    -l|--list)
        run_python list
        ;;
    -h|--help)
        usage
        ;;
    *)
        echo "Unknown option: $1"
        echo ""
        usage
        exit 1
        ;;
esac

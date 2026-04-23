#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
DATA_DIR="${SCRIPT_DIR}/data"
DB_FILE="${DATA_DIR}/baostock.db"
PYTHON="${SCRIPT_DIR}/.venv/bin/python"

mkdir -p "$LOG_DIR" "$DATA_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/${TIMESTAMP}.log"

# ─── Helpers ────────────────────────────────────────────────────────────────

run() {
    local cmd="$1"
    local label="$2"
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  ${label}"
    echo "  Log: ${LOG_FILE}"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    echo "[${TIMESTAMP}] START: ${label}" >> "$LOG_FILE"
    echo "───────────────────────────────────────────────────────" >> "$LOG_FILE"

    local exit_code=0
    eval "$cmd" 2>&1 | tee -a "$LOG_FILE" || exit_code=$?

    local end_ts
    end_ts="$(date +%Y%m%d_%H%M%S)"
    echo "───────────────────────────────────────────────────────" >> "$LOG_FILE"
    if [ $exit_code -eq 0 ]; then
        echo "[${end_ts}] DONE: ${label}" >> "$LOG_FILE"
    else
        echo "[${end_ts}] FAILED (exit ${exit_code}): ${label}" >> "$LOG_FILE"
    fi
    echo ""
    return $exit_code
}

status() {
    if [ ! -f "$DB_FILE" ]; then
        echo "  Database: not found"
        return
    fi

    local size
    size=$(du -h "$DB_FILE" | cut -f1)
    echo "  Database: ${DB_FILE} (${size})"
    echo ""

    $PYTHON -c "
import sqlite3
conn = sqlite3.connect('${DB_FILE}')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()
for (t,) in tables:
    try:
        cnt = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        if cnt > 0:
            print(f'  {t}: {cnt:,} rows')
    except:
        pass
conn.close()
" 2>/dev/null || echo "  (unable to read database)"
}

check_db() {
    if [ ! -f "$DB_FILE" ]; then
        echo "Database not found. Run 'init' or 'full' first."
        exit 1
    fi
}

# ─── Commands ───────────────────────────────────────────────────────────────

cmd_init() {
    run "$PYTHON ${SCRIPT_DIR}/scripts/init_db.py" "Initialize Database"
}

cmd_full() {
    check_extra_args
    run "$PYTHON ${SCRIPT_DIR}/scripts/download_all.py $*" "Full Download"
}

cmd_update() {
    check_extra_args
    run "$PYTHON ${SCRIPT_DIR}/scripts/update_daily.py $*" "Daily Update"
}

cmd_status() {
    status
}

cmd_logs() {
    local count
    count=$(find "$LOG_DIR" -name "*.log" 2>/dev/null | wc -l)
    echo "Log files: ${count}"
    echo ""
    if [ "$count" -gt 0 ]; then
        ls -lht "$LOG_DIR"/*.log | awk '{print "  " $5, $6, $7, $8, $9}'
        echo ""
        echo "Latest log:"
        tail -5 "$(find "$LOG_DIR" -name "*.log" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2)"
    else
        echo "  (no logs yet)"
    fi
}

cmd_clean_logs() {
    local keep="${1:-7}"
    echo "Removing logs older than ${keep} days..."
    find "$LOG_DIR" -name "*.log" -mtime +"$keep" -delete
    echo "Done."
}

cmd_clean_tmp() {
    echo "Cleaning temporary tables..."
    $PYTHON -c "
import sqlite3
conn = sqlite3.connect('${DB_FILE}')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_tmp'\").fetchall()
for (t,) in tables:
    conn.execute(f'DROP TABLE IF EXISTS {t}')
    print(f'  Dropped: {t}')
conn.commit()
conn.close()
print('Done.')
" 2>/dev/null || echo "No database found."
}

cmd_help() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  init          Initialize database (create tables)
  full          Full data download (all phases)
  update        Daily incremental update
  status        Show database status and table sizes
  logs          Show recent log files
  clean-logs    Remove logs older than 7 days (pass days as arg)
  clean-tmp     Drop temporary tables (_tmp suffix)
  help          Show this help

Examples:
  $(basename "$0") full
  $(basename "$0") full --skip-financial --skip-minute
  $(basename "$0") update
  $(basename "$0") status
  $(basename "$0") logs
  $(basename "$0") clean-logs 30
  $(basename "$0") clean-tmp
EOF
}

check_extra_args() {
    shift || true
}

# ─── Main ───────────────────────────────────────────────────────────────────

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    init)       cmd_init ;;
    full)       cmd_full "$@" ;;
    update)     cmd_update "$@" ;;
    status)     cmd_status ;;
    logs)       cmd_logs ;;
    clean-logs) cmd_clean_logs "${1:-7}" ;;
    clean-tmp)  check_db; cmd_clean_tmp ;;
    help|--help|-h) cmd_help ;;
    *)
        echo "Unknown command: $COMMAND"
        echo ""
        cmd_help
        exit 1
        ;;
esac

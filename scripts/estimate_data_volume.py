#!/usr/bin/env python3
"""Estimate total row counts for all BaoStock database tables.

Reads stock_basic (IPO dates, delist dates) and trade_dates (trading calendar)
from the database, then calculates expected row counts per table based on
each stock's actual listing period.

Usage:
    .venv/bin/python scripts/estimate_data_volume.py
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "baostock.db"

FINANCIAL_START_YEAR = 2007
REPORT_START_DATE = "2003-01-01"
DIVIDEND_START_YEAR = 2007
MINUTE_DATA_START = "2019-01-02"
# Bars per trading day per frequency (A-share market: 9:30-11:30, 13:00-15:00 = 240 minutes)
MINUTE_BARS_PER_DAY = {
    "5": 48,   # 240 / 5
    "15": 16,  # 240 / 15
    "30": 8,   # 240 / 30
    "60": 4,   # 240 / 60
}
INDEX_COUNT = 8
ADJUST_FLAGS = 3
FINANCIAL_TABLES = [
    "profit_data", "operation_data", "growth_data",
    "balance_data", "cash_flow_data", "dupont_data",
]


def load_stock_info(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT code, code_name, ipo_date, out_date, type, status "
        "FROM stock_basic WHERE type = 1 ORDER BY ipo_date"
    ).fetchall()
    return [
        {"code": r[0], "name": r[1], "ipo_date": r[2], "out_date": r[3], "status": r[5]}
        for r in rows
    ]


def load_trade_dates(conn) -> list[str]:
    rows = conn.execute(
        "SELECT calendar_date FROM trade_dates "
        "WHERE is_trading_day = 1 ORDER BY calendar_date"
    ).fetchall()
    return [r[0] for r in rows]


def count_trading_days(trading_days: list[str], start: str, end: str | None) -> int:
    count = 0
    for d in trading_days:
        if d < start:
            continue
        if end and d > end:
            break
        count += 1
    return count


def estimate_kline(stocks: list[dict], trading_days: list[str]) -> dict[str, int]:
    total_daily = 0
    total_weekly = 0
    total_monthly = 0

    for stock in stocks:
        ipo = stock["ipo_date"]
        if not ipo:
            continue

        days = count_trading_days(trading_days, ipo, stock["out_date"])
        total_daily += days * ADJUST_FLAGS
        total_weekly += (days // 5) * ADJUST_FLAGS
        total_monthly += (days // 21) * ADJUST_FLAGS

    return {
        "all_stock_daily": total_daily,
        "all_stock_weekly": total_weekly,
        "all_stock_monthly": total_monthly,
    }


def estimate_financial(stocks: list[dict]) -> dict[str, int]:
    current_year = datetime.now().year
    table_rows = {t: 0 for t in FINANCIAL_TABLES}

    for stock in stocks:
        ipo = stock["ipo_date"]
        if not ipo:
            continue

        try:
            ipo_year = int(ipo[:4])
        except (ValueError, IndexError):
            ipo_year = FINANCIAL_START_YEAR

        years = current_year - max(FINANCIAL_START_YEAR, ipo_year) + 1
        if years <= 0:
            continue

        quarters = years * 4
        for t in FINANCIAL_TABLES:
            table_rows[t] += quarters

    return table_rows


def estimate_reports(stocks: list[dict]) -> dict[str, int]:
    current_year = datetime.now().year
    express_rows = 0
    forecast_rows = 0

    for stock in stocks:
        ipo = stock["ipo_date"]
        if not ipo:
            continue

        try:
            ipo_year = int(ipo[:4])
        except (ValueError, IndexError):
            ipo_year = 2003

        years = current_year - max(2003, ipo_year) + 1
        if years <= 0:
            continue

        express_rows += years
        forecast_rows += years

    return {"performance_express": express_rows, "forecast_report": forecast_rows}


def estimate_dividend(stocks: list[dict]) -> dict[str, int]:
    current_year = datetime.now().year
    total = 0

    for stock in stocks:
        ipo = stock["ipo_date"]
        if not ipo:
            continue

        try:
            ipo_year = int(ipo[:4])
        except (ValueError, IndexError):
            ipo_year = DIVIDEND_START_YEAR

        years = current_year - max(DIVIDEND_START_YEAR, ipo_year) + 1
        if years <= 0:
            continue

        total += int(years * 0.6)

    return {"dividend": total, "adjust_factor": total}


def estimate_index(trading_days: list[str]) -> dict[str, int]:
    total_days = len(trading_days)
    return {
        "index_daily": INDEX_COUNT * total_days,
        "index_weekly": INDEX_COUNT * (total_days // 5) * ADJUST_FLAGS,
        "index_monthly": INDEX_COUNT * (total_days // 21) * ADJUST_FLAGS,
    }


def estimate_minute_kline(stocks: list[dict], trading_days: list[str]) -> dict[str, int]:
    recent_days = count_trading_days(trading_days, MINUTE_DATA_START, None)
    result = {}

    for stock in stocks:
        ipo = stock["ipo_date"]
        if not ipo:
            continue

        if stock["out_date"] and stock["out_date"] < MINUTE_DATA_START:
            continue

        effective_start = max(MINUTE_DATA_START, ipo)
        stock_days = min(
            count_trading_days(trading_days, effective_start, stock["out_date"]),
            recent_days,
        )
        for freq, bars_per_day in MINUTE_BARS_PER_DAY.items():
            result[f"all_stock_{freq}min"] = result.get(f"all_stock_{freq}min", 0) + stock_days * bars_per_day

    return result


def estimate_macro() -> dict[str, int]:
    return {
        "deposit_rate": 30,
        "loan_rate": 30,
        "reserve_ratio": 50,
        "money_supply_month": 320,
        "money_supply_year": 30,
    }


def main():
    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("请先运行 './start.sh init' 初始化数据库，再下载 stock_basic 和 trade_dates。")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    stocks = load_stock_info(conn)
    trading_days = load_trade_dates(conn)

    print(f"📊 股票数: {len(stocks)}")
    print(f"📅 交易日: {len(trading_days)} ({trading_days[0]} ~ {trading_days[-1]})")

    ipo_years = {}
    for s in stocks:
        if s["ipo_date"]:
            try:
                y = int(s["ipo_date"][:4])
                ipo_years[y] = ipo_years.get(y, 0) + 1
            except (ValueError, IndexError):
                pass

    print(f"\n📈 IPO 年份分布（前10年）:")
    for y in sorted(ipo_years.keys())[:10]:
        print(f"   {y}: {ipo_years[y]} 只")
    print("   ...")

    delisted = [s for s in stocks if s["out_date"]]
    print(f"\n   正常上市: {len(stocks) - len(delisted)} 只")
    print(f"   已退市: {len(delisted)} 只")

    results = {}
    results.update(estimate_kline(stocks, trading_days))
    results.update(estimate_minute_kline(stocks, trading_days))
    results.update(estimate_financial(stocks))
    results.update(estimate_reports(stocks))
    results.update(estimate_dividend(stocks))
    results.update(estimate_index(trading_days))

    meta_tables = ["stock_basic", "trade_dates", "stock_industry",
                   "sz50_stocks", "hs300_stocks", "zz500_stocks"]
    for t in meta_tables:
        try:
            results[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            results[t] = 0

    results.update(estimate_macro())

    categories = {
        "K 线数据（日/周/月）": ["all_stock_daily", "all_stock_weekly", "all_stock_monthly"],
        "分钟 K 线（5/15/30/60）": ["all_stock_5min", "all_stock_15min", "all_stock_30min", "all_stock_60min"],
        "财务数据（6 类）": FINANCIAL_TABLES,
        "公司报告": ["performance_express", "forecast_report"],
        "分红与复权": ["dividend", "adjust_factor"],
        "指数 K 线": ["index_daily", "index_weekly", "index_monthly"],
        "元数据": meta_tables,
        "宏观数据": ["deposit_rate", "loan_rate", "reserve_ratio",
                    "money_supply_month", "money_supply_year"],
    }

    print(f"\n{'=' * 80}")
    print("📋 各表预估总行数（基于实际 IPO 日期计算）")
    print("=" * 80)

    grand_total = 0
    for cat, tables in categories.items():
        print(f"\n  📁 {cat}")
        print(f"  {'─' * 70}")
        cat_total = 0
        for t in tables:
            rows = results.get(t, 0)
            if isinstance(rows, int):
                print(f"    {t:<35} {rows:>12,} 行")
                cat_total += rows
            else:
                print(f"    {t:<35} {rows}")
        print(f"    {'─' * 45}")
        print(f"    {'小计':<35} {cat_total:>12,} 行")
        grand_total += cat_total

    print(f"\n{'=' * 80}")
    print(f"  📊 预估总行数: {grand_total:,} 行")
    print(f"{'=' * 80}")

    stock_count = len(stocks)
    kline_requests = stock_count * 3 * ADJUST_FLAGS
    minute_requests = stock_count * len(MINUTE_BARS_PER_DAY)
    financial_requests = sum(results[t] for t in FINANCIAL_TABLES)
    report_requests = stock_count * 2
    div_requests = stock_count
    index_requests = INDEX_COUNT * 3 * ADJUST_FLAGS
    macro_requests = 5
    meta_requests = 4

    total_requests = (kline_requests + minute_requests + financial_requests +
                      report_requests + div_requests + index_requests +
                      macro_requests + meta_requests)

    daily_limit = 49000

    print(f"\n🔢 API 请求数估算")
    print(f"{'─' * 70}")
    print(f"    K 线（日/周/月 × 3 复权）: {kline_requests:>10,} 次")
    print(f"    分钟线（4 频率）:          {minute_requests:>10,} 次")
    print(f"    财务数据（按 IPO 优化）:   {financial_requests:>10,} 次")
    print(f"    公司报告:                  {report_requests:>10,} 次")
    print(f"    分红数据:                  {div_requests:>10,} 次")
    print(f"    指数 K 线:                 {index_requests:>10,} 次")
    print(f"    宏观数据:                  {macro_requests:>10,} 次")
    print(f"    元数据:                    {meta_requests:>10,} 次")
    print(f"    {'─' * 45}")
    print(f"    总计:                      {total_requests:>10,} 次")
    print(f"    按 {daily_limit:,} 次/天:   {total_requests / daily_limit:.1f} 天")

    conn.close()


if __name__ == "__main__":
    main()

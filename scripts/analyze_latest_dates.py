#!/usr/bin/env python3
"""Analyze the latest data dates for all tables in the BaoStock SQLite database."""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "baostock.db"

TABLE_DATE_COLUMNS = {
    "trade_dates": "calendar_date",
    "stock_basic": None,
    "stock_industry": "update_date",
    "all_stock": "day",
    "all_stock_daily": "date",
    "all_stock_weekly": "date",
    "all_stock_monthly": "date",
    "all_stock_5min": "date",
    "all_stock_15min": "date",
    "all_stock_30min": "date",
    "all_stock_60min": "date",
    "index_daily": "date",
    "index_weekly": "date",
    "index_monthly": "date",
    "dividend": "divid_operate_date",
    "adjust_factor": "divid_operate_date",
    "profit_data": "stat_date",
    "operation_data": "stat_date",
    "growth_data": "stat_date",
    "balance_data": "stat_date",
    "cash_flow_data": "stat_date",
    "dupont_data": "stat_date",
    "performance_express": "performance_exp_pub_date",
    "forecast_report": "profit_forecast_exp_pub_date",
    "sz50_stocks": "update_date",
    "hs300_stocks": "update_date",
    "zz500_stocks": "update_date",
    "deposit_rate": "pub_date",
    "loan_rate": "pub_date",
    "reserve_ratio": "pub_date",
    "money_supply_month": None,
    "money_supply_year": None,
    "request_count": "date",
}


def analyze_table(conn, table: str, date_column: str) -> dict:
    result = {
        "table": table,
        "date_column": date_column,
        "latest_date": None,
        "row_count": 0,
        "error": None,
    }
    
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        result["row_count"] = cursor.fetchone()[0]
        
        if result["row_count"] == 0:
            return result
        
        if date_column:
            cursor = conn.execute(
                f"SELECT MAX({date_column}) FROM {table}"
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                result["latest_date"] = row[0]
        
        if table == "money_supply_month":
            cursor = conn.execute(
                "SELECT MAX(stat_year * 100 + stat_month) FROM money_supply_month"
            )
            row = cursor.fetchone()
            if row and row[0]:
                year = row[0] // 100
                month = row[0] % 100
                result["latest_date"] = f"{year}-{month:02d}"
                result["date_column"] = "stat_year+stat_month"
        
        if table == "money_supply_year":
            cursor = conn.execute(
                "SELECT MAX(stat_year) FROM money_supply_year"
            )
            row = cursor.fetchone()
            if row and row[0]:
                result["latest_date"] = str(row[0])
                result["date_column"] = "stat_year"
    
    except Exception as e:
        result["error"] = str(e)
    
    return result


def main():
    """Main analysis function."""
    if not DB_PATH.exists():
        print(f"❌ Database not found at: {DB_PATH}")
        print("Please run './start.sh init' to initialize the database first.")
        sys.exit(1)
    
    print(f"📊 Analyzing BaoStock database: {DB_PATH}")
    print("=" * 80)
    
    conn = sqlite3.connect(str(DB_PATH))
    
    results = []
    for table, date_column in TABLE_DATE_COLUMNS.items():
        # Check if table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        if not cursor.fetchone():
            continue
        
        result = analyze_table(conn, table, date_column)
        results.append(result)
    
    conn.close()
    
    # Print results
    print(f"\n{'Table Name':<30} {'Date Column':<25} {'Latest Date':<15} {'Row Count':>12}")
    print("-" * 80)
    
    for r in results:
        if r["error"]:
            print(f"❌ {r['table']:<28} Error: {r['error']}")
            continue
        
        latest = r["latest_date"] if r["latest_date"] else "N/A (empty)"
        row_count_str = f"{r['row_count']:,}"
        
        if r["row_count"] == 0:
            print(f"⚪ {r['table']:<28} {r['date_column'] or 'N/A':<25} {'Empty':<15} {row_count_str:>12}")
        else:
            print(f"✅ {r['table']:<28} {r['date_column'] or 'N/A':<25} {latest:<15} {row_count_str:>12}")
    
    print("\n" + "=" * 80)
    print("Summary:")
    
    # Count tables with data
    tables_with_data = [r for r in results if r["row_count"] > 0]
    tables_empty = [r for r in results if r["row_count"] == 0]
    
    print(f"  Total tables analyzed: {len(results)}")
    print(f"  Tables with data: {len(tables_with_data)}")
    print(f"  Empty tables: {len(tables_empty)}")
    
    if tables_with_data:
        print("\nLatest dates by category:")
        
        # K-line data
        kline_tables = [r for r in tables_with_data if "stock" in r["table"] or "index" in r["table"]]
        if kline_tables:
            print("\n  📈 K-Line Data:")
            for r in kline_tables:
                print(f"    {r['table']:<30} {r['latest_date']}")
        
        # Financial data
        financial_tables = [r for r in tables_with_data if r["table"] in 
                          ["profit_data", "operation_data", "growth_data", "balance_data", 
                           "cash_flow_data", "dupont_data"]]
        if financial_tables:
            print("\n  💰 Financial Data (Quarterly):")
            for r in financial_tables:
                print(f"    {r['table']:<30} {r['latest_date']}")
        
        # Macro data
        macro_tables = [r for r in tables_with_data if r["table"] in 
                       ["deposit_rate", "loan_rate", "reserve_ratio", 
                        "money_supply_month", "money_supply_year"]]
        if macro_tables:
            print("\n  🏦 Macro Economic Data:")
            for r in macro_tables:
                print(f"    {r['table']:<30} {r['latest_date']}")
        
        # Other data
        other_tables = [r for r in tables_with_data if r["table"] not in 
                       [t["table"] for t in kline_tables + financial_tables + macro_tables]]
        if other_tables:
            print("\n  📋 Other Data:")
            for r in other_tables:
                print(f"    {r['table']:<30} {r['latest_date']}")
    
    if tables_empty:
        print(f"\n  ⚪ Empty Tables ({len(tables_empty)}):")
        for r in tables_empty:
            print(f"    {r['table']}")


if __name__ == "__main__":
    main()

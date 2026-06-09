#!/usr/bin/env python3
"""统计数据库数据总行数及每天的新增数据量 - 优化版"""

import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "baostock.db"


def get_table_count(cursor, table_name):
    """使用 sqlite 元数据快速估算行数"""
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    except Exception:
        return 0


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()

    # 先获取所有存在的表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    all_tables = [row[0] for row in cursor.fetchall()]

    print("=" * 70)
    print("数据库数据总量统计")
    print("=" * 70)

    total_rows = 0
    table_counts = {}

    # 统计每个表的行数
    for table in all_tables:
        count = get_table_count(cursor, table)
        table_counts[table] = count
        total_rows += count
        print(f"  {table}: {count:,} 行")

    print("=" * 70)
    print(f"数据总行数: {total_rows:,}")
    print("=" * 70)

    # 统计有日期字段的表的每日新增
    date_tables = [
        ("all_stock_daily", "date", "股票日K线"),
        ("index_daily", "date", "指数日K线"),
        ("all_stock_weekly", "date", "股票周K线"),
        ("all_stock_monthly", "date", "股票月K线"),
    ]

    print("\n每天新增数据量 (仅显示主要K线表):")
    print("-" * 70)

    daily_stats = {}

    for table_name, date_field, desc in date_tables:
        if table_name not in all_tables:
            continue

        print(f"\n  [{desc}] {table_name}:")
        cursor.execute(
            f"SELECT {date_field}, COUNT(*) as cnt FROM {table_name} GROUP BY {date_field} ORDER BY {date_field} DESC LIMIT 10"
        )
        rows = cursor.fetchall()
        for date_val, cnt in rows:
            daily_stats.setdefault(date_val, {})[desc] = cnt
            print(f"    {date_val}: {cnt:,} 行")

    # 汇总每日总量
    print("\n" + "=" * 70)
    print("每日新增汇总 (最近30天):")
    print("-" * 70)

    sorted_dates = sorted(daily_stats.keys(), reverse=True)[:30]
    for date_val in sorted_dates:
        tables = daily_stats[date_val]
        day_total = sum(tables.values())
        details = ", ".join(f"{k}: {v:,}" for k, v in sorted(tables.items()))
        print(f"  {date_val}: {day_total:,} 行 ({details})")

    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""修复数据完整性报告中的空洞

读取 data/integrity_report.json，自动补齐：
- L3: K线日期空洞（退市股票缺失最后交易日）
- L5: 复权因子缺失记录
- L6: 指数K线空洞

用法：
    .venv/bin/python scripts/fix_data_gaps.py
    .venv/bin/python scripts/fix_data_gaps.py --level 3        # 仅修复 L3
    .venv/bin/python scripts/fix_data_gaps.py --level 5 6      # 修复 L5 和 L6
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.index_downloader import IndexDownloader
from src.downloaders.dividend_downloader import DividendDownloader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

REPORT_PATH = Path("data/integrity_report.json")


def fix_l3_kline_gaps(report: dict) -> int:
    gaps = report.get("L3_kline_gaps", {}).get("daily", [])
    if not gaps:
        logger.info("L3: 无空洞需要修复")
        return 0

    logger.info(f"L3: 修复 {len(gaps)} 只股票的K线空洞...")
    total = 0
    dl = KlineDownloader(DB_PATH, logger)
    try:
        for gap in gaps:
            code = gap["code"]
            missing_dates = gap["missing_dates"]
            if not missing_dates:
                continue
            start = min(missing_dates)
            end = max(missing_dates)
            logger.info(f"  {code} ({gap['code_name']}): 补齐 {start} ~ {end}")
            rows = dl.download_daily_kline([code], start_date=start, end_date=end)
            total += rows
            time.sleep(0.3)
    finally:
        dl.close()
    logger.info(f"L3: 共补齐 {total} 行")
    return total


def fix_l5_adjust_factor(report: dict) -> int:
    missing = report.get("L5_dividend", {}).get("missing_adjust_factor", [])
    if not missing:
        logger.info("L5: 无复权因子缺失")
        return 0

    codes = sorted(set(m["code"] for m in missing))
    logger.info(f"L5: 修复 {len(codes)} 只股票的复权因子 (共 {len(missing)} 条缺失)...")

    years = [int(m["divid_operate_date"][:4]) for m in missing]
    start_year = min(years)
    start_date = f"{start_year}-01-01"

    dl = DividendDownloader(DB_PATH, logger)
    try:
        total = dl.download_adjust_factor(codes, start_date=start_date)
    finally:
        dl.close()
    logger.info(f"L5: 共补齐 {total} 行")
    return total


def fix_l6_index_gaps(report: dict) -> int:
    gaps = report.get("L6_index", {}).get("daily_gaps", [])
    if not gaps:
        logger.info("L6: 无指数空洞需要修复")
        return 0

    total = 0
    dl = IndexDownloader(DB_PATH, logger)
    try:
        for gap in gaps:
            code = gap["code"]
            missing_dates = gap["missing_dates"]
            if not missing_dates:
                continue
            start = min(missing_dates)
            end = max(missing_dates)
            logger.info(f"  {code}: 补齐 {start} ~ {end} ({len(missing_dates)} 天)")
            rows = dl.download_index_daily(
                [code], start_date=start, end_date=end,
            )
            total += rows
            time.sleep(0.5)
    finally:
        dl.close()
    logger.info(f"L6: 共补齐 {total} 行")
    return total


def main():
    parser = argparse.ArgumentParser(description="修复数据完整性报告中的空洞")
    parser.add_argument(
        "--level", type=int, action="append",
        help="仅修复特定层级 (3/5/6)，可多次指定",
    )
    parser.add_argument(
        "--report", type=str, default=str(REPORT_PATH),
        help="报告文件路径 (默认: data/integrity_report.json)",
    )
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        logger.error(f"报告文件不存在: {report_path}")
        logger.error("请先运行: ./start.sh check")
        sys.exit(1)

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    levels = args.level
    print(f"读取报告: {report_path}")
    print(f"报告时间: {report.get('report_time')}")
    print(f"校验基准日: {report.get('check_date')}")
    print()

    results = {}
    if not levels or 3 in levels:
        results["L3"] = fix_l3_kline_gaps(report)
    if not levels or 5 in levels:
        results["L5"] = fix_l5_adjust_factor(report)
    if not levels or 6 in levels:
        results["L6"] = fix_l6_index_gaps(report)

    print()
    print("=" * 60)
    print("修复完成")
    print("=" * 60)
    for level, rows in results.items():
        print(f"  {level}: {rows:,} 行")


if __name__ == "__main__":
    main()

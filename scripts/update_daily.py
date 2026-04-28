import sys
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.db_manager import DBManager
from src.utils.helpers import setup_logging
from src.downloaders.meta_downloader import MetaDownloader
from src.downloaders.component_downloader import ComponentDownloader
from src.downloaders.index_downloader import IndexDownloader
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.dividend_downloader import DividendDownloader
from src.utils.helpers import get_current_quarter


def main():
    parser = argparse.ArgumentParser(description="BaoStock daily incremental update")
    parser.add_argument("--log-file", default=None, help="Path to log file")
    args = parser.parse_args()

    logger = setup_logging("baostock", args.log_file)
    logger.info("=== BaoStock Daily Incremental Update ===")

    db = DBManager(str(DB_PATH))
    db.migrate_schema()

    last_daily = db.get_max_date("all_stock_daily") or "1990-12-19"
    last_index = db.get_max_date("index_daily") or "2006-01-01"

    start_date = (
        datetime.strptime(last_daily, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    index_start = (
        datetime.strptime(last_index, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    logger.info(f"Stock K-line from: {start_date}")
    logger.info(f"Index K-line from: {index_start}")

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT code FROM stock_basic WHERE type = 1 AND status = 1"
    ).fetchall()
    codes = sorted(row[0] for row in rows)
    conn.close()
    if not codes:
        logger.error("No stock codes found. Run full download first.")
        return

    logger.info(f"Updating {len(codes)} stocks...")

    with MetaDownloader(str(DB_PATH), logger) as dl:
        dl.download_trade_dates()
        dl.download_stock_industry()

    # 程序在凌晨运行，目标是更新截止到前一天的数据
    # 例如：26日凌晨0:05运行 → 更新截止到25日(含)的数据
    # 若25日非交易日，则追溯到最近的交易日（如周五）
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    kline_end_date = db.get_latest_trading_day_on_or_before(target_date)

    if kline_end_date and kline_end_date >= start_date:
        logger.info(f"Latest trading day on or before {target_date}: {kline_end_date}. Proceeding with K-line update.")

        # 周一更新指数成分股（基于 target_date 判断）
        if datetime.strptime(target_date, "%Y-%m-%d").weekday() == 0:
            with ComponentDownloader(str(DB_PATH), logger) as dl:
                dl.download_all_components()

        logger.info("Updating index K-line...")
        with IndexDownloader(str(DB_PATH), logger) as dl:
            dl.download_index_daily(start_date=index_start, end_date=kline_end_date)
            dl.download_index_weekly(start_date=index_start, end_date=kline_end_date)
            dl.download_index_monthly(start_date=index_start, end_date=kline_end_date)

        logger.info("Updating stock daily K-line...")
        with KlineDownloader(str(DB_PATH), logger) as dl:
            dl.download_daily_kline(codes, start_date=start_date, end_date=kline_end_date)
    else:
        logger.info(f"No new trading data found on or before {target_date}. Skipping K-line update.")

    current_year, current_quarter = get_current_quarter()
    logger.info(f"Updating financial data for {current_year} Q{current_quarter}...")
    
    if current_quarter == 1:
        start_quarter = 1
        end_quarter = 1
    else:
        start_quarter = current_quarter - 1
        end_quarter = current_quarter
    
    with FinancialDownloader(str(DB_PATH), logger) as dl:
        dl.download_all_financial(
            codes,
            start_year=current_year,
            end_year=current_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    logger.info(f"Updating dividend data for {current_year}...")
    with DividendDownloader(str(DB_PATH), logger) as dl:
        dl.download_dividend(codes, start_year=current_year, end_year=current_year)
        dl.download_adjust_factor(codes, start_date=start_date)

    db.close()
    logger.info("=== Daily Update Complete ===")


if __name__ == "__main__":
    main()

import sys
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH, DAILY_SHUTDOWN_TIME
from src.db_manager import DBManager
from src.utils.helpers import setup_logging
from src.downloaders.base import is_past_shutdown_time
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

    # 程序在凌晨运行，目标是更新截止到前一天的数据
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    kline_end_date = db.get_latest_trading_day_on_or_before(target_date)

    logger.info(f"DB max date (daily): {last_daily}")
    logger.info(f"DB max date (index):  {last_index}")
    logger.info(f"K-line query range:   {start_date} → {kline_end_date} (target: {target_date})")
    logger.info(f"Index query range:    {index_start} → {kline_end_date}")

    if kline_end_date and kline_end_date >= start_date:
        logger.info(f"Proceeding with K-line update.")

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

        # 周一更新指数成分股（基于 target_date 判断）
        if datetime.strptime(target_date, "%Y-%m-%d").weekday() == 0:
            with ComponentDownloader(str(DB_PATH), logger) as dl:
                dl.download_all_components()

        logger.info("Updating index K-line...")
        with IndexDownloader(str(DB_PATH), logger) as dl:
            dl.download_index_daily(start_date=index_start, end_date=kline_end_date)
            dl.download_index_weekly(start_date=index_start, end_date=kline_end_date)
            dl.download_index_monthly(start_date=index_start, end_date=kline_end_date)

        if is_past_shutdown_time():
            logger.warning(f"已达到每日停止时间 ({DAILY_SHUTDOWN_TIME})，跳过后续阶段，程序退出。")
            db.close()
            return

        logger.info("Updating stock K-line (daily/weekly/monthly)...")
        with KlineDownloader(str(DB_PATH), logger) as dl:
            # 日线：仅更新到最近交易日
            if kline_end_date and kline_end_date >= start_date:
                logger.info(f"Updating daily K-line: {start_date} → {kline_end_date}")
                dl.download_daily_kline(codes, start_date=start_date, end_date=kline_end_date)
            else:
                logger.info(f"No new trading day found. Skipping daily K-line update.")

            # 周线：距上次周线数据 >= 7 天才下载（跨周才有新数据），节省 ~16K 次/天 API 请求
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            latest_weekly = datetime.strptime(db.get_max_date("all_stock_weekly") or "1990-12-19", "%Y-%m-%d")
            should_update_weekly = (target_dt - latest_weekly).days >= 7

            # 月线：仅每月前 3 个交易日下载，节省 ~16K 次/天 API 请求
            latest_monthly = datetime.strptime(db.get_max_date("all_stock_monthly") or "1990-12-19", "%Y-%m-%d")
            first_day_of_month = target_dt.replace(day=1)
            trading_days_so_far = db.get_trading_days_in_range(
                first_day_of_month.strftime("%Y-%m-%d"),
                target_date,
            )
            should_update_monthly = len(trading_days_so_far) <= 3

            if should_update_weekly:
                # Week-completion guard: BaoStock only returns weekly data for completed
                # calendar weeks (Mon-Fri). If the Friday of target_date's week hasn't
                # arrived yet, the week is incomplete and all requests return rows=0.
                friday_of_target_week = target_dt + timedelta(days=(4 - target_dt.weekday()))
                if friday_of_target_week.date() > target_dt.date():
                    logger.info(
                        f"Skipping weekly K-line: target {target_date} "
                        f"({target_dt.strftime('%A')}) is before the Friday of its week "
                        f"({friday_of_target_week.strftime('%Y-%m-%d')}), week not yet complete."
                    )
                else:
                    weekly_start = (latest_weekly + timedelta(days=1)).strftime("%Y-%m-%d")
                    if target_date >= weekly_start:
                        logger.info(f"Updating weekly K-line: {weekly_start} → {target_date}")
                        dl.download_weekly_kline(codes, start_date=weekly_start, end_date=target_date)
                    else:
                        logger.info("Weekly K-line is up to date. Skipping.")
            else:
                logger.info(f"Skipping weekly K-line (latest: {latest_weekly.strftime('%Y-%m-%d')}, {(target_dt - latest_weekly).days}d < 7d).")

            if should_update_monthly:
                monthly_start_dt = latest_monthly + timedelta(days=1)
                monthly_start = monthly_start_dt.strftime("%Y-%m-%d")
                if monthly_start_dt.month == latest_monthly.month and monthly_start_dt.year == latest_monthly.year:
                    logger.info(
                        f"Skipping monthly K-line: start {monthly_start} still in same month as latest data ({latest_monthly.strftime('%Y-%m-%d')}), no complete new month to fetch."
                    )
                elif target_date >= monthly_start:
                    logger.info(f"Updating monthly K-line: {monthly_start} → {target_date}")
                    dl.download_monthly_kline(codes, start_date=monthly_start, end_date=target_date)
                else:
                    logger.info("Monthly K-line is up to date. Skipping.")
            else:
                logger.info(f"Skipping monthly K-line (latest: {latest_monthly.strftime('%Y-%m-%d')}, {len(trading_days_so_far)} trading days into month).")
    else:
        logger.info(f"No new trading data found on or before {target_date}. Skipping K-line update.")

    if is_past_shutdown_time():
        logger.warning(f"已达到每日停止时间 ({DAILY_SHUTDOWN_TIME})，跳过后续阶段，程序退出。")
        db.close()
        return

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

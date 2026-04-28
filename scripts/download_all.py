import sys
import argparse
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.config_loader import (
    load_config,
    get_financial_start_year,
    get_kline_start_date,
    get_index_kline_start_date,
    get_reports_start_date,
    get_minute_frequencies,
    is_download_enabled,
)
from src.db_manager import DBManager
from src.utils.helpers import setup_logging
from src.utils.validator import DataValidator
from src.downloaders.meta_downloader import MetaDownloader
from src.downloaders.macro_downloader import MacroDownloader
from src.downloaders.component_downloader import ComponentDownloader
from src.downloaders.index_downloader import IndexDownloader
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.report_downloader import ReportDownloader
from src.downloaders.dividend_downloader import DividendDownloader


def _get_stock_codes(db_path: Path, codes_file: str | None = None, logger=None):
    if codes_file:
        path = Path(codes_file)
        if path.suffix == ".csv":
            df = pd.read_csv(path, dtype=str)
            col = "code" if "code" in df.columns else df.columns[0]
            codes = df[col].dropna().tolist()
        else:
            codes = [
                line.strip() for line in path.read_text().splitlines() if line.strip()
            ]
        logger.info(f"Loaded {len(codes)} codes from {codes_file}")
        return codes

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT code FROM stock_basic WHERE type = 1")
    codes = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"Loaded {len(codes)} stock codes from database")
    return codes


def main():
    parser = argparse.ArgumentParser(description="BaoStock full data download")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--financial-start-year", type=int, default=None)
    parser.add_argument("--codes-file", default=None)
    parser.add_argument("--skip-kline", action="store_true")
    parser.add_argument("--skip-financial", action="store_true")
    parser.add_argument("--skip-minute", action="store_true")
    parser.add_argument("--skip-macro", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--skip-dividend", action="store_true")
    parser.add_argument(
        "--validate", action="store_true", help="Run data validation after download"
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--log-file", default=None, help="Path to log file")
    args = parser.parse_args()

    logger = setup_logging("baostock", args.log_file)
    cfg = load_config()

    logger.info("=== BaoStock Full Data Download ===")

    from datetime import datetime, timedelta

    with DBManager(str(DB_PATH)) as db:
        db.init_all_tables()
        db.migrate_schema()

        # 程序在凌晨运行，目标是拉取截止到前一天的完整数据
        # 例如：26日凌晨0:05运行 → 拉取截止到25日(含)的数据
        # 若25日非交易日，则追溯到最近的交易日（如周五）
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        kline_end_date = db.get_latest_trading_day_on_or_before(target_date)
    logger.info("Database initialized.")

    if kline_end_date:
        logger.info(f"Latest trading day on or before {target_date}: {kline_end_date}. Proceeding with K-line download.")
    else:
        logger.info(f"No trading day found on or before {target_date}. Skipping K-line download.")

    logger.info("Phase 2: Downloading metadata...")
    with MetaDownloader(str(DB_PATH), logger) as dl:
        meta_results = dl.download_all_metadata()
    logger.info(f"Metadata: {meta_results}")

    codes = _get_stock_codes(DB_PATH, args.codes_file, logger)

    if not args.skip_macro and is_download_enabled("macro"):
        logger.info("Phase 4: Downloading macroeconomic data...")
        with MacroDownloader(str(DB_PATH), logger) as dl:
            macro_results = dl.download_all_macro()
        logger.info(f"Macro: {macro_results}")

    logger.info("Phase 5: Downloading index constituents...")
    with ComponentDownloader(str(DB_PATH), logger) as dl:
        comp_results = dl.download_all_components()
    logger.info(f"Components: {comp_results}")

    if kline_end_date:
        if is_download_enabled("index_kline"):
            logger.info("Phase 6: Downloading index K-line...")
            with IndexDownloader(str(DB_PATH), logger) as dl:
                idx_results = dl.download_all_index(
                    start_date=args.start_date or get_index_kline_start_date(),
                    end_date=args.end_date or kline_end_date,
                )
            logger.info(f"Index K-line: {idx_results}")

        if not args.skip_kline and is_download_enabled("kline", "daily"):
            logger.info("Phase 7: Downloading stock K-line (daily/weekly/monthly)...")
            with KlineDownloader(str(DB_PATH), logger) as dl:
                ckpt_path = DB_PATH.parent / ".download_checkpoint.json"
                dl.setup_signal_handler(ckpt_path)
                dl._checkpoint_data = dl._load_checkpoint(ckpt_path)
                kline_results = {}
                kline_results["daily"] = dl.download_daily_kline(
                    codes,
                    start_date=args.start_date or get_kline_start_date("daily"),
                    end_date=args.end_date or kline_end_date,
                )
                if not dl._interrupted:
                    kline_results["weekly"] = dl.download_weekly_kline(
                        codes, start_date=args.start_date or get_kline_start_date("weekly"),
                        end_date=args.end_date or kline_end_date,
                    )
                if not dl._interrupted:
                    kline_results["monthly"] = dl.download_monthly_kline(
                        codes, start_date=args.start_date or get_kline_start_date("monthly"),
                        end_date=args.end_date or kline_end_date,
                    )
                if not dl._interrupted:
                    dl.clear_checkpoint(ckpt_path)
            logger.info(f"Stock K-line: {kline_results}")

            if not args.skip_minute and is_download_enabled("kline", "minute"):
                logger.info("Phase 8: Downloading minute K-line...")
                with KlineDownloader(str(DB_PATH), logger) as dl:
                    for freq in get_minute_frequencies():
                        count = dl.download_minute_kline(
                            codes,
                            frequency=freq,
                            start_date=args.start_date or get_kline_start_date("minute"),
                            end_date=args.end_date or kline_end_date,
                        )
                        logger.info(f"  {freq}min: {count} rows")
    else:
        logger.info("Skipping Phase 6-8 (K-line) due to no trading day found.")

    if not args.skip_financial and is_download_enabled("financial"):
        logger.info("Phase 9: Downloading financial data...")
        fin_year = args.financial_start_year or get_financial_start_year()
        with FinancialDownloader(str(DB_PATH), logger) as dl:
            fin_results = dl.download_all_financial(codes, start_year=fin_year)
        logger.info(f"Financial: {fin_results}")

    if not args.skip_reports and is_download_enabled("reports"):
        logger.info("Phase 10: Downloading company reports...")
        with ReportDownloader(str(DB_PATH), logger) as dl:
            report_results = dl.download_all_reports(
                codes,
                start_date=args.start_date or get_reports_start_date(),
                end_date=args.end_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            )
        logger.info(f"Reports: {report_results}")

    if not args.skip_dividend and is_download_enabled("dividend"):
        logger.info("Phase 11: Downloading dividend and adjust factor...")
        with DividendDownloader(str(DB_PATH), logger) as dl:
            div_results = dl.download_all_dividend(codes)
        logger.info(f"Dividend: {div_results}")

    if args.validate:
        logger.info("=== Running data validation ===")
        with DataValidator(DB_PATH) as v:
            issues = v.check_all()
            if issues:
                for issue in issues:
                    logger.warning(f"  ISSUE: {issue}")
            else:
                logger.info("  All checks passed!")
            summary = v.summary()
            logger.info("=== Database Summary ===")
            for table, count in summary.items():
                logger.info(f"  {table}: {count} rows")

    logger.info("=== Download Complete ===")


if __name__ == "__main__":
    main()

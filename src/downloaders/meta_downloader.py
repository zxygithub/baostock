"""Metadata downloader for BaoStock trade dates, stock basic info, and industry classification."""

import baostock as bs
import pandas as pd
import logging
import time

from src.downloaders.base import BaseDownloader
from src.config_loader import get_batch_size, get_batch_sleep
from src.utils.helpers import fetch_all_rows, setup_logging


class MetaDownloader(BaseDownloader):
    """Downloads metadata: trade dates, stock basic info, industry classification."""

    def download_trade_dates(
        self, start_date: str = "1990-01-01", end_date: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_trade_dates, start_date, end_date)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(rows, columns=["calendar_date", "is_trading_day"])
        self.save_df(df, "trade_dates", if_exists="replace")
        self.logger.info(f"Trade dates: {len(df)} rows")
        return len(df)

    def download_stock_basic(self) -> int:
        rs = self._api_call(bs.query_stock_basic)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(
            rows, columns=["code", "code_name", "ipoDate", "outDate", "type", "status"]
        )
        df = df.rename(columns={"ipoDate": "ipo_date", "outDate": "out_date"})
        self.save_df(df, "stock_basic", if_exists="replace")
        self.logger.info(f"Stock basic: {len(df)} rows")
        return len(df)

    def download_stock_industry(self) -> int:
        rs = self._api_call(bs.query_stock_industry)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(rows, columns=rs.fields)
        df.rename(
            columns={
                "updateDate": "update_date",
                "industryClassification": "industry_classification",
            },
            inplace=True,
        )
        self.save_df(df, "stock_industry", if_exists="replace")
        self.logger.info(f"Stock industry: {len(df)} rows")
        return len(df)

    def download_all_metadata(self) -> dict[str, int]:
        results: dict[str, int] = {}

        self.logger.info("=== Starting metadata download ===")

        batch_sleep = get_batch_sleep()
        count = self.download_trade_dates()
        results["trade_dates"] = count

        time.sleep(batch_sleep)

        count = self.download_stock_basic()
        results["stock_basic"] = count

        time.sleep(batch_sleep)

        count = self.download_stock_industry()
        results["stock_industry"] = count

        self.logger.info(f"=== Metadata download complete: {results} ===")
        return results

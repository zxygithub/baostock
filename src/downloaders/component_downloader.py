"""Index constituent stock downloader for SZ50, HS300, and ZZ500."""

import baostock as bs
import pandas as pd
import logging
from datetime import datetime

from src.downloaders.base import BaseDownloader
from src.utils.helpers import fetch_all_rows


class ComponentDownloader(BaseDownloader):
    """Downloads index constituent stocks: SZ50, HS300, ZZ500."""

    def download_sz50_stocks(self) -> int:
        self.logger.info("Downloading SZ50 constituent stocks...")
        rs = self._api_call(bs.query_sz50_stocks)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={"updateDate": "update_date"})
        self.save_df(df, "sz50_stocks", if_exists="replace")
        self.logger.info(f"SZ50 constituent stocks download complete: {len(df)} rows")
        return len(df)

    def download_hs300_stocks(self) -> int:
        self.logger.info("Downloading HS300 constituent stocks...")
        rs = self._api_call(bs.query_hs300_stocks)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={"updateDate": "update_date"})
        self.save_df(df, "hs300_stocks", if_exists="replace")
        self.logger.info(f"HS300 constituent stocks download complete: {len(df)} rows")
        return len(df)

    def download_zz500_stocks(self) -> int:
        self.logger.info("Downloading ZZ500 constituent stocks...")
        rs = self._api_call(bs.query_zz500_stocks)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={"updateDate": "update_date"})
        self.save_df(df, "zz500_stocks", if_exists="replace")
        self.logger.info(f"ZZ500 constituent stocks download complete: {len(df)} rows")
        return len(df)

    def download_all_components(self) -> dict[str, int]:
        """Download all index constituents in sequence.

        Returns:
            Dict mapping table names to row counts.
        """
        results: dict[str, int] = {}

        self.logger.info("=== Starting index constituent download ===")

        count = self.download_sz50_stocks()
        results["sz50_stocks"] = count

        count = self.download_hs300_stocks()
        results["hs300_stocks"] = count

        count = self.download_zz500_stocks()
        results["zz500_stocks"] = count

        self.logger.info(f"=== Index constituent download complete: {results} ===")
        return results

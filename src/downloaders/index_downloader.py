import baostock as bs
import pandas as pd
import logging
import time
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import (
    INDEX_CODES,
    INDEX_DAILY_FIELDS,
    INDEX_WEEKLY_MONTHLY_FIELDS,
)
from src.config_loader import get_index_kline_start_date, get_batch_sleep
from src.utils.helpers import fetch_all_rows


class IndexDownloader(BaseDownloader):
    def download_index_daily(
        self,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if codes is None:
            codes = INDEX_CODES
        if start_date is None:
            start_date = get_index_kline_start_date()

        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(codes, desc="Index daily"):
            rs = self.query_with_retry(
                bs.query_history_k_data_plus,
                code=code,
                fields=INDEX_DAILY_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
            )
            rows = fetch_all_rows(rs)
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=INDEX_DAILY_FIELDS.split(","))
            df = df.rename(columns={"pctChg": "pct_chg"})
            self.save_df(df, "index_daily", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_index_weekly(
        self,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if codes is None:
            codes = INDEX_CODES
        if start_date is None:
            start_date = get_index_kline_start_date()

        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(codes, desc="Index weekly"):
            rs = self.query_with_retry(
                bs.query_history_k_data_plus,
                code=code,
                fields=INDEX_WEEKLY_MONTHLY_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="w",
            )
            rows = fetch_all_rows(rs)
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=INDEX_WEEKLY_MONTHLY_FIELDS.split(","))
            df = df.rename(columns={"pctChg": "pct_chg"})
            self.save_df(df, "index_weekly", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_index_monthly(
        self,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if codes is None:
            codes = INDEX_CODES
        if start_date is None:
            start_date = get_index_kline_start_date()

        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(codes, desc="Index monthly"):
            rs = self.query_with_retry(
                bs.query_history_k_data_plus,
                code=code,
                fields=INDEX_WEEKLY_MONTHLY_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="m",
            )
            rows = fetch_all_rows(rs)
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=INDEX_WEEKLY_MONTHLY_FIELDS.split(","))
            df = df.rename(columns={"pctChg": "pct_chg"})
            self.save_df(df, "index_monthly", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_all_index(
        self,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        return {
            "index_daily": self.download_index_daily(codes, start_date, end_date),
            "index_weekly": self.download_index_weekly(codes, start_date, end_date),
            "index_monthly": self.download_index_monthly(codes, start_date, end_date),
        }

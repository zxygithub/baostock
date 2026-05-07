import baostock as bs
import pandas as pd
import logging
import time
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import (
    DAILY_KLINE_FIELDS,
    WEEKLY_MONTHLY_KLINE_FIELDS,
    MINUTE_KLINE_FIELDS,
    RENAME_KLINE,
)
from src.config_loader import (
    get_batch_size,
    get_batch_sleep,
    get_kline_start_date,
    get_nested_value,
    get_download_config,
)
from src.utils.helpers import fetch_all_rows, batch_iterable, convert_turn_field


class KlineDownloader(BaseDownloader):
    def _download_kline_batch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str | None,
        frequency: str,
        fields: str,
        table: str,
        adjustflag: int = 3,
        resume_from: str | None = None,
    ) -> int:
        total_rows = 0
        desc = f"{table} (adj={adjustflag})"
        skipping = bool(resume_from)
        batch_size = get_batch_size()
        batch_sleep = get_batch_sleep()

        for batch in batch_iterable(codes, batch_size):
            all_rows = []
            for code in tqdm(batch, desc=desc, leave=False):
                if self._interrupted:
                    return total_rows

                if skipping:
                    if code == resume_from:
                        skipping = False
                    continue

                last = self.get_last_downloaded(table, code, adjustflag=adjustflag)
                actual_start = max(start_date, last) if last else start_date
                if last and last >= (end_date or "9999-99-99"):
                    self._checkpoint_data = {
                        "table": table,
                        "adjustflag": adjustflag,
                        "last_code": code,
                    }
                    continue

                rs = self.query_with_retry(
                    bs.query_history_k_data_plus,
                    code=code,
                    fields=fields,
                    start_date=actual_start,
                    end_date=end_date,
                    frequency=frequency,
                    adjustflag=str(adjustflag),
                )
                rows = fetch_all_rows(rs)
                all_rows.extend(rows)

                self._checkpoint_data = {
                    "table": table,
                    "adjustflag": adjustflag,
                    "last_code": code,
                }

            if not all_rows:
                continue

            df = pd.DataFrame(all_rows, columns=fields.split(","))
            df = df.rename(
                columns={k: v for k, v in RENAME_KLINE.items() if k in df.columns}
            )

            for col in ["open", "high", "low", "close", "volume", "amount", "preclose"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "turn" in df.columns:
                df["turn"] = df["turn"].apply(convert_turn_field)
            for col in ["tradestatus", "is_st"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

            self.save_df(df, table, if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)

        return total_rows

    def download_daily_kline(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_kline_start_date("daily")
        total_rows = 0
        for adjustflag in [1, 2, 3]:
            self.logger.info(f"Downloading daily K-line (adjustflag={adjustflag})...")
            resume = self._get_resume_code("all_stock_daily", adjustflag, codes)
            count = self._download_kline_batch(
                codes,
                start_date,
                end_date,
                "d",
                DAILY_KLINE_FIELDS,
                "all_stock_daily",
                adjustflag,
                resume,
            )
            if self._interrupted:
                break
            self.logger.info(f"Daily K-line (adj={adjustflag}): {count} rows")
            total_rows += count
        return total_rows

    def download_weekly_kline(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_kline_start_date("weekly")
        total_rows = 0
        for adjustflag in [1, 2, 3]:
            self.logger.info(f"Downloading weekly K-line (adjustflag={adjustflag})...")
            resume = self._get_resume_code("all_stock_weekly", adjustflag, codes)
            count = self._download_kline_batch(
                codes,
                start_date,
                end_date,
                "w",
                WEEKLY_MONTHLY_KLINE_FIELDS,
                "all_stock_weekly",
                adjustflag,
                resume,
            )
            if self._interrupted:
                break
            self.logger.info(f"Weekly K-line (adj={adjustflag}): {count} rows")
            total_rows += count
        return total_rows

    def download_monthly_kline(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_kline_start_date("monthly")
        total_rows = 0
        for adjustflag in [1, 2, 3]:
            self.logger.info(f"Downloading monthly K-line (adjustflag={adjustflag})...")
            resume = self._get_resume_code("all_stock_monthly", adjustflag, codes)
            count = self._download_kline_batch(
                codes,
                start_date,
                end_date,
                "m",
                WEEKLY_MONTHLY_KLINE_FIELDS,
                "all_stock_monthly",
                adjustflag,
                resume,
            )
            if self._interrupted:
                break
            self.logger.info(f"Monthly K-line (adj={adjustflag}): {count} rows")
            total_rows += count
        return total_rows

    def download_minute_kline(
        self,
        codes: list[str],
        frequency: str = "5",
        start_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_kline_start_date("minute")
        table_name = f"all_stock_{frequency}min"
        total_rows = 0
        # BaoStock minute data only supports adjustflag=3 (no adjustment)
        adjustflags = get_nested_value(
            get_download_config(), ["kline", "minute", "adjustflags"], [3]
        )
        for adjustflag in adjustflags:
            self.logger.info(
                f"Downloading {frequency}min K-line (adjustflag={adjustflag})..."
            )
            count = self._download_kline_batch(
                codes,
                start_date,
                None,
                frequency,
                MINUTE_KLINE_FIELDS,
                table_name,
                adjustflag,
            )
            self.logger.info(f"{frequency}min K-line (adj={adjustflag}): {count} rows")
            total_rows += count
        return total_rows

    def download_all_kline(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        results: dict[str, int] = {}
        self.logger.info("=== Starting all K-line data download ===")

        results["all_stock_daily"] = self.download_daily_kline(
            codes, start_date, end_date
        )
        results["all_stock_weekly"] = self.download_weekly_kline(codes, start_date, end_date)
        results["all_stock_monthly"] = self.download_monthly_kline(codes, start_date, end_date)

        for freq in ["5", "15", "30", "60"]:
            results[f"all_stock_{freq}min"] = self.download_minute_kline(
                codes, frequency=freq, start_date=start_date
            )

        self.logger.info(f"=== All K-line data download complete: {results} ===")
        return results

    def _get_resume_code(
        self, table: str, adjustflag: int, codes: list[str]
    ) -> str | None:
        cp = getattr(self, "_checkpoint_data", {})
        if cp.get("table") == table and cp.get("adjustflag") == adjustflag:
            last = cp.get("last_code")
            if last and last in codes:
                idx = codes.index(last)
                if idx + 1 < len(codes):
                    self.logger.info(
                        f"Resuming from {codes[idx + 1]} (after checkpoint {last})"
                    )
                    return last
        return None

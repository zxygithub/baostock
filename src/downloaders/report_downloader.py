import baostock as bs
import pandas as pd
import logging
import time
from datetime import datetime
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import RENAME_PERFORMANCE_EXPRESS, RENAME_FORECAST_REPORT
from src.config_loader import get_reports_start_date, get_batch_sleep
from src.utils.helpers import fetch_all_rows


class ReportDownloader(BaseDownloader):
    def _get_recently_queried_codes(self, table: str, days: int = 7) -> set[str]:
        try:
            rows = self.conn.execute(
                f"SELECT code FROM {table} WHERE update_time > datetime('now', '-{days} days')"
            ).fetchall()
            return {row[0] for row in rows}
        except Exception:
            return set()

    def download_performance_express(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_reports_start_date()

        total_rows = 0
        batch_sleep = get_batch_sleep()
        
        recently_queried = self._get_recently_queried_codes("performance_express", days=7)
        if recently_queried:
            self.logger.info(
                f"performance_express: skipping {len(recently_queried)} codes queried in last 7 days"
            )

        for code in tqdm(codes, desc="Performance express"):
            if self._interrupted:
                break
            if code in recently_queried:
                continue
            rs = self.query_with_retry(
                bs.query_performance_express_report,
                code=code,
                start_date=start_date,
                end_date=end_date,
            )
            rows = fetch_all_rows(rs)
            if not rows:
                df = pd.DataFrame(
                    [[code, '9999-01-01']],
                    columns=['code', 'performance_exp_pub_date']
                )
                df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_df(df, "performance_express", if_exists="upsert")
                time.sleep(batch_sleep)
                continue
            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(columns=RENAME_PERFORMANCE_EXPRESS, inplace=True)
            self.save_df(df, "performance_express", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_forecast_report(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = get_reports_start_date()

        total_rows = 0
        batch_sleep = get_batch_sleep()

        recently_queried = self._get_recently_queried_codes("forecast_report", days=7)
        if recently_queried:
            self.logger.info(
                f"forecast_report: skipping {len(recently_queried)} codes queried in last 7 days"
            )

        for code in tqdm(codes, desc="Forecast report"):
            if self._interrupted:
                break
            if code in recently_queried:
                continue
            rs = self.query_with_retry(
                bs.query_forecast_report,
                code=code,
                start_date=start_date,
                end_date=end_date,
            )
            rows = fetch_all_rows(rs)
            if not rows:
                df = pd.DataFrame(
                    [[code, '9999-01-01']],
                    columns=['code', 'profit_forecast_exp_pub_date']
                )
                df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_df(df, "forecast_report", if_exists="upsert")
                time.sleep(batch_sleep)
                continue
            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(columns=RENAME_FORECAST_REPORT, inplace=True)
            self.save_df(df, "forecast_report", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_all_reports(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        return {
            "performance_express": self.download_performance_express(codes, start_date, end_date),
            "forecast_report": self.download_forecast_report(codes, start_date, end_date),
        }

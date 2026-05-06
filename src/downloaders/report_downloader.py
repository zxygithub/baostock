import baostock as bs
import pandas as pd
import logging
import time
from datetime import datetime
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config_loader import get_reports_start_date, get_batch_sleep
from src.utils.helpers import fetch_all_rows


class ReportDownloader(BaseDownloader):
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
        existing = self._get_existing_report_codes("performance_express")

        for code in tqdm(codes, desc="Performance express"):
            if code in existing:
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
            df.rename(
                columns={
                    "performanceExpPubDate": "performance_exp_pub_date",
                    "performanceExpStatDate": "performance_exp_stat_date",
                    "performanceExpUpdateDate": "performance_exp_update_date",
                    "performanceExpressTotalAsset": "total_asset",
                    "performanceExpressNetAsset": "net_asset",
                    "performanceExpressEPSChgPct": "eps_chg_pct",
                    "performanceExpressROEWa": "roe_wa",
                    "performanceExpressEPSDiluted": "eps_diluted",
                    "performanceExpressGRYOY": "gr_yoy",
                    "performanceExpressOPYOY": "op_yoy",
                },
                inplace=True,
            )
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
        existing = self._get_existing_report_codes("forecast_report")

        for code in tqdm(codes, desc="Forecast report"):
            if code in existing:
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
            df.rename(
                columns={
                    "profitForcastExpPubDate": "profit_forecast_exp_pub_date",
                    "profitForcastExpStatDate": "profit_forecast_exp_stat_date",
                    "profitForcastType": "profit_forecast_type",
                    "profitForcastAbstract": "profit_forecast_abstract",
                    "profitForcastChgPctUp": "profit_forecast_chg_pct_up",
                    "profitForcastChgPctDwn": "profit_forecast_chg_pct_down",
                },
                inplace=True,
            )
            self.save_df(df, "forecast_report", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def _get_existing_report_codes(self, table_name: str) -> set[str]:
        try:
            rows = self.conn.execute(
                f"SELECT code FROM {table_name}"
            ).fetchall()
            return {r[0] for r in rows}
        except Exception:
            return set()

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

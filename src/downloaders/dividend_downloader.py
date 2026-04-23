import baostock as bs
import pandas as pd
import logging
import time
from datetime import datetime
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config_loader import get_batch_sleep, get_financial_start_year
from src.utils.helpers import fetch_all_rows


class DividendDownloader(BaseDownloader):
    def download_dividend(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> int:
        if start_year is None:
            start_year = get_financial_start_year()
        if end_year is None:
            end_year = datetime.now().year

        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(codes, desc="Dividend"):
            all_rows = []
            for year in range(start_year, end_year + 1):
                for year_type in ["report", "operate"]:
                    rs = self._api_call(
                        bs.query_dividend_data,
                        code=code, year=str(year), yearType=year_type,
                    )
                    rows = fetch_all_rows(rs)
                    for row in rows:
                        all_rows.append(list(row) + [year, year_type])

            if not all_rows:
                time.sleep(batch_sleep)
                continue

            columns = rs.fields + ["year", "year_type"]
            df = pd.DataFrame(all_rows, columns=columns)
            df.rename(
                columns={
                    "dividPreNoticeDate": "divid_pre_notice_date",
                    "dividAgmPumDate": "divid_agm_pum_date",
                    "dividPlanAnnounceDate": "divid_plan_announce_date",
                    "dividPlanDate": "divid_plan_date",
                    "dividRegistDate": "divid_regist_date",
                    "dividOperateDate": "divid_operate_date",
                    "dividPayDate": "divid_pay_date",
                    "dividStockMarketDate": "divid_stock_market_date",
                    "dividCashPsBeforeTax": "divid_cash_ps_before_tax",
                    "dividCashPsAfterTax": "divid_cash_ps_after_tax",
                    "dividStocksPs": "divid_stocks_ps",
                    "dividCashStock": "divid_cash_stock",
                    "dividReserveToStockPs": "divid_reserve_to_stock_ps",
                },
                inplace=True,
            )
            self.save_df(df, "dividend", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_adjust_factor(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = f"{get_financial_start_year()}-01-01"
        
        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(codes, desc="Adjust factor"):
            rs = self._api_call(
                bs.query_adjust_factor,
                code=code, start_date=start_date, end_date=end_date,
            )
            rows = fetch_all_rows(rs)
            if not rows:
                time.sleep(batch_sleep)
                continue
            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(
                columns={
                    "dividOperateDate": "divid_operate_date",
                    "foreAdjustFactor": "fore_adjust_factor",
                    "backAdjustFactor": "back_adjust_factor",
                    "adjustFactor": "adjust_factor",
                },
                inplace=True,
            )
            self.save_df(df, "adjust_factor", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)
        return total_rows

    def download_all_dividend(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, int]:
        if start_year is None:
            start_year = get_financial_start_year()
        if start_date is None:
            start_date = f"{start_year}-01-01"
        
        return {
            "dividend": self.download_dividend(codes, start_year, end_year),
            "adjust_factor": self.download_adjust_factor(codes, start_date, end_date),
        }

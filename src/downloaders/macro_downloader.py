import baostock as bs
import pandas as pd
import logging
import time

from src.downloaders.base import BaseDownloader
from src.config import (
    RENAME_DEPOSIT_RATE,
    RENAME_LOAN_RATE,
    RENAME_RESERVE_RATIO,
    RENAME_MONEY_SUPPLY_MONTH,
    RENAME_MONEY_SUPPLY_YEAR,
)
from src.config_loader import get_batch_sleep
from src.utils.helpers import fetch_all_rows


class MacroDownloader(BaseDownloader):
    def download_deposit_rate(
        self, start_date: str = "2000-01-01", end_date: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_deposit_rate_data, start_date, end_date)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(
            rows,
            columns=[
                "pubDate",
                "demandDepositRate",
                "fixedDepositRate3Month",
                "fixedDepositRate6Month",
                "fixedDepositRate1Year",
                "fixedDepositRate2Year",
                "fixedDepositRate3Year",
                "fixedDepositRate5Year",
                "installmentFixedDepositRate1Year",
                "installmentFixedDepositRate3Year",
                "installmentFixedDepositRate5Year",
            ],
        )
        df.rename(columns=RENAME_DEPOSIT_RATE, inplace=True)
        self.save_df(df, "deposit_rate", if_exists="upsert")
        return len(df)

    def download_loan_rate(
        self, start_date: str = "2000-01-01", end_date: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_loan_rate_data, start_date, end_date)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(
            rows,
            columns=[
                "pubDate",
                "loanRate6Month",
                "loanRate6MonthTo1Year",
                "loanRate1YearTo3Year",
                "loanRate3YearTo5Year",
                "loanRateAbove5Year",
                "mortgateRateBelow5Year",
                "mortgateRateAbove5Year",
            ],
        )
        df.rename(columns=RENAME_LOAN_RATE, inplace=True)
        self.save_df(df, "loan_rate", if_exists="upsert")
        return len(df)

    def download_reserve_ratio(
        self, start_date: str = "2000-01-01", end_date: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_required_reserve_ratio_data, start_date, end_date)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(
            rows,
            columns=[
                "pubDate",
                "effectiveDate",
                "bigInstitutionsRatioPre",
                "bigInstitutionsRatioAfter",
                "mediumInstitutionsRatioPre",
                "mediumInstitutionsRatioAfter",
            ],
        )
        df.rename(columns=RENAME_RESERVE_RATIO, inplace=True)
        self.save_df(df, "reserve_ratio", if_exists="upsert")
        return len(df)

    def download_money_supply_month(
        self, start_date: str = "2000-01", end_date: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_money_supply_data_month, start_date, end_date)
        rows = fetch_all_rows(rs)
        df = pd.DataFrame(
            rows,
            columns=[
                "statYear",
                "statMonth",
                "m0Month",
                "m0YOY",
                "m0ChainRelative",
                "m1Month",
                "m1YOY",
                "m1ChainRelative",
                "m2Month",
                "m2YOY",
                "m2ChainRelative",
            ],
        )
        df.rename(columns=RENAME_MONEY_SUPPLY_MONTH, inplace=True)
        self.save_df(df, "money_supply_month", if_exists="upsert")
        return len(df)

    def download_money_supply_year(
        self, start_year: str = "2000", end_year: str | None = None
    ) -> int:
        rs = self._api_call(bs.query_money_supply_data_year, start_year, end_year)
        rows = fetch_all_rows(rs)
        if not rows:
            return 0
        df = pd.DataFrame(rows, columns=rs.fields)
        df.rename(columns=RENAME_MONEY_SUPPLY_YEAR, inplace=True)
        self.save_df(df, "money_supply_year", if_exists="upsert")
        return len(df)

    def download_all_macro(self) -> dict[str, int]:
        results = {}
        self.logger.info("=== Starting macroeconomic data download ===")

        batch_sleep = get_batch_sleep()
        results["deposit_rate"] = self.download_deposit_rate()
        time.sleep(batch_sleep)
        results["loan_rate"] = self.download_loan_rate()
        time.sleep(batch_sleep)
        results["reserve_ratio"] = self.download_reserve_ratio()
        time.sleep(batch_sleep)
        results["money_supply_month"] = self.download_money_supply_month()
        time.sleep(batch_sleep)
        results["money_supply_year"] = self.download_money_supply_year()

        self.logger.info(f"=== Macroeconomic data download complete: {results} ===")
        return results

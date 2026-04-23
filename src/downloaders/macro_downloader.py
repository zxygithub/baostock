import baostock as bs
import pandas as pd
import logging
import time

from src.downloaders.base import BaseDownloader
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
        df.rename(
            columns={
                "pubDate": "pub_date",
                "demandDepositRate": "demand_deposit_rate",
                "fixedDepositRate3Month": "fixed_deposit_rate_3_month",
                "fixedDepositRate6Month": "fixed_deposit_rate_6_month",
                "fixedDepositRate1Year": "fixed_deposit_rate_1_year",
                "fixedDepositRate2Year": "fixed_deposit_rate_2_year",
                "fixedDepositRate3Year": "fixed_deposit_rate_3_year",
                "fixedDepositRate5Year": "fixed_deposit_rate_5_year",
                "installmentFixedDepositRate1Year": "installment_fixed_rate_1_year",
                "installmentFixedDepositRate3Year": "installment_fixed_rate_3_year",
                "installmentFixedDepositRate5Year": "installment_fixed_rate_5_year",
            },
            inplace=True,
        )
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
        df.rename(
            columns={
                "pubDate": "pub_date",
                "loanRate6Month": "loan_rate_6_month",
                "loanRate6MonthTo1Year": "loan_rate_6m_to_1y",
                "loanRate1YearTo3Year": "loan_rate_1y_to_3y",
                "loanRate3YearTo5Year": "loan_rate_3y_to_5y",
                "loanRateAbove5Year": "loan_rate_above_5y",
                "mortgateRateBelow5Year": "mortgage_rate_below_5y",
                "mortgateRateAbove5Year": "mortgage_rate_above_5y",
            },
            inplace=True,
        )
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
        df.rename(
            columns={
                "pubDate": "pub_date",
                "effectiveDate": "effective_date",
                "bigInstitutionsRatioPre": "big_institutions_ratio_pre",
                "bigInstitutionsRatioAfter": "big_institutions_ratio_after",
                "mediumInstitutionsRatioPre": "medium_institutions_ratio_pre",
                "mediumInstitutionsRatioAfter": "medium_institutions_ratio_after",
            },
            inplace=True,
        )
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
        df.rename(
            columns={
                "statYear": "stat_year",
                "statMonth": "stat_month",
                "m0Month": "m0_month",
                "m0YOY": "m0_yoy",
                "m0ChainRelative": "m0_chain",
                "m1Month": "m1_month",
                "m1YOY": "m1_yoy",
                "m1ChainRelative": "m1_chain",
                "m2Month": "m2_month",
                "m2YOY": "m2_yoy",
                "m2ChainRelative": "m2_chain",
            },
            inplace=True,
        )
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
        df.rename(
            columns={
                "statYear": "stat_year",
                "m0Year": "m0_year",
                "m0YearYOY": "m0_year_yoy",
                "m1Year": "m1_year",
                "m1YearYOY": "m1_year_yoy",
                "m2Year": "m2_year",
                "m2YearYOY": "m2_year_yoy",
            },
            inplace=True,
        )
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

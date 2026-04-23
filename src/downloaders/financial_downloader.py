import baostock as bs
import pandas as pd
import logging
import time
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import FINANCIAL_SLEEP
from src.config_loader import get_financial_start_year
from src.utils.helpers import fetch_all_rows, get_current_quarter


class FinancialDownloader(BaseDownloader):
    def _download_quarterly_data(
        self,
        codes: list[str],
        query_func,
        column_renames: dict[str, str],
        table_name: str,
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        if start_year is None:
            start_year = get_financial_start_year()
        if end_year is None:
            end_year = get_current_quarter()[0]

        existing = self._get_existing_quarters(table_name)
        total_rows = 0
        all_dfs: list[pd.DataFrame] = []
        current_year, current_quarter = get_current_quarter()

        tasks = []
        for code in codes:
            for year in range(start_year, end_year + 1):
                # 如果指定了季度范围，且是单年份查询，使用指定范围
                if start_quarter is not None and end_quarter is not None and start_year == end_year:
                    quarters = list(range(start_quarter, end_quarter + 1))
                else:
                    quarters = (
                        [1, 2, 3, 4]
                        if year < current_year
                        else list(range(1, current_quarter + 1))
                    )
                for quarter in quarters:
                    if (code, year, quarter) not in existing:
                        tasks.append((code, year, quarter))

        if not tasks:
            self.logger.info(f"{table_name}: all up to date, skipping")
            return 0

        self.logger.info(
            f"{table_name}: {len(tasks)} new quarters to download "
            f"({len(existing)} already exist)"
        )

        batch_dfs: list[pd.DataFrame] = []
        BATCH_FLUSH = 500

        for code, year, quarter in tqdm(tasks, desc=table_name):
            try:
                rs = self.query_with_retry(
                    query_func, code=code, year=year, quarter=quarter
                )
            except RuntimeError:
                continue
            rows = fetch_all_rows(rs)
            if not rows:
                continue

            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(columns=column_renames, inplace=True)
            df["year"] = year
            df["quarter"] = quarter
            all_dfs.append(df)
            batch_dfs.append(df)
            total_rows += len(df)
            time.sleep(FINANCIAL_SLEEP)

            if len(batch_dfs) >= BATCH_FLUSH:
                combined = pd.concat(batch_dfs, ignore_index=True)
                self._batch_upsert(combined, table_name)
                batch_dfs.clear()

        if batch_dfs:
            combined = pd.concat(batch_dfs, ignore_index=True)
            self._batch_upsert(combined, table_name)

        return total_rows

    def _get_existing_quarters(self, table_name: str) -> set[tuple[str, int, int]]:
        try:
            rows = self.conn.execute(
                f"SELECT code, year, quarter FROM {table_name}"
            ).fetchall()
            return {(r[0], r[1], r[2]) for r in rows}
        except Exception:
            return set()

    def _batch_upsert(self, df: pd.DataFrame, table_name: str) -> None:
        tmp = f"{table_name}_batch_tmp"
        df.to_sql(tmp, self.conn, if_exists="replace", index=False)
        cols = ", ".join(f'"{c}"' for c in df.columns)
        self.conn.execute(f"""
            INSERT OR REPLACE INTO {table_name} ({cols})
            SELECT {cols} FROM {tmp}
        """)
        self.conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        self.conn.commit()

    def download_profit_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_profit_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "roeAvg": "roe_avg",
                "npMargin": "np_margin",
                "gpMargin": "gp_margin",
                "netProfit": "net_profit",
                "epsTTM": "eps_ttm",
                "MBRevenue": "mb_revenue",
                "totalShare": "total_share",
                "liqaShare": "liqa_share",
            },
            table_name="profit_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_operation_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_operation_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "NRTurnRatio": "nr_turn_ratio",
                "NRTurnDays": "nr_turn_days",
                "INVTurnRatio": "inv_turn_ratio",
                "INVTurnDays": "inv_turn_days",
                "CATurnRatio": "ca_turn_ratio",
                "AssetTurnRatio": "asset_turn_ratio",
            },
            table_name="operation_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_growth_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_growth_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "YOYEquity": "yoy_equity",
                "YOYAsset": "yoy_asset",
                "YOYNI": "yoy_ni",
                "YOYEPSBasic": "yoy_eps_basic",
                "YOYPNI": "yoy_pni",
            },
            table_name="growth_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_balance_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_balance_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "currentRatio": "current_ratio",
                "quickRatio": "quick_ratio",
                "cashRatio": "cash_ratio",
                "YOYLiability": "yoy_liability",
                "liabilityToAsset": "liability_to_asset",
                "assetToEquity": "asset_to_equity",
            },
            table_name="balance_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_cash_flow_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_cash_flow_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "CAToAsset": "ca_to_asset",
                "NCAToAsset": "nca_to_asset",
                "tangibleAssetToAsset": "tangible_asset_to_asset",
                "ebitToInterest": "ebit_to_interest",
                "CFOToOR": "cfo_to_or",
                "CFOToNP": "cfo_to_np",
                "CFOToGr": "cfo_to_gr",
            },
            table_name="cash_flow_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_dupont_data(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> int:
        return self._download_quarterly_data(
            codes=codes,
            query_func=bs.query_dupont_data,
            column_renames={
                "pubDate": "pub_date",
                "statDate": "stat_date",
                "dupontROE": "dupont_roe",
                "dupontAssetStoEquity": "dupont_asset_to_equity",
                "dupontAssetTurn": "dupont_asset_turn",
                "dupontPnitoni": "dupont_pni_to_ni",
                "dupontNitogr": "dupont_ni_to_gr",
                "dupontTaxBurden": "dupont_tax_burden",
                "dupontIntburden": "dupont_int_burden",
                "dupontEbittogr": "dupont_ebit_to_gr",
            },
            table_name="dupont_data",
            start_year=start_year,
            end_year=end_year,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )

    def download_all_financial(
        self,
        codes: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        start_quarter: int | None = None,
        end_quarter: int | None = None,
    ) -> dict[str, int]:
        self.logger.info("Starting download of all financial data...")
        results = {}
        results["profit_data"] = self.download_profit_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        results["operation_data"] = self.download_operation_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        results["growth_data"] = self.download_growth_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        results["balance_data"] = self.download_balance_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        results["cash_flow_data"] = self.download_cash_flow_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        results["dupont_data"] = self.download_dupont_data(
            codes, start_year, end_year, start_quarter, end_quarter
        )
        self.logger.info(
            f"All financial data download complete. Total rows: {sum(results.values())}"
        )
        return results

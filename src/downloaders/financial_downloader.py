import baostock as bs
import pandas as pd
import logging
import time
from datetime import datetime
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import (
    FINANCIAL_SLEEP,
    RENAME_PROFIT,
    RENAME_OPERATION,
    RENAME_GROWTH,
    RENAME_BALANCE,
    RENAME_CASH_FLOW,
    RENAME_DUPONT,
)
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

        stock_years = self.get_stock_years(codes, start_year, end_year)
        total_rows = 0
        current_year, current_quarter = get_current_quarter()
        recent_years = {current_year, current_year - 1}

        candidates = []
        for code in codes:
            ipo_y, out_y = stock_years.get(code, (start_year, end_year))
            eff_start = max(start_year, ipo_y)
            eff_end = min(end_year, out_y)
            if eff_start > eff_end:
                continue

            for year in range(eff_start, eff_end + 1):
                if start_quarter is not None and end_quarter is not None and start_year == end_year:
                    quarters = list(range(start_quarter, end_quarter + 1))
                else:
                    quarters = (
                        [1, 2, 3, 4]
                        if year < current_year
                        else list(range(1, current_quarter + 1))
                    )
                for quarter in quarters:
                    candidates.append((code, year, quarter))

        tasks, skipped = self._find_missing_quarters(table_name, candidates)
        total_possible = len(tasks) + skipped

        if not tasks:
            self.logger.info(f"{table_name}: all up to date, skipping")
            return 0

        self.logger.info(
            f"{table_name}: {len(tasks)} tasks to download, "
            f"{skipped} skipped (already exist), "
            f"{total_possible} total checked"
        )

        self._batch_dfs: list[pd.DataFrame] = []
        self._batch_table: str = table_name
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
                if year not in recent_years:
                    df = pd.DataFrame(
                        [[code] + [pd.NA] * len(column_renames)],
                        columns=["code"] + list(column_renames.values()),
                    )
                    df["year"] = year
                    df["quarter"] = quarter
                    self._batch_dfs.append(df)
                time.sleep(FINANCIAL_SLEEP)
                continue

            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(columns=column_renames, inplace=True)
            df["year"] = year
            df["quarter"] = quarter
            self._batch_dfs.append(df)
            total_rows += len(df)
            time.sleep(FINANCIAL_SLEEP)

            if len(self._batch_dfs) >= BATCH_FLUSH:
                combined = pd.concat(self._batch_dfs, ignore_index=True)
                self._batch_upsert(combined, table_name)
                self._batch_dfs.clear()

        if self._batch_dfs:
            combined = pd.concat(self._batch_dfs, ignore_index=True)
            self._batch_upsert(combined, table_name)
            self._batch_dfs.clear()

        return total_rows

    def _find_missing_quarters(
        self,
        table_name: str,
        candidates: list[tuple[str, int, int]],
    ) -> tuple[list[tuple[str, int, int]], int]:
        if not candidates:
            return [], 0

        self.conn.execute("DROP TABLE IF EXISTS _fin_candidates")
        self.conn.execute(
            "CREATE TEMP TABLE _fin_candidates "
            "(code TEXT, year INTEGER, quarter INTEGER)"
        )
        self.conn.executemany(
            "INSERT INTO _fin_candidates VALUES (?,?,?)", candidates
        )

        rows = self.conn.execute(f"""
            SELECT c.code, c.year, c.quarter
            FROM _fin_candidates c
            LEFT JOIN {table_name} t
                ON c.code = t.code AND c.year = t.year AND c.quarter = t.quarter
            WHERE t.code IS NULL
        """).fetchall()
        self.conn.execute("DROP TABLE _fin_candidates")

        return rows, len(candidates) - len(rows)

    def _flush_pending_batches(self):
        batch_dfs = getattr(self, "_batch_dfs", None)
        if batch_dfs:
            combined = pd.concat(batch_dfs, ignore_index=True)
            self._batch_upsert(combined, getattr(self, "_batch_table", "unknown"))
            self._batch_dfs.clear()
            self.logger.info("Flushed pending batch to DB before API limit exit")
        super()._flush_pending_batches()

    def _batch_upsert(self, df: pd.DataFrame, table_name: str) -> None:
        if "update_time" not in df.columns:
            df = df.copy()
            df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            column_renames=RENAME_PROFIT,
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
            column_renames=RENAME_OPERATION,
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
            column_renames=RENAME_GROWTH,
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
            column_renames=RENAME_BALANCE,
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
            column_renames=RENAME_CASH_FLOW,
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
            column_renames=RENAME_DUPONT,
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

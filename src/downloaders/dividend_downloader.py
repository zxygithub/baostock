import baostock as bs
import pandas as pd
import logging
import time
from datetime import datetime
from tqdm import tqdm

from src.downloaders.base import BaseDownloader
from src.config import RENAME_DIVIDEND, RENAME_ADJUST_FACTOR
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
        current_year = datetime.now().year
        recent_years = {current_year, current_year - 1}

        stock_years = self.get_stock_years(codes, start_year, end_year)

        candidates = []
        for code in codes:
            ipo_y, out_y = stock_years.get(code, (start_year, end_year))
            eff_start = max(start_year, ipo_y)
            eff_end = min(end_year, out_y)
            if eff_start > eff_end:
                continue
            for year in range(eff_start, eff_end + 1):
                for year_type in ["report", "operate"]:
                    candidates.append((code, year, year_type))

        missing = self._find_missing_dividend(candidates, recent_years)
        tasks = missing["tasks"]
        skipped = missing["skipped"]

        total_possible = len(tasks) + skipped

        if not tasks:
            self.logger.info("Dividend: all up to date, skipping")
            return 0

        self.logger.info(
            f"Dividend: {len(tasks)} tasks to download, "
            f"{skipped} skipped (already exist), "
            f"{total_possible} total checked"
        )

        # Batch placeholder writes to reduce individual transactions
        placeholder_dfs = []
        BATCH_SIZE = 50

        for code, year, year_type in tqdm(tasks, desc="Dividend"):
            if self._interrupted:
                break
            all_rows = []
            try:
                rs = self.query_with_retry(
                    bs.query_dividend_data,
                    code=code, year=str(year), yearType=year_type,
                )
                rows = fetch_all_rows(rs)
            except RuntimeError as e:
                self.logger.warning(f"dividend: skipping {code} {year} {year_type} after retries: {e}")
                time.sleep(batch_sleep)
                continue
            for row in rows:
                all_rows.append(list(row) + [year, year_type])

            if not all_rows:
                if year not in recent_years:
                    df = pd.DataFrame(
                        [[code, '9999-01-01', year, year_type]],
                        columns=['code', 'divid_operate_date', 'year', 'year_type']
                    )
                    placeholder_dfs.append(df)
                time.sleep(batch_sleep)
                continue

            columns = rs.fields + ["year", "year_type"]
            df = pd.DataFrame(all_rows, columns=columns)
            df.rename(columns=RENAME_DIVIDEND, inplace=True)
            self.save_df(df, "dividend", if_exists="upsert")
            total_rows += len(df)
            time.sleep(batch_sleep)

            # Flush placeholders in batches
            if len(placeholder_dfs) >= BATCH_SIZE:
                combined = pd.concat(placeholder_dfs, ignore_index=True)
                combined["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_df(combined, "dividend", if_exists="upsert")
                placeholder_dfs.clear()

        # Flush remaining placeholders
        if placeholder_dfs:
            combined = pd.concat(placeholder_dfs, ignore_index=True)
            combined["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_df(combined, "dividend", if_exists="upsert")
            placeholder_dfs.clear()

        return total_rows

    def _find_missing_dividend(
        self,
        candidates: list[tuple[str, int, str]],
        recent_years: set[int],
    ) -> dict:
        """Find missing (code, year, year_type) combos using SQL, not full-table scan.

        Creates a temp table with candidates, then LEFT JOINs against dividend
        to find missing entries. Recent years are always included (forced refresh).
        """
        if not candidates:
            return {"tasks": [], "skipped": 0}

        self.conn.execute("DROP TABLE IF EXISTS _div_candidates")
        self.conn.execute(
            "CREATE TEMP TABLE _div_candidates "
            "(code TEXT, year INTEGER, year_type TEXT)"
        )
        self.conn.executemany(
            "INSERT INTO _div_candidates VALUES (?,?,?)", candidates
        )

        rows = self.conn.execute("""
            SELECT c.code, c.year, c.year_type
            FROM _div_candidates c
            LEFT JOIN dividend d
                ON c.code = d.code AND c.year = d.year AND c.year_type = d.year_type
            WHERE d.code IS NULL
        """).fetchall()
        self.conn.execute("DROP TABLE _div_candidates")
        # executemany INSERT 隐式开启了事务；若不关闭，遗留的读快照会让
        # close() 里的 wal_checkpoint(TRUNCATE) 抛 "database table is locked"
        # （当所有分红已存在、后续没有任何 commit 时触发）。
        self.conn.rollback()

        tasks = []
        skipped = 0
        for code, year, year_type in rows:
            if year not in recent_years:
                tasks.append((code, year, year_type))
            else:
                skipped += 1
        # All candidates minus tasks = skipped (existing + recent forced)
        total_existing = len(candidates) - len(tasks) - len([
            c for c in candidates if c[1] in recent_years
        ])
        return {"tasks": tasks, "skipped": total_existing}

    def _find_stale_adjust_factor(self, codes: list[str], today: str) -> tuple[list[str], int]:
        """Find codes needing an adjust-factor re-query (temp table + LEFT JOIN).

        Stale = rows not refreshed today, or known dividend events uncovered
        (the L5 expected-set model). Skipping is safe: rows are append-only
        per (code, divid_operate_date).
        """
        if not codes:
            return [], 0

        self.conn.execute("DROP TABLE IF EXISTS _af_candidates")
        self.conn.execute(
            "CREATE TEMP TABLE _af_candidates (code TEXT PRIMARY KEY)"
        )
        self.conn.executemany(
            "INSERT INTO _af_candidates VALUES (?)", [(c,) for c in codes]
        )

        rows = self.conn.execute("""
            SELECT c.code
            FROM _af_candidates c
            LEFT JOIN (
                SELECT code, MAX(update_time) AS last_check
                FROM adjust_factor GROUP BY code
            ) m ON m.code = c.code
            WHERE m.last_check IS NULL OR m.last_check < ?
            UNION
            SELECT d.code
            FROM dividend d
            JOIN _af_candidates c ON c.code = d.code
            LEFT JOIN adjust_factor af
                ON af.code = d.code AND af.divid_operate_date = d.divid_operate_date
            WHERE d.divid_operate_date != '9999-01-01' AND af.code IS NULL
        """, (today,)).fetchall()
        self.conn.execute("DROP TABLE IF EXISTS _af_candidates")
        # 同 _find_missing_dividend：executemany 隐式事务不回滚会让 close() 的
        # wal_checkpoint(TRUNCATE) 抛 "database table is locked"
        self.conn.rollback()

        stale = sorted(r[0] for r in rows)
        return stale, len(codes) - len(stale)

    def _mark_adjust_checked(self, code: str) -> None:
        """Write a '9999-01-01' placeholder so an empty result is not re-queried the same day."""
        df = pd.DataFrame(
            [[code, '9999-01-01', None, None, None]],
            columns=['code', 'divid_operate_date', 'fore_adjust_factor',
                     'back_adjust_factor', 'adjust_factor'],
        )
        self.save_df(df, "adjust_factor", if_exists="upsert")

    def download_adjust_factor(
        self,
        codes: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        if start_date is None:
            start_date = f"{get_financial_start_year()}-01-01"

        today = datetime.now().strftime("%Y-%m-%d")
        stale_codes, skipped = self._find_stale_adjust_factor(codes, today)
        self.logger.info(
            f"Adjust factor: {len(stale_codes)} to refresh, "
            f"{skipped} skipped (already checked today)"
        )

        total_rows = 0
        batch_sleep = get_batch_sleep()
        for code in tqdm(stale_codes, desc="Adjust factor"):
            if self._interrupted:
                break
            try:
                rs = self.query_with_retry(
                    bs.query_adjust_factor,
                    code=code, start_date=start_date, end_date=end_date,
                )
                rows = fetch_all_rows(rs)
            except RuntimeError as e:
                self.logger.warning(f"adjust_factor: skipping {code} after retries: {e}")
                time.sleep(batch_sleep)
                continue
            if not rows:
                self._mark_adjust_checked(code)
                time.sleep(batch_sleep)
                continue
            df = pd.DataFrame(rows, columns=rs.fields)
            df.rename(columns=RENAME_ADJUST_FACTOR, inplace=True)
            self.save_df(df, "adjust_factor", if_exists="upsert")
            self.conn.execute(
                "DELETE FROM adjust_factor WHERE code = ? AND divid_operate_date = '9999-01-01'",
                (code,),
            )
            self.conn.commit()
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

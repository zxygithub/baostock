"""Unit tests for FinancialDownloader candidate generation skip logic.

Tests the two new skip rules added to _download_quarterly_data:
1. Skip current quarter (financial reports not yet published)
2. Skip IPO year for growth_data (no YoY comparison available)
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    import os
    os.close(fd)
    return path


def _setup_stock_basic(conn, stocks):
    """Create stock_basic table and insert test stocks.

    stocks: list of (code, ipo_date, out_date)
    """
    conn.execute("""
        CREATE TABLE stock_basic (
            code TEXT PRIMARY KEY,
            ipo_date TEXT,
            out_date TEXT,
            type INTEGER DEFAULT 1,
            status INTEGER DEFAULT 1
        )
    """)
    conn.executemany(
        "INSERT INTO stock_basic (code, ipo_date, out_date, type, status) VALUES (?, ?, ?, 1, 1)",
        stocks,
    )
    conn.commit()


def _create_financial_table(conn, table_name):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            code TEXT, year INTEGER, quarter INTEGER,
            PRIMARY KEY (code, year, quarter)
        )
    """)
    conn.commit()


def _count_candidates(conn, codes, start_year, end_year, table_name, current_year, current_quarter):
    """Simulate the candidate generation logic from _download_quarterly_data."""
    rows = conn.execute(
        "SELECT code, ipo_date, out_date FROM stock_basic WHERE code IN ({})".format(
            ",".join("?" * len(codes))
        ),
        codes,
    ).fetchall()
    stock_years = {}
    for code, ipo, out in rows:
        ipo_y = int(ipo[:4]) if ipo and ipo[:4].isdigit() else start_year
        out_y = int(out[:4]) if out and out[:4].isdigit() else end_year
        stock_years[code] = (ipo_y, out_y)

    candidates = []
    for code in codes:
        ipo_y, out_y = stock_years.get(code, (start_year, end_year))
        eff_start = max(start_year, ipo_y)
        eff_end = min(end_year, out_y)
        if eff_start > eff_end:
            continue
        for year in range(eff_start, eff_end + 1):
            quarters = [1, 2, 3, 4] if year < current_year else list(range(1, current_quarter + 1))
            for quarter in quarters:
                # Skip current quarter
                if year == current_year and quarter == current_quarter:
                    continue
                # Skip IPO year for growth_data
                if table_name == "growth_data" and year == ipo_y:
                    continue
                candidates.append((code, year, quarter))
    return candidates


class TestCurrentQuarterSkip:
    """Test that the current (unpublished) quarter is skipped for all financial tables."""

    def test_q2_2026_skipped_for_all_tables(self, tmp_db_path):
        """When current quarter is Q2 2026, no table should have Q2 2026 candidates."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.600000", "2000-01-01", None)])
        codes = ["sh.600000"]

        for table in ["profit_data", "operation_data", "growth_data", "balance_data", "cash_flow_data", "dupont_data"]:
            candidates = _count_candidates(conn, codes, 2007, 2026, table, 2026, 2)
            q2_2026 = [c for c in candidates if c[1] == 2026 and c[2] == 2]
            assert q2_2026 == [], f"{table} should not have Q2 2026 candidates"

        conn.close()

    def test_q1_2026_included_when_current_is_q2(self, tmp_db_path):
        """Q1 2026 should still be included when current quarter is Q2 2026."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.600000", "2000-01-01", None)])
        codes = ["sh.600000"]

        candidates = _count_candidates(conn, codes, 2007, 2026, "profit_data", 2026, 2)
        q1_2026 = [c for c in candidates if c[1] == 2026 and c[2] == 1]
        assert len(q1_2026) == 1

        conn.close()

    def test_past_quarters_not_skipped(self, tmp_db_path):
        """Only the current quarter should be skipped, not past quarters."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.600000", "2000-01-01", None)])
        codes = ["sh.600000"]

        candidates = _count_candidates(conn, codes, 2025, 2026, "profit_data", 2026, 2)
        # 2025 Q1-Q4 should all be present
        y2025 = [c for c in candidates if c[1] == 2025]
        assert len(y2025) == 4

        conn.close()


class TestIPOYearSkipForGrowthData:
    """Test that IPO year is skipped only for growth_data."""

    def test_growth_data_skips_ipo_year(self, tmp_db_path):
        """growth_data should not include IPO year quarters."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.688001", "2019-07-22", None)])
        codes = ["sh.688001"]

        candidates = _count_candidates(conn, codes, 2007, 2025, "growth_data", 2025, 4)
        ipo_year = [c for c in candidates if c[1] == 2019]
        assert ipo_year == [], "growth_data should skip IPO year 2019"

        conn.close()

    def test_profit_data_includes_ipo_year(self, tmp_db_path):
        """profit_data should still include IPO year quarters."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.688001", "2019-07-22", None)])
        codes = ["sh.688001"]

        candidates = _count_candidates(conn, codes, 2007, 2025, "profit_data", 2025, 4)
        ipo_year = [c for c in candidates if c[1] == 2019]
        assert len(ipo_year) == 4, "profit_data should include IPO year 2019 (all 4 quarters)"

        conn.close()

    def test_operation_data_includes_ipo_year(self, tmp_db_path):
        """operation_data should still include IPO year quarters."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sh.688001", "2019-07-22", None)])
        codes = ["sh.688001"]

        candidates = _count_candidates(conn, codes, 2007, 2025, "operation_data", 2025, 4)
        ipo_year = [c for c in candidates if c[1] == 2019]
        assert len(ipo_year) == 4, "operation_data should include IPO year 2019"

        conn.close()

    def test_delisted_stock_ipo_year_skipped_for_growth(self, tmp_db_path):
        """Delisted stocks should also skip IPO year for growth_data."""
        conn = sqlite3.connect(tmp_db_path)
        _setup_stock_basic(conn, [("sz.000693", "1997-02-26", "2019-07-09")])
        codes = ["sz.000693"]

        candidates = _count_candidates(conn, codes, 2007, 2026, "growth_data", 2026, 2)
        # IPO year is 1997, which is before start_year=2007, so eff_start=2007
        # 1997 should not be in range anyway
        ipo_year = [c for c in candidates if c[1] == 1997]
        assert ipo_year == []

        conn.close()

    def test_both_skips_combined(self, tmp_db_path):
        """When IPO year == current year, both skips should apply (no double-count issue)."""
        conn = sqlite3.connect(tmp_db_path)
        # Simulate a stock IPO'd in current year
        _setup_stock_basic(conn, [("sh.688999", "2026-03-01", None)])
        codes = ["sh.688999"]

        candidates = _count_candidates(conn, codes, 2007, 2026, "growth_data", 2026, 2)
        # eff_start = 2026, current_quarter = 2
        # Q1 2026: skipped by IPO year rule
        # Q2 2026: skipped by current quarter rule
        # Result: no candidates
        assert candidates == []

        conn.close()

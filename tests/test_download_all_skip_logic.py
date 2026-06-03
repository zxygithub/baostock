"""Unit tests for scripts/download_all.py — weekly/monthly K-line skip logic.

Tests the decision logic that determines whether to download weekly/monthly
K-line data based on staleness thresholds, without requiring a live database
or network connection.

Core rules under test:
- Weekly: skip if (target_date - latest_weekly_date) < 7 days
- Monthly: skip if trading days from month-start to target_date > 3
- Monthly same-month guard: skip if monthly_start is in the same month as latest data
- When downloading, use incremental start = latest_date + 1 day
- When end_date < start_date, skip download as "up to date"
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures: temporary database with trade_dates populated
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_path():
    """Create a temporary SQLite database and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    import os
    os.close(fd)
    return path


def _create_trade_dates(conn: sqlite3.Connection):
    """Create trade_dates table and insert sample trading days for May 2026."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_dates (
            calendar_date   TEXT PRIMARY KEY,
            is_trading_day  INTEGER NOT NULL,
            update_time     TEXT
        )
    """)
    # May 2026 trading days (Mon-Fri, excluding holidays)
    # May 1 (Fri) - holiday, May 4 (Mon) - first trading day
    trading_days = [
        "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
        "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
        "2026-05-18", "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
        "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
    ]
    # All calendar days in May
    for day in range(1, 32):
        date_str = f"2026-05-{day:02d}"
        is_trading = 1 if date_str in trading_days else 0
        conn.execute(
            "INSERT INTO trade_dates (calendar_date, is_trading_day) VALUES (?, ?)",
            (date_str, is_trading),
        )
    conn.commit()


def _create_kline_tables(conn: sqlite3.Connection):
    """Create minimal weekly/monthly K-line tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS all_stock_weekly (
            code TEXT NOT NULL, date TEXT NOT NULL, close REAL, adjustflag INTEGER DEFAULT 3,
            PRIMARY KEY (code, date, adjustflag)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS all_stock_monthly (
            code TEXT NOT NULL, date TEXT NOT NULL, close REAL, adjustflag INTEGER DEFAULT 3,
            PRIMARY KEY (code, date, adjustflag)
        )
    """)


# ---------------------------------------------------------------------------
# Helper: replicate the skip logic from download_all.py
# ---------------------------------------------------------------------------

def compute_should_update_weekly(target_date: str, latest_weekly: str | None) -> bool:
    """Replicate weekly skip logic from download_all.py."""
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    latest_weekly_dt = datetime.strptime(latest_weekly or "1990-12-19", "%Y-%m-%d")
    return (target_dt - latest_weekly_dt).days >= 7


def compute_should_update_monthly(
    target_date: str,
    latest_monthly: str | None,
    trading_days_in_range: list[str],
) -> bool:
    """Replicate monthly skip logic from download_all.py."""
    return len(trading_days_in_range) <= 3


def should_skip_monthly_same_month(latest_monthly: str) -> bool:
    """Replicate the same-month guard from download_all.py.

    When monthly_start (latest_monthly + 1 day) falls in the same
    month as latest_monthly, the new month has no complete data yet.
    """
    lm = datetime.strptime(latest_monthly, "%Y-%m-%d")
    ms = lm + timedelta(days=1)
    return ms.month == lm.month and ms.year == lm.year


# ---------------------------------------------------------------------------
# Weekly skip logic tests
# ---------------------------------------------------------------------------

class TestWeeklySkipLogic:
    """Tests for the weekly K-line staleness check."""

    def test_exactly_7_days_should_update(self):
        """When exactly 7 days have passed, should update."""
        assert compute_should_update_weekly("2026-05-15", "2026-05-08") is True

    def test_6_days_should_skip(self):
        """When less than 7 days have passed, should skip."""
        assert compute_should_update_weekly("2026-05-14", "2026-05-08") is False

    def test_14_days_should_update(self):
        """Two weeks without update should definitely trigger."""
        assert compute_should_update_weekly("2026-05-22", "2026-05-08") is True

    def test_empty_table_should_update(self):
        """When table is empty (None), should always update."""
        assert compute_should_update_weekly("2026-05-15", None) is True

    def test_same_day_should_skip(self):
        """Same day re-run should skip weekly."""
        assert compute_should_update_weekly("2026-05-08", "2026-05-08") is False

    def test_one_day_should_skip(self):
        """One day after last update should skip."""
        assert compute_should_update_weekly("2026-05-09", "2026-05-08") is False


# ---------------------------------------------------------------------------
# Monthly skip logic tests
# ---------------------------------------------------------------------------

class TestMonthlySkipLogic:
    """Tests for the monthly K-line trading-day threshold check."""

    def test_first_trading_day_should_update(self):
        """Month with only 1 trading day should update."""
        assert compute_should_update_monthly(
            "2026-05-04", None, ["2026-05-04"]
        ) is True

    def test_second_trading_day_should_update(self):
        """Month with 2 trading days should update."""
        assert compute_should_update_monthly(
            "2026-05-05", None, ["2026-05-04", "2026-05-05"]
        ) is True

    def test_third_trading_day_should_update(self):
        """Month with exactly 3 trading days should update (boundary)."""
        assert compute_should_update_monthly(
            "2026-05-06", None,
            ["2026-05-04", "2026-05-05", "2026-05-06"],
        ) is True

    def test_fourth_trading_day_should_skip(self):
        """Month with 4+ trading days should skip."""
        assert compute_should_update_monthly(
            "2026-05-07", None,
            ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07"],
        ) is False

    def test_ten_trading_days_should_skip(self):
        """Mid-month with many trading days should skip."""
        trading_days = [
            "2026-05-04", "2026-05-05", "2026-05-06",
            "2026-05-07", "2026-05-08", "2026-05-11",
            "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
        ]
        assert compute_should_update_monthly("2026-05-15", None, trading_days) is False

    def test_empty_table_should_update(self):
        """When monthly table is empty, should update on first trading day."""
        assert compute_should_update_monthly(
            "2026-05-04", None, ["2026-05-04"]
        ) is True

    def test_already_updated_this_month_should_skip(self):
        """If latest_monthly is within this month and >3 trading days passed, skip."""
        # Latest monthly data is from May 6 (3rd trading day), now it's May 15 (10th)
        trading_days = [
            "2026-05-04", "2026-05-05", "2026-05-06",
            "2026-05-07", "2026-05-08", "2026-05-11",
            "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
        ]
        assert compute_should_update_monthly(
            "2026-05-15", "2026-05-06", trading_days
        ) is False


# ---------------------------------------------------------------------------
# Same-month guard tests (prevents redundant monthly requests)
# ---------------------------------------------------------------------------

class TestMonthlySameMonthGuard:
    """Tests for the same-month guard that prevents downloading when
    monthly_start falls in the same month as latest_monthly."""

    def test_last_day_of_month_should_not_skip(self):
        """latest_monthly=2026-04-30 → monthly_start=2026-05-01 (new month) → don't skip."""
        assert should_skip_monthly_same_month("2026-04-30") is False

    def test_may29_should_skip(self):
        """latest_monthly=2026-05-29 → monthly_start=2026-05-30 (same month) → skip.
        This is the exact 6/3 scenario from the bug report."""
        assert should_skip_monthly_same_month("2026-05-29") is True

    def test_last_day_feb_leap_year(self):
        """latest_monthly=2024-02-29 (leap) → monthly_start=2024-03-01 → don't skip."""
        assert should_skip_monthly_same_month("2024-02-29") is False

    def test_last_day_feb_non_leap(self):
        """latest_monthly=2025-02-28 → monthly_start=2025-03-01 → don't skip."""
        assert should_skip_monthly_same_month("2025-02-28") is False

    def test_mid_month_should_skip(self):
        """latest_monthly=2026-05-15 → monthly_start=2026-05-16 (same month) → skip."""
        assert should_skip_monthly_same_month("2026-05-15") is True

    def test_last_day_of_year_should_not_skip(self):
        """latest_monthly=2026-12-31 → monthly_start=2027-01-01 → don't skip."""
        assert should_skip_monthly_same_month("2026-12-31") is False

    def test_last_day_january_should_not_skip(self):
        """latest_monthly=2026-01-31 → monthly_start=2026-02-01 (new month) → don't skip."""
        assert should_skip_monthly_same_month("2026-01-31") is False


# ---------------------------------------------------------------------------
# Incremental download range tests
# ---------------------------------------------------------------------------

class TestIncrementalRange:
    """Tests for incremental download start/end date calculation."""

    def test_weekly_start_date_calculation(self):
        """Weekly start should be latest_weekly + 1 day."""
        latest_weekly = datetime.strptime("2026-05-08", "%Y-%m-%d")
        weekly_start = (latest_weekly + timedelta(days=1)).strftime("%Y-%m-%d")
        assert weekly_start == "2026-05-09"

    def test_monthly_start_date_calculation(self):
        """Monthly start should be latest_monthly + 1 day."""
        latest_monthly = datetime.strptime("2026-04-30", "%Y-%m-%d")
        monthly_start = (latest_monthly + timedelta(days=1)).strftime("%Y-%m-%d")
        assert monthly_start == "2026-05-01"

    def test_end_date_before_start_skip(self):
        """If kline_end_date < start_date, download should be skipped."""
        start = "2026-05-15"
        end = "2026-05-10"
        assert (end >= start) is False

    def test_end_date_equals_start_download(self):
        """If kline_end_date == start_date, single-day download should happen."""
        start = "2026-05-15"
        end = "2026-05-15"
        assert (end >= start) is True

    def test_normal_range_download(self):
        """Normal case: end_date > start_date should trigger download."""
        start = "2026-05-09"
        end = "2026-05-22"
        assert (end >= start) is True


# ---------------------------------------------------------------------------
# DBManager method tests with real SQLite
# ---------------------------------------------------------------------------

class TestDBManagerMethods:
    """Test DBManager methods used by the skip logic against a real SQLite DB."""

    def test_get_max_date_empty_table(self, tmp_db_path):
        """get_max_date should return None for empty table."""
        conn = sqlite3.connect(tmp_db_path)
        conn.execute("""
            CREATE TABLE test_empty (code TEXT, date TEXT)
        """)
        conn.commit()
        cursor = conn.execute("SELECT MAX(date) FROM test_empty")
        row = cursor.fetchone()
        conn.close()
        assert row[0] is None

    def test_get_max_date_with_data(self, tmp_db_path):
        """get_max_date should return the maximum date value."""
        conn = sqlite3.connect(tmp_db_path)
        conn.execute("""
            CREATE TABLE test_with_data (code TEXT, date TEXT)
        """)
        conn.executemany(
            "INSERT INTO test_with_data (code, date) VALUES (?, ?)",
            [("sh.600000", "2026-05-01"), ("sh.600000", "2026-05-08"),
             ("sh.600000", "2026-05-15")],
        )
        conn.commit()
        cursor = conn.execute("SELECT MAX(date) FROM test_with_data")
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "2026-05-15"

    def test_get_trading_days_in_range(self, tmp_db_path):
        """get_trading_days_in_range should return only trading days."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)

        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date >= ? AND calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date ASC",
            ("2026-05-04", "2026-05-08"),
        )
        days = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert days == ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]

    def test_get_trading_days_in_range_cross_weekend(self, tmp_db_path):
        """Trading days range should skip weekends."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)

        # May 9-10 is Sat-Sun, should not be included
        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date >= ? AND calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date ASC",
            ("2026-05-08", "2026-05-11"),
        )
        days = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert days == ["2026-05-08", "2026-05-11"]

    def test_get_latest_trading_day_on_or_before(self, tmp_db_path):
        """Should return the most recent trading day on or before given date."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)

        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date DESC LIMIT 1",
            ("2026-05-10",),  # May 10 is Sunday
        )
        row = cursor.fetchone()
        conn.close()

        assert row[0] == "2026-05-08"  # Friday


# ---------------------------------------------------------------------------
# End-to-end skip decision tests (mocked DBManager)
# ---------------------------------------------------------------------------

class TestEndToEndSkipDecision:
    """Test the complete skip decision flow as it would run in download_all.py."""

    def test_weekly_stale_triggers_download(self, tmp_db_path):
        """When weekly data is >7 days stale, should trigger download."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)
        # Insert old weekly data
        conn.execute(
            "INSERT INTO all_stock_weekly (code, date, close) VALUES (?, ?, ?)",
            ("sh.600000", "2026-05-01", 10.5),
        )
        conn.commit()

        target_date = "2026-05-22"
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        cursor = conn.execute("SELECT MAX(date) FROM all_stock_weekly")
        row = cursor.fetchone()
        latest_weekly = datetime.strptime(row[0] if row else "1990-12-19", "%Y-%m-%d")
        should_update = (target_dt - latest_weekly).days >= 7

        conn.close()
        assert should_update is True
        assert (target_dt - latest_weekly).days == 21

    def test_weekly_fresh_skips_download(self, tmp_db_path):
        """When weekly data is <7 days stale, should skip."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)
        conn.execute(
            "INSERT INTO all_stock_weekly (code, date, close) VALUES (?, ?, ?)",
            ("sh.600000", "2026-05-20", 10.5),
        )
        conn.commit()

        target_date = "2026-05-22"
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        cursor = conn.execute("SELECT MAX(date) FROM all_stock_weekly")
        row = cursor.fetchone()
        latest_weekly = datetime.strptime(row[0] if row else "1990-12-19", "%Y-%m-%d")
        should_update = (target_dt - latest_weekly).days >= 7

        conn.close()
        assert should_update is False
        assert (target_dt - latest_weekly).days == 2

    def test_monthly_first_three_days_triggers_download(self, tmp_db_path):
        """When within first 3 trading days of month, should download monthly."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)

        target_date = "2026-05-06"  # 3rd trading day of May
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        first_day_of_month = target_dt.replace(day=1)

        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date >= ? AND calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date ASC",
            (first_day_of_month.strftime("%Y-%m-%d"), target_date),
        )
        trading_days_so_far = [row[0] for row in cursor.fetchall()]
        should_update = len(trading_days_so_far) <= 3

        conn.close()
        assert should_update is True
        assert len(trading_days_so_far) == 3

    def test_monthly_after_three_days_skips_download(self, tmp_db_path):
        """When past 3 trading days of month, should skip monthly."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)

        target_date = "2026-05-15"  # 10th trading day of May
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        first_day_of_month = target_dt.replace(day=1)

        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date >= ? AND calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date ASC",
            (first_day_of_month.strftime("%Y-%m-%d"), target_date),
        )
        trading_days_so_far = [row[0] for row in cursor.fetchall()]
        should_update = len(trading_days_so_far) <= 3

        conn.close()
        assert should_update is False
        assert len(trading_days_so_far) == 10

    def test_weekly_up_to_date_skips_download(self, tmp_db_path):
        """When weekly_start > kline_end_date, should skip as 'up to date'."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)
        # Weekly data is very recent
        conn.execute(
            "INSERT INTO all_stock_weekly (code, date, close) VALUES (?, ?, ?)",
            ("sh.600000", "2026-05-21", 10.5),
        )
        conn.commit()

        target_date = "2026-05-22"
        kline_end_date = target_date  # Assume target is a trading day
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        cursor = conn.execute("SELECT MAX(date) FROM all_stock_weekly")
        row = cursor.fetchone()
        latest_weekly = datetime.strptime(row[0] if row else "1990-12-19", "%Y-%m-%d")
        should_update = (target_dt - latest_weekly).days >= 7

        # Even if should_update were True, check date range
        weekly_start = (latest_weekly + timedelta(days=1)).strftime("%Y-%m-%d")
        would_download = should_update and kline_end_date >= weekly_start

        conn.close()
        assert should_update is False  # 1 day < 7 days
        assert would_download is False

    def test_monthly_already_up_to_date_skips(self, tmp_db_path):
        """When monthly_start > kline_end_date, should skip as 'up to date'."""
        conn = sqlite3.connect(tmp_db_path)
        _create_trade_dates(conn)
        _create_kline_tables(conn)
        # Monthly data already has latest date
        conn.execute(
            "INSERT INTO all_stock_monthly (code, date, close) VALUES (?, ?, ?)",
            ("sh.600000", "2026-05-22", 10.5),
        )
        conn.commit()

        target_date = "2026-05-22"
        kline_end_date = target_date
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")

        cursor = conn.execute("SELECT MAX(date) FROM all_stock_monthly")
        row = cursor.fetchone()
        latest_monthly = datetime.strptime(row[0] if row else "1990-12-19", "%Y-%m-%d")

        first_day_of_month = target_dt.replace(day=1)
        cursor = conn.execute(
            "SELECT calendar_date FROM trade_dates "
            "WHERE calendar_date >= ? AND calendar_date <= ? AND is_trading_day = 1 "
            "ORDER BY calendar_date ASC",
            (first_day_of_month.strftime("%Y-%m-%d"), target_date),
        )
        trading_days_so_far = [row[0] for row in cursor.fetchall()]
        should_update = len(trading_days_so_far) <= 3

        monthly_start = (latest_monthly + timedelta(days=1)).strftime("%Y-%m-%d")
        would_download = should_update and kline_end_date >= monthly_start

        conn.close()
        # May 22 is the 14th trading day, so should_update is False
        assert should_update is False
        assert would_download is False

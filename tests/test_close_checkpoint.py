"""Regression tests for the WAL checkpoint lock bug on downloader close.

Bug scenario (reproduced by smoke_test.py phase 7):
1. `_find_missing_quarters` / `_find_missing_dividend` insert candidates into
   a TEMP table via executemany. Python sqlite3 implicitly opens a transaction
   for the INSERT, and the subsequent LEFT JOIN SELECT on the main table
   acquires a WAL read snapshot inside that transaction.
2. When all candidates already exist, the downloader returns early without any
   commit, leaving the transaction open.
3. `close()` runs `PRAGMA wal_checkpoint(TRUNCATE)`, which fails with
   sqlite3.OperationalError("database table is locked") against the
   connection's own read snapshot.

These tests bypass `__init__` (which requires a live baostock login) via
`object.__new__` and drive the internal methods against a temp SQLite DB.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.dividend_downloader import DividendDownloader


@pytest.fixture
def downloader_factory(tmp_path):
    """Build a downloader instance without running __init__ (no network)."""

    def _make(cls, table_ddl: dict[str, str]):
        db_path = tmp_path / f"{cls.__name__.lower()}.db"
        dl = object.__new__(cls)
        dl.db_path = db_path
        dl.logger = None  # set below once conn exists
        dl._conn = None
        dl._limit_exceeded = True  # skip logout() in close()
        dl._interrupted = False

        import logging

        dl.logger = logging.getLogger(f"test_{cls.__name__}")

        # Create required tables upfront via the same connection the
        # downloader will use, so schemas match what the methods expect.
        for ddl in table_ddl.values():
            dl.conn.execute(ddl)
        dl.conn.commit()
        return dl

    return _make


class TestFinancialCloseAfterAllUpToDate:
    """FinancialDownloader.close() must not raise when nothing was downloaded."""

    def test_close_after_all_quarters_exist(self, downloader_factory):
        dl = downloader_factory(
            FinancialDownloader,
            {
                "profit_data": (
                    "CREATE TABLE profit_data ("
                    "code TEXT, year INTEGER, quarter INTEGER, "
                    "PRIMARY KEY (code, year, quarter))"
                ),
            },
        )
        # Candidate already exists -> _find_missing_quarters returns no tasks,
        # mirroring the "all up to date, skipping" path.
        dl.conn.execute(
            "INSERT INTO profit_data (code, year, quarter) VALUES (?, ?, ?)",
            ("sh.600000", 2024, 1),
        )
        dl.conn.commit()

        tasks, skipped = dl._find_missing_quarters(
            "profit_data", [("sh.600000", 2024, 1)]
        )
        assert tasks == []
        assert skipped == 1

        # Before the fix this raised:
        # sqlite3.OperationalError: database table is locked
        dl.close()
        assert dl._conn is None

    def test_close_after_partial_missing(self, downloader_factory):
        """Some candidates missing: tasks returned, close still clean."""
        dl = downloader_factory(
            FinancialDownloader,
            {
                "profit_data": (
                    "CREATE TABLE profit_data ("
                    "code TEXT, year INTEGER, quarter INTEGER, "
                    "PRIMARY KEY (code, year, quarter))"
                ),
            },
        )
        dl.conn.execute(
            "INSERT INTO profit_data (code, year, quarter) VALUES (?, ?, ?)",
            ("sh.600000", 2024, 1),
        )
        dl.conn.commit()

        tasks, skipped = dl._find_missing_quarters(
            "profit_data",
            [("sh.600000", 2024, 1), ("sh.600000", 2024, 2)],
        )
        assert tasks == [("sh.600000", 2024, 2)]
        assert skipped == 1

        dl.close()
        assert dl._conn is None


class TestDividendCloseAfterAllUpToDate:
    """DividendDownloader.close() must not raise when nothing was downloaded."""

    def test_close_after_all_dividend_exist(self, downloader_factory):
        dl = downloader_factory(
            DividendDownloader,
            {
                "dividend": (
                    "CREATE TABLE dividend ("
                    "code TEXT, year INTEGER, year_type TEXT, "
                    "PRIMARY KEY (code, year, year_type))"
                ),
            },
        )
        dl.conn.execute(
            "INSERT INTO dividend (code, year, year_type) VALUES (?, ?, ?)",
            ("sh.600000", 2020, "report"),
        )
        dl.conn.commit()

        # 2020 not in recent_years -> relies on the DB row, not the
        # recent-year skip, so the temp-table path runs fully.
        result = dl._find_missing_dividend(
            [("sh.600000", 2020, "report")], recent_years={2026}
        )
        assert result["tasks"] == []

        dl.close()
        assert dl._conn is None


class TestCloseExceptionSafety:
    """close() must always close the connection and not raise, even when a
    stray transaction would make the checkpoint fail."""

    def test_close_with_stray_transaction_does_not_raise(self, tmp_path):
        dl = object.__new__(FinancialDownloader)
        dl.db_path = tmp_path / "stray.db"
        dl._conn = None
        dl._limit_exceeded = True
        dl._interrupted = False

        import logging

        dl.logger = logging.getLogger("test_stray")

        # Recreate the pre-fix stray transaction: temp-table INSERT with no
        # commit/rollback, then a read on the main table inside it.
        dl.conn.execute("CREATE TABLE profit_data (code TEXT)")
        dl.conn.commit()
        dl.conn.execute("CREATE TEMP TABLE _t (x INTEGER)")
        dl.conn.executemany("INSERT INTO _t VALUES (?)", [(1,)])
        dl.conn.execute("SELECT * FROM profit_data").fetchall()
        dl.conn.execute("DROP TABLE _t")

        # Checkpoint would fail here; close() must swallow and clean up.
        dl.close()
        assert dl._conn is None

    def test_close_idempotent(self, downloader_factory):
        dl = downloader_factory(FinancialDownloader, {})
        dl.close()
        dl.close()  # second close is a no-op
        assert dl._conn is None

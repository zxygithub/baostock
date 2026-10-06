"""Unit tests for API request quota accounting in BaseDownloader.

Bug regression suite: every attempt that reaches the query function must be
counted exactly once in the request_count table - whether the query succeeds,
returns error_code != "0", or raises an exception. Failed attempts used to
jump to `except Exception` before `_increment_request_count()` ran, so the
client ledger under-counted while the BaoStock server still counted the
requests (2026-10-06: 924 under-counted exception-path attempts contributed
to an IP blacklist past the 50000/day server cap).
"""

import logging
import sqlite3
from datetime import date

import pytest

from src.downloaders.base import BaseDownloader


REQUEST_COUNT_DDL = (
    "CREATE TABLE IF NOT EXISTS request_count ("
    "date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, update_time TEXT)"
)


class FakeRs:
    """Minimal successful BaoStock result set (error_code == "0")."""

    error_code = "0"
    error_msg = ""
    fields = []

    def next(self):
        return False

    def get_row_data(self):
        return []


def _make_dl(tmp_path, monkeypatch):
    dl = object.__new__(BaseDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl.logger = logging.getLogger("test_request_count")
    dl.conn.execute(REQUEST_COUNT_DDL)
    dl.conn.commit()
    monkeypatch.setattr(dl, "ensure_login", lambda: None)
    monkeypatch.setattr(dl, "login", lambda: None)
    monkeypatch.setattr(dl, "logout", lambda: None)
    monkeypatch.setattr(BaseDownloader, "DAILY_REQUEST_LIMIT", 10**9)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    return dl


def _today_count(db_path) -> int:
    """Read today's request count through a separate connection.

    Committed state (not the downloader connection's own open transaction) is
    what survives a rollback at connection close - exactly the persistence the
    quota ledger depends on.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT count FROM request_count WHERE date = ?",
            (date.today().isoformat(),),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def test_exception_attempts_are_counted(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)

    def failing_query(**kwargs):
        raise ValueError("Expecting ',' delimiter: line 1 column 505 (char 504)")

    with pytest.raises(RuntimeError):
        dl.query_with_retry(failing_query, max_retries=3)

    assert _today_count(dl.db_path) == 3


def test_success_query_counted_exactly_once(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)

    result = dl.query_with_retry(lambda **kwargs: FakeRs(), max_retries=3)

    assert result.error_code == "0"
    assert _today_count(dl.db_path) == 1


def test_api_call_exception_is_counted(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)

    def failing_func(*args, **kwargs):
        raise ValueError("Expecting ',' delimiter: line 1 column 505 (char 504)")

    with pytest.raises(ValueError):
        dl._api_call(failing_func)

    assert _today_count(dl.db_path) == 1

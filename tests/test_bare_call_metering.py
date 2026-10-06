"""Metering tests for bare bs.* calls outside BaseDownloader.

2026-10-06 incident: the server counted requests the local request_count
ledger never saw - BaseDownloader.login()/logout() (initial login, 540s
session refreshes, session-error relogins ~400-440/day) plus diagnostic
scripts - forcing a blind 4000-request safety margin under the 50000 cap.
These tests pin down:
- BaseDownloader.login()/logout() each record exactly 1 request, committed
  (verified through a separate sqlite connection)
- src.utils.quota.record_requests(n) UPSERTs n into today's ledger row and
  never raises on sqlite failures.
"""

import logging
import sqlite3
from datetime import date

from src.downloaders.base import BaseDownloader


REQUEST_COUNT_DDL = (
    "CREATE TABLE IF NOT EXISTS request_count ("
    "date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, update_time TEXT)"
)


class FakeLoginRs:
    """Minimal successful BaoStock login result (error_code == "0")."""

    error_code = "0"
    error_msg = ""


class FakeBs:
    """Stand-in for the baostock module - no network."""

    @staticmethod
    def login():
        return FakeLoginRs()

    @staticmethod
    def logout():
        return None


def _make_dl(tmp_path, monkeypatch):
    dl = object.__new__(BaseDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl.logger = logging.getLogger("test_bare_call_metering")
    dl.conn.execute(REQUEST_COUNT_DDL)
    dl.conn.commit()
    monkeypatch.setattr(dl, "_apply_socket_timeout", lambda: None)
    monkeypatch.setattr("src.downloaders.base.bs", FakeBs)
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


def test_login_records_one_request(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)

    dl.login()

    assert _today_count(dl.db_path) == 1


def test_logout_records_one_request(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)

    dl.logout()

    assert _today_count(dl.db_path) == 1


def test_record_requests_adds_n(tmp_path):
    from src.utils.quota import record_requests

    db = tmp_path / "quota.db"
    conn = sqlite3.connect(str(db))
    conn.execute(REQUEST_COUNT_DDL)
    conn.commit()
    conn.close()

    record_requests(3, db_path=db)

    assert _today_count(db) == 3


def test_record_requests_never_raises(tmp_path):
    from src.utils.quota import record_requests

    bad_db = tmp_path / "no_such_dir" / "quota.db"

    assert record_requests(1, db_path=bad_db) is None

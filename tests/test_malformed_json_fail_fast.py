"""Fail-fast regression suite for deterministic server-side JSON corruption.

2026-10-06 incident follow-up: 22 stocks return 业绩预告 (forecast report)
payloads with unescaped 中文引号, producing json.JSONDecodeError("Expecting ','
delimiter", ...) at the same char positions on every request. Retrying such
deterministic parse failures wasted ~594 requests/day toward the 50000/day
server cap and contributed to the IP blacklist. query_with_retry must give up
after exactly one attempt on JSONDecodeError while still retrying transient
exceptions.
"""

import json
import logging
import sqlite3
from datetime import date

import pytest

from src.downloaders.base import BaseDownloader


REQUEST_COUNT_DDL = (
    "CREATE TABLE IF NOT EXISTS request_count ("
    "date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, update_time TEXT)"
)


def _make_dl(tmp_path, monkeypatch):
    dl = object.__new__(BaseDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl.logger = logging.getLogger("test_malformed_json_fail_fast")
    dl.conn.execute(REQUEST_COUNT_DDL)
    dl.conn.commit()
    monkeypatch.setattr(dl, "ensure_login", lambda: None)
    monkeypatch.setattr(dl, "login", lambda: None)
    monkeypatch.setattr(dl, "logout", lambda: None)
    monkeypatch.setattr(BaseDownloader, "DAILY_REQUEST_LIMIT", 10**9)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    return dl


def _today_count(db_path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT count FROM request_count WHERE date = ?",
            (date.today().isoformat(),),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def test_json_decode_error_fails_fast_after_one_attempt(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)
    calls = []

    def corrupt_query(**kwargs):
        calls.append(kwargs)
        raise json.JSONDecodeError("Expecting ',' delimiter", "doc", 504)

    with pytest.raises(RuntimeError):
        dl.query_with_retry(corrupt_query, max_retries=3)

    assert len(calls) == 1
    assert _today_count(dl.db_path) == 1


def test_generic_exception_still_retries_three_times(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, monkeypatch)
    calls = []

    def flaky_query(**kwargs):
        calls.append(kwargs)
        raise ValueError("transient failure")

    with pytest.raises(RuntimeError):
        dl.query_with_retry(flaky_query, max_retries=3)

    assert len(calls) == 3
    assert _today_count(dl.db_path) == 3

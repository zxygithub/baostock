"""Unit tests for the daily_probe_memo table and probe memo helpers.

The memo table records "this scope/item was probed today" so later tasks
probe permanently-missing data once per day instead of every pass.
mark_probed UPSERTs today's local date and commits immediately;
is_probed_today is True only when probe_date equals today.
"""

import logging
import sqlite3
from datetime import date, timedelta

from src.db_manager import DBManager
from src.downloaders.base import BaseDownloader


def _make_dl(tmp_path):
    db_path = tmp_path / "dl.db"
    db = DBManager(str(db_path))
    db.init_all_tables()
    db.close()

    dl = object.__new__(BaseDownloader)
    dl.db_path = db_path
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_probe_memo")
    return dl


def _memo_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT scope, item_key, probe_date FROM daily_probe_memo"
        ).fetchall()
    finally:
        conn.close()


def test_mark_then_probed_same_day(tmp_path):
    dl = _make_dl(tmp_path)

    assert dl.is_probed_today("af_uncovered", "sh.600000") is False

    dl.mark_probed("af_uncovered", "sh.600000")

    assert dl.is_probed_today("af_uncovered", "sh.600000") is True
    # 不同 scope/item_key 互不影响
    assert dl.is_probed_today("af_uncovered", "sh.600001") is False
    assert dl.is_probed_today("fin_missing:profit_data", "sh.600000") is False


def test_yesterday_mark_not_probed(tmp_path):
    dl = _make_dl(tmp_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    dl.conn.execute(
        "INSERT INTO daily_probe_memo (scope, item_key, probe_date) "
        "VALUES (?, ?, ?)",
        ("fin_missing:profit_data", "sh.600000|2020|1", yesterday),
    )
    dl.conn.commit()

    assert dl.is_probed_today("fin_missing:profit_data", "sh.600000|2020|1") is False


def test_mark_upserts_overwrite(tmp_path):
    dl = _make_dl(tmp_path)

    dl.mark_probed("af_uncovered", "sh.600000")
    dl.mark_probed("af_uncovered", "sh.600000")  # 重复 mark 不报错

    rows = _memo_rows(dl.db_path)
    assert len(rows) == 1
    assert rows[0] == ("af_uncovered", "sh.600000", date.today().isoformat())
    # mark_probed 立即 commit，独立连接可见且不在写事务中
    assert not dl.conn.in_transaction


def test_missing_table_recreated_on_migrate(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE request_count ("
        "date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, update_time TEXT)"
    )
    conn.commit()
    conn.close()

    db = DBManager(str(db_path))
    try:
        db.migrate_schema()
    finally:
        db.close()

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "daily_probe_memo" in tables

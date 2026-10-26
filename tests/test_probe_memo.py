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
from src.downloaders.financial_downloader import FinancialDownloader
from src.downloaders.dividend_downloader import DividendDownloader
import src.downloaders.financial_downloader as fin_mod


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


# ---------------------------------------------------------------------------
# Task 5: 财务缺失季度 / 复权未覆盖事件 每日一探
# ---------------------------------------------------------------------------


def _make_fin_dl(tmp_path):
    db_path = tmp_path / "fin_probe.db"
    db = DBManager(str(db_path))
    db.init_all_tables()
    db.close()
    dl = object.__new__(FinancialDownloader)
    dl.db_path = db_path
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_fin_probe")
    dl.new_rows = 0
    return dl


def _make_div_dl(tmp_path):
    db_path = tmp_path / "div_probe.db"
    db = DBManager(str(db_path))
    db.init_all_tables()
    db.close()
    dl = object.__new__(DividendDownloader)
    dl.db_path = db_path
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_div_probe")
    return dl


def _run_quarterly(dl, monkeypatch, table_name, codes, start_year, end_year,
                   current, fields, rows, column_renames):
    monkeypatch.setattr(fin_mod, "get_current_quarter", lambda: current)
    monkeypatch.setattr(dl, "get_stock_years",
                        lambda c, s, e: {x: (s, e) for x in c})
    monkeypatch.setattr(dl, "get_stock_out_dates",
                        lambda: {x: None for x in codes})
    monkeypatch.setattr(fin_mod, "FINANCIAL_SLEEP", 0)

    FakeRs = type("FakeRs", (), {"fields": fields})

    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kw: FakeRs())
    monkeypatch.setattr(fin_mod, "fetch_all_rows", lambda rs: rows)
    return dl._download_quarterly_data(
        codes=codes,
        query_func=lambda **kw: None,
        column_renames=column_renames,
        table_name=table_name,
        start_year=start_year,
        end_year=end_year,
    )


def test_fin_missing_probed_once_per_day(tmp_path, monkeypatch):
    dl = _make_fin_dl(tmp_path)

    _run_quarterly(
        dl, monkeypatch, "profit_data", ["sh.600000"], 2024, 2024,
        (2024, 3), ["statDate"], [], {"statDate": "stat_date"},
    )

    # 空结果（recent-year 无占位行）任务当日已探，第二趟不再出现
    assert dl.is_probed_today("fin_missing:profit_data", "sh.600000|2024|1")
    tasks, skipped = dl._find_missing_quarters(
        "profit_data", [("sh.600000", 2024, 1)]
    )
    assert tasks == []
    assert skipped == 1


def test_fin_missing_reprobed_next_day(tmp_path):
    dl = _make_fin_dl(tmp_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    dl.mark_probed("fin_missing:profit_data", "sh.600000|2024|1")
    dl.conn.execute(
        "UPDATE daily_probe_memo SET probe_date = ? "
        "WHERE scope = ? AND item_key = ?",
        (yesterday, "fin_missing:profit_data", "sh.600000|2024|1"),
    )
    dl.conn.commit()

    tasks, skipped = dl._find_missing_quarters(
        "profit_data", [("sh.600000", 2024, 1)]
    )
    assert tasks == [("sh.600000", 2024, 1)]
    assert skipped == 0


def test_fin_missing_not_marked_on_error(tmp_path, monkeypatch):
    dl = _make_fin_dl(tmp_path)
    monkeypatch.setattr(fin_mod, "get_current_quarter", lambda: (2024, 3))
    monkeypatch.setattr(dl, "get_stock_years",
                        lambda c, s, e: {x: (s, e) for x in c})
    monkeypatch.setattr(dl, "get_stock_out_dates",
                        lambda: {x: None for x in ["sh.600000"]})
    monkeypatch.setattr(fin_mod, "FINANCIAL_SLEEP", 0)

    def boom(func, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(dl, "query_with_retry", boom)

    dl._download_quarterly_data(
        codes=["sh.600000"],
        query_func=lambda **kw: None,
        column_renames={"statDate": "stat_date"},
        table_name="profit_data",
        start_year=2024,
        end_year=2024,
    )

    # RuntimeError 路径不 mark，下趟仍在
    assert dl.is_probed_today("fin_missing:profit_data", "sh.600000|2024|1") is False
    tasks, _ = dl._find_missing_quarters(
        "profit_data", [("sh.600000", 2024, 1)]
    )
    assert tasks == [("sh.600000", 2024, 1)]


def test_fin_missing_counts_new_rows(tmp_path, monkeypatch):
    dl = _make_fin_dl(tmp_path)

    total = _run_quarterly(
        dl, monkeypatch, "profit_data", ["sh.600000"], 2024, 2024,
        (2024, 3), ["code", "statDate"],
        [["sh.600000", "2024-03-31"]], {"statDate": "stat_date"},
    )

    assert total == 1
    assert dl.new_rows == 1


def test_af_uncovered_probed_once_per_day(tmp_path):
    dl = _make_div_dl(tmp_path)
    today = date.today().isoformat()

    # 第一分支排除：已有今日刷新的复权行（另一除权日）
    dl.conn.execute(
        "INSERT OR REPLACE INTO adjust_factor VALUES (?,?,?,?,?,?)",
        ("A", "2020-01-01", 1.0, 2.0, 2.0, f"{today} 05:00:00"),
    )
    # 第二分支命中：未被复权因子覆盖的除权事件
    dl.conn.execute(
        "INSERT INTO dividend (code, divid_operate_date, year, year_type) "
        "VALUES (?,?,?,?)",
        ("A", "2025-06-30", 2025, "operate"),
    )
    dl.conn.commit()

    stale, _ = dl._find_stale_adjust_factor(["A"], today)
    assert stale == ["A"]

    dl.mark_probed("af_uncovered", "A")

    stale2, skipped2 = dl._find_stale_adjust_factor(["A"], today)
    assert stale2 == []
    assert skipped2 == 1


def test_af_uncovered_reprobed_next_day(tmp_path):
    dl = _make_div_dl(tmp_path)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    dl.conn.execute(
        "INSERT OR REPLACE INTO adjust_factor VALUES (?,?,?,?,?,?)",
        ("A", "2020-01-01", 1.0, 2.0, 2.0, f"{today} 05:00:00"),
    )
    dl.conn.execute(
        "INSERT INTO dividend (code, divid_operate_date, year, year_type) "
        "VALUES (?,?,?,?)",
        ("A", "2025-06-30", 2025, "operate"),
    )
    dl.conn.commit()

    dl.mark_probed("af_uncovered", "A")
    dl.conn.execute(
        "UPDATE daily_probe_memo SET probe_date = ? "
        "WHERE scope = 'af_uncovered' AND item_key = ?",
        (yesterday, "A"),
    )
    dl.conn.commit()

    stale, _ = dl._find_stale_adjust_factor(["A"], today)
    assert stale == ["A"]

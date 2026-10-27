"""Unit tests for the zero-new probe memo on K-line / index fetches.

Delisted stocks whose last bar sits at `out_date - 1` can never satisfy the
self-heal condition `last >= stock_out`, so each pass re-queried them forever
(2026-10-27 实测空转趟 153 次请求中 129 次来自 43 只这类股票;指数末日重探再占 24 次).
The fix: any K-line fetch that yields zero new rows is recorded in
`daily_probe_memo` (scope "zero_new") and not re-queried until the next day.

Fixture pattern follows test_dead_stock_skip.py: `object.__new__` bypasses the
live baostock login; query_with_retry / save_df / get_last_downloaded are
mocked; the real `daily_probe_memo` table is created via DBManager.init_all_tables.
"""

import logging

from src.db_manager import DBManager
from src.downloaders.kline_downloader import KlineDownloader
from src.downloaders.index_downloader import IndexDownloader
import src.downloaders.kline_downloader as kline_mod
import src.downloaders.index_downloader as index_mod


FIELDS = "date,code,open"


def _make_dl(cls, tmp_path):
    dl = object.__new__(cls)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_zero_new_probe_memo")
    dl.new_rows = 0
    DBManager(str(dl.db_path)).init_all_tables()
    return dl


class _Rs:
    def __init__(self, code):
        self.code = code


def _run_kline(dl, monkeypatch, *, rows_by_code=None, last=None, end_date="2026-10-26"):
    rows_by_code = rows_by_code or {}
    last = last or {}
    queries = []

    def fake_query(func, **kwargs):
        queries.append(kwargs["code"])
        return _Rs(kwargs["code"])

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(dl, "save_df", lambda df, table, if_exists="append": None)
    monkeypatch.setattr(
        dl, "get_last_downloaded",
        lambda table, code, adjustflag=None: last.get(code),
    )
    monkeypatch.setattr(kline_mod, "fetch_all_rows",
                        lambda rs: rows_by_code.get(rs.code, []))
    monkeypatch.setattr(kline_mod, "get_batch_size", lambda: 100)
    monkeypatch.setattr(kline_mod, "get_batch_sleep", lambda: 0)

    dl._download_kline_batch(
        ["A"], "1990-12-19", end_date, "d", FIELDS, "all_stock_daily", 3, None,
        ipo_dates={"A": (None, "2025-07-25")},
    )
    return queries


def _run_index(dl, monkeypatch, *, rows_by_code=None, last=None):
    rows_by_code = rows_by_code or {}
    last = last or {}
    queries = []

    def fake_query(func, **kwargs):
        queries.append(kwargs["code"])
        return _Rs(kwargs["code"])

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(dl, "save_df", lambda df, table, if_exists="append": None)
    monkeypatch.setattr(
        dl, "get_last_downloaded",
        lambda table, code, adjustflag=None: last.get(code),
    )
    monkeypatch.setattr(index_mod, "fetch_all_rows",
                        lambda rs: rows_by_code.get(rs.code, []))
    monkeypatch.setattr(index_mod, "get_batch_sleep", lambda: 0)

    dl.download_index_daily(["sh.000001"], "2006-01-01", "2026-10-26")
    return queries


def test_zero_new_kline_probe_happens_once_per_day(monkeypatch, tmp_path):
    """退市股末日重探(0 新增)当日只发生一次,第二趟 0 请求。"""
    dl = _make_dl(KlineDownloader, tmp_path)
    rows = {"A": [["2025-07-24", "A", "1"]]}  # 只回灌最后一天,0 新增
    last = {"A": "2025-07-24"}                # 库内 max = out_date 前一日

    q1 = _run_kline(dl, monkeypatch, rows_by_code=rows, last=last)
    assert q1 == ["A"]                       # 第一趟探测
    assert dl.new_rows == 0

    q2 = _run_kline(dl, monkeypatch, rows_by_code=rows, last=last)
    assert q2 == []                          # 同日第二趟不再请求


def test_zero_new_kline_probe_reopens_next_day(monkeypatch, tmp_path):
    """备忘过期(昨日)后恢复探测。"""
    import sqlite3
    from datetime import date, timedelta

    dl = _make_dl(KlineDownloader, tmp_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(str(dl.db_path))
    conn.execute(
        "INSERT INTO daily_probe_memo (scope, item_key, probe_date) VALUES (?, ?, ?)",
        ("zero_new", "all_stock_daily|A|3", yesterday),
    )
    conn.commit()
    conn.close()

    q = _run_kline(
        dl, monkeypatch,
        rows_by_code={"A": [["2025-07-24", "A", "1"]]},
        last={"A": "2025-07-24"},
    )
    assert q == ["A"]


def test_kline_fetch_with_new_rows_not_marked(monkeypatch, tmp_path):
    """返回新增行的查询不落备忘(数据还在增长,下趟继续)。"""
    dl = _make_dl(KlineDownloader, tmp_path)
    rows = {"A": [["2025-07-24", "A", "1"], ["2026-10-26", "A", "2"]]}

    q1 = _run_kline(dl, monkeypatch, rows_by_code=rows, last={"A": "2025-07-24"})
    assert q1 == ["A"]
    assert dl.new_rows == 1

    q2 = _run_kline(dl, monkeypatch, rows_by_code=rows, last={"A": "2025-07-24"})
    assert q2 == ["A"]                       # 未被备忘抑制


def test_zero_new_index_probe_happens_once_per_day(monkeypatch, tmp_path):
    """指数末日重探(0 新增)同样每日一探。"""
    dl = _make_dl(IndexDownloader, tmp_path)
    rows = {"sh.000001": [["2026-10-23", "sh.000001"] + ["1"] * 8]}
    last = {"sh.000001": "2026-10-23"}

    q1 = _run_index(dl, monkeypatch, rows_by_code=rows, last=last)
    assert q1 == ["sh.000001"]
    assert dl.new_rows == 0

    q2 = _run_index(dl, monkeypatch, rows_by_code=rows, last=last)
    assert q2 == []

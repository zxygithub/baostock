"""Unit tests for adjust-factor skip logic in DividendDownloader.download_adjust_factor.

Every stock used to be re-queried on every pass (~5561 API calls each); now a
stock is queried only when its rows were not refreshed today or its known
dividend events are uncovered (the L5 expected-set model).
"""

import logging
from datetime import datetime
from pathlib import Path

from src.downloaders.dividend_downloader import DividendDownloader
import src.downloaders.dividend_downloader as div_mod


ADJUST_DDL = (
    "CREATE TABLE adjust_factor ("
    "code TEXT NOT NULL, divid_operate_date TEXT NOT NULL, "
    "fore_adjust_factor REAL, back_adjust_factor REAL, adjust_factor REAL, "
    "update_time TEXT, PRIMARY KEY (code, divid_operate_date))"
)
DIVIDEND_DDL = (
    "CREATE TABLE dividend ("
    "code TEXT, divid_operate_date TEXT, year INTEGER, year_type TEXT, "
    "PRIMARY KEY (code, divid_operate_date, year, year_type))"
)


class FakeResult:
    fields = ["code", "dividOperateDate", "foreAdjustFactor",
              "backAdjustFactor", "adjustFactor"]

    def __init__(self, code):
        self.code = code


def _make_dl(tmp_path):
    dl = object.__new__(DividendDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_adjust_skip")
    dl.conn.execute(ADJUST_DDL)
    dl.conn.execute(DIVIDEND_DDL)
    dl.conn.commit()
    return dl


def _add_adjust(dl, code, date_, update_time):
    dl.conn.execute(
        "INSERT OR REPLACE INTO adjust_factor VALUES (?,?,?,?,?,?)",
        (code, date_, 1.0, 2.0, 2.0, update_time),
    )
    dl.conn.commit()


def _add_dividend(dl, code, date_, year=2025, year_type="operate"):
    dl.conn.execute(
        "INSERT OR REPLACE INTO dividend VALUES (?,?,?,?)",
        (code, date_, year, year_type),
    )
    dl.conn.commit()


def _run(dl, monkeypatch, rows_by_code, codes):
    queries = []

    def fake_query(func, **kwargs):
        queries.append(kwargs["code"])
        return FakeResult(kwargs["code"])

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(div_mod, "fetch_all_rows",
                        lambda rs: rows_by_code.get(rs.code, []))
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)
    total = dl.download_adjust_factor(codes, start_date="2007-01-01")
    return queries, total


def _today():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_fresh_covered_stock_skipped(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "2020-01-01", _today())
    _add_dividend(dl, "A", "2020-01-01", year=2019)

    queries, total = _run(dl, monkeypatch, {}, codes=["A"])

    assert queries == []
    assert total == 0


def test_stale_stock_requeried_and_refreshed(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "2020-01-01", "2026-09-30 10:00:00")
    rows = [
        ["A", "2020-01-01", 1.0, 2.0, 2.0],
        ["A", "2025-06-30", 1.0, 3.0, 1.5],
    ]

    queries, total = _run(dl, monkeypatch, {"A": rows}, codes=["A"])

    assert queries == ["A"]
    assert total == 2
    stored = dl.conn.execute(
        "SELECT COUNT(*) FROM adjust_factor WHERE code='A'").fetchone()[0]
    assert stored == 2
    max_update = dl.conn.execute(
        "SELECT MAX(update_time) FROM adjust_factor WHERE code='A'").fetchone()[0]
    assert max_update.startswith(datetime.now().strftime("%Y-%m-%d"))


def test_uncovered_dividend_event_forces_requery(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "2020-01-01", _today())
    _add_dividend(dl, "A", "2025-06-30")

    queries, total = _run(
        dl, monkeypatch, {"A": [["A", "2025-06-30", 1.0, 3.0, 1.5]]}, codes=["A"])

    assert queries == ["A"]
    assert total == 1


def test_empty_result_writes_placeholder_then_skips(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)

    queries, total = _run(dl, monkeypatch, {}, codes=["A"])

    assert queries == ["A"]
    assert total == 0
    row = dl.conn.execute(
        "SELECT divid_operate_date, update_time FROM adjust_factor "
        "WHERE code='A'").fetchone()
    assert row[0] == "9999-01-01"
    assert row[1].startswith(datetime.now().strftime("%Y-%m-%d"))

    queries2, _ = _run(dl, monkeypatch, {}, codes=["A"])
    assert queries2 == []


def test_real_rows_remove_placeholder(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "9999-01-01", "2026-09-30 10:00:00")

    queries, total = _run(
        dl, monkeypatch, {"A": [["A", "2025-06-30", 1.0, 3.0, 1.5]]}, codes=["A"])

    assert queries == ["A"]
    assert total == 1
    leftovers = dl.conn.execute(
        "SELECT COUNT(*) FROM adjust_factor "
        "WHERE code='A' AND divid_operate_date='9999-01-01'").fetchone()[0]
    assert leftovers == 0


def test_mixed_batch_only_queries_stale(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "2020-01-01", _today())
    _add_adjust(dl, "B", "2020-01-01", "2026-09-30 10:00:00")

    queries, total = _run(
        dl, monkeypatch, {"B": [["B", "2020-01-01", 1.0, 2.0, 2.0]]},
        codes=["A", "B"])

    assert queries == ["B"]
    assert total == 1


def test_close_after_all_fresh_no_lock(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    _add_adjust(dl, "A", "2020-01-01", _today())

    _run(dl, monkeypatch, {}, codes=["A"])

    dl.close()  # must not raise (WAL checkpoint regression guard)

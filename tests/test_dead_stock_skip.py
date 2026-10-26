"""Unit tests for delisted-stock skip and new-row counting in KlineDownloader.

~340 delisted stocks were re-queried on every pass forever because the old
skip condition `max(date) >= end_date` never became true for them (their data
ends at their delisting date, not the fetch window's end date). The fix adds a
self-healing skip rule: a delisted stock is skipped only when its last
downloaded date already covers its delisting date, and genuinely-new rows are
counted via `count_new_by_date`.

These tests bypass `__init__` (which requires a live baostock login) via
`object.__new__`, and mock query_with_retry / save_df / get_last_downloaded —
the same pattern as test_adjust_factor_skip.py.
"""

import logging

from src.downloaders.kline_downloader import KlineDownloader
import src.downloaders.kline_downloader as kline_mod


FIELDS = "date,code,open"


def _make_dl(tmp_path):
    dl = object.__new__(KlineDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_dead_stock_skip")
    dl.new_rows = 0
    return dl


class _Rs:
    def __init__(self, code):
        self.code = code


def _run(dl, monkeypatch, *, codes, start_date, end_date, ipo_dates, last,
         rows_by_code=None):
    rows_by_code = rows_by_code or {}
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

    total = dl._download_kline_batch(
        codes,
        start_date,
        end_date,
        "d",
        FIELDS,
        "all_stock_daily",
        3,
        None,
        ipo_dates=ipo_dates,
    )
    return queries, total


def test_delisted_and_complete_skips_query(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch,
        codes=["A"],
        start_date="2008-01-01",
        end_date=None,
        ipo_dates={"A": (None, "2009-12-29")},
        last={"A": "2009-12-29"},
    )

    assert queries == []
    assert total == 0
    assert dl._checkpoint_data == {
        "table": "all_stock_daily",
        "adjustflag": 3,
        "last_code": "A",
    }


def test_delisted_with_gap_still_fetches(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch,
        codes=["A"],
        start_date="2020-01-01",
        end_date=None,
        ipo_dates={"A": (None, "2022-06-28")},
        last={"A": "2022-01-31"},
    )

    assert queries == ["A"]


def test_live_stock_fetches(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch,
        codes=["A"],
        start_date="2020-01-01",
        end_date=None,
        ipo_dates={"A": (None, None)},
        last={"A": "2026-10-23"},
    )

    assert queries == ["A"]


def test_out_date_after_end_date_fetches(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch,
        codes=["A"],
        start_date="2020-01-01",
        end_date="2026-01-01",
        ipo_dates={"A": (None, "2026-06-28")},
        last={"A": None},
    )

    assert queries == ["A"]


def test_new_rows_counts_only_rows_after_last(monkeypatch, tmp_path):
    dl = _make_dl(tmp_path)
    rows = [
        ["2026-10-23", "A", "1.0"],
        ["2026-10-26", "A", "2.0"],
    ]
    queries, total = _run(
        dl, monkeypatch,
        codes=["A"],
        start_date="2020-01-01",
        end_date=None,
        ipo_dates={"A": (None, None)},
        last={"A": "2026-10-23"},
        rows_by_code={"A": rows},
    )

    assert queries == ["A"]
    assert dl.new_rows == 1
    assert total == 2

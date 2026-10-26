"""Unit tests for incremental index K-line downloads.

The three `download_index_daily/weekly/monthly` methods used to re-download the
full index history (from the configured start date) on every pass. This change
makes them incremental per (code, frequency): look up the code's last-downloaded
date, skip codes already covered through `end_date`, otherwise re-query from
`max(start_date, last)` and count genuinely-new rows via `count_new_by_date`.

These tests bypass `__init__` (which requires a live baostock login) via
`object.__new__`, and mock query_with_retry / save_df / get_last_downloaded —
the same pattern as test_dead_stock_skip.py.
"""

import logging

import pytest

import src.downloaders.index_downloader as index_mod
from src.downloaders.index_downloader import IndexDownloader
from src.config import INDEX_DAILY_FIELDS, INDEX_WEEKLY_MONTHLY_FIELDS


# method key -> (method name, table, fields, frequency)
METHODS = {
    "daily": ("download_index_daily", "index_daily", INDEX_DAILY_FIELDS, "d"),
    "weekly": ("download_index_weekly", "index_weekly", INDEX_WEEKLY_MONTHLY_FIELDS, "w"),
    "monthly": ("download_index_monthly", "index_monthly", INDEX_WEEKLY_MONTHLY_FIELDS, "m"),
}


def _make_dl(tmp_path):
    dl = object.__new__(IndexDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_index_kline_incremental")
    dl.new_rows = 0
    return dl


class _Rs:
    def __init__(self, code):
        self.code = code


def _row(date, code, ncols):
    return [date, code] + [""] * (ncols - 2)


def _run(dl, monkeypatch, method, *, codes, start_date, end_date, last,
         rows_by_code=None, start_config="2006-01-01"):
    rows_by_code = rows_by_code or {}
    queries = []

    def fake_query(func, **kwargs):
        queries.append(kwargs)
        return _Rs(kwargs["code"])

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(dl, "save_df", lambda df, table, if_exists="append": None)
    monkeypatch.setattr(
        dl, "get_last_downloaded",
        lambda table, code, date_column="date", adjustflag=None: last.get(code),
    )
    monkeypatch.setattr(index_mod, "fetch_all_rows",
                        lambda rs: rows_by_code.get(rs.code, []))
    monkeypatch.setattr(index_mod, "get_batch_sleep", lambda: 0)
    monkeypatch.setattr(index_mod, "get_index_kline_start_date",
                        lambda: start_config)

    method_name, _, _, _ = METHODS[method]
    total = getattr(dl, method_name)(codes, start_date, end_date)
    return queries, total


@pytest.mark.parametrize("method", ["daily", "weekly", "monthly"])
def test_up_to_date_index_skipped(monkeypatch, tmp_path, method):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch, method,
        codes=["A"], start_date="2006-01-01", end_date="2026-10-23",
        last={"A": "2026-10-23"},
    )

    assert queries == []
    assert total == 0


@pytest.mark.parametrize("method", ["daily", "weekly", "monthly"])
def test_incremental_start_from_last(monkeypatch, tmp_path, method):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch, method,
        codes=["A", "B"], start_date="2006-01-01", end_date=None,
        last={"A": "2026-01-15", "B": "2005-01-01"},
    )

    starts = {q["code"]: q["start_date"] for q in queries}
    assert starts["A"] == "2026-01-15"  # last > config start -> from last
    assert starts["B"] == "2006-01-01"  # last < config start -> config start


@pytest.mark.parametrize("method", ["daily", "weekly", "monthly"])
def test_first_time_full_range(monkeypatch, tmp_path, method):
    dl = _make_dl(tmp_path)
    queries, total = _run(
        dl, monkeypatch, method,
        codes=["A"], start_date=None, end_date=None,
        last={"A": None}, start_config="2006-01-01",
    )

    assert queries[0]["start_date"] == "2006-01-01"


@pytest.mark.parametrize("method", ["daily", "weekly", "monthly"])
def test_new_rows_counts_after_last(monkeypatch, tmp_path, method):
    dl = _make_dl(tmp_path)
    ncols = len(METHODS[method][2].split(","))
    rows = [_row("2026-10-23", "A", ncols), _row("2026-10-26", "A", ncols)]
    queries, total = _run(
        dl, monkeypatch, method,
        codes=["A"], start_date="2006-01-01", end_date=None,
        last={"A": "2026-10-23"}, rows_by_code={"A": rows},
    )

    assert dl.new_rows == 1
    assert total == 2

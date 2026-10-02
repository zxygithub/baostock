"""Unit tests for dividend task detection in DividendDownloader.

Bug B regression suite: recent-window combos must be re-probed (they were
permanently skipped after the SQL refactor), placeholder-only combos must be
healed periodically (empty responses can be bogus), and the probe must be
bounded to once per day per combo.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.downloaders.dividend_downloader import DividendDownloader
import src.downloaders.dividend_downloader as div_mod


DIVIDEND_DDL = (
    "CREATE TABLE dividend ("
    "code TEXT NOT NULL, divid_operate_date TEXT NOT NULL, "
    "year INTEGER, year_type TEXT, update_time TEXT, "
    "PRIMARY KEY (code, divid_operate_date, year, year_type))"
)

CUR = datetime.now().year
TODAY = datetime.now().strftime("%Y-%m-%d")


def _make_dl(tmp_path):
    dl = object.__new__(DividendDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_dividend_refresh")
    dl.conn.execute(DIVIDEND_DDL)
    dl.conn.commit()
    return dl


def _seed(dl, code, year, year_type, rows):
    """rows: list of (divid_operate_date, update_time)."""
    for date_, update_time in rows:
        dl.conn.execute(
            "INSERT OR REPLACE INTO dividend VALUES (?,?,?,?,?)",
            (code, date_, year, year_type, update_time),
        )
    dl.conn.commit()


def _tasks(dl, candidates, recent_years=None):
    result = dl._find_missing_dividend(
        candidates, recent_years if recent_years is not None else {CUR, CUR - 1})
    return sorted(result["tasks"])


def test_window_missing_combo_is_task_not_skipped(tmp_path):
    dl = _make_dl(tmp_path)

    assert _tasks(dl, [("A", CUR, "operate")]) == [("A", CUR, "operate")]
    assert _tasks(dl, [("A", CUR, "report")]) == [("A", CUR, "report")]


def test_window_operate_probed_once_per_day(tmp_path):
    dl = _make_dl(tmp_path)
    _seed(dl, "A", CUR, "operate", [("2020-01-01", f"{TODAY} 05:00:00")])

    assert _tasks(dl, [("A", CUR, "operate")]) == []

    _seed(dl, "A", CUR, "operate", [("2020-01-01", "2020-01-01 00:00:00")])
    assert _tasks(dl, [("A", CUR, "operate")]) == [("A", CUR, "operate")]


def test_window_report_present_not_probed(tmp_path):
    dl = _make_dl(tmp_path)
    _seed(dl, "A", CUR, "report", [("2020-01-01", "2020-01-01 00:00:00")])

    assert _tasks(dl, [("A", CUR, "report")]) == []


def test_old_year_rules_unchanged(tmp_path):
    dl = _make_dl(tmp_path)
    _seed(dl, "C", 2020, "report", [("9999-01-01", f"{TODAY} 05:00:00")])

    assert _tasks(dl, [("B", 2020, "report")]) == [("B", 2020, "report")]
    assert _tasks(dl, [("C", 2020, "report")]) == []


def test_placeholder_healed_after_30_days(tmp_path):
    dl = _make_dl(tmp_path)
    stale = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    _seed(dl, "D", 2020, "operate", [("9999-01-01", stale)])

    assert _tasks(dl, [("D", 2020, "operate")]) == [("D", 2020, "operate")]

    _seed(dl, "D", 2020, "operate", [("9999-01-01", f"{TODAY} 05:00:00")])
    assert _tasks(dl, [("D", 2020, "operate")]) == []


def test_placeholder_with_real_rows_not_healed(tmp_path):
    dl = _make_dl(tmp_path)
    stale = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    _seed(dl, "E", 2020, "operate",
          [("9999-01-01", stale), ("2020-05-06", stale)])

    assert _tasks(dl, [("E", 2020, "operate")]) == []


def test_heal_batch_is_capped(tmp_path):
    dl = _make_dl(tmp_path)
    stale = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    candidates = []
    for i in range(1500):
        code = f"sh.{i:06d}"
        _seed(dl, code, 2020, "operate", [("9999-01-01", stale)])
        candidates.append((code, 2020, "operate"))

    result = dl._find_missing_dividend(candidates, {CUR, CUR - 1})

    assert len(result["tasks"]) == 1000


def test_download_dividend_writes_placeholder_then_skips(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    monkeypatch.setattr(dl, "get_stock_years",
                        lambda codes, s, e: {c: (2007, 2026) for c in codes})
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)
    queries = []

    def fake_query(func, **kwargs):
        queries.append((kwargs["code"], kwargs["year"], kwargs["yearType"]))
        return object()

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(div_mod, "fetch_all_rows", lambda rs: [])

    dl.download_dividend(["A"], start_year=CUR, end_year=CUR)
    assert len(queries) == 2
    placeholders = dl.conn.execute(
        "SELECT COUNT(*) FROM dividend WHERE code='A' AND divid_operate_date='9999-01-01'"
    ).fetchone()[0]
    assert placeholders == 2

    queries.clear()
    dl.download_dividend(["A"], start_year=CUR, end_year=CUR)
    assert queries == []


def test_real_rows_remove_combo_placeholder(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    _seed(dl, "A", CUR, "operate",
          [("9999-01-01", (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"))])
    monkeypatch.setattr(dl, "get_stock_years",
                        lambda codes, s, e: {c: (2007, 2026) for c in codes})
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)

    class FakeRs:
        fields = ["code", "dividOperateDate"]

    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kw: FakeRs())
    monkeypatch.setattr(div_mod, "fetch_all_rows",
                        lambda rs: [["A", "2020-05-06"]])

    dl.download_dividend(["A"], start_year=CUR - 1, end_year=CUR)

    leftovers = dl.conn.execute(
        "SELECT COUNT(*) FROM dividend WHERE code='A' AND divid_operate_date='9999-01-01'"
    ).fetchone()[0]
    assert leftovers == 0


def test_close_after_all_skipped_no_lock(tmp_path):
    dl = _make_dl(tmp_path)
    _seed(dl, "A", 2020, "report", [("2020-01-01", f"{TODAY} 05:00:00")])

    result = dl._find_missing_dividend([("A", 2020, "report")], {CUR, CUR - 1})
    assert result["tasks"] == []

    dl.close()

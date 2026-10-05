"""Regression tests: full-year trade calendar + future-day filtering.

`download_trade_dates()` used to call `bs.query_trade_dates` with
`end_date=None`, which the BaoStock client resolves to *today*. The exchange
publishes the full-year schedule at the beginning of the year, so the rest of
the year was never fetched.

After the fix the downloader fetches through Dec 31 of the current year, which
puts *future* trading days into `trade_dates`. Consumers that compute expected
data volume must only count trading days <= today, otherwise they inflate
expectations and report false gaps.
"""

import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_data_integrity as cdi
import daily_report as dr
import estimate_data_volume as edv
import src.downloaders.meta_downloader as meta_mod
from src.downloaders.meta_downloader import MetaDownloader

# Past trading days are always historical; future days are far ahead of any
# "today" so the assertions are stable regardless of when tests run.
PAST_TRADING_DAYS = ["2020-01-02", "2020-01-03"]
FUTURE_TRADING_DAYS = ["2099-01-06", "2099-01-07"]

TRADE_DATES_DDL = (
    "CREATE TABLE trade_dates ("
    "calendar_date TEXT PRIMARY KEY, is_trading_day INTEGER NOT NULL)"
)
STOCK_BASIC_DDL = (
    "CREATE TABLE stock_basic ("
    "code TEXT PRIMARY KEY, code_name TEXT, ipo_date TEXT, "
    "out_date TEXT, type INTEGER, status INTEGER)"
)


def _seed_calendar(conn: sqlite3.Connection) -> None:
    conn.execute(TRADE_DATES_DDL)
    for d in PAST_TRADING_DAYS:
        conn.execute("INSERT INTO trade_dates VALUES (?, 1)", (d,))
    conn.execute("INSERT INTO trade_dates VALUES (?, 0)", ("2020-01-04",))
    for d in FUTURE_TRADING_DAYS:
        conn.execute("INSERT INTO trade_dates VALUES (?, 1)", (d,))
    conn.commit()


def _seed_stock(conn: sqlite3.Connection) -> None:
    conn.execute(STOCK_BASIC_DDL)
    conn.execute(
        "INSERT INTO stock_basic VALUES ('sh.600000', 'X', '2020-01-01', NULL, 1, 1)"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# MetaDownloader.download_trade_dates default range
# ---------------------------------------------------------------------------
class _FakeResult:
    pass


def _make_meta(tmp_path) -> MetaDownloader:
    dl = object.__new__(MetaDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_trade_dates_full_year")
    return dl


def _capture_api_call(monkeypatch, dl):
    captured = {}

    def fake_api_call(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        return _FakeResult()

    monkeypatch.setattr(dl, "_api_call", fake_api_call)
    monkeypatch.setattr(
        meta_mod, "fetch_all_rows", lambda rs: [["2026-01-01", "0"], ["2026-12-31", "1"]]
    )
    saved = {}
    monkeypatch.setattr(
        dl,
        "save_df",
        lambda df, table, if_exists="append": saved.update(table=table, df=df),
    )
    return captured, saved


def test_download_trade_dates_default_end_is_year_end(tmp_path, monkeypatch):
    """end_date omitted -> query through Dec 31 of the current year."""
    dl = _make_meta(tmp_path)
    captured, saved = _capture_api_call(monkeypatch, dl)

    count = dl.download_trade_dates()

    expected_end = f"{date.today().year}-12-31"
    assert captured["args"] == ("1990-01-01", expected_end)
    assert count == 2
    assert saved["table"] == "trade_dates"
    assert list(saved["df"].columns) == ["calendar_date", "is_trading_day"]


def test_download_trade_dates_explicit_end_date_preserved(tmp_path, monkeypatch):
    """Explicit end_date is passed through unchanged."""
    dl = _make_meta(tmp_path)
    captured, _ = _capture_api_call(monkeypatch, dl)

    dl.download_trade_dates(start_date="2026-01-01", end_date="2026-06-30")

    assert captured["args"] == ("2026-01-01", "2026-06-30")


# ---------------------------------------------------------------------------
# Consumers must not count future trading days
# ---------------------------------------------------------------------------
def test_daily_report_estimates_exclude_future_trading_days():
    conn = sqlite3.connect(":memory:")
    _seed_calendar(conn)
    _seed_stock(conn)

    est = dr.get_precise_estimates(conn, {})

    # Only the 2 historical trading days may be counted.
    assert est["all_stock_daily"] == len(PAST_TRADING_DAYS) * 3
    assert est["index_daily"] == 8 * len(PAST_TRADING_DAYS)


def test_estimate_data_volume_excludes_future_trading_days():
    conn = sqlite3.connect(":memory:")
    _seed_calendar(conn)

    days = edv.load_trade_dates(conn)

    assert days == PAST_TRADING_DAYS
    assert edv.estimate_index(days)["index_daily"] == 8 * len(PAST_TRADING_DAYS)


def test_integrity_checker_ignores_future_trading_days(tmp_path):
    """latest_trading_day must be the last *occurred* trading day, not the
    last scheduled one stored in the table."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    _seed_calendar(conn)
    _seed_stock(conn)
    conn.close()

    checker = cdi.DataIntegrityChecker(db)

    assert checker.latest_trading_day == PAST_TRADING_DAYS[-1]


def test_integrity_checker_future_check_date_caps_cutoff(tmp_path):
    """A future --date must not move expected_cutoff past what has traded."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    _seed_calendar(conn)
    _seed_stock(conn)
    conn.close()

    checker = cdi.DataIntegrityChecker(db, check_date="2099-12-31")

    assert checker.expected_cutoff == PAST_TRADING_DAYS[-1]


def test_integrity_checker_future_check_date_expected_days(tmp_path):
    """Expected-day counts must not include not-yet-traded days."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    _seed_calendar(conn)
    _seed_stock(conn)
    conn.close()

    checker = cdi.DataIntegrityChecker(db, check_date="2099-12-31")

    # IPO 2020-01-01, active stock: only historical trading days count.
    assert checker._expected_trading_days("sh.600000") == len(PAST_TRADING_DAYS)

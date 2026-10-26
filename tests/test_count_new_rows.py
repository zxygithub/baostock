"""Unit tests for BaseDownloader new-row counting infrastructure.

count_new_rows: exact count of df rows whose key combination is absent from
the target table (temp-table + LEFT JOIN, like _find_missing_quarters).
count_new_by_date: shared "strictly greater than last date" rule for K-line
and index incremental fetch (pre-flight ruling R1).
"""

import logging

import pandas as pd

from src.downloaders.base import BaseDownloader


K_DATA_DDL = (
    "CREATE TABLE k_data ("
    "code TEXT NOT NULL, date TEXT NOT NULL, open TEXT, "
    "PRIMARY KEY (code, date))"
)


def _make_dl(tmp_path):
    dl = object.__new__(BaseDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_count_new_rows")
    dl.new_rows = 0
    dl.conn.execute(K_DATA_DDL)
    dl.conn.commit()
    return dl


def _df(rows):
    return pd.DataFrame(rows, columns=["code", "date", "open"])


def _add(dl, code, date):
    dl.conn.execute(
        "INSERT INTO k_data (code, date) VALUES (?, ?)", (code, date))
    dl.conn.commit()


def test_all_rows_missing_counts_all(tmp_path):
    dl = _make_dl(tmp_path)
    df = _df([["A", "2020-01-01", "1"], ["A", "2020-01-02", "2"]])

    assert dl.count_new_rows(df, "k_data", ["code", "date"]) == 2


def test_existing_rows_count_zero(tmp_path):
    dl = _make_dl(tmp_path)
    _add(dl, "A", "2020-01-01")
    _add(dl, "A", "2020-01-02")
    df = _df([["A", "2020-01-01", "1"], ["A", "2020-01-02", "2"]])

    assert dl.count_new_rows(df, "k_data", ["code", "date"]) == 0


def test_partial_overlap_counts_only_missing(tmp_path):
    dl = _make_dl(tmp_path)
    _add(dl, "A", "2020-01-01")
    df = _df([["A", "2020-01-01", "1"], ["A", "2020-01-02", "2"]])

    assert dl.count_new_rows(df, "k_data", ["code", "date"]) == 1


def test_placeholder_rows_not_counted(tmp_path):
    dl = _make_dl(tmp_path)
    placeholder = _df([["A", "9999-01-01", None]])

    assert dl.count_new_rows(placeholder, "k_data", ["code", "date"]) == 0

    # 占位行混入真实行时同样不计，真实行照常计数
    mixed = _df([["A", "9999-01-01", None], ["A", "2020-01-01", "1"]])
    assert dl.count_new_rows(mixed, "k_data", ["code", "date"]) == 1


def test_empty_df_returns_zero(tmp_path):
    dl = _make_dl(tmp_path)

    assert dl.count_new_rows(_df([]), "k_data", ["code", "date"]) == 0
    assert dl.new_rows == 0


def test_close_after_count_no_lock(tmp_path):
    dl = _make_dl(tmp_path)
    _add(dl, "A", "2020-01-01")
    df = _df([["A", "2020-01-01", "1"]])

    dl.count_new_rows(df, "k_data", ["code", "date"])

    # rollback 必须关闭 executemany 遗留的隐式事务（wal_checkpoint 锁库地雷）
    assert not dl.conn.in_transaction
    dl.close()  # must not raise (WAL checkpoint regression guard)


def test_count_new_by_date_none_counts_all(tmp_path):
    dl = _make_dl(tmp_path)
    rows = [["A", "2020-01-01"], ["A", "2020-01-02"]]

    assert dl.count_new_by_date(rows, date_idx=1, last=None) == 2


def test_count_new_by_date_strictly_greater_only(tmp_path):
    dl = _make_dl(tmp_path)
    rows = [["A", "2020-01-01"], ["A", "2020-01-02"], ["A", "2020-01-03"]]

    assert dl.count_new_by_date(rows, date_idx=1, last="2020-01-01") == 2
    assert dl.count_new_by_date(rows, date_idx=1, last="2020-01-03") == 0
    assert dl.count_new_by_date(rows, date_idx=1, last="2020-01-05") == 0
    assert dl.count_new_by_date([], date_idx=1, last="2020-01-01") == 0

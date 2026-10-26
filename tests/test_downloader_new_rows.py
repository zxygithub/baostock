"""Unit tests for precise new-row counting at report/dividend/adjust-factor save sites.

Task 6: each real-row save site accumulates self.new_rows via
BaseDownloader.count_new_rows (Task 1). Placeholder dfs ('9999-01-01'
report-empty placeholders, dividend placeholder batches, the
_mark_adjust_checked probe marker) are constructed separately and must never
be counted. Counting runs BEFORE save_df so the count reflects pre-save
state (counting after the upsert would see the rows as already existing).

Downloaders are built via object.__new__ (no live baostock login), matching
tests/test_count_new_rows.py.
"""

import logging
from datetime import datetime

import baostock as bs

from src.db_manager import DBManager
from src.downloaders.report_downloader import ReportDownloader
from src.downloaders.dividend_downloader import DividendDownloader
import src.downloaders.report_downloader as rep_mod
import src.downloaders.dividend_downloader as div_mod


PE_FIELDS = ["code", "performanceExpPubDate"]
FC_FIELDS = ["code", "profitForcastExpPubDate"]
AF_FIELDS = ["code", "dividOperateDate", "foreAdjustFactor",
             "backAdjustFactor", "adjustFactor"]
DIV_FIELDS = ["code", "dividOperateDate"]

CUR = datetime.now().year


def _make_dl(cls, name, tmp_path):
    db_path = tmp_path / f"{name}.db"
    db = DBManager(str(db_path))
    db.init_all_tables()
    db.close()

    dl = object.__new__(cls)
    dl.db_path = db_path
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger(name)
    dl.new_rows = 0
    return dl


class _FakeRs:
    def __init__(self, fields, tag=None):
        self.fields = fields
        self.tag = tag


def _patch_report(dl, monkeypatch, rows_by_fields):
    def fake_query(func, **kwargs):
        fields = (PE_FIELDS if func is bs.query_performance_express_report
                  else FC_FIELDS)
        return _FakeRs(fields)

    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(
        rep_mod, "fetch_all_rows",
        lambda rs: rows_by_fields.get(tuple(rs.fields), []))
    monkeypatch.setattr(rep_mod, "get_batch_sleep", lambda: 0)


def test_report_refetch_of_existing_rows_counts_zero(tmp_path, monkeypatch):
    """7 天窗口复拉存量行 → new_rows 为 0；同一趟里的新披露日照常计数。"""
    dl = _make_dl(ReportDownloader, "report_new_rows", tmp_path)
    # update_time 老于 7 天 → 不被窗口跳过，允许复拉
    dl.conn.execute(
        "INSERT INTO performance_express "
        "(code, performance_exp_pub_date, update_time) VALUES (?,?,?)",
        ("sh.600000", "2024-01-01", "2020-01-01 00:00:00"))
    dl.conn.execute(
        "INSERT INTO forecast_report "
        "(code, profit_forecast_exp_pub_date, update_time) VALUES (?,?,?)",
        ("sh.600000", "2024-01-01", "2020-01-01 00:00:00"))
    dl.conn.commit()

    _patch_report(dl, monkeypatch, {
        tuple(PE_FIELDS): [["sh.600000", "2024-01-01"]],
        tuple(FC_FIELDS): [["sh.600000", "2024-01-01"]],
    })

    total_pe = dl.download_performance_express(["sh.600000"], start_date="2020-01-01")
    total_fc = dl.download_forecast_report(["sh.600000"], start_date="2020-01-01")

    assert total_pe == 1
    assert total_fc == 1
    assert dl.new_rows == 0  # 复拉存量行不产生新增计数

    # 同一套接口：新 code 的新披露日必须被精确计数（两表各 1 行）
    rows = {
        tuple(PE_FIELDS): [["sh.600001", "2025-01-01"]],
        tuple(FC_FIELDS): [["sh.600001", "2025-01-01"]],
    }
    _patch_report(dl, monkeypatch, rows)
    dl.download_performance_express(["sh.600001"], start_date="2020-01-01")
    dl.download_forecast_report(["sh.600001"], start_date="2020-01-01")
    assert dl.new_rows == 2


def test_placeholder_rows_not_counted(tmp_path, monkeypatch):
    """Review Focus 2：占位 df 写入后 new_rows 仍为 0（报表/分红/复权三处占位路径）。"""
    dl = _make_dl(ReportDownloader, "report_placeholder", tmp_path)
    _patch_report(dl, monkeypatch, {})  # 空结果 → 写 '9999-01-01' 占位

    dl.download_performance_express(["sh.600000"], start_date="2020-01-01")
    dl.download_forecast_report(["sh.600000"], start_date="2020-01-01")
    assert dl.new_rows == 0
    placeholders = dl.conn.execute(
        "SELECT COUNT(*) FROM performance_express WHERE performance_exp_pub_date='9999-01-01'"
    ).fetchone()[0]
    assert placeholders == 1  # 占位确实写库了，只是不计数

    div = _make_dl(DividendDownloader, "div_placeholder", tmp_path)
    monkeypatch.setattr(div, "get_stock_years",
                        lambda codes, s, e: {c: (2007, CUR) for c in codes})
    monkeypatch.setattr(div, "query_with_retry", lambda func, **kw: _FakeRs(DIV_FIELDS))
    monkeypatch.setattr(div_mod, "fetch_all_rows", lambda rs: [])
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)

    div.download_dividend(["A"], start_year=CUR, end_year=CUR)
    assert div.new_rows == 0
    placeholders = div.conn.execute(
        "SELECT COUNT(*) FROM dividend WHERE divid_operate_date='9999-01-01'"
    ).fetchone()[0]
    assert placeholders == 2  # report + operate 两个占位批次都写库了

    div.download_adjust_factor(["A"], start_date="2007-01-01")  # 空结果 → _mark_adjust_checked
    assert div.new_rows == 0
    marker = div.conn.execute(
        "SELECT COUNT(*) FROM adjust_factor WHERE divid_operate_date='9999-01-01'"
    ).fetchone()[0]
    assert marker == 1


def test_dividend_new_rows_counted(tmp_path, monkeypatch):
    """新 (code, divid_operate_date, year, year_type) → new_rows 为 1。

    (A, CUR, operate) 是 recent-year 复拉任务：库中已有 2020-05-06，接口返回
    2020-05-06（存量，不计）+ 2021-06-30（新增，计 1）。(A, CUR, report)
    空结果走占位批次，不计。
    """
    dl = _make_dl(DividendDownloader, "div_new_rows", tmp_path)
    dl.conn.execute(
        "INSERT INTO dividend (code, divid_operate_date, year, year_type, update_time) "
        "VALUES (?,?,?,?,?)",
        ("A", "2020-05-06", CUR, "operate", "2020-01-01 00:00:00"))
    dl.conn.commit()

    monkeypatch.setattr(dl, "get_stock_years",
                        lambda codes, s, e: {c: (2007, CUR) for c in codes})

    def fake_query(func, **kwargs):
        return _FakeRs(DIV_FIELDS, tag=kwargs["yearType"])

    rows_by_type = {
        "operate": [["A", "2020-05-06"], ["A", "2021-06-30"]],
        "report": [],
    }
    monkeypatch.setattr(dl, "query_with_retry", fake_query)
    monkeypatch.setattr(div_mod, "fetch_all_rows", lambda rs: rows_by_type[rs.tag])
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)

    dl.download_dividend(["A"], start_year=CUR, end_year=CUR)

    assert dl.new_rows == 1


def test_adjust_factor_new_rows_counted(tmp_path, monkeypatch):
    """复权因子复拉：存量 (code, divid_operate_date) 不计，新增除权日计 1。"""
    dl = _make_dl(DividendDownloader, "af_new_rows", tmp_path)
    dl.conn.execute(
        "INSERT INTO adjust_factor VALUES (?,?,?,?,?,?)",
        ("A", "2020-01-01", 1.0, 2.0, 2.0, "2020-01-01 00:00:00"))
    dl.conn.commit()

    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kw: _FakeRs(AF_FIELDS))
    monkeypatch.setattr(div_mod, "fetch_all_rows", lambda rs: [
        ["A", "2020-01-01", 1.0, 2.0, 2.0],
        ["A", "2025-06-30", 1.0, 3.0, 1.5],
    ])
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 0)

    dl.download_adjust_factor(["A"], start_date="2007-01-01")

    assert dl.new_rows == 1

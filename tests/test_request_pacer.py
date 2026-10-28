"""Unit tests for helpers.RequestPacer batch pacing (A1).

Regression suite: per-request ``time.sleep(batch_sleep)`` in the dividend /
adjust-factor / report loops cost ~4.5 h of pure sleeping per night. Pacing
must sleep once per ``requests_per_sleep`` requests instead, matching the
K-line batch pacing.
"""

import logging
import time

from src import config_loader
from src.downloaders.dividend_downloader import DividendDownloader
import src.downloaders.dividend_downloader as div_mod
from src.downloaders.report_downloader import ReportDownloader
import src.downloaders.report_downloader as rep_mod
from src.utils.helpers import RequestPacer


def test_pacer_sleeps_once_per_window():
    sleeps = []
    pacer = RequestPacer(3, 1.5, sleep=sleeps.append)
    for _ in range(7):
        pacer.tick()
    assert sleeps == [1.5, 1.5]  # 第 3、6 次后各睡一次;第 7 次不满窗口不睡


def test_pacer_window_of_one_sleeps_every_tick():
    sleeps = []
    pacer = RequestPacer(1, 2.0, sleep=sleeps.append)
    for _ in range(3):
        pacer.tick()
    assert sleeps == [2.0, 2.0, 2.0]


def test_pacer_non_positive_window_clamps_to_one():
    sleeps = []
    pacer = RequestPacer(0, 1.0, sleep=sleeps.append)
    for _ in range(2):
        pacer.tick()
    assert sleeps == [1.0, 1.0]  # 不得除零,也不得漏睡


def test_pacer_defaults_to_time_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)  # 经 helpers.time 解析,与现有测试同款
    pacer = RequestPacer(2, 0.5)
    for _ in range(2):
        pacer.tick()
    assert sleeps == [0.5]


def test_batch_sleep_default_matches_config_yaml(monkeypatch):
    """缺省值须与 config.yaml 显式值一致(batch_sleep: 1),否则限速窗口静默变慢。"""
    monkeypatch.setattr(config_loader, "get_stocks_config", lambda: {})
    assert config_loader.get_batch_sleep() == 1


# ── 集成:分红循环按批限速,而非逐请求休眠 ──────────────────────────────

DIVIDEND_DDL = (
    "CREATE TABLE dividend ("
    "code TEXT NOT NULL, divid_operate_date TEXT NOT NULL, "
    "year INTEGER, year_type TEXT, update_time TEXT, "
    "PRIMARY KEY (code, divid_operate_date, year, year_type))"
)


def _make_dividend_dl(tmp_path):
    dl = object.__new__(DividendDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_request_pacer")
    dl.new_rows = 0
    dl.conn.execute(DIVIDEND_DDL)
    dl.conn.commit()
    return dl


def test_dividend_loop_paces_per_batch_not_per_request(tmp_path, monkeypatch):
    dl = _make_dividend_dl(tmp_path)
    tasks = [(f"sh.60000{i}", 2026, "operate") for i in range(5)]
    monkeypatch.setattr(
        dl, "get_stock_years", lambda codes, start, end: {}
    )
    monkeypatch.setattr(
        dl, "_find_missing_dividend",
        lambda candidates, recent_years: {"tasks": tasks, "skipped": 0},
    )
    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kwargs: object())
    monkeypatch.setattr(div_mod, "fetch_all_rows", lambda rs: [])
    monkeypatch.setattr(div_mod, "get_batch_size", lambda: 2)
    monkeypatch.setattr(div_mod, "get_batch_sleep", lambda: 1.0)

    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    dl.download_dividend(["sh.600000"], start_year=2026, end_year=2026)

    # 5 次请求、限速窗口 2:仅第 2、4 次后各睡一次;逐请求休眠会是 5 次
    assert sleeps == [1.0, 1.0]


# ── 集成:报表循环按批限速 ──────────────────────────────────────────────

PERF_EXPRESS_DDL = (
    "CREATE TABLE performance_express ("
    "code TEXT NOT NULL, performance_exp_pub_date TEXT NOT NULL, "
    "update_time TEXT, "
    "PRIMARY KEY (code, performance_exp_pub_date))"
)


def test_performance_express_loop_paces_per_batch_not_per_request(tmp_path, monkeypatch):
    dl = object.__new__(ReportDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl._limit_exceeded = True
    dl._interrupted = False
    dl.logger = logging.getLogger("test_request_pacer")
    dl.new_rows = 0
    dl.conn.execute(PERF_EXPRESS_DDL)
    dl.conn.commit()

    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kwargs: object())
    monkeypatch.setattr(rep_mod, "fetch_all_rows", lambda rs: [])
    monkeypatch.setattr(rep_mod, "get_batch_size", lambda: 2)
    monkeypatch.setattr(rep_mod, "get_batch_sleep", lambda: 1.0)

    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    dl.download_performance_express(
        ["sh.600000", "sh.600001", "sh.600002"], start_date="2026-01-01",
    )

    # 3 次请求、限速窗口 2:仅第 2 次后睡一次;逐请求休眠会是 3 次
    assert sleeps == [1.0]

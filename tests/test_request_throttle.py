"""请求频率闸测试(设计方案组件 4,§3.4 不冻结约束)。

契约:_throttle 在每次请求前补足差额(与既有 sleep 取最大值语义,不叠加);
min_request_interval 是 property 每次现读,不得退化成问题 A 的冻结类属性;
K 线空批也必须执行批间睡眠(缺口 G)。
"""

import logging
import time

import pytest

from src import config_loader
from src.downloaders import base as base_mod
from src.downloaders import kline_downloader as kline_mod
from src.downloaders.base import BaseDownloader
from src.downloaders.kline_downloader import KlineDownloader


class FakeRs:
    error_code = "0"
    error_msg = ""
    fields = []
    cur_page_num = 1

    def next(self):
        return False

    def get_row_data(self):
        return []


def _make_dl(tmp_path, cls=BaseDownloader):
    dl = object.__new__(cls)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl.logger = logging.getLogger("test_request_throttle")
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl._blacklisted = False
    dl.new_rows = 0
    dl._last_request_ts = 0.0
    return dl


def test_min_interval_enforced_between_requests(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    monkeypatch.setattr(base_mod, "get_min_request_interval", lambda: 0.3)
    sleeps = []
    monkeypatch.setattr(base_mod.time, "sleep", sleeps.append)
    dl._last_request_ts = time.time() - 0.1  # 距上次请求 0.1s

    dl._throttle()

    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 0.25  # 只补足差额(~0.2s),不是整段 0.3s


def test_no_double_sleep_when_existing_sleep_longer(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    monkeypatch.setattr(base_mod, "get_min_request_interval", lambda: 0.3)
    sleeps = []
    monkeypatch.setattr(base_mod.time, "sleep", sleeps.append)
    dl._last_request_ts = time.time() - 1.0  # 既有节流(Pacer/批间 sleep)已更慢

    dl._throttle()

    assert sleeps == []  # 取最大值语义:不叠加等待


def test_non_positive_interval_disables(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    monkeypatch.setattr(base_mod, "get_min_request_interval", lambda: 0)
    sleeps = []
    monkeypatch.setattr(base_mod.time, "sleep", sleeps.append)
    dl._last_request_ts = time.time()

    dl._throttle()

    assert sleeps == []  # <=0 视为禁用


def test_query_with_retry_throttles_before_request(tmp_path, monkeypatch):
    """接线契约:_throttle 必须在真正发请求之前被调用,否则闸门是死代码。"""
    dl = _make_dl(tmp_path)
    order = []
    monkeypatch.setattr(dl, "_throttle", lambda: order.append("throttle"))
    monkeypatch.setattr(dl, "ensure_login", lambda: None)
    monkeypatch.setattr(dl, "_increment_request_count", lambda: None)
    monkeypatch.setattr(dl, "_check_limit_after_increment", lambda: None)

    def fake_query(**kwargs):
        order.append("request")
        return FakeRs()

    dl.query_with_retry(fake_query, code="sh.600000")
    assert order[0] == "throttle"
    assert order[-1] == "request"


def test_kline_empty_batch_still_sleeps(tmp_path, monkeypatch):
    """缺口 G 回归:空批跳过批间睡眠 → 200 个重查询背靠背发出。"""
    dl = _make_dl(tmp_path, KlineDownloader)
    dl._checkpoint_data = {}
    monkeypatch.setattr(kline_mod, "get_batch_size", lambda: 2)
    monkeypatch.setattr(kline_mod, "get_batch_sleep", lambda: 0.5)
    monkeypatch.setattr(kline_mod, "fetch_all_rows", lambda rs: [])
    monkeypatch.setattr(dl, "query_with_retry", lambda func, **kwargs: FakeRs())
    monkeypatch.setattr(dl, "get_last_downloaded", lambda *a, **k: None)
    monkeypatch.setattr(dl, "count_new_by_date", lambda *a, **k: 0)
    monkeypatch.setattr(dl, "is_probed_today", lambda *a, **k: False)
    monkeypatch.setattr(dl, "mark_probed", lambda *a, **k: None)
    sleeps = []
    monkeypatch.setattr(kline_mod.time, "sleep", sleeps.append)

    dl._download_kline_batch(
        codes=["sh.600000", "sh.600001"],
        start_date="2026-01-01",
        end_date="2026-10-27",
        frequency="d",
        fields="date,code,close",
        table="all_stock_daily",
    )

    assert sleeps == [0.5]  # 一批全空也必须睡批间间隔


def test_min_request_interval_is_property_not_frozen(tmp_path, monkeypatch):
    """§3.4:不得复制问题 A 的冻结反模式(类属性/模块级常量)。"""
    dl = _make_dl(tmp_path)

    assert isinstance(BaseDownloader.__dict__["min_request_interval"], property)
    monkeypatch.setattr(
        config_loader, "_config_cache", {"api": {"min_request_interval": 0.5}}
    )
    assert dl.min_request_interval == 0.5  # 配置变化即反映,无需改类属性

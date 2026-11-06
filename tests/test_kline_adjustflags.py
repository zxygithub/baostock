"""Unit tests for K-line adjustflags config reading (fail-fast).

功能来源：社区 PR #1 (gitee superman75/baostock) —— K线复权类型支持通过配置文件自定义。
本文件覆盖 config_loader.get_kline_adjustflags 与 KlineDownloader 下载循环两层。

Breaks under test:
- daily/weekly/monthly 默认 [1, 2, 3]、minute 默认 [3](与重构前硬编码行为一致)
- config.yaml 自定义 adjustflags 不被忽略
- 非法配置(空列表/None/非列表/越界值/未知频率)必须 fail-fast 报错并指明配置键,
  而不是静默跳过下载(空列表循环 0 次"成功")或烧配额后才在 API 层失败
- 下载循环按配置的复权类型逐一执行(而非硬编码 [1, 2, 3])
"""

import logging

import pytest

import src.config_loader as config_loader
from src.config_loader import get_kline_adjustflags
from src.downloaders.kline_downloader import KlineDownloader


@pytest.fixture
def download_config(monkeypatch):
    """Replace the config source with an in-memory dict (real helpers read it)."""

    def _set(cfg):
        monkeypatch.setattr(config_loader, "get_download_config", lambda: cfg)

    return _set


# ---------------------------------------------------------------------------
# get_kline_adjustflags: defaults
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly"])
def test_default_adjustflags_matches_legacy_hardcoded_loop(download_config, freq):
    """无配置时返回 [1, 2, 3] —— 与重构前硬编码循环行为一致(向后兼容)。"""
    download_config({})
    assert get_kline_adjustflags(freq) == [1, 2, 3]


def test_default_minute_adjustflags_is_no_adjust_only(download_config):
    """minute 默认 [3](BaoStock 分钟线仅支持不复权)。"""
    download_config({})
    assert get_kline_adjustflags("minute") == [3]


# ---------------------------------------------------------------------------
# get_kline_adjustflags: config read
# ---------------------------------------------------------------------------

def test_custom_adjustflags_read_from_config(download_config):
    download_config({"kline": {"daily": {"adjustflags": [3]}}})
    assert get_kline_adjustflags("daily") == [3]


# ---------------------------------------------------------------------------
# get_kline_adjustflags: fail-fast validation
# ---------------------------------------------------------------------------

def test_empty_list_rejected_naming_the_key(download_config):
    """空列表会让下载循环执行 0 次并"成功"退出——必须报错而不是静默跳过。"""
    download_config({"kline": {"daily": {"adjustflags": []}}})
    with pytest.raises(ValueError, match=r"kline\.daily\.adjustflags"):
        get_kline_adjustflags("daily")


def test_null_value_rejected(download_config):
    """YAML `adjustflags:`(空值→None)不可迭代会 TypeError——应给出指明配置键的报错。"""
    download_config({"kline": {"weekly": {"adjustflags": None}}})
    with pytest.raises(ValueError, match=r"kline\.weekly\.adjustflags"):
        get_kline_adjustflags("weekly")


def test_non_list_rejected(download_config):
    download_config({"kline": {"monthly": {"adjustflags": 3}}})
    with pytest.raises(ValueError, match=r"kline\.monthly\.adjustflags"):
        get_kline_adjustflags("monthly")


def test_out_of_range_value_rejected(download_config):
    """[1, 2, 4] 会被送往 API 烧掉配额重试后才失败——必须在配置层拦截。"""
    download_config({"kline": {"daily": {"adjustflags": [1, 2, 4]}}})
    with pytest.raises(ValueError, match=r"kline\.daily\.adjustflags"):
        get_kline_adjustflags("daily")


def test_boolean_value_rejected(download_config):
    """bool 是 int 子类，[True] 不应被当作 adjustflag=1 放行。"""
    download_config({"kline": {"daily": {"adjustflags": [True]}}})
    with pytest.raises(ValueError, match=r"kline\.daily\.adjustflags"):
        get_kline_adjustflags("daily")


def test_unknown_frequency_rejected(download_config):
    download_config({})
    with pytest.raises(ValueError, match="hourly"):
        get_kline_adjustflags("hourly")


# ---------------------------------------------------------------------------
# KlineDownloader loops consume the config
# ---------------------------------------------------------------------------

def _make_dl(monkeypatch):
    """Build a KlineDownloader without login (pattern: test_zero_new_probe_memo)."""
    dl = object.__new__(KlineDownloader)
    dl.logger = logging.getLogger("test_kline_adjustflags")
    dl._interrupted = False
    dl.new_rows = 0
    calls = []
    monkeypatch.setattr(dl, "get_stock_ipo_dates", lambda: {})
    monkeypatch.setattr(dl, "_get_resume_code", lambda *a, **k: None)
    monkeypatch.setattr(
        dl,
        "_download_kline_batch",
        lambda codes, start, end, ktype, fields, table, adjustflag, resume,
        ipo_dates=None: calls.append(adjustflag) or 0,
    )
    return dl, calls


_LOOP_CASES = [
    ("download_daily_kline", "daily"),
    ("download_weekly_kline", "weekly"),
    ("download_monthly_kline", "monthly"),
]


@pytest.mark.parametrize("method_name,freq", _LOOP_CASES)
def test_download_loop_uses_configured_adjustflags(
    monkeypatch, download_config, method_name, freq
):
    """下载循环按配置的复权类型执行，而非硬编码 [1, 2, 3]。"""
    download_config({"kline": {freq: {"adjustflags": [3]}}})
    dl, calls = _make_dl(monkeypatch)
    getattr(dl, method_name)(["sh.600000"], start_date="2026-01-01", end_date="2026-02-01")
    assert calls == [3]


@pytest.mark.parametrize("method_name,freq", _LOOP_CASES)
def test_download_loop_defaults_to_all_adjustflags(
    monkeypatch, download_config, method_name, freq
):
    download_config({})
    dl, calls = _make_dl(monkeypatch)
    getattr(dl, method_name)(["sh.600000"], start_date="2026-01-01", end_date="2026-02-01")
    assert calls == [1, 2, 3]

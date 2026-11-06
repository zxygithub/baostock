"""Unit tests for scripts/download_all.py — per-module download switches.

功能来源：社区 PR #1 (gitee superman75/baostock) —— 全量拉取脚本支持按模块开关下载。
本文件重点覆盖 PR 评审发现的缺陷 2：周/月/分钟线开关被 kline.daily 耦合锁死。

Breaks under test:
- kline.daily 关闭时，周/月线仍须照常下载(Phase 7 不得整体跳过)
- kline.daily/weekly/monthly 全关而 minute 开启时，Phase 8 仍须执行
  (PR 原实现把 Phase 8 嵌在 Phase 7 的 daily 开关之下)
- 每个频率独立门控：关谁谁不跑，其余照跑(正向对照防真空通过)
- 四个频率全关时 KlineDownloader 完全不得构造
- components 开关关闭时 ComponentDownloader 不得构造
- 默认全开行为与开关引入前一致(向后兼容)

日期钉桩(关键)：download_all.main() 在函数内部 `from datetime import datetime`,
故需向 sys.modules 注入替身模块钉住 now()=2026-11-07 03:00 → target=2026-11-06(周五)，
使周线周完整性守卫放行、月线可下上一完整月，各下载方法真正被调用。
"""

import sqlite3
import sys
import types
from datetime import date, datetime, timedelta

import pytest

import scripts.download_all as download_all
import src.config_loader as config_loader


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeDateTime(datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


def _fake_datetime_module():
    mod = types.ModuleType("datetime")
    mod.datetime = _FakeDateTime
    mod.timedelta = timedelta
    mod.date = date
    return mod


class FakeDBManager:
    """Stub DBManager exposing exactly what download_all.main() reads."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def init_all_tables(self):
        pass

    def migrate_schema(self):
        pass

    def get_latest_trading_day_on_or_before(self, date_str):
        return date_str  # every day is a "trading day" in the stub

    def get_max_date(self, table):
        return {
            "all_stock_weekly": "2026-10-23",
            "all_stock_monthly": "2026-09-30",
        }.get(table)

    def get_trading_days_in_range(self, start, end):
        return ["2026-11-02", "2026-11-03", "2026-11-04"]  # 3 days → monthly due


def _make_spy(name, constructed, calls):
    class SpyDownloader:
        def __init__(self, *args, **kwargs):
            constructed.append(name)
            self.new_rows = 0
            self._interrupted = False
            self._checkpoint_data = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __getattr__(self, method):
            def _record(*args, **kwargs):
                calls.append((name, method))
                return {}
            return _record

    return SpyDownloader


# ---------------------------------------------------------------------------
# Fixture: run download_all.main() against spies and a temp stock_basic DB
# ---------------------------------------------------------------------------

@pytest.fixture
def run_download_all(monkeypatch, tmp_path):
    """Returns a runner(config) -> (constructed, calls)."""

    def _run(config):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE stock_basic (code TEXT, type INTEGER)")
        conn.execute("INSERT INTO stock_basic VALUES ('sh.600000', 1)")
        conn.commit()
        conn.close()

        # skip the metadata phase via its real once-per-day marker
        (tmp_path / f".meta_fetched_{date.today():%Y-%m-%d}").touch()

        constructed, calls = [], []
        for cls_name in (
            "MetaDownloader",
            "MacroDownloader",
            "ComponentDownloader",
            "IndexDownloader",
            "KlineDownloader",
            "FinancialDownloader",
            "ReportDownloader",
            "DividendDownloader",
        ):
            monkeypatch.setattr(
                download_all, cls_name, _make_spy(cls_name, constructed, calls)
            )
        monkeypatch.setattr(download_all, "DBManager", FakeDBManager)
        monkeypatch.setattr(download_all, "DB_PATH", db_path)
        monkeypatch.setattr(download_all, "is_past_shutdown_time", lambda: False)
        monkeypatch.setattr(config_loader, "get_download_config", lambda: config)
        monkeypatch.setitem(sys.modules, "datetime", _fake_datetime_module())
        monkeypatch.setattr(sys, "argv", ["download_all.py"])

        _FakeDateTime._now = datetime(2026, 11, 7, 3, 0)  # → target 2026-11-06 (Fri)

        download_all.main()
        return constructed, calls

    return _run


def _called(calls):
    return {method for _, method in calls}


# ---------------------------------------------------------------------------
# Backward compatibility: default config runs everything
# ---------------------------------------------------------------------------

def test_default_config_runs_all_phases(run_download_all):
    constructed, calls = run_download_all({})
    assert "KlineDownloader" in constructed
    call_names = _called(calls)
    for method in (
        "download_daily_kline",
        "download_weekly_kline",
        "download_monthly_kline",
        "download_minute_kline",
    ):
        assert method in call_names, f"expected {method} to run with default config"


# ---------------------------------------------------------------------------
# Defect 2: per-module switches must not be coupled to kline.daily
# ---------------------------------------------------------------------------

def test_daily_disabled_still_runs_weekly_and_monthly(run_download_all):
    """PR 缺陷 2：daily 关闭曾让 Phase 7 整体跳过，周/月线开关不可达。"""
    _, calls = run_download_all({"kline": {"daily": {"enabled": False}}})
    call_names = _called(calls)
    assert "download_daily_kline" not in call_names
    assert "download_weekly_kline" in call_names
    assert "download_monthly_kline" in call_names


def test_weekly_disabled_skips_only_weekly(run_download_all):
    _, calls = run_download_all({"kline": {"weekly": {"enabled": False}}})
    call_names = _called(calls)
    assert "download_weekly_kline" not in call_names
    assert "download_daily_kline" in call_names
    assert "download_monthly_kline" in call_names


def test_monthly_disabled_skips_only_monthly(run_download_all):
    _, calls = run_download_all({"kline": {"monthly": {"enabled": False}}})
    call_names = _called(calls)
    assert "download_monthly_kline" not in call_names
    assert "download_daily_kline" in call_names
    assert "download_weekly_kline" in call_names


def test_all_stock_kline_disabled_minute_still_runs(run_download_all):
    """PR 缺陷 2：Phase 8 曾嵌在 Phase 7 的 daily 开关之下。"""
    config = {
        "kline": {
            "daily": {"enabled": False},
            "weekly": {"enabled": False},
            "monthly": {"enabled": False},
        }
    }
    _, calls = run_download_all(config)
    call_names = _called(calls)
    assert "download_minute_kline" in call_names
    assert "download_daily_kline" not in call_names
    assert "download_weekly_kline" not in call_names
    assert "download_monthly_kline" not in call_names


def test_minute_disabled_skips_only_minute(run_download_all):
    _, calls = run_download_all({"kline": {"minute": {"enabled": False}}})
    call_names = _called(calls)
    assert "download_minute_kline" not in call_names
    assert "download_daily_kline" in call_names


def test_all_four_disabled_constructs_no_kline_downloader(run_download_all):
    config = {
        "kline": {
            "daily": {"enabled": False},
            "weekly": {"enabled": False},
            "monthly": {"enabled": False},
            "minute": {"enabled": False},
        }
    }
    constructed, _ = run_download_all(config)
    assert "KlineDownloader" not in constructed


# ---------------------------------------------------------------------------
# components switch
# ---------------------------------------------------------------------------

def test_components_disabled_skips_component_downloader(run_download_all):
    constructed, _ = run_download_all({"components": {"enabled": False}})
    assert "ComponentDownloader" not in constructed


def test_components_enabled_constructs_component_downloader(run_download_all):
    constructed, _ = run_download_all({})
    assert "ComponentDownloader" in constructed

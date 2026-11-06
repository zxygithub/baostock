"""Unit tests for scripts/update_daily.py — per-module download switches.

功能来源：社区 PR #1 (gitee superman75/baostock) —— 每日更新脚本支持按模块开关下载。

Breaks under test:
- 每个下载阶段(components / index_kline / kline.daily / kline.weekly /
  kline.monthly / financial / dividend)开关关闭时，对应 Downloader 不得构造、
  下载方法不得调用(默认开启则必须照常执行——防止空洞断言)
- kline 三个开关全关时 KlineDownloader 完全不得构造
  (PR 原实现的缺陷 1：with 块不受开关控制，白白 login BaoStock)
- 开关默认开启时行为与开关引入前一致(向后兼容)

夹具日期设计(关键)：
- 周五目标日 2026-11-06：周线周完整性守卫放行、月线上一完整月可下，
  三个 K 线下载方法都会真正被调用
- 周一目标日 2026-11-02：成分股阶段触发
"""

import sys
import sqlite3
from datetime import datetime, timedelta

import pytest

import scripts.update_daily as update_daily
import src.config_loader as config_loader


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeDateTime(datetime):
    """datetime subclass with a pinnable now(); strptime/replace stay real."""

    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


class FakeDBManager:
    """Stub DBManager exposing exactly what update_daily.main() reads."""

    def __init__(self, *args, **kwargs):
        pass

    def migrate_schema(self):
        pass

    def close(self):
        pass

    def get_max_date(self, table):
        return {
            "all_stock_daily": "2026-10-31",
            "index_daily": "2026-10-31",
            "all_stock_weekly": "2026-10-23",
            "all_stock_monthly": "2026-09-30",
        }.get(table)

    def get_latest_trading_day_on_or_before(self, date_str):
        return date_str  # every day is a "trading day" in the stub

    def get_trading_days_in_range(self, start, end):
        return ["2026-11-02", "2026-11-03", "2026-11-04"]  # 3 days → monthly due


def _make_spy(name, constructed, calls):
    class SpyDownloader:
        def __init__(self, *args, **kwargs):
            constructed.append(name)

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
# Fixture: run update_daily.main() against spies and a temp stock_basic DB
# ---------------------------------------------------------------------------

@pytest.fixture
def run_update(monkeypatch, tmp_path):
    """Run update_daily.main() with all external boundaries stubbed.

    Returns a runner(config, target_date) -> (constructed, calls).
    """

    def _run(config, target_date):
        # stock_basic table for the codes query (real sqlite, real SQL)
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE stock_basic (code TEXT, type INTEGER, status INTEGER)"
        )
        conn.execute("INSERT INTO stock_basic VALUES ('sh.600000', 1, 1)")
        conn.commit()
        conn.close()

        constructed, calls = [], []
        for cls_name in (
            "MetaDownloader",
            "ComponentDownloader",
            "IndexDownloader",
            "KlineDownloader",
            "FinancialDownloader",
            "DividendDownloader",
        ):
            monkeypatch.setattr(
                update_daily, cls_name, _make_spy(cls_name, constructed, calls)
            )
        monkeypatch.setattr(update_daily, "DBManager", FakeDBManager)
        monkeypatch.setattr(update_daily, "DB_PATH", db_path)
        monkeypatch.setattr(update_daily, "is_past_shutdown_time", lambda: False)
        monkeypatch.setattr(update_daily, "datetime", _FakeDateTime)
        monkeypatch.setattr(config_loader, "get_download_config", lambda: config)
        monkeypatch.setattr(sys, "argv", ["update_daily.py"])

        _FakeDateTime._now = datetime.strptime(target_date, "%Y-%m-%d").replace(
            hour=3
        ) + timedelta(days=1)

        update_daily.main()
        return constructed, calls

    return _run


MONDAY = "2026-11-02"   # weekday 0 → components stage triggers
FRIDAY = "2026-11-06"   # weekday 4 → week-completion guard passes


# ---------------------------------------------------------------------------
# Backward compatibility: default config runs everything
# ---------------------------------------------------------------------------

def test_default_config_runs_all_download_stages(run_update):
    constructed, calls = run_update({}, FRIDAY)
    for cls_name in (
        "MetaDownloader",
        "IndexDownloader",
        "KlineDownloader",
        "FinancialDownloader",
        "DividendDownloader",
    ):
        assert cls_name in constructed
    call_names = {method for _, method in calls}
    for method in (
        "download_index_daily",
        "download_daily_kline",
        "download_weekly_kline",
        "download_monthly_kline",
        "download_all_financial",
        "download_dividend",
        "download_adjust_factor",
    ):
        assert method in call_names, f"expected {method} to run with default config"


# ---------------------------------------------------------------------------
# Per-module gates
# ---------------------------------------------------------------------------

def test_components_disabled_skips_component_downloader(run_update):
    constructed, _ = run_update({"components": {"enabled": False}}, MONDAY)
    assert "ComponentDownloader" not in constructed


def test_components_enabled_on_monday_constructs_component_downloader(run_update):
    constructed, _ = run_update({}, MONDAY)
    assert "ComponentDownloader" in constructed


def test_index_kline_disabled_skips_index_downloader(run_update):
    constructed, _ = run_update({"index_kline": {"enabled": False}}, FRIDAY)
    assert "IndexDownloader" not in constructed


def test_kline_daily_disabled_skips_only_daily(run_update):
    _, calls = run_update({"kline": {"daily": {"enabled": False}}}, FRIDAY)
    call_names = {method for _, method in calls}
    assert "download_daily_kline" not in call_names
    # positive control: weekly/monthly must still run
    assert "download_weekly_kline" in call_names
    assert "download_monthly_kline" in call_names


def test_kline_weekly_disabled_skips_only_weekly(run_update):
    _, calls = run_update({"kline": {"weekly": {"enabled": False}}}, FRIDAY)
    call_names = {method for _, method in calls}
    assert "download_weekly_kline" not in call_names
    assert "download_daily_kline" in call_names
    assert "download_monthly_kline" in call_names


def test_kline_monthly_disabled_skips_only_monthly(run_update):
    _, calls = run_update({"kline": {"monthly": {"enabled": False}}}, FRIDAY)
    call_names = {method for _, method in calls}
    assert "download_monthly_kline" not in call_names
    assert "download_daily_kline" in call_names
    assert "download_weekly_kline" in call_names


def test_all_kline_disabled_constructs_no_kline_downloader(run_update):
    """PR 缺陷 1：with KlineDownloader 不受开关控制——三开关全关时不得构造。"""
    config = {
        "kline": {
            "daily": {"enabled": False},
            "weekly": {"enabled": False},
            "monthly": {"enabled": False},
        }
    }
    constructed, _ = run_update(config, FRIDAY)
    assert "KlineDownloader" not in constructed


def test_financial_disabled_skips_financial_downloader(run_update):
    constructed, _ = run_update({"financial": {"enabled": False}}, FRIDAY)
    assert "FinancialDownloader" not in constructed


def test_dividend_disabled_skips_dividend_downloader(run_update):
    constructed, _ = run_update({"dividend": {"enabled": False}}, FRIDAY)
    assert "DividendDownloader" not in constructed

"""Unit tests for src.utils.helpers.run_main_with_report pass scheduler (loop mode)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config_loader
from src.utils import helpers


def _capture_send(monkeypatch):
    sent = []
    monkeypatch.setattr(helpers, "send_daily_report",
                        lambda reason, logger=None: sent.append(reason))
    return sent


def _stub_shutdown(monkeypatch, value):
    monkeypatch.setattr("src.downloaders.base.is_past_shutdown_time", lambda: value)


def test_loop_false_runs_single_pass(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, False)

    calls = []

    def main():
        calls.append(1)
        return 0

    helpers.run_main_with_report(main)

    assert calls == [1]
    assert sent == []


def test_productive_pass_runs_immediately(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, False)
    sleeps = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def main():
        calls["n"] += 1
        if calls["n"] == 1:
            return 5
        raise SystemExit(1)

    helpers.run_main_with_report(main, loop=True)

    assert calls["n"] == 2
    assert sleeps == []
    assert sent == ["达到每日请求上限(46000)"]


def test_idle_pass_sleeps_in_segments_with_heartbeat(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, False)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 10)
    sleeps = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: sleeps.append(s))
    logger = MagicMock()

    calls = {"n": 0}

    def main():
        calls["n"] += 1
        if calls["n"] == 1:
            return 0
        raise SystemExit(1)

    helpers.run_main_with_report(main, logger, loop=True)

    assert all(s <= 300 for s in sleeps)
    assert len(sleeps) == 2  # 10 分钟 = 2 段 × 300 秒
    heartbeats = [
        c.args[0]
        for c in logger.info.call_args_list
        if "休眠心跳" in str(c.args[0])
    ]
    assert len(heartbeats) == 2
    assert sent == ["达到每日请求上限(46000)"]


def test_sleep_crossing_shutdown_sends_report(monkeypatch):
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 10)
    sleeps = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: sleeps.append(s))

    state = {"n": 0}

    def shutdown():
        state["n"] += 1
        return state["n"] >= 2

    monkeypatch.setattr("src.downloaders.base.is_past_shutdown_time", shutdown)

    def main():
        return 0

    helpers.run_main_with_report(main, loop=True)

    assert sent == ["达到每日停止时间(23:55)"]
    assert len(sleeps) >= 1
    assert all(s <= 300 for s in sleeps)


def test_systemexit_1_sends_limit_reason_loop(monkeypatch):
    sent = _capture_send(monkeypatch)

    def hit_limit():
        raise SystemExit(1)

    helpers.run_main_with_report(hit_limit, loop=True)

    assert sent == ["达到每日请求上限(46000)"]


def test_idle_interval_from_config(monkeypatch):
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(config_loader, "get_download_config",
                        lambda: {"idle_pass_interval_minutes": 7})
    _stub_shutdown(monkeypatch, False)
    sleeps = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def main():
        calls["n"] += 1
        if calls["n"] == 1:
            return 0
        raise SystemExit(1)

    helpers.run_main_with_report(main, loop=True)

    assert sum(sleeps) == 7 * 60
    assert all(s <= 300 for s in sleeps)


def test_non_positive_interval_clamps_to_min_sleep(monkeypatch):
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(helpers, "get_idle_pass_interval_minutes", lambda: 0)
    _stub_shutdown(monkeypatch, False)
    sleeps = []
    monkeypatch.setattr(helpers.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def main():
        calls["n"] += 1
        if calls["n"] == 1:
            return 0
        raise SystemExit(1)

    helpers.run_main_with_report(main, loop=True)

    assert sleeps and all(s > 0 for s in sleeps)  # 非正间隔仍须真实休眠,不热循环
    assert sum(sleeps) == 60  # 钳位到最低 1 分钟
    assert calls["n"] == 2  # 先睡一觉才进入第二趟


def test_idle_interval_default(monkeypatch):
    monkeypatch.setattr(config_loader, "get_download_config", lambda: {})
    assert config_loader.get_idle_pass_interval_minutes() == 90

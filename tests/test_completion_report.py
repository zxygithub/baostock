"""Unit tests for src.utils.helpers.run_main_with_report completion hook."""

import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import helpers


def _capture_send(monkeypatch):
    sent = []
    monkeypatch.setattr(helpers, "send_daily_report",
                        lambda reason, logger=None: sent.append(reason))
    return sent


def _stub_shutdown(monkeypatch, value):
    monkeypatch.setattr("src.downloaders.base.is_past_shutdown_time", lambda: value)


def test_normal_return_mid_day_does_not_send(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, False)

    helpers.run_main_with_report(lambda: None)

    assert sent == []


def test_shutdown_time_sends_shutdown_reason(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, True)

    helpers.run_main_with_report(lambda: None)

    assert sent == ["达到每日停止时间(23:55)"]


def test_systemexit_1_sends_limit_reason(monkeypatch):
    sent = _capture_send(monkeypatch)

    def hit_limit():
        raise SystemExit(1)

    helpers.run_main_with_report(hit_limit)

    assert sent == ["达到每日请求上限(49000)"]


def test_keyboardinterrupt_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        helpers.run_main_with_report(interrupted)

    assert sent == []


def test_generic_exception_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def crashed():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        helpers.run_main_with_report(crashed)

    assert sent == []


def test_systemexit_string_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def blacklisted():
        raise SystemExit("IP blacklisted.")

    with pytest.raises(SystemExit):
        helpers.run_main_with_report(blacklisted)

    assert sent == []


def test_send_daily_report_invokes_with_flags(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return MagicMock(returncode=0)

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    helpers.send_daily_report("测试原因")

    cmd, kwargs = calls[0]
    assert cmd[1].endswith("scripts/daily_report.py")
    assert "--if-needed" in cmd
    assert cmd[cmd.index("--date") + 1] == date.today().isoformat()
    assert cmd[cmd.index("--reason") + 1] == "测试原因"
    assert kwargs["timeout"] >= 300


def test_send_daily_report_swallows_subprocess_errors(monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(helpers.subprocess, "run", boom)

    helpers.send_daily_report("reason")  # must not raise

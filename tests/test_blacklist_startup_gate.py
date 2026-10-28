"""启动前退避闸测试(设计方案组件 2、§3.2 退出码约定)。

契约:封禁期内启动不进 main_fn、零网络请求、退出码 2(与配额上限的 1 区分)、
不发日报;报错文案自带解法;--ignore-blacklist / BAOSTOCK_IGNORE_BLACKLIST=1 放行。
"""

import subprocess
import sys
from pathlib import Path

import pytest

from src.utils import helpers
from src.utils import blacklist


def _capture_send(monkeypatch):
    sent = []
    monkeypatch.setattr(
        helpers, "send_daily_report", lambda reason, logger=None: sent.append(reason)
    )
    return sent


def _arm_fresh_marker(monkeypatch, tmp_path):
    """放行 conftest 旁路,并把标记指向 tmp_path 的新鲜标记(模拟封禁中)。"""
    marker = tmp_path / ".blacklisted"
    marker.write_text("{}")
    monkeypatch.setattr(blacklist, "marker_path", lambda: marker)
    monkeypatch.delenv("BAOSTOCK_IGNORE_BLACKLIST", raising=False)
    blacklist.set_bypass(False)
    return marker


def test_loop_false_blocked_exits_2(monkeypatch, tmp_path):
    sent = _capture_send(monkeypatch)
    _arm_fresh_marker(monkeypatch, tmp_path)
    calls = []

    def main():
        calls.append(1)
        raise AssertionError("main_fn 不应被调用(闸门缺失时用例必须失败而非挂起)")

    with pytest.raises(SystemExit) as exc:
        helpers.run_main_with_report(main)

    assert exc.value.code == 2  # 2=封禁闸,不得与配额上限的 1 混淆
    assert calls == []  # 不进 main_fn,零网络请求
    assert sent == []  # 不发日报


def test_loop_true_blocked_terminates_without_pass(monkeypatch, tmp_path):
    sent = _capture_send(monkeypatch)
    _arm_fresh_marker(monkeypatch, tmp_path)
    calls = []

    def main():
        calls.append(1)
        raise AssertionError("趟次不应开始(闸门缺失时用例必须失败而非挂起)")

    with pytest.raises(SystemExit) as exc:
        helpers.run_main_with_report(main, loop=True)

    assert exc.value.code == 2
    assert calls == []  # 不进趟次
    assert sent == []


def test_ignore_flag_or_env_allows(monkeypatch, tmp_path):
    sent = _capture_send(monkeypatch)
    _arm_fresh_marker(monkeypatch, tmp_path)
    calls = []

    blacklist.set_bypass(True)  # --ignore-blacklist 的落点
    helpers.run_main_with_report(lambda: calls.append(1))
    assert calls == [1]

    blacklist.set_bypass(False)
    monkeypatch.setenv("BAOSTOCK_IGNORE_BLACKLIST", "1")  # monitor 拉起进程的形态
    helpers.run_main_with_report(lambda: calls.append(1))
    assert calls == [1, 1]
    assert sent == []


def test_error_message_carries_remedy_and_exit_2_not_quota(monkeypatch, tmp_path, caplog):
    sent = _capture_send(monkeypatch)
    marker = _arm_fresh_marker(monkeypatch, tmp_path)

    with caplog.at_level("ERROR", logger="baostock"), pytest.raises(SystemExit) as exc:
        helpers.run_main_with_report(lambda: None)

    assert exc.value.code != 1  # 不得被 run_main_with_report 误判为配额上限
    assert sent == []
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "退避期" in text
    assert str(marker) in text  # 文案给出标记路径(生产为 data/.blacklisted)
    assert "--ignore-blacklist" in text  # 报错文案必须自带解法


def test_cli_scripts_expose_ignore_blacklist():
    """两个入口脚本都必须提供 --ignore-blacklist(BaseDownloader 拿不到 argv)。"""
    root = Path(__file__).resolve().parent.parent
    for script in ("scripts/download_all.py", "scripts/update_daily.py"):
        out = subprocess.run(
            [sys.executable, script, "--help"],
            capture_output=True, text=True, cwd=root, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert "--ignore-blacklist" in out.stdout, script

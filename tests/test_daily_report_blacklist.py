"""日报与黑名单退避的协同测试(设计方案组件 6)。

契约:退避期内 check_blacklist_status() 零网络请求(反复登录会延长封禁,
日报不得替我们把封禁续上),直接用标记内容出状态;未在退避期才走原探测。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import daily_report  # noqa: E402
from src.utils import blacklist  # noqa: E402


class FakeLogin:
    def __init__(self, error_code="0", error_msg=""):
        self.error_code = error_code
        self.error_msg = error_msg


class FakeRs:
    def __init__(self, error_code="0", error_msg=""):
        self.error_code = error_code
        self.error_msg = error_msg


def test_daily_report_skips_probe_during_backoff(monkeypatch, tmp_path):
    marker = tmp_path / ".blacklisted"
    marker.write_text("{}")  # 封禁退避中(monitor touch 形态)
    monkeypatch.setattr(blacklist, "marker_path", lambda: marker)
    monkeypatch.delenv("BAOSTOCK_IGNORE_BLACKLIST", raising=False)
    blacklist.set_bypass(False)

    login_calls = []
    monkeypatch.setattr(
        daily_report.bs, "login", lambda: login_calls.append(1) or FakeLogin()
    )
    monkeypatch.setattr(daily_report, "record_requests", lambda n=1: None)

    status, detail = daily_report.check_blacklist_status()

    assert login_calls == []  # 零网络请求
    assert "黑名单" in status
    assert "分钟" in detail  # 用标记内容出状态(含剩余时间)


def test_daily_report_probes_when_not_blocked(monkeypatch, tmp_path):
    marker = tmp_path / ".blacklisted"  # 不存在:不在退避期
    monkeypatch.setattr(blacklist, "marker_path", lambda: marker)
    monkeypatch.setattr(daily_report, "record_requests", lambda n=1: None)

    login_calls = []
    monkeypatch.setattr(
        daily_report.bs, "login", lambda: login_calls.append(1) or FakeLogin()
    )
    monkeypatch.setattr(daily_report.bs, "logout", lambda: FakeLogin())
    monkeypatch.setattr(
        daily_report.bs,
        "query_stock_basic",
        lambda **kwargs: FakeRs(error_code="0"),
    )

    status, detail = daily_report.check_blacklist_status()

    assert login_calls == [1]  # 未封禁才走原探测逻辑
    assert "正常" in status

"""查询期熔断测试(设计方案组件 3,§3.2 决策 2)。

契约:首个 10001011 即熔断,被封后零后续请求;BlacklistedError 直接继承
Exception(不得被 except RuntimeError: continue 吞掉);arm 只在真实观测到
10001011 时调用;close 跳过 logout 但关 socket;login 成功即 clear。
"""

import logging

import pandas as pd
import pytest

from src.config import BSERR_BLACKLIST_USER
from src.downloaders.base import BaseDownloader, BlacklistedError
from src.downloaders.financial_downloader import FinancialDownloader
from src.utils import blacklist, helpers


class FakeRs:
    def __init__(self, error_code="0", error_msg=""):
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = []
        self.cur_page_num = 1

    def next(self):
        return False

    def get_row_data(self):
        return []


class FakeLogin:
    def __init__(self, error_code="0", error_msg=""):
        self.error_code = error_code
        self.error_msg = error_msg


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


REQUEST_COUNT_DDL = (
    "CREATE TABLE request_count ("
    "date TEXT PRIMARY KEY, count INTEGER, update_time TEXT)"
)


def _make_dl(tmp_path, cls=BaseDownloader):
    dl = object.__new__(cls)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl.logger = logging.getLogger("test_blacklist_circuit_break")
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl._blacklisted = False
    dl.new_rows = 0
    dl.conn.execute(REQUEST_COUNT_DDL)
    dl.conn.commit()
    return dl


def _stub_broken_query(dl, monkeypatch, calls):
    def fake_query(**kwargs):
        calls.append(kwargs)
        return FakeRs(error_code=BSERR_BLACKLIST_USER, error_msg="黑名单用户，请与管理员联系")

    monkeypatch.setattr(dl, "ensure_login", lambda: None)
    monkeypatch.setattr(blacklist, "arm", lambda source, detail="": None)
    return fake_query


def test_query_blacklist_single_request_then_break(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    calls = []
    fake_query = _stub_broken_query(dl, monkeypatch, calls)

    with pytest.raises(BlacklistedError):
        dl.query_with_retry(fake_query, code="sh.600000")

    assert len(calls) == 1  # 不重试:每一发都会延长封禁


def test_error_not_swallowed_by_runtime_error_continue(tmp_path, monkeypatch):
    """financial/report/dividend 的 `except RuntimeError: continue` 不得吞掉熔断。"""
    dl = _make_dl(tmp_path)
    calls = []
    fake_query = _stub_broken_query(dl, monkeypatch, calls)

    with pytest.raises(BlacklistedError):
        try:
            dl.query_with_retry(fake_query, code="sh.600000")
        except RuntimeError:
            pass  # 仿生产循环的吞掉路径


def test_flush_pending_batches_called_before_raise(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    calls, flushed = [], []
    fake_query = _stub_broken_query(dl, monkeypatch, calls)
    monkeypatch.setattr(dl, "_flush_pending_batches", lambda: flushed.append(1))

    with pytest.raises(BlacklistedError):
        dl.query_with_retry(fake_query, code="sh.600000")

    assert flushed == [1]  # 保住已拉到的数据


def test_arm_called_with_source_query(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    calls, armed = [], []
    fake_query = _stub_broken_query(dl, monkeypatch, calls)
    monkeypatch.setattr(
        blacklist, "arm", lambda source, detail="": armed.append((source, detail))
    )

    with pytest.raises(BlacklistedError):
        dl.query_with_retry(fake_query, code="sh.600000")

    assert armed and armed[0][0] == "query"
    assert "code=sh.600000" in armed[0][1]  # detail 含定位信息


def test_close_skips_logout_but_closes_socket(tmp_path, monkeypatch):
    import baostock.common.context as context

    dl = _make_dl(tmp_path)
    dl._blacklisted = True
    logout_calls = []
    monkeypatch.setattr(dl, "logout", lambda: logout_calls.append(1))
    sock = FakeSocket()
    # default_socket 由 baostock connect() 动态创建,模块上可能不存在
    monkeypatch.setattr(context, "default_socket", sock, raising=False)

    dl.close()

    assert logout_calls == []  # 被封时不再多打一发 logout
    assert sock.closed is True  # 但必须关 socket,防 fd 泄漏


def test_login_success_clears_marker(tmp_path, monkeypatch):
    import baostock as bs

    dl = _make_dl(tmp_path)
    cleared = []
    monkeypatch.setattr(blacklist, "clear", lambda: cleared.append(1))
    monkeypatch.setattr(bs, "login", lambda: FakeLogin("0"))
    monkeypatch.setattr(dl, "_apply_socket_timeout", lambda: None)

    dl.login()

    assert cleared == [1]  # 成功登录即清除标记(解封自愈)


def test_login_blacklist_arms_login_source(tmp_path, monkeypatch):
    import baostock as bs

    dl = _make_dl(tmp_path)
    armed = []
    monkeypatch.setattr(
        blacklist, "arm", lambda source, detail="": armed.append(source)
    )
    monkeypatch.setattr(bs, "login", lambda: FakeLogin(BSERR_BLACKLIST_USER, "IP blacklisted"))

    with pytest.raises(BlacklistedError):
        dl.login()  # 取代原 SystemExit("IP blacklisted.")

    assert armed == ["login"]


def test_flush_without_batch_table_writes_no_unknown(tmp_path, monkeypatch):
    """评审问题 E 回归:_batch_table 未设时不得静默建 unknown 垃圾表。"""
    dl = _make_dl(tmp_path, FinancialDownloader)
    dl._batch_dfs = [pd.DataFrame([{"code": "sh.600000"}])]

    dl._flush_pending_batches()

    tables = {
        row[0]
        for row in dl.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "unknown" not in tables
    assert "unknown_batch_tmp" not in tables


def test_api_call_blacklist_breaks(tmp_path, monkeypatch):
    """_api_call 路径同样熔断(目标:被封后 0 次请求)。"""
    dl = _make_dl(tmp_path)
    calls = []
    monkeypatch.setattr(blacklist, "arm", lambda source, detail="": None)

    def fake_call():
        calls.append(1)
        return FakeRs(error_code=BSERR_BLACKLIST_USER, error_msg="黑名单用户")

    with pytest.raises(BlacklistedError):
        dl._api_call(fake_call)

    assert len(calls) == 1


def test_loop_true_blacklisted_exits_nonzero(monkeypatch):
    """spec §3.2:loop=True 被封终止的退出码必须非 0(1=配额,2=闸,3=熔断终止)。"""
    sent = []
    monkeypatch.setattr(
        helpers, "send_daily_report", lambda reason, logger=None: sent.append(reason)
    )
    monkeypatch.setattr("src.downloaders.base.is_past_shutdown_time", lambda: False)
    calls = []

    def main():
        calls.append(1)
        raise BlacklistedError("黑名单用户")

    with pytest.raises(SystemExit) as exc:
        helpers.run_main_with_report(main, loop=True)

    assert calls == [1]  # 终止,不再开下一趟
    assert exc.value.code not in (None, 0)  # 不得静默退出 0(start.sh 会误标 DONE)
    assert sent == []  # 不发日报

"""Unit tests for src.utils.blacklist marker + backoff (spec §4/§5 组件 1).

自愈核心:闸判年龄不判存在性;fail-open 六条;退避期内绝不 touch/续期。
所有用例把标记指向 tmp_path,不触碰生产 data/.blacklisted。
"""

import json
import os
import time
from pathlib import Path

import pytest

from src.utils import blacklist


@pytest.fixture
def marker(tmp_path, monkeypatch):
    p = tmp_path / ".blacklisted"
    monkeypatch.setattr(blacklist, "marker_path", lambda: p)
    monkeypatch.delenv("BAOSTOCK_IGNORE_BLACKLIST", raising=False)
    blacklist.set_bypass(False)
    yield p
    blacklist.set_bypass(False)


WINDOW = 120 * 60  # api.blacklist_backoff_minutes 默认 120 → 秒


def _set_mtime(path: Path, when: float) -> None:
    os.utime(path, (when, when))


def test_no_marker_allows(marker):
    assert blacklist.in_backoff(marker=marker, now=time.time()) == (False, 0)


def test_fresh_marker_blocks_with_remaining(marker):
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now - 30)

    blocked, remain = blacklist.in_backoff(marker=marker, now=now)

    assert blocked is True
    assert remain == WINDOW - 30  # 剩余秒数 = 窗口 - 年龄


def test_expired_marker_allows(marker):
    """自愈核心:窗口一过自动放行,不依赖任何外部删除者。"""
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now - WINDOW - 1)

    assert blacklist.in_backoff(marker=marker, now=now) == (False, 0)


def test_stat_oserror_allows(marker, monkeypatch):
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now - 30)
    real_stat = Path.stat

    def boom(self, *args, **kwargs):
        if Path(self) == marker:
            raise OSError("race: marker deleted between check and read")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", boom)

    assert blacklist.in_backoff(marker=marker, now=now) == (False, 0)


def test_future_mtime_allows(marker):
    """时钟回拨 / mtime 在未来 → 放行,不得长期锁死。"""
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now + 3600)

    assert blacklist.in_backoff(marker=marker, now=now) == (False, 0)


def test_corrupt_or_empty_marker_falls_back_to_mtime(marker):
    """monitor touch 出的空文件/损坏 JSON:回落纯 mtime 判定,不报错。"""
    now = time.time()
    marker.write_text("")  # monitor touch 的形态
    _set_mtime(marker, now - 30)
    assert blacklist.in_backoff(marker=marker, now=now)[0] is True

    marker.write_text("{not json")  # 损坏内容
    _set_mtime(marker, now - WINDOW - 1)
    assert blacklist.in_backoff(marker=marker, now=now) == (False, 0)


def test_non_positive_window_disables_gate(marker, monkeypatch):
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now - 30)
    monkeypatch.setattr(blacklist, "get_blacklist_backoff_minutes", lambda: 0)

    assert blacklist.in_backoff(marker=marker, now=now) == (False, 0)


def test_arm_increments_hits_and_keeps_first(marker, monkeypatch):
    monkeypatch.setattr(blacklist, "marker_path", lambda: marker)

    blacklist.arm(source="query", detail="query_history_k_data_plus code=sh.600000")
    first = json.loads(marker.read_text())
    blacklist.arm(source="login", detail="")
    second = json.loads(marker.read_text())

    assert second["consecutive_hits"] == 2
    assert second["first_banned_at"] == first["first_banned_at"]
    assert second["source"] == "login"


def test_clear_idempotent(marker, monkeypatch):
    monkeypatch.setattr(blacklist, "marker_path", lambda: marker)

    blacklist.arm(source="query")
    blacklist.clear()
    blacklist.clear()  # 文件已不存在,静默

    assert not marker.exists()
    assert blacklist.in_backoff(marker=marker, now=time.time()) == (False, 0)


def test_in_backoff_never_touches_marker(marker):
    """不变量③:退避判定只读。若它刷新 mtime,窗口会被自己无限续期。"""
    now = time.time()
    marker.write_text("{}")
    _set_mtime(marker, now - 30)

    before = marker.stat().st_mtime
    for _ in range(5):
        blacklist.in_backoff(marker=marker, now=now)
    after = marker.stat().st_mtime

    assert after == before

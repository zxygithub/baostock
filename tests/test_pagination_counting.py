"""分页请求计数修正测试(设计方案组件 5,缺口 H)。

契约:服务端翻页(resultset.next 满页自行 send_msg)即计一次请求;
单页 1 次、翻 N 页 N+1 次;分页途中触顶同样熔断(SystemExit(1))。
"""

import logging
from datetime import date

import pytest

from src.downloaders.base import BaseDownloader


class PaginatingRs:
    """模拟 baostock resultset:满页自动取下一页,cur_page_num 递增。"""

    def __init__(self, total_rows: int, page_size: int):
        self.error_code = "0"
        self.error_msg = ""
        self.fields = ["x"]
        self.cur_page_num = 1
        self._total = total_rows
        self._page_size = page_size
        self._served = 0

    def next(self):
        if self._served >= self._total:
            return False
        self._served += 1
        if self._served > self._page_size * self.cur_page_num:
            self.cur_page_num += 1
        return True

    def get_row_data(self):
        return [self._served]


REQUEST_COUNT_DDL = (
    "CREATE TABLE request_count ("
    "date TEXT PRIMARY KEY, count INTEGER, update_time TEXT)"
)


def _make_dl(tmp_path, limit=46000):
    dl = object.__new__(BaseDownloader)
    dl.db_path = tmp_path / "dl.db"
    dl._conn = None
    dl.logger = logging.getLogger("test_pagination_counting")
    dl._login_time = 0
    dl._interrupted = False
    dl._limit_exceeded = False
    dl._blacklisted = False
    dl.new_rows = 0
    dl.DAILY_REQUEST_LIMIT = limit
    dl.conn.execute(REQUEST_COUNT_DDL)
    dl.conn.commit()
    return dl


def _consume(rs):
    while rs.next():
        rs.get_row_data()


def _today_count(dl) -> int:
    row = dl.conn.execute(
        "SELECT count FROM request_count WHERE date = ?", (date.today().isoformat(),)
    ).fetchone()
    return row[0] if row else 0


def _stub_query(monkeypatch, dl, rs):
    monkeypatch.setattr(dl, "ensure_login", lambda: None)
    monkeypatch.setattr(dl, "_throttle", lambda: None)
    return lambda **kwargs: rs


def test_single_page_counts_once(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    rs = PaginatingRs(total_rows=2, page_size=10)  # 不翻页
    fake_query = _stub_query(monkeypatch, dl, rs)

    _consume(dl.query_with_retry(fake_query))

    assert _today_count(dl) == 1  # 查询本身 1 次


def test_two_page_turns_count_three(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path)
    rs = PaginatingRs(total_rows=5, page_size=2)  # 5 行 / 每页 2 行 → 翻 2 页
    fake_query = _stub_query(monkeypatch, dl, rs)

    _consume(dl.query_with_retry(fake_query))

    assert _today_count(dl) == 3  # 1 查询 + 2 翻页


def test_quota_hit_mid_pagination_exits_1(tmp_path, monkeypatch):
    dl = _make_dl(tmp_path, limit=3)
    dl.conn.execute(
        "INSERT INTO request_count (date, count, update_time) VALUES (?, 1, ?)",
        (date.today().isoformat(), "2026-10-28 00:00:00"),
    )
    dl.conn.commit()
    rs = PaginatingRs(total_rows=5, page_size=2)
    fake_query = _stub_query(monkeypatch, dl, rs)

    with pytest.raises(SystemExit) as exc:
        _consume(dl.query_with_retry(fake_query))

    assert exc.value.code == 1  # 分页途中触顶:退出码 1(配额上限),不得混淆为 2

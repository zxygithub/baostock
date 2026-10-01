"""Regression tests for scripts/daily_report.py after email module migration.

build_email must return (subject, html) with the exact historical subject
format so the daily report email is byte-identical to pre-migration.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import daily_report

API_REQ = {
    "daily_limit": 49000,
    "days_remaining": 5,
    "kline": 100,
    "financial": 200,
    "reports": 300,
    "dividend": 400,
    "index": 500,
    "macro": 600,
    "meta": 700,
    "total": 2800,
}


def test_build_email_returns_subject_and_html():
    subject, html = daily_report.build_email(
        "2026-09-30 00:00:00",
        "2026-09-30 06:00:00",
        1234,
        56789,
        "正常",
        "未列入黑名单",
        "<tr><td>row</td></tr>",
        API_REQ,
        report_date=date(2026, 9, 30),
    )
    assert subject == "BaoStock 数据下载日报 (2026-09-30)"
    assert "BaoStock 数据下载状态日报" in html
    assert "<tr><td>row</td></tr>" in html
    assert "56,789" in html

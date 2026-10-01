"""Unit tests for daily_report.py --if-needed / --date / --reason behavior."""

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import daily_report


API_REQ = {
    "kline": 1, "financial": 2, "reports": 3, "dividend": 4, "index": 5,
    "macro": 6, "meta": 7, "total": 28, "daily_limit": 49000,
    "today_count": 100, "days_remaining": 1.0,
}


def _patch_heavy(monkeypatch, send_result=True):
    """Stub everything touching DB/network/yaml; return a (subject, body) recorder."""
    sent = []
    monkeypatch.setattr(daily_report, "load_dotenv", lambda: None)
    monkeypatch.setattr(daily_report, "load_config", lambda: {"email": {"enabled": True}})
    monkeypatch.setattr(daily_report, "load_email_config", lambda: {
        "smtp_server": "s", "smtp_port": 465,
        "sender": "a", "password": "p", "receiver": "r",
    })
    monkeypatch.setattr(daily_report, "get_db_stats",
                        lambda rd: (MagicMock(), 100, 1000, {}))
    monkeypatch.setattr(daily_report, "get_latest_download_times", lambda: ("t1", "t2"))
    monkeypatch.setattr(daily_report, "check_blacklist_status", lambda: ("正常", "ok"))
    monkeypatch.setattr(daily_report, "get_progress_table",
                        lambda conn, counts, rd: ("<tr><td>row</td></tr>", API_REQ))
    monkeypatch.setattr(daily_report, "parse_api_request_log", lambda target_date=None: None)
    monkeypatch.setattr(daily_report, "get_monitor_events", lambda: None)

    def fake_send(cfg, subject, body, subtype="plain"):
        sent.append((subject, body))
        return send_result

    monkeypatch.setattr(daily_report, "send_email", fake_send)
    return sent


def _run(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(daily_report, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["daily_report.py"] + argv)
    daily_report.main()


def test_if_needed_skips_when_marker_exists(monkeypatch, tmp_path):
    sent = _patch_heavy(monkeypatch)
    (tmp_path / ".report_sent_2026-10-01").write_text("x", encoding="utf-8")

    _run(monkeypatch, tmp_path, ["--if-needed", "--date", "2026-10-01"])

    assert sent == []


def test_success_sends_and_writes_marker(monkeypatch, tmp_path):
    sent = _patch_heavy(monkeypatch)

    _run(monkeypatch, tmp_path, ["--if-needed", "--date", "2026-10-01"])

    assert len(sent) == 1
    assert sent[0][0] == "BaoStock 数据下载日报 (2026-10-01)"
    assert (tmp_path / ".report_sent_2026-10-01").exists()


def test_send_failure_does_not_write_marker(monkeypatch, tmp_path):
    _patch_heavy(monkeypatch, send_result=False)

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, tmp_path, ["--if-needed", "--date", "2026-10-01"])

    assert excinfo.value.code == 1
    assert not (tmp_path / ".report_sent_2026-10-01").exists()


def test_date_option_drives_report_date(monkeypatch, tmp_path):
    sent = _patch_heavy(monkeypatch)
    captured = {}

    def spy(rd):
        captured["report_date"] = rd
        return (MagicMock(), 100, 1000, {})

    monkeypatch.setattr(daily_report, "get_db_stats", spy)

    _run(monkeypatch, tmp_path, ["--date", "2026-10-01"])

    assert captured["report_date"] == date(2026, 10, 1)
    assert "(2026-10-01)" in sent[0][0]


def test_default_date_is_yesterday(monkeypatch, tmp_path):
    _patch_heavy(monkeypatch)
    captured = {}

    def spy(rd):
        captured["report_date"] = rd
        return (MagicMock(), 100, 1000, {})

    monkeypatch.setattr(daily_report, "get_db_stats", spy)

    _run(monkeypatch, tmp_path, [])

    assert captured["report_date"] == date.today() - timedelta(days=1)


def test_reason_appears_in_body(monkeypatch, tmp_path):
    sent = _patch_heavy(monkeypatch)

    _run(monkeypatch, tmp_path,
         ["--date", "2026-10-01", "--reason", "达到每日请求上限(49000)"])

    _, body = sent[0]
    assert "完成原因" in body
    assert "达到每日请求上限(49000)" in body


def test_marker_written_even_without_if_needed(monkeypatch, tmp_path):
    sent = _patch_heavy(monkeypatch)

    _run(monkeypatch, tmp_path, ["--date", "2026-10-01"])

    assert len(sent) == 1
    assert (tmp_path / ".report_sent_2026-10-01").exists()

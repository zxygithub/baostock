"""Unit tests for backup email notification in scripts/backup_to_baidu.py.

All SMTP and backup side effects are mocked; no network, no real files.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backup_to_baidu


RUN_TIME = datetime(2026, 10, 1, 14, 0, 32)


def make_result(**overrides):
    result = {
        "success": True,
        "stage": "",
        "error": None,
        "archive_name": "baostock_backup_20261001_140032.tar.gz",
        "archive_size": 1234567890,
        "remote_path": "/apps/bypy/证券数据备份/baostock_backup_20261001_140032.tar.gz",
        "duration": 85.0,
        "keep_count": 7,
        "deleted_old": 1,
        "started_at": RUN_TIME,
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# Pure builders
# ---------------------------------------------------------------------------

def test_subject_format():
    subject = backup_to_baidu.build_subject(RUN_TIME)
    assert subject == "证券数据baostock百度云备份结果-2026年10月01日"


def test_success_body_contains_all_fields():
    body = backup_to_baidu.build_success_text(make_result())
    assert "结果:成功" in body
    assert "baostock_backup_20261001_140032.tar.gz" in body
    assert "1,234,567,890 字节" in body
    assert "/apps/bypy/证券数据备份/baostock_backup_20261001_140032.tar.gz" in body
    assert "总耗时:85 秒" in body
    assert "保留最近 7 份" in body
    assert "本次清理旧备份 1 份" in body
    assert "2026-10-01 14:00:32" in body


def test_failure_body_contains_stage_error_and_log_path():
    body = backup_to_baidu.build_failure_text(make_result(
        success=False, stage="上传", error="Chunk 3 failed after 3 attempts: Connection reset",
    ))
    assert "结果:失败" in body
    assert "失败阶段:上传" in body
    assert "Chunk 3 failed after 3 attempts: Connection reset" in body
    assert "logs/backup.log" in body


# ---------------------------------------------------------------------------
# notify_result policy
# ---------------------------------------------------------------------------

def _args(no_email=False):
    return SimpleNamespace(no_email=no_email)


def _capture_send(monkeypatch, ok=True):
    calls = []

    def fake_send(cfg, subject, body, subtype="plain"):
        calls.append((cfg, subject, body, subtype))
        return ok

    monkeypatch.setattr(backup_to_baidu, "send_email", fake_send)
    monkeypatch.setattr(backup_to_baidu, "load_email_config", lambda: {
        "smtp_server": "smtp.qq.com", "smtp_port": 465,
        "sender": "s@qq.com", "password": "p", "receiver": "r@qq.com",
    })
    return calls


def test_notify_sends_on_success(monkeypatch):
    calls = _capture_send(monkeypatch)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {"email": {"backup_notify": True}})

    backup_to_baidu.notify_result(make_result(), _args())

    assert len(calls) == 1
    cfg, subject, body, subtype = calls[0]
    assert subject == "证券数据baostock百度云备份结果-2026年10月01日"
    assert "结果:成功" in body
    assert subtype == "plain"
    assert cfg["receiver"] == "r@qq.com"


def test_notify_sends_failure_body(monkeypatch):
    calls = _capture_send(monkeypatch)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {"email": {"backup_notify": True}})

    backup_to_baidu.notify_result(
        make_result(success=False, stage="打包", error="disk full"), _args())

    assert len(calls) == 1
    _, subject, body, _ = calls[0]
    assert "结果:失败" in body
    assert "失败阶段:打包" in body
    assert "disk full" in body


def test_notify_no_email_flag_skips(monkeypatch):
    calls = _capture_send(monkeypatch)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {"email": {"backup_notify": True}})

    backup_to_baidu.notify_result(make_result(), _args(no_email=True))

    assert calls == []


def test_notify_config_false_skips(monkeypatch):
    calls = _capture_send(monkeypatch)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {"email": {"backup_notify": False}})

    backup_to_baidu.notify_result(make_result(), _args())

    assert calls == []


def test_notify_config_missing_defaults_to_send(monkeypatch):
    calls = _capture_send(monkeypatch)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {})

    backup_to_baidu.notify_result(make_result(), _args())

    assert len(calls) == 1


def test_notify_skips_when_email_config_incomplete(monkeypatch):
    calls = []
    monkeypatch.setattr(backup_to_baidu, "send_email",
                        lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(backup_to_baidu, "load_email_config", lambda: None)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: {"email": {"backup_notify": True}})

    backup_to_baidu.notify_result(make_result(), _args())  # must not raise

    assert calls == []


# ---------------------------------------------------------------------------
# main() exit-code semantics
# ---------------------------------------------------------------------------

def _setup_main(monkeypatch, tmp_path, upload_ok=True, send_ok=True,
                no_email=False, config=None, create_raises=None):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    def fake_create(dd, output_path):
        if create_raises is not None:
            raise create_raises
        output_path.write_bytes(b"fake-archive")
        return output_path

    sent = []
    monkeypatch.setattr(backup_to_baidu, "load_token", lambda: "fake-token")
    monkeypatch.setattr(backup_to_baidu, "create_backup_archive", fake_create)
    monkeypatch.setattr(backup_to_baidu, "upload_file",
                        lambda token, filepath, remote_path: upload_ok)
    monkeypatch.setattr(backup_to_baidu, "cleanup_old_backups",
                        lambda token, dir_path, keep_count: 1)
    monkeypatch.setattr(backup_to_baidu, "load_config", lambda: config or {"email": {"backup_notify": True}})
    monkeypatch.setattr(backup_to_baidu, "load_email_config", lambda: {
        "smtp_server": "s", "smtp_port": 465,
        "sender": "a", "password": "p", "receiver": "r",
    })
    monkeypatch.setattr(backup_to_baidu, "send_email",
                        lambda cfg, subject, body, subtype="plain": sent.append((subject, body)) or send_ok)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    argv = ["backup_to_baidu.py", "--data-dir", str(data_dir)]
    if no_email:
        argv.append("--no-email")
    monkeypatch.setattr(sys, "argv", argv)
    return sent


def test_main_success_sends_email_and_exits_0(monkeypatch, tmp_path):
    sent = _setup_main(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        backup_to_baidu.main()

    assert excinfo.value.code == 0
    assert len(sent) == 1
    assert "结果:成功" in sent[0][1]


def test_main_send_failure_keeps_exit_0(monkeypatch, tmp_path):
    _setup_main(monkeypatch, tmp_path, send_ok=False)

    with pytest.raises(SystemExit) as excinfo:
        backup_to_baidu.main()

    assert excinfo.value.code == 0  # 发信失败不影响备份退出码


def test_main_upload_failure_sends_failure_email_and_exits_1(monkeypatch, tmp_path):
    sent = _setup_main(monkeypatch, tmp_path, upload_ok=False)

    with pytest.raises(SystemExit) as excinfo:
        backup_to_baidu.main()

    assert excinfo.value.code == 1
    assert len(sent) == 1
    assert "结果:失败" in sent[0][1]
    assert "失败阶段:上传" in sent[0][1]


def test_main_create_exception_sends_failure_email_and_exits_1(monkeypatch, tmp_path):
    sent = _setup_main(monkeypatch, tmp_path, create_raises=RuntimeError("disk full"))

    with pytest.raises(SystemExit) as excinfo:
        backup_to_baidu.main()

    assert excinfo.value.code == 1
    assert len(sent) == 1
    assert "disk full" in sent[0][1]
    assert "失败阶段:打包" in sent[0][1]


def test_main_no_email_flag_sends_nothing(monkeypatch, tmp_path):
    sent = _setup_main(monkeypatch, tmp_path, no_email=True)

    with pytest.raises(SystemExit) as excinfo:
        backup_to_baidu.main()

    assert excinfo.value.code == 0
    assert sent == []

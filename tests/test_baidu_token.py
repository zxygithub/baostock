"""Unit tests for Baidu token expiry detection and auto-refresh in scripts/backup_to_baidu.py.

All network calls are mocked; the token file is a tmp file.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backup_to_baidu


EXPIRES_IN = 2592000

OLD_TOKEN_JSON = {
    "access_token": "old-access",
    "expires_in": EXPIRES_IN,
    "refresh_token": "old-refresh",
    "scope": "basic netdisk",
    "session_key": "",
    "session_secret": "",
}

NEW_TOKEN_JSON = {
    "access_token": "new-access",
    "expires_in": EXPIRES_IN,
    "refresh_token": "new-refresh",
    "scope": "basic netdisk",
    "session_key": "",
    "session_secret": "",
}


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _write_token_file(tmp_path, monkeypatch, mtime_offset=0.0, **overrides):
    data = {**OLD_TOKEN_JSON, **overrides}
    token_file = tmp_path / "bypy.json"
    token_file.write_text(json.dumps(data), encoding="utf-8")
    stamped = time.time() + mtime_offset
    os.utime(token_file, (stamped, stamped))
    monkeypatch.setattr(backup_to_baidu, "TOKEN_FILE", token_file)
    return token_file


# ---------------------------------------------------------------------------
# load_token: proactive expiry check
# ---------------------------------------------------------------------------

def test_load_token_fresh_does_not_refresh(tmp_path, monkeypatch):
    _write_token_file(tmp_path, monkeypatch)

    with patch("backup_to_baidu.requests.post") as mock_post:
        token = backup_to_baidu.load_token()

    assert token == "old-access"
    mock_post.assert_not_called()


def test_load_token_expired_refreshes_and_persists(tmp_path, monkeypatch):
    token_file = _write_token_file(
        tmp_path, monkeypatch, mtime_offset=-(EXPIRES_IN + 3600))

    with patch("backup_to_baidu.requests.post",
               return_value=FakeResp(NEW_TOKEN_JSON)) as mock_post:
        token = backup_to_baidu.load_token()

    assert token == "new-access"
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new-access"
    assert saved["refresh_token"] == "new-refresh"

    data = mock_post.call_args.kwargs["data"]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "old-refresh"
    assert data["client_id"]
    assert data["client_secret"]


def test_load_token_expiring_within_margin_refreshes(tmp_path, monkeypatch):
    _write_token_file(
        tmp_path, monkeypatch, mtime_offset=-(EXPIRES_IN - 3600))

    with patch("backup_to_baidu.requests.post",
               return_value=FakeResp(NEW_TOKEN_JSON)) as mock_post:
        token = backup_to_baidu.load_token()

    assert token == "new-access"
    mock_post.assert_called_once()


def test_refresh_failure_raises_with_reauth_hint(tmp_path, monkeypatch):
    _write_token_file(
        tmp_path, monkeypatch, mtime_offset=-(EXPIRES_IN + 3600))

    with patch("backup_to_baidu.requests.post", return_value=FakeResp(
            {"error": "expired_token", "error_description": "refresh token has been used"})):
        with pytest.raises(RuntimeError, match="python -m bypy info"):
            backup_to_baidu.load_token()


def test_missing_token_file_raises_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_to_baidu, "TOKEN_FILE", tmp_path / "nope.json")

    with pytest.raises(RuntimeError, match="python -m bypy info"):
        backup_to_baidu.load_token()


# ---------------------------------------------------------------------------
# upload_file: reactive retry on token errno
# ---------------------------------------------------------------------------

def _fake_archive(tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"fake-archive-bytes")
    return archive


def test_precreate_token_errno_retries_after_refresh(tmp_path, monkeypatch):
    _write_token_file(tmp_path, monkeypatch)
    archive = _fake_archive(tmp_path)

    payloads = [
        {"errno": -6},
        NEW_TOKEN_JSON,
        {"errno": 0, "uploadid": "up1"},
        {"md5": "abc"},
        {"errno": 0, "fs_id": 42},
    ]
    with patch("backup_to_baidu.requests.post",
               side_effect=[FakeResp(p) for p in payloads]) as mock_post:
        ok = backup_to_baidu.upload_file("old-access", archive, "/remote/a.tar.gz")

    assert ok is True
    assert mock_post.call_count == 5
    assert mock_post.call_args_list[0].kwargs["params"]["access_token"] == "old-access"
    assert mock_post.call_args_list[2].kwargs["params"]["access_token"] == "new-access"
    saved = json.loads((tmp_path / "bypy.json").read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "new-refresh"


def test_precreate_non_auth_errno_does_not_refresh(tmp_path, monkeypatch):
    token_file = _write_token_file(tmp_path, monkeypatch)
    archive = _fake_archive(tmp_path)

    with patch("backup_to_baidu.requests.post",
               return_value=FakeResp({"errno": -7})) as mock_post:
        ok = backup_to_baidu.upload_file("old-access", archive, "/remote/a.tar.gz")

    assert ok is False
    assert mock_post.call_count == 1
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "old-refresh"

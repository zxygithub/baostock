"""Unit tests for src/utils/email_notifier.py.

Mock smtplib — no real network, no real credentials.
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.email_notifier import load_dotenv, load_email_config, send_email


# ---------------------------------------------------------------------------
# load_dotenv
# ---------------------------------------------------------------------------

def test_load_dotenv_parses_and_strips_quotes(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# comment line\n'
        '\n'
        'EMAIL_SENDER="quoted@qq.com"\n'
        "EMAIL_PASSWORD='single@qq.com'\n"
        "EMAIL_RECEIVER=naked@qq.com\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EMAIL_SENDER", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_RECEIVER", raising=False)

    load_dotenv(env)

    assert os.environ["EMAIL_SENDER"] == "quoted@qq.com"
    assert os.environ["EMAIL_PASSWORD"] == "single@qq.com"
    assert os.environ["EMAIL_RECEIVER"] == "naked@qq.com"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EMAIL_SENDER=file@qq.com\n", encoding="utf-8")
    monkeypatch.setenv("EMAIL_SENDER", "preset@qq.com")

    load_dotenv(env)

    assert os.environ["EMAIL_SENDER"] == "preset@qq.com"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    load_dotenv(tmp_path / "nope.env")  # must not raise


# ---------------------------------------------------------------------------
# load_email_config
# ---------------------------------------------------------------------------

def _set_full_env(monkeypatch, port="465"):
    monkeypatch.setenv("EMAIL_SMTP_SERVER", "smtp.qq.com")
    monkeypatch.setenv("EMAIL_SMTP_PORT", port)
    monkeypatch.setenv("EMAIL_SENDER", "sender@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "authcode")
    monkeypatch.setenv("EMAIL_RECEIVER", "receiver@qq.com")


def test_load_email_config_complete(monkeypatch):
    _set_full_env(monkeypatch, port="465")
    cfg = load_email_config()
    assert cfg == {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 465,
        "sender": "sender@qq.com",
        "password": "authcode",
        "receiver": "receiver@qq.com",
    }


def test_load_email_config_missing_field_returns_none(monkeypatch):
    _set_full_env(monkeypatch)
    monkeypatch.delenv("EMAIL_PASSWORD")
    assert load_email_config() is None


def test_load_email_config_invalid_port_returns_none(monkeypatch):
    _set_full_env(monkeypatch, port="ssl_port")
    assert load_email_config() is None


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------

CFG = {
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender": "sender@qq.com",
    "password": "authcode",
    "receiver": "receiver@qq.com",
}


def test_send_email_ssl_port_465_success():
    with patch("src.utils.email_notifier.smtplib.SMTP_SSL") as mock_ssl:
        server = MagicMock()
        mock_ssl.return_value = server
        ok = send_email(CFG, "主题", "正文")
    assert ok is True
    mock_ssl.assert_called_once_with("smtp.qq.com", 465)
    server.login.assert_called_once_with("sender@qq.com", "authcode")
    server.send_message.assert_called_once()
    server.quit.assert_called_once()
    sent_msg = server.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "主题"
    assert sent_msg["From"] == "sender@qq.com"
    assert sent_msg["To"] == "receiver@qq.com"


def test_send_email_starttls_on_non_465_port():
    cfg = dict(CFG, smtp_port=587)
    with patch("src.utils.email_notifier.smtplib.SMTP") as mock_smtp:
        server = MagicMock()
        mock_smtp.return_value = server
        ok = send_email(cfg, "主题", "正文")
    assert ok is True
    mock_smtp.assert_called_once_with("smtp.qq.com", 587)
    server.starttls.assert_called_once()
    server.login.assert_called_once()


def test_send_email_returns_false_on_login_failure():
    with patch("src.utils.email_notifier.smtplib.SMTP_SSL") as mock_ssl:
        mock_ssl.return_value = MagicMock()
        mock_ssl.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
        ok = send_email(CFG, "主题", "正文")
    assert ok is False  # never raises


def test_send_email_subtype_plain_and_html():
    with patch("src.utils.email_notifier.smtplib.SMTP_SSL") as mock_ssl:
        server = MagicMock()
        mock_ssl.return_value = server

        send_email(CFG, "s", "plain body")
        msg = server.send_message.call_args[0][0]
        assert msg.get_content_type() == "text/plain"

        send_email(CFG, "s", "<p>html body</p>", subtype="html")
        msg = server.send_message.call_args[0][0]
        assert msg.get_content_type() == "text/html"

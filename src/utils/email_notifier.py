"""Shared email utilities for baostock scripts.

Extracted from scripts/daily_report.py so the daily report and the
backup notification share one SMTP implementation.

Contract: send_email never raises — it returns True/False so callers
decide their own failure policy (backup: log & keep exit code;
daily report: sys.exit(1)).
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

# src/utils/email_notifier.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(env_path: Path | None = None) -> None:
    """Load environment variables from .env file if it exists.

    Existing environment variables win (os.environ.setdefault).
    """
    path = env_path if env_path is not None else DEFAULT_ENV_PATH
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_email_config() -> dict | None:
    """Read SMTP settings from env. Returns None if incomplete or port invalid."""
    smtp_server = os.getenv("EMAIL_SMTP_SERVER", "")
    smtp_port = os.getenv("EMAIL_SMTP_PORT", "")
    sender = os.getenv("EMAIL_SENDER", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    receiver = os.getenv("EMAIL_RECEIVER", "")

    if not all([smtp_server, smtp_port, sender, password, receiver]):
        return None
    try:
        port = int(smtp_port)
    except ValueError:
        return None

    return {
        "smtp_server": smtp_server,
        "smtp_port": port,
        "sender": sender,
        "password": password,
        "receiver": receiver,
    }


def send_email(cfg: dict, subject: str, body: str, subtype: str = "plain") -> bool:
    """Send one email. Returns True on success, False on any failure (never raises).

    Port 465 uses SMTP_SSL; any other port uses SMTP + STARTTLS.
    """
    msg = MIMEText(body, subtype, "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]

    try:
        if cfg["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"])
        else:
            server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"])
            server.starttls()
        server.login(cfg["sender"], cfg["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.warning("Failed to send email to %s: %s", cfg.get("receiver"), e)
        return False

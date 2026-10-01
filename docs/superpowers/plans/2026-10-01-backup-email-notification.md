# 百度网盘备份邮件通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次百度网盘备份（成功/失败）结束后向 `EMAIL_RECEIVER` 发送一封纯文本通知邮件。

**Architecture:** 从 `scripts/daily_report.py` 提炼公共邮件模块 `src/utils/email_notifier.py`（`load_dotenv` / `load_email_config` / `send_email`，失败返回 False 不抛出）；`scripts/backup_to_baidu.py` 收敛 `main()` 出口、采集结果字段后统一调用通知；`daily_report.py` 迁移到公共模块（行为不变）。开关走 `config.yaml` 的 `email.backup_notify`，凭据复用 `.env` 的 `EMAIL_*`。

**Tech Stack:** Python 3.11+、smtplib（stdlib）、pytest + monkeypatch（mock SMTP，无网络）。

**Spec:** `docs/superpowers/specs/2026-10-01-backup-email-notification-design.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/utils/email_notifier.py` | Create | 公共邮件模块：.env 加载、SMTP 配置解析、发信（永不抛出） |
| `tests/test_email_notifier.py` | Create | 模块单元测试（mock smtplib） |
| `scripts/daily_report.py` | Modify | 删除本地邮件三函数，改用公共模块；`build_email` 改返回 `(subject, html)` |
| `tests/test_daily_report_email.py` | Create | `build_email` 新返回契约回归测试 |
| `scripts/backup_to_baidu.py` | Modify | 结果采集 + 通知挂钩 + `--no-email`；`cleanup_old_backups` 返回删除数 |
| `tests/test_backup_notify.py` | Create | 通知触发/跳过/主题正文/退出码测试 |
| `config.yaml` | Modify | `email:` 块加 `backup_notify: true` |
| `.env.example` | Modify | 注释注明备份通知复用 EMAIL_* |
| `README.md` | Modify | 备份章节补充通知说明 + 更新日志 |

**测试导入约定**（本仓库已有惯例，见 `tests/test_download_all_skip_logic.py`）：测试文件头部把仓库根和 `scripts/` 插入 `sys.path` 后直接 `import` 脚本模块。

---

### Task 1: 公共邮件模块 `src/utils/email_notifier.py`

**Files:**
- Create: `src/utils/email_notifier.py`
- Test: `tests/test_email_notifier.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_email_notifier.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_email_notifier.py -v
```

预期：收集失败 `ModuleNotFoundError: No module named 'src.utils.email_notifier'`。

- [ ] **Step 3: 实现模块**

创建 `src/utils/email_notifier.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_email_notifier.py -v
```

预期：8 passed。

- [ ] **Step 5: Commit**

```bash
cd /home/workspace/baostock && git add src/utils/email_notifier.py tests/test_email_notifier.py && git commit -m "feat: 新增公共邮件模块 email_notifier"
```

---

### Task 2: `daily_report.py` 迁移到公共模块

行为保持不变：`email.enabled` 开关、缺配置 `sys.exit(1)`、发送失败 `sys.exit(1)`、主题/正文/收发件人完全一致。

**Files:**
- Modify: `scripts/daily_report.py`
- Test: `tests/test_daily_report_email.py`

- [ ] **Step 1: 写失败测试（build_email 新契约）**

创建 `tests/test_daily_report_email.py`：

```python
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
    assert "56789" in html
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_daily_report_email.py -v
```

预期：FAIL —— `build_email` 当前返回 `MIMEMultipart` 而非 `(subject, html)`（`TypeError: cannot unpack non-iterable MIMEMultipart`）。

- [ ] **Step 3: 改 `scripts/daily_report.py` 头部 imports**

把第 10–31 行（imports 与路径常量区）中的以下行：

```python
import smtplib
...
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
```

删除（`smtplib`/`MIMEText`/`MIMEMultipart` 迁移后不再使用），并在 `from pathlib import Path` 之后加：

```python
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.email_notifier import load_dotenv, load_email_config, send_email
```

保留 `import sys, re, os, sqlite3, baostock as bs, yaml`、`from datetime import ...` 及 `PROJECT_ROOT`/`DB_PATH`/`LOG_DIR`/`CONFIG_PATH` 常量不动。

- [ ] **Step 4: 删除本地三函数**

删除 `load_dotenv`（原 33–42 行）与 `get_email_config`（原 54–86 行）两个函数定义；删除 `send_email`（原 790–812 行）函数定义。`load_config` 保留不动。

- [ ] **Step 5: 改 `build_email` 返回 `(subject, html)`**

签名（原 696–698 行）从：

```python
def build_email(sender, start_time, end_time, yesterday_requests, total_requests,
                blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html="",
                monitor_html="", report_date=None):
```

改为：

```python
def build_email(start_time, end_time, yesterday_requests, total_requests,
                blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html="",
                monitor_html="", report_date=None):
```

函数开头（原 701–704 行）从：

```python
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BaoStock 数据下载日报 ({report_date.strftime('%Y-%m-%d')})"
    msg["From"] = sender
```

改为：

```python
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
    subject = f"BaoStock 数据下载日报 ({report_date.strftime('%Y-%m-%d')})"
```

函数结尾（原 787–788 行）从：

```python
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg
```

改为：

```python
    return subject, html
```

中间 `html = f"""..."""` 模板整段（含样式与表格）**字节级保留不动**。

- [ ] **Step 6: 改 `main()` 的配置与发送段**

`main()` 开头（原 817–820 行）从：

```python
def main():
    load_dotenv()
    cfg = load_config()
    email_cfg = get_email_config(cfg)
```

改为：

```python
def main():
    load_dotenv()
    cfg = load_config()
    if not cfg.get("email", {}).get("enabled"):
        print("Email reporting is disabled. Set email.enabled: true in config.yaml")
        sys.exit(0)
    email_cfg = load_email_config()
    if email_cfg is None:
        print("Missing email config in .env: EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, EMAIL_SENDER, etc. in .env")
        sys.exit(1)
```

`main()` 末尾（原 839–845 行）从：

```python
    msg = build_email(
        email_cfg["sender"], start_time, end_time, yesterday_requests, total_requests,
        blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html,
        monitor_html, report_date,
    )
    send_email(email_cfg, msg)
    conn.close()
```

改为：

```python
    subject, html = build_email(
        start_time, end_time, yesterday_requests, total_requests,
        blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html,
        monitor_html, report_date,
    )
    if send_email(email_cfg, subject, html, subtype="html"):
        print(f"✅ Email sent successfully to {email_cfg['receiver']}")
    else:
        print("❌ Failed to send email")
        sys.exit(1)
    conn.close()
```

- [ ] **Step 7: 运行测试确认通过 + 全量回归**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_daily_report_email.py -v && .venv/bin/python -m pytest tests/ -v
```

预期：新测试 1 passed；`tests/` 全部原有测试通过（无新增失败）。另做一次 import 冒烟：

```bash
cd /home/workspace/baostock && .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); import daily_report; print('import ok')"
```

预期输出：`import ok`。

- [ ] **Step 8: Commit**

```bash
cd /home/workspace/baostock && git add scripts/daily_report.py tests/test_daily_report_email.py && git commit -m "refactor: daily_report 迁移至公共邮件模块 email_notifier"
```

---

### Task 3: `backup_to_baidu.py` 通知挂钩

**Files:**
- Modify: `scripts/backup_to_baidu.py`
- Test: `tests/test_backup_notify.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_backup_notify.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_backup_notify.py -v
```

预期：收集失败/大量 FAIL —— `AttributeError: module 'backup_to_baidu' has no attribute 'build_subject'` 等。

- [ ] **Step 3a: 让模块可安全 import（stdout reconfigure 加护栏）**

`scripts/backup_to_baidu.py` 第 24–26 行从：

```python
# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
```

改为：

```python
# Force unbuffered output (best-effort: pytest capture objects may lack reconfigure)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
```

第 19 行 `from datetime import datetime` 之后加 imports 与路径引导：

```python
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.utils.email_notifier import load_dotenv, load_email_config, send_email
```

（`load_dotenv` 备份脚本本身不调用也会被 `notify_result` 用到；`argparse` 保持在 `main()` 内局部 import 不变。）

- [ ] **Step 3b: 新增通知函数（放在 `cleanup_old_backups` 之后、`main` 之前）**

```python
# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------
def format_size(nbytes: int) -> str:
    """Human-readable size: GB for >= 1 GiB, otherwise MB."""
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.1f} GB({nbytes:,} 字节)"
    return f"{nbytes / 1024 / 1024:.1f} MB({nbytes:,} 字节)"


def build_subject(run_date: datetime) -> str:
    """主题固定格式:证券数据baostock百度云备份结果-YYYY年MM月DD日"""
    return f"证券数据baostock百度云备份结果-{run_date.year}年{run_date.month:02d}月{run_date.day:02d}日"


def build_success_text(result: dict) -> str:
    return (
        "证券数据baostock百度云备份已完成。\n"
        "结果:成功\n"
        f"备份时间:{result['started_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"归档文件:{result['archive_name']}\n"
        f"归档大小:{format_size(result['archive_size'])}\n"
        f"远端路径:{result['remote_path']}\n"
        f"总耗时:{result['duration']:.0f} 秒\n"
        f"保留策略:保留最近 {result['keep_count']} 份,本次清理旧备份 {result['deleted_old']} 份"
    )


def build_failure_text(result: dict) -> str:
    return (
        "证券数据baostock百度云备份失败,请尽快处理。\n"
        "结果:失败\n"
        f"失败阶段:{result['stage']}\n"
        f"错误信息:{result['error']}\n"
        f"备份时间:{result['started_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"归档文件:{result['archive_name']}\n"
        "详细日志:logs/backup.log"
    )


def notify_result(result: dict, args) -> None:
    """Send the backup result email. Never raises; never affects exit code.

    Skip conditions (logged, silent): --no-email, email.backup_notify: false,
    incomplete EMAIL_* config.
    """
    try:
        if getattr(args, "no_email", False):
            logger.info("Email notification skipped (--no-email)")
            return
        cfg = load_config()
        if not cfg.get("email", {}).get("backup_notify", True):
            logger.info("Email notification disabled (email.backup_notify: false)")
            return
        load_dotenv()
        email_cfg = load_email_config()
        if email_cfg is None:
            logger.warning("Email config incomplete in .env, notification skipped")
            return
        subject = build_subject(result["started_at"])
        body = build_success_text(result) if result["success"] else build_failure_text(result)
        if send_email(email_cfg, subject, body):
            logger.info("Notification email sent to %s", email_cfg["receiver"])
        else:
            logger.warning("Notification email not sent (see warning above)")
    except Exception as e:
        logger.warning("Notification error (ignored): %s", e)
```

- [ ] **Step 3c: `cleanup_old_backups` 返回删除数**

签名从 `def cleanup_old_backups(token: str, dir_path: str, keep_count: int = 7):` 改为 `def cleanup_old_backups(token: str, dir_path: str, keep_count: int = 7) -> int:`；函数体末尾统计返回：

```python
def cleanup_old_backups(token: str, dir_path: str, keep_count: int = 7) -> int:
    """Remove old backups, keeping only the latest N. Returns number deleted."""
    files = list_remote_files(token, dir_path)
    backup_files = [f for f in files if f.get("server_filename", "").startswith("baostock_backup_")]
    if len(backup_files) <= keep_count:
        return 0
    backup_files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    deleted = 0
    for f in backup_files[keep_count:]:
        filename = f.get("server_filename")
        if filename:
            logger.info(f"Deleting old backup: {filename}")
            try:
                requests.post(FILE_API_URL,
                    params={"access_token": token, "method": "filemanager", "opera": "delete", "openapi": "xpansdk"},
                    data={"filelist": json.dumps([f"{dir_path}/{filename}"])},
                    timeout=30)
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {filename}: {e}")
    return deleted
```

（其余函数 `load_token` / `create_backup_archive` / `upload_file` / `list_remote_files` 不动。）

- [ ] **Step 3d: 重写 `main()`（出口收敛 + 通知）**

整个 `main()` 替换为：

```python
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backup baostock to Baidu Pan")
    parser.add_argument("--keep", type=int, default=7, help="Number of backups to keep")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    parser.add_argument("--no-email", action="store_true", help="Skip email notification")
    args = parser.parse_args()

    started_at = datetime.now()
    t0 = time.time()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    archive_name = f"baostock_backup_{timestamp}.tar.gz"
    result = {
        "success": False,
        "stage": "初始化",
        "error": None,
        "archive_name": archive_name,
        "archive_size": 0,
        "remote_path": f"{BACKUP_DIR}/{archive_name}",
        "duration": 0.0,
        "keep_count": args.keep,
        "deleted_old": 0,
        "started_at": started_at,
    }
    exit_code = 0
    archive_path = None

    try:
        data_dir = Path(args.data_dir)
        if not data_dir.exists():
            result["error"] = f"Data directory not found: {data_dir}"
            logger.error(result["error"])
            exit_code = 1
        else:
            try:
                token = load_token()
                logger.info("Token loaded")
            except Exception as e:
                result["error"] = str(e)
                logger.error(str(e))
                exit_code = 1

        if exit_code == 0:
            # Cleanup old local archives
            tmp_dir = Path(tempfile.gettempdir())
            for archive in tmp_dir.glob("baostock_backup_*.tar.gz"):
                logger.info(f"Cleaning up: {archive.name}")
                archive.unlink()

            archive_path = tmp_dir / archive_name
            try:
                result["stage"] = "打包"
                create_backup_archive(data_dir, archive_path)
                result["archive_size"] = archive_path.stat().st_size
                logger.info(f"Uploading to: {result['remote_path']}")

                result["stage"] = "上传"
                if upload_file(token, archive_path, result["remote_path"]):
                    result["deleted_old"] = cleanup_old_backups(token, BACKUP_DIR, args.keep)
                    result["success"] = True
                    logger.info("Backup completed successfully!")
                else:
                    result["error"] = "上传失败,详见日志"
                    logger.error("Backup failed!")
                    exit_code = 1
            except Exception as e:
                result["error"] = str(e)
                logger.error(f"Backup failed: {e}")
                exit_code = 1
    finally:
        result["duration"] = time.time() - t0
        if archive_path is not None and archive_path.exists():
            archive_path.unlink()
        notify_result(result, args)

    sys.exit(exit_code)
```

（`if __name__ == "__main__": main()` 不动。）

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_backup_notify.py -v && .venv/bin/python -m pytest tests/ -v
```

预期：`test_backup_notify.py` 11 passed；`tests/` 全部通过。再做 CLI 冒烟：

```bash
cd /home/workspace/baostock && .venv/bin/python scripts/backup_to_baidu.py --help
```

预期：usage 含 `--no-email`。

- [ ] **Step 5: Commit**

```bash
cd /home/workspace/baostock && git add scripts/backup_to_baidu.py tests/test_backup_notify.py && git commit -m "feat: 百度网盘备份结束后发送结果通知邮件"
```

---

### Task 4: 配置与文档

**Files:**
- Modify: `config.yaml`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: `config.yaml` 的 `email:` 块加开关**

第 83–87 行从：

```yaml
# ---------------------------------------------------------------------------
# Email reporting (for daily_report.py)
# ---------------------------------------------------------------------------
# Sensitive credentials (smtp_server, smtp_port, sender, password, receiver)
# should be set in .env file. Only the enabled switch stays here.
email:
  enabled: true
```

改为：

```yaml
# ---------------------------------------------------------------------------
# Email reporting (for daily_report.py / backup_to_baidu.py)
# ---------------------------------------------------------------------------
# Sensitive credentials (smtp_server, smtp_port, sender, password, receiver)
# should be set in .env file. Only the enabled switches stay here.
email:
  enabled: true        # daily_report.py 日报开关
  backup_notify: true  # backup_to_baidu.py 备份结果通知开关
```

- [ ] **Step 2: `.env.example` 补注释**

在 `EMAIL_RECEIVER=...` 行之后、`# Baidu Pan Backup Configuration` 之前加一行：

```bash
# The same EMAIL_* block above is reused by backup_to_baidu.py for
# backup result notifications.
```

- [ ] **Step 3: `README.md` 更新**

(a) 「4. 百度网盘备份」代码块末尾（`--keep 14` 示例之后）加：

```markdown
# 备份结束后自动发送结果通知邮件（复用 .env 中 EMAIL_* 配置）
# 主题格式：证券数据baostock百度云备份结果-YYYY年MM月DD日
# 关闭通知：config.yaml 中 email.backup_notify: false
# 手动静默试跑：加 --no-email
.venv/bin/python scripts/backup_to_baidu.py --no-email
```

(b) 「🔄 更新日志」列表最上方加一条：

```markdown
- **2026-10-01**：新增百度网盘备份结果邮件通知
  - **新增功能**：每次备份（成功/失败）结束后向 `EMAIL_RECEIVER` 发送一封纯文本通知邮件，主题格式 `证券数据baostock百度云备份结果-YYYY年MM月DD日`（成功失败同主题，正文首行区分）
  - **成功正文**：备份时间、归档文件、归档大小、远端路径、总耗时、保留/清理备份数；**失败正文**：失败阶段（初始化/打包/上传）、错误信息、日志位置 `logs/backup.log`
  - **公共模块**：`src/utils/email_notifier.py`（从 `daily_report.py` 提炼 `load_dotenv` / `load_email_config` / `send_email`），`daily_report.py` 同步迁移，邮件主题/正文/收发件人不变
  - **配置**：`config.yaml` 新增 `email.backup_notify` 开关（与日报 `email.enabled` 互不影响）；发信失败仅记 warning，不改变备份退出码；新增 `--no-email` 参数支持静默试跑
  - 修改文件：`src/utils/email_notifier.py`（新增）、`scripts/backup_to_baidu.py`、`scripts/daily_report.py`、`config.yaml`、`.env.example`、`tests/test_email_notifier.py`（新增）、`tests/test_daily_report_email.py`（新增）、`tests/test_backup_notify.py`（新增）
```

- [ ] **Step 4: 回归 + Commit**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/ -v
```

预期：全部通过。提交：

```bash
cd /home/workspace/baostock && git add config.yaml .env.example README.md && git commit -m "docs: 备份邮件通知配置与文档更新"
```

---

### Task 5: 手工验证（不改代码，不提交）

- [ ] **Step 1: 静默试跑验证退出码**

```bash
cd /home/workspace/baostock && .venv/bin/python scripts/backup_to_baidu.py --no-email; echo "exit=$?"
```

预期：日志出现 `Email notification skipped (--no-email)`；`exit=0`（备份成功时）。

- [ ] **Step 2: 真实发信验证（需 .env 已配置真实凭据）**

```bash
cd /home/workspace/baostock && .venv/bin/python scripts/backup_to_baidu.py
```

预期：邮箱收到主题为 `证券数据baostock百度云备份结果-2026年10月01日`（当天日期）的纯文本邮件，正文首行 `结果:成功`，字段与 Step 1 的日志一致。此步若在非备份窗口进行，可用 `--keep 2` 减少影响。

---

## Self-Review（写完计划后已执行）

1. **Spec coverage:** 触发条件（成功+失败）→ Task 3 `notify_result` + `test_main_*`；主题格式 → `build_subject`；纯文本 → `subtype="plain"`（Task 1 测试含 plain/html 分支）；收件人 `EMAIL_RECEIVER` → `load_email_config`；`email.backup_notify` 开关 + 缺省默认开 → Task 3 测试两项；`--no-email` → 测试；发信失败不影响退出码 → `test_main_send_failure_keeps_exit_0`；daily_report 行为不变 → Task 2；错误处理矩阵 8 行 → 均有对应测试或明确跳过逻辑；测试计划 2 个文件 → 实为 3 个（多一个 `test_daily_report_email.py` 覆盖迁移回归，spec 回归节要求）。无缺口。
2. **Placeholder scan:** 无 TBD/TODO。唯一"保留不动"指令（build_email 的 HTML 模板）指明了精确的锚点行号，属重构边界而非占位。
3. **Type consistency:** `send_email(cfg, subject, body, subtype="plain") -> bool` 三处一致（定义/测试/daily_report 调用）；`load_email_config() -> dict | None` 一致；`result` dict 10 个键在 `make_result`、`main()` 初始化、三个 build 函数中字段名一致（`started_at`/`archive_name`/`archive_size`/`remote_path`/`duration`/`keep_count`/`deleted_old`/`success`/`stage`/`error`）；`cleanup_old_backups -> int` 与 `result["deleted_old"]` 赋值一致。

# 数据拉取完成即发日报 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日数据拉取任务完成（正常跑完/49000 上限/日停 23:55/手动运行）时立即发送日报邮件，0:00 cron 作为兜底补发，一天一封。

**Architecture:** `daily_report.py` 增加 `--if-needed/--date/--reason` 参数与 `data/.report_sent_<日期>` 发送标记（去重单点）；`src/utils/helpers.py` 新增 `run_main_with_report(main_fn)` 完成钩子，仅在正常 return 或 `SystemExit(1)`（请求上限）时经 subprocess 调日报，崩溃/SIGINT 不发；`download_all.py`/`update_daily.py` 的 `__main__` 接入钩子；0:00 cron 改为 `--if-needed` 兜底。

**Tech Stack:** Python 3.11+、argparse、subprocess、pytest + monkeypatch（无网络）。

**Spec:** `docs/superpowers/specs/2026-10-01-daily-report-on-completion-design.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/daily_report.py` | Modify | CLI 参数、报告日参数化（3 处 `today-1` 硬编码）、发送标记、完成原因入正文 |
| `tests/test_daily_report_trigger.py` | Create | `--if-needed/--date/--reason` 行为测试（重依赖全部 mock） |
| `src/utils/helpers.py` | Modify | 新增 `send_daily_report` / `run_main_with_report` 完成钩子 |
| `tests/test_completion_report.py` | Create | 钩子退出分类测试（发/不发） |
| `scripts/download_all.py` | Modify | `__main__` 接入钩子（2 行） |
| `scripts/update_daily.py` | Modify | `__main__` 接入钩子（2 行） |
| crontab | Modify | 0:00 行加 `--if-needed --reason 次日0:00兜底补发` |
| `README.md` | Modify | 更新日志补一条 |

**命名约定（全文一致）**：`report_date`（`date` 对象）、`report_date_str`（YYYYMMDD，日志解析用）、`day_requests`（报告日请求数）、`report_marker_path()`、`DATA_DIR`、`run_main_with_report`、`send_daily_report`、`--if-needed`/`--date`/`--reason`。

**测试导入约定**（本仓库既有惯例）：测试文件头部 `sys.path.insert` 后直接 import 脚本/模块；重依赖用 `monkeypatch.setattr` 桩掉，不碰真实 DB/SMTP。

---

### Task 1: `daily_report.py` 参数化 + 标记 + 完成原因

**Files:**
- Modify: `scripts/daily_report.py`
- Test: `tests/test_daily_report_trigger.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_daily_report_trigger.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_daily_report_trigger.py -q`
Expected: FAIL/ERROR —— 首先在 `monkeypatch.setattr(daily_report, "DATA_DIR", ...)` 处 `AttributeError: <module 'daily_report'> has no attribute 'DATA_DIR'`（模块尚无该属性与新行为）。

- [ ] **Step 3a: imports 与常量**

`scripts/daily_report.py` 顶部 imports（约第 10 行起）改为：

```python
import argparse
import sys
import re
import os
import sqlite3
import baostock as bs
from pathlib import Path
from datetime import datetime, date, timedelta
```

（`argparse` 新增；其余顺序不变。后续 `import yaml`、`sys.path.insert`、email_notifier import 不动。）

路径常量区（`DB_PATH` 之后）加一行：

```python
DATA_DIR = PROJECT_ROOT / "data"
```

- [ ] **Step 3b: 新增 `report_marker_path` 与 `parse_args`**

放在 `load_config()` 之后：

```python
def report_marker_path(report_date):
    return DATA_DIR / f".report_sent_{report_date.isoformat()}"


def parse_args():
    parser = argparse.ArgumentParser(description="BaoStock daily download status email report")
    parser.add_argument("--if-needed", action="store_true",
                        help="Skip sending if the report for the date already went out")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                        help="Report date (default: yesterday)")
    parser.add_argument("--reason", default="",
                        help="Completion reason shown in the email body")
    return parser.parse_args()
```

- [ ] **Step 3c: `get_db_stats` 接受报告日**

整体替换为：

```python
def get_db_stats(report_date):
    conn = sqlite3.connect(str(DB_PATH))

    day_str = report_date.isoformat()
    cursor = conn.execute("SELECT count FROM request_count WHERE date = ?", (day_str,))
    row = cursor.fetchone()
    day_requests = row[0] if row else 0

    total_requests = conn.execute("SELECT COALESCE(SUM(count), 0) FROM request_count").fetchone()[0]

    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    counts = {}
    for (t,) in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except:
            counts[t] = 0

    return conn, day_requests, total_requests, counts
```

- [ ] **Step 3d: `get_api_request_estimates` 去掉 `today-1` 硬编码**

签名（约第 240 行）从 `def get_api_request_estimates(conn, precise_est=None):` 改为：

```python
def get_api_request_estimates(conn, precise_est=None, report_date=None):
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
```

（`if report_date is None` 两行为函数体第一段。）函数体内的日期查询（约第 278–283 行）从：

```python
    daily_limit = conn.execute(
        "SELECT count FROM request_count WHERE date = ?",
        ((date.today() - timedelta(days=1)).isoformat(),)
    ).fetchone()
    today_count = daily_limit[0] if daily_limit else 0
```

改为：

```python
    day_count_row = conn.execute(
        "SELECT count FROM request_count WHERE date = ?",
        (report_date.isoformat(),)
    ).fetchone()
    today_count = day_count_row[0] if day_count_row else 0
```

（返回键 `"today_count"` 保持不变，避免破坏未知消费方。）

- [ ] **Step 3e: `get_progress_table` 透传报告日**

签名与首两行（约第 300 行）从：

```python
def get_progress_table(conn, counts):
    estimates = get_precise_estimates(conn, counts)
    api_req = get_api_request_estimates(conn, estimates)
```

改为：

```python
def get_progress_table(conn, counts, report_date):
    estimates = get_precise_estimates(conn, counts)
    api_req = get_api_request_estimates(conn, estimates, report_date)
```

- [ ] **Step 3f: `build_email` 加 `reason` 与标签改名**

签名从：

```python
def build_email(start_time, end_time, yesterday_requests, total_requests,
                blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html="",
                monitor_html="", report_date=None):
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
    subject = f"BaoStock 数据下载日报 ({report_date.strftime('%Y-%m-%d')})"

    pct_used = (yesterday_requests / api_req["daily_limit"] * 100) if api_req["daily_limit"] else 0
    est_days = api_req["days_remaining"]
```

改为：

```python
def build_email(start_time, end_time, day_requests, total_requests,
                blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html="",
                monitor_html="", report_date=None, reason=""):
    if report_date is None:
        report_date = date.today() - timedelta(days=1)
    subject = f"BaoStock 数据下载日报 ({report_date.strftime('%Y-%m-%d')})"

    pct_used = (day_requests / api_req["daily_limit"] * 100) if api_req["daily_limit"] else 0
    est_days = api_req["days_remaining"]
    reason_html = f'<p><span class="card-label">✅ 完成原因:</span> {reason}</p>' if reason else ""
```

模板第一张信息卡（`<div class="card">` 开头）从：

```html
            <div class="card">
                <p><span class="card-label">⏱️ 最近一次拉取开始时间:</span> {start_time}</p>
                <p><span class="card-label">⏱️ 最近一次拉取结束时间:</span> {end_time}</p>
                <p><span class="card-label">📈 昨日已使用请求次数:</span> {yesterday_requests:,} 次 ({pct_used:.0f}%)</p>
```

改为：

```html
            <div class="card">
                {reason_html}
                <p><span class="card-label">⏱️ 最近一次拉取开始时间:</span> {start_time}</p>
                <p><span class="card-label">⏱️ 最近一次拉取结束时间:</span> {end_time}</p>
                <p><span class="card-label">📈 当日已使用请求次数:</span> {day_requests:,} 次 ({pct_used:.0f}%)</p>
```

（其余模板不动。）

- [ ] **Step 3g: 重写 `main()`**

整体替换 `main()`（含其后 `if __name__ == "__main__": main()` 不动）：

```python
def main():
    args = parse_args()
    if args.date:
        report_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        report_date = date.today() - timedelta(days=1)

    marker = report_marker_path(report_date)
    if args.if_needed and marker.exists():
        print(f"Report for {report_date} already sent, skipping.")
        return

    load_dotenv()
    cfg = load_config()
    if not cfg.get("email", {}).get("enabled"):
        print("Email reporting is disabled. Set email.enabled: true in config.yaml")
        sys.exit(0)
    email_cfg = load_email_config()
    if email_cfg is None:
        print("Missing email config in .env: EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT, EMAIL_SENDER, etc. in .env")
        sys.exit(1)

    conn, day_requests, total_requests, counts = get_db_stats(report_date)
    start_time, end_time = get_latest_download_times()
    blacklist_status, blacklist_detail = check_blacklist_status()
    table_rows, api_req = get_progress_table(conn, counts, report_date)

    report_date_str = report_date.strftime("%Y%m%d")
    api_log = parse_api_request_log(target_date=report_date_str)
    api_analysis_html = build_api_analysis_section(api_log) if api_log else ""

    monitor_data = get_monitor_events()
    monitor_html = build_monitor_section(monitor_data) if monitor_data else ""

    subject, html = build_email(
        start_time, end_time, day_requests, total_requests,
        blacklist_status, blacklist_detail, table_rows, api_req, api_analysis_html,
        monitor_html, report_date, reason=args.reason,
    )
    if send_email(email_cfg, subject, html, subtype="html"):
        print(f"✅ Email sent successfully to {email_cfg['receiver']}")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{datetime.now().isoformat()} {args.reason}\n", encoding="utf-8")
    else:
        print("❌ Failed to send email")
        sys.exit(1)
    conn.close()
```

（相比旧 main：新增参数/标记逻辑；`parse_api_request_log` 只调用一次——旧代码第一次无参调用的结果被立即覆盖，属死代码，顺手清除；`build_email` 调用改传 `report_date` 与 `reason`。）

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_daily_report_trigger.py -q`
Expected: 7 passed。
Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/ -q`
Expected: 全部通过（含既有 `test_daily_report_email.py`——`build_email` 仅追加参数与内部改名，位置调用兼容）。

- [ ] **Step 5: Commit**

```bash
cd /home/workspace/baostock && git add scripts/daily_report.py tests/test_daily_report_trigger.py && git commit -m "feat: 日报支持报告日参数、完成原因与发送标记去重"
```

---

### Task 2: `helpers.py` 完成钩子

**Files:**
- Modify: `src/utils/helpers.py`
- Test: `tests/test_completion_report.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_completion_report.py`：

```python
"""Unit tests for src.utils.helpers.run_main_with_report completion hook."""

import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import helpers


def _capture_send(monkeypatch):
    sent = []
    monkeypatch.setattr(helpers, "send_daily_report",
                        lambda reason, logger=None: sent.append(reason))
    return sent


def _stub_shutdown(monkeypatch, value):
    monkeypatch.setattr("src.downloaders.base.is_past_shutdown_time", lambda: value)


def test_normal_return_sends_completion_reason(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, False)

    helpers.run_main_with_report(lambda: None)

    assert sent == ["数据拉取完成(全部已更新)"]


def test_shutdown_time_sends_shutdown_reason(monkeypatch):
    sent = _capture_send(monkeypatch)
    _stub_shutdown(monkeypatch, True)

    helpers.run_main_with_report(lambda: None)

    assert sent == ["达到每日停止时间(23:55)"]


def test_systemexit_1_sends_limit_reason(monkeypatch):
    sent = _capture_send(monkeypatch)

    def hit_limit():
        raise SystemExit(1)

    helpers.run_main_with_report(hit_limit)

    assert sent == ["达到每日请求上限(49000)"]


def test_keyboardinterrupt_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        helpers.run_main_with_report(interrupted)

    assert sent == []


def test_generic_exception_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def crashed():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        helpers.run_main_with_report(crashed)

    assert sent == []


def test_systemexit_string_propagates_and_skips(monkeypatch):
    sent = _capture_send(monkeypatch)

    def blacklisted():
        raise SystemExit("IP blacklisted.")

    with pytest.raises(SystemExit):
        helpers.run_main_with_report(blacklisted)

    assert sent == []


def test_send_daily_report_invokes_with_flags(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return MagicMock(returncode=0)

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    helpers.send_daily_report("测试原因")

    cmd, kwargs = calls[0]
    assert cmd[1].endswith("scripts/daily_report.py")
    assert "--if-needed" in cmd
    assert cmd[cmd.index("--date") + 1] == date.today().isoformat()
    assert cmd[cmd.index("--reason") + 1] == "测试原因"
    assert kwargs["timeout"] == 120


def test_send_daily_report_swallows_subprocess_errors(monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(helpers.subprocess, "run", boom)

    helpers.send_daily_report("reason")  # must not raise
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_completion_report.py -q`
Expected: FAIL/ERROR —— `AttributeError: ... no attribute 'send_daily_report'`（或 import 后 `run_main_with_report` 不存在）。

- [ ] **Step 3: 实现钩子**

`src/utils/helpers.py` 顶部 imports 从：

```python
import logging
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
```

改为：

```python
import logging
import subprocess
import sys
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path
```

`__all__` 列表追加两个名字（保持字母序）：

```python
__all__ = [
    "batch_iterable",
    "convert_stock_code",
    "convert_time_format",
    "convert_turn_field",
    "fetch_all_rows",
    "get_current_quarter",
    "run_main_with_report",
    "safe_float",
    "safe_int",
    "send_daily_report",
    "setup_logging",
]
```

文件末尾追加：

```python
def send_daily_report(reason: str, logger: logging.Logger | None = None) -> None:
    """Trigger daily_report.py in a subprocess. Never raises."""
    log = logger or logging.getLogger("baostock")
    script = Path(__file__).resolve().parents[2] / "scripts" / "daily_report.py"
    cmd = [
        sys.executable, str(script),
        "--if-needed",
        "--date", date.today().isoformat(),
        "--reason", reason,
    ]
    try:
        result = subprocess.run(cmd, timeout=120, check=False)
        if result.returncode != 0:
            log.warning("daily_report exited %s (fallback cron will retry)", result.returncode)
    except Exception as e:
        log.warning("daily_report send failed (fallback cron will retry): %s", e)


def run_main_with_report(main_fn, logger: logging.Logger | None = None) -> None:
    """Run main_fn; send the daily report on completion exits only.

    Completion = normal return (data up to date / daily shutdown) or
    SystemExit(1) (daily request limit). KeyboardInterrupt and other
    exceptions propagate untouched — those runs get restarted by the
    monitor and never "completed".
    """
    from src.downloaders.base import is_past_shutdown_time

    reason = None
    try:
        main_fn()
    except SystemExit as e:
        if e.code != 1:
            raise
        reason = "达到每日请求上限(49000)"
    else:
        reason = ("达到每日停止时间(23:55)"
                  if is_past_shutdown_time() else "数据拉取完成(全部已更新)")
    if reason is not None:
        send_daily_report(reason, logger)
```

（`is_past_shutdown_time` 用函数内 import——与 `base.py` 内 `from src.db_manager import ...` 的既有延迟导入风格一致，且避免 helpers↔downloaders 顶层依赖。）

- [ ] **Step 4: 运行测试确认通过 + 回归**

Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/test_completion_report.py -q`
Expected: 8 passed。
Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/ -q`
Expected: 全部通过。

- [ ] **Step 5: Commit**

```bash
cd /home/workspace/baostock && git add src/utils/helpers.py tests/test_completion_report.py && git commit -m "feat: 新增拉取完成即发日报钩子 run_main_with_report"
```

---

### Task 3: 两个下载脚本接入钩子

**Files:**
- Modify: `scripts/download_all.py`
- Modify: `scripts/update_daily.py`

- [ ] **Step 1: `download_all.py` 接入**

imports（约第 19 行）从：

```python
from src.utils.helpers import setup_logging
```

改为：

```python
from src.utils.helpers import run_main_with_report, setup_logging
```

文件末尾从：

```python
if __name__ == "__main__":
    main()
```

改为：

```python
if __name__ == "__main__":
    run_main_with_report(main)
```

- [ ] **Step 2: `update_daily.py` 接入**

imports（约第 16 行）从：

```python
from src.utils.helpers import setup_logging
```

改为：

```python
from src.utils.helpers import run_main_with_report, setup_logging
```

文件末尾 `if __name__ == "__main__": main()` 同 Step 1 改为 `run_main_with_report(main)`。

- [ ] **Step 3: 验证**

Run: `cd /home/workspace/baostock && .venv/bin/python -m pytest tests/ -q`
Expected: 全部通过（Task 2 的钩子测试覆盖行为；本任务仅接线）。
Run: `cd /home/workspace/baostock && .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); import download_all, update_daily; print('import ok')"`
Expected: `import ok`。

- [ ] **Step 4: Commit**

```bash
cd /home/workspace/baostock && git add scripts/download_all.py scripts/update_daily.py && git commit -m "feat: download_all/update_daily 接入完成即发日报钩子"
```

---

### Task 4: crontab 兜底 + README

**Files:**
- Modify: crontab（系统）
- Modify: `README.md`

- [ ] **Step 1: 更新 crontab**

Run:

```bash
crontab -l | sed 's|python scripts/daily_report.py >>|python scripts/daily_report.py --if-needed --reason 次日0:00兜底补发 >>|' | crontab -
crontab -l | grep daily_report
```

Expected 输出含：

```
0 0 * * * cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py --if-needed --reason 次日0:00兜底补发 >> logs/cron_daily_report.log 2>&1
```

（其余 crontab 行不变。）

- [ ] **Step 2: README 更新日志**

「🔄 更新日志」列表最上方加：

```markdown
- **2026-10-01**：日报改为数据拉取完成即发
  - **行为变更**：拉取任务完成（全部更新 / 49000 请求上限 / 日停 23:55 / 手动运行）时立即发送日报，不再等到 0:00
  - **完成原因**：正文信息卡新增「完成原因」行（数据拉取完成/达到每日停止时间/达到每日请求上限），标签「昨日已使用请求次数」改为「当日已使用请求次数」
  - **一天一封**：`data/.report_sent_<日期>` 标记去重，先到先得；发送失败不写标记
  - **兜底保证**：崩溃/被强杀/整日宕机等无法即时发信的情况，由 0:00 cron 以 `--if-needed` 补发（检查昨日标记），最迟次日 0:00 必达
  - **新参数**：`daily_report.py --if-needed --date YYYY-MM-DD --reason 文本`
  - 修改文件：`scripts/daily_report.py`、`scripts/download_all.py`、`scripts/update_daily.py`、`src/utils/helpers.py`、`tests/test_daily_report_trigger.py`（新增）、`tests/test_completion_report.py`（新增）
```

- [ ] **Step 3: 回归 + Commit**

```bash
cd /home/workspace/baostock && .venv/bin/python -m pytest tests/ -q
```

Expected: 全部通过。

```bash
cd /home/workspace/baostock && git add README.md && git commit -m "docs: 日报改为完成即发的配置与文档更新"
```

---

### Task 5: 手工验证（不改代码，不提交）

- [ ] **Step 1: 真实发信 + 去重验证**

```bash
cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py --date $(date +%F) --reason 手工验证-1
```

预期：邮箱收到主题 `BaoStock 数据下载日报 (<今天>)` 的邮件，正文含「✅ 完成原因: 手工验证-1」；随后：

```bash
cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py --if-needed --date $(date +%F) --reason 手工验证-2
```

预期：打印 `Report for <今天> already sent, skipping.`，**不再发信**（标记去重生效）。

- [ ] **Step 2: 兜底补发验证（可选）**

```bash
rm -f /home/workspace/baostock/data/.report_sent_$(date +%F)
cd /home/workspace/baostock && .venv/bin/python scripts/daily_report.py --if-needed --date $(date +%F) --reason 手工验证-兜底
```

预期：标记删除后重新发出（模拟 0:00 兜底路径）。

---

## Self-Review（写完计划后已执行）

1. **Spec coverage:** 触发/不触发矩阵 → Task 2 的 6 个退出分类测试逐一对应；`--if-needed` 去重+失败不写标记 → Task 1 测试 1/3/7；`--date` 参数化 3 处 `today-1` 硬编码（get_db_stats / get_api_request_estimates / build_email 默认值）→ Step 3c/3d/3f；`--reason` 入正文 → Step 3f；标签改名 → Step 3f；标记文件路径/内容 → Step 3b/3g；0:00 兜底 cron → Task 4；两脚本接入 → Task 3；手工验证含去重与兜底 → Task 5。无缺口。
2. **Placeholder scan:** 无 TBD/TODO；所有改动步骤均给出前后完整代码；唯一"其余模板不动"指明了精确锚点，属重构边界而非占位。
3. **Type consistency:** `report_date: date` 贯穿 `get_db_stats(report_date)` / `get_api_request_estimates(..., report_date)` / `get_progress_table(..., report_date)` / `build_email(..., report_date, reason)`；`run_main_with_report(main_fn, logger=None)` 与 `send_daily_report(reason, logger=None)` 在实现与测试中签名一致；`DATA_DIR` / `report_marker_path` / `day_requests` 命名全文一致；返回键 `today_count` 保留（Step 3d 注明）。

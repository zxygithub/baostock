# SQLite 结构完整性检查脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立脚本 `scripts/check_sqlite_structure.py`,对 `data/baostock.db` 做物理结构校验(页面/freelist/索引/schema),损坏时发邮件告警并以退出码反映状态。

**Architecture:** 单文件 CLI 脚本,分两层检查:秒级前置层(头部一致性、freelist 链遍历、schema 可读,纯只读)+ 深度层(`PRAGMA integrity_check`,可 `--quick` 跳过)。每个检查产出统一 `CheckResult`,汇总为 JSON/TXT 报告;`status != healthy` 时经 `src/utils/email_notifier` 发 HTML 告警邮件。测试全部在 tmp 小库上注入损坏验证,不接触真库。

**Tech Stack:** Python 3.10+(stdlib: `sqlite3`/`struct`/`argparse`/`json`/`dataclasses`)、pytest(venv 已装 9.0.3)、复用 `src.config.DB_PATH` 与 `src/utils/email_notifier`。

**Spec:** `docs/superpowers/specs/2026-10-04-sqlite-structure-check-design.md`

**提交策略(覆盖模板中的 commit 步骤):** 本计划执行期间**不执行任何 `git commit`**(用户未明确要求)。每个任务完成后停在"测试通过"状态;用户要求提交时再统一提交。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/check_sqlite_structure.py` | 创建 | CLI + 四个检查函数 + 报告生成 + 邮件告警(单一职责:结构校验) |
| `tests/test_check_sqlite_structure.py` | 创建 | 9 组测试:损坏注入验证每个检查的报警行为 + E2E 退出码 + 邮件接线 |
| `README.md` | 修改 | 快速开始代码块中补充结构检查用法 |

依赖方向:`check_sqlite_structure.py` → `src.config`、`src.utils.email_notifier`(单向,不反向依赖)。测试文件通过 `sys.path.insert` 引入 `scripts/`(与 `tests/test_daily_report_email.py` 相同模式)。

**运行命令约定**(均在项目根 `/home/workspace/baostock` 下执行):

- 测试:`.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
- 脚本:`.venv/bin/python scripts/check_sqlite_structure.py [参数]`

---

### Task 1: 模块骨架 + CheckResult + header 检查

**Files:**
- Create: `scripts/check_sqlite_structure.py`
- Test: `tests/test_check_sqlite_structure.py`

- [ ] **Step 1: 写失败测试(测试文件全部辅助函数在此步定义)**

创建 `tests/test_check_sqlite_structure.py`:

```python
"""tests/test_check_sqlite_structure.py

SQLite 结构检查脚本的损坏注入测试。
全部在 tmp_path 小库上进行,绝不接触 data/baostock.db。
"""

import sqlite3
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_sqlite_structure as css


# ---------------------------------------------------------------------------
# 辅助函数:小库构造与损坏注入
# ---------------------------------------------------------------------------

PAGE_SIZE = 4096


def _make_db(path: Path, rows: int = 50) -> None:
    """建一个含表+索引的小型健康库并关闭连接(默认 rollback journal,字节可预测)。"""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.execute("CREATE INDEX idx_t_a ON t (a)")
    conn.executemany("INSERT INTO t VALUES (?, ?)",
                     [(i, f"row-{i}") for i in range(rows)])
    conn.commit()
    conn.close()


def _make_db_with_freelist(path: Path) -> int:
    """建一个 DROP 大表后产生空闲页的库,返回 header 里的 freelist_count。"""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE big (x BLOB)")
    conn.executemany("INSERT INTO big VALUES (?)",
                     [(b"x" * 200,) for _ in range(2000)])
    conn.commit()
    conn.execute("DROP TABLE big")
    conn.commit()
    conn.close()
    return _read_header(path)["freelist_count"]


def _read_header(path: Path) -> dict:
    with open(path, "rb") as f:
        hdr = f.read(100)
    return {
        "page_size": struct.unpack(">H", hdr[16:18])[0] or 65536,
        "page_count": struct.unpack(">I", hdr[28:32])[0],
        "freelist_head": struct.unpack(">I", hdr[32:36])[0],
        "freelist_count": struct.unpack(">I", hdr[36:40])[0],
    }


def _patch_bytes(path: Path, offset: int, data: bytes) -> None:
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)


def _truncate(path: Path, drop_pages: int = 1) -> None:
    size = path.stat().st_size
    path.truncate(size - drop_pages * PAGE_SIZE)


def test_healthy_db_header_passes(tmp_path):
    db = tmp_path / "ok.db"
    _make_db(db)
    r = css.check_header(db)
    assert r.status == "pass"
    assert r.errors == []
    assert r.layer == "preflight"


def test_truncated_file_header_fails(tmp_path):
    db = tmp_path / "trunc.db"
    _make_db(db, rows=200)
    _truncate(db, drop_pages=1)
    r = css.check_header(db)
    assert r.status == "fail"
    assert any("文件大小" in e for e in r.errors)


def test_bad_magic_header_fails(tmp_path):
    db = tmp_path / "magic.db"
    _make_db(db)
    _patch_bytes(db, 0, b"NOTSQLIT")
    r = css.check_header(db)
    assert r.status == "fail"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: FAIL/ERROR,`ModuleNotFoundError: No module named 'check_sqlite_structure'`(或 `AttributeError: check_header`)。

- [ ] **Step 3: 写最小实现**

创建 `scripts/check_sqlite_structure.py`:

```python
"""SQLite 物理结构完整性检查脚本。

对数据库做物理结构校验:页面结构、freelist 链、索引结构、schema 可读性。
分两层:
  - 前置层(秒级,总是运行):header 一致性 / freelist 链 / schema 可读
  - 深度层(默认运行,--quick 跳过):PRAGMA integrity_check
      (15GB 库实测约 75 分钟,建议每周低峰期运行)

退出码:0=健康 / 1=发现损坏 / 2=检查器自身出错。
发现损坏时经 src/utils/email_notifier 发告警邮件(--no-email 关闭)。

本脚本绝不写库:所有 SQLite 语句均为只读,且连接启用 PRAGMA query_only。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

MAGIC = b"SQLite format 3\x00"
MAX_REPORTED_ERRORS = 200


@dataclass
class CheckResult:
    """单项检查结果。status 取值:pass / fail。"""
    name: str
    layer: str          # "preflight" | "deep"
    status: str
    detail: str
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


def check_header(db_path: Path) -> CheckResult:
    """前置层 1:头部一致性。捕获文件截断、头部损坏。"""
    start = time.monotonic()
    errors: list[str] = []
    try:
        size = db_path.stat().st_size
        with open(db_path, "rb") as f:
            hdr = f.read(100)
    except OSError as e:
        return CheckResult("header", "preflight", "fail", f"无法读取文件: {e}",
                           [str(e)], time.monotonic() - start)
    if len(hdr) < 100 or hdr[:16] != MAGIC:
        return CheckResult("header", "preflight", "fail", "文件头魔数非法",
                           ["SQLite 魔数不匹配"], time.monotonic() - start)
    page_size = struct.unpack(">H", hdr[16:18])[0] or 65536
    page_count = struct.unpack(">I", hdr[28:32])[0]
    if not (512 <= page_size <= 65536) or (page_size & (page_size - 1)) != 0:
        errors.append(f"page_size 非法: {page_size}")
    expected = page_size * page_count
    if size != expected:
        errors.append(
            f"文件大小 {size} != page_size×page_count ({page_size}×{page_count}={expected})")
    detail = f"page_size={page_size}, page_count={page_count}, file_size={size}"
    return CheckResult("header", "preflight", "fail" if errors else "pass",
                       detail, errors, time.monotonic() - start)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 3 passed。

---

### Task 2: freelist 链检查

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `check_freelist`)
- Test: `tests/test_check_sqlite_structure.py`(追加 3 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def test_freelist_healthy_passes(tmp_path):
    db = tmp_path / "fl_ok.db"
    n = _make_db_with_freelist(db)
    assert n > 0, "fixture 必须产生空闲页"
    r = css.check_freelist(db)
    assert r.status == "pass"
    assert r.errors == []


def test_freelist_count_mismatch_fails(tmp_path):
    db = tmp_path / "fl_count.db"
    n = _make_db_with_freelist(db)
    # 改写 header freelist_count(偏移 36,4 字节大端)+1
    _patch_bytes(db, 36, struct.pack(">I", n + 1))
    r = css.check_freelist(db)
    assert r.status == "fail"
    assert any("计数不符" in e for e in r.errors)


def test_freelist_cycle_fails(tmp_path):
    db = tmp_path / "fl_cycle.db"
    _make_db_with_freelist(db)
    head = _read_header(db)["freelist_head"]
    assert head > 0
    # 把 trunk 页的 next 指针(页首 4 字节)指回自身 → 成环
    _patch_bytes(db, (head - 1) * PAGE_SIZE, struct.pack(">I", head))
    r = css.check_freelist(db)
    assert r.status == "fail"
    assert any("成环" in e for e in r.errors)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k freelist`
Expected: FAIL,`AttributeError: check_freelist`。

- [ ] **Step 3: 写实现**

追加到 `scripts/check_sqlite_structure.py`(`check_header` 之后):

```python
def check_freelist(db_path: Path) -> CheckResult:
    """前置层 2:freelist 链遍历。捕获环/越界/重复/计数不符。

    只解析 trunk 页结构([next_trunk][nleaf][leaf...]);leaf 空闲页内容
    属历史残留,不解析。
    """
    start = time.monotonic()
    errors: list[str] = []
    try:
        with open(db_path, "rb") as f:
            hdr = f.read(100)
            page_size = struct.unpack(">H", hdr[16:18])[0] or 65536
            page_count = struct.unpack(">I", hdr[28:32])[0]
            head = struct.unpack(">I", hdr[32:36])[0]
            count_hdr = struct.unpack(">I", hdr[36:40])[0]

            trunks: set[int] = set()
            leaves: set[int] = set()
            trunk = head
            while trunk:
                if trunk in trunks:
                    errors.append(f"trunk 链成环: 页面 {trunk}")
                    break
                if not (1 <= trunk <= page_count):
                    errors.append(f"trunk 越界: 页面 {trunk}")
                    break
                trunks.add(trunk)
                f.seek((trunk - 1) * page_size)
                data = f.read(page_size)
                if len(data) < page_size:
                    errors.append(f"trunk 读取失败: 页面 {trunk}")
                    break
                next_trunk, nleaf = struct.unpack(">II", data[:8])
                if nleaf > page_size // 4:
                    errors.append(f"trunk {trunk} 的 leaf 数非法: {nleaf}")
                    break
                for i in range(nleaf):
                    leaf = struct.unpack(">I", data[8 + 4 * i:12 + 4 * i])[0]
                    if not (1 <= leaf <= page_count):
                        errors.append(f"leaf 越界: 页面 {leaf} (trunk {trunk})")
                    elif leaf in leaves or leaf in trunks:
                        errors.append(f"leaf 重复: 页面 {leaf} (trunk {trunk})")
                    else:
                        leaves.add(leaf)
                trunk = next_trunk
    except OSError as e:
        return CheckResult("freelist", "preflight", "fail", f"读取失败: {e}",
                           [str(e)], time.monotonic() - start)

    overlap = trunks & leaves
    if overlap:
        errors.append(f"leaf 与 trunk 重叠: {sorted(overlap)[:5]}")
    total = len(trunks) + len(leaves)
    if total != count_hdr:
        errors.append(f"freelist 计数不符: 链内 {total} vs header {count_hdr}")
    detail = f"trunks={len(trunks)}, leaves={len(leaves)}, header_count={count_hdr}"
    return CheckResult("freelist", "preflight", "fail" if errors else "pass",
                       detail, errors, time.monotonic() - start)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 6 passed(3 旧 + 3 新)。

---

### Task 3: 只读连接 + schema 检查

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `_connect`、`check_schema`)
- Test: `tests/test_check_sqlite_structure.py`(追加 2 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def test_schema_healthy_passes(tmp_path):
    db = tmp_path / "sch_ok.db"
    _make_db(db)
    r = css.check_schema(db)
    assert r.status == "pass"
    assert "schema 对象数" in r.detail


def test_schema_corrupted_fails(tmp_path):
    db = tmp_path / "sch_bad.db"
    _make_db(db)
    # 破坏 page 1(即 sqlite_master 根页)的页头区(偏移 100 起 8 字节)
    _patch_bytes(db, 100, b"\x00" * 8)
    r = css.check_schema(db)
    assert r.status == "fail"
    assert r.errors
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k schema`
Expected: FAIL,`AttributeError: check_schema`。

- [ ] **Step 3: 写实现**

追加到 `scripts/check_sqlite_structure.py`(`check_freelist` 之后):

```python
def _connect(db_path: Path) -> sqlite3.Connection:
    """打开只读连接:query_only 兜底防写,语句层面也只执行读操作。

    不用 URI mode=ro:WAL 恢复可能因只读连接失败;普通连接 + query_only
    与应用日常读连接行为一致,且引擎级拒绝任何写。
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only = ON")
    return conn


def check_schema(db_path: Path) -> CheckResult:
    """前置层 3:schema 可读性。捕获 sqlite_master 所在页损坏。"""
    start = time.monotonic()
    try:
        conn = _connect(db_path)
        try:
            total = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return CheckResult("schema", "preflight", "fail",
                           f"sqlite_master 读取失败: {e}", [str(e)],
                           time.monotonic() - start)
    detail = f"schema 对象数={total}, 表/索引对象={len(names)}"
    return CheckResult("schema", "preflight", "pass", detail, [],
                       time.monotonic() - start)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 8 passed。

---

### Task 4: 深度层 integrity_check + run_checks 编排

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `check_integrity`、`run_checks`、`summarize`)
- Test: `tests/test_check_sqlite_structure.py`(追加 3 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def _corrupt_index_root(path: Path) -> None:
    """找到 idx_t_a 的根页并破坏其页头 8 字节。"""
    conn = sqlite3.connect(str(path))
    root = conn.execute(
        "SELECT rootpage FROM sqlite_master WHERE name='idx_t_a'").fetchone()[0]
    conn.close()
    _patch_bytes(path, (root - 1) * PAGE_SIZE, b"\x00" * 8)


def test_integrity_healthy_passes(tmp_path):
    db = tmp_path / "int_ok.db"
    _make_db(db)
    r = css.check_integrity(db)
    assert r.status == "pass"
    assert r.layer == "deep"


def test_integrity_index_corrupt_fails(tmp_path):
    db = tmp_path / "int_bad.db"
    _make_db(db)
    _corrupt_index_root(db)
    r = css.check_integrity(db)
    assert r.status == "fail"
    assert r.errors


def test_run_checks_quick_skips_deep(tmp_path):
    db = tmp_path / "quick.db"
    _make_db(db)
    results, skipped = css.run_checks(db, quick=True)
    assert skipped is True
    assert all(r.layer == "preflight" for r in results)
    assert len(results) == 3

    results2, skipped2 = css.run_checks(db, quick=False)
    assert skipped2 is False
    assert len(results2) == 4
    assert results2[-1].name == "integrity_check"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k "integrity or run_checks"`
Expected: FAIL,`AttributeError: check_integrity`。

- [ ] **Step 3: 写实现**

追加到 `scripts/check_sqlite_structure.py`(`check_schema` 之后):

```python
def check_integrity(db_path: Path, max_errors: int = MAX_REPORTED_ERRORS) -> CheckResult:
    """深度层:PRAGMA integrity_check。

    覆盖:页面重复使用/未使用、b-tree 键序、cell 偏移、溢出链、
    索引↔表内容一致性、freelist 计数、pointer-map。错误列表截断到 max_errors 条。
    """
    start = time.monotonic()
    try:
        conn = _connect(db_path)
        try:
            rows = [r[0] for r in conn.execute("PRAGMA integrity_check")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return CheckResult("integrity_check", "deep", "fail",
                           f"integrity_check 执行失败: {e}", [str(e)],
                           time.monotonic() - start)
    if rows == ["ok"]:
        return CheckResult("integrity_check", "deep", "pass",
                           "PRAGMA integrity_check = ok", [],
                           time.monotonic() - start)
    errors = rows[:max_errors]
    detail = (f"PRAGMA integrity_check 报告 {len(rows)} 条错误"
              f"(展示前 {len(errors)} 条)")
    return CheckResult("integrity_check", "deep", "fail", detail, errors,
                       time.monotonic() - start)


def run_checks(db_path: Path, quick: bool = False) -> tuple[list[CheckResult], bool]:
    """按序执行全部检查,返回 (结果列表, 是否跳过深度层)。"""
    results = [
        check_header(db_path),
        check_freelist(db_path),
        check_schema(db_path),
    ]
    if quick:
        return results, True
    print("  深度层 PRAGMA integrity_check 开始,15GB 库预计 60–90 分钟...",
          flush=True)
    results.append(check_integrity(db_path))
    return results, False


def summarize(results: list[CheckResult], deep_skipped: bool) -> dict:
    failed = [r for r in results if r.status == "fail"]
    return {
        "status": "corrupted" if failed else "healthy",
        "failed_checks": len(failed),
        "deep_check_skipped": deep_skipped,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 11 passed。

---

### Task 5: JSON / TXT 报告生成

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `build_json_report`、`render_text_report`、`save_reports`)
- Test: `tests/test_check_sqlite_structure.py`(追加 2 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def _sample_report(quick: bool = False) -> dict:
    results = [
        css.CheckResult("header", "preflight", "pass", "page_size=4096", [], 0.1),
        css.CheckResult("freelist", "preflight", "pass", "trunks=1", [], 0.1),
        css.CheckResult("schema", "preflight", "pass", "对象数=5", [], 0.1),
    ]
    if not quick:
        results.append(css.CheckResult("integrity_check", "deep", "fail",
                                       "2 条错误(展示前 2 条)",
                                       ["page 3: bad b-tree", "freelist size wrong"],
                                       1.0))
    summary = css.summarize(results, deep_skipped=quick)
    return css.build_json_report(Path("/tmp/x.db"), "quick" if quick else "full",
                                 results, summary)


def test_json_report_shape():
    rep = _sample_report()
    assert rep["mode"] == "full"
    assert rep["summary"]["status"] == "corrupted"
    assert rep["summary"]["deep_check_skipped"] is False
    assert [c["name"] for c in rep["checks"]] == [
        "header", "freelist", "schema", "integrity_check"]
    assert "report_time" in rep and "db_size_mb" in rep


def test_text_report_content():
    rep = _sample_report(quick=True)
    text = css.render_text_report(rep)
    assert "SQLite 结构完整性检查报告" in text
    assert "快速" in text
    assert "健康" in text
    rep2 = _sample_report()
    text2 = css.render_text_report(rep2)
    assert "发现损坏" in text2
    assert "bad b-tree" in text2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k report`
Expected: FAIL,`AttributeError: build_json_report`。

- [ ] **Step 3: 写实现**

追加到 `scripts/check_sqlite_structure.py`(`summarize` 之后):

```python
def build_json_report(db_path: Path, mode: str, results: list[CheckResult],
                      summary: dict) -> dict:
    return {
        "report_time": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "db_size_mb": round(db_path.stat().st_size / 1024 / 1024, 2)
                      if db_path.exists() else 0,
        "mode": mode,
        "checks": [
            {
                "name": r.name,
                "layer": r.layer,
                "status": r.status,
                "detail": r.detail,
                "errors": r.errors,
                "elapsed_s": round(r.elapsed_s, 3),
            }
            for r in results
        ],
        "summary": summary,
    }


_STATUS_CN = {"healthy": "健康", "corrupted": "发现损坏", "error": "检查出错"}


def render_text_report(report: dict) -> str:
    mode_cn = "快速(未运行深度检查)" if report["mode"] == "quick" else "全量"
    lines = [
        "=" * 80,
        "                    SQLite 结构完整性检查报告",
        "=" * 80,
        f"检查时间:     {report['report_time']}",
        f"数据库路径:   {report['db_path']}",
        f"数据库大小:   {report['db_size_mb']} MB",
        f"检查模式:     {mode_cn}",
        "",
        "=" * 80,
        "一、汇总",
        "=" * 80,
        "",
        f"【检查结果】{_STATUS_CN.get(report['summary']['status'], report['summary']['status'])}",
        "",
        "  检查项              层级      状态    耗时     问题数",
        "  " + "-" * 60,
    ]
    for c in report["checks"]:
        status_cn = "✅ 通过" if c["status"] == "pass" else "❌ 失败"
        lines.append(
            f"  {c['name']:<18} {c['layer']:<9} {status_cn} "
            f"{c['elapsed_s']:>7.1f}s {len(c['errors']):>6}")
    lines += ["", "=" * 80, "二、明细", "=" * 80, ""]
    for c in report["checks"]:
        lines.append(f"【{c['name']}】{c['detail']}")
        for e in c["errors"]:
            lines.append(f"  ❌ {e}")
        lines.append("")
    if report["summary"]["status"] == "corrupted":
        lines += [
            "=" * 80,
            "总结",
            "=" * 80,
            "",
            "发现结构损坏。建议处置:立即停止写入、先做文件级备份,",
            "再人工评估 `sqlite3 .recover` 或从备份恢复。切勿直接 VACUUM/REINDEX。",
            "",
        ]
    return "\n".join(lines) + "\n"


def save_reports(report: dict, text: str, output_base: Path) -> None:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    output_base.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output_base.with_suffix(".txt").write_text(text, encoding="utf-8")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 13 passed。

---

### Task 6: 邮件告警

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `load_config`、`build_alert_html`、`send_alert`)
- Test: `tests/test_check_sqlite_structure.py`(追加 3 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def _email_env(monkeypatch, sent: list, enabled: bool = True):
    """把邮件三件套打桩,记录 send_email 调用。"""
    monkeypatch.setattr(css, "load_dotenv", lambda: None)
    monkeypatch.setattr(css, "load_email_config",
                        lambda: {"smtp_server": "s", "smtp_port": 465,
                                 "sender": "a@b.c", "password": "p",
                                 "receiver": "r@b.c"})
    monkeypatch.setattr(css, "send_email",
                        lambda cfg, subject, body, subtype="html":
                        sent.append(subject) or True)
    monkeypatch.setattr(css, "load_config",
                        lambda: {"email": {"enabled": enabled}})


def test_email_sent_when_corrupted(monkeypatch):
    sent: list = []
    _email_env(monkeypatch, sent)
    rep = _sample_report()          # corrupted
    css.send_alert(rep)
    assert len(sent) == 1
    assert "结构损坏告警" in sent[0]


def test_email_not_sent_when_healthy(monkeypatch):
    sent: list = []
    _email_env(monkeypatch, sent)
    rep = _sample_report(quick=True)  # healthy
    css.send_alert(rep)
    assert sent == []


def test_email_respects_config_disabled(monkeypatch):
    sent: list = []
    _email_env(monkeypatch, sent, enabled=False)
    rep = _sample_report()          # corrupted 但开关关闭
    css.send_alert(rep)
    assert sent == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k email`
Expected: FAIL,`AttributeError: send_alert`。

- [ ] **Step 3: 写实现**

先在文件顶部把邮件函数导入模块级命名名(便于测试 monkeypatch):

```python
from src.config import DB_PATH
from src.utils.email_notifier import load_dotenv, load_email_config, send_email
```

追加到 `scripts/check_sqlite_structure.py`(`save_reports` 之后):

```python
def load_config() -> dict:
    """读取 config.yaml(与 scripts/daily_report.py 同模式)。"""
    if not CONFIG_PATH.exists():
        return {}
    import yaml
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_alert_html(report: dict) -> str:
    status_cn = _STATUS_CN.get(report["summary"]["status"], report["summary"]["status"])
    rows = "".join(
        f"<tr><td>{c['name']}</td><td>{c['layer']}</td>"
        f"<td>{'通过' if c['status'] == 'pass' else '失败'}</td>"
        f"<td>{len(c['errors'])}</td></tr>"
        for c in report["checks"])
    err_lines = []
    for c in report["checks"]:
        err_lines += [f"<li>[{c['name']}] {e}</li>" for e in c["errors"][:20]]
    errors_html = "".join(err_lines) or "<li>无</li>"
    return f"""<html><body>
<h2>SQLite 结构检查: {status_cn}</h2>
<p>数据库: {report['db_path']}({report['db_size_mb']} MB,模式 {report['mode']})</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>检查项</th><th>层级</th><th>状态</th><th>问题数</th></tr>
{rows}
</table>
<h3>问题(前 20 条)</h3>
<ul>{errors_html}</ul>
<p>完整报告: data/sqlite_structure_report.txt / .json</p>
<p>建议:停止写入 → 文件级备份 → 人工评估 .recover。切勿直接 VACUUM/REINDEX。</p>
</body></html>"""


def send_alert(report: dict) -> None:
    """损坏/出错时发告警邮件。发送失败不影响退出码。

    触发条件由调用方保证(summary.status != healthy);本函数再校验
    config.yaml email.enabled 开关。healthy 状态不发(调用方不调用即可,
    此处亦有幂等保护)。
    """
    if report["summary"]["status"] == "healthy":
        return
    cfg = load_config()
    if not cfg.get("email", {}).get("enabled"):
        print("邮件通知未启用(config.yaml email.enabled),跳过告警")
        return
    load_dotenv()
    email_cfg = load_email_config()
    if email_cfg is None:
        print("缺少 .env 邮件配置(EMAIL_*),跳过告警")
        return
    subject = f"[BaoStock] SQLite 结构损坏告警: {Path(report['db_path']).name}"
    ok = send_email(email_cfg, subject, build_alert_html(report), subtype="html")
    if ok:
        print(f"✅ 告警邮件已发送: {email_cfg['receiver']}")
    else:
        print("❌ 告警邮件发送失败(不影响退出码)")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 16 passed。

---

### Task 7: CLI 主入口 + 退出码 + E2E

**Files:**
- Modify: `scripts/check_sqlite_structure.py`(追加 `build_parser`、`main`)
- Test: `tests/test_check_sqlite_structure.py`(追加 4 个测试)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_check_sqlite_structure.py`:

```python
def test_main_healthy_exit_0(tmp_path):
    db = tmp_path / "ok.db"
    _make_db(db)
    out = tmp_path / "rep"
    rc = css.main(["--db", str(db), "--quick", "--output", str(out),
                   "--no-email"])
    assert rc == 0
    assert out.with_suffix(".json").exists()
    assert out.with_suffix(".txt").exists()


def test_main_corrupted_exit_1(tmp_path):
    db = tmp_path / "bad.db"
    _make_db(db, rows=200)
    _truncate(db, drop_pages=1)
    rc = css.main(["--db", str(db), "--quick", "--output", str(tmp_path / "r"),
                   "--no-email"])
    assert rc == 1


def test_main_missing_db_exit_2(tmp_path):
    rc = css.main(["--db", str(tmp_path / "nope.db"), "--quick",
                   "--output", str(tmp_path / "r"), "--no-email"])
    assert rc == 2
    assert not (tmp_path / "r.json").exists()


def test_main_full_mode_runs_deep(tmp_path):
    db = tmp_path / "full.db"
    _make_db(db)
    out = tmp_path / "rep"
    rc = css.main(["--db", str(db), "--output", str(out), "--no-email"])
    assert rc == 0
    import json as _json
    rep = _json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert rep["mode"] == "full"
    assert rep["summary"]["deep_check_skipped"] is False
    assert rep["checks"][-1]["name"] == "integrity_check"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v -k main`
Expected: FAIL,`AttributeError: main`。

- [ ] **Step 3: 写实现**

追加到 `scripts/check_sqlite_structure.py`(`send_alert` 之后):

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SQLite 物理结构完整性检查(页面/freelist/索引/schema)")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="目标数据库路径(默认 src.config.DB_PATH)")
    parser.add_argument("--quick", action="store_true",
                        help="跳过深度层 integrity_check,仅跑秒级前置层")
    parser.add_argument("--output", type=Path,
                        default=PROJECT_ROOT / "data" / "sqlite_structure_report",
                        help="报告基础路径(输出 .json 与 .txt)")
    parser.add_argument("--no-email", action="store_true",
                        help="即使发现损坏也不发告警邮件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path: Path = args.db

    print("开始 SQLite 结构完整性检查...")
    print(f"  数据库: {db_path}")
    print(f"  模式:   {'快速(跳过深度层)' if args.quick else '全量'}")
    print()

    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return 2

    try:
        results, deep_skipped = run_checks(db_path, quick=args.quick)
        summary = summarize(results, deep_skipped)
        report = build_json_report(
            db_path, "quick" if deep_skipped else "full", results, summary)
        text = render_text_report(report)
        save_reports(report, text, args.output)
        print()
        print(f"✅ 报告已保存: {args.output}.json / {args.output}.txt")
        print(f"检查结果: {_STATUS_CN.get(summary['status'], summary['status'])}"
              f"(失败项 {summary['failed_checks']})")
        if summary["status"] != "healthy" and not args.no_email:
            send_alert(report)
        return 0 if summary["status"] == "healthy" else 1
    except Exception as e:  # 检查器自身出错(非库损坏)
        print(f"❌ 检查器异常: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v`
Expected: 20 passed。

---

### Task 8: README 文档

**Files:**
- Modify: `README.md`(快速开始代码块)

- [ ] **Step 1: 更新 README**

在 `README.md` 快速开始代码块中 `# 数据完整性校验` 的 4 行示例之后(`# 查看最近日志` 之前)插入:

```markdown
# SQLite 物理结构检查(页面/freelist/索引/schema)
.venv/bin/python scripts/check_sqlite_structure.py             # 全量检查(15GB 库约 75 分钟,建议每周低峰)
.venv/bin/python scripts/check_sqlite_structure.py --quick     # 秒级快速检查(跳过完整性深度检查)
.venv/bin/python scripts/check_sqlite_structure.py --no-email  # 发现损坏也不发告警邮件
# 退出码:0=健康 1=发现损坏 2=检查器出错
# 损坏时告警邮件复用 .env 的 EMAIL_* 配置,开关为 config.yaml 的 email.enabled
```

- [ ] **Step 2: 校验 Markdown 渲染**

Run: `.venv/bin/python -c "import pathlib; t=pathlib.Path('README.md').read_text(); assert 'check_sqlite_structure' in t; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests/test_check_sqlite_structure.py -v && .venv/bin/python scripts/check_sqlite_structure.py --quick --db /tmp/opencode/smoke.db --no-email --output /tmp/opencode/smoke_rep`(先用 `_make_db` 生成 `/tmp/opencode/smoke.db`)
Expected: 20 passed;脚本输出"健康"并生成报告,退出码 0。

---

## Self-Review 结果

1. **Spec 覆盖**:前置层 3 项(Task 1–3)、深度层(Task 4)、报告(Task 5)、邮件(Task 6)、CLI/退出码(Task 7)、README(Task 8)、测试矩阵(spec 9 用例 → 20 个测试函数全对应:`--db` 不存在、`--quick`、邮件 mock、损坏注入、健康路径)。spec 的"不做"项均未引入。
2. **占位符扫描**:无 TBD/TODO;所有代码块完整可粘贴;测试辅助函数在 Task 1 一次性定义,后续任务引用均带签名。
3. **类型一致性**:`check_header/check_freelist/check_schema/check_integrity → CheckResult`、`run_checks → tuple[list[CheckResult], bool]`、`summarize → dict`、`build_json_report(Path, str, list, dict) → dict`、`send_alert(dict) → None`、`main(list|None) → int` 在各任务间签名一致;测试中 `css.` 前缀引用的名字与实现一一对应(`check_header`、`check_freelist`、`check_schema`、`check_integrity`、`run_checks`、`summarize`、`build_json_report`、`render_text_report`、`send_alert`、`load_config`、`load_dotenv`、`load_email_config`、`send_email`、`CheckResult`、`main`)。

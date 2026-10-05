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
import html
import json
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH
from src.utils.email_notifier import load_dotenv, load_email_config, send_email

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
    except (OSError, struct.error) as e:
        return CheckResult("header", "preflight", "fail", f"无法读取文件: {e}",
                           [str(e)], time.monotonic() - start)
    if len(hdr) < 100 or hdr[:16] != MAGIC:
        return CheckResult("header", "preflight", "fail", "文件头魔数非法",
                           ["SQLite 魔数不匹配"], time.monotonic() - start)
    raw = struct.unpack(">H", hdr[16:18])[0]
    page_size = 65536 if raw == 1 else raw
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
            if len(hdr) < 100 or hdr[:16] != MAGIC:
                return CheckResult("freelist", "preflight", "fail", "文件头魔数非法",
                                   ["SQLite 魔数不匹配"], time.monotonic() - start)
            raw = struct.unpack(">H", hdr[16:18])[0]
            page_size = 65536 if raw == 1 else raw
            if not (512 <= page_size <= 65536) or (page_size & (page_size - 1)) != 0:
                return CheckResult("freelist", "preflight", "fail",
                                   f"page_size 非法: {page_size}",
                                   [f"page_size 非法: {page_size}"],
                                   time.monotonic() - start)
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
                if nleaf > (page_size - 8) // 4:
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
    except (OSError, struct.error) as e:
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


def _connect(db_path: Path) -> sqlite3.Connection:
    """打开只读连接:query_only 兜底防写,语句层面也只执行读操作。

    不用 URI mode=ro:WAL 恢复可能因只读连接失败;普通连接 + query_only
    与应用日常读连接行为一致,且引擎级拒绝任何写。
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only = ON")
    return conn


def _is_environmental_error(e: BaseException) -> bool:
    if not isinstance(e, sqlite3.OperationalError):
        return False
    msg = str(e).lower()
    return "locked" in msg or "unable to open" in msg


def check_schema(db_path: Path) -> CheckResult:
    """前置层 3:schema 可读性。捕获 sqlite_master 所在页损坏。"""
    start = time.monotonic()
    try:
        with open(db_path, "rb") as f:
            hdr = f.read(100)
    except OSError as e:
        return CheckResult("schema", "preflight", "fail", f"无法读取文件: {e}",
                           [str(e)], time.monotonic() - start)
    if len(hdr) < 100 or hdr[:16] != MAGIC:
        return CheckResult("schema", "preflight", "fail", "文件头魔数非法",
                           ["SQLite 魔数不匹配"], time.monotonic() - start)
    try:
        conn = _connect(db_path)
        try:
            total = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        status = "error" if _is_environmental_error(e) else "fail"
        return CheckResult("schema", "preflight", status,
                           f"sqlite_master 读取失败: {e}", [str(e)],
                           time.monotonic() - start)
    detail = f"schema 对象数={total}, 表/索引对象={len(names)}"
    return CheckResult("schema", "preflight", "pass", detail, [],
                       time.monotonic() - start)


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
        status = "error" if _is_environmental_error(e) else "fail"
        return CheckResult("integrity_check", "deep", status,
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
    errored = [r for r in results if r.status == "error"]
    if failed:
        status = "corrupted"
    elif errored:
        status = "error"
    else:
        status = "healthy"
    return {
        "status": status,
        "failed_checks": len(failed),
        "deep_check_skipped": deep_skipped,
    }


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
        err_lines += [f"<li>[{c['name']}] {html.escape(e)}</li>" for e in c["errors"][:20]]
    errors_html = "".join(err_lines) or "<li>无</li>"
    return f"""<html><body>
<h2>SQLite 结构检查: {status_cn}</h2>
<p>数据库: {html.escape(report['db_path'])}({report['db_size_mb']} MB,模式 {report['mode']})</p>
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
            try:
                send_alert(report)
            except Exception as e:
                print(f"❌ 告警失败: {e}")
        if summary["status"] == "healthy":
            return 0
        return 1 if summary["status"] == "corrupted" else 2
    except Exception as e:  # 检查器自身出错(非库损坏)
        print(f"❌ 检查器异常: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

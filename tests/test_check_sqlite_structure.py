"""tests/test_check_sqlite_structure.py

SQLite 结构检查脚本的损坏注入测试。
全部在 tmp_path 小库上进行,绝不接触 data/baostock.db。
"""

import sqlite3
import struct
import subprocess
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
    raw = struct.unpack(">H", hdr[16:18])[0]
    return {
        "page_size": 65536 if raw == 1 else raw,
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
    with open(path, "r+b") as f:
        f.truncate(size - drop_pages * PAGE_SIZE)


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


def test_cli_subprocess_smoke(tmp_path):
    db = tmp_path / "cli.db"
    _make_db(db)
    proc = subprocess.run(
        [sys.executable, str(Path(css.__file__)), "--quick", "--db", str(db),
         "--no-email", "--output", str(tmp_path / "rep")],
        capture_output=True, text=True)
    assert proc.returncode == 0
    assert (tmp_path / "rep.json").exists()
    assert (tmp_path / "rep.txt").exists()


def test_page_size_65536_healthy_passes(tmp_path):
    db = tmp_path / "ps64k.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA page_size=65536")
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.execute("CREATE INDEX idx_t_a ON t (a)")
    conn.executemany("INSERT INTO t VALUES (?, ?)",
                     [(i, f"row-{i}") for i in range(50)])
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    h = css.check_header(db)
    assert h.status == "pass", h.errors
    f = css.check_freelist(db)
    assert f.status == "pass", f.errors
    assert _read_header(db)["page_size"] == 65536


def test_zero_byte_file_all_checks_fail_not_crash(tmp_path):
    db = tmp_path / "empty.db"
    db.write_bytes(b"")
    for fn in (css.check_header, css.check_freelist, css.check_schema):
        r = fn(db)
        assert r.status in ("fail", "error"), (fn.__name__, r.status)


def test_nleaf_boundary_no_crash(tmp_path):
    db = tmp_path / "nleaf.db"
    _make_db_with_freelist(db)
    head = _read_header(db)["freelist_head"]
    assert head > 0
    _patch_bytes(db, (head - 1) * PAGE_SIZE + 4, struct.pack(">I", PAGE_SIZE // 4))
    r = css.check_freelist(db)
    assert r.status == "fail"
    assert r.errors


def test_lock_error_classified_as_error(monkeypatch, tmp_path):
    db = tmp_path / "locked.db"
    _make_db(db)

    def _locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", _locked)
    r = css.check_schema(db)
    assert r.status == "error"
    s1 = css.summarize(
        [css.CheckResult("header", "preflight", "fail", "x", ["e"], 0.0),
         css.CheckResult("schema", "preflight", "error", "y", ["locked"], 0.0)],
        deep_skipped=True)
    assert s1["status"] == "corrupted"
    s2 = css.summarize(
        [css.CheckResult("header", "preflight", "pass", "x", [], 0.0),
         css.CheckResult("schema", "preflight", "error", "y", ["locked"], 0.0)],
        deep_skipped=True)
    assert s2["status"] == "error"


def test_alert_html_escapes():
    rep = _sample_report()
    rep["checks"][3]["errors"] = ["boom <script>alert(1)</script> & more"]
    rep["db_path"] = "/tmp/<x>.db"
    out = css.build_alert_html(rep)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out
    assert "&lt;x&gt;" in out


def test_send_alert_exception_preserves_exit_code(monkeypatch, tmp_path):
    db = tmp_path / "bad.db"
    _make_db(db, rows=200)
    _truncate(db, drop_pages=1)
    sent: list = []
    _email_env(monkeypatch, sent)

    def _broken_config():
        raise RuntimeError("config.yaml malformed")

    monkeypatch.setattr(css, "load_config", _broken_config)
    rc = css.main(["--db", str(db), "--quick", "--output", str(tmp_path / "r")])
    assert rc == 1
    assert sent == []

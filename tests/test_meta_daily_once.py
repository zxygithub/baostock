"""Unit tests for scripts/download_all.py — metadata (Phase 2) once-per-day gating.

Core rules under test:
- Phase 2 skips when today's marker file `DB_PATH.parent/.meta_fetched_YYYY-MM-DD` exists
- A successful download_all_metadata() writes today's marker
- --force-meta overrides an existing marker and refreshes anyway
- A failed download writes no marker, so the next pass retries
- CLI exposes --once (single pass) and --force-meta (force metadata refresh)
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import download_all


class _Log:
    """Silent logger stub — captures nothing, exercises the call signature."""

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


@pytest.fixture
def meta_env(monkeypatch, tmp_path):
    """Point download_all.DB_PATH at a temp dir and stub MetaDownloader."""
    db_path = tmp_path / "baostock.db"
    monkeypatch.setattr(download_all, "DB_PATH", db_path)
    marker = tmp_path / f".meta_fetched_{date.today():%Y-%m-%d}"

    state = {"download_calls": 0, "fail": False}

    class FakeMetaDownloader:
        def __init__(self, path, logger=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download_all_metadata(self):
            state["download_calls"] += 1
            if state["fail"]:
                raise RuntimeError("meta fetch failed")
            return {"trade_dates": 1, "stock_basic": 2, "stock_industry": 3}

    monkeypatch.setattr(download_all, "MetaDownloader", FakeMetaDownloader)

    class Env:
        pass

    env = Env()
    env.marker = marker
    env.state = state
    env.log = _Log()
    return env


def test_meta_skipped_when_marker_exists(meta_env):
    meta_env.marker.write_text("done", encoding="utf-8")

    refreshed = download_all.refresh_meta_if_due(force=False, logger=meta_env.log)

    assert refreshed is False
    assert meta_env.state["download_calls"] == 0


def test_meta_runs_and_writes_marker(meta_env):
    refreshed = download_all.refresh_meta_if_due(force=False, logger=meta_env.log)

    assert refreshed is True
    assert meta_env.state["download_calls"] == 1
    assert meta_env.marker.exists()


def test_force_meta_overrides_marker(meta_env):
    meta_env.marker.write_text("done", encoding="utf-8")

    refreshed = download_all.refresh_meta_if_due(force=True, logger=meta_env.log)

    assert refreshed is True
    assert meta_env.state["download_calls"] == 1


def test_failed_meta_download_does_not_write_marker(meta_env):
    meta_env.state["fail"] = True

    with pytest.raises(RuntimeError):
        download_all.refresh_meta_if_due(force=False, logger=meta_env.log)

    assert meta_env.state["download_calls"] == 1
    assert not meta_env.marker.exists()
    # A failed pass must retry on the next pass:
    assert download_all.should_refresh_meta(force=False) is True


def test_should_refresh_meta_true_when_marker_absent(meta_env):
    assert download_all.should_refresh_meta(force=False) is True
    meta_env.marker.write_text("done", encoding="utf-8")
    assert download_all.should_refresh_meta(force=False) is False
    # force bypasses the marker check entirely
    assert download_all.should_refresh_meta(force=True) is True


def test_cli_flags_present():
    script = Path(download_all.__file__)
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--once" in result.stdout
    assert "--force-meta" in result.stdout

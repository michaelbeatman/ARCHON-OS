"""P0-Regression Welle B: Scheinerfolg im Chaos-Test, Draining-Gate.

Audit 23.11.2026:
- K-4: test_watchdog_supervisor_responsiveness() gab hartcodiert 'passed'.
- K-2: can_start_task() wurde im Produktivcode nie aufgerufen.
"""

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_watchdog_paths(tmp_path, monkeypatch, *, with_log, age_seconds=0):
    import scripts.chaos_tester as ct

    monkeypatch.setattr(ct, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ct, "WORKSPACE_DIR", str(tmp_path))
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    if with_log:
        log = log_dir / "watchdog_daemon.log"
        log.write_text("watchdog alive\n", encoding="utf-8")
        if age_seconds:
            old = time.time() - age_seconds
            os.utime(log, (old, old))
    return ct


def test_chaos_watchdog_without_evidence_is_not_passed(tmp_path, monkeypatch):
    ct = _setup_watchdog_paths(tmp_path, monkeypatch, with_log=False)
    result = ct.ArchonChaosTester().test_watchdog_supervisor_responsiveness()
    assert result["status"] != "passed"
    assert result["status"] == "skipped"


def test_chaos_watchdog_with_fresh_log_can_pass(tmp_path, monkeypatch):
    ct = _setup_watchdog_paths(tmp_path, monkeypatch, with_log=True)
    result = ct.ArchonChaosTester().test_watchdog_supervisor_responsiveness()
    assert result["status"] == "passed"


def test_chaos_watchdog_with_stale_log_fails(tmp_path, monkeypatch):
    ct = _setup_watchdog_paths(tmp_path, monkeypatch, with_log=True, age_seconds=3600)
    result = ct.ArchonChaosTester().test_watchdog_supervisor_responsiveness()
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_spawn_background_respects_draining_gate():
    import main as main_mod
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as coord

    async def noop():
        return None

    coord.start_draining("P0-Test", grace_seconds=1)
    try:
        task = main_mod._spawn_background(noop(), name="p0_drain_probe")
        assert task is None, "waehrend des Draining duerfen keine Background-Tasks starten"
    finally:
        coord.cancel_draining()

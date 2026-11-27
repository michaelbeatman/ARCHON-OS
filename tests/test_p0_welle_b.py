"""P0-Regression Welle B: Scheinerfolg im Chaos-Test, Draining-Gate.

Audit 23.11.2026:
- K-4: test_watchdog_supervisor_responsiveness() gab hartcodiert 'passed'.
- K-2: can_start_task() wurde im Produktivcode nie aufgerufen.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_watchdog_paths(tmp_path, monkeypatch, *, with_log, age_seconds=0):
    """D10-M1: der Watchdog schreibt watchdog_liveness.json, keine Logdatei."""
    import json

    import scripts.chaos_tester as ct

    monkeypatch.setattr(ct, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ct, "WORKSPACE_DIR", str(tmp_path))
    liveness = tmp_path / "watchdog_liveness.json"
    monkeypatch.setattr(ct, "WATCHDOG_LIVENESS_CANDIDATES", (str(liveness),))
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    if with_log:
        now = time.time()
        stamp = now - age_seconds

        def _write(loop_count: int, last_seen: float) -> None:
            liveness.write_text(json.dumps({
                "last_seen": last_seen, "loop_count": loop_count,
                "alive": True, "pid": 4242,
            }), encoding="utf-8")

        _write(5 if age_seconds else 4, stamp)

        def _advance(_seconds):
            _write(5 if age_seconds else 5, stamp if age_seconds else time.time())

        monkeypatch.setattr(ct.time, "sleep", _advance)
    return ct


def test_chaos_watchdog_without_evidence_is_not_passed(tmp_path, monkeypatch):
    ct = _setup_watchdog_paths(tmp_path, monkeypatch, with_log=False)
    result = ct.ArchonChaosTester().test_watchdog_supervisor_responsiveness()
    assert result["status"] != "passed"
    # D10-M1: fehlende Evidenz ist failed (Exit 1), nie wieder skipped.
    assert result["status"] == "failed"


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

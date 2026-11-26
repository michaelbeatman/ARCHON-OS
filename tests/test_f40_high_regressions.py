"""F40 Regressionstests fuer die beiden Phase-1-HIGH-Befunde (Agent B & Agent C)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from archon.core import orchestration
from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
from scripts.sync_soul_modes import refresh_soul_pin_for_agents


def test_f40_high_b_refresh_soul_pin_calls_real_inventory_api_and_fails_closed(monkeypatch, tmp_path):
    """Agent-B-HIGH: refresh_soul_pin_for_agents nutzt echte generate_inventory(save=True)-API; Fehler bricht hart ab."""
    inv_file = tmp_path / "eu_ai_act_inventory.json"
    monkeypatch.setattr(eu_ai_act_inventory_manager, "inventory_file", str(inv_file))

    res = refresh_soul_pin_for_agents(target_agent_id="founder")
    assert res["pin_refreshed"] is True
    assert res["target_agent_id"] == "founder"
    assert res["inventory_count"] >= 1
    assert inv_file.is_file()
    saved = json.loads(inv_file.read_text(encoding="utf-8"))
    assert isinstance(saved, list) and len(saved) >= 1
    assert any(item.get("agent_id") == "founder" and item.get("soul_sha256") for item in saved)

    # Negativprobe: Schreib-/Regenerationsfehler darf niemals pin_refreshed=True melden
    monkeypatch.setattr(
        eu_ai_act_inventory_manager,
        "generate_inventory",
        lambda **_kw: (_ for _ in ()).throw(OSError("inventory disk full")),
    )
    with pytest.raises(OSError, match="inventory disk full"):
        refresh_soul_pin_for_agents(target_agent_id="founder")


@pytest.mark.asyncio
async def test_f40_high_c_second_cancel_during_finally_cleanup_still_commits_status():
    """Agent-C-HIGH: zweiter cancel() waehrend finally-Cleanup darf Lease-/Idem-/Status-Commit nicht abbrechen."""
    import time

    task_obj = {
        "id": "t-f40-cancel",
        "title": "Cancel Cleanup Probe",
        "capture_input": "work",
        "agent_id": "coder",
        "status": "in_progress",
    }
    store = {"tasks": [task_obj]}
    committed_snapshots: list[str] = []
    release_started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _slow_release(_tid, _tok):
        loop.call_soon_threadsafe(release_started.set)
        time.sleep(0.15)
        return True

    supervisor = MagicMock()
    supervisor.acquire_lease.return_value = {"acquired": True, "lease_token": "tok-f40"}
    supervisor.heartbeat.return_value = True
    supervisor.release_lease.side_effect = _slow_release

    guard = MagicMock()
    guard.check_or_register.return_value = {
        "allowed": True,
        "blocked": False,
        "idempotency_key": "idem-f40",
    }
    guard.record_execution_result.return_value = True
    guard.invalidate_key.return_value = True

    dispatch_started = asyncio.Event()

    async def _hanging_dispatch(**_kwargs):
        dispatch_started.set()
        await asyncio.sleep(10)
        return {"status": "success", "content": "never"}

    dispatcher = MagicMock()
    dispatcher.dispatch_to_omniroute_or_container = _hanging_dispatch

    def _save_mc(d):
        committed_snapshots.append(str(d["tasks"][0].get("status")))

    def _update_mc(fn):
        fn(store)
        committed_snapshots.append(str(store["tasks"][0].get("status")))

    with patch("backend.deadlock_supervisor.deadlock_supervisor", supervisor), patch(
        "backend.idempotency_guard.idempotency_guard", guard
    ):
        coro = orchestration._execute_mission_control_task(
            "t-f40-cancel",
            dispatcher=dispatcher,
            load_mc=lambda: store,
            save_mc=_save_mc,
            update_mc=_update_mc,
            ticker=lambda *_a: None,
            get_profiles=lambda: [],
            sync_obsidian=lambda _t: "note.md",
            trigger_sandy=AsyncMock(),
            fan_in=AsyncMock(),
        )
        runner = asyncio.create_task(coro)
        await dispatch_started.wait()
        # 1. Cancel bricht den laufenden Dispatch ab -> faellt in finally
        runner.cancel()
        await asyncio.wait_for(release_started.wait(), timeout=2.0)
        # 2. Cancel waehrend Lease-Release im finally -> asyncio.shield schuetzt Kette
        runner.cancel()
        try:
            await asyncio.wait_for(runner, timeout=3.0)
        except asyncio.CancelledError:
            pass

    assert supervisor.release_lease.called, "Lease-Release wurde durch zweiten Cancel abgebrochen"
    assert guard.invalidate_key.called, "Idempotency-Invalidation wurde durch zweiten Cancel abgebrochen"
    assert committed_snapshots, "Status-Commit im finally wurde durch zweiten Cancel abgebrochen"

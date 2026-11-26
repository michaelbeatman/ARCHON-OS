# -*- coding: utf-8 -*-
"""W3-B (Orchestrierung) — Regressionstests.

D02-H2  Cancel im Mission-Control-Dispatch (Lease-/Idempotency-Phase) muss
        'cancelled' persistieren; Check nach JEDEM await.
D02-H3  Gestoerte Profil-SSOT darf nicht fail-open mit Generik-Prompt laufen.
D02-M1  Run-Cap-Prognose vor dem ersten, unbezifferten Dispatch.
D07-M4  Idempotency-Check-/Record-Fehler duerfen den Seiteneffekt nicht
        erneut ausfuehren (fail-closed + Audit).
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from archon.core.orchestration import _execute_mission_control_task
from backend.workflow_dag_runner import (
    _exec_with_retry_and_timeout,
    default_agent_node_executor,
    run_workflow_dag,
)


def _mc_store(task_id: str) -> dict:
    return {
        "tasks": [{
            "id": task_id,
            "title": "W3-B Cancel-Test",
            "agent_id": "default",
            "agent_name": "Default",
            "capture_input": "Tu etwas",
            "status": "approval",
        }],
        "metrics": {},
        "audit_logs": [],
    }


# ---------------------------------------------------------------------------
# D02-H2 — Cancel waehrend der Lease-Phase (frueher ausserhalb des Handlers)
# ---------------------------------------------------------------------------


async def test_d02_h2_cancel_during_lease_persists_cancelled():
    from backend.cancellation import reset_scope

    task_id = f"w3b-lease-{uuid.uuid4().hex[:8]}"
    scope = f"dispatch:{task_id}"
    store = _mc_store(task_id)
    committed: list = []

    def _update_mc(fn):
        fn(store)
        committed.append(str(store["tasks"][0].get("status")))

    entered = threading.Event()
    release = threading.Event()

    def _acquire_lease(_tid, ttl_seconds=300):
        entered.set()
        release.wait(timeout=2.0)
        return {"acquired": True, "lease_token": "lease-w3b"}

    supervisor = MagicMock()
    supervisor.acquire_lease.side_effect = _acquire_lease
    supervisor.release_lease.return_value = True

    dispatcher = MagicMock()
    dispatcher.dispatch_to_omniroute_or_container = AsyncMock()

    try:
        with patch("backend.deadlock_supervisor.deadlock_supervisor", supervisor):
            runner = asyncio.create_task(_execute_mission_control_task(
                task_id,
                dispatcher=dispatcher,
                load_mc=lambda: store,
                save_mc=lambda _d: None,
                update_mc=_update_mc,
                ticker=lambda *_a, **_k: None,
                get_profiles=lambda: [],
                sync_obsidian=lambda _t: "note.md",
                trigger_sandy=AsyncMock(),
                fan_in=AsyncMock(),
            ))
            await asyncio.to_thread(entered.wait, 2.0)
            assert entered.is_set(), "Lease-Acquire wurde nicht erreichtet"
            # Cancel trifft den laufenden Task exakt in der Lease-Phase.
            runner.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(runner, timeout=3.0)
    finally:
        release.set()
        reset_scope(scope)

    assert "cancelled" in committed, f"Status nicht persistiert: {committed}"
    assert store["tasks"][0]["status"] == "cancelled"
    dispatcher.dispatch_to_omniroute_or_container.assert_not_called()


async def test_d02_h2_pre_cancelled_scope_persists_cancelled_without_dispatch():
    from backend.cancellation import cancel_scope, reset_scope

    task_id = f"w3b-pre-{uuid.uuid4().hex[:8]}"
    scope = f"dispatch:{task_id}"
    store = _mc_store(task_id)
    committed: list = []

    def _update_mc(fn):
        fn(store)
        committed.append(str(store["tasks"][0].get("status")))

    dispatcher = MagicMock()
    dispatcher.dispatch_to_omniroute_or_container = AsyncMock()

    try:
        # Token existiert bereits als abgebrochen, bevor der Task startet.
        from backend.cancellation import get_token
        get_token(scope)
        cancel_scope(scope, reason="operator")
        with pytest.raises(asyncio.CancelledError):
            await _execute_mission_control_task(
                task_id,
                dispatcher=dispatcher,
                load_mc=lambda: store,
                save_mc=lambda _d: None,
                update_mc=_update_mc,
                ticker=lambda *_a, **_k: None,
                get_profiles=lambda: [],
                sync_obsidian=lambda _t: "note.md",
                trigger_sandy=AsyncMock(),
                fan_in=AsyncMock(),
            )
    finally:
        reset_scope(scope)

    assert "cancelled" in committed, f"Status nicht persistiert: {committed}"
    dispatcher.dispatch_to_omniroute_or_container.assert_not_called()


# ---------------------------------------------------------------------------
# D02-H3 — Profil-SSOT gestoert => fail-closed, kein Generik-Prompt
# ---------------------------------------------------------------------------


def test_d02_h3_profile_ssot_error_blocks_unknown_agent(monkeypatch):
    import archon.core.profiles as core_profiles

    def _broken_ssot():
        raise RuntimeError("SSOT nicht erreichbar")

    monkeypatch.setattr(core_profiles, "api_get_hermes_profiles", _broken_ssot)

    dispatch = AsyncMock()
    with patch("core_dispatcher.dispatch_to_omniroute_or_container", dispatch), \
            patch("backend.workflow_dag_runner._recovery_audit") as audit:
        out = asyncio.run(default_agent_node_executor(
            {"id": "n-ghost", "type": "agent", "agent_id": "ercefil"}, {}
        ))

    assert out["status"] == "blocked"
    assert out["error_code"] == "UNKNOWN_AGENT_ID"
    dispatch.assert_not_awaited()
    assert audit.called, "SSOT-Fehler wurde nicht auditiert"


# ---------------------------------------------------------------------------
# D02-M1 — Kostenprognose vor dem ersten Dispatch
# ---------------------------------------------------------------------------


def test_d02_m1_prognosis_blocks_first_unpriced_node(tmp_path, monkeypatch):
    called: list = []

    async def _exec(node, _up):
        called.append(node["id"])
        return {"status": "success", "content": "should not run", "cost_usd": 0.0}

    dag = {
        "id": "wf-w3b-cap",
        "max_budget_eur": 0.01,
        "root_ticket_id": f"w3b-cap-{uuid.uuid4().hex[:8]}",
        "nodes": [{
            "id": "n1", "type": "agent", "depends_on": [],
            # Kein max_budget_eur, aber eine Prognose-Basis.
            "estimated_input_tokens": 100000,
            "estimated_output_tokens": 100000,
        }],
        "edges": [],
    }
    # 2 USD prognostiziert >> Run-Cap von 0.01 EUR.
    monkeypatch.setattr("backend.llm_kernel.estimate_model_cost_usd", lambda *a, **k: 2.0)

    res = asyncio.run(run_workflow_dag(
        dag, executor_fn=_exec, db_path=str(tmp_path / "dag.db")
    ))

    assert called == [], f"Node wurde trotz Prognose-Ueberschreitung dispatched: {called}"
    out = res["outputs"]["n1"]
    assert out["status"] == "blocked"
    assert out["block_kind"] == "budget_exhausted"
    assert out["needs_human"] is True


# ---------------------------------------------------------------------------
# D07-M4 — Idempotency fail-closed
# ---------------------------------------------------------------------------


async def test_d07_m4_check_failure_blocks_without_executor():
    called: list = []

    async def _exec(node, _up):
        called.append(node["id"])
        return {"status": "success", "content": "ok"}

    guard = MagicMock()
    guard.check_or_register.side_effect = RuntimeError("Idempotency-DB gesperrt")

    with patch("backend.idempotency_guard.idempotency_guard", guard), \
            patch("backend.workflow_dag_runner._recovery_audit") as audit:
        out = await _exec_with_retry_and_timeout(
            _exec, {"id": "n-check"}, {}, idempotency_key="w3b-idem-check"
        )

    assert called == [], "Executor lief ohne erfolgreichen Idempotency-Check"
    assert out["error"] == "IDEMPOTENCY_UNAVAILABLE"
    assert out["needs_human"] is True
    assert audit.called, "Check-Fehler wurde nicht auditiert"


async def test_d07_m4_record_failure_marks_node_error():
    called: list = []

    async def _exec(node, _up):
        called.append(node["id"])
        return {"status": "success", "content": "ok"}

    guard = MagicMock()
    guard.check_or_register.return_value = {"blocked": False}
    guard.record_execution_result.side_effect = RuntimeError("Idempotency-DB gesperrt")

    with patch("backend.idempotency_guard.idempotency_guard", guard), \
            patch("backend.workflow_dag_runner._recovery_audit") as audit:
        out = await _exec_with_retry_and_timeout(
            _exec, {"id": "n-record"}, {}, idempotency_key="w3b-idem-record"
        )

    assert len(called) == 1, "Node wurde unerwartet erneut ausgefuehrt"
    assert out["status"] == "error"
    assert out["error"] == "IDEMPOTENCY_RECORD_FAILED"
    assert out["needs_human"] is True
    assert audit.called, "Record-Fehler wurde nicht auditiert"

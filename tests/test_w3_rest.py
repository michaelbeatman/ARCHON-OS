# -*- coding: utf-8 -*-
"""W3-Reste — Regressionstests fuer D07-M4/M6/M7, D11-M3/M4 und Lease-Fail-Open.

Alle Tests fahren den Produktivpfad (Produzent -> Konsument -> Effekt ->
Verifikation). Kein Coroutine-Replay, keine PostgreSQL-Migration, keine
fremden Dateien. DB-Isolation: ARCHON_TEST_DB_ISOLATION=1 (conftest.py).
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Callable
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _audit_sink(events: list[dict]) -> Callable[..., dict]:
    """Zeichnet signierte Pflicht-Events auf, statt die echte Audit-DB zu schreiben."""

    def _record(**kwargs: object) -> dict:
        events.append(kwargs)
        return {}

    return _record


# ---------------------------------------------------------------------------
# Lease-Fail-Open (archon/core/orchestration.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mission_control_lease_claim_is_fail_closed_even_with_optout(monkeypatch):
    """Der fruehere ARCHON_LEASE_FAIL_OPEN-Schalter darf nie mehr greifen."""
    from archon.core import orchestration as orch
    from backend.deadlock_supervisor import deadlock_supervisor

    monkeypatch.setenv("ARCHON_LEASE_FAIL_OPEN", "1")
    task = {
        "id": "t-w3-rest", "agent_id": "default", "agent_name": "Default",
        "title": "Lease-Test", "status": "todo",
    }
    store = {"tasks": [task]}
    dispatched: list[str] = []

    class _Dispatcher:
        def __getattr__(self, name: str):
            def _noop(*_args, **_kwargs):
                dispatched.append(name)
                return {}
            return _noop

    def _acquire(_task_id, **_kwargs):
        raise RuntimeError("lease store down")

    monkeypatch.setattr(deadlock_supervisor, "acquire_lease", _acquire)

    await orch._execute_mission_control_task(
        "t-w3-rest",
        dispatcher=_Dispatcher(),
        load_mc=lambda: store,
        update_mc=lambda mutate: mutate(store),
        ticker=lambda *_a, **_k: None,
        get_profiles=lambda: [],
        sync_obsidian=lambda *_a, **_k: "",
        trigger_sandy=lambda *_a, **_k: None,
        fan_in=lambda *_a, **_k: None,
    )

    assert task["status"] == "blocked", task
    assert dispatched == [], "ohne Lease darf kein Dispatch erfolgen"
    assert "nicht verfügbar" in str(task.get("result_summary"))


# ---------------------------------------------------------------------------
# D07-M4 — 30-s-Recovery-Loops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_loop_failures_are_audited_and_escalate(monkeypatch):
    """Drei aufeinanderfolgende Fehler je Loop -> Audit + externer Alarm."""
    import archon.core.orchestration as orch
    import archon.services.background_loops as bg
    import backend.approval_policy_engine as approval_mod
    import backend.audit_log as audit_log
    import backend.deadlock_supervisor as deadlock_mod
    import backend.metrics_collector as metrics
    import backend.resource_backpressure as bp_mod

    events: list[dict] = []
    alarms: list[tuple] = []
    monkeypatch.setattr(
        audit_log, "_require_audit_event",
        _audit_sink(events),
    )
    monkeypatch.setattr(
        metrics, "report_external_alert",
        lambda *args, **kwargs: alarms.append((args, kwargs)),
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("loop down")

    monkeypatch.setattr(deadlock_mod.deadlock_supervisor, "detect_and_resolve_deadlocks", _boom)
    monkeypatch.setattr(orch, "recover_stale_synthesis", _boom)
    monkeypatch.setattr(metrics, "check_and_dispatch_alerts_now", _boom)
    monkeypatch.setattr(bp_mod.resource_backpressure_protector, "check_health_and_backpressure", lambda *_a, **_k: {})
    monkeypatch.setattr(approval_mod.approval_engine, "check_and_escalate_timeouts", lambda *_a, **_k: [])
    monkeypatch.setattr(audit_log, "anchor_secondary_chains", lambda *_a, **_k: {})

    deps = SimpleNamespace(
        orch_fan_in_maybe_start_synthesis=lambda *_a, **_k: None,
        mc_async_lock=None,
        run_synthesis_cascade=lambda *_a, **_k: None,
        load_mission_control_data=lambda: {},
        update_mission_control_data=lambda _fn: None,
        verify_all_audit_chains=lambda: {},
        mark_audit_compromised=lambda *_a, **_k: None,
    )
    monkeypatch.setattr(bg, "_resolve_deps", lambda: deps)

    for key in ("deadlock_supervisor", "synthesis_recovery", "alerting"):
        bg._LOOP_FAILURE_COUNTS[key] = 0

    class _StopLoop(Exception):
        pass

    real_sleep = asyncio.sleep
    sleep_calls = {"n": 0}

    async def _fake_sleep(_delay):
        sleep_calls["n"] += 1
        # 1x 15 s Start + 3 Zyklen à 30 s: nach Zyklus 3 beenden.
        if sleep_calls["n"] >= 4:
            raise _StopLoop()
        await real_sleep(0)

    monkeypatch.setattr(bg.asyncio, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        await bg._deadlock_supervisor_loop()

    actions = [event.get("action") for event in events]
    for expected in (
        "deadlock_supervisor_loop_failed",
        "synthesis_recovery_loop_failed",
        "alerting_loop_failed",
    ):
        assert expected in actions, actions
    assert actions.count("loop_external_alarm") == 3, actions
    assert len(alarms) == 3, alarms


# ---------------------------------------------------------------------------
# D07-M6 — Shutdown-Audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anchor_and_graceful_shutdown_failures_are_audited(monkeypatch):
    import archon.services.runtime_endpoints as re_mod
    import backend.audit_log as audit_log
    from backend.audit_log import chained_audit_log
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as coord

    events: list[dict] = []
    monkeypatch.setattr(
        audit_log, "_require_audit_event",
        _audit_sink(events),
    )

    def _anchor_boom():
        raise RuntimeError("anchor down")

    async def _grace_boom(reason: str = ""):
        raise RuntimeError("graceful down")

    monkeypatch.setattr(chained_audit_log, "stop_anchor_worker", _anchor_boom)
    monkeypatch.setattr(coord, "execute_graceful_shutdown", _grace_boom)

    await re_mod.on_shutdown_graceful()

    actions = [event.get("action") for event in events]
    assert "anchor_stop_failed" in actions, actions
    assert "graceful_shutdown_failed" in actions, actions


@pytest.mark.asyncio
async def test_client_close_failure_is_audited_and_mirrored(monkeypatch):
    import archon.services.shutdown_clients as sc
    import backend.agent_router as agent_router
    import backend.audit_log as audit_log
    from archon.services.background_loops import _FAILED_CANCELS

    events: list[dict] = []
    monkeypatch.setattr(
        audit_log, "_require_audit_event",
        _audit_sink(events),
    )

    def _boom():
        raise RuntimeError("close down")

    monkeypatch.setattr(agent_router, "router_instance", SimpleNamespace(close_http_clients=_boom))
    before = len(_FAILED_CANCELS)

    try:
        await sc._close_all_http_clients()

        assert any(event.get("action") == "client_close_failed" for event in events), events
        assert len(_FAILED_CANCELS) > before
        assert _FAILED_CANCELS[-1]["task"].startswith("client_close:")
    finally:
        # /readyz konsumiert _FAILED_CANCELS — keine Testreste hinterlassen.
        del _FAILED_CANCELS[before:]


# ---------------------------------------------------------------------------
# D07-M7 — Shutdown-Gesamtbudget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_shutdown_honours_total_budget_and_audits_hooks(monkeypatch):
    import backend.audit_log as audit_log
    import backend.loop_liveness as liveness
    from archon.services import lifecycle as lc

    events: list[dict] = []
    monkeypatch.setattr(
        audit_log, "_require_audit_event",
        _audit_sink(events),
    )
    monkeypatch.setattr(lc, "_SHUTDOWN_BUDGET_SECONDS", 0.25)
    start_mock = AsyncMock()
    stop_mock = AsyncMock()
    monkeypatch.setattr(liveness, "start_loop_heartbeat", start_mock)
    monkeypatch.setattr(liveness, "stop_loop_heartbeat", stop_mock)

    order: list[str] = []

    async def _hang():
        order.append("hang")
        await asyncio.sleep(5)

    def _fast():
        order.append("fast")

    _hang.__name__ = "hang"
    _fast.__name__ = "fast"

    loop = asyncio.get_running_loop()
    async with lc.lifespan_context(
        startup_hooks=[],
        shutdown_hooks=[_hang, _fast],
        fail_fast_hooks=set(),
        init_readiness_probe_table=lambda: None,
    ):
        started = loop.time()
    elapsed = loop.time() - started

    assert elapsed < 2.0, f"Shutdown blockierte {elapsed:.2f}s"
    assert order == ["fast", "hang"], order
    stop_mock.assert_awaited_once()
    hook_events = [event for event in events if event.get("action") == "shutdown_hook"]
    names = {event["payload"]["hook"] for event in hook_events}
    assert {"fast", "hang"} <= names, hook_events
    hang_event = next(event for event in hook_events if event["payload"]["hook"] == "hang")
    assert "failed" in hang_event["payload"]["status"], hang_event


# ---------------------------------------------------------------------------
# D11-M3 — verlustfreie Turns / Session-Fingerprint
# ---------------------------------------------------------------------------


def test_identical_turns_stay_distinct_and_sessions_do_not_bleed(tmp_path):
    from backend import lossless_session_dag as lcm

    db = str(tmp_path / "lcm.db")
    messages = [
        {"role": "system", "content": "Regel", "session_id": "s1", "tenant_id": "t1"},
        {"role": "user", "content": "Gleich", "session_id": "s1", "tenant_id": "t1"},
        {"role": "user", "content": "Gleich", "session_id": "s1", "tenant_id": "t1"},
    ]
    ids = lcm.record_turns("session:s1", messages, tenant_id="t1", db_path=db)
    assert ids[1] and ids[2] and ids[1] != ids[2], ids
    # Exakt gleicher Re-Dispatch bleibt idempotent.
    assert lcm.record_turns("session:s1", messages, tenant_id="t1", db_path=db) == ids

    head = [
        {"role": "system", "content": "Gleicher Anfang"},
        {"role": "user", "content": "Erster Turn"},
    ]
    a = head + [{"role": "user", "content": "Pfad A"}]
    b = head + [{"role": "user", "content": "Pfad B"}]
    assert lcm.derive_session_id(a, tenant_id="t1") != lcm.derive_session_id(b, tenant_id="t1")
    assert lcm.derive_session_id(a, tenant_id="t1") != lcm.derive_session_id(a, tenant_id="t2")


# ---------------------------------------------------------------------------
# D11-M4 — markierte Kuerzungen im Boardroom
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storm_panel_truncations_carry_marker_and_artifact(monkeypatch):
    import archon.routers.boardroom as br
    import backend.lossless_session_dag as lcm

    long_text = "X" * 4000

    async def _fake_panel(question, seats, seat_runner, judge_runner):
        return {
            "question": question,
            "perspectives": {},
            "synthesis": await judge_runner(question, {}),
            "requires_human_gate": True,
        }

    monkeypatch.setattr(lcm, "run_storm_panel", _fake_panel)
    res = {
        "task": "t-req",
        "events": [{"type": "agent_response", "agent_id": "s1", "content": long_text}],
        "synthesis": long_text,
    }
    panel = await br._run_no_consensus_storm_panel(res, [{"id": "s1"}], {"id": "chair"})

    assert "[gekürzt:" in panel["synthesis"], panel["synthesis"]
    assert "boardroom.debate/t-req/synthesis" in panel["synthesis"], panel["synthesis"]


def test_hitl_escalation_truncations_carry_marker_and_artifact(monkeypatch):
    import archon.routers.boardroom as br
    import archon.routers.decisions as decisions

    captured: dict = {}

    def _fake_create_decision(_typ, **kwargs):
        captured.update(kwargs)
        return {"id": "dec-rest"}

    monkeypatch.setattr(decisions, "create_decision", _fake_create_decision)
    monkeypatch.setattr(br, "_audit_boardroom", lambda *_a, **_k: None)

    long_text = "Y" * 4000
    result = br._escalate_boardroom_no_consensus(
        task_id="t-hitl",
        task="HITL-Test",
        consensus_status="NO_CONSENSUS",
        res={"critique": long_text, "synthesis": long_text},
        actor_id="system",
    )

    assert result and result["id"] == "dec-rest"
    extra = captured["extra"]
    assert "[gekürzt:" in extra["critique"]
    assert "boardroom.hitl/t-hitl/critique" in extra["critique"]
    assert "[gekürzt:" in extra["synthesis"]
    assert "boardroom.hitl/t-hitl/synthesis" in extra["synthesis"]

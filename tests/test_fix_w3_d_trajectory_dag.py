"""W3-D — Trajectory-SSOT, Repeat-Budget, DAG-Recovery, Budget-Fail-Closed.

ALLE Tests arbeiten ausschliesslich mit ``tmp_path``/expliziten DB-Pfaden.
Es wird NEVER gegen ``./data`` geschrieben (Produktiv-DBs sind tabu).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# D13-MED / F032: Depth-SSOT + kein Expand-Pfad
# ---------------------------------------------------------------------------

def test_depth_ssot_is_three_and_cannot_be_widened(tmp_path):
    from backend import trajectory_budget as tb

    assert tb.MAX_DELEGATION_DEPTH == 3
    assert tb.DEFAULT_MAX_HOPS == tb.MAX_DELEGATION_DEPTH
    assert tb.clamp_max_hops(50) == 3
    assert tb.clamp_max_hops(None) == 0

    db = str(tmp_path / "traj.db")
    first = tb.ensure_trajectory(max_hops=50, root_ticket_id="ssot-ticket", db_path=db)
    assert first["max_hops"] == 3
    second = tb.ensure_trajectory(max_hops=50, root_ticket_id="ssot-ticket", db_path=db)
    assert second["max_hops"] == 3  # ensure_trajectory verschaeft nur


def test_dag_validator_rejects_hops_above_ssot():
    from backend.workflow_dag_runner import validate_dag_def

    base = {"nodes": [{"id": "a"}], "max_budget_eur": 1.0}
    bad = validate_dag_def({**base, "max_hops": 50})
    assert bad["valid"] is False
    assert any("max_hops" in e and "3" in e for e in bad["errors"]), bad["errors"]
    good = validate_dag_def({**base, "max_hops": 3})
    assert good["valid"] is True, good["errors"]


def test_no_runtime_widener_left_in_dag_source():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "AND max_hops < ?" not in src, "Der 50er-Expand-Pfad muss ersatzlos entfernt sein."
    assert "max_hops=(_max_hops_cfg or None)" in src
    assert "min(50" in src  # Rueckwaertskompatibler Parser-Guard (stale source test)
    assert "asyncio.to_thread(_persist_run_cancelled_sync" in src
    assert "_finalize_run_sync, db_path, rid, wf_id" in src
    assert "_persist_node_state_sync, db_path, rid, nid" in src


# ---------------------------------------------------------------------------
# D13-MED: gezaehltes Repeat-Budget statt Präfix-Whitelist
# ---------------------------------------------------------------------------

def test_tool_call_is_visible_in_visited_set(tmp_path, monkeypatch):
    from backend import trajectory_budget as tb

    audits = []
    monkeypatch.setattr(tb, "_audit", lambda *a, **k: audits.append(a))
    db = str(tmp_path / "traj.db")
    tid = tb.ensure_trajectory(root_ticket_id="tool-cycle", db_path=db)["trajectory_id"]
    first = tb.reserve_hop(tid, "agent_a", "dag_node_start", db_path=db)
    second = tb.reserve_hop(tid, "agent_a", "tool:search", db_path=db)
    assert first["allowed"] is True and second["allowed"] is True
    assert "agent_a::tool:search" in second["visited_agents"]

    # A -> tool -> A (echter Agentwechsel) bleibt sofort CYCLE_DETECTED.
    third = tb.reserve_hop(tid, "agent_a", "agent_switch", db_path=db)
    assert third["allowed"] is False and third["reason"] == "CYCLE_DETECTED"
    assert audits, "Cycle muss auditiert werden"


def test_repeat_budget_caps_llm_call_even_with_allow_repeat(tmp_path, monkeypatch):
    from backend import trajectory_budget as tb

    monkeypatch.setattr(tb, "_audit", lambda *a, **k: None)
    db = str(tmp_path / "traj.db")
    tid = tb.ensure_trajectory(root_ticket_id="repeat-cap", db_path=db)["trajectory_id"]
    tb.set_repeat_budget(tid, "agent-r", "llm_call:agent-r", 1, db_path=db)

    results = [
        tb.reserve_hop(tid, "agent-r", "llm_call:agent-r", allow_repeat=True, db_path=db)
        for _ in range(3)
    ]
    assert results[0]["allowed"] is True
    assert results[1]["allowed"] is True
    assert results[2]["allowed"] is False
    assert results[2]["reason"] == "CYCLE_DETECTED"
    assert results[2]["detail"] == "REPEAT_BUDGET_EXCEEDED"

    status = tb.repeat_budget_status(tid, "agent-r", "llm_call:agent-r", db_path=db)
    assert status["used"] == 1 and status["limit"] == 1


def test_retry_prefix_is_no_longer_a_blanket_exemption(tmp_path, monkeypatch):
    from backend import trajectory_budget as tb

    monkeypatch.setattr(tb, "_audit", lambda *a, **k: None)
    db = str(tmp_path / "traj.db")
    tid = tb.ensure_trajectory(root_ticket_id="retry-cap", db_path=db)["trajectory_id"]
    tb.set_repeat_budget(tid, "agent-r", "retry", 1, db_path=db)
    tb.reserve_hop(tid, "agent-r", "agent_switch", db_path=db)         # erster Besuch
    assert tb.reserve_hop(tid, "agent-r", "retry:1", db_path=db)["allowed"] is True
    blocked = tb.reserve_hop(tid, "agent-r", "retry:2", db_path=db)
    assert blocked["allowed"] is False and blocked["reason"] == "CYCLE_DETECTED"


# ---------------------------------------------------------------------------
# D07: Cancelled-Persistenz, Flightlog-Audit, Lease-Recovery
# ---------------------------------------------------------------------------

def test_cancelled_error_persists_status_through_threadpool(tmp_path, monkeypatch):
    import backend.workflow_dag_runner as dag

    db = str(tmp_path / "dag.db")
    with dag._connect(db) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (run_id, workflow_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            ("run-cancel", "wf", time.time(), time.time()),
        )
        conn.commit()

    async def _boom(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(dag, "_run_workflow_dag_impl", _boom)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dag.run_workflow_dag({"nodes": []}, run_id="run-cancel", db_path=db))

    with dag._connect(db) as conn:
        status = conn.execute(
            "SELECT status FROM workflow_runs WHERE run_id = ?", ("run-cancel",)
        ).fetchone()[0]
    assert status == "cancelled"


def test_flightlog_audit_failure_is_escalated(tmp_path, monkeypatch):
    import backend.flightlog_backtester as fb
    import backend.workflow_dag_runner as dag
    from backend import trajectory_budget as tb

    monkeypatch.setattr(fb, "record_flight_event", lambda **kwargs: None)
    monkeypatch.setattr(fb, "mirror_flight_event_to_trace", lambda **kwargs: None)
    monkeypatch.setattr(fb, "detect_silent_failures", lambda *a, **k: {"flags": ["loop"]})
    monkeypatch.setattr(tb, "close_trajectory", lambda *a, **k: {})
    monkeypatch.setattr(tb, "record_tokens", lambda *a, **k: {"allowed": True})

    def _audit_boom(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(tb, "_audit", _audit_boom)
    escalations = []
    monkeypatch.setattr(dag, "_recovery_audit", lambda action, payload: escalations.append(action))

    db = str(tmp_path / "dag.db")
    out = dag._finalize_run_sync(db, "run-flight", "wf", "completed", None, "traj-x", {})
    assert out["final_status"] == "blocked"
    assert "SILENT_FAILURE" in str(out["cycle_error"])
    assert "audit_write_failed" in escalations


def test_recover_orphaned_runs_terminates_expired_lease(tmp_path):
    import backend.workflow_dag_runner as dag

    kernel_db = str(tmp_path / "kernel.db")
    conn = sqlite3.connect(kernel_db)
    conn.execute(
        "CREATE TABLE durable_executions (run_id TEXT PRIMARY KEY, state TEXT, "
        "fencing_token TEXT, claim_expires REAL)"
    )
    conn.execute(
        "INSERT INTO durable_executions VALUES (?, ?, ?, ?)",
        ("orphan-1", "RUNNING", "old-token", time.time() - 10.0),
    )
    conn.commit()
    conn.close()

    class FakeKernel:
        def __init__(self):
            self.db_path = kernel_db
            self.transitions = []

        def claim(self, run_id, ttl_seconds=300, dag_fingerprint="", fencing_token=None):
            return {"claimed": True, "fencing_token": fencing_token or "fresh-token"}

        def transition(self, run_id, to_state, token, reason=""):
            self.transitions.append((run_id, to_state, reason))
            return {"status": "transitioned"}

    kernel = FakeKernel()
    out = dag.recover_orphaned_runs(
        db_path=str(tmp_path / "dag.db"), kernel=kernel, only_run_id="orphan-1",
    )
    assert out["scanned"] == 1
    assert out["recovered"][0]["run_id"] == "orphan-1"
    assert kernel.transitions == [("orphan-1", "FAILED", "lease_lost")]


def test_recovery_errors_are_not_swallowed_in_source():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    for marker in (
        "cancel_status_persist_failed",
        "status_transition_failed",
        "terminal_transition_failed",
        "lease_lost_unrecovered",
        "flightlog_flags fehlgeschlagen",
    ):
        assert marker in src, f"Fehlender D07-Eskalationspfad: {marker}"
    assert 'logger.debug("[WorkflowDAG] Cancelled-Status nicht persistierbar' not in src
    assert 'logger.debug("[WorkflowDAG] Durable-Kernel Transition fehlgeschlagen' not in src


# ---------------------------------------------------------------------------
# D07/F7: SSE-Broadcast-Fehler sichtbar (Log + Metrik)
# ---------------------------------------------------------------------------

def test_scheduler_broadcast_failure_is_logged_and_counted(tmp_path, monkeypatch, caplog):
    import archon.core.runtime as runtime
    import backend.workflow_scheduler as ws

    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", str(tmp_path / "sched.db"))
    monkeypatch.setattr(ws, "_EVENT_BUS_BROADCAST_FAILED", 0)
    telemetry = []
    monkeypatch.setattr(ws, "_enqueue_telemetry", lambda *a, **k: telemetry.append(a[0]))

    def _boom(*args, **kwargs):
        raise RuntimeError("sse bus down")

    monkeypatch.setattr(runtime, "broadcast_event", _boom)
    with caplog.at_level(logging.WARNING, logger="backend.workflow_scheduler"):
        out = ws.dispatch_workflow_event("manual", "test_event", title="t", tenant_id="default")
    assert out["event_id"]
    assert ws.event_bus_broadcast_failed_count() == 1
    assert "event_bus_broadcast_failed" in telemetry
    assert "SSE-Event-Broadcast" in caplog.text


# ---------------------------------------------------------------------------
# D13-MED: Task-Cap fail-closed in BudgetBank.reserve
# ---------------------------------------------------------------------------

def test_budget_reserve_fails_closed_without_task_allocation(tmp_path):
    from backend.role_budget_engine import BudgetBank

    db = str(tmp_path / "budget.db")
    bank = BudgetBank(db_path=db)
    denied = bank.reserve(
        "agent-x", task_id="unregistered-task", estimated_tokens=10, estimated_cost_eur=0.01,
    )
    assert denied["allowed"] is False
    assert denied["error_code"] == "TASK_BUDGET_NOT_REGISTERED"

    now = time.time()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO task_budget_allocations "
        "(task_id, agent_id, token_budget, tokens_used, cost_limit_eur, cost_used_eur, created_at, updated_at) "
        "VALUES (?, ?, ?, 0, ?, 0.0, ?, ?)",
        ("registered-task", "agent-x", 1000, 10.0, now, now),
    )
    conn.commit()
    conn.close()
    allowed = bank.reserve(
        "agent-x", task_id="registered-task", estimated_tokens=10, estimated_cost_eur=0.01,
    )
    assert allowed["allowed"] is True, allowed

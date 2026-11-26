"""W3-D — Trajectory-Governance: D13-H1 + M1/M2/M3 (SQLite ONLY).

Kein Replay, keine Postgres-Migration. Alle DB-Zeilen liegen in tmp_path.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import archon.core.dispatch_budget_cache as dbc
import backend.flightlog_backtester as flb
import backend.role_budget_engine as rbe
import backend.trajectory_budget as tb
from backend.trace_context import use_trace_context

# ---------------------------------------------------------------------------
# D13-H1 — stabile Trajectory-Root-Korrelation
# ---------------------------------------------------------------------------

def test_normalize_without_root_never_produces_anonymous_time_id() -> None:
    with use_trace_context(trace_id="a" * 32, span_id="b" * 16):
        first = tb.normalize_trajectory_id()
        second = tb.normalize_trajectory_id(None, root_ticket_id="", session_id="")
    assert first == second
    assert first.startswith("traj-")
    assert "anonymous" not in first
    assert "time" not in first.lower()

    # Ohne jeglichen Kontext bleibt die ID deterministisch (Fail-closed).
    assert tb.stable_trajectory_id("") == tb.stable_trajectory_id("")
    assert tb.stable_trajectory_id("") == tb.normalize_trajectory_id()


def test_trajectory_root_scope_is_stable_per_session() -> None:
    with tb.trajectory_root_scope("quickchat:session-42") as root:
        a = tb.normalize_trajectory_id()
        b = tb.normalize_trajectory_id()
    assert a == b == tb.stable_trajectory_id(root)
    with tb.trajectory_root_scope("quickchat:session-43") as other:  # noqa: F841
        assert tb.normalize_trajectory_id() != a
    # Scope wurde zurueckgesetzt — kein Leak in den naechsten Request.
    assert tb.current_trajectory_root() == ""


def test_dispatch_without_root_is_counted(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "ops.db")
    monkeypatch.setattr(tb, "resolve_trajectory_db_path", lambda _p=None: db)
    monkeypatch.setattr(tb, "expire_stale_reservations", lambda **_k: {"expired": 0})
    dbc._DISPATCH_WITHOUT_ROOT.clear()
    with use_trace_context(trace_id="c" * 32, span_id="d" * 16):
        result = dbc._reserve_trajectory_budget_sync("", "agent-a", 100)
    assert result["allowed"] is True
    assert result["root_present"] is False
    metrics = dbc.get_dispatch_without_root_metrics()
    assert metrics.get("trace", 0) >= 1


# ---------------------------------------------------------------------------
# D13-M3 — Actual-Token-Reconciliation, Gegenbuchung, TTL, Audit
# ---------------------------------------------------------------------------

def test_reserve_settle_release_and_ttl(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "ops.db")
    monkeypatch.setattr(tb, "resolve_trajectory_db_path", lambda _p=None: db)
    tid = tb.ensure_trajectory(root_ticket_id="ticket-m3", db_path=db)["trajectory_id"]

    reserved = tb.reserve_tokens(tid, 10_000, reason="estimate", agent_id="agent-a", db_path=db)
    assert reserved["allowed"] is True
    assert tb.get_trajectory(tid, db_path=db)["tokens_used"] == 10_000  # type: ignore[index]
    assert tb.get_trajectory(tid, db_path=db)["reserved_tokens"] == 10_000  # type: ignore[index]

    done = tb.finalize_tokens(
        tid, reservation_id=reserved["reservation_id"], actual_tokens=2_000, db_path=db
    )
    assert done["status"] == "settled"
    row = tb.get_trajectory(tid, db_path=db)
    assert (row["tokens_used"], row["reserved_tokens"], row["actual_tokens"]) == (2_000, 0, 2_000)  # type: ignore[index]

    second = tb.reserve_tokens(tid, 3_000, reason="estimate", agent_id="agent-a", db_path=db)
    released = tb.release_tokens(tid, reservation_id=second["reservation_id"], db_path=db)
    assert released["status"] == "settled"
    assert tb.get_trajectory(tid, db_path=db)["tokens_used"] == 2_000  # type: ignore[index]

    third = tb.reserve_tokens(tid, 5_000, reason="estimate", agent_id="agent-a", db_path=db)
    expired = tb.expire_stale_reservations(
        db_path=db, now=time.time() + tb.RESERVATION_TTL_SECONDS + 60
    )
    assert expired["expired"] >= 1
    assert third["reservation_id"] in [r["reservation_id"] for r in expired["reservations"]]
    assert tb.get_trajectory(tid, db_path=db)["tokens_used"] == 2_000  # type: ignore[index]
    assert tb.get_trajectory(tid, db_path=db)["reserved_tokens"] == 0  # type: ignore[index]


def test_budget_bank_settle_reconciles_estimate_to_actual(tmp_path, monkeypatch) -> None:
    """Der Dispatcher ruft budget_bank.settle() im Erfolgspfad — dort muss
    die Trajectory-Reservierung gegen den echten Wert abgerechnet werden."""
    traj_db = str(tmp_path / "ops.db")
    budget_db = str(tmp_path / "agentic_memory.db")
    monkeypatch.setattr(tb, "resolve_trajectory_db_path", lambda _p=None: traj_db)
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", budget_db)
    rbe._INITIALIZED_BUDGET_DBS.discard(budget_db)
    monkeypatch.setattr(rbe.budget_bank, "db_path", budget_db)

    audit_events = []

    class _FakeAudit:
        def record_event(self, **kwargs):
            audit_events.append(kwargs)

    import backend.audit_log as audit_mod
    monkeypatch.setattr(audit_mod, "chained_audit_log", _FakeAudit())
    monkeypatch.setattr(tb.broadcast_event if hasattr(tb, "broadcast_event") else tb, "broadcast_event", lambda *_a, **_k: None, raising=False)

    # Beide Reservierungen laufen im selben Request-Kontext wie im Chokepoint.
    with use_trace_context(trace_id="e" * 32, span_id="f" * 16):
        gate = dbc._reserve_trajectory_budget_sync("", "agent-a", 10_000, "llm_call:agent-a")
        assert gate["allowed"] is True
        tid = gate["trajectory_id"]
        bank = rbe.budget_bank.reserve(
            agent_id="agent-a", task_id=None, estimated_tokens=10_000, estimated_cost_eur=0.0
        )
    assert tb.get_trajectory(tid, db_path=traj_db)["tokens_used"] == 10_000  # type: ignore[index]
    assert bank["allowed"] is True
    assert bank["trajectory_id"] == tid

    settled = rbe.budget_bank.settle(bank["reservation_id"], actual_tokens=2_000)
    assert settled["status"] == "settled"
    row = tb.get_trajectory(tid, db_path=traj_db)
    assert row["tokens_used"] == 2_000, row  # type: ignore[index]
    assert row["reserved_tokens"] == 0  # type: ignore[index]
    assert any(
        e.get("payload", {}).get("estimated") == 10_000
        and e.get("payload", {}).get("actual") == 2_000
        for e in audit_events
    ), audit_events


def test_budget_bank_release_clears_reservation(tmp_path, monkeypatch) -> None:
    traj_db = str(tmp_path / "ops.db")
    budget_db = str(tmp_path / "agentic_memory.db")
    monkeypatch.setattr(tb, "resolve_trajectory_db_path", lambda _p=None: traj_db)
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", budget_db)
    rbe._INITIALIZED_BUDGET_DBS.discard(budget_db)
    monkeypatch.setattr(rbe.budget_bank, "db_path", budget_db)

    for i in range(3):
        with use_trace_context(trace_id=str(i + 1) * 32, span_id=str(i + 2) * 16):
            gate = dbc._reserve_trajectory_budget_sync("", "agent-b", 1_000)
            assert gate["allowed"] is True
            bank = rbe.budget_bank.reserve(
                agent_id="agent-b", task_id=None, estimated_tokens=1_000
            )
            assert rbe.budget_bank.release(bank["reservation_id"], "blocked")["status"] == "released"
        assert tb.get_trajectory(gate["trajectory_id"], db_path=traj_db)["tokens_used"] == 0  # type: ignore[index]


# ---------------------------------------------------------------------------
# D13-M1 — Admin-Endpoint: Ceilings, Parent-Check, transaktionales Hiring
# ---------------------------------------------------------------------------

def test_allocate_request_has_no_unbounded_default() -> None:
    import archon.routers.operations_org as ops

    req = ops.TaskBudgetAllocateRequest()
    assert req.total_token_budget is None
    with pytest.raises(ValidationError):
        ops.TaskBudgetAllocateRequest(total_token_budget=rbe.TASK_BUDGET_TOKEN_CEILING + 1)
    with pytest.raises(ValidationError):
        ops.TaskBudgetAllocateRequest(total_cost_limit_eur=rbe.TASK_BUDGET_COST_CEILING_EUR + 1)


def test_allocate_endpoint_returns_409_and_hires_nothing_on_blocked(tmp_path, monkeypatch) -> None:
    import archon.routers.operations_org as ops

    budget_db = str(tmp_path / "agentic_memory.db")
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", budget_db)
    rbe._INITIALIZED_BUDGET_DBS.discard(budget_db)
    monkeypatch.setattr(ops, "require_admin_or_503", lambda *_a, **_k: None)

    req = ops.TaskBudgetAllocateRequest(allow_autonomous_hiring=True)
    with pytest.raises(HTTPException) as exc:
        ops.api_allocate_task_budget(object(), "orphan-task", req)  # type: ignore[arg-type]
    assert exc.value.status_code in (409, 422)

    with rbe._get_conn(budget_db) as conn:
        hired = conn.execute(
            "SELECT COUNT(*) FROM autonomous_hired_agents WHERE parent_task_id = ?",
            ("orphan-task",),
        ).fetchone()[0]
    assert hired == 0


def test_hiring_happens_after_allocation_with_exact_share(tmp_path, monkeypatch) -> None:
    budget_db = str(tmp_path / "agentic_memory.db")
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", budget_db)
    rbe._INITIALIZED_BUDGET_DBS.discard(budget_db)

    plan = rbe.plan_and_decompose_task_with_budgets(
        "t-hire", "Bauprojekt.prüfen", "Technische und kaufmännische Prüfung",
        total_token_budget=100_000, allow_autonomous_hiring=True, db_path=budget_db,
    )
    assert plan.get("status") != "blocked"
    hired = plan["hired_specialist"]
    assert hired is not None and hired["agent_id"].startswith("hired_")
    alloc = next(
        a for a in plan["budget_plan"]["allocations"] if a["agent_id"] == hired["agent_id"]
    )
    assert hired["token_budget"] == alloc["token_budget"]
    assert all(not a["agent_id"].startswith("hired_placeholder_")
               for a in plan["budget_plan"]["allocations"])


# ---------------------------------------------------------------------------
# D13-M2 — Flightlog-Loops unabhaengig von args_hash
# ---------------------------------------------------------------------------

def test_tool_name_frequency_loop_is_detected(tmp_path) -> None:
    db = str(tmp_path / "flightlog.db")
    for args in ({"q": "a"}, {"q": "b"}, {"q": "c"}):
        flb.record_flight_event(
            "run-loop", "agent-a", "search", args=args, db_path=db,
            trajectory_id="traj-loop", hop_index=1,
        )
    finding = flb.detect_silent_failures("run-loop", db_path=db)
    assert any(f.startswith("tool_loop:search") for f in finding["flags"]), finding
    assert finding["loop_details"][0]["trajectory_id"] == "traj-loop"
    assert finding["loop_details"][0]["hop_index"] == 1


def test_cyclic_agent_tool_pattern_is_detected(tmp_path) -> None:
    db = str(tmp_path / "flightlog.db")
    for i, (agent, tool) in enumerate([
        ("agent-a", "tool_x"), ("agent-b", "tool_y"),
        ("agent-a", "tool_x"), ("agent-b", "tool_y"),
    ]):
        flb.record_flight_event(
            "run-cycle", agent, tool, args={"i": i}, db_path=db,
            trajectory_id="traj-cycle", hop_index=i,
        )
    finding = flb.detect_silent_failures("run-cycle", db_path=db)
    assert any(f.startswith("tool_loop:cycle:") for f in finding["flags"]), finding


def test_no_loop_for_distinct_tools(tmp_path) -> None:
    db = str(tmp_path / "flightlog.db")
    for i, tool in enumerate(("search", "read", "write")):
        flb.record_flight_event(
            "run-ok", "agent-a", tool, args={"i": i}, db_path=db,
            trajectory_id="traj-ok", hop_index=i,
        )
    finding = flb.detect_silent_failures(
        "run-ok", final_output="Eine ausreichend lange Abschlussantwort.", db_path=db
    )
    assert finding["silent_failure"] is False, finding


def test_flight_event_carries_trajectory_and_hop(tmp_path) -> None:
    db = str(tmp_path / "flightlog.db")
    flb.record_flight_event(
        "run-meta", "agent-a", "search", db_path=db,
        trajectory_id="traj-meta", hop_index=4,
    )
    with flb._connect(db) as conn:
        row = conn.execute(
            "SELECT trajectory_id, hop_index FROM flight_events WHERE run_id = ?",
            ("run-meta",),
        ).fetchone()
    assert (row["trajectory_id"], row["hop_index"]) == ("traj-meta", 4)


def test_async_dispatch_gate_is_callable() -> None:
    """Der Gate-Helfer bleibt der vom Chokepoint re-exportierte Sync-Helfer."""
    assert asyncio.iscoroutinefunction(dbc._reserve_trajectory_budget_sync) is False

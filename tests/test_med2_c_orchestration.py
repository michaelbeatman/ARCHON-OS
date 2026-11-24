"""Re-Audit Etappe MED-2/C — Orchestrierung, Konsens, Handoff, Trajectory.

Deckt die verbleibenden MED-Funde aus domain_02/11/12/13/14 in den Dateien
ab, die diesem Agenten gehoeren. Kein Replay, keine Migration.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- D11: extra="forbid" ist fuer Dict-Eingaben echt -------------------------

def test_debate_statement_forbid_rejects_shadow_field():
    from backend.consensus_gate import validate_debate_statements

    ok = validate_debate_statements([
        {
            "type": "agent_response", "round": 1, "agent_id": "senior_coder",
            "agent_name": "Coder", "role": "Expert", "content": "KONSENS_ERREICHT",
        }
    ])
    assert len(ok) == 1 and not ok[0].policy_violation

    shadowed = validate_debate_statements([
        {"agent_id": "senior_coder", "content": "ZUSTIMME", "shadow_field": "x"}
    ])
    assert len(shadowed) == 1
    assert shadowed[0].policy_violation is True


def test_policy_veto_uses_structured_guardrail_result():
    from backend.consensus_gate import resolve_debate_consensus

    result = resolve_debate_consensus([
        {"agent_id": "senior_coder", "content": "ZUSTIMME", "guardrail_violation": True}
    ])
    assert result["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"
    assert result["consensus_reached"] is False


def test_missing_critique_is_not_fabricated(monkeypatch):
    import core_dispatcher
    from backend.consensus_gate import review_task_output

    async def _fake_dispatch(**kwargs):
        # Gueltiges JSON, aber ohne das Pflichtfeld `critique`.
        return {"content": '{"approved": true, "score": 9, "verdict": "APPROVED"}'}

    monkeypatch.setattr(
        core_dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch
    )
    out = asyncio.run(review_task_output("t-critique", "Test", "output"))
    assert out["approved"] is False
    assert out["evaluation_failed"] is True
    assert "keine gravierenden" not in out["critique"].lower()


# --- D11: reply_to-Kette aus SQLite, Korrelation aus Trace -------------------

def test_handoff_reply_to_lookup_uses_sqlite(tmp_path):
    from backend.handoff_desk import HandoffDesk

    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    first = desk.create_handoff("parent-task", "a", "b", {"result": "x"}, "K", trace_id="tr")
    second = desk.create_handoff("parent-task", "b", "c", {"result": "y"}, "K", trace_id="tr")
    assert desk.latest_handoff_id_for_task("parent-task") == second["handoff_id"]
    assert first["handoff_id"] != second["handoff_id"]
    assert desk.latest_handoff_id_for_task("") == ""
    assert desk.latest_handoff_id_for_task("unknown") == ""


def test_delegation_has_no_ram_handoff_dict_and_no_removed_profile():
    src = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert "_HANDOFF_IDS_BY_TASK" not in src
    assert "latest_handoff_id_for_task" in src
    assert '"micha"' not in src
    assert "trace_id=_handoff_trace" in src
    assert "session_id=str(origin_sess_id" in src


# --- D11: replan_count ist ein funktionierender Alias -----------------------

def test_replan_count_alias_survives_budget_caps_and_reload():
    from archon.core import mission_control as mc

    meta = mc.enforce_task_budget_caps({"replans_used": 2, "max_replans": 3})
    assert meta["replan_count"] == 2
    reverse = mc.enforce_task_budget_caps({"replan_count": 1, "max_replans": 3})
    assert reverse["replans_used"] == 1


# --- D13: Token-Cap zur Laufzeit --------------------------------------------

def test_reserve_tokens_enforces_cap_during_run(tmp_path):
    from backend.trajectory_budget import (
        close_trajectory, ensure_trajectory, get_trajectory,
        record_tokens, reserve_tokens,
    )

    db = str(tmp_path / "traj.db")
    tid = ensure_trajectory(max_tokens=100, root_ticket_id="ticket-runtime", db_path=db)["trajectory_id"]
    assert reserve_tokens(tid, 60, db_path=db)["allowed"] is True
    blocked = reserve_tokens(tid, 60, db_path=db)
    assert blocked["allowed"] is False and blocked["reason"] == "TOKEN_CAP_REACHED"
    # Abschluss darf die Reservierung nicht verdoppeln und nicht aufheben.
    final = record_tokens(tid, 60, db_path=db, set_total=True)
    assert final["allowed"] is True and final["tokens_used"] == 60
    assert close_trajectory(tid, "completed", db_path=db)["state"] == "blocked"
    assert get_trajectory(tid, db_path=db)["state"] == "blocked"


def test_dag_wires_runtime_reservation_and_30s_heartbeat():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "HEARTBEAT_INTERVAL_SEC = 30" in src
    assert "asyncio.sleep(60)" not in src
    assert "reserve_tokens(" in src
    assert "TRAJECTORY_TOKEN_CAP" in src
    assert "set_total=True" in src
    assert "_lease_heartbeat(rid" in src


def test_initial_dag_run_has_durable_claim():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    # Der Claim steht vor dem lokalen Lock und gilt nur ohne bereits gesetztes
    # Fencing-Token (Resume claimt nicht doppelt).
    assert 'if not fencing_token:' in src
    assert "durable_claim_not_acquired" in src
    assert "lease_guard = _LeaseGuard()" in src


# --- D13: HANDOFF-Vertraege (Guard-Fenster, Zombie-Lease) --------------------

def test_guard_window_and_zombie_lease_contracts():
    from backend.trajectory_budget import guard_window_size, zombie_eligible

    assert guard_window_size({"max_steps_per_task": 15}) == 16
    now = 1_000_000.0
    assert zombie_eligible(
        {"status": "in_progress", "claim_expires": now + 100}, now=now
    ) is False
    assert zombie_eligible(
        {"status": "in_progress", "claim_expires": now - 100}, now=now
    ) is True


def test_reserve_replan_cap_in_pytest(tmp_path):
    from backend.trajectory_budget import ensure_trajectory, reserve_replan

    db = str(tmp_path / "replan.db")
    tid = ensure_trajectory(max_replans=2, root_ticket_id="ticket-replan", db_path=db)["trajectory_id"]
    assert reserve_replan(tid, run_id="r1", db_path=db)["allowed"] is True
    assert reserve_replan(tid, run_id="r2", db_path=db)["allowed"] is True
    third = reserve_replan(tid, run_id="r3", db_path=db)
    assert third["allowed"] is False and third["reason"] == "replan_cap_reached"

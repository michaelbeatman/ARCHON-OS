# -*- coding: utf-8 -*-
"""W3-A — Orchestrierung + Handoff (F030/F031/F033, D13/D11/D07).

Alle Tests sind offline/deterministisch. DB-Zugriffe laufen ausschließlich
über explizit übergebene ``tmp_path``-Pfade oder monkeypatchte SSOT-Funktionen;
es wird nie gegen ``./data`` geschrieben.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import archon.core.delegation as delegation
import archon.core.orchestration as orchestration
import backend.agent_router as agent_router
import backend.cancellation as cancellation
from archon.routers.chat import history_with_dropped_marker
from backend.consensus_gate import (
    resolve_debate_consensus,
    validate_debate_statements,
)
from backend.handoff_desk import HandoffDesk, require_accepted_handoff
from backend.precedent_log import resolve_task_tenant_id


# ---------------------------------------------------------------------------
# H-02-1 — Unknown-Agent fail-closed (kein Substring-/Rollen-Fallback)
# ---------------------------------------------------------------------------

def test_unknown_agent_has_no_substring_fallback():
    profiles = [
        {"id": "default", "role": "Hermes Orchestrator (Root)"},
        {"id": "finance_lead", "role": "Finance Lead"},
    ]
    # "orchestrator" war der Angriffsvektor: Substring traf @default (APEX,
    # terminal/filesystem). Jetzt: kein Treffer.
    assert delegation._resolve_target_agent_id("orchestrator", profiles) == (None, "")
    assert delegation._resolve_target_agent_id("lead", profiles) == (None, "")
    # Explizite ID und Whitelist bleiben erhalten.
    assert delegation._resolve_target_agent_id("finance_lead", profiles)[0] == "finance_lead"
    assert delegation._resolve_target_agent_id(" FINANCE_LEAD ", profiles)[0] == "finance_lead"


def test_unknown_agent_receipt_is_blocked(monkeypatch):
    monkeypatch.setattr(
        delegation, "api_get_hermes_profiles",
        lambda: [{"id": "default", "role": "Hermes Orchestrator (Root)"}],
    )
    monkeypatch.setattr("backend.trajectory_budget._audit", lambda *a, **k: None)
    monkeypatch.setattr("backend.trajectory_budget.get_trajectory", lambda *a, **k: None)
    monkeypatch.setattr(
        "archon.core.mission_control.mc_update_task_sqlite", lambda *a, **k: None
    )
    receipt = delegation._execute_delegation(
        "default",
        {"ziel_agent": "orchestrator", "auftrag": "test", "root_ticket_id": "traj-w3a"},
        provider=None, all_keys={}, origin_session_id=None,
    )
    assert receipt.status == "blocked"
    assert receipt.block_kind == "unknown_agent"
    assert "UNKNOWN_AGENT" in str(receipt)


# ---------------------------------------------------------------------------
# H-02-2 — cancelled ist terminal; Parent blockiert statt stumm zu hängen
# ---------------------------------------------------------------------------

def test_cancelled_child_blocks_parent_without_synthesis():
    data = {"tasks": [
        {"id": "parent", "title": "Projekt"},
        {"id": "c1", "parent_project_id": "parent", "status": "done"},
        {"id": "c2", "parent_project_id": "parent", "status": "cancelled"},
    ]}
    decision = orchestration.fan_in_start_decision(data, "parent")
    assert not decision.get("start")
    assert "c2" in str(decision["blocked"])
    assert decision["cancelled"] == "c2"
    parent = data["tasks"][0]
    assert parent["status"] == "blocked"
    assert "abgebrochen" in parent["failure_reason"]
    assert parent["fan_in_escalation"] == "hitl_required"
    assert not parent.get("synthesis_started")


def test_all_done_still_starts_synthesis():
    data = {"tasks": [
        {"id": "parent"},
        {"id": "c1", "parent_project_id": "parent", "status": "done"},
        {"id": "c2", "parent_project_id": "parent", "status": "review"},
    ]}
    decision = orchestration.fan_in_start_decision(data, "parent")
    assert decision["start"] == 2
    assert data["tasks"][0]["synthesis_started"] is True


# ---------------------------------------------------------------------------
# H-14-1 — echter Marker-Produzent aus dem Dispatch-Result
# ---------------------------------------------------------------------------

def test_dispatch_verdict_is_extracted_from_real_result():
    res = {
        "status": "success",
        "content": "Analyse",
        "consensus_verdict": "CONSENSUS_REACHED",
        "guardrail_result": {"policy_violation": False, "severity": "low",
                             "source_trace_id": "trace-1"},
    }
    verdict = orchestration.extract_dispatch_verdict(res, "completed")
    assert verdict["consensus_verdict"] == "CONSENSUS_REACHED"
    assert verdict["verdict_source"].startswith("dispatch_result:")
    assert verdict["source_trace_id"] == "trace-1"
    assert orchestration.fan_verdict_marker(verdict) == "KONSENS_ERREICHT"


def test_marker_is_never_empty_and_real_votes_are_counted():
    no_vote = orchestration.fan_verdict_marker({})
    assert no_vote and orchestration._FAN_NO_VOTE_MARKER in no_vote
    statements = [
        {"agent_id": "a", "content": f"Bericht\n{no_vote}"},
        {"agent_id": "b", "content": "Bericht\nKONSENS_ERREICHT"},
        {"agent_id": "c", "content": "Bericht\nKONSENS_ERREICHT", "verdict_source": "dispatch_result:verdict"},
    ]
    result = resolve_debate_consensus(validate_debate_statements(statements))
    # Zwei echte Ja-Stimmen, eine Enthaltung → 2/2 = Konsens ( kein 0/0-Theater ).
    assert result["total_votes"] == 2
    assert result["yes_votes"] == 2
    assert result["verdict"].startswith("CONSENSUS_REACHED")


def test_policy_violation_from_dispatch_is_hard_veto():
    res = {"status": "success", "content": "x",
           "guardrail_result": {"policy_violation": True, "severity": "high"}}
    verdict = orchestration.extract_dispatch_verdict(res)
    assert orchestration.fan_verdict_marker(verdict) == "POLICY_VIOLATION"
    statements = [{"agent_id": "a", "content": "x\nPOLICY_VIOLATION", "policy_violation": True}]
    result = resolve_debate_consensus(validate_debate_statements(statements))
    assert result["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"


# ---------------------------------------------------------------------------
# H-11-1/2 — EIN kanonisches Schema, serverseitig aufgelöst und signiert
# ---------------------------------------------------------------------------

def test_canonical_schema_unifies_both_models(monkeypatch):
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w3a-delegation-key")
    assert (
        delegation.DelegationPayload
        is delegation.KanbanDelegationPayload
        is delegation.HandoffDelegationPayload
    )
    with pytest.raises(ValidationError):
        delegation.HandoffDelegationPayload.model_validate(
            {"ziel_agent": "a", "auftrag": "x", "schattenfeld": 1}
        )


def test_canonicalize_keeps_extensions_and_signs_server_context(monkeypatch):
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w3a-delegation-key")
    raw = {
        "ziel_agent": "finance_lead", "auftrag": "Prüfen",
        "isolated": True, "allowed_tools": ["read_file"],
        "tenant_id": "client-provided-evil",
        "soul_mode": "full", "schattenfeld": 42,
    }
    payload = delegation.canonicalize_delegation_payload(
        raw, trajectory_id="traj-w3a", task_id="t-w3a", session_id="s-w3a"
    )
    assert payload["tenant_id"] != "client-provided-evil"
    assert payload["project_id"] == "" or isinstance(payload["project_id"], str)
    assert payload["cancel_scope"] == "task:t-w3a"
    assert payload["budget_remaining_tokens"] == 0
    assert payload["soul_mode"] == "full"
    assert payload["extensions"]["schattenfeld"] == 42
    assert payload["isolated"] is True
    assert delegation.verify_delegation_payload(payload) is True
    tampered = dict(payload, tenant_id="attacker")
    assert delegation.verify_delegation_payload(tampered) is False


def test_child_cancel_token_propagates_parent_abort():
    parent_id, child_id = "t-w3a-parent", "t-w3a-child"
    child = cancellation.get_task_child_token(parent_id, child_id)
    assert not child.cancelled
    assert cancellation.cancel_scope(cancellation.task_scope(parent_id), "w3a-test")
    assert child.cancelled is True
    cancellation.clear_scope(cancellation.task_scope(parent_id))
    cancellation.clear_scope(cancellation.task_scope(child_id))


# ---------------------------------------------------------------------------
# D13 — Guardian-Toggle wirkt, gezählter Retry statt allow_repeat
# ---------------------------------------------------------------------------

def test_guardian_writes_circuit_breaker_ssot(monkeypatch):
    import archon.routers.autonomy_settings as autonomy

    captured = {}
    monkeypatch.setattr(
        "backend.autonomy_settings.save_autonomy_settings",
        lambda payload: captured.update(payload) or payload,
    )
    out = autonomy.save_circuit_breaker_limits(
        {"loop_detection_enabled": True, "max_steps_per_task": 9}
    )
    assert captured["circuit_breaker"]["loop_detection_enabled"] is True
    assert captured["circuit_breaker"]["max_steps_per_task"] == 9
    assert autonomy.guardian_limits_path() == autonomy.GUARDIAN_LIMITS_FILE


def test_agent_router_consumes_w3d_repeat_budget(tmp_path, monkeypatch):
    """`allow_repeat=True` verbraucht die SSOT, keinen RAM-Zähler im Router."""
    import backend.trajectory_budget as tb

    monkeypatch.setattr(tb, "_audit", lambda *a, **k: None)  # keine DB-Nebenwirkung
    db = str(tmp_path / "repeat_budget.db")
    tid = tb.ensure_trajectory(root_ticket_id="ticket-w3a-repeat", db_path=db)["trajectory_id"]
    agent = "agent-r"
    reason = "llm_call:agent-r"
    tb.set_repeat_budget(tid, agent, reason, 1, db_path=db)
    first = tb.reserve_hop(tid, agent, reason, allow_repeat=True, db_path=db)
    second = tb.reserve_hop(tid, agent, reason, allow_repeat=True, db_path=db)
    third = tb.reserve_hop(tid, agent, reason, allow_repeat=True, db_path=db)
    assert first["allowed"] and second["allowed"], (first, second)
    assert third["allowed"] is False
    assert third["reason"] == "CYCLE_DETECTED"
    assert third["detail"] == "REPEAT_BUDGET_EXCEEDED"
    status = tb.repeat_budget_status(tid, agent, reason, db_path=db)
    assert status["used"] == 1 and status["remaining"] == 0
    # Der Router darf keinen eigenen Zähler mehr besitzen (SSOT-Duplikation).
    assert not hasattr(agent_router, "counted_retry_allowed")


# ---------------------------------------------------------------------------
# D11/D07 — History-Marker, Präzedenz-Tenant, HANDOFF-Hard-Gate
# ---------------------------------------------------------------------------

def test_history_truncation_has_dropped_marker():
    history = [{"role": "user", "content": str(i)} for i in range(10)]
    trimmed = history_with_dropped_marker(history, 2, dropped=8)
    assert trimmed[0]["role"] == "system"
    assert "8 ältere Turns" in trimmed[0]["content"]
    assert "Vollversion" in trimmed[0]["content"]
    assert [m["content"] for m in trimmed[1:]] == ["8", "9"]


def test_precedent_tenant_accepts_both_column_names(monkeypatch):
    monkeypatch.setattr(
        "backend.tenant_context.tenant_context.get_active_tenant_id",
        lambda: "acme",
    )
    assert resolve_task_tenant_id({"tenant": "acme"}) == "acme"
    assert resolve_task_tenant_id({"tenant_id": "acme"}) == "acme"
    assert resolve_task_tenant_id({"tenant": "acme", "tenant_id": "other"}) == "acme"
    assert resolve_task_tenant_id({}) == "acme"  # nie hart "default"


def test_handoff_gate_requires_verified_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHON_HANDOFF_HMAC_KEY", "w3a-handoff-key")
    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    created = desk.create_handoff(
        task_id="t-w3a", from_agent="a", to_agent="worker",
        deliverables={"result": "fertig", "status": "done"},
        acceptance_criteria="Ergebnis vorhanden",
    )
    h_id = created["handoff_id"]
    assert require_accepted_handoff("t-w3a", "wrong-agent", desk=desk)["allowed"] is False
    gate = require_accepted_handoff("t-w3a", "worker", desk=desk)
    assert gate["allowed"] is True
    assert gate["handoff_id"] == h_id
    assert desk.get_handoff(h_id)["status"] == "accepted"

"""Regressionstests fuer den Multi-Agent-Orchestrierungs-Batch."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p1_root_orchestrator_can_delegate():
    from archon.core.delegation import _check_delegation_permission

    allowed, reason = _check_delegation_permission("default", "research_scout")
    assert allowed is True
    assert reason == "APEX"

    # Weitere Apex-IDs (unabhaengig vom UI-Org-Chart).
    assert _check_delegation_permission("executive_decision_architect", "research_scout")[0] is True
    # Tier-3-Spezialisten duerfen weiterhin nicht delegieren.
    assert _check_delegation_permission("research_scout", "default")[0] is False
    # Selbst-Delegation bleibt gesperrt.
    assert _check_delegation_permission("default", "default")[0] is False


def test_p1_delegation_subtasks_are_not_stuck_in_approval():
    src = (REPO_ROOT / "archon/core/delegation.py").read_text(encoding="utf-8")
    # D07: fail-closed Default 'manual' — kein HITL-Bypass bei Config-Fehler.
    assert '_del_cfg.get("autonomy", "manual")' in src
    assert '"approval_granted" if _del_autonomy == "autonomous"' in src
    assert "block_kind" in src


def test_p1_unknown_agent_is_not_silently_redirected():
    src = (REPO_ROOT / "archon/routers/chat.py").read_text(encoding="utf-8")
    assert "if not prof and profiles:" not in src
    assert 'raise ValueError(f"Unbekannte agent_id' in src


def test_p1_boardroom_consensus_check_excludes_negation():
    disp_src = (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    gate_src = (REPO_ROOT / "backend/consensus_gate.py").read_text(encoding="utf-8")
    assert "resolve_debate_consensus" in disp_src
    assert '"KEIN KONSENS"' in gate_src
    assert "_NEGATIVE_DEBATE_MARKERS" in gate_src


def test_p1_delegation_result_uses_agent_role_and_handoff():
    src = (REPO_ROOT / "archon/core/delegation.py").read_text(encoding="utf-8")
    assert '_save_message_to_db(origin_sess_id, "assistant", delegator_feedback)' in src
    assert "handoff_desk.create_handoff" in src


def test_p1_handoff_envelope_integrity(tmp_path):
    from backend.handoff_desk import HandoffDesk

    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    created = desk.create_handoff("task-1", "research_scout", "coder", {"result": "x"}, "Pruefen")
    assert created["status"] == "pending_acceptance"
    assert created["payload_hash"]

    assert desk.accept_handoff(created["handoff_id"], "wrong-agent")["status"] == "error"
    assert desk.accept_handoff(created["handoff_id"], "coder")["status"] == "accepted"


def test_p1_profile_tools_come_from_profile_yaml():
    import pytest
    import api_provider
    from backend.delegation_isolation import is_tool_allowed_for_agent

    profiles_dir = REPO_ROOT / ".hermes" / "profiles"
    if not profiles_dir.is_dir():
        pytest.skip(".hermes/profiles ist gitignored und im CI-Checkout nicht vorhanden")
    profiles = api_provider.list_real_hermes_profiles(
        profiles_dir=str(profiles_dir)
    )
    assert profiles
    legal = next((p for p in profiles if p["id"] == "legal_counsel"), None)
    coder = next((p for p in profiles if p["id"] == "senior_fullstack_engineer"), None)
    # Kein globaler 18-Tool-Satz mehr.
    tool_sets = {frozenset(p.get("tools") or []) for p in profiles}
    assert len(tool_sets) > 1, "alle Profile haben weiterhin identische Tools"
    if legal and coder:
        assert "computer_use" not in legal.get("tools", [])
    assert is_tool_allowed_for_agent(
        "senior_fullstack_engineer", "execute_code", profiles=profiles
    ) is True
    assert is_tool_allowed_for_agent(
        "legal_counsel", "computer_use", profiles=profiles
    ) is False

"""Re-Audit Etappe 8 — D14 HITL-Wirksamkeit und D11-restliche Kürzungsmarker."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_d14_hitl_resolution_has_real_effect(monkeypatch):
    import archon.routers.decisions as dec

    events = []
    monkeypatch.setattr(dec, "create_decision", lambda *a, **kw: {"id": "d-archived"})
    monkeypatch.setattr(
        "backend.audit_log.chained_audit_log.record_event",
        lambda **kw: events.append(kw),
    )
    out = asyncio.run(dec._decision_followup(
        "boardroom_no_consensus",
        {"ref_id": "deb-1", "extra": {"synthesis": "Synthese", "consensus_verdict": "NO_CONSENSUS"}},
        "approve",
    ))
    assert "d-archived" in out
    assert events and events[0]["action"] == "no_consensus_resolved_by_human"


def test_d14_kanban_override_fails_closed_without_creator():
    from backend.kanban_verifier import resolve_card_hitl_decision

    with pytest.raises(PermissionError):
        resolve_card_hitl_decision(
            "override", current_budget=100, actor="admin-1",
            created_by="", result_text="ok",
        )


def test_d14_no_constant_creator_in_task_create():
    src = (ROOT / "backend" / "operations_api.py").read_text(encoding="utf-8")
    block = src.split("def create_kanban_task(", 1)[1].split("\n@router", 1)[0]
    assert '"Archon-User"' not in block
    assert "_task_creator_actor(request)" in block


def test_d11_truncations_are_marked():
    delegation = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    dispatcher = (ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    consensus = (ROOT / "backend" / "consensus_gate.py").read_text(encoding="utf-8")
    router = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    assert 'mark_truncated(result, 2000' in delegation
    assert 'mark_truncated(ev[0], 500' in delegation
    assert '_mark_truncated(prompt, 500' in dispatcher
    assert 'mark_truncated(task_output, 4000' in consensus
    assert 'mark_truncated(task_output, 3500' in consensus
    assert 'KONTEXT GEKÜRZT' in router

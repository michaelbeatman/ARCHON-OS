# -*- coding: utf-8 -*-
"""Re-Audit Domäne 14 — Regressionstests für die MED-Funde (Stage 1)."""
from __future__ import annotations

import asyncio
import glob
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import archon.routers.boardroom as boardroom
import archon.routers.operations_approvals as approvals
from backend.approval_policy_engine import ApprovalPolicyEngine
from backend.role_budget_engine import get_default_role_budget


class _Req:
    headers = {"host": "localhost"}
    cookies = {}  # type: ignore[var-annotated]
    state = SimpleNamespace(user={"id": "usr_test", "username": "tester", "role": "admin"})

    class _URL:
        scheme = "http"

    url = _URL()


def _actor(actor: str):
    req = _Req()
    req._actor = actor  # type: ignore[attr-defined]
    return req


def _isolated_engine(tmp_path, monkeypatch):
    eng = ApprovalPolicyEngine(db_path=str(tmp_path / "approvals_med14.db"))
    monkeypatch.setattr("backend.approval_policy_engine.approval_engine", eng)
    monkeypatch.setattr(approvals, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(approvals, "require_session_actor", lambda r: r._actor)
    return eng


def _policy(eng, key: str) -> str:
    return str(next(
        p["policy_value"] for p in eng.get_policies(domain="finance")
        if p["policy_key"] == key
    ))


# --- MED: finance_auto_approval_max durch Einzel-Admin änderbar ----------------

def test_auto_approval_max_single_admin_change_blocked(tmp_path, monkeypatch):
    eng = _isolated_engine(tmp_path, monkeypatch)
    assert _policy(eng, "finance_auto_approval_max") == "50.00"

    with pytest.raises(HTTPException) as exc:
        approvals.api_update_approval_policy(
            _actor("alice"),
            approvals.ApprovalPolicyUpdateRequest(
                policy_key="finance_auto_approval_max", new_value="499.99"
            ),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "approvals_policy_auto_max_fixed"  # type: ignore[index]
    assert _policy(eng, "finance_auto_approval_max") == "50.00"

    # Reparaturpfad: Rücksetzen auf den fixierten Wert bleibt erlaubt.
    ok = approvals.api_update_approval_policy(
        _actor("alice"),
        approvals.ApprovalPolicyUpdateRequest(
            policy_key="finance_auto_approval_max", new_value="50.00"
        ),
    )
    assert ok["status"] == "success"
    assert _policy(eng, "finance_auto_approval_max") == "50.00"

    # Die 50-EUR-Invariante greift wieder: 499 EUR ist nicht mehr auto-freigegeben.
    request = eng.evaluate_and_enqueue(domain="finance", title="Rechnung", amount=499)
    assert request["status"] == "pending"
    assert eng.evaluate_and_enqueue(domain="finance", title="Kleinstbetrag", amount=49)["status"] == "auto_approved"


# --- MED: approve_policy_change_proposal() ohne Endpoint ----------------------

def test_policy_change_proposal_endpoint_four_eyes(tmp_path, monkeypatch):
    eng = _isolated_engine(tmp_path, monkeypatch)
    assert _policy(eng, "finance_four_eyes_min") == "500.00"

    proposed = approvals.api_update_approval_policy(
        _actor("alice"),
        approvals.ApprovalPolicyUpdateRequest(
            policy_key="finance_four_eyes_min", new_value="750"
        ),
    )
    assert proposed["result"]["status"] == "pending_four_eyes"
    proposal_id = proposed["result"]["proposal_id"]
    # Bis zur zweiten Freigabe bleibt die Policy unverändert.
    assert _policy(eng, "finance_four_eyes_min") == "500.00"

    listed = approvals.api_get_policy_change_proposals(_actor("bob"), status="pending")
    assert any(p["proposal_id"] == proposal_id for p in listed["proposals"])

    # Gleiche Session → 403, kein Wertwechsel.
    with pytest.raises(HTTPException) as exc:
        approvals.api_approve_policy_change_proposal(_actor("alice"), proposal_id)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "approvals_proposal_four_eyes_violation"  # type: ignore[index]
    assert _policy(eng, "finance_four_eyes_min") == "500.00"

    # Zweite, unabhängige Session → Schwelle wird wirksam.
    approved = approvals.api_approve_policy_change_proposal(_actor("bob"), proposal_id)
    assert approved["result"]["status"] == "approved"
    assert _policy(eng, "finance_four_eyes_min") == "750"


def test_policy_change_proposal_endpoint_requires_admin(monkeypatch):
    def deny(request):
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(approvals, "require_admin_or_503", deny)
    with pytest.raises(HTTPException) as exc:
        approvals.api_approve_policy_change_proposal(_Req(), "policy-change-x")  # type: ignore[arg-type]
    assert exc.value.status_code == 403


# --- MED: NO_CONSENSUS erzeugt trotzdem "Finale Synthese" im Artefakt ----------

def _stub_dispatch(monkeypatch, result):
    async def fake(**kwargs):
        return dict(result)
    monkeypatch.setattr(boardroom.core_dispatcher, "run_boardroom_debate", fake)


def _run_boardroom(monkeypatch, tmp_path, result):
    monkeypatch.setitem(boardroom._DEPS, "load_roles", lambda: [{
        "id": "executive_decision_architect", "name": "Chair", "role": "Executive",
        "prompt": "p", "model": "m", "provider": "openrouter",
    }])
    monkeypatch.setitem(boardroom._DEPS, "api_get_hermes_profiles", lambda: [])
    monkeypatch.setattr(boardroom, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(boardroom, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(boardroom, "OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    captured = {}

    def fake_save(entry, actor_id="system"):
        captured["entry"] = dict(entry)

    monkeypatch.setattr(boardroom, "save_boardroom_history_item", fake_save)
    monkeypatch.setattr(boardroom, "_escalate_boardroom_no_consensus", lambda **kw: {"id": "esc-1"})
    monkeypatch.setattr("backend.workflow_scheduler.dispatch_workflow_event", lambda **kw: None)
    _stub_dispatch(monkeypatch, result)
    res = asyncio.run(boardroom.api_run_boardroom(
        boardroom.BoardroomRequest(task="Konfliktfall"), _Req()  # type: ignore[arg-type]
    ))
    notes = glob.glob(os.path.join(str(tmp_path / "vault"), "*.md"))
    assert notes, "Vault-Notiz wurde nicht geschrieben"
    return res, captured["entry"], open(notes[0], encoding="utf-8").read()


def test_no_consensus_vault_has_no_final_decision(monkeypatch, tmp_path):
    res, entry, note = _run_boardroom(monkeypatch, tmp_path, {
        "status": "success",
        "consensus_status": "NO_CONSENSUS",
        "transcript": "Diskussion …",
        "synthesis": (
            "Zwei Positionen widersprechen sich.\n"
            "### 3. Final Actionable Decision\n"
            "Wir entscheiden jetzt X.\n"
            "## Offene Punkte\nWeiter klären."
        ),
    })
    assert "Final Actionable Decision" not in res["synthesis"]
    assert "## Konfliktanalyse / keine Entscheidung" in note
    assert "## Finale Synthese" not in note
    assert "Wir entscheiden jetzt X" not in note
    assert "## Offene Punkte" in note  # nachfolgender Abschnitt bleibt erhalten
    assert entry["decision_status"] == "no_consensus"


def test_consensus_vault_keeps_final_synthesis(monkeypatch, tmp_path):
    synthesis = "Konsens erzielt.\n### 3. Final Actionable Decision\nWir entscheiden X."
    res, entry, note = _run_boardroom(monkeypatch, tmp_path, {
        "status": "success",
        "consensus_status": "CONSENSUS_REACHED",
        "transcript": "Diskussion …",
        "synthesis": synthesis,
    })
    assert res["synthesis"] == synthesis
    assert "## Finale Synthese" in note
    assert "## Konfliktanalyse" not in note
    assert entry["decision_status"] == "approved"


# --- MED: Tier-Gewicht über nicht registrierte Slot-ID manipulierbar ----------

def test_boardroom_slot_profile_must_be_registered(monkeypatch):
    roles = [
        {"id": "executive_decision_architect", "name": "Chair", "role": "Executive",
         "prompt": "p", "model": "m", "provider": "openrouter"},
        {"id": "senior_coder", "name": "Coder", "role": "Specialist",
         "prompt": "p", "model": "m", "provider": "openrouter"},
    ]
    monkeypatch.setitem(boardroom._DEPS, "load_roles", lambda: list(roles))
    monkeypatch.setitem(boardroom._DEPS, "api_get_hermes_profiles", lambda: [])

    # "default" ist Executive in der SSOT, aber hier NICHT registriert → 400.
    with pytest.raises(HTTPException) as exc:
        boardroom._prepare_boardroom_agents(boardroom.BoardroomRequest(
            task="t", slots=[boardroom.BoardroomSlotItem(role_name="X", profile_id="default")]
        ))
    assert exc.value.status_code == 400

    # Registriertes Profil: Tier kommt aus der SSOT, nicht aus dem Body.
    _, agents = boardroom._prepare_boardroom_agents(boardroom.BoardroomRequest(
        task="t",
        slots=[boardroom.BoardroomSlotItem(role_name="X", profile_id="senior_coder",
                                           model_id="evil-model")],
    ))
    slot = agents[1]
    assert slot["id"] == "senior_coder"
    assert slot["tier"] == get_default_role_budget("senior_coder")["tier"] == "specialist"
    # W4-C/D15-H6: CEO ist nicht mehr automatisch APEX/executive — die
    # hoheitliche Instanz ist `default`. Der Tier kommt aus der SSOT.
    assert agents[0]["tier"] == get_default_role_budget("executive_decision_architect")["tier"]

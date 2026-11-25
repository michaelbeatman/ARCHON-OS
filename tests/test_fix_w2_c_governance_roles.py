"""Remediation W2-C — Entscheidungs-Hoheit (F022) + Rollen-/Prompt-Trennschärfe (F023).

Regressionstests gegen:
- H-14-2: fälschbares Vier-Augen-Quality-Gate (`force_verdict`, Body-Actor)
- H-14-3: Einzel-Admin-Reklassifizierung der EU-AI-Act-Risikoklasse
- H-15-1: Isolation-Header ohne Negativ-Grenze / User-Nachricht statt System
- H-15-2/3: inexistente Transparenz-IDs, `founder` falsch klassifiziert
- H-15-4/5/6: Lisa-Theater, fehlende Reviewer-Rolle, erfundene Freigabe
- MED: zwei Autoritäts-SSOTs, APEX, Alias-Register, soul_mode
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.operations_api as ops  # noqa: E402
from backend.operations_api import QualityReviewRequest, TaskStatusUpdateRequest  # noqa: E402


def _read(rel: str) -> str:
    return (Path(BASE_DIR) / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# H-14-2 — Vier-Augen-Quality-Gate
# ---------------------------------------------------------------------------

def test_force_verdict_and_body_reviewer_removed():
    assert "force_verdict" not in QualityReviewRequest.model_fields
    assert "reviewer_id" not in QualityReviewRequest.model_fields
    # Extra-Felder werden ignoriert: ein alter Client kann das Gate nicht mehr
    # über den Body steuern.
    req = QualityReviewRequest.model_validate({"force_verdict": "approved", "reviewer_id": "operator"})
    assert not hasattr(req, "force_verdict")


def test_status_force_done_without_hitl_proof_is_blocked(monkeypatch):
    monkeypatch.setattr(ops, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(ops, "require_session_actor", lambda r: "bob")
    monkeypatch.setattr(ops, "_current_quality_review", lambda t: {
        "status": "changes_requested", "reviewer_id": "katharina", "reviewer": "Katharina Völk",
    })
    monkeypatch.setattr(ops, "_task_created_by", lambda t: "alice")
    monkeypatch.setattr(ops, "_task_status", lambda t: "review")
    monkeypatch.setattr("backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: False)

    calls = []
    monkeypatch.setattr(ops, "_update_task_status_db", lambda *a, **k: calls.append((a, k)) or {
        "old_status": "review", "title": "T", "assignee": "alice", "now_iso": "now",
    })

    async def _run():
        return await ops.update_task_status(
            None, "t-1", TaskStatusUpdateRequest(status="done", force=True, reason="Einvernehmen")
        )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_run())
    assert exc.value.status_code == 403
    assert calls == []  # kein Statuswechsel ohne Proof


def test_status_force_done_with_proof_writes_actor_and_evidence(monkeypatch):
    monkeypatch.setattr(ops, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(ops, "require_session_actor", lambda r: "bob")
    monkeypatch.setattr(ops, "_current_quality_review", lambda t: {
        "status": "changes_requested", "reviewer_id": "katharina", "reviewer": "Katharina Völk",
    })
    monkeypatch.setattr(ops, "_task_created_by", lambda t: "alice")
    monkeypatch.setattr(ops, "_task_status", lambda t: "review")
    monkeypatch.setattr("backend.passkey_hitl.consume_hitl_proof_token", lambda *a, **k: True)

    audited = []
    monkeypatch.setattr(
        "backend.audit_log._require_audit_event",
        lambda category, action, agent_id, payload, **kw: audited.append((category, action, agent_id, payload)),
    )
    captured = {}

    def _fake_db(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"old_status": "review", "title": "T", "assignee": "alice", "now_iso": "now"}

    monkeypatch.setattr(ops, "_update_task_status_db", _fake_db)
    monkeypatch.setattr(ops, "_sync_to_memory_bridge", lambda *a, **k: None)
    monkeypatch.setattr(ops, "get_provider", lambda name: None)

    result = asyncio.run(ops.update_task_status(
        None, "t-1", TaskStatusUpdateRequest(
            status="done", force=True, reason="Zweite Person hat geprüft",
            passkey_proof_token="proof-1", approval_id="apr-1",
        )
    ))
    assert result["status"] == "success"
    # args: task_id, status, result, force, actor, reason, evidence
    assert captured["args"][0:6] == ("t-1", "done", None, True, "bob", "Zweite Person hat geprüft")
    evidence = captured["args"][6]
    assert evidence["actor"] == "bob" and evidence["hitl_proof_verified"] is True
    assert evidence["approval_id"] == "apr-1"
    assert any(a == "status_forced" and agent == "bob" for _, a, agent, _ in audited)


def test_status_changed_event_contains_actor_force_reason(monkeypatch):
    events = []

    class _Conn:
        def cursor(self):
            return self

        def execute(self, sql, params=()):
            if "INSERT INTO task_events" in sql:
                events.append(json.loads(params[2]))
            return self

        def fetchone(self):
            return {"id": "t-1", "title": "T", "assignee": "a", "status": "review"}

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(ops, "_get_kanban_connection", lambda **k: _Conn())
    monkeypatch.setattr(ops, "_load_kanban_meta", lambda: {"tasks": {"t-1": {"quality_review": {
        "status": "changes_requested", "reviewer_id": "katharina",
    }}}})
    info = ops._update_task_status_db(
        "t-1", "done", None, True, "bob", "geprüft", {"hitl_proof_verified": True}
    )
    assert info["old_status"] == "review"
    payload = next(e for e in events if e["from"] == "review")
    assert payload["actor"] == "bob"
    assert payload["force"] is True
    assert payload["reason"] == "geprüft"
    assert payload["four_eyes_evidence"]["hitl_proof_verified"] is True


# ---------------------------------------------------------------------------
# H-14-3 — KI-Reklassifikation
# ---------------------------------------------------------------------------

def test_reclassify_requires_reason():
    with pytest.raises(Exception):
        AiActReclassifyRequest = __import__(
            "archon.routers.governance", fromlist=["AiActReclassifyRequest"]
        ).AiActReclassifyRequest
        AiActReclassifyRequest(risk_tier="MINIMAL_RISK", override_reason="kurz")


def test_reclassify_downgrade_uses_four_eyes_proposal(monkeypatch):
    import archon.routers.governance as gov

    monkeypatch.setattr(gov, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(gov, "require_session_actor", lambda r: "alice")
    monkeypatch.setattr(
        "backend.eu_ai_act_inventory.eu_ai_act_inventory_manager.get_inventory",
        lambda refresh=False: [{"agent_id": "x", "risk_tier": "HIGH_RISK"}],
    )
    captured = {}

    def _enqueue(**kwargs):
        captured.update(kwargs)
        return {"request_id": "REQ-1", "status": "pending"}

    monkeypatch.setattr("backend.approval_policy_engine.approval_engine.evaluate_and_enqueue", _enqueue)
    monkeypatch.setattr(gov, "_audit_or_503", lambda *a, **k: None)

    res = gov.api_ai_act_reclassify(
        None, "x", gov.AiActReclassifyRequest(
            risk_tier="MINIMAL_RISK", override_reason="Begründung laenger als zehn Zeichen"
        )
    )
    assert res.status_code == 202
    assert res.body  # JSONResponse
    assert captured["force_four_eyes"] is True
    assert captured["requester_id"] == "alice"
    assert captured["domain"] == "ai_act"


def test_reclassify_prohibited_downgrade_forbidden(monkeypatch):
    import archon.routers.governance as gov

    monkeypatch.setattr(gov, "require_admin_or_503", lambda r: None)
    monkeypatch.setattr(gov, "require_session_actor", lambda r: "alice")
    monkeypatch.setattr(
        "backend.eu_ai_act_inventory.eu_ai_act_inventory_manager.get_inventory",
        lambda refresh=False: [{"agent_id": "x", "risk_tier": "PROHIBITED"}],
    )
    monkeypatch.setattr(gov, "_audit_or_503", lambda *a, **k: None)
    with pytest.raises(HTTPException) as exc:
        gov.api_ai_act_reclassify(
            None, "x", gov.AiActReclassifyRequest(
                risk_tier="MINIMAL_RISK", override_reason="Begründung laenger als zehn Zeichen"
            )
        )
    assert exc.value.status_code == 403


def test_manual_override_audit_error_not_swallowed(monkeypatch):
    from backend.eu_ai_act_inventory import EUAIActInventoryManager

    mgr = EUAIActInventoryManager()
    item = {"agent_id": "x", "risk_tier": "MINIMAL_RISK"}
    monkeypatch.setattr(mgr, "get_inventory", lambda refresh=False: [dict(item)])
    monkeypatch.setattr("os.replace", lambda a, b: None)
    monkeypatch.setattr(
        "backend.audit_log._require_audit_event",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit_write_failed")),
    )
    with pytest.raises(RuntimeError, match="audit_write_failed"):
        mgr.set_manual_override(
            "x", {"risk_tier": "HIGH_RISK", "override_reason": "Neue Bewertung nach Prüfung"},
            actor="alice",
        )


# ---------------------------------------------------------------------------
# H-15-1 — Isolations-Header mit Negativ-Grenze als System-Prompt
# ---------------------------------------------------------------------------

def test_isolation_header_has_negative_scope_and_risk_tier():
    from archon.core.delegation import (
        build_isolation_header_with_negative_scope,
        resolve_isolated_scope_with_role_limits,
    )

    profiles = json.loads((Path(BASE_DIR) / "agent_profiles.json").read_text(encoding="utf-8"))
    scope = resolve_isolated_scope_with_role_limits("clinical_medical_advisor", "", profiles)
    header = build_isolation_header_with_negative_scope(scope)
    assert "NEGATIVE_SCOPE (Strikt verboten)" in header
    assert "RISK_TIER: HIGH_RISK" in header
    assert "keine medizinischen Diagnosen" in header


def test_isolation_header_anchored_as_system_prompt():
    src = _read("archon/core/delegation.py")
    assert '_save_message_to_db(tgt_sess, "system", isolation_header)' in src
    # Die alte Variante (Header in der User-Nachricht) darf nicht mehr stehen.
    assert 'f"{isolation_header}\\n"\n        f"STRUKTURIERTE ÜBERGABE' not in src


def test_soul_mode_is_consumed_in_dispatch():
    from archon.core.delegation import active_soul_tier_text

    assert active_soul_tier_text("executive_decision_architect", "compact")
    assert active_soul_tier_text("executive_decision_architect", "pro")


# ---------------------------------------------------------------------------
# H-15-2/3 — EU-AI-Act-Konsistenz gegen die echten 71 Profile
# ---------------------------------------------------------------------------

def test_inventory_consistency_with_71_profiles():
    from backend.eu_ai_act_inventory import (
        HIGH_RISK_AGENT_IDS,
        TRANSPARENCY_AGENT_IDS,
        eu_ai_act_inventory_manager,
    )

    profiles = json.loads((Path(BASE_DIR) / "agent_profiles.json").read_text(encoding="utf-8"))
    profile_ids = {p["id"] for p in profiles}
    assert len(profile_ids) == 71
    assert HIGH_RISK_AGENT_IDS <= profile_ids
    assert TRANSPARENCY_AGENT_IDS <= profile_ids  # keine erfundenen IDs mehr
    for fake in ("performance_ads_media_buyer", "content_marketing_strategist",
                 "community_retention_manager", "podcast_video_scriptwriter"):
        assert fake not in TRANSPARENCY_AGENT_IDS

    inv = eu_ai_act_inventory_manager.get_inventory()
    assert len(inv) == 71
    by_id = {x["agent_id"]: x for x in inv}
    for aid in ("founder", "crisis_escalation_lead"):
        assert by_id[aid]["risk_tier"] == "HIGH_RISK"
        assert "MANDATORY_4_EYES_HITL" in by_id[aid]["required_guardrails"]
    for aid in ("paid_ads_manager", "content_repurposing_specialist",
                "speechwriter_keynote_designer", "customer_retention_specialist"):
        assert by_id[aid]["risk_tier"] == "SPECIFIC_TRANSPARENCY"
        assert "OUTBOUND_APPROVAL_QUEUE" in by_id[aid]["required_guardrails"]
        assert "AI_DISCLOSURE_TAG" in by_id[aid]["required_guardrails"]


def test_legacy_tool_names_canonical_in_profiles():
    for name in ("agent_profiles.json", "roles.json"):
        profiles = json.loads((Path(BASE_DIR) / name).read_text(encoding="utf-8"))
        for p in profiles:
            tools = set(p.get("tools") or [])
            assert not ({"FileSystem_MCP", "Calculator", "WebSearch"} & tools), (name, p["id"])
    from backend.role_budget_engine import canonical_tool_name

    assert canonical_tool_name("FileSystem_MCP") == "filesystem"
    assert canonical_tool_name("Calculator") == "execute_code"
    assert canonical_tool_name("WebSearch") == "web_search"


# ---------------------------------------------------------------------------
# H-15-4/5/6 — Rollen-Theater / erfundene Freigabe
# ---------------------------------------------------------------------------

def test_fan_in_labels_and_real_reviewer():
    src = _read("archon/core/orchestration.py")
    assert 'agent_id="gpts_critical_reviewer"' not in src
    assert "_REVIEWER_ID = \"red_team_challenger\"" in src
    assert "LISAS SYNTHESE" not in src
    assert 'quelle="Lisa (aggregation_lisa)"' not in src
    assert "reviewer_failed_closed" in src  # fail-closed bei fehlendem Profil


def test_no_fabricated_approval_text():
    src = _read("archon/core/delegation.py")
    assert "Freigegeben durch <strong>@executive_decision_architect</strong>" not in src
    assert "_project_approval_evidence" in src
    assert "ENTWURF — nicht freigegeben" in src


# ---------------------------------------------------------------------------
# MED — Autoritäts-SSOT / APEX / Aliase
# ---------------------------------------------------------------------------

def test_single_authority_source_of_truth():
    from backend.role_budget_engine import LEAD_ROLE_IDS, EXECUTIVE_ROLE_IDS, authority_tier

    assert authority_tier("default") == "executive"
    assert authority_tier("robert") == "executive"
    assert authority_tier("scientific_literature_synthesizer") == "lead"
    assert authority_tier("labor_law_hr_governance") == "specialist"
    assert "labor_law_hr_governance" not in EXECUTIVE_ROLE_IDS
    assert "finance_lead" not in LEAD_ROLE_IDS
    assert "scientific_literature_synthesizer" in LEAD_ROLE_IDS


def test_apex_set_equals_tier1_from_org_hierarchy():
    from archon.core.delegation import _apex_ids

    org = json.loads((Path(BASE_DIR) / "config" / "org_hierarchy.json").read_text(encoding="utf-8"))
    expected = {n["id"] for n in org["nodes"] if n.get("tier") == 1}
    assert set(_apex_ids()) == expected
    assert "default" in expected


def test_alias_registries_agree():
    from archon.core.delegation import canonical_agent_id

    ids = {p["id"] for p in json.loads((Path(BASE_DIR) / "agent_profiles.json").read_text(encoding="utf-8"))}
    for handle, target in (
        ("robert", "executive_decision_architect"),
        ("lisa", "aggregation_lisa"),
        ("sarah", "agile_scrum_master"),
        ("patrick", "b2b_outreach_specialist"),
    ):
        assert canonical_agent_id(handle, ids) == target

"""W4-A (Partition A) — Regressionstests fuer D15-H2, D15-H4, D15-M1, D15-M5, D15-H6.

Alle Tests pruefen den KONSUMENTEN im Produktivpfad: den HR-SOUL-Save-Endpoint,
die Aktivierungs-Entscheidung der Compliance-Engine, den Inventar-/PDF-Konsumenten
und die Klassifizierung selbst — nicht nur die Existenz von Artefakten.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import archon.core.profiles as profiles_mod
import backend.compliance_engine as ce_mod
import backend.compliance_pdf as pdf_mod
import backend.eu_ai_act_inventory as eu_mod
import scripts.sync_soul_modes as ssm
from archon.routers import hr as hr_router
from backend.compliance_engine import ComplianceEngine
from backend.eu_ai_act_inventory import (
    CREDIT_RISK_AGENT_IDS,
    EXPECTED_HIGH_RISK_COUNT,
    HIGH_RISK_AGENT_IDS,
    EUAIActInventoryManager,
    compute_live_soul_sha256,
    validate_classification_ids,
)


def _write_profiles(tmp_path, profiles):
    path = tmp_path / "agent_profiles.json"
    path.write_text(json.dumps(profiles, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _patch_profile_source(monkeypatch, profiles_path):
    """Pin-Berechnung und Live-Verifikation muessen dieselbe SSOT lesen."""
    monkeypatch.setattr(eu_mod, "PROFILES_FILE", profiles_path)
    monkeypatch.setattr(ce_mod, "PROFILES_FILE", profiles_path)


class _StubInventory:
    def __init__(self, item):
        self.item = item

    def get_inventory(self):
        return [self.item]


class _CapturingAuditLog:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)
        return {"status": "recorded"}


def _prepare_soul_edit_env(monkeypatch, tmp_path):
    """Echter HR-Save-Pfad mit tmp-SSOT: app_main, Profile-Cache und Inventar."""
    agent_id = "w4a_soul_agent"
    profiles_path = _write_profiles(tmp_path, [{
        "id": agent_id,
        "name": "W4A Soul Agent",
        "category": "General",
        "prompt": "OLD W4A PROMPT",
        "system_prompt": "OLD W4A PROMPT",
    }])
    _patch_profile_source(monkeypatch, profiles_path)
    inv_file = tmp_path / "eu_ai_act_inventory.json"
    monkeypatch.setattr(eu_mod.eu_ai_act_inventory_manager, "profiles_file", profiles_path)
    monkeypatch.setattr(eu_mod.eu_ai_act_inventory_manager, "inventory_file", str(inv_file))

    class _AppMain:
        def profile_dir(self, _agent_id):
            return str(tmp_path / "hermes" / _agent_id)

    monkeypatch.setattr("archon.core.provider_registry.get_provider", lambda _name: _AppMain())
    from pathlib import Path

    def _get_profiles():
        return json.loads(Path(profiles_path).read_text(encoding="utf-8"))

    def _save_profiles(items):
        Path(profiles_path).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(profiles_mod, "api_get_hermes_profiles", _get_profiles)
    monkeypatch.setattr(profiles_mod, "save_all_agent_profiles", _save_profiles)
    monkeypatch.setattr(profiles_mod, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(profiles_mod, "get_hermes_profiles_base_dirs", lambda: [])
    monkeypatch.setattr(hr_router, "_require_admin", lambda _req: None)
    return agent_id, profiles_path, inv_file


def test_w4a_h2_soul_edit_refreshes_pin_and_activation_stays_allowed(monkeypatch, tmp_path):
    """D15-H2: SOUL-Edit ueber den echten Endpoint liefert neuen Pin; Aktivierung bleibt erlaubt."""
    agent_id, profiles_path, inv_file = _prepare_soul_edit_env(monkeypatch, tmp_path)

    res = hr_router.api_save_hermes_soul(
        cast(Any, SimpleNamespace()), agent_id, hr_router.SaveSoulReq(markdown="NEW W4A PROMPT")
    )
    expected_pin = hashlib.sha256(b"NEW W4A PROMPT").hexdigest()
    assert res["status"] == "success"
    assert res["pin_refreshed"] is True
    assert res["soul_sha256"] == expected_pin

    saved = json.loads(inv_file.read_text(encoding="utf-8"))
    item = next(entry for entry in saved if entry["agent_id"] == agent_id)
    assert item["soul_sha256"] == expected_pin
    assert item["soul_hash_source"] == eu_mod.SOUL_HASH_SOURCE

    # Konsument der Compliance-Engine im Produktivpfad (kein gemockter Pin).
    engine = ComplianceEngine(
        inventory_mgr=EUAIActInventoryManager(
            profiles_file=profiles_path, inventory_file=str(inv_file)
        ),
        literacy_file=str(tmp_path / "lit.json"),
    )
    check = engine.check_activation_allowed(agent_id)
    assert check["allowed"] is True
    assert check["soul_sha256"] == expected_pin


def test_w4a_h2_pin_refresh_failure_is_hard_rejected_and_rolled_back(monkeypatch, tmp_path):
    """D15-H2: schlagender Pin-Refresh darf keinen Erfolg melden (fail-closed)."""
    agent_id, profiles_path, _inv_file = _prepare_soul_edit_env(monkeypatch, tmp_path)

    def _fail_refresh(target_agent_id=None):
        raise OSError("simulated pin refresh failure")

    monkeypatch.setattr(ssm, "refresh_soul_pin_for_agents", _fail_refresh)
    with pytest.raises(HTTPException) as exc_info:
        hr_router.api_save_hermes_soul(
            cast(Any, SimpleNamespace()), agent_id, hr_router.SaveSoulReq(markdown="BROKEN W4A PROMPT")
        )
    assert exc_info.value.status_code == 500
    assert cast(dict, exc_info.value.detail)["code"] == "SOUL_PIN_REFRESH_FAILED"
    # Rollback: die Prompt-SSOT darf nicht auf dem manipulierten Text stehen bleiben.
    persisted = json.loads(open(profiles_path, encoding="utf-8").read())
    assert persisted[0]["prompt"] == "OLD W4A PROMPT"


def test_w4a_h4_null_certificate_hash_blocks_high_risk_activation(monkeypatch, tmp_path):
    """D15-H4: null-Hash/Bootstrap-Actor blockieren HIGH_RISK; add_literacy_entry heilt."""
    lit_file = tmp_path / "lit.json"
    lit_file.write_text(json.dumps([{
        "id": "lit-w4a-bootstrap",
        "person_name": "Test-Operator",
        "role": "Admin & HITL-Freigabeverantwortlicher",
        "training_module": "Art. 4 EU AI Act",
        "scope_tiers": ["HIGH_RISK"],
        "completed_at": "2026-11-24",
        "valid_until": "2027-11-24",
        "status": "ACTIVE",
        "certificate_sha256": None,
        "recorded_by": "fix_a8_roles_bootstrap",
    }], ensure_ascii=False), encoding="utf-8")

    high_risk_item = {
        "agent_id": "hr_recruiter",
        "risk_tier": "HIGH_RISK",
        "compliance_status": "COMPLIANT_WITH_OVERSIGHT",
        "human_oversight_measure": "MANDATORY_HITL (4-Augen-Freigabe)",
        "soul_sha256": "a" * 64,
        "guardrails_verified": True,
    }
    monkeypatch.setattr(
        ComplianceEngine, "_canonical_soul_sha256", staticmethod(lambda _aid: "a" * 64)
    )
    audit = _CapturingAuditLog()
    engine = ComplianceEngine(
        literacy_file=str(lit_file),
        inventory_mgr=_StubInventory(high_risk_item),
        audit_logger=audit,
    )

    blocked = engine.check_activation_allowed("hr_recruiter")
    assert blocked["allowed"] is False
    assert "Kompetenznachweis" in blocked["reason"]

    # Regulaerer, auditierter Pfad erzeugt einen gueltigen signierten Nachweis.
    engine.add_literacy_entry({
        "person_name": "Test-Operator",
        "role": "Admin & HITL-Freigabeverantwortlicher",
        "training_module": "Art. 4 EU AI Act",
        "scope_tiers": ["HIGH_RISK"],
    }, actor="michael")
    allowed = engine.check_activation_allowed("hr_recruiter")
    assert allowed["allowed"] is True
    assert any(e.get("action") == "ai_act_literacy_recorded" for e in audit.events)


def test_w4a_m1_transparency_hash_drift_blocks_and_emits_audit(monkeypatch, tmp_path):
    """D15-M1: Drift bei SPECIFIC_TRANSPARENCY wird blockiert und auditiert."""
    lit_file = tmp_path / "lit.json"
    lit_file.write_text("[]", encoding="utf-8")
    item = {
        "agent_id": "paid_ads_manager",
        "risk_tier": "SPECIFIC_TRANSPARENCY",
        "compliance_status": "COMPLIANT",
        "human_oversight_measure": "HUMAN_IN_THE_LOOP",
        "soul_sha256": "b" * 64,
        "guardrails_verified": True,
    }
    monkeypatch.setattr(
        ComplianceEngine, "_canonical_soul_sha256", staticmethod(lambda _aid: "c" * 64)
    )
    audit = _CapturingAuditLog()
    engine = ComplianceEngine(
        literacy_file=str(lit_file), inventory_mgr=_StubInventory(item), audit_logger=audit
    )
    res = engine.check_activation_allowed("paid_ads_manager", system_prompt="ignored copy")
    assert res["allowed"] is False
    assert res["error_code"] == "SOUL_SHA256_MISMATCH"
    assert res["guardrails_verified"] is False
    assert res["reclassification_required"] is True
    assert any(e.get("action") == "soul_sha256_drift_detected" for e in audit.events)


def test_w4a_m1_guardrails_verified_comes_from_real_comparison(monkeypatch, tmp_path):
    """D15-M1: guardrails_verified ist Ergebnisse des Pin-Vergleichs, nicht bool(pin)."""
    agent_id = "w4a_guard_agent"
    profiles_path = _write_profiles(tmp_path, [{
        "id": agent_id, "name": "W4A Guard Agent", "prompt": "CURRENT W4A PROMPT"
    }])
    monkeypatch.setattr(eu_mod, "PROFILES_FILE", profiles_path)
    mgr = EUAIActInventoryManager(
        profiles_file=profiles_path, inventory_file=str(tmp_path / "inv.json")
    )

    stale = mgr.classify_agent({"id": agent_id, "name": "W4A Guard Agent", "prompt": "STALE W4A PROMPT"})
    assert stale["soul_sha256"] != compute_live_soul_sha256(agent_id, profiles_path)
    assert stale["guardrails_verified"] is False

    current = mgr.classify_agent({"id": agent_id, "name": "W4A Guard Agent", "prompt": "CURRENT W4A PROMPT"})
    assert current["guardrails_verified"] is True


def test_w4a_m5_counts_derived_from_positive_list_and_pdf_consumes_them(tmp_path):
    """D15-M5: 28 aus Positivliste, keine Phantomer; PDF-Konsument uebernimmt die Zahl."""
    profiles = EUAIActInventoryManager().load_profiles()
    report = validate_classification_ids(profiles)
    assert report["ok"] is True
    assert report["profile_count"] > 0
    assert report["high_risk_count"] == EXPECTED_HIGH_RISK_COUNT == len(HIGH_RISK_AGENT_IDS) == 28
    # Drei fruehere Phantomer sind als historische Aliase markiert, greifen
    # aber in der echten 71-Profil-SSOT nicht mehr als Klassifikationsziel.
    assert CREDIT_RISK_AGENT_IDS == eu_mod.HISTORICAL_CREDIT_RISK_ALIASES
    assert report["active_credit_risk_ids"] == []
    assert len(report["historical_credit_aliases_outside_ssot"]) == 3

    mgr = EUAIActInventoryManager(inventory_file=str(tmp_path / "inv.json"))
    stats = mgr.get_stats()
    assert stats["high_risk_count"] == EXPECTED_HIGH_RISK_COUNT

    line = pdf_mod._ai_act_summary_line(stats)
    assert f"Anhang-III-Hochrisiko (Art. 6): {EXPECTED_HIGH_RISK_COUNT}" in line
    pdf_bytes, digest = pdf_mod.build_verfahrensdokumentation_pdf({
        "ai_act_stats": stats,
        "ai_act_inventory": mgr.get_inventory()[:2],
        "literacy_register": [],
        "audit_chain": {"valid": True},
        "privacy_routing": {},
        "guardrails": {},
    })
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert len(digest) == 64


def test_w4a_h6_approval_authority_only_ceo(tmp_path):
    """D15-H6: CEO allein hat Freigaberecht; founder ist beratend (beide HIGH_RISK)."""
    mgr = EUAIActInventoryManager(inventory_file=str(tmp_path / "inv.json"))
    profiles = mgr.load_profiles()
    founder = next(p for p in profiles if p.get("id") == "founder")
    ceo = next(p for p in profiles if p.get("id") == "executive_decision_architect")

    founder_item = mgr.classify_agent(founder)
    ceo_item = mgr.classify_agent(ceo)
    assert founder_item["risk_tier"] == "HIGH_RISK"
    assert ceo_item["risk_tier"] == "HIGH_RISK"
    assert founder_item["approval_authority"] is False
    assert ceo_item["approval_authority"] is True

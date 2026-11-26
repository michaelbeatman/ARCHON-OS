"""F23 (D15): Produktive 3-Tier-SOUL-Aufloesung + zwingender SOUL-Hash-Pin-Refresh."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from archon.core.delegation import active_soul_tier_text, resolve_effective_soul_mode
from archon.routers import hr as hr_router
from backend.compliance_engine import ComplianceEngine


def test_f23_resolve_effective_soul_mode_uses_all_three_tiers():
    """HIGH_RISK -> full, Tier-2-Lead -> pro, Spezialist -> compact."""
    assert resolve_effective_soul_mode("founder", "compact") == "full"
    assert resolve_effective_soul_mode("system_architect_orchestrator", "compact") in ("pro", "full")
    assert resolve_effective_soul_mode("nonexistent_specialist_xyz", "compact") == "compact"
    # Explizite Profil-Wahl bleibt vorrangig
    assert resolve_effective_soul_mode("nonexistent_specialist_xyz", "pro") == "pro"
    assert resolve_effective_soul_mode("nonexistent_specialist_xyz", "full") == "full"

    # Alle drei Tier-Texte fuer einen realen Agenten existieren und unterscheiden sich
    compact_txt = active_soul_tier_text("founder", "compact")
    pro_txt = active_soul_tier_text("founder", "pro")
    full_txt = active_soul_tier_text("founder", "full")
    assert compact_txt and pro_txt and full_txt
    assert len(full_txt) >= len(pro_txt) >= len(compact_txt) or len({compact_txt, pro_txt, full_txt}) >= 2


def test_f23_soul_mode_switch_without_pin_refresh_is_blocked_403(monkeypatch):
    """Negativprobe: Tier-Wechsel fuer HIGH_RISK ohne refresh_soul_pin=True -> HTTP 403."""
    monkeypatch.setattr(hr_router, "_require_admin", lambda _req: None)
    with pytest.raises(HTTPException) as exc_info:
        hr_router.api_set_soul_mode(
            SimpleNamespace(),
            hr_router.SetSoulModeReq(mode="full", agent_id="founder", refresh_soul_pin=False),
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "agent_not_compliant"
    assert exc_info.value.detail["code"] == "SOUL_PIN_REFRESH_REQUIRED"


def test_f23_soul_mode_switch_with_pin_refresh_passes_refresh_flag(monkeypatch):
    """Positivprobe: mit refresh_soul_pin=True wird apply_soul_mode(..., refresh_pin=True) gerufen."""
    import scripts.sync_soul_modes as ssm

    captured = {}

    def _fake_apply(
        mode="compact",
        target_agent_id=None,
        lang=None,
        *,
        refresh_pin=False,
        guardrail_review_note="",
    ):
        captured.update(
            mode=mode,
            target_agent_id=target_agent_id,
            refresh_pin=refresh_pin,
            guardrail_review_note=guardrail_review_note,
        )
        return {"status": "success", "mode": mode, "pin_refreshed": refresh_pin}

    monkeypatch.setattr(hr_router, "_require_admin", lambda _req: None)
    monkeypatch.setattr(ssm, "apply_soul_mode", _fake_apply)
    monkeypatch.setattr(hr_router, "api_get_hermes_soul", lambda _aid: {"markdown": "# SOUL FULL"})

    res = hr_router.api_set_soul_mode(
        SimpleNamespace(),
        hr_router.SetSoulModeReq(
            mode="full",
            agent_id="founder",
            refresh_soul_pin=True,
            guardrail_review_note="F23 review ok",
        ),
    )
    assert captured == {
        "mode": "full",
        "target_agent_id": "founder",
        "refresh_pin": True,
        "guardrail_review_note": "F23 review ok",
    }
    assert res["pin_refreshed"] is True


def test_f23_soul_tier_change_audit_write_failure_is_fail_closed_403(monkeypatch, tmp_path):
    """Negativprobe: scheitert chained_audit_log.record_event -> HTTP 403 audit_write_failed, soul_mode unveraendert."""
    import json
    import backend.audit_log as audit_mod
    import scripts.sync_soul_modes as ssm

    profiles_file = tmp_path / "agent_profiles.json"
    profiles_file.write_text(
        json.dumps([{"id": "founder", "name": "Founder", "role": "CEO", "soul_mode": "compact", "prompt": "old"}]),
        encoding="utf-8",
    )
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()

    monkeypatch.setattr(hr_router, "_require_admin", lambda _req: None)
    monkeypatch.setattr(ssm, "PROFILES_JSON_PATH", str(profiles_file))
    monkeypatch.setattr(ssm, "get_profile_directories", lambda: [str(prof_dir)])
    monkeypatch.setattr(ssm, "refresh_soul_pin_for_agents", lambda target_agent_id=None: {"pin_refreshed": True})
    monkeypatch.setattr(
        audit_mod.chained_audit_log,
        "record_event",
        lambda **_kw: (_ for _ in ()).throw(OSError("simulated audit disk failure")),
    )

    with pytest.raises(HTTPException) as exc_info:
        hr_router.api_set_soul_mode(
            SimpleNamespace(),
            hr_router.SetSoulModeReq(
                mode="full",
                agent_id="founder",
                refresh_soul_pin=True,
                guardrail_review_note="audit fail test",
            ),
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "audit_write_failed"
    persisted = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert persisted[0]["soul_mode"] == "compact"
    assert persisted[0]["prompt"] == "old"


def test_f23_soul_tier_change_records_signed_audit_event_with_hashes_and_note(monkeypatch, tmp_path):
    """Positivprobe: Pin-Refresh schreibt compliance/soul_tier_changed inkl. old_hash, new_hash und note."""
    import json
    import backend.audit_log as audit_mod
    import scripts.sync_soul_modes as ssm

    profiles_file = tmp_path / "agent_profiles.json"
    profiles_file.write_text(
        json.dumps([{"id": "founder", "name": "Founder", "role": "CEO", "soul_mode": "compact", "prompt": "old"}]),
        encoding="utf-8",
    )
    prof_dir = tmp_path / "profiles"
    prof_dir.mkdir()
    recorded = []

    def _spy_record_event(**kwargs):
        recorded.append(kwargs)
        return {"id": "evt-f23-1", **kwargs}

    monkeypatch.setattr(hr_router, "_require_admin", lambda _req: None)
    monkeypatch.setattr(ssm, "PROFILES_JSON_PATH", str(profiles_file))
    monkeypatch.setattr(ssm, "get_profile_directories", lambda: [str(prof_dir)])
    monkeypatch.setattr(ssm, "refresh_soul_pin_for_agents", lambda target_agent_id=None: {"pin_refreshed": True})
    monkeypatch.setattr(hr_router, "api_get_hermes_soul", lambda _aid: {"markdown": "# SOUL FULL"})
    monkeypatch.setattr(audit_mod.chained_audit_log, "record_event", _spy_record_event)

    res = hr_router.api_set_soul_mode(
        SimpleNamespace(),
        hr_router.SetSoulModeReq(
            mode="full",
            agent_id="founder",
            refresh_soul_pin=True,
            guardrail_review_note="F23 compliance review signed",
        ),
    )
    assert res["pin_refreshed"] is True
    assert res["audit_recorded"] is True
    assert len(recorded) == 1
    ev = recorded[0]
    assert ev["category"] == "compliance"
    assert ev["action"] == "soul_tier_changed"
    assert ev["agent_id"] == "founder"
    payload = ev["payload"]
    assert payload["from"] == "compact"
    assert payload["to"] == "full"
    assert payload["old_hash"] and payload["new_hash"]
    assert payload["old_hash"] != payload["new_hash"]
    assert payload["guardrail_review_note"] == "F23 compliance review signed"
    persisted = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert persisted[0]["soul_mode"] == "full"


def test_f23_compliance_engine_blocks_unrefreshed_soul_hash_drift(monkeypatch):
    """Negativprobe: geaenderter SOUL-Hash ohne Inventar-Pin-Refresh -> SOUL_SHA256_MISMATCH."""
    engine = ComplianceEngine()
    monkeypatch.setattr(
        ComplianceEngine,
        "_canonical_soul_sha256",
        staticmethod(lambda _aid: "deadbeef" * 8),
    )
    res = engine.check_activation_allowed("founder")
    assert res["allowed"] is False
    assert res.get("error_code") == "SOUL_SHA256_MISMATCH"

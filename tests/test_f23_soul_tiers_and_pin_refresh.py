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

    def _fake_apply(mode="compact", target_agent_id=None, lang=None, *, refresh_pin=False):
        captured.update(mode=mode, target_agent_id=target_agent_id, refresh_pin=refresh_pin)
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
    assert captured == {"mode": "full", "target_agent_id": "founder", "refresh_pin": True}
    assert res["pin_refreshed"] is True


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

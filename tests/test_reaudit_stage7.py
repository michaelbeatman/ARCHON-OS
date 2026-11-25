"""Re-Audit Etappe 7 — D11: schema-validierte Handoffs, HMAC-Konsument, Canary-Ref."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from archon.core.delegation import (
    DelegationPayload,
    HandoffDelegationPayload,
    _parse_delegation_blocks,
    canonicalize_delegation_payload,
    verify_delegation_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def test_d11_payload_requires_target_and_task(monkeypatch):
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w5b-delegation-key")
    # F030/W3-A: EIN kanonisches Schema an der Handoff-Kante (alias-faehig).
    assert DelegationPayload is HandoffDelegationPayload
    with pytest.raises(ValidationError):
        HandoffDelegationPayload.model_validate({"ziel_agent": ""})
    with pytest.raises(ValidationError):
        HandoffDelegationPayload.model_validate({"auftrag": "Fix"})
    # extra="forbid" ist das korrekte Soll-Verhalten: Schattenfelder duerfen
    # nicht mehr still verworfen werden (frueher: extra="ignore").
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HandoffDelegationPayload.model_validate(
            {"ziel_agent": "coder", "auftrag": "Fix", "extra": "ignored"}
        )
    p = HandoffDelegationPayload.model_validate({"ziel_agent": "coder", "auftrag": "Fix"})
    assert p.ziel_agent == "coder"
    assert p.acceptance_criteria == ""

    # Der kanonische Helfer normalisiert Legacy-Aliase, dokumentiert Unknowns
    # in `extensions` und setzt/signiert den Server-Kontext (kein Body-Vertrauen).
    canon = canonicalize_delegation_payload(
        {"agent": "coder", "prompt": "Fix", "extra": "ignored"},
        task_id="task-w5b",
    )
    assert canon["ziel_agent"] == "coder"
    assert canon["auftrag"] == "Fix"
    assert canon["cancel_scope"] == "task:task-w5b"
    assert canon["extensions"]["extra"] == "ignored"
    assert canon["payload_signature"].startswith("dlg-hmac-sha256:")
    assert verify_delegation_payload(canon) is True


def test_d11_parser_schema_validates_before_dispatch():
    good = json.dumps({"ziel_agent": "coder", "auftrag": "Fix", "acceptance_criteria": "Tests grün"})
    bad = json.dumps({"ziel_agent": "coder"})
    valid, invalid = _parse_delegation_blocks(f"```delegation\n{good}\n```\n```delegation\n{bad}\n```")
    assert len(valid) == 1
    assert valid[0]["acceptance_criteria"] == "Tests grün"
    assert any("DelegationPayload" in str(i.get("error", "")) for i in invalid)


def test_d11_no_dead_import_fallback():
    src = (ROOT / "backend" / "operations_api.py").read_text(encoding="utf-8")
    assert "DelegationPayload = None" not in src
    # W3-A: kein lokales Zweitschema und kein Alter Import mehr. Die Kante
    # konsumiert das kanonische Schema ueber genau einen Helfer-Aufruf.
    assert "class KanbanDelegationPayload" not in src
    assert "from archon.core.delegation import DelegationPayload" not in src
    assert "HandoffDelegationPayload" in src
    assert "canonicalize_delegation_payload" in src
    # Kanonische Konsumenten: akzeptierte Uebergabe + Mandant aus SSOT.
    assert "require_accepted_handoff" in src
    assert "resolve_task_tenant_id" in src


def test_d11_structured_handoff_and_hmac_consumer():
    src = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert "STRUKTURIERTE ÜBERGABE (DelegationPayload v1, signiert)" in src
    assert "verify_payload_hash(handoff_id)" in src
    assert "mark_truncated(result, 4000" in src
    assert '"result": str(result or ""),' in src
    # Neues Schema + Signaturhelfer sind die Produzentenseite der Kante.
    assert "class HandoffDelegationPayload(BaseModel)" in src
    assert 'model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)' in src
    assert "def canonicalize_delegation_payload(" in src
    assert "payload = canonicalize_delegation_payload(raw)" in src
    assert "def sign_delegation_payload(" in src
    assert "def verify_delegation_payload(" in src


def test_d11_stream_prompt_ref_is_resolved():
    src = (ROOT / "backend" / "llm_kernel.py").read_text(encoding="utf-8")
    assert "prompt_registry.get_effective_prompt" in src
    assert '"source": "prompt_registry"' in src
    assert "hashlib.sha256" in src

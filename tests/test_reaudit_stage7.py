"""Re-Audit Etappe 7 — D11: schema-validierte Handoffs, HMAC-Konsument, Canary-Ref."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from archon.core.delegation import DelegationPayload, _parse_delegation_blocks

ROOT = Path(__file__).resolve().parents[1]


def test_d11_payload_requires_target_and_task():
    with pytest.raises(ValidationError):
        DelegationPayload.model_validate({"ziel_agent": ""})
    p = DelegationPayload.model_validate({"ziel_agent": "coder", "auftrag": "Fix", "extra": "ignored"})
    assert p.ziel_agent == "coder"
    assert p.acceptance_criteria == ""


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
    assert "from archon.core.delegation import DelegationPayload" in src


def test_d11_structured_handoff_and_hmac_consumer():
    src = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert "STRUKTURIERTE ÜBERGABE (DelegationPayload v1)" in src
    assert "verify_payload_hash(handoff_id)" in src
    assert "mark_truncated(result, 4000" in src
    assert '"result": str(result or ""),' in src


def test_d11_stream_prompt_ref_is_resolved():
    src = (ROOT / "backend" / "llm_kernel.py").read_text(encoding="utf-8")
    assert "prompt_registry.get_effective_prompt" in src
    assert '"source": "prompt_registry"' in src
    assert "hashlib.sha256" in src

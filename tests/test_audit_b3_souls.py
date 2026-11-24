"""Audit B3: versionierte SOUL-SSOT, Negativ-Abgrenzungen, AI-Act-Einstufung."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "ARCHON_NEGATIVE_GUARDRAILS_v1"


def test_all_profiles_have_negative_guardrails_de_en():
    data = json.loads((ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    assert len(data) >= 70
    for p in data:
        assert str(p.get("negative_scope") or "").strip(), f"{p.get('id')}: negative_scope fehlt"
        assert str(p.get("negative_scope_en") or "").strip(), f"{p.get('id')}: negative_scope_en fehlt"
        for field in ("prompt", "prompt_en", "system_prompt", "system_prompt_en"):
            if field in p:
                assert str(p[field] or "").strip(), f"{p.get('id')}: {field} leer"


def test_canonical_souls_manifest_is_complete():
    manifest = json.loads((ROOT / "souls" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) >= 480, f"Nur {len(manifest)} SOUL-Artefakte"
    for rel, expected in manifest.items():
        path = ROOT / "souls" / rel
        assert path.is_file(), f"fehlt: {rel}"
        # Git-checkout auf Windows liefert CRLF; der Generator hasht normalisierte
        # Texte (read_text macht Universal-Newline-Konvertierung). Daher auch hier
        # ueber read_text() hasht, nicht ueber rohe Bytes.
        content = path.read_text(encoding="utf-8")
        assert hashlib.sha256(content.encode("utf-8")).hexdigest() == expected, f"Hash abweichend: {rel}"


def test_regulated_domains_are_high_risk():
    import sys

    sys.path.insert(0, str(ROOT))
    from backend.eu_ai_act_inventory import EUAIActInventoryManager

    manager = EUAIActInventoryManager()
    tiers = Counter(manager.classify_agent(p)["risk_tier"] for p in manager.load_profiles())
    assert tiers["HIGH_RISK"] >= 20, f"Zu wenige HIGH_RISK-Rollen: {tiers}"
    for pid in ("tax_holding_advisor", "commercial_jurist_contracts", "clinical_medical_advisor"):
        p = next((x for x in manager.load_profiles() if x.get("id") == pid), None)
        if p:
            assert manager.classify_agent(p)["risk_tier"] == "HIGH_RISK", f"{pid} nicht HIGH_RISK"

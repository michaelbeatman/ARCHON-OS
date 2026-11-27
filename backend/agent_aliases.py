"""Auflösung historischer Agenten-Handles auf echte Kader-Profile.

Mehrere Module (Kanban-Default, Internet-Watchdog, Dunning, DocuSeal) verwenden
noch Handles aus der Frühphase, die im Kader nicht existieren. Aufgaben für
solche Handles wurden bisher als `skipped_nonspawnable` verworfen.

Diese Zuordnung ist die einzige Stelle, an der die Altnamen übersetzt werden.
"""

from __future__ import annotations

import json
import os

_WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ORG_HIERARCHY_PATH = os.path.join(_WORKSPACE_DIR, "config", "org_hierarchy.json")

# D15-H5: historische Tool-Namen aus Prompt-Freitext sind keine eigenen Tools.
# Die Normalisierung liest die SSOT (`tool_aliases`) und kennt nur diese drei
# Legacy-Zuordnungen. Ein unbekanntes Tool bleibt unveraendert und wird damit
# im Gate als Abweichung sichtbar (fail-closed, kein stilles Map auf web_search).
_FALLBACK_TOOL_ALIASES = {
    "FileSystem_MCP": "filesystem",
    "Calculator": "execute_code",
    "WebSearch": "web_search",
}

# D15-H5: beratende HIGH_RISK-Rollen duerfen keine Exekutivwerkzeuge fuehren.
# Positivliste bewusst hier (nicht im Inventar) — das Inventar gehoert einer
# anderen Wellen-Partition. Diese IDs sind die beratenden Rollen aus
# HIGH_RISK_AGENT_IDS von backend/eu_ai_act_inventory.py.
ADVISORY_HIGH_RISK_AGENT_IDS = frozenset({
    "hr_recruiter",
    "labor_law_hr_governance",
    "legal_counsel",
    "commercial_jurist_contracts",
    "ip_patent_analyst",
    "compliance_gdpr_auditor",
    "tax_holding_advisor",
    "vvgmbh_immo_tax_lead",
    "finance_lead",
    "debt_financing_specialist",
    "insurance_claims_manager",
    "liability_risk_analyst",
    "bi_controller",
    "realestate_dcf_calculator",
    "clinical_medical_advisor",
    "medtech_regulatory_lead",
    "pharma_biotech_scientist",
    "scientific_literature_synthesizer",
    "chemistry_materials_specialist",
    "urban_planning_architect",
    "industrial_process_engineer",
    "facility_asset_manager",
    "vendor_contract_negotiator",
    "founder",
})

_LEGACY_ALIASES = {
    "hermes-researcher": "research_scout",
    "hermes_researcher": "research_scout",
    "research_scout": "research_scout",
    "hermes-coder": "senior_fullstack_engineer",
    "hermes_coder": "senior_fullstack_engineer",
    "hermes-orchestrator": "default",
    "hermes_orchestrator": "default",
    "finance_lead": "finance_lead",
    "legal_counsel": "legal_counsel",
    # Kurz-Handles aus Workflow-Templates & Content-Pipelines
    "research": "research_scout",
    "writer": "storyteller_ghostwriter",
    "copywriter": "direct_response_copywriter",
    "qa": "qa_test_engineer",
    "engineer": "senior_fullstack_engineer",
    "analyst": "bi_controller",
    "security": "devops_cloud_sec_specialist",
    "seo": "seo_geo_specialist",
    "video": "video_script_architect",
    "repurposing": "content_repurposing_specialist",
    "linkedin": "linkedin_social_media_specialist",
    "social_media": "linkedin_social_media_specialist",
}


def _load_ssot_aliases() -> dict:
    """W2-C/F034: `config/org_hierarchy.json.aliases` ist die Alias-SSOT.

    Das frühere zweite Register hier widersprach Delegation, Konsens und
    Compliance. historische Kurz-Handles bleiben nur als Fallback für Keys,
    die die SSOT nicht kennt — nie als Überschreibung einer SSOT-Zuordnung.
    """
    import json
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "org_hierarchy.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        aliases = {str(k): str(v) for k, v in (data.get("aliases") or {}).items()}
    except Exception:
        aliases = {}
    merged = dict(_LEGACY_ALIASES)
    merged.update(aliases)
    return merged


def _load_tool_aliases() -> dict:
    """D15-H5: Tool-Aliase stammen ausschliesslich aus der Organigramm-SSOT."""
    aliases = dict(_FALLBACK_TOOL_ALIASES)
    try:
        with open(_ORG_HIERARCHY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ssot = {str(k): str(v) for k, v in (data.get("tool_aliases") or {}).items()}
        aliases.update(ssot)
    except Exception:
        # Fallback auf die eingebauten Aliase; das Gate bleibt trotzdem aktiv.
        pass
    return aliases


TOOL_ALIASES = _load_tool_aliases()

ALIASES = _load_ssot_aliases()

# W2-B/D04-M6: Ein eindeutiger, nicht mit einem echten Kader-Profil
# verwechselbarer Sentinel für nicht auflösbare Ziel-IDs. Aufrufer MÜSSEN ihn
# als Default-Deny behandeln (z. B. status=blocked, error_code=UNKNOWN_AGENT_ID).
UNKNOWN_AGENT_ID = "!UNKNOWN_AGENT!"


def resolve_agent_id(agent_id: str | None, known_ids: set[str] | None = None) -> str:
    """Übersetzt einen Altnamen in eine gültige Kader-ID.

    Ist der Name bereits gültig, bleibt er unverändert. Ohne ``known_ids``
    werden unbekannte Namen unverändert zurückgegeben, damit der Aufrufer den
    Fehler sichtbar behandeln kann (kein stiller Fallback auf einen falschen
    Agenten).

    D04-M6: Eine leere ID wird NICHT mehr auf "research_scout" gemappt, sondern
    auf ``UNKNOWN_AGENT_ID``. Wird ``known_ids`` übergeben, erhält der Aufrufer
    den Sentinel auch bei unbekanntem Ziel. Ohne ``known_ids`` kann der Helper
    eine unbekannte ID nicht erkennen — die Produktivaufrufer müssen daher zwingend
    ``known_ids`` übergeben und den Sentinel hart blockieren.
    """
    raw = (agent_id or "").strip()
    if not raw:
        return UNKNOWN_AGENT_ID
    mapped = ALIASES.get(raw, raw)
    if known_ids is not None and mapped not in known_ids:
        return UNKNOWN_AGENT_ID
    return mapped


def canonical_tool_name(name: str) -> str:
    """Normalisiert einen Tool-Namen ueber die Alias-SSOT (D15-H5)."""
    raw = str(name or "").strip()
    return TOOL_ALIASES.get(raw, raw)


def canonical_tool_names(names: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Normalisiert eine Tool-Menge und entfernt Duplikate ohne Reihenfolge zu aendern."""
    result: list[str] = []
    for name in names:
        canonical = canonical_tool_name(name)
        if canonical and canonical not in result:
            result.append(canonical)
    return result

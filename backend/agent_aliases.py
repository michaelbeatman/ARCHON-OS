"""Auflösung historischer Agenten-Handles auf echte Kader-Profile.

Mehrere Module (Kanban-Default, Internet-Watchdog, Dunning, DocuSeal) verwenden
noch Handles aus der Frühphase, die im Kader nicht existieren. Aufgaben für
solche Handles wurden bisher als `skipped_nonspawnable` verworfen.

Diese Zuordnung ist die einzige Stelle, an der die Altnamen übersetzt werden.
"""

from __future__ import annotations

_LEGACY_ALIASES = {
    "hermes-researcher": "research_scout",
    "hermes_researcher": "research_scout",
    "research_scout": "research_scout",
    "hermes-coder": "senior_fullstack_engineer",
    "hermes_coder": "senior_fullstack_engineer",
    "hermes-orchestrator": "system_architect_orchestrator",
    "hermes_orchestrator": "system_architect_orchestrator",
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


ALIASES = _load_ssot_aliases()


def resolve_agent_id(agent_id: str | None, known_ids: set[str] | None = None) -> str:
    """Übersetzt einen Altnamen in eine gültige Kader-ID.

    Ist der Name bereits gültig, bleibt er unverändert. Unbekannte Namen werden
    unverändert zurückgegeben, damit der Aufrufer den Fehler sichtbar behandeln
    kann (kein stiller Fallback auf einen falschen Agenten).
    """
    raw = (agent_id or "").strip()
    if not raw:
        return "research_scout"
    mapped = ALIASES.get(raw, raw)
    if known_ids is not None and mapped not in known_ids:
        return mapped
    return mapped

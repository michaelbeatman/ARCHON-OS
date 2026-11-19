# -*- coding: utf-8 -*-
"""
backend/operations_templates.py
===============================
Meilenstein 62: Einheitliche Vorlagen-Verwaltung in Operations
(Beleg-, Playbook- & Workflow-Vorlagen mit Vorschau-Renderer).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

BUILTIN_OPERATIONS_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "tpl_invoice_de",
        "category": "beleg",
        "title": "Rechnung (DE / § 14 UStG)",
        "description": "Standard-Rechnungsvorlage mit Leistungszeitraum, USt-Ausweis und Zahlungsziel.",
        "body": "Rechnung {{doc.number}} an {{customer.name}} ueber {{doc.total_eur}} EUR (inkl. 19% USt).",
    },
    {
        "id": "tpl_playbook_research",
        "category": "playbook",
        "title": "Deep-Research & Dossier",
        "description": "Mehrstufiges Research-Playbook inkl. Triangulation und Obsidian-Ablage.",
        "body": "1. Primaerquellen pruefen\n2. Triangulation (>= 2 Domains)\n3. Dossier in 02_Research/{{topic}}.md",
    },
    {
        "id": "tpl_workflow_release",
        "category": "workflow",
        "title": "Verified Release Gate",
        "description": "Writer -> Cross-Model-Verifier -> Proof-Command -> Human-Approval.",
        "body": "Writer: {{agent.writer}} | Verifier: {{agent.verifier}} | Proof: {{task.proof_command}}",
    },
]


def list_operations_templates(category: Optional[str] = None) -> List[Dict[str, Any]]:
    if not category or category == "all":
        return list(BUILTIN_OPERATIONS_TEMPLATES)
    cat = category.strip().lower()
    return [t for t in BUILTIN_OPERATIONS_TEMPLATES if t["category"] == cat]


def preview_operations_template(template_id: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tpl = next((t for t in BUILTIN_OPERATIONS_TEMPLATES if t["id"] == template_id), None)
    if not tpl:
        raise KeyError(f"Vorlage '{template_id}' nicht gefunden.")
    vals = variables or {}

    def _repl(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(vals.get(key, f"[{key}]"))

    rendered = re.sub(r"\{\{([^}]+)\}\}", _repl, tpl["body"])
    return {**tpl, "rendered_preview": rendered}

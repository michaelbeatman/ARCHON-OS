# -*- coding: utf-8 -*-
"""
backend/execution_routing_guard.py
==================================
Architektur-Trennungsregel (Deterministisch vs. Probabilistisch):
Entscheidet vor dem Start eines LLM-Agenten, ob eine Aufgabe deterministisch
(tokenfrei über n8n-Workflow oder lokales Python-Skript) ausgeführt werden
muss oder probabilistische Urteilskraft (Archon LLM-Agent via MCP + HITL-Gate)
erfordert.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

ROUTING_MATRIX: List[Dict[str, Any]] = [
    {
        "rule_id": "det_n8n_email_crm_sync",
        "layer": "deterministic_n8n",
        "title": "E-Mail-Abruf, IMAP-Polling & CRM-Kontakt-Abgleich",
        "keywords": ["e-mail-sync", "gleiche mails ab", "imap abruf", "newsletter versand", "webhook crm", "autoresponder"],
        "target_engine": "n8n / scripts/archon_crm_mcp.py",
        "webhook_action": "webhook_crm",
        "token_cost": 0,
        "requires_hitl": False,
        "rationale": "Standardisierter Datenabgleich nach festen Feldregeln (messageId-Deduplizierung) benötigt kein Sprachmodell.",
    },
    {
        "rule_id": "det_n8n_scheduled_publishing",
        "layer": "deterministic_n8n",
        "title": "Zeitgesteuertes Social-Media-Publishing & Webhook-Auslieferung",
        "keywords": ["post_linkedin", "publish_linkedin", "veröffentliche geplanten post", "schedule webhook", "n8n_publish"],
        "target_engine": "n8n (/webhook/archon-execution)",
        "webhook_action": "publish_linkedin",
        "token_cost": 0,
        "requires_hitl": True,
        "rationale": "Nach bestandener Human-Score-Prüfung und menschlicher Freigabe ist der API-Upload ein rein deterministischer Transport.",
    },
    {
        "rule_id": "det_script_backup_maintenance",
        "layer": "deterministic_script",
        "title": "System-Backups, Datenbank-Konsolidierung, USt-Split & Telegram-Session-Sync",
        "keywords": ["docker backup", "ust-split", "mehrwertsteuer berechnen", "synchronisiere telegram", "importiere linkedin archiv", "db backup"],
        "target_engine": "Python Native Script (backup_archon.py / sync_telegram_sessions.py / auto-calculate-vat-split)",
        "webhook_action": "local_script",
        "token_cost": 0,
        "requires_hitl": False,
        "rationale": "Mathematische Berechnungen und Dateisystem-Snapshots dürfen niemals halluzinieren und laufen zu 100 % deterministisch.",
    },
    {
        "rule_id": "det_watchdog_rss_scan",
        "layer": "deterministic_script",
        "title": "RSS-, News- & Wettbewerber-Radar (Rohdaten-Erfassung)",
        "keywords": ["rss scan", "watchdog poll", "feed abrufen", "website diff"],
        "target_engine": "backend/internet_watchdog.py + backend/watchdog_radar_v2.py",
        "webhook_action": "watchdog_scan",
        "token_cost": 0,
        "requires_hitl": False,
        "rationale": "Kontinuierliches Polling und SHA-256-Dublettenfilterung laufen tokenfrei im Hintergrund; erst bei relevanten Treffern wird eine Idee erzeugt.",
    },
    {
        "rule_id": "hybrid_agent_harness",
        "layer": "hybrid_harness",
        "title": "Hybride Kette: Deterministischer Trigger -> KI-Bewertung -> n8n-Ausführung mit HITL",
        "keywords": ["content-pipeline", "repurpose", "angebot aus anfrage", "bewerbung prüfen", "vertrag prüfen und versenden", "dossier erstellen und senden"],
        "target_engine": "n8n Intake -> Archon Specialist Agent (MCP + voice.md Gate) -> HITL Approval -> n8n Outbound",
        "webhook_action": "hybrid_pipeline",
        "token_cost": "bounded_by_task_budget",
        "requires_hitl": True,
        "rationale": "Kombiniert tokenfreie Datenerfassung mit kognitiver Bewertung durch Spezialisten-Agenten und zwingender Freigabe vor Außenwirkung.",
    },
    {
        "rule_id": "prob_agent_cognition",
        "layer": "probabilistic_agent",
        "title": "Kognitive Analyse, Strategie, Code-Architektur, Red-Teaming & Text-Synthese",
        "keywords": ["strategie", "boardroom", "entwurf", "ghostwriting", "architektur", "analyse", "code", "rechtsprüfung", "dcf", "konzept"],
        "target_engine": "Archon Multi-Agent Orchestrator (Robert / Sandy / Spezialisten / Lisa)",
        "webhook_action": "archon_agent_dispatch",
        "token_cost": "role_and_task_budget_capped",
        "requires_hitl": False,
        "rationale": "Offene Fragestellungen, Abwägungen und kreative Synthese erfordern Sprachmodelle innerhalb harter Token-Budgets.",
    },
]

# D02/M2: Negativ-Kontext. "Analysiere die USt-Split-Logik" ist eine kognitive
# Aufgabe — ein Keyword-Treffer (z. B. "ust-split") darf daraus keinen
# 0-Token-Skript-Dispatch machen, nur weil das Wort im Text vorkommt.
_ANALYSIS_DIRECTIVE_RE = re.compile(
    r"\b(?:analysier\w*|beschreib\w*|(?:erklär|erklaer)\w*|interpretier\w*|beurteil\w*)\b",
    re.IGNORECASE,
)

# Rollen-Präfixe sind Transport-Metadaten, kein Auftragstext.
_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:system|developer|assistant|user)\s*:\s*", re.IGNORECASE
)


def canonical_routing_text(
    messages: Optional[List[Any]] = None, prompt: Optional[str] = None
) -> str:
    """D02/M2: EIN kanonischer, ungekürzter Auftragstext für beide Chokepoints.

    Der Router liefert ``messages`` (System-Direktiven + alle Nutzer-Turns,
    rollenbereinigt), der Dispatcher den vollständigen ``prompt``. Es wird
    bewusst NICHT gekürzt (früher: ``messages[-4:]`` / 160 Zeichen) — eine
    Deterministik-Direktive in einem älteren Turn darf nicht verloren gehen.
    """
    if messages is None:
        return str(prompt or "").strip()
    parts: List[str] = []
    for message in messages:
        if isinstance(message, dict):
            role = str(message.get("role") or "user").strip().lower()
            if role not in ("system", "developer", "user"):
                continue
            content = message.get("content")
            if isinstance(content, (list, tuple)):
                # Multimodal: nur die Text-Blöcke zählen für die Klassifikation.
                content = " ".join(
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict)
                )
            value = str(content or "").strip()
        else:
            value = str(message or "").strip()
        value = _ROLE_PREFIX_RE.sub("", value).strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()


def classify_execution_request(
    messages: Optional[List[Any]] = None, prompt: Optional[str] = None
) -> Dict[str, Any]:
    """D02/M2: kanonischer Klassifikations-Chokepoint.

    Router UND Dispatcher rufen ausschließlich diese Funktion; damit gibt es
    für denselben Auftrag keine pfadabhängigen Routing-Entscheidungen mehr.
    """
    return classify_execution_layer(
        canonical_routing_text(messages=messages, prompt=prompt)
    )


def classify_execution_layer(title: str, body: str = "") -> Dict[str, Any]:
    """
    Classifies a task into:
    - `deterministic_n8n` (0 tokens, n8n workflow)
    - `deterministic_script` (0 tokens, local Python script)
    - `hybrid_harness` (n8n + bounded Agent + HITL Gate)
    - `probabilistic_agent` (Archon LLM Agent with Role/Task Token Budget)
    """
    text = f"{title or ''} {body or ''}".strip().lower()

    # Check explicit directive tags first (Leerzeichen um ':' tolerant —
    # "ACTION: WEBHOOK_CRM" muss genauso greifen wie "action:webhook_crm").
    compact = re.sub(r"\s+", "", text)
    explicit_directive = (
        "layer:n8n" in compact
        or "action:webhook_" in compact
        or "action:publish_" in compact
    )
    if explicit_directive:
        return {
            "layer": "deterministic_n8n",
            "rule_id": "explicit_n8n_directive",
            "token_free": True,
            "recommended_engine": "n8n",
            "requires_llm": False,
            "requires_hitl": True,
            "rationale": "Explizite n8n-Webhook-Direktive im Auftrag erkannt.",
        }

    # D02/M2: "analysiere/beschreibe ..." ist ein kognitiver Auftrag. Solche
    # Texte dürfen nicht allein wegen eines enthaltenen Keywords als 0-Token-
    # Skript/Workflow klassifiziert werden. Explizite Direktiven (oben) haben
    # Vorrang; analysierte Hybrid-/Probabilistik-Regeln bleiben erreichbar.
    analysis_context = bool(_ANALYSIS_DIRECTIVE_RE.search(text))
    for rule in ROUTING_MATRIX:
        matched = [kw for kw in rule["keywords"] if kw in text]
        if matched:
            if (
                analysis_context
                and rule["layer"] in ("deterministic_n8n", "deterministic_script")
            ):
                continue
            is_det = rule["layer"] in ("deterministic_n8n", "deterministic_script")
            return {
                "layer": rule["layer"],
                "rule_id": rule["rule_id"],
                "title": rule["title"],
                "matched_keywords": matched,
                "token_free": is_det,
                "recommended_engine": rule["target_engine"],
                "webhook_action": rule["webhook_action"],
                "requires_llm": not is_det,
                "requires_hitl": rule["requires_hitl"],
                "rationale": rule["rationale"],
            }

    return {
        "layer": "probabilistic_agent",
        "rule_id": "default_probabilistic_agent",
        "title": "Kognitive Spezialisten-Aufgabe (Archon Agent)",
        "matched_keywords": [],
        "token_free": False,
        "recommended_engine": "Archon Multi-Agent Orchestrator",
        "webhook_action": "archon_agent_dispatch",
        "requires_llm": True,
        "requires_hitl": any(w in text for w in ("veröffentlichen", "senden", "zahlung", "überweisung", "vertrag unterschreiben", "löschen")),
        "rationale": "Aufgabe erfordert inhaltliche Bewertung oder Text-/Code-Synthese durch einen budgetierten Archon-Spezialisten.",
    }


def get_routing_architecture_matrix() -> Dict[str, Any]:
    return {
        "principle": "Deterministisch vor Probabilistisch (No unnecessary tokens, no unapproved external actions)",
        "layers": [
            {
                "id": "deterministic_n8n",
                "name": "1. Deterministischer Workflow-Layer (n8n)",
                "token_budget": "0 Tokens",
                "scope": "Webhooks, Zeitpläne, API-Transport, IMAP/SMTP-Sync, CRM-Feldabgleich, Social-Media-Upload nach Freigabe.",
            },
            {
                "id": "deterministic_script",
                "name": "2. Deterministischer System- & Mathe-Layer (Python/SQLite)",
                "token_budget": "0 Tokens",
                "scope": "RSS/Watchdog-Polling, SHA-256-Deduplizierung, USt-/Finanzmathematik, Docker-/DB-Backups, Session-Sync.",
            },
            {
                "id": "hybrid_harness",
                "name": "3. Hybrider Agent-Harness-Layer (n8n + Archon MCP + HITL)",
                "token_budget": "Task-Budget-Capped",
                "scope": "n8n liefert strukturierte Rohdaten -> Archon-Spezialist bewertet/formuliert (mit voice.md & Human-Score) -> HITL-Freigabe -> n8n führt aus.",
            },
            {
                "id": "probabilistic_agent",
                "name": "4. Probabilistischer Kognitions-Layer (Archon Organigramm & Boardroom)",
                "token_budget": "Role & Task Budget-Capped (Auto-Split nach Komplexität)",
                "scope": "Strategie, C-Level-Dossiers, Rechts-/Steueranalyse, Software-Engineering, Ghostwriting, Ad-hoc CEO-Hiring.",
            },
        ],
        "rules": ROUTING_MATRIX,
    }

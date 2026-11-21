# -*- coding: utf-8 -*-
"""
backend/voice_to_workflow.py
============================
Meilenstein 54: Voice-to-Workflow & 2-Stufen-KI-Spezifikations-Helfer.

Stufe 1: Erkennt Unklarheiten im gesprochenen Diktat und stellt gezielte Rueckfragen.
Stufe 2: Uebersetzt Diktat + Antworten in ein deterministisches Playbook-JSON.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def analyze_dictation_ambiguities(dictated_text: str) -> Dict[str, Any]:
    low = (dictated_text or "").lower()
    questions: List[str] = []
    if not re.search(r"\b(taeglich|woechentlich|monatlich|manuell|webhook|sofort|cron)\b", low):
        questions.append("Wann bzw. wodurch soll der Workflow ausgeloest werden (manuell, Zeitplan, Webhook)?")
    if not re.search(r"\b(telegram|email|e-mail|kanban|obsidian|erp)\b", low):
        questions.append("Wohin soll das Ergebnis ausgegeben werden (Kanban, Telegram, E-Mail, Obsidian)?")
    if not re.search(r"\b(freigabe|hitl|automatisch|genehmig)\b", low):
        questions.append("Soll vor kritischen Aktionen eine menschliche Freigabe (HITL) erfolgen?")
    return {
        "needs_clarification": len(questions) > 0,
        "questions": questions,
    }


def compile_playbook_from_spec(
    name: str,
    dictated_text: str,
    clarifications: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    answers = clarifications or {}
    steps = [
        {"id": "step_1_ingest", "kind": "script", "action": "parse_input", "source_text": dictated_text.strip()},
        {"id": "step_2_execute", "kind": "agent", "prompt": dictated_text.strip(), "trigger": answers.get("trigger", "manual")},
        {"id": "step_3_deliver", "kind": "script", "target": answers.get("target", "kanban"), "require_hitl": answers.get("hitl", "ja").lower() in ("ja", "yes", "true")},
    ]
    return {
        "id": re.sub(r"[^a-zA-Z0-9_-]+", "_", name.lower()).strip("_") or "voice_playbook",
        "name": name,
        "steps": steps,
    }

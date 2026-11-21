# -*- coding: utf-8 -*-
"""
backend/meeting_copilot.py
==========================
Meilenstein 39: Lokaler Meeting- & Call-Copilot (Audio -> Protokoll + Tasks).

Formatiert sprechergetrennte Transkripte, extrahiert To-Dos fuer Kanban
und erstellt strukturierte CRM-Aktennotizen.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def format_diarized_transcript(segments: List[Dict[str, Any]]) -> str:
    lines = []
    for seg in segments:
        spk = seg.get("speaker") or "Sprecher"
        ts = seg.get("timestamp") or "00:00"
        txt = (seg.get("text") or "").strip()
        if txt:
            lines.append(f"[{ts}] {spk}: {txt}")
    return "\n".join(lines)


def extract_action_items(transcript_text: str) -> List[Dict[str, str]]:
    """Extrahiert erkannte To-Dos / Action Items aus Meeting-Protokollen."""
    items: List[Dict[str, str]] = []
    pat = re.compile(r"(?:TODO|AUFGABE|ACTION|@([a-zA-Z0-9_]+))\s*:?\s*(.+)", re.I)
    for line in (transcript_text or "").splitlines():
        m = pat.search(line)
        if m:
            assignee = m.group(1) or "default"
            title = m.group(2).strip()
            if title:
                items.append({"assignee": assignee, "title": title, "status": "todo"})
    return items


def build_crm_meeting_note(
    customer_name: str,
    segments: List[Dict[str, Any]],
    all_participants_consented: bool = False,
    consent_timestamp: str = "",
) -> Dict[str, Any]:
    """
    Erstellt Meeting-Protokoll + Kanban-Tasks.
    § 201 StGB Schutz: Blockiert fail-closed ohne dokumentierte Einwilligung aller Teilnehmer.
    """
    if not all_participants_consented:
        raise PermissionError(
            "§ 201 StGB Consent-Gate: Verarbeitung von Gespraechsmitschnitten erfordert die "
            "dokumentierte Einwilligung aller Teilnehmer (all_participants_consented=True)."
        )
    transcript = format_diarized_transcript(segments)
    tasks = extract_action_items(transcript)
    return {
        "customer": customer_name,
        "consent_verified": True,
        "consent_timestamp": consent_timestamp,
        "transcript": transcript,
        "kanban_tasks": tasks,
        "task_count": len(tasks),
    }

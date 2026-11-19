# -*- coding: utf-8 -*-
"""
backend/enterprise_calendar.py
==============================
Meilenstein 55 (inkl. M25): Enterprise-Kalender-Ausbau
(Monats-/Wochen-/Tagesraster, Drag-&-Drop-Reschedule, Serientermine, Agenten-Ansicht).
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def expand_recurring_events(
    events: List[Dict[str, Any]],
    horizon_days: int = 30,
) -> List[Dict[str, Any]]:
    """Expandiert Serientermine (recurrence: daily|weekly|monthly) bis horizon_days."""
    expanded: List[Dict[str, Any]] = []
    for ev in events:
        expanded.append(ev)
        rec = str(ev.get("recurrence") or "").lower()
        if rec not in ("daily", "weekly", "monthly"):
            continue
        start_s = str(ev.get("start") or "")
        try:
            dt = datetime.datetime.fromisoformat(start_s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        count = int(ev.get("recurrence_count") or 4)
        for i in range(1, count):
            delta_days = i if rec == "daily" else (7 * i if rec == "weekly" else 30 * i)
            if delta_days > horizon_days:
                break
            ndt = dt + datetime.timedelta(days=delta_days)
            expanded.append({**ev, "id": f"{ev.get('id')}_r{i}", "start": ndt.isoformat(), "is_occurrence": True})
    return expanded


def build_calendar_grid(
    events: List[Dict[str, Any]],
    view: str = "week",
    anchor_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Gruppiert Events fuer Monats-, Wochen- oder Tagesraster."""
    v = (view or "week").lower()
    if v not in ("day", "week", "month"):
        v = "week"
    anchor = anchor_date or datetime.date.today().isoformat()
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for ev in expand_recurring_events(events):
        day_key = str(ev.get("start") or "")[:10] or anchor
        by_day.setdefault(day_key, []).append(ev)
    return {"view": v, "anchor_date": anchor, "days": by_day, "total_events": sum(len(x) for x in by_day.values())}


def reschedule_calendar_event(event: Dict[str, Any], new_start_iso: str, new_end_iso: Optional[str] = None) -> Dict[str, Any]:
    updated = dict(event)
    updated["start"] = new_start_iso
    if new_end_iso:
        updated["end"] = new_end_iso
    return updated


def group_events_by_agent(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        ag = str(ev.get("assignee") or ev.get("agent_id") or "unassigned")
        grouped.setdefault(ag, []).append(ev)
    return grouped

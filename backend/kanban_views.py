# -*- coding: utf-8 -*-
"""
backend/kanban_views.py
=======================
Meilenstein 78: Mission Control Kanban — Gantt-Timeline & Dependency-Graph
(kanban-gantt-Pattern auf Archons zentraler tasks-SQLite-DB).

Hybrid-Modus: Explizite Start-/Enddaten werden genutzt; fehlende Werte werden
automatisch aus created_at + Default-Dauer/Laufzeit berechnet.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def _parse_iso(val: Optional[str]) -> Optional[datetime.datetime]:
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def build_gantt_items(
    tasks: List[Dict[str, Any]],
    default_duration_hours: int = 4,
    now_dt: Optional[datetime.datetime] = None,
) -> List[Dict[str, Any]]:
    now = now_dt or datetime.datetime.now()
    items: List[Dict[str, Any]] = []

    for t in tasks:
        explicit_start = _parse_iso(t.get("started_at"))
        created = _parse_iso(t.get("created_at"))
        start = explicit_start or created or now

        explicit_end = _parse_iso(t.get("completed_at")) or _parse_iso(t.get("due_date"))
        has_explicit = bool(explicit_start and explicit_end)

        if explicit_end and explicit_end > start:
            end = explicit_end
        elif str(t.get("status") or "").lower() == "in_progress":
            candidate = max(now, start + datetime.timedelta(hours=1))
            end = candidate
        else:
            end = start + datetime.timedelta(hours=default_duration_hours)

        dur_h = round(max(0.25, (end - start).total_seconds() / 3600.0), 2)
        items.append({
            "id": t.get("id"),
            "title": t.get("title") or t.get("id"),
            "status": t.get("status") or "todo",
            "assignee": t.get("assignee") or "",
            "priority": t.get("priority", 1),
            "project_id": t.get("project_id") or "",
            "parent_id": t.get("parent_id") or t.get("delegated_from") or "",
            "subtasks": t.get("subtasks") or [],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_hours": dur_h,
            "has_explicit_dates": has_explicit,
        })

    items.sort(key=lambda x: (x["start"], str(x["id"])))
    return items


def build_dependency_graph(
    tasks: List[Dict[str, Any]],
    links: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Erzeugt Nodes mit Longest-Path-Layering und gerichtete Edges aus tasks + task_links.
    """
    task_map: Dict[str, Dict[str, Any]] = {str(t["id"]): t for t in tasks if t.get("id")}
    edges: List[Dict[str, str]] = []
    parents: Dict[str, List[str]] = {tid: [] for tid in task_map}
    children: Dict[str, List[str]] = {tid: [] for tid in task_map}

    for lnk in links:
        src = str(lnk.get("parent_id") or lnk.get("from_id") or lnk.get("source") or "").strip()
        dst = str(lnk.get("child_id") or lnk.get("to_id") or lnk.get("target") or "").strip()
        kind = str(lnk.get("link_type") or lnk.get("kind") or "depends_on").strip()
        if src in task_map and dst in task_map and src != dst:
            edges.append({"from": src, "to": dst, "type": kind})
            parents[dst].append(src)
            children[src].append(dst)

    # Longest-path layer calculation (cycle-safe)
    layers: Dict[str, int] = {}

    def _layer(tid: str, visiting: set[str]) -> int:
        if tid in layers:
            return layers[tid]
        if tid in visiting:
            return 0
        visiting.add(tid)
        p_layers = [_layer(p, visiting) + 1 for p in parents.get(tid, [])]
        visiting.remove(tid)
        lvl = max(p_layers) if p_layers else 0
        layers[tid] = lvl
        return lvl

    nodes: List[Dict[str, Any]] = []
    for tid, t in task_map.items():
        nodes.append({
            "id": tid,
            "title": t.get("title") or tid,
            "status": t.get("status") or "todo",
            "assignee": t.get("assignee") or "",
            "layer": _layer(tid, set()),
            "blocked_by": parents.get(tid, []),
            "blocks": children.get(tid, []),
        })

    nodes.sort(key=lambda n: (n["layer"], n["id"]))
    return {"nodes": nodes, "edges": edges}

# -*- coding: utf-8 -*-
"""
backend/calendar_sync_blocker.py
================================
Meilenstein 41: Bi-direktionaler Kalender-Sync (CalDAV/ICS) & Fokus-Blocker.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def parse_ics_events(ics_text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for raw_line in (ics_text or "").splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if cur.get("uid"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            k, v = line.split(":", 1)
            key = k.split(";")[0].upper()
            if key == "UID":
                cur["uid"] = v
            elif key == "SUMMARY":
                cur["title"] = v
            elif key == "DTSTART":
                cur["start"] = v
            elif key == "DTEND":
                cur["end"] = v
            elif key == "LAST-MODIFIED":
                cur["updated_at"] = v
    return events


def export_ics_events(events: List[Dict[str, Any]]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Archon OS//Calendar Sync//DE"]
    for ev in events:
        uid = ev.get("uid") or ev.get("id") or "ev-1"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{ev.get('title') or 'Archon Event'}",
            f"DTSTART:{ev.get('start') or ''}",
            f"DTEND:{ev.get('end') or ''}",
            f"LAST-MODIFIED:{ev.get('updated_at') or ''}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def sync_calendar_bidirectional(
    local_events: List[Dict[str, Any]],
    remote_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """2-Wege-Merge per UID anhand des neueren updated_at-Zeitstempels."""
    loc_map = {str(e.get("uid") or e.get("id")): e for e in local_events if (e.get("uid") or e.get("id"))}
    rem_map = {str(e.get("uid") or e.get("id")): e for e in remote_events if (e.get("uid") or e.get("id"))}

    merged: List[Dict[str, Any]] = []
    push_to_remote: List[Dict[str, Any]] = []
    pull_to_local: List[Dict[str, Any]] = []

    for uid in sorted(set(loc_map) | set(rem_map)):
        le = loc_map.get(uid)
        re_ = rem_map.get(uid)
        if le and not re_:
            merged.append(le)
            push_to_remote.append(le)
        elif re_ and not le:
            merged.append(re_)
            pull_to_local.append(re_)
        elif le is not None and re_ is not None:
            # Beide UID-Karten muessen belegt sein (uid stammt aus der Vereinigung
            # beider Maps); die explizite Pruefung macht das gegenueber MyPy sichtbar.
            lu = str(le.get("updated_at") or "")
            ru = str(re_.get("updated_at") or "")
            if ru > lu:
                merged.append(re_)
                pull_to_local.append(re_)
            else:
                merged.append(le)
                if lu > ru:
                    push_to_remote.append(le)

    return {"merged": merged, "push_to_remote": push_to_remote, "pull_to_local": pull_to_local}


def schedule_focus_blocks(
    busy_events: List[Dict[str, Any]],
    deadlines: List[Dict[str, Any]],
    target_date: datetime.date,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
    block_hours: int = 2,
) -> List[Dict[str, Any]]:
    """Findet freie Deep-Work-Zeitfenster fuer dringende Kanban-Deadlines."""
    busy_intervals: List[tuple[datetime.datetime, datetime.datetime]] = []
    for ev in busy_events:
        try:
            s = datetime.datetime.fromisoformat(str(ev["start"]).replace("Z", "+00:00")).replace(tzinfo=None)
            e = datetime.datetime.fromisoformat(str(ev["end"]).replace("Z", "+00:00")).replace(tzinfo=None)
            busy_intervals.append((s, e))
        except Exception:
            continue

    blocks: List[Dict[str, Any]] = []
    cursor = datetime.datetime.combine(target_date, datetime.time(work_start_hour, 0))
    day_end = datetime.datetime.combine(target_date, datetime.time(work_end_hour, 0))

    for dl in deadlines:
        placed = False
        while cursor + datetime.timedelta(hours=block_hours) <= day_end:
            cand_end = cursor + datetime.timedelta(hours=block_hours)
            overlaps = any(not (cand_end <= bs or cursor >= be) for bs, be in busy_intervals)
            if not overlaps:
                blk = {
                    "uid": f"focus-{dl.get('id', 'task')}",
                    "title": f"Deep Work: {dl.get('title') or dl.get('id')}",
                    "start": cursor.isoformat(),
                    "end": cand_end.isoformat(),
                    "kind": "focus_blocker",
                }
                blocks.append(blk)
                busy_intervals.append((cursor, cand_end))
                cursor = cand_end
                placed = True
                break
            cursor += datetime.timedelta(minutes=30)
        if not placed:
            break
    return blocks

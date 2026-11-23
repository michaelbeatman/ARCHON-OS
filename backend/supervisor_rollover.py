# -*- coding: utf-8 -*-
"""
backend/supervisor_rollover.py
==============================
Laufzeit-Auflösung von Supervisoren aus ``config/org_hierarchy.json``.

Die Hierarchie ist die SSOT: explizites ``supervisor_id`` pro Node (falls
vorhanden) schlägt den ``links``-Eintrag (from -> to). Bei Ausfall eines
Supervisors wird die Eskalationskette nach oben gegangen (Rollover), ohne
die Konfiguration zu mutieren.
"""
from __future__ import annotations

import json
import os
import time
import threading
from typing import Dict, List, Optional, Set

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORG_PATH = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")

DEFAULT_APEX = "executive_decision_architect"
APEX_IDS = frozenset({"default", DEFAULT_APEX, "system_architect_orchestrator"})

_lock = threading.RLock()
_failed: Dict[str, str] = {}
# TTL pro Ausfall: ein fachlicher Fehler eines Sub-Agenten markierte frueher
# seinen Supervisor dauerhaft als ausgefallen (bis Neustart). Jetzt verfällt
# die Markierung nach 5 Minuten automatisch.
_FAILED_TTL_SECONDS = 300
_failed_at: Dict[str, float] = {}
_cache: Dict[str, object] = {"mtime": -1.0, "parents": {}, "nodes": {}}


def _load() -> tuple:
    """Liest die Hierarchie mtime-basiert gecacht (explizite links vor Tier-Rang)."""
    mtime = os.path.getmtime(ORG_PATH) if os.path.isfile(ORG_PATH) else -1.0
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["parents"], _cache["nodes"]  # type: ignore[return-value]
        parents: Dict[str, str] = {}
        nodes: Dict[str, dict] = {}
        if os.path.isfile(ORG_PATH):
            with open(ORG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            node_rows = data.get("nodes") or []
            nodes = {
                str(n.get("id") or ""): n
                for n in node_rows if isinstance(n, dict) and n.get("id")
            }
            for link in data.get("links") or []:
                if not isinstance(link, dict):
                    continue
                src = str(link.get("from") or "")
                dst = str(link.get("to") or "")
                if src and dst:
                    parents[dst] = src
        # Explizite supervisor_id-Felder haben Vorrang vor links.
        for aid, node in nodes.items():
            explicit = str(node.get("supervisor_id") or "").strip()
            if explicit:
                parents[aid] = explicit
        _cache["mtime"] = mtime
        _cache["parents"] = parents
        _cache["nodes"] = nodes
        return parents, nodes


def mark_agent_failed(agent_id: str, reason: str = "") -> None:
    """Markiert einen Agenten als ausgefallen (nur Laufzeit, keine Persistenz)."""
    with _lock:
        _failed[str(agent_id)] = str(reason or "unbekannt")
        _failed_at[str(agent_id)] = time.time()


def mark_agent_recovered(agent_id: str) -> None:
    with _lock:
        _failed.pop(str(agent_id), None)
        _failed_at.pop(str(agent_id), None)


def failed_agents() -> Dict[str, str]:
    with _lock:
        return dict(_failed)


def clear_state() -> None:
    """Nur für Tests: Ausfall-Registry leeren."""
    with _lock:
        _failed.clear()
        _failed_at.clear()


def escalation_chain(agent_id: str) -> List[str]:
    """Parent-Kette bis zum Apex (zyklensicher, max. 8 Sprünge)."""
    parents, _ = _load()
    chain: List[str] = []
    cur = str(agent_id)
    for _ in range(8):
        parent = parents.get(cur)
        if not parent or parent in chain or parent == cur:
            break
        chain.append(parent)
        cur = parent
    if not chain or chain[-1] not in APEX_IDS:
        chain.append(DEFAULT_APEX)
    return chain


def resolve_supervisor(agent_id: str, *, exclude: Optional[Set[str]] = None) -> str:
    """Aktueller Supervisor; überspringt ausgefallene/ausgeschlossene Kandidaten."""
    parents, nodes = _load()
    aid = str(agent_id)
    candidates: List[str] = []
    direct = str((nodes.get(aid) or {}).get("supervisor_id") or parents.get(aid) or "")
    if direct:
        candidates.append(direct)
    candidates.extend(c for c in escalation_chain(aid) if c not in candidates)
    with _lock:
        now = time.time()
        expired = [aid for aid, ts in _failed_at.items() if now - ts > _FAILED_TTL_SECONDS]
        for aid in expired:
            _failed.pop(aid, None)
            _failed_at.pop(aid, None)
        down = set(_failed)
    skip = set(exclude or set()) | down
    for cand in candidates:
        if cand and cand != aid and cand not in skip:
            return cand
    return DEFAULT_APEX


def on_supervisor_failure(
    agent_id: str, failed_supervisor: str, reason: str = ""
) -> Dict[str, object]:
    """Rollover nach Supervisor-Ausfall: neuen Supervisor + Kette melden."""
    failed_supervisor = str(failed_supervisor)
    mark_agent_failed(failed_supervisor, reason)
    new_supervisor = resolve_supervisor(agent_id, exclude={failed_supervisor})
    return {
        "agent_id": str(agent_id),
        "failed_supervisor": failed_supervisor,
        "new_supervisor": new_supervisor,
        "chain": escalation_chain(str(agent_id)),
        "reason": str(reason or ""),
    }

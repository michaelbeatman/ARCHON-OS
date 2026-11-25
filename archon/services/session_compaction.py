"""Session-Kompaktierung — Fachlogik ohne HTTP-Schicht (A2).

Aus ``archon/routers/context_meter.py`` hierher verlagert: ``backend/**`` darf
``archon.routers.*`` nicht importieren (D09/H-09-2). Der Router bleibt die
Fassade (RBAC, Request/Response) und importiert diese Symbole zurueck —
``archon.routers -> archon.services`` ist erlaubt, ``backend -> archon.routers``
nicht.

``archon/services/__init__.py``: „Ein Service kennt keine HTTP-Schicht: kein
Request, kein Body, keinen RBAC-Zaun." Diese Datei enthaelt entsprechend nur
DB-, Config- und Compactor-Logik.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from archon.core.state_db import _get_profile_state_db, _get_state_db


def _find_active_messages(session_id: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Liefert (db_key, messages) einer Session; db_key: 'root' | 'telegram_bot'."""
    with _get_state_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, role, content, timestamp, token_count FROM messages "
            "WHERE session_id = ? AND active = 1 ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        if rows:
            return "root", [dict(r) for r in rows]
    prof_conn = _get_profile_state_db("telegram_bot")
    if prof_conn:
        with prof_conn as pconn:
            pconn.row_factory = sqlite3.Row
            prows = pconn.execute(
                "SELECT id, role, content, timestamp, token_count FROM messages "
                "WHERE session_id = ? AND active = 1 ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            if prows:
                return "telegram_bot", [dict(r) for r in prows]
    return "root", []


def _compactor_keep_recent() -> int:
    try:
        from backend.autonomy_settings import get_module_config
        return int(get_module_config("context_compactor").get("keep_recent_turns", 4))
    except Exception:
        return 4


def compact_session_core(session_id: str) -> Dict[str, Any]:
    """Kompaktiert die aktive Historie einer Session (Kern, ohne RBAC).

    Wird von drei Stellen genutzt: manueller UI-Knopf, Auto-Hook im
    Chat-Flow (M73 Teil 3) und dem HITL-geschützten MCP-Werkzeug
    archon__compress_agent_context (M73 Teil 4).
    """
    from backend.context_compactor import context_compactor

    session_id = (session_id or "").strip()
    if not session_id:
        return {"compacted": False, "reason": "session_id fehlt", "session_id": session_id}

    db_key, msgs = _find_active_messages(session_id)
    non_system = [m for m in msgs if (m.get("role") or "").lower() != "system"]

    if len(non_system) < 6:
        return {"compacted": False, "reason": "Zu wenig Historie zum Verdichten.", "session_id": session_id}

    payload = [{"role": m.get("role") or "user", "content": m.get("content") or ""} for m in non_system]
    result = context_compactor.compact_messages(payload, force=True)

    if not result.get("compacted"):
        return {"compacted": False, "reason": result.get("reason", ""), "session_id": session_id}

    summary_text = str(result["messages"][0].get("content", "")) if result.get("messages") else ""
    # Die letzten keep_recent_turns bleiben aktiv (Compactor-Config), Rest wird deaktiviert.
    cfg_keep = _compactor_keep_recent()
    keep_ids = {m["id"] for m in non_system[-cfg_keep:] if m.get("id") is not None}
    deactivate_ids = [m["id"] for m in non_system if m.get("id") is not None and m["id"] not in keep_ids]

    target = _get_state_db if db_key == "root" else _get_profile_state_db("telegram_bot")
    with target() as conn:
        if deactivate_ids:
            chunk = 400
            for i in range(0, len(deactivate_ids), chunk):
                ids = deactivate_ids[i:i + chunk]
                q = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE messages SET active = 0, compacted = 1 WHERE id IN ({q})",
                    ids,
                )
        if summary_text:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, token_count, active, compacted) "
                "VALUES (?, 'system', ?, strftime('%s','now'), ?, 1, 1)",
                (session_id, summary_text, max(1, len(summary_text) // 4)),
            )
        conn.commit()

    try:
        from archon.core.runtime import logger
        logger.info(
            f"[Context-Meter] Session {session_id} kompaktiert: "
            f"{result.get('original_tokens')} -> {result.get('compacted_tokens')} Tokens "
            f"({result.get('saved_pct')}% gespart, {len(deactivate_ids)} Nachrichten verdichtet)"
        )
    except Exception as _exc:
        logger.debug("[context_meter] Ignorierte Ausnahme (Z.164): %s", _exc)

    return {
        "compacted": True,
        "session_id": session_id,
        "original_tokens": result.get("original_tokens"),
        "compacted_tokens": result.get("compacted_tokens"),
        "saved_pct": result.get("saved_pct"),
        "compacted_messages": len(deactivate_ids),
        "kept_recent": len(keep_ids),
    }


__all__ = ("compact_session_core", "_find_active_messages", "_compactor_keep_recent")

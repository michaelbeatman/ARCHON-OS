"""Session-Kompaktierung — Fachlogik ohne HTTP-Schicht (A2 + M99).

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
from typing import Any, Dict, List, Optional, Tuple

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


def _find_session_model(session_id: str) -> Optional[str]:
    """Liest das aktive Modell einer Session aus root oder telegram_bot state.db."""
    if not session_id:
        return None
    try:
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT model FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row and row["model"]:
                return str(row["model"]).strip() or None
    except Exception:
        pass
    try:
        prof_conn = _get_profile_state_db("telegram_bot")
        if prof_conn:
            with prof_conn as pconn:
                pconn.row_factory = sqlite3.Row
                prow = pconn.execute(
                    "SELECT model FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if prow and prow["model"]:
                    return str(prow["model"]).strip() or None
    except Exception:
        pass
    return None


def _compactor_keep_recent() -> int:
    try:
        from backend.autonomy_settings import get_module_config
        return max(1, min(100, int(get_module_config("context_compactor").get("keep_recent_turns", 4))))
    except Exception:
        return 4


def compact_session_core(session_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Kompaktiert die aktive Historie einer Session (Kern, ohne RBAC).

    Wird von drei Stellen genutzt: manueller UI-Knopf, Auto-Hook im
    Chat-Flow (M73 Teil 3) und dem HITL-geschützten MCP-Werkzeug
    archon__compress_agent_context (M73 Teil 4).
    """
    from backend.context_compactor import context_compactor, format_compaction_marker

    session_id = (session_id or "").strip()
    if not session_id:
        return {"compacted": False, "reason": "session_id fehlt", "session_id": session_id}

    resolved_model = (model or "").strip() or _find_session_model(session_id)
    db_key, msgs = _find_active_messages(session_id)
    non_system = [m for m in msgs if (m.get("role") or "").lower() != "system"]

    cfg_keep = _compactor_keep_recent()
    min_required = max(6, cfg_keep + 2)
    if len(non_system) < min_required:
        return {
            "compacted": False,
            "reason": f"Zu wenig Historie zum Verdichten ({len(non_system)} < {min_required}).",
            "session_id": session_id,
        }

    # M94-Verzahnung: session_id + message_id mitgeben, damit der Lossless-DAG
    # ueber mehrfache Kompaktierungen stabil unter session:<session_id> bleibt.
    payload = [
        {
            "role": m.get("role") or "user",
            "content": m.get("content") or "",
            "session_id": session_id,
            "message_id": m.get("id"),
        }
        for m in non_system
    ]
    result = context_compactor.compact_messages(
        payload,
        force=True,
        keep_recent_override=cfg_keep,
        model=resolved_model,
        session_id=session_id,
    )

    if not result.get("compacted"):
        return {"compacted": False, "reason": result.get("reason", ""), "session_id": session_id}

    raw_summary = str(result["messages"][0].get("content", "")) if result.get("messages") else ""
    keep_ids = {m["id"] for m in non_system[-cfg_keep:] if m.get("id") is not None}
    deactivate_ids = [m["id"] for m in non_system if m.get("id") is not None and m["id"] not in keep_ids]

    marker_line = format_compaction_marker(
        original_tokens=int(result.get("original_tokens") or 0),
        compacted_tokens=int(result.get("compacted_tokens") or 0),
        saved_pct=float(result.get("saved_pct") or 0.0),
        compacted_messages=len(deactivate_ids),
        kept_recent=len(keep_ids),
        max_context_tokens=int(result.get("max_context_tokens") or 32000),
        model=resolved_model,
    )
    summary_text = f"{marker_line}\n{raw_summary}" if raw_summary else marker_line

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

    saved_tokens = max(0, int(result.get("original_tokens") or 0) - int(result.get("compacted_tokens") or 0))
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
        "model": resolved_model,
        "max_context_tokens": result.get("max_context_tokens"),
        "original_tokens": result.get("original_tokens"),
        "compacted_tokens": result.get("compacted_tokens"),
        "saved_tokens": saved_tokens,
        "saved_pct": result.get("saved_pct"),
        "compacted_messages": len(deactivate_ids),
        "kept_recent": len(keep_ids),
        "compaction_marker": marker_line,
        "lossless_session_id": result.get("lossless_session_id"),
        "lossless_summary_id": result.get("lossless_summary_id"),
    }


__all__ = (
    "compact_session_core",
    "_find_active_messages",
    "_find_session_model",
    "_compactor_keep_recent",
)

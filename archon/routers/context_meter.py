"""Kontext-Meter & Session-Compaction fuer den Master-/Agenten-Chat.

Teil 1+2 des Kontext-Hygiene-Features (M73):
- GET  /api/chat/context-status  -> Fuellstand des Kontextfensters einer Session
- POST /api/chat/compact-session -> Kompaktiert die Session-Historie via ContextCompactor

Die token_count-Spalte der messages-Tabelle wird genutzt; fehlende Werte
werden mit der chars/4-Schaetzung des Compactors ergaenzt.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends as _ArchonDepends, HTTPException, Request
from pydantic import BaseModel

from archon.core.state_db import _get_profile_state_db, _get_state_db
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["context-meter"])

DEFAULT_MAX_CONTEXT_TOKENS = 32000


def _settings_max_context_tokens() -> int:
    try:
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "settings.json"))
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        agent = (cfg.get("guardian") or {}).get("agent") or {}
        return int(agent.get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS))
    except Exception:
        return DEFAULT_MAX_CONTEXT_TOKENS


def _tokens_of(content: Optional[str], token_count: Any) -> int:
    if isinstance(token_count, (int, float)) and token_count and token_count > 0:
        return int(token_count)
    return max(1, len(str(content or "")) // 4)


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


def _compacted_parts_count(session_id: str) -> int:
    """Zaehlt verdichtete Verlaufsteile einer Session (DB, nicht im Handler)."""
    try:
        with _get_state_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ? AND compacted = 1",
                (session_id,),
            ).fetchone()
            return int(row["c"]) if row else 0
    except Exception:
        return 0


@router.get("/api/chat/context-status")
def api_chat_context_status(session_id: str):
    """Fuellstand des Kontextfensters fuer die Kontext-Anzeige im Chat."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id fehlt")
    _, msgs = _find_active_messages(session_id)
    used = sum(_tokens_of(m.get("content"), m.get("token_count")) for m in msgs)
    compacted_hint = _compacted_parts_count(session_id)
    max_tokens = _settings_max_context_tokens()
    return {
        "session_id": session_id,
        "used_tokens": used,
        "max_context_tokens": max_tokens,
        "fill_pct": round(min(100.0, (used / max(1, max_tokens)) * 100.0), 1),
        "message_count": len(msgs),
        "compacted_parts": compacted_hint,
    }


class CompactSessionRequest(BaseModel):
    session_id: str


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
    except Exception:
        pass

    return {
        "compacted": True,
        "session_id": session_id,
        "original_tokens": result.get("original_tokens"),
        "compacted_tokens": result.get("compacted_tokens"),
        "saved_pct": result.get("saved_pct"),
        "compacted_messages": len(deactivate_ids),
        "kept_recent": len(keep_ids),
    }


@router.post("/api/chat/compact-session")
def api_chat_compact_session(request: Request, req: CompactSessionRequest):
    """Kompaktiert die aktive Historie einer Chat-Session (manuell aus der UI)."""
    require_admin_or_503(request)
    session_id = (req.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id fehlt")
    return compact_session_core(session_id)


def _compactor_keep_recent() -> int:
    try:
        from backend.autonomy_settings import get_module_config
        return int(get_module_config("context_compactor").get("keep_recent_turns", 4))
    except Exception:
        return 4


def maybe_auto_compact_session(session_id: str) -> Dict[str, Any]:
    """M73 Teil 3: Auto-Kompaktierung vor jedem Chat-Versand.

    Greift nur, wenn der Compactor aktiv ist und die Session-Historie
    mehr als `auto_compact_pct` (Standard 85 %) des Kontextfensters
    belegt. Kompaktiert niemals frische Sessions (< 6 Nachrichten).
    """
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("context_compactor")
    except Exception:
        cfg = {}
    if not bool((cfg or {}).get("enabled", True)):
        return {"compacted": False, "reason": "Compactor deaktiviert"}
    auto_pct = float((cfg or {}).get("auto_compact_pct", 85))
    min_msgs = int((cfg or {}).get("auto_compact_min_messages", 24))

    status = api_chat_context_status_impl(session_id)
    if status["fill_pct"] < auto_pct or status["message_count"] < min_msgs:
        return {
            "compacted": False,
            "reason": (
                f"Fuellstand {status['fill_pct']}% unter Schwellwert {auto_pct}% "
                f"oder {status['message_count']} < {min_msgs} Nachrichten"
            ),
        }
    return compact_session_core(session_id)


def api_chat_context_status_impl(session_id: str) -> Dict[str, Any]:
    """Status-Logik ohne FastAPI-Wrapper (fuer Auto-Hook und Tests)."""
    _, msgs = _find_active_messages(session_id)
    used = sum(_tokens_of(m.get("content"), m.get("token_count")) for m in msgs)
    max_tokens = _settings_max_context_tokens()
    return {
        "session_id": session_id,
        "used_tokens": used,
        "max_context_tokens": max_tokens,
        "fill_pct": round(min(100.0, (used / max(1, max_tokens)) * 100.0), 1),
        "message_count": len(msgs),
    }
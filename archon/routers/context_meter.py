"""Kontext-Meter & Session-Compaction fuer den Master-/Agenten-Chat.

Teil 1+2 des Kontext-Hygiene-Features (M73) + M99 (modell-dynamische Fenster):
- GET  /api/chat/context-status  -> Fuellstand des Kontextfensters einer Session
- POST /api/chat/compact-session -> Kompaktiert die Session-Historie via ContextCompactor

Die token_count-Spalte der messages-Tabelle wird genutzt; fehlende Werte
werden mit der chars/4-Schaetzung des Compactors ergaenzt.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi import Depends as _ArchonDepends
from pydantic import BaseModel

from archon.core.state_db import _get_state_db
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503

# A2: Kompaktierungs-Logik liegt in der Service-Schicht (kein HTTP im Service).
from archon.services.session_compaction import (
    _find_active_messages,
    _find_session_model,
    compact_session_core,
)
from backend.context_compactor import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    resolve_effective_compaction_params,
    resolve_model_context_window,
)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["context-meter"])


def _settings_max_context_tokens_override() -> Optional[int]:
    """Liest optionalen Fallback aus settings.json (nur fuer unbekannte/lokale Modelle)."""
    try:
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "settings.json"))
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        agent = (cfg.get("guardian") or {}).get("agent") or {}
        raw = agent.get("max_context_tokens")
        if raw is not None and not isinstance(raw, bool):
            val = int(raw)
            if val > 0:
                return val
    except Exception:
        pass
    return None


def _settings_max_context_tokens(model: Optional[str] = None) -> int:
    """Dynamisches Kontextfenster fuer das gegebene Modell (Fallback: Override oder 32k)."""
    return resolve_model_context_window(
        model,
        configured_override=_settings_max_context_tokens_override(),
    )


def _resolve_session_context_window(
    session_id: str,
    model: Optional[str] = None,
) -> Tuple[Optional[str], int]:
    resolved_model = (model or "").strip() or _find_session_model(session_id)
    max_tokens = _settings_max_context_tokens(resolved_model)
    return resolved_model, max_tokens


def _tokens_of(content: Optional[str], token_count: Any) -> int:
    if isinstance(token_count, (int, float)) and token_count and token_count > 0:
        return int(token_count)
    return max(1, len(str(content or "")) // 4)


def _compactor_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("context_compactor")
    except Exception:
        return {}


# A2: _find_active_messages liegt in archon.services.session_compaction und
# wird oben importiert (Router-Status, Auto-Hook und Kompaktierung nutzen es).


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
def api_chat_context_status(session_id: str, model: Optional[str] = None):
    """Fuellstand des Kontextfensters fuer die Kontext-Anzeige im Chat."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id fehlt")
    status = api_chat_context_status_impl(session_id, model=model)
    status["compacted_parts"] = _compacted_parts_count(session_id)
    return status


class CompactSessionRequest(BaseModel):
    session_id: str
    model: Optional[str] = None


# A2: compact_session_core liegt in archon.services.session_compaction und
# wird oben importiert. Der Router behaelt nur die HTTP-Fassade (RBAC/Request).


@router.post("/api/chat/compact-session")
def api_chat_compact_session(request: Request, req: CompactSessionRequest):
    """Kompaktiert die aktive Historie einer Chat-Session (manuell aus der UI)."""
    require_admin_or_503(request)
    session_id = (req.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id fehlt")
    return compact_session_core(session_id, model=req.model)


# A2: _compactor_keep_recent liegt in archon.services.session_compaction.


def maybe_auto_compact_session(
    session_id: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """M73 Teil 3 + M99: Auto-Kompaktierung vor jedem Chat-Versand.

    Greift nur, wenn der Compactor aktiv ist und die Session-Historie
    mehr als `auto_compact_pct` (Standard 85 %) des modell-dynamischen
    Kontextfensters belegt. Kompaktiert niemals frische Sessions.
    """
    cfg = _compactor_cfg()
    status = api_chat_context_status_impl(session_id, model=model)
    params = resolve_effective_compaction_params(cfg, status["max_context_tokens"])

    if not params["enabled"]:
        return {"compacted": False, "reason": "Compactor deaktiviert"}

    auto_pct = float(params["auto_compact_pct"])
    keep_recent = int(params["keep_recent_turns"])
    min_msgs = max(
        int((cfg or {}).get("auto_compact_min_messages", 24)),
        keep_recent + 2,
    )

    if status["fill_pct"] < auto_pct or status["message_count"] < min_msgs:
        return {
            "compacted": False,
            "reason": (
                f"Fuellstand {status['fill_pct']}% unter Schwellwert {auto_pct}% "
                f"oder {status['message_count']} < {min_msgs} Nachrichten"
            ),
            "max_context_tokens": status["max_context_tokens"],
            "model": status["model"],
        }
    return compact_session_core(session_id, model=status["model"])


def api_chat_context_status_impl(
    session_id: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Status-Logik ohne FastAPI-Wrapper (fuer Auto-Hook und Tests)."""
    _, msgs = _find_active_messages(session_id)
    used = sum(_tokens_of(m.get("content"), m.get("token_count")) for m in msgs)
    resolved_model, max_tokens = _resolve_session_context_window(session_id, model=model)
    params = resolve_effective_compaction_params(_compactor_cfg(), max_tokens)
    return {
        "session_id": session_id,
        "model": resolved_model,
        "used_tokens": used,
        "max_context_tokens": max_tokens,
        "fill_pct": round(min(100.0, (used / max(1, max_tokens)) * 100.0), 1),
        "message_count": len(msgs),
        "auto_compact_pct": params["auto_compact_pct"],
        "trigger_token_threshold": params["trigger_token_threshold"],
        "effective_threshold": params["effective_threshold"],
        "keep_recent_turns": params["keep_recent_turns"],
    }


__all__ = (
    "router",
    "DEFAULT_MAX_CONTEXT_TOKENS",
    "CompactSessionRequest",
    "api_chat_context_status",
    "api_chat_context_status_impl",
    "api_chat_compact_session",
    "maybe_auto_compact_session",
)

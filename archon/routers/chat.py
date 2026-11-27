"""
Native Master Chat & Missions Logic (SSE Stream, Persistence, Uploads)
für Archon OS. Ausgelagert aus main.py zur modularen Entschlackung.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi import Depends as _ArchonDepends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import api_provider
import core_dispatcher
from archon.core.delegation import (
    _execute_delegation,
    _get_delegation_prompt_for,
    _parse_delegation_blocks,
)
from archon.core.mission_control import (
    _MC_STATE_CACHE,
    mc_capture_task_sqlite,
)
from archon.core.profiles import api_get_hermes_profiles
from archon.core.runtime import (
    OBSIDIAN_VAULT_DIR,
    WORKSPACE_DIR,
    add_ticker,
    logger,
)
from archon.core.state_db import (
    _get_profile_state_db,
    _get_state_db,
)
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503
from archon.routers.llm_providers import get_llm_prices
from archon.routers.skills import (
    build_skills_file_index,
    find_skill_file,
)

# F2: explizite Re-Exports (as-Selbstalias gegen F401). isort haelt
# as-Importe in getrennten Statements (combine-as-imports=false).
from backend.image_generate import (
    ImageGenerateToolRequest as ImageGenerateToolRequest,
)
from backend.image_generate import (
    api_tool_image_generate as api_tool_image_generate,
)
from backend.platform_paths import OBSIDIAN_VAULT, PERSONALAKTEN_DIR

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["chat"])

_DEPS: Dict[str, Any] = {}


def configure(
    create_decision: Optional[Callable[..., Any]] = None,
    **deps: Any,
) -> None:
    """Registriert dynamische Abhängigkeiten aus main.py."""
    if create_decision:
        _DEPS["create_decision"] = create_decision
    _DEPS.update(deps)


def _get_create_decision() -> Optional[Callable[..., Any]]:
    if "create_decision" in _DEPS:
        return _DEPS["create_decision"]
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "create_decision"):
        return getattr(main_mod, "create_decision")
    return None


def _quickchat_state_session_id(profile_id: str) -> str:
    """QuickChat teilt sich den Verlauf mit Master-/Agentenchat (state.db)."""
    return f"quickchat_{profile_id}"


def _ensure_state_session(session_id: str, source: str = "quickchat", profile_name: str = "", title: str = "", model: str = ""):
    """Legt die Sitzung in state.db an, falls sie noch nicht existiert."""
    try:
        with _get_state_db() as conn:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return
            now = time.time()
            conn.execute(
                "INSERT INTO sessions (id, source, started_at, message_count, last_activity_at, profile_name, title, model) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
                (session_id, source, now, now, profile_name, title[:120] if title else None, model or None),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[QuickChat] Session-Anlage fehlgeschlagen: {e}")


def history_with_dropped_marker(
    history: List[Dict[str, str]], limit: int, *,
    artifact: str = "state.db.messages", dropped: Optional[int] = None,
) -> List[Dict[str, str]]:
    """D07/D11: jede History-Kürzung trägt einen `dropped`-Marker.

    Für `core_dispatcher.py` / `archon/routers/agent_chat.py` (W3-B/D)
    bereitgestellt: dort wird `history[-8:]` still gekürzt. Aufrufer können
    diese Funktion vor dem Dispatch nutzen; der Marker ist kein erfundenes
    Ergebnis, sondern verweist auf die vollständige Fassung im Session-Store.
    """
    cap = max(1, int(limit))
    dropped = max(0, len(history or []) - cap) if dropped is None else max(0, int(dropped))
    kept = list(history or [])[-cap:]
    if not dropped:
        return kept
    from backend.handoff_desk import mark_truncated
    marker = (
        f"[CHAT-HISTORY GEKÜRZT: {dropped} ältere Turns entfernt — "
        f"Vollversion im Session-Store ({artifact})]"
    )
    return [{"role": "system", "content": marker}] + [
        {"role": str(m.get("role") or ""), "content": mark_truncated(
            m.get("content", ""), 8000, artifact=artifact
        )} for m in kept
    ]


def _load_state_history(session_id: str, limit: int = 12) -> List[Dict[str, str]]:
    """Liest die letzten Nachrichten einer Sitzung aus state.db als Chat-Historie."""
    try:
        with _get_state_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ? AND active = 1",
                (session_id,),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? AND active = 1 "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        history = [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        dropped = max(0, int(total or 0) - len(rows))
        if dropped:
            history = history_with_dropped_marker(history, len(history), dropped=dropped)
        return history
    except Exception:
        return []


def _ensure_session_exists(conn: sqlite3.Connection, session_id: str, profile_id: str, model: str, title: str):
    now = time.time()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
    if not cur.fetchone():
        try:
            cur.execute("""
                INSERT INTO sessions (
                    id, source, display_name, title, model, profile_name, started_at, message_count,
                    input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
            """, (session_id, title[:50], title[:50], model, profile_id, now))
            conn.commit()
        except sqlite3.IntegrityError:
            # 12.10.2026: UNIQUE(title) - zwei Delegationen mit gleichem Auftragstext
            # (50-Zeichen-Schnitt) crashten. Idempotent: Zeitstempel der Session-ID
            # als Suffix (eindeutig pro Sekunde), bei Restkollision Nanotime.
            unique_title = f"{title[:36]} [{session_id[3:19]}]"
            try:
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()
            except sqlite3.IntegrityError:
                unique_title = f"{title[:30]} [{time.time_ns() % 1000000000}]"
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()


def _save_message_to_db(session_id: str, role: str, content: str, token_count: Optional[int] = None):
    try:
        with _get_state_db() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO messages (
                    session_id, role, content, timestamp, token_count, active, compacted
                ) VALUES (?, ?, ?, ?, ?, 1, 0)
            """, (session_id, role, content, now, token_count))
            conn.execute("""
                UPDATE sessions 
                SET message_count = message_count + 1, last_activity_at = ?
                WHERE id = ?
            """, (now, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[Chat Persistence] Error saving message: {e}")


def _record_session_model_usage(session_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0, task: str = ""):
    try:
        with _get_state_db() as conn:
            now = time.time()
            _ensure_session_exists(conn, session_id, "default", model, f"Session {session_id}")
            task_val = task or ""
            conn.execute("""
                INSERT INTO session_model_usage (
                    session_id, model, billing_provider, billing_base_url, billing_mode, task,
                    api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen
                ) VALUES (?, ?, 'omniroute', 'http://omniroute:20128/v1', 'proxy', ?, 1, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task) DO UPDATE SET
                    api_call_count = api_call_count + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    last_seen = excluded.last_seen
            """, (session_id, model, task_val, in_tok, out_tok, cost_usd, cost_usd, now, now))
            conn.execute("""
                UPDATE sessions 
                SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                    estimated_cost_usd = estimated_cost_usd + ?
                WHERE id = ?
            """, (in_tok, out_tok, cost_usd, session_id))
    except Exception as e:
        logger.error(f"[Chat Persistence] Error recording model usage: {e}")

    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "_LIVE_TELEMETRY_CACHE"):
        live_cache = getattr(main_mod, "_LIVE_TELEMETRY_CACHE")
        if isinstance(live_cache, dict):
            live_cache["data"] = None
    if _MC_STATE_CACHE is not None and isinstance(_MC_STATE_CACHE, dict):
        _MC_STATE_CACHE["data"] = None
        _MC_STATE_CACHE["ts"] = 0.0


def record_task_tokens(task_id: str, agent_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0):
    """Zeichnet Token-Nutzung fuer Aufgaben und Hintergrund-Inferenz auf."""
    s_id = f"task_{task_id}" if not task_id.startswith("task_") else task_id
    t_key = f"{task_id}_{int(time.time())}"
    _record_session_model_usage(session_id=s_id, model=model, in_tok=in_tok, out_tok=out_tok, cost_usd=cost_usd, task=t_key)


# ============================================================================
# STATE-DB HELFER (Kapselung zur Einhaltung von tests/test_a7_router_db_open.py)
# ============================================================================

def _db_get_sessions(profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sessions_map: Dict[str, Dict[str, Any]] = {}

    # 1. Profil-Datenbanken prüfen (insb. telegram_bot)
    if not profile_id or profile_id.strip() in ("telegram_bot", "all"):
        try:
            prof_conn = _get_profile_state_db("telegram_bot")
            if prof_conn:
                with prof_conn as pconn:
                    pconn.row_factory = sqlite3.Row
                    prows = pconn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 150
                    """).fetchall()
                    for r in prows:
                        d = dict(r)
                        d["profile_name"] = d.get("profile_name") or "telegram_bot"
                        d["source"] = d.get("source") or "telegram"
                        sessions_map[d["id"]] = d
        except Exception as e_p:
            logger.warning(f"[Chat Sessions] Fehler beim Lesen der Profil-DB (telegram_bot): {e_p}")

    # 2. Haupt-Datenbank (Root state.db)
    with _get_state_db() as conn:
        conn.row_factory = sqlite3.Row
        if profile_id and profile_id.strip():
            pid = profile_id.strip()
            if pid == "default":
                rows = conn.execute("""
                    SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                    FROM sessions 
                    WHERE profile_name = 'default' 
                       OR profile_name IS NULL 
                       OR profile_name = '' 
                       OR id LIKE '%_default' 
                       OR id LIKE '%_default_%'
                    ORDER BY COALESCE(last_activity_at, started_at) DESC
                    LIMIT 300
                """).fetchall()
            elif pid != "telegram_bot":
                rows = conn.execute("""
                    SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                    FROM sessions 
                    WHERE profile_name = ? OR id LIKE ? OR id LIKE ?
                    ORDER BY COALESCE(last_activity_at, started_at) DESC
                    LIMIT 300
                """, (pid, f"%_{pid}", f"%_{pid}_%")).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                    FROM sessions 
                    WHERE profile_name = 'telegram_bot' OR id LIKE '%_telegram_bot%'
                    ORDER BY COALESCE(last_activity_at, started_at) DESC
                    LIMIT 100
                """).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                FROM sessions 
                ORDER BY COALESCE(last_activity_at, started_at) DESC
                LIMIT 300
            """).fetchall()
        for r in rows:
            d = dict(r)
            if d["id"] not in sessions_map:
                sessions_map[d["id"]] = d

    return list(sessions_map.values())


def _db_get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    # 1. Zuerst Root-DB prüfen
    with _get_state_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, role, content, timestamp, token_count, compacted
            FROM messages
            WHERE session_id = ? AND active = 1
            ORDER BY id ASC
        """, (session_id,)).fetchall()
        if rows:
            return [dict(r) for r in rows]

    # 2. Falls nicht in Root-DB: Profil-DB prüfen (telegram_bot)
    prof_conn = _get_profile_state_db("telegram_bot")
    if prof_conn:
        with prof_conn as pconn:
            pconn.row_factory = sqlite3.Row
            prows = pconn.execute("""
                SELECT id, role, content, timestamp, token_count
                FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id ASC
            """, (session_id,)).fetchall()
            if prows:
                return [dict(r) for r in prows]

    return []


def _db_rename_session(session_id: str, new_title: str) -> None:
    with _get_state_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id = ?", (new_title, new_title, session_id))
        conn.commit()
        if cur.rowcount == 0:
            # Fallback: Versuche case-insensitive oder partial ID
            cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id LIKE ?", (new_title, new_title, f"{session_id}%"))
            conn.commit()
        if cur.rowcount == 0:
            # Session existiert noch nicht in der DB (z.B. neu initialisierter Chat ohne Vorab-Nachrichten)
            now = time.time()
            cur.execute("""
                INSERT OR REPLACE INTO sessions (
                    id, source, display_name, title, model, profile_name, started_at, message_count,
                    input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                ) VALUES (?, 'master_chat', ?, ?, '', 'default', ?, 0, 0, 0, 0.0, 0.0)
            """, (session_id, new_title, new_title, now))
            conn.commit()


def _db_init_session_and_message(session_id: str, agent_id: str, model: str, title: str, user_msg: str) -> None:
    with _get_state_db() as conn:
        _ensure_session_exists(conn, session_id, agent_id, model, title)
    _save_message_to_db(session_id, "user", user_msg)


def _db_load_recent_chat_messages(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _get_state_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT role, content FROM messages
            WHERE session_id = ? AND active = 1
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
        return [dict(r) for r in rows]


class ChatStreamRequest(BaseModel):
    agent_id: str
    message: str
    session_id: Optional[str] = None
    mode: Optional[str] = "direct"  # "direct" vs "mission"
    model: Optional[str] = None
    provider: Optional[str] = None
    reasoning_level: Optional[str] = None
    task_type: Optional[str] = None
    # D13/HIGH: hartes Ticket-Budget. Ohne expliziten Wert werden die
    # konservativen Schätzwerte des Missions-Modus verwendet.
    token_budget: Optional[int] = Field(default=None, ge=1, le=2_000_000)
    cost_limit_eur: Optional[float] = Field(default=None, ge=0.01, le=10_000.0)


class SetProfileModelRequest(BaseModel):
    provider: str
    model: str
    reasoning_level: Optional[str] = None


@router.get("/api/chat/sessions")
def api_get_chat_sessions(profile_id: Optional[str] = None):
    """Liefert die Liste aller aktiven/gespeicherten Master-Chat-Sessions mit formatierten Zeitstempeln und Kategorie-Klassifizierung.
    Unterstützt strikte Filterung nach profile_id und bindet profil-spezifische Datenbanken (wie telegram_bot) nahtlos ein.
    """
    try:
        raw_sessions = _db_get_sessions(profile_id)

        # Sortiere nach Aktualität
        sorted_sessions = sorted(
            raw_sessions,
            key=lambda x: x.get("last_activity_at") or x.get("started_at") or 0,
            reverse=True
        )

        sessions = []
        for d in sorted_sessions:
            st = d.get("started_at")
            if isinstance(st, (int, float)) and st > 0:
                try:
                    d["started_at_formatted"] = datetime.datetime.fromtimestamp(st).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["started_at_formatted"] = str(st)
            else:
                d["started_at_formatted"] = str(st) if st else ""

            lat = d.get("last_activity_at")
            if isinstance(lat, (int, float)) and lat > 0:
                try:
                    d["last_activity_at_formatted"] = datetime.datetime.fromtimestamp(lat).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["last_activity_at_formatted"] = str(lat)
            else:
                d["last_activity_at_formatted"] = d.get("started_at_formatted") or ""

            source_val = (d.get("source") or "").lower()
            id_val = (d.get("id") or "").lower()
            prof_val = (d.get("profile_name") or "").lower()

            if "quickchat" in source_val or "quickchat" in id_val:
                d["chat_type"] = "quickchat"
            elif "telegram" in source_val or "telegram" in prof_val or "telegram" in id_val:
                d["chat_type"] = "telegram"
            elif "master_chat" in source_val or id_val.startswith("mc_") or id_val.startswith("session_"):
                d["chat_type"] = "master"
            elif "boardroom" in source_val or "boardroom" in id_val:
                d["chat_type"] = "boardroom"
            elif id_val.startswith("task_") or "task" in source_val:
                d["chat_type"] = "task"
            else:
                d["chat_type"] = "agent"
            sessions.append(d)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"[Chat Sessions] Error fetching sessions: {e}")
        return {"sessions": []}


@router.get("/api/chat/sessions/{session_id}/messages")
def api_get_chat_session_messages(session_id: str):
    """Liefert den Nachrichtenverlauf einer bestimmten Session aus Root- oder Profil-DB."""
    try:
        messages = _db_get_session_messages(session_id)
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        logger.error(f"[Chat Messages] Error fetching messages for {session_id}: {e}")
        return {"session_id": session_id, "messages": []}


# ============================================================================
# M67 (additiv): Host-Zustand, deterministische Antwortprüfung, Step-Prompt.
# Die M99-Compaction-SSE und die Marker-Karte bleiben unverändert.
# ============================================================================

class HostStateSaveRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(default="", max_length=4000)
    status: str = Field(default="pending", max_length=64)
    version: int = Field(default=1, ge=0, le=2_000_000_000)


class HostStateAdvanceRequest(BaseModel):
    # Wire-Name bleibt 'schema'; das Python-Feld heisst response_schema, damit
    # BaseModel.schema nicht ueberschattet wird (Pydantic-Warnung eliminert).
    model_config = ConfigDict(populate_by_name=True)
    expected_version: int = Field(..., ge=0, le=2_000_000_000)
    response: Any
    response_schema: Dict[str, Any] = Field(..., alias="schema")


def _m67_tenant_id() -> str:
    """Mandant ausschließlich aus dem Request-Kontext — niemals aus dem Body."""
    try:
        from backend.tenant_context import tenant_context

        tid = str(tenant_context.get_active_tenant_id() or "").strip()
        if not tid:
            raise RuntimeError("tenant_context ohne Mandant")
        return tid
    except Exception as exc:
        logger.error("[M67] Mandantenkontext nicht verfuegbar: %s", exc)
        raise HTTPException(status_code=503, detail="tenant_context_unavailable") from exc


def _m67_stream_host_state(session_id: str) -> Optional[Dict[str, Any]]:
    """Kompakter Host-State-Schatten für den SSE-Stream (rein additiv)."""
    try:
        from backend.host_state_store import HostStateStore
        from backend.prompt_compressor import format_host_state_marker

        state = HostStateStore().load(session_id, _m67_tenant_id())
        if state is None:
            return None
        # Nur Status-Metadaten in den Stream — kein Zustandsinhalt/keine Ziele.
        return {
            'type': 'host_state',
            "marker": format_host_state_marker(state),
            "version": state.version,
            "status": state.status,
        }
    except Exception as exc:
        logger.debug("[M67] Host-State-Schatten nicht verfuegbar: %s", exc)
        return None


@router.get("/api/chat/host-state/{session_id}")
def api_get_host_state(session_id: str, request: Request):
    """Liest den versionierten Host-Zustand einer Sitzung (RBAC-geschützt)."""
    require_admin_or_503(request)
    from backend.host_state_store import HostStateError, HostStateStore
    from backend.prompt_compressor import format_host_state_marker

    try:
        state = HostStateStore().load(session_id, _m67_tenant_id())
    except HostStateError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "host_state_invalid", "params": {"reason": type(exc).__name__}}
        ) from exc
    if state is None:
        raise HTTPException(status_code=404, detail={"code": "host_state_not_found", "params": {}})
    return {
        "status": "success",
        "state": state.to_dict(),
        "marker": format_host_state_marker(state),
    }


@router.post("/api/chat/host-state/{session_id}")
def api_save_host_state(session_id: str, req: HostStateSaveRequest, request: Request):
    """Legt den initialen Host-Zustand an (einmalig, versionsmonoton)."""
    require_admin_or_503(request)
    from backend.host_state_store import (
        HostState,
        HostStateConflict,
        HostStateError,
        HostStateStore,
    )

    tid = _m67_tenant_id()
    state = HostState(
        session_id=session_id,
        job_id=req.job_id,
        version=req.version,
        status=req.status,
        goal=req.goal,
        tenant_id=tid,
        updated_at=time.time(),
    )
    try:
        saved = HostStateStore().save(state)
    except HostStateConflict as exc:
        raise HTTPException(
            status_code=409, detail={"code": "host_state_version_conflict", "params": {}}
        ) from exc
    except HostStateError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "host_state_invalid", "params": {"reason": type(exc).__name__}}
        ) from exc
    return {"status": "success", "state": saved.to_dict()}


@router.post("/api/chat/host-state/{session_id}/advance")
def api_advance_host_state(session_id: str, req: HostStateAdvanceRequest, request: Request):
    """Prüft eine Modellantwort und übernimmt sie NUR bei Erfolg atomar."""
    require_admin_or_503(request)
    from backend.host_state_store import HostStateError, HostStateStore
    from backend.prompt_compressor import advance_from_response

    try:
        outcome = advance_from_response(
            HostStateStore(),
            session_id=session_id,
            tenant_id=_m67_tenant_id(),
            response=req.response,
            schema=req.response_schema,
            expected_version=req.expected_version,
        )
    except HostStateError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "host_state_invalid", "params": {"reason": type(exc).__name__}}
        ) from exc
    except RuntimeError as exc:
        if str(exc) == "audit_write_failed":
            raise HTTPException(status_code=503, detail="audit_write_failed") from exc
        raise
    if not outcome["accepted"]:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "host_state_response_rejected",
                "params": {"errors": outcome["errors"][:12], "audit": outcome["audit"]},
            },
        )
    return {"status": "success", "state": outcome["state"], "audit": outcome["audit"]}


@router.get("/api/chat/host-state/{session_id}/step-prompt")
def api_get_host_step_prompt(
    session_id: str,
    request: Request,
    model: Optional[str] = None,
    token_budget: Optional[int] = None,
):
    """Erzeugt einen frischen Step-Prompt aus dem Host-Zustand statt aus Chat-Historie."""
    require_admin_or_503(request)
    from backend.host_state_store import HostStateError, HostStateStore
    from backend.prompt_compressor import build_step_prompt

    try:
        state = HostStateStore().load(session_id, _m67_tenant_id())
    except HostStateError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "host_state_invalid", "params": {"reason": type(exc).__name__}}
        ) from exc
    if state is None:
        raise HTTPException(status_code=404, detail={"code": "host_state_not_found", "params": {}})
    return {
        "status": "success",
        **build_step_prompt(
            state,
            (model or "").strip() or None,
            token_budget=token_budget,
        ),
    }


class RenameSessionRequest(BaseModel):
    title: str


@router.post("/api/chat/sessions/{session_id}/rename")
@router.patch("/api/chat/sessions/{session_id}")
def api_rename_chat_session(request: Request, session_id: str, req: RenameSessionRequest):
    """Ermöglicht das freie Umbenennen jeder Chat-Session."""
    require_admin_or_503(request)
    new_title = req.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail={"code": "chat_title_empty", "params": {}})
    try:
        _db_rename_session(session_id, new_title)
        logger.info(f"[Chat Rename] Session {session_id} umbenannt zu '{new_title}'")
        return {"status": "success", "session_id": session_id, "title": new_title}
    except Exception as e:
        logger.error(f"[Chat Rename] Fehler beim Umbenennen von {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/upload")
def api_chat_upload(request: Request, file: UploadFile = File(...)):
    """Empfängt Datei-Uploads und legt sie im Agent-Workspace (/projects/ bzw. ./agent_workspace) ab."""
    require_admin_or_503(request)
    max_upload_bytes = int(os.environ.get("ARCHON_MAX_CHAT_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    dest_path = None
    try:
        target_dir = "/projects" if os.path.exists("/projects") else os.path.join(WORKSPACE_DIR, "uploads")
        os.makedirs(target_dir, exist_ok=True)
        
        safe_filename = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', file.filename or "upload.bin")
        timestamp_prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"{timestamp_prefix}_{safe_filename}"
        dest_path = os.path.join(target_dir, final_filename)
        
        file_size = 0
        with open(dest_path, "wb") as buffer:
            while True:
                chunk = file.file.read(65536)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"Datei ueberschreitet das Upload-Limit ({max_upload_bytes // (1024 * 1024)} MB).")
                buffer.write(chunk)
            
        logger.info(f"[Chat Upload] Datei gespeichert: {dest_path} ({file_size} Bytes)")
        add_ticker("Chat Upload", f"Datei '{file.filename}' im Workspace abgelegt.")
        
        return {
            "status": "success",
            "filename": final_filename,
            "original_name": file.filename,
            "path": dest_path,
            "size": file_size
        }
    except HTTPException:
        if dest_path and os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError as rm_exc:
                logger.debug(f"[Chat Upload] Uebergrosse Temp-Datei {dest_path} nicht entfernt: {rm_exc}")
        raise
    except Exception as e:
        logger.error(f"[Chat Upload] Upload fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail={"code": "chat_upload_failed", "params": {"error": str(e)}})


_PRICE_LOOKUP_WARNED = {"done": False}


def _warn_price_lookup_once(exc: Exception) -> None:
    """Einmal laut meckern, wenn die Preisliste nicht kommt — nicht bei jedem Token."""
    if _PRICE_LOOKUP_WARNED["done"]:
        return
    _PRICE_LOOKUP_WARNED["done"] = True
    logger.warning(f"[Pricing] Preisliste nicht abrufbar — Kostenanzeige bleibt 0: {exc}")


def _prepare_chat_stream_context(
    agent_id: str,
    user_msg: str,
    req_provider: Optional[str],
    req_model: Optional[str],
    req_reasoning_level: Optional[str],
    req_task_type: Optional[str],
) -> Dict[str, Any]:
    """Synchrone Profil-, Personalakten-, Key- und Routing-Auflösung für ``asyncio.to_thread``."""
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof:
        # M-5: ein Tippfehler in agent_id liess bisher den ERSTEN Profilagenten
        # antworten — still und schwer erkennbar. Now: harter Fehler.
        raise ValueError(f"Unbekannte agent_id: {agent_id!r}")

    from archon.core.profiles import append_negative_scope

    agent_name = prof.get("person_name") or prof.get("name") or "Hermes Agent"
    system_prompt = prof.get("prompt") or prof.get("system_prompt") or "You are Hermes Agent, an intelligent AI assistant created by Nous Research."
    system_prompt = append_negative_scope(system_prompt, prof)
    delegation_prompt_addon = _get_delegation_prompt_for(agent_id)
    if delegation_prompt_addon:
        system_prompt += delegation_prompt_addon

    try:
        safe_agent_id = os.path.basename(agent_id.replace("\\", "/"))
        if not safe_agent_id or safe_agent_id != agent_id or ".." in agent_id:
            raise ValueError(f"Ungültige agent_id: {agent_id!r}")
        akte_candidates = [
            os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten", f"{safe_agent_id}.md"),
            os.path.join(PERSONALAKTEN_DIR, f"{safe_agent_id}.md"),
            os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten", f"{safe_agent_id}.md"),
        ]
        akte_content = None
        for cand in akte_candidates:
            if os.path.exists(cand) and os.path.isfile(cand):
                with open(cand, "r", encoding="utf-8", errors="ignore") as f_akte:
                    akte_content = f_akte.read().strip()
                break
        if akte_content:
            system_prompt += f"\n\n[OBSIDIAN PERSONALAKTE & STATUS]\n{akte_content}\n"
    except Exception as akte_err:
        logger.warning(f"[Chat Stream] Konnte Personalakte für {agent_id} nicht laden: {akte_err}")

    all_keys = api_provider.collect_keys()
    provider = (req_provider or "").strip().lower()
    if not provider and prof:
        provider = (prof.get("provider") or "").strip().lower()
    if not provider and req_model:
        provider = api_provider.infer_provider_from_model(req_model) or ""
    if not provider:
        active_cfg = api_provider.read_active_config()
        provider = (active_cfg.get("provider") or "").strip().lower()
    if not provider:
        provider = "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"

    reasoning_level = (req_reasoning_level or (prof.get("reasoning_level") if prof else None) or "medium").strip().lower()
    model = (req_model or (prof.get("model") if prof else None) or "").strip()
    if not model or model == "free-forever":
        if provider == "google":
            model = "gemini-2.5-flash"
        elif provider == "openrouter":
            model = "meta-llama/llama-3.3-70b-instruct"
        elif provider == "groq":
            model = "llama-3.3-70b-versatile"
        elif provider == "omniroute":
            # D-12: Validierte Alias-ID für OmniRoute statt historischem Plugin-Key
            model = "auto/best-coding"
        else:
            model = "auto/best-coding"

    try:
        from backend.model_routing import classify_task as _mr_classify
        from backend.model_routing import is_enabled as _mr_enabled
        from backend.model_routing import resolve as _mr_resolve
        if _mr_enabled():
            _task_type = (req_task_type or "").strip()
            if not _task_type:
                _task_type = _mr_classify(user_msg)
            _route = _mr_resolve(_task_type)
            if _route:
                provider, model = _route["provider"], _route["model"]
                logger.info(f"[ModelRouting] Chat '{_task_type}' -> {provider}/{model}")
    except Exception as _mr_err:
        logger.warning(f"[ModelRouting] Chat-Fallback: {_mr_err}")

    return {
        "prof": prof or {},
        "agent_name": agent_name,
        "system_prompt": system_prompt,
        "all_keys": all_keys,
        "provider": provider,
        "reasoning_level": reasoning_level,
        "model": model,
    }


def _capture_mission_task_with_budget(
    new_task: Dict[str, Any],
    audit_entry: Optional[Dict[str, Any]],
    token_budget: int,
    cost_limit_eur: float,
) -> Dict[str, Any]:
    """D13/HIGH: Task + Budget-Allocation in EINER Transaktion anlegen.

    `budget_bank.reserve()` prüft Task-Caps nur, wenn eine
    `task_budget_allocations`-Zeile existiert. Ohne atomare Zeile entsteht ein
    Task ohne hartes Cap. Beide Tabellen liegen in verschiedenen SQLite-DBs,
    daher ATTACH innerhalb desselben BEGIN IMMEDIATE (kein Event-Replay, keine
    Migration).
    """
    import sqlite3 as _sqlite3

    from archon.core import mission_control as _mc
    from backend import role_budget_engine as _rbe

    tid = str(new_task.get("id") or "")
    agent_id = str(new_task.get("agent_id") or "default")
    cap_tokens = max(1, int(token_budget or 0))
    cap_eur = max(0.0, float(cost_limit_eur or 0.0))
    now = datetime.datetime.now().isoformat()
    _ALLOC_SQL = (
        "INSERT INTO task_budget_allocations "
        "(task_id, parent_task_id, agent_id, token_budget, tokens_used, "
        " cost_limit_eur, cost_used_eur, complexity_weight, budget_share_pct, "
        " allow_autonomous_hiring, status, created_at, updated_at) "
        "VALUES (?, NULL, ?, ?, 0, ?, 0, 1.0, 100.0, 0, 'active', ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET "
        "agent_id=excluded.agent_id, token_budget=excluded.token_budget, "
        "cost_limit_eur=excluded.cost_limit_eur, status='active', "
        "updated_at=excluded.updated_at"
    )
    _ALLOC_PARAMS = (tid, agent_id, cap_tokens, cap_eur, now, now)

    if _mc._is_file_override():
        # Test-/Dev-Modus: die Mission-Control-Datei hat keine Transaktion.
        mc_capture_task_sqlite(new_task, audit_entry)
        _rbe.init_budget_tables()
        with _sqlite3.connect(_rbe.BUDGET_DB_PATH, timeout=15.0) as conn:
            conn.execute(_ALLOC_SQL, _ALLOC_PARAMS)
            conn.commit()
        return new_task

    _rbe.init_budget_tables()
    with _mc._MC_DATA_LOCK:
        conn = _mc._connect_kanban()
        try:
            conn.execute("ATTACH DATABASE ? AS budget", (_rbe.BUDGET_DB_PATH,))
            conn.execute("BEGIN IMMEDIATE")
            _mc._ensure_mc_tables(conn)
            _mc._upsert_task_in_conn(conn, new_task, overwrite=True)
            if audit_entry:
                conn.execute(
                    "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) "
                    "VALUES (?, NULL, 'mc_audit', ?, ?)",
                    (tid, json.dumps(audit_entry, ensure_ascii=False), int(time.time())),
                )
            conn.execute(
                _ALLOC_SQL.replace("task_budget_allocations", "budget.task_budget_allocations"),
                _ALLOC_PARAMS,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    _MC_STATE_CACHE["ts"] = 0.0
    return new_task


@router.post("/api/chat/stream")
async def api_chat_stream(req: ChatStreamRequest, request: Request = None):  # type: ignore[assignment]
    """
    Natives Chat-Streaming via Server-Sent Events (SSE).
    Unterstützt Direkt-Dialog und Missions-Modus mit Paperclip-Kopplung.
    """
    agent_id = req.agent_id or "default"
    user_msg = req.message.strip()
    session_id = req.session_id or f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_id}"
    mode = (req.mode or "direct").lower()

    if not user_msg:
        raise HTTPException(status_code=400, detail={"code": "chat_message_empty", "params": {}})

    try:
        from backend.dual_llm_sanitizer import sanitize_external_input
        san = sanitize_external_input(user_msg, source_id=session_id, source_type="chat")
        if not san.get("is_safe", True):
            blocked_msg = f"🛑 [PROMPT-INJECTION-GUARD]: Eingabe blockiert ({', '.join(san.get('detected_patterns') or ['suspicious_pattern'])})."
            async def _blocked_sse():
                yield f"data: {json.dumps({'type': 'chunk', 'content': blocked_msg})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return StreamingResponse(_blocked_sse(), media_type="text/event-stream")
    except Exception as san_exc:
        # F-038 (S-6.6 / S-4.7): Ein fehlgeschlagener Sanitizer darf NEVER
        # fail-open. Analog zu backend/event_mesh.py:299-321 wird die Eingabe
        # mit Status 'blocked' zurueckgewiesen: kein Dispatch, kein Rohtext im
        # Log, Audit-Eintrag und ERROR-Log. Vorher lief die ungepruefte Nachricht
        # hier still weiter (logger.debug + Fallthrough).
        logger.error("[Chat] Dual-LLM-Sanitizer fehlgeschlagen — Eingabe blockiert: %s", san_exc)
        blocked_reason = "input_sanitizer_unavailable"
        try:
            from backend.audit_log import chained_audit_log
            await asyncio.to_thread(
                chained_audit_log.record_event,
                "chat_input",
                "input_blocked",
                agent_id,
                {
                    "session_id": session_id,
                    "status": "blocked",
                    "reason": blocked_reason,
                    "error": str(san_exc)[:200],
                },
            )
        except Exception as audit_exc:
            # Audit-Fehler darf die fail-closed-Entscheidung nicht aufheben.
            logger.error("[Chat] Audit-Eintrag fuer blockierte Eingabe fehlgeschlagen: %s", audit_exc)

        blocked_msg = (
            "🛑 [PROMPT-INJECTION-GUARD]: Eingabe blockiert — "
            "Eingabeprüfung nicht verfügbar (input_sanitizer_unavailable). "
            "Bitte später erneut versuchen."
        )

        async def _sanitizer_unavailable_sse():
            yield f"data: {json.dumps({'type': 'blocked', 'reason': blocked_reason, 'status': 'blocked'})}\n\n"
            yield f"data: {json.dumps({'type': 'chunk', 'content': blocked_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(_sanitizer_unavailable_sse(), media_type="text/event-stream")

    if user_msg.lower().startswith("/termin ") or user_msg.lower().startswith("/kalender "):
        from backend.operations_calendar import operations_calendar
        query_txt = user_msg.split(" ", 1)[1].strip() if " " in user_msg else ""
        msg = operations_calendar.handle_calendar_nl_query(query_txt)
        async def _cal_sse():
            yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(_cal_sse(), media_type="text/event-stream")

    ctx = await asyncio.to_thread(
        _prepare_chat_stream_context,
        agent_id,
        user_msg,
        req.provider,
        req.model,
        req.reasoning_level,
        getattr(req, "task_type", None),
    )
    prof = ctx["prof"]
    agent_name = ctx["agent_name"]
    system_prompt = ctx["system_prompt"]
    all_keys = ctx["all_keys"]
    provider = ctx["provider"]
    reasoning_level = ctx["reasoning_level"]
    model = ctx["model"]

    # 1. MISSIONS-MODUS: Task erzeugen & HITL Approval-Gate aktivieren
    if mode == "mission":
        task_id = f"task-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        title = user_msg[:80] + ("..." if len(user_msg) > 80 else "")

        # Task in Archon OS erfassen mit status: approval
        est_tokens = 95000 if len(user_msg) > 200 else 45000
        est_cost = 0.18 if len(user_msg) > 200 else 0.05
        # D13/HIGH: hartes, validiertes Ticket-Budget (Pydantic ge/le).
        token_budget = int(req.token_budget or est_tokens)
        cost_limit_eur = float(req.cost_limit_eur or est_cost)
        try:
            from backend.trajectory_budget import (
                DEFAULT_MAX_REPLANS,
                ensure_trajectory,
                normalize_trajectory_id,
            )
            _mission_tid = normalize_trajectory_id(None, root_ticket_id=task_id)
            ensure_trajectory(
                _mission_tid, root_ticket_id=task_id, max_tokens=token_budget,
                max_replans=DEFAULT_MAX_REPLANS,
            )
        except Exception as _traj_exc:
            # Fail-closed: ohne Trajectory kein hartes Ticket-Cap -> kein Dispatch.
            logger.error("[Chat] Mission-Trajectory nicht anlegbar: %s", _traj_exc)
            raise HTTPException(status_code=503, detail="trajectory_budget_unavailable")

        # Operative Zielaktion erkennen (z.B. ACTION: POST_LINKEDIN)
        detected_action = core_dispatcher.detect_target_action(user_msg)

        # Phase bestimmen: Falls Robert (executive_decision_architect), startet Kaskade mit strategy
        initial_phase = "strategy" if agent_id in ("executive_decision_architect", "robert") else "execution"

        new_task = {
            "id": task_id,
            "title": title,
            "capture_input": user_msg,
            "plan": [
                f"Missions-Start: '{title}' über Hermes Core Task Engine",
                f"Ressourcen- und Werkzeugallokation für {agent_name} ({agent_id})",
                "Ausführung & atomarer Obsidian-Sync"
            ],
            "agent_id": agent_id,
            "agent_name": agent_name,
            "model": model,
            "estimated_tokens": est_tokens,
            "estimated_cost_eur": est_cost,
            "token_budget": token_budget,
            "cost_limit_eur": cost_limit_eur,
            # D13/MED: echter Produzent für den Task-Meta-Budget-Alias.
            "trajectory_id": _mission_tid,
            "root_ticket_id": task_id,
            "max_tokens": token_budget,
            "tokens_used": 0,
            "max_replans": DEFAULT_MAX_REPLANS,
            "replans_used": 0,
            "replan_count": 0,
            "subagents_count": 0,  # F-007: ehrlich — noch keine Subtasks erzeugt
            "subagents_count_source": "none_yet",  # D01: nach Fan-Out durch echte Zahl ersetzt
            "subagents_count_estimated": False,
            "status": "approval",  # HITL Gate sperrt Ausführung zwingend
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result_summary": "",
            "artifact_path": "",
            "paperclip_issue": None,
            "parent_project_id": None,
            "subtask_ids": [],
            "target_action": detected_action,
            "phase": initial_phase
        }

        # Audit Log + atomare Persistenz direkt in kanban.db
        now_t = datetime.datetime.now().strftime("%H:%M:%S")
        audit_entry = {
            "time": now_t,
            "source": "Approval Gate",
            "msg": f"Missions-Modus: Task #{task_id} erfordert Freigabe vor Ausführung!"
        }
        await asyncio.to_thread(
            _capture_mission_task_with_budget,
            new_task, audit_entry, token_budget, cost_limit_eur,
        )
        try:
            from backend.trajectory_budget import sync_task_budget_meta
            await asyncio.to_thread(sync_task_budget_meta, _mission_tid, task_id)
        except Exception as _sync_exc:
            logger.debug("[Chat] Mission-Budget-Meta nicht gespiegelt: %s", _sync_exc)
        
        # --- 2c: Mission liegt im HITL-Approval-Gate -> ueber den zentralen
        # Entscheidungs-Service (echter Kanban-Task, EIN Schreibpfad) ---
        try:
            _create_dec = _get_create_decision()
            if _create_dec:
                # D04/D14 (Vier-Augen): der Ersteller MUSS gesetzt sein, sonst
                # verweigert /api/decisions/decide die Freigabe fail-closed.
                # Identitaet ausschliesslich aus der verifizierten Session —
                # nie aus req/Body. Ohne Request bleibt ein dokumentierter
                # Service-Principal, damit Hintergrund-Trigger freigebbar sind.
                from archon.routers._rbac import get_session_actor
                _mission_creator = (
                    get_session_actor(request, fallback="chat-service")
                    if request is not None else "chat-service"
                )
                _mdec = await asyncio.to_thread(
                    _create_dec, "mission_freigabe",
                    f"Mission-Freigabe: {str(title)[:80]}",
                    f"Agent: {agent_name} ({agent_id})\nGeschätzte Kosten: ~{est_cost:.2f} €",
                    task_id, None, "", None, None, _mission_creator)
                if not _mdec:
                    logger.warning(f"[Mission] Entscheidungs-Task für {task_id} nicht angelegt.")
        except Exception as tg_err:
            logger.warning(f"[Telegram] Missions-Freigabe-Ping für {task_id} fehlgeschlagen: {tg_err}")

        # In DB persistieren
        await asyncio.to_thread(_db_init_session_and_message, session_id, agent_id, model, title, user_msg)
        
        approval_confirmation = (
            f"🛡️ **Mission erfasst & HITL-Freigabe erforderlich!**\n\n"
            f"- **Task-ID:** `{task_id}`\n"
            f"- **Operations Identifier:** `TASK-{task_id}`\n"
            f"- **Zugewiesener Agent:** {agent_name} (`{agent_id}`)\n"
            f"- **Geschätzte Kosten:** ~{est_cost:.2f} € ({est_tokens:,} Tokens)\n"
            f"- **Status:** `🛑 STOP / Freigabe erforderlich` (Im Mission Control Approval Gate gesperrt)"
        )
        await asyncio.to_thread(_save_message_to_db, session_id, "assistant", approval_confirmation)

        async def mission_event_stream():
            yield f"data: {json.dumps({'type': 'mission_created', 'task_id': task_id, 'task': new_task, 'content': approval_confirmation}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(mission_event_stream(), media_type="text/event-stream")

    # 2. DIREKT-DIALOG: Streaming via ausgewählten Provider (Google, OpenRouter, Groq, OmniRoute etc.)
    try:
        await asyncio.to_thread(_db_init_session_and_message, session_id, agent_id, model, user_msg[:50], user_msg)
    except Exception as db_err:
        logger.warning(f"[Chat Stream] Session/Message DB init warning: {db_err}")

    # M73 Teil 3 + M99: Auto-Kompaktierung gegen das modell-dynamische Kontextfenster
    _auto_compaction_result: Optional[Dict[str, Any]] = None
    try:
        from archon.routers.context_meter import maybe_auto_compact_session
        _auto = await asyncio.to_thread(maybe_auto_compact_session, session_id, model)
        if _auto.get("compacted"):
            _auto_compaction_result = _auto
            logger.info(
                f"[Chat Stream] Auto-Kompaktierung: Session {session_id} "
                f"{_auto.get('original_tokens')} -> {_auto.get('compacted_tokens')} Tokens "
                f"({_auto.get('saved_pct')}% gespart)"
            )
    except Exception as auto_err:
        logger.warning(f"[Chat Stream] Auto-Kompaktierung uebersprungen: {auto_err}")

    # Lade letzten Kontext aus DB (bis zu 50 Nachrichten fuer stabilen Sitzungsverlauf)
    recent_messages = []
    try:
        raw_rows = await asyncio.to_thread(_db_load_recent_chat_messages, session_id, 50)
        for r in reversed(raw_rows):
            content_val = r["content"]
            role_val = r["role"]
            # Sanitize repetitive metadata footers and system checks from context history to prevent autoregressive feedback loops
            if role_val == "assistant" and isinstance(content_val, str):
                content_val = re.sub(r'(\n|\r\n)*\s*(\*?-?\s*Routed to:[^\n]+|\*?-?\s*🧠 Antwort generiert von[^\n]+)', '', content_val)
                content_val = re.sub(r'\(System-Check via mcp__[^\)]+\)\s*[🟢🔴🟡]?', '', content_val).strip()

            # Dateianhänge (bis zu 5 Dateien: Bilder als multimodale Vision-Inhalte, Text/Code als Prompt-Inhalt)
            if role_val == "user" and "[Datei angehängt:" in content_val:
                matches = list(re.finditer(r'\[Datei angehängt:\s*([^\]]+)\]', content_val))
                if matches:
                    clean_text = content_val
                    for m in matches:
                        clean_text = clean_text.replace(m.group(0), "")
                    clean_text = clean_text.strip()
                    
                    image_blocks = []
                    text_attachments = []
                    from utils.path_jail import PathJailError, safe_path_within
                    allowed_attach_roots = [
                        r for r in (
                            WORKSPACE_DIR,
                            "/projects" if os.path.exists("/projects") else None,
                            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "uploads"),
                            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"),
                            OBSIDIAN_VAULT_DIR,
                        ) if r
                    ]
                    for m in matches[:5]:
                        raw_path = m.group(1).strip()
                        f_path = None
                        try:
                            f_path = safe_path_within(raw_path, allowed_attach_roots, must_exist=True, allow_dirs=False)
                        except PathJailError:
                            f_path = None
                        if f_path and os.path.isfile(f_path):
                            lower_p = f_path.lower()
                            if lower_p.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                                try:
                                    with open(f_path, "rb") as img_f:
                                        img_b64 = base64.b64encode(img_f.read()).decode("utf-8")
                                    mime = "image/png"
                                    if lower_p.endswith(('.jpg', '.jpeg')):
                                        mime = "image/jpeg"
                                    elif lower_p.endswith('.webp'):
                                        mime = "image/webp"
                                    elif lower_p.endswith('.gif'):
                                        mime = "image/gif"
                                    image_blocks.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:{mime};base64,{img_b64}"}
                                    })
                                except Exception as img_err:
                                    logger.warning(f"[Chat Stream] Konnte Bild nicht einbetten: {img_err}")
                            elif lower_p.endswith(('.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.html', '.css', '.yaml', '.yml', '.log')):
                                try:
                                    with open(f_path, "r", encoding="utf-8", errors="ignore") as tf:
                                        snippet = tf.read(15000)
                                        b_name = os.path.basename(f_path)
                                        text_attachments.append(f"\n--- DATEI-INHALT ({b_name}) ---\n{snippet}\n--- ENDE DATEI-INHALT ---")
                                except Exception as tf_err:
                                    logger.warning(f"[Chat Stream] Konnte Textdatei nicht lesen: {tf_err}")

                    if image_blocks:
                        full_prompt = clean_text
                        if text_attachments:
                            full_prompt += "\n" + "\n".join(text_attachments)
                        content_val = [{"type": "text", "text": full_prompt or "Siehe angehängte Dateien."}] + image_blocks
                    elif text_attachments:
                        content_val = (clean_text + "\n" + "\n".join(text_attachments)).strip()

            recent_messages.append({"role": role_val, "content": content_val})
    except Exception as e:
        logger.warning(f"[Chat Stream] Konnte Kontext nicht laden: {e}")
        recent_messages = [{"role": "user", "content": user_msg}]

    # Enterprise Skill Resolver (Dynamische Kontext-Injektion für Session)
    skills_prompt_block = None
    freshly_loaded_skills: List[str] = []
    direct_skill_notice = None
    try:
        from scripts.skill_resolver import resolve_and_prepare_skill_context
        skills_idx = build_skills_file_index()
        skills_prompt_block, freshly_loaded_skills, direct_skill_notice = resolve_and_prepare_skill_context(
            session_id=session_id,
            user_msg=user_msg,
            find_skill_file_fn=find_skill_file,
            skills_index=skills_idx,
            agent_prof=prof
        )
    except Exception as sk_err:
        logger.error(f"[Chat Stream] Error resolving enterprise skills: {sk_err}")

    if skills_prompt_block:
        payload_messages = [{"role": "system", "content": system_prompt}, {"role": "system", "content": skills_prompt_block}] + recent_messages
    else:
        payload_messages = [{"role": "system", "content": system_prompt}] + recent_messages

    def _sync_subagents_count_from_store(mission_task_id: Optional[str]) -> Optional[int]:
        """D01/MED: `subagents_count` aus der echten Anzahl erzeugter Subtasks ableiten.

        Der Fan-Out selbst liegt in `archon/core/delegation.py` (anderer Owner).
        Dieser Chokepoint liest danach den persistierten Task und ersetzt die
        Prognose durch die tatsaechliche Anzahl — ohne Subtasks bleibt der Wert
        verifiziert 0 statt einer erfundenen Zahl.
        """
        if not mission_task_id:
            return None
        try:
            from archon.core.mission_control import mc_get_task_sqlite, mc_update_task_sqlite

            task = mc_get_task_sqlite(mission_task_id)
            if not task:
                return None
            child_ids = task.get("subtask_ids") or []
            actual = len(child_ids) if isinstance(child_ids, (list, tuple)) else 0
            mc_update_task_sqlite(
                mission_task_id,
                {
                    "subagents_count": actual,
                    "subagents_count_source": "actual",
                    "subagents_count_estimated": False,
                },
            )
            return actual
        except Exception as exc:
            logger.warning(f"[Chat] subagents_count konnte nicht verifiziert werden: {exc}")
            return None

    async def chat_event_stream():
        full_assistant_text = ""
        # Nur echte Provider-Chunks zaehlen als Antwort. System-Hinweise
        # (Skill-Pills) duerfen eine leere LLM-Antwort nicht ueberdecken.
        provider_answer_text = ""
        synced_subagents: Optional[int] = None
        mission_task_id = task_id if mode == "mission" else None
        prompt_tokens = len(user_msg.split()) * 2
        completion_tokens = 0

        # M99: Sichtbarer Compaction-Marker bei automatischer Verdichtung im Live-Stream
        if _auto_compaction_result:
            yield f"data: {json.dumps({'type': 'compaction_marker', 'marker': _auto_compaction_result.get('compaction_marker', ''), 'original_tokens': _auto_compaction_result.get('original_tokens', 0), 'compacted_tokens': _auto_compaction_result.get('compacted_tokens', 0), 'saved_tokens': _auto_compaction_result.get('saved_tokens', 0), 'saved_pct': _auto_compaction_result.get('saved_pct', 0.0), 'compacted_messages': _auto_compaction_result.get('compacted_messages', 0), 'kept_recent': _auto_compaction_result.get('kept_recent', 0), 'model': _auto_compaction_result.get('model'), 'max_context_tokens': _auto_compaction_result.get('max_context_tokens')}, ensure_ascii=False)}\n\n"

        # M67 (additiv): kompakter Host-State im selben Stream. Der M99-Marker
        # oben bleibt unverändert und wird weiterhin zuerst gesendet.
        try:
            _m67_event = await asyncio.to_thread(_m67_stream_host_state, session_id)
            if _m67_event:
                yield f"data: {json.dumps(_m67_event, ensure_ascii=False)}\n\n"
        except Exception as m67_exc:
            logger.debug("[M67] Host-State-Schatten im Stream uebersprungen: %s", m67_exc)

        # Direkte System-Antwort bei Management-Befehlen (/skill list, /skill clear)
        if direct_skill_notice:
            yield f"data: {json.dumps({'type': 'delta', 'delta': direct_skill_notice}, ensure_ascii=False)}\n\n"
            full_assistant_text = direct_skill_notice
            _save_message_to_db(session_id, "assistant", full_assistant_text)
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
            return

        # Falls in diesem Turn ein neuer Skill geladen wurde, visuelle Bestätigung im Stream ausgeben
        if freshly_loaded_skills:
            skill_pills = ", ".join([f"`{s}`" for s in freshly_loaded_skills])
            pill_text = f"⚙️ *[System: Skill(s) erfolgreich in den Arbeitsspeicher geladen: {skill_pills}]*\n\n"
            full_assistant_text += pill_text
            yield f"data: {json.dumps({'type': 'delta', 'delta': pill_text}, ensure_ascii=False)}\n\n"

        from backend.agent_router import router_instance

        # Delegate LLM execution to the Hardware Abstraction Layer (AgentRouter)
        # F-05: Ein Provider-Fehler wurde als erfolgreicher Turn verbucht — die
        # Fehlermeldung landete in ``full_assistant_text``, wurde als
        # Assistenten-Antwort persistiert, "done" gesendet und die Nutzung
        # gebucht. Jetzt wird der Fehler als solcher markiert: die
        # Fehlermeldung wird NICHT als Antwort gespeichert und es wird keine
        # Nutzung gebucht.
        provider_failed = False
        try:
            async for chunk in router_instance.stream_chat_completion(
                messages=payload_messages,
                provider=provider,
                model=model,
                api_keys=all_keys,
                reasoning_level=reasoning_level,
                agent_id=agent_id,
                role=str((prof or {}).get("name") or ""),
                # D13/HIGH: im Missionsmodus die echte Ticket-ID durchreichen,
                # damit reserve_tokens() gegen dieselbe Trajectory (und damit
                # dasselbe `max_tokens`) bucht wie das Task-Anlegen.
                task_id=mission_task_id or session_id,
            ):
                if chunk.startswith("ERROR: "):
                    provider_failed = True
                    yield f"data: {json.dumps({'type': 'error', 'error': chunk[7:]})}\n\n"
                    full_assistant_text += chunk[7:]
                else:
                    full_assistant_text += chunk
                    provider_answer_text += chunk
                    completion_tokens += 1
                    yield f"data: {json.dumps({'type': 'delta', 'delta': chunk}, ensure_ascii=False)}\n\n"

            if not provider_failed and not provider_answer_text.strip():
                # BLOCKER (D12/S-12.1): HTTP 200 ohne SSE-Nutzlast ist ein
                # Provider-Fehler. Kein erfundener Text, kein `done`, keine
                # DB-Speicherung, kein Transparenztag, keine Usage-Buchung.
                provider_failed = True
                err_msg = f"Leere Antwort von {provider.capitalize()} (HTTP 200 ohne SSE-Nutzlast)."
                logger.error(f"[Chat Stream] {err_msg}")
                yield f"data: {json.dumps({'type': 'error', 'error': err_msg}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            provider_failed = True
            err_msg = f"Verbindungsfehler zu {provider.capitalize()}: {str(exc)}"
            logger.error(f"[Chat Stream] {err_msg}")
            # Die Fehlermeldung gehoert in den Fehlerkanal, nicht in die
            # Antwort (sonst wird sie als Antwort gespeichert/gebucht).
            yield f"data: {json.dumps({'type': 'error', 'error': err_msg}, ensure_ascii=False)}\n\n"

        if provider_failed:
            # Harte Eskalation: der Stream endet mit `error`. Es gibt keine
            # Antwort zu delegieren, zu speichern, zu bezahlen oder zu
            # quittieren — insbesondere kein `done`-Event.
            return

        # Kosten-Berechnung und Transparenz-Anzeige (Pillar 3/6)
        cost_str = "unverifiziert"
        cost_unverified = True
        try:
            prices = None
            try:
                # A) Kein blockierender HTTP-Call im SSE-Event-Loop: nach
                # TTL-Ablauf wartet urlopen(timeout=5) im Thread, nicht im Loop.
                p_res = await asyncio.to_thread(get_llm_prices)
                if isinstance(p_res, dict) and "prices" in p_res:
                    prices = p_res["prices"]
            except Exception as price_err:
                _warn_price_lookup_once(price_err)
            m_price = (prices or {}).get(model, {})
            p_rate = m_price.get("prompt_1m", 0.0)
            c_rate = m_price.get("completion_1m", 0.0)
            if p_rate == 0.0 and c_rate == 0.0:
                m_low = model.lower()
                if "opus" in m_low:
                    p_rate, c_rate = (7.50, 37.50) if "batch" in m_low else (15.0, 75.0)
                elif "sonnet" in m_low:
                    p_rate, c_rate = (3.0, 15.0)
                elif "deepseek" in m_low:
                    p_rate, c_rate = (0.25, 1.0)
                elif "gpt-4o-mini" in m_low:
                    p_rate, c_rate = (0.15, 0.60)
                elif "gpt-4o" in m_low:
                    p_rate, c_rate = (2.50, 10.0)
            if p_rate > 0.0 or c_rate > 0.0:
                p_cost = (max(prompt_tokens, 800) / 1_000_000) * p_rate
                c_cost = (max(completion_tokens, 100) / 1_000_000) * c_rate
                total_cost = p_cost + c_cost
                if total_cost > 0:
                    cost_str = f"{total_cost:.5f}"
                    cost_unverified = False
        except Exception as e:
            logger.error(f"Cost calculation error: {e}")

        tier = "High" if provider == "openrouter" else "Low"
        cost_display = "unverifiziert" if cost_unverified else f"{cost_str}$"
        transparency_tag = f"\n\n*- 🧠 Antwort generiert von `@{agent_id}` via `{model}` | Tier: `{tier}` | Est. Cost: `{cost_display}`*"

        # Delegation Engine v2: strukturierte ```delegation```-Blöcke + Legacy-CLI-Interception.
        # Quittungen werden in die Delegator-Session geschrieben -> der Agent "erinnert" sich.
        delegation_receipts: list[str] = []
        try:
            # D13: zentraler Fan-out-Cap im Produktivpfad (vorher nur Default
            # im Modul, chat.py rief ohne Cap -> beliebig viele Delegationen).
            from backend.trajectory_budget import (
                DEFAULT_MAX_DELEGATIONS_PER_RESPONSE,
                normalize_trajectory_id,
            )
            cap = DEFAULT_MAX_DELEGATIONS_PER_RESPONSE
            # D13/HIGH: erst ALLE Payloads (strukturiert + Legacy-Regex) in
            # dieselbe Menge/dedup, dann den Cap EINMAL anwenden. Der Parser
            # bekommt bewusst einen weiten Cap, damit er nicht vorzeitig
            # kürzt und der Überschuss hier einheitlich quittiert wird.
            payloads, invalid_blocks = _parse_delegation_blocks(
                full_assistant_text, fanout_cap=max(cap, len(full_assistant_text) // 8 + 1)
            )
            seen_hashes = {
                f"{str(p.get('ziel_agent') or '')}:{str(p.get('auftrag') or '')[:40]}"
                for p in payloads
            }
            # Legacy-Fallback: alte `hermes -p ...`-CLI-Befehle weiterhin abfangen
            for m in re.finditer(r'hermes\s+-p\s+([a-zA-Z0-9_-]+)\s+chat\s+.*?-q\s+["\'](.*?)["\']', full_assistant_text, re.DOTALL):
                mm = re.search(r'-m\s+([a-zA-Z0-9_/.:-]+)', m.group(0))
                legacy = {
                    "ziel_agent": m.group(1),
                    "auftrag": m.group(2),
                    "modell": mm.group(1) if mm else "",
                    "prioritaet": "normal"
                }
                h = f"{legacy['ziel_agent']}:{legacy['auftrag'][:40]}"
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                payloads.append(legacy)

            if len(payloads) > cap:
                from archon.core.delegation import DelegationReceipt
                from backend.trajectory_budget import _audit
                omitted = payloads[cap:]
                payloads = payloads[:cap]
                _fanout_tid = normalize_trajectory_id(None, root_ticket_id=session_id)
                for _op in omitted:
                    _ziel = str(_op.get("ziel_agent") or "?")
                    receipt = DelegationReceipt(
                        f"❌ DELEGATION BLOCKIERT — Grund: FANOUT_CAP (max {cap} pro Antwort) | "
                        f"Ziel: {_ziel} | Der Auftrag wurde NICHT ausgeführt. HITL/escalate required.",
                        status="blocked", reason="FANOUT_CAP", block_kind="fanout_cap",
                        failure_reason="FANOUT_CAP", trajectory_id=_fanout_tid,
                    )
                    delegation_receipts.append(receipt)
                    invalid_blocks.append({
                        "raw": "", "error": "FANOUT_CAP", "blocked": True,
                        "cap": cap, "ziel_agent": _ziel,
                        "reason": f"MAX_DELEGATIONS_PER_RESPONSE={cap} überschritten",
                    })
                    try:
                        _audit(_fanout_tid, f"FANOUT_CAP: {_ziel} blockiert (cap={cap})", mission_task_id or session_id)
                    except Exception as _audit_exc:
                        # D07/MED: Audit-Fehler nie verschlucken. Die Cap-
                        # Blockade bleibt auch ohne Audit wirksam, wird aber
                        # als `audit_failed` markiert und in Produktion
                        # (ARCHON_AUDIT_STRICT=1) hart abgebrochen.
                        logger.error(
                            "[Chat] FANOUT_CAP-Audit nicht geschrieben (Ziel=%s): %s",
                            _ziel, _audit_exc,
                        )
                        receipt.failure_reason = "FANOUT_CAP (audit_failed)"
                        if os.environ.get("ARCHON_AUDIT_STRICT", "").strip().lower() in ("1", "true", "yes"):
                            raise RuntimeError("FANOUT_CAP audit_write_failed") from _audit_exc
                if mission_task_id:
                    try:
                        from archon.core.mission_control import mc_update_task_sqlite
                        await asyncio.to_thread(
                            mc_update_task_sqlite, mission_task_id,
                            {"status": "blocked", "block_kind": "fanout_cap",
                             "failure_reason": "FANOUT_CAP"},
                        )
                    except Exception as _mc_exc:
                        logger.debug("[Chat] FANOUT_CAP-Task-Meta nicht persistiert: %s", _mc_exc)
                try:
                    invalid_blocks.fanout_cap = cap
                    invalid_blocks.fanout_blocked = True
                    invalid_blocks.omitted_count = len(omitted)
                except Exception:
                    pass

            for payload in payloads:
                try:
                    delegation_receipts.append(_execute_delegation(agent_id, payload, provider, all_keys, origin_session_id=session_id))
                except Exception as de:
                    delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Intern: {de}")
            for bad in invalid_blocks:
                if str(bad.get("error") or "") == "FANOUT_CAP":
                    # Bereits oben als `blocked`/FANOUT_CAP-Quittung ausgegeben.
                    continue
                delegation_receipts.append(
                    f"⚠️ DELEGATION-FEHLER — Ungültiger Delegations-Block ({bad['error']}). "
                    f"Der Auftrag wurde NICHT ausgeführt. Block: {bad['raw'][:120]}"
                )
        except Exception as e:
            logger.error(f"Delegation Engine Fehler: {e}")
            delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Engine: {e}")

        if mission_task_id:
            synced_subagents = await asyncio.to_thread(_sync_subagents_count_from_store, mission_task_id)

        if delegation_receipts:
            receipt_text = "\n\n" + "\n".join(delegation_receipts)
            payload = json.dumps({"type": "delta", "delta": receipt_text}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            full_assistant_text += receipt_text

        # Antwort & Metriken in SQLite verbuchen
        # Transparenz-Tag nach Delegationsquittungen nur bei realer KI-Antwort ausgeben (Art. 50)
        if not provider_failed:
            payload_trans = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
            yield f"data: {payload_trans}\n\n"
            full_assistant_text += transparency_tag

        # F-05: Bei Provider-Fehler wird die Fehlermeldung NICHT als
        # Assistenten-Antwort gespeichert und es wird keine Nutzung gebucht.
        if not provider_failed:
            # Audit D08: SQLite-Writes im async SSE-Generator blockieren den
            # Event-Loop bei jedem Chatabschluss -> in den Thread-Pool.
            await asyncio.to_thread(
                _save_message_to_db, session_id, "assistant", full_assistant_text, completion_tokens
            )

        # Parse total_cost if possible
        try:
            total_cost_val = float(cost_str)
        except (ValueError, TypeError):
            total_cost_val = 0.0

        if not provider_failed:
            await asyncio.to_thread(
                _record_session_model_usage, session_id, model, prompt_tokens, completion_tokens, total_cost_val
            )
        done_payload: Dict[str, Any] = {"type": "done", "session_id": session_id, "tokens": completion_tokens}
        if synced_subagents is not None:
            done_payload["subagents_count"] = synced_subagents
        payload_done = json.dumps(done_payload, ensure_ascii=False)
        yield f"data: {payload_done}\n\n"

    return StreamingResponse(chat_event_stream(), media_type="text/event-stream")


# F2: ImageGenerateToolRequest + api_tool_image_generate liegen in
# backend/image_generate.py (backend/** darf archon.routers nicht importieren).
# Der Re-Export oben haelt chat.* und main.py unveraendert. Die Route wird
# hier auf demselben chat.router re-registriert: gleicher Pfad, gleiche
# Reihenfolge, tags/dependencies bleiben erhalten.
router.post("/api/v1/tools/image_generate")(api_tool_image_generate)

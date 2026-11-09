"""
Native Master Chat & Missions Logic (SSE Stream, Persistence, Uploads)
für Archon OS. Ausgelagert aus main.py zur modularen Entschlackung.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import api_provider
import core_dispatcher
from archon.core.delegation import (
    _execute_delegation,
    _get_delegation_prompt_for,
    _parse_delegation_blocks,
)
from archon.core.mission_control import (
    _MC_STATE_CACHE,
    update_mission_control_data,
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
from archon.routers.llm_providers import get_llm_prices
from archon.routers.skills import (
    build_skills_file_index,
    find_skill_file,
)
from backend.platform_paths import OBSIDIAN_VAULT, PERSONALAKTEN_DIR

router = APIRouter(tags=["chat"])

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


def _load_state_history(session_id: str, limit: int = 12) -> List[Dict[str, str]]:
    """Liest die letzten Nachrichten einer Sitzung aus state.db als Chat-Historie."""
    try:
        with _get_state_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? AND active = 1 "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
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
            SELECT id, role, content, timestamp, token_count
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


class RenameSessionRequest(BaseModel):
    title: str


@router.post("/api/chat/sessions/{session_id}/rename")
@router.patch("/api/chat/sessions/{session_id}")
def api_rename_chat_session(session_id: str, req: RenameSessionRequest):
    """Ermöglicht das freie Umbenennen jeder Chat-Session."""
    new_title = req.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Der Titel darf nicht leer sein.")
    try:
        _db_rename_session(session_id, new_title)
        logger.info(f"[Chat Rename] Session {session_id} umbenannt zu '{new_title}'")
        return {"status": "success", "session_id": session_id, "title": new_title}
    except Exception as e:
        logger.error(f"[Chat Rename] Fehler beim Umbenennen von {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/upload")
def api_chat_upload(file: UploadFile = File(...)):
    """Empfängt Datei-Uploads und legt sie im Agent-Workspace (/projects/ bzw. ./agent_workspace) ab."""
    try:
        target_dir = "/projects" if os.path.exists("/projects") else os.path.join(WORKSPACE_DIR, "uploads")
        os.makedirs(target_dir, exist_ok=True)
        
        safe_filename = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', file.filename)
        timestamp_prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"{timestamp_prefix}_{safe_filename}"
        dest_path = os.path.join(target_dir, final_filename)
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_size = os.path.getsize(dest_path)
        logger.info(f"[Chat Upload] Datei gespeichert: {dest_path} ({file_size} Bytes)")
        add_ticker("Chat Upload", f"Datei '{file.filename}' im Workspace abgelegt.")
        
        return {
            "status": "success",
            "filename": final_filename,
            "original_name": file.filename,
            "path": dest_path,
            "size": file_size
        }
    except Exception as e:
        logger.error(f"[Chat Upload] Upload fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {str(e)}")


_PRICE_LOOKUP_WARNED = {"done": False}


def _warn_price_lookup_once(exc: Exception) -> None:
    """Einmal laut meckern, wenn die Preisliste nicht kommt — nicht bei jedem Token."""
    if _PRICE_LOOKUP_WARNED["done"]:
        return
    _PRICE_LOOKUP_WARNED["done"] = True
    logger.warning(f"[Pricing] Preisliste nicht abrufbar — Kostenanzeige bleibt 0: {exc}")


@router.post("/api/chat/stream")
async def api_chat_stream(req: ChatStreamRequest):
    """
    Natives Chat-Streaming via Server-Sent Events (SSE).
    Unterstützt Direkt-Dialog und Missions-Modus mit Paperclip-Kopplung.
    """
    agent_id = req.agent_id or "default"
    user_msg = req.message.strip()
    session_id = req.session_id or f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_id}"
    mode = (req.mode or "direct").lower()

    if not user_msg:
        raise HTTPException(status_code=400, detail="Nachricht darf nicht leer sein.")

    # Profil laden
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof and profiles:
        prof = profiles[0]
    
    agent_name = prof.get("person_name") or prof.get("name") or "Hermes Agent"
    system_prompt = prof.get("prompt") or "You are Hermes Agent, an intelligent AI assistant created by Nous Research."
    # Delegations-Protokoll für berechtigte Hierarchie-Ebenen (Tier 1/2) dynamisch injizieren
    delegation_prompt_addon = _get_delegation_prompt_for(agent_id)
    if delegation_prompt_addon:
        system_prompt += delegation_prompt_addon

    # Obsidian Personalakte als Identitäts- und Kompetenzkontext injizieren
    try:
        akte_candidates = [
            os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
            os.path.join(PERSONALAKTEN_DIR, f"{agent_id}.md"),
            os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten", f"{agent_id}.md")
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

    provider = (req.provider or "").strip().lower()
    if not provider:
        provider = (prof.get("provider") or "").strip().lower()
    if not provider and req.model:
        provider = api_provider.infer_provider_from_model(req.model) or ""
    if not provider:
        active_cfg = api_provider.read_active_config()
        provider = (active_cfg.get("provider") or "").strip().lower()
    if not provider:
        provider = "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"

    reasoning_level = (req.reasoning_level or prof.get("reasoning_level") or "medium").strip().lower()
    model = (req.model or prof.get("model") or "").strip()
    if not model or model == "free-forever":
        if provider == "google":
            model = "gemini-2.5-flash"
        elif provider == "openrouter":
            model = "meta-llama/llama-3.3-70b-instruct"
        elif provider == "groq":
            model = "llama-3.3-70b-versatile"
        elif provider == "omniroute":
            # D-12: "evey-session-guard:" war kein Modellname, sondern ein
            # Plugin-Key mit angehaengtem Doppelpunkt — als Modell-ID war
            # jeder Aufruf ein erwartbarer Upstream-400. Der Default ist jetzt
            # ein Alias, den OmniRoute tatsaechlich kennt (vgl.
            # api_provider._list_provider_models_uncached).
            model = "auto/best-coding"
        else:
            model = "auto/best-coding"

    # Modell-Routing (Eigentümer-Tabelle): überschreibt das Profilmodell, wenn aktiv.
    try:
        from backend.model_routing import is_enabled as _mr_enabled, resolve as _mr_resolve, classify_task as _mr_classify
        if _mr_enabled():
            _task_type = (getattr(req, "task_type", None) or "").strip()
            if not _task_type:
                _task_type = _mr_classify(user_msg)
            _route = _mr_resolve(_task_type)
            if _route:
                provider, model = _route["provider"], _route["model"]
                logger.info(f"[ModelRouting] Chat '{_task_type}' -> {provider}/{model}")
    except Exception as _mr_err:
        logger.warning(f"[ModelRouting] Chat-Fallback: {_mr_err}")

    # 1. MISSIONS-MODUS: Task erzeugen & HITL Approval-Gate aktivieren
    if mode == "mission":
        task_id = f"task-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        title = user_msg[:80] + ("..." if len(user_msg) > 80 else "")

        # Task in Archon OS erfassen mit status: approval
        est_tokens = 95000 if len(user_msg) > 200 else 45000
        est_cost = 0.18 if len(user_msg) > 200 else 0.05

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
            "subagents_count": 2,
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

        # Audit Log
        now_t = datetime.datetime.now().strftime("%H:%M:%S")

        # F-10: Read-Modify-Write unter Lock statt load->modify->save.
        def _approval_mutate(mc_data):
            mc_data.setdefault("tasks", []).insert(0, new_task)
            mc_data.setdefault("audit_logs", []).insert(0, {
                "time": now_t,
                "source": "Approval Gate",
                "msg": f"Missions-Modus: Task #{task_id} erfordert Freigabe vor Ausführung!"
            })
            mc_data["audit_logs"] = mc_data["audit_logs"][:25]
            return new_task

        await asyncio.to_thread(update_mission_control_data, _approval_mutate)
        
        # --- 2c: Mission liegt im HITL-Approval-Gate -> ueber den zentralen
        # Entscheidungs-Service (echter Kanban-Task, EIN Schreibpfad) ---
        try:
            _create_dec = _get_create_decision()
            if _create_dec:
                _mdec = await asyncio.to_thread(
                    _create_dec, "mission_freigabe",
                    f"Mission-Freigabe: {str(title)[:80]}",
                    f"Agent: {agent_name} ({agent_id})\nGeschätzte Kosten: ~{est_cost:.2f} €",
                    task_id, None, "", None)
                if not _mdec:
                    logger.warning(f"[Mission] Entscheidungs-Task für {task_id} nicht angelegt.")
        except Exception as tg_err:
            logger.warning(f"[Telegram] Missions-Freigabe-Ping für {task_id} fehlgeschlagen: {tg_err}")

        # In DB persistieren
        _db_init_session_and_message(session_id, agent_id, model, title, user_msg)
        
        approval_confirmation = (
            f"🛡️ **Mission erfasst & HITL-Freigabe erforderlich!**\n\n"
            f"- **Task-ID:** `{task_id}`\n"
            f"- **Operations Identifier:** `TASK-{task_id}`\n"
            f"- **Zugewiesener Agent:** {agent_name} (`{agent_id}`)\n"
            f"- **Geschätzte Kosten:** ~{est_cost:.2f} € ({est_tokens:,} Tokens)\n"
            f"- **Status:** `🛑 STOP / Freigabe erforderlich` (Im Mission Control Approval Gate gesperrt)"
        )
        _save_message_to_db(session_id, "assistant", approval_confirmation)

        async def mission_event_stream():
            yield f"data: {json.dumps({'type': 'mission_created', 'task_id': task_id, 'task': new_task, 'content': approval_confirmation}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(mission_event_stream(), media_type="text/event-stream")

    # 2. DIREKT-DIALOG: Streaming via ausgewählten Provider (Google, OpenRouter, Groq, OmniRoute etc.)
    try:
        _db_init_session_and_message(session_id, agent_id, model, user_msg[:50], user_msg)
    except Exception as db_err:
        logger.warning(f"[Chat Stream] Session/Message DB init warning: {db_err}")

    # Lade letzten Kontext aus DB (bis zu 50 Nachrichten fuer stabilen Sitzungsverlauf)
    recent_messages = []
    try:
        raw_rows = _db_load_recent_chat_messages(session_id, 50)
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
                    for m in matches[:5]:
                        f_path = m.group(1).strip()
                        if os.path.exists(f_path):
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
    freshly_loaded_skills = []
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

    async def chat_event_stream():
        full_assistant_text = ""
        prompt_tokens = len(user_msg.split()) * 2
        completion_tokens = 0

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
                reasoning_level=reasoning_level
            ):
                if chunk.startswith("ERROR: "):
                    provider_failed = True
                    yield f"data: {json.dumps({'type': 'error', 'error': chunk[7:]})}\n\n"
                    full_assistant_text += chunk[7:]
                else:
                    full_assistant_text += chunk
                    completion_tokens += 1
                    yield f"data: {json.dumps({'type': 'delta', 'delta': chunk}, ensure_ascii=False)}\n\n"

            if not full_assistant_text:
                full_assistant_text = f"Keine Antwort von {provider.capitalize()} erhalten."
                yield f"data: {json.dumps({'type': 'delta', 'delta': full_assistant_text})}\n\n"

        except Exception as exc:
            provider_failed = True
            err_msg = f"Verbindungsfehler zu {provider.capitalize()}: {str(exc)}"
            logger.error(f"[Chat Stream] {err_msg}")
            # Die Fehlermeldung gehoert in den Fehlerkanal, nicht in die
            # Antwort (sonst wird sie als Antwort gespeichert/gebucht).
            yield f"data: {json.dumps({'type': 'error', 'error': err_msg})}\n\n"

        # Kosten-Berechnung und Transparenz-Anzeige (Pillar 3/6)
        cost_str = "0.0000"
        try:
            prices = None
            try:
                p_res = get_llm_prices()
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
            p_cost = (max(prompt_tokens, 800) / 1_000_000) * p_rate
            c_cost = (max(completion_tokens, 100) / 1_000_000) * c_rate
            total_cost = p_cost + c_cost
            if total_cost > 0:
                cost_str = f"{total_cost:.5f}"
        except Exception as e:
            logger.error(f"Cost calculation error: {e}")
            
        tier = "High" if provider == "openrouter" else "Low"
        transparency_tag = f"\n\n*- 🧠 Antwort generiert von `@{agent_id}` via `{model}` | Tier: `{tier}` | Est. Cost: `{cost_str}$`*"

        # Delegation Engine v2: strukturierte ```delegation```-Blöcke + Legacy-CLI-Interception.
        # Quittungen werden in die Delegator-Session geschrieben -> der Agent "erinnert" sich.
        delegation_receipts = []
        try:
            payloads, invalid_blocks = _parse_delegation_blocks(full_assistant_text)
            # Legacy-Fallback: alte `hermes -p ...`-CLI-Befehle weiterhin abfangen
            for m in re.finditer(r'hermes\s+-p\s+([a-zA-Z0-9_-]+)\s+chat\s+.*?-q\s+["\'](.*?)["\']', full_assistant_text, re.DOTALL):
                mm = re.search(r'-m\s+([a-zA-Z0-9_/.:-]+)', m.group(0))
                payloads.append({
                    "ziel_agent": m.group(1),
                    "auftrag": m.group(2),
                    "modell": mm.group(1) if mm else "",
                    "prioritaet": "normal"
                })
            for payload in payloads:
                try:
                    delegation_receipts.append(_execute_delegation(agent_id, payload, provider, all_keys, origin_session_id=session_id))
                except Exception as de:
                    delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Intern: {de}")
            for bad in invalid_blocks:
                delegation_receipts.append(
                    f"⚠️ DELEGATION-FEHLER — Ungültiger Delegations-Block ({bad['error']}). "
                    f"Der Auftrag wurde NICHT ausgeführt. Block: {bad['raw'][:120]}"
                )
        except Exception as e:
            logger.error(f"Delegation Engine Fehler: {e}")
            delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Engine: {e}")

        if delegation_receipts:
            receipt_text = "\n\n" + "\n".join(delegation_receipts)
            payload = json.dumps({"type": "delta", "delta": receipt_text}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            full_assistant_text += receipt_text

        # Antwort & Metriken in SQLite verbuchen
        # Transparenz-Tag nach Delegationsquittungen ausgeben
        payload_trans = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
        yield f"data: {payload_trans}\n\n"
        full_assistant_text += transparency_tag

        # F-05: Bei Provider-Fehler wird die Fehlermeldung NICHT als
        # Assistenten-Antwort gespeichert und es wird keine Nutzung gebucht.
        if not provider_failed:
            _save_message_to_db(session_id, "assistant", full_assistant_text, completion_tokens)

        # Parse total_cost if possible
        try:
            total_cost_val = float(cost_str)
        except:
            total_cost_val = 0.0

        if not provider_failed:
            _record_session_model_usage(session_id, model, prompt_tokens, completion_tokens, total_cost_val)
        payload_done = json.dumps({"type": "done", "session_id": session_id, "tokens": completion_tokens})
        yield f"data: {payload_done}\n\n"

    return StreamingResponse(chat_event_stream(), media_type="text/event-stream")


class ImageGenerateToolRequest(BaseModel):
    prompt: str
    model: Optional[str] = "google/gemini-2.5-flash-image"
    provider: Optional[str] = "openrouter"
    session_id: Optional[str] = None


@router.post("/api/v1/tools/image_generate")
async def api_tool_image_generate(req: ImageGenerateToolRequest):
    """Führt eine direkte Bildgenerierung über OpenRouter (z.B. Google Nano Banana) oder Bild-Modelle aus."""
    all_keys = api_provider.collect_keys()
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")

    model = (req.model or "google/gemini-2.5-flash-image").strip()
    provider = (req.provider or "openrouter").strip().lower()

    if provider == "openrouter":
        or_key = all_keys.get("OPENROUTER_API_KEY")
        if not or_key:
            raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY fehlt in den Einstellungen.")
        headers = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Archon OS"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail=f"OpenRouter Fehler: {resp.text[:300]}")
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                text = msg.get("content", "")
                images = msg.get("images", [])
                img_url = ""
                if images:
                    first = images[0]
                    img_url = first.get("image_url", {}).get("url") if isinstance(first, dict) else str(first)

                markdown = f"{text}\n\n![{prompt}]({img_url})" if img_url else text
                if req.session_id and img_url:
                    _save_message_to_db(req.session_id, "assistant", markdown)

                return {
                    "status": "ok",
                    "image_url": img_url,
                    "text": text,
                    "markdown": markdown,
                    "model": model
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fehler bei Bildgenerierung: {str(e)}")

    raise HTTPException(status_code=400, detail=f"Provider '{provider}' für Bildgenerierung aktuell nicht unterstützt. Bitte 'openrouter' wählen.")

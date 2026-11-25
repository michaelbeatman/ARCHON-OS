"""Router fuer Agent Run Dispatcher und Direct Agent Chat."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi import Depends as _ArchonDepends
from pydantic import BaseModel

import core_dispatcher
from archon.core.runtime import MEMORY_DIR, WORKSPACE_DIR, add_ticker
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from backend.handoff_desk import mark_truncated

logger = logging.getLogger("archon.routers.agent_chat")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["agent_chat"])


class ChatMessage(BaseModel):
    """D11/MED: strukturierte Chat-Nutzlast statt Freitext-Zerlegung."""

    role: Literal["user", "assistant"]
    content: str


class RunRequest(BaseModel):
    prompt: str


def _as_chat_messages(raw: Any) -> List[ChatMessage]:
    """Validiert Rollen/Reihenfolge maschinell; lehnt unbekannte Rollen ab."""
    if not isinstance(raw, list):
        return []
    result: List[ChatMessage] = []
    for item in raw:
        if isinstance(item, ChatMessage):
            result.append(item)
        elif isinstance(item, dict):
            result.append(ChatMessage.model_validate(item))
        else:
            raise HTTPException(status_code=422, detail={"code": "INVALID_CHAT_MESSAGE"})
    return result


async def fetch_agent_response_api(agent: Dict, user_prompt: str) -> Dict:
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    agent_name = agent["name"]
    model_combo = agent.get("model", "free-forever")
    agent_id = agent["id"]
    agent_role = agent.get("role", "Custom")
    agent_prompt = agent.get("prompt", "")

    start_time = time.time()

    add_ticker(agent_name, f"Leite Anfrage an physischen Container '{agent_id}' weiter (Dispatcher)...")

    prompt_text = user_prompt
    if isinstance(user_prompt, list):
        # D11/MED: Rollen und Reihenfolge bleiben als maschinell auswertbare
        # Struktur erhalten, statt in Verluste-Freitext zerlegt zu werden.
        chat_messages = _as_chat_messages(user_prompt)
        last_user = next((m.content for m in reversed(chat_messages) if m.role == "user"), "")
        prompt_text = last_user or (
            "[STRUKTURIERTER VERLAUF]\n"
            + json.dumps([m.model_dump() for m in chat_messages], ensure_ascii=False)
        )

    try:
        res = await core_dispatcher.dispatch_to_external_agent(
            agent_id=agent_id,
            agent_name=agent_name,
            prompt=prompt_text,
            role=agent_role,
            system_prompt=agent_prompt,
            model=model_combo,
            timeout=30,
        )
    except Exception as e:
        res = {"status": "error", "content": f"Dispatcher Fehler: {str(e)}"}

    duration = time.time() - start_time

    if res.get("status") == "success":
        add_ticker(agent_name, f"Antwort erfolgreich erhalten in {duration:.2f}s")
        try:
            skills_engine = getattr(app_main, "skills_engine", None)
            if skills_engine:
                note_title = f"run_{agent_id}_{int(start_time)}"
                note_content = (
                    f"# Agent Run Log - {agent_name}\n\n"
                    f"- **Agent ID**: {agent_id}\n"
                    f"- **Model**: {model_combo}\n"
                    f"- **Role**: {agent_role}\n"
                    f"- **Timestamp**: {datetime.datetime.now().isoformat()}\n"
                    f"- **Duration**: {duration:.2f}s\n\n"
                    f"## Prompt\n\n```\n{prompt_text}\n```\n\n"
                    f"## Response\n\n```\n{res.get('content', '')}\n```\n"
                )
                skills_engine.obsidian.write_obsidian_note(note_title, note_content, ["run", agent_id, agent_role])
        except Exception as obs_err:
            print(f"Failed to write note to Obsidian: {obs_err}", file=sys.stderr)
    else:
        add_ticker(agent_name, f"Fehler: {res.get('content')}")

    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": res.get("status"),
        "error_code": res.get("error_code"),
        "content": res.get("content"),
        "duration": f"{duration:.2f}s",
        "model": res.get("model") or model_combo,
        "effective_prompt_info": res.get("effective_prompt_info"),
        "prompt_version_info": res.get("prompt_version_info"),
        "trace_id": res.get("trace_id"),
        "session_id": res.get("session_id"),
        "correlation_id": res.get("correlation_id"),
    }


@router.post("/api/run")
async def api_run_parallel(req: RunRequest):
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    agents = app_main.load_agents() if hasattr(app_main, "load_agents") else []
    active_agents = [a for a in agents if a.get("active")]
    if not active_agents:
        raise HTTPException(status_code=400, detail="Keine aktiven Agenten konfiguriert.")

    add_ticker("System", f"Run gestartet für Befehl: '{req.prompt[:40]}'")
    tasks = [fetch_agent_response_api(agent, req.prompt) for agent in active_agents]
    results = await asyncio.gather(*tasks)

    memory = app_main.load_memory() if hasattr(app_main, "load_memory") else []
    memory.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": req.prompt,
        "responses": {
            res["agent_name"]: {
                "model": res["model"],
                "content": res["content"],
                "duration": res["duration"],
                "status": res["status"],
            }
            for res in results
        },
    })
    if hasattr(app_main, "save_memory"):
        app_main.save_memory(memory)
    return results


class DirectAgentChatRequest(BaseModel):
    agent_id: str
    message: str
    attachment_name: Optional[str] = None
    attachment_content: Optional[str] = None
    history: Optional[List[ChatMessage]] = []


_PROFILES_LIST_CACHE: Dict[str, Any] = {"sig": None, "data": []}


def load_profiles_list() -> List[Dict]:
    """Profile-Liste mit mtime-basierter Invalidierung (Audit D08).

    Vorher wurde die ~1 MB große agent_profiles.json bei jeder Chat-Anfrage
    neu geparst. Die Signatur aus Pfad/mtime/size erkennt Änderungen ohne
    Neustart, bleibt aber bei unveränderter Datei ein Cache-Hit.
    """
    from archon.core.provider_registry import get_provider
    app_main = get_provider("app_main")

    _app_root = (
        os.path.dirname(os.path.abspath(app_main.__file__))
        if hasattr(app_main, "__file__")
        else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    for path in [
        os.path.join(_app_root, "agent_profiles.json"),
        "agent_profiles.json",
        "/app/agent_profiles.json",
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        "/app/data/agent_profiles.json",
        os.path.join(WORKSPACE_DIR, "agent_profiles.json"),
    ]:
        if os.path.exists(path):
            try:
                stat = os.stat(path)
                signature = (path, stat.st_mtime_ns, stat.st_size)
                if _PROFILES_LIST_CACHE["sig"] == signature:
                    return _PROFILES_LIST_CACHE["data"]
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    result = data
                elif isinstance(data, dict) and "profiles" in data:
                    result = data["profiles"]
                else:
                    result = []
                _PROFILES_LIST_CACHE["sig"] = signature
                _PROFILES_LIST_CACHE["data"] = result
                return result
            except Exception as _exc:
                logger.debug("[agent_chat] Ignorierte Ausnahme (Z.158): %s", _exc)
    return []


@router.post("/api/v1/agent/chat")
async def api_direct_agent_chat(req: DirectAgentChatRequest):
    from archon.core.profiles import api_get_hermes_profiles
    try:
        profiles = api_get_hermes_profiles()
    except Exception:
        profiles = load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.agent_id), None)
    if not prof:
        fallback_list = load_profiles_list()
        prof = next((p for p in fallback_list if p.get("id") == req.agent_id), None)
    if not prof:
        # D11/HIGH: unbekannte agent_id ist kein "Spezialist" mit erfundenem
        # Prompt/Modell, sondern eine harte Ablehnung ohne jeden Dispatch.
        raise HTTPException(status_code=404, detail={
            "status": "error",
            "code": "UNKNOWN_AGENT_PROFILE",
            "agent_id": req.agent_id,
        })

    from archon.core.profiles import append_negative_scope

    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or "IT-Spezialist & DevOps Auditor"
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Du bist ein praxisorientierter, hochkompetenter IT-Administrator, Systemarchitekt und DevOps-Experte. "
        "Wenn dir Log-Einträge, Fehlermeldungen oder Systemfragen übergeben werden, analysiere die Ursache sofort präzise "
        "und erkläre dem Nutzer Schritt für Schritt, wie das Problem behoben werden kann (inklusive passender Konfigurations- oder Terminal-Befehle)."
    )
    system_prompt = append_negative_scope(system_prompt, prof)

    user_msg = req.message
    if req.attachment_content:
        # D11/MED: keine stille Kuerzung — mark_truncated() setzt einen
        # maschinenlesbaren Marker inkl. Artifact-Referenz.
        attachment = mark_truncated(
            req.attachment_content, 6000, artifact="request.attachment"
        )
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{attachment}\n```\n\n{req.message}"

    # D11/MED: strukturierte History direkt an den Dispatcher (der filtert auf
    # user/assistant). Tote lokale `messages`-Liste entfernt.
    history_payload = [m.model_dump() for m in (req.history or [])[-8:]]

    model_to_use = prof.get("model") or "deepseek/deepseek-chat"
    provider_to_use = prof.get("provider") or "openrouter"

    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=str(agent_name or prof.get("id") or "agent"),
            prompt=user_msg,
            role=prof.get("name", "Spezialist"),
            system_prompt=system_prompt,
            model=model_to_use,
            provider=provider_to_use,
            history=history_payload,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={
            "status": "error", "code": "DISPATCH_FAILED", "message": str(e)
        })

    # D12/HIGH: `blocked`/`error` ist keine Agenten-Antwort. Fehlertexte
    # duerfen nie als Assistant-Reply ausgegeben werden.
    st = str(res.get("status") or "").lower()
    if st != "success":
        raise HTTPException(status_code=403 if st == "blocked" else 502, detail={
            "status": st or "error",
            "code": res.get("error_code") or "DISPATCH_NOT_SUCCESS",
        })
    reply_text = res.get("content", "")
    if not isinstance(reply_text, str) or not reply_text.strip():
        raise HTTPException(status_code=502, detail={
            "status": "error", "code": "EMPTY_RESPONSE"
        })

    duration = round(time.time() - start_t, 2)
    add_ticker("Direct Chat", f"Nachricht an {agent_name} beantwortet ({duration}s)")

    # D11/HIGH: berechnete Werte und Korrelationsfelder duerfen am Endpunkt
    # nicht verworfen werden — nur real vorhandene Werte weitergeben.
    return {
        "status": st,
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "model": res.get("model") or model_to_use,
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "effective_prompt_info": res.get("effective_prompt_info"),
        "prompt_version_info": res.get("prompt_version_info"),
        "trace_id": res.get("trace_id"),
        "session_id": res.get("session_id"),
        "correlation_id": res.get("correlation_id"),
    }

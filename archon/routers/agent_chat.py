"""Router fuer Agent Run Dispatcher und Direct Agent Chat."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import asyncio
import datetime
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import core_dispatcher
from archon.core.runtime import MEMORY_DIR, WORKSPACE_DIR, add_ticker

logger = logging.getLogger("archon.routers.agent_chat")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["agent_chat"])


class RunRequest(BaseModel):
    prompt: str


async def fetch_agent_response_api(agent: Dict, user_prompt: str) -> Dict:
    import main as app_main

    agent_name = agent["name"]
    model_combo = agent.get("model", "free-forever")
    agent_id = agent["id"]
    agent_role = agent.get("role", "Custom")
    agent_prompt = agent.get("prompt", "")

    start_time = time.time()

    add_ticker(agent_name, f"Leite Anfrage an physischen Container '{agent_id}' weiter (Dispatcher)...")

    prompt_text = user_prompt
    if isinstance(user_prompt, list):
        prompt_text = "\n".join([f"{m.get('role', '')}: {m.get('content', '')}" for m in user_prompt])

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
        "content": res.get("content"),
        "duration": f"{duration:.2f}s",
        "model": model_combo,
    }


@router.post("/api/run")
async def api_run_parallel(req: RunRequest):
    import main as app_main

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
    history: Optional[List[Dict[str, Any]]] = []


def load_profiles_list() -> List[Dict]:
    import main as app_main

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
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "profiles" in data:
                        return data["profiles"]
            except Exception:
                pass
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
        prof = {
            "id": req.agent_id,
            "person_name": req.agent_id,
            "name": req.agent_id,
            "system_prompt": "Du bist ein intelligenter KI-Spezialist in Archon OS. Antworte präzise, strukturiert und direkt.",
            "model": "gpt-4o-mini",
        }

    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or "IT-Spezialist & DevOps Auditor"
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Du bist ein praxisorientierter, hochkompetenter IT-Administrator, Systemarchitekt und DevOps-Experte. "
        "Wenn dir Log-Einträge, Fehlermeldungen oder Systemfragen übergeben werden, analysiere die Ursache sofort präzise "
        "und erkläre dem Nutzer Schritt für Schritt, wie das Problem behoben werden kann (inklusive passender Konfigurations- oder Terminal-Befehle)."
    )

    user_msg = req.message
    if req.attachment_content:
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"

    messages = [{"role": "system", "content": system_prompt}]
    if req.history:
        for h in req.history[-8:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})

    model_to_use = prof.get("model") or "deepseek/deepseek-chat"
    provider_to_use = prof.get("provider") or "openrouter"

    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=prof.get("name", "Spezialist"),
            system_prompt=system_prompt,
            model=model_to_use,
            provider=provider_to_use,
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"Fehler bei der Kommunikation mit {agent_name}: {str(e)}"

    duration = round(time.time() - start_t, 2)
    add_ticker("Direct Chat", f"Nachricht an {agent_name} beantwortet ({duration}s)")

    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
    }

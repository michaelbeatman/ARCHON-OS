"""Router fuer Container Execution & Agent Kill-Switch."""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.container_ops")

router = APIRouter(tags=["container_ops"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def send_prompt_to_agent(
    agent_name: str,
    agent_config: dict,
    user_input: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
) -> str:
    """Sendet eine echte HTTP-Anfrage an den lokalen OmniRoute LLM Router (Non-Streaming) mit kontinuierlichem Chat-Kontext."""
    import main as app_main

    role_name = (
        agent_config.get("role", "Orchestrator & System-Architekt")
        if isinstance(agent_config, dict)
        else "Orchestrator & System-Architekt"
    )

    system_prompt = "Du bist ein hilfreicher KI-Assistent."
    all_roles = []
    if hasattr(app_main, "load_roles"):
        try:
            all_roles = app_main.load_roles()
        except Exception:
            all_roles = []
    if not all_roles and hasattr(app_main, "DEFAULT_ROLES"):
        all_roles = app_main.DEFAULT_ROLES

    for r in all_roles:
        if r.get("name") == role_name or r.get("id") == role_name:
            system_prompt = r.get("prompt", system_prompt)
            break

    memory_bridge = getattr(app_main, "memory_bridge", None)
    if memory_bridge:
        try:
            ctx_inj = memory_bridge.get_agent_context_injection(agent_name, limit=3)
            if ctx_inj:
                system_prompt = f"{system_prompt}\n\n{ctx_inj}"
        except Exception:
            pass

    model_name = agent_config.get("model", "auto/best-free") if isinstance(agent_config, dict) else "auto/best-free"
    if model_name == "free-forever":
        model_name = "auto/best-free"

    messages = [{"role": "system", "content": system_prompt}]

    prior_messages = []
    if history and isinstance(history, list):
        for msg in history:
            r = msg.get("role")
            c = msg.get("content")
            if r in ["user", "assistant"] and c:
                prior_messages.append({"role": r, "content": c})
    elif memory_bridge:
        try:
            db_hist = memory_bridge.get_conversation_history(agent_name, limit=16, session_id=session_id)
            for msg in db_hist:
                r = msg.get("role")
                c = msg.get("content")
                if r in ["user", "assistant"] and c:
                    prior_messages.append({"role": r, "content": c})
        except Exception:
            pass

    if len(prior_messages) > 14:
        prior_messages = prior_messages[-14:]
    messages.extend(prior_messages)

    if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != user_input:
        messages.append({"role": "user", "content": user_input})

    headers = {"Content-Type": "application/json", "Authorization": "Bearer omniroute-local-key"}
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
    }

    urls = [
        "http://omniroute:20128/v1/chat/completions",
        "http://localhost:20128/v1/chat/completions",
        "http://127.0.0.1:20128/v1/chat/completions",
        "http://host.docker.internal:20128/v1/chat/completions",
    ]

    last_err = ""
    ai_resp = None
    for url in urls:
        try:
            with httpx.Client(timeout=40.0) as client:
                res = client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    try:
                        data = res.json()
                        if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
                            choice = data["choices"][0]
                            if isinstance(choice, dict) and "message" in choice and "content" in choice["message"]:
                                ai_resp = choice["message"]["content"]
                                break
                        elif isinstance(data, dict) and "response" in data:
                            ai_resp = data["response"]
                            break
                    except Exception:
                        raw_text = res.text
                        lines = [
                            line.replace("data: ", "").strip()
                            for line in raw_text.splitlines()
                            if line.strip() and not line.startswith("event:") and "x-omniroute" not in line
                        ]
                        cleaned = "\n".join(lines)
                        if cleaned:
                            ai_resp = cleaned
                            break
                else:
                    last_err = f"[SYSTEM FEHLER {res.status_code}]: {res.text}"
        except Exception as e:
            last_err = f"[VERBINDUNGSFEHLER]: {e}"

    final_output = ai_resp if ai_resp else (last_err or f"[{agent_name}]: Anweisung empfangen mit Rolle '{role_name}'.")

    if memory_bridge:
        try:
            memory_bridge.record_conversation(agent_name, "user", user_input, session_id=session_id)
            if ai_resp:
                memory_bridge.record_conversation(agent_name, "assistant", ai_resp, session_id=session_id)
        except Exception as e:
            print(f"[QuickChat] Failed to record conversation to DB: {e}", file=sys.stderr)

    return final_output


class ContainerExecRequest(BaseModel):
    container_name: str
    command: str
    history: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None


@router.post("/api/v1/container/exec")
def exec_container_command_api(req: ContainerExecRequest, request: Request):
    _require_admin(request)
    import main as app_main

    load_agent_configs_fn = getattr(app_main, "load_agent_configs", None)
    configs = load_agent_configs_fn() if load_agent_configs_fn else {}
    agent_cfg = configs.get(req.container_name, {})

    if not agent_cfg and hasattr(app_main, "load_agents"):
        try:
            all_a = app_main.load_agents()
            for a in all_a:
                if a.get("id") == req.container_name:
                    agent_cfg = a
                    break
        except Exception:
            pass

    try:
        import jev_router

        if jev_router.is_jev_enabled():
            classification = jev_router.classify_prompt(req.command)
            if classification.get("action") == "direct_command":
                cmd = classification.get("command")
                desc = classification.get("description", "System-Befehl")
                cmd_args = shlex.split(cmd) if isinstance(cmd, str) else cmd
                proc = subprocess.run(cmd_args, shell=False, capture_output=True, text=True, timeout=30)
                out = proc.stdout if proc.stdout else proc.stderr
                return {
                    "exit_code": proc.returncode,
                    "stdout": f"[⚡ JEV Fast-Path: {desc}]\n\n{out.strip() if out else '(Befehl erfolgreich ohne Ausgabe ausgeführt)'}",
                    "stderr": proc.stderr,
                }
    except Exception as e_jev:
        logger.warning(f"JEV Fast-Path Fehler (Fallback auf LLM): {e_jev}")

    send_prompt_fn = getattr(app_main, "send_prompt_to_agent", send_prompt_to_agent)
    output = send_prompt_fn(
        agent_name=req.container_name,
        agent_config=agent_cfg,
        user_input=req.command,
        history=req.history,
        session_id=req.session_id,
    )

    return {
        "exit_code": 0,
        "stdout": output,
        "stderr": "",
    }


@router.post("/api/v1/agent/abort")
def abort_agent_endpoint(payload: dict):
    import main as app_main

    agent_id = payload.get("agent_id") or payload.get("profile") or payload.get("profile_handle", "unknown")
    reason = payload.get("reason", "Manual Kill-Switch Triggered")
    watchdog = getattr(app_main, "watchdog_runner", None)
    if watchdog:
        watchdog.abort_agent_thread(agent_id, reason, {"manual": True, "source": "UI_KILLSWITCH"})
    return {"status": "aborted", "agent": agent_id, "reason": reason}

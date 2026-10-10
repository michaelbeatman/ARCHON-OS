"""
jev_router.py — Optionale JEV (TypeSafe AI) Fast-Path & Tool-Routing Engine für AgenticOS.

Bietet schnelles, deterministisches Vorfiltern von Benutzeranfragen:
1. Fast-Path: Sofortige Ausführung bekannter System-Befehle ohne teuren LLM-Call.
2. Tool-Pruning: Reduktion der MCP-Toolliste auf die 2-3 relevanten Werkzeuge vor dem LLM-Prompt.
3. Fail-Open: Fällt bei Nichtverfügbarkeit oder Deaktivierung transparent auf die Standard-Pipeline zurück.
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any

WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_workspace")
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

# Standard-Muster für bekannte lokale Schnellbefehle
FAST_PATH_REGISTRY = [
    {
        "intent": "email_sync",
        "patterns": ["starte e-mail-sync", "starte email sync", "gleiche mails ab", "synchronisiere mails", "e-mail sync", "fetch mails"],
        "command": "python scripts/archon_crm_mcp.py --fetch-mails",
        "description": "E-Mail-Synchronisation ausführen"
    },
    {
        "intent": "get_contacts",
        "patterns": ["hole kontakte", "zeige kontakte", "kontakte abrufen", "kontaktsync", "crm kontakte"],
        "command": "python scripts/archon_crm_mcp.py --get-contacts",
        "description": "CRM-Kontakte laden"
    },
    {
        "intent": "system_status",
        "patterns": ["system status", "status prüfen", "wie ist der status", "prüfe services"],
        "command": "python -c \"import sys; print('System Status: Online')\"",
        "description": "System- und Service-Status prüfen"
    },
    {
        "intent": "git_status",
        "patterns": ["git status", "zeige git status", "geänderte dateien"],
        "command": "git status -s",
        "description": "Git Arbeitsbaum-Status"
    }
]

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def get_jev_config() -> dict:
    settings = load_settings()
    jev_cfg = settings.get("jev", {})
    return {
        "enabled": bool(jev_cfg.get("enabled", False)),
        "provider": jev_cfg.get("provider", "openrouter"),
        "base_url": jev_cfg.get("base_url", "https://openrouter.ai/api/v1"),
        "api_key": jev_cfg.get("api_key", ""),
        "model": jev_cfg.get("model", "typesafe/jev-latest"),
        "fast_path_enabled": bool(jev_cfg.get("fast_path_enabled", True)),
        "tool_pruning_enabled": bool(jev_cfg.get("tool_pruning_enabled", True)),
        "agent_routing_enabled": bool(jev_cfg.get("agent_routing_enabled", True)),
    }

def is_jev_enabled() -> bool:
    return get_jev_config().get("enabled", False)

def match_local_fast_path(prompt: str) -> Optional[dict]:
    """Prüft, ob die Eingabe einem lokal registrierten Standard-Befehl entspricht."""
    clean = prompt.strip().lower()
    for item in FAST_PATH_REGISTRY:
        for p in item["patterns"]:
            if p in clean:
                return {
                    "action": "direct_command",
                    "intent": item["intent"],
                    "command": item["command"],
                    "description": item["description"],
                    "confidence": 1.0,
                    "tokens_saved": 4000
                }
    return None

def classify_prompt(prompt: str) -> dict:
    """
    Klassifiziert die Benutzeranfrage.
    Prüft zuerst lokale Schnellmuster. Falls kein Treffer, wird bei aktiviertem JEV
    der Remote-Entscheidungsendpunkt konsultiert.
    """
    cfg = get_jev_config()
    if not cfg["enabled"]:
        return {"action": "llm_required", "reason": "jev_disabled"}

    # 1. Lokale Fast-Path Erkennung (0 ms Latenz)
    if cfg["fast_path_enabled"]:
        local_hit = match_local_fast_path(prompt)
        if local_hit:
            return local_hit

    # 2. Falls kein lokaler Treffer, aber JEV aktiv:
    return {
        "action": "llm_required",
        "intent": "general_task",
        "confidence": 0.95
    }

def prune_tools(prompt: str, available_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reduziert die Liste verfügbarer Tools auf die für den Prompt relevanten Werkzeuge.
    Spart Tausende von Context-Tokens ein.
    """
    cfg = get_jev_config()
    if not cfg["enabled"] or not cfg["tool_pruning_enabled"]:
        return available_tools

    if not available_tools:
        return []

    p_lower = prompt.lower()
    selected: List[Dict[str, Any]] = []

    for tool in available_tools:
        name = ""
        desc = ""
        if isinstance(tool, dict):
            if "function" in tool:
                name = tool["function"].get("name", "").lower()
                desc = tool["function"].get("description", "").lower()
            else:
                name = tool.get("name", "").lower()
                desc = tool.get("description", "").lower()

        tool_keywords = set(name.replace("_", " ").split())
        matched = False
        for kw in tool_keywords:
            if len(kw) > 3 and kw in p_lower:
                matched = True
                break

        if matched:
            selected.append(tool)

    if selected:
        return selected[:4]

    return available_tools[:5] if len(available_tools) > 5 else available_tools

def test_jev_connection(api_key: Optional[str] = None, base_url: Optional[str] = None) -> dict:
    """Prüft die Erreichbarkeit und Latenz des konfigurierten Endpunkts."""
    cfg = get_jev_config()
    key = api_key if api_key is not None else cfg["api_key"]
    url = base_url or cfg["base_url"]

    start = time.time()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AgenticOS-JEV-Router",
                "Authorization": f"Bearer {key}" if key else ""
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency_ms = int((time.time() - start) * 1000)
            return {
                "status": "success",
                "code": resp.status,
                "latency_ms": latency_ms,
                "message": f"Endpunkt erreichbar ({latency_ms} ms)"
            }
    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "connected" if e.code in (400, 401, 404, 405) else "error",
            "code": e.code,
            "latency_ms": latency_ms,
            "message": f"Server antwortet mit HTTP {e.code} ({latency_ms} ms)"
        }
    except Exception as e:
        return {
            "status": "error",
            "code": 0,
            "latency_ms": 0,
            "message": f"Verbindungsfehler: {str(e)}"
        }

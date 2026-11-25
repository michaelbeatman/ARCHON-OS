"""
jev_router.py — Optionale JEV (TypeSafe AI) Fast-Path & Tool-Routing Engine für AgenticOS.

Bietet schnelles, deterministisches Vorfiltern von Benutzeranfragen:
1. Fast-Path: Sofortige Ausführung bekannter System-Befehle ohne teuren LLM-Call.
2. Tool-Pruning: Reduktion der MCP-Toolliste auf die 2-3 relevanten Werkzeuge vor dem LLM-Prompt.
3. Fail-Open: Fällt bei Nichtverfügbarkeit oder Deaktivierung transparent auf die Standard-Pipeline zurück.
"""
import logging

_archon_exc_logger = logging.getLogger("jev_router")

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

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
        except Exception as _exc:
            _archon_exc_logger.debug("[jev_router] Ignorierte Ausnahme (Z.53): %s", _exc)
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
            # Lokales Pattern ist echt (0 ms), wird aber nur als Routing-Hinweis
            # genutzt — nicht als simulierter LLM-Erfolg.
            local_hit["demo_only"] = False
            local_hit["mode"] = "local_pattern"
            return local_hit

    # 2. Kein lokaler Treffer: der fruehere "confidence 0.95" war ein
    # fest verdrahteter Platzhalter, kein echter JEV-Remote-Entscheid.
    # Explizit als Demo kennzeichnen statt Erfolg vorzutaeuschen.
    return {
        "action": "llm_required",
        "intent": "general_task",
        "confidence": 0.0,
        "demo_only": True,
        "mode": "heuristic_demo",
        "reason": "no_remote_jev_decision_available",
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
    cfg_url = str(cfg.get("base_url") or "").rstrip("/")
    req_url = str(base_url or "").rstrip("/")
    is_custom_url = bool(req_url and req_url != cfg_url)
    # Keine Key-Exfiltration: Gespeicherten API-Key niemals an eine abweichende Test-URL senden.
    if api_key is not None and api_key != "***":
        key = api_key
    elif is_custom_url:
        key = ""
    else:
        key = cfg["api_key"]
    url = base_url or cfg["base_url"]

    start = time.time()
    try:
        # W4-B/D06: niemals rohes urlopen() — das folgt 3xx automatisch und
        # wuerde eine vorher validierte Public-URL auf IMDS/localhost umlenken.
        # safe_http_request() blockiert ALLE Redirects, pinnt die gepruefte IP
        # und begrenzt die Antwortgroesse. Die Eingangs-URL wird dabei erneut
        # gegen Egress-Regeln geprueft (kein Vertrauen in den Aufrufer).
        from utils.safe_http import safe_http_request

        headers = {"User-Agent": "AgenticOS-JEV-Router"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        status_code, _resp_headers, _body = safe_http_request(
            str(url or ""),
            method="GET",
            headers=headers,
            timeout=5,
            max_bytes=64 * 1024,
            public_only=True,
        )
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "success",
            "code": int(status_code),
            "latency_ms": latency_ms,
            "message": f"Endpunkt erreichbar ({latency_ms} ms)"
        }
    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - start) * 1000)
        # Der Redirect-Blocker wirft HTTPError mit dem 3xx-Status. Alles andere
        # ist eine echte Server-Antwort und bleibt wie zuvor 'connected'/'error'.
        if int(e.code) in (301, 302, 303, 307, 308):
            return {
                "status": "blocked",
                "error_code": "REDIRECT_BLOCKED",
                "code": int(e.code),
                "latency_ms": latency_ms,
                "message": f"HTTP-Redirect ({e.code}) aus SSRF-Schutzgruenden blockiert."
            }
        return {
            "status": "connected" if e.code in (400, 401, 404, 405) else "error",
            "code": e.code,
            "latency_ms": latency_ms,
            "message": f"Server antwortet mit HTTP {e.code} ({latency_ms} ms)"
        }
    except Exception as e:
        from utils.egress_guard import EgressBlocked

        if isinstance(e, EgressBlocked):
            return {
                "status": "blocked",
                "error_code": "EGRESS_BLOCKED",
                "code": 400,
                "latency_ms": int((time.time() - start) * 1000),
                "message": f"JEV-Ziel aus Egress-Schutzgruenden blockiert: {e}"
            }
        return {
            "status": "error",
            "code": 0,
            "latency_ms": 0,
            "message": f"Verbindungsfehler: {str(e)}"
        }

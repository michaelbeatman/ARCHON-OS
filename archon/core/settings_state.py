"""Zustands- und Persistenz-Helfer fuer UI-Konfiguration, Agenten, Rollen, Services und Themes."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from archon.core.cache import invalidate as invalidate_ttl_cache, ttl_cache
from archon.core.paths import (
    AGENTS_FILE,
    COUPLED_AGENTS_FILE,
    MEMORY_FILE,
    ROLES_FILE,
    SERVICES_FILE,
    THEME_FILE,
    WORKSPACE_DIR,
)
from archon.core.profiles import restore_data_uri_avatars
from archon.core.roles_data import DEFAULT_ROLES
from archon.core.runtime import _load_json, _save_json

logger = logging.getLogger("archon.core.settings_state")

DEFAULT_AGENTS = [
    {
        "id": "hermes-orchestrator",
        "name": "Hermes Master Orchestrator",
        "role": "System-Architekt & Paperclip Lead",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe",
    },
    {
        "id": "hermes-researcher",
        "name": "Hermes Deep Researcher",
        "role": "Web-Scraping, Markt- & SEO-Analysen",
        "model": "omniroute/free-forever",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe",
    },
    {
        "id": "hermes-coder",
        "name": "Hermes Senior Coder",
        "role": "Fullstack Software Engineer & Dev",
        "model": "omniroute/deepseek-coder",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe",
    },
    {
        "id": "hermes-odysseus",
        "name": "Hermes Odysseus Strategist",
        "role": "Business Strategy & Second Brain Vault",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe",
    },
]

DEFAULT_SERVICES = [
    {
        "id": "omniroute",
        "name": "OmniRoute AI Gateway",
        "description": "Multi-LLM & Gateway Proxy Router",
        "active": True,
        "model": "free-forever",
        "role": "Gateway",
        "port": 20128,
    },
    {
        "id": "hermes",
        "name": "Hermes Engine & WebUI",
        "description": "Universelle Multi-Profile Agent Engine",
        "active": True,
        "model": "free-forever",
        "role": "Orchestrator",
        "port": 8787,
    },
    {
        "id": "hermes-dashboard",
        "name": "Hermes Control Dashboard",
        "description": "Hermes Telemetrie & Performance Monitor",
        "active": True,
        "model": "free-forever",
        "role": "Telemetry",
        "port": 9119,
    },
    {
        "id": "crm",
        "name": "CRM & LinkedIn Hub",
        "description": "Kontakt-Management & Outreach System",
        "active": True,
        "model": "free-forever",
        "role": "CRM",
        "port": 3005,
    },
    {
        "id": "open-webui",
        "name": "Open WebUI",
        "description": "Schneller LLM-Chat Fallback",
        "active": True,
        "model": "free-forever",
        "role": "Chat Fallback",
        "port": 8082,
    },
    {
        "id": "pocketbase",
        "name": "Pocketbase Storage",
        "description": "Echtzeit-Datenbank & Auth System",
        "active": True,
        "model": "free-forever",
        "role": "Database",
        "port": 8090,
    },
    {
        "id": "n8n",
        "name": "n8n Automatisierung",
        "description": "Workflow- & Integrations-Automatisierung",
        "active": True,
        "model": "free-forever",
        "role": "Automation",
        "port": 5678,
    },
]

GHOST_AGENT_IDS = {"prime-agent", "autogen-studio", "openhands", "openclaw", "gpt-researcher", "a-01", "a-02"}
SYSTEM_INTERNAL_IDS = {"agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"}


def load_agents() -> List[Dict]:
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    if os.path.exists(agents_root):
        loaded = _load_json(agents_root, DEFAULT_AGENTS)
    elif os.path.exists(AGENTS_FILE):
        loaded = _load_json(AGENTS_FILE, DEFAULT_AGENTS)
    else:
        loaded = DEFAULT_AGENTS
    cleaned = [a for a in loaded if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    return cleaned if len(cleaned) > 0 else DEFAULT_AGENTS


def save_agents(agents: List[Dict]):
    existing = load_agents()
    # M-16: Inaktive und interne System-Agenten duerfen nicht geloescht werden,
    # wenn ein Frontend (z.B. skill_markt.js) nur ein gefiltertes Array sendet.
    incoming_ids = {str(a.get("id")) for a in agents if a.get("id")}
    preserved = [
        a
        for a in existing
        if str(a.get("id")) not in incoming_ids
        and (a.get("active") is False or str(a.get("id", "")).lower() in SYSTEM_INTERNAL_IDS)
    ]
    merged = preserved + list(agents)
    cleaned = [a for a in merged if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    _save_json(agents_root, cleaned)
    _save_json(AGENTS_FILE, cleaned)

    # M-18: Sync zu agent_profiles.json (SSOT fuer Hermes und Chat)
    try:
        from archon.core.profiles import invalidate_hermes_profiles_cache
        from archon.core.runtime import APP_ROOT, atomic_write_json

        ssot_file = os.path.join(APP_ROOT, "agent_profiles.json")
        if os.path.exists(ssot_file):
            with open(ssot_file, "r", encoding="utf-8") as f:
                p_list = json.load(f)
            if isinstance(p_list, list):
                incoming_map = {str(a.get("id")): a for a in agents if a.get("id")}
                updated = False
                for p in p_list:
                    pid = str(p.get("id"))
                    if pid in incoming_map:
                        inc = incoming_map[pid]
                        for fld in ("name", "role", "model", "provider", "system_prompt"):
                            if fld in inc and inc[fld]:
                                p[fld] = inc[fld]
                                updated = True
                if updated:
                    atomic_write_json(ssot_file, p_list)
                    invalidate_hermes_profiles_cache()
    except Exception:
        pass


@ttl_cache(seconds=60)
def load_roles() -> List[Dict]:
    return _load_json(ROLES_FILE, DEFAULT_ROLES)


def save_roles(roles: List[Dict]):
    # Rueckweg zum GET: das Frontend postet die materialisierte Antwort
    # unveraendert zurueck. Ohne diese Umkehrung stuenden /static-Pfade in
    # roles.json und die data-URI (einzige Kopie fuer Rollen ohne Profil)
    # waere verloren. Vorlage ist der Stand, der gleich ueberschrieben wird:
    # nur Pfade, die aus genau diesem data-URI entstehen, werden zurueckgedreht.
    vorher = _load_json(ROLES_FILE, [])
    _save_json(ROLES_FILE, restore_data_uri_avatars(roles, vorher))
    # Invalidierung an der Schreibstelle: der naechste Leser sieht die Aenderung
    # sofort statt erst nach Ablauf der TTL.
    invalidate_ttl_cache(load_roles)


def load_services() -> List[Dict]:
    if os.path.exists(COUPLED_AGENTS_FILE):
        return _load_json(COUPLED_AGENTS_FILE, DEFAULT_SERVICES)
    return _load_json(SERVICES_FILE, DEFAULT_SERVICES)


def save_services(services: List[Dict]):
    _save_json(SERVICES_FILE, services)
    os.makedirs(os.path.join(WORKSPACE_DIR, "config"), exist_ok=True)
    _save_json(COUPLED_AGENTS_FILE, services)


def load_memory() -> List[Dict]:
    return _load_json(MEMORY_FILE, [])


def save_memory(memory_data: List[Dict]):
    _save_json(MEMORY_FILE, memory_data)


def load_theme() -> Dict:
    return _load_json(THEME_FILE, {})


def save_theme(theme_data: Dict):
    _save_json(THEME_FILE, theme_data)

"""Router fuer Core Settings, Ticker, Agents & Roles."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from archon.core.profiles import materialize_role_avatars
from archon.core.paths import ROLES_FILE, SETTINGS_FILE
from backend.platform_paths import OBSIDIAN_VAULT
from archon.core.runtime import (
    WORKSPACE_DIR,
    _load_json,
    _save_json,
    ticker_entries,
)

logger = logging.getLogger("archon.routers.core_settings")

router = APIRouter(tags=["core_settings"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


@router.get("/api/settings")
async def get_settings(request: Request):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        import main as app_main
        return await app_main.forward_to_hermes(request)

    s = _load_json(SETTINGS_FILE, {})
    gw_url = s.get("gateway_url") if isinstance(s, dict) else None
    if not gw_url:
        gw_url = "http://localhost:20128/v1"
    jev_cfg = s.get("jev", {}) if isinstance(s, dict) else {}
    mem_cfg = s.get("memory", {
        "enabled": True,
        "auto_learn": True,
        "apply_lessons": True,
        "max_injected_lessons": 3,
        "half_life_days": 14,
        "auto_evict": False,
        "eviction_threshold": 0.1,
        "vault_path": OBSIDIAN_VAULT,
        "daily_consolidation": True,
        "hours_back": 24,
    }) if isinstance(s, dict) else {}
    email_guard_cfg = s.get("email_guard", {
        "enabled": True,
        "protect_email": True,
        "protect_telegram": True,
        "protect_crm": True,
        "sensitivity": "moderate",
        "use_llm": False,
        "model": "omniroute/free-forever",
    }) if isinstance(s, dict) else {}
    validate_cfg = s.get("validate", {
        "enabled": True,
        "min_score": 7,
        "on_failure": "warn",
        "check_hallucinations": True,
        "check_cutoff": True,
        "use_llm": False,
        "judge_model": "omniroute/free-forever",
    }) if isinstance(s, dict) else {}
    return {
        "gateway_url": gw_url,
        "workspace_dir": WORKSPACE_DIR,
        "jev": jev_cfg,
        "memory": mem_cfg,
        "email_guard": email_guard_cfg,
        "validate": validate_cfg,
    }


@router.post("/api/settings")
async def api_save_settings(request: Request, settings: Dict = Body(None)):
    _require_admin(request)
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        import main as app_main
        return await app_main.forward_to_hermes(request)

    current = _load_json(SETTINGS_FILE, {})
    if isinstance(current, dict) and isinstance(settings, dict):
        current.update(settings)
        _save_json(SETTINGS_FILE, current)
    elif settings is not None:
        _save_json(SETTINGS_FILE, settings)
    try:
        from backend.audit_log import chained_audit_log
        keys_changed = list(settings.keys()) if isinstance(settings, dict) else ["all"]
        chained_audit_log.record_event(
            category="config",
            action="settings_saved",
            agent_id="operator",
            payload={"changed_keys": keys_changed},
        )
    except Exception:
        pass
    return {"status": "success"}


@router.get("/api/ticker")
def get_ticker():
    return {"entries": ticker_entries}


@router.post("/api/ticker/clear")
def clear_ticker():
    # .clear() statt Neuzuweisung: die Liste wird mit archon.core.runtime geteilt
    ticker_entries.clear()
    return {"status": "cleared"}


@router.get("/api/agents")
def api_get_agents():
    import main as app_main
    agents = app_main.load_agents()
    try:
        from archon.core.profiles import api_get_hermes_profiles
        profiles_list = api_get_hermes_profiles()
        p_map = {p.get("id"): p for p in profiles_list if isinstance(p, dict) and p.get("id")}
        for a in agents:
            aid = a.get("id")
            if aid in p_map:
                prof = p_map[aid]
                if not a.get("avatar_url") and prof.get("avatar_url"):
                    a["avatar_url"] = prof["avatar_url"]
                if "runtime_status" not in a and "runtime_status" in prof:
                    a["runtime_status"] = prof["runtime_status"]
    except Exception:
        pass
    return agents


@router.post("/api/agents")
def api_save_agents(request: Request, agents: List[Dict]):
    _require_admin(request)
    import main as app_main
    app_main.save_agents(agents)
    return {"status": "success"}


@router.get("/api/roles")
def api_get_roles():
    import main as app_main
    return materialize_role_avatars(app_main.load_roles())


@router.post("/api/roles")
def api_save_roles(request: Request, roles: List[Dict]):
    _require_admin(request)
    import main as app_main
    app_main.save_roles(roles)
    return {"status": "success"}

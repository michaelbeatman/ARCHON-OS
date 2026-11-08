"""Router fuer Research Lab (Deep Research, Quellen, Dossiers)."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("archon.routers.research")

router = APIRouter(prefix="/api/v1/research", tags=["research"])


@router.get("/providers")
def api_get_research_providers():
    import main as app_main
    import research_engine

    settings = app_main._load_json(app_main.SETTINGS_FILE, {})
    return {
        "status": "success",
        "providers": research_engine.get_available_providers(settings),
    }


@router.post("/run")
def api_run_research_mission(payload: dict):
    import main as app_main
    import research_engine

    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(
            status_code=400, detail="Query darf nicht leer sein."
        )
    profile = payload.get("profile", "deep")
    engines = payload.get(
        "engines", ["duckduckgo", "grokipedia", "wikipedia", "arxiv"]
    )
    depth = int(payload.get("depth", 3))
    adversarial = bool(payload.get("adversarial", True))
    export_obsidian = bool(payload.get("export_obsidian", True))
    model = payload.get("model", "omniroute/free-forever")
    agent_role = payload.get("agent_role", "Lead Research Analyst")
    settings = app_main._load_json(app_main.SETTINGS_FILE, {})
    vault_path = settings.get("memory", {}).get(
        "vault_path", app_main.OBSIDIAN_VAULT
    )
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")

    use_reflect = (
        bool(payload.get("reflect")) or payload.get("mode") == "reflect"
    )
    if use_reflect:
        import research_engine_v2

        return research_engine_v2.run_research_mission_reflect(
            query=query,
            profile=profile,
            engines=engines,
            depth=depth,
            adversarial=adversarial,
            export_obsidian=export_obsidian,
            vault_path=vault_path,
            workspace_dir=workspace_dir,
            settings=settings,
            model=model,
            agent_role=agent_role,
            fast_model=payload.get("fast_model") or None,
            max_rounds=int(payload.get("max_rounds", 3)),
            max_pages=int(payload.get("max_pages", 4)),
        )
    res = research_engine.run_research_mission(
        query=query,
        profile=profile,
        engines=engines,
        depth=depth,
        adversarial=adversarial,
        export_obsidian=export_obsidian,
        vault_path=vault_path,
        workspace_dir=workspace_dir,
        settings=settings,
        model=model,
        agent_role=agent_role,
    )
    return res


@router.get("/history")
def api_get_research_history():
    import main as app_main
    import research_engine

    settings = app_main._load_json(app_main.SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    items = research_engine.list_research_history(workspace_dir)
    return {"status": "success", "dossiers": items}


@router.get("/dossier/{filename}")
def api_get_research_dossier(filename: str):
    import main as app_main

    settings = app_main._load_json(app_main.SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    safe_name = os.path.basename(filename)
    fpath = os.path.join(workspace_dir, "research", safe_name)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Dossier nicht gefunden.")
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"status": "success", "filename": safe_name, "content": content}


@router.get("/sources")
def api_get_research_sources():
    from backend.research_sources import TRUST_TIERS, get_curated_sources_pool

    return {
        "status": "success",
        "sources": get_curated_sources_pool(),
        "trust_tiers": TRUST_TIERS,
    }

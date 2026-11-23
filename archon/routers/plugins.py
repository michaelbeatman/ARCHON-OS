from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Router /api/v1/plugins — ausgelagerte Routen (Modularisierung main.py -> archon/routers)."""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile

from archon.routers._rbac import require_admin_or_503, get_session_actor
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR, APP_ROOT,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json, atomic_write_json,
)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])

@router.get("/api/v1/plugins")
def api_list_plugins():
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    return {"status": "success", "plugins": pm.list_plugins_summary()}


@router.post("/api/v1/plugins/{plugin_id}/toggle")
def api_toggle_plugin(request: Request, plugin_id: str, payload: dict = Body(default={})):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail={"code": "plugins_plugin_not_found", "params": {"plugin_id": plugin_id}})
    enable = payload.get("enable")
    if enable is None:
        enable = not plugin.enabled
    if enable:
        pm.enable_plugin(plugin_id)
    else:
        pm.disable_plugin(plugin_id)
    return {"status": "success", "plugin_id": plugin_id, "enabled": plugin.enabled}


@router.post("/api/v1/plugins/{plugin_id}/reload")
def api_reload_plugin(request: Request, plugin_id: str):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    success = pm.reload_plugin(plugin_id)
    if not success:
        raise HTTPException(status_code=400, detail={"code": "plugins_reload_failed", "params": {"plugin_id": plugin_id}})
    return {"status": "success", "message": f"Plugin '{plugin_id}' erfolgreich neu geladen."}


@router.get("/api/v1/plugins/{plugin_id}/config")
def api_get_plugin_settings(request: Request, plugin_id: str):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail={"code": "plugins_plugin_not_found_2", "params": {"plugin_id": plugin_id}})
    return {
        "status": "success",
        "plugin_id": plugin_id,
        "config": plugin.config,
        "schema": plugin.manifest.get("settings_schema", {})
    }


@router.post("/api/v1/plugins/{plugin_id}/config")
def api_save_plugin_settings(request: Request, plugin_id: str, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    plugin = pm.plugins.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail={"code": "plugins_plugin_not_found_3", "params": {"plugin_id": plugin_id}})
    success = plugin.save_config(payload)
    return {"status": "success" if success else "error", "config": plugin.config}


@router.post("/api/v1/plugins/discover")
def api_discover_plugins(request: Request):
    require_admin_or_503(request)
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    pm.load_all_plugins()
    return {"status": "success", "plugins": pm.list_plugins_summary()}


@router.get("/api/v1/plugins/tools")
def api_get_plugin_tools():
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    return {"status": "success", "tools": pm.get_all_exported_tools()}


@router.post("/api/v1/plugins/tools/execute")
async def api_execute_plugin_tool(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    from backend.plugin_manager import get_plugin_manager
    from backend.tool_runtime import enforce_tool_execution, guard_result, record_tool_read_side_effect
    pm = get_plugin_manager()
    tool_name = str(payload.get("tool_name") or "").strip()
    args = payload.get("args", {})
    # Actor/Session/Agent aus der authentifizierten Identität — nie aus dem
    # Body. Ein client-gesteuertes agent_id umgeht agentenbezogene Taint-/RBAC-
    # und Budget-Gates (Audit 23.11.2026).
    session_id = f"user:{get_session_actor(request)}"
    agent_id = session_id
    approval_id = payload.get("approval_id")
    # Warrant ausschließlich aus dem serverseitigen Registry, nie aus dem Body.
    from backend.tool_warrants import get_warrant_for_session
    warrant = get_warrant_for_session(session_id, tool_name)
    if not tool_name:
        raise HTTPException(status_code=400, detail={"code": "plugins_tool_name_required", "params": {}})
    gate = enforce_tool_execution(
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
    )
    if not gate.get("allowed"):
        raise HTTPException(status_code=403, detail=gate)
    try:
        res = await pm.execute_plugin_tool(tool_name, args)
        record_tool_read_side_effect(session_id, tool_name)
        # F10: Plugin-Output vor der Rueckgabe durch den Firewall-Chokepoint.
        return {"status": "success", "result": guard_result(tool_name, res)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

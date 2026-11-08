"""Router fuer Inbox Watcher und Robert Tool Permissions (Batch 3)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, Optional

from fastapi import APIRouter, Body, Request

logger = logging.getLogger("archon.routers.inbox_tools")

router = APIRouter(tags=["inbox_tools"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


@router.get("/api/inbox-watcher/config")
def api_get_inbox_watcher_config():
    from backend.inbox_watcher import get_inbox_config

    cfg = get_inbox_config()
    watch_dir = cfg.get("watch_folder")
    exists = os.path.exists(watch_dir) if watch_dir else False
    file_count = len(os.listdir(watch_dir)) if exists else 0
    return {"status": "success", "config": cfg, "folder_exists": exists, "file_count": file_count}


@router.post("/api/inbox-watcher/config")
async def api_save_inbox_watcher_config(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.inbox_watcher import get_inbox_config, save_inbox_config

    current = get_inbox_config()
    current.update(payload)
    ok = save_inbox_config(current)
    return {"status": "success" if ok else "error", "config": current}


@router.post("/api/inbox-watcher/scan-now")
async def api_scan_inbox_watcher_now():
    from backend.inbox_watcher import scan_and_process_inbox

    res = await scan_and_process_inbox()
    try:
        from backend.internet_watchdog import run_watchdog_scan

        loop = asyncio.get_event_loop()
        wd_res = await loop.run_in_executor(None, run_watchdog_scan, True)
        res["internet_watchdog"] = wd_res
    except Exception as e:
        res["internet_watchdog_error"] = str(e)
    return res


@router.get("/api/tools/proposals")
def api_list_tool_proposals(status: Optional[str] = None):
    from backend.tool_permission_manager import tool_permission_manager

    return {"status": "success", "proposals": tool_permission_manager.list_proposals(status=status)}


@router.post("/api/tools/proposals")
def api_create_tool_proposal(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.tool_permission_manager import tool_permission_manager

    return tool_permission_manager.propose_tool_installation(
        tool_name=payload.get("tool_name", ""),
        tool_type=payload.get("tool_type", "pip"),
        reason=payload.get("reason", ""),
        command=payload.get("command"),
        requested_by=payload.get("requested_by", "Robert (Lead Orchestrator)"),
    )


@router.post("/api/tools/proposals/{permission_id}/resolve")
def api_resolve_tool_proposal(request: Request, permission_id: str, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.tool_permission_manager import tool_permission_manager

    action = payload.get("action", "grant")
    return tool_permission_manager.resolve_proposal(permission_id, action=action)

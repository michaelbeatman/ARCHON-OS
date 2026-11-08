"""Router /api/contracts — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

from archon.routers._rbac import require_admin_or_503

router = APIRouter()

@router.get("/api/contracts")
@router.get("/api/v1/contracts")
def api_list_contracts(category: Optional[str] = None, status: Optional[str] = None, sort_by: str = "deadline"):
    from backend.contract_manager import ContractManager
    return {"status": "success", "contracts": ContractManager.list_contracts(category=category, status=status, sort_by=sort_by)}


@router.get("/api/contracts/stats")
@router.get("/api/v1/contracts/stats")
def api_contract_stats():
    from backend.contract_manager import ContractManager
    return {"status": "success", "stats": ContractManager.get_stats()}


@router.get("/api/contracts/{contract_id}")
@router.get("/api/v1/contracts/{contract_id}")
def api_get_contract(contract_id: str):
    from backend.contract_manager import ContractManager
    c = ContractManager.get(contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden.")
    return {"status": "success", "contract": c}


@router.post("/api/contracts")
@router.post("/api/v1/contracts")
def api_save_contract(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.contract_manager import ContractManager
    saved = ContractManager.create_or_update(payload)
    return {"status": "success", "contract": saved}


@router.delete("/api/contracts/{contract_id}")
@router.delete("/api/v1/contracts/{contract_id}")
def api_delete_contract(request: Request, contract_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.contract_manager import ContractManager
    deleted = ContractManager.delete(contract_id)
    return {"status": "success" if deleted else "not_found", "deleted": deleted}


@router.post("/api/contracts/parse")
@router.post("/api/v1/contracts/parse")
def api_parse_contract(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.contract_manager import ContractParser
    text = payload.get("text", "")
    parsed = ContractParser.parse(text)
    return {"status": "success", "parsed": parsed}


@router.post("/api/contracts/scan-deadlines")
@router.post("/api/v1/contracts/scan-deadlines")
def api_scan_contract_deadlines(request: Request, payload: dict = Body(default={})):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.contract_manager import ContractManager
    send_telegram = payload.get("send_telegram", True)
    create_kanban = payload.get("create_kanban_task", True)
    alerts = ContractManager.scan_and_alert_deadlines(send_telegram=send_telegram, create_kanban_task=create_kanban)
    return {"status": "success", "alerts_triggered": alerts, "count": len(alerts)}


@router.post("/api/contracts/{contract_id}/renew")
@router.post("/api/v1/contracts/{contract_id}/renew")
def api_renew_contract(request: Request, contract_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.contract_manager import ContractManager
    renewed = ContractManager.renew_contract(contract_id)
    if not renewed:
        raise HTTPException(status_code=404, detail="Vertrag konnte nicht verlängert werden.")
    return {"status": "success", "contract": renewed}


@router.post("/api/contracts/create")
def api_create_contract(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return sla_contract_enforcer.create_contract(
        task_id=payload.get("task_id", "task-sla"),
        delegator_agent=payload.get("delegator", "agent-lead"),
        assignee_agent=payload.get("assignee", "agent-worker"),
        required_keys=payload.get("required_keys"),
        min_content_length=int(payload["min_content_length"]) if "min_content_length" in payload else None,
        acceptance_criteria=payload.get("acceptance_criteria"),
        max_turnaround_minutes=int(payload["max_turnaround_minutes"]) if "max_turnaround_minutes" in payload else None
    )


@router.post("/api/contracts/validate")
def api_validate_contract(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return sla_contract_enforcer.validate_delivery(
        contract_id=payload.get("contract_id", ""),
        delivery_payload=payload.get("delivery", {})
    )


@router.get("/api/contracts/history")
def api_get_contracts_history(limit: int = 25):
    from backend.sla_contract_enforcer import sla_contract_enforcer
    return {"status": "success", "contracts": sla_contract_enforcer.list_contracts(limit=limit)}

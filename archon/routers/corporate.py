"""Router /api/corporate — ausgelagerte Routen.

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

@router.get("/api/corporate/companies")
def api_list_corporate_companies():
    from backend.corporate_manager import corporate_manager
    return {"companies": corporate_manager.list_companies()}


@router.get("/api/corporate/companies/{company_id}")
def api_get_corporate_company(company_id: str):
    from backend.corporate_manager import corporate_manager
    comp = corporate_manager.get_company(company_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Company not found")
    return comp


@router.post("/api/corporate/companies")
def api_save_corporate_company(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.corporate_manager import corporate_manager
    saved = corporate_manager.save_company(payload)
    return {"success": True, "company": saved}


@router.post("/api/corporate/companies/{company_id}/set-active")
def api_set_active_corporate_company(request: Request, company_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.corporate_manager import corporate_manager
    success = corporate_manager.set_active_company(company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"success": True, "active_company_id": company_id}


@router.delete("/api/corporate/companies/{company_id}")
def api_delete_corporate_company(request: Request, company_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.corporate_manager import corporate_manager
    success = corporate_manager.delete_company(company_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete active or only existing company")
    return {"success": True, "deleted_id": company_id}


@router.post("/api/corporate/render-template")
def api_render_corporate_template(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.corporate_manager import corporate_manager
    template_type = payload.get("template_type", "letterhead")
    company_id = payload.get("company_id")
    custom = payload.get("custom", {})
    result = corporate_manager.render_template(template_type=template_type, company_id=company_id, custom=custom)
    return result

from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
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
from archon.routers._validated_body import TypedBody, PassthroughBody, as_payload

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class CorporateCompanyBody(PassthroughBody):
    pass


class CorporateTemplateBody(TypedBody):
    template_type: str = "letterhead"
    company_id: str = ""
    custom: dict = {}


class CorporateLayoutBody(TypedBody):
    template_type: str = "letterhead"
    company_id: str = ""
    layout: dict = {}

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
def api_save_corporate_company(request: Request, payload: CorporateCompanyBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    payload = as_payload(payload)
    from backend.corporate_manager import corporate_manager
    saved = corporate_manager.save_company(payload)
    return {"success": True, "company": saved}


@router.post("/api/corporate/companies/{company_id}/set-active")
def api_set_active_corporate_company(request: Request, company_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    # D03/HIGH: kein zweiter, unauditierter Umschalter. Der zentrale
    # TenantContextManager.switch_tenant() macht GoBD-Audit, Rollback,
    # ensure_tenant_databases() und SSE-Event.
    from archon.routers._rbac import require_session_actor
    from backend.tenant_context import tenant_context
    actor = require_session_actor(request)
    try:
        result = tenant_context.switch_tenant(company_id, actor=actor)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"tenant_switch_failed: {exc}")
    if not result or not result.get("success", True):
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
def api_render_corporate_template(request: Request, payload: CorporateTemplateBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    payload = as_payload(payload)
    from backend.corporate_manager import corporate_manager
    template_type = payload.get("template_type", "letterhead")
    company_id = payload.get("company_id")
    custom = payload.get("custom", {})
    try:
        result = corporate_manager.render_template(template_type=template_type, company_id=company_id, custom=custom)
    except ValueError as verr:
        # R-21: explizit angefragte, unbekannte Company darf nicht still die
        # Stammdaten einer anderen Rechtsperson drucken.
        raise HTTPException(status_code=404, detail=str(verr))
    return result


@router.get("/api/corporate/template-layout")
def api_get_corporate_template_layout(
    template_type: str = Query("letterhead"),
    company_id: Optional[str] = Query(None),
):
    from backend.corporate_manager import corporate_manager
    try:
        layout = corporate_manager.get_template_layout(company_id=company_id, template_type=template_type)
    except ValueError as verr:
        raise HTTPException(status_code=404, detail=str(verr))
    return {"status": "ok", "template_type": template_type, "company_id": company_id, "layout": layout}


@router.post("/api/corporate/template-layout")
def api_save_corporate_template_layout(request: Request, payload: CorporateLayoutBody = Body(...)):
    require_admin_or_503(request)
    payload = as_payload(payload)
    from backend.corporate_manager import corporate_manager
    template_type = str(payload.get("template_type") or "letterhead")
    company_id = payload.get("company_id")
    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    try:
        saved = corporate_manager.save_template_layout(
            company_id=company_id,
            template_type=template_type,
            layout=layout,
        )
    except ValueError as verr:
        raise HTTPException(status_code=404, detail=str(verr))
    return {"status": "ok", "template_type": template_type, "company_id": company_id, "layout": saved}


@router.post("/api/corporate/render-pdf")
def api_render_corporate_template_pdf(request: Request, payload: CorporateTemplateBody = Body(...)):
    require_admin_or_503(request)
    payload = as_payload(payload)
    from backend.corporate_manager import corporate_manager
    from backend.erp_zugferd_pdf import build_corporate_template_pdf
    template_type = str(payload.get("template_type") or "letterhead")
    company_id = payload.get("company_id")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else {}
    try:
        rendered = corporate_manager.render_template(
            template_type=template_type,
            company_id=company_id,
            custom=custom,
        )
        pdf_bytes = build_corporate_template_pdf(rendered)
    except ValueError as verr:
        raise HTTPException(status_code=404, detail=str(verr))
    doc_num = re.sub(
        r"[^a-zA-Z0-9._-]+",
        "_",
        str((rendered.get("pdf_meta") or {}).get("doc_number") or template_type),
    ).strip("_") or "beleg"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="archon-{doc_num}.pdf"',
            "Cache-Control": "no-store",
        },
    )

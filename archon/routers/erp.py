"""Router /api/erp — ausgelagerte Routen.

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

@router.get("/api/erp/documents/{doc_id}/print", response_class=HTMLResponse)
def api_erp_document_print(
    doc_id: str,
    company_id: Optional[str] = None,
    autoprint: bool = False,
    doc_type: Optional[str] = None,
    entity_name: Optional[str] = None,
    amount_net: Optional[float] = None
):
    from backend.corporate_manager import corporate_manager
    from backend.erp_manager import erp_manager
    doc = erp_manager.get_document(doc_id, company_id=company_id)
    tmpl_type = "invoice"
    custom: Dict[str, Any] = {"document_id": doc_id}
    
    if doc:
        raw_type = doc.get("doc_type", "invoice")
        if raw_type in ("offer", "ang"):
            tmpl_type = "offer"
        elif raw_type in ("order", "order_confirmation", "ab"):
            tmpl_type = "order_confirmation"
        else:
            tmpl_type = "invoice"
    else:
        # Fallback für dynamische / simulierte Belege aus CRM Vorgänge
        if doc_id.upper().startswith("ANG") or doc_type in ("offer", "ang"):
            tmpl_type = "offer"
            custom["offer_num"] = doc_id
        elif doc_id.upper().startswith("AB") or doc_type in ("order", "order_confirmation", "ab"):
            tmpl_type = "order_confirmation"
            custom["order_num"] = doc_id
        else:
            tmpl_type = "invoice"
            custom["invoice_num"] = doc_id
            
        if entity_name:
            custom["recipient_name"] = entity_name
        if amount_net and amount_net > 0:
            custom["items"] = [
                {"pos": 1, "desc": f"Dienstleistung / Projektleistungen gem. Vorgang {doc_id}", "qty": 1, "unit": "Pauschal", "price": float(amount_net)}
            ]

    try:
        rendered = corporate_manager.render_template(template_type=tmpl_type, company_id=company_id, custom=custom)
    except ValueError as verr:
        # R-21: unbekannte explizite company_id -> 404 statt falscher Stammdaten.
        raise HTTPException(status_code=404, detail=str(verr))
    doc_num = custom.get("offer_num") or custom.get("order_num") or custom.get("invoice_num") or doc_id
    autoprint_script = "<script>window.onload = function() { window.print(); };</script>" if autoprint else ""
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Belegdruck - {doc_num}</title>
  <style>
    @page {{ size: A4; margin: 12mm; }}
    body {{ margin: 0; padding: 24px; background: #f8fafc; display: flex; justify-content: center; font-family: system-ui, -apple-system, sans-serif; }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .no-print {{ display: none !important; }}
    }}
    .print-bar {{
      position: fixed; top: 16px; right: 20px; z-index: 9999;
      background: #0f172a; color: #fff; border-radius: 12px; padding: 10px 18px;
      display: flex; align-items: center; gap: 12px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3); font-size: 13px; font-weight: 600;
    }}
    .print-btn {{
      background: #4f46e5; hover:background: #4338ca; color: #fff; border: 0; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 13px; transition: all 0.2s;
    }}
    .print-btn:hover {{ background: #4338ca; }}
    .close-btn {{
      background: transparent; color: #94a3b8; border: 1px solid #334155; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 12px;
    }}
    .close-btn:hover {{ color: #fff; background: #1e293b; }}
  </style>
</head>
<body>
  <div class="print-bar no-print">
    <span>Archon ERP DIN 5008 Beleg</span>
    <button class="print-btn" onclick="window.print()">🖨️ Drucken / Als PDF speichern</button>
    <button class="close-btn" onclick="window.close()">Fenster schließen</button>
  </div>
  {rendered.get("html", "")}
  {autoprint_script}
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.get("/api/erp/overview")
def api_erp_overview(company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    return erp_manager.get_tenant_overview(company_id=company_id)


@router.get("/api/erp/entities")
def api_erp_list_entities(
    company_id: Optional[str] = None,
    role: str = "all",
    search: str = "",
    status: str = ""
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_entities(company_id=company_id, role_filter=role, search=search, status=status)


@router.get("/api/erp/entities/{entity_id}")
def api_erp_get_entity_detail(entity_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    res = erp_manager.get_entity_detail(entity_id=entity_id, company_id=company_id)
    if not res:
        raise HTTPException(status_code=404, detail="Entity not found")
    return res


@router.post("/api/erp/entities")
def api_erp_save_entity(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_entity(payload=payload, company_id=company_id)
    return {"success": True, "data": saved}


@router.post("/api/erp/contacts")
def api_erp_save_contact(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_contact(payload=payload, company_id=company_id)
    return {"success": True, "contact": saved}


@router.post("/api/erp/interactions")
def api_erp_add_interaction(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.add_interaction(payload=payload, company_id=company_id)
    return {"success": True, "interaction": saved}


@router.get("/api/erp/items")
def api_erp_list_items(
    company_id: Optional[str] = None,
    item_type: str = "all",
    search: str = ""
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_items(company_id=company_id, item_type=item_type, search=search)


@router.post("/api/erp/items")
def api_erp_save_item(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_item(payload=payload, company_id=company_id)
    return {"success": True, "item": saved}


@router.get("/api/erp/documents")
def api_erp_list_documents(
    company_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    entity_id: Optional[str] = None
):
    from backend.erp_manager import erp_manager
    return erp_manager.list_documents(
        company_id=company_id, doc_type=doc_type, status=status, entity_id=entity_id
    )


@router.get("/api/erp/documents/{doc_id}")
def api_erp_get_document(doc_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    doc = erp_manager.get_document(doc_id=doc_id, company_id=company_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/api/erp/documents")
def api_erp_save_document(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    saved = erp_manager.save_document(payload=payload, company_id=company_id)
    return {"success": True, "document": saved}


@router.post("/api/erp/documents/{doc_id}/convert")
def api_erp_convert_document(request: Request, doc_id: str, payload: Dict = Body(default={})):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    target_type = payload.get("target_doc_type", "invoice")
    company_id = payload.get("company_id")
    converted = erp_manager.convert_document(
        source_doc_id=doc_id, target_doc_type=target_type, company_id=company_id
    )
    return {"success": True, "document": converted}


@router.post("/api/erp/sync/pocketbase")
def api_erp_sync_pocketbase(request: Request, payload: Dict = Body(default={})):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    if "pocketbase_url" in payload or "collection_name" in payload:
        erp_manager.update_sync_config(payload, company_id=company_id)
    return erp_manager.sync_with_pocketbase(company_id=company_id)

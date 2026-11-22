from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Router /api/erp — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
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

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])

@router.get("/api/erp/documents/{doc_id}/print", response_class=HTMLResponse)
def api_erp_document_print(
    request: Request,
    doc_id: str,
    company_id: Optional[str] = None,
    autoprint: bool = False,
    doc_type: Optional[str] = None,
    entity_name: Optional[str] = None,
    amount_net: Optional[float] = None
):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
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
        # D-15: doc_id ist ein Pfadsegment und darf nicht roh in HTML landen
        # (Reflected XSS im App-Origin).
        safe_doc_id = html.escape(doc_id)
        if doc_id.upper().startswith("ANG") or doc_type in ("offer", "ang"):
            tmpl_type = "offer"
            custom["offer_num"] = safe_doc_id
        elif doc_id.upper().startswith("AB") or doc_type in ("order", "order_confirmation", "ab"):
            tmpl_type = "order_confirmation"
            custom["order_num"] = safe_doc_id
        else:
            tmpl_type = "invoice"
            custom["invoice_num"] = safe_doc_id
            
        if entity_name:
            custom["recipient_name"] = html.escape(entity_name)
        if amount_net and amount_net > 0:
            custom["items"] = [
                {"pos": 1, "desc": f"Dienstleistung / Projektleistungen gem. Vorgang {safe_doc_id}", "qty": 1, "unit": "Pauschal", "price": float(amount_net)}
            ]

    try:
        rendered = corporate_manager.render_template(template_type=tmpl_type, company_id=company_id, custom=custom)
    except ValueError as verr:
        # R-21: unbekannte explizite company_id -> 404 statt falscher Stammdaten.
        raise HTTPException(status_code=404, detail=str(verr))
    autoprint_script = "<script>window.onload = function() { window.print(); };</script>" if autoprint else ""
    # D-15: Das Pfadsegment doc_id ist die Angreifer-Kontrolle — im <title>
    # GENAU EINMAL escapen (nicht die bereits escapten custom-Werte verwenden,
    # sonst Doppel-Escaping). Die custom-Werte (invoice_num etc.) sind fuer den
    # HTML-Body von render_template bereits escapt.
    safe_doc_num = html.escape(str(doc_id))
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Belegdruck - {safe_doc_num}</title>
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
    request: Request,
    company_id: Optional[str] = None,
    role: str = "all",
    search: str = "",
    status: str = ""
):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.erp_manager import erp_manager
    return erp_manager.list_entities(company_id=company_id, role_filter=role, search=search, status=status)


@router.get("/api/erp/entities/{entity_id}")
def api_erp_get_entity_detail(entity_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    res = erp_manager.get_entity_detail(entity_id=entity_id, company_id=company_id)
    if not res:
        raise HTTPException(status_code=404, detail={"code": "erp_entity_not_found", "params": {}})
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
    request: Request,
    company_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    entity_id: Optional[str] = None
):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.erp_manager import erp_manager
    return erp_manager.list_documents(
        company_id=company_id, doc_type=doc_type, status=status, entity_id=entity_id
    )


@router.get("/api/erp/documents/{doc_id}")
def api_erp_get_document(doc_id: str, company_id: Optional[str] = None):
    from backend.erp_manager import erp_manager
    doc = erp_manager.get_document(doc_id=doc_id, company_id=company_id)
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "erp_document_not_found", "params": {}})
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


@router.post("/api/erp/documents/{doc_id}/cancel")
def api_erp_cancel_document(request: Request, doc_id: str, payload: Dict = Body(default={})):
    """Storniert einen Beleg GoBD-konform über eine Storno-Gutschrift (Typ 381)."""
    require_admin_or_503(request)
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    reason = str(payload.get("reason") or "")
    try:
        res = erp_manager.cancel_document(doc_id=doc_id, reason=reason, company_id=company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, **res}


@router.get("/api/erp/documents/{doc_id}/xrechnung.xml")
def api_erp_document_xrechnung_xml(request: Request, doc_id: str, company_id: Optional[str] = None):
    """Exportiert einen ERP-Beleg als EN-16931 / XRechnung-3.0-konforme UBL-XML-Datei."""
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.erp_manager import erp_manager
    try:
        doc_num, xml_str = erp_manager.export_xrechnung_xml(doc_id=doc_id, company_id=company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", doc_num or doc_id).strip("_") or "xrechnung"
    return Response(
        content=xml_str.encode("utf-8"),
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_xrechnung.xml"'},
    )


@router.get("/api/erp/export/datev.csv")
def api_erp_export_datev_csv(
    request: Request,
    company_id: Optional[str] = None,
    include_drafts: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Exportiert den DATEV-EXTF-Buchungsstapel (SKR03) als Semikolon-CSV mit UTF-8-BOM."""
    require_admin_or_503(request)
    from backend.erp_manager import erp_manager
    csv_text = erp_manager.export_datev_extf_csv(
        company_id=company_id,
        include_drafts=include_drafts,
        date_from=date_from,
        date_to=date_to,
    )
    bom_bytes = b"\xef\xbb\xbf" + csv_text.encode("utf-8")
    return Response(
        content=bom_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="EXTF_Buchungsstapel_Archon.csv"'},
    )


@router.get("/api/erp/export/gobd-z3.zip")
def api_erp_export_gobd_z3_zip(
    request: Request,
    company_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Exportiert eine GoBD-Z3-Datenträgerüberlassung (index.xml + CSV-Tabellen + SHA-256-Manifest)."""
    require_admin_or_503(request)
    from backend.gobd_z3_export import build_gobd_z3_archive
    filename, zip_bytes, zip_sha256 = build_gobd_z3_archive(
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Archive-SHA256": zip_sha256,
        },
    )


@router.get("/api/erp/documents/{doc_id}/zugferd.pdf")
def api_erp_document_zugferd_pdf(request: Request, doc_id: str, company_id: Optional[str] = None):
    """Exportiert eine Hybrid-E-Rechnung im ZUGFeRD-2.2-/Factur-X-Format (PDF + `factur-x.xml`)."""
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.erp_manager import erp_manager
    try:
        doc_num, pdf_bytes = erp_manager.export_zugferd_pdf(doc_id=doc_id, company_id=company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", doc_num or doc_id).strip("_") or "zugferd"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_zugferd.pdf"'},
    )


@router.get("/api/erp/bank/transactions")
def api_erp_list_bank_transactions(request: Request, company_id: Optional[str] = None, match_status: Optional[str] = None):
    """Listet importierte Bankumsätze und deren OPOS-Matching-Status."""
    require_admin_or_503(request)
    from backend.erp_manager import erp_manager
    return erp_manager.list_bank_transactions(company_id=company_id, match_status=match_status)


@router.post("/api/erp/bank/import")
def api_erp_import_bank_statement(request: Request, payload: Dict = Body(...)):
    """Importiert Kontoauszüge (ISO 20022 CAMT.053 XML, MT940, Bank-CSV) und führt automatischen OPOS-Abgleich aus."""
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    raw_content = payload.get("content") or ""
    if not str(raw_content).strip():
        raise HTTPException(status_code=400, detail="Kontoauszugs-Inhalt ('content') darf nicht leer sein.")
    try:
        return erp_manager.import_and_reconcile_bank_statement(
            raw_content=str(raw_content),
            fmt=str(payload.get("format") or "auto"),
            auto_mark_paid=bool(payload.get("auto_mark_paid", False)),
            company_id=payload.get("company_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültiges CAMT.053-XML: {exc}") from exc


@router.post("/api/erp/bank/transactions/{tx_id}/match")
def api_erp_match_bank_transaction(request: Request, tx_id: str, payload: Dict = Body(...)):
    """Ordnet eine importierte Banktransaktion einer Rechnung zu und verbucht optional als bezahlt."""
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    doc_id = str(payload.get("doc_id") or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id ist erforderlich.")
    try:
        return erp_manager.match_bank_transaction(
            tx_id=tx_id,
            doc_id=doc_id,
            mark_paid=bool(payload.get("mark_paid", True)),
            company_id=payload.get("company_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/erp/sync/pocketbase")
def api_erp_sync_pocketbase(request: Request, payload: Dict = Body(default={})):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.erp_manager import erp_manager
    company_id = payload.get("company_id")
    if "pocketbase_url" in payload or "collection_name" in payload:
        erp_manager.update_sync_config(payload, company_id=company_id)
    return erp_manager.sync_with_pocketbase(company_id=company_id)

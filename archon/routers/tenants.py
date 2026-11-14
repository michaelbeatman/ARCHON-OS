"""
archon/routers/tenants.py
=========================
M43 — Multi-Mandanten-Umschalter & Physische DB-Isolation (Holding / Operative GmbH / SPV).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from archon.core.runtime import broadcast_event
from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.tenant_context import sanitize_tenant_id, tenant_context

router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["Multi-Tenant (M43)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("/context")
def get_tenant_context():
    """Liefert den aktiven Mandanten, alle Firmen und den physischen SQLite-Isolationsstatus."""
    mgr = tenant_context._get_corporate_manager()
    companies = mgr.list_companies()
    active = tenant_context.get_active_company()
    tid = tenant_context.get_active_tenant_id()
    return {
        "status": "success",
        "active_company": active,
        "active_tenant_id": tid,
        "companies": companies,
        "isolation": tenant_context.get_isolation_status(tid),
        "number_ranges": tenant_context.get_number_ranges(tid),
    }


@router.post("/companies")
def create_or_update_tenant_company(request: Request, payload: Dict[str, Any] = Body(...)):
    """Legt eine neue Gesellschaft (Holding / GmbH / SPV) an und provisioniert sofort ihre 5 isolierten SQLite-DBs."""
    require_admin_or_503(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Firmenname ('name') ist erforderlich.")

    entity_type = str(payload.get("entity_type") or "operative_gmbh").strip().lower()
    if entity_type not in ("holding", "operative_gmbh", "spv"):
        entity_type = "operative_gmbh"

    raw_id = str(payload.get("id") or name.lower().replace(" ", "-"))
    cid = sanitize_tenant_id(raw_id)

    mgr = tenant_context._get_corporate_manager()
    company_payload = dict(payload)
    company_payload["id"] = cid
    company_payload["name"] = name
    company_payload["entity_type"] = entity_type

    saved = mgr.save_company(company_payload)
    db_paths = tenant_context.ensure_tenant_databases(cid, init_schemas=True)
    ranges = tenant_context.get_number_ranges(cid)

    if payload.get("activate"):
        tenant_context.switch_tenant(cid)

    return {
        "status": "success",
        "company": saved,
        "tenant_id": cid,
        "isolated_dbs": db_paths,
        "number_ranges": ranges,
    }


@router.post("/switch")
async def switch_active_tenant(request: Request, payload: Dict[str, Any] = Body(...)):
    """Wechselt den aktiven Mandanten atomar und informiert verbundene Clients per SSE."""
    require_admin_or_503(request)
    company_id = str(payload.get("company_id") or "").strip()
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id ist erforderlich.")
    try:
        res = tenant_context.switch_tenant(company_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        broadcast_event(
            "tenant_switched",
            {
                "tenant_id": res["tenant_id"],
                "company": res["active_company"],
            },
        )
    except Exception:
        pass
    return res


@router.get("/{company_id}/number-ranges")
def get_tenant_number_ranges(company_id: str):
    """Liefert die getrennten Beleg-Nummernkreise eines Mandanten."""
    return {
        "status": "success",
        "tenant_id": company_id,
        "number_ranges": tenant_context.get_number_ranges(company_id),
    }


@router.post("/{company_id}/number-ranges/next")
def allocate_next_tenant_number(request: Request, company_id: str, payload: Dict[str, Any] = Body(...)):
    """Vergibt atomar die nächste Belegnummer (invoice, offer, order, credit_note, contract)."""
    require_admin_or_503(request)
    doc_type = str(payload.get("doc_type") or "invoice").strip()
    try:
        number = tenant_context.next_document_number(doc_type, company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "tenant_id": company_id, "doc_type": doc_type, "document_number": number}


@router.get("/{company_id}/isolation-status")
def get_tenant_isolation_status(company_id: str):
    """Zeigt die physisch isolierten SQLite-Datenbanken des Mandanten."""
    return {"status": "success", **tenant_context.get_isolation_status(company_id)}

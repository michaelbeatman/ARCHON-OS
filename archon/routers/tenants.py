"""
archon/routers/tenants.py
========================
M43 — Multi-Mandanten-Umschalter & Physische DB-Isolation (Holding / Operative GmbH / SPV).
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("tenants")

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from archon.core.runtime import broadcast_event
from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.tenant_context import sanitize_tenant_id, tenant_context

_TENANT_ID_RE = r"[A-Za-z0-9._\-]{1,64}"


class TenantAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")
    street: str = Field(default="", max_length=300)
    postal_code: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=120)
    country: str = Field(default="Deutschland", max_length=120)


class TenantContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=256)
    website: str = Field(default="", max_length=256)


class TenantRegistry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    court: str = Field(default="", max_length=120)
    number: str = Field(default="", max_length=64)
    managing_directors: str = Field(default="", max_length=300)


class TenantTax(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tax_number: str = Field(default="", max_length=64)
    vat_id: str = Field(default="", max_length=64)
    small_business: bool = False


class TenantBank(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bank_name: str = Field(default="", max_length=120)
    iban: str = Field(default="", max_length=42)
    bic: str = Field(default="", max_length=16)


class TenantDesign(BaseModel):
    model_config = ConfigDict(extra="ignore")
    primary_color: str = Field(default="#4f46e5", max_length=32)
    secondary_color: str = Field(default="#06b6d4", max_length=32)
    accent_color: str = Field(default="#10b981", max_length=32)
    logo_url: str = Field(default="", max_length=512)
    font_family: str = Field(default="Inter, system-ui, sans-serif", max_length=128)


class TenantCompanyRequest(BaseModel):
    """Validierter Payload für POST /api/v1/tenants/companies (Etappe 7).

    Die Mandanten-ID wird hier bereits gegen Pfad-Traversal geprüft; zusätzlich
    ruft der Endpoint sanitize_tenant_id() auf (defense in depth).
    """
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=200)
    entity_type: str = Field(default="operative_gmbh", max_length=64)
    legal_form: str = Field(default="", max_length=120)
    slogan: str = Field(default="", max_length=300)
    address: TenantAddress = Field(default_factory=TenantAddress)
    contact: TenantContact = Field(default_factory=TenantContact)
    registry: TenantRegistry = Field(default_factory=TenantRegistry)
    tax: TenantTax = Field(default_factory=TenantTax)
    bank: TenantBank = Field(default_factory=TenantBank)
    design: TenantDesign = Field(default_factory=TenantDesign)
    template_layouts: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = Field(default=None, max_length=64)
    activate: bool = False

    @field_validator("id")
    @classmethod
    def _validate_company_id_field(cls, v: Optional[str]) -> Optional[str]:
        import re as _re
        if v and (".." in v or not _re.fullmatch(_TENANT_ID_RE, v.strip())):
            raise ValueError("Ungueltige Mandanten-ID (Pfad-Traversal unzulaessig).")
        return v


class TenantSwitchRequest(BaseModel):
    """Validierter Payload für POST /api/v1/tenants/switch (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    company_id: str = Field(default="", max_length=64)

    @field_validator("company_id")
    @classmethod
    def _validate_company_id_field(cls, v: str) -> str:
        import re as _re
        v = v.strip()
        if v and (".." in v or not _re.fullmatch(_TENANT_ID_RE, v)):
            raise ValueError("Ungueltige Mandanten-ID (Pfad-Traversal unzulaessig).")
        return v


class TenantNumberRangeRequest(BaseModel):
    """Validierter Payload für POST /api/v1/tenants/{id}/number-ranges/next (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    doc_type: str = Field(default="invoice", max_length=50)


router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["Multi-Tenant (M43)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("/context")
def get_tenant_context(request: Request):
    """Liefert den aktiven Mandanten, alle Firmen und den physischen SQLite-Isolationsstatus."""
    require_admin_or_503(request)  # RBAC: Mandanten-/Firmenstruktur + DB-Pfade sind sensibel
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
def create_or_update_tenant_company(request: Request, payload: TenantCompanyRequest):
    """Legt eine neue Gesellschaft (Holding / GmbH / SPV) an und provisioniert sofort ihre 5 isolierten SQLite-DBs."""
    require_admin_or_503(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Firmenname ('name') ist erforderlich.")

    entity_type = payload.entity_type.strip().lower()
    if entity_type not in ("holding", "operative_gmbh", "spv"):
        entity_type = "operative_gmbh"

    raw_id = str(payload.id or name.lower().replace(" ", "-"))
    cid = sanitize_tenant_id(raw_id)

    mgr = tenant_context._get_corporate_manager()
    company_payload = payload.model_dump(exclude_none=True)
    company_payload["id"] = cid
    company_payload["name"] = name
    company_payload["entity_type"] = entity_type

    saved = mgr.save_company(company_payload)
    db_paths = tenant_context.ensure_tenant_databases(cid, init_schemas=True)
    ranges = tenant_context.get_number_ranges(cid)

    if payload.activate:
        tenant_context.switch_tenant(cid)

    return {
        "status": "success",
        "company": saved,
        "tenant_id": cid,
        "isolated_dbs": db_paths,
        "number_ranges": ranges,
    }


@router.post("/switch")
async def switch_active_tenant(request: Request, payload: TenantSwitchRequest):
    """Wechselt den aktiven Mandanten atomar und informiert verbundene Clients per SSE."""
    require_admin_or_503(request)
    company_id = payload.company_id.strip()
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id ist erforderlich.")
    _validate_company_id(company_id)
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
    except Exception as _exc:
        _archon_exc_logger.debug("[tenants] Ignorierte Ausnahme (Z.98): %s", _exc)
    return res


def _validate_company_id(company_id: str) -> str:
    import re as _re
    if not company_id or ".." in company_id or not _re.fullmatch(_TENANT_ID_RE, company_id):
        raise HTTPException(status_code=400, detail="Ungueltige company_id (Pfad-Traversal unzulaessig).")
    return company_id


@router.get("/{company_id}/number-ranges")
def get_tenant_number_ranges(company_id: str):
    """Liefert die getrennten Beleg-Nummernkreise eines Mandanten."""
    _validate_company_id(company_id)
    return {
        "status": "success",
        "tenant_id": company_id,
        "number_ranges": tenant_context.get_number_ranges(company_id),
    }


@router.post("/{company_id}/number-ranges/next")
def allocate_next_tenant_number(request: Request, company_id: str, payload: TenantNumberRangeRequest):
    """Vergibt atomar die nächste Belegnummer (invoice, offer, order, credit_note, contract)."""
    require_admin_or_503(request)
    _validate_company_id(company_id)
    doc_type = payload.doc_type.strip()
    try:
        number = tenant_context.next_document_number(doc_type, company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "tenant_id": company_id, "doc_type": doc_type, "document_number": number}


@router.get("/{company_id}/isolation-status")
def get_tenant_isolation_status(company_id: str):
    """Zeigt die physisch isolierten SQLite-Datenbanken des Mandanten."""
    _validate_company_id(company_id)
    return {"status": "success", **tenant_context.get_isolation_status(company_id)}

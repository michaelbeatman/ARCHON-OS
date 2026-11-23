from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503
"""Sub-Router fuer Mahnwesen & Debitorenmanagement (Dunning Engine).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class InvoiceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = ""
    amount_net: float = Field(gt=0, le=100_000_000)
    due_days: int = Field(default=14, ge=0, le=365)
    invoice_date: Optional[str] = None
    recipient_address: Optional[str] = None


class DunningDraftRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    invoice_id: str = Field(min_length=1, max_length=100)
    level: int = Field(default=1, ge=1, le=3)


class DunningApproveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dunning_id: str = Field(min_length=1, max_length=100)


class DunningMarkPaidRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    invoice_id: str = Field(min_length=1, max_length=100)


@router.get("/dunning/invoices")
def api_dunning_invoices(request: Request):
    """Gibt alle Ausgangsrechnungen inklusive Fälligkeits- und Mahnstufenstatus zurück."""
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    try:
        from backend.dunning_engine import dunning_engine
        invoices = dunning_engine.check_overdue_invoices()
        return {"status": "success", "count": len(invoices), "invoices": invoices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/invoices")
def api_dunning_create_invoice(req: InvoiceCreateRequest):
    """Erstellt eine neue Ausgangsrechnung."""
    customer_name = req.customer_name.strip()
    customer_email = req.customer_email.strip()
    amount_net = req.amount_net
    due_days = req.due_days
    invoice_date = req.invoice_date
    recipient_address = req.recipient_address

    try:
        from backend.dunning_engine import dunning_engine
        inv = dunning_engine.create_invoice(
            customer_name=customer_name,
            customer_email=customer_email,
            amount_net=amount_net,
            due_days=due_days,
            invoice_date=invoice_date,
            recipient_address=recipient_address,
        )
        return {"status": "success", "invoice": inv}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/draft")
def api_dunning_generate_draft(req: DunningDraftRequest):
    """Erzeugt einen rechtssicheren 3-stufigen Mahnentwurf zur manuellen Prüfung."""
    invoice_id = req.invoice_id.strip()
    level = req.level

    try:
        from backend.dunning_engine import dunning_engine
        draft = dunning_engine.generate_dunning_draft(invoice_id, level)
        return {"status": "success", "draft": draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/approve")
def api_dunning_approve(request: Request, req: DunningApproveRequest):
    """Gibt einen Mahnentwurf frei und aktualisiert den Rechnungsstatus (HITL-Freigabe)."""
    require_admin_or_503(request)
    dunning_id = req.dunning_id.strip()

    try:
        from backend.dunning_engine import dunning_engine
        res = dunning_engine.approve_and_send_dunning(dunning_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/mark-paid")
def api_dunning_mark_paid(request: Request, req: DunningMarkPaidRequest):
    """Markiert eine Ausgangsrechnung als bezahlt."""
    require_admin_or_503(request)
    invoice_id = req.invoice_id.strip()

    try:
        from backend.dunning_engine import dunning_engine
        ok = dunning_engine.mark_invoice_paid(invoice_id)
        if not ok:
            raise HTTPException(status_code=404, detail={"code": "dunning_invoice_not_found", "params": {}})
        return {"status": "success", "invoice_id": invoice_id, "paid": True}
    except HTTPException:
        # 400/404 nicht durch das blanket-except in 500 verwandeln.
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

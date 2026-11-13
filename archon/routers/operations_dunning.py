from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Mahnwesen & Debitorenmanagement (Dunning Engine).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


@router.get("/dunning/invoices")
def api_dunning_invoices():
    """Gibt alle Ausgangsrechnungen inklusive Fälligkeits- und Mahnstufenstatus zurück."""
    try:
        from backend.dunning_engine import dunning_engine
        invoices = dunning_engine.check_overdue_invoices()
        return {"status": "success", "count": len(invoices), "invoices": invoices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/invoices")
def api_dunning_create_invoice(req: Dict[str, Any] = Body(...)):
    """Erstellt eine neue Ausgangsrechnung."""
    customer_name = req.get("customer_name", "").strip()
    customer_email = req.get("customer_email", "").strip()
    amount_net = float(req.get("amount_net", 0.0))
    due_days = int(req.get("due_days", 14))
    invoice_date = req.get("invoice_date")
    recipient_address = req.get("recipient_address")

    if not customer_name or amount_net <= 0:
        raise HTTPException(status_code=400, detail={"code": "dunning_customer_amount_required", "params": {}})

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
def api_dunning_generate_draft(req: Dict[str, Any] = Body(...)):
    """Erzeugt einen rechtssicheren 3-stufigen Mahnentwurf zur manuellen Prüfung."""
    invoice_id = req.get("invoice_id", "").strip()
    level = int(req.get("level", 1))

    if not invoice_id:
        raise HTTPException(status_code=400, detail={"code": "dunning_invoice_id_required", "params": {}})

    try:
        from backend.dunning_engine import dunning_engine
        draft = dunning_engine.generate_dunning_draft(invoice_id, level)
        return {"status": "success", "draft": draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/approve")
def api_dunning_approve(req: Dict[str, Any] = Body(...)):
    """Gibt einen Mahnentwurf frei und aktualisiert den Rechnungsstatus (HITL-Freigabe)."""
    dunning_id = req.get("dunning_id", "").strip()
    if not dunning_id:
        raise HTTPException(status_code=400, detail={"code": "dunning_id_required", "params": {}})

    try:
        from backend.dunning_engine import dunning_engine
        res = dunning_engine.approve_and_send_dunning(dunning_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/mark-paid")
def api_dunning_mark_paid(req: Dict[str, Any] = Body(...)):
    """Markiert eine Ausgangsrechnung als bezahlt."""
    invoice_id = req.get("invoice_id", "").strip()
    if not invoice_id:
        raise HTTPException(status_code=400, detail={"code": "dunning_invoice_id_required_2", "params": {}})

    try:
        from backend.dunning_engine import dunning_engine
        ok = dunning_engine.mark_invoice_paid(invoice_id)
        if not ok:
            raise HTTPException(status_code=404, detail={"code": "dunning_invoice_not_found", "params": {}})
        return {"status": "success", "invoice_id": invoice_id, "paid": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

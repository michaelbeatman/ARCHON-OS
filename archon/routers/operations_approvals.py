from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Approval Policies & 4-Augen-Prinzip (t-5596bd).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, HTTPException, Request

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


@router.get("/approvals/policies")
def api_get_approval_policies(domain: Optional[str] = None):
    """Gibt alle aktiven Freigaberegeln (optional gefiltert nach Domain) zurück."""
    try:
        from backend.approval_policy_engine import approval_engine
        policies = approval_engine.get_policies(domain=domain)
        return {"status": "success", "policies": policies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/policies")
def api_update_approval_policy(request: Request, req: Dict[str, Any] = Body(...)):
    """Aktualisiert eine Freigaberegel revisionssicher mit SHA-256 Hash-Kette."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    policy_key = req.get("policy_key", "").strip()
    new_value = str(req.get("new_value", "")).strip()
    user_id = req.get("user_id", "admin").strip()

    if not policy_key or new_value == "":
        raise HTTPException(status_code=400, detail={"code": "approvals_policy_key_value_required", "params": {}})

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.update_policy(policy_key, new_value, user_id=user_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/requests")
def api_get_approval_requests(status: Optional[str] = None, domain: Optional[str] = None):
    """Gibt Freigabeanfragen aus der Warteschlange zurück."""
    try:
        from backend.approval_policy_engine import approval_engine
        requests = approval_engine.get_requests(status=status, domain=domain)
        return {"status": "success", "requests": requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests")
def api_create_approval_request(req: Dict[str, Any] = Body(...)):
    """Erstellt eine neue Freigabeanfrage und evaluiert Auto-Freigabe Schwellenwerte."""
    domain = req.get("domain", "finance").strip()
    title = req.get("title", "").strip()
    amount = float(req.get("amount", 0.0))
    reference_id = req.get("reference_id")
    payload = req.get("payload")

    if not title:
        raise HTTPException(status_code=400, detail={"code": "approvals_title_required", "params": {}})

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.evaluate_and_enqueue(
            domain=domain,
            title=title,
            amount=amount,
            reference_id=reference_id,
            payload=payload,
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests/{request_id}/approve")
def api_approve_request(request_id: str, req: Dict[str, Any] = Body(default={})):
    """Gibt eine anhängige Anfrage frei (unterstützt 1. und 2. Prüfer)."""
    approver_id = req.get("approver_id", "admin").strip()
    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.approve_request(request_id, approver_id=approver_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests/{request_id}/reject")
def api_reject_request(request_id: str, req: Dict[str, Any] = Body(...)):
    """Lehnt eine anhängige Freigabeanfrage mit Begründung ab."""
    rejected_by = req.get("rejected_by", "admin").strip()
    reason = req.get("reason", "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail={"code": "approvals_reason_required", "params": {}})

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.reject_request(request_id, rejected_by=rejected_by, reason=reason)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/delegation")
def api_get_delegation(user_id: str = "admin"):
    """Ruft den Urlaubs- und Vertretungsmodus ab."""
    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.get_delegation(user_id=user_id)
        return {"status": "success", "delegation": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/delegation")
def api_set_delegation(req: Dict[str, Any] = Body(...)):
    """Aktiviert oder deaktiviert den Urlaubsmodus mit Stellvertretung."""
    user_id = req.get("user_id", "admin").strip()
    is_active = bool(req.get("is_active", False))
    substitute_id = req.get("substitute_id", "katharina").strip()
    substitute_name = req.get("substitute_name", "Katharina Völk (QM)").strip()

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.set_delegation(
            user_id=user_id,
            is_active=is_active,
            substitute_id=substitute_id,
            substitute_name=substitute_name,
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/audit-chain")
def api_get_approval_audit_chain(limit: int = 50):
    """Liefert die kryptografisch verkettete Revisionshistorie (GoBD/ISO 27001)."""
    try:
        from backend.approval_policy_engine import approval_engine
        chain = approval_engine.get_audit_chain(limit=limit)
        return {"status": "success", "chain": chain}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/audit-verify")
def api_verify_approval_audit():
    """Überprüft die mathematische Gültigkeit der gesamten SHA-256 Hash-Kette."""
    try:
        from backend.approval_policy_engine import approval_engine
        integrity = approval_engine.verify_audit_integrity()
        return {"status": "success", "integrity": integrity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

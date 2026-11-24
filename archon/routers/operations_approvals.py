from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Approval Policies & 4-Augen-Prinzip (t-5596bd).

Ausgelagert aus backend/operations_api.py.
"""
import json
import logging
logger = logging.getLogger("archon.routers.operations_approvals")

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import require_admin_or_503, require_session_actor


class ApprovalPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    policy_key: str = Field(min_length=1, max_length=120)
    new_value: str = ""


class ApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    domain: str = "finance"
    title: str = Field(min_length=1, max_length=300)
    amount: float = Field(default=0.0, ge=0)
    reference_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class ApprovalRejectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = Field(min_length=1, max_length=2000)


class DelegationSetRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_active: bool = False
    substitute_id: str = "katharina"
    substitute_name: str = "Katharina Völk (QM)"

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


@router.get("/approvals/policies")
def api_get_approval_policies(request: Request, domain: Optional[str] = None):
    """Gibt alle aktiven Freigaberegeln (optional gefiltert nach Domain) zurück."""
    require_admin_or_503(request)  # Freigabepolicies sind administrativ
    try:
        from backend.approval_policy_engine import approval_engine
        policies = approval_engine.get_policies(domain=domain)
        return {"status": "success", "policies": policies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/policies")
def api_update_approval_policy(request: Request, req: ApprovalPolicyUpdateRequest):
    """Aktualisiert eine Freigaberegel revisionssicher mit SHA-256 Hash-Kette."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    policy_key = req.policy_key.strip()
    new_value = req.new_value.strip()
    user_id = require_session_actor(request)

    if not policy_key or new_value == "":
        raise HTTPException(status_code=400, detail={"code": "approvals_policy_key_value_required", "params": {}})

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.update_policy(policy_key, new_value, user_id=user_id)
        return {"status": "success", "result": res}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/requests")
def api_get_approval_requests(request: Request, status: Optional[str] = None, domain: Optional[str] = None):
    """Gibt Freigabeanfragen aus der Warteschlange zurück (inkl. Beträge/Payloads)."""
    require_admin_or_503(request)
    try:
        from backend.approval_policy_engine import approval_engine
        requests = approval_engine.get_requests(status=status, domain=domain)
        return {"status": "success", "requests": requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests")
def api_create_approval_request(request: Request, req: ApprovalRequestCreate):
    """Erstellt eine neue Freigabeanfrage und evaluiert Auto-Freigabe Schwellenwerte."""
    # Audit 23.11.2026: Freigabeanfragen konnten ohne Rollenzaun angelegt werden.
    require_admin_or_503(request)
    domain = req.domain.strip()
    title = req.title.strip()
    amount = req.amount
    reference_id = req.reference_id
    # Audit D04/D14: der Antragsteller kommt AUSSCHLIESSLICH aus der
    # verifizierten Session und wird mit dem Request persistiert.
    requester_id = require_session_actor(request)
    payload = dict(req.payload or {})
    payload.setdefault("_requester_id", requester_id)

    try:
        from backend.approval_policy_engine import approval_engine
        try:
            # Handoff: backend/approval_policy_engine.py (anderer Agent) muss
            # requester_id akzeptieren und in `approval_requests` persistieren.
            res = approval_engine.evaluate_and_enqueue(
                domain=domain,
                title=title,
                amount=amount,
                reference_id=reference_id,
                payload=payload,
                requester_id=requester_id,
            )
        except TypeError:
            # Rueckwaertskompatibel bis Handoff: der Antragsteller steht dann
            # wenigstens im signierten Payload und wird von approve_request()
            # ueber die defense-in-depth-Pruefung unten beruecksichtigt.
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
def api_approve_request(request: Request, request_id: str):
    """Gibt eine anhängige Anfrage frei (unterstützt 1. und 2. Prüfer)."""
    require_admin_or_503(request)
    approver_id = require_session_actor(request)
    try:
        from backend.approval_policy_engine import approval_engine
        # Audit D04/D14: Vier-Augen auch hier. Der Engine-Check in
        # approve_request() gehoert einem anderen Agenten (Handoff); dieser
        # Router suedert zusaetzlich gegen identischen Ersteller/Genehmiger.
        requester_id = ""
        try:
            row = next(
                (r for r in approval_engine.get_requests() if str(r.get("id")) == str(request_id)),
                None,
            )
            if row:
                requester_id = str(row.get("requester_id") or row.get("created_by") or "")
                if not requester_id:
                    pl = row.get("payload_json") or row.get("payload") or {}
                    if isinstance(pl, str):
                        try:
                            pl = json.loads(pl)
                        except (TypeError, ValueError):
                            pl = {}
                    requester_id = str((pl or {}).get("_requester_id") or "")
        except Exception as lookup_exc:
            logger.warning("Antragsteller fuer %s nicht lesbar: %s", request_id, lookup_exc)
        if requester_id and requester_id == approver_id:
            logger.warning(
                "Vier-Augen-Verletzung: Antragsteller '%s' will eigenen Antrag %s freigeben.",
                approver_id, request_id,
            )
            raise HTTPException(
                status_code=403,
                detail="Ersteller darf die eigene Freigabeanfrage nicht genehmigen (Vier-Augen-Prinzip).",
            )
        res = approval_engine.approve_request(request_id, approver_id=approver_id)
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="approval",
                event_type="approved",
                title=f"Freigabe erteilt: {request_id}",
                summary=f"Freigegeben durch {approver_id}",
                payload={"request_id": request_id, "approver": approver_id},
                correlation_id=f"apr-{request_id}",
            )
        except Exception as exc:
            logger.debug(f"Event-Bus-Event fuer Freigabe {request_id} konnte nicht gesendet werden: {exc}")
        return {"status": "success", "result": res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests/{request_id}/reject")
def api_reject_request(request: Request, request_id: str, req: ApprovalRejectRequest):
    """Lehnt eine anhängige Freigabeanfrage mit Begründung ab."""
    require_admin_or_503(request)
    rejected_by = require_session_actor(request)
    reason = req.reason.strip()

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.reject_request(request_id, rejected_by=rejected_by, reason=reason)
        try:
            from backend.workflow_scheduler import dispatch_workflow_event
            dispatch_workflow_event(
                source="approval",
                event_type="rejected",
                title=f"Freigabe abgelehnt: {request_id}",
                summary=reason,
                payload={"request_id": request_id, "rejected_by": rejected_by},
                correlation_id=f"rej-{request_id}",
            )
        except Exception as exc:
            logger.debug(f"Event-Bus-Event fuer Ablehnung {request_id} konnte nicht gesendet werden: {exc}")
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
def api_set_delegation(request: Request, req: DelegationSetRequest):
    """Aktiviert oder deaktiviert den Urlaubsmodus mit Stellvertretung."""
    require_admin_or_503(request)
    user_id = require_session_actor(request)
    is_active = req.is_active
    substitute_id = req.substitute_id.strip()
    substitute_name = req.substitute_name.strip()

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
def api_get_approval_audit_chain(request: Request, limit: int = 50):
    """Liefert die kryptografisch verkettete Revisionshistorie (GoBD/ISO 27001)."""
    require_admin_or_503(request)
    try:
        from backend.approval_policy_engine import approval_engine
        chain = approval_engine.get_audit_chain(limit=limit)
        return {"status": "success", "chain": chain}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/audit-verify")
def api_verify_approval_audit(request: Request):
    """Überprüft die mathematische Gültigkeit der gesamten SHA-256 Hash-Kette."""
    require_admin_or_503(request)
    try:
        from backend.approval_policy_engine import approval_engine
        integrity = approval_engine.verify_audit_integrity()
        return {"status": "success", "integrity": integrity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

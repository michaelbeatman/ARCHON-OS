"""M69: Policy-Gate-, Freigabe-Token- und Telegram-Callback-Endpunkte.

WICHTIG: dieser Router wird bewusst NICHT in ``main.py`` registriert. Der
Integrator ergaenzt nach dem Import der uebrigen Router:

    from archon.routers.policy_gates import router as policy_gates_router
    app.include_router(policy_gates_router)

Die Telegram-Buttons werden ausschliesslich als Payload-Beschreibung
(``reply_markup``) zurueckgegeben; dieser Router sendet keine Nachricht und
aendert ``telegram.py`` nicht. Das Roh-Token erscheint nur in ``callback_data``
dieses einen Auslieferungspfads — niemals in Logs oder anderen Responses.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from archon.routers import _rbac

logger = logging.getLogger("archon.routers.policy_gates")

# Alias wie in den anderen Routern: Tests koennen die Dependency gezielt
# ueberschreiben, ohne main.py oder den RBAC-Helper zu veraendern.
forbid_viewer_writes = _rbac.forbid_viewer_writes

router = APIRouter(
    prefix="/api/policy-gates",
    tags=["policy-gates"],
    dependencies=[Depends(forbid_viewer_writes)],
)


class GateEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    domain: str = "finance"
    action: str = "dispatch"
    amount_eur: float = Field(default=0.0, ge=0)
    vendor: str = ""
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    actor: str = ""
    approver: str = ""
    request_id: str = ""
    chain_depth: int = Field(default=0, ge=0)
    actions_in_chain: int = Field(default=0, ge=0)


class TokenIssueRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_id: str = Field(min_length=1, max_length=200)
    ttl_seconds: Optional[int] = None
    actor: str = ""


class SessionGateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_id: str = Field(min_length=1, max_length=200)
    approval_token: str = Field(default="", max_length=200)
    reason: str = Field(default="Abgelehnt", max_length=2000)


class TelegramGateCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    callback_data: str = Field(min_length=1, max_length=200)
    chat_id: str = Field(min_length=1, max_length=30)
    reason: str = Field(default="Per Telegram abgelehnt", max_length=2000)


def _extract_token(value: str) -> str:
    """Akzeptiert Roh-Token oder ``hitl:<aktion>:<token>`` als callback_data."""
    from backend.approval_policy_engine import parse_policy_callback

    text = str(value or "").strip()
    parsed = parse_policy_callback(text)
    return str(parsed["token"]) if parsed else text


def _no_store(payload: Dict[str, Any]) -> JSONResponse:
    """Antworten mit Tokens duerfen nie zwischengespeichert werden."""
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _execute_decision(
    *,
    token: str,
    action: str,
    request_id: str,
    actor: str,
    reason: str,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prueft Token, M95-RBAC und Policy-Gate VOR der tatsaechlichen Ausfuehrung."""
    from backend import approval_policy_engine as ape
    from backend.approval_policy_engine import approval_engine

    clean_token = _extract_token(token)
    pre = ape.verify_approval_token(
        clean_token, expected_action=action, expected_request_id=request_id, consume=False
    )
    if not pre["valid"]:
        raise HTTPException(
            status_code=400, detail=f"Freigabe-Token abgelehnt: {pre['reason']}"
        )
    rid = str(pre["request_id"])
    record = approval_engine.get_request(rid)
    if record is None:
        raise HTTPException(status_code=404, detail="Freigabeanfrage nicht gefunden.")

    effective_actor = str(actor or "").strip()
    if chat_id is not None:
        from backend import telegram_gateway_v2 as tg_gateway

        canonical = f"hitl:{'reject' if action == 'deny' else 'approve'}:{rid}"
        authz = tg_gateway.authorize_hitl_callback(
            canonical,
            chat_id,
            approval_record=record,
            expected_user_id=str(pre["actor"] or "") or None,
        )
        if not authz.get("authorized"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Telegram-Callback nicht autorisiert: "
                    f"{authz.get('reason', 'unauthorized')}"
                ),
            )
        effective_actor = str(authz["actor"])

    # M95: ein an eine Person gebundenes Token darf nicht von einer anderen
    # Session oder einem anderen Chat eingeloest werden.
    if pre["actor"] and not (
        ape._actor_identity_tokens(str(pre["actor"]))
        & ape._actor_identity_tokens(effective_actor)
    ):
        raise HTTPException(status_code=403, detail="Token ist an eine andere Person gebunden.")

    gate = ape.evaluate_policy_gate(
        domain=str(record.get("domain") or "finance"),
        action=action,
        amount_eur=float(record.get("amount") or 0.0),
        actor=effective_actor,
        approver=effective_actor,
        request_id=rid,
        approval_token=clean_token,
    )
    if not gate["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={"code": gate["reason_code"], "message": gate["reason"]},
        )

    try:
        if action == "approve":
            result = approval_engine.approve_request(rid, approver_id=effective_actor)
        else:
            result = approval_engine.reject_request(
                rid, rejected_by=effective_actor, reason=reason or "Abgelehnt"
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Nur ID/Fingerprint loggen — niemals das Token selbst.
    logger.info(
        "[M69] Gate-Entscheidung %s fuer %s durch %s (token=%s)",
        action, rid, effective_actor, pre["fingerprint"],
    )
    return {
        "status": "success",
        "actor": effective_actor,
        "request_id": rid,
        "result": result,
    }


@router.get("/policy")
def api_policy_gates_get_policy(request: Request) -> Dict[str, Any]:
    """Gibt die validierte Policy (ohne Geheimnisse) fuer das M70/M74-Panel zurueck."""
    _rbac.require_admin_or_503(request)
    from backend.approval_policy_engine import load_approval_policy

    policy = load_approval_policy()
    return {"status": "success", "policy": policy}


@router.post("/evaluate")
def api_policy_gates_evaluate(
    request: Request, payload: GateEvaluationRequest
) -> Dict[str, Any]:
    """Einheitlicher Interface-Vertrag ``evaluate_policy_gate(...) -> dict``."""
    _rbac.require_admin_or_503(request)
    actor = _rbac.require_session_actor(request)
    from backend.approval_policy_engine import evaluate_policy_gate

    gate = evaluate_policy_gate(
        domain=payload.domain,
        action=payload.action,
        amount_eur=payload.amount_eur,
        vendor=payload.vendor,
        estimated_cost_usd=payload.estimated_cost_usd,
        actor=payload.actor or actor,
        approver=payload.approver or actor,
        request_id=payload.request_id,
        chain_depth=payload.chain_depth,
        actions_in_chain=payload.actions_in_chain,
    )
    return {"status": "success", "gate": gate}


@router.post("/tokens")
def api_policy_gates_issue_tokens(
    request: Request, payload: TokenIssueRequest
) -> JSONResponse:
    """Stellt kurzlebige Einmal-Tokens und die Telegram-Button-Payload aus."""
    _rbac.require_admin_or_503(request)
    actor = _rbac.require_session_actor(request)
    from backend.approval_policy_engine import issue_approval_token

    try:
        approve = issue_approval_token(
            payload.request_id,
            "approve",
            actor=payload.actor or actor,
            ttl_seconds=payload.ttl_seconds,
        )
        deny = issue_approval_token(
            payload.request_id,
            "deny",
            actor=payload.actor or actor,
            ttl_seconds=payload.ttl_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def _safe(issued: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in issued.items() if key != "token"}

    return _no_store({
        "status": "issued",
        "request_id": payload.request_id,
        "approve": _safe(approve),
        "deny": _safe(deny),
        "telegram_payload": {
            "text": (
                f"Freigabe erforderlich: {payload.request_id}\n"
                "Bitte eine der beiden Optionen waehlen."
            ),
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Freigeben", "callback_data": approve["callback_data"]},
                    {"text": "Ablehnen", "callback_data": deny["callback_data"]},
                ]]
            },
        },
    })


@router.post("/approve")
def api_policy_gates_session_approve(
    request: Request, payload: SessionGateDecisionRequest
) -> Dict[str, Any]:
    """Session-basierte Freigabe (RBAC: require_admin_or_503 + require_session_actor)."""
    _rbac.require_admin_or_503(request)
    actor = _rbac.require_session_actor(request)
    return _execute_decision(
        token=payload.approval_token,
        action="approve",
        request_id=payload.request_id,
        actor=actor,
        reason="",
    )


@router.post("/deny")
def api_policy_gates_session_deny(
    request: Request, payload: SessionGateDecisionRequest
) -> Dict[str, Any]:
    """Session-basierte Ablehnung (RBAC: require_admin_or_503 + require_session_actor)."""
    _rbac.require_admin_or_503(request)
    actor = _rbac.require_session_actor(request)
    return _execute_decision(
        token=payload.approval_token,
        action="deny",
        request_id=payload.request_id,
        actor=actor,
        reason=payload.reason,
    )


@router.post("/telegram/approve")
def api_policy_gates_telegram_approve(
    request: Request, payload: TelegramGateCallbackRequest
) -> Dict[str, Any]:
    """Telegram-Approve-Button: signiertes Token + M95-chat_id-Autorisierung."""
    return _execute_decision(
        token=payload.callback_data,
        action="approve",
        request_id="",
        actor="",
        reason="",
        chat_id=payload.chat_id,
    )


@router.post("/telegram/deny")
def api_policy_gates_telegram_deny(
    request: Request, payload: TelegramGateCallbackRequest
) -> Dict[str, Any]:
    """Telegram-Deny-Button: signiertes Token + M95-chat_id-Autorisierung."""
    return _execute_decision(
        token=payload.callback_data,
        action="deny",
        request_id="",
        actor="",
        reason=payload.reason,
        chat_id=payload.chat_id,
    )

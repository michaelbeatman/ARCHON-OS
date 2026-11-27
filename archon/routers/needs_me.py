"""M70/M74 — Router für das „Braucht mich“-Panel (neu, nicht in main.py registriert).

Der Integrator registriert::

    from archon.routers import needs_me as needs_me_router
    app.include_router(needs_me_router.router, prefix="/api/needs-me")

Alle Endpunkte verlangen eine verifizierte menschliche Rolle (admin/operator).
Service-Tokens, Viewer, Agenten- und Systemidentitäten werden mit 403 abgewiesen.
Der Router enthält bewusst KEINE Freigabe-/Reject-Route: das Panel bereitet
Entscheidungen vor, es erteilt sie nicht.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from backend.auto_review import AutoReviewRequest, run_auto_review
from backend.needs_me_panel import (
    NEEDS_ME_SSE_EVENT,
    NeedsMeBundle,
    collect_needs_me,
    is_agent_identity,
    normalize_escalation,
    sse_payload,
)

logger = logging.getLogger("archon.routers.needs_me")

# M95: nur menschliche Freigabeberechtigte. Viewer/Service/Agent nie.
_ALLOWED_ROLES: frozenset[str] = frozenset({"admin", "operator"})

# Injektionspunkt für den Integrator (M68/M69/M95-Verdrahtung).
# `collect`, `review`, `resolve_escalation`, `emit_event`, `get_current_user`.
_DEPS: dict[str, Callable[..., Any]] = {}

router = APIRouter(dependencies=[Depends(_forbid_viewer_writes)])


class EscalationPreviewBody(BaseModel):
    """Parameter für die read-only Vertretungsprüfung (kein Statuswechsel)."""

    model_config = ConfigDict(extra="ignore")

    owner: str = Field(default="admin", min_length=1, max_length=120)
    domain: str = Field(default="finance", max_length=80)
    requester_id: str = ""
    first_approver: str = ""


def configure(**deps: Callable[..., Any]) -> None:
    """Verdrahtet fuehrende Module; unbeannte Abhaengigkeiten bleiben bestehen."""
    allowed = {"collect", "review", "resolve_escalation", "emit_event", "get_current_user"}
    for name, fn in deps.items():
        if name not in allowed or not callable(fn):
            raise ValueError(f"Unbekannte needs_me-Abhaengigkeit: {name}")
        _DEPS[name] = fn


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump(mode="json"))
    raise TypeError("Unerwartetes Ergebnisobjekt des Panel-Providers.")


def _get_current_user(request: Request) -> Mapping[str, Any]:
    fn = _DEPS.get("get_current_user")
    if fn is None:
        from archon.routers.auth import get_current_user_from_request

        fn = get_current_user_from_request
    try:
        user = fn(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[NeedsMe] Session-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="Identitaetspruefung nicht verfuegbar.") from exc
    if not isinstance(user, Mapping):
        raise HTTPException(status_code=401, detail="Keine verifizierte Identitaet.")
    return user


def require_approver(request: Request) -> str:
    """Rollenzaun: nur admin/operator als menschliche Entscheider (403 sonst)."""
    user = _get_current_user(request)
    if bool(user.get("is_service")):
        raise HTTPException(status_code=403, detail="Service-Tokens duerfen keine Gates entscheiden.")
    role = str(user.get("role") or "").strip().lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Nur Administratoren oder Operatoren duerfen das Bedienfeld nutzen (Rolle: {role or 'unbekannt'}).",
        )
    actor = str(
        user.get("username") or user.get("user_id") or user.get("sub") or user.get("email") or ""
    ).strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Keine verifizierte Identitaet.")
    if is_agent_identity(actor):
        raise HTTPException(status_code=403, detail="Agenten-/Systemidentitaet ist kein HITL-Entscheider.")
    return actor


def _emit(payload: Mapping[str, Any]) -> dict[str, Any]:
    """SSE-Event mit Zählern/Status — keine Payload-Inhalte, keine Secrets."""
    event = dict(payload)
    emitter = _DEPS.get("emit_event")
    if emitter is None:

        def default_emitter(event_type: str, data: Mapping[str, Any]) -> Any:
            from archon.core.runtime import broadcast_event

            return broadcast_event(event_type, dict(data))

        emitter = default_emitter
    try:
        emitter(str(event.get("type") or NEEDS_ME_SSE_EVENT), event)
    except Exception as exc:
        # Ein fehlgeschlagener SSE-Versand darf die Fachantwort nicht faelschen.
        logger.warning("[NeedsMe] SSE-Event nicht gesendet: %s", exc)
    return event


def _collect(actor: str, tenant: str) -> Any:
    fn = _DEPS.get("collect")
    return fn(actor, tenant) if fn is not None else collect_needs_me(actor, tenant)


@router.get("")
def api_get_needs_me(request: Request, tenant: str = "default") -> dict[str, Any]:
    """Read-only: bündelt alle offenen Gates für den verifizierten Actor."""
    actor = require_approver(request)
    bundle = _collect(actor, tenant)
    return {"status": "success", "bundle": _as_dict(bundle)}


@router.post("/refresh")
def api_refresh_needs_me(request: Request, tenant: str = "default") -> dict[str, Any]:
    """Löst nur ein SSE-Update aus; es wird keine Freigabe verändert."""
    actor = require_approver(request)
    bundle = _collect(actor, tenant)
    event = _emit(sse_payload(_bundle_model(bundle)))
    return {"status": "success", "event": event}


def _bundle_model(value: Any) -> NeedsMeBundle:
    """sse_payload akzeptiert das Bundle-Modell; DI-Provider liefern dieses."""
    if isinstance(value, NeedsMeBundle):
        return value
    # Fremde Provider duerfen ein Dict liefern — dann nur die Zaehler uebernehmen.
    data = _as_dict(value)
    return NeedsMeBundle.model_validate(
        {
            "actor": str(data.get("actor") or ""),
            "tenant": str(data.get("tenant") or "default"),
            "actor_is_human": bool(data.get("actor_is_human", True)),
            "generated_at": str(data.get("generated_at") or ""),
            "items": [],
        }
    )


@router.post("/auto-review")
def api_run_auto_review(request: Request, body: AutoReviewRequest) -> dict[str, Any]:
    """Fuehrt die Pre-Gate-Runde aus; NEVER auto-approve."""
    actor = require_approver(request)
    logger.info("[NeedsMe] Auto-Review angefordert von %s fuer %s", actor, body.request_id)
    fn = _DEPS.get("review")
    result = fn(body) if fn is not None else run_auto_review(body)
    data = _as_dict(result)
    _emit(
        {
            "type": NEEDS_ME_SSE_EVENT,
            "action": "auto_review",
            "request_id": body.request_id,
            "ready": bool(data.get("ready_for_human_gate")),
            "evidence_count": len(data.get("evidence") or []),
        }
    )
    return {"status": "success", "result": data}


@router.post("/{item_id}/escalation-preview")
def api_escalation_preview(
    request: Request, item_id: str, body: EscalationPreviewBody
) -> dict[str, Any]:
    """Zeigt das M95-Eskalationsziel — ohne Vertretung zu aktivieren."""
    require_approver(request)
    fn = _DEPS.get("resolve_escalation")
    if fn is None:
        from backend.approval_policy_engine import approval_engine

        fn = approval_engine.resolve_human_escalation_target
    raw = fn(
        body.owner,
        domain=body.domain,
        requester_id=body.requester_id or None,
        first_approver=body.first_approver or None,
    )
    info = normalize_escalation(
        _as_dict(raw) if isinstance(raw, Mapping) else {},
        owner=body.owner,
        requester_id=body.requester_id,
        first_approver=body.first_approver,
    )
    event = _emit(
        {
            "type": NEEDS_ME_SSE_EVENT,
            "action": "escalation_preview",
            "item_id": item_id,
            "resolved": info.resolved,
            "blocked": info.status == "escalated_blocked",
        }
    )
    return {"status": "success", "item_id": item_id, "escalation": info.model_dump(), "event": event}

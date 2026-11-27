"""M112: Read-only-Endpunkte fuer das unveraenderliche Event-Ledger.

Der Router wird bewusst NICHT in ``main.py`` registriert (Dateihoheit des
Integrators). Registrierungs-Snippet:

    from archon.routers.event_ledger import router as event_ledger_router
    app.include_router(event_ledger_router)

Alle drei Routen sind GET, verlangen den zentralen Admin-Rollenzaun und einen
verifizierten Session-Actor. Bei ungueltiger Verification/Replay wird mit 503
und vollem Pruefbericht geantwortet (fail-closed sichtbar), niemals mit einem
stillen leeren Erfolg. Antworten enthalten keine Payload-Rohdaten und keine
Secrets; das Ledger redigiert sensible Felder bereits beim Schreiben.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request
from fastapi import Depends as _ArchonDepends
from fastapi.responses import JSONResponse

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from backend.event_ledger import EventLedger

logger = logging.getLogger("archon.routers.event_ledger")

router = APIRouter(
    dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["event_ledger"]
)

_configured_ledger: Optional[EventLedger] = None


def configure(ledger: Optional[EventLedger] = None) -> None:
    """Injektion der Ledger-Instanz (Tests / applikationsweite Singleton-Nutzung)."""
    global _configured_ledger
    _configured_ledger = ledger


def _get_ledger() -> EventLedger:
    global _configured_ledger
    if _configured_ledger is None:
        _configured_ledger = EventLedger()
    return _configured_ledger


def _require_admin(request: Request) -> None:
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


def _guard(request: Request) -> str:
    """Admin-Gate + verifizierter Actor (kein Body-/Header-Fallback)."""
    _require_admin(request)
    from archon.routers._rbac import require_session_actor

    return require_session_actor(request)


def _invalid(report: Dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"status": "error", "ledger_valid": False, "verification": report},
    )


@router.get("/api/event-ledger/status")
def api_event_ledger_status(request: Request) -> Dict[str, Any]:
    """Zustand, Anker-Konfiguration und letzter Merkle-Root (read-only)."""
    actor = _guard(request)
    logger.info("[EventLedger] Status abgerufen von %s", actor)
    return {"status": "ok", "ledger": _get_ledger().status()}


@router.get("/api/event-ledger/verify")
def api_event_ledger_verify(
    request: Request,
    check_anchor: bool = Query(default=True, description="Externen Merkle-Anker mitpruefen"),
) -> Any:
    """Vollstaendige Ketten-, Luecken- und Ankerpruefung."""
    actor = _guard(request)
    logger.info("[EventLedger] Verification abgerufen von %s", actor)
    report = _get_ledger().verify_ledger(
        store=_get_ledger().anchor_store if check_anchor else None,
        require_anchor=None if check_anchor else False,
    )
    if not report.get("valid"):
        return _invalid(report)
    return {"status": "ok", "verification": report}


@router.get("/api/event-ledger/replay")
def api_event_ledger_replay(
    request: Request,
    from_block: int = Query(default=1, ge=1),
    to_block: Optional[int] = Query(default=None, ge=1),
    limit: Optional[int] = Query(default=None, ge=1, le=10000),
    include_pending: bool = Query(default=False),
) -> Any:
    """Compliance-Replay (M68) in der Reihenfolge der finalen Eintraege."""
    actor = _guard(request)
    logger.info("[EventLedger] Replay abgerufen von %s", actor)
    report = _get_ledger().replay(
        from_block=from_block,
        to_block=to_block,
        limit=limit,
        include_pending=include_pending,
        store=_get_ledger().anchor_store,
    )
    if not report.get("valid"):
        return _invalid(report)
    return {"status": "ok", "replay": report}

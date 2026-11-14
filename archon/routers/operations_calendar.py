"""
archon/routers/operations_calendar.py
=====================================
M25 — Operativer Operations-Kalender Endpunkte.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.operations_calendar import operations_calendar

router = APIRouter(
    prefix="/api/v1/calendar",
    tags=["Operations Calendar (M25)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("/events")
def list_calendar_events(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    source: str = Query("all"),
):
    events = operations_calendar.list_events(start_date=start_date, end_date=end_date, source=source)
    return {"status": "success", "count": len(events), "events": events}


@router.post("/events")
def create_calendar_event(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        ev = operations_calendar.create_event(payload)
        return {"status": "success", "event": ev}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/events/{event_id}")
def delete_calendar_event(request: Request, event_id: str):
    require_admin_or_503(request)
    deleted = operations_calendar.delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
    return {"status": "success", "deleted_id": event_id}

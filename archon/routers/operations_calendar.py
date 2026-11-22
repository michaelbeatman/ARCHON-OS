"""
archon/routers/operations_calendar.py
=====================================
M25 — Operativer Operations-Kalender Endpunkte.
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("operations_calendar")

import asyncio
import html
import json
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.operations_calendar import operations_calendar

router = APIRouter(
    prefix="/api/v1/calendar",
    tags=["Operations Calendar (M25)"],
    dependencies=[Depends(forbid_viewer_writes)],
)

ws_router = APIRouter(tags=["Operations Calendar WS"])
_ws_clients: Set[WebSocket] = set()
_ws_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_calendar_update(action: str, detail: Optional[Dict[str, Any]] = None) -> None:
    if not _ws_clients:
        return
    msg = json.dumps({"type": "calendar_changed", "action": action, "detail": detail or {}})
    async def _send_all():
        dead = []
        for ws in list(_ws_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients.discard(ws)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_all())
    except RuntimeError:
        if _ws_loop and _ws_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send_all(), _ws_loop)


@ws_router.websocket("/api/v1/calendar/ws")
async def calendar_ws_endpoint(websocket: WebSocket):
    global _ws_loop
    try:
        _ws_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    # Auth-Gate: Bei aktivem Multi-User-Auth muessen gueltige Session/Bearer-Token vorliegen
    try:
        from backend.auth_service import auth_service
        if auth_service.is_auth_enabled():
            tok = websocket.cookies.get("archon_session") or ""
            if not tok:
                auth_hdr = websocket.headers.get("authorization") or ""
                if auth_hdr.lower().startswith("bearer "):
                    tok = auth_hdr[7:].strip()
            user = auth_service.verify_session(tok) if tok else None
            if not user or user.get("role") == "anonymous":
                await websocket.close(code=1008)
                return
    except Exception as _exc:
        _archon_exc_logger.warning("[operations_calendar] WS-Auth-Pruefung fehlgeschlagen: %s", _exc)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
    except Exception:
        _ws_clients.discard(websocket)


@router.get("/events")
def list_calendar_events(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    source: str = Query("all"),
    company_id: Optional[str] = Query(None),
    holiday_state: str = Query("BY"),
):
    events = operations_calendar.list_events(
        start_date=start_date, end_date=end_date, source=source, company_id=company_id, holiday_state=holiday_state
    )
    return {"status": "success", "count": len(events), "events": events}


@router.post("/events")
def create_calendar_event(request: Request, payload: Dict[str, Any] = Body(...), company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    try:
        ev = operations_calendar.create_event(payload, company_id=company_id)
        broadcast_calendar_update("created", {"id": ev.get("id")})
        return {"status": "success", "event": ev}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/events/{event_id}")
def update_calendar_event(request: Request, event_id: str, payload: Dict[str, Any] = Body(...), company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    ev = operations_calendar.update_event(event_id, payload, company_id=company_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
    broadcast_calendar_update("updated", {"id": event_id})
    return {"status": "success", "event": ev}


@router.delete("/events/{event_id}")
def delete_calendar_event(
    request: Request,
    event_id: str,
    company_id: Optional[str] = Query(None),
    occurrence_date: Optional[str] = Query(None),
):
    require_admin_or_503(request)
    deleted = operations_calendar.delete_event(event_id, company_id=company_id, occurrence_date=occurrence_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
    broadcast_calendar_update("deleted", {"id": event_id})
    return {"status": "success", "deleted_id": event_id}


@router.post("/events/{event_id}/invite")
def send_calendar_invites(request: Request, event_id: str, company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    try:
        res = operations_calendar.send_invites(event_id, company_id=company_id)
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/events/{event_id}/rsvp")
def update_calendar_rsvp(request: Request, event_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        res = operations_calendar.update_rsvp(event_id, email=str(payload.get("email") or ""), status=str(payload.get("status") or "pending"))
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")


@router.post("/events/{event_id}/push")
def push_calendar_event(request: Request, event_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    ev = next((e for e in operations_calendar.list_events(source="custom") if e.get("id") == event_id), None)
    if not ev:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
    try:
        res = operations_calendar.push_event_to_source(str(payload.get("source_id") or ""), ev)
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Kalenderquelle nicht gefunden.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/booking-types")
def list_booking_types():
    return {"status": "success", "types": operations_calendar.list_booking_types()}


@router.post("/booking-types")
def save_booking_type(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        item = operations_calendar.upsert_booking_type(payload)
        return {"status": "success", "type": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/booking-types/{slug}")
def delete_booking_type(request: Request, slug: str):
    require_admin_or_503(request)
    if not operations_calendar.delete_booking_type(slug):
        raise HTTPException(status_code=404, detail="Buchungstyp nicht gefunden.")
    return {"status": "success", "deleted_slug": slug}


@router.get("/booking/{slug}")
def get_public_booking_slots(slug: str, duration_min: Optional[int] = Query(None, ge=15, le=240)):
    bt = operations_calendar.get_booking_type(slug)
    slots = operations_calendar.get_booking_slots_for_slug(slug, duration_min=duration_min)
    return {
        "status": "success",
        "slug": slug,
        "duration_min": duration_min or bt.get("duration_min", 30),
        "event_type": bt,
        "all_types": operations_calendar.list_booking_types(),
        "slots": slots,
    }


@router.post("/booking/{slug}")
def submit_public_booking(slug: str, payload: Dict[str, Any] = Body(...)):
    try:
        ev = operations_calendar.book_public_slot(slug, payload)
        broadcast_calendar_update("booking_created", {"id": ev.get("id"), "slug": slug})
        return {"status": "success", "event": ev}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/sources")
def list_calendar_sources(request: Request):
    require_admin_or_503(request)
    _secret_keys = {"password", "access_token", "refresh_token", "client_secret", "token"}
    sources = [{k: v for k, v in s.items() if k not in _secret_keys} for s in operations_calendar.list_sources()]
    return {"status": "success", "sources": sources}


@router.post("/sources")
def save_calendar_source(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        src = operations_calendar.upsert_source(payload)
        return {"status": "success", "source": src}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/sources/{src_id}")
def delete_calendar_source(request: Request, src_id: str):
    require_admin_or_503(request)
    if not operations_calendar.delete_source(src_id):
        raise HTTPException(status_code=404, detail="Kalenderquelle nicht gefunden.")
    return {"status": "success", "deleted_id": src_id}


@router.post("/sources/{src_id}/sync")
def sync_calendar_source(request: Request, src_id: str):
    require_admin_or_503(request)
    try:
        res = operations_calendar.sync_source(src_id)
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Kalenderquelle nicht gefunden.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sync fehlgeschlagen: {exc}")


@router.post("/import-ics")
def import_ics_calendar(request: Request, payload: Dict[str, Any] = Body(...), company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    ics_text = str(payload.get("ics_text") or "")
    if not ics_text.strip():
        raise HTTPException(status_code=400, detail="ics_text erforderlich")
    created = operations_calendar.import_ics_text(ics_text, company_id=company_id)
    return {"status": "success", "imported": len(created), "events": created}


@router.get("/export.ics")
def export_ics_calendar(company_id: Optional[str] = Query(None)):
    ics = operations_calendar.export_ics_text(company_id=company_id)
    return Response(content=ics, media_type="text/calendar", headers={"Content-Disposition": "attachment; filename=archon-calendar.ics"})


@router.get("/focus-slots")
def find_calendar_focus_slots(duration_min: int = Query(90, ge=15, le=240), days_ahead: int = Query(5, ge=1, le=14)):
    return {"status": "success", "slots": operations_calendar.find_focus_slots(duration_min=duration_min, days_ahead=days_ahead)}


@router.get("/resources")
def get_calendar_resources():
    return {"status": "success", "resources": operations_calendar.list_resources()}


@router.post("/resources")
def save_calendar_resources(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    items = payload.get("resources") if isinstance(payload.get("resources"), list) else []
    saved = operations_calendar.save_resources(items)
    return {"status": "success", "resources": saved}


@router.get("/free-busy")
def get_team_free_busy(
    date: str = Query(""),
    resources: str = Query(""),
    duration_min: int = Query(30, ge=15, le=240),
    company_id: Optional[str] = Query(None),
):
    res_list = [r.strip() for r in resources.split(",") if r.strip()]
    data = operations_calendar.find_team_availability(res_list, date_str=date, duration_min=duration_min, company_id=company_id)
    return {"status": "success", **data}


@router.post("/quick-add")
def quick_add_calendar_event(request: Request, payload: Dict[str, Any] = Body(...), company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    try:
        ev = operations_calendar.parse_and_create_quick_add(str(payload.get("text") or ""), company_id=company_id)
        broadcast_calendar_update("quick_add", {"id": ev.get("id")})
        return {"status": "success", "event": ev}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/oauth/config")
def get_calendar_oauth_config(request: Request):
    require_admin_or_503(request)
    return {"status": "success", "config": operations_calendar.get_oauth_config(mask_secret=True)}


@router.post("/oauth/config")
def save_calendar_oauth_config(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    cfg = operations_calendar.save_oauth_config(payload)
    return {"status": "success", "config": cfg}


@router.get("/oauth/{provider}/start")
def start_calendar_oauth(request: Request, provider: str, source_name: str = Query("")):
    require_admin_or_503(request)
    base = str(request.base_url).rstrip("/")
    prov = "google" if "google" in provider else "outlook"
    redirect_uri = f"{base}/api/v1/calendar/oauth/{prov}/callback"
    try:
        url = operations_calendar.build_oauth_authorize_url(prov, redirect_uri=redirect_uri, source_name=source_name)
        return RedirectResponse(url=url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/oauth/{provider}/callback")
def calendar_oauth_callback(provider: str, code: str = Query(""), state: str = Query(""), error: str = Query("")):
    if error:
        return HTMLResponse(f"<h3>OAuth Fehler: {html.escape(str(error))}</h3>", status_code=400)
    try:
        src = operations_calendar.complete_oauth_callback(code=code, state=state)
        safe_name = html.escape(str(src.get("name") or ""))
        safe_payload = json.dumps({"type": "archon_cal_oauth_done", "source_id": str(src.get("id") or "")})
        return HTMLResponse(
            f"""<!doctype html><html><body style="font-family:sans-serif;padding:24px;background:#0f172a;color:#e2e8f0;">
            <h3>Kalender verbunden: {safe_name}</h3>
            <p>Du kannst dieses Fenster jetzt schliessen.</p>
            <script>
              if (window.opener) window.opener.postMessage({safe_payload}, window.location.origin);
              setTimeout(() => window.close(), 1200);
            </script></body></html>"""
        )
    except Exception as exc:
        return HTMLResponse(f"<h3>OAuth Callback fehlgeschlagen: {html.escape(str(exc))}</h3>", status_code=400)


@router.get("/check-conflict")
def check_resource_conflict_endpoint(
    resource: str = Query(""),
    date: str = Query(""),
    start: str = Query(""),
    end: str = Query(""),
    exclude_id: str = Query(""),
    company_id: Optional[str] = Query(None),
):
    conflicts = operations_calendar.check_resource_conflict(
        resource=resource, date_str=date, start_str=start, end_str=end, exclude_id=exclude_id, company_id=company_id
    )
    return {"status": "success", "has_conflict": bool(conflicts), "conflicts": conflicts}


@router.post("/sources/{src_id}/watch")
def register_calendar_webhook_watch(request: Request, src_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    base = str(request.base_url).rstrip("/")
    webhook_url = str(payload.get("webhook_url") or f"{base}/api/v1/calendar/webhooks/push")
    try:
        res = operations_calendar.register_webhook_watch(src_id, webhook_url=webhook_url)
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Kalenderquelle nicht gefunden.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.api_route("/webhooks/push", methods=["GET", "POST"])
def receive_calendar_push_webhook(request: Request, validationToken: Optional[str] = Query(None)):
    if validationToken:
        return PlainTextResponse(content=validationToken, status_code=200)
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    res = operations_calendar.handle_webhook_push(channel_id=channel_id)
    broadcast_calendar_update("webhook_synced", res)
    return {"status": "success", **res}


@router.post("/rsvp/ingest-ics")
def ingest_rsvp_ics_reply(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    updates = operations_calendar.process_rsvp_ics_text(str(payload.get("ics_text") or ""))
    return {"status": "success", "updated": updates}


@router.post("/rsvp/poll-imap")
def poll_imap_rsvp(request: Request):
    require_admin_or_503(request)
    res = operations_calendar.poll_imap_rsvp_replies()
    return {"status": "success", **res}


@router.post("/nl-query")
def run_calendar_nl_query(request: Request, payload: Dict[str, Any] = Body(...), company_id: Optional[str] = Query(None)):
    require_admin_or_503(request)
    try:
        answer = operations_calendar.handle_calendar_nl_query(str(payload.get("text") or ""), company_id=company_id)
        return {"status": "success", "answer": answer}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/maintenance/run")
def trigger_calendar_maintenance(request: Request):
    require_admin_or_503(request)
    return {"status": "success", **operations_calendar.run_maintenance_cycle()}


operations_calendar.start_background_maintenance(interval_sec=900)

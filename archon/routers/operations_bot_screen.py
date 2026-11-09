"""Sub-Router fuer Bot Screen & Human Takeover (Virtual Desktop Integration).

Ausgelagert aus backend/operations_api.py.
"""

import datetime
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

router = APIRouter()

_bot_screen_state = {
    "active": True,
    "session_id": "hermes-desktop-main",
    "display": ":99",
    "resolution": "1920x1080",
    "agent_name": "Hermes Web & Desktop Agent",
    "current_url": "https://dashboard.service.internal",
    "takeover_requested": False,
    "takeover_reason": "",
    "takeover_timestamp": None,
    "last_interaction": None,
    "mouse_control_enabled": True,
}


def _get_kanban_connection():
    from backend.operations_api import _get_kanban_connection as _kgc
    return _kgc()


@router.get("/bot-screen/status")
def get_bot_screen_status():
    """Liefert den aktuellen Status des virtuellen Desktops & Human Takeover."""
    return _bot_screen_state


class TakeoverRequestModel(BaseModel):
    reason: str
    url: Optional[str] = None
    agent_name: Optional[str] = None


@router.post("/bot-screen/takeover/request")
def request_human_takeover(request: Request, req: TakeoverRequestModel):
    """Wird von einem Agenten ausgelöst, wenn ein Captcha oder 2FA-Schranke erkannt wird."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    _bot_screen_state["takeover_requested"] = True
    _bot_screen_state["takeover_reason"] = req.reason
    _bot_screen_state["takeover_timestamp"] = datetime.datetime.now().isoformat()
    if req.url:
        _bot_screen_state["current_url"] = req.url
    if req.agent_name:
        _bot_screen_state["agent_name"] = req.agent_name

    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps(
            {
                "author": "bot_desktop",
                "message": f"🚨 Human Takeover angefordert: {req.reason} ({_bot_screen_state['current_url']})",
                "target": "commander",
                "broadcast": True,
                "takeover_requested": True,
                "url": _bot_screen_state["current_url"],
            },
            ensure_ascii=False,
        )
        cur.execute(
            """
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'human_takeover_requested', ?, ?)
        """,
            (payload, now_iso),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "takeover_active", "state": _bot_screen_state}


@router.post("/bot-screen/takeover/resume")
def resume_from_human_takeover(request: Request):
    """Wird vom Nutzer per Klick auf 'Agent fortsetzen' aufgerufen."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    _bot_screen_state["takeover_requested"] = False
    _bot_screen_state["takeover_reason"] = ""
    _bot_screen_state["aborted"] = False
    _bot_screen_state["mouse_control_enabled"] = True
    _bot_screen_state["agent_authorized"] = True
    _bot_screen_state["last_interaction"] = datetime.datetime.now().isoformat()

    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps(
            {
                "author": "commander",
                "message": "✅ Human Takeover abgeschlossen: Nutzer hat Freigabe erteilt. Agent setzt Ausführung fort.",
                "target": "all",
                "broadcast": True,
                "takeover_resolved": True,
            },
            ensure_ascii=False,
        )
        cur.execute(
            """
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'human_takeover_resolved', ?, ?)
        """,
            (payload, now_iso),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "resumed", "state": _bot_screen_state}


class ScreenInteractionModel(BaseModel):
    action: str = "click"  # click, key, scroll
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None


@router.post("/bot-screen/interact")
def interact_with_bot_screen(request: Request, action_data: ScreenInteractionModel):
    """Nimmt Benutzerinteraktionen (Klick, Tasteneingabe) entgegen."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if (
        _bot_screen_state.get("aborted")
        or not _bot_screen_state.get("agent_authorized", True)
        or not _bot_screen_state.get("mouse_control_enabled", True)
    ):
        raise HTTPException(
            status_code=409,
            detail="Interaktion blockiert: Notfall-Abbruch aktiv oder Steuerung gesperrt.",
        )
    _bot_screen_state["last_interaction"] = datetime.datetime.now().isoformat()
    return {"status": "success", "echo": action_data.dict()}


@router.post("/bot-screen/abort")
def abort_bot_screen_execution(request: Request):
    """Notfall-Abbruch: Entzieht dem Agenten sofort alle Rechte und stoppt aktive Browser-Aktionen."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    _bot_screen_state["aborted"] = True
    _bot_screen_state["takeover_requested"] = False
    _bot_screen_state["mouse_control_enabled"] = False
    _bot_screen_state["agent_authorized"] = False
    now_iso = datetime.datetime.now().isoformat()
    try:
        conn = _get_kanban_connection()
        cur = conn.cursor()
        payload = json.dumps(
            {
                "author": "commander",
                "message": "🛑 Notfall-Abbruch: Sofortiger Stopp aller Browser- und Desktop-Aktionen. Volle Kontrolle liegt wieder beim Nutzer.",
                "target": "all",
                "broadcast": True,
                "aborted": True,
            },
            ensure_ascii=False,
        )
        cur.execute(
            """
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'emergency_abort', ?, ?)
        """,
            (payload, now_iso),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"status": "aborted", "state": _bot_screen_state}

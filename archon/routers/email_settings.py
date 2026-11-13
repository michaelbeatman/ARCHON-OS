"""Router fuer SMTP-Settings und E-Mail-Synchronisation."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("archon.routers.email_settings")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["email_settings"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


class SmtpConfigPayload(BaseModel):
    enabled: Optional[bool] = False
    auto_send: Optional[bool] = False
    host: Optional[str] = ""
    port: Optional[int] = 587
    username: Optional[str] = ""
    password: Optional[str] = ""
    from_email: Optional[str] = ""
    to_email: Optional[str] = ""
    use_tls: Optional[bool] = True


@router.get("/api/v1/settings/smtp")
def api_get_smtp_settings():
    from backend.post_task_pipeline import get_smtp_config

    cfg = get_smtp_config()
    safe_cfg = dict(cfg)
    if safe_cfg.get("password"):
        safe_cfg["password"] = "••••••••"
    return {"status": "ok", "config": safe_cfg}


@router.post("/api/v1/settings/smtp")
def api_save_smtp_settings(request: Request, payload: SmtpConfigPayload):
    _require_admin(request)
    from backend.post_task_pipeline import get_smtp_config, save_smtp_config

    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    success = save_smtp_config(cfg_data)
    return {"status": "success" if success else "error"}


@router.post("/api/v1/settings/smtp/test")
def api_test_smtp_settings(request: Request, payload: SmtpConfigPayload):
    _require_admin(request)
    from backend.post_task_pipeline import get_smtp_config, save_smtp_config, send_smtp_email

    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    save_smtp_config(cfg_data)

    sub = "🧪 Archon OS: SMTP-Testnachricht"
    body = "Dies ist eine automatische Testnachricht von deinem Archon OS System. Die E-Mail-Konfiguration funktioniert einwandfrei!"
    html = "<div style='font-family: sans-serif; padding: 20px;'><h2 style='color: #0f172a;'>🧪 Archon OS SMTP-Test</h2><p>Die E-Mail-Konfiguration funktioniert einwandfrei!</p></div>"
    res = send_smtp_email(sub, body, html)
    return res


@router.post("/api/v1/inbox/emails/sync")
def api_sync_emails_endpoint():
    try:
        from backend.email_service import sync_imap_inbox

        return sync_imap_inbox(limit=30)
    except Exception as e:
        return {"status": "error", "message": str(e), "synced": 0}

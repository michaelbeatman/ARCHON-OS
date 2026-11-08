"""Router /api/crm — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

from archon.routers._rbac import require_admin_or_503

router = APIRouter()

@router.get("/api/crm/contacts")
def api_crm_list_contacts(
    search: str = "",
    status: str = "",
    role: str = "all",
    region: str = "",
    tag: str = "",
    sort_by: str = "updated",
    sort_order: str = "desc",
    page: int = 1,
    limit: int = 100
):
    from backend.crm_service import crm_service
    return crm_service.list_contacts(
        search=search, status=status, role_filter=role, region=region,
        tag=tag, sort_by=sort_by, sort_order=sort_order, page=page, limit=limit
    )


@router.get("/api/crm/contacts/{contact_id}")
def api_crm_get_contact(contact_id: str):
    from backend.crm_service import crm_service
    contact = crm_service.get_contact_detail(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    return contact


@router.post("/api/crm/contacts")
def api_crm_create_contact(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.crm_service import crm_service
    return crm_service.save_contact(contact_id=payload.get("id"), payload=payload)


@router.put("/api/crm/contacts/{contact_id}")
def api_crm_update_contact(request: Request, contact_id: str, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.crm_service import crm_service
    return crm_service.save_contact(contact_id=contact_id, payload=payload)


@router.delete("/api/crm/contacts/{contact_id}")
def api_crm_delete_contact(request: Request, contact_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.crm_service import crm_service
    ok = crm_service.delete_contact(contact_id)
    return {"success": ok}


@router.post("/api/crm/contacts/{contact_id}/messages")
def api_crm_add_message(request: Request, contact_id: str, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.crm_service import crm_service
    text = payload.get("text", "")
    channel = payload.get("channel", "note")
    direction = payload.get("direction", "outbound")
    sender = payload.get("sender", "Michael Keller")
    return crm_service.add_contact_message(
        contact_id=contact_id, text=text, channel=channel, direction=direction, sender=sender
    )


@router.get("/api/crm/messages")
def api_crm_list_messages(
    search: str = "",
    channel: str = "all",
    direction: str = "all",
    sort: str = "newest",
    page: int = 1,
    limit: int = 50
):
    from backend.crm_service import crm_service
    return crm_service.list_all_messages(
        search=search, channel=channel, direction=direction, sort=sort, page=page, limit=limit
    )


@router.get("/api/crm/calendar")
def api_crm_get_calendar():
    from backend.crm_service import crm_service
    return crm_service.get_calendar_events()


@router.get("/api/crm/report")
def api_crm_get_report():
    from backend.crm_service import crm_service
    return crm_service.get_report_metrics()


@router.get("/api/crm/avatars/{contact_id}/{filename}")
def api_crm_avatar(contact_id: str, filename: str):
    # F13: Path-Traversal-Schutz
    if any(sep in contact_id or sep in filename for sep in ("/", "\\")) or ".." in contact_id or ".." in filename:
        raise HTTPException(status_code=400, detail="Ungueltige Pfadparameter")

    from archon.core.runtime import WORKSPACE_DIR
    from utils.path_jail import safe_filename, safe_path_within, PathJailError

    clean_cid = safe_filename(contact_id)
    clean_fn = safe_filename(filename)

    pb_avatar_dir = os.path.join(WORKSPACE_DIR, "pocketbase", "pb_data", "storage", "pbc_1512878646", clean_cid)
    static_avatar_dir = os.path.join(WORKSPACE_DIR, "static", "avatars")

    # 1. Pocketbase Storage
    try:
        cand_pb = os.path.join(pb_avatar_dir, clean_fn)
        safe_pb = safe_path_within(cand_pb, [pb_avatar_dir], allow_write=False, allow_dirs=False)
        if os.path.isfile(safe_pb):
            return FileResponse(safe_pb)
    except (PathJailError, ValueError):
        pass

    # 2. Static Avatars
    try:
        cand_static = os.path.join(static_avatar_dir, clean_fn)
        safe_static = safe_path_within(cand_static, [static_avatar_dir], allow_write=False, allow_dirs=False)
        if os.path.isfile(safe_static):
            return FileResponse(safe_static)
    except (PathJailError, ValueError):
        pass

    raise HTTPException(status_code=404, detail="Avatar not found")


@router.get("/api/crm/contacts/{contact_id}/gdpr-export")
def api_crm_gdpr_export(contact_id: str):
    from backend.crm_service import crm_service
    res = crm_service.export_gdpr(contact_id)
    if not res:
        raise HTTPException(status_code=404, detail="Contact not found")
    return res


@router.post("/api/crm/contacts/{contact_id}/gdpr-anonymize")
def api_crm_gdpr_anonymize(request: Request, contact_id: str):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.crm_service import crm_service
    ok = crm_service.anonymize_gdpr(contact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found or update failed")
    return {"success": True, "message": "Contact anonymized per Art. 17 GDPR"}

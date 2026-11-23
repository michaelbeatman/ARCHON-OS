"""Router /api/context-packages — wiederverwendbare Kontext-Pakete fuer Workflow-Stationen."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile

from archon.routers._rbac import require_admin_or_503

router = APIRouter()


@router.post("/api/context-packages")
async def api_create_context_package(
    request: Request,
    file: UploadFile = File(...),
    scope: str = Form("project"),
    acl_json: str = Form("[]"),
    ttl_seconds: int = Form(0),
    description: str = Form(""),
):
    require_admin_or_503(request)
    from backend.context_packages import create_package

    try:
        acl = json.loads(acl_json or "[]")
        if not isinstance(acl, list):
            raise ValueError("acl_json muss eine Liste sein.")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Ungueltige ACL: {exc}")

    raw = await file.read()
    try:
        meta = create_package(
            raw,
            file.filename or "upload.bin",
            scope=scope,
            acl=acl,
            ttl_seconds=ttl_seconds,
            description=description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "package": meta}


@router.get("/api/context-packages")
def api_list_context_packages(agent_id: str = "", scope: Optional[str] = None):
    from backend.context_packages import list_packages

    return {"status": "ok", "packages": list_packages(agent_id=agent_id, scope=scope)}


@router.get("/api/context-packages/{ctx_id}")
def api_get_context_package(ctx_id: str):
    from backend.context_packages import get_package

    meta = get_package(ctx_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Kontext-Paket nicht gefunden.")
    return {"status": "ok", "package": meta}


@router.delete("/api/context-packages/{ctx_id}")
def api_delete_context_package(request: Request, ctx_id: str):
    require_admin_or_503(request)
    from backend.context_packages import delete_package

    if not delete_package(ctx_id):
        raise HTTPException(status_code=404, detail="Kontext-Paket nicht gefunden.")
    return {"status": "ok", "deleted": ctx_id}

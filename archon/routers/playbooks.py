"""
archon/routers/playbooks.py
===========================
M44 — Business Playbooks (Operations-Vorlagen, Katalog & Editor).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.playbooks_engine import playbooks_engine

router = APIRouter(
    prefix="/api/v1/playbooks",
    tags=["Playbooks (M44)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("")
def list_playbooks(
    active_only: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    items = playbooks_engine.list_playbooks(active_only=active_only, category=category, search=search)
    return {"status": "success", "count": len(items), "playbooks": items}


@router.get("/{playbook_id}")
def get_playbook(playbook_id: str):
    pb = playbooks_engine.get_playbook(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook nicht gefunden.")
    return {"status": "success", "playbook": pb}


@router.post("")
def create_playbook(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        pb = playbooks_engine.create_playbook(payload)
        return {"status": "success", "playbook": pb}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{playbook_id}")
def update_playbook(request: Request, playbook_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    try:
        pb = playbooks_engine.update_playbook(playbook_id, payload)
        return {"status": "success", "playbook": pb}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{playbook_id}/toggle")
def toggle_playbook(request: Request, playbook_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    active = bool(payload.get("active", True))
    try:
        pb = playbooks_engine.toggle_playbook(playbook_id, active)
        return {"status": "success", "playbook": pb}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{playbook_id}")
def delete_playbook(request: Request, playbook_id: str):
    require_admin_or_503(request)
    try:
        deleted = playbooks_engine.delete_playbook(playbook_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Playbook nicht gefunden.")
        return {"status": "success", "deleted_id": playbook_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{playbook_id}/run")
def run_playbook(request: Request, playbook_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    variables = payload.get("variables") or {}
    try:
        run_res = playbooks_engine.run_playbook(playbook_id, variables=variables)
        return {"status": "success", "run": run_res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

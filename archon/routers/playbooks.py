"""
archon/routers/playbooks.py
===========================
M44 — Business Playbooks (Operations-Vorlagen, Katalog & Editor).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.playbooks_engine import playbooks_engine


class PlaybookStep(BaseModel):
    """Ein einzelner Schritt einer Playbook-Vorlage (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=300)
    agent_id: str = Field(default="", max_length=128)
    prompt_template: str = Field(default="", max_length=50_000)


class PlaybookCreateRequest(BaseModel):
    """Validierter Payload für POST /api/v1/playbooks (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=300)
    category: str = Field(default="Operations & Führung", max_length=120)
    description: str = Field(default="", max_length=5_000)
    active: bool = True
    variables: List[str] = Field(default_factory=list, max_length=100)
    steps: List[PlaybookStep] = Field(default_factory=list, max_length=200)
    id: Optional[str] = Field(default=None, max_length=128)


class PlaybookUpdateRequest(BaseModel):
    """Validierter Payload für PUT /api/v1/playbooks/{id} (Etappe 7).

    None bedeutet "nicht angegeben" und wird nicht an die Engine weitergereicht.
    """
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = Field(default=None, max_length=300)
    category: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=5_000)
    active: Optional[bool] = None
    variables: Optional[List[str]] = Field(default=None, max_length=100)
    steps: Optional[List[PlaybookStep]] = Field(default=None, max_length=200)


class PlaybookToggleRequest(BaseModel):
    """Validierter Payload für POST /api/v1/playbooks/{id}/toggle (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    active: bool = True


class PlaybookRunRequest(BaseModel):
    """Optionaler Payload für POST /api/v1/playbooks/{id}/run (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    variables: Dict[str, Any] = Field(default_factory=dict)
    execute: bool = True


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
def create_playbook(request: Request, payload: PlaybookCreateRequest):
    require_admin_or_503(request)
    try:
        pb = playbooks_engine.create_playbook(payload.model_dump(exclude_none=True))
        return {"status": "success", "playbook": pb}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{playbook_id}")
def update_playbook(request: Request, playbook_id: str, payload: PlaybookUpdateRequest):
    require_admin_or_503(request)
    try:
        pb = playbooks_engine.update_playbook(playbook_id, payload.model_dump(exclude_none=True))
        return {"status": "success", "playbook": pb}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{playbook_id}/toggle")
def toggle_playbook(request: Request, playbook_id: str, payload: PlaybookToggleRequest):
    require_admin_or_503(request)
    active = payload.active
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
async def run_playbook(request: Request, playbook_id: str, payload: PlaybookRunRequest = Body(default=PlaybookRunRequest())):
    require_admin_or_503(request)
    variables = payload.variables
    execute_now = payload.execute
    try:
        run_res = playbooks_engine.run_playbook(playbook_id, variables=variables)
        if execute_now:
            import asyncio
            asyncio.create_task(playbooks_engine.execute_run_async(run_res))
        return {"status": "success", "run": run_res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

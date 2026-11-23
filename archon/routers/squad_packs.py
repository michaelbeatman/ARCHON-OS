"""
archon/routers/squad_packs.py
=============================
M51 — REST-Endpunkte für den .archonpack Squad-Blueprint-Paketmanager.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.squad_pack_manager import squad_pack_manager

router = APIRouter(
    prefix="/api/v1/squad-packs",
    tags=["Squad Blueprints (M51)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


class SquadPackExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(default="archon-squad", max_length=120)
    domain: Optional[str] = Field(default=None, max_length=120)
    agent_ids: Optional[List[str]] = Field(default=None, max_length=200)
    include_prompts: bool = True
    include_n8n: bool = True
    author: str = Field(default="Archon OS", max_length=120)
    description: str = Field(default="", max_length=2000)


@router.get("/domains")
def list_squad_pack_domains():
    """Listet alle exportierbaren Fachabteilungen (Domänen) auf."""
    return {"status": "success", "domains": squad_pack_manager.list_available_domains()}


@router.post("/export")
def export_squad_pack(request: Request, payload: SquadPackExportRequest):
    """Exportiert eine Fachabteilung / Agenten-Auswahl als .archonpack ZIP-Download."""
    require_admin_or_503(request)
    name = str(payload.name or "archon-squad").strip()
    domain = payload.domain
    agent_ids: Optional[List[str]] = payload.agent_ids
    include_prompts = bool(payload.include_prompts)
    include_n8n = bool(payload.include_n8n)
    author = str(payload.author or "Archon OS")
    description = str(payload.description or "")

    zip_bytes, manifest = squad_pack_manager.export_pack(
        name=name,
        domain=domain,
        agent_ids=agent_ids,
        include_prompts=include_prompts,
        include_n8n=include_n8n,
        author=author,
        description=description,
    )
    safe_slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name).strip("_") or "squad"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_slug}.archonpack"',
            "X-ArchonPack-Agents": str(manifest["stats"]["agents"]),
        },
    )


@router.post("/inspect")
async def inspect_squad_pack(file: UploadFile = File(...)):
    """Prüft ein hochgeladenes .archonpack Archiv (Dry-Run ohne Schreibzugriff)."""
    raw = await file.read()
    ok, result = squad_pack_manager.inspect_pack(raw)
    if not ok:
        raise HTTPException(status_code=400, detail=result.get("error", "Ungültiges .archonpack"))
    return result


@router.post("/import")
async def import_squad_pack(
    request: Request,
    file: UploadFile = File(...),
    conflict_mode: str = Form("skip"),
):
    """Importiert ein geprüftes .archonpack Archiv in den Workspace."""
    require_admin_or_503(request)
    if conflict_mode not in ("skip", "overwrite"):
        raise HTTPException(status_code=400, detail="conflict_mode muss 'skip' oder 'overwrite' sein.")
    raw = await file.read()
    ok, result = squad_pack_manager.import_pack(raw, conflict_mode=conflict_mode)
    if not ok:
        raise HTTPException(status_code=400, detail=result.get("error", "Import fehlgeschlagen"))
    return result

"""
archon/routers/squad_packs.py
=============================
M51 — REST-Endpunkte für den .archonpack Squad-Blueprint-Paketmanager.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.squad_pack_manager import squad_pack_manager

router = APIRouter(
    prefix="/api/v1/squad-packs",
    tags=["Squad Blueprints (M51)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.get("/domains")
def list_squad_pack_domains():
    """Listet alle exportierbaren Fachabteilungen (Domänen) auf."""
    return {"status": "success", "domains": squad_pack_manager.list_available_domains()}


@router.post("/export")
def export_squad_pack(request: Request, payload: Dict[str, Any] = Body(...)):
    """Exportiert eine Fachabteilung / Agenten-Auswahl als .archonpack ZIP-Download."""
    require_admin_or_503(request)
    name = str(payload.get("name") or "archon-squad").strip()
    domain = payload.get("domain")
    agent_ids: Optional[List[str]] = payload.get("agent_ids")
    include_prompts = bool(payload.get("include_prompts", True))
    include_n8n = bool(payload.get("include_n8n", True))
    author = str(payload.get("author") or "Archon OS")
    description = str(payload.get("description") or "")

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

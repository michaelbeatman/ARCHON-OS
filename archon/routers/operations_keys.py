from fastapi import Depends as _ArchonDepends

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

"""Sub-Router fuer API-Keys & Scopes Access Management (t-6fad7a).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import get_session_actor, require_admin_or_503, require_session_actor


class ApiKeyCreateRequest(BaseModel):
    """Validierter Payload für die API-Key-Erzeugung (Etappe 1)."""
    # extra="ignore" bewusst: bestehende Clients senden 'created_by', das
    # serverseitig aus der Session kommt (kein Body-Vertrauensmoment).
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=120)
    scopes: List[str] = Field(default_factory=lambda: ["read_only"])
    rate_limit_rpm: int = Field(default=60, ge=0, le=100_000)
    rate_limit_rpd: int = Field(default=5000, ge=0, le=10_000_000)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


@router.get("/keys")
def api_list_keys(request: Request):
    """Gibt alle registrierten API-Keys ohne Klardaten zurück."""
    require_admin_or_503(request)  # RBAC: Key-Verzeichnis ist sensibel (Audit v3 Befund 2.2)
    try:
        from backend.api_key_manager import api_key_manager
        keys = api_key_manager.list_keys()
        return {"status": "success", "keys": keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys")
def api_create_key(request: Request, req: ApiKeyCreateRequest):
    """Erstellt einen neuen API-Key und gibt den Klartext-Token einmalig zurück."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    name = req.name.strip()
    scopes = req.scopes
    rate_limit_rpm = req.rate_limit_rpm
    rate_limit_rpd = req.rate_limit_rpd
    created_by = require_session_actor(request)

    if not name:
        raise HTTPException(status_code=400, detail="Name/Zweck des API-Keys ist erforderlich.")

    try:
        from backend.api_key_manager import AuditWriteFailedError, api_key_manager
        res = api_key_manager.create_key(
            name=name,
            scopes=scopes,
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_rpd=rate_limit_rpd,
            created_by=created_by,
        )
        return {"status": "success", "result": res}
    except AuditWriteFailedError as exc:
        # A2: AuditWriteFailedError erbt von RuntimeError, nicht von
        # HTTPException. Ohne explizites Mapping wuerde die nachfolgende
        # blanket-except die neue 503 in eine 500 umwandeln und den
        # Audit-Ausfall als generischen Fehler tarnen.
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys/{key_id}/revoke")
def api_revoke_key(request: Request, key_id: str):
    """Deaktiviert einen API-Key dauerhaft und revisionssicher."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    revoked_by = require_session_actor(request)
    try:
        from backend.api_key_manager import api_key_manager
        success = api_key_manager.revoke_key(key_id, revoked_by=revoked_by)
        if not success:
            raise HTTPException(status_code=404, detail="Key nicht gefunden oder bereits inaktiv.")
        return {"status": "success", "message": "API-Key erfolgreich widerrufen."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/keys/{key_id}")
def api_delete_key(request: Request, key_id: str):
    """Löscht einen Key vollständig aus der aktiven Liste."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    deleted_by = require_session_actor(request)
    try:
        from backend.api_key_manager import api_key_manager
        success = api_key_manager.delete_key(key_id, deleted_by=deleted_by)
        if not success:
            raise HTTPException(status_code=404, detail="Key nicht gefunden.")
        return {"status": "success", "message": "API-Key gelöscht."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/keys/audit")
def api_get_keys_audit(request: Request, limit: int = 50):
    """Liefert das revisionssichere SHA-256 Audit-Log der Key-Verwaltung."""
    require_admin_or_503(request)  # audit_trail enthaelt key_id/scopes/created_by — Admin only
    try:
        from backend.api_key_manager import api_key_manager
        trail = api_key_manager.get_audit_trail(limit=limit)
        return {"status": "success", "audit_log": trail}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

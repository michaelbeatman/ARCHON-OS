"""Sub-Router fuer API-Keys & Scopes Access Management (t-6fad7a).

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException, Request

from archon.routers._rbac import require_admin_or_503

router = APIRouter()


@router.get("/keys")
def api_list_keys():
    """Gibt alle registrierten API-Keys ohne Klardaten zurück."""
    try:
        from backend.api_key_manager import api_key_manager
        keys = api_key_manager.list_keys()
        return {"status": "success", "keys": keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys")
def api_create_key(request: Request, req: Dict[str, Any] = Body(...)):
    """Erstellt einen neuen API-Key und gibt den Klartext-Token einmalig zurück."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    name = req.get("name", "").strip()
    scopes = req.get("scopes", ["read_only"])
    rate_limit_rpm = int(req.get("rate_limit_rpm", 60))
    rate_limit_rpd = int(req.get("rate_limit_rpd", 5000))
    created_by = req.get("created_by", "admin").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name/Zweck des API-Keys ist erforderlich.")

    try:
        from backend.api_key_manager import api_key_manager
        res = api_key_manager.create_key(
            name=name,
            scopes=scopes,
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_rpd=rate_limit_rpd,
            created_by=created_by,
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys/{key_id}/revoke")
def api_revoke_key(request: Request, key_id: str, req: Dict[str, Any] = Body(default={})):
    """Deaktiviert einen API-Key dauerhaft und revisionssicher."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    revoked_by = req.get("revoked_by", "admin").strip()
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
def api_delete_key(request: Request, key_id: str, req: Dict[str, Any] = Body(default={})):
    """Löscht einen Key vollständig aus der aktiven Liste."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    deleted_by = req.get("deleted_by", "admin").strip()
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
def api_get_keys_audit(limit: int = 50):
    """Liefert das revisionssichere SHA-256 Audit-Log der Key-Verwaltung."""
    try:
        from backend.api_key_manager import api_key_manager
        trail = api_key_manager.get_audit_trail(limit=limit)
        return {"status": "success", "audit_log": trail}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

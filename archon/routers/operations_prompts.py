"""Sub-Router fuer Prompt-Registry, Canary-Testing, Rollback und Versionierung.

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, HTTPException, Query, Request
from archon.routers._rbac import require_admin_or_503

router = APIRouter()


# =========================================================================
# PROMPT REGISTRY, VERSIONING, CANARY & ROLLBACK
# =========================================================================

@router.get("/prompts/{agent_id}/versions")
def api_list_prompt_versions(agent_id: str):
    """Listet alle Versionen des System-Prompts für den angegebenen Agenten auf."""
    try:
        from backend.prompt_registry import prompt_registry
        versions = prompt_registry.list_versions(agent_id)
        return {"status": "success", "agent_id": agent_id, "versions": versions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/versions")
def api_save_prompt_version(request: Request, agent_id: str, req: Dict[str, Any] = Body(...)):
    """Speichert eine neue Version des System-Prompts für einen Agenten."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        prompt_text = req.get("prompt")
        if not prompt_text:
            raise HTTPException(status_code=400, detail="Feld 'prompt' ist erforderlich.")
        res = prompt_registry.save_version(
            agent_id=agent_id,
            prompt=prompt_text,
            commit_message=req.get("commit_message", ""),
            created_by=req.get("created_by", "manual_api"),
            model=req.get("model"),
            make_active=req.get("make_active", True),
            canary_percentage=req.get("canary_percentage", 0)
        )
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/{agent_id}/diff")
def api_diff_prompt_versions(agent_id: str, v1: int = Query(...), v2: int = Query(...)):
    """Gibt ein Unified Diff zwischen zwei Prompt-Versionen zurück."""
    try:
        from backend.prompt_registry import prompt_registry
        diff_text = prompt_registry.diff_versions(agent_id, v1, v2)
        return {"status": "success", "agent_id": agent_id, "v1": v1, "v2": v2, "diff": diff_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/rollback")
def api_rollback_prompt_version(request: Request, agent_id: str, req: Dict[str, Any] = Body(...)):
    """Führt einen 1-Click Rollback auf eine frühere Prompt-Version durch."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        target_v = req.get("target_version")
        if not target_v:
            raise HTTPException(status_code=400, detail="Feld 'target_version' erforderlich.")
        reason = req.get("reason", "Manuelles Rollback über UI/API")
        res = prompt_registry.rollback_to_version(agent_id, int(target_v), reason=reason)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/canary")
def api_set_prompt_canary(request: Request, agent_id: str, req: Dict[str, Any] = Body(...)):
    """Konfiguriert eine Prompt-Version als Canary mit Prozentsatz (1-99%)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        version = req.get("version")
        pct = req.get("percentage")
        if version is None or pct is None:
            raise HTTPException(status_code=400, detail="Felder 'version' und 'percentage' erforderlich.")
        res = prompt_registry.set_canary(agent_id, int(version), int(pct))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/promote")
def api_promote_prompt_canary(request: Request, agent_id: str, req: Dict[str, Any] = Body(...)):
    """Befördert eine Canary-Version zur vollwertigen stabilen Version (100% Traffic)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        version = req.get("version")
        if version is None:
            raise HTTPException(status_code=400, detail="Feld 'version' erforderlich.")
        res = prompt_registry.promote_canary(agent_id, int(version))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

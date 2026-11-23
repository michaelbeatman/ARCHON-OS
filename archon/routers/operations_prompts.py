from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Prompt-Registry, Canary-Testing, Rollback und Versionierung.

Ausgelagert aus backend/operations_api.py.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from archon.routers._rbac import require_admin_or_503


class PromptVersionSaveRequest(BaseModel):
    """Validierter Payload für POST /prompts/{agent_id}/versions (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    prompt: str = Field(default="", max_length=200_000)
    commit_message: str = Field(default="", max_length=1_000)
    created_by: str = Field(default="manual_api", max_length=128)
    model: Optional[str] = Field(default=None, max_length=128)
    make_active: bool = True
    canary_percentage: int = Field(default=0, ge=0, le=100)


class PromptRollbackRequest(BaseModel):
    """Validierter Payload für POST /prompts/{agent_id}/rollback (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    target_version: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(default="Manuelles Rollback über UI/API", max_length=1_000)


class PromptCanaryRequest(BaseModel):
    """Validierter Payload für POST /prompts/{agent_id}/canary (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    version: Optional[int] = Field(default=None, ge=1)
    percentage: Optional[int] = Field(default=None, ge=0, le=100)


class PromptPromoteRequest(BaseModel):
    """Validierter Payload für POST /prompts/{agent_id}/promote (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    version: Optional[int] = Field(default=None, ge=1)


router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


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
def api_save_prompt_version(request: Request, agent_id: str, req: PromptVersionSaveRequest):
    """Speichert eine neue Version des System-Prompts für einen Agenten."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        prompt_text = req.prompt
        if not prompt_text:
            raise HTTPException(status_code=400, detail="Feld 'prompt' ist erforderlich.")
        res = prompt_registry.save_version(
            agent_id=agent_id,
            prompt=prompt_text,
            commit_message=req.commit_message,
            created_by=req.created_by,
            model=req.model,
            make_active=req.make_active,
            canary_percentage=req.canary_percentage,
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
def api_rollback_prompt_version(request: Request, agent_id: str, req: PromptRollbackRequest):
    """Führt einen 1-Click Rollback auf eine frühere Prompt-Version durch."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        target_v = req.target_version
        if not target_v:
            raise HTTPException(status_code=400, detail="Feld 'target_version' erforderlich.")
        reason = req.reason
        res = prompt_registry.rollback_to_version(agent_id, int(target_v), reason=reason)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/canary")
def api_set_prompt_canary(request: Request, agent_id: str, req: PromptCanaryRequest):
    """Konfiguriert eine Prompt-Version als Canary mit Prozentsatz (1-99%)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        version = req.version
        pct = req.percentage
        if version is None or pct is None:
            raise HTTPException(status_code=400, detail="Felder 'version' und 'percentage' erforderlich.")
        res = prompt_registry.set_canary(agent_id, int(version), int(pct))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/promote")
def api_promote_prompt_canary(request: Request, agent_id: str, req: PromptPromoteRequest):
    """Befördert eine Canary-Version zur vollwertigen stabilen Version (100% Traffic)."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.prompt_registry import prompt_registry
        version = req.version
        if version is None:
            raise HTTPException(status_code=400, detail="Feld 'version' erforderlich.")
        res = prompt_registry.promote_canary(agent_id, int(version))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

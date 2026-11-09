"""Sub-Router fuer Dual-LLM Guard, Break-Glass Notfallzugang und Agent-Scorecards.

Ausgelagert aus backend/operations_api.py.
"""

import os
from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException, Request, Response

from archon.routers._rbac import require_admin_or_503

router = APIRouter()


# =========================================================================
# AGENT SCORECARDS & PERSONALAKTE INTEGRATION (t-f257ba)
# =========================================================================

@router.get("/agents/{agent_id}/scorecard")
def api_get_agent_scorecard(agent_id: str):
    """Liefert aggregierte Leistungsmetriken, KPIs und Projektdaten für die Personalakte."""
    try:
        from backend.agent_scorecard_engine import agent_scorecard_engine
        data = agent_scorecard_engine.get_scorecard(agent_id)
        return {"status": "success", "scorecard": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_id}/operator-notes")
def api_save_agent_operator_notes(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Speichert Operator-Beurteilungen persistent und synchronisiert sie mit Obsidian."""
    notes = req.get("notes", "").strip()
    try:
        from backend.agent_scorecard_engine import agent_scorecard_engine
        agent_scorecard_engine.save_operator_notes(agent_id, notes)
        return {"status": "success", "message": "Operator-Beurteilung gespeichert und mit Obsidian synchronisiert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# DUAL-LLM GUARD & PROMPT INJECTION SANITIZER (t-d3f2d2)
# =========================================================================

@router.post("/security/sanitize")
def api_sanitize_input(req: Dict[str, Any] = Body(...)):
    """Stufe 1 Quarantäne: Untersucht externe Inputs auf Prompt Injections."""
    text = req.get("text", "")
    source_id = req.get("source_id", "unknown")
    source_type = req.get("source_type", "external")
    try:
        from backend.dual_llm_sanitizer import sanitize_external_input
        result = sanitize_external_input(raw_text=text, source_id=source_id, source_type=source_type)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/trusted-sources")
def api_get_trusted_sources():
    """Gibt die Whitelist vertrauenswürdiger Absender [T] zurück."""
    try:
        from backend.dual_llm_sanitizer import load_trusted_sources
        sources = load_trusted_sources()
        return {"status": "success", "trusted_sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security/trusted-sources/toggle")
def api_toggle_trusted_source(request: Request, req: Dict[str, Any] = Body(...)):
    """Schaltet den Trusted-Status [T] für einen Absender um."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    source_id = req.get("source_id", "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="Keine source_id angegeben.")
    try:
        from backend.dual_llm_sanitizer import toggle_trusted_source
        res = toggle_trusted_source(source_id)
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# NOTFALLZUGANG / BREAK-GLASS PROTOCOL (t-8efcf3)
# =========================================================================

@router.get("/security/break-glass/status")
def api_get_break_glass_status():
    """Liefert den Integritäts- und Initialisierungsstatus des Break-Glass Vaults."""
    try:
        from scripts.break_glass_recovery import get_vault_status
        return {"status": "success", "vault": get_vault_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security/break-glass/create")
def api_create_break_glass_vault(request: Request):
    """Generiert ein neues verschlüsseltes Notfall-Backup und einen einmaligen Recovery-Key."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from scripts.break_glass_recovery import create_break_glass_vault
        res = create_break_glass_vault(operator="admin")
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/break-glass/kit")
def api_download_break_glass_kit():
    """Liefert das druckbare Notfall-Dokument (BREAK_GLASS_RECOVERY_KIT.md) als Download."""
    try:
        from scripts.break_glass_recovery import KIT_DOC_FILE
        if not os.path.exists(KIT_DOC_FILE):
            raise HTTPException(status_code=404, detail="Recovery-Kit noch nicht generiert.")
        with open(KIT_DOC_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="ARCHON_BREAK_GLASS_RECOVERY_KIT.md"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

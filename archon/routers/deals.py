"""Deals Pipeline & Forecast Router.

Bietet Deal-Tracking, Forecast-Berechnungen und Stage-Management
fuer das CRM- und Vertriebs-Subsystem.
"""

from typing import Optional
from fastapi import APIRouter, Body, HTTPException

router = APIRouter(tags=["deals"])


@router.get("/api/deals")
@router.get("/api/v1/deals")
def api_list_deals(stage: Optional[str] = None, partner: Optional[str] = None, assigned_agent: Optional[str] = None):
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "deals": DealPipelineManager.list_deals(stage=stage, partner=partner, assigned_agent=assigned_agent)}


@router.get("/api/deals/forecast")
@router.get("/api/v1/deals/forecast")
def api_deal_forecast():
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "forecast": DealPipelineManager.get_forecast()}


@router.get("/api/deals/{deal_id}")
@router.get("/api/v1/deals/{deal_id}")
def api_get_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deal = DealPipelineManager.get(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal nicht gefunden.")
    return {"status": "success", "deal": deal}


@router.post("/api/deals")
@router.post("/api/v1/deals")
def api_save_deal(payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    saved = DealPipelineManager.create_or_update(payload)
    return {"status": "success", "deal": saved}


@router.post("/api/deals/{deal_id}/move-stage")
@router.post("/api/v1/deals/{deal_id}/move-stage")
def api_move_deal_stage(deal_id: str, payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    new_stage = payload.get("stage", "")
    notes = payload.get("notes")
    if not new_stage:
        raise HTTPException(status_code=400, detail="'stage' erforderlich.")
    moved = DealPipelineManager.move_stage(deal_id, new_stage, notes=notes)
    if not moved:
        raise HTTPException(status_code=404, detail="Deal oder Phase ungültig.")
    return {"status": "success", "deal": moved}


@router.delete("/api/deals/{deal_id}")
@router.delete("/api/v1/deals/{deal_id}")
def api_delete_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deleted = DealPipelineManager.delete(deal_id)
    return {"status": "success" if deleted else "not_found", "deleted": deleted}

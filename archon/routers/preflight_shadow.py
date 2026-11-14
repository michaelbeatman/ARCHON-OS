"""
archon/routers/preflight_shadow.py
==================================
M52 — Pre-Flight Cost-Estimator & Shadow-Mode Endpunkte.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.shadow_mode import estimate_chain_cost, shadow_mode_manager

router = APIRouter(
    tags=["Pre-Flight & Shadow-Mode (M52)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.post("/api/v1/preflight/estimate")
def preflight_estimate_chain(payload: Dict[str, Any] = Body(...)):
    steps = payload.get("steps") or []
    model_name = str(payload.get("model_name") or "deepseek/deepseek-chat")
    budget_usd = float(payload.get("budget_usd", 0.50))
    return {
        "status": "success",
        "estimate": estimate_chain_cost(steps=steps, model_name=model_name, budget_usd=budget_usd),
    }


@router.post("/api/v1/shadow-mode/record")
def record_shadow_prediction(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    agent_id = str(payload.get("agent_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    decision = str(payload.get("shadow_decision") or "").strip()
    if not agent_id or not task_id:
        raise HTTPException(status_code=400, detail="agent_id und task_id sind erforderlich.")
    entry = shadow_mode_manager.record_shadow_run(agent_id, task_id, decision)
    return {"status": "success", "shadow_run": entry}


@router.post("/api/v1/shadow-mode/{shadow_id}/evaluate")
def evaluate_shadow_prediction(request: Request, shadow_id: str, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    human_decision = str(payload.get("human_decision") or "")
    match_score = float(payload.get("match_score", 0.0))
    try:
        updated = shadow_mode_manager.evaluate_shadow_run(shadow_id, human_decision, match_score)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "shadow_run": updated}


@router.get("/api/v1/shadow-mode/agents/{agent_id}")
def get_agent_shadow_stats(agent_id: str):
    return {"status": "success", **shadow_mode_manager.get_agent_stats(agent_id)}

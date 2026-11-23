"""
archon/routers/preflight_shadow.py
==================================
M52 — Pre-Flight Cost-Estimator & Shadow-Mode Endpunkte.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import forbid_viewer_writes, require_admin_or_503
from backend.shadow_mode import estimate_chain_cost, shadow_mode_manager


class CostEstimateStep(BaseModel):
    """Ein Schritt der Kosten-Kette für den Pre-Flight Estimator (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=300)
    prompt: str = Field(default="", max_length=200_000)
    prompt_template: str = Field(default="", max_length=200_000)
    model: str = Field(default="", max_length=128)
    expected_output_tokens: int = Field(default=1_000, ge=1, le=1_000_000)


class PreflightEstimateRequest(BaseModel):
    """Validierter Payload für POST /api/v1/preflight/estimate (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    steps: List[CostEstimateStep] = Field(default_factory=list, max_length=500)
    model_name: str = Field(default="deepseek/deepseek-chat", max_length=128)
    budget_usd: float = Field(default=0.50, ge=0.0, le=1_000_000.0)


class ShadowRecordRequest(BaseModel):
    """Validierter Payload für POST /api/v1/shadow-mode/record (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    agent_id: str = Field(default="", max_length=128)
    task_id: str = Field(default="", max_length=128)
    shadow_decision: str = Field(default="", max_length=20_000)


class ShadowEvaluateRequest(BaseModel):
    """Validierter Payload für POST /api/v1/shadow-mode/{id}/evaluate (Etappe 7)."""
    model_config = ConfigDict(extra="ignore")
    human_decision: str = Field(default="", max_length=20_000)
    match_score: float = Field(default=0.0, ge=0.0, le=1.0)


router = APIRouter(
    tags=["Pre-Flight & Shadow-Mode (M52)"],
    dependencies=[Depends(forbid_viewer_writes)],
)


@router.post("/api/v1/preflight/estimate")
def preflight_estimate_chain(payload: PreflightEstimateRequest):
    steps = [step.model_dump(exclude_none=True) for step in payload.steps]
    model_name = payload.model_name
    budget_usd = payload.budget_usd
    return {
        "status": "success",
        "estimate": estimate_chain_cost(steps=steps, model_name=model_name, budget_usd=budget_usd),
    }


@router.post("/api/v1/shadow-mode/record")
def record_shadow_prediction(request: Request, payload: ShadowRecordRequest):
    require_admin_or_503(request)
    agent_id = payload.agent_id.strip()
    task_id = payload.task_id.strip()
    decision = payload.shadow_decision.strip()
    if not agent_id or not task_id:
        raise HTTPException(status_code=400, detail="agent_id und task_id sind erforderlich.")
    entry = shadow_mode_manager.record_shadow_run(agent_id, task_id, decision)
    return {"status": "success", "shadow_run": entry}


@router.post("/api/v1/shadow-mode/{shadow_id}/evaluate")
def evaluate_shadow_prediction(request: Request, shadow_id: str, payload: ShadowEvaluateRequest):
    require_admin_or_503(request)
    human_decision = payload.human_decision
    match_score = payload.match_score
    try:
        updated = shadow_mode_manager.evaluate_shadow_run(shadow_id, human_decision, match_score)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "shadow_run": updated}


@router.get("/api/v1/shadow-mode/agents/{agent_id}")
def get_agent_shadow_stats(agent_id: str):
    return {"status": "success", **shadow_mode_manager.get_agent_stats(agent_id)}

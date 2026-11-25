from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503
"""Router /api/routergate — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class _RouterGateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ModelBenchmarkRequest(_RouterGateRequest):
    prompt: str = "Erstelle eine strukturierte Zusammenfassung der DSGVO-Kernpflichten."
    model_a: str = "deepseek/deepseek-chat"
    model_b: str = "anthropic/claude-3-5-sonnet"
    role: str = "Senior Analyst"


class EstimateCostRequest(_RouterGateRequest):
    prompt: str = ""
    model: str = "deepseek/deepseek-chat"
    expected_output_tokens: int = Field(default=1000, ge=0)
    task_budget_usd: float = Field(default=0.25, ge=0)


class HedgedCompletionRequest(_RouterGateRequest):
    prompt: str = "Test-Anfrage"
    primary_model: str = "openai/gpt-4o"
    fallback_model: Optional[str] = None
    hedge_delay_seconds: Optional[float] = None
    simulate_primary_latency_sec: Optional[float] = None
    simulate_fallback_latency_sec: float = 0.05
    # Nur explizit angeforderte Demo-Laeufe erzeugen synthetische Antworten.
    demo: bool = False


class BanditOutcomeRequest(_RouterGateRequest):
    model_id: str = "deepseek/deepseek-chat"
    success: bool = True
    latency_ms: float = Field(default=500.0, ge=0)


@router.post("/api/router/benchmark")
async def api_run_model_benchmark(payload: ModelBenchmarkRequest = Body(...)):
    payload = payload.model_dump()
    from backend.model_benchmarker import run_model_benchmark
    return await run_model_benchmark(
        prompt=payload.get("prompt", "Erstelle eine strukturierte Zusammenfassung der DSGVO-Kernpflichten."),
        model_a=payload.get("model_a", "deepseek/deepseek-chat"),
        model_b=payload.get("model_b", "anthropic/claude-3-5-sonnet"),
        role=payload.get("role", "Senior Analyst")
    )


@router.post("/api/router/estimate-cost")
def api_estimate_cost(request: Request, payload: EstimateCostRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    payload = payload.model_dump()
    from backend.cost_estimator import estimate_prompt_cost
    return estimate_prompt_cost(
        prompt=payload.get("prompt", ""),
        model_name=payload.get("model", "deepseek/deepseek-chat"),
        expected_output_tokens=int(payload.get("expected_output_tokens", 1000)),
        task_budget_usd=float(payload.get("task_budget_usd", 0.25))
    )


@router.get("/api/router/benchmark/history")
def api_get_benchmark_history(limit: int = 25):
    from backend.model_benchmarker import get_benchmark_history
    return {"status": "success", "benchmarks": get_benchmark_history(limit=limit)}


@router.post("/api/router/hedged-completion")
async def api_hedged_completion(payload: HedgedCompletionRequest = Body(...)):
    """Produktivpfad fuer Latenz-Hedging (H-01-2/F042).

    Primär- und Fallback-Call sind echte Dispatcher-Coroutines; der Gewinner
    wird gegen deren echte Antworten verifiziert. ``demo: true`` erzeugt
    ausschliesslich einen explizit gekennzeichneten Simulationslauf.
    """
    payload = payload.model_dump()
    from backend.speculative_hedger import make_dispatcher_coro, speculative_hedger

    prompt = str(payload.get("prompt") or "Test-Anfrage")
    primary_model = str(payload.get("primary_model") or "openai/gpt-4o")
    try:
        from backend.autonomy_settings import get_module_config
        _hedge_cfg = get_module_config("speculative_hedger")
    except Exception:
        _hedge_cfg = {}
    fallback_model = str(
        payload.get("fallback_model") or _hedge_cfg.get("fallback_model") or "deepseek/deepseek-chat"
    )
    demo = bool(payload.get("demo", False))
    primary_coro_fn = None if demo else make_dispatcher_coro(prompt, primary_model)
    fallback_coro_fn = None if demo else make_dispatcher_coro(prompt, fallback_model)

    result = await speculative_hedger.execute_hedged_call(
        prompt=prompt,
        primary_model=primary_model,
        fallback_model_override=fallback_model,
        hedge_delay_override=payload.get("hedge_delay_seconds"),
        simulate_primary_latency_sec=payload.get("simulate_primary_latency_sec"),
        simulate_fallback_latency_sec=float(payload.get("simulate_fallback_latency_sec", 0.05)),
        primary_coro_fn=primary_coro_fn,
        fallback_coro_fn=fallback_coro_fn,
    )
    # demo_only stammt jetzt aus der echten Verdrahtung (Coroutines vorhanden
    # oder nicht) und wird nicht mehr vom Endpoint ueberschrieben.
    result["demo_only"] = bool(demo or result.get("demo_only", False))
    return result


@router.get("/api/router/hedged-stats")
def api_hedged_stats(request: Request):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.speculative_hedger import speculative_hedger
    return speculative_hedger.get_stats()


@router.post("/api/router/bandit-outcome")
def api_bandit_record_outcome(payload: BanditOutcomeRequest = Body(...)):
    payload = payload.model_dump()
    from backend.bandit_model_router import bandit_model_router
    return bandit_model_router.record_outcome(
        model_id=payload.get("model_id", "deepseek/deepseek-chat"),
        success=bool(payload.get("success", True)),
        latency_ms=float(payload.get("latency_ms", 500.0))
    )


@router.get("/api/router/bandit-select")
def api_bandit_select_best():
    from backend.bandit_model_router import bandit_model_router
    return bandit_model_router.select_best_model()

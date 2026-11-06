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
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

router = APIRouter()

@router.post("/api/router/benchmark")
async def api_run_model_benchmark(payload: Dict = Body(...)):
    from backend.model_benchmarker import run_model_benchmark
    return await run_model_benchmark(
        prompt=payload.get("prompt", "Erstelle eine strukturierte Zusammenfassung der DSGVO-Kernpflichten."),
        model_a=payload.get("model_a", "deepseek/deepseek-chat"),
        model_b=payload.get("model_b", "anthropic/claude-3-5-sonnet"),
        role=payload.get("role", "Senior Analyst")
    )


@router.post("/api/router/estimate-cost")
def api_estimate_cost(payload: Dict = Body(...)):
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
async def api_hedged_completion(payload: Dict = Body(...)):
    from backend.speculative_hedger import speculative_hedger
    return await speculative_hedger.execute_hedged_call(
        prompt=payload.get("prompt", "Test-Anfrage"),
        primary_model=payload.get("primary_model", "openai/gpt-4o"),
        fallback_model_override=payload.get("fallback_model"),
        hedge_delay_override=payload.get("hedge_delay_seconds"),
        simulate_primary_latency_sec=payload.get("simulate_primary_latency_sec"),
        simulate_fallback_latency_sec=float(payload.get("simulate_fallback_latency_sec", 0.05))
    )


@router.get("/api/router/hedged-stats")
def api_hedged_stats():
    from backend.speculative_hedger import speculative_hedger
    return speculative_hedger.get_stats()


@router.post("/api/router/bandit-outcome")
def api_bandit_record_outcome(payload: Dict = Body(...)):
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

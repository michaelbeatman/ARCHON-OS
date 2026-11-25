"""Router fuer Autonomie-Module, Model-Routing, Semantic-Cache & Evolution."""
from __future__ import annotations

import logging
import os
from typing import Dict

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi import Depends as _ArchonDepends

from archon.routers._rbac import (
    forbid_viewer_writes as _forbid_viewer_writes,
)
from archon.routers._rbac import (
    require_admin_or_503,
)
from archon.routers._validated_body import PassthroughBody, as_payload

logger = logging.getLogger("archon.routers.autonomy_settings")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["autonomy_settings"])


def guardian_limits_path() -> str:
    """Kompatibilitaets-Helfer (F1a): SSOT liegt jetzt in archon.core.paths."""
    from archon.core.paths import GUARDIAN_LIMITS_FILE
    return GUARDIAN_LIMITS_FILE


GUARDIAN_LIMITS_FILE = guardian_limits_path()


def save_circuit_breaker_limits(limits: Dict) -> Dict:
    """D13/MED: Guardian-Toggles in die SSOT schreiben, die der CB liest.

    `agent_router._get_guardian_policy()` liest `get_module_config(
    "circuit_breaker")` aus settings.json — nicht guardian_limits.json.
    """
    from backend.autonomy_settings import save_autonomy_settings

    cb = {
        key: limits[key]
        for key in ("loop_detection_enabled", "max_steps_per_task", "max_identical_turns")
        if key in limits
    }
    if not cb:
        return {}
    return save_autonomy_settings({"circuit_breaker": cb})


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


# --- MODEL ROUTING ---


@router.get("/api/settings/model-routing")
def api_get_model_routing():
    from backend.model_routing import load_config

    return {"status": "success", "config": load_config()}


@router.post("/api/settings/model-routing")
def api_save_model_routing(request: Request, payload: PassthroughBody = Body(...)):
    _require_admin(request)
    data = as_payload(payload)
    from backend.model_routing import save_config

    try:
        cfg = save_config(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "config": cfg}


@router.get("/api/settings/model-routing/resolve")
def api_resolve_model_routing(task: str = Query("")):
    from backend.model_routing import is_enabled, resolve

    return {"status": "success", "enabled": is_enabled(), "route": resolve(task)}


# --- AUTONOMY MODULES & HERMES SYNC ---


@router.get("/api/settings/autonomy-modules")
def api_get_autonomy_modules_settings():
    from backend.autonomy_settings import load_all_settings

    return {"status": "success", "settings": load_all_settings()}


@router.post("/api/settings/autonomy-modules")
def api_save_autonomy_modules_settings(request: Request, payload: PassthroughBody = Body(...)):
    _require_admin(request)
    data = as_payload(payload)
    import main as app_main
    from backend.autonomy_settings import save_autonomy_settings

    updated = save_autonomy_settings(data)
    try:
        import yaml

        fn = getattr(app_main, "_get_hermes_config_paths", None)
        active_path = None
        if fn:
            active_path, _ = fn()
        if active_path and os.path.exists(active_path):
            with open(active_path, "r", encoding="utf-8") as f:
                hdata = yaml.safe_load(f.read()) or {}
            if not isinstance(hdata, dict):
                hdata = {}
            conc = data.get("concurrency", {})
            if isinstance(conc, dict):
                if "max_concurrent_agents" in conc:
                    hdata.setdefault("delegation", {})["max_concurrent_children"] = int(
                        conc["max_concurrent_agents"]
                    )
                if "queue_timeout_seconds" in conc:
                    hdata.setdefault("agent", {})["task_timeout_seconds"] = int(
                        conc["queue_timeout_seconds"]
                    )
            cb = data.get("circuit_breaker", {})
            if isinstance(cb, dict):
                tlg = hdata.setdefault("tool_loop_guardrails", {})
                if "loop_detection_enabled" in cb:
                    tlg["warnings_enabled"] = bool(cb["loop_detection_enabled"])
                if "max_identical_turns" in cb:
                    tlg.setdefault("hard_stop_after", {})["exact_failure"] = int(cb["max_identical_turns"])
                if "max_steps_per_task" in cb:
                    hdata.setdefault("agent", {})["max_turns"] = int(cb["max_steps_per_task"])
            sb = data.get("ephemeral_sandbox", {})
            if isinstance(sb, dict):
                term = hdata.setdefault("terminal", {})
                if "cpu_limit" in sb:
                    term["container_cpu"] = float(sb["cpu_limit"])
                if "timeout_seconds" in sb:
                    term["timeout"] = int(sb["timeout_seconds"])
            cc = data.get("context_compactor", {})
            if isinstance(cc, dict):
                comp = hdata.setdefault("compression", {})
                if "enabled" in cc:
                    comp["enabled"] = bool(cc["enabled"])
                if "keep_recent_turns" in cc:
                    comp["protect_last_n"] = int(cc["keep_recent_turns"])
            cg = data.get("consensus_gate", {})
            if isinstance(cg, dict) and "enabled" in cg:
                hdata.setdefault("moa", {})["enabled"] = bool(cg["enabled"])
            with open(active_path, "w", encoding="utf-8") as f:
                yaml.dump(hdata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e_sync:
        logger.warning(f"[Archon -> Hermes Sync] {e_sync}")
    return {"status": "success", "settings": updated}


# --- SEMANTIC CACHE ---


@router.post("/api/cache/semantic-lookup")
def api_semantic_cache_lookup(payload: PassthroughBody = Body(...)):
    data = as_payload(payload)
    from backend.semantic_cache import semantic_cache_manager

    return semantic_cache_manager.lookup(
        prompt=data.get("prompt", ""),
        model=data.get("model", "any"),
        threshold_override=data.get("similarity_threshold"),
    )


@router.post("/api/cache/semantic-store")
def api_semantic_cache_store(payload: PassthroughBody = Body(...)):
    data = as_payload(payload)
    from backend.semantic_cache import semantic_cache_manager

    return semantic_cache_manager.store(
        prompt=data.get("prompt", ""),
        response=data.get("response", ""),
        model=data.get("model", "any"),
    )


@router.get("/api/cache/semantic-stats")
def api_semantic_cache_stats():
    from backend.semantic_cache import semantic_cache_manager

    return semantic_cache_manager.get_stats()


@router.delete("/api/cache/semantic-clear")
def api_semantic_cache_clear(request: Request):
    _require_admin(request)
    from backend.semantic_cache import semantic_cache_manager

    return semantic_cache_manager.clear()


# --- EVOLUTION & REGRESSION SUITE ---


@router.post("/api/evolution/optimize-prompt")
def api_optimize_role_prompt(request: Request, payload: PassthroughBody = Body(...)):
    _require_admin(request)
    data = as_payload(payload)
    from backend.prompt_optimizer import prompt_optimizer

    return prompt_optimizer.optimize_role_prompt(
        agent_role=data.get("agent_role", "backend_architect"),
        current_prompt=data.get("current_prompt", "Du bist ein präziser System-Agent."),
        recent_failures=data.get("recent_failures", []),
    )


@router.post("/api/evolution/eval-suite/run")
def api_run_eval_regression_suite(
    request: Request,
    payload: PassthroughBody = Body(default={}),
    simulation: bool = Query(False),
):
    # Audit D01/D12: dieser Endpoint konnte clientseitige simulated_outputs als
    # echten Kandidatenlauf ausgeben und release_approved=true schreiben.
    require_admin_or_503(request)  # Admin-Gate (auch fuer Simulationspfad)
    data = as_payload(payload)
    simulated_outputs = data.get("simulated_outputs")
    if simulated_outputs is not None and not simulation:
        raise HTTPException(
            status_code=400,
            detail={"code": "simulation_opt_in_required", "message": "simulated_outputs erfordert ?simulation=true"},
        )
    from backend.eval_regression_runner import eval_regression_runner

    return eval_regression_runner.run_suite(
        candidate_label=data.get("candidate_label", "v2026.10-release"),
        simulated_outputs=simulated_outputs,
    )

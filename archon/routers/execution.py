from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503
"""Router /api/execution — ausgelagerte Routen.

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


class _ExecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _as_payload(value) -> Dict[str, Any]:
    """Tolerant: interne/direkte Aufrufer uebergeben weiterhin Dicts."""
    return value.model_dump(by_alias=True) if hasattr(value, "model_dump") else dict(value)


class MapReduceRequest(_ExecRequest):
    task_title: str = "Map-Reduce Batch"
    items: List[Any] = []
    instruction: str = "Analysiere und extrahiere Kernergebnisse"
    max_parallel_workers: Optional[int] = None


class StructuredOutputRequest(_ExecRequest):
    raw_output: str = ""
    json_schema: Optional[Any] = Field(default=None, alias="schema")


class DurableCheckpointRequest(_ExecRequest):
    workflow_id: str = "wf-default"
    task_title: str = "Workflow"
    current_step_index: int = 1
    total_steps: int = 5
    state: Dict[str, Any] = {}
    completed_steps: List[Any] = []
    status: str = "in_progress"


class IdempotencyCheckRequest(_ExecRequest):
    tool_name: str = "send_email"
    params: Dict[str, Any] = {}
    idempotency_key: Optional[str] = None
    execution_result: Optional[Any] = None


class DryRunRequest(_ExecRequest):
    task_title: str = "Shadow Simulation"
    proposed_actions: List[Any] = []


class DlqEnqueueRequest(_ExecRequest):
    job_type: str = "webhook_delivery"
    source_module: str = "router"
    payload: Dict[str, Any] = {}
    error_message: str = "Unbekannter Fehler"


class DlqReplayRequest(_ExecRequest):
    dlq_id: str = ""
    simulate_success: bool = False


class QueueEnqueueRequest(_ExecRequest):
    job_type: str = "generic"
    source_module: str = "router"
    payload: Dict[str, Any] = {}
    priority: int = 0
    idempotency_key: str = ""
    max_retries: Optional[int] = None


class QueueClaimRequest(_ExecRequest):
    worker_id: str = "api-worker"
    lease_seconds: int = 120
    job_types: Optional[List[str]] = None


class QueueCompleteRequest(_ExecRequest):
    result: Dict[str, Any] = {}


class QueueFailRequest(_ExecRequest):
    error_message: str = "Worker-Fehler"

@router.post("/api/execution/map-reduce")
async def api_execute_map_reduce(request: Request, payload: MapReduceRequest = Body(...)):
    """Demo-Endpoint (D01/D12): es wird kein echter `worker_fn` injiziert.

    Deshalb ist jedes Ergebnis dieses Endpoints explizit als Simulation
    gekennzeichnet. Produktivaufrufer muessen `execute_map_reduce(worker_fn=...)`
    direkt mit einer echten Worker-Funktion nutzen.
    """
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.map_reduce_executor import map_reduce_executor
    result = await map_reduce_executor.execute_map_reduce(
        task_title=payload.get("task_title", "Map-Reduce Batch"),
        items=payload.get("items", []),
        instruction=payload.get("instruction", "Analysiere und extrahiere Kernergebnisse"),
        max_workers_override=payload.get("max_parallel_workers")
    )
    result["simulated"] = True
    result["mode"] = "demo_only"
    result["demo_only"] = True
    result["status"] = "simulation"
    return result


@router.get("/api/execution/map-reduce/history")
def api_map_reduce_history(limit: int = 20):
    from backend.map_reduce_executor import map_reduce_executor
    return {"status": "success", "jobs": map_reduce_executor.get_history(limit=limit)}


@router.post("/api/execution/structured-output")
def api_structured_output_validate(payload: StructuredOutputRequest = Body(...)):
    payload = _as_payload(payload)
    if not payload.get("schema"):
        raise HTTPException(status_code=400, detail={"code": "schema_required"})
    from backend.structured_output_enforcer import structured_output_enforcer
    return structured_output_enforcer.validate_and_enforce(
        raw_output=payload.get("raw_output", ""),
        schema=payload.get("schema")
    )


@router.post("/api/execution/checkpoints/save")
def api_save_durable_checkpoint(payload: DurableCheckpointRequest = Body(...)):
    payload = _as_payload(payload)
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return durable_checkpoint_manager.save_checkpoint(
        workflow_id=payload.get("workflow_id", "wf-default"),
        task_title=payload.get("task_title", "Workflow"),
        current_step_index=int(payload.get("current_step_index", 1)),
        total_steps=int(payload.get("total_steps", 5)),
        state_payload=payload.get("state", {}),
        completed_steps=payload.get("completed_steps", []),
        status=payload.get("status", "in_progress")
    )


@router.get("/api/execution/checkpoints/resume/{workflow_id}")
def api_resume_durable_checkpoint(workflow_id: str):
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return durable_checkpoint_manager.resume_checkpoint(workflow_id=workflow_id)


@router.get("/api/execution/checkpoints/list")
def api_list_durable_checkpoints(status: Optional[str] = None):
    from backend.durable_checkpoint_manager import durable_checkpoint_manager
    return {"status": "success", "checkpoints": durable_checkpoint_manager.list_checkpoints(status_filter=status)}


@router.post("/api/execution/idempotency/check")
def api_idempotency_check(payload: IdempotencyCheckRequest = Body(...)):
    payload = _as_payload(payload)
    from backend.idempotency_guard import idempotency_guard
    return idempotency_guard.check_or_register(
        tool_name=payload.get("tool_name", "send_email"),
        params=payload.get("params", {}),
        explicit_key=payload.get("idempotency_key"),
        execution_result=payload.get("execution_result")
    )


@router.post("/api/execution/dry-run")
def api_dry_run_simulate(payload: DryRunRequest = Body(...)):
    payload = _as_payload(payload)
    from backend.dry_run_simulator import dry_run_simulator
    return dry_run_simulator.simulate_task_plan(
        task_title=payload.get("task_title", "Shadow Simulation"),
        proposed_actions=payload.get("proposed_actions", [])
    )


@router.post("/api/execution/dlq/enqueue")
def api_dlq_enqueue(request: Request, payload: DlqEnqueueRequest = Body(...)):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.enqueue_failed_job(
        job_type=payload.get("job_type", "webhook_delivery"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {}),
        error_message=payload.get("error_message", "Unbekannter Fehler")
    )


@router.post("/api/execution/dlq/replay")
def api_dlq_replay(request: Request, payload: DlqReplayRequest = Body(...)):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.replay_job(
        dlq_id=payload.get("dlq_id", ""),
        # Default: echter Replay. Simulation nur explizit und gekennzeichnet
        # (Audit 23.11.2026) — sonst werden Jobs als erfolgreich markiert,
        # ohne dass jemals ein Zustelldurchlauf stattfand.
        simulate_success=bool(payload.get("simulate_success", False))
    )


@router.get("/api/execution/dlq/list")
def api_dlq_list(status: Optional[str] = None):
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.list_dlq(status_filter=status)


# ---------------------------------------------------------------------------
# Shared Task Queue (attempt / idempotency_key / priority / CAS-Lease)
# ---------------------------------------------------------------------------

@router.post("/api/execution/queue/enqueue")
def api_queue_enqueue(request: Request, payload: QueueEnqueueRequest = Body(...)):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.enqueue_task(
        job_type=payload.get("job_type", "generic"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {}),
        priority=int(payload.get("priority", 0)),
        idempotency_key=str(payload.get("idempotency_key", "") or ""),
        max_retries=payload.get("max_retries"),
    )


@router.post("/api/execution/queue/claim")
def api_queue_claim(request: Request, payload: QueueClaimRequest = Body(default=QueueClaimRequest())):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    item = dead_letter_queue_manager.claim_next(
        worker_id=str(payload.get("worker_id") or "api-worker"),
        lease_seconds=int(payload.get("lease_seconds", 120)),
        job_types=payload.get("job_types") or None,
    )
    return {"claimed": item is not None, "item": item}


@router.post("/api/execution/queue/{dlq_id}/complete")
def api_queue_complete(request: Request, dlq_id: str, payload: QueueCompleteRequest = Body(default=QueueCompleteRequest())):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    return {"completed": dead_letter_queue_manager.complete(dlq_id, payload.get("result") or {})}


@router.post("/api/execution/queue/{dlq_id}/fail")
def api_queue_fail(request: Request, dlq_id: str, payload: QueueFailRequest = Body(default=QueueFailRequest())):
    require_admin_or_503(request)
    payload = _as_payload(payload)
    from backend.dead_letter_queue import dead_letter_queue_manager
    return dead_letter_queue_manager.fail(
        dlq_id, str(payload.get("error_message") or "Worker-Fehler")
    )


class _ReplanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    new_dag_def: Dict[str, Any] = Field(default_factory=dict)
    trajectory_id: str = ""


@router.post("/api/execution/dag/replan")
def api_request_dag_replan(request: Request, body: _ReplanRequest):
    """D13: Produktivaufrufer für `request_dag_replan()` — Cap pro Trajectory."""
    require_admin_or_503(request)
    from backend.workflow_dag_runner import request_dag_replan
    res = request_dag_replan(
        run_id=body.run_id,
        new_dag_def=body.new_dag_def or {},
        reason=body.reason,
        trajectory_id=body.trajectory_id or None,
    )
    if not res.get("allowed", False):
        raise HTTPException(status_code=409, detail=res)
    return res

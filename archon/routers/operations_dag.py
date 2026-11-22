from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer DAG-Scheduler, Workflow-Checkpoints und OTEL-Tracing.

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


# =========================================================================
# DAG-SCHEDULER & WORKFLOW CHECKPOINTS
# =========================================================================

class DecomposeTaskRequest(BaseModel):
    title: str
    body: Optional[str] = ""
    assignee: Optional[str] = "orchestrator"


@router.post("/kanban/dag/decompose")
async def api_dag_decompose_task(req: DecomposeTaskRequest):
    """ALTER 2-Tier-DAG-Scheduler entfernt (21.11.2026) — Nachfolger: Workflow-Studio + /api/v2/workflows/templates/{id}/run."""
    raise HTTPException(
        status_code=410,
        detail="Der alte dag_scheduler wurde durch die Workflow-/DAG-Engine ersetzt: Templates unter /api/v2/workflows/templates anlegen und via /api/v2/workflows/templates/{id}/run ausfuehren.",
    )


@router.post("/kanban/dag/execute/{parent_id}")
async def api_dag_execute_task(parent_id: str):
    """ALTER 2-Tier-DAG-Scheduler entfernt (21.11.2026) — Nachfolger: /api/v2/workflows/dag/run bzw. Template-Run."""
    raise HTTPException(
        status_code=410,
        detail="Der alte dag_scheduler wurde durch die Workflow-/DAG-Engine ersetzt: /api/v2/workflows/dag/run (DAG-JSON) oder Template-Run verwenden.",
    )


class WorkflowCheckpointCreateRequest(BaseModel):
    checkpoint_id: str
    workflow_id: str
    agent_id: str
    current_step: int
    total_steps: int
    state_data: Dict[str, Any]
    status: Optional[str] = "running"
    pause_reason: Optional[str] = None


@router.post("/workflows/checkpoints")
def api_create_workflow_checkpoint(req: WorkflowCheckpointCreateRequest):
    """Speichert einen atomaren Workflow-Snapshot für unterbrechbare Langzeitprozesse."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    bridge.save_workflow_checkpoint(
        req.checkpoint_id, req.workflow_id, req.agent_id,
        req.current_step, req.total_steps, req.state_data,
        req.status or "running", req.pause_reason
    )
    return {"status": "success", "checkpoint_id": req.checkpoint_id}


@router.get("/workflows/checkpoints")
def api_list_workflow_checkpoints(status: Optional[str] = None):
    """Liefert aktive oder pausierte Workflow-Snapshots."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    return {"status": "success", "checkpoints": bridge.list_workflow_checkpoints(status=status)}


@router.post("/workflows/checkpoints/{checkpoint_id}/resume")
def api_resume_workflow_checkpoint(checkpoint_id: str):
    """Reaktiviert einen pausierten Workflow-Snapshot für die Weiterführung ab Schritt N."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    cp = bridge.get_workflow_checkpoint(checkpoint_id)
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint nicht gefunden.")
    bridge.save_workflow_checkpoint(
        checkpoint_id, cp["workflow_id"], cp["agent_id"],
        cp["current_step"], cp["total_steps"], cp.get("state", {}),
        status="resumed", pause_reason=None
    )
    return {"status": "success", "message": f"Workflow {cp['workflow_id']} ab Schritt {cp['current_step']} reaktiviert.", "checkpoint": cp}


@router.post("/workflows/runs/{run_id}/resume-suspended")
async def api_resume_suspended_workflow_run(run_id: str, request: Request):
    """P2: SUSPENDED → RUNNING ueber persistierte Checkpoints + Node-States.

    Der alte ``/checkpoints/{id}/resume`` setzte nur ein Flag — kein Consumer
    fuehrte den Workflow fort. Dieser Endpoint startet den echten Executor;
    bereits abgeschlossene Nodes werden ueber den Fingerprint-Cache
    (``workflow_node_states``) uebernommen, nicht erneut ausgefuehrt.
    """
    require_admin_or_503(request)
    from backend.workflow_dag_runner import resume_suspended_workflow_run
    from backend.durable_execution_kernel import (
        InvalidTransitionError, StaleFencingTokenError,
    )

    try:
        return await resume_suspended_workflow_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (InvalidTransitionError, StaleFencingTokenError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# =========================================================================
# OPENTELEMETRY & TRACING
# =========================================================================

@router.get("/traces/otel")
def api_list_otel_traces(limit: int = Query(25, ge=1, le=100)):
    """OpenTelemetry & Langfuse Tracing: Liefert jüngste Traces mit Token-, Latenz- und Kosten-Metriken."""
    try:
        from backend.otel_tracer import tracer
        traces = tracer.list_recent_traces(limit=limit)
        return {"status": "success", "total": len(traces), "traces": traces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/otel/{trace_or_task_id}")
def api_get_otel_trace_tree(trace_or_task_id: str):
    """OpenTelemetry & Langfuse Tracing: Liefert den vollständigen hierarchischen Trace- und Span-Baum."""
    try:
        from backend.otel_tracer import tracer
        tree = tracer.get_trace_tree(trace_or_task_id)
        if not tree:
            raise HTTPException(status_code=404, detail="Trace nicht gefunden.")
        return {"status": "success", "trace": tree}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

"""Sub-Router fuer DAG-Scheduler, Workflow-Checkpoints und OTEL-Tracing.

Ausgelagert aus backend/operations_api.py.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


# =========================================================================
# DAG-SCHEDULER & WORKFLOW CHECKPOINTS
# =========================================================================

class DecomposeTaskRequest(BaseModel):
    title: str
    body: Optional[str] = ""
    assignee: Optional[str] = "orchestrator"


@router.post("/kanban/dag/decompose")
async def api_dag_decompose_task(req: DecomposeTaskRequest):
    """Zerlegt eine komplexe Aufgabe in einen Directed Acyclic Graph (DAG) mit parallelen Teilaufgaben."""
    from backend.dag_scheduler import dag_scheduler_instance
    return await dag_scheduler_instance.decompose_task(req.title, req.body or "", req.assignee or "orchestrator")


@router.post("/kanban/dag/execute/{parent_id}")
async def api_dag_execute_task(parent_id: str):
    """Führt einen zerlegten DAG aus: Parallele Vorstufen -> abhängige Stufen -> Abschluss-Synthese."""
    from backend.dag_scheduler import dag_scheduler_instance
    return await dag_scheduler_instance.execute_dag(parent_id)


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

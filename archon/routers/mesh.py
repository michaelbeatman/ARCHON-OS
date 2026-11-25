"""Router fuer Event-Mesh, Concurrency, Vision, RAG, Handoff, Consensus & War-Room."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import datetime
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from fastapi import APIRouter, Body, HTTPException, Query, Request

logger = logging.getLogger("archon.routers.mesh")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["mesh"])

# D06/MED: explizite Allowlists fuer alle per HTTP setzbaren Config-Felder.
# Alles andere (insbesondere Steuerungs-/Laufzeitfelder) wird verworfen.
_CONCURRENCY_CONFIG_KEYS = ("max_concurrent_agents", "queue_timeout_seconds")
_CONSOLIDATION_CONFIG_KEYS = (
    "enabled",
    "schedule_time",
    "retention_days",
    "archive_threshold_similarity",
    "auto_prune_temporary_logs",
)


class _MeshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MeshDiffPreviewRequest(_MeshRequest):
    file_path: str = ""
    new_content: str = ""
    context_lines: int = 3


class InboundEventRequest(_MeshRequest):
    """W4-B: strikte Allowlist statt ``extra="allow"``.

    ``idempotency_key``/``correlation_id`` duerfen nicht vom Sender kommen
    (extra="ignore" verwirft sie); der Handler leitet beide serverseitig aus
    (Mandant, Kanal, Event-Typ, kanonischer Body-Hash) ab.
    """

    model_config = ConfigDict(extra="ignore")

    event_type: str = Field(default="generic_event", max_length=128)
    title: str = Field(default="", max_length=500)
    summary: str = Field(default="", max_length=4000)
    content: str = Field(default="", max_length=20000)
    priority: int = Field(default=3, ge=0, le=10)
    # W3/W4: Trace-Kontext darf ueber die Grenze propagiert werden, ist aber
    # formatbegrenzt und wird von event_mesh validiert (parse_traceparent).
    trace_id: str = Field(default="", max_length=64)
    span_id: str = Field(default="", max_length=32)
    traceparent: str = Field(default="", max_length=128)
    tracestate: str = Field(default="", max_length=512)


class InboxScanRequest(_MeshRequest):
    inbox_dir: Optional[str] = None


class ConcurrencyConfigRequest(_MeshRequest):
    # D06/MED: extra="allow" + cfg.update() liess den Body beliebige
    # Steuerungsfelder in die persistierte Config schreiben. Nur explizit
    # typisierte Felder duerfen den Wert ueberschreiben (siehe _CONCURRENCY_CONFIG_KEYS).
    max_concurrent_agents: Optional[int] = Field(default=None, ge=1, le=128)
    queue_timeout_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    # Legacy-Felder alter Clients (test_p0_api_validation_memory_mesh): sie
    # bleiben im Modell, werden aber vom Handler NICHT in die Config uebernommen.
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=128)
    custom_option: Optional[str] = Field(default=None, max_length=200)


class VisionAnalyzeRequest(_MeshRequest):
    image_path: str = ""
    focus_prompt: str = "Beschreibe den Inhalt dieses Screenshots detailliert."


class HandoffCreateRequest(_MeshRequest):
    task_id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    deliverables: Dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: str = ""


class HandoffAcceptRequest(_MeshRequest):
    receiving_agent: str = ""


class TaskConsensusReviewRequest(_MeshRequest):
    task_id: str = "task-gen"
    title: str = ""
    output: str = ""
    worker_agent: str = "hermes-coder"
    priority: int = 3


class TaskBudgetCheckRequest(_MeshRequest):
    cost_usd: float = 0.0
    budget_usd: float = 0.25
    title: str = ""


class CouncilVoteRequest(_MeshRequest):
    task_id: str = "council-task"
    title: str = ""
    output: str = ""
    model: Optional[str] = None


class SandboxExecuteRequest(_MeshRequest):
    code: str = ""
    language: str = "python"
    memory_limit_mb: Optional[int] = None
    cpu_limit: Optional[float] = None
    timeout_seconds: Optional[int] = None
    network_enabled: Optional[bool] = None


class MemoryConsolidationConfigRequest(_MeshRequest):
    # D06/MED: nur fachliche Einstellungen, keine Laufzeit-/Steuerungsfelder
    # (last_run, last_pruned_records_count) aus dem Body.
    enabled: Optional[bool] = None
    schedule_time: Optional[str] = Field(default=None, max_length=32)
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    archive_threshold_similarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_prune_temporary_logs: Optional[bool] = None


class BrowseCaptureRequest(_MeshRequest):
    task_id: Optional[str] = None
    url: str = "https://example.com"
    actions: Optional[Any] = None
    extract_selector: Optional[str] = None


class WarRoomRequest(_MeshRequest):
    topic: str = "System-Update"
    proposal: str = ""
    model: Optional[str] = None
    task_id: Optional[str] = None


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


def _require_admin_or_503(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


# --- RAG BRIDGE & DIFF PREVIEW ---


@router.get("/api/rag/query")
def api_query_rag(q: str = Query(..., description="Suchbegriff für das AnythingLLM Docker-RAG")):
    from backend.rag_bridge import rag_bridge

    return rag_bridge.query_vault_rag(q)


@router.post("/api/diff/preview")
def api_diff_preview(request: Request, payload: MeshDiffPreviewRequest = Body(...)):
    _require_admin_or_503(request)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.diff_engine import compute_file_diff
    from utils.path_jail import PathJailError, safe_path_within

    raw_path = str(data.get("file_path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Gültiger 'file_path' erforderlich.")

    import main as app_main

    repo_root = (
        os.path.dirname(os.path.abspath(app_main.__file__))
        if hasattr(app_main, "__file__")
        else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    try:
        real_path = safe_path_within(
            raw_path,
            [repo_root],
            must_exist=True,
            allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail={"code": "mesh_path_not_allowed", "params": {"error": str(e)}})

    return compute_file_diff(
        file_path=real_path,
        new_content=data.get("new_content", ""),
        context_lines=int(data.get("context_lines", 3)),
    )


# --- SKILL PROPOSALS ---


@router.get("/api/skills/proposals")
def api_list_skill_proposals(status: Optional[str] = None):
    from backend.skill_synthesizer import skill_synthesizer

    # list_proposals() behandelt leeren Status als "alle" (`if status:`).
    # None -> "" ist daher verhaltensidentisch und erfuellt den str-Parameter.
    return {"status": "success", "proposals": skill_synthesizer.list_proposals(status=status or "")}


@router.post("/api/skills/proposals/{proposal_id}/approve")
def api_approve_skill_proposal(request: Request, proposal_id: str):
    _require_admin(request)
    from backend.skill_synthesizer import skill_synthesizer

    return skill_synthesizer.approve_skill(proposal_id)


# --- EVENT MESH ---


def _verify_inbound_signature(raw_body: bytes, supplied: str) -> bool:
    """HMAC-SHA256 ueber die exakten Body-Bytes (fail-closed).

    Secret ausschliesslich aus der Umwelt; kein Default, kein Platzhalter.
    """
    secret = (os.environ.get("ARCHON_WEBHOOK_HMAC_SECRET") or "").strip()
    sig = str(supplied or "").strip()
    if not secret or not sig:
        return False
    if sig.lower().startswith("sha256="):
        sig = sig[7:]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


@router.post("/api/events/inbound/{channel}")
async def api_ingest_inbound_event(request: Request, channel: str):
    """Inbound-Webhook mit Signaturpruefung und serverseitigen Dedup-Keys."""
    _require_admin_or_503(request)
    raw_body = await request.body()
    if not _verify_inbound_signature(raw_body, request.headers.get("x-archon-webhook-signature", "")):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "WEBHOOK_SIGNATURE_INVALID",
                "message": "X-Archon-Webhook-Signature fehlt oder ungueltig (HMAC-SHA256).",
            },
        )
    try:
        inbound = InboundEventRequest.model_validate_json(raw_body or b"{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PAYLOAD", "message": str(exc)[:300]}) from exc

    from backend.event_mesh import event_mesh
    from backend.event_mesh import _current_tenant_id as mesh_tenant_id

    payload = inbound.model_dump()
    tenant_id = mesh_tenant_id()
    event_type = str(payload.get("event_type") or "generic_event")
    body_hash = hashlib.sha256(raw_body or b"").hexdigest()
    key_material = json.dumps(
        [tenant_id, str(channel), event_type, body_hash],
        ensure_ascii=False, separators=(",", ":"),
    )
    idempotency_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    correlation_id = f"inbound-{idempotency_key}"
    trace_columns = {
        k: str(payload.get(k) or request.headers.get(k, "") or "")
        for k in ("trace_id", "span_id", "traceparent", "tracestate")
    }
    return event_mesh.ingest_inbound_event(
        channel=str(channel),
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        trace_columns=trace_columns,
    )


@router.get("/api/events/history")
def api_list_event_history(limit: int = 50):
    from backend.event_mesh import event_mesh

    return {"status": "success", "events": event_mesh.list_events(limit=limit)}


@router.post("/api/events/scan-directory")
def api_scan_inbox_directory(request: Request, payload: InboxScanRequest = Body(default=InboxScanRequest())):
    _require_admin(request)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.event_mesh import event_mesh

    return event_mesh.scan_inbox_directory(inbox_dir=data.get("inbox_dir"))


# --- CONCURRENCY THROTTLE ---


@router.get("/api/concurrency/status")
def api_get_concurrency_status():
    from backend.concurrency_throttle import concurrency_throttle

    return {"status": "success", "concurrency": concurrency_throttle.get_status()}


@router.post("/api/concurrency/config")
def api_save_concurrency_config(request: Request, payload: ConcurrencyConfigRequest = Body(...)):
    _require_admin(request)
    data = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else dict(payload)
    from backend.concurrency_throttle import get_concurrency_config, save_concurrency_config

    cfg = get_concurrency_config()
    for key in _CONCURRENCY_CONFIG_KEYS:
        if key in data:
            cfg[key] = data[key]
    ok = save_concurrency_config(cfg)
    return {"status": "success" if ok else "error", "concurrency": cfg}


# --- VISION PIPELINE ---


@router.post("/api/vision/analyze")
def api_analyze_vision(payload: VisionAnalyzeRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.vision_pipeline import analyze_image_file

    return analyze_image_file(
        image_path=data.get("image_path", ""),
        focus_prompt=data.get("focus_prompt", "Beschreibe den Inhalt dieses Screenshots detailliert."),
    )


# --- HANDOFF DESK ---


@router.post("/api/handoff/create")
def api_create_handoff(payload: HandoffCreateRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.handoff_desk import handoff_desk

    return handoff_desk.create_handoff(
        task_id=data.get("task_id", ""),
        from_agent=data.get("from_agent", ""),
        to_agent=data.get("to_agent", ""),
        deliverables=data.get("deliverables", {}),
        acceptance_criteria=data.get("acceptance_criteria", ""),
    )


@router.post("/api/handoff/{handoff_id}/accept")
def api_accept_handoff(request: Request, handoff_id: str, payload: HandoffAcceptRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from archon.routers._rbac import require_session_actor
    from backend.handoff_desk import handoff_desk

    # D11/MED: der Empfänger war self-attestierend (Body == Envelope-Feld).
    # Identität jetzt aus dem echten Executor (Kanban-assignee) ableiten;
    # der Request-Actor muss zusätzlich verifiziert sein.
    require_session_actor(request)
    envelope = handoff_desk.get_handoff(handoff_id) or {}
    claimed = str(data.get("receiving_agent") or "").strip()
    assignee = ""
    try:
        from backend.operations_api import _get_kanban_connection
        conn = _get_kanban_connection()
        try:
            row = conn.execute(
                "SELECT assignee FROM tasks WHERE id = ?", (str(envelope.get("task_id") or ""),)
            ).fetchone()
            assignee = str(row[0] or "") if row else ""
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[Mesh] Handoff-Empfänger nicht aus Kanban-SSOT lesbar: %s", exc)
        raise HTTPException(status_code=503, detail="executor identity unavailable")
    if not assignee or claimed != assignee or str(envelope.get("to_agent") or "") != assignee:
        raise HTTPException(status_code=403, detail="receiving_agent is not the verified executor")
    return handoff_desk.accept_handoff(handoff_id=handoff_id, receiving_agent=assignee)


# --- TASK CONSENSUS & BUDGET ---


@router.post("/api/tasks/review-consensus")
async def api_review_task_consensus(payload: TaskConsensusReviewRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.consensus_gate import review_task_output

    task_id = data.get("task_id", "task-gen")
    task_title = data.get("title", "")
    task_output = data.get("output", "")
    worker = data.get("worker_agent", "hermes-coder")
    priority = int(data.get("priority", 3))
    return await review_task_output(
        task_id, task_title, task_output, worker_agent=worker, priority=priority
    )


@router.post("/api/tasks/{task_id}/budget/check")
def api_check_task_budget(task_id: str, payload: TaskBudgetCheckRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.agent_router import check_task_budget

    return check_task_budget(
        task_id=task_id,
        cost_usd=data.get("cost_usd", 0.0),
        budget_usd=data.get("budget_usd", 0.25),
        task_title=data.get("title", ""),
    )


@router.post("/api/consensus/council-vote")
async def api_run_council_vote(payload: CouncilVoteRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.consensus_gate import run_tri_agent_council

    return await run_tri_agent_council(
        task_id=data.get("task_id", "council-task"),
        task_title=data.get("title", ""),
        task_output=data.get("output", ""),
        model=data.get("model"),
    )


@router.get("/api/consensus/history")
def api_get_consensus_history(limit: int = 25):
    from backend.consensus_gate import get_consensus_history

    return {"status": "success", "consensus_history": get_consensus_history(limit=limit)}


# --- SANDBOX EXECUTE ---


@router.post("/api/sandbox/execute")
def api_execute_sandbox(request: Request, payload: SandboxExecuteRequest = Body(...)):
    _require_admin(request)
    # Der Handler prueft per `"key" in data` — None-Werte muessen daher
    # entfernt werden, sonst int(None)/float(None)/bool(None).
    data = payload.model_dump(exclude_none=True)
    from backend.ephemeral_sandbox import ephemeral_sandbox

    return ephemeral_sandbox.execute_in_sandbox(
        code=data.get("code", ""),
        language=data.get("language", "python"),
        memory_limit_mb=int(data["memory_limit_mb"]) if "memory_limit_mb" in data else None,
        cpu_limit=float(data["cpu_limit"]) if "cpu_limit" in data else None,
        timeout_seconds=int(data["timeout_seconds"]) if "timeout_seconds" in data else None,
        network_enabled=bool(data["network_enabled"]) if "network_enabled" in data else None,
    )


# --- MEMORY CONSOLIDATION SETTINGS ---


@router.get("/api/settings/memory-consolidation")
def api_get_memory_consolidation_settings():
    from backend.memory_consolidator import get_consolidation_config

    return {"status": "success", "config": get_consolidation_config()}


@router.post("/api/settings/memory-consolidation")
def api_save_memory_consolidation_settings(request: Request, payload: MemoryConsolidationConfigRequest = Body(...)):
    _require_admin(request)
    data = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else dict(payload)
    from backend.memory_consolidator import get_consolidation_config, save_consolidation_config

    cfg = get_consolidation_config()
    for key in _CONSOLIDATION_CONFIG_KEYS:
        if key in data:
            cfg[key] = data[key]
    ok = save_consolidation_config(cfg)
    return {"status": "success" if ok else "error", "config": cfg}


# --- VISUAL WEB AGENT ---


@router.post("/api/browser/browse-and-capture")
def api_browse_and_capture(request: Request, payload: BrowseCaptureRequest = Body(...)):
    _require_admin(request)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.visual_web_agent import visual_web_agent

    return visual_web_agent.browse_and_capture(
        task_id=data.get("task_id", f"vis-{datetime.datetime.now().strftime('%H%M%S')}"),
        target_url=data.get("url", "https://example.com"),
        actions=data.get("actions"),
        extract_selector=data.get("extract_selector"),
    )


# --- WAR ROOM SIMULATOR ---


@router.post("/api/simulation/war-room")
async def api_run_war_room(payload: WarRoomRequest = Body(...)):
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    from backend.war_room_simulator import run_war_room_simulation

    result = await run_war_room_simulation(
        topic=data.get("topic", "System-Update"),
        proposal_text=data.get("proposal", ""),
        model=data.get("model"),
        task_id=str(data.get("task_id") or "") or None,
    )
    # Bei blocked=True wurde echt blockiert (HITL-Decision + Task-Status),
    # nicht nur eine Empfehlung zurueckgegeben.
    if result.get("blocked") and not result.get("hitl_enforcement"):
        result["hitl_enforcement"] = {
            "decision_created": False,
            "task_blocked": False,
            "error": "HITL-Durchsetzung nicht verfuegbar",
        }
    return result


@router.get("/api/simulation/war-room/history")
def api_get_war_room_history(limit: int = 20):
    from backend.war_room_simulator import get_war_room_history

    return {"status": "success", "history": get_war_room_history(limit=limit)}

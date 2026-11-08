"""Router fuer Event-Mesh, Concurrency, Vision, RAG, Handoff, Consensus & War-Room."""
from __future__ import annotations

import datetime
import logging
import os
from typing import Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request

logger = logging.getLogger("archon.routers.mesh")

router = APIRouter(tags=["mesh"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def _require_admin_or_503(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin_or_503"):
        app_main.require_admin_or_503(request)


# --- RAG BRIDGE & DIFF PREVIEW ---


@router.get("/api/rag/query")
def api_query_rag(q: str = Query(..., description="Suchbegriff für das AnythingLLM Docker-RAG")):
    from backend.rag_bridge import rag_bridge

    return rag_bridge.query_vault_rag(q)


@router.post("/api/diff/preview")
def api_diff_preview(request: Request, payload: Dict = Body(...)):
    _require_admin_or_503(request)
    from backend.diff_engine import compute_file_diff
    from utils.path_jail import PathJailError, safe_path_within

    raw_path = str(payload.get("file_path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Gültiger 'file_path' erforderlich.")

    import main as app_main

    repo_root = getattr(app_main, "WORKSPACE_DIR", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        real_path = safe_path_within(
            raw_path,
            [repo_root],
            must_exist=True,
            allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=f"Pfad nicht erlaubt: {e}")

    return compute_file_diff(
        file_path=real_path,
        new_content=payload.get("new_content", ""),
        context_lines=int(payload.get("context_lines", 3)),
    )


# --- SKILL PROPOSALS ---


@router.get("/api/skills/proposals")
def api_list_skill_proposals(status: Optional[str] = None):
    from backend.skill_synthesizer import skill_synthesizer

    return {"status": "success", "proposals": skill_synthesizer.list_proposals(status=status)}


@router.post("/api/skills/proposals/{proposal_id}/approve")
def api_approve_skill_proposal(request: Request, proposal_id: str):
    _require_admin(request)
    from backend.skill_synthesizer import skill_synthesizer

    return skill_synthesizer.approve_skill(proposal_id)


# --- EVENT MESH ---


@router.post("/api/events/inbound/{channel}")
def api_ingest_inbound_event(channel: str, payload: Dict = Body(...)):
    from backend.event_mesh import event_mesh

    return event_mesh.ingest_inbound_event(
        channel=channel,
        event_type=payload.get("event_type", "generic_event"),
        payload=payload,
    )


@router.get("/api/events/history")
def api_list_event_history(limit: int = 50):
    from backend.event_mesh import event_mesh

    return {"status": "success", "events": event_mesh.list_events(limit=limit)}


@router.post("/api/events/scan-directory")
def api_scan_inbox_directory(payload: Dict = Body(default={})):
    from backend.event_mesh import event_mesh

    return event_mesh.scan_inbox_directory(inbox_dir=payload.get("inbox_dir"))


# --- CONCURRENCY THROTTLE ---


@router.get("/api/concurrency/status")
def api_get_concurrency_status():
    from backend.concurrency_throttle import concurrency_throttle

    return {"status": "success", "concurrency": concurrency_throttle.get_status()}


@router.post("/api/concurrency/config")
def api_save_concurrency_config(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.concurrency_throttle import get_concurrency_config, save_concurrency_config

    cfg = get_concurrency_config()
    cfg.update(payload)
    ok = save_concurrency_config(cfg)
    return {"status": "success" if ok else "error", "concurrency": cfg}


# --- VISION PIPELINE ---


@router.post("/api/vision/analyze")
def api_analyze_vision(payload: Dict = Body(...)):
    from backend.vision_pipeline import analyze_image_file

    return analyze_image_file(
        image_path=payload.get("image_path", ""),
        focus_prompt=payload.get("focus_prompt", "Beschreibe den Inhalt dieses Screenshots detailliert."),
    )


# --- HANDOFF DESK ---


@router.post("/api/handoff/create")
def api_create_handoff(payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk

    return handoff_desk.create_handoff(
        task_id=payload.get("task_id", ""),
        from_agent=payload.get("from_agent", ""),
        to_agent=payload.get("to_agent", ""),
        deliverables=payload.get("deliverables", {}),
        acceptance_criteria=payload.get("acceptance_criteria", ""),
    )


@router.post("/api/handoff/{handoff_id}/accept")
def api_accept_handoff(handoff_id: str, payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk

    return handoff_desk.accept_handoff(
        handoff_id=handoff_id, receiving_agent=payload.get("receiving_agent", "")
    )


# --- TASK CONSENSUS & BUDGET ---


@router.post("/api/tasks/review-consensus")
async def api_review_task_consensus(payload: Dict = Body(...)):
    from backend.consensus_gate import review_task_output

    task_id = payload.get("task_id", "task-gen")
    task_title = payload.get("title", "")
    task_output = payload.get("output", "")
    worker = payload.get("worker_agent", "hermes-coder")
    priority = int(payload.get("priority", 3))
    return await review_task_output(
        task_id, task_title, task_output, worker_agent=worker, priority=priority
    )


@router.post("/api/tasks/{task_id}/budget/check")
def api_check_task_budget(task_id: str, payload: Dict = Body(...)):
    from backend.agent_router import check_task_budget

    return check_task_budget(
        task_id=task_id,
        cost_usd=payload.get("cost_usd", 0.0),
        budget_usd=payload.get("budget_usd", 0.25),
        task_title=payload.get("title", ""),
    )


@router.post("/api/consensus/council-vote")
async def api_run_council_vote(payload: Dict = Body(...)):
    from backend.consensus_gate import run_tri_agent_council

    return await run_tri_agent_council(
        task_id=payload.get("task_id", "council-task"),
        task_title=payload.get("title", ""),
        task_output=payload.get("output", ""),
        model=payload.get("model"),
    )


@router.get("/api/consensus/history")
def api_get_consensus_history(limit: int = 25):
    from backend.consensus_gate import get_consensus_history

    return {"status": "success", "consensus_history": get_consensus_history(limit=limit)}


# --- SANDBOX EXECUTE ---


@router.post("/api/sandbox/execute")
def api_execute_sandbox(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.ephemeral_sandbox import ephemeral_sandbox

    return ephemeral_sandbox.execute_in_sandbox(
        code=payload.get("code", ""),
        language=payload.get("language", "python"),
        memory_limit_mb=int(payload["memory_limit_mb"]) if "memory_limit_mb" in payload else None,
        cpu_limit=float(payload["cpu_limit"]) if "cpu_limit" in payload else None,
        timeout_seconds=int(payload["timeout_seconds"]) if "timeout_seconds" in payload else None,
        network_enabled=bool(payload["network_enabled"]) if "network_enabled" in payload else None,
    )


# --- MEMORY CONSOLIDATION SETTINGS ---


@router.get("/api/settings/memory-consolidation")
def api_get_memory_consolidation_settings():
    from backend.memory_consolidator import get_consolidation_config

    return {"status": "success", "config": get_consolidation_config()}


@router.post("/api/settings/memory-consolidation")
def api_save_memory_consolidation_settings(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.memory_consolidator import get_consolidation_config, save_consolidation_config

    cfg = get_consolidation_config()
    cfg.update(payload)
    ok = save_consolidation_config(cfg)
    return {"status": "success" if ok else "error", "config": cfg}


# --- VISUAL WEB AGENT ---


@router.post("/api/browser/browse-and-capture")
def api_browse_and_capture(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    from backend.visual_web_agent import visual_web_agent

    return visual_web_agent.browse_and_capture(
        task_id=payload.get("task_id", f"vis-{datetime.datetime.now().strftime('%H%M%S')}"),
        target_url=payload.get("url", "https://example.com"),
        actions=payload.get("actions"),
        extract_selector=payload.get("extract_selector"),
    )


# --- WAR ROOM SIMULATOR ---


@router.post("/api/simulation/war-room")
async def api_run_war_room(payload: Dict = Body(...)):
    from backend.war_room_simulator import run_war_room_simulation

    return await run_war_room_simulation(
        topic=payload.get("topic", "System-Update"),
        proposal_text=payload.get("proposal", ""),
        model=payload.get("model"),
    )


@router.get("/api/simulation/war-room/history")
def api_get_war_room_history(limit: int = 20):
    from backend.war_room_simulator import get_war_room_history

    return {"status": "success", "history": get_war_room_history(limit=limit)}

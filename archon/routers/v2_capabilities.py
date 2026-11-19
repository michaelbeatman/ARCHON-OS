# -*- coding: utf-8 -*-
"""
archon/routers/v2_capabilities.py
=================================
Zentraler FastAPI-Router, der alle 26 neu entwickelten Archon-v2-Module
(Orchestrierung, Security, Memory, Research, Operations & Connectoren)
sauber ueber /api/v2/* mit RBAC (forbid_viewer_writes + require_admin_or_503) bereitstellt.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends as _ArchonDepends, HTTPException, Request
from fastapi.responses import HTMLResponse

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["archon_v2"])


# --- M84: Prompt-Injection-Feueruebung ---
@router.post("/api/v2/security/injection-drill")
def api_v2_injection_drill(request: Request):
    require_admin_or_503(request)
    from backend.injection_range import run_injection_drill
    return {"status": "success", **run_injection_drill()}


# --- M90: Signierte Tool-Warrants ---
@router.post("/api/v2/security/warrants/issue")
def api_v2_issue_warrant(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.tool_warrants import issue_warrant
    return {
        "status": "success",
        "warrant": issue_warrant(
            session_id=str(payload.get("session_id") or "default"),
            allowed_tools=list(payload.get("allowed_tools") or []),
            constraints=payload.get("constraints"),
            ttl_seconds=int(payload.get("ttl_seconds") or 900),
        ),
    }


@router.post("/api/v2/security/warrants/verify")
def api_v2_verify_warrant(payload: Dict[str, Any] = Body(...)):
    from backend.tool_warrants import verify_warrant_for_call
    return verify_warrant_for_call(
        warrant=payload.get("warrant") or {},
        session_id=str(payload.get("session_id") or ""),
        tool_name=str(payload.get("tool_name") or ""),
        args=payload.get("args"),
    )


# --- M79: Offline Encrypted Memory Vault ---
@router.post("/api/v2/memory/compartment/store")
def api_v2_compartment_store(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.offline_memory_vault import store_memory
    eid = store_memory(
        namespace=str(payload.get("namespace") or "default"),
        content=str(payload.get("content") or ""),
        tags=list(payload.get("tags") or []),
    )
    return {"status": "success", "id": eid}


@router.get("/api/v2/memory/compartment/recall")
def api_v2_compartment_recall(namespace: str = "default", query: str = "", top_k: int = 5):
    from backend.offline_memory_vault import recall_memory
    return {"status": "success", "results": recall_memory(namespace, query, top_k=max(1, min(20, top_k)))}


# --- M83: Flightlog & Policy Backtester ---
@router.get("/api/v2/observability/flightlog/{run_id}")
def api_v2_flightlog_check(run_id: str, final_status: str = "success"):
    from backend.flightlog_backtester import detect_silent_failures
    return {"status": "success", **detect_silent_failures(run_id, final_status=final_status)}


@router.post("/api/v2/observability/policy-backtest")
def api_v2_policy_backtest(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.flightlog_backtester import backtest_policy
    return {"status": "success", **backtest_policy(payload)}


# --- M77, M80, M92, M93: Workflows, SOPs, Freeze & Firewall ---
@router.post("/api/v2/workflows/dag/run")
async def api_v2_workflow_dag_run(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_dag_runner import run_workflow_dag

    async def _noop_exec(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "node": node.get("id"), "upstream_keys": sorted(upstream.keys())}

    res = await run_workflow_dag(
        dag_def=payload.get("dag") or {},
        executor_fn=_noop_exec,
        run_id=payload.get("run_id"),
        gate_approvals=payload.get("gate_approvals"),
    )
    return {"status": "success", **res}


@router.post("/api/v2/workflows/sop/run")
async def api_v2_hybrid_sop_run(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.hybrid_sop_runner import run_hybrid_sop

    async def _agent_stub(step: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "step": step.get("id")}

    res = await run_hybrid_sop(
        sop_def=payload.get("sop") or {},
        script_handlers={"noop": lambda s, c: {"ok": True}},
        agent_handler=_agent_stub,
        initial_context=payload.get("context"),
    )
    return {"status": "success", **res}


@router.post("/api/v2/workflows/freeze")
def api_v2_workflow_freeze(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_freeze import freeze_tool_sequence
    return freeze_tool_sequence(
        workflow_id=str(payload.get("workflow_id") or "wf_default"),
        recorded_calls=list(payload.get("calls") or []),
        description=str(payload.get("description") or ""),
    )


@router.post("/api/v2/tools/firewall/guard")
def api_v2_tool_output_guard(payload: Dict[str, Any] = Body(...)):
    from backend.tool_output_firewall import guard_tool_output
    return guard_tool_output(
        tool_name=str(payload.get("tool_name") or "tool"),
        raw_output=payload.get("output", ""),
        max_chars=int(payload.get("max_chars") or 8000),
    )


# --- M82 & M94: Session Receipts & Lossless Session DAG ---
@router.post("/api/v2/receipts/html", response_class=HTMLResponse)
def api_v2_render_receipt_html(payload: Dict[str, Any] = Body(...)):
    from backend.session_receipts import render_offline_html_receipt
    return render_offline_html_receipt(
        task_id=str(payload.get("task_id") or "t-0"),
        title=str(payload.get("title") or "Session Receipt"),
        original_ask=str(payload.get("original_ask") or ""),
        events=list(payload.get("events") or []),
    )


@router.get("/api/v2/sessions/{session_id}/lossless/search")
def api_v2_lossless_search(session_id: str, q: str = ""):
    from backend.lossless_session_dag import search_lossless_history
    return {"status": "success", "turns": search_lossless_history(session_id, q)}


# --- M45 & M50: Deep Research & Eval Arena ---
@router.post("/api/v2/research/triangulate")
def api_v2_research_triangulate(payload: Dict[str, Any] = Body(...)):
    from backend.deep_research_lab import compile_research_dossier
    return compile_research_dossier(
        topic=str(payload.get("topic") or "Research"),
        summary=str(payload.get("summary") or ""),
        sources=list(payload.get("sources") or []),
    )


@router.get("/api/v2/eval/gold-deck")
def api_v2_eval_gold_deck():
    from backend.agent_eval_arena import DEFAULT_GOLD_DECK
    return {"status": "success", "deck": DEFAULT_GOLD_DECK}


# --- M32, M33, M37, M38, M39, M40, M41, M42, M54, M55, M62, M85, M87, M88 ---
@router.get("/api/v2/operations/templates")
def api_v2_operations_templates(category: Optional[str] = None):
    from backend.operations_templates import list_operations_templates
    return {"status": "success", "templates": list_operations_templates(category)}


@router.post("/api/v2/calendar/grid")
def api_v2_calendar_grid(payload: Dict[str, Any] = Body(...)):
    from backend.enterprise_calendar import build_calendar_grid
    return build_calendar_grid(
        events=list(payload.get("events") or []),
        view=str(payload.get("view") or "week"),
        anchor_date=payload.get("anchor_date"),
    )


@router.post("/api/v2/calendar/sync")
def api_v2_calendar_sync(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.calendar_sync_blocker import sync_calendar_bidirectional
    return sync_calendar_bidirectional(
        local_events=list(payload.get("local_events") or []),
        remote_events=list(payload.get("remote_events") or []),
    )


@router.post("/api/v2/contracts/diff")
def api_v2_contract_diff(payload: Dict[str, Any] = Body(...)):
    from backend.contract_diff_redliner import diff_contract_clauses
    return diff_contract_clauses(str(payload.get("old_text") or ""), str(payload.get("new_text") or ""))


@router.post("/api/v2/contracts/deadlines/scan")
def api_v2_contract_deadlines(payload: Dict[str, Any] = Body(...)):
    from backend.contract_deadline_watcher import scan_upcoming_deadlines
    return {"status": "success", "alerts": scan_upcoming_deadlines(list(payload.get("contracts") or []))}


@router.post("/api/v2/portal/links")
def api_v2_create_portal_link(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.client_approval_portal import create_share_link
    return create_share_link(
        offer_id=str(payload.get("offer_id") or ""),
        title=str(payload.get("title") or "Angebot"),
        password=str(payload.get("password") or ""),
        ttl_hours=int(payload.get("ttl_hours") or 72),
    )


@router.post("/api/v2/time/start")
def api_v2_time_start(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.time_tracking_invoice import start_timer
    eid = start_timer(
        project_id=str(payload.get("project_id") or "default"),
        task_id=str(payload.get("task_id") or ""),
        description=str(payload.get("description") or ""),
        hourly_rate_eur=float(payload.get("hourly_rate_eur") or 120.0),
    )
    return {"status": "success", "entry_id": eid}


@router.post("/api/v2/time/{entry_id}/stop")
def api_v2_time_stop(request: Request, entry_id: str):
    require_admin_or_503(request)
    from backend.time_tracking_invoice import stop_timer
    res = stop_timer(entry_id)
    if not res:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return {"status": "success", "entry": res}


@router.post("/api/v2/watchdog/score")
def api_v2_watchdog_score(payload: Dict[str, Any] = Body(...)):
    from backend.watchdog_radar_v2 import score_signal_relevance
    return score_signal_relevance(
        str(payload.get("title") or ""),
        str(payload.get("body") or ""),
        list(payload.get("keywords") or []),
    )


@router.post("/api/v2/meetings/note")
def api_v2_meeting_note(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.meeting_copilot import build_crm_meeting_note
    try:
        return build_crm_meeting_note(
            str(payload.get("customer") or ""),
            list(payload.get("segments") or []),
            all_participants_consented=bool(payload.get("all_participants_consented", False)),
            consent_timestamp=str(payload.get("consent_timestamp") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/api/v2/gdpr/erase")
def api_v2_gdpr_erase(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.tenant_db_registry import gdpr_erase_subject_data
    try:
        return {
            "status": "success",
            **gdpr_erase_subject_data(
                subject_identifier=str(payload.get("subject") or ""),
                tenant_id=str(payload.get("tenant_id") or "default"),
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/voice/workflow/analyze")
def api_v2_voice_workflow_analyze(payload: Dict[str, Any] = Body(...)):
    from backend.voice_to_workflow import analyze_dictation_ambiguities
    return analyze_dictation_ambiguities(str(payload.get("text") or ""))


@router.post("/api/v2/telegram/route")
def api_v2_telegram_route(payload: Dict[str, Any] = Body(...)):
    from backend.telegram_gateway_v2 import parse_telegram_agent_route
    agent, rest = parse_telegram_agent_route(str(payload.get("text") or ""))
    return {"agent_id": agent, "prompt": rest}


@router.post("/api/v2/joust/score")
def api_v2_joust_score(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.worktree_joust import score_joust_contenders
    return score_joust_contenders(list(payload.get("results") or []))


@router.get("/api/v2/connectors")
def api_v2_connectors():
    from backend.external_connectors import list_connector_capabilities
    return {"status": "success", "connectors": list_connector_capabilities()}


@router.post("/api/v2/extensions/manners")
def api_v2_manners(payload: Dict[str, Any] = Body(...)):
    from backend.special_extensions import analyze_manners_metrics
    return analyze_manners_metrics(list(payload.get("messages") or []))

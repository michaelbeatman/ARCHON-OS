# -*- coding: utf-8 -*-
"""
archon/routers/v2_capabilities.py
=================================
Zentraler FastAPI-Router, der alle 26 neu entwickelten Archon-v2-Module
(Orchestrierung, Security, Memory, Research, Operations & Connectoren)
sauber ueber /api/v2/* mit RBAC (forbid_viewer_writes + require_admin_or_503) bereitstellt.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends as _ArchonDepends, HTTPException, Request
from fastapi.responses import HTMLResponse

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes, require_admin_or_503

logger = logging.getLogger("archon.routers.v2_capabilities")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["archon_v2"])


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
def api_v2_compartment_recall(request: Request, namespace: str = "default", query: str = "", top_k: int = 5):
    require_admin_or_503(request)
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

    # Standard: ECHTER Agenten-Executor. `"noop": true` behält den Trockenlauf für Tests.
    res = await run_workflow_dag(
        dag_def=payload.get("dag") or {},
        executor_fn=_noop_exec if payload.get("noop") else None,
        run_id=payload.get("run_id"),
        gate_approvals=payload.get("gate_approvals"),
    )
    # Vorgabe 1: ehrlicher Status — kein pauschales "success" mehr.
    # Top-Level "status" entspricht dem Run-Status ("completed"/"paused"/"failed"/"already_running");
    # "dag_status" spiegelt ihn fuer Konsumenten, die das alte Feld-Framework erwarten.
    dag_status = str(res.get("status") or "failed")
    rest = {k: v for k, v in res.items() if k != "status"}
    return {"status": dag_status, "dag_status": dag_status, **rest}


@router.get("/api/v2/workflows/dag/runs/{run_id}")
async def api_v2_workflow_dag_run_status(request: Request, run_id: str):
    require_admin_or_503(request)
    from backend.workflow_dag_runner import get_workflow_run
    run = await asyncio.to_thread(get_workflow_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    return {"status": "ok", "run": run}


@router.get("/api/v2/workflows/dag/runs")
async def api_v2_workflow_dag_runs_list(request: Request, limit: int = 50):
    require_admin_or_503(request)
    from backend.workflow_dag_runner import list_workflow_runs
    return {"status": "ok", "runs": await asyncio.to_thread(list_workflow_runs, limit=limit)}


@router.post("/api/v2/workflows/dag/runs/{run_id}/resume")
async def api_v2_workflow_dag_resume(request: Request, run_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.workflow_dag_runner import get_workflow_run
    existing = await asyncio.to_thread(get_workflow_run, run_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    if existing.get("status") not in ("paused", "running"):
        return {"status": "already_terminal", "run": existing}
    # Resume laeuft als Hintergrund-Task: Agenten-Knoten brauchen Minuten, die Route blockiert nicht.
    # Vorgabe 3: schedule_workflow_resume (sync, legt nur einen Task an — nicht blockierend).
    try:
        # DEFERRED-Import: Helper wird parallel in Paket B (backend/workflow_dag_runner.py) gebaut.
        from backend.workflow_dag_runner import schedule_workflow_resume
        schedule_workflow_resume(run_id=run_id, gate_approvals=payload.get("gate_approvals") or {})
    except ImportError:
        # FALLBACK (Helper noch nicht gemerged): direkter Hintergrund-Task via resume_workflow_run.
        try:
            from backend.workflow_dag_runner import resume_workflow_run
            import asyncio as _asyncio
            _asyncio.create_task(resume_workflow_run(run_id=run_id, gate_approvals=payload.get("gate_approvals") or {}))
        except Exception as e:
            logger.error(f"[v2 dag resume] Fallback-Resume fuer {run_id} fehlgeschlagen: {e}")
            raise HTTPException(status_code=500, detail=f"resume scheduling failed: {e}")
    return {"status": "resume_scheduled", "run_id": run_id, "prior_status": existing.get("status")}


@router.get("/api/v2/workflows/templates")
async def api_v2_workflow_templates_list(request: Request):
    require_admin_or_503(request)
    from backend.workflow_templates import list_workflow_templates
    return {"status": "ok", "templates": await asyncio.to_thread(list_workflow_templates)}


@router.post("/api/v2/workflows/templates")
async def api_v2_workflow_templates_save(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_templates import save_workflow_template
    try:
        tpl = await asyncio.to_thread(save_workflow_template, payload)
        return {"status": "ok", "template": tpl}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/workflows/templates/import-n8n")
async def api_v2_workflow_templates_import_n8n(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_templates import import_n8n_workflow_json
    try:
        n8n_json = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else payload
        tpl = await asyncio.to_thread(import_n8n_workflow_json, n8n_json, title_override=payload.get("title"))
        return {"status": "ok", "template": tpl}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/v2/workflows/templates/{tpl_id}")
async def api_v2_workflow_templates_delete(request: Request, tpl_id: str):
    require_admin_or_503(request)
    from backend.workflow_templates import delete_workflow_template
    deleted = await asyncio.to_thread(delete_workflow_template, tpl_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom template not found or built-in")
    return {"status": "ok", "deleted": tpl_id}


@router.post("/api/v2/workflows/templates/{tpl_id}/run")
async def api_v2_workflow_templates_run(request: Request, tpl_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.workflow_templates import launch_workflow_run
    try:
        res = await asyncio.to_thread(
            launch_workflow_run,
            tpl_id=tpl_id,
            inputs=payload.get("inputs") or {},
            cron_schedule=payload.get("cron_schedule"),
            n8n_webhook_url=payload.get("n8n_webhook_url"),
            execute=bool(payload.get("execute", True)),
        )
        return {"status": "success", **res}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/v2/workflows/schedules")
async def api_v2_workflow_schedules_list(request: Request, template_id: Optional[str] = None):
    require_admin_or_503(request)
    from backend.workflow_scheduler import list_schedules
    return {"status": "ok", "schedules": await asyncio.to_thread(list_schedules, template_id=template_id)}


@router.post("/api/v2/workflows/schedules")
async def api_v2_workflow_schedules_save(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_scheduler import upsert_schedule
    try:
        sched = await asyncio.to_thread(upsert_schedule, payload)
        return {"status": "ok", "schedule": sched}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/v2/workflows/schedules/{schedule_id}")
async def api_v2_workflow_schedules_delete(request: Request, schedule_id: str):
    require_admin_or_503(request)
    from backend.workflow_scheduler import delete_schedule
    if not await asyncio.to_thread(delete_schedule, schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "ok", "deleted": schedule_id}


@router.get("/api/v2/workflows/events")
async def api_v2_workflow_events_list(request: Request, limit: int = 100, source: Optional[str] = None):
    require_admin_or_503(request)
    from backend.workflow_scheduler import list_workflow_events
    return {"status": "ok", "events": await asyncio.to_thread(list_workflow_events, limit=limit, source=source)}


@router.post("/api/v2/workflows/events/emit")
async def api_v2_workflow_events_emit(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_scheduler import dispatch_workflow_event
    res = await asyncio.to_thread(
        dispatch_workflow_event,
        source=str(payload.get("source") or "manual"),
        event_type=str(payload.get("event_type") or "manual_trigger"),
        title=str(payload.get("title") or "Manuelles Event"),
        summary=str(payload.get("summary") or ""),
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        correlation_id=payload.get("correlation_id"),
    )
    return {"status": "ok", **res}


@router.get("/api/v2/workflows/event-policies")
async def api_v2_workflow_event_policies_list(request: Request):
    require_admin_or_503(request)
    from backend.workflow_scheduler import EVENT_BUS_SOURCES, EVENT_BUS_TARGETS, list_event_policies
    return {
        "status": "ok",
        "sources": EVENT_BUS_SOURCES,
        "targets": EVENT_BUS_TARGETS,
        "policies": await asyncio.to_thread(list_event_policies),
    }


@router.post("/api/v2/workflows/event-policies")
async def api_v2_workflow_event_policies_save(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.workflow_scheduler import upsert_event_policy
    rule = await asyncio.to_thread(
        upsert_event_policy,
        source=str(payload.get("source") or ""),
        target=str(payload.get("target") or ""),
        policy=str(payload.get("policy") or "allow"),
        max_per_min=int(payload.get("max_per_min") or 20),
        note=str(payload.get("note") or ""),
    )
    return {"status": "ok", "rule": rule}


@router.post("/api/v2/workflows/events/{event_id}/replay")
async def api_v2_workflow_event_replay(request: Request, event_id: str):
    require_admin_or_503(request)
    from backend.workflow_scheduler import replay_workflow_event
    try:
        res = await asyncio.to_thread(replay_workflow_event, event_id)
        return {"status": "ok", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Event not found")


def _treasury_actor(request: Request) -> str:
    try:
        from archon.routers.auth import _resolve_target_passkey_user
        uid, _ = _resolve_target_passkey_user(request)
        return uid
    except Exception as exc:
        # Vorgabe 5: niemals heimlich auf 'admin' fallen — Aufruf ohne identifizierbaren Actor ist 'anonymous'.
        logger.warning(f"[v2 treasury] Actor nicht aufloesbar -> 'anonymous': {exc}")
        return "anonymous"


@router.get("/api/v2/treasury/overview")
async def api_v2_treasury_overview(request: Request):
    require_admin_or_503(request)
    from backend.treasury_engine import get_treasury_overview
    return {"status": "ok", **(await asyncio.to_thread(get_treasury_overview, user_id=_treasury_actor(request)))}


@router.post("/api/v2/treasury/accounts")
async def api_v2_treasury_accounts_save(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required
    from backend.treasury_engine import upsert_account

    uid = _treasury_actor(request)
    if is_passkey_required(uid, category="payments"):
        proof = payload.get("passkey_proof_token") or request.headers.get("x-passkey-proof")
        if not await asyncio.to_thread(
            consume_hitl_proof_token, proof, uid, category="payments"
        ):
            raise HTTPException(status_code=403, detail="passkey_verification_required")
    try:
        acc = await asyncio.to_thread(upsert_account, payload)
        return {"status": "ok", "account": acc}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/v2/treasury/accounts/{acc_id}")
async def api_v2_treasury_accounts_delete(request: Request, acc_id: str):
    require_admin_or_503(request)
    from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required
    from backend.treasury_engine import delete_account

    uid = _treasury_actor(request)
    if is_passkey_required(uid, category="payments"):
        proof = request.headers.get("x-passkey-proof") or request.query_params.get("passkey_proof_token")
        if not await asyncio.to_thread(consume_hitl_proof_token, proof, uid, category="payments"):
            raise HTTPException(status_code=403, detail="passkey_verification_required")
    if not await asyncio.to_thread(delete_account, acc_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok", "deleted": acc_id}


@router.post("/api/v2/treasury/payments/request")
async def api_v2_treasury_payment_request(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin_or_503(request)
    from backend.treasury_engine import request_payment
    try:
        tx = await asyncio.to_thread(request_payment, payload, actor_id=_treasury_actor(request))
        return {"status": "ok", "transaction": tx}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/v2/treasury/payments/{tx_id}/approve")
async def api_v2_treasury_payment_approve(request: Request, tx_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.passkey_hitl import consume_hitl_proof_token
    from backend.treasury_engine import approve_payment

    uid = _treasury_actor(request)
    # Niemals dem Client-Boolean `passkey_verified` vertrauen; nur serverseitig ausgestelltes Einmal-Token akzeptieren.
    server_verified = await asyncio.to_thread(
        consume_hitl_proof_token, payload.get("passkey_proof_token"), uid, category="payments"
    )
    try:
        tx = await asyncio.to_thread(approve_payment, tx_id, approver_id=uid, passkey_verified=server_verified)
        return {"status": "ok", "transaction": tx}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/v2/treasury/payments/{tx_id}/reject")
async def api_v2_treasury_payment_reject(request: Request, tx_id: str, payload: Dict[str, Any] = Body(default={})):
    require_admin_or_503(request)
    from backend.treasury_engine import reject_payment
    try:
        tx = await asyncio.to_thread(
            reject_payment, tx_id, rejected_by=_treasury_actor(request), reason=str(payload.get("reason") or "")
        )
        return {"status": "ok", "transaction": tx}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# (M80 hybrid_sop_runner im Triage-Lauf 21.11.2026 entfernt: Stub-Runner ohne echten
#  Agenten — Nachfolger ist die zentrale DAG-Engine /api/v2/workflows/dag/run.)


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
def api_v2_lossless_search(request: Request, session_id: str, q: str = ""):
    require_admin_or_503(request)
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


@router.post("/api/v2/telegram/route")
def api_v2_telegram_route(payload: Dict[str, Any] = Body(...)):
    from backend.telegram_gateway_v2 import parse_telegram_agent_route
    agent, rest = parse_telegram_agent_route(str(payload.get("text") or ""))
    return {"agent_id": agent, "prompt": rest}
# (M84 injection-drill, M87 connectors, M88 manners, M92 freeze, M39 meetings,
#  M54 voice-analyze und M85 joust sind im Triage-Lauf 21.11.2026 entfernt:
#  Theater-Code laut Deepdive — Module liegen unter archive/20261121_triage_c_modules/)

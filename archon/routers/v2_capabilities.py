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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from archon.routers._rbac import (
    forbid_viewer_writes as _forbid_viewer_writes,
    require_admin_or_503,
    get_session_actor,
)

logger = logging.getLogger("archon.routers.v2_capabilities")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["archon_v2"])


# --- Pydantic-v2 Payload-Modelle (Etappe 3, Teil 1) --------------------------
# Alle Modelle mit extra="ignore": bestehende Clients senden Zusatzfelder
# (created_by/user_id/...), die serverseitig aus der Session kommen.
# Verschachtelte Freiform-Strukturen (DAG, n8n-JSON, Tool-Args, Nodes/Edges)
# bleiben bewusst Dict/List, damit die Backend-Funktionen keine Felder verlieren.


class WarrantIssueRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    allowed_tools: List[str] = Field(default_factory=list, max_length=200)
    constraints: Optional[Dict[str, Any]] = None
    # backend.tool_warrants.issue_warrant begrenzt die Laufzeit hart auf 900 s.
    ttl_seconds: int = Field(default=900, ge=1, le=900)


class WarrantVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    warrant: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="", max_length=300)
    tool_name: str = Field(default="", max_length=200)
    args: Optional[Dict[str, Any]] = None


class CompartmentStoreRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    namespace: str = Field(default="default", min_length=1, max_length=200)
    content: str = Field(default="", max_length=1_000_000)
    tags: List[str] = Field(default_factory=list, max_length=100)


class PolicyBacktestRequest(BaseModel):
    """Policy-Regeln für den Flightlog-Backtester (Felder aus backend/flightlog_backtester.py)."""
    model_config = ConfigDict(extra="ignore")
    blocked_tools: List[str] = Field(default_factory=list, max_length=500)
    blocked_arg_patterns: List[str] = Field(default_factory=list, max_length=200)
    max_tokens_per_call: int = Field(default=0, ge=0, le=10_000_000)


class WorkflowDagRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dag: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = Field(default=None, max_length=200)
    # KRITISCH (Audit 23.11.2026): `noop` und `gate_approvals` waren
    # client-gesteuerte HITL-/Erfolgs-Bypasses. Freigaben kommen ausschliesslich
    # aus dem verifizierten Decision-Store (archon/routers/decisions.py).


class WorkflowDagResumeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CustomPluginRegisterRequest(BaseModel):
    """Felder aus backend.workflow_node_plugins.register_custom_marketplace_plugin."""
    model_config = ConfigDict(extra="ignore")
    source_url: str = Field(default="", max_length=1000)
    github_url: str = Field(default="", max_length=1000)  # Legacy-Alias im Backend
    label: str = Field(default="", max_length=200)
    category: str = Field(default="business", max_length=50)
    description: str = Field(default="", max_length=2000)
    adapter: str = Field(default="http", max_length=30)
    icon: str = Field(default="", max_length=64)
    http_endpoint: str = Field(default="", max_length=1000)
    mcp_tool: str = Field(default="", max_length=200)


class WorkflowTemplateSaveRequest(BaseModel):
    """Kompletter Template-Payload; Nodes/Edges bleiben roh (viele optionale Felder)."""
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    category: str = Field(default="Eigene Workflows", max_length=200)
    description: str = Field(default="", max_length=5000)
    header_image: str = Field(default="", max_length=350_000)
    schedule_hint: str = Field(default="", max_length=500)
    n8n_webhook_hint: str = Field(default="", max_length=500)
    inputs: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)
    nodes: List[Dict[str, Any]] = Field(default_factory=list, max_length=1000)
    edges: List[Dict[str, Any]] = Field(default_factory=list, max_length=2000)


class N8nImportRequest(BaseModel):
    """Studio schickt {workflow: <n8n-JSON>}; Rohes n8n-JSON bleibt als Fallback möglich."""
    model_config = ConfigDict(extra="ignore")
    workflow: Optional[Dict[str, Any]] = None
    title: Optional[str] = Field(default=None, max_length=300)
    # Fallback-Felder für den Import ohne "workflow"-Wrapper.
    name: Optional[str] = Field(default=None, max_length=300)
    nodes: Optional[List[Dict[str, Any]]] = None
    connections: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None
    pinData: Optional[Dict[str, Any]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    versionId: Optional[str] = None
    id: Optional[str] = None


class WorkflowTemplateRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    inputs: Dict[str, Any] = Field(default_factory=dict)
    cron_schedule: Optional[str] = Field(default=None, max_length=500)
    n8n_webhook_url: Optional[str] = Field(default=None, max_length=1000)
    execute: bool = True


class WorkflowScheduleSaveRequest(BaseModel):
    """Felder aus backend.workflow_scheduler.upsert_schedule (Studio-Formular)."""
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = Field(default=None, max_length=200)
    template_id: str = Field(min_length=1, max_length=200)
    title: Optional[str] = Field(default=None, max_length=300)
    enabled: bool = True
    trigger_type: str = Field(default="cron", max_length=50)
    cron_expr: str = Field(default="", max_length=200)
    start_at: str = Field(default="", max_length=100)
    end_at: str = Field(default="", max_length=100)
    start_condition: str = Field(default="always", max_length=50)
    end_condition: str = Field(default="none", max_length=50)
    max_runs: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    watchdog_keyword: str = Field(default="", max_length=200)
    n8n_webhook_url: str = Field(default="", max_length=1000)
    inputs: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_runs", mode="before")
    @classmethod
    def _blank_max_runs_is_none(cls, value: Any) -> Any:
        # Das Studio sendet einen leeren Zahlen-Input als "" → keine Begrenzung.
        return None if value == "" else value


class WorkflowEventEmitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = Field(default="manual", min_length=1, max_length=100)
    event_type: str = Field(default="manual_trigger", min_length=1, max_length=100)
    title: str = Field(default="Manuelles Event", max_length=300)
    summary: str = Field(default="", max_length=5000)
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, max_length=200)


class EventPolicySaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = Field(default="", max_length=100)
    target: str = Field(default="", max_length=100)
    policy: str = Field(default="allow", max_length=50)
    # backend.workflow_scheduler.upsert_event_policy clampet auf mindestens 1.
    max_per_min: int = Field(default=20, ge=0, le=100_000)
    note: str = Field(default="", max_length=1000)


# --- M90: Signierte Tool-Warrants ---
@router.post("/api/v2/security/warrants/issue")
def api_v2_issue_warrant(request: Request, payload: WarrantIssueRequest):
    require_admin_or_503(request)
    from backend.tool_warrants import issue_warrant, register_warrant
    # Session aus der authentifizierten Identität, nicht aus dem Body —
    # sonst könnte ein Aufrufer ein Warrant für eine fremde Session binden.
    session_id = f"user:{get_session_actor(request)}"
    warrant = issue_warrant(
        session_id=session_id,
        allowed_tools=payload.allowed_tools,
        constraints=payload.constraints,
        ttl_seconds=payload.ttl_seconds,
    )
    register_warrant(warrant)
    return {"status": "success", "warrant": warrant, "session_id": session_id}


@router.post("/api/v2/security/warrants/verify")
def api_v2_verify_warrant(payload: WarrantVerifyRequest):
    from backend.tool_warrants import verify_warrant_for_call
    return verify_warrant_for_call(
        warrant=payload.warrant,
        session_id=payload.session_id,
        tool_name=payload.tool_name,
        args=payload.args,
    )


# --- M79: Offline Encrypted Memory Vault ---
@router.post("/api/v2/memory/compartment/store")
def api_v2_compartment_store(request: Request, payload: CompartmentStoreRequest):
    require_admin_or_503(request)
    from backend.offline_memory_vault import store_memory
    eid = store_memory(
        namespace=payload.namespace,
        content=payload.content,
        tags=payload.tags,
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
def api_v2_policy_backtest(request: Request, payload: PolicyBacktestRequest):
    require_admin_or_503(request)
    from backend.flightlog_backtester import backtest_policy
    return {"status": "success", **backtest_policy(payload.model_dump(exclude_none=True))}


# --- M77, M80, M92, M93: Workflows, SOPs, Freeze & Firewall ---
@router.post("/api/v2/workflows/dag/run")
async def api_v2_workflow_dag_run(request: Request, payload: WorkflowDagRunRequest):
    require_admin_or_503(request)
    from backend.workflow_dag_runner import run_workflow_dag

    # Immer der echte Agenten-Executor. Ein client-gesteuerter Trockenlauf oder
    # client-gesteuerte Gate-Freigaben sind nicht zulaessig (Audit 23.11.2026).
    res = await run_workflow_dag(
        dag_def=payload.dag,
        executor_fn=None,
        run_id=payload.run_id,
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
async def api_v2_workflow_dag_resume(request: Request, run_id: str, payload: WorkflowDagResumeRequest = WorkflowDagResumeRequest()):
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
        schedule_workflow_resume(run_id=run_id)
    except ImportError:
        # FALLBACK (Helper noch nicht gemerged): direkter Hintergrund-Task via resume_workflow_run.
        try:
            from backend.workflow_dag_runner import resume_workflow_run
            import asyncio as _asyncio
            _asyncio.create_task(resume_workflow_run(run_id=run_id))
        except Exception as e:
            logger.error(f"[v2 dag resume] Fallback-Resume fuer {run_id} fehlgeschlagen: {e}")
            raise HTTPException(status_code=500, detail=f"resume scheduling failed: {e}")
    return {"status": "resume_scheduled", "run_id": run_id, "prior_status": existing.get("status")}


@router.get("/api/v2/workflows/templates")
async def api_v2_workflow_templates_list(request: Request):
    require_admin_or_503(request)
    from backend.workflow_templates import list_workflow_templates
    return {"status": "ok", "templates": await asyncio.to_thread(list_workflow_templates)}


@router.get("/api/v2/workflows/node-plugins")
async def api_v2_workflow_node_plugins(request: Request):
    require_admin_or_503(request)
    from backend.workflow_node_plugins import list_workflow_node_plugins
    return {"status": "ok", "plugins": await asyncio.to_thread(list_workflow_node_plugins)}


@router.get("/api/v2/workflows/node-plugins/marketplace")
async def api_v2_workflow_node_plugins_marketplace(request: Request):
    require_admin_or_503(request)
    from backend.workflow_node_plugins import list_marketplace_plugins
    return {"status": "ok", "items": await asyncio.to_thread(list_marketplace_plugins)}


@router.post("/api/v2/workflows/node-plugins/marketplace/{plugin_id}/install")
async def api_v2_workflow_node_plugin_install(request: Request, plugin_id: str):
    require_admin_or_503(request)
    from backend.workflow_node_plugins import install_marketplace_plugin
    try:
        res = await asyncio.to_thread(install_marketplace_plugin, plugin_id)
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/v2/workflows/node-plugins/marketplace/{plugin_id}")
async def api_v2_workflow_node_plugin_uninstall(request: Request, plugin_id: str):
    require_admin_or_503(request)
    from backend.workflow_node_plugins import uninstall_marketplace_plugin
    try:
        return await asyncio.to_thread(uninstall_marketplace_plugin, plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v2/workflows/node-plugins/marketplace/custom")
async def api_v2_workflow_node_plugin_register_custom(request: Request, payload: CustomPluginRegisterRequest):
    require_admin_or_503(request)
    from backend.workflow_node_plugins import register_custom_marketplace_plugin
    try:
        return await asyncio.to_thread(register_custom_marketplace_plugin, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v2/workflows/templates")
async def api_v2_workflow_templates_save(request: Request, payload: WorkflowTemplateSaveRequest):
    require_admin_or_503(request)
    from backend.workflow_templates import save_workflow_template
    try:
        tpl = await asyncio.to_thread(save_workflow_template, payload.model_dump(exclude_none=True))
        return {"status": "ok", "template": tpl}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/workflows/templates/import-n8n")
async def api_v2_workflow_templates_import_n8n(request: Request, payload: N8nImportRequest):
    require_admin_or_503(request)
    from backend.workflow_templates import import_n8n_workflow_json
    try:
        n8n_json = payload.workflow
        if not isinstance(n8n_json, dict):
            # Fallback: rohes n8n-JSON direkt im Body (ohne "workflow"-Wrapper).
            n8n_json = payload.model_dump(exclude_none=True, exclude={"workflow", "title"})
        tpl = await asyncio.to_thread(import_n8n_workflow_json, n8n_json, title_override=payload.title)
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
async def api_v2_workflow_templates_run(request: Request, tpl_id: str, payload: WorkflowTemplateRunRequest = WorkflowTemplateRunRequest()):
    require_admin_or_503(request)
    from backend.workflow_templates import launch_workflow_run
    try:
        res = await asyncio.to_thread(
            launch_workflow_run,
            tpl_id=tpl_id,
            inputs=payload.inputs,
            cron_schedule=payload.cron_schedule,
            n8n_webhook_url=payload.n8n_webhook_url,
            execute=payload.execute,
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
async def api_v2_workflow_schedules_save(request: Request, payload: WorkflowScheduleSaveRequest):
    require_admin_or_503(request)
    from backend.workflow_scheduler import upsert_schedule
    try:
        sched = await asyncio.to_thread(upsert_schedule, payload.model_dump(exclude_none=True))
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
async def api_v2_workflow_events_emit(request: Request, req: WorkflowEventEmitRequest):
    require_admin_or_503(request)
    from backend.workflow_scheduler import dispatch_workflow_event
    res = await asyncio.to_thread(
        dispatch_workflow_event,
        source=req.source,
        event_type=req.event_type,
        title=req.title,
        summary=req.summary,
        payload=req.payload,
        correlation_id=req.correlation_id,
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
async def api_v2_workflow_event_policies_save(request: Request, payload: EventPolicySaveRequest):
    require_admin_or_503(request)
    from backend.workflow_scheduler import upsert_event_policy
    rule = await asyncio.to_thread(
        upsert_event_policy,
        source=payload.source,
        target=payload.target,
        policy=payload.policy,
        max_per_min=payload.max_per_min,
        note=payload.note,
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


# --- Etappe 4: Pydantic-v2-Requestmodelle fuer /api/v2/treasury/* bis Dateiende ---
# Import und Modelle stehen bewusst erst hier (nach Etappe 3), damit der
# parallel bearbeitete Kopf der Datei nicht angefasst wird.
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TreasuryAccountSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=200)
    account_type: str = Field(default="bank", max_length=40)
    custody_mode: str = Field(default="", max_length=40)
    allowlist: List[str] = Field(default_factory=list)
    id: Optional[str] = Field(default=None, max_length=120)
    currency: str = Field(default="EUR", max_length=10)
    balance: float = Field(default=0.0, ge=0, le=1e15)
    identifier: str = Field(default="", max_length=200)
    per_tx_limit: float = Field(default=0.0, ge=0, le=1e15)
    daily_limit: float = Field(default=0.0, ge=0, le=1e15)
    active: bool = True
    # Nur serverseitig ausgewertet (HITL-Proof), nie an upsert_account durchgereicht.
    passkey_proof_token: Optional[str] = None

    @field_validator("allowlist", mode="before")
    @classmethod
    def _allowlist_from_csv(cls, value: Any) -> Any:
        """Alt-Clients senden die Allowlist als 'a,b,c' — Normalisierung wie im Backend."""
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return value


class TreasuryPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    account_id: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=1e15)
    direction: str = Field(default="out", max_length=10)
    recipient: str = Field(default="", max_length=300)
    purpose: str = Field(default="", max_length=500)
    category: str = Field(default="Sonstiges", max_length=120)
    requested_by: Optional[str] = Field(default=None, max_length=120)
    idempotency_key: Optional[str] = Field(default=None, max_length=200)
    is_agent_request: bool = False


class TreasuryPaymentApproveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    passkey_proof_token: Optional[str] = None


class TreasuryPaymentRejectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = Field(default="", max_length=1000)


class ToolOutputGuardRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tool_name: str = Field(default="tool", max_length=200)
    output: Any = ""
    max_chars: int = Field(default=8000, ge=1, le=1_000_000)


class ReceiptHtmlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str = Field(default="t-0", max_length=120)
    title: str = Field(default="Session Receipt", max_length=300)
    original_ask: str = Field(default="", max_length=20_000)
    events: List[Dict[str, Any]] = Field(default_factory=list)


class ResearchTriangulateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str = Field(default="Research", max_length=300)
    summary: str = Field(default="", max_length=20_000)
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class CalendarGridRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    events: List[Dict[str, Any]] = Field(default_factory=list)
    view: str = Field(default="week", max_length=20)
    anchor_date: Optional[str] = Field(default=None, max_length=40)


class CalendarSyncRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    local_events: List[Dict[str, Any]] = Field(default_factory=list)
    remote_events: List[Dict[str, Any]] = Field(default_factory=list)


class ContractDiffRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    old_text: str = Field(default="", max_length=2_000_000)
    new_text: str = Field(default="", max_length=2_000_000)


class ContractDeadlinesScanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    contracts: List[Dict[str, Any]] = Field(default_factory=list)


class PortalLinkCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    offer_id: str = Field(default="", max_length=120)
    title: str = Field(default="Angebot", max_length=300)
    password: str = Field(default="", max_length=200)
    ttl_hours: int = Field(default=72, ge=1, le=8760)


class TimeStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_id: str = Field(default="default", max_length=120)
    task_id: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    hourly_rate_eur: float = Field(default=120.0, ge=0, le=1_000_000)


class WatchdogScoreRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20_000)
    keywords: List[str] = Field(default_factory=list)


class GdprEraseRequest(BaseModel):
    # 'subject' bewusst ohne min_length: die leere Pruefung bleibt im Backend
    # und liefert weiterhin die etablierte HTTP 400 mit altem Body-Shape.
    model_config = ConfigDict(extra="ignore")
    subject: str = Field(default="", max_length=300)
    tenant_id: str = Field(default="default", max_length=120)


class TelegramRouteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(default="", max_length=20_000)


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    target_type: str = Field(default="profile", max_length=80)
    target_id: str = Field(default="default", max_length=120)
    gold_dataset: Optional[Any] = None
    judge_model: str = Field(default="auto", max_length=120)
    min_pass_score: float = Field(default=70.0, ge=0, le=100)


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
async def api_v2_treasury_accounts_save(request: Request, req: TreasuryAccountSaveRequest):
    require_admin_or_503(request)
    from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required
    from backend.treasury_engine import upsert_account

    uid = _treasury_actor(request)
    if is_passkey_required(uid, category="payments"):
        proof = req.passkey_proof_token or request.headers.get("x-passkey-proof")
        if not await asyncio.to_thread(
            consume_hitl_proof_token, proof, uid, category="payments",
            action="Treasury-Konto speichern", resource=str(req.id or req.name or ""),
        ):
            raise HTTPException(status_code=403, detail="passkey_verification_required")
    try:
        acc = await asyncio.to_thread(
            upsert_account, req.model_dump(exclude_none=True, exclude={"passkey_proof_token"})
        )
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
        if not await asyncio.to_thread(
            consume_hitl_proof_token, proof, uid, category="payments",
            action="Treasury-Konto entfernen", resource=acc_id,
        ):
            raise HTTPException(status_code=403, detail="passkey_verification_required")
    if not await asyncio.to_thread(delete_account, acc_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok", "deleted": acc_id}


@router.post("/api/v2/treasury/payments/request")
async def api_v2_treasury_payment_request(request: Request, req: TreasuryPaymentRequest):
    require_admin_or_503(request)
    from backend.treasury_engine import request_payment
    try:
        tx = await asyncio.to_thread(
            request_payment, req.model_dump(exclude_none=True), actor_id=_treasury_actor(request)
        )
        return {"status": "ok", "transaction": tx}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/v2/treasury/payments/{tx_id}/approve")
async def api_v2_treasury_payment_approve(
    request: Request,
    tx_id: str,
    req: Optional[TreasuryPaymentApproveRequest] = Body(default=None),
):
    require_admin_or_503(request)
    from backend.passkey_hitl import consume_hitl_proof_token
    from backend.treasury_engine import approve_payment

    req = req or TreasuryPaymentApproveRequest()
    uid = _treasury_actor(request)
    # Niemals dem Client-Boolean `passkey_verified` vertrauen; nur serverseitig
    # ausgestelltes Einmal-Token akzeptieren. KRITISCH: das Proof muss an die
    # KONKRETE Aktion + Ressource gebunden sein, sonst kann ein Proof fuer
    # eine harmlose Payments-Operation eine beliebige andere Zahlung freigeben.
    server_verified = await asyncio.to_thread(
        consume_hitl_proof_token,
        req.passkey_proof_token,
        uid,
        category="payments",
        action="Zahlung freigeben",
        resource=tx_id,
    )
    try:
        tx = await asyncio.to_thread(approve_payment, tx_id, approver_id=uid, passkey_verified=server_verified)
        return {"status": "ok", "transaction": tx}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/v2/treasury/payments/{tx_id}/reject")
async def api_v2_treasury_payment_reject(
    request: Request,
    tx_id: str,
    req: Optional[TreasuryPaymentRejectRequest] = Body(default=None),
):
    require_admin_or_503(request)
    from backend.treasury_engine import reject_payment

    req = req or TreasuryPaymentRejectRequest()
    try:
        tx = await asyncio.to_thread(
            reject_payment, tx_id, rejected_by=_treasury_actor(request), reason=req.reason
        )
        return {"status": "ok", "transaction": tx}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# (M80 hybrid_sop_runner im Triage-Lauf 21.11.2026 entfernt: Stub-Runner ohne echten
#  Agenten — Nachfolger ist die zentrale DAG-Engine /api/v2/workflows/dag/run.)


@router.post("/api/v2/tools/firewall/guard")
def api_v2_tool_output_guard(req: ToolOutputGuardRequest):
    from backend.tool_output_firewall import guard_tool_output
    return guard_tool_output(
        tool_name=req.tool_name,
        raw_output=req.output,
        max_chars=req.max_chars,
    )


# --- M82 & M94: Session Receipts & Lossless Session DAG ---
@router.post("/api/v2/receipts/html", response_class=HTMLResponse)
def api_v2_render_receipt_html(req: ReceiptHtmlRequest):
    from backend.session_receipts import render_offline_html_receipt
    return render_offline_html_receipt(
        task_id=req.task_id,
        title=req.title,
        original_ask=req.original_ask,
        events=req.events,
    )


@router.get("/api/v2/sessions/{session_id}/lossless/search")
def api_v2_lossless_search(request: Request, session_id: str, q: str = ""):
    require_admin_or_503(request)
    from backend.lossless_session_dag import search_lossless_history
    return {"status": "success", "turns": search_lossless_history(session_id, q)}


# --- M45 & M50: Deep Research & Eval Arena ---
@router.post("/api/v2/research/triangulate")
def api_v2_research_triangulate(req: ResearchTriangulateRequest):
    from backend.deep_research_lab import compile_research_dossier
    return compile_research_dossier(
        topic=req.topic,
        summary=req.summary,
        sources=req.sources,
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
def api_v2_calendar_grid(req: CalendarGridRequest):
    from backend.enterprise_calendar import build_calendar_grid
    return build_calendar_grid(
        events=req.events,
        view=req.view,
        anchor_date=req.anchor_date,
    )


@router.post("/api/v2/calendar/sync")
def api_v2_calendar_sync(request: Request, req: CalendarSyncRequest):
    require_admin_or_503(request)
    from backend.calendar_sync_blocker import sync_calendar_bidirectional
    return sync_calendar_bidirectional(
        local_events=req.local_events,
        remote_events=req.remote_events,
    )


@router.post("/api/v2/contracts/diff")
def api_v2_contract_diff(req: ContractDiffRequest):
    from backend.contract_diff_redliner import diff_contract_clauses
    return diff_contract_clauses(req.old_text, req.new_text)


@router.post("/api/v2/contracts/deadlines/scan")
def api_v2_contract_deadlines(req: ContractDeadlinesScanRequest):
    from backend.contract_deadline_watcher import scan_upcoming_deadlines
    return {"status": "success", "alerts": scan_upcoming_deadlines(req.contracts)}


@router.post("/api/v2/portal/links")
def api_v2_create_portal_link(request: Request, req: PortalLinkCreateRequest):
    require_admin_or_503(request)
    from backend.client_approval_portal import create_share_link
    return create_share_link(
        offer_id=req.offer_id,
        title=req.title,
        password=req.password,
        ttl_hours=req.ttl_hours,
    )


@router.post("/api/v2/time/start")
def api_v2_time_start(request: Request, req: TimeStartRequest):
    require_admin_or_503(request)
    from backend.time_tracking_invoice import start_timer
    eid = start_timer(
        project_id=req.project_id,
        task_id=req.task_id,
        description=req.description,
        hourly_rate_eur=req.hourly_rate_eur,
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
def api_v2_watchdog_score(req: WatchdogScoreRequest):
    from backend.watchdog_radar_v2 import score_signal_relevance
    return score_signal_relevance(
        req.title,
        req.body,
        req.keywords,
    )


@router.post("/api/v2/gdpr/erase")
def api_v2_gdpr_erase(request: Request, req: GdprEraseRequest):
    require_admin_or_503(request)
    from backend.tenant_db_registry import gdpr_erase_subject_data
    try:
        return {
            "status": "success",
            **gdpr_erase_subject_data(
                subject_identifier=req.subject,
                tenant_id=req.tenant_id,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/v2/telegram/route")
def api_v2_telegram_route(req: TelegramRouteRequest):
    from backend.telegram_gateway_v2 import parse_telegram_agent_route
    agent, rest = parse_telegram_agent_route(req.text)
    return {"agent_id": agent, "prompt": rest}


# --- Punkt 3.2.4: Automatische Eval- & Regression-Gates (Gold-Datasets + LLM-as-a-Judge) ---
@router.post("/api/v2/eval/run")
async def api_v2_eval_run(request: Request, req: EvalRunRequest):
    require_admin_or_503(request)
    from backend.eval_gates import run_evaluation
    target_type = req.target_type.strip()
    target_id = req.target_id.strip()
    gold_dataset = req.gold_dataset
    judge_model = req.judge_model.strip()
    min_pass_score = req.min_pass_score

    res = await run_evaluation(
        target_type=target_type,
        target_id=target_id,
        gold_dataset=gold_dataset,
        judge_model=judge_model,
        min_pass_score=min_pass_score,
    )
    return res


@router.get("/api/v2/eval/runs")
def api_v2_eval_runs_list(request: Request, target_id: Optional[str] = None, limit: int = 50):
    require_admin_or_503(request)
    from backend.eval_gates import list_eval_runs
    return {"status": "success", "runs": list_eval_runs(target_id=target_id, limit=limit)}


@router.get("/api/v2/eval/runs/{eval_id}")
def api_v2_eval_run_detail(request: Request, eval_id: str):
    require_admin_or_503(request)
    from backend.eval_gates import get_eval_run
    run_obj = get_eval_run(eval_id)
    if not run_obj:
        raise HTTPException(status_code=404, detail=f"Eval-Run '{eval_id}' nicht gefunden.")
    return {"status": "success", "run": run_obj}


@router.get("/api/v2/eval/gold-datasets/{target_type}")
def api_v2_eval_gold_dataset(target_type: str, target_id: Optional[str] = None):
    from backend.eval_gates import get_default_gold_dataset
    return {"status": "success", "target_type": target_type, "dataset": get_default_gold_dataset(target_type, target_id or "")}

# (M84 injection-drill, M87 connectors, M88 manners, M92 freeze, M39 meetings,
#  M54 voice-analyze und M85 joust sind im Triage-Lauf 21.11.2026 entfernt:
#  Theater-Code laut Deepdive — Module liegen unter archive/20261121_triage_c_modules/)

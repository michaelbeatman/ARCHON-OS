from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Feedback, Notifications, MCP, Streaming, Backup, GDPR und Chaos-Testing.

Ausgelagert aus backend/operations_api.py.
"""
import logging
logger = logging.getLogger("archon.routers.operations_sysops")

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from archon.routers._rbac import require_admin_or_503, get_session_actor

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Pydantic-v2 Request-Modelle (Etappe 6)
# Frontend-Feldnamen bleiben unverändert; unbekannte Felder werden ignoriert.
# ---------------------------------------------------------------------------

class NotificationPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: Optional[bool] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = Field(None, pattern=r"^\d{1,2}:[0-5]\d$")
    quiet_hours_end: Optional[str] = Field(None, pattern=r"^\d{1,2}:[0-5]\d$")
    allow_critical_during_quiet_hours: Optional[bool] = None
    telegram_enabled: Optional[bool] = None
    telegram_min_severity: Optional[str] = Field(None, max_length=32)
    timezone: Optional[str] = Field(None, max_length=64)
    allow_emergency_during_quiet: Optional[bool] = None
    digest_enabled: Optional[bool] = None
    digest_delivery_time: Optional[str] = Field(None, pattern=r"^\d{1,2}:[0-5]\d$")
    min_severity: Optional[str] = Field(None, max_length=32)


class McpToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = Field(None, max_length=200)
    arguments: Union[Dict[str, Any], str] = Field(default_factory=dict)
    agent_id: Optional[str] = Field(None, max_length=200)
    approval_id: Optional[str] = Field(None, max_length=200)


class TaskChunkBroadcastRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk: str = Field("", max_length=100_000)
    agent_id: Optional[str] = Field(None, max_length=200)
    status: str = Field("in_progress", max_length=32)


class GdprExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    identifier: str = Field("", max_length=500)


class GdprEraseRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    identifier: str = Field("", max_length=500)
    dry_run: bool = False
    anonymize: bool = True


class GdprVvtUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    activity_id: Optional[str] = Field(None, max_length=128)
    name: str = Field("", max_length=300)
    purpose: str = Field("", max_length=4000)
    legal_basis: str = Field("", max_length=500)
    data_categories: Optional[str] = Field(None, max_length=4000)
    data_subjects: Optional[str] = Field(None, max_length=4000)
    recipient_categories: Optional[str] = Field(None, max_length=4000)
    third_country_transfers: Optional[str] = Field(None, max_length=4000)
    retention_period: Optional[str] = Field(None, max_length=500)
    technical_organizational_measures: Optional[str] = Field(None, max_length=8000)


class ChaosRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dry_run: bool = True


# =========================================================================
# HUMAN FEEDBACK ENGINE
# =========================================================================

class HumanFeedbackSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    agent_id: str
    score: int  # +1 (positiv / Daumen hoch) oder -1 (negativ / Daumen runter)
    task_id: Optional[str] = None
    comment: Optional[str] = None
    corrected_text: Optional[str] = None
    source: Optional[str] = "kanban_card"
    task_prompt: Optional[str] = None


@router.post("/feedback")
def api_submit_human_feedback(req: HumanFeedbackSubmitRequest):
    """
    Nimmt menschliches Feedback (Daumen hoch/runter, Korrekturhinweise) entgegen.
    Negative Bewertungen (-1) werden automatisch als Gold-Standard-Regressionstestfall angelegt.
    """
    try:
        from backend.human_feedback_engine import feedback_engine
        res = feedback_engine.submit_feedback(
            agent_id=req.agent_id,
            score=req.score,
            task_id=req.task_id,
            comment=req.comment,
            corrected_text=req.corrected_text,
            source=req.source or "kanban_card",
            task_prompt=req.task_prompt
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/stats")
def api_get_feedback_stats():
    """Gibt globale Feedback-Statistiken, Zustimmungsquoten und Agenten-Metriken zurück."""
    try:
        from backend.human_feedback_engine import feedback_engine
        return {"status": "success", "stats": feedback_engine.get_stats()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/task/{task_id}")
def api_get_task_feedback(task_id: str):
    """Liefert alle Feedback-Einträge für eine bestimmte Aufgabe."""
    try:
        from backend.human_feedback_engine import feedback_engine
        entries = feedback_engine.get_task_feedback(task_id)
        return {"status": "success", "task_id": task_id, "feedbacks": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# CONFIG VALIDATION & METRICS
# =========================================================================

@router.get("/config/validate")
def api_validate_system_config():
    """Führt eine vollständige Pre-Flight-Konfigurationsprüfung aller System-JSONs durch."""
    try:
        from backend.config_validator import validator
        res = validator.validate_all(strict=False)
        return {"status": "success", "report": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/summary")
def api_get_metrics_summary():
    """Liefert aggregierte System-, Queue- und Telemetrie-Metriken als strukturiertes JSON."""
    try:
        from backend.metrics_collector import metrics_collector
        return {"status": "success", "metrics": metrics_collector.get_summary_json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# NOTIFICATIONS & DIGESTS
# =========================================================================

@router.get("/notifications/policy")
def api_get_notification_policy():
    """Liefert die aktuellen Benachrichtigungs- und Ruhezeit-Regeln."""
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        return {
            "status": "success",
            "policy": hub.get_policy(),
            "in_quiet_hours": hub.is_in_quiet_hours()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/policy")
def api_update_notification_policy(request: Request, req: NotificationPolicyUpdateRequest):
    """Aktualisiert die Benachrichtigungs- und Ruhezeit-Regeln in settings.json."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        updated = hub.update_policy(req.model_dump(exclude_none=True))
        return {
            "status": "success",
            "policy": updated,
            "in_quiet_hours": hub.is_in_quiet_hours()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/digest")
def api_get_suppressed_digest(since_hours: int = 24):
    """Liefert alle während der Ruhezeiten gepufferten Benachrichtigungen als Sammel-Digest."""
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        items = hub.get_suppressed_digest(since_hours=since_hours)
        return {
            "status": "success",
            "count": len(items),
            "since_hours": since_hours,
            "suppressed_notifications": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# MCP PROTOCOL (MODEL CONTEXT PROTOCOL)
# =========================================================================

@router.get("/mcp/tools")
def api_get_mcp_tools():
    """Gibt alle über den Archon MCP-Server exponierten Werkzeuge und deren Schemas zurück."""
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        server = ArchonMcpServer()
        return {
            "status": "success",
            "server": server.server_name,
            "version": server.server_version,
            "protocol": server.protocol_version,
            "tools": server.get_tool_definitions()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcp/call")
def api_call_mcp_tool(request: Request, req: McpToolCallRequest):
    """Führt ein Archon MCP-Werkzeug über eine HTTP-REST-Schnittstelle aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        # D04/MED: Tool-Output-Firewall im echten Chokepoint (wie in plugins.py,
        # mcp_gateway.py und workflow_node_plugins.py).
        from backend.tool_runtime import enforce_tool_execution, guard_result, record_tool_read_side_effect
        tool_name = req.name
        arguments = req.arguments
        if not tool_name:
            raise HTTPException(status_code=400, detail={"code": "sysops_name_required", "params": {}})
        # Actor/Session und Warrant serverseitig — nie aus dem Request-Body.
        # Ein client-gesteuertes agent_id wuerde die agentenbezogenen Taint-/
        # Warrant-Gates umgehen (identisch zu plugins.py:144-145).
        actor = get_session_actor(request)
        session_id = f"user:{actor}"
        agent_id = session_id
        from backend.tool_warrants import get_warrant_for_session
        warrant = get_warrant_for_session(session_id, str(tool_name))
        gate = enforce_tool_execution(
            agent_id=agent_id,
            session_id=session_id,
            tool_name=tool_name,
            args=arguments if isinstance(arguments, dict) else {},
            approval_id=req.approval_id,
            warrant=warrant,
            requested_by=actor,
        )
        if not gate.get("allowed"):
            raise HTTPException(status_code=403, detail=gate)
        server = ArchonMcpServer()
        result = server.execute_tool(tool_name, arguments if isinstance(arguments, dict) else {})
        record_tool_read_side_effect(session_id, tool_name)
        try:
            guarded = guard_result(tool_name, result)
        except Exception as exc:
            # Firewall-Fehler darf NIE den Roh-Output durchlassen.
            logger.error(
                "[SysOps] Tool-Output-Firewall fehlgeschlagen (%s: %s) — Response gesperrt.",
                tool_name, exc,
            )
            raise HTTPException(status_code=503, detail={"code": "sysops_tool_output_guard_failed", "params": {}})
        return {"status": "success", "result": guarded}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# REAL-TIME TASK EXECUTION STREAMING & CHUNKING
# =========================================================================

@router.get("/tasks/{task_id}/stream")
async def api_stream_task_execution(task_id: str):
    """
    Server-Sent Events (SSE) Stream für die Live-Beobachtung einer laufenden Task-Ausführung.
    Ermöglicht Token-Streaming in Echtzeit ohne Polling.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=200)

    try:
        from archon.core.provider_registry import get_provider
        main = get_provider("app_main")
        if hasattr(main, "_SSE_SUBSCRIBERS"):
            lock = getattr(main, "_SSE_SUB_LOCK", None)
            if lock is not None:
                with lock:
                    main._SSE_SUBSCRIBERS.append(q)
            else:
                main._SSE_SUBSCRIBERS.append(q)
    except Exception as exc:
        logger.debug(f"SSE-Subscriber-Registrierung fehlgeschlagen: {exc}")

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id, 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    try:
                        p_dict = json.loads(payload)
                        p_data = p_dict.get("data", {})
                        if p_data.get("task_id") == task_id or p_dict.get("type") in ("ticker_update", "ping"):
                            yield f"data: {payload}\n\n"
                            if p_dict.get("type") == "task_status" and p_data.get("status") in ("done", "failed"):
                                break
                    except Exception:
                        yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError as exc:
            # D16/M5: ein abgebrochener Stream ist ein sichtbares Ereignis,
            # kein stiller DEBUG-Fall.
            logger.info("SSE-Stream wurde abgebrochen: %s", exc)
            raise
        finally:
            try:
                from archon.core.provider_registry import get_provider
                main = get_provider("app_main")
                if hasattr(main, "_SSE_SUBSCRIBERS"):
                    lock = getattr(main, "_SSE_SUB_LOCK", None)
                    if lock is not None:
                        with lock:
                            if q in main._SSE_SUBSCRIBERS:
                                main._SSE_SUBSCRIBERS.remove(q)
                    elif q in main._SSE_SUBSCRIBERS:
                        main._SSE_SUBSCRIBERS.remove(q)
            except Exception as exc:
                logger.debug(f"SSE-Subscriber-Deregistrierung fehlgeschlagen: {exc}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/tasks/{task_id}/chunk")
def api_broadcast_task_chunk(task_id: str, req: TaskChunkBroadcastRequest):
    """Broadcastet ein Token oder Teilergebnis für einen laufenden Task."""
    chunk = req.chunk
    agent_id = req.agent_id or ""
    status = req.status
    try:
        from archon.core.provider_registry import get_provider
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("task_chunk", {"task_id": task_id, "agent_id": agent_id, "chunk": chunk, "status": status})
            if status in ("done", "failed"):
                main.broadcast_event("task_status", {"task_id": task_id, "status": status})
        return {"status": "success", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# BACKUP & INTEGRITY RESTORE TESTS
# =========================================================================

@router.get("/backup/restore-test")
def api_get_restore_test_history():
    """Gibt die Historie der automatisierten Restore- und Integritätstests zurück."""
    try:
        from scripts.automated_restore_test import HISTORY_FILE
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            return {"status": "success", "history": history, "latest": history[0] if history else None}
        return {"status": "success", "history": [], "latest": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backup/restore-test")
def api_trigger_restore_test(request: Request, notify: bool = Query(default=True)):
    """Führt einen On-Demand Restore- und Integritätstest in einer Sandbox aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from scripts.automated_restore_test import restore_tester
        report = restore_tester.run_restore_test(notify=notify)
        return {"status": "success", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# GDPR / DSGVO COMPLIANCE ENGINE
# =========================================================================

@router.post("/gdpr/export")
def api_gdpr_export(request: Request, req: GdprExportRequest):
    """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person über alle Speicherschichten."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    identifier = req.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail={"code": "sysops_identifier_required", "params": {}})
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        res = gdpr_engine.export_subject_data(identifier)
        return {"status": "success", "export": res}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gdpr/erase")
def api_gdpr_erase(request: Request, req: GdprEraseRequest):
    """Art. 17 DSGVO: Löscht/anonymisiert Daten zu einer Person und erzeugt eine kryptografische Quittung."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    identifier = req.identifier.strip()
    dry_run = req.dry_run
    anonymize = req.anonymize
    if not identifier:
        raise HTTPException(status_code=400, detail={"code": "sysops_identifier_required_2", "params": {}})
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        res = gdpr_engine.erase_subject_data(identifier, dry_run=dry_run, anonymize=anonymize)
        return {"status": "success", "result": res}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gdpr/audit-log")
def api_gdpr_audit_log(limit: int = Query(default=50)):
    """Art. 30 DSGVO: Gibt manipulationssichere Löschquittungen aus dem Audit-Log zurück."""
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        receipts = gdpr_engine.list_audit_receipts(limit=limit)
        return {"status": "success", "count": len(receipts), "receipts": receipts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gdpr/vvt")
def api_gdpr_export_vvt(request: Request, fmt: str = Query(default="json")):
    """Art. 30 DSGVO: Exportiert das Verzeichnis von Verarbeitungstätigkeiten (VVT)."""
    require_admin_or_503(request)
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        return {"status": "success", **gdpr_engine.export_processing_register(fmt=fmt)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gdpr/vvt")
def api_gdpr_upsert_vvt(request: Request, req: GdprVvtUpsertRequest):
    """Art. 30 DSGVO: Erstellt oder aktualisiert einen VVT-Eintrag."""
    require_admin_or_503(request)
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        act = gdpr_engine.upsert_processing_activity(req.model_dump(exclude_none=True))
        return {"status": "success", "activity": act}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# CHAOS & RESILIENCE TESTING
# =========================================================================

@router.post("/chaos/run")
def api_chaos_run(request: Request, req: ChaosRunRequest = Body(default=ChaosRunRequest())):
    """Führt automatisierte Chaos- und Resilienz-Tests gegen Container, DB und Watchdog aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    dry_run = req.dry_run
    try:
        sys.path.insert(0, os.path.join(WORKSPACE_DIR, "scripts"))
        from chaos_tester import ArchonChaosTester
        tester = ArchonChaosTester(dry_run=dry_run)
        results = tester.run_all()
        # D10/MED: kein Fake-Erfolg. Ein SLA-Bruch oder Lock-Fehler muss im
        # Status sichtbar sein — sonst bleibt der Produktiv-Gate gruen.
        failed = int(results.get("tests_failed", 0))
        details = results.get("details", {}) or {}
        db_res = details.get("db_concurrency", {}) or {}
        restart_res = details.get("container_restart", {}) or {}
        return {
            # "success" bedeutet hier nur: die Suite lief durch. Der echte
            # Testausstand steht in status/tests_failed/metrics.
            "status": "failed" if failed else "success",
            "chaos_results": results,
            "tests_failed": failed,
            "metrics": {
                "chaos_db_lock_errors": int(db_res.get("errors_count", 0) or 0),
                "chaos_restart_sla_violations": int(bool(restart_res.get("sla_violation"))),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "sysops_chaos_test_failed", "params": {"error": str(e)}})


@router.get("/chaos/results")
def api_chaos_results():
    """Gibt das letzte Ergebnis der Chaos- und Resilienz-Suite zurück."""
    res_file = os.path.join(WORKSPACE_DIR, "data", "chaos_test_results.json")
    if not os.path.exists(res_file):
        raise HTTPException(status_code=404, detail={"code": "sysops_no_chaos_results", "params": {}})
    try:
        with open(res_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {"status": "success", "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

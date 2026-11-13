from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Sub-Router fuer Feedback, Notifications, MCP, Streaming, Backup, GDPR und Chaos-Testing.

Ausgelagert aus backend/operations_api.py.
"""

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =========================================================================
# HUMAN FEEDBACK ENGINE
# =========================================================================

class HumanFeedbackSubmitRequest(BaseModel):
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
def api_update_notification_policy(request: Request, req: Dict[str, Any] = Body(...)):
    """Aktualisiert die Benachrichtigungs- und Ruhezeit-Regeln in settings.json."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        updated = hub.update_policy(req)
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
def api_call_mcp_tool(request: Request, req: Dict[str, Any] = Body(...)):
    """Führt ein Archon MCP-Werkzeug über eine HTTP-REST-Schnittstelle aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        tool_name = req.get("name")
        arguments = req.get("arguments", {})
        if not tool_name:
            raise HTTPException(status_code=400, detail={"code": "sysops_name_required", "params": {}})
        server = ArchonMcpServer()
        result = server.execute_tool(tool_name, arguments)
        return {"status": "success", "result": result}
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
    q = asyncio.Queue(maxsize=50)

    try:
        import main
        if hasattr(main, "_SSE_SUBSCRIBERS"):
            main._SSE_SUBSCRIBERS.append(q)
    except Exception:
        pass

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
        except asyncio.CancelledError:
            pass
        finally:
            try:
                import main
                if hasattr(main, "_SSE_SUBSCRIBERS") and q in main._SSE_SUBSCRIBERS:
                    main._SSE_SUBSCRIBERS.remove(q)
            except Exception:
                pass

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
def api_broadcast_task_chunk(task_id: str, req: Dict[str, Any] = Body(...)):
    """Broadcastet ein Token oder Teilergebnis für einen laufenden Task."""
    chunk = req.get("chunk", "")
    agent_id = req.get("agent_id", "")
    status = req.get("status", "in_progress")
    try:
        import main
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
def api_gdpr_export(request: Request, req: Dict[str, Any] = Body(...)):
    """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person über alle Speicherschichten."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    identifier = req.get("identifier", "").strip()
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
def api_gdpr_erase(request: Request, req: Dict[str, Any] = Body(...)):
    """Art. 17 DSGVO: Löscht/anonymisiert Daten zu einer Person und erzeugt eine kryptografische Quittung."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    identifier = req.get("identifier", "").strip()
    dry_run = bool(req.get("dry_run", False))
    anonymize = bool(req.get("anonymize", True))
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


# =========================================================================
# CHAOS & RESILIENCE TESTING
# =========================================================================

@router.post("/chaos/run")
def api_chaos_run(request: Request, req: Dict[str, Any] = Body(default={})):
    """Führt automatisierte Chaos- und Resilienz-Tests gegen Container, DB und Watchdog aus."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    dry_run = bool(req.get("dry_run", True))
    try:
        sys.path.insert(0, os.path.join(WORKSPACE_DIR, "scripts"))
        from chaos_tester import ArchonChaosTester
        tester = ArchonChaosTester(dry_run=dry_run)
        results = tester.run_all()
        return {"status": "success", "chaos_results": results}
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

"""Router fuer Resilienz: Snapshots, Audit-Log, Fleet-Healing, Notifications, Traces & Self-Healing."""
from __future__ import annotations

import logging
from typing import Dict

from fastapi import APIRouter, Body, Request

logger = logging.getLogger("archon.routers.resilience")

router = APIRouter(tags=["resilience"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def _require_admin_or_503(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin_or_503"):
        app_main.require_admin_or_503(request)


# --- SNAPSHOTS ---


@router.get("/api/snapshots")
def api_list_snapshots(limit: int = 50):
    from backend.snapshot_manager import snapshot_manager

    return {"status": "success", "snapshots": snapshot_manager.list_snapshots(limit=limit)}


@router.post("/api/snapshots/{snapshot_id}/restore")
def api_restore_snapshot(request: Request, snapshot_id: str):
    _require_admin(request)
    from backend.snapshot_manager import snapshot_manager

    return snapshot_manager.restore_snapshot(snapshot_id)


# --- AUDIT LOG ---


@router.get("/api/audit/logs")
def api_list_audit_logs(limit: int = 50):
    from backend.audit_log import chained_audit_log

    return {"status": "success", "logs": chained_audit_log.list_events(limit=limit)}


@router.get("/api/audit/verify")
def api_verify_audit_log():
    from backend.audit_log import chained_audit_log

    return chained_audit_log.verify_integrity()


# --- FLEET SELF-HEALING ---


@router.post("/api/fleet/heal/{service_name}")
def api_heal_service(request: Request, service_name: str):
    _require_admin(request)
    from backend.fleet_self_healing import restart_service_container

    return restart_service_container(service_name)


@router.get("/api/fleet/health-check")
def api_fleet_health_check():
    from backend.fleet_self_healing import check_fleet_and_heal

    return check_fleet_and_heal()


# --- NOTIFICATION HUB ---


@router.post("/api/notifications/dispatch")
def api_dispatch_notification(payload: Dict = Body(...)):
    from backend.notification_hub import notification_hub

    return notification_hub.dispatch_notification(
        title=payload.get("title", "System-Benachrichtigung"),
        message=payload.get("message", ""),
        severity=payload.get("severity", "INFO"),
        category=payload.get("category", "system"),
    )


@router.get("/api/notifications/recent")
def api_list_recent_notifications(limit: int = 50):
    from backend.notification_hub import notification_hub

    return {"status": "success", "notifications": notification_hub.list_recent(limit=limit)}


# --- TIME-TRAVEL DEBUGGER & TRACES ---


@router.get("/api/traces/{task_id}")
def api_get_task_trace(task_id: str):
    from backend.time_travel_debugger import time_travel_debugger

    return {
        "status": "success",
        "task_id": task_id,
        "trace": time_travel_debugger.get_task_trace(task_id),
    }


@router.post("/api/traces/{task_id}/fork")
def api_fork_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger

    return time_travel_debugger.fork_execution(
        task_id=task_id,
        from_step=int(payload.get("from_step", 1)),
        new_prompt=payload.get("new_prompt"),
        new_model=payload.get("new_model"),
    )


@router.post("/api/traces/{task_id}/rollback")
def api_rollback_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger

    return time_travel_debugger.rollback_to_step(
        task_id=task_id,
        to_step=int(payload.get("to_step", 0)),
    )


# --- TASK SELF-HEALING ---


@router.get("/api/healing/logs")
def api_get_healing_logs(limit: int = 25):
    from backend.task_self_healer import task_self_healer

    return {"status": "success", "logs": task_self_healer.get_healing_logs(limit=limit)}

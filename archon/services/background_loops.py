"""Hintergrund-Loops, Task-Registry & Shutdown-Abbruch (M1 aus main.py).

Reine Extraktion nach dem S3-Muster (Call-Time-Dependency-Injection ueber
``register_background_loop_deps_provider``):
* Kein Rueckimport auf ``main``.
* Alle Listen/Locks (``_BACKGROUND_TASKS``, ``_FAILED_CANCELS``,
  ``_WATCHDOG_STOP_FAILED``, ``_STARTUP_RECOVERY_FAILED``,
  ``_DB_MAINTENANCE_STATUS``, ``_RAG_SYNC_LOCK``, ``_ANCHOR_WRITE_LOCK``)
  werden in ``main.py`` als identische Objekte re-exportiert.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from backend.process_lock import exclusive_loop as _exclusive_loop

logger = logging.getLogger("archon_os")

_LOOPS_STARTED: bool = False

_BACKGROUND_TASKS: List[asyncio.Task[Any]] = []
_RAG_SYNC_LOCK = asyncio.Lock()

# D07/MED: fehlgeschlagene Abbrueche duerfen nicht als Erfolg quittiert werden.
_FAILED_CANCELS: List[Dict[str, Any]] = []
_WATCHDOG_STOP_FAILED: List[Dict[str, Any]] = []
_STARTUP_RECOVERY_FAILED: List[Dict[str, Any]] = []

# D08/MED: Audit-Schreibpfade im 30-s-Loop laufen im Thread + Lock.
_ANCHOR_WRITE_LOCK = threading.Lock()

# A3-DELEGATED: DB-Wartungsstatus fuer /readyz.
_DB_MAINTENANCE_STATUS: Dict[str, Any] = {"status": "not_started", "error": None, "ts": 0.0}


class BackgroundLoopDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus main.py."""

    load_mission_control_data: Callable[..., Any]
    update_mission_control_data: Callable[..., Any]
    mc_async_lock: Any
    run_synthesis_cascade: Callable[..., Any]
    orch_fan_in_maybe_start_synthesis: Callable[..., Any]
    verify_all_audit_chains: Callable[[], Dict[str, Dict[str, Any]]]
    mark_audit_compromised: Callable[[str, Dict[str, Any]], None]
    get_service_token: Callable[[], str]
    get_rag_sync_process: Callable[[], Any]
    set_rag_sync_process: Callable[[Any], None]
    gateway_idle_stop_loop: Callable[[], Any]


_DEPS_PROVIDER: Optional[Callable[[], BackgroundLoopDeps]] = None


def register_background_loop_deps_provider(provider: Callable[[], BackgroundLoopDeps]) -> None:
    """Registriert den Call-Time-Resolver fuer main.py (S3-Muster)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _resolve_deps() -> BackgroundLoopDeps:
    if _DEPS_PROVIDER is None:
        raise RuntimeError("BackgroundLoopDeps provider nicht registriert")
    return _DEPS_PROVIDER()


def reset_loops_started() -> None:
    """Setzt den In-Process-Restart-Guard beim Shutdown zurueck."""
    global _LOOPS_STARTED
    _LOOPS_STARTED = False


@_exclusive_loop("email_imap")
async def _email_imap_background_loop() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            from backend.email_service import sync_imap_inbox

            await asyncio.to_thread(sync_imap_inbox, limit=20)
        except Exception as e:
            logger.warning("[EmailService] Background sync error: %s", e)
        await asyncio.sleep(180)


def _record_failed_cancel(task_name: str, detail: str) -> None:
    """Persistiert einen gescheiterten cancel() inkl. Audit (best effort)."""
    entry = {"task": str(task_name), "detail": str(detail), "ts": time.time()}
    _FAILED_CANCELS.append(entry)
    logger.error("[Shutdown] Cancel fehlgeschlagen: %s — %s", task_name, detail)
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(
            category="recovery",
            action="cancel_failed",
            agent_id="system",
            payload=entry,
        )
    except Exception as audit_exc:
        logger.warning("[Shutdown] Cancel-Fehler nicht auditierbar: %s", audit_exc)


def _spawn_background(coro: Any, name: str = "", priority: int = 1) -> Optional[asyncio.Task[Any]]:
    """Startet einen Background-Task, registriert ihn fuer Shutdown und loggt unhandled exceptions."""
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as _coord

    allowed, reason = _coord.can_start_task(name or "background", priority=priority)
    if not allowed:
        logger.warning("[BackgroundTask] Start verweigert (%s): %s", name or "background", reason)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None
    task: asyncio.Task[Any] = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _BACKGROUND_TASKS.append(task)

    def _done_cb(t: asyncio.Task[Any]) -> None:
        try:
            _BACKGROUND_TASKS.remove(t)
        except ValueError as rm_exc:
            logger.debug(f"[BackgroundTask] Task {t.get_name()} bereits aus Registry entfernt: {rm_exc}")
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.error(f"[BackgroundTask] Unhandled exception in {t.get_name()}: {exc}", exc_info=exc)

    task.add_done_callback(_done_cb)
    return task


@_exclusive_loop("deadlock_supervisor")
async def _deadlock_supervisor_loop() -> None:
    """30-Sekunden Watchdog/Deadlock-Loop (Pillar 1): befreit stagnierende Kanban-Tasks."""
    await asyncio.sleep(15)
    while True:
        deps = _resolve_deps()
        try:
            from backend.deadlock_supervisor import deadlock_supervisor

            res = await asyncio.to_thread(deadlock_supervisor.detect_and_resolve_deadlocks)
            if isinstance(res, dict) and res.get("resolved_count", 0) > 0:
                logger.warning(f"[DeadlockSupervisor] {res['resolved_count']} blockierte(r) Task(s) reaktiviert.")
        except Exception as e:
            logger.debug(f"[DeadlockSupervisor] Loop-Hinweis: {e}")

        try:
            from archon.core.orchestration import recover_stale_synthesis
            from archon.core.task_registry import spawn as _tracked_spawn

            stale = await asyncio.to_thread(  # type: ignore[call-arg]
                recover_stale_synthesis,
                deps.load_mission_control_data,
                deps.update_mission_control_data,
                900,
                lambda pid: _tracked_spawn(
                    deps.orch_fan_in_maybe_start_synthesis(
                        pid,
                        mc_async_lock=deps.mc_async_lock,
                        run_cascade=deps.run_synthesis_cascade,
                    ),
                    name=f"synthesis_restart:{pid}",
                ),
            )
            if stale:
                logger.warning("[Synthese-Recovery] %s Kaskade(n) neu gestartet.", len(stale))
        except Exception as e:
            logger.debug(f"[Synthese-Recovery] Loop-Hinweis: {e}")

        try:
            from backend.metrics_collector import check_and_dispatch_alerts_now

            alerts = await asyncio.to_thread(check_and_dispatch_alerts_now)
            if isinstance(alerts, dict) and alerts.get("dispatched"):
                logger.info("[Alerting] %s Alarm(e) versendet.", alerts["dispatched"])
        except Exception as e:
            logger.debug(f"[Alerting] Loop-Hinweis: {e}")

        try:
            from backend.resource_backpressure import resource_backpressure_protector

            bp = await asyncio.to_thread(
                resource_backpressure_protector.check_health_and_backpressure
            )
            if isinstance(bp, dict) and bp.get("disk_critical"):
                logger.error("[Backpressure] Disk kritisch: %s", bp)
        except Exception as e:
            logger.error(f"[Backpressure] Periodischer Check fehlgeschlagen: {e}")

        try:
            results = await asyncio.to_thread(deps.verify_all_audit_chains)
            for label, audit_res in results.items():
                if isinstance(audit_res, dict) and audit_res.get("valid") is False:
                    deps.mark_audit_compromised(label, audit_res)
        except Exception as e:
            logger.error(f"[Integritaet] Kettenverifikation nicht pruefbar: {e}")
            deps.mark_audit_compromised(
                "Kettenverifikation", {"valid": False, "reason": str(e)}
            )

        def _write_chain_anchors() -> Dict[str, Any]:
            from backend.audit_log import anchor_secondary_chains

            with _ANCHOR_WRITE_LOCK:
                return anchor_secondary_chains()

        try:
            anchors = await asyncio.to_thread(_write_chain_anchors)
            failed = [
                k
                for k, v in anchors.items()
                if isinstance(v, dict)
                and v.get("written") is False
                and ("error" in v or v.get("violation") is True)
            ]
            if failed:
                logger.error("[Integritaet] Head-Anker fehlgeschlagen: %s", failed)
                violations = [k for k in failed if anchors[k].get("violation") is True]
                if violations:
                    deps.mark_audit_compromised(
                        "Head-Anker",
                        {"valid": False, "reason": f"Tail-Loeschung/Rollback: {violations}"},
                    )
        except Exception as e:
            logger.error(f"[Integritaet] Head-Anker-Loop fehlgeschlagen: {e}")

        try:
            from backend.approval_policy_engine import approval_engine as _approval_timeout

            escalated = await asyncio.to_thread(_approval_timeout.check_and_escalate_timeouts)
            if escalated:
                logger.warning("[Approval] %s Freigabe(n) automatisch eskaliert.", escalated)
        except Exception as e:
            logger.error(f"[Approval] Timeout-Eskalation fehlgeschlagen: {e}")

        await asyncio.sleep(30)


@_exclusive_loop("db_maintenance")
async def _db_maintenance_loop() -> None:
    """Periodische DB-Sicherung & Optimierung (WAL-Truncate, Backup, VACUUM alle 6h)."""
    await asyncio.sleep(120)
    while True:
        try:
            from backend.db_backup_manager import db_backup_manager
            from backend.db_optimizer import optimize_all_databases

            await asyncio.to_thread(db_backup_manager.checkpoint_and_backup)
            result = await asyncio.to_thread(optimize_all_databases)
            _DB_MAINTENANCE_STATUS.update(
                status="error" if isinstance(result, dict) and result.get("status") == "error" else "ok",
                error=(result or {}).get("error") if isinstance(result, dict) else None,
                ts=time.time(),
            )
            if _DB_MAINTENANCE_STATUS["status"] == "error":
                logger.error("[DBMaintenance] Optimierung fehlgeschlagen: %s", _DB_MAINTENANCE_STATUS["error"])
        except Exception as e:
            _DB_MAINTENANCE_STATUS.update(status="error", error=str(e), ts=time.time())
            logger.error("[DBMaintenance] Loop fehlgeschlagen: %s", e)
        await asyncio.sleep(21600)


@_exclusive_loop("fleet_self_healing")
async def _fleet_self_healing_loop() -> None:
    """C13: Core-Dienste periodisch pruefen und ausgefallene Container neu starten."""
    await asyncio.sleep(45)
    while True:
        try:
            from backend.fleet_self_healing import check_fleet_and_heal

            res = await asyncio.to_thread(check_fleet_and_heal)
            if isinstance(res, dict) and res.get("status") == "ok":
                missing = res.get("missing_services") or []
                if missing or res.get("healed_count", 0):
                    logger.warning(
                        "[FleetSelfHealing] vermisst/unhealthy=%s, geheilt=%s, übersprungen=%s",
                        missing,
                        res.get("healed_count", 0),
                        res.get("skipped_not_deployed") or [],
                    )
            elif isinstance(res, dict):
                logger.debug("[FleetSelfHealing] Loop-Hinweis: %s", res.get("error"))
        except Exception as e:
            logger.debug(f"[FleetSelfHealing] Loop-Hinweis: {e}")
        await asyncio.sleep(120)


async def _start_gateway_idle_loop() -> None:
    """Alle Hintergrund-Loops genau einmal starten."""
    global _LOOPS_STARTED
    if _LOOPS_STARTED:
        logger.warning("[Startup] Hintergrund-Loops laufen bereits — kein zweiter Start.")
        return
    _LOOPS_STARTED = True
    deps = _resolve_deps()
    _spawn_background(deps.gateway_idle_stop_loop())
    _spawn_background(_email_imap_background_loop())
    _spawn_background(_deadlock_supervisor_loop(), name="deadlock_supervisor_30s")
    _spawn_background(_fleet_self_healing_loop(), name="fleet_self_healing_120s")
    _spawn_background(_db_maintenance_loop(), name="db_maintenance_6h")
    try:
        from archon.core.delegation import resume_pending_delegation_watchers

        _spawn_background(resume_pending_delegation_watchers(), name="delegation_watcher_recovery")
    except Exception as e:
        logger.debug(f"[Startup] Delegation-Watcher-Recovery Hinweis: {e}")
    try:
        from backend.inbox_watcher import inbox_watcher_background_loop

        _spawn_background(inbox_watcher_background_loop())
    except Exception as e:
        print(f"[Startup] Inbox Watcher init notice: {e}")
    try:
        from backend.internet_watchdog import internet_watchdog_background_loop

        _spawn_background(internet_watchdog_background_loop())
    except Exception as e:
        print(f"[Startup] Internet Watchdog init notice: {e}")
    try:
        from backend.workflow_scheduler import workflow_scheduler_background_loop

        _spawn_background(workflow_scheduler_background_loop())
    except Exception as e:
        print(f"[Startup] Workflow Scheduler init notice: {e}")
    try:
        from backend.auth_service import auth_service as _auth_svc

        deps = _resolve_deps()
        if _auth_svc.is_auth_enabled() and not deps.get_service_token():
            logger.critical(
                "[Auth] Auth ist aktiv, aber kein ARCHON_SERVICE_TOKEN konfiguriert — "
                "interne Automaten (n8n, Adapter) werden mit 401 abgewiesen."
            )
    except Exception as e:
        logger.debug(f"[Startup] Auth-Token-Pruefung Hinweis: {e}")


async def _cancel_background_tasks() -> None:
    """Bricht die Endlos-Loops ab (inkl. RAG-Sync-Subprocess-Terminate)."""
    deps = _resolve_deps()
    _rag_proc = deps.get_rag_sync_process()
    if _rag_proc is not None and _rag_proc.poll() is None:
        try:
            logger.info("[Shutdown] RAG-Sync-Subprocess wird beendet.")
            _rag_proc.terminate()
            try:
                _rag_proc.wait(timeout=5.0)
            except Exception:
                _rag_proc.kill()
                try:
                    _rag_proc.wait(timeout=5.0)
                except Exception:
                    logger.warning(
                        "[Shutdown] RAG-Sync bleibt nach kill() unresponsive "
                        "(Zombie-Risiko)."
                    )
        except Exception as exc:
            logger.warning("[Shutdown] RAG-Sync konnte nicht beendet werden: %s", exc)
    deps.set_rag_sync_process(None)

    pending = [t for t in _BACKGROUND_TASKS if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        results = None
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning("[Shutdown] %s Task(s) reagierten nicht binnen 10s.", len(pending))
            for task in pending:
                if not task.done():
                    _record_failed_cancel(
                        task.get_name(), "timeout_after_cancel(10s): task_possibly_alive"
                    )
        if results is not None:
            for task, result in zip(pending, results):
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, BaseException):
                    _record_failed_cancel(task.get_name(), f"{type(result).__name__}: {result}")
        confirmed = sum(1 for t in pending if t.cancelled())
        print(
            f"[Shutdown] {confirmed}/{len(pending)} Hintergrund-Task(s) verifiziert abgebrochen; "
            f"{len(_FAILED_CANCELS)} fehlgeschlagene Abbruch(e) insgesamt."
        )
    _BACKGROUND_TASKS[:] = [t for t in _BACKGROUND_TASKS if not t.done()]

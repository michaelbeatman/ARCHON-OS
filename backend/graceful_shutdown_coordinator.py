"""
backend/graceful_shutdown_coordinator.py
Sauberes Herunterfahren mit Task-Draining & Durable Checkpointing (t-12113b, Pillar 1 & 2).
- Verwaltet Draining-Zustand des Systems (RUNNING -> DRAINING -> CHECKPOINTING -> FLUSHING_WAL -> TERMINATED).
- Verhindert neue Hintergrund-Jobs während des Draining-Fensters.
- Lässt aktive Kurzläufer innerhalb einer Grace-Period (Standard: 5s, D10-M7) geordnet auslaufen.
- Sichert noch laufende Langläufer als transaktionale Checkpoints in SQLite (`durable_workflow_checkpoints`).
- Flusht alle SQLite WAL-Logs (`PRAGMA wal_checkpoint(TRUNCATE)`) und den Async-Write-Batcher vor dem Exit.
- Stellt unterbrochene Tasks beim Systemstart automatisch wieder her.
"""

import asyncio
import datetime
import logging
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _audit_recovery(action: str, payload: "Dict[str, Any]") -> None:
    """Audit-Event best effort — ein Write-Fehler darf nicht erneut verschluckt werden."""
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(
            category="recovery",
            action=action,
            agent_id="system",
            payload=payload,
        )
    except Exception as exc:
        logger.error("[GracefulShutdown] Audit '%s' fehlgeschlagen: %s", action, exc)


def _hitl_escalate(title: str, detail: str) -> None:
    try:
        from backend.event_mesh import event_mesh

        event_mesh.ingest_inbound_event("system", "hitl_required", {"title": title, "detail": detail, "source": "recovery"})
    except Exception as exc:
        logger.error("[GracefulShutdown] HITL-Eskalation fehlgeschlagen: %s", exc)


class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# D10-M7: das Drain-Fenster und die beiden Folgephasen dürfen den
# Lifespan-Shutdown nicht unbegrenzt blockieren (früher 15 s Drain ohne
# Phase-Limit). Die Phasen laufen in to_thread; wait_for begrenzt nur das
# Warten, nicht den Worker-Thread — der Shutdown macht aber weiter.
_MAX_DRAIN_GRACE_SECONDS = 5.0
_SHUTDOWN_PHASE_TIMEOUT_SECONDS = 5.0


class GracefulShutdownCoordinator:
    def __init__(self):
        self._is_draining = False
        self._draining_reason = ""
        self._draining_started_at: Optional[float] = None
        self._default_grace_seconds = _MAX_DRAIN_GRACE_SECONDS
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock() if sys.version_info >= (3, 7) else None
        # D07/MED: gescheiterte Checkpoints/Resumes bleiben nachvollziehbar.
        self.failed_checkpoints: List[str] = []
        self.failed_resumes: List[Dict[str, Any]] = []

    @property
    def is_draining(self) -> bool:
        return self._is_draining

    def start_draining(self, reason: str = "System shutdown / update", grace_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Aktiviert den Draining-Modus. Neue Tasks werden ab jetzt abgewiesen."""
        self._is_draining = True
        self._draining_reason = reason
        self._draining_started_at = time.time()
        if grace_seconds is not None:
            requested = float(grace_seconds)
            # D10-M7: AUC ein explizit uebergebenes Fenster darf die Obergrenze
            # nicht durchbrechen (sonst waere der Lifespan wieder 60 s blockiert).
            self._default_grace_seconds = min(requested, _MAX_DRAIN_GRACE_SECONDS)
            if requested > _MAX_DRAIN_GRACE_SECONDS:
                logger.warning(
                    "[GracefulShutdown] Grace-Period %.1fs auf %.1fs begrenzt (D10-M7).",
                    requested, _MAX_DRAIN_GRACE_SECONDS,
                )

        print(f"[GracefulShutdown] Draining aktiviert: '{reason}' (Grace-Period: {self._default_grace_seconds}s)")
        return {
            "status": "draining",
            "reason": self._draining_reason,
            "active_tasks_count": len(self._active_tasks),
            "grace_seconds": self._default_grace_seconds,
            "started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def cancel_draining(self) -> Dict[str, Any]:
        """Bricht das Draining ab (z. B. falls ein Update-Vorgang vorzeitig gestoppt wurde)."""
        self._is_draining = False
        self._draining_reason = ""
        self._draining_started_at = None
        print("[GracefulShutdown] Draining abgebrochen. System läuft normal weiter.")
        return {"status": "running", "is_draining": False}

    def can_start_task(self, task_id: str, priority: int = 1) -> Tuple[bool, str]:
        """Prüft, ob eine neue Aufgabe angenommen werden darf."""
        if not self._is_draining:
            return True, "OK"
        # Notfall-Prio 3 Chats dürfen passieren, Hintergrund-Workflows (P1/P2) werden blockiert
        if priority >= 3:
            return True, "Allowed (Emergency Priority)"
        return False, f"Server fährt herunter oder führt ein Update durch ({self._draining_reason})"

    def register_task(
        self,
        task_id: str,
        title: str,
        agent_name: str = "system",
        total_steps: int = 1,
        current_step: int = 0,
        state_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Registriert eine laufende Hintergrundaufgabe."""
        self._active_tasks[task_id] = {
            "task_id": task_id,
            "title": title,
            "agent_name": agent_name,
            "started_at": time.time(),
            "total_steps": total_steps,
            "current_step": current_step,
            "state_payload": state_payload or {},
            "status": "in_progress"
        }

    def update_task_progress(
        self,
        task_id: str,
        current_step: int,
        state_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Aktualisiert Schritt und State einer laufenden Aufgabe."""
        if task_id in self._active_tasks:
            self._active_tasks[task_id]["current_step"] = current_step
            if state_payload is not None:
                self._active_tasks[task_id]["state_payload"] = state_payload

    def unregister_task(self, task_id: str) -> None:
        """Meldet eine abgeschlossene oder abgebrochene Aufgabe ab."""
        self._active_tasks.pop(task_id, None)

    def get_status(self) -> Dict[str, Any]:
        """Liefert den aktuellen Draining- und Task-Status."""
        elapsed = (time.time() - self._draining_started_at) if self._draining_started_at else 0.0
        return {
            "is_draining": self._is_draining,
            "reason": self._draining_reason,
            "elapsed_draining_seconds": round(elapsed, 1),
            "grace_period_seconds": self._default_grace_seconds,
            "active_tasks_count": len(self._active_tasks),
            "active_tasks": list(self._active_tasks.values())
        }

    def drain_active_tasks_sync(self, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Synchrone Variante für Threading, atexit und Signal-Handler.
        Wartet bis zu timeout_seconds, ob laufende Aufgaben von selbst enden.
        """
        timeout = timeout_seconds if timeout_seconds is not None else self._default_grace_seconds
        start = time.time()
        initial_count = len(self._active_tasks)

        print(f"[GracefulShutdown] Task-Draining gestartet ({initial_count} aktive Aufgaben, Timeout {timeout}s)...")
        while len(self._active_tasks) > 0 and (time.time() - start) < timeout:
            time.sleep(0.1)

        remaining = len(self._active_tasks)
        completed = initial_count - remaining
        print(f"[GracefulShutdown] Draining beendet: {completed} abgeschlossen, {remaining} verbleibend.")
        return {
            "initial_tasks": initial_count,
            "completed_during_grace": completed,
            "remaining_for_checkpoint": remaining,
            "time_spent_seconds": round(time.time() - start, 2)
        }

    async def drain_active_tasks(self, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Asynchrone Variante für FastAPI Lifespan Events. Blockiert den Event-Loop nicht."""
        timeout = timeout_seconds if timeout_seconds is not None else self._default_grace_seconds
        start = time.time()
        initial_count = len(self._active_tasks)

        print(f"[GracefulShutdown] Task-Draining gestartet ({initial_count} aktive Aufgaben, Timeout {timeout}s)...")
        while len(self._active_tasks) > 0 and (time.time() - start) < timeout:
            await asyncio.sleep(0.1)

        remaining = len(self._active_tasks)
        completed = initial_count - remaining
        print(f"[GracefulShutdown] Draining beendet: {completed} abgeschlossen, {remaining} verbleibend.")
        return {
            "initial_tasks": initial_count,
            "completed_during_grace": completed,
            "remaining_for_checkpoint": remaining,
            "time_spent_seconds": round(time.time() - start, 2)
        }

    def checkpoint_remaining_tasks(self) -> List[Dict[str, Any]]:
        """
        Sichert alle Aufgaben, die das Draining-Fenster nicht geschafft haben,
        als transaktionale Checkpoints in SQLite und markiert sie als 'checkpointed'.
        """
        if not self._active_tasks:
            return []

        checkpoints: List[Dict[str, Any]] = []
        failed: List[str] = []
        try:
            from backend.durable_checkpoint_manager import durable_checkpoint_manager
            has_mgr = True
        except Exception as exc:
            has_mgr = False
            print(f"[GracefulShutdown] Checkpoint-Manager nicht verfuegbar: {exc}", file=sys.stderr)

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for tid, tinfo in list(self._active_tasks.items()):
            if not has_mgr:
                failed.append(tid)
                continue
            title = tinfo.get("title", f"Task {tid}")
            cur_step = tinfo.get("current_step", 0)
            total_steps = tinfo.get("total_steps", 1)
            state = tinfo.get("state_payload", {})

            # 1. In durable_checkpoint_manager eintragen. Nur bei Erfolg darf
            # der Task als 'checkpointed' gelten (Audit C12: vorher wurde ein
            # Checkpoint-Fehler nur gedruckt und die Registry trotzdem geleert).
            # D07/MED: save_checkpoint() liefert bei deaktiviertem Modul
            # {"saved": False, "bypassed": True} OHNE Exception — der
            # Rueckgabewert muss ausgewertet werden, sonst entsteht ein
            # 'checkpointed'-Task ohne Resume-Payload.
            try:
                cp_res = durable_checkpoint_manager.save_checkpoint(
                    workflow_id=tid,
                    task_title=title,
                    current_step_index=cur_step,
                    total_steps=total_steps,
                    state_payload=state,
                    status="checkpointed"
                )
            except Exception as e:
                logger.error("[GracefulShutdown] Fehler beim Checkpointing von %s: %s", tid, e)
                failed.append(tid)
                _audit_recovery("checkpoint_write_failed", {"task_id": tid, "error": str(e)})
                continue
            if not isinstance(cp_res, dict) or cp_res.get("saved") is not True:
                reason = "checkpoint_bypassed" if (cp_res or {}).get("bypassed") else "checkpoint_not_saved"
                logger.error(
                    "[GracefulShutdown] Task %s NICHT checkpointed (%s): %s",
                    tid, reason, cp_res,
                )
                failed.append(tid)
                _audit_recovery("checkpoint_bypassed", {
                    "task_id": tid, "reason": reason, "result": cp_res,
                })
                _hitl_escalate("Checkpoint nicht gespeichert", f"Task {tid}: {reason}")
                continue

            # 2. In kanban.db oder agent_os.db Status von 'in_progress' auf 'checkpointed' setzen
            self._update_task_db_status(tid, "checkpointed", f"Automatisch pausiert vor System-Shutdown ({now_iso})")

            checkpoints.append({
                "task_id": tid,
                "title": title,
                "step": cur_step,
                "total": total_steps,
                "status": "checkpointed"
            })

        # Nur tatsaechlich gesicherte Tasks aus der Registry entfernen.
        for cp in checkpoints:
            self._active_tasks.pop(cp["task_id"], None)
        self.failed_checkpoints = list(failed)
        if failed:
            logger.error(
                "[GracefulShutdown] %s Aufgaben konnten NICHT gesichert werden "
                "und bleiben in der Registry: %s", len(failed), failed,
            )
            print(
                f"[GracefulShutdown] {len(failed)} Aufgaben konnten NICHT gesichert werden "
                f"und bleiben in der Registry: {failed}",
                file=sys.stderr,
            )
        print(f"[GracefulShutdown] {len(checkpoints)} verbleibende Aufgaben erfolgreich als Checkpoint gesichert.")
        return checkpoints

    @staticmethod
    def _known_db_paths(filenames: List[str]) -> List[str]:
        candidates: List[str] = []
        # Explizite Workspace-Pfade zuerst: sie sind konfigurierbar und in
        # Tests mockbar. resolve_db() ergaenzt nur (frueher kamen dessen Pfade
        # zuerst und ueberschrieben den gemockten Workspace-Pfad).
        for fname in filenames:
            if fname == "agent_os.db":
                candidates.append(os.path.join(WORKSPACE_DIR, fname))
            else:
                candidates.append(os.path.join(WORKSPACE_DIR, "data", fname))
        # resolve_db() nur als Ergaenzung, wenn der explizite Pfad nicht
        # existiert. Sonst werden in Tests/isolierten Workspaces fremde DBs
        # geoeffnet (und auf Windows das Temp-Verzeichnis blockiert).
        explicit = set(candidates)
        try:
            from backend.db_paths import resolve_db
            for fname in filenames:
                resolved = os.path.abspath(resolve_db(fname))
                if resolved not in explicit:
                    candidates.append(resolved)
        except Exception as exc:
            print(f"[GracefulShutdown] Warnung: resolve_db nicht verfuegbar, Fallback auf Workspace-DB-Pfade: {exc}", file=sys.stderr)
        seen = set()
        ordered: List[str] = []
        for p in candidates:
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                ordered.append(ap)
        return ordered

    def _update_task_db_status(
        self, task_id: str, new_status: str, note: str = "",
        db_path: Optional[str] = None,
    ):
        """Setzt den Task-Status in den bekannten SQLite-Tasktabellen.

        ``db_path`` erlaubt explizite Dependency Injection (Tests, isolation),
        ohne globale Pfade mocken oder fremde DBs oeffnen zu muessen.
        """
        db_paths = [db_path] if db_path else self._known_db_paths(
            ["kanban.db", "state.db", "agent_os.db"]
        )
        for dbp in db_paths:
            if os.path.exists(dbp):
                try:
                    with sqlite3.connect(dbp, timeout=2.0, factory=_ArchonClosingConn) as conn:
                        # N-07: 'tasks' hat KEINE Spalte 'updated_at' (pragma
                        # table_info(tasks) -> 0 Treffer). Das SET auf die
                        # fehlende Spalte warf OperationalError, wurde geschluckt
                        # und der Task nie als 'checkpointed' markiert.
                        conn.execute(
                            "UPDATE tasks SET status = ? WHERE id = ?",
                            (new_status, task_id)
                        )
                        conn.commit()
                except Exception as exc:
                    print(f"[GracefulShutdown] Warnung: Task {task_id} konnte nicht als '{new_status}' markiert werden: {exc}", file=sys.stderr)

    def flush_all_databases(self) -> Dict[str, Any]:
        """
        Leert den Async-Write-Batcher und führt PRAGMA wal_checkpoint(PASSIVE)
        auf allen relevanten SQLite-Datenbanken aus, um Datenverlust zu verhindern.
        """
        flushed_dbs = []
        errors = []

        # 1. Async Write Batcher leeren
        # N-03: das Modul exportiert die Singleton-INSTANZ (async_write_batcher),
        # keinen get_write_batcher()-Factory. Der ImportError wurde vorher vom
        # blanket-except geschluckt — der RAM-Puffer blieb liegen, das Log
        # meldete trotzdem "WAL-Flush abgeschlossen".
        try:
            from backend.async_write_batcher import async_write_batcher as write_batcher
            flush_info = write_batcher.flush()
            if isinstance(flush_info, dict) and flush_info.get("status") == "error":
                msg = f"Batcher-Flush meldet Fehler: {flush_info}"
                errors.append(msg)
                print(f"[GracefulShutdown] {msg}", file=sys.stderr)
            else:
                flushed_dbs.append("async_write_batcher_ram_queue")
        except Exception as e:
            errors.append(f"Batcher-Flush fehlgeschlagen: {e}")
            print(f"[GracefulShutdown] Batcher-Flush fehlgeschlagen: {e}", file=sys.stderr)

        # 2. Alle SQLite-Datenbanken über zentrale DB-SSOT einsammeln
        candidate_paths = self._known_db_paths([
            "agent_os.db",
            "agentic_memory.db",
            "contracts.db",
            "kanban.db",
            "state.db",
            "hybrid_search.db",
        ])

        for db_file in candidate_paths:
            if os.path.isfile(db_file):
                try:
                    with sqlite3.connect(db_file, timeout=2.0, factory=_ArchonClosingConn) as conn:
                        cur = conn.cursor()
                        # PASSIVE checkpoint: schreibt unblockiert alle ungelockten Pages
                        cur.execute("PRAGMA wal_checkpoint(PASSIVE);")
                        flushed_dbs.append(os.path.basename(db_file))
                except Exception as e:
                    errors.append(f"WAL-Flush {db_file} fehlgeschlagen: {e}")
                    print(f"[GracefulShutdown] Fehler beim WAL-Flush für {db_file}: {e}", file=sys.stderr)

        # Audit 23.11.2026: frueher wurde unbedingt 'success' zurueckgegeben,
        # auch wenn ALLE Flushes fehlgeschlagen sind (stiller Datenverlust +
        # falsche Shutdown-Bestaetigung). Jetzt statusgenau melden.
        if not errors:
            status = "success"
        elif flushed_dbs:
            status = "partial"
        else:
            status = "error"
        print(
            f"[GracefulShutdown] WAL-Flush {status} "
            f"({len(flushed_dbs)} Speicherpunkte konsolidiert, {len(errors)} Fehler)."
        )
        return {"status": status, "flushed_databases": flushed_dbs, "errors": errors}

    def execute_graceful_shutdown_sync(self, reason: str = "Server shutdown", grace_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Synchrone Komplett-Orchestrierung für atexit / Signal Handler."""
        self.start_draining(reason=reason, grace_seconds=grace_seconds)
        drain_result = self.drain_active_tasks_sync(timeout_seconds=grace_seconds)
        checkpoints = self.checkpoint_remaining_tasks()
        flush_result = self.flush_all_databases()

        return {
            "status": "shutdown_ready",
            "reason": reason,
            "draining": drain_result,
            "checkpoints_created": checkpoints,
            "wal_flush": flush_result
        }

    async def execute_graceful_shutdown(self, reason: str = "Server shutdown", grace_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Vollständige asynchrone Orchestrierung: Draining -> Grace Wait -> Checkpointing -> WAL-Flush.

        D10-M7: jede Phase hat ein eigenes Zeitfenster (Drain <= 5 s,
        Checkpoint/WAL-Flush je <= 5 s) und meldet einen Timeout als Audit,
        statt den Lifespan-Shutdown zu blockieren.
        """
        self.start_draining(reason=reason, grace_seconds=grace_seconds)
        drain_result = await asyncio.wait_for(
            self.drain_active_tasks(timeout_seconds=self._default_grace_seconds),
            timeout=_MAX_DRAIN_GRACE_SECONDS + 0.5,
        )

        try:
            checkpoints = await asyncio.wait_for(
                asyncio.to_thread(self.checkpoint_remaining_tasks),
                timeout=_SHUTDOWN_PHASE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            checkpoints = []
            logger.error("[GracefulShutdown] Checkpoint-Phase Timeout: %s", exc)
            _audit_recovery("shutdown_phase_timeout", {
                "phase": "checkpoint",
                "timeout_seconds": _SHUTDOWN_PHASE_TIMEOUT_SECONDS,
            })

        try:
            flush_result = await asyncio.wait_for(
                asyncio.to_thread(self.flush_all_databases),
                timeout=_SHUTDOWN_PHASE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            flush_result = {
                "status": "error",
                "flushed_databases": [],
                "errors": [f"phase_timeout: {exc}"],
            }
            logger.error("[GracefulShutdown] WAL-Flush-Phase Timeout: %s", exc)
            _audit_recovery("shutdown_phase_timeout", {
                "phase": "wal_flush",
                "timeout_seconds": _SHUTDOWN_PHASE_TIMEOUT_SECONDS,
            })

        return {
            "status": "shutdown_ready",
            "reason": reason,
            "draining": drain_result,
            "checkpoints_created": checkpoints,
            "wal_flush": flush_result
        }

    def auto_resume_on_startup(self) -> Dict[str, Any]:
        """
        Prüft beim Serverstart auf unterbrochene Tasks ('checkpointed' oder 'in_progress' Verwaiste)
        und stellt sie für die Fortführung bereit.
        """
        recovered = []
        try:
            from backend.durable_checkpoint_manager import durable_checkpoint_manager
            cps = durable_checkpoint_manager.list_checkpoints(status_filter="checkpointed")
            for cp in cps:
                workflow_id = str(cp.get("workflow_id") or "")
                resume = durable_checkpoint_manager.resume_checkpoint(workflow_id) if workflow_id else {"found": False}
                restart = {"queued": False, "reason": "checkpoint_not_found"}
                if resume.get("found"):
                    try:
                        from backend.dead_letter_queue import dead_letter_queue_manager as _dlq
                        # Der echte Restart laeuft im produktiven Scheduler-Loop
                        # (Shared-Queue-Consumer) — kein asyncio.run() im
                        # synchronen Startup-Hook, keine neue Event-Loop.
                        restart = dict(_dlq.enqueue_task(
                            job_type="workflow_resume",
                            source_module="graceful_shutdown_coordinator",
                            payload={
                                "run_id": workflow_id,
                                "resume_from_step": resume.get("resume_from_step"),
                                "task_title": cp.get("task_title"),
                            },
                            priority=3,
                            idempotency_key=f"workflow-resume:{workflow_id}",
                        ))
                    except Exception as enqueue_exc:
                        restart = {"queued": False, "reason": f"enqueue_failed: {enqueue_exc}"}
                # D07/MED: ein gescheiterter Enqueue war frueher nur im
                # Rueckgabe-Dict sichtbar. Der Checkpoint bleibt 'checkpointed'
                # und wird vom Idempotency-Key am erneuten Enqueue gehindert —
                # daher hart eskalieren, statt ihn als wiederhergestellt zu melden.
                if restart.get("queued") is not True and restart.get("duplicate") is not True:
                    failure = {
                        "task_id": workflow_id,
                        "reason": restart.get("reason", "unknown"),
                    }
                    self.failed_resumes.append(failure)
                    logger.error(
                        "[GracefulShutdown] Resume von %s nicht enqueued: %s",
                        workflow_id, failure["reason"],
                    )
                    _audit_recovery("checkpoint_resume_enqueue_failed", failure)
                    _hitl_escalate(
                        "Resume-Enqueue fehlgeschlagen",
                        f"Workflow {workflow_id}: {failure['reason']}",
                    )
                recovered.append({
                    "task_id": workflow_id,
                    "title": cp.get("task_title"),
                    "step": cp.get("current_step_index"),
                    "total": cp.get("total_steps"),
                    "resume_from_step": resume.get("resume_from_step") if resume.get("found") else None,
                    "restart": restart,
                })
        except Exception as exc:
            print(f"[GracefulShutdown] Keine unterbrochenen Checkpoints wiederhergestellt (durable_checkpoint_manager nicht erreichbar): {exc}", file=sys.stderr)

        # Verwaiste 'in_progress' Tasks nach hartem Crash (z.B. Stromausfall) auf 'todo' zurücksetzen
        recovered_orphans = self._heal_orphan_tasks()

        if recovered or recovered_orphans:
            print(f"[GracefulShutdown] Startup-Recovery: {len(recovered)} Checkpoints gefunden, {recovered_orphans} verwaiste Tasks reaktiviert.")

        return {
            "recovered_checkpoints": recovered,
            "recovered_orphans_count": recovered_orphans,
            "resume_failures": list(self.failed_resumes),
            "checkpoint_failures": list(self.failed_checkpoints),
        }

    def _heal_orphan_tasks(self, db_path: Optional[str] = None) -> int:
        """Heilt Tasks, die durch unvorhergesehenes Beenden im 'in_progress'-Status hängengeblieben sind."""
        count = 0
        db_paths = [db_path] if db_path else self._known_db_paths(
            ["kanban.db", "state.db", "agent_os.db"]
        )
        for dbp in db_paths:
            if os.path.exists(dbp):
                try:
                    with sqlite3.connect(dbp, timeout=5.0, factory=_ArchonClosingConn) as conn:
                        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
                        if not cols:
                            continue
                        assignments = ["status = 'todo'"]
                        if "claim_lock" in cols:
                            assignments.append("claim_lock = NULL")
                        if "worker_pid" in cols:
                            assignments.append("worker_pid = NULL")
                        cur = conn.execute(
                            f"UPDATE tasks SET {', '.join(assignments)} WHERE status = 'in_progress'"
                        )
                        count += cur.rowcount
                        conn.commit()
                except Exception as exc:
                    print(f"[GracefulShutdown] Warnung: Verwaiste 'in_progress' Tasks in dieser DB konnten nicht zurueckgesetzt werden: {exc}", file=sys.stderr)
        return count


# Globaler Singleton
graceful_shutdown_coordinator = GracefulShutdownCoordinator()

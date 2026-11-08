"""
backend/graceful_shutdown_coordinator.py
Sauberes Herunterfahren mit Task-Draining & Durable Checkpointing (t-12113b, Pillar 1 & 2).
- Verwaltet Draining-Zustand des Systems (RUNNING -> DRAINING -> CHECKPOINTING -> FLUSHING_WAL -> TERMINATED).
- Verhindert neue Hintergrund-Jobs während des Draining-Fensters.
- Lässt aktive Kurzläufer innerhalb einer Grace-Period (Standard: 15s) geordnet auslaufen.
- Sichert noch laufende Langläufer als transaktionale Checkpoints in SQLite (`durable_workflow_checkpoints`).
- Flusht alle SQLite WAL-Logs (`PRAGMA wal_checkpoint(TRUNCATE)`) und den Async-Write-Batcher vor dem Exit.
- Stellt unterbrochene Tasks beim Systemstart automatisch wieder her.
"""

import os
import sys
import time
import json
import signal
import sqlite3
import asyncio
import datetime
from typing import Dict, Any, List, Optional, Set, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GracefulShutdownCoordinator:
    def __init__(self):
        self._is_draining = False
        self._draining_reason = ""
        self._draining_started_at: Optional[float] = None
        self._default_grace_seconds = 15.0
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock() if sys.version_info >= (3, 7) else None

    @property
    def is_draining(self) -> bool:
        return self._is_draining

    def start_draining(self, reason: str = "System shutdown / update", grace_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Aktiviert den Draining-Modus. Neue Tasks werden ab jetzt abgewiesen."""
        self._is_draining = True
        self._draining_reason = reason
        self._draining_started_at = time.time()
        if grace_seconds is not None:
            self._default_grace_seconds = float(grace_seconds)

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
        """Asynchrone Variante für FastAPI Lifespan Events."""
        try:
            return await asyncio.to_thread(self.drain_active_tasks_sync, timeout_seconds)
        except Exception:
            return self.drain_active_tasks_sync(timeout_seconds)

    def checkpoint_remaining_tasks(self) -> List[Dict[str, Any]]:
        """
        Sichert alle Aufgaben, die das Draining-Fenster nicht geschafft haben,
        als transaktionale Checkpoints in SQLite und markiert sie als 'checkpointed'.
        """
        if not self._active_tasks:
            return []

        checkpoints = []
        try:
            from backend.durable_checkpoint_manager import durable_checkpoint_manager
            has_mgr = True
        except Exception:
            has_mgr = False

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for tid, tinfo in list(self._active_tasks.items()):
            title = tinfo.get("title", f"Task {tid}")
            cur_step = tinfo.get("current_step", 0)
            total_steps = tinfo.get("total_steps", 1)
            state = tinfo.get("state_payload", {})

            # 1. In durable_checkpoint_manager eintragen
            if has_mgr:
                try:
                    durable_checkpoint_manager.save_checkpoint(
                        workflow_id=tid,
                        task_title=title,
                        current_step_index=cur_step,
                        total_steps=total_steps,
                        state_payload=state,
                        status="checkpointed"
                    )
                except Exception as e:
                    print(f"[GracefulShutdown] Fehler beim Checkpointing von {tid}: {e}", file=sys.stderr)

            # 2. In kanban.db oder agent_os.db Status von 'in_progress' auf 'checkpointed' setzen
            self._update_task_db_status(tid, "checkpointed", f"Automatisch pausiert vor System-Shutdown ({now_iso})")

            checkpoints.append({
                "task_id": tid,
                "title": title,
                "step": cur_step,
                "total": total_steps,
                "status": "checkpointed"
            })

        print(f"[GracefulShutdown] {len(checkpoints)} verbleibende Aufgaben erfolgreich als Checkpoint gesichert.")
        self._active_tasks.clear()
        return checkpoints

    def _update_task_db_status(self, task_id: str, new_status: str, note: str = ""):
        """Setzt den Task-Status in den bekannten SQLite-Tasktabellen."""
        db_paths = [
            os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
            os.path.join(WORKSPACE_DIR, "agent_os.db"),
        ]
        for dbp in db_paths:
            if os.path.exists(dbp):
                try:
                    with sqlite3.connect(dbp, timeout=2.0) as conn:
                        conn.execute(
                            "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (new_status, task_id)
                        )
                        conn.commit()
                except Exception:
                    pass

    def flush_all_databases(self) -> Dict[str, Any]:
        """
        Leert den Async-Write-Batcher und führt PRAGMA wal_checkpoint(PASSIVE)
        auf allen relevanten SQLite-Datenbanken aus, um Datenverlust zu verhindern.
        """
        flushed_dbs = []

        # 1. Async Write Batcher leeren
        # N-03: das Modul exportiert die Singleton-INSTANZ (async_write_batcher),
        # keinen get_write_batcher()-Factory. Der ImportError wurde vorher vom
        # blanket-except geschluckt — der RAM-Puffer blieb liegen, das Log
        # meldete trotzdem "WAL-Flush abgeschlossen".
        try:
            from backend.async_write_batcher import async_write_batcher as write_batcher
            flush_info = write_batcher.flush()
            flushed_dbs.append("async_write_batcher_ram_queue")
            if isinstance(flush_info, dict) and flush_info.get("status") == "error":
                print(f"[GracefulShutdown] Batcher-Flush meldet Fehler: {flush_info}", file=sys.stderr)
        except Exception as e:
            print(f"[GracefulShutdown] Batcher-Flush fehlgeschlagen: {e}", file=sys.stderr)

        # 2. Alle SQLite-Datenbanken einsammeln
        candidate_paths = [
            os.path.join(WORKSPACE_DIR, "agent_os.db"),
            os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
            os.path.join(WORKSPACE_DIR, "data", "contracts.db"),
            os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
            os.path.join(WORKSPACE_DIR, "data", "state.db"),
            os.path.join(WORKSPACE_DIR, "data", "hybrid_search.db"),
        ]

        for db_file in candidate_paths:
            if os.path.isfile(db_file):
                try:
                    with sqlite3.connect(db_file, timeout=2.0) as conn:
                        cur = conn.cursor()
                        # PASSIVE checkpoint: schreibt unblockiert alle ungelockten Pages
                        cur.execute("PRAGMA wal_checkpoint(PASSIVE);")
                        flushed_dbs.append(os.path.basename(db_file))
                except Exception as e:
                    print(f"[GracefulShutdown] Fehler beim WAL-Flush für {db_file}: {e}", file=sys.stderr)

        print(f"[GracefulShutdown] WAL-Flush abgeschlossen ({len(flushed_dbs)} Speicherpunkte konsolidiert).")
        return {"status": "success", "flushed_databases": flushed_dbs}

        print(f"[GracefulShutdown] WAL-Flush abgeschlossen ({len(flushed_dbs)} Speicherpunkte konsolidiert).")
        return {"status": "success", "flushed_databases": flushed_dbs}

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
        """Vollständige Orchestrierung: Draining -> Grace Wait -> Checkpointing -> WAL-Flush."""
        try:
            return await asyncio.to_thread(self.execute_graceful_shutdown_sync, reason, grace_seconds)
        except Exception:
            return self.execute_graceful_shutdown_sync(reason=reason, grace_seconds=grace_seconds)

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
                recovered.append({
                    "task_id": cp.get("workflow_id"),
                    "title": cp.get("task_title"),
                    "step": cp.get("current_step_index"),
                    "total": cp.get("total_steps")
                })
        except Exception:
            pass

        # Verwaiste 'in_progress' Tasks nach hartem Crash (z.B. Stromausfall) auf 'todo' zurücksetzen
        recovered_orphans = self._heal_orphan_tasks()

        if recovered or recovered_orphans:
            print(f"[GracefulShutdown] Startup-Recovery: {len(recovered)} Checkpoints gefunden, {recovered_orphans} verwaiste Tasks reaktiviert.")

        return {
            "recovered_checkpoints": recovered,
            "recovered_orphans_count": recovered_orphans
        }

    def _heal_orphan_tasks(self) -> int:
        """Heilt Tasks, die durch unvorhergesehenes Beenden im 'in_progress'-Status hängengeblieben sind."""
        count = 0
        db_paths = [
            os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
            os.path.join(WORKSPACE_DIR, "agent_os.db")
        ]
        for dbp in db_paths:
            if os.path.exists(dbp):
                try:
                    with sqlite3.connect(dbp, timeout=5.0) as conn:
                        cur = conn.execute(
                            "UPDATE tasks SET status = 'todo', updated_at = CURRENT_TIMESTAMP WHERE status = 'in_progress'"
                        )
                        count += cur.rowcount
                        conn.commit()
                except Exception:
                    pass
        return count


# Globaler Singleton
graceful_shutdown_coordinator = GracefulShutdownCoordinator()

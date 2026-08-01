import os
import json
import hashlib
import datetime
import asyncio
from typing import Dict, Any, Optional

class CoreWatchdog:
    def __init__(self, storage, check_interval: float = 30.0, timeout_limit: float = 300.0):
        self.storage = storage
        self.check_interval = check_interval
        self.timeout_limit = timeout_limit
        self.scheduler = None
        self.is_running = False
        self._loop_task = None
        
        self._init_telemetry_table()

    def _init_telemetry_table(self):
        """
        Initialisiert die Tabelle für das kryptografisch verkettete Telemetrie-Audit-Log.
        """
        conn = self.storage._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    latency REAL NOT NULL,
                    prev_hash TEXT,
                    current_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def log_telemetry(self, event_type: str, details: str, latency: float) -> str:
        """
        Schreibt einen Eintrag in das Telemetrie-Log mit kryptografischer SHA-256 Verkettung.
        """
        conn = self.storage._get_connection()
        try:
            # 1. Letzten Hash auslesen
            row = conn.execute("SELECT current_hash FROM telemetry_audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["current_hash"] if row else "0" * 64

            timestamp = datetime.datetime.now().isoformat()
            
            # 2. Block formatieren und hashen
            log_str = f"{event_type}|{details}|{latency}|{prev_hash}|{timestamp}"
            current_hash = hashlib.sha256(log_str.encode("utf-8")).hexdigest()

            # 3. Speichern
            conn.execute("""
                INSERT INTO telemetry_audit_log (event_type, details, latency, prev_hash, current_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (event_type, details, latency, prev_hash, current_hash, timestamp))
            conn.commit()
            
            return current_hash
        finally:
            conn.close()

    def start(self, scheduler):
        """
        Startet die Watchdog-Schleife im Hintergrund.
        """
        self.scheduler = scheduler
        self.is_running = True
        self._loop_task = asyncio.create_task(self._watchdog_loop())
        print("[Watchdog] Started active watchdog loop.")

    def stop(self):
        """
        Stoppt die Watchdog-Schleife.
        """
        self.is_running = False
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        print("[Watchdog] Stopped active watchdog loop.")

    async def _watchdog_loop(self):
        """
        Asynchroner Watchdog-Hintergrundprozess.
        """
        while self.is_running:
            try:
                await asyncio.sleep(self.check_interval)
                if not self.is_running:
                    break
                await self.run_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Watchdog Error] Exception in loop: {e}")

    async def run_checks(self):
        """
        Scanned die Datenbank nach hängenden Prozessen und beendet diese.
        """
        conn = self.storage._get_connection()
        try:
            # Hole alle Tasks, die sich in Ausführung befinden
            rows = conn.execute("SELECT * FROM tasks WHERE status = 'in_progress'").fetchall()
        finally:
            conn.close()

        now = datetime.datetime.now()

        for row in rows:
            task_id = row["task_id"]
            agent_id = row["agent_id"]
            updated_at_str = row["updated_at"]
            
            try:
                updated_at = datetime.datetime.fromisoformat(updated_at_str)
            except Exception:
                # Fallback falls ISO-Format ungültig
                updated_at = now

            elapsed = (now - updated_at).total_seconds()

            if elapsed > self.timeout_limit:
                print(f"[Watchdog] Task {task_id} for agent {agent_id} timed out ({elapsed:.1f}s > {self.timeout_limit:.1f}s). Preempting...")
                
                # 1. Breche laufende Task im Scheduler ab
                if self.scheduler and task_id in self.scheduler.active_tasks:
                    task_obj = self.scheduler.active_tasks.get(task_id)
                    if task_obj:
                        try:
                            # Thread-sicherer Abbruch
                            loop = task_obj.get_loop()
                            loop.call_soon_threadsafe(task_obj.cancel)
                        except Exception:
                            task_obj.cancel()
                
                # 2. Speichere Status in DB als failed mit Fehlercode
                self.storage.save_task(
                    task_id=task_id,
                    agent_id=agent_id,
                    status="failed",
                    result={"error": "TIMEOUT_WATCHDOG_FORCED_CANCEL"}
                )
                
                # 3. Protokolliere den Timeout-Ereignis im Telemetrie-Log
                self.log_telemetry(
                    event_type="watchdog_preemption",
                    details=f"Task {task_id} preemptively cancelled. Elapsed: {elapsed:.1f}s",
                    latency=elapsed
                )

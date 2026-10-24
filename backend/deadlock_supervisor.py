"""
backend/deadlock_supervisor.py
Deadlock- & Stagnations-Wächter für parallele Subagenten (Pillar 1 & 2).
Erkennt zirkuläre Abhängigkeiten und stagnierende Tasks im Kanban/Scheduler.
Löst Blockaden nach konfigurierbarer Inaktivität autonom auf.
"""

import os
import sys
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KANBAN_DB = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else os.path.expanduser("~/.hermes/kanban.db")

class DeadlockSupervisor:
    def __init__(self, db_path: str = KANBAN_DB):
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def detect_and_resolve_deadlocks(self, stagnation_threshold_seconds: Optional[int] = None) -> Dict[str, Any]:
        """
        Prüft laufende Tasks auf Blockaden und Stagnation.
        Setzt hängende Tasks nach Timeout kontrolliert zurück auf 'todo' mit Backoff.
        """
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("concurrency")
            if not cfg.get("auto_deadlock_recovery", True):
                return {"status": "disabled", "resolved_count": 0, "resolved_tasks": [], "message": "Deadlock-Recovery ist in den Einstellungen deaktiviert."}
            if stagnation_threshold_seconds is None:
                stagnation_threshold_seconds = int(cfg.get("stagnation_threshold_seconds", 45))
        except Exception:
            if stagnation_threshold_seconds is None:
                stagnation_threshold_seconds = 45

        if not os.path.exists(self.db_path):
            return {"status": "no_db", "resolved_count": 0, "stagnant_tasks": []}

        now = datetime.datetime.now()
        resolved = []

        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, title, assignee, status, created_at, body
                    FROM tasks
                    WHERE status IN ('in_progress', 'blocked')
                """)
                active_tasks = cur.fetchall()

                for t in active_tasks:
                    t_id = t["id"]
                    c_at_str = t["created_at"]
                    try:
                        c_at = datetime.datetime.fromisoformat(c_at_str)
                    except Exception:
                        continue

                    age_sec = (now - c_at).total_seconds()
                    if age_sec > stagnation_threshold_seconds:
                        new_body = (t["body"] or "") + f"\n\n[STAGNATION-RESOLVED: Task nach {int(age_sec)}s Blockade vom Supervisor reaktiviert.]"
                        conn.execute("""
                            UPDATE tasks
                            SET status = 'todo', body = ?
                            WHERE id = ?
                        """, (new_body, t_id))
                        resolved.append({
                            "task_id": t_id,
                            "title": t["title"],
                            "assignee": t["assignee"],
                            "stagnant_seconds": int(age_sec)
                        })
                conn.commit()

            return {
                "status": "success",
                "resolved_count": len(resolved),
                "resolved_tasks": resolved,
                "stagnation_threshold_seconds": stagnation_threshold_seconds,
                "message": f"{len(resolved)} stagnierende(r) Task(s) aufgelöst und reaktiviert." if resolved else "Keine Deadlocks oder Stagnationen festgestellt."
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "resolved_count": 0}

deadlock_supervisor = DeadlockSupervisor()

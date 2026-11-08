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

def _to_dt(value) -> Optional[datetime.datetime]:
    """Wandelt einen Zeitstempel (Epoch-Float/Int oder ISO-String) in datetime um.

    N-06: die Kanban-DB deklariert created_at als INTEGER/Epoch; andere Quellen
    liefern ISO-Strings. fromisoformat allein uebersprang jede Zeile.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(float(value))
    s = str(value).strip()
    try:
        return datetime.datetime.fromtimestamp(float(s))
    except ValueError:
        pass
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


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

        conn = self._get_conn()
        try:
            with conn:
                cur = conn.cursor()
                # N-06: 'last_heartbeat_at' existiert nicht in jedem Schema —
                # Spalte optional ermitteln.
                cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
                has_heartbeat = "last_heartbeat_at" in cols
                sel = "id, title, assignee, status, created_at, body" + (", last_heartbeat_at" if has_heartbeat else "")
                cur.execute(
                    f"SELECT {sel} FROM tasks WHERE status IN ('in_progress', 'blocked')"
                )
                active_tasks = cur.fetchall()

                for t in active_tasks:
                    t_id = t["id"]
                    # N-06: kanban.db speichert created_at als INTEGER (Epoch),
                    # nicht als ISO-String — fromisoformat warf, das except
                    # uebersprang jede Zeile: "Keine Deadlocks" fuer immer.
                    c_at = _to_dt(t["created_at"])
                    if c_at is None:
                        continue

                    # Stagnation ab dem LETZTEN Heartbeat messen, nicht ab
                    # Erstellung: ein legitim langer Task mit lebendem Worker
                    # wurde vorher auf 'todo' zurueckgesetzt, waehrend er noch
                    # claim_lock/worker_pid hielt (Doppelausfuehrung).
                    if has_heartbeat and t["last_heartbeat_at"]:
                        last_beacon = _to_dt(t["last_heartbeat_at"])
                        if last_beacon is not None:
                            c_at = max(c_at, last_beacon)

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
        finally:
            conn.close()

deadlock_supervisor = DeadlockSupervisor()

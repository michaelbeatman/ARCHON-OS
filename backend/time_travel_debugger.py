"""
backend/time_travel_debugger.py
Replay & Time-Travel Debugging (Execution Trace Player & State Forker).
Ermöglicht das lückenlose Aufzeichnen, Abspielen, Forken und Zurückrollen
von Agenten-Ausführungsschritten (Pillar 4 & 6).
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

class TimeTravelDebugger:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    model TEXT,
                    input_payload TEXT,
                    output_payload TEXT,
                    snapshot_id TEXT,
                    tokens_used INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'success',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_task ON execution_traces(task_id, step_index);")
            conn.commit()

    def record_step(
        self,
        task_id: str,
        step_index: int,
        agent_id: str,
        action_type: str,
        input_payload: Any,
        output_payload: Any,
        model: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        tokens_used: int = 0,
        duration_seconds: float = 0.0,
        status: str = "success"
    ) -> int:
        """Protokolliert einen atomaren Ausführungsschritt für Time-Travel Replay."""
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("time_travel_snapshots")
            if not cfg.get("tracing_enabled", True):
                return 0
            max_steps = int(cfg.get("max_trace_steps", 100))
            if step_index > max_steps:
                return 0
        except Exception:
            pass

        in_str = json.dumps(input_payload, ensure_ascii=False) if not isinstance(input_payload, str) else input_payload
        out_str = json.dumps(output_payload, ensure_ascii=False) if not isinstance(output_payload, str) else output_payload

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO execution_traces 
                (task_id, step_index, agent_id, action_type, model, input_payload, output_payload, snapshot_id, tokens_used, duration_seconds, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (task_id, step_index, agent_id, action_type, model, in_str, out_str, snapshot_id, tokens_used, duration_seconds, status))
            conn.commit()
            return cur.lastrowid

    def get_task_trace(self, task_id: str) -> List[Dict[str, Any]]:
        """Liefert den lückenlosen chronologischen Ablauf eines Tasks für den Trace Player."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM execution_traces 
                WHERE task_id = ? 
                ORDER BY step_index ASC, id ASC
            """, (task_id,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                try:
                    r["input_payload"] = json.loads(r["input_payload"])
                except Exception:
                    pass
                try:
                    r["output_payload"] = json.loads(r["output_payload"])
                except Exception:
                    pass
            return rows

    def fork_execution(self, task_id: str, from_step: int, new_prompt: Optional[str] = None, new_model: Optional[str] = None) -> Dict[str, Any]:
        """
        Erstellt einen Fork des Tasks ab einem bestimmten Teilschritt.
        Ermöglicht Was-wäre-wenn-Analysen mit alternativen Prompts oder Modellen.
        """
        traces = self.get_task_trace(task_id)
        if not traces:
            return {"status": "error", "message": f"Keine Trace-Daten für Task '{task_id}' gefunden."}

        valid_steps = [t for t in traces if t["step_index"] <= from_step]
        if not valid_steps:
            return {"status": "error", "message": f"Kein Schritt <= {from_step} vorhanden."}

        forked_task_id = f"{task_id}-fork-s{from_step}-{datetime.datetime.now().strftime('%H%M%S')}"

        with self._get_conn() as conn:
            for s in valid_steps:
                conn.execute("""
                    INSERT INTO execution_traces 
                    (task_id, step_index, agent_id, action_type, model, input_payload, output_payload, snapshot_id, tokens_used, duration_seconds, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'forked_base', CURRENT_TIMESTAMP)
                """, (
                    forked_task_id,
                    s["step_index"],
                    s["agent_id"],
                    s["action_type"],
                    new_model if (s["step_index"] == from_step and new_model) else s["model"],
                    json.dumps(s["input_payload"], ensure_ascii=False) if isinstance(s["input_payload"], (dict, list)) else s["input_payload"],
                    json.dumps(s["output_payload"], ensure_ascii=False) if isinstance(s["output_payload"], (dict, list)) else s["output_payload"],
                    s.get("snapshot_id"),
                    s.get("tokens_used", 0),
                    s.get("duration_seconds", 0.0)
                ))
            conn.commit()

        try:
            from local_memory_bridge import LocalMemoryBridge
            bridge = LocalMemoryBridge()
            last_step = valid_steps[-1]
            bridge.sync_task(
                task_id=forked_task_id,
                title=f"[FORK ab Schritt {from_step}] {task_id}",
                role=last_step.get("agent_id", "hermes-coder"),
                status="in_progress"
            )
        except Exception:
            pass

        return {
            "status": "success",
            "forked_task_id": forked_task_id,
            "origin_task_id": task_id,
            "forked_at_step": from_step,
            "retained_steps_count": len(valid_steps),
            "new_model": new_model,
            "new_prompt": new_prompt
        }

    def rollback_to_step(self, task_id: str, to_step: int) -> Dict[str, Any]:
        """
        Rollt alle Dateiänderungen zurück, die nach to_step durchgeführt wurden.
        Nutzt die Snapshot-IDs der nachfolgenden Schritte.
        """
        traces = self.get_task_trace(task_id)
        if not traces:
            return {"status": "error", "message": f"Keine Trace-Daten für Task '{task_id}' gefunden."}

        steps_to_undo = [t for t in traces if t["step_index"] > to_step and t.get("snapshot_id")]
        steps_to_undo.reverse()

        from backend.snapshot_manager import snapshot_manager
        restored = []
        for s in steps_to_undo:
            snap_id = s["snapshot_id"]
            res = snapshot_manager.restore_snapshot(snap_id)
            restored.append({"step": s["step_index"], "snapshot_id": snap_id, "result": res})

        return {
            "status": "success",
            "task_id": task_id,
            "rolled_back_to_step": to_step,
            "undone_steps_count": len(steps_to_undo),
            "restored_snapshots": restored
        }

time_travel_debugger = TimeTravelDebugger()

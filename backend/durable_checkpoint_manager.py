"""
backend/durable_checkpoint_manager.py
Paket 3 (Feature 12): Durable Execution Checkpointing (Pause / Resume über Neustarts hinweg).
Speichert den exakten Ausführungszustand mehrstufiger Agenten-Workflows nach jedem Schritt
transaktional in SQLite (`durable_workflow_checkpoints`), sodass unterbrochene Jobs nach
einem Server-Neustart nahtlos ab dem letzten erledigten Schritt fortgesetzt werden können.
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("durable_checkpointing")
    except Exception:
        return {
            "enabled": True,
            "checkpoint_every_n_steps": 1,
            "auto_resume_on_boot": True,
            "retention_days": 14
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS durable_workflow_checkpoints (
                workflow_id TEXT PRIMARY KEY,
                task_title TEXT,
                current_step_index INTEGER,
                total_steps INTEGER,
                status TEXT,
                state_json TEXT,
                completed_steps_json TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()


class DurableCheckpointManager:
    def __init__(self):
        _init_db()

    def save_checkpoint(
        self,
        workflow_id: str,
        task_title: str,
        current_step_index: int,
        total_steps: int,
        state_payload: Dict[str, Any],
        completed_steps: Optional[List[str]] = None,
        status: str = "in_progress"
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"saved": False, "bypassed": True}

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO durable_workflow_checkpoints
                (workflow_id, task_title, current_step_index, total_steps, status, state_json, completed_steps_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    task_title = excluded.task_title,
                    current_step_index = excluded.current_step_index,
                    total_steps = excluded.total_steps,
                    status = excluded.status,
                    state_json = excluded.state_json,
                    completed_steps_json = excluded.completed_steps_json,
                    updated_at = excluded.updated_at
            """, (
                workflow_id,
                task_title,
                current_step_index,
                total_steps,
                status,
                json.dumps(state_payload, ensure_ascii=False),
                json.dumps(completed_steps or [], ensure_ascii=False),
                now_iso
            ))
            conn.commit()

        return {
            "saved": True,
            "workflow_id": workflow_id,
            "current_step_index": current_step_index,
            "total_steps": total_steps,
            "status": status,
            "updated_at": now_iso
        }

    def resume_checkpoint(self, workflow_id: str) -> Dict[str, Any]:
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM durable_workflow_checkpoints WHERE workflow_id = ?",
                (workflow_id,)
            ).fetchone()

        if not row:
            return {"found": False, "workflow_id": workflow_id}

        return {
            "found": True,
            "workflow_id": row["workflow_id"],
            "task_title": row["task_title"],
            "resume_from_step": row["current_step_index"] + 1,
            "last_completed_step": row["current_step_index"],
            "total_steps": row["total_steps"],
            "status": row["status"],
            "state": json.loads(row["state_json"] or "{}"),
            "completed_steps": json.loads(row["completed_steps_json"] or "[]"),
            "updated_at": row["updated_at"]
        }

    def list_checkpoints(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            if status_filter:
                rows = conn.execute(
                    "SELECT * FROM durable_workflow_checkpoints WHERE status = ? ORDER BY updated_at DESC",
                    (status_filter,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM durable_workflow_checkpoints ORDER BY updated_at DESC LIMIT 50"
                ).fetchall()
            return [dict(r) for r in rows]


durable_checkpoint_manager = DurableCheckpointManager()

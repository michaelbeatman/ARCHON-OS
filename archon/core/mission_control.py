"""Mission-Control-Store (atomare, nebenlaeufigkeitssichere Persistenz).

Aus main.py ausgelagert: die Datei hat viele Schreiber (Move-Handler, Watcher,
Cascade). _write_mc_atomic schreibt ueber Temp-Datei + fsync + os.replace,
damit nie Halbstaende entstehen. Der Thread-Lock serialisiert die Writer, der
Async-Lock schuetzt Read-Modify-Write-Sequenzen im Event-Loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
from typing import Any, Dict

from archon.core.runtime import MEMORY_DIR

MISSION_CONTROL_FILE = os.path.join(MEMORY_DIR, "mission_control_data.json")

_MC_DATA_LOCK = threading.Lock()
_MC_ASYNC_LOCK = asyncio.Lock()

def _write_mc_atomic(data: dict):
    """Atomarer MC-Store-Write. Nur mit gehaltenem _MC_DATA_LOCK aufrufen
    (Lock ist nicht reentrant - _save_mission_control_data haelt ihn aussen)."""
    _dir = os.path.dirname(os.path.abspath(MISSION_CONTROL_FILE)) or "."
    os.makedirs(_dir, exist_ok=True)
    _fd, _tmp = tempfile.mkstemp(dir=_dir, prefix=".mission_control_", suffix=".tmp")
    try:
        with os.fdopen(_fd, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)
            _f.flush()
            os.fsync(_f.fileno())
        os.replace(_tmp, MISSION_CONTROL_FILE)
    except BaseException:
        try:
            os.unlink(_tmp)
        except OSError:
            pass
        raise


def _load_mission_control_data() -> dict:
    if os.path.exists(MISSION_CONTROL_FILE):
        try:
            with open(MISSION_CONTROL_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d and isinstance(d, dict) and d.get("tasks"):
                    return d
        except Exception as e:
            print(f"Error loading mission_control_data: {e}")

    # Echte Tasks aus SQLite laden
    real_tasks = []

    # SQLite Tasks als Ergänzung
    if not real_tasks:
        try:
            import sqlite3
            for db in ["/opt/data/agentic_memory.db", "./data/agentic_memory.db"]:
                if os.path.exists(db):
                    conn = sqlite3.connect(db, timeout=5.0)
                    conn.execute("PRAGMA busy_timeout=5000;")
                    try:
                        cur = conn.cursor()
                        cur_rows = cur.execute("SELECT id, title, role, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 20").fetchall()
                    finally:
                        conn.close()
                    for row in cur_rows:
                        t_id, t_title, t_role, t_status, t_created = row
                        status_raw = (t_status or "").lower()
                        if status_raw in ["waiting_approval", "approval", "gate"]:
                            col_status = "approval"
                        elif status_raw in ["in_progress", "running"]:
                            col_status = "in_progress"
                        elif status_raw in ["completed", "done", "finished"]:
                            col_status = "completed"
                        else:
                            col_status = "backlog"

                        real_tasks.append({
                            "id": t_id,
                            "title": t_title or t_id,
                            "plan": ["Autonomer Task aus dem System"],
                            "agent_id": t_role or "system",
                            "agent_name": t_role or "System Agent",
                            "model": "omniroute/best-free",
                            "estimated_tokens": 15000,
                            "estimated_cost_eur": 0.0,
                            "subagents_count": 1,
                            "status": col_status,
                            "created_at": str(t_created)[:16],
                            "result_summary": "",
                            "artifact_path": ""
                        })
                    conn.close()
                    if real_tasks:
                        break
        except Exception:
            pass

    archive_file = os.path.join(MEMORY_DIR, "archived_tasks.json")
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r") as f:
                archived = set(json.load(f))
            real_tasks = [t for t in real_tasks if t["id"] not in archived]
        except Exception:
            pass

    return {
        "tasks": real_tasks,
        "metrics": {
            "tpm_current": 184200,
            "tpm_limit": 2000000,
            "cost_today_usd": 0.00,
            "cost_limit_usd": 5.00
        },
        "audit_logs": []
    }

def _save_mission_control_data(data: dict):
    try:
        with _MC_DATA_LOCK:
            _write_mc_atomic(data)
    except Exception as e:
        print(f"Error saving mission_control_data: {e}")

__all__ = [
    "MISSION_CONTROL_FILE", "_MC_DATA_LOCK", "_MC_ASYNC_LOCK",
    "_write_mc_atomic", "_load_mission_control_data", "_save_mission_control_data",
]

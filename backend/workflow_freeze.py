# -*- coding: utf-8 -*-
"""
backend/workflow_freeze.py
==========================
Meilenstein 92: Deterministischer Workflow-Freeze & Replay
(freeze & workflow-record-Pattern).

Friert eine erfolgreiche Sequenz aus Tool-/Browser-Calls ein und fuehrt
sie zukuenftig exakt und ohne LLM-Tokenkosten wieder aus.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "frozen_workflows.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS frozen_workflows (
                workflow_id TEXT PRIMARY KEY,
                steps_json TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at REAL NOT NULL,
                replay_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def freeze_tool_sequence(
    workflow_id: str,
    recorded_calls: List[Dict[str, Any]],
    description: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    steps = [
        {"tool": str(c.get("tool") or ""), "args": c.get("args") or {}}
        for c in recorded_calls
        if c.get("tool")
    ]
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO frozen_workflows (workflow_id, steps_json, description, created_at, replay_count)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(workflow_id) DO UPDATE SET
                steps_json=excluded.steps_json, description=excluded.description
            """,
            (workflow_id, json.dumps(steps, ensure_ascii=False), description, time.time()),
        )
        conn.commit()
    return {"workflow_id": workflow_id, "step_count": len(steps), "frozen": True}


async def replay_frozen_workflow(
    workflow_id: str,
    tool_executor: Callable[[str, Dict[str, Any]], Awaitable[Any]],
    param_overrides: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT steps_json FROM frozen_workflows WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if not row:
            return {"status": "not_found", "workflow_id": workflow_id, "results": []}
        steps = json.loads(row["steps_json"])
        conn.execute(
            "UPDATE frozen_workflows SET replay_count = replay_count + 1 WHERE workflow_id = ?",
            (workflow_id,),
        )
        conn.commit()

    overrides = param_overrides or {}
    results = []
    for idx, st in enumerate(steps, start=1):
        args = dict(st.get("args") or {})
        args.update(overrides)
        out = await tool_executor(st["tool"], args)
        results.append({"step": idx, "tool": st["tool"], "output": out})

    return {"status": "completed", "workflow_id": workflow_id, "llm_tokens_used": 0, "results": results}

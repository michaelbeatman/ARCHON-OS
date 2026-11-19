# -*- coding: utf-8 -*-
"""
backend/lossless_session_dag.py
===============================
Meilenstein 94: Lossless Session-DAG & Multi-Perspektiven-Research
(hermes-lcm-x & storm-fusion-research-Pattern).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "lcm_sessions.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lcm_turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lcm_summaries (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                child_turn_ids_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def append_turn(session_id: str, role: str, content: str, db_path: Optional[str] = None) -> str:
    tid = f"turn-{secrets.token_hex(5)}"
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM lcm_turns WHERE session_id = ?", (session_id,)).fetchone()
        seq = int(row["m"]) + 1
        conn.execute(
            "INSERT INTO lcm_turns (id, session_id, seq, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tid, session_id, seq, role, content, time.time()),
        )
        conn.commit()
    return tid


def compact_range_to_summary(
    session_id: str,
    turn_ids: List[str],
    summary_text: str,
    db_path: Optional[str] = None,
) -> str:
    sid = f"sum-{secrets.token_hex(5)}"
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO lcm_summaries (id, session_id, summary_text, child_turn_ids_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (sid, session_id, summary_text, json.dumps(turn_ids), time.time()),
        )
        conn.commit()
    return sid


def expand_summary_node(summary_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT child_turn_ids_json FROM lcm_summaries WHERE id = ?", (summary_id,)).fetchone()
        if not row:
            return []
        ids = json.loads(row["child_turn_ids_json"])
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        turns = conn.execute(
            f"SELECT id, seq, role, content FROM lcm_turns WHERE id IN ({placeholders}) ORDER BY seq ASC",
            ids,
        ).fetchall()
        return [dict(t) for t in turns]


def search_lossless_history(session_id: str, query: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"%{(query or '').strip()}%"
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, seq, role, content FROM lcm_turns WHERE session_id = ? AND content LIKE ? ORDER BY seq ASC",
            (session_id, q),
        ).fetchall()
        return [dict(r) for r in rows]


async def run_storm_panel(
    question: str,
    seats: List[str],
    seat_runner: Callable[[str, str], Awaitable[str]],
    judge_runner: Callable[[str, Dict[str, str]], Awaitable[str]],
) -> Dict[str, Any]:
    """Multi-Perspektiven-Research-Panel mit parallelen Seats, Judge & Human-Gate."""
    seat_answers = await asyncio.gather(*(seat_runner(seat, question) for seat in seats))
    perspectives = dict(zip(seats, seat_answers))
    synthesis = await judge_runner(question, perspectives)
    return {
        "question": question,
        "perspectives": perspectives,
        "synthesis": synthesis,
        "requires_human_gate": True,
    }

# -*- coding: utf-8 -*-
"""
backend/session_taint_guard.py
==============================
Meilenstein 89: Information-Flow-Taint-Tracking & Session-Versiegelung
(airlock-Pattern mit HITL-Freigabe-Gate).

Sobald eine Session untrusted Content liest (Webseiten, externe E-Mails,
fremde MCP-Outputs), wird sie als `tainted` markiert. Kritische Ausgaenge
(E-Mail-Versand, Payment/pay, git push, Deploy, Memory-Write) werden dann
geparkt und benoetigen eine explizite HITL-Freigabe.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "taint_guard.db")

CRITICAL_EGRESS_TOOLS = frozenset({
    "send_email",
    "email_send",
    "pay",
    "pay-cli",
    "pay_cli",
    "git_push",
    "deploy",
    "memory_write",
    "execute_shell",
    "webhook_post",
    "telegram_send",
})

CRITICAL_EGRESS_PREFIXES = ("pay_", "mcp__pay", "mcp__email", "deploy_")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tainted_sessions (
                session_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                reason TEXT DEFAULT '',
                tainted_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS taint_hitl_approvals (
                approval_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_json TEXT DEFAULT '{}',
                taint_source TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer TEXT DEFAULT '',
                created_at REAL NOT NULL,
                resolved_at REAL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def is_critical_egress_tool(tool_name: str) -> bool:
    norm = (tool_name or "").strip().lower()
    if not norm:
        return False
    if norm in CRITICAL_EGRESS_TOOLS:
        return True
    return any(norm.startswith(pref) for pref in CRITICAL_EGRESS_PREFIXES)


def mark_session_tainted(
    session_id: str,
    source: str,
    reason: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tainted_sessions (session_id, source, reason, tainted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                source = excluded.source,
                reason = excluded.reason,
                tainted_at = excluded.tainted_at
            """,
            (session_id, source, reason, now),
        )
        conn.commit()
    return {"session_id": session_id, "tainted": True, "source": source, "reason": reason}


def get_session_taint(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id, source, reason, tainted_at FROM tainted_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def check_egress_tool_call(
    session_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Prueft, ob ein Tool-Aufruf in `session_id` ausgefuehrt werden darf.
    Bei kontaminierten Sessions werden kritische Ausgaenge ueber HITL geparkt.
    """
    if not is_critical_egress_tool(tool_name):
        return {"allowed": True, "tainted": False, "tool": tool_name}

    taint = get_session_taint(session_id, db_path=db_path)
    if not taint:
        return {"allowed": True, "tainted": False, "tool": tool_name}

    with _connect(db_path) as conn:
        if approval_id:
            row = conn.execute(
                """
                SELECT approval_id, status, consumed, tool_name, session_id
                FROM taint_hitl_approvals
                WHERE approval_id = ? AND session_id = ? AND tool_name = ?
                """,
                (approval_id, session_id, tool_name),
            ).fetchone()
            if row and row["status"] == "approved" and int(row["consumed"]) == 0:
                conn.execute(
                    "UPDATE taint_hitl_approvals SET consumed = 1 WHERE approval_id = ?",
                    (approval_id,),
                )
                conn.commit()
                return {
                    "allowed": True,
                    "tainted": True,
                    "hitl_approved": True,
                    "approval_id": approval_id,
                    "tool": tool_name,
                }

        new_id = f"ta-{secrets.token_hex(6)}"
        conn.execute(
            """
            INSERT INTO taint_hitl_approvals
                (approval_id, session_id, tool_name, args_json, taint_source, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (new_id, session_id, tool_name, json.dumps(args or {}, ensure_ascii=False), taint["source"], time.time()),
        )
        conn.commit()

    return {
        "allowed": False,
        "blocked": True,
        "requires_hitl": True,
        "tainted": True,
        "approval_id": new_id,
        "tool": tool_name,
        "taint_source": taint["source"],
        "reason": f"Session '{session_id}' ist durch '{taint['source']}' versiegelt. HITL-Freigabe '{new_id}' fuer '{tool_name}' erforderlich.",
    }


def resolve_taint_approval(
    approval_id: str,
    approved: bool,
    reviewer: str = "admin",
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    new_status = "approved" if approved else "rejected"
    now = time.time()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE taint_hitl_approvals
            SET status = ?, reviewer = ?, resolved_at = ?
            WHERE approval_id = ? AND status = 'pending'
            """,
            (new_status, reviewer, now, approval_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM taint_hitl_approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None


def list_pending_taint_approvals(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM taint_hitl_approvals WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

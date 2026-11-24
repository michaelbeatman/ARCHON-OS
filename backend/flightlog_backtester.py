# -*- coding: utf-8 -*-
"""
backend/flightlog_backtester.py
===============================
Meilenstein 83: Agenten-Flugschreiber & Guardrail-Backtester
(flightlog & policy-backtester-Pattern).

1. Flugschreiber: Erkennt "gruen fehlgeschlagene" Runs (versteckte Tool-Fehler,
   Endlosschleifen, Token-Spikes, Effort-Collapse).
2. Backtester: Spielt neue Policy-Regeln vor Aktivierung gegen historische
   Tool-Calls ab und zeigt, welche Jobs sie blockiert oder verpasst haette.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    # D12/BLOCKER: kein getrenntes flightlog.db mehr — der konsolidierte
    # ops.db-Pfad ist die einzige Autoritaet (db_paths.resolve_db mapped
    # flightlog.db -> ops.db, sobald Konsolidierung aktiv ist).
    from backend.db_paths import resolve_db as _resolve_db

    DEFAULT_DB_PATH = _resolve_db("flightlog.db")
except Exception:
    DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "flightlog.db")


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS flight_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_json TEXT DEFAULT '{}',
                args_hash TEXT NOT NULL,
                tool_ok INTEGER NOT NULL DEFAULT 1,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_flight_run ON flight_events(run_id)")
        conn.commit()
        yield conn
    finally:
        conn.close()


def record_flight_event(
    run_id: str,
    agent_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    tool_ok: bool = True,
    tokens_used: int = 0,
    db_path: Optional[str] = None,
) -> None:
    args_str = json.dumps(args or {}, sort_keys=True, ensure_ascii=False)
    args_hash = hashlib.sha256(f"{tool_name}:{args_str}".encode("utf-8")).hexdigest()[:16]
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO flight_events (run_id, agent_id, tool_name, args_json, args_hash, tool_ok, tokens_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, agent_id, tool_name, args_str, args_hash, 1 if tool_ok else 0, int(tokens_used), time.time()),
        )
        conn.commit()


def mirrored_run_ids(run_id: str, session_id: str = "") -> List[str]:
    """D13/HIGH: alle Namensräume, unter denen ein Flight-Event auffindbar sein muss.

    Der Tool-Chokepoint schreibt unter ``flightlog_run_id`` (trajectory/task ID),
    der Dispatcher frägt historisch ``current_trace_id()`` ab. Solange beide
    Keys auseinanderfallen, findet der Konsument keine Events. Diese Funktion
    liefert primäre ID + Session-ID + Trace-ID in stabiler Reihenfolge — ohne
    DB-Migration und ohne Event-Replay.
    """
    ids: List[str] = []
    for candidate in (run_id, session_id):
        value = str(candidate or "").strip()
        if value and value not in ids:
            ids.append(value)
    try:
        from backend.trace_context import current_trace_id
        trace = str(current_trace_id() or "").strip()
        if trace and trace not in ids:
            ids.append(trace)
    except Exception as exc:
        # Kein Trace-Kontext (z. B. Hintergrundjob) -> nur primärer Namensraum.
        import logging
        logging.getLogger("archon.flightlog").debug(
            "[Flightlog] Trace-ID für Mirror nicht verfügbar: %s", exc
        )
    return ids or ["no-trace"]


def mirror_flight_event_to_trace(
    run_id: str,
    agent_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    tool_ok: bool = True,
    tokens_used: int = 0,
    session_id: str = "",
    db_path: Optional[str] = None,
) -> List[str]:
    """Spiegelt ein bereits geschriebenes Flight-Event unter der Trace-ID.

    Der Produzent (`tool_runtime._record_tool_flight_event`) schreibt nur unter
    dem primären `flightlog_run_id`. Diese Funktion schreibt ZUSÄTZLICH unter
    `current_trace_id()`, damit `_guard_silent_failures()` (core_dispatcher.py,
    A4) auch ohne Parameterweiterreichung die Events sieht. Es wird nie ein
    Event gelöscht oder überschrieben; die Spiegelung ist idempotent pro Call.
    """
    primary = str(run_id or "").strip() or "no-trace"
    written: List[str] = []
    for rid in mirrored_run_ids(primary, session_id):
        if rid == primary:
            continue  # primärer Event wurde bereits vom Chokepoint geschrieben
        record_flight_event(
            run_id=rid, agent_id=agent_id, tool_name=tool_name, args=args,
            tool_ok=tool_ok, tokens_used=tokens_used, db_path=db_path,
        )
        written.append(rid)
    return written


def detect_silent_failures(
    run_id: str,
    final_status: str = "success",
    final_output: str = "",
    baseline_tokens: int = 10000,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Analysiert einen Run auf versteckte Fehler trotz 'success'-Status."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_name, args_hash, tool_ok, tokens_used FROM flight_events WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()

    events = [dict(r) for r in rows]
    flags: List[str] = []

    hidden_errors = sum(1 for e in events if e["tool_ok"] == 0)
    if hidden_errors > 0 and final_status == "success":
        flags.append(f"hidden_tool_errors:{hidden_errors}")

    # Loop detection (>= 3 identische aufeinanderfolgende Tool-Calls)
    streak = 1
    for i in range(1, len(events)):
        if events[i]["args_hash"] == events[i - 1]["args_hash"]:
            streak += 1
            if streak >= 3:
                flags.append(f"tool_loop:{events[i]['tool_name']}")
                break
        else:
            streak = 1

    total_tokens = sum(int(e["tokens_used"] or 0) for e in events)
    if baseline_tokens > 0 and total_tokens > baseline_tokens * 3:
        flags.append(f"token_spike:{total_tokens}")

    # D13/HIGH: `llm_dispatch`-Mirror-Events sind Korrelationsmarker, keine
    # echten Tool-Calls. Ein kurzer LLM-Text darf dadurch nicht falsch als
    # "effort_collapse" gelten (G-03: Effekt muss zum Produzenten passen).
    real_tool_events = [
        e for e in events
        if str(e.get("tool_name") or "") != "llm_dispatch"
    ]
    if final_status == "success" and len((final_output or "").strip()) < 20 and len(real_tool_events) > 0:
        flags.append("effort_collapse")

    return {
        "run_id": run_id,
        "silent_failure": len(flags) > 0,
        "flags": flags,
        "event_count": len(events),
        "total_tokens": total_tokens,
    }


def backtest_policy(
    policy: Dict[str, Any],
    limit: int = 500,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Spielt historische Tool-Calls aus flight_events gegen eine neue Policy ab.
    `policy`: {"blocked_tools": [...], "blocked_arg_patterns": [...], "max_tokens_per_call": int}
    """
    blocked_tools = {str(t).lower() for t in (policy.get("blocked_tools") or [])}
    patterns = [re.compile(p, re.I) for p in (policy.get("blocked_arg_patterns") or [])]
    max_tok = int(policy.get("max_tokens_per_call") or 0)

    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, agent_id, tool_name, args_json, tool_ok, tokens_used FROM flight_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    would_block: List[Dict[str, Any]] = []
    would_miss_failed: List[Dict[str, Any]] = []

    for r in rows:
        d = dict(r)
        hit_reason = None
        if d["tool_name"].lower() in blocked_tools:
            hit_reason = f"blocked_tool:{d['tool_name']}"
        elif any(pat.search(d["args_json"] or "") for pat in patterns):
            hit_reason = "blocked_arg_pattern"
        elif max_tok > 0 and int(d["tokens_used"] or 0) > max_tok:
            hit_reason = f"max_tokens:{d['tokens_used']}"

        if hit_reason:
            would_block.append({"event_id": d["id"], "run_id": d["run_id"], "tool": d["tool_name"], "reason": hit_reason})
        elif d["tool_ok"] == 0:
            would_miss_failed.append({"event_id": d["id"], "run_id": d["run_id"], "tool": d["tool_name"]})

    return {
        "evaluated_events": len(rows),
        "would_block_count": len(would_block),
        "would_block": would_block[:50],
        "would_miss_failed_count": len(would_miss_failed),
        "would_miss_failed": would_miss_failed[:50],
    }

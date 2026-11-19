# -*- coding: utf-8 -*-
"""
backend/workflow_dag_runner.py
==============================
Meilenstein 77: Agenten-Workflow-DAGs mit Fan-Out/Quorum & Resume
(hermes-workflows-Pattern).

Unterstuetzt:
- JSON-DAGs mit `agent`, `fanout` (mit Quorum) und `gate` (Human/Machine-Gate)
- Parallele Ausfuehrung bereiter Knoten
- Fingerprint-basiertes Replay-Skip-Resume ueber SQLite WAL (data/workflow_dags.db)
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "workflow_dags.db")

ExecutorFn = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_node_states (
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (run_id, node_id)
            )
        """)
        conn.commit()
        yield conn
    finally:
        conn.close()


def compute_node_fingerprint(node: Dict[str, Any], upstream_outputs: Dict[str, Any]) -> str:
    payload = json.dumps({"node": node, "upstream": upstream_outputs}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def run_workflow_dag(
    dag_def: Dict[str, Any],
    executor_fn: ExecutorFn,
    run_id: Optional[str] = None,
    gate_approvals: Optional[Dict[str, bool]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fuehrt einen Workflow-DAG aus.
    `dag_def`: {"id": "...", "nodes": [{"id": "...", "type": "agent|fanout|gate", "depends_on": [...], ...}]}
    """
    wf_id = str(dag_def.get("id") or "workflow")
    rid = run_id or f"wfrun-{secrets.token_hex(5)}"
    nodes = dag_def.get("nodes") or []
    node_map: Dict[str, Dict[str, Any]] = {str(n["id"]): n for n in nodes if n.get("id")}
    approvals = gate_approvals or {}
    now = time.time()

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO workflow_runs (run_id, workflow_id, status, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET status='running', updated_at=excluded.updated_at
            """,
            (rid, wf_id, now, now),
        )
        conn.commit()
        cached_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json FROM workflow_node_states WHERE run_id = ?",
            (rid,),
        ).fetchall()
        cached = {r["node_id"]: dict(r) for r in cached_rows}

    outputs: Dict[str, Any] = {}
    statuses: Dict[str, str] = {}

    pending = set(node_map.keys())
    while pending:
        ready = [
            nid for nid in sorted(pending)
            if all(statuses.get(dep) in ("completed", "skipped_cached") for dep in (node_map[nid].get("depends_on") or []))
        ]
        if not ready:
            # Entweder durch Gate/Fehler blockiert oder Zyklus
            break

        async def _run_one(nid: str) -> None:
            node = node_map[nid]
            deps = node.get("depends_on") or []
            upstream = {d: outputs.get(d) for d in deps}
            fp = compute_node_fingerprint(node, upstream)

            prev = cached.get(nid)
            if prev and prev["fingerprint"] == fp and prev["status"] in ("completed", "skipped_cached"):
                outputs[nid] = json.loads(prev["output_json"] or "{}")
                statuses[nid] = "skipped_cached"
                return

            ntype = str(node.get("type") or "agent").lower()
            if ntype == "gate":
                if approvals.get(nid) is True:
                    out = {"approved": True}
                    st = "completed"
                elif approvals.get(nid) is False:
                    out = {"approved": False}
                    st = "rejected"
                else:
                    out = {"awaiting_gate": True}
                    st = "awaiting_gate"
            elif ntype == "fanout":
                branches = node.get("branches") or []
                quorum = int(node.get("quorum_min") or max(1, len(branches)))
                results = await asyncio.gather(
                    *(executor_fn({**node, "branch": b}, upstream) for b in branches),
                    return_exceptions=True,
                )
                ok_results = [r for r in results if isinstance(r, dict) and r.get("status", "success") != "error"]
                if len(ok_results) >= quorum:
                    out = {"quorum_met": True, "ok_count": len(ok_results), "results": ok_results}
                    st = "completed"
                else:
                    out = {"quorum_met": False, "ok_count": len(ok_results), "required": quorum}
                    st = "failed"
            else:
                res = await executor_fn(node, upstream)
                out = res if isinstance(res, dict) else {"result": res}
                st = "failed" if out.get("status") == "error" else "completed"

            outputs[nid] = out
            statuses[nid] = st
            with _connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_id) DO UPDATE SET
                        fingerprint=excluded.fingerprint, status=excluded.status,
                        output_json=excluded.output_json, updated_at=excluded.updated_at
                    """,
                    (rid, nid, fp, st, json.dumps(out, ensure_ascii=False), time.time()),
                )
                conn.commit()

        await asyncio.gather(*(_run_one(nid) for nid in ready))
        for nid in ready:
            pending.remove(nid)

    if any(s == "failed" or s == "rejected" for s in statuses.values()):
        final_status = "failed"
    elif any(s == "awaiting_gate" for s in statuses.values()) or pending:
        final_status = "paused"
    else:
        final_status = "completed"

    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (final_status, time.time(), rid),
        )
        conn.commit()

    return {
        "run_id": rid,
        "workflow_id": wf_id,
        "status": final_status,
        "node_statuses": statuses,
        "outputs": outputs,
    }

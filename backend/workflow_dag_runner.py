# -*- coding: utf-8 -*-
"""
backend/workflow_dag_runner.py
==============================
Meilenstein 77: Agenten-Workflow-DAGs mit Fan-Out/Quorum, Edge-Bedingungen,
Datenfluss-Modi, HITL-Gates, Kanban-Synchronisation & Resume.

Unterstuetzt:
- JSON-DAGs mit `agent`, `fanout` (mit Quorum), `gate` (HITL-Gate) und `require_hitl`
- Kanten-Bedingungen (`always`, `on_success`, `on_failure`) & Datenfluss-Modi
  (`full`, `summary`, `artifact_only`, `none`)
- Parallele Ausfuehrung bereiter Knoten mit Retry- und Timeout-Limits
- Live-Kanban-Status-Synchronisation fuer materialisierte Workflow-Tasks
- Persistentes Fingerprint-basiertes Replay-Skip-Resume ueber SQLite WAL (data/workflow_dags.db)
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import datetime
import hashlib
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("archon.workflow_dag")

# D16/M4: zentrale Fehler-Zaehlung ueber die echte API in trace_context
# (delegiert an tracer.note_local_trace_error). Kein lokaler Fallback mehr.
from backend.trace_context import note_local_trace_error


async def _otel_start(name: str, run_id: str) -> Optional[str]:
    try:
        from backend.otel_tracer import tracer
        return await asyncio.to_thread(tracer.start_trace, name, run_id, "workflow_engine")
    except Exception as exc:
        note_local_trace_error("OTel-Trace-Start fehlgeschlagen", exc)
        return None


async def _otel_span(trace_id: str, **kwargs: Any) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.record_span, trace_id, **kwargs)
    except Exception as exc:
        note_local_trace_error("OTel-Span fehlgeschlagen", exc)


async def _otel_end(trace_id: str, status: str) -> None:
    try:
        from backend.otel_tracer import tracer
        await asyncio.to_thread(tracer.end_trace, trace_id, status)
    except Exception as exc:
        note_local_trace_error("OTel-Trace-Ende fehlgeschlagen", exc)


# M110: harter Deckel für Replans — ein Agent darf nicht unbegrenzt neu
# planen und damit Budget/Deadline endlos umgehen.
MAX_REPLAN_COUNT = 2

_PRIVILEGED_NODE_TOOLS = frozenset({
    "pay", "terminal", "execute_code", "filesystem", "computer_use", "mcp", "pay-cli",
})


class _LeaseGuard:
    """Geteilter Zustand zwischen Lease-Heartbeat und DAG-Hauptausfuehrung.

    `lost` bedeutet: ein anderer Worker hat den Claim uebernommen -> die
    Hauptausfuehrung muss sofort abbrechen (fail-closed).
    `suspended` bedeutet: das Run wurde bewusst an einem HITL-Gate
    suspendiert -> der Heartbeat darf das nicht als Lease-Verlust melden.
    """

    def __init__(self) -> None:
        self.lost = asyncio.Event()
        self.suspended = asyncio.Event()


def _claim_kernel_run(
    kernel: Any,
    run_id: str,
    dag_fingerprint: str,
    fencing_token: Optional[str] = None,
) -> Dict[str, Any]:
    """CAS-Claim mit erlaubtem Retry nach FAILED (sonst fail-closed).

    FAILED ist im Kernel terminal, aber ein expliziter Resume eines
    fehlgeschlagenen Runs ist zulaessig (Transition FAILED -> PENDING ->
    RUNNING). COMPLETED/CANCELLED bleiben strikt terminal.
    """
    from backend.durable_execution_kernel import PENDING, FAILED

    claim = kernel.claim(
        run_id, ttl_seconds=300,
        dag_fingerprint=dag_fingerprint[:2000],
        fencing_token=fencing_token or None,
    )
    if claim.get("claimed") or str(claim.get("state") or "") != FAILED:
        return claim
    current = kernel.get_state(run_id)
    current_token = str((current or {}).get("fencing_token") or "")
    if not current_token:
        return claim
    try:
        kernel.transition(run_id, PENDING, current_token, reason="retry_after_failure")
        return kernel.claim(
            run_id, ttl_seconds=300,
            dag_fingerprint=dag_fingerprint[:2000],
            fencing_token=current_token,
        )
    except Exception as exc:
        logger.debug("[WorkflowDAG] Retry-Transition %s nicht moeglich: %s", run_id, exc)
        return claim


def _suspend_run_at_gate(
    run_id: str,
    wf_id: str,
    node_id: str,
    statuses: Dict[str, str],
    outputs: Dict[str, Any],
    fencing_token: str = "",
    lease_guard: Optional[_LeaseGuard] = None,
) -> Dict[str, Any]:
    """Produktivaufrufer von ``durable_kernel.suspend()``.

    Ein HITL-Gate ist kein "wir warten mal kurz": der Run wird mit Checkpoint
    in den Zustand SUSPENDED ueberfuehrt und die Lease freigegeben, damit ein
    anderer Worker nach der Entscheidung sauber resume darf.
    """
    try:
        from backend.durable_execution_kernel import durable_kernel, SUSPENDED

        existing = durable_kernel.get_state(run_id)
        if existing and str(existing.get("state")) == SUSPENDED:
            if lease_guard is not None and fencing_token:
                lease_guard.suspended.set()
            return {"suspended": True, "already": True, "run_id": run_id, "gate_node_id": node_id}

        token = fencing_token or str((existing or {}).get("fencing_token") or "")
        claim = _claim_kernel_run(durable_kernel, run_id, wf_id, token or None)
        if not claim.get("claimed"):
            return {"suspended": False, "reason": claim.get("reason", "claim_failed"), "gate_node_id": node_id}
        token = str(claim["fencing_token"])

        checkpoint_step = sum(
            1 for st in statuses.values() if st in ("completed", "skipped_cached")
        )
        try:
            state_json = json.loads(json.dumps({
                "workflow_id": wf_id,
                "gate_node_id": node_id,
                "node_statuses": statuses,
                "outputs": outputs,
            }, ensure_ascii=False, default=str))
        except Exception:
            state_json = {"workflow_id": wf_id, "gate_node_id": node_id}

        durable_kernel.suspend(
            run_id, token, checkpoint_step, state_json,
            reason=f"hitl_gate:{node_id}",
        )
        # Keine aktive Lease, waehrend ein Mensch entscheidet.
        durable_kernel.release(run_id, token)
        if lease_guard is not None and fencing_token:
            lease_guard.suspended.set()
        return {
            "suspended": True,
            "run_id": run_id,
            "gate_node_id": node_id,
            "checkpoint_step": checkpoint_step,
        }
    except Exception as exc:
        logger.debug("[WorkflowDAG] Durable-Suspend am Gate '%s' fehlgeschlagen: %s", node_id, exc)
        return {"suspended": False, "error": str(exc)[:300], "gate_node_id": node_id}


def validate_dag_def(
    dag_def: Dict[str, Any],
    *,
    now: Optional[float] = None,
    max_nodes: int = 100,
    require_cap: bool = True,
) -> Dict[str, Any]:
    """M110 Pre-Execution Plan Validator.

    Prüft Schema, Zyklen, Input-Mapping, Budget, Deadline, RBAC/HITL und
    Replan-Count, BEVOR irgendein Node ausgeführt wird. Fehler sind immer
    `valid=False` mit klarer Diagnose (nie stilles Weiterlaufen).
    """
    errors: List[str] = []
    nodes = dag_def.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return {"valid": False, "errors": ["DAG enthält keine Nodes."]}
    if len(nodes) > max_nodes:
        errors.append(f"Zu viele Nodes: {len(nodes)} > {max_nodes}")

    node_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            errors.append("Node ohne id oder falscher Typ.")
            continue
        nid = str(n["id"])
        if nid in node_map:
            errors.append(f"Doppelte Node-ID: {nid}")
        node_map[nid] = n

    edge_map = _extract_edge_map(dag_def)
    for src, targets in edge_map.items():
        if src not in node_map:
            errors.append(f"Kante von unbekannter Quelle: {src}")
        for e in targets or []:
            dst = str(e.get("to") or "")
            if dst and dst not in node_map:
                errors.append(f"Kante zu unbekanntem Ziel: {dst}")

    # Zyklus-Erkennung via Kahn — vor dem Start, nicht als Restgröße.
    deps: Dict[str, set] = {}
    for nid, node in node_map.items():
        deps[nid] = {
            str(d) for d in _all_dependencies_for_node(node, edge_map.get(nid, []))
        }
        for d in deps[nid]:
            if d not in node_map:
                errors.append(f"Unbekannte Abhängigkeit '{d}' bei Node '{nid}'")
    remaining = set(node_map)
    progress = True
    while remaining and progress:
        progress = False
        for nid in sorted(remaining):
            if not (deps.get(nid, set()) & remaining):
                remaining.discard(nid)
                progress = True
    if remaining:
        errors.append(f"Zyklus in DAG erkannt: {', '.join(sorted(remaining))}")

    # Input-Mapping: {{upstream.<node>.<field>}} nur aus deklarierten Deps.
    ref_re = re.compile(r"\{\{\s*upstream\.([A-Za-z0-9_-]+)\.")
    for nid, node in node_map.items():
        blob = json.dumps(node, ensure_ascii=False)
        for ref in set(ref_re.findall(blob)):
            if ref not in deps.get(nid, set()):
                errors.append(f"Node '{nid}' referenziert '{ref}', das keine deklarierte Abhängigkeit ist.")

    # D13/HIGH: harte Cash-Obergrenze, keine 15 % Toleranz. Fehlender Run-Cap
    # ist `valid=False` (kein stilles Ueberspringen der Budgetpruefung).
    cap = dag_def.get("max_budget_eur")
    if cap is None:
        if require_cap:
            errors.append("max_budget_eur fehlt — Run-Cap ist Pflicht (fail-closed).")
    else:
        try:
            run_cap = float(cap)
            if run_cap <= 0.0:
                errors.append("max_budget_eur muss > 0 sein.")
            total = sum(
                float(n.get("max_budget_eur") or 0.0)
                for n in node_map.values()
            )
            if total > run_cap + 1e-6:
                errors.append(
                    f"Node-Budgets ({total:.2f} EUR) überschreiten Run-Cap ({run_cap:.2f} EUR)."
                )
        except (TypeError, ValueError):
            errors.append("Ungültiger max_budget_eur-Wert.")

    # Deadline
    deadline = dag_def.get("deadline")
    if deadline:
        try:
            dl = datetime.datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            if dl.timestamp() <= (now if now is not None else time.time()):
                errors.append("Deadline liegt in der Vergangenheit.")
        except (TypeError, ValueError):
            errors.append("Ungültige Deadline.")

    # RBAC/HITL: privilegierte Tools brauchen ein Gate.
    has_gate = any(
        str(n.get("type") or "").lower() in ("gate", "require_hitl") or n.get("require_hitl")
        for n in node_map.values()
    )
    for nid, node in node_map.items():
        tool = str(node.get("tool") or node.get("plugin_id") or "")
        if any(tool.lower().startswith(p) for p in _PRIVILEGED_NODE_TOOLS):
            if not has_gate and not node.get("require_hitl"):
                errors.append(f"Node '{nid}' nutzt privilegiertes Tool '{tool}' ohne HITL-Gate.")

    # Replan-Cap
    replan_count = int(dag_def.get("_replan_count") or 0)
    if replan_count > MAX_REPLAN_COUNT:
        errors.append(f"replan_count {replan_count} überschreitet den Deckel ({MAX_REPLAN_COUNT}).")

    return {"valid": not errors, "errors": errors, "node_count": len(node_map)}


def request_dag_replan(
    run_id: str,
    new_dag_def: Dict[str, Any],
    reason: str,
    db_path: Optional[str] = None,
    trajectory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Kontrollierter Replan-Pfad — Cap pro TRAJECTORY, nicht pro run_id.

    D13/HIGH: jeder Replan geht durch `trajectory_budget.reserve_replan()`;
    ein neuer run_id erbt den Zaehler ueber-root_ticket_id. Replan #3 liefert
    `replan_cap_reached` + `blocked` + Audit-Event.
    """
    existing = get_workflow_run(run_id, db_path=db_path)
    if not existing:
        return {"allowed": False, "reason": "run_not_found"}
    from backend.trajectory_budget import (
        normalize_trajectory_id, reserve_replan,
    )
    old_dag = existing.get("dag") or {}
    tid = normalize_trajectory_id(
        trajectory_id or old_dag.get("trajectory_id"),
        old_dag.get("root_ticket_id") or run_id,
    )
    reservation = reserve_replan(
        tid, run_id=run_id, dag_def=old_dag, reason=reason, db_path=db_path,
    )
    if not reservation.get("allowed", False):
        with _connect(db_path) as conn:
            conn.execute(
                "UPDATE workflow_runs SET status = 'blocked', updated_at = ? WHERE run_id = ?",
                (time.time(), run_id),
            )
            conn.commit()
        try:
            from backend.trajectory_budget import _audit
            _audit(tid, f"replan_cap_reached via {run_id}: {reason[:120]}", run_id)
        except Exception:
            logger.error("[WorkflowDAG] replan_cap_reached Audit fehlgeschlagen für %s", run_id)
        return {
            "allowed": False, "reason": "replan_cap_reached",
            "replan_count": int(reservation.get("replan_count") or MAX_REPLAN_COUNT),
            "status": "blocked", "needs_human": True, "trajectory_id": tid,
        }
    candidate = dict(new_dag_def or old_dag or {})
    candidate["_replan_count"] = int(reservation["replan_count"])
    candidate["_replan_reason"] = str(reason or "")[:500]
    candidate["trajectory_id"] = tid
    candidate.setdefault("root_ticket_id", old_dag.get("root_ticket_id") or run_id)
    validation = validate_dag_def(candidate)
    if not validation["valid"]:
        return {"allowed": False, "reason": "invalid_plan",
                "errors": validation["errors"], "trajectory_id": tid}
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE workflow_runs SET dag_json = ?, updated_at = ? WHERE run_id = ?",
            (json.dumps(candidate, ensure_ascii=False), time.time(), run_id),
        )
        conn.commit()
    return {"allowed": True, "replan_count": int(reservation["replan_count"]),
            "dag_def": candidate, "trajectory_id": tid}


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "workflow_dags.db")
_INITIAL_DEFAULT_DB_PATH = DEFAULT_DB_PATH

ExecutorFn = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]

TERMINAL_NODE_STATES = {"completed", "skipped_cached", "skipped_condition", "failed", "rejected"}
SUCCESS_NODE_STATES = {"completed", "skipped_cached"}
FAILURE_NODE_STATES = {"failed", "rejected"}

# Per-run_id-Locks: verhindert doppelte/parallele Ausfuehrung desselben Runs.
# Erzeugung neuer Locks geschuetzt ueber threading.Lock (Sync-Kontext, async-sicher).
_RUN_LOCKS: Dict[str, asyncio.Lock] = {}
_locks_guard = threading.Lock()
_MAX_RUN_LOCKS = 512


def _get_run_lock(run_id: str) -> asyncio.Lock:
    with _locks_guard:
        lock = _RUN_LOCKS.get(run_id)
        if lock is None:
            if len(_RUN_LOCKS) >= _MAX_RUN_LOCKS:
                for k in list(_RUN_LOCKS.keys()):
                    if not _RUN_LOCKS[k].locked():
                        _RUN_LOCKS.pop(k, None)
                        if len(_RUN_LOCKS) < _MAX_RUN_LOCKS:
                            break
            lock = asyncio.Lock()
            _RUN_LOCKS[run_id] = lock
        return lock


def _resolve_dag_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return db_path
    if DEFAULT_DB_PATH != _INITIAL_DEFAULT_DB_PATH:
        return DEFAULT_DB_PATH
    try:
        from backend.db_paths import resolve_db
        return resolve_db("workflow_dags.db")
    except Exception:
        return DEFAULT_DB_PATH


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = _resolve_dag_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                dag_json TEXT DEFAULT '{}',
                gate_approvals_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_node_states (
                run_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT DEFAULT '{}',
                updated_at REAL NOT NULL
            )
        """) if False else conn.execute("""
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
        # Sichere Migration fuer bestehende workflow_dags.db ohne dag_json / gate_approvals_json
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        if "dag_json" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN dag_json TEXT DEFAULT '{}'")
        if "gate_approvals_json" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN gate_approvals_json TEXT DEFAULT '{}'")
        if "total_cost_usd" not in run_cols:
            conn.execute("ALTER TABLE workflow_runs ADD COLUMN total_cost_usd REAL DEFAULT 0.0")
        conn.commit()
        yield conn
    finally:
        conn.close()


def compute_node_fingerprint(node: Dict[str, Any], upstream_outputs: Dict[str, Any]) -> str:
    # Transiente Laufzeit-Metadaten fuer stabilen Cache-Fingerprint ignorieren
    stable_node = {
        k: v for k, v in (node or {}).items()
        if k not in ("kanban_task_id", "_edge_inputs")
    }
    payload = json.dumps({"node": stable_node, "upstream": upstream_outputs}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_edge_map(dag_def: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Ordnet jedem Ziel-Knoten seine eingehenden Kanten zu."""
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    for edge in (dag_def.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or edge.get("source") or "").strip()
        dst = str(edge.get("to") or edge.get("target") or "").strip()
        if not src or not dst:
            continue
        incoming.setdefault(dst, []).append({
            "from": src,
            "to": dst,
            "condition": str(edge.get("condition") or "always").strip().lower(),
            "data_mode": str(edge.get("data_mode") or "full").strip().lower(),
            "label": str(edge.get("label") or "").strip(),
        })
    return incoming


def _all_dependencies_for_node(node: Dict[str, Any], incoming_edges: List[Dict[str, Any]]) -> List[str]:
    deps: List[str] = []
    for d in (node.get("depends_on") or []):
        ds = str(d).strip()
        if ds and ds not in deps:
            deps.append(ds)
    for e in incoming_edges:
        src = e["from"]
        if src and src not in deps:
            deps.append(src)
    return deps


def _edge_condition_matches(condition: str, parent_status: str) -> bool:
    cond = (condition or "always").strip().lower()
    if cond in ("on_failure", "failed", "error"):
        return parent_status in FAILURE_NODE_STATES
    if cond in ("on_success", "success"):
        return parent_status in SUCCESS_NODE_STATES
    # Default "always": bereit sobald der Upstream IRGENDEINEN Terminal-Status
    # erreicht hat (completed, skipped_cached, failed, rejected, skipped_condition)
    return parent_status in TERMINAL_NODE_STATES


def _raw_output_status(raw_out: Any) -> str:
    """F-045: Status aus einem Nicht-Dict-Raw-Output ableiten (fail-closed).

    ``None`` und leere/whitespace Strings sind keine Erfolgsergebnisse: ein
    Executor, der nichts liefert, darf nicht still zu ``success`` werden.
    """
    if raw_out is None:
        return "error"
    if isinstance(raw_out, str) and not raw_out.strip():
        return "error"
    return "success"


def _shape_upstream_output(raw_out: Any, data_mode: str) -> Any:
    mode = (data_mode or "full").strip().lower()
    if mode == "none":
        if isinstance(raw_out, dict):
            return {"status": raw_out.get("status", "success")}
        return {"status": _raw_output_status(raw_out)}
    if mode == "artifact_only":
        if isinstance(raw_out, dict):
            return {
                "status": raw_out.get("status", "success"),
                "artifacts": raw_out.get("artifacts") or raw_out.get("files") or [],
                "obsidian_path": raw_out.get("obsidian_path") or "",
            }
        return {"status": _raw_output_status(raw_out), "artifacts": []}
    if mode == "summary":
        if isinstance(raw_out, dict):
            txt = str(raw_out.get("content") or raw_out.get("result") or json.dumps(raw_out, ensure_ascii=False))
            return {
                "status": raw_out.get("status", "success"),
                "summary": txt[:1200],
            }
        return {
            "status": _raw_output_status(raw_out),
            "summary": str(raw_out or "")[:1200],
        }
    return raw_out


def _update_kanban_task_status(
    task_id: Optional[str],
    status: str,
    *,
    result: Optional[str] = None,
    block_kind: Optional[str] = None,
    event_kind: Optional[str] = None,
    event_payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not task_id:
        return
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Ein transienter SQLite-Lock (z. B. paralleler Task-Write) darf den Kanban-Sync
    # NICHT still schlucken — sonst bleibt ein wartender Gate-Task sichtbar falsch.
    # Deshalb: 1 Retry mit kurzem Backoff, erst danach sichtbarer DEBUG-Log.
    last_exc: Exception = RuntimeError("nicht ausgefuehrt")
    for _attempt in range(2):
        try:
            from backend.operations_api import _get_kanban_connection

            conn = _get_kanban_connection()
            try:
                if status == "in_progress":
                    conn.execute(
                        "UPDATE tasks SET status = 'in_progress', started_at = COALESCE(started_at, ?) WHERE id = ?",
                        (now_iso, task_id),
                    )
                elif status == "done":
                    conn.execute(
                        "UPDATE tasks SET status = 'done', completed_at = ?, result = ?, block_kind = NULL WHERE id = ?",
                        (now_iso, (result or "")[:12000], task_id),
                    )
                elif status in ("blocked", "failed", "review"):
                    conn.execute(
                        "UPDATE tasks SET status = ?, result = COALESCE(?, result), block_kind = COALESCE(?, block_kind) WHERE id = ?",
                        (status, (result or "")[:12000] if result is not None else None, block_kind, task_id),
                    )
                else:
                    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))

                if event_kind:
                    conn.execute(
                        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                        (task_id, event_kind, json.dumps(event_payload or {}, ensure_ascii=False), now_iso),
                    )
                conn.commit()
            finally:
                conn.close()
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if _attempt == 0:
                time.sleep(0.5)
    if last_exc is not None:
        logger.debug(f"[WorkflowDAG] Kanban-Sync fuer {task_id} fehlgeschlagen (2 Versuche): {last_exc}")

    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("kanban_updated", {"action": "workflow_node", "task_id": task_id, "status": status})
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] broadcast_event fuer {task_id} fehlgeschlagen (Fallback): {exc}")


def _register_hitl_gate_decision(
    run_id: str,
    wf_id: str,
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Optional[str]:
    node_id = str(node.get("id") or "")
    # Doppelte HITL-Decisions verhindern: falls fuer (run_id, node_id) bereits
    # eine Decision existiert, diese wiederverwenden statt neu anzulegen.
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT output_json FROM workflow_node_states WHERE run_id = ? AND node_id = ?",
                (run_id, node_id),
            ).fetchone()
        if row:
            prev_out = json.loads(row["output_json"] or "{}")
            prev_id = prev_out.get("decision_id")
            if prev_id:
                return str(prev_id)
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] HITL-Decision-Dedupe-Check fehlgeschlagen: {exc}")
    try:
        from archon.routers.decisions import create_decision
        title = f"Workflow-Freigabe: {node.get('title') or node.get('id')} ({run_id})"
        upstream_preview = json.dumps(upstream, ensure_ascii=False)[:1500]
        deci = create_decision(
            "workflow_hitl_gate",
            title,
            f"Workflow '{wf_id}' (Run `{run_id}`) wartet am Knoten `{node.get('id')}` auf Freigabe.\n\nVorlauf-Ergebnisse:\n{upstream_preview}",
            ref_id=f"{run_id}:{node.get('id')}",
        )
        if isinstance(deci, dict):
            return str(deci.get("id") or deci.get("task_id") or "")
    except Exception as exc:
        logger.debug(f"[WorkflowDAG] HITL-Decision konnte nicht angelegt werden: {exc}")
    return None


async def _execute_research_dag_node(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    """Nativer Research-Knoten: ruft research_engine_v2 (echte Quellen) statt
    eines Prompt-Agenten auf. P1/Content B1: vorher war 'Research' nur ein
    LLM-Auftrag ohne Triangulation, Quellenbewertung oder Zitationen.

    Laeuft in einem Thread, weil die Research-Engine synchron HTTP + LLM macht.
    """
    query = str(node.get("query") or node.get("prompt") or "").strip()
    # Upstream-Kontext (z. B. Quell-Notizen der Campaign) anhaengen.
    extra = []
    for _nid, up in (upstream or {}).items():
        if isinstance(up, dict):
            txt = str(up.get("content") or up.get("synthesis") or "").strip()
            if txt:
                extra.append(txt[:2000])
    if extra:
        query = f"{query}\n\nZusaetzlicher Kontext:\n" + "\n---\n".join(extra[:4])

    try:
        import research_engine_v2
        result = await asyncio.to_thread(
            research_engine_v2.run_research_mission_v2,
            query,
            max_rounds=max(1, min(4, int(node.get("max_rounds", 2)))),
            max_pages=max(1, min(10, int(node.get("max_pages", 4)))),
            depth=max(1, min(5, int(node.get("depth", 3)))),
        )
    except Exception as exc:
        logger.error("[WorkflowDAG] Research-Knoten fehlgeschlagen: %s", exc, exc_info=exc)
        return {
            "status": "error",
            "content": f"Research fehlgeschlagen: {exc}",
            "agent_id": "research_scout",
            "node_id": node.get("id"),
        }

    synthesis = str(result.get("synthesis") or "")
    # research_engine_v2 liefert 'triangulation_verdict'; alte Mocks/Fixtures
    # nutzen 'verdict'. Beide Keys werden unterstuetzt (P2-Verdict-Fix).
    verdict = str(result.get("triangulation_verdict") or result.get("verdict") or "")
    sources = result.get("sources") or []
    source_lines = []
    for idx, src in enumerate(sources[:12], start=1):
        if not isinstance(src, dict):
            continue
        title = str(src.get("title") or src.get("name") or "")[:120]
        url = str(src.get("url") or src.get("link") or "")[:200]
        domain = str(src.get("domain") or "")
        source_lines.append(f"[{idx}] {title} — {domain} — {url}")
    ok = bool(synthesis) and result.get("status") != "no_evidence"

    # Batch D: Dossier aus dem strukturierten v2-Ergebnis schreiben (gleicher
    # Pfad wie run_research_mission_reflect). Fehler duerfen den Research-Knoten
    # nicht scheitern lassen.
    dossier_path = ""
    if ok and str(result.get("status")) == "success":
        try:
            dossier_path = str(
                research_engine_v2.save_dossier_for_result(result, query) or ""
            )
        except Exception as exc:
            logger.debug("[WorkflowDAG] Research-Dossier nicht gespeichert: %s", exc)

    content = (
        "### Research-Synthese (quellenbasiert)\n"
        f"{synthesis or '(keine Synthese — Status: ' + str(result.get('status')) + ')'}\n\n"
        f"### Verifikationsstatus\n{verdict}\n\n"
        f"### Belegquellen ({len(sources)})\n" + "\n".join(source_lines)
        + (f"\n\n### Research-Dossier\n{dossier_path}" if dossier_path else "")
    )
    return {
        "status": "success" if ok else "error",
        "content": content,
        "synthesis": synthesis,
        "sources": sources,
        "verdict": verdict,
        "total_sources": len(sources),
        "dossier_path": dossier_path,
        "agent_id": "research_scout",
        "node_id": node.get("id"),
    }


def _node_budget_ok(node: Dict[str, Any], res: Dict[str, Any], model: str, phase: str) -> bool:
    """D13/MED: kumulierter Node-Verbrauch vor JEDEM Folge-Dispatch pruefen."""
    used = max(0, int(res.get("input_tokens") or 0) + int(res.get("output_tokens") or 0))
    tok_cap = int(float(node.get("token_budget") or 0))
    if tok_cap > 0 and used > tok_cap:
        logger.error("[WorkflowDAG] Node-Budget %s: %s/%s Tokens (%s)", phase, used, tok_cap, node.get("id"))
        return False
    cap = node.get("max_budget_eur") or node.get("_dag_max_budget_eur")
    if cap:
        try:
            from backend.llm_kernel import estimate_model_cost_usd
            from backend.role_budget_engine import USD_TO_EUR_RATE
            cost_eur = float(estimate_model_cost_usd(
                model or "deepseek/deepseek-chat",
                max(0, int(res.get("input_tokens") or 0)),
                max(0, int(res.get("output_tokens") or 0)),
            )) * USD_TO_EUR_RATE
            if cost_eur > float(cap) + 1e-6:
                logger.error("[WorkflowDAG] Node-EUR-Cap %s: %.4f/%.4f (%s)", phase, cost_eur, float(cap), node.get("id"))
                return False
        except Exception:
            return False
    tid = str(node.get("_trajectory_id") or "")
    if tid.startswith("traj-"):
        try:
            from backend.trajectory_budget import get_trajectory
            row = get_trajectory(tid)
            if row and str(row.get("state") or "") == "blocked":
                return False
            if row and used + int(row.get("tokens_used") or 0) > int(row.get("max_tokens") or 0):
                return False
        except Exception:
            return False
    return True


def _blocked_node_result(node: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "status": "error", "error": reason, "block_kind": "node_budget",
        "needs_human": True, "failure_reason": reason,
        "node_id": node.get("id"),
        "agent_id": str(node.get("agent_id") or ""),
        "content": "", "cost_usd": 0.0,
    }


async def _dispatch_with_node_budget(
    node: Dict[str, Any], res: Dict[str, Any], base_model: str, **kwargs: Any
) -> tuple:
    phase = str(kwargs.pop("_phase", "dispatch"))
    if not _node_budget_ok(node, res, str(kwargs.get("model") or base_model), phase):
        return _blocked_node_result(node, "NODE_TOKEN_BUDGET_EXCEEDED"), True
    import core_dispatcher
    out = await core_dispatcher.dispatch_to_omniroute_or_container(**kwargs)
    return out, False


async def default_agent_node_executor(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Standard-Executor fuer DAG-Knoten: loest Agenten-Profil auf, reicht
    Upstream-Outputs weiter, ruft core_dispatcher auf und synchronisiert Kanban."""
    import core_dispatcher
    from backend.agent_aliases import resolve_agent_id

    raw_agent = str(node.get("agent_id") or node.get("branch") or "default").strip()
    agent_id = resolve_agent_id(raw_agent)
    kanban_task_id = node.get("kanban_task_id")

    # Agenten-Profil laden
    prof: Dict[str, Any] = {}
    try:
        from archon.core.profiles import api_get_hermes_profiles
        profiles = await asyncio.to_thread(api_get_hermes_profiles) or []
        prof = next((p for p in profiles if p.get("id") == agent_id), {})
    except Exception:
        prof = {}

    node_type = str(node.get("type") or "agent").strip().lower()
    kanban_task_id = node.get("kanban_task_id")

    # P1/Content B1: nativer Research-Knoten mit echter Quellen-Triangulation.
    if node_type == "research":
        return await _execute_research_dag_node(node, upstream)

    # Standardisierte Node-Plugins ("VST-Schnittstelle": ffmpeg, kinocut, tts, suno, image_gen, calendar_publish, 3rd-Party)
    from backend.workflow_node_plugins import is_workflow_node_plugin, execute_workflow_node_plugin
    if is_workflow_node_plugin(node_type):
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "in_progress",
            event_kind="workflow_node_started",
            event_payload={"node_id": node.get("id"), "type": node_type},
        )
        try:
            pres = await execute_workflow_node_plugin(node_type, node, upstream)
        except Exception as pexc:
            logger.error("[WorkflowDAG] Node-Plugin '%s' abgestuerzt: %s", node_type, pexc, exc_info=pexc)
            pres = {"status": "error", "error": f"Plugin-Ausfuehrungsfehler: {pexc}", "content": ""}
        p_err = str(pres.get("status") or "success").lower() in ("error", "failed", "blocked")
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "blocked" if p_err else "done",
            result=str(pres.get("content") or pres.get("error") or ""),
            block_kind="workflow_error" if p_err else None,
            event_kind="workflow_node_failed" if p_err else "workflow_node_completed",
            event_payload={"node_id": node.get("id"), "type": node_type, "status": pres.get("status", "success")},
        )
        return {
            **pres,
            "node_id": node.get("id"),
            "agent_id": str(node.get("agent_id") or node_type),
            "kanban_task_id": kanban_task_id,
        }

    # Nativer Media-Render / Clip-Matrix Knoten (Content-Maschine im DAG)
    if node_type in ("media_render", "clip_matrix"):
        await asyncio.to_thread(
            _update_kanban_task_status,
            kanban_task_id,
            "in_progress",
            event_kind="workflow_node_started",
            event_payload={"node_id": node.get("id"), "type": node_type},
        )
        try:
            from backend.content_machine import generate_video_clip_matrix
            mcfg = dict(node.get("media_config") or {})
            up_texts = []
            for _dv in (upstream or {}).values():
                if isinstance(_dv, dict):
                    up_texts.append(str(_dv.get("content") or _dv.get("summary") or ""))
                elif _dv:
                    up_texts.append(str(_dv))
            script_text = str(mcfg.get("script") or "\n\n".join(t for t in up_texts if t) or node.get("prompt") or node.get("title") or "")
            campaign_id = str(mcfg.get("campaign_id") or node.get("workflow_id") or "wf_media")
            target_channels = mcfg.get("target_channels")
            if not isinstance(target_channels, list) or not target_channels:
                target_channels = [str(mcfg.get("target_platform") or node.get("channel") or "youtube_shorts")]
            matrix = await generate_video_clip_matrix(
                campaign_id=campaign_id,
                script_text=script_text,
                clip_count=int(mcfg.get("clip_count") or 3),
                target_channels=target_channels,
                dry_run=bool(mcfg.get("dry_run", False)),
            )
            rendered_md = json.dumps(matrix, ensure_ascii=False, indent=2)
            await asyncio.to_thread(
                _update_kanban_task_status,
                kanban_task_id,
                "done",
                result=rendered_md,
                event_kind="workflow_node_completed",
                event_payload={"node_id": node.get("id"), "type": node_type, "status": "success"},
            )
            return {
                "status": "success",
                "node_id": node.get("id"),
                "agent_id": str(node.get("agent_id") or "media_engine"),
                "content": rendered_md,
                "media_matrix": matrix,
                "kanban_task_id": kanban_task_id,
            }
        except Exception as mexc:
            await asyncio.to_thread(
                _update_kanban_task_status,
                kanban_task_id,
                "blocked",
                result=str(mexc),
                block_kind="workflow_error",
                event_kind="workflow_node_failed",
                event_payload={"node_id": node.get("id"), "type": node_type, "error": str(mexc)},
            )
            return {
                "status": "error",
                "node_id": node.get("id"),
                "error": str(mexc),
                "content": "",
                "kanban_task_id": kanban_task_id,
            }

    agent_name = str(prof.get("person_name") or prof.get("name") or agent_id)
    role = str(prof.get("role") or prof.get("category") or "Fach-Spezialist")
    system_prompt = str(
        prof.get("system_prompt")
        or prof.get("prompt")
        or f"Du bist {agent_name} in Archon OS. Bearbeite deinen Workflow-Schritt praezise und strukturiert."
    )
    model = str(node.get("model") or prof.get("model") or "deepseek/deepseek-chat").strip()
    # Punkt 3.2.6: Cheap-First -> Frontier-Escalation pro Node
    _esc_model = str(node.get("escalation_model") or "").strip()
    reasoning_level = str(node.get("reasoning_effort") or "medium").strip()

    # Optionale Markenstimme (config/voice.md) automatisch fuer Content-/Marketing-Schritte injizieren
    _voice_block = ""
    _channel_hint = str(node.get("channel") or "").strip().lower()
    _is_content_node = bool(
        _channel_hint
        or node.get("quality_gate")
        or any(
            kw in f"{agent_id} {role} {node.get('title', '')}".lower()
            for kw in ("writer", "content", "linkedin", "youtube", "tiktok", "shorts", "social", "storyteller", "newsletter", "blog")
        )
    )
    if _is_content_node:
        try:
            from archon.core.runtime import APP_ROOT
            _voice_path = os.path.join(APP_ROOT, "config", "voice.md")
            if os.path.isfile(_voice_path):
                with open(_voice_path, "r", encoding="utf-8", errors="ignore") as _vf:
                    _voice_txt = _vf.read(3000).strip()
                if _voice_txt:
                    _voice_block = f"\n\n[BRAND VOICE & STIL-VORGABEN (config/voice.md)]\n{_voice_txt}"
        except OSError as _vexc:
            logger.debug("[WorkflowDAG] config/voice.md nicht lesbar: %s", _vexc)

    # Prompt inkl. Upstream-Kontext & Guardrails aufbauen
    sections: List[str] = []
    node_title = str(node.get("title") or node.get("id") or "Workflow-Schritt")
    sections.append(f"WORKFLOW-SCHRITT: {node_title}")
    if node.get("prompt"):
        sections.append(str(node["prompt"]))
    if node.get("expected_output"):
        sections.append(f"[ERWARTETES ERGEBNIS]\n{node['expected_output']}")
    if node.get("allowed_tools"):
        _allowed_list = [str(t) for t in node["allowed_tools"] if str(t).strip()]
        sections.append(
            f"[ERLAUBTE TOOLS]\n{', '.join(_allowed_list)}\n"
            "Wenn du ein Tool ausfuehren musst, antworte exakt mit einem JSON-Objekt: "
            '{"tool_call": {"name": "<tool_name>", "args": {...}}}'
        )
    if node.get("forbidden_actions"):
        sections.append("[VERBOTEN / GUARDRAILS]\n- " + "\n- ".join(str(f) for f in node["forbidden_actions"]))
    if node.get("map_item") is not None:
        item_val = node["map_item"]
        item_str = json.dumps(item_val, ensure_ascii=False) if isinstance(item_val, (dict, list)) else str(item_val)
        sections.append(f"[AKTUELLER MAP-EINTRAG ({int(node.get('map_index', 0)) + 1}/{int(node.get('map_total', 1))})]\n{item_str}")
        if node.get("prompt") and "{{item}}" in str(node.get("prompt")):
            for p_idx, p_sec in enumerate(sections):
                if "{{item}}" in p_sec:
                    sections[p_idx] = p_sec.replace("{{item}}", item_str)
    if upstream:
        up_blocks = []
        for dep_id, dep_val in upstream.items():
            if isinstance(dep_val, dict):
                txt = dep_val.get("content") or dep_val.get("summary") or dep_val.get("result") or json.dumps(dep_val, ensure_ascii=False)
            else:
                txt = str(dep_val)
            up_blocks.append(f"### Vorlauf-Schritt `{dep_id}`:\n{str(txt)[:4000]}")
        sections.append("[UPSTREAM-ERGEBNISSE AUS VORHERIGEN SCHRITTEN]\n" + "\n\n".join(up_blocks))

    full_prompt = "\n\n".join(sections)
    eff_system_prompt = system_prompt + _voice_block

    await asyncio.to_thread(
        _update_kanban_task_status,
        kanban_task_id,
        "in_progress",
        event_kind="workflow_node_started",
        event_payload={"node_id": node.get("id"), "agent_id": agent_id, "model": model},
    )

    res, _dispatch_blocked = await _dispatch_with_node_budget(
        node, {"input_tokens": 0, "output_tokens": 0}, model,
        agent_id=agent_id,
        agent_name=agent_name,
        prompt=full_prompt,
        role=role,
        system_prompt=eff_system_prompt,
        model=model,
        reasoning_level=reasoning_level,
        task_id=str(kanban_task_id or node.get("id") or ""),
        _phase="initial_dispatch",
    )
    if _dispatch_blocked:
        await asyncio.to_thread(
            _update_kanban_task_status, kanban_task_id, "blocked",
            result=str(res.get("error")), block_kind="node_budget",
            event_kind="workflow_node_failed",
        )
        return res

    status_raw = str(res.get("status") or "success").lower()
    content = str(res.get("content") or "").strip()
    is_error = status_raw in ("error", "failed", "blocked") or (not content and bool(res.get("error")))

    # Multi-Turn Tool-Calling Loop ueber zentralen ToolRuntime-Chokepoint
    tool_trace: List[Dict[str, Any]] = []
    allowed_tool_set = {str(t).strip() for t in (node.get("allowed_tools") or []) if str(t).strip()}
    if not is_error and content and allowed_tool_set:
        max_turns = max(1, min(6, int(node.get("max_turns") or 3)))
        turn_prompt = full_prompt
        for _turn in range(max_turns):
            _tc = None
            try:
                _stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
                if _stripped.startswith("{") and '"tool_call"' in _stripped:
                    _parsed_tc = json.loads(_stripped)
                    if isinstance(_parsed_tc, dict) and isinstance(_parsed_tc.get("tool_call"), dict):
                        _tc = _parsed_tc["tool_call"]
            except Exception:
                _tc = None
            if not _tc:
                break
            _tname = str(_tc.get("name") or "").strip()
            _targs = _tc.get("args") if isinstance(_tc.get("args"), dict) else {}
            _tid_node = str(node.get("_trajectory_id") or "")
            _hop_ok = True
            if _tid_node.startswith("traj-"):
                try:
                    from backend.trajectory_budget import reserve_hop
                    _hop = await asyncio.to_thread(
                        reserve_hop, _tid_node, str(node.get("agent_id") or agent_id),
                        f"tool:{_tname}",
                    )
                    _hop_ok = bool(_hop.get("allowed", False))
                except Exception:
                    _hop_ok = False
            if not _hop_ok:
                _tres = {"status": "blocked", "error": "TRAJECTORY_HOP_CAP (tool call)"}
            elif _tname not in allowed_tool_set:
                _tres = {"status": "blocked", "error": f"Tool '{_tname}' ist in diesem DAG-Node nicht unter allowed_tools freigegeben."}
            else:
                from backend.tool_runtime import execute_agent_tool
                _tres = await execute_agent_tool(
                    tool_name=_tname,
                    args=_targs,
                    agent_id=agent_id,
                    session_id=str(kanban_task_id or node.get("id") or "dag_session"),
                    # R-B4: identischer Schluessel wie detect_silent_failures() am
                    # Run-Abschluss (dort `rid`, hier ueber den Node mitgefuehrt).
                    flightlog_run_id=str(node.get("_dag_run_id") or ""),
                )
            tool_trace.append({"turn": _turn + 1, "tool": _tname, "args": _targs, "result": _tres})
            _ckpt_rid = str(node.get("_dag_run_id") or "")
            _ckpt_db = node.get("_dag_db_path")
            if _ckpt_rid and node.get("id"):
                try:
                    with _connect(_ckpt_db) as conn:
                        conn.execute(
                            """
                            INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                            VALUES (?, ?, ?, 'running', ?, ?)
                            ON CONFLICT(run_id, node_id) DO UPDATE SET
                                status='running', output_json=excluded.output_json, updated_at=excluded.updated_at
                            """,
                            (
                                _ckpt_rid,
                                str(node["id"]),
                                "running_checkpoint",
                                json.dumps({"partial_tool_trace": tool_trace, "turn": _turn + 1}, ensure_ascii=False),
                                time.time(),
                            ),
                        )
                        conn.commit()
                except Exception as _cexc:
                    logger.debug("[WorkflowDAG] Tool-Checkpoint fehlgeschlagen: %s", _cexc)
            turn_prompt = (
                f"{turn_prompt}\n\n[TOOL-AUFRUF #{_turn + 1}: {_tname}]\n"
                f"Ergebnis:\n{json.dumps(_tres, ensure_ascii=False)[:3500]}\n\n"
                "Nutze dieses Ergebnis. Wenn kein weiterer Tool-Aufruf noetig ist, liefere jetzt deine finale Antwort ohne tool_call-Wrapper."
            )
            _next_res, _next_blocked = await _dispatch_with_node_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=turn_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=model,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="tool_loop_followup",
            )
            if _next_blocked:
                is_error = True
                res["error"] = str(_next_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
                break
            res["input_tokens"] = int(res.get("input_tokens") or 0) + int(_next_res.get("input_tokens") or 0)
            res["output_tokens"] = int(res.get("output_tokens") or 0) + int(_next_res.get("output_tokens") or 0)
            _next_status = str(_next_res.get("status") or "success").lower()
            _next_content = str(_next_res.get("content") or "").strip()
            if _next_status in ("error", "failed", "blocked") or not _next_content:
                is_error = True
                res["error"] = _next_res.get("error") or "Tool-Loop Folgeschritt fehlgeschlagen"
                break
            content = _next_content

    # JSON/Schema-Contract-Validierung zwischen DAG-Nodes (inkl. 1 Repair-Retry)
    parsed_output: Optional[Any] = None
    output_schema = node.get("output_schema")
    if not is_error and content and isinstance(output_schema, dict):
        def _validate_contract(raw_txt: str, schema: Dict[str, Any]) -> Tuple[bool, Any, str]:
            _clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt.strip(), flags=re.IGNORECASE | re.DOTALL).strip()
            try:
                _obj = json.loads(_clean)
            except Exception as _jerr:
                return False, None, f"Kein gueltiges JSON: {_jerr}"
            if not isinstance(_obj, dict):
                return False, None, "JSON-Root muss ein Objekt sein."
            req_keys = schema.get("required") if isinstance(schema.get("required"), list) else list(schema.keys())
            missing = [k for k in req_keys if k not in _obj]
            if missing:
                return False, _obj, f"Fehlende Pflichtfelder: {', '.join(str(m) for m in missing)}"
            return True, _obj, ""

        _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        if not _ok_schema:
            _repair_prompt = (
                f"{full_prompt}\n\n[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN]\n"
                f"Fehler: {_schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Deine bisherige Ausgabe:\n{content[:3000]}\n\n"
                "Gib ausschliesslich ein valides JSON-Objekt zurueck, das alle Pflichtfelder erfuellt."
            )
            _repair_model_used = _esc_model or model
            _rep_res, _rep_blocked = await _dispatch_with_node_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=_repair_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=_repair_model_used,
                reasoning_level=reasoning_level,
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="schema_repair",
            )
            if _rep_blocked:
                is_error = True
                res["error"] = str(_rep_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
            _repair_in = int(_rep_res.get("input_tokens") or 0)
            _repair_out = int(_rep_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + _repair_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + _repair_out
            _rep_content = str(_rep_res.get("content") or "").strip()
            if _rep_content:
                content = _rep_content
                _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        # Punkt 3.2.6: Frontier-Eskalation, wenn der Repair-Retry am billigen Modell scheitert
        _esc_in = 0
        _esc_out = 0
        if not _ok_schema and not is_error and _esc_model and _esc_model != model:
            _esc_prompt = (
                f"{full_prompt}\n\n"
                f"[SCHEMA-VALIDIERUNG FEHLGESCHLAGEN — FRONTIER-ESKALATION]\n"
                f"Fehler: {_schema_err}\n"
                f"Erwartetes Schema: {json.dumps(output_schema, ensure_ascii=False)}\n"
                f"Vorheriger Versuch:\n{content[:3000]}\n\n"
                "Liefere ausschliesslich das korrekte JSON-Objekt."
            )
            _esc_res, _esc_blocked = await _dispatch_with_node_budget(
                node, res, model,
                agent_id=agent_id,
                agent_name=agent_name,
                prompt=_esc_prompt,
                role=role,
                system_prompt=eff_system_prompt,
                model=_esc_model,
                reasoning_level="high",
                task_id=str(kanban_task_id or node.get("id") or ""),
                _phase="frontier_escalation",
            )
            if _esc_blocked:
                is_error = True
                res["error"] = str(_esc_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
            _esc_in = int(_esc_res.get("input_tokens") or 0)
            _esc_out = int(_esc_res.get("output_tokens") or 0)
            res["input_tokens"] = int(res.get("input_tokens") or 0) + _esc_in
            res["output_tokens"] = int(res.get("output_tokens") or 0) + _esc_out
            _esc_content = str(_esc_res.get("content") or "").strip()
            if _esc_content:
                content = _esc_content
                _ok_schema, _parsed_obj, _schema_err = _validate_contract(content, output_schema)
        if _ok_schema:
            parsed_output = _parsed_obj
        else:
            is_error = True
            res["error"] = f"Output-Schema-Verletzung: {_schema_err}"

    # Self-Critique / Anti-AI-Slop-Revisionsschleife fuer Content- & Quality-Gate-Knoten
    # Wichtig: Bei aktivem output_schema niemals validiertes JSON durch Prosa-Revision ueberschreiben.
    quality_report: Optional[Dict[str, Any]] = None
    revisions_used = 0
    if not is_error and content and _is_content_node:
        try:
            from backend.content_machine import evaluate_asset_quality
            if isinstance(output_schema, dict) and isinstance(parsed_output, dict):
                _q_hook = str(parsed_output.get("hook") or parsed_output.get("title") or "")
                _q_body = str(parsed_output.get("body") or parsed_output.get("content") or parsed_output.get("summary") or content)
                _q_cta = str(parsed_output.get("cta") or "")
                quality_report = evaluate_asset_quality({
                    "channel": _channel_hint or "linkedin",
                    "hook": _q_hook,
                    "body": _q_body,
                    "cta": _q_cta,
                })
            else:
                max_rev = max(0, min(2, int(node.get("max_revisions") if node.get("max_revisions") is not None else 1)))
                min_q = int(node.get("min_quality_score") or 75)
                lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                quality_report = evaluate_asset_quality({
                    "channel": _channel_hint or "linkedin",
                    "hook": lines_c[0] if lines_c else "",
                    "body": content,
                    "cta": lines_c[-1] if len(lines_c) > 1 else "",
                })
                while (revisions_used < max_rev and not is_error
                       and (not quality_report.get("passed") or int(quality_report.get("score", 0)) < min_q)):
                    revisions_used += 1
                    rev_issues = "; ".join(quality_report.get("issues") or [])
                    rev_sugg = "; ".join(quality_report.get("suggestions") or [])
                    rev_prompt = (
                        f"{full_prompt}\n\n"
                        f"[SELBST-KRITIK / ANTI-AI-SLOP-PRUEFUNG (Revision {revisions_used}/{max_rev})]\n"
                        f"Dein bisheriger Entwurf erreichte nur Quality-Score {quality_report.get('score')}/100.\n"
                        f"Befunde: {rev_issues}\n"
                        f"Konkrete Korrektur-Aufgaben: {rev_sugg}\n\n"
                        f"BISHERIGER ENTWURF:\n{content[:4500]}\n\n"
                        "Ueberarbeite den Text direkt, konkret, faktenbasiert (mit Zahlen-Anker & klarem CTA) und komplett ohne KI-Floskeln."
                    )
                    rev_res, _rev_blocked = await _dispatch_with_node_budget(
                        node, res, model,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        prompt=rev_prompt,
                        role=role,
                        system_prompt=eff_system_prompt,
                        model=model,
                        reasoning_level=reasoning_level,
                        task_id=str(kanban_task_id or node.get("id") or ""),
                        _phase="anti_slop_revision",
                    )
                    if _rev_blocked:
                        is_error = True
                        res["error"] = str(rev_res.get("error") or "NODE_TOKEN_BUDGET_EXCEEDED")
                        break
                    rev_content = str(rev_res.get("content") or "").strip()
                    if rev_content and str(rev_res.get("status") or "success").lower() not in ("error", "failed", "blocked"):
                        content = rev_content
                        res["input_tokens"] = int(res.get("input_tokens") or 0) + int(rev_res.get("input_tokens") or 0)
                        res["output_tokens"] = int(res.get("output_tokens") or 0) + int(rev_res.get("output_tokens") or 0)
                        lines_c = [ln.strip() for ln in content.splitlines() if ln.strip()]
                        quality_report = evaluate_asset_quality({
                            "channel": _channel_hint or "linkedin",
                            "hook": lines_c[0] if lines_c else "",
                            "body": content,
                            "cta": lines_c[-1] if len(lines_c) > 1 else "",
                        })
                    else:
                        break
        except Exception as _qexc:
            logger.debug("[WorkflowDAG] Anti-Slop-Quality-Check uebersprungen: %s", _qexc)

    # Automatisches Deliverable-Export-Handling (Showroom / Obsidian 03_Endprodukte)
    deliverable_path = ""
    if not is_error and content and (bool(node.get("save_to_showroom")) or _is_content_node):
        try:
            from archon.core.paths import PROJEKTE_DIR
            wf_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("workflow_id") or "workflow_deliverables")).strip("_")[:48] or "workflow_deliverables"
            node_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("id") or "step")).strip("_")[:40] or "step"
            target_dir = os.path.join(PROJEKTE_DIR, f"WF_{wf_slug}", "03_Endprodukte")
            os.makedirs(target_dir, exist_ok=True)
            ts_tag = time.strftime("%Y%m%d_%H%M%S")
            deliverable_path = os.path.join(target_dir, f"{ts_tag}_{node_slug}.md")
            header_md = f"# {node_title}\n\n- **Agent:** `{agent_id}`\n- **Modell:** `{res.get('model') or model}`\n"
            if quality_report is not None:
                header_md += f"- **Anti-Slop Quality-Score:** `{quality_report.get('score')}/100` (Revisionen: {revisions_used})\n"
            header_md += "\n---\n\n"
            with open(deliverable_path, "w", encoding="utf-8") as _df:
                _df.write(header_md + content + "\n")
        except OSError as _dexc:
            logger.debug("[WorkflowDAG] Showroom-Deliverable nicht geschrieben: %s", _dexc)

    # Punkt 3.2.6: exakte Kosten pro Node (Basis-/Repair-/Eskalations-Modell getrennt)
    _cost_usd = None
    _cost_unverified = True
    try:
        from backend.llm_kernel import estimate_model_cost_usd as _est_cost
        _rep_in_tok = int(locals().get("_repair_in", 0) or 0)
        _rep_out_tok = int(locals().get("_repair_out", 0) or 0)
        _esc_in_tok = int(locals().get("_esc_in", 0) or 0)
        _esc_out_tok = int(locals().get("_esc_out", 0) or 0)
        _base_in = int(res.get("input_tokens") or 0) - _rep_in_tok - _esc_in_tok
        _base_out = int(res.get("output_tokens") or 0) - _rep_out_tok - _esc_out_tok
        if _base_in or _base_out:
            _cost_usd += _est_cost(model, _base_in, _base_out)
        if _rep_in_tok or _rep_out_tok:
            _cost_usd += _est_cost(locals().get("_repair_model_used") or model, _rep_in_tok, _rep_out_tok)
        if _esc_in_tok or _esc_out_tok:
            _cost_usd += _est_cost(_esc_model or model, _esc_in_tok, _esc_out_tok)
        _cost_usd = round(_cost_usd, 6)
        _cost_unverified = False
    except Exception as _cost_exc:
        # D12: kein 0.0 als realer Wert bei fehlgeschlagener Berechnung.
        logger.error("[WorkflowDAG] Kostenberechnung fehlgeschlagen: %s", _cost_exc)
        _cost_usd = None
        _cost_unverified = True
    out = {
        "status": "error" if is_error else "success",
        "node_id": node.get("id"),
        "agent_id": agent_id,
        "model": res.get("model") or model,
        "content": content,
        "error": res.get("error") or "",
        "input_tokens": int(res.get("input_tokens") or 0),
        "output_tokens": int(res.get("output_tokens") or 0),
        "kanban_task_id": kanban_task_id,
        "cost_usd": _cost_usd,
        "cost_unverified": _cost_unverified,
    }
    if quality_report is not None:
        out["quality_score"] = int(quality_report.get("score", 0))
        out["quality_report"] = quality_report
        out["revisions_used"] = revisions_used
    if deliverable_path:
        out["deliverable_path"] = deliverable_path
    if tool_trace:
        out["tool_trace"] = tool_trace
    if parsed_output is not None:
        out["parsed_output"] = parsed_output

    await asyncio.to_thread(
        _update_kanban_task_status,
        kanban_task_id,
        "blocked" if is_error else "done",
        result=content or out["error"],
        block_kind="workflow_error" if is_error else None,
        event_kind="workflow_node_failed" if is_error else "workflow_node_completed",
        event_payload={"node_id": node.get("id"), "agent_id": agent_id, "status": out["status"]},
    )
    return out


def _enqueue_dag_node_dlq(
    node: Dict[str, Any],
    idempotency_key: Optional[str],
    error_text: str,
) -> None:
    """H: Retry-Erschöpfung in die bestehende DLQ stellen — stabiler Key verhindert Duplikate."""
    stable_key = (
        "dag-node-retry-exhausted:"
        f"{idempotency_key or node.get('id') or 'unknown'}"
    )
    payload = {
        "node_id": str(node.get("id") or ""),
        "node_type": str(node.get("type") or ""),
        "idempotency_key": str(idempotency_key or ""),
        "error": str(error_text)[:1000],
    }
    try:
        from backend.dead_letter_queue import dead_letter_queue_manager as _dlq
        result = _dlq.enqueue_task(
            job_type="workflow_node",
            source_module="backend.workflow_dag_runner",
            payload=payload,
            priority=1,
            idempotency_key=stable_key,
        )
        if result.get("queued"):
            logger.warning(
                "[WorkflowDAG] Node '%s' nach Retry-Erschöpfung in DLQ gestellt: %s",
                node.get("id"), stable_key,
            )
        else:
            logger.debug("[WorkflowDAG] DLQ-Eintrag %s bereits vorhanden: %s", stable_key, result)
    except Exception as exc:
        logger.warning("[WorkflowDAG] DLQ-Eintrag für Node '%s' fehlgeschlagen: %s", node.get("id"), exc)


async def _exec_with_retry_and_timeout(
    executor_fn: ExecutorFn,
    node: Dict[str, Any],
    upstream: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Fuehrt einen Node aus. ``idempotency_key`` (run_id + node_id +
    fingerprint) verhindert doppelte Seiteneffekte bei Replay/Resume — der
    leichte Ersatz fuer Coroutinen-Replay: bereits verbuchte Effekte werden
    aus dem Ledger zurueckgegeben statt erneut auszufuehren.
    """
    max_retries = max(0, min(5, int(node.get("max_retries") or 0)))
    timeout_sec = max(5.0, min(900.0, float(node.get("timeout_sec") or 180.0)))
    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            # D13: Retry zhlt als Hop — kein endloser Re-Dispatch ohne Cap.
            _tid_node = str(node.get("_trajectory_id") or "")
            if _tid_node.startswith("traj-"):
                from backend.trajectory_budget import reserve_hop
                _hop = await asyncio.to_thread(
                    reserve_hop, _tid_node,
                    str(node.get("agent_id") or "dag_node"),
                    f"retry:{node.get('id')}:{attempt}",
                )
                if not _hop.get("allowed", False):
                    return _blocked_node_result(node, str(_hop.get("reason") or "HOP_CAP_REACHED"))
            if idempotency_key:
                try:
                    from backend.idempotency_guard import idempotency_guard
                    idem = idempotency_guard.check_or_register(
                        "dag_node",
                        {"key": idempotency_key, "attempt": attempt},
                        explicit_key=idempotency_key,
                    )
                    if idem.get("blocked") and idem.get("cached_result"):
                        cached = idem["cached_result"]
                        if isinstance(cached, dict) and cached.get("status") != "error":
                            return cached
                except Exception as _idem_exc:
                    logger.debug("[WorkflowDAG] Idempotency-Check uebersprungen: %s", _idem_exc)
            res = await asyncio.wait_for(executor_fn(node, upstream), timeout=timeout_sec)
            if isinstance(res, dict):
                out = res
            elif res is None or (isinstance(res, str) and not res.strip()):
                # F-045: None/leere Strings duerfen nicht als Erfolg gewertet
                # werden — sonst wird ein fehlgeschlagener Node-Dispatch als
                # 'completed' persistiert (S-7.4).
                out = {
                    "status": "error",
                    "error": "executor returned non-dict/empty",
                    "node_id": node.get("id"),
                }
            else:
                # Erfolgreiche Nicht-Dict-Werte explizit als Erfolg kennzeichnen.
                out = {"status": "success", "result": res}
            if out.get("status") != "error":
                if idempotency_key:
                    try:
                        from backend.idempotency_guard import idempotency_guard
                        idempotency_guard.record_execution_result(idempotency_key, out)
                    except Exception as _idem_exc:
                        logger.debug("[WorkflowDAG] Idempotency-Record fehlgeschlagen: %s", _idem_exc)
                return out
            last_err = str(out.get("error") or "node_returned_error")
            if attempt == max_retries:
                _enqueue_dag_node_dlq(node, idempotency_key, last_err)
                return out
        except asyncio.TimeoutError:
            last_err = f"Timeout nach {timeout_sec}s (Versuch {attempt + 1}/{max_retries + 1})"
        except Exception as exc:
            last_err = str(exc)
        if attempt < max_retries:
            # H: Jitter bricht die Synchronisation paralleler Nodes auf.
            await asyncio.sleep(min(2.0 * (attempt + 1), 6.0) * random.uniform(0.75, 1.25))
    _enqueue_dag_node_dlq(node, idempotency_key, last_err)
    return {"status": "error", "error": last_err, "node_id": node.get("id")}


async def run_workflow_dag(
    dag_def: Dict[str, Any],
    executor_fn: Optional[ExecutorFn] = None,
    run_id: Optional[str] = None,
    gate_approvals: Optional[Dict[str, bool]] = None,
    db_path: Optional[str] = None,
    cancel_token: Optional[Any] = None,
    *,
    fencing_token: str = "",
    lease_guard: Optional[_LeaseGuard] = None,
) -> Dict[str, Any]:
    """Wrapper: persistiert 'cancelled' auch bei CancelledError (BaseException)."""
    try:
        return await _run_workflow_dag_impl(
            dag_def, executor_fn=executor_fn, run_id=run_id,
            gate_approvals=gate_approvals, db_path=db_path,
            cancel_token=cancel_token, fencing_token=fencing_token,
            lease_guard=lease_guard,
        )
    except asyncio.CancelledError:
        rid = run_id or ""
        if rid:
            try:
                with _connect(db_path) as conn:
                    conn.execute(
                        "UPDATE workflow_runs SET status = 'cancelled', updated_at = ? WHERE run_id = ?",
                        (time.time(), rid),
                    )
                    conn.commit()
            except Exception as exc:
                logger.debug("[WorkflowDAG] Cancelled-Status nicht persistierbar: %s", exc)
        raise


async def _run_workflow_dag_impl(
    dag_def: Dict[str, Any],
    executor_fn: Optional[ExecutorFn] = None,
    run_id: Optional[str] = None,
    gate_approvals: Optional[Dict[str, bool]] = None,
    db_path: Optional[str] = None,
    cancel_token: Optional[Any] = None,
    *,
    fencing_token: str = "",
    lease_guard: Optional[_LeaseGuard] = None,
) -> Dict[str, Any]:
    """
    Fuehrt einen Workflow-DAG aus (mit Per-run_id-Lock gegen Doppel-Ausfuehrung).
    `dag_def`: {
        "id": "...",
        "nodes": [{"id": "...", "type": "agent|fanout|gate", "depends_on": [...], ...}],
        "edges": [{"from": "...", "to": "...", "condition": "always|on_success|on_failure", "data_mode": "full|summary|artifact_only|none"}]
    }
    """
    rid = run_id or f"wfrun-{secrets.token_hex(5)}"
    # Zentrale Cancel-Propagation: Run-Token oder explizit übergebener Token
    # (Mission Control → Dispatch → DAG). Ohne Token unveraendertes Verhalten.
    from backend.cancellation import get_token as _get_cancel_token
    cancel_token = cancel_token or _get_cancel_token(f"run:{rid}")
    # Per-run_id-Lock: nur EINE Ausfuehrung pro Run. Falls belegt, laufende
    # Ausfuehrung nicht stoeren, sondern sofort melden.
    run_lock = _get_run_lock(rid)
    if run_lock.locked():
        logger.warning(f"[WorkflowDAG] Run '{rid}' laeuft bereits — keine zweite Ausfuehrung gestartet.")
        return {
            "status": "already_running",
            "run_id": rid,
            "workflow_id": str(dag_def.get("id") or "workflow"),
            "node_statuses": {},
            "outputs": {},
        }
    await run_lock.acquire()
    try:
        return await _run_workflow_dag_locked(
            dag_def, executor_fn, rid, gate_approvals, db_path, cancel_token=cancel_token,
            fencing_token=fencing_token, lease_guard=lease_guard,
        )
    finally:
        run_lock.release()


async def _run_workflow_dag_locked(
    dag_def: Dict[str, Any],
    executor_fn: Optional[ExecutorFn],
    rid: str,
    gate_approvals: Optional[Dict[str, bool]],
    db_path: Optional[str],
    cancel_token: Optional[Any] = None,
    *,
    fencing_token: str = "",
    lease_guard: Optional[_LeaseGuard] = None,
) -> Dict[str, Any]:
    """Eigentliche DAG-Ausfuehrung; Per-run_id-Lock wird von run_workflow_dag gehalten."""
    eff_executor = executor_fn or default_agent_node_executor
    wf_id = str(dag_def.get("id") or "workflow")
    nodes = dag_def.get("nodes") or []
    node_map: Dict[str, Dict[str, Any]] = {str(n["id"]): n for n in nodes if isinstance(n, dict) and n.get("id")}
    edge_map = _extract_edge_map(dag_def)
    now = time.time()

    # D13: Trajectory ueber run_id hinweg vererben — der Replan-Zaehler lebt
    # am Root-Ticket, nicht am (bei jedem Resume neuen) run_id.
    from backend.trajectory_budget import (
        ensure_trajectory, inherit_replan_count, normalize_trajectory_id,
    )
    dag_def = dict(dag_def or {})
    _root_ticket = str(dag_def.get("root_ticket_id") or dag_def.get("id") or wf_id)
    _tid = normalize_trajectory_id(dag_def.get("trajectory_id"), _root_ticket)
    dag_def["trajectory_id"] = _tid
    dag_def["root_ticket_id"] = _root_ticket
    _node_token_cap = sum(
        int(float(n.get("token_budget") or 0)) for n in nodes if isinstance(n, dict)
    )
    _traj_row = ensure_trajectory(
        _tid, _root_ticket,
        max_tokens=(int(_node_token_cap) if _node_token_cap > 0 else None),
    )
    _inherited = inherit_replan_count(_tid, rid, dag_def, db_path=db_path)
    dag_def["_replan_count"] = max(
        int(dag_def.get("_replan_count") or 0), int(_inherited.get("replan_count") or 0)
    )
    if str(_traj_row.get("state") or "") == "blocked" or dag_def["_replan_count"] > MAX_REPLAN_COUNT:
        logger.error("[WorkflowDAG] Run '%s' blockiert: Trajectory %s state=%s replan=%s",
                     rid, _tid, _traj_row.get("state"), dag_def["_replan_count"])
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at) "
                "VALUES (?, ?, 'blocked', ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status='blocked', updated_at=excluded.updated_at",
                (rid, wf_id, json.dumps(dag_def, ensure_ascii=False), now, now),
            )
            conn.commit()
        return {
            "run_id": rid, "workflow_id": wf_id, "status": "blocked",
            "needs_human": True, "failure_reason": "TRAJECTORY_BLOCKED",
            "node_statuses": {}, "outputs": {}, "trajectory_id": _tid,
            "error": "Trajectory-Cap erreicht — Replan/Resume blockiert.",
        }

    # M110 Pre-Execution Validator: Zyklen/Schema/Mapping/Budget/Deadline/
    # RBAC/HITL/Replan-Count werden VOR jedem Node geprüft (kein halber Start).
    validation = validate_dag_def(dag_def, now=now)
    if not validation["valid"]:
        err_msg = "Plan-Validator: " + "; ".join(validation["errors"][:8])
        logger.error(f"[WorkflowDAG] Run '{rid}' von Plan-Validator abgelehnt: {err_msg}")
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at) "
                "VALUES (?, ?, 'failed', ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at",
                (rid, wf_id, json.dumps(dag_def, ensure_ascii=False), now, now),
            )
            conn.commit()
        return {
            "run_id": rid,
            "workflow_id": wf_id,
            "status": "failed",
            "node_statuses": {},
            "outputs": {},
            "error": err_msg,
            "validation_errors": validation["errors"],
        }

    # Unbekannte depends_on-IDs / Kanten-Quellen: sofort failed mit klarer Diagnose
    for _nid, _node in node_map.items():
        for _dep in _all_dependencies_for_node(_node, edge_map.get(_nid, [])):
            if _dep not in node_map:
                _err_msg = f"Unknown dependency: {_dep}"
                logger.error(f"[WorkflowDAG] Run '{rid}': {_err_msg}")
                with _connect(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at)
                        VALUES (?, ?, 'failed', '{}', ?, ?)
                        ON CONFLICT(run_id) DO UPDATE SET status = 'failed', updated_at = excluded.updated_at
                        """,
                        (rid, wf_id, now, now),
                    )
                    conn.commit()
                return {
                    "run_id": rid,
                    "workflow_id": wf_id,
                    "status": "failed",
                    "node_statuses": {},
                    "outputs": {},
                    "error": _err_msg,
                }

    # OTel: ein Trace pro Run, ein Span pro Node. Alle Tracer-Writes laufen
    # im Threadpool, damit der Event-Loop nicht blockiert.
    trace_id = await _otel_start(f"workflow.{wf_id}", rid)

    approvals: Dict[str, bool] = {}
    approvals_parse_failed = False
    with _connect(db_path) as conn:
        prev_run = conn.execute(
            "SELECT gate_approvals_json FROM workflow_runs WHERE run_id = ?",
            (rid,),
        ).fetchone()
        if prev_run and prev_run["gate_approvals_json"]:
            try:
                stored_app = json.loads(prev_run["gate_approvals_json"])
                if isinstance(stored_app, dict):
                    approvals.update({str(k): bool(v) for k, v in stored_app.items()})
            except Exception as exc:
                # B: Ein Parsefehler darf NIE zum Überschreiben mit einem leeren
                # Dict führen — das würde erteilte Freigaben dauerhaft löschen.
                approvals_parse_failed = True
                logger.error(
                    "[WorkflowDAG] Run '%s': gate_approvals_json konnte nicht gelesen werden "
                    "(%s); alter Wert wird bewahrt.", rid, exc,
                )
        if gate_approvals:
            approvals.update({str(k): bool(v) for k, v in gate_approvals.items()})
        conn.execute(
            """
            INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, gate_approvals_json, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status='running',
                dag_json=CASE WHEN excluded.dag_json != '{}' THEN excluded.dag_json ELSE workflow_runs.dag_json END,
                gate_approvals_json=CASE WHEN ? THEN workflow_runs.gate_approvals_json ELSE excluded.gate_approvals_json END,
                updated_at=excluded.updated_at
            """,
            (rid, wf_id, json.dumps(dag_def, ensure_ascii=False), json.dumps(approvals, ensure_ascii=False),
             now, now, int(approvals_parse_failed)),
        )
        conn.commit()
        cached_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json FROM workflow_node_states WHERE run_id = ?",
            (rid,),
        ).fetchall()
        cached = {r["node_id"]: dict(r) for r in cached_rows}

    outputs: Dict[str, Any] = {}
    statuses: Dict[str, str] = {}

    max_conc = max(1, min(16, int(dag_def.get("max_concurrent_tasks") or 4)))
    sem = asyncio.Semaphore(max_conc)
    pending = set(node_map.keys())
    running_tasks: Dict[str, "asyncio.Task[None]"] = {}
    budget_blocked = False

    async def _run_one(nid: str) -> None:
        nonlocal budget_blocked
        node_started = time.perf_counter()
        node = node_map[nid]
        # D13/HIGH: harte Laufzeit-Obergrenze VOR jedem Node-Dispatch.
        _run_cap = float(dag_def.get("max_budget_eur") or 0.0)
        if _run_cap > 0.0:
            _spent = sum(
                float((v or {}).get("cost_usd") or 0.0)
                for v in outputs.values() if isinstance(v, dict)
            )
            _node_est = float(node.get("max_budget_eur") or 0.0)
            if _spent + _node_est > _run_cap + 1e-6:
                budget_blocked = True
                statuses[nid] = "blocked"
                outputs[nid] = {
                    "status": "blocked", "block_kind": "budget_exhausted",
                    "needs_human": True, "failure_reason": "BUDGET_EXHAUSTED",
                    "error": f"Run-Cap {_run_cap:.2f} EUR erreicht (verbraucht {_spent:.2f}).",
                }
                logger.error("[WorkflowDAG] '%s': Budget-Cap vor Node '%s' erreicht.", rid, nid)
                return
        if cancel_token is not None:
            cancel_token.check()
        if lease_guard is not None and lease_guard.lost.is_set():
            statuses[nid] = "failed"
            outputs[nid] = {"status": "error", "error": "lease_lost"}
            return
        inc_edges = edge_map.get(nid, [])
        edge_by_src = {e["from"]: e for e in inc_edges}
        deps = _all_dependencies_for_node(node, inc_edges)
        upstream = {
            d: _shape_upstream_output(outputs.get(d), (edge_by_src.get(d) or {}).get("data_mode", "full"))
            for d in deps
        }
        fp = compute_node_fingerprint(node, upstream)

        prev = cached.get(nid)
        if prev and prev["fingerprint"] == fp and prev["status"] in ("completed", "skipped_cached"):
            outputs[nid] = json.loads(prev["output_json"] or "{}")
            statuses[nid] = "skipped_cached"
            return

        # Persistenter Running-Status + Live-SSE-Broadcast
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                VALUES (?, ?, ?, 'running', '{}', ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    fingerprint=excluded.fingerprint, status='running', updated_at=excluded.updated_at
                """,
                (rid, nid, fp, time.time()),
            )
            conn.commit()

        try:
            from archon.core.runtime import broadcast_event
            broadcast_event("workflow_node_state", {
                "run_id": rid, "workflow_id": wf_id, "node_id": nid, "status": "running"
            })
        except Exception as _bexc:
            logger.debug("[WorkflowDAG] SSE running-Event uebersprungen: %s", _bexc)

        ntype = str(node.get("type") or "agent").lower()
        requires_gate = ntype == "gate" or bool(node.get("require_hitl"))
        node_ctx = {
            **node, "workflow_id": wf_id, "_dag_run_id": rid, "_dag_db_path": db_path,
            "_trajectory_id": _tid, "_dag_max_budget_eur": dag_def.get("max_budget_eur"),
            "_root_ticket_id": _root_ticket,
        }

        if ntype == "gate":
            if approvals.get(nid) is True:
                out = {"approved": True, "status": "success"}
                st = "completed"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "done", result="HITL-Gate freigegeben.")
            elif approvals.get(nid) is False:
                out = {"approved": False, "status": "rejected"}
                st = "rejected"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="HITL-Gate abgelehnt.", block_kind="hitl_rejected")
            else:
                deci_id = await asyncio.to_thread(_register_hitl_gate_decision, rid, wf_id, node, upstream, db_path)
                out = {"awaiting_gate": True, "decision_id": deci_id}
                st = "awaiting_gate"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="Wartet auf HITL-Freigabe.", block_kind="hitl_gate")
        elif requires_gate and approvals.get(nid) is not True:
            if approvals.get(nid) is False:
                out = {"approved": False, "status": "rejected"}
                st = "rejected"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="HITL-Freigabe abgelehnt.", block_kind="hitl_rejected")
            else:
                deci_id = await asyncio.to_thread(_register_hitl_gate_decision, rid, wf_id, node, upstream, db_path)
                out = {"awaiting_gate": True, "decision_id": deci_id}
                st = "awaiting_gate"
                await asyncio.to_thread(_update_kanban_task_status, node.get("kanban_task_id"), "blocked", result="Wartet auf HITL-Freigabe vor Ausfuehrung.", block_kind="hitl_gate")

        elif ntype == "quality_gate":
            from backend.content_machine import evaluate_asset_quality
            combined_up = "\n\n".join(
                str(v.get("content") or v.get("result") or "") if isinstance(v, dict) else str(v)
                for v in upstream.values()
            ).strip()
            lines_u = [ln.strip() for ln in combined_up.splitlines() if ln.strip()]
            q_rep = evaluate_asset_quality({
                "channel": str(node.get("channel") or "linkedin"),
                "hook": lines_u[0] if lines_u else "",
                "body": combined_up,
                "cta": lines_u[-1] if len(lines_u) > 1 else "",
            })
            min_q = int(node.get("min_quality_score") or 70)
            q_ok = bool(q_rep.get("passed")) and int(q_rep.get("score", 0)) >= min_q
            out = {
                "status": "success" if q_ok else "error",
                "quality_score": int(q_rep.get("score", 0)),
                "quality_report": q_rep,
                "content": combined_up,
            }
            st = "completed" if q_ok else "failed"
            await asyncio.to_thread(
                _update_kanban_task_status,
                node.get("kanban_task_id"),
                "done" if q_ok else "blocked",
                result=f"Anti-Slop Quality-Score: {out['quality_score']}/100",
                block_kind=None if q_ok else "quality_gate_failed",
            )
        elif ntype in ("map", "dynamic_fanout"):
            # Punkt 3.2.3: Dynamisches Sub-DAG-Spawning (Map-Over-Items)
            items = []
            items_key = str(node.get("items_key") or "items").strip()
            if isinstance(node.get("items"), list):
                items = list(node["items"])
            else:
                for up_k, up_val in upstream.items():
                    if isinstance(up_val, dict):
                        po = up_val.get("parsed_output")
                        if isinstance(po, list):
                            items = po
                            break
                        elif isinstance(po, dict) and isinstance(po.get(items_key), list):
                            items = po[items_key]
                            break
                        if isinstance(up_val.get("items"), list):
                            items = up_val["items"]
                            break
                        if isinstance(up_val.get("results"), list):
                            items = up_val["results"]
                            break
                        raw_c = str(up_val.get("content") or up_val.get("result") or "").strip()
                        if raw_c.startswith("[") and raw_c.endswith("]"):
                            try:
                                loaded = json.loads(raw_c)
                                if isinstance(loaded, list):
                                    items = loaded
                                    break
                            except Exception:
                                pass
                    elif isinstance(up_val, list):
                        items = up_val
                        break

            max_items = max(1, min(50, int(node.get("max_items") or 10)))
            max_budget_eur = float(
                node.get("max_budget_eur") or node.get("_dag_max_budget_eur") or 0.0
            )
            items_to_process = items[:max_items]

            if not items_to_process:
                out = await _exec_with_retry_and_timeout(eff_executor, node_ctx, upstream)
                st = "failed" if out.get("status") == "error" else "completed"
            else:
                sub_tasks = []
                for idx, itm in enumerate(items_to_process):
                    sub_ctx = {
                        **node_ctx,
                        "id": f"{nid}_item_{idx}",
                        "map_item": itm,
                        "map_index": idx,
                        "map_total": len(items_to_process),
                        "plugin_params": {
                            **dict(node.get("plugin_params") or {}),
                            "item": itm,
                            "index": idx,
                        },
                    }
                    sub_up = {**upstream, "_item": itm}
                    _db_scope = hashlib.sha256(os.path.abspath(db_path).encode("utf-8")).hexdigest()[:10] if db_path else "default"
                    sub_tasks.append(_exec_with_retry_and_timeout(
                        eff_executor, sub_ctx, sub_up,
                        idempotency_key=f"dag-{_db_scope}-{rid}-{nid}-item-{idx}",
                    ))

                sub_results = await asyncio.gather(*sub_tasks, return_exceptions=True)
                ok_results = []
                total_cost = 0.0
                for r in sub_results:
                    if isinstance(r, dict):
                        total_cost += float(r.get("cost_usd") or 0.0)
                        if r.get("status") != "error":
                            ok_results.append(r)
                    elif not isinstance(r, Exception):
                        ok_results.append({"result": r, "status": "success"})

                budget_exceeded = bool(max_budget_eur > 0.0 and total_cost > max_budget_eur + 1e-6)
                quorum = int(node.get("quorum_min") or max(1, len(items_to_process) // 2 or 1))
                st = "completed" if (len(ok_results) >= quorum and not budget_exceeded) else "failed"
                out = {
                    "status": "success" if st == "completed" else "error",
                    "map_results": ok_results,
                    "items_count": len(items_to_process),
                    "ok_count": len(ok_results),
                    "cost_usd": round(total_cost, 6),
                    "budget_exceeded": budget_exceeded,
                    "max_budget_eur": max_budget_eur,
                    "results": ok_results,
                }
        elif ntype == "fanout":
            branches = node.get("branches") or []
            if branches:
                quorum = int(node.get("quorum_min") or max(1, len(branches)))
                results = await asyncio.gather(
                    *(_exec_with_retry_and_timeout(eff_executor, {**node_ctx, "branch": b}, upstream) for b in branches),
                    return_exceptions=True,
                )
                ok_results = [r for r in results if isinstance(r, dict) and r.get("status", "success") != "error"]
                if len(ok_results) >= quorum:
                    out = {"status": "success", "quorum_met": True, "ok_count": len(ok_results), "results": ok_results}
                    st = "completed"
                else:
                    out = {"status": "error", "quorum_met": False, "ok_count": len(ok_results), "required": quorum}
                    st = "failed"
            else:
                out = await _exec_with_retry_and_timeout(eff_executor, node_ctx, upstream)
                st = "failed" if out.get("status") == "error" else "completed"
        else:
            # Stabiler Idempotency-Key: db_scope + run + node + fingerprint.
            # db_scope verhindert Ledger-Kollisionen zwischen isolierten
            # Test-/Mandanten-DBs bei gleichem run_id; innerhalb derselben DB
            # bleibt der Key bei Resume/Replay stabil.
            _db_scope = hashlib.sha256(os.path.abspath(db_path).encode("utf-8")).hexdigest()[:10] if db_path else "default"
            node_idem_key = f"dag-{_db_scope}-{rid}-{nid}-{fp}"
            out = await _exec_with_retry_and_timeout(
                eff_executor, node_ctx, upstream, idempotency_key=node_idem_key
            )
            st = "failed" if out.get("status") == "error" else "completed"

        outputs[nid] = out
        statuses[nid] = st

        # HITL-Gate: Run mit Checkpoint suspendieren (durable_execution_kernel).
        # Das ist der Produktivaufrufer von suspend() — ohne ihn blieb der
        # SUSPENDED-Zustand eine Sackgasse.
        if st == "awaiting_gate":
            gate_suspend = _suspend_run_at_gate(
                rid, wf_id, nid, statuses, outputs,
                fencing_token=fencing_token, lease_guard=lease_guard,
            )
            outputs[nid]["durable_suspend"] = gate_suspend

        if trace_id:
            await _otel_span(
                trace_id,
                name=f"dag.node.{nid}",
                span_type="agent",
                agent_id=str(node.get("agent_id") or "workflow_engine"),
                model=str(node.get("model") or ""),
                output_data=out if isinstance(out, dict) else {"result": out},
                status="OK" if st in SUCCESS_NODE_STATES else "ERROR",
                cost_usd=float(out.get("cost_usd") or 0.0) if isinstance(out, dict) else 0.0,
                duration_ms=round((time.perf_counter() - node_started) * 1000.0, 2),
                attributes={"run_id": rid, "node_id": nid, "node_type": ntype, "status": st},
            )
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
        try:
            from archon.core.runtime import broadcast_event
            broadcast_event("workflow_node_state", {
                "run_id": rid,
                "workflow_id": wf_id,
                "node_id": nid,
                "status": st,
                "quality_score": out.get("quality_score") if isinstance(out, dict) else None,
                "deliverable_path": out.get("deliverable_path") if isinstance(out, dict) else None,
            })
        except Exception as _bexc:
            logger.debug("[WorkflowDAG] SSE terminal-Event uebersprungen: %s", _bexc)

    async def _run_guarded(nid: str) -> None:
        async with sem:
            await _run_one(nid)

    # Event-gesteuerte Topologische Ready-Queue (kein globales Wave-Barrier-Warten)
    lease_lost = False
    while pending or running_tasks:
        if lease_guard is not None and lease_guard.lost.is_set():
            # Fencing-Token wurde entwertet -> ein anderer Worker fuehrt den Run.
            # Alle noch laufenden Nodes abbrechen, keine neuen mehr starten.
            lease_lost = True
            for _t in running_tasks.values():
                if not _t.done():
                    _t.cancel()
            if running_tasks:
                await asyncio.gather(*running_tasks.values(), return_exceptions=True)
            running_tasks.clear()
            for _nid in list(pending):
                statuses[_nid] = "failed"
                outputs[_nid] = {"status": "error", "error": "lease_lost"}
            pending.clear()
            logger.warning("[WorkflowDAG] Run '%s': Lease verloren — Ausfuehrung abgebrochen.", rid)
            break
        if cancel_token is not None and cancel_token.cancelled:
            for _t in running_tasks.values():
                _t.cancel()
            cancel_token.check()
        ready: List[str] = []
        skippable: List[str] = []

        for nid in sorted(pending - set(running_tasks.keys())):
            node = node_map[nid]
            inc_edges = edge_map.get(nid, [])
            deps = _all_dependencies_for_node(node, inc_edges)
            if not deps:
                ready.append(nid)
                continue
            if not all(statuses.get(d) in TERMINAL_NODE_STATES for d in deps):
                continue

            edge_by_src = {e["from"]: e for e in inc_edges}
            all_conditions_met = True
            for d in deps:
                e = edge_by_src.get(d)
                cond = e["condition"] if e else "on_success"
                if not _edge_condition_matches(cond, statuses.get(d, "")):
                    all_conditions_met = False
                    break
            if all_conditions_met:
                ready.append(nid)
            else:
                skippable.append(nid)

        for nid in skippable:
            outputs[nid] = {"status": "skipped", "reason": "upstream_condition_not_met"}
            statuses[nid] = "skipped_condition"
            pending.discard(nid)
            with _connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, node_id) DO UPDATE SET
                        status=excluded.status, output_json=excluded.output_json, updated_at=excluded.updated_at
                    """,
                    (rid, nid, "skipped", "skipped_condition", json.dumps(outputs[nid], ensure_ascii=False), time.time()),
                )
                conn.commit()

        if budget_blocked:
            for _nid in list(pending):
                statuses[_nid] = "blocked"
                outputs[_nid] = {
                    "status": "blocked", "block_kind": "budget_exhausted",
                    "needs_human": True, "failure_reason": "BUDGET_EXHAUSTED",
                }
            pending.clear()
            break

        for nid in ready:
            running_tasks[nid] = asyncio.create_task(_run_guarded(nid))

        if not running_tasks:
            # Entweder durch Gate/Fehler blockiert oder Zyklus
            break

        done_set, _ = await asyncio.wait(list(running_tasks.values()), return_when=asyncio.FIRST_COMPLETED)
        for fin_nid, fin_task in list(running_tasks.items()):
            if fin_task in done_set:
                running_tasks.pop(fin_nid, None)
                pending.discard(fin_nid)
                # Exceptions im Task abfangen, damit Scheduler nicht abbricht
                try:
                    fin_task.result()
                except asyncio.CancelledError:
                    # CancelledError erbt BaseException — vorher fiel er durch
                    # das except Exception, verliess die Schleife und liess den
                    # Run dauerhaft auf 'running'. Jetzt kontrolliert beenden.
                    logger.warning("[WorkflowDAG] Node '%s' abgebrochen — Run wird beendet.", fin_nid)
                    statuses[fin_nid] = "cancelled"
                    outputs[fin_nid] = {"status": "cancelled", "error": "node_cancelled"}
                    raise
                except Exception as _texc:
                    logger.error("[WorkflowDAG] Unbehandelter Task-Fehler in Node '%s': %s", fin_nid, _texc, exc_info=_texc)
                    statuses[fin_nid] = "failed"
                    outputs[fin_nid] = {"status": "error", "error": str(_texc)}

    # on_failure-Recovery pruefen: ein fehlgeschlagener Node gilt als aufgefangen,
    # wenn ein nachgelagerter on_failure-Knoten erfolgreich abgeschlossen wurde.
    recovered_failures = set()
    for target_nid, inc_edges in edge_map.items():
        if statuses.get(target_nid) in ("completed", "skipped_cached"):
            for e in inc_edges:
                if e.get("condition") == "on_failure" and statuses.get(e.get("from")) == "failed":
                    recovered_failures.add(e["from"])

    unrecovered_fail = any(
        (st == "rejected") or (st == "failed" and nid not in recovered_failures)
        for nid, st in statuses.items()
    )
    has_awaiting_gate = any(s == "awaiting_gate" for s in statuses.values())
    cycle_error: Optional[str] = None
    if any(st == "cancelled" for st in statuses.values()):
        # Cancel muss als terminaler Zustand persistiert werden, sonst bleibt
        # der Run dauerhaft 'running' und blockiert Resume/UI.
        final_status = "cancelled"
        cycle_error = "Run cancelled"
    elif lease_lost:
        final_status = "failed"
        cycle_error = "Lease lost during execution — run aborted (fenced)"
        logger.error(f"[WorkflowDAG] Run '{rid}': {cycle_error}")
    elif unrecovered_fail:
        final_status = "failed"
    elif has_awaiting_gate:
        final_status = "paused"
    elif budget_blocked:
        final_status = "blocked"
        cycle_error = "BUDGET_EXHAUSTED — Run-Cap erreicht (HITL erforderlich)"
    elif pending:
        # Kein Fortschritt moeglich und kein wartendes Gate: Zyklus / unresolvable dependency
        final_status = "failed"
        cycle_error = "Cycle or unresolvable dependency detected"
        logger.error(f"[WorkflowDAG] Run '{rid}': {cycle_error}")
    else:
        final_status = "completed"

    with _connect(db_path) as conn:
        # Punkt 3.2.6: Gesamtkosten pro Run/Deliverable ausmessen
        _total_cost = 0.0
        try:
            for _r in conn.execute("SELECT output_json FROM workflow_node_states WHERE run_id = ?", (rid,)).fetchall():
                try:
                    _o = json.loads(_r[0] or "{}")
                    _total_cost += float(_o.get("cost_usd") or 0.0)
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass
        _total_tokens = 0
        for _r in conn.execute(
            "SELECT output_json FROM workflow_node_states WHERE run_id = ?", (rid,)
        ).fetchall():
            try:
                _o = json.loads(_r[0] or "{}")
                _total_tokens += int(_o.get("input_tokens") or 0) + int(_o.get("output_tokens") or 0)
            except Exception:
                pass
        # D13/BLOCKER: Flightlog-Abschluss-Event (Produzent im Tool-Chokepoint
        # kommt von einem anderen Agenten) + Silent-Failure-Detektion.
        _flight_flags: List[str] = []
        try:
            from backend.flightlog_backtester import (
                detect_silent_failures, record_flight_event,
            )
            record_flight_event(
                run_id=rid, agent_id=str(dag_def.get("id") or "workflow_engine"),
                tool_name="dag_run_complete",
                args={"workflow_id": wf_id, "trajectory_id": _tid, "status": final_status},
                tool_ok=final_status in ("completed", "paused"),
                tokens_used=_total_tokens,
            )
            _detected = detect_silent_failures(
                rid, final_status=final_status,
                final_output="\n".join(
                    str((v or {}).get("content") or "")[:400]
                    for v in outputs.values() if isinstance(v, dict)
                ),
            )
            _flight_flags = list(_detected.get("flags") or [])
            if _flight_flags and final_status in ("completed", "paused"):
                final_status = "blocked"
                cycle_error = f"SILENT_FAILURE: {', '.join(_flight_flags)}"
                logger.error("[WorkflowDAG] '%s' blockiert durch Flightlog: %s", rid, _flight_flags)
                try:
                    from backend.trajectory_budget import _audit
                    _audit(_tid, f"flightlog_flags:{_flight_flags}", rid)
                except Exception:
                    pass
        except Exception as _flight_exc:
            logger.debug("[WorkflowDAG] Flightlog-Abschluss nicht verfuegbar: %s", _flight_exc)
        try:
            from backend.trajectory_budget import close_trajectory, record_tokens
            if _total_tokens > 0:
                # R-B3 (Re-Audit D13): Das Ergebnis der Budgetbuchung auswerten.
                # Vorher wurde `blocked` ignoriert und vom Abschluss auf
                # `completed`/`failed` ueberschrieben.
                _token_res = record_tokens(_tid, _total_tokens, reason=f"dag_run:{rid}")
                if isinstance(_token_res, dict) and not _token_res.get("allowed", True):
                    final_status = "blocked"
                    cycle_error = cycle_error or f"TRAJECTORY_TOKEN_CAP: {_token_res.get('reason')}"
                    logger.error("[WorkflowDAG] '%s' blockiert durch Trajectory-Token-Cap", rid)
            close_trajectory(
                _tid,
                "blocked" if final_status == "blocked"
                else ("completed" if final_status == "completed" else "failed"),
            )
        except Exception as _traj_exc:
            logger.error("[WorkflowDAG] Trajectory-Abschluss nicht persistiert: %s", _traj_exc)
        conn.execute(
            "UPDATE workflow_runs SET status = ?, updated_at = ?, total_cost_usd = ? WHERE run_id = ?",
            (final_status, time.time(), round(_total_cost, 6), rid),
        )
        conn.commit()

    result: Dict[str, Any] = {
        "run_id": rid,
        "workflow_id": wf_id,
        "status": final_status,
        "node_statuses": statuses,
        "outputs": outputs,
    }
    if cycle_error:
        result["error"] = cycle_error
    if final_status == "blocked":
        result["needs_human"] = True
        result["failure_reason"] = str(cycle_error or "BUDGET_EXHAUSTED")
    result["trajectory_id"] = _tid
    if _flight_flags:
        result["flightlog_flags"] = _flight_flags
    if trace_id:
        await _otel_end(trace_id, "ERROR" if final_status in FAILURE_NODE_STATES or cycle_error else "OK")
    return result


def get_workflow_run(run_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        cost_col = ", total_cost_usd" if "total_cost_usd" in run_cols else ""
        run_row = conn.execute(
            f"SELECT run_id, workflow_id, status, dag_json, created_at, updated_at{cost_col} FROM workflow_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not run_row:
            return None
        node_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json, updated_at FROM workflow_node_states WHERE run_id = ? ORDER BY updated_at ASC",
            (run_id,),
        ).fetchall()
    nodes = {}
    for nr in node_rows:
        try:
            out_parsed = json.loads(nr["output_json"] or "{}")
        except Exception:
            out_parsed = {}
        nodes[nr["node_id"]] = {
            "status": nr["status"],
            "fingerprint": nr["fingerprint"],
            "output": out_parsed,
            "updated_at": nr["updated_at"],
        }
    try:
        dag_parsed = json.loads(run_row["dag_json"] or "{}")
    except Exception:
        dag_parsed = {}
    return {
        "run_id": run_row["run_id"],
        "workflow_id": run_row["workflow_id"],
        "status": run_row["status"],
        "dag": dag_parsed,
        "nodes": nodes,
        "total_cost_usd": float(run_row["total_cost_usd"] or 0.0) if "total_cost_usd" in run_row.keys() else 0.0,
        "created_at": run_row["created_at"],
        "updated_at": run_row["updated_at"],
    }


def list_workflow_runs(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        cost_col = ", total_cost_usd" if "total_cost_usd" in run_cols else ""
        rows = conn.execute(
            f"SELECT run_id, workflow_id, status, created_at, updated_at{cost_col} FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
    return [dict(r) for r in rows]


async def resume_workflow_run(
    run_id: str,
    gate_approvals: Optional[Dict[str, bool]] = None,
    executor_fn: Optional[ExecutorFn] = None,
    db_path: Optional[str] = None,
    *,
    fencing_token: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_workflow_run(run_id, db_path=db_path)
    if not existing:
        raise KeyError(f"Workflow run '{run_id}' not found")
    dag_def = existing.get("dag") or {}
    if not dag_def.get("nodes"):
        raise ValueError(f"Workflow run '{run_id}' besitzt keine gespeicherte DAG-Definition fuer Resume.")
    # P2/Durable Execution: CAS-Claim + Fencing-Token statt prozesslokaler Locks.
    # FRUEHER fail-open: ein verweigerter Claim wurde ignoriert und der Run
    # lief trotzdem — zwei Worker konnten denselben DAG parallel ausfuehren.
    # Jetzt fail-closed: ohne Claim kein Resume.
    try:
        from backend.durable_execution_kernel import durable_kernel, FAILED as _FAILED, COMPLETED as _COMPLETED
        claim = _claim_kernel_run(
            durable_kernel,
            run_id,
            json.dumps(dag_def, sort_keys=True, ensure_ascii=False),
            fencing_token or None,
        )
        if not claim.get("claimed"):
            logger.warning(
                "[WorkflowDAG] Run '%s': CAS-Claim verweigert (%s/%s) — Resume nicht gestartet.",
                run_id, claim.get("reason"), claim.get("state"),
            )
            return {
                "status": "skipped",
                "run_id": run_id,
                "reason": "durable_claim_not_acquired",
                "claim_reason": claim.get("reason"),
                "claim_state": claim.get("state"),
            }
        token = str(claim["fencing_token"])
    except Exception as kc_exc:
        logger.error(
            "[WorkflowDAG] Durable-Kernel Claim nicht verfuegbar — Resume blockiert (fail-closed): %s",
            kc_exc,
        )
        return {
            "status": "skipped",
            "run_id": run_id,
            "reason": "durable_kernel_unavailable",
            "error": str(kc_exc)[:300],
        }

    kernel = durable_kernel
    # Der Claim galt nur 300 s; lange LLM-DAGs wurden danach von einem
    # anderen Worker uebernommen. Heartbeat verlaengert die Lease alle 60 s.
    # Bei renew=False wird `guard.lost` gesetzt und die DAG-Hauptausfuehrung
    # bricht ab (statt still weiterzulaufen).
    guard = _LeaseGuard()

    async def _renew_lease() -> None:
        while True:
            await asyncio.sleep(60)
            if guard.suspended.is_set():
                return  # bewusstes HITL-Suspend, kein Lease-Verlust
            try:
                if not kernel.renew(run_id, token, ttl_seconds=300):
                    logger.warning("[WorkflowDAG] Lease '%s' nicht mehr gueltig — Resume abbrechen.", run_id)
                    guard.lost.set()
                    return
            except Exception as exc:
                logger.debug("[WorkflowDAG] Lease-Renew Hinweis: %s", exc)
                guard.lost.set()
                return

    heartbeat = asyncio.create_task(_renew_lease(), name=f"dag_lease_{run_id}")

    result = None
    try:
        result = await run_workflow_dag(
            dag_def=dag_def,
            executor_fn=executor_fn,
            run_id=run_id,
            gate_approvals=gate_approvals or {},
            db_path=db_path,
            fencing_token=token,
            lease_guard=guard,
        )
    except Exception as run_exc:
        if not guard.suspended.is_set():
            try:
                kernel.transition(run_id, _FAILED, token, reason=str(run_exc)[:300])
            except Exception:
                pass
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)

    if guard.lost.is_set():
        # Fencing-Token ist veraltet: kein Status-Transition mit diesem Token,
        # der uebernehmende Worker besitzt die Hoheit.
        logger.error("[WorkflowDAG] Run '%s': Lease verloren — Resume als fehlgeschlagen markiert.", run_id)
        if isinstance(result, dict):
            result["status"] = "failed"
            result["error"] = "lease_lost"
    elif guard.suspended.is_set():
        # Am HITL-Gate suspendiert: Run bleibt 'paused' bis zur Entscheidung.
        logger.info("[WorkflowDAG] Run '%s' wurde am HITL-Gate suspendiert.", run_id)
    else:
        try:
            final_state = _COMPLETED if str(result.get("status", "")).lower() in ("success", "completed") else _FAILED
            kernel.transition(run_id, final_state, token, reason=str(result.get("status", "")))
        except Exception as tr_exc:
            logger.debug("[WorkflowDAG] Durable-Kernel Transition fehlgeschlagen: %s", tr_exc)

    # P1: Die Asset-Finalisierung hing bisher nur am decisions.py-Pfad. Wurde
    # derselbe Run ueber den generischen Resume-Endpoint fortgesetzt, blieben
    # die Assets dauerhaft auf 'review'. Jetzt zentral im Resume verankert
    # (idempotent — ein zweiter Aufruf durch decisions.py trifft 0 Zeilen).
    try:
        from backend.content_machine import finalize_assets_for_workflow_run
        # KRITISCH: all([]) ist True. Der generische Resume-Endpoint uebergibt
        # standardmaessig {} — frueher wurden Assets damit ohne jede Freigabe
        # freigegeben (HITL-Bypass). Nur ein expliziter True am Editorial-Gate
        # (oder ein expliziter boolescher approved-Wert) zaehlt.
        approvals = gate_approvals or {}
        if isinstance(approvals, dict) and approvals:
            approved = all(bool(v) for v in approvals.values())
        else:
            approved = False
        # WICHTIG: nur ein explizites Dict mit True am Editorial-Gate zaehlt.
        # `gate_approvals: true` aus dem Request-Body darf die Freigabe nicht
        # erzwingen (Single-Admin-Self-Approval / HITL-Bypass).
        finalized = finalize_assets_for_workflow_run(run_id, approved=approved)
        if finalized.get("updated"):
            logger.info(
                "[WorkflowDAG] Content-Assets fuer Run '%s' finalisiert: %s (%s)",
                run_id, finalized["updated"], finalized.get("target_status"),
            )
    except Exception as exc:
        # Keine Eskalation: die Finalisierung ist ein Folge-Schritt, der
        # DAG-Run selbst ist bereits erfolgreich durchgelaufen.
        logger.warning("[WorkflowDAG] Content-Finalisierung fuer '%s' fehlgeschlagen: %s", run_id, exc)
    return result


async def resume_suspended_workflow_run(
    run_id: str,
    *,
    executor_fn: ExecutorFn = None,
    db_path: Optional[str] = None,
    max_missing_outputs: int = 0,
) -> Dict[str, Any]:
    """P2: SUSPENDED → RUNNING pragmatisch ueber Checkpoints + Node-States.

    Kein schwergewichtiges Coroutinen-Replay: der DAG-Runner persistiert jeden
    Node-Output in ``workflow_node_states``. Beim Resume laedt er den
    Kernel-Checkpoint, verifiziert, dass alle als 'completed' markierten Nodes
    auch einen Output haben, transitioniert SUSPENDED → RUNNING und startet
    ``resume_workflow_run`` neu. Der bestehende Fingerprint-Cache ueberspringt
    alle bereits abgeschlossenen Knoten (``skipped_cached``); nur die
    unfertigen Nodes werden erneut ausgefuehrt.
    """
    from backend.durable_execution_kernel import durable_kernel, SUSPENDED

    ctx = durable_kernel.resume_context(run_id)
    if not ctx:
        raise KeyError(f"Kein Durable-Checkpoint fuer Run '{run_id}' vorhanden.")
    if ctx["state"] != SUSPENDED:
        return {
            "status": "not_suspended",
            "run_id": run_id,
            "state": ctx["state"],
            "reason": "Nur SUSPENDED-Runs koennen ueber dieses Portal fortgesetzt werden.",
        }

    # Persistierte Node-States pruefen: jeder 'completed' muss einen Output haben.
    with _connect(db_path) as conn:
        node_rows = conn.execute(
            "SELECT node_id, status, output_json FROM workflow_node_states WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    missing: List[str] = []
    completed = 0
    for row in node_rows:
        if str(row["status"]) in ("completed", "skipped_cached"):
            completed += 1
            raw = str(row["output_json"] or "").strip()
            if raw in ("", "{}", "null"):
                missing.append(str(row["node_id"]))
    if len(missing) > max_missing_outputs:
        return {
            "status": "resume_blocked",
            "run_id": run_id,
            "reason": f"{len(missing)} bereits abgeschlossene Nodes haben keinen persistierten Output.",
            "missing_outputs": missing[:20],
        }

    resumed = durable_kernel.resume_suspended(run_id, ctx.get("fencing_token"))
    logger.info(
        "[WorkflowDAG] Run '%s' von Schritt %s fortgesetzt (%s Node-Outputs uebernommen).",
        run_id, resumed["resume_from_step"], completed,
    )
    result = await resume_workflow_run(
        run_id=run_id, executor_fn=executor_fn, db_path=db_path,
        fencing_token=resumed["fencing_token"],
    )
    result["resume"] = resumed
    result["resumed_from_step"] = resumed["resume_from_step"]
    result["reused_node_outputs"] = completed
    return result


def schedule_workflow_resume(
    run_id: str,
    gate_approvals: Optional[Dict[str, bool]] = None,
    executor_fn: Optional[ExecutorFn] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Feuert einen Fire-and-Forget-Resume-Task ab (fire-and-sauber-vergessen).

    Eine Exception im Hintergrund-Task wird NICHT still geschluckt: der
    Done-Callback loggt sie mit traceback und setzt den Run in workflow_runs
    auf 'failed' (statt fuer immer 'running'/'paused' zu bleiben).
    Wird von decisions.py / v2_capabilities.py benutzt.
    """
    async def _resume_runner() -> Dict[str, Any]:
        return await resume_workflow_run(
            run_id=run_id,
            gate_approvals=gate_approvals,
            executor_fn=executor_fn,
            db_path=db_path,
        )

    def _on_resume_done(task: "asyncio.Task[Dict[str, Any]]") -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug(f"[WorkflowDAG] Resume-Task fuer Run '{run_id}' wurde abgebrochen.")
        except Exception as exc:
            logger.error(f"[WorkflowDAG] Resume-Task fuer Run '{run_id}' fehlgeschlagen: {exc}", exc_info=exc)
            try:
                with _connect(db_path) as conn:
                    conn.execute(
                        "UPDATE workflow_runs SET status = 'failed', updated_at = ? WHERE run_id = ?",
                        (time.time(), run_id),
                    )
                    conn.commit()
            except Exception as persist_exc:
                logger.error(
                    f"[WorkflowDAG] Failed-Status fuer Run '{run_id}' konnte nicht persistiert werden: {persist_exc}",
                    exc_info=persist_exc,
                )

    task = asyncio.create_task(_resume_runner())
    task.add_done_callback(_on_resume_done)
    return {"status": "scheduled", "run_id": run_id, "scheduled": True}

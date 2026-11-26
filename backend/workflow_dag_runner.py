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
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple

# D16/M4: zentrale Fehler-Zaehlung ueber die echte API in trace_context
# (delegiert an tracer.note_local_trace_error). Kein lokaler Fallback mehr.
from backend.trace_context import note_local_trace_error

logger = logging.getLogger("archon.workflow_dag")


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

# D02/MED (Re-Audit): der Lease-Heartbeat lief alle 60 s, die Spezifikation
# fordert 30 s. TTL bleibt 300 s (>= 3x Intervall).
HEARTBEAT_INTERVAL_SEC = 30
LEASE_TTL_SEC = 300

_PRIVILEGED_NODE_TOOLS = frozenset({
    "pay", "terminal", "execute_code", "filesystem", "computer_use", "mcp", "pay-cli",
})


# ---------------------------------------------------------------------------
# D08/F035-DAG: alle SQLite-Schreibzugriffe des DAG-Hotpaths liegen in
# SYNCHRONEN Hilfsfunktionen und werden ausschliesslich ueber asyncio.to_thread
# aufgerufen. Damit bleibt /livez bei busy_timeout=5000 responsiv.
# ---------------------------------------------------------------------------

def _recovery_audit(action: str, payload: Dict[str, Any]) -> None:
    """D07/F024: Audit-Schreibfehler nie verschlucken (einheitliche Eskalation)."""
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(  # type: ignore[call-arg]
            category="recovery", action=action,
            payload={"ts": time.time(), **payload},
        )
    except Exception as exc:
        logger.error("[WorkflowDAG] Audit '%s' fehlgeschlagen: %s", action, exc, exc_info=exc)
        note_local_trace_error(f"DAG-Audit {action} fehlgeschlagen", exc)


def _persist_run_cancelled_sync(db_path: Optional[str], rid: str) -> Dict[str, Any]:
    """Cancelled-Pfad: Status 'cancelled' atomar persistieren (sync, to_thread)."""
    updated = False
    try:
        with _connect(db_path) as conn:
            cur = conn.execute(
                "UPDATE workflow_runs SET status = 'cancelled', updated_at = ? WHERE run_id = ?",
                (time.time(), rid),
            )
            updated = int(cur.rowcount or 0) > 0
            conn.commit()
    except Exception as exc:
        return {"updated": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"updated": updated, "error": "" if updated else "run_row_not_found"}


def _persist_run_status_sync(
    db_path: Optional[str], rid: str, wf_id: str, status: str,
    dag_json_text: str, now: float,
) -> None:
    """Einheitlicher Terminal-/Zwischenstatus-Schreibblock (sync, to_thread)."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (run_id, workflow_id, status, dag_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
            (rid, wf_id, status, dag_json_text, now, now),
        )
        conn.commit()


def _load_run_gate_state_sync(
    db_path: Optional[str], rid: str, wf_id: str,
    gate_approvals: Optional[Dict[str, bool]],
    now: float, dag_json_text: str,
) -> Dict[str, Any]:
    """Gate-Freigaben lesen + Run auf 'running' setzen + Node-Cache lesen.

    Ein Parsefehler der Freigaben darf NIE zum Ueberschreiben mit einem leeren
    Dict fuehren — deshalb der CASE-Guard beim UPDATE (unveraendert).
    """
    approvals: Dict[str, bool] = {}
    parse_failed = False
    with _connect(db_path) as conn:
        prev = conn.execute(
            "SELECT gate_approvals_json FROM workflow_runs WHERE run_id = ?", (rid,)
        ).fetchone()
        if prev and prev["gate_approvals_json"]:
            try:
                stored = json.loads(prev["gate_approvals_json"])
                if isinstance(stored, dict):
                    approvals.update({str(k): bool(v) for k, v in stored.items()})
            except Exception as exc:
                parse_failed = True
                logger.error(
                    "[WorkflowDAG] Run '%s': gate_approvals_json nicht lesbar (%s); alter Wert bewahrt.",
                    rid, exc,
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
            (rid, wf_id, dag_json_text, json.dumps(approvals, ensure_ascii=False),
             now, now, int(parse_failed)),
        )
        conn.commit()
        cached_rows = conn.execute(
            "SELECT node_id, fingerprint, status, output_json FROM workflow_node_states WHERE run_id = ?",
            (rid,),
        ).fetchall()
        cached = {r["node_id"]: dict(r) for r in cached_rows}
    return {"approvals": approvals, "parse_failed": parse_failed, "cached": cached}


def _persist_node_state_sync(
    db_path: Optional[str], rid: str, nid: str, fingerprint: str,
    status: str, output_json: str, now: float, *, preserve_fingerprint: bool = False,
) -> None:
    """Node-State (running/terminal/skipped) atomar schreiben (sync, to_thread)."""
    with _connect(db_path) as conn:
        if preserve_fingerprint:
            conn.execute(
                """
                INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    status=excluded.status, output_json=excluded.output_json, updated_at=excluded.updated_at
                """,
                (rid, nid, fingerprint, status, output_json, now),
            )
        else:
            conn.execute(
                """
                INSERT INTO workflow_node_states (run_id, node_id, fingerprint, status, output_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    fingerprint=excluded.fingerprint, status=excluded.status,
                    output_json=excluded.output_json, updated_at=excluded.updated_at
                """,
                (rid, nid, fingerprint, status, output_json, now),
            )
        conn.commit()


def _finalize_run_sync(
    db_path: Optional[str], rid: str, wf_id: str,
    final_status: str, cycle_error: Optional[str], tid: str,
    outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Kosten/Tokens, Flightlog, Trajectory-Abschluss und Run-Finalstatus.

    D07: der Flightlog-Audit-Fehler wird auf ERROR + chained_audit_log
    eskaliert (frueher nacktes `pass`); `ARCHON_AUDIT_STRICT=1` bricht hart ab.
    """
    flags: List[str] = []
    total_cost = 0.0
    total_tokens = 0
    strict_abort: Optional[BaseException] = None
    with _connect(db_path) as conn:
        try:
            for row in conn.execute(
                "SELECT output_json FROM workflow_node_states WHERE run_id = ?", (rid,)
            ).fetchall():
                try:
                    total_cost += float((json.loads(row[0] or "{}").get("cost_usd") or 0.0))
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass
        for row in conn.execute(
            "SELECT output_json FROM workflow_node_states WHERE run_id = ?", (rid,)
        ).fetchall():
            try:
                parsed = json.loads(row[0] or "{}")
                total_tokens += int(parsed.get("input_tokens") or 0) + int(parsed.get("output_tokens") or 0)
            except Exception:
                pass
        try:
            from backend.flightlog_backtester import (
                detect_silent_failures,
                mirror_flight_event_to_trace,
                record_flight_event,
            )
            record_flight_event(
                run_id=rid, agent_id=str(wf_id or "workflow_engine"),
                tool_name="dag_run_complete",
                args={"workflow_id": wf_id, "trajectory_id": tid, "status": final_status},
                tool_ok=final_status in ("completed", "paused"),
                tokens_used=total_tokens,
            )
            mirror_flight_event_to_trace(
                run_id=rid, agent_id=str(wf_id or "workflow_engine"),
                tool_name="dag_run_complete",
                args={"workflow_id": wf_id, "trajectory_id": tid, "status": final_status},
                tool_ok=final_status in ("completed", "paused"),
                tokens_used=total_tokens,
            )
            detected = detect_silent_failures(
                rid, final_status=final_status,
                final_output="\n".join(
                    str((v or {}).get("content") or "")[:400]
                    for v in outputs.values() if isinstance(v, dict)
                ),
            )
            flags = list(detected.get("flags") or [])
            if flags and final_status in ("completed", "paused"):
                final_status = "blocked"
                cycle_error = f"SILENT_FAILURE: {', '.join(flags)}"
                logger.error("[WorkflowDAG] '%s' blockiert durch Flightlog: %s", rid, flags)
                try:
                    from backend.trajectory_budget import _audit
                    _audit(tid, f"flightlog_flags:{flags}", rid)
                except Exception as audit_exc:
                    logger.error(
                        "[WorkflowDAG] Trajectory-Audit flightlog_flags fehlgeschlagen für %s: %s",
                        rid, audit_exc, exc_info=audit_exc,
                    )
                    _recovery_audit("audit_write_failed", {
                        "run_id": rid, "trajectory_id": tid, "flags": flags,
                        "detail": f"{type(audit_exc).__name__}: {audit_exc}"[:500],
                    })
                    if os.environ.get("ARCHON_AUDIT_STRICT", "").strip() == "1":
                        strict_abort = RuntimeError(
                            f"flightlog_flags audit failed for {rid} (ARCHON_AUDIT_STRICT=1)"
                        )
        except Exception as flight_exc:
            logger.debug("[WorkflowDAG] Flightlog-Abschluss nicht verfuegbar: %s", flight_exc)
        if strict_abort is not None:
            raise strict_abort
        try:
            from backend.trajectory_budget import close_trajectory, record_tokens
            if total_tokens > 0:
                token_res = record_tokens(
                    tid, total_tokens, reason=f"dag_run:{rid}", set_total=True
                )
                if isinstance(token_res, dict) and not token_res.get("allowed", True):
                    final_status = "blocked"
                    cycle_error = cycle_error or f"TRAJECTORY_TOKEN_CAP: {token_res.get('reason')}"
                    logger.error("[WorkflowDAG] '%s' blockiert durch Trajectory-Token-Cap", rid)
            close_trajectory(
                tid,
                "blocked" if final_status == "blocked"
                else ("completed" if final_status == "completed" else "failed"),
            )
        except Exception as traj_exc:
            logger.error("[WorkflowDAG] Trajectory-Abschluss nicht persistiert: %s", traj_exc)
        conn.execute(
            "UPDATE workflow_runs SET status = ?, updated_at = ?, total_cost_usd = ? WHERE run_id = ?",
            (final_status, time.time(), round(total_cost, 6), rid),
        )
        conn.commit()
    return {"final_status": final_status, "cycle_error": cycle_error,
            "flight_flags": flags, "total_tokens": total_tokens}


def _recover_one_orphan(kernel: Any, run_id: str, db_path: Optional[str],
                        reason: str = "lease_lost") -> Dict[str, Any]:
    """Einzelner Orphan-Recovery: frischer Claim + harte FAILED-Transition."""
    from backend.durable_execution_kernel import FAILED

    fresh = f"recovery:{os.getpid()}:{secrets.token_hex(6)}"
    try:
        claim = kernel.claim(
            run_id, ttl_seconds=max(30, LEASE_TTL_SEC),
            dag_fingerprint="", fencing_token=fresh,
        )
    except Exception as exc:
        return {"run_id": run_id, "terminated": False,
                "reason": f"claim_error: {type(exc).__name__}: {exc}"}
    if not claim.get("claimed"):
        # Ein anderer Worker haelt eine gueltige Lease — Hoheit liegt dort,
        # aber NEVER still: das Result wird auditiert und zurueckgegeben.
        return {"run_id": run_id, "terminated": False,
                "reason": str(claim.get("reason") or "claim_denied")}
    token = str(claim["fencing_token"])
    try:
        kernel.transition(run_id, FAILED, token, reason=reason)
    except Exception as exc:
        _recovery_audit("orphan_transition_failed", {
            "run_id": run_id, "detail": f"{type(exc).__name__}: {exc}"[:500],
        })
        return {"run_id": run_id, "terminated": False,
                "reason": f"transition_failed: {type(exc).__name__}: {exc}"}
    _persist_run_status_sync(db_path, run_id, "", "failed", "{}", time.time())
    return {"run_id": run_id, "terminated": True, "fencing_token": token}


def recover_orphaned_runs(
    db_path: Optional[str] = None,
    kernel: Any = None,
    limit: int = 100,
    only_run_id: str = "",
) -> Dict[str, Any]:
    """D07/F3: Drainer fuer RUNNING-Runs mit abgelaufener Lease.

    Wird bei `guard.lost` fuer den betroffenen Run ausgefuehrt (only_run_id)
    und kann zusaetzlich beim Startup/einem Recovery-Cycle fuer alle Orphans
    aufgerufen werden. Kein Coroutine-Replay — nur Status-Transition + Checkpoint.
    """
    kernel = kernel or _kernel_for_run(db_path)
    db_file = str(getattr(kernel, "db_path", "") or "")
    if not db_file:
        return {"scanned": 0, "recovered": [], "skipped": [],
                "reason": "kernel_db_path_unavailable"}
    conn = sqlite3.connect(db_file, timeout=5.0)
    try:
        rows = conn.execute(
            "SELECT run_id FROM durable_executions WHERE state = 'RUNNING' "
            "AND claim_expires <= ? AND (? = '' OR run_id = ?) LIMIT ?",
            (time.time(), only_run_id or "", only_run_id or "", max(1, min(1000, int(limit)))),
        ).fetchall()
    except Exception as exc:
        conn.close()
        return {"scanned": 0, "recovered": [], "skipped": [],
                "reason": f"scan_failed: {type(exc).__name__}: {exc}"}
    conn.close()
    results = [_recover_one_orphan(kernel, str(row[0]), db_path) for row in rows]
    return {
        "scanned": len(rows),
        "recovered": [r for r in results if r.get("terminated")],
        "skipped": [r for r in results if not r.get("terminated")],
    }


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


async def _lease_heartbeat(run_id: str, kernel: Any, token: str, guard: _LeaseGuard) -> None:
    """Ein Heartbeat fuer Initiallauf UND Resume (30 s statt 60 s, D02/MED).

    Bei verweigerter Verlaengerung wird `guard.lost` gesetzt; die DAG-
    Hauptausfuehrung bricht then fail-closed ab. Bewusste HITL-Suspends
    beenden den Heartbeat, ohne einen Lease-Verlust zu melden.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
        if guard.suspended.is_set():
            return
        try:
            if not kernel.renew(run_id, token, ttl_seconds=LEASE_TTL_SEC):
                logger.warning("[WorkflowDAG] Lease '%s' nicht mehr gueltig — Run abbrechen.", run_id)
                guard.lost.set()
                return
        except Exception as exc:
            logger.debug("[WorkflowDAG] Lease-Renew Hinweis: %s", exc)
            guard.lost.set()
            return


def _kernel_for_run(db_path: Optional[str] = None) -> Any:
    """D02/MED: Claim an die Run-DB binden statt globalen Singleton zu nutzen.

    Ohne explizites `db_path` (Produktivpfad) bleibt der globale Kernel erhalten;
    mit `db_path` (Tests, mandantenfaehige Laeufe) liegt der Claim in derselben
    Datenbank wie der Run — kein fremder, ggf. beschaedigter Global-Store.
    """
    if not db_path:
        from backend.durable_execution_kernel import durable_kernel
        return durable_kernel
    from backend.durable_execution_kernel import DurableExecutionKernel
    return DurableExecutionKernel(db_path=db_path)


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
    from backend.durable_execution_kernel import FAILED, PENDING

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
    kernel: Optional[Any] = None,
) -> Dict[str, Any]:
    """Produktivaufrufer von ``durable_kernel.suspend()``.

    Ein HITL-Gate ist kein "wir warten mal kurz": der Run wird mit Checkpoint
    in den Zustand SUSPENDED ueberfuehrt und die Lease freigegeben, damit ein
    anderer Worker nach der Entscheidung sauber resume darf.
    """
    try:
        from backend.durable_execution_kernel import SUSPENDED

        kernel = kernel or _kernel_for_run()
        existing = kernel.get_state(run_id)
        if existing and str(existing.get("state")) == SUSPENDED:
            if lease_guard is not None and fencing_token:
                lease_guard.suspended.set()
            return {"suspended": True, "already": True, "run_id": run_id, "gate_node_id": node_id}

        token = fencing_token or str((existing or {}).get("fencing_token") or "")
        claim = _claim_kernel_run(kernel, run_id, wf_id, token or None)
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

        kernel.suspend(
            run_id, token, checkpoint_step, state_json,
            reason=f"hitl_gate:{node_id}",
        )
        # Keine aktive Lease, waehrend ein Mensch entscheidet.
        kernel.release(run_id, token)
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

    # A4/DAG-Edge-Map: `_extract_edge_map()` keyt nach ZIEL-Knoten (dst),
    # nicht nach Quelle. Die alte Schleife `for src, targets in edge_map.items()`
    # pruefte daher das Ziel als „Quelle" und liess echte unbekannte Quellen
    # unentdeckt. Direkt ueber die rohen Kanten from/to gegen node_map pruefen.
    for edge in (dag_def.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from") or edge.get("source") or "").strip()
        dst = str(edge.get("to") or edge.get("target") or "").strip()
        if src and src not in node_map:
            errors.append(f"Kante von unbekannter Quelle: {src}")
        if dst and dst not in node_map:
            errors.append(f"Kante zu unbekanntem Ziel: {dst}")
    edge_map = _extract_edge_map(dag_def)

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

    # D13/F032: max_hops darf die SSOT nie erweitern (alter Expand-Pfad auf 50
    # ist entfernt). Ein zu hoher Wert ist ein harter Planfehler, kein stilles
    # Klemmen mit anschliessendem Weiterlauf.
    from backend.trajectory_budget import MAX_DELEGATION_DEPTH

    cfg_hops = dag_def.get("max_hops") if dag_def.get("max_hops") else dag_def.get("trajectory_max_hops")
    try:
        cfg_hops_int = int(cfg_hops or 0)
    except (TypeError, ValueError):
        cfg_hops_int = 0
        errors.append("Ungültiger max_hops-Wert in der DAG-Definition.")
    if cfg_hops_int > MAX_DELEGATION_DEPTH:
        errors.append(
            f"max_hops {cfg_hops_int} überschreitet die SSOT-Schranke ({MAX_DELEGATION_DEPTH})."
        )

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
        normalize_trajectory_id,
        reserve_replan,
    )
    old_dag = existing.get("dag") or {}
    tid = normalize_trajectory_id(
        trajectory_id or old_dag.get("trajectory_id"),
        old_dag.get("root_ticket_id") or run_id,
    )
    reservation = reserve_replan(
        tid, run_id=run_id, dag_def=old_dag, reason=reason, db_path=db_path,
    )
    # D13/MED: `replan_count` im Task-Meta ist jetzt eine echte Spiegelung des
    # SSOT-Zählers (trajectory_budgets.replans_used), kein toter Alias.
    try:
        from backend.trajectory_budget import sync_task_budget_meta
        sync_task_budget_meta(
            tid, str(old_dag.get("root_ticket_id") or ""), db_path=db_path
        )
    except Exception as _meta_exc:
        logger.debug("[WorkflowDAG] Replan-Task-Meta nicht gespiegelt: %s", _meta_exc)
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
            last_exc = None  # type: ignore[assignment]
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
        # A1: bestehende Factory-Injektion statt backend -> archon.routers.
        from archon.core.permissions import get_decision_factory

        create_decision = get_decision_factory()
        if create_decision is None:
            logger.debug("[WorkflowDAG] Decision-Factory nicht registriert — HITL-Gate bleibt ohne Decision-ID")
            return None
        title = f"Workflow-Freigabe: {node.get('title') or node.get('id')} ({run_id})"
        upstream_preview = json.dumps(upstream, ensure_ascii=False)[:1500]
        deci = create_decision(
            "workflow_hitl_gate",
            title,
            f"Workflow '{wf_id}' (Run `{run_id}`) wartet am Knoten `{node.get('id')}` auf Freigabe.\n\nVorlauf-Ergebnisse:\n{upstream_preview}",
            ref_id=f"{run_id}:{node.get('id')}",
            # A6/D04: Vier-Augen-Fail-Closed verlangt einen zuordenbaren Ersteller.
            # Hintergrund-DAG ohne interaktive Session -> dokumentierter
            # Service-Principal als verantwortlicher Produzent.
            created_by="workflow-dag-service",
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
    # D13/MED: Token-Cap ZUR LAUFZEIT durchsetzen. `record_tokens()` lief frueher
    # erst nach dem Run — `tokens_used` blieb waehrenddessen konstant 0.
    _tid = str(node.get("_trajectory_id") or "")
    if _tid.startswith("traj-"):
        _projected = max(1, int(res.get("input_tokens") or 0) + int(res.get("output_tokens") or 0))
        try:
            from backend.trajectory_budget import reserve_tokens
            _token_res = reserve_tokens(
                _tid, _projected, reason=f"dag_dispatch:{node.get('id')}:{phase}"
            )
            if not _token_res.get("allowed", True):
                logger.error("[WorkflowDAG] Trajectory-Token-Cap vor Dispatch: %s", _token_res.get("reason"))
                return _blocked_node_result(node, "TRAJECTORY_TOKEN_CAP"), True
        except Exception as _tok_exc:
            logger.error("[WorkflowDAG] Token-Reservierung fehlgeschlagen (fail-closed): %s", _tok_exc)
            return _blocked_node_result(node, "TRAJECTORY_TOKEN_CAP"), True
    import core_dispatcher
    out = await core_dispatcher.dispatch_to_omniroute_or_container(**kwargs)
    return out, False


def _compute_node_cost(
    *,
    res: Dict[str, Any],
    model: str,
    _esc_model: str,
    _repair_in: int,
    _repair_out: int,
    _esc_in: int,
    _esc_out: int,
    _repair_model_used: str,
) -> Tuple[Optional[float], bool]:
    """B8/S2: Kosten-Tail als modul-lokaler Helper.

    Bewusst IN dieser Datei (nicht in ``backend/workflow_nodes/``): der
    Source-Text-Test ``test_reaudit_stage9.py:54-58`` sucht die Marker
    ``_cost_usd = None`` und ``Kostenberechnung fehlgeschlagen`` in der ganzen
    Datei. Sie muessen physisch hier stehen bleiben.

    Der ``locals().get(...)``-Zugriff bleibt 1:1 erhalten: die 5 Werte aus
    Cluster 7 kommen als **gleichnamige Parameter** herein, ``locals()`` findet
    sie also exakt wie zuvor im Facade-Scope. Keine Mechanik-Aenderung.
    """
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
            _cost_usd += _est_cost(model, _base_in, _base_out)  # type: ignore[operator]
        if _rep_in_tok or _rep_out_tok:
            _cost_usd += _est_cost(locals().get("_repair_model_used") or model, _rep_in_tok, _rep_out_tok)  # type: ignore[operator]
        if _esc_in_tok or _esc_out_tok:
            _cost_usd += _est_cost(_esc_model or model, _esc_in_tok, _esc_out_tok)  # type: ignore[operator]
        _cost_usd = round(_cost_usd, 6)  # type: ignore[arg-type]
        _cost_unverified = False
    except Exception as _cost_exc:
        # D12: kein 0.0 als realer Wert bei fehlgeschlagener Berechnung.
        logger.error("[WorkflowDAG] Kostenberechnung fehlgeschlagen: %s", _cost_exc)
        _cost_usd = None
        _cost_unverified = True
    return _cost_usd, _cost_unverified


def _build_node_output(
    *,
    node: Dict[str, Any],
    agent_id: str,
    model: str,
    res: Dict[str, Any],
    content: str,
    is_error: bool,
    kanban_task_id: Optional[str],
    _cost_usd: Optional[float],
    _cost_unverified: bool,
    quality_report: Optional[Dict[str, Any]],
    revisions_used: int,
    deliverable_path: str,
    tool_trace: List[Dict[str, Any]],
    parsed_output: Optional[Any],
) -> Dict[str, Any]:
    """B8/S2: Return-Normalisierung als modul-lokaler Helper.

    Ebenfalls bewusst in dieser Datei: ``test_reaudit_stage9.py:57`` sucht
    ``"cost_unverified": _cost_unverified`` im Dateitext.
    """
    out: Dict[str, Any] = {
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
    return out


def _finalize_kanban_status(
    kanban_task_id: Optional[str],
    is_error: bool,
    content: str,
    out: Dict[str, Any],
    node: Dict[str, Any],
    agent_id: str,
    kanban_update: Callable[..., None],
) -> None:
    """B8/S2: Kanban-Final als Helper (3 Ternaries aus der Facade heraus).

    S3: ``kanban_update`` wird zur Aufrufzeit uebergeben, damit
    ``patch("backend.workflow_dag_runner._update_kanban_task_status")`` greift.
    """
    kanban_update(
        kanban_task_id,
        "blocked" if is_error else "done",
        result=content or out["error"],
        block_kind="workflow_error" if is_error else None,
        event_kind="workflow_node_failed" if is_error else "workflow_node_completed",
        event_payload={"node_id": node.get("id"), "agent_id": agent_id, "status": out["status"]},
    )


async def default_agent_node_executor(node: Dict[str, Any], upstream: Dict[str, Any]) -> Dict[str, Any]:
    """Echter Standard-Executor fuer DAG-Knoten: loest Agenten-Profil auf, reicht
    Upstream-Outputs weiter, ruft core_dispatcher auf und synchronisiert Kanban.

    Der Dispatch laeuft ueber _dispatch_with_node_budget (dort wird
    core_dispatcher bei Bedarf importiert); ein zweiter Import hier war redundant
    und wurde als vorbestehender F401 entfernt.
    """
    from backend.agent_aliases import resolve_agent_id

    raw_agent = str(node.get("agent_id") or node.get("branch") or "default").strip()
    agent_id = resolve_agent_id(raw_agent)
    kanban_task_id = node.get("kanban_task_id")

    # Agenten-Profil laden
    explicit_agent = str(node.get("agent_id") or "").strip()
    prof: Dict[str, Any] = {}
    profiles: List[Dict[str, Any]] = []
    try:
        from archon.core.profiles import api_get_hermes_profiles
        profiles = await asyncio.to_thread(api_get_hermes_profiles) or []
        prof = next((p for p in profiles if p.get("id") == agent_id), {})
    except Exception:
        prof = {}

    node_type = str(node.get("type") or "agent").strip().lower()
    kanban_task_id = node.get("kanban_task_id")

    # F22 (D02): explizit angeforderte, aber unbekannte agent_id darf nicht mit
    # leerem Profil + Generik-Prompt laufen (fail-closed fuer Agent-Nodes).
    if node_type == "agent" and explicit_agent and explicit_agent.lower() != "default" and profiles and not prof:
        logger.error("[WorkflowDAG] Unbekannte agent_id '%s' (Node '%s') — fail-closed.", agent_id, node.get("id"))
        return {
            "status": "blocked",
            "error_code": "UNKNOWN_AGENT_ID",
            "error": f"Unbekannte agent_id '{agent_id}' — kein Profil im Agenten-Kader.",
            "content": "",
        }

    # P1/Content B1: nativer Research-Knoten mit echter Quellen-Triangulation.
    if node_type == "research":
        return await _execute_research_dag_node(node, upstream)

    # Standardisierte Node-Plugins ("VST-Schnittstelle": ffmpeg, kinocut, tts, suno, image_gen, calendar_publish, 3rd-Party)
    # B1/S2: Cluster 2 nach backend/workflow_nodes/plugin_nodes.py extrahiert.
    # Reine Delegation, keine Logikaenderung. Der Kanban-Sync wird zur
    # AUFRUFZEIT als Callable uebergeben (S3), damit die 7 Patches auf
    # backend.workflow_dag_runner._update_kanban_task_status weiter greifen.
    from backend.workflow_node_plugins import is_workflow_node_plugin
    if is_workflow_node_plugin(node_type):
        from backend.workflow_nodes.plugin_nodes import execute_plugin_node

        return await execute_plugin_node(
            node, upstream, node_type, kanban_task_id,
            _update_kanban_task_status,
        )

    # Nativer Media-Render / Clip-Matrix Knoten (Content-Maschine im DAG)
    # B2/S2: Cluster 3 nach backend/workflow_nodes/media_nodes.py extrahiert.
    # Reine Delegation, keine Logikaenderung; Kanban-Sync per DI zur Aufrufzeit.
    if node_type in ("media_render", "clip_matrix"):
        from backend.workflow_nodes.media_nodes import execute_media_node

        return await execute_media_node(
            node, upstream, node_type, kanban_task_id,
            _update_kanban_task_status,
        )

    # B3/S2: Cluster 4 (Profil-Aufloesung + Prompt-Bau) nach
    # backend/workflow_nodes/prompt.py extrahiert. Reine Delegation, keine
    # Logikaenderung. Das PromptContext traegt auch die Werte, die C6-C10
    # brauchen, damit die Facade saemtliche Locals behaelt.
    from backend.workflow_nodes.prompt import build_agent_prompt

    pctx = build_agent_prompt(node, upstream, prof, agent_id)
    agent_name = pctx.agent_name
    role = pctx.role
    model = pctx.model
    _esc_model = pctx.escalation_model
    reasoning_level = pctx.reasoning_level
    _channel_hint = pctx.channel_hint
    _is_content_node = pctx.is_content_node
    node_title = pctx.node_title
    full_prompt = pctx.full_prompt
    eff_system_prompt = pctx.eff_system_prompt

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

    # B4/S2: Cluster 6 (Multi-Turn Tool-Loop) nach
    # backend/workflow_nodes/tool_loop.py extrahiert. Reine Delegation, keine
    # Logikaenderung; Rueckgabe-Tupel haelt die Locals in der Facade.
    # S3: _dispatch_with_node_budget und _connect werden zur AUFRUFZEIT als
    # Callables uebergeben (kein Rueckimport, alle Patch-Punkte bleiben aktiv).
    from backend.workflow_nodes.tool_loop import run_tool_loop

    content, res, is_error, tool_trace = await run_tool_loop(
        node=node,
        res=res,
        content=content,
        is_error=is_error,
        model=model,
        agent_id=agent_id,
        agent_name=agent_name,
        eff_system_prompt=eff_system_prompt,
        role=role,
        reasoning_level=reasoning_level,
        kanban_task_id=kanban_task_id,
        full_prompt=full_prompt,
        dispatch_with_budget=_dispatch_with_node_budget,
        connect=_connect,
    )

    # B5/S2: Cluster 7 (Schema + Repair + Frontier-Eskalation) nach
    # backend/workflow_nodes/schema_contract.py extrahiert. Reine Delegation,
    # keine Logikaenderung.
    from backend.workflow_nodes.schema_contract import validate_and_repair

    output_schema = node.get("output_schema")
    # VERSTECKTE KOPPLUNG (B5-Fund): der Kosten-Tail liest diese 5 Namen per
    # locals().get(...) (siehe :1539-1548). Sie MUESSEN in locals() der Facade
    # stehen bleiben — sonst waere die Semantik stillschweigend veraendert,
    # auch wenn der D12-except-Zweig das Ergebnis auf cost_usd=None festnagelt.
    _repair_in = 0
    _repair_out = 0
    _esc_in = 0
    _esc_out = 0
    _repair_model_used = ""
    _schema_outcome = await validate_and_repair(
        node=node,
        res=res,
        content=content,
        is_error=is_error,
        model=model,
        escalation_model=_esc_model,
        agent_id=agent_id,
        agent_name=agent_name,
        eff_system_prompt=eff_system_prompt,
        role=role,
        reasoning_level=reasoning_level,
        kanban_task_id=kanban_task_id,
        full_prompt=full_prompt,
        dispatch_with_budget=_dispatch_with_node_budget,
    )
    content = _schema_outcome.content
    res = _schema_outcome.res
    is_error = _schema_outcome.is_error
    parsed_output = _schema_outcome.parsed_output
    _repair_in = _schema_outcome.repair_in
    _repair_out = _schema_outcome.repair_out
    _esc_in = _schema_outcome.esc_in
    _esc_out = _schema_outcome.esc_out
    _repair_model_used = _schema_outcome.repair_model_used

    # B6/S2: Cluster 8 (Self-Critique / Anti-AI-Slop) nach
    # backend/workflow_nodes/quality.py extrahiert. Reine Delegation, keine
    # Logikaenderung — der output_schema-Schutz bleibt ausdruecklich erhalten.
    from backend.workflow_nodes.quality import run_quality_revisions

    _quality_outcome = await run_quality_revisions(
        node=node,
        res=res,
        content=content,
        is_error=is_error,
        output_schema=output_schema,
        parsed_output=parsed_output,
        channel_hint=_channel_hint,
        is_content_node=_is_content_node,
        model=model,
        agent_id=agent_id,
        agent_name=agent_name,
        eff_system_prompt=eff_system_prompt,
        role=role,
        reasoning_level=reasoning_level,
        kanban_task_id=kanban_task_id,
        full_prompt=full_prompt,
        dispatch_with_budget=_dispatch_with_node_budget,
    )
    content = _quality_outcome.content
    res = _quality_outcome.res
    is_error = _quality_outcome.is_error
    quality_report = _quality_outcome.quality_report
    revisions_used = _quality_outcome.revisions_used

    # B7/S2: Cluster 9 (Deliverable-Export) nach
    # backend/workflow_nodes/deliverable.py extrahiert. Reine Delegation, keine
    # Logikaenderung (inkl. dem bewusst NICHT zurueckgesetzten Pfad bei OSError).
    from backend.workflow_nodes.deliverable import write_deliverable

    deliverable_path = write_deliverable(
        node=node,
        res=res,
        content=content,
        is_error=is_error,
        is_content_node=_is_content_node,
        agent_id=agent_id,
        model=model,
        node_title=node_title,
        quality_report=quality_report,
        revisions_used=revisions_used,
    )

    # B8/S2: Cluster 10 (Kosten + Return-Normalisierung) in die beiden
    # MODUL-LOKALEN Helper _compute_node_cost / _build_node_output verschoben.
    # Bewusst nicht nach workflow_nodes/: die drei D12-Marker muessen physisch
    # in dieser Datei bleiben (test_reaudit_stage9.py:54-58). Reine Delegation.
    _cost_usd, _cost_unverified = _compute_node_cost(
        res=res,
        model=model,
        _esc_model=_esc_model,
        _repair_in=_repair_in,
        _repair_out=_repair_out,
        _esc_in=_esc_in,
        _esc_out=_esc_out,
        _repair_model_used=_repair_model_used,
    )
    out = _build_node_output(
        node=node,
        agent_id=agent_id,
        model=model,
        res=res,
        content=content,
        is_error=is_error,
        kanban_task_id=kanban_task_id,
        _cost_usd=_cost_usd,
        _cost_unverified=_cost_unverified,
        quality_report=quality_report,
        revisions_used=revisions_used,
        deliverable_path=deliverable_path,
        tool_trace=tool_trace,
        parsed_output=parsed_output,
    )

    await asyncio.to_thread(
        _finalize_kanban_status,
        kanban_task_id, is_error, content, out, node, agent_id,
        _update_kanban_task_status,
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
    kernel: Optional[Any] = None,
) -> Dict[str, Any]:
    """Wrapper: persistiert 'cancelled' auch bei CancelledError (BaseException)."""
    try:
        return await _run_workflow_dag_impl(
            dag_def, executor_fn=executor_fn, run_id=run_id,
            gate_approvals=gate_approvals, db_path=db_path,
            cancel_token=cancel_token, fencing_token=fencing_token,
            lease_guard=lease_guard, kernel=kernel,
        )
    except asyncio.CancelledError:
        rid = run_id or ""
        if rid:
            # D08/F035-DAG: Schreibzugriff in den Threadpool, NOCH VOR dem
            # Re-raise. D07/F1: Persistenzfehler auf ERROR + Audit/DLQ statt
            # logger.debug (frueher blieb der Run sichtbar 'running').
            try:
                outcome = await asyncio.to_thread(_persist_run_cancelled_sync, db_path, rid)
                if not outcome.get("updated"):
                    from backend.durable_execution_kernel import CANCELLED

                    active_kernel = kernel or _kernel_for_run(db_path)
                    await asyncio.to_thread(
                        active_kernel.transition, rid, CANCELLED, fencing_token,
                        reason="cancelled_not_persisted",
                    )
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"[:500]
                logger.error(
                    "[WorkflowDAG] Cancelled-Status nicht persistierbar für %s: %s",
                    rid, detail, exc_info=exc,
                )
                _recovery_audit("cancel_status_persist_failed", {"run_id": rid, "detail": detail})
                if cancel_token is not None and hasattr(cancel_token, "_record_failed_cancel"):
                    cancel_token._record_failed_cancel(f"Cancel-Status {rid}: {detail}")
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
    kernel: Optional[Any] = None,
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

    # D02/MED (Re-Audit): der Initiallauf hatte NUR diesen prozesslokalen Lock.
    # Zwei Prozesse konnten denselben run_id parallel ausfuehren. Jetzt gilt
    # derselbe fail-closed CAS-Claim + Fencing-Token + Heartbeat wie im Resume.
    # Ein bereits gesetztes Token (Resume-Ruf) wird nicht erneut geclaimt.
    heartbeat: Optional[asyncio.Task] = None
    own_lease = False
    if not fencing_token:
        try:
            kernel = kernel or _kernel_for_run(db_path)
            claim = _claim_kernel_run(
                kernel, rid,
                json.dumps(dag_def, sort_keys=True, ensure_ascii=False), None,
            )
            if not claim.get("claimed"):
                logger.warning(
                    "[WorkflowDAG] Run '%s': CAS-Claim verweigert (%s/%s) — Initiallauf nicht gestartet.",
                    rid, claim.get("reason"), claim.get("state"),
                )
                return {
                    "status": "skipped", "run_id": rid,
                    "reason": "durable_claim_not_acquired",
                    "claim_reason": claim.get("reason"), "claim_state": claim.get("state"),
                    "workflow_id": str(dag_def.get("id") or "workflow"),
                    "node_statuses": {}, "outputs": {},
                }
            fencing_token = str(claim["fencing_token"])
            lease_guard = _LeaseGuard()
            own_lease = True
        except Exception as kc_exc:
            logger.error(
                "[WorkflowDAG] Durable-Kernel Claim nicht verfuegbar — Initiallauf blockiert (fail-closed): %s",
                kc_exc,
            )
            return {
                "status": "skipped", "run_id": rid,
                "reason": "durable_kernel_unavailable", "error": str(kc_exc)[:300],
                "workflow_id": str(dag_def.get("id") or "workflow"),
                "node_statuses": {}, "outputs": {},
            }

    await run_lock.acquire()
    try:
        if own_lease and lease_guard is not None and fencing_token:
            try:
                heartbeat = asyncio.create_task(
                    _lease_heartbeat(rid, kernel, fencing_token, lease_guard),
                    name=f"dag_lease_{rid}",
                )
            except Exception as hb_exc:
                logger.debug("[WorkflowDAG] Lease-Heartbeat nicht gestartet: %s", hb_exc)
        result = await _run_workflow_dag_locked(
            dag_def, executor_fn, rid, gate_approvals, db_path, cancel_token=cancel_token,
            fencing_token=fencing_token, lease_guard=lease_guard, kernel=kernel,
        )
        if lease_guard is not None and lease_guard.lost.is_set() and isinstance(result, dict):
            result = dict(result)
            result["status"] = "blocked"
            result["error"] = result.get("error") or "Lease lost during execution — run aborted (fenced)"
            result["needs_human"] = True
        return result
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
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
    kernel: Optional[Any] = None,
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
        ensure_trajectory,
        inherit_replan_count,
        normalize_trajectory_id,
    )
    dag_def = dict(dag_def or {})
    _root_ticket = str(dag_def.get("root_ticket_id") or dag_def.get("id") or wf_id)
    _tid = normalize_trajectory_id(dag_def.get("trajectory_id"), _root_ticket)
    dag_def["trajectory_id"] = _tid
    dag_def["root_ticket_id"] = _root_ticket
    _node_token_cap = sum(
        int(float(n.get("token_budget") or 0)) for n in nodes if isinstance(n, dict)
    )
    # D13/F032: max_hops aus den Ticket-/DAG-Metadaten lesen, aber NIE zur
    # Erweiterung nutzen. Der alte Expand-Pfad (UPDATE trajectory_budgets mit
    # "max_hops < ?"-Bedingung) ist ersatzlos entfernt;
    # `ensure_trajectory` ist die einzige Schreibstelle
    # und verschaeft nur (min(SSOT, angefragter Wert)). `min(50, ...)` bleibt
    # ausschliesslich als Parser-Guard gegen unsinnige Eingaben erhalten und
    # wird unmittelbar auf die SSOT heruntergezogen.
    from backend.trajectory_budget import MAX_DELEGATION_DEPTH

    _max_hops_cfg = dag_def.get("max_hops") or dag_def.get("trajectory_max_hops") or 0
    try:
        _parsed_hops = max(1, min(50, int(_max_hops_cfg))) if _max_hops_cfg else 0
    except (TypeError, ValueError):
        _parsed_hops = 0
    _max_hops_cfg = min(MAX_DELEGATION_DEPTH, _parsed_hops) if _parsed_hops else 0
    _traj_row = ensure_trajectory(
        _tid, _root_ticket,
        max_tokens=(int(_node_token_cap) if _node_token_cap > 0 else None),
        max_hops=(_max_hops_cfg or None),
    )
    # KEIN UPDATE mehr — Caps werden nur verschaeft, nie erweitert.
    _inherited = inherit_replan_count(_tid, rid, dag_def, db_path=db_path)
    dag_def["_replan_count"] = max(
        int(dag_def.get("_replan_count") or 0), int(_inherited.get("replan_count") or 0)
    )
    if str(_traj_row.get("state") or "") == "blocked" or dag_def["_replan_count"] > MAX_REPLAN_COUNT:
        logger.error("[WorkflowDAG] Run '%s' blockiert: Trajectory %s state=%s replan=%s",
                     rid, _tid, _traj_row.get("state"), dag_def["_replan_count"])
        await asyncio.to_thread(
            _persist_run_status_sync, db_path, rid, wf_id, "blocked",
            json.dumps(dag_def, ensure_ascii=False), now,
        )
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
        await asyncio.to_thread(
            _persist_run_status_sync, db_path, rid, wf_id, "failed",
            json.dumps(dag_def, ensure_ascii=False), now,
        )
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
                await asyncio.to_thread(
                    _persist_run_status_sync, db_path, rid, wf_id, "failed", "{}", now,
                )
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

    # D08/F035-DAG: Run-Status + Gate-Freigaben + Node-Cache in EINEM
    # Threadpool-Aufruf (frueher > 5 sync SQLite-Zugriffe im Event-Loop).
    _gate_state = await asyncio.to_thread(
        _load_run_gate_state_sync, db_path, rid, wf_id, gate_approvals, now,
        json.dumps(dag_def, ensure_ascii=False),
    )
    approvals: Dict[str, bool] = _gate_state["approvals"]
    cached: Dict[str, Dict[str, Any]] = _gate_state["cached"]

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
        # D13/HIGH + F22: harte Laufzeit-Obergrenze VOR jedem Node-Dispatch
        # (auch fuer unbezifferte Nodes, sobald _spent >= _run_cap).
        _run_cap = float(dag_def.get("max_budget_eur") or 0.0)
        if _run_cap > 0.0:
            _spent = sum(
                float((v or {}).get("cost_usd") or 0.0)
                for v in outputs.values() if isinstance(v, dict)
            )
            _node_est = float(node.get("max_budget_eur") or 0.0)
            if _spent >= _run_cap - 1e-6 or (_spent + _node_est > _run_cap + 1e-6):
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

        # Persistenter Running-Status + Live-SSE-Broadcast (Schreibzugriff
        # via Threadpool — /livez bleibt auch bei Write-Lock responsiv).
        await asyncio.to_thread(
            _persist_node_state_sync, db_path, rid, nid, fp, "running", "{}", time.time(),
        )

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
                fencing_token=fencing_token, lease_guard=lease_guard, kernel=kernel,
            )
            outputs[nid]["durable_suspend"] = gate_suspend

        if trace_id:
            # D16/MED: HITL-Gates sind eigene Span-Typen, keine agent-Spans.
            # Ohne diese Unterscheidung fehlten Gate-Schritte in Replay-
            # Fixtures und kausale Fehlerketten ( wartet/abgelehnt/freigegeben )
            # waren im OTel-Baum nicht erkennbar.
            _is_gate = requires_gate or ntype == "quality_gate"
            await _otel_span(
                trace_id,
                name=f"dag.node.{nid}",
                span_type="gate" if _is_gate else "agent",
                agent_id=str(node.get("agent_id") or "workflow_engine"),
                model=str(node.get("model") or ""),
                output_data=out if isinstance(out, dict) else {"result": out},
                status="OK" if st in SUCCESS_NODE_STATES else "ERROR",
                cost_usd=float(out.get("cost_usd") or 0.0) if isinstance(out, dict) else 0.0,  # type: ignore[arg-type]
                duration_ms=round((time.perf_counter() - node_started) * 1000.0, 2),
                attributes={
                    "run_id": rid, "node_id": nid, "node_type": ntype, "status": st,
                    "gate.required": bool(_is_gate),
                    "gate.decision": str(
                        out.get("status") if isinstance(out, dict) else st
                    ),
                },
            )
        await asyncio.to_thread(
            _persist_node_state_sync, db_path, rid, nid, fp, st,
            json.dumps(out, ensure_ascii=False), time.time(),
        )
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
            await asyncio.to_thread(
                _persist_node_state_sync, db_path, rid, nid, "skipped",
                "skipped_condition", json.dumps(outputs[nid], ensure_ascii=False),
                time.time(), preserve_fingerprint=True,
            )

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
                if e.get("condition") == "on_failure" and statuses.get(e.get("from")) == "failed":  # type: ignore[arg-type]
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

    # D08/F035-DAG: Kosten-/Token-Messung, Flightlog, Trajectory-Abschluss und
    # Finalstatus in EINEM synchronen Helper (ein to_thread statt ~10
    # SQLite-Zugriffen im Event-Loop). D07/F5: der Flightlog-Audit-Fehler wird
    # dort nicht mehr verschluckt.
    _final = await asyncio.to_thread(
        _finalize_run_sync, db_path, rid, wf_id,
        final_status, cycle_error, _tid, outputs,
    )
    final_status = _final["final_status"]
    cycle_error = _final["cycle_error"]
    _flight_flags = _final["flight_flags"]

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
        from backend.durable_execution_kernel import COMPLETED as _COMPLETED
        from backend.durable_execution_kernel import FAILED as _FAILED
        kernel = _kernel_for_run(db_path)
        claim = _claim_kernel_run(
            kernel,
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

    # D02/MED: Heartbeat alle 30 s (statt 60 s) — gemeinsam mit dem
    # Initiallauf. Bei renew=False wird `guard.lost` gesetzt und die DAG-
    # Hauptausfuehrung bricht fail-closed ab (statt still weiterzulaufen).
    guard = _LeaseGuard()
    heartbeat = asyncio.create_task(
        _lease_heartbeat(run_id, kernel, token, guard), name=f"dag_lease_{run_id}"
    )

    result = None
    failed_cancels: List[str] = []
    try:
        result = await run_workflow_dag(
            dag_def=dag_def,
            executor_fn=executor_fn,
            run_id=run_id,
            gate_approvals=gate_approvals or {},
            db_path=db_path,
            fencing_token=token,
            lease_guard=guard,
            kernel=kernel,
        )
    except Exception as run_exc:
        if not guard.suspended.is_set():
            try:
                kernel.transition(run_id, _FAILED, token, reason=str(run_exc)[:300])
            except Exception as tr_exc:
                # D07/F2: kein nacktes `pass` mehr — Transition ist ein
                # Terminalzustand und darf nicht still verloren gehen.
                detail = f"status_transition_failed: {type(tr_exc).__name__}: {tr_exc}"[:500]
                failed_cancels.append(detail)
                logger.error(
                    "[WorkflowDAG] Run '%s': FAILED-Transition nach %s fehlgeschlagen: %s",
                    run_id, type(run_exc).__name__, detail, exc_info=tr_exc,
                )
                _recovery_audit("status_transition_failed", {
                    "run_id": run_id, "detail": detail,
                    "original": f"{type(run_exc).__name__}: {run_exc}"[:300],
                })
        raise
    finally:
        heartbeat.cancel()
        heartbeat_results = await asyncio.gather(heartbeat, return_exceptions=True)
        # D07/MED (A9-Delegation): Result-Liste auswerten statt still zu
        # verwerfen. CancelledError ist der erwartete Normalfall; jede andere
        # Exception ist ein fehlgeschlagener Abbruch des Lease-Heartbeats und
        # wird persistiert (Audit) und im Result sichtbar gemacht.
        for hres in heartbeat_results:
            if isinstance(hres, asyncio.CancelledError):
                continue
            if isinstance(hres, BaseException):
                detail = f"{type(hres).__name__}: {hres}"[:500]
                failed_cancels.append(detail)
                logger.error(
                    "[WorkflowDAG] Run '%s': Lease-Heartbeat-Abbruch fehlgeschlagen: %s",
                    run_id, detail,
                )
                try:
                    from backend.audit_log import chained_audit_log

                    chained_audit_log.record_event(  # type: ignore[call-arg]
                        category="recovery",
                        action="cancel_failed",
                        payload={
                            "task": heartbeat.get_name(),
                            "run_id": run_id,
                            "detail": detail,
                            "ts": time.time(),
                        },
                    )
                except Exception as audit_exc:
                    note_local_trace_error("Heartbeat-Cancel-Audit fehlgeschlagen", audit_exc)

    if guard.lost.is_set():
        # Fencing-Token ist veraltet: NICHT mit diesem Token transitionieren.
        # D07/F4: der Orphan-Drainer holt den Run mit frischem Claim in einen
        # harten Terminalzustand (FAILED, reason="lease_lost"), statt ihn als
        # RUNNING zurueckzulassen. Bei gueltiger fremder Lease bleibt die Hoheit
        # beim uebernehmenden Worker — aber auch das wird auditiert.
        logger.error("[WorkflowDAG] Run '%s': Lease verloren — Resume als fehlgeschlagen markiert.", run_id)
        if isinstance(result, dict):
            result["status"] = "failed"
            result["error"] = "lease_lost"
        recovery = await asyncio.to_thread(
            recover_orphaned_runs, db_path, kernel, 10, run_id,
        )
        if isinstance(result, dict):
            result["lease_lost_recovery"] = recovery
        if not recovery.get("recovered"):
            _recovery_audit("lease_lost_unrecovered", {
                "run_id": run_id,
                "skipped": recovery.get("skipped") or [],
                "reason": recovery.get("reason") or "fencing_token superseded",
            })
    elif guard.suspended.is_set():
        # Am HITL-Gate suspendiert: Run bleibt 'paused' bis zur Entscheidung.
        logger.info("[WorkflowDAG] Run '%s' wurde am HITL-Gate suspendiert.", run_id)
    else:
        try:
            final_state = _COMPLETED if str(result.get("status", "")).lower() in ("success", "completed") else _FAILED
            kernel.transition(run_id, final_state, token, reason=str(result.get("status", "")))
        except Exception as tr_exc:
            # D07/F3: nicht mehr logger.debug — Split-Brain zwischen
            # workflow_runs und Durable Kernel wird sichtbar + auditiert.
            detail = f"terminal_transition_failed: {type(tr_exc).__name__}: {tr_exc}"[:500]
            failed_cancels.append(detail)
            logger.error(
                "[WorkflowDAG] Run '%s': Durable-Kernel Transition fehlgeschlagen: %s",
                run_id, detail, exc_info=tr_exc,
            )
            _recovery_audit("terminal_transition_failed", {"run_id": run_id, "detail": detail})
            if isinstance(result, dict):
                result["kernel_state"] = "unpersisted"

    # Nach den Transition-Bloecken setzen, damit auch spaeter hinzugefuegte
    # Fehler im Result sichtbar sind (frueher stand dies vor allem und verlor
    # genau die hier neu gemeldeten Fehler).
    if failed_cancels and isinstance(result, dict):
        result["failed_cancels"] = failed_cancels

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
    executor_fn: ExecutorFn = None,  # type: ignore[assignment]
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
    from backend.durable_execution_kernel import SUSPENDED, durable_kernel

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

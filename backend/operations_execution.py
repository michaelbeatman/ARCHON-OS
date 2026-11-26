"""Kanban Task-Ausfuehrung, Lease/Cancel-Fencing & Cross-Model-Verification (D3/6).

Ausgelagert aus ``backend/operations_api.py`` nach dem S3-Muster
(Call-Time-Dependency-Injection ueber ``register_execution_deps_provider``):
* Kein Rueckimport auf ``backend.operations_api``.
* Kein Import aus ``archon.routers.*`` (wahrt Layer-Contract D09/H-09-2).
* Alle Monkeypatches auf ``backend.operations_api._get_kanban_connection``,
  ``_load_profiles_map``, ``_load_kanban_meta``, ``_sync_to_memory_bridge``,
  ``_resolve_task_obsidian_rel``, ``_load_kanban_delegation_payload`` und
  ``_get_active_kanban_db_path`` greifen unveraendert zur Aufrufzeit.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, NamedTuple, Optional, Set

from archon.core.provider_registry import get_provider
from backend.handoff_desk import mark_truncated, require_accepted_handoff

logger = logging.getLogger("archon_os.operations_api")

# W3-C/M1: explizite Positiv-Feldliste fuer den Child-Kontext.
# `model_dump(exclude_defaults=True)` liess gerade die Default-Werte
# (taint=unknown, soul=compact, leere ACLs) und trace/warrant/budget im Kind
# verschwinden. Diese Liste ist die verbindliche Minimal-Hydrierung.
_DELEGATION_CHILD_FIELDS = (
    "task_id", "ziel_agent", "auftrag", "trace_id", "correlation_id",
    "tenant_id", "project_id", "cancel_scope", "taint_status",
    "budget_remaining_tokens", "soul_mode", "reasoning_level",
    "delegation_chain", "session_id", "origin_session_id", "tgt_session_id",
    "isolated", "allowed_tools", "allowed_skills", "memory_scope",
    "memory_acl", "memory_ttl_seconds", "acceptance_criteria", "reply_to",
    "trajectory_id", "root_ticket_id", "hops_used", "via", "delegator",
    "warrant_id", "complexity_weight", "budget_share_pct", "token_budget",
    "extensions", "payload_signature",
)

_CONSECUTIVE_FAILURES_MIGRATED_DBS: Set[str] = set()


class ExecutionDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus backend.operations_api."""

    get_active_kanban_db_path: Callable[[], str]
    get_kanban_connection: Callable[..., Any]
    load_kanban_delegation_payload: Callable[..., Any]
    sync_to_memory_bridge: Callable[..., Any]
    load_profiles_map: Callable[[], Dict[str, Any]]
    resolve_task_obsidian_rel: Callable[..., Optional[str]]
    load_kanban_meta: Callable[[], Dict[str, Any]]


_DEPS_PROVIDER: Optional[Callable[[], ExecutionDeps]] = None


def register_execution_deps_provider(provider: Callable[[], ExecutionDeps]) -> None:
    """Registriert den Call-Time-Resolver fuer backend.operations_api (S3-Muster)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _resolve_deps(deps: Optional[ExecutionDeps] = None) -> ExecutionDeps:
    if deps is not None:
        return deps
    if _DEPS_PROVIDER is None:
        raise RuntimeError("ExecutionDeps provider nicht registriert")
    return _DEPS_PROVIDER()


def _ensure_consecutive_failures_column(conn: sqlite3.Connection) -> None:
    """Fix-Sprint Paket A (Punkt 10): Retry-Zaehler-Spalte nachziehen, falls das
    Schema aelter ist. Wird einmal pro DB-Pfad ausgefuehrt."""
    deps = _resolve_deps()
    target_db = deps.get_active_kanban_db_path()
    if target_db in _CONSECUTIVE_FAILURES_MIGRATED_DBS:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "consecutive_failures" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN consecutive_failures INTEGER DEFAULT 0")
        conn.commit()
        print(
            f"[OperationsAPI] Schema-Migration: tasks.consecutive_failures hinzugefuegt ({target_db}).",
            file=sys.stderr,
        )
    _CONSECUTIVE_FAILURES_MIGRATED_DBS.add(target_db)


def _accept_loaded_handoff(conn: Any, task_id: str, model: Any) -> None:
    """D11 (A8): Empfaenger-Worker quittiert das geladene A2A-Envelope."""
    try:
        from backend.handoff_desk import handoff_desk

        h_id = str(handoff_desk.latest_handoff_id_for_task(
            task_id, to_agent=str(getattr(model, "ziel_agent", "") or "")
        ) or "").strip()
        if not h_id:
            return
        row = handoff_desk.get_handoff(h_id) or {}
        if str(row.get("status") or "") == "accepted":
            return  # idempotent, kein Event-Replay (G-01/G-02)
        receiver = str(row.get("to_agent") or "").strip()
        if not receiver:
            return
        result = handoff_desk.accept_handoff(h_id, receiver)
        accepted = result.get("status") == "accepted"
        payload = {
            "handoff_id": h_id,
            "receiving_agent": str(result.get("receiving_agent") or receiver),
            "acceptance": result,
            "trace_id": str(result.get("trace_id") or getattr(model, "trace_id", "") or ""),
            "session_id": str(result.get("session_id") or getattr(model, "session_id", "") or ""),
            "correlation_id": str(result.get("correlation_id") or getattr(model, "correlation_id", "") or ""),
        }
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                task_id,
                "handoff_accepted" if accepted else "handoff_accept_failed",
                json.dumps(payload, ensure_ascii=False),
                datetime.datetime.now().isoformat(),
            ),
        )
        conn.commit()
        try:
            from backend.audit_log import chained_audit_log

            chained_audit_log.record_event(
                category="handoff",
                action="handoff_accepted_by_worker" if accepted else "handoff_accept_failed",
                agent_id=receiver or "system",
                payload=payload,
            )
        except Exception as audit_exc:
            logger.warning("[KanbanWorker] Handoff-Audit fehlgeschlagen: %s", audit_exc)
    except Exception as exc:
        logger.debug("[KanbanWorker] Automatische Handoff-Annahme nicht moeglich: %s", exc)


def _merge_task_meta_facts(task_id: str, facts: Dict[str, Any]) -> None:
    """D11 (A8): Prompt-Ref + Korrelations-IDs nach ``mc_task_meta`` spiegeln."""
    if not task_id or not facts:
        return
    deps = _resolve_deps()
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mc_task_meta ("
            "task_id TEXT PRIMARY KEY, meta_json TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        row = conn.execute(
            "SELECT meta_json FROM mc_task_meta WHERE task_id = ?", (task_id,)
        ).fetchone()
        meta: Dict[str, Any] = {}
        if row is not None:
            raw = row["meta_json"] if hasattr(row, "keys") else row[0]
            if raw:
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        meta = loaded
                except (TypeError, ValueError):
                    meta = {}
        meta.update(facts)
        conn.execute(
            "INSERT INTO mc_task_meta (task_id, meta_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET meta_json = excluded.meta_json, "
            "updated_at = excluded.updated_at",
            (task_id, json.dumps(meta, ensure_ascii=False), time.time()),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[OperationsAPI] mc_task_meta-Fakten-Spiegelung fehlgeschlagen: %s", exc)
    finally:
        conn.close()


def _kanban_load_task_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """F-055: SQLite-Punktabfrage im Worker-Thread statt im Event-Loop."""
    deps = _resolve_deps()
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        _ensure_consecutive_failures_column(conn)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        ev = conn.execute(
            "SELECT payload FROM task_events WHERE task_id = ? AND kind = 'created' "
            "ORDER BY rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if ev is not None:
            raw_payload = ev["payload"] if hasattr(ev, "keys") else ev[0]
            # D11-H1/H2: signierte Übergaben werden vor jeder Kanonisierung
            # geprüft und unverändert konsumiert. Manipulation → harter Block.
            from archon.core.delegation import is_signed_delegation_payload

            signed = is_signed_delegation_payload(raw_payload)
            model = deps.load_kanban_delegation_payload(
                raw_payload, task_id=task_id, require_signature=signed
            )
            if signed and model is None:
                task["_delegation_signature_invalid"] = True
                logger.error(
                    "[KanbanWorker] Signatur des created-Events fuer %s ungueltig — Dispatch gesperrt.",
                    task_id,
                )
            elif model is not None:
                # Unverändert: genau die signierte Fassung, kein neues Dict.
                task["_delegation_payload"] = model.model_dump()
                task["_delegation_payload_model"] = model
                task["_delegation_signed"] = signed
                _accept_loaded_handoff(conn, task_id, model)
        return task
    finally:
        conn.close()


def _kanban_autonomy_gate_sync(task_id: str, autonomy: str) -> str:
    """F-055: Autonomie-/Freigabe-Gate im Worker-Thread. Liefert die Aktion."""
    deps = _resolve_deps()
    gate = deps.get_kanban_connection(maintenance=True)
    try:
        now = datetime.datetime.now().isoformat()
        row = gate.execute("SELECT block_kind FROM tasks WHERE id = ?", (task_id,)).fetchone()
        block_kind = row["block_kind"] if row is not None and hasattr(row, "keys") else (row[0] if row else None)
        if autonomy == "manual":
            gate.execute("UPDATE tasks SET status = 'todo' WHERE id = ?", (task_id,))
            gate.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'autonomy_manual', ?, ?)",
                (task_id, json.dumps({"level": "manual", "reason": "Nur Vorschlag — Ausführung gesperrt"}), now),
            )
            gate.commit()
            print(f"[Autonomy] Task {task_id} nicht gestartet (manual).")
            return "manual"
        if block_kind != "approval_granted":
            gate.execute("UPDATE tasks SET status = 'blocked', block_kind = 'approval' WHERE id = ?", (task_id,))
            gate.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'awaiting_approval', ?, ?)",
                (task_id, json.dumps({"level": "approval", "reason": "Freigabe erforderlich"}), now),
            )
            gate.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'blocked', ?, ?)",
                (task_id, json.dumps({"reason": "approval_required"}), now),
            )
            gate.commit()
            print(f"[Autonomy] Task {task_id} wartet auf Freigabe.")
            return "awaiting_approval"
        gate.execute("UPDATE tasks SET block_kind = NULL WHERE id = ?", (task_id,))
        gate.commit()
        return "continue"
    finally:
        gate.close()


def _kanban_mark_started_sync(task_id: str, assignee: str) -> None:
    """F-055: Status-Update + Event im Worker-Thread."""
    deps = _resolve_deps()
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        now = datetime.datetime.now().isoformat()
        conn.execute("UPDATE tasks SET status = 'in_progress', started_at = ? WHERE id = ?", (now, task_id))
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'started', ?, ?)",
            (task_id, json.dumps({"status": "in_progress", "agent": assignee}), now),
        )
        conn.commit()
    finally:
        conn.close()


def _kanban_assign_orchestrator_sync(task_id: str) -> None:
    """F-055: Auto-Zuweisung im Worker-Thread."""
    deps = _resolve_deps()
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        now = datetime.datetime.now().isoformat()
        conn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", ("default", task_id))
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'auto_assigned_orchestrator', ?, ?)",
            (
                task_id,
                json.dumps(
                    {"assignee": "default", "reason": "Kein Profil gesetzt — automatische Zuweisung an Orchestrator"}
                ),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _persist_kanban_result_sync(
    task_id: str,
    *,
    mode: str,
    title: str = "",
    assignee: str = "",
    target_status: str = "",
    reply: str = "",
    verdict: Optional[Dict[str, Any]] = None,
    proof_facts: Optional[Dict[str, Any]] = None,
    is_success: bool = False,
) -> Dict[str, Any]:
    """D08/H-08-3: kompletter Terminalstatus-Persistenzblock im Worker-Thread."""
    deps = _resolve_deps()
    _get_kanban_connection = deps.get_kanban_connection
    facts: Dict[str, Any] = dict(proof_facts or {})
    verdict = dict(verdict or {})
    now_iso = datetime.datetime.now().isoformat()
    conn = _get_kanban_connection(maintenance=True)
    persisted_status = target_status
    try:
        if mode == "result":
            if target_status == "blocked" and verdict.get("block_kind"):
                conn.execute(
                    "UPDATE tasks SET status = 'blocked', block_kind = ?, result = ?, consecutive_failures = COALESCE(consecutive_failures, 0) + 1 WHERE id = ?",
                    (verdict["block_kind"], reply, task_id),
                )
                conn.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'awaiting_approval', ?, ?)",
                    (
                        task_id,
                        json.dumps(
                            {
                                "block_kind": verdict["block_kind"],
                                "options": verdict.get("hitl_options", []),
                                "reason": verdict.get("reason"),
                                **facts,
                            }
                        ),
                        now_iso,
                    ),
                )
                conn.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'blocked', ?, ?)",
                    (task_id, json.dumps({"reason": verdict["block_kind"], **facts}), now_iso),
                )
            elif target_status == "failed":
                conn.execute(
                    "UPDATE tasks SET status = 'failed', result = ?, consecutive_failures = COALESCE(consecutive_failures, 0) + 1 WHERE id = ?",
                    (reply, task_id),
                )
                conn.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'failed', ?, ?)",
                    (
                        task_id,
                        json.dumps({
                            **facts,
                            "status": "failed",
                            "summary": mark_truncated(reply, 200, artifact=f"tasks.result/{task_id}"),
                            "truncated": len(reply) > 200,
                            "original_length": len(reply),
                            "verified": False,
                        }),
                        now_iso,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status = ?, completed_at = ?, result = ?, consecutive_failures = 0 WHERE id = ?",
                    (target_status, now_iso, reply, task_id),
                )
                conn.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'completed', ?, ?)",
                    (
                        task_id,
                        json.dumps({
                            **facts,
                            "status": target_status,
                            "summary": mark_truncated(reply, 200, artifact=f"tasks.result/{task_id}"),
                            "truncated": len(reply) > 200,
                            "original_length": len(reply),
                            "verified": is_success,
                        }),
                        now_iso,
                    ),
                )
        elif mode == "error":
            persisted_status = "blocked"
            conn.execute(
                "UPDATE tasks SET status = 'blocked', result = ?, consecutive_failures = COALESCE(consecutive_failures, 0) + 1 WHERE id = ?",
                (reply, task_id),
            )
        elif mode == "cancelled":
            persisted_status = "cancelled"
            conn.execute(
                "UPDATE tasks SET status = 'cancelled', result = ? WHERE id = ?",
                (reply, task_id),
            )
        else:
            raise ValueError(f"unbekannter Kanban-Persistenzmodus: {mode}")
        conn.commit()
        if mode in ("result", "error"):
            deps.sync_to_memory_bridge(task_id, title, assignee, persisted_status, reply)
    finally:
        conn.close()
    return {"mode": mode, "status": persisted_status, "task_id": task_id}


async def _execute_kanban_task_async(task_id: str) -> Any:
    """CAS-gesicherter Einstieg: nur ein Worker darf einen Task ausfuehren."""
    lease_token = ""
    heartbeat_task: Optional[asyncio.Task[None]] = None
    try:
        from backend.deadlock_supervisor import deadlock_supervisor

        claim = await asyncio.to_thread(deadlock_supervisor.acquire_lease, task_id)
        if not claim.get("acquired"):
            # D07-H2: auch `task_exists=False` ist fail-closed. Ein Fallthrough
            # mit leerem Lease-Token wuerde einen Dispatch ohne Fencing erlauben.
            reason = "lease_held" if claim.get("task_exists") else "lease_unavailable"
            logger.warning(
                "[KanbanWorker] Lease fuer '%s' nicht erworben (%s) — Skip (fail-closed).",
                task_id, reason,
            )
            return {"skipped": reason, "task_id": task_id}
        lease_token = str(claim.get("lease_token") or "")
        if not lease_token:
            # Nie ohne Gueltigkeitsnachweis dispatchen (CAS/Heartbeat waeren tot).
            logger.error(
                "[KanbanWorker] Lease-Claim fuer '%s' ohne Token — Skip (fail-closed).", task_id
            )
            return {"skipped": "lease_unavailable", "task_id": task_id}
        from backend.cancellation import get_token as _get_cancel_token

        cancel_token = _get_cancel_token(f"task:{task_id}")

        async def _hb() -> None:
            while True:
                await asyncio.sleep(30)
                try:
                    ok = await asyncio.to_thread(
                        deadlock_supervisor.heartbeat, task_id, lease_token
                    )
                    if not ok:
                        logger.warning(
                            "[KanbanWorker] Lease '%s' verloren — Ausfuehrung wird abgebrochen.",
                            task_id,
                        )
                        if cancel_token is not None:
                            cancel_token.cancel("lease_lost")
                        return
                except Exception as exc:
                    logger.warning(
                        "[KanbanWorker] Heartbeat fehlgeschlagen — Task %s wird abgebrochen: %s",
                        task_id,
                        exc,
                    )
                    if cancel_token is not None:
                        cancel_token.cancel("lease_heartbeat_failed")
                    return

        heartbeat_task = asyncio.create_task(_hb(), name=f"kanban_lease_{task_id}")
    except Exception as exc:
        # D07-H2: ARCHON_LEASE_FAIL_OPEN entfernt. Jeder Claim-Fehler ist
        # fail-closed: kein Dispatch ohne CAS-gesicherte Lease.
        logger.error(
            "[KanbanWorker] Lease-Claim fehlgeschlagen (%s) — Task %s wird nicht ausgefuehrt (fail-closed).",
            exc, task_id,
        )
        try:
            from backend.audit_log import _require_audit_event

            _require_audit_event(
                "recovery", "lease_unavailable", "system",
                {"task_id": task_id, "error": str(exc)[:300]},
            )
        except Exception as audit_exc:
            logger.error("[KanbanWorker] Audit lease_unavailable fehlgeschlagen: %s", audit_exc)
        return {"skipped": "lease_unavailable", "task_id": task_id}

    if not lease_token:
        # Letzte Barriere: nie mit leerem Token in den Dispatch laufen.
        return {"skipped": "lease_unavailable", "task_id": task_id}

    try:
        return await _execute_kanban_task_inner(task_id, lease_token=lease_token)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        if lease_token:
            try:
                await asyncio.to_thread(
                    deadlock_supervisor.release_lease, task_id, lease_token
                )
            except Exception as exc:
                logger.debug("[KanbanWorker] Lease-Release-Hinweis: %s", exc)


async def _execute_kanban_task_inner(task_id: str, *, lease_token: str = "") -> Any:
    """Fuehrt eine Kanban-Aufgabe autonom ueber core_dispatcher aus (alter dag_scheduler entfernt)."""
    import core_dispatcher

    deps = _resolve_deps()
    _cancel_token: Any = None

    def _check_cancel() -> None:
        if _cancel_token is not None:
            _cancel_token.check()

    try:
        from backend.cancellation import get_token as _get_cancel_token

        _cancel_token = _get_cancel_token(f"task:{task_id}")
        _current = asyncio.current_task()
        if _current is not None:
            _cancel_token.register_task(_current)
        _cancel_token.check()
    except asyncio.CancelledError as cancel_exc:
        logger.warning("[KanbanWorker] Cancel-Token vor Ausfuehrung: %s", cancel_exc)
        try:
            await asyncio.to_thread(
                _persist_kanban_result_sync,
                task_id,
                mode="cancelled",
                reply=f"Aufgabe abgebrochen: {cancel_exc}"[:500],
            )
        except Exception as exc:
            print(f"[OperationsAPI] Cancel-Status nicht persistiert: {exc}", file=sys.stderr)
        raise
    except ImportError as cancel_import_exc:
        logger.error(
            "[KanbanWorker] Cancel-Token-Modul nicht verfuegbar — Dispatch verweigert (fail-closed): %s",
            cancel_import_exc,
        )
        try:
            await asyncio.to_thread(
                _persist_kanban_result_sync,
                task_id,
                mode="result",
                target_status="blocked",
                verdict={
                    "block_kind": "cancellation_unavailable",
                    "hitl_options": ["retry", "abort"],
                    "reason": f"cancellation_unavailable: {cancel_import_exc}",
                },
                reply=f"Dispatch verweigert: Cancel-Token nicht verfuegbar ({cancel_import_exc})"[:500],
            )
        except Exception as persist_exc:
            logger.error("[KanbanWorker] Blocked-Status nicht persistiert: %s", persist_exc)
        raise RuntimeError("cancellation unavailable") from cancel_import_exc

    t_dict = await asyncio.to_thread(_kanban_load_task_sync, task_id)
    if not t_dict:
        return None

    if t_dict.get("_delegation_signature_invalid"):
        # D11-H1: manipuliertes created-Event → kein LLM-Call, harter Block.
        reason = "delegation_signature_invalid"
        logger.error("[KanbanWorker] %s fuer Task %s — Dispatch verweigert.", reason, task_id)
        await asyncio.to_thread(
            _persist_kanban_result_sync,
            task_id,
            mode="result",
            target_status="blocked",
            verdict={
                "block_kind": reason,
                "hitl_options": ["retry", "abort"],
                "reason": "Signatur der Delegationsuebergabe ungueltig",
            },
            reply=f"Dispatch verweigert: {reason}"[:500],
        )
        return {"blocked": reason, "task_id": task_id}

    if t_dict["id"].startswith("dag-") and not any(
        t_dict["id"].endswith(f"-{s}") for s in ["1", "2", "3", "4", "syn"]
    ):
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Task {task_id} ist ein dag-*-Epic des entfernten "
            "dag_scheduler — Ausfuehrung nicht moeglich. Nachfolger: Workflow-Engine (/api/v2/workflows/templates/{id}/run).",
            file=sys.stderr,
        )
        return None

    try:
        from backend.model_routing import autonomy_level

        _autonomy = autonomy_level("operations")
    except Exception:
        _autonomy = "approval"

    if _autonomy != "autonomous":
        if await asyncio.to_thread(_kanban_autonomy_gate_sync, task_id, _autonomy) != "continue":
            return None

    try:
        await asyncio.to_thread(_kanban_mark_started_sync, task_id, t_dict.get("assignee") or "")
    except Exception as exc:
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )

    from backend.agent_aliases import UNKNOWN_AGENT_ID, resolve_agent_id

    profiles = await asyncio.to_thread(deps.load_profiles_map)
    # W2-B: leere/unbekannte Ziel-IDs muessen hart blockiert werden. known_ids
    # kommt aus der Profil-SSOT; nur wenn sie (degradiert) leer ist, bleibt der
    # Legacy-Alias-Pfad fuer unsignierte Kanban-Tasks erhalten.
    _known_ids = {
        str(p.get("id") or "") for p in profiles.values() if isinstance(p, dict)
    } or None
    raw_assignee = (t_dict.get("assignee") or "").strip()
    if not raw_assignee:
        raw_assignee = "default"
        try:
            await asyncio.to_thread(_kanban_assign_orchestrator_sync, task_id)
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )
    assignee = resolve_agent_id(raw_assignee, known_ids=_known_ids)
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title

    async def _block_unknown_agent(reason: str) -> None:
        logger.error("[KanbanWorker] %s — Task %s wird nicht dispatched.", reason, task_id)
        await asyncio.to_thread(
            _persist_kanban_result_sync,
            task_id,
            mode="result",
            target_status="blocked",
            verdict={
                "block_kind": "UNKNOWN_AGENT_ID",
                "hitl_options": ["retry", "abort"],
                "reason": reason,
            },
            reply=f"Dispatch verweigert: {reason}"[:500],
        )

    if assignee == UNKNOWN_AGENT_ID or (
        t_dict.get("_delegation_signed") and _known_ids is None
    ):
        await _block_unknown_agent(
            f"UNKNOWN_AGENT_ID: {raw_assignee or '(leer)'} nicht in der Profil-SSOT"
        )
        return {"blocked": "UNKNOWN_AGENT_ID", "task_id": task_id}

    async def _handoff_gate_ok() -> bool:
        """F030/W3-A: harter Konsument-Gate vor jedem kostenpflichtigen Dispatch.

        D11-H3: signierte Delegations-Kinder brauchen zwingend den vor dem
        Dispatch angelegten Envelope (``require_envelope=True``).
        """
        _require_envelope = bool(t_dict.get("_delegation_signed"))
        try:
            gate = await asyncio.to_thread(
                require_accepted_handoff, task_id, assignee,
                require_envelope=_require_envelope,
            )
        except Exception as gate_exc:
            logger.error(
                "[KanbanWorker] Handoff-Gate nicht auswertbar — Dispatch verweigert: %s",
                gate_exc,
            )
            gate = {"allowed": False, "reason": f"handoff_gate_unavailable: {gate_exc}"}
        if bool(gate.get("allowed", False)):
            return True
        reason = str(gate.get("reason") or "handoff_not_accepted")
        logger.error("[KanbanWorker] Handoff-Gate blockiert Task %s: %s", task_id, reason)
        await asyncio.to_thread(
            _persist_kanban_result_sync,
            task_id,
            mode="result",
            title=title,
            assignee=assignee,
            target_status="blocked",
            verdict={
                "block_kind": "handoff_not_accepted",
                "hitl_options": ["retry", "abort"],
                "reason": reason,
            },
            reply=f"Dispatch verweigert: {reason}"[:500],
        )
        return False

    prof = profiles.get(assignee, {})
    model = (t_dict.get("model_override") or "").strip()
    provider_override = (t_dict.get("provider_override") or "").strip()
    if not model:
        try:
            from backend.model_routing import classify_task, is_enabled, resolve

            if is_enabled():
                _task_type = (t_dict.get("task_type") or "").strip() or classify_task(f"{title} {body}")
                _route = resolve(_task_type)
                if _route:
                    model = _route["model"]
                    provider_override = provider_override or _route["provider"]
                    print(f"[ModelRouting] Task {task_id}: '{_task_type}' -> {model} ({provider_override})")
        except Exception as _mr_err:
            print(f"[ModelRouting] Fallback auf Profilmodell: {_mr_err}")
    model = model or prof.get("model") or "deepseek/deepseek-chat"

    agent_name = prof.get("name") or assignee
    role = prof.get("category") or prof.get("role") or "Fach-Spezialist"
    system_prompt = (
        prof.get("prompt")
        or prof.get("system_prompt")
        or f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."
    )

    _delegation_model = t_dict.get("_delegation_payload_model")
    _dispatch_reasoning = "medium"
    if _delegation_model is not None:
        structured = {
            k: v for k, v in _delegation_model.model_dump().items()
            if k in _DELEGATION_CHILD_FIELDS
        }
        structured.setdefault("task_id", task_id)
        try:
            from backend.trace_context import current_trace_id

            _active_trace = str(current_trace_id() or "")
        except Exception:
            _active_trace = ""
        structured["trace_id"] = str(
            structured.get("trace_id") or _active_trace or f"task:{task_id}"
        )
        structured.setdefault(
            "correlation_id", str(structured.get("correlation_id") or f"trace:{structured['trace_id']}")
        )
        _dispatch_reasoning = str(_delegation_model.reasoning_level or "medium")
        system_prompt = (
            f"{system_prompt}\n\n[STRUKTURIERTE_DELEGATION_JSON]\n"
            + json.dumps(structured, sort_keys=True, ensure_ascii=False)
            + "\n[/STRUKTURIERTE_DELEGATION_JSON]"
        )
        # W3-C/M2: der signierte soul_mode wird produktiv konsumiert, statt
        # nur als tote System-Nachricht in state.db zu landen.
        try:
            from archon.core.delegation import active_soul_tier_text

            _soul_mode = str(structured.get("soul_mode") or "compact")
            _soul_text = active_soul_tier_text(assignee, _soul_mode)
            if _soul_text:
                system_prompt += (
                    f"\n\n[AKTIVER_SOUL_TIER: {_soul_mode.upper()}]\n{_soul_text}\n"
                    "[/AKTIVER_SOUL_TIER]"
                )
            elif _soul_mode in ("pro", "full"):
                logger.error(
                    "[KanbanWorker] SOUL-Tier '%s' fuer %s nicht gefunden — kompakter Fallback sichtbar.",
                    _soul_mode, assignee,
                )
        except Exception as _soul_exc:
            logger.error("[KanbanWorker] SOUL-Tier nicht konsumierbar: %s", _soul_exc)

    try:
        try:
            from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

            graceful_shutdown_coordinator.register_task(
                task_id=task_id,
                title=t_dict.get("title", task_id),
                agent_name=t_dict.get("assignee", "system"),
                total_steps=1,
                current_step=0,
                state_payload={"task_id": task_id, "status": t_dict.get("status")},
            )
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        proj_context = ""
        p_rel = deps.resolve_task_obsidian_rel(task_id)
        if p_rel:
            try:
                from backend.operations_projects import safe_path_within
                from backend.post_task_pipeline import get_vault_dir

                vault = Path(get_vault_dir()).resolve()
                p_dir = safe_path_within(vault, p_rel)
                if p_dir is None:
                    logger.warning("[OperationsAPI] Unsicherer Obsidian-Pfad abgewiesen: %s", p_rel)
                else:
                    proj_context = f"\n\nPROJEKT-ORDNER IM OBSIDIAN VAULT: `{p_rel}`\n"
                    end_dir = p_dir / "03_Endprodukte"
                    if end_dir.is_dir():
                        files = [f.name for f in end_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
                        if files:
                            proj_context += (
                                "Bereits vorhandene Projektergebnisse in 03_Endprodukte:\n"
                                + "\n".join(f"- {fn}" for fn in files[:12])
                                + "\n"
                            )
            except Exception as exc:
                print(
                    f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                    file=sys.stderr,
                )

        precedent_block = ""
        try:
            from backend.precedent_log import (
                find_matching_precedents,
                format_precedents_for_prompt,
                resolve_task_tenant_id,
            )

            _tenant_id = resolve_task_tenant_id(t_dict)
            _project_id = str(t_dict.get("project_id") or "")
            _matched_precs = await asyncio.to_thread(
                find_matching_precedents, _tenant_id, _project_id, f"{title} {body}"
            )
            precedent_block = format_precedents_for_prompt(_matched_precs)
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        task_prompt = f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\nTITEL: {title}\nAUFTRAG / DETAILS:\n{body}{proj_context}{precedent_block}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte."
        _check_cancel()
        if lease_token:
            from backend.deadlock_supervisor import deadlock_supervisor as _fence

            if not await asyncio.to_thread(_fence.heartbeat, task_id, lease_token):
                if _cancel_token is not None:
                    _cancel_token.cancel("lease_lost")
                raise asyncio.CancelledError("lease_lost")
        if not await _handoff_gate_ok():
            return {"blocked": "handoff_not_accepted", "task_id": task_id}
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=assignee,
            agent_name=agent_name,
            prompt=task_prompt,
            role=role,
            system_prompt=system_prompt,
            model=model,
            provider=provider_override,
            reasoning_level=_dispatch_reasoning,
            task_id=task_id,
        )
        raw_reply = (res.get("content") or "").strip()
        _token_used = int(
            res.get("total_tokens")
            or res.get("tokens_used")
            or ((res.get("input_tokens") or 0) + (res.get("output_tokens") or 0))
            or 0
        )
        _sidecar_tmeta: Dict[str, Any] = {}
        try:
            _sidecar_tmeta = (deps.load_kanban_meta().get("tasks") or {}).get(task_id) or {}
        except Exception:
            _sidecar_tmeta = {}
        _token_budget = int(t_dict.get("token_budget") or _sidecar_tmeta.get("token_budget") or 0)
        _proof_cmd = str(t_dict.get("proof_command") or _sidecar_tmeta.get("proof_command") or "").strip()
        _retry_cnt = int(t_dict.get("consecutive_failures") or t_dict.get("retry_count") or 0)

        from backend.kanban_verifier import verify_card_completion

        verdict = verify_card_completion(
            task_id=task_id,
            result_text=raw_reply,
            proof_command=_proof_cmd or None,
            token_used=_token_used,
            token_budget=_token_budget,
            retry_count=_retry_cnt,
        )
        if verdict["status"] == "retry":
            _check_cancel()
            if lease_token:
                from backend.deadlock_supervisor import deadlock_supervisor as _fence2

                if not await asyncio.to_thread(_fence2.heartbeat, task_id, lease_token):
                    if _cancel_token is not None:
                        _cancel_token.cancel("lease_lost")
                    raise asyncio.CancelledError("lease_lost")
            if not await _handoff_gate_ok():
                return {"blocked": "handoff_not_accepted", "task_id": task_id}
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=assignee,
                agent_name=agent_name,
                prompt=f"{task_prompt}\n\n[VERIFIER RETRY]: {verdict['reason']}",
                role=role,
                system_prompt=system_prompt,
                model=model,
                provider=provider_override,
                reasoning_level=_dispatch_reasoning,
                task_id=task_id,
                trajectory_reason="retry:verifier",
            )
            raw_reply = (res.get("content") or "").strip()
            _token_used += int(
                res.get("total_tokens")
                or res.get("tokens_used")
                or ((res.get("input_tokens") or 0) + (res.get("output_tokens") or 0))
                or 0
            )
            verdict = verify_card_completion(
                task_id=task_id,
                result_text=raw_reply,
                proof_command=_proof_cmd or None,
                token_used=_token_used,
                token_budget=_token_budget,
                retry_count=_retry_cnt + 1,
            )

        _delegation_dump = _delegation_model.model_dump() if _delegation_model is not None else {}
        _proof_facts: Dict[str, Any] = {}
        for _k in ("trace_id", "session_id", "correlation_id"):
            _v = res.get(_k) or _delegation_dump.get(_k)
            if _v:
                _proof_facts[_k] = str(_v)
        _prompt_info = res.get("effective_prompt_info")
        if _prompt_info:
            _proof_facts["effective_prompt_info"] = _prompt_info
        if _proof_facts:
            await asyncio.to_thread(_merge_task_meta_facts, task_id, _proof_facts)

        _cross = await _cross_model_verify_task_result(
            task_id=task_id,
            result_text=raw_reply,
            primary_model=str(model or ""),
            system_prompt=str(system_prompt or ""),
        )
        if not _cross.get("passed"):
            verdict = dict(verdict)
            verdict["status"] = "blocked"
            verdict["block_kind"] = _cross.get("block_kind") or "cross_model_verification_failed_hitl"
            verdict["reason"] = _cross.get("reason") or "Cross-Modell-Verifier abgelehnt."
            verdict["hitl_options"] = ["override_budget", "retry", "abort"]
        _cross_fact = {
            "passed": bool(_cross.get("passed")),
            "verifier_model": _cross.get("verifier_model"),
            "model_call": bool(_cross.get("model_call")),
            "reason": _cross.get("reason"),
        }
        _proof_facts["cross_model_verification"] = _cross_fact
        await asyncio.to_thread(
            _merge_task_meta_facts, task_id, {"cross_model_verification": _cross_fact}
        )

        is_success = verdict["status"] == "done" and res.get("status") == "success"
        target_status = "done" if is_success else ("blocked" if verdict["status"] == "blocked" else "failed")
        reply = raw_reply or f"Aufgabe '{title}' abgeschlossen ({target_status})."
        if not is_success and verdict.get("reason"):
            reply = f"{reply}\n\n[VERIFIER / HITL]: {verdict['reason']}"
        await asyncio.to_thread(
            _persist_kanban_result_sync,
            task_id,
            mode="result",
            title=title,
            assignee=assignee,
            target_status=target_status,
            reply=reply,
            verdict=verdict,
            proof_facts=_proof_facts,
            is_success=is_success,
        )

        try:
            from backend.operations_projects import safe_path_within
            from backend.post_task_pipeline import get_vault_dir

            vault = Path(get_vault_dir()).resolve()
            p_rel = deps.resolve_task_obsidian_rel(task_id)
            obs_status_label = "ABGESCHLOSSEN" if target_status == "done" else target_status.upper()
            p_dir = safe_path_within(vault, p_rel) if p_rel else None
            if p_dir is not None:
                end_dir = p_dir / "03_Endprodukte"
                if end_dir.is_dir():
                    matched = False
                    for f in end_dir.iterdir():
                        if task_id in f.name and f.suffix == ".md":
                            f.write_text(
                                f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** {obs_status_label}\n\n{reply}\n",
                                encoding="utf-8",
                            )
                            matched = True
                            break
                    if not matched:
                        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:40].strip("-")
                        (end_dir / f"{task_id}-{slug}.md").write_text(
                            f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** {obs_status_label}\n\n{reply}\n",
                            encoding="utf-8",
                        )
        except Exception as e_upd:
            print(f"[OperationsAPI] Could not update obsidian markdown: {e_upd}", file=sys.stderr)

        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event(
                    "kanban_updated",
                    {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": target_status},
                )
                main.broadcast_event(
                    "ticker_update",
                    {
                        "agent": agent_name,
                        "message": f"Aufgabe '{title[:30]}...' ({target_status}).",
                        "time": datetime.datetime.now().strftime("%H:%M:%S"),
                    },
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(
                _persist_kanban_result_sync,
                task_id,
                mode="cancelled",
                reply="Aufgabe abgebrochen (Cancel oder Lease-Verlust)",
            )
        except Exception as exc:
            print(f"[OperationsAPI] Cancel-Status nicht persistiert: {exc}", file=sys.stderr)
        raise
    except Exception as ex:
        print(f"[OperationsAPI] Execution failed for {task_id}: {ex}", file=sys.stderr)
        await asyncio.to_thread(
            _persist_kanban_result_sync,
            task_id,
            mode="error",
            title=title,
            assignee=assignee,
            reply=f"Fehler bei Ausführung: {ex}",
        )
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event(
                    "kanban_updated",
                    {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": "blocked"},
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )
    finally:
        try:
            from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

            graceful_shutdown_coordinator.unregister_task(task_id)
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )
    return None


async def _cross_model_verify_task_result(
    *,
    task_id: str,
    result_text: str,
    primary_model: str,
    diff_text: str = "",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """D14/MED: echter Cross-Modell-Call im regulaeren Abschluss-Gate."""
    from backend.kanban_verifier import cross_model_verify_card

    min_chars = 200
    try:
        min_chars = int(os.environ.get("ARCHON_CROSS_MODEL_VERIFY_MIN_CHARS", "200"))
    except (TypeError, ValueError):
        pass
    forced = str(os.environ.get("ARCHON_CROSS_MODEL_VERIFY", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not forced and len(str(result_text or "").strip()) < min_chars and not str(diff_text or "").strip():
        return {
            "passed": True,
            "requires_hitl": False,
            "block_kind": None,
            "reason": "Kein substantielles Ergebnis — kein Cross-Modell-Call noetig.",
            "verifier_model": None,
            "model_call": False,
            "skipped": True,
        }

    precheck = cross_model_verify_card(task_id, primary_model, diff_text)
    if not precheck.get("passed"):
        return {
            "passed": False,
            "requires_hitl": True,
            "block_kind": precheck.get("block_kind") or "cross_model_precheck_hitl",
            "reason": precheck.get("reason") or "Cross-Model-Precheck fehlgeschlagen.",
            "verifier_model": precheck.get("verifier_model"),
            "model_call": False,
        }

    verifier_model = str(precheck.get("verifier_model") or "").strip()
    if not verifier_model or verifier_model == str(primary_model or "").strip():
        return {
            "passed": False,
            "requires_hitl": True,
            "block_kind": "cross_model_unavailable_hitl",
            "reason": "Kein unabhaengiges Verifier-Modell bestimmbar (fail-closed).",
            "verifier_model": verifier_model,
            "model_call": False,
        }

    prompt = (
        "Du bist der UNABHAENGIGE Cross-Modell-Verifier einer anderen Modellfamilie. "
        "Pruefe das folgende Arbeitsergebnis auf unbelegte Behauptungen, logische "
        "Brueche und fehlende Nachweise. Antworte AUSSCHLIESSLICH als JSON: "
        '{"passed": true|false, "reason": "..."}. Bei Zweifeln passed=false.\n\n'
        f"ERGEBNIS ZUR PRUEFUNG:\n{(result_text or '')[:12000]}"
    )
    try:
        import core_dispatcher

        verifier_system = (
            str(system_prompt or "").strip()
            + "\n\n[ROLLENWECHSEL] Du bist jetzt der UNABHAENGIGE Cross-Modell-Verifier "
            'einer anderen Modellfamilie. Antworte ausschliesslich mit reinem JSON '
            '{"passed": bool, "reason": str}.'
        )
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="qa_test_engineer",
            agent_name="Cross-Model Verifier",
            prompt=prompt,
            role="Independent QA verifier (different model family)",
            system_prompt=verifier_system,
            model=verifier_model,
            task_id=task_id,
            trajectory_reason="tool:cross_model_verify",
        )
        content = str(res.get("content") or "").strip()
        parsed: Dict[str, Any] = {}
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
        else:
            first = (content.splitlines() or [""])[0].strip().upper()
            parsed = {"passed": first in ("PASS", "PASSED", "APPROVED", "FREIGABE"), "reason": content[:500]}
        passed = bool(parsed.get("passed")) and str(parsed.get("reason") or "").strip() != ""
        return {
            "passed": passed,
            "requires_hitl": not passed,
            "block_kind": None if passed else "cross_model_verification_failed_hitl",
            "reason": str(parsed.get("reason") or "Keine Begruendung geliefert.")[:1000],
            "verifier_model": verifier_model,
            "model_call": True,
        }
    except Exception as exc:
        logger.error("[CrossModel] Verifier-Dispatch fehlgeschlagen (fail-closed): %s", exc)
        return {
            "passed": False,
            "requires_hitl": True,
            "block_kind": "cross_model_verification_failed_hitl",
            "reason": f"Cross-Modell-Verifikation nicht abschliessbar: {exc}"[:1000],
            "verifier_model": verifier_model,
            "model_call": True,
        }

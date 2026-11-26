"""Kanban CRUD, Status-Wechsel und Zombie-Reset fuer Operations API (D3/8).

Kapselt die Kern-Endpunktlogik fuer ``/kanban/tasks`` (GET/POST),
``/kanban/tasks/{task_id}/status`` (PATCH), ``/kanban/reset-zombies`` (POST)
sowie ``_block_task_budget_allocation_failed_sync`` und ``_update_task_status_db``
per S3-Call-Time-Injektion (``register_kanban_crud_deps_provider``).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import secrets
import sys
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

from fastapi import HTTPException
from pydantic import BaseModel

from archon.core.provider_registry import get_provider
from backend.operations_constants import TEAMS_DEFINITION

logger = logging.getLogger("archon_os.operations_api")


class KanbanCrudDeps(NamedTuple):
    get_kanban_connection: Callable[..., Any]
    load_profiles_map: Callable[[], Dict[str, Any]]
    load_kanban_meta: Callable[[], Dict[str, Any]]
    build_kanban_obsidian_map: Callable[..., Dict[str, Optional[str]]]
    enrich_task: Callable[..., Dict[str, Any]]
    sync_to_memory_bridge: Callable[..., None]
    current_quality_review: Callable[[str], Dict[str, Any]]
    task_created_by: Callable[[str], str]
    task_status: Callable[[str], str]
    require_four_eyes_override: Callable[..., Dict[str, Any]]
    execute_kanban_task_async: Callable[[str], Any]
    update_task_status_db: Callable[..., Dict[str, Any]]
    block_task_budget_allocation_failed_sync: Callable[..., Dict[str, Any]]
    valid_kanban_statuses: Set[str]


_DEPS_PROVIDER: Optional[Callable[[], KanbanCrudDeps]] = None


def register_kanban_crud_deps_provider(
    provider: Callable[[], KanbanCrudDeps],
) -> None:
    """Registriert den Call-Time-Dependency-Provider aus operations_api.py (S3)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _deps() -> KanbanCrudDeps:
    if _DEPS_PROVIDER is None:
        raise RuntimeError(
            "KanbanCrudDeps provider not registered "
            "(call register_kanban_crud_deps_provider first)"
        )
    return _DEPS_PROVIDER()


class TaskCreateRequest(BaseModel):
    title: str
    body: Optional[str] = ""
    assignee: Optional[str] = None
    column: Optional[str] = "todo"
    priority: Optional[int] = 0
    model_override: Optional[str] = None
    provider_override: Optional[str] = None
    decompose: Optional[bool] = False
    allow_autonomous_hiring: Optional[bool] = False
    team_id: Optional[str] = None
    reasoning_effort: Optional[str] = None
    soul_mode: Optional[str] = None
    tool_preset: Optional[str] = None
    token_budget: Optional[int] = None
    cost_limit_usd: Optional[float] = None
    cost_limit_eur: Optional[float] = None
    require_hitl: Optional[bool] = False
    due_date: Optional[str] = None
    cron_schedule: Optional[str] = None
    depends_on: Optional[str] = None
    trusted_input: Optional[bool] = False


class TaskStatusUpdateRequest(BaseModel):
    status: str
    result: Optional[str] = None
    # 12.10.2026 (Decision-Service): "decision" = Aufruf kam vom zentralen
    # Entscheidungs-Endpoint -> dann KEIN zusaetzlicher Telegram-Ping (der
    # Service bestaetigt selbst), sonst Doppelnachricht.
    source: Optional[str] = None
    force: Optional[bool] = False
    # H-14-2 (F022): `force` auf `done` ist ein Hoheitsakt und braucht
    # Begruendung + Passkey-Proof + eine identitaetsverschiedene zweite Person.
    # Der Actor kommt ausschliesslich aus der Session (require_session_actor),
    # NIE aus diesen Feldern.
    reason: Optional[str] = None
    passkey_proof_token: Optional[str] = None
    approval_id: Optional[str] = None


def list_kanban_tasks(archived: Any = False) -> Dict[str, Any]:
    """Board-Daten: aktive Tasks gruppiert nach Spalten; ?archived=true liefert die flache Archiv-Liste."""
    d = _deps()
    if hasattr(archived, "default"):
        archived = archived.default
    archived_flag = bool(archived)
    conn = d.get_kanban_connection()

    profiles = d.load_profiles_map()
    meta = d.load_kanban_meta()
    base_select = """
            SELECT rowid AS task_num, id, title, body, assignee, status, priority, created_by,
                   created_at, started_at, completed_at, result, model_override, provider_override, block_kind,
                   (SELECT count(*) FROM task_comments c WHERE c.task_id = tasks.id) AS comment_count,
                   (SELECT count(*) FROM task_links l WHERE l.parent_id = tasks.id AND COALESCE(l.kind, 'subtask') = 'subtask') AS subtask_count,
                   (SELECT count(*) FROM task_links l WHERE l.child_id = tasks.id AND COALESCE(l.kind, 'subtask') = 'subtask') AS parent_count
            FROM tasks
    """
    try:
        cursor = conn.cursor()
        if archived_flag:
            cursor.execute(base_select + " WHERE status = 'archived' ORDER BY completed_at DESC")
            arch_rows = cursor.fetchall()
            obs_map = d.build_kanban_obsidian_map(conn, arch_rows, meta)
            tasks = [d.enrich_task(dict(r), profiles, meta, obsidian_map=obs_map) for r in arch_rows]
            return {"status": "success", "archived": True, "tasks": tasks, "total": len(tasks)}

        cursor.execute(base_select + " ORDER BY priority DESC, created_at DESC")
        rows = cursor.fetchall()
        obs_map = d.build_kanban_obsidian_map(conn, rows, meta)

        columns: Dict[str, List[Any]] = {
            "triage": [],
            "todo": [],
            "ready": [],
            "in_progress": [],
            "review": [],
            "done": [],
            "blocked": [],
            "scheduled": [],
            "failed": [],
        }

        active_rows = 0
        for r in rows:
            task_dict = dict(r)
            st = (task_dict.get("status") or "todo").lower()
            if st == "archived":
                continue
            if (task_dict.get("block_kind") or "").lower() == "approval":
                st = "blocked"
            d.enrich_task(task_dict, profiles, meta, obsidian_map=obs_map)
            if st in columns:
                columns[st].append(task_dict)
            else:
                columns["todo"].append(task_dict)
            active_rows += 1

        return {
            "status": "success",
            "columns": columns,
            "total_tasks": active_rows,
            "counts": {k: len(v) for k, v in columns.items()},
            "wip": meta.get("wip", {}),
        }
    finally:
        conn.close()


def _block_task_budget_allocation_failed_sync(
    task_id: str,
    title: str,
    assignee: str,
    reason: str,
    subtask_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """D13/MED: Task ohne registriertes hartes Ticket-Cap nie ausfuehrbar."""
    d = _deps()
    now_iso = datetime.datetime.now().isoformat()
    detail = f"budget_allocation_failed: {reason}"[:500]
    conn = d.get_kanban_connection(maintenance=True)
    try:
        for tid in [task_id, *(subtask_ids or [])]:
            conn.execute(
                "UPDATE tasks SET status = 'blocked', block_kind = 'budget_allocation_failed', "
                "result = ? WHERE id = ?",
                (detail, tid),
            )
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) "
                "VALUES (?, 'budget_allocation_failed', ?, ?)",
                (tid, json.dumps({"reason": detail, "task_id": tid}), now_iso),
            )
        conn.commit()
    finally:
        conn.close()
    d.sync_to_memory_bridge(task_id, title, assignee, "blocked", detail)
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(
            category="recovery",
            action="budget_allocation_failed",
            agent_id="system",
            payload={"task_id": task_id, "reason": detail[:300]},
        )
    except Exception as audit_exc:
        logger.error("[OperationsAPI] Budget-Audit fehlgeschlagen: %s", audit_exc)
    return {"blocked": True, "task_id": task_id, "reason": detail}


def create_kanban_task_impl(req: TaskCreateRequest, creator_actor: str) -> Dict[str, Any]:
    """Erstellt eine neue Aufgabe im Hermes Kanban über CLI-Execution oder direkten Insert."""
    d = _deps()
    conn = d.get_kanban_connection(maintenance=True)
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        task_id = f"t-{secrets.token_hex(3)}"

        target_status = (
            req.column
            if req.column
            in ["triage", "todo", "ready", "in_progress", "review", "done", "blocked", "scheduled"]
            else "todo"
        )

        target_assignee = req.assignee
        team_name = ""
        if req.team_id:
            team_match = next((t for t in TEAMS_DEFINITION if t["id"] == req.team_id), None)
            if team_match:
                team_name = str(team_match["name"])
                if not target_assignee:
                    target_assignee = str(team_match["lead_id"])

        task_body = req.body or ""
        if team_name and f"[Team: {team_name}]" not in task_body:
            task_body = f"[Team: {team_name}]\n{task_body}".strip()

        cursor.execute(
            """
            INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, model_override, provider_override, block_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                task_id,
                req.title,
                task_body,
                target_assignee,
                target_status,
                req.priority or 0,
                creator_actor,
                now_iso,
                req.model_override,
                req.provider_override,
                "hitl_gate" if req.require_hitl else None,
            ),
        )

        if req.depends_on and str(req.depends_on).strip():
            dep_id = str(req.depends_on).strip()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO task_links (parent_id, child_id, kind, created_at) VALUES (?, ?, 'blocks', ?)",
                    (dep_id, task_id, now_iso),
                )
            except Exception as exc:
                print(
                    f"[OperationsAPI] WARNUNG (MEDIUM) create_kanban_task: Exception im Fehler-/Fallback-Pfad: {exc}",
                    file=sys.stderr,
                )

        cursor.execute(
            """
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """,
            (
                task_id,
                "created",
                json.dumps(
                    {
                        "title": req.title,
                        "assignee": target_assignee,
                        "team": req.team_id,
                        "status": target_status,
                        "soul_mode": req.soul_mode,
                        "reasoning_effort": req.reasoning_effort,
                        "tool_preset": req.tool_preset,
                    }
                ),
                now_iso,
            ),
        )

        conn.commit()
        d.sync_to_memory_bridge(task_id, req.title, target_assignee, target_status)

        eff_cost_eur = (
            req.cost_limit_eur
            if req.cost_limit_eur is not None
            else (
                round(float(req.cost_limit_usd) * 0.92, 2)
                if req.cost_limit_usd is not None
                else None
            )
        )
        if any(
            [
                req.soul_mode,
                req.reasoning_effort,
                req.tool_preset,
                req.token_budget,
                req.cost_limit_usd,
                eff_cost_eur,
                req.require_hitl,
                req.due_date,
                req.cron_schedule,
                req.depends_on,
                req.trusted_input,
                req.allow_autonomous_hiring,
            ]
        ):
            try:
                from backend.kanban_sidecar import update_kanban_meta

                def _save_create_meta(meta: Dict[str, Any]) -> None:
                    tmeta = meta.setdefault("tasks", {}).setdefault(task_id, {})
                    if req.soul_mode:
                        tmeta["soul_mode"] = req.soul_mode
                    if req.reasoning_effort:
                        tmeta["reasoning_effort"] = req.reasoning_effort
                    if req.tool_preset:
                        tmeta["tool_preset"] = req.tool_preset
                    if req.token_budget:
                        tmeta["token_budget"] = int(req.token_budget)
                    if req.cost_limit_usd is not None:
                        tmeta["cost_limit_usd"] = float(req.cost_limit_usd)
                    if eff_cost_eur is not None:
                        tmeta["cost_limit_eur"] = float(eff_cost_eur)
                    if req.require_hitl:
                        tmeta["require_hitl"] = True
                    if req.due_date:
                        tmeta["due"] = str(req.due_date)[:10]
                    if req.cron_schedule:
                        tmeta["cron_schedule"] = str(req.cron_schedule).strip()
                    if req.depends_on:
                        tmeta["depends_on"] = str(req.depends_on).strip()
                    if req.trusted_input:
                        tmeta["trusted_input"] = True
                    if req.allow_autonomous_hiring:
                        tmeta["allow_autonomous_hiring"] = True

                update_kanban_meta(_save_create_meta)
            except Exception as meta_err:
                print(f"[OperationsAPI] Meta save warning: {meta_err}", file=sys.stderr)

        decomposition_plan: Optional[Dict[str, Any]] = None
        created_subtask_ids: List[str] = []
        if req.decompose or req.allow_autonomous_hiring:
            try:
                from backend.role_budget_engine import plan_and_decompose_task_with_budgets

                decomposition_plan = plan_and_decompose_task_with_budgets(
                    parent_task_id=task_id,
                    title=req.title,
                    body=task_body,
                    total_token_budget=req.token_budget,
                    total_cost_limit_eur=eff_cost_eur,
                    allow_autonomous_hiring=bool(req.allow_autonomous_hiring),
                )
                subtasks_list = (decomposition_plan or {}).get("subtasks", [])
                for idx, sub in enumerate(subtasks_list):
                    sub_id = f"{task_id}-sub{idx + 1}"
                    sub_title = f"[AP{idx + 1}: {sub.get('role', 'Spezialist')}] {req.title[:70]}"
                    sub_body = (
                        f"{sub.get('mandate', '')}\n\n"
                        f"---\n"
                        f"🪙 **Zugeteiltes Teil-Budget (Orchestrator-Split):** "
                        f"`{sub.get('token_budget', 0):,} Tokens` / `{sub.get('cost_limit_eur', 0.0):.2f} €` "
                        f"(Komplexitätsgewicht: `{sub.get('complexity_weight', 1.0)}x`, Anteil: `{sub.get('budget_share_pct', 0)}%`)"
                    )
                    sub_assignee = sub.get("agent_id") or target_assignee or "default"
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, model_override, provider_override, block_kind)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sub_id,
                            sub_title,
                            sub_body,
                            sub_assignee,
                            target_status,
                            req.priority or 0,
                            "CEO-Orchestrator",
                            now_iso,
                            req.model_override,
                            req.provider_override,
                            "hitl_gate" if req.require_hitl else None,
                        ),
                    )
                    cursor.execute(
                        "INSERT OR IGNORE INTO task_links (parent_id, child_id, kind, created_at) VALUES (?, ?, 'subtask', ?)",
                        (task_id, sub_id, now_iso),
                    )
                    created_subtask_ids.append(sub_id)
                conn.commit()
                if created_subtask_ids:
                    from backend.kanban_sidecar import update_kanban_meta

                    def _save_sub_budgets(meta: Dict[str, Any]) -> None:
                        for idx, sub in enumerate(subtasks_list):
                            sid = f"{task_id}-sub{idx + 1}"
                            smeta = meta.setdefault("tasks", {}).setdefault(sid, {})
                            smeta["token_budget"] = int(sub.get("token_budget") or 0)
                            smeta["cost_limit_eur"] = float(sub.get("cost_limit_eur") or 0.0)
                            smeta["cost_limit_usd"] = float(sub.get("cost_limit_usd") or 0.0)
                            smeta["complexity_weight"] = float(sub.get("complexity_weight") or 1.0)
                            smeta["budget_share_pct"] = float(sub.get("budget_share_pct") or 0.0)
                            if sub.get("is_autonomously_hired"):
                                smeta["autonomously_hired"] = True

                    update_kanban_meta(_save_sub_budgets)
            except Exception as dec_err:
                logger.error(
                    "[OperationsAPI] Budget-Decompose fehlgeschlagen — Task %s wird blockiert: %s",
                    task_id,
                    dec_err,
                )
                d.block_task_budget_allocation_failed_sync(
                    task_id, req.title, target_assignee, str(dec_err), created_subtask_ids
                )
                return {
                    "status": "blocked",
                    "task_id": task_id,
                    "block_kind": "budget_allocation_failed",
                    "reason": f"budget_decomposition_failed: {dec_err}",
                }
        elif req.token_budget or eff_cost_eur:
            try:
                from backend.role_budget_engine import allocate_task_budget_to_subagents

                allocate_task_budget_to_subagents(
                    parent_task_id=task_id,
                    total_token_budget=int(req.token_budget or 60000),
                    subtasks=[],
                    total_cost_limit_eur=eff_cost_eur,
                    orchestrator_reserve_pct=1.0,
                )
            except Exception as alloc_err:
                # D13/MED: ohne Allokationszeile greift nur das Rollen-Tagesbudget;
                # ein Task ohne hartes Cap darf NICHT ausfuehrbar bleiben.
                logger.error(
                    "[OperationsAPI] Budget-Allokation fehlgeschlagen — Task %s wird blockiert: %s",
                    task_id,
                    alloc_err,
                )
                d.block_task_budget_allocation_failed_sync(
                    task_id, req.title, target_assignee, str(alloc_err)
                )
                return {
                    "status": "blocked", "task_id": task_id,
                    "block_kind": "budget_allocation_failed",
                    "reason": f"budget_allocation_failed: {alloc_err}",
                }

        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event(
                    "kanban_updated",
                    {"action": "created", "task_id": task_id, "status": target_status},
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) create_kanban_task: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        resp_out: Dict[str, Any] = {
            "status": "success",
            "task_id": task_id,
            "title": req.title,
            "assigned_to": target_assignee,
            "team": req.team_id,
            "subtask_ids": created_subtask_ids,
        }
        if decomposition_plan:
            resp_out["budget_plan"] = decomposition_plan.get("budget_plan")
            resp_out["hired_specialist"] = decomposition_plan.get("hired_specialist")
        return resp_out
    finally:
        conn.close()


def _update_task_status_db(
    task_id: str,
    new_status: str,
    result: Optional[str],
    force: bool,
    actor: str = "",
    reason: str = "",
    override_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fix-Sprint Paket A (Punkt 2): der komplette synchrone SQLite-/Datei-Block
    von update_task_status — wird via asyncio.to_thread ausgefuehrt."""
    d = _deps()
    conn = d.get_kanban_connection(maintenance=True)
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        cursor.execute("SELECT id, title, assignee, status FROM tasks WHERE id = ?", (task_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")

        old_status = existing["status"]

        if new_status == "done" and not force:
            meta = d.load_kanban_meta()
            t_meta = (meta.get("tasks") or {}).get(task_id, {})
            q_rev = t_meta.get("quality_review")
            if q_rev and q_rev.get("status") == "changes_requested":
                critique_msg = (
                    ", ".join(q_rev.get("critique_points") or [])
                    or q_rev.get("summary")
                    or "Nachbesserung erforderlich"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"4-Augen-Review blockiert Abschluss: {q_rev.get('reviewer', 'Qualitätsprüfer')} fordert Nachbesserung! ({critique_msg})",
                )

        cursor.execute(
            """
            UPDATE tasks
            SET status = ?,
                started_at = CASE
                    WHEN ? = 'todo' THEN NULL
                    WHEN ? = 'in_progress' AND started_at IS NULL THEN ?
                    ELSE started_at
                END,
                completed_at = CASE
                    WHEN ? = 'done' THEN ?
                    ELSE NULL
                END,
                result = COALESCE(?, result)
            WHERE id = ?
        """,
            (new_status, new_status, new_status, now_iso, new_status, now_iso, result, task_id),
        )

        status_payload: Dict[str, Any] = {
            "from": old_status,
            "to": new_status,
            "actor": str(actor or ""),
            "force": bool(force),
            "reason": str(reason or "") or None,
        }
        if force and new_status == "done":
            status_payload["four_eyes_evidence"] = override_evidence or {}
            q_rev = d.current_quality_review(task_id)
            status_payload["previous_review"] = {
                "status": q_rev.get("status"),
                "reviewer_id": q_rev.get("reviewer_id"),
                "reviewer": q_rev.get("reviewer"),
            }
        cursor.execute(
            """
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """,
            (task_id, "status_changed", json.dumps(status_payload, ensure_ascii=False), now_iso),
        )

        conn.commit()
        return {
            "old_status": old_status,
            "title": existing["title"],
            "assignee": existing["assignee"],
            "now_iso": now_iso,
        }
    finally:
        conn.close()


async def update_task_status_impl(
    task_id: str, actor: str, req: TaskStatusUpdateRequest
) -> Dict[str, Any]:
    """Verschiebt eine Aufgabe in eine neue Spalte / Status und startet ggf. Ausführung."""
    d = _deps()
    new_status = (req.status or "").lower()
    if new_status not in d.valid_kanban_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Ungültiger Status '{req.status}'. Erlaubt sind: {', '.join(sorted(d.valid_kanban_statuses))}",
        )

    override_evidence: Optional[Dict[str, Any]] = None
    if bool(req.force) and new_status == "done":
        review = await asyncio.to_thread(d.current_quality_review, task_id)
        created_by = await asyncio.to_thread(d.task_created_by, task_id)
        old_status_before_force = await asyncio.to_thread(d.task_status, task_id)
        override_evidence = await asyncio.to_thread(
            d.require_four_eyes_override,
            task_id=task_id,
            actor=actor,
            review=review,
            reason=req.reason or "",
            proof_token=req.passkey_proof_token,
            action="quality_review_override",
            created_by=created_by,
            approval_id=req.approval_id,
        )
        try:
            from backend.audit_log import _require_audit_event

            await asyncio.to_thread(
                _require_audit_event,
                "governance",
                "status_forced",
                actor,
                {
                    "task_id": task_id,
                    "from": old_status_before_force,
                    "to": new_status,
                    "force": True,
                    "old_review": review,
                    "reason": req.reason or "",
                    "approval_id": override_evidence.get("approval_id"),
                },
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    info = await asyncio.to_thread(
        d.update_task_status_db,
        task_id,
        new_status,
        req.result,
        bool(req.force),
        actor,
        req.reason or "",
        override_evidence,
    )
    old_status = info["old_status"]

    try:
        await asyncio.to_thread(
            d.sync_to_memory_bridge, task_id, info["title"], info["assignee"], new_status, req.result
        )
    except Exception as exc:
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) update_task_status: Memory-Bridge fehlgeschlagen: {exc}",
            file=sys.stderr,
        )

    from archon.core.task_registry import spawn as _spawn_tracked

    if new_status == "in_progress" and old_status != "in_progress":
        _spawn_tracked(d.execute_kanban_task_async(task_id), name=f"kanban_task:{task_id}")
    elif new_status == "todo" and old_status in ("review", "failed", "blocked", "done"):
        _spawn_tracked(d.execute_kanban_task_async(task_id), name=f"kanban_task:{task_id}")

    if old_status == "review" and new_status != "review" and (req.source or "") != "decision":
        try:
            _dm = (
                (await asyncio.to_thread(d.load_kanban_meta))
                .get("tasks", {})
                .get(task_id, {})
                .get("decision")
            )
            if _dm:
                from telegram_notify import send_telegram_message

                _verb = (
                    "✅ freigegeben"
                    if new_status in ("todo", "in_progress", "done")
                    else "⛔ abgelehnt/verworfen"
                )
                await asyncio.to_thread(
                    send_telegram_message,
                    f"{_verb} — {_dm.get('titel') or task_id}\n"
                    f"(im Kanban verschoben: review → {new_status})",
                )
        except Exception as _tg_err:
            print(
                f"[OperationsAPI] Telegram-Benachrichtigung fehlgeschlagen: {_tg_err}",
                file=sys.stderr,
            )

    try:
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event(
                "kanban_updated",
                {"action": "status_changed", "task_id": task_id, "from": old_status, "to": new_status},
            )
    except Exception as exc:
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) update_task_status: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )

    return {"status": "success", "task_id": task_id, "old_status": old_status, "new_status": new_status}


def reset_zombie_kanban_tasks_impl(
    assignee: str, task_id: str, target_status: str
) -> Dict[str, Any]:
    """Setzt hängengebliebene 'in_progress' Tasks (optional gefiltert nach assignee oder Alter) auf 'todo' zurück."""
    d = _deps()
    conn = d.get_kanban_connection(maintenance=True)
    try:
        assignee_clean = (assignee or "").strip()
        task_id_clean = (task_id or "").strip()
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        if task_id_clean:
            cursor.execute(
                "SELECT id, title, assignee FROM tasks WHERE id = ? AND status = 'in_progress'",
                (task_id_clean,),
            )
        elif assignee_clean:
            cursor.execute(
                "SELECT id, title, assignee FROM tasks WHERE status = 'in_progress' AND LOWER(assignee) = LOWER(?)",
                (assignee_clean,),
            )
        else:
            cursor.execute("SELECT id, title, assignee FROM tasks WHERE status = 'in_progress'")

        rows = cursor.fetchall()
        reset_ids: List[str] = []
        for r in rows:
            tid = r["id"]
            cursor.execute(
                "UPDATE tasks SET status = ?, started_at = NULL WHERE id = ?",
                (target_status, tid),
            )
            cursor.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    tid,
                    "zombie_reset",
                    json.dumps({"from": "in_progress", "to": target_status, "by": "user_or_watchdog"}),
                    now_iso,
                ),
            )
            d.sync_to_memory_bridge(tid, r["title"], r["assignee"], target_status)
            reset_ids.append(tid)

        conn.commit()
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event") and reset_ids:
                main.broadcast_event(
                    "kanban_updated",
                    {"action": "zombie_reset", "task_ids": reset_ids, "to": target_status},
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] WARNUNG (MEDIUM) reset_zombie_kanban_tasks: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        return {
            "status": "ok",
            "reset_count": len(reset_ids),
            "task_ids": reset_ids,
            "target_status": target_status,
        }
    finally:
        conn.close()

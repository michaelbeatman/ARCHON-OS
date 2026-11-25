from fastapi import Depends as _ArchonDepends

from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_session_actor

"""
Kanban Persistenz Router fuer Archon OS.
Verwaltet /api/kanban Endpunkte (Karten lesen und synchronisieren in kanban.db und JSON).
Extrahiert aus main.py zur Modularisierung.
"""

import asyncio
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from archon.core.paths import KANBAN_CARDS_FILE, KANBAN_DB_PATH
from archon.core.runtime import atomic_write_json, logger, run_io_bound
from backend.db_paths import get_db_connection
from backend.platform_paths import HERMES_HOME

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["kanban"])


def _get_kanban_cards_file() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "KANBAN_CARDS_FILE"):
        cand = getattr(main_mod, "KANBAN_CARDS_FILE")
        if cand != KANBAN_CARDS_FILE:
            return cand
    try:
        from backend.tenant_context import PRIMARY_TENANT_IDS, tenant_context
        tid = tenant_context.get_active_tenant_id()
        if tid not in PRIMARY_TENANT_IDS:
            return os.path.join(tenant_context.get_tenant_dir(tid), "kanban_cards.json")
    except Exception as exc:
        logger.warning(f"Tenant-Kontext nicht ermittelbar, falle auf Standard-Kanban-Cards-Datei zurueck: {exc}")
    return KANBAN_CARDS_FILE


def _get_hermes_home() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "HERMES_HOME"):
        return getattr(main_mod, "HERMES_HOME")
    return HERMES_HOME


def _atomic_write_json(path, data):
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "atomic_write_json"):
        return main_mod.atomic_write_json(path, data)
    return atomic_write_json(path, data)


def _resolve_active_kanban_db() -> str:
    hermes_home = _get_hermes_home()
    if hermes_home != HERMES_HOME:
        cand_db = os.path.join(hermes_home, "kanban.db")
        return cand_db if os.path.exists(cand_db) else (KANBAN_DB_PATH if os.path.exists(KANBAN_DB_PATH) else cand_db)
    try:
        from backend.tenant_context import tenant_context
        return tenant_context.resolve_active_db("kanban.db")
    except Exception as exc:
        logger.warning(f"Tenant-Kontext nicht ermittelbar, falle auf Standard-Kanban-DB zurueck: {exc}")
    cand_db = os.path.join(hermes_home, "kanban.db")
    return cand_db if os.path.exists(cand_db) else (KANBAN_DB_PATH if os.path.exists(KANBAN_DB_PATH) else cand_db)


@router.get("/api/kanban")
def api_get_kanban():
    kanban_db = _resolve_active_kanban_db()
    if os.path.exists(kanban_db):
        kconn = None
        try:
            kconn = get_db_connection(kanban_db, timeout=5.0)
            kconn.row_factory = sqlite3.Row
            rows = kconn.execute(
                "SELECT id, title, body as description, assignee, status, priority, created_at FROM tasks WHERE status != 'archived' ORDER BY priority DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"[Kanban Router] Fehler beim Lesen aus {kanban_db}: {e}")
        finally:
            if kconn:
                kconn.close()
    cards_file = _get_kanban_cards_file()
    if os.path.exists(cards_file):
        try:
            with open(cards_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.debug(f"Kanban-Cards-Datei {cards_file} nicht lesbar, gebe leere Liste zurueck: {exc}")
    return []


def _persist_kanban_sync(cards: Any) -> None:
    cards_file = _get_kanban_cards_file()
    _atomic_write_json(cards_file, cards)
    kanban_db = _resolve_active_kanban_db()
    if os.path.exists(kanban_db) and isinstance(cards, list):
        kconn = None
        try:
            kconn = get_db_connection(kanban_db, timeout=5.0)
            for c in cards:
                if not isinstance(c, dict) or not c.get("id"):
                    continue
                kconn.execute("""
                    INSERT INTO tasks (id, title, body, assignee, status, priority, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        body=excluded.body,
                        assignee=excluded.assignee,
                        status=excluded.status,
                        priority=excluded.priority
                """, (
                    c.get("id"),
                    c.get("title", ""),
                    c.get("description") or c.get("body", ""),
                    c.get("assignee", "coder"),
                    c.get("status", "todo"),
                    c.get("priority", 1),
                    c.get("created_at")
                ))
            kconn.commit()
        except Exception as e:
            logger.warning(f"[Kanban Router] Fehler beim Schreiben in {kanban_db}: {e}")
        finally:
            if kconn:
                kconn.close()


@router.post("/api/kanban")
async def api_save_kanban(request: Request):
    try:
        cards = await request.json()
        await run_io_bound(_persist_kanban_sync, cards)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# --- M78: Kanban Gantt & Dependency Graph ---
def _load_tasks_and_links_sync():
    kanban_db = _resolve_active_kanban_db()
    if not os.path.exists(kanban_db):
        return [], []
    kconn = None
    try:
        kconn = get_db_connection(kanban_db, timeout=5.0)
        kconn.row_factory = sqlite3.Row
        tasks = [
            dict(r)
            for r in kconn.execute(
                "SELECT * FROM tasks WHERE status != 'archived' ORDER BY id DESC LIMIT 5000"
            ).fetchall()
        ]
        links = []
        try:
            links = [
                dict(r)
                for r in kconn.execute("SELECT * FROM task_links ORDER BY id DESC LIMIT 5000").fetchall()
            ]
        except Exception:
            links = []
        return tasks, links
    finally:
        if kconn:
            kconn.close()


@router.get("/api/operations/kanban/gantt")
async def api_kanban_gantt(default_hours: int = 4):
    from backend.kanban_views import build_gantt_items
    tasks, _ = await run_io_bound(_load_tasks_and_links_sync)
    return {"status": "success", "items": build_gantt_items(tasks, default_duration_hours=max(1, default_hours))}


@router.get("/api/operations/kanban/graph")
async def api_kanban_graph():
    from backend.kanban_views import build_dependency_graph
    tasks, links = await run_io_bound(_load_tasks_and_links_sync)
    return {"status": "success", **build_dependency_graph(tasks, links)}


def _load_hitl_creator(kanban_db: str, task_id: str) -> str:
    """D08/MED: SQLite-Lesezugriff des HITL-Endpoints aus dem Loop auslagern."""
    if not os.path.exists(kanban_db):
        return ""
    kconn = get_db_connection(kanban_db, timeout=5.0)
    try:
        row = kconn.execute(
            "SELECT created_by FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return str(row["created_by"] or "") if row else ""
    finally:
        kconn.close()


# --- M76: Kanban Card HITL Decision (override_budget | retry | abort) ---
@router.post("/api/operations/kanban/tasks/{task_id}/hitl")
async def api_kanban_task_hitl(request: Request, task_id: str):
    """HITL-Auflösung: override (mit Reverifikation) / retry (Re-Dispatch) / abort."""
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    actor = require_session_actor(request)  # Actor NIE aus dem Body
    payload = await request.json()
    action = str(payload.get("action") or "").strip()
    old_budget = int(payload.get("current_budget") or 0)

    # Ersteller aus der DB — nie aus dem Body.
    created_by = ""
    try:
        kanban_db = _resolve_active_kanban_db()
        created_by = await run_io_bound(_load_hitl_creator, kanban_db, task_id)
    except Exception as exc:
        logger.warning("[Kanban] HITL-Ersteller nicht lesbar: %s", exc)

    from backend.kanban_verifier import resolve_card_hitl_decision
    try:
        decision = resolve_card_hitl_decision(
            action,
            current_budget=old_budget,
            override_budget=payload.get("token_budget"),
            actor=actor,
            created_by=created_by,
            result_text=str(payload.get("result_text") or ""),
            proof_command=payload.get("proof_command"),
            primary_model=str(payload.get("primary_model") or ""),
            diff_text=str(payload.get("diff_text") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # D14/MED: Der Verifier hat einen Env-Fail-Open
    # (ARCHON_KANBAN_HITL_ALLOW_UNVERIFIED_OVERRIDE). Im Router wird die
    # Reverifikationspflicht hart durchgesetzt: ohne erfolgreichen Proof gibt
    # es keinen Uebergang nach 'todo' — unabhaengig von der Env-Variable.
    if (
        action in ("override", "override_budget")
        and decision.get("next_status") == "todo"
        and not decision.get("verified")
    ):
        decision["next_status"] = "blocked"
        decision["reason"] = (
            "Override ohne erfolgreiche Reverifikation gesperrt "
            "(Vier-Augen-Prinzip; Env-Fail-Open ist wirkungslos)."
        )

    # Signiertes Audit-Event mit Resolution, Actor und alter/neuer Budgetwert.
    try:
        from backend.audit_log import chained_audit_log
        # D08/MED: signierte HMAC-Kette (BEGIN IMMEDIATE, timeout=30) nie im
        # Event-Loop. audit_log.py:604 serialisiert die Kettenreihenfolge.
        await run_io_bound(
            chained_audit_log.record_event,
            category="security",
            action="kanban_hitl_resolution",
            agent_id=actor,
            payload={
                "task_id": task_id,
                "resolution": decision.get("resolution") or action,
                "actor": actor,
                "created_by": created_by,
                "old_budget": decision.get("old_budget", old_budget),
                "new_budget": decision.get("token_budget", old_budget),
                "verified": bool(decision.get("verified")),
            },
        )
    except Exception as exc:
        logger.warning("[Kanban] HITL-Audit-Event fehlgeschlagen: %s", exc)

    if decision.get("next_status") == "blocked":
        raise HTTPException(status_code=403, detail=decision.get("reason") or "Reverifikation fehlgeschlagen.")

    # Re-Dispatch ueber die registry-gestuetzte update_task_status (kein
    # direktes UPDATE tasks auf 'ready' mehr — 'ready' ist keine gueltiger Status).
    from backend.operations_api import TaskStatusUpdateRequest, update_task_status
    await update_task_status(
        request, task_id,
        TaskStatusUpdateRequest(
            status=decision["next_status"],
            source="hitl",
            result=str(decision.get("reason") or "")[:1000],
        ),
    )

    # Neues Budget im Task-Meta persistieren (nur bei override).
    if action in ("override", "override_budget"):
        try:
            from archon.routers.decisions import _decision_self_api
            await run_io_bound(
                _decision_self_api, "POST", "/api/operations/kanban/meta",
                {"kind": "task", "task_id": task_id, "token_budget": int(decision["token_budget"])},
            )
        except Exception as exc:
            logger.warning("[Kanban] HITL-Budget-Meta nicht persistiert: %s", exc)

    return {"status": "success", "task_id": task_id, **decision}


# --- M91: Precedent Log (Tenant-/Project-isoliert) ---
@router.get("/api/operations/precedents")
async def api_list_precedents(project_id: Optional[str] = None):
    from backend.precedent_log import canonical_tenant_id, list_precedents
    from backend.tenant_context import tenant_context
    # D11/MED: `tenant`/`tenant_id` über einen Kanoniker auflösen.
    tid = canonical_tenant_id(tenant_context.get_active_tenant_id())
    return {"status": "success", "precedents": list_precedents(tid, project_id)}


@router.post("/api/operations/precedents")
async def api_create_precedent(request: Request):
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    payload = await request.json()
    from backend.precedent_log import canonical_tenant_id, record_precedent
    from backend.tenant_context import tenant_context
    rec = record_precedent(
        # Tenant und Actor ausschliesslich aus verifiziertem Kontext (IDOR /
        # Body-Actor-Schutz, Audit 23.11.2026).
        tenant_id=canonical_tenant_id(tenant_context.get_active_tenant_id()),
        project_id=str(payload.get("project_id") or ""),
        question=str(payload.get("question") or ""),
        ruling_text=str(payload.get("ruling_text") or ""),
        created_by=require_session_actor(request),
        expires_at=payload.get("expires_at"),
    )
    return {"status": "success", "precedent": rec}


@router.delete("/api/operations/precedents/{precedent_id}")
async def api_revoke_precedent(request: Request, precedent_id: str):
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    from backend.precedent_log import canonical_tenant_id, revoke_precedent
    from backend.tenant_context import tenant_context
    ok = revoke_precedent(
        precedent_id, canonical_tenant_id(tenant_context.get_active_tenant_id())
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Precedent not found")
    return {"status": "success", "revoked": precedent_id}


# --- M89: Session Taint Guard HITL Approvals ---
@router.get("/api/v1/guardian/taint/approvals")
async def api_list_taint_approvals(request: Request):
    # Audit D04/HIGH: der lesende Endpoint war der einzige ungeschuetzte
    # Zugriff auf Session-IDs, Tool-Namen und args_json der HITL-Queue.
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    actor = require_session_actor(request)

    from backend.session_taint_guard import list_pending_taint_approvals

    # Admin-Dashboard: args_json nur hier (Verified-Admin) ausliefern.
    approvals = list_pending_taint_approvals(include_args=True)

    # Audit-Event fuer jeden Lesezugriff auf die Freigabe-Queue (signierte Kette).
    try:
        from backend.audit_log import chained_audit_log
        await run_io_bound(
            chained_audit_log.record_event,
            category="security",
            action="taint_approval_queue_read",
            agent_id=actor,
            payload={
                "endpoint": "/api/v1/guardian/taint/approvals",
                "approval_count": len(approvals),
                "include_args": True,
            },
        )
    except Exception as exc:
        logger.warning("[Kanban] Audit-Event Taint-Queue-Lesezugriff fehlgeschlagen: %s", exc)

    return {"status": "success", "approvals": approvals}


@router.post("/api/v1/guardian/taint/approvals/{approval_id}")
async def api_resolve_taint_approval(request: Request, approval_id: str):
    from archon.routers._rbac import require_admin_or_503
    require_admin_or_503(request)
    payload = await request.json()
    approved = bool(payload.get("approved", False))
    reviewer = require_session_actor(request)
    passkey_proof = str(payload.get("passkey_proof_token") or request.headers.get("x-passkey-proof") or "").strip()
    from backend.session_taint_guard import resolve_taint_approval
    try:
        res = resolve_taint_approval(
            approval_id, approved=approved, reviewer=reviewer, passkey_proof=passkey_proof
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not res:
        raise HTTPException(status_code=404, detail="Pending taint approval not found")
    return {"status": "success", "approval": res}

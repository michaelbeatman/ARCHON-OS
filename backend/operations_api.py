"""
Operations API Router for Archon OS
Provides Kanban (Hermes kanban.db), Org-Chart, and Inter-Agent Communication Feed.
"""

import asyncio
import base64 as base64
import datetime
import json
import logging
import os
import secrets
import sqlite3
import sys
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.operations_bulk import (
    _KANBAN_UNDO_STORE as _KANBAN_UNDO_STORE,
)
from backend.operations_bulk import (
    _KANBAN_UNDO_STORE_MAX_SIZE as _KANBAN_UNDO_STORE_MAX_SIZE,
)
from backend.operations_bulk import (
    BulkActionDeps as _BulkActionDeps,
)
from backend.operations_bulk import (
    KanbanBulkActionRequest as KanbanBulkActionRequest,
)
from backend.operations_bulk import (
    KanbanBulkUndoRequest as KanbanBulkUndoRequest,
)
from backend.operations_bulk import (
    _prune_undo_store as _prune_undo_store,
)
from backend.operations_bulk import (
    execute_kanban_bulk_action as _execute_kanban_bulk_action,
)
from backend.operations_bulk import (
    execute_kanban_bulk_undo as _execute_kanban_bulk_undo,
)
from backend.operations_constants import _get_org_hierarchy_file
from backend.operations_enrichment import (
    _PROFILES_MAP_CACHE as _PROFILES_MAP_CACHE,
)
from backend.operations_enrichment import (
    EnrichmentDeps as _EnrichmentDeps,
)
from backend.operations_enrichment import (
    _build_kanban_obsidian_map as _build_kanban_obsidian_map,
)
from backend.operations_enrichment import (
    _enrich_task as _enrich_task,
)
from backend.operations_enrichment import (
    _fuzzy_project_exact_match as _fuzzy_project_exact_match,
)
from backend.operations_enrichment import (
    _get_fallback_avatar as _get_fallback_avatar,
)
from backend.operations_enrichment import (
    _load_profiles_map as _load_profiles_map,
)
from backend.operations_enrichment import (
    _parse_kanban_ts as _parse_kanban_ts,
)
from backend.operations_enrichment import (
    _sync_to_memory_bridge as _sync_to_memory_bridge,
)
from backend.operations_enrichment import (
    register_enrichment_deps_provider as _register_enrichment_deps_provider,
)
from backend.operations_execution import (
    _CONSECUTIVE_FAILURES_MIGRATED_DBS as _CONSECUTIVE_FAILURES_MIGRATED_DBS,
)
from backend.operations_execution import (
    ExecutionDeps as _ExecutionDeps,
)
from backend.operations_execution import (
    _accept_loaded_handoff as _accept_loaded_handoff,
)
from backend.operations_execution import (
    _cross_model_verify_task_result as _cross_model_verify_task_result,
)
from backend.operations_execution import (
    _ensure_consecutive_failures_column as _ensure_consecutive_failures_column,
)
from backend.operations_execution import (
    _execute_kanban_task_async as _execute_kanban_task_async,
)
from backend.operations_execution import (
    _execute_kanban_task_inner as _execute_kanban_task_inner,
)
from backend.operations_execution import (
    _kanban_assign_orchestrator_sync as _kanban_assign_orchestrator_sync,
)
from backend.operations_execution import (
    _kanban_autonomy_gate_sync as _kanban_autonomy_gate_sync,
)
from backend.operations_execution import (
    _kanban_load_task_sync as _kanban_load_task_sync,
)
from backend.operations_execution import (
    _kanban_mark_started_sync as _kanban_mark_started_sync,
)
from backend.operations_execution import (
    _merge_task_meta_facts as _merge_task_meta_facts,
)
from backend.operations_execution import (
    _persist_kanban_result_sync as _persist_kanban_result_sync,
)
from backend.operations_execution import (
    register_execution_deps_provider as _register_execution_deps_provider,
)
from backend.operations_kanban_crud import (
    KanbanCrudDeps as _KanbanCrudDeps,
)
from backend.operations_kanban_crud import (
    TaskCreateRequest as TaskCreateRequest,
)
from backend.operations_kanban_crud import (
    TaskStatusUpdateRequest as TaskStatusUpdateRequest,
)
from backend.operations_kanban_crud import (
    _block_task_budget_allocation_failed_sync as _block_task_budget_allocation_failed_sync_impl,
)
from backend.operations_kanban_crud import (
    _update_task_status_db as _update_task_status_db,
)
from backend.operations_kanban_crud import (
    create_kanban_task_impl as _create_kanban_task_impl,
)
from backend.operations_kanban_crud import (
    list_kanban_tasks as _list_kanban_tasks,
)
from backend.operations_kanban_crud import (
    register_kanban_crud_deps_provider as _register_kanban_crud_deps_provider,
)
from backend.operations_kanban_crud import (
    reset_zombie_kanban_tasks_impl as _reset_zombie_kanban_tasks_impl,
)
from backend.operations_kanban_crud import (
    update_task_status_impl as _update_task_status_impl,
)
from backend.operations_kanban_meta import (
    KanbanMetaDeps as _KanbanMetaDeps,
)
from backend.operations_kanban_meta import (
    KanbanMetaSaveRequest as KanbanMetaSaveRequest,
)
from backend.operations_kanban_meta import (
    KanbanPaletteUpdate as KanbanPaletteUpdate,
)
from backend.operations_kanban_meta import (
    compute_kanban_stats as _compute_kanban_stats,
)
from backend.operations_kanban_meta import (
    fetch_task_details as _fetch_task_details,
)
from backend.operations_kanban_meta import (
    insert_task_comment as _insert_task_comment,
)
from backend.operations_kanban_meta import (
    load_kanban_palette as _load_kanban_palette,
)
from backend.operations_kanban_meta import (
    persist_kanban_meta as _persist_kanban_meta,
)
from backend.operations_kanban_meta import (
    persist_kanban_palette as _persist_kanban_palette,
)
from backend.operations_projects import (
    _PROJECTS_META_ALLOWED as _PROJECTS_META_ALLOWED,
)
from backend.operations_projects import (
    _PROJECTS_META_LOCK as _PROJECTS_META_LOCK,
)
from backend.operations_projects import (
    ProjectMetaUpdate as ProjectMetaUpdate,
)
from backend.operations_projects import (
    ProjectsDeps as _ProjectsDeps,
)
from backend.operations_projects import (
    build_projects_overview as _build_projects_overview,
)
from backend.operations_projects import (
    list_kanban_project_files as _list_kanban_project_files,
)
from backend.operations_projects import (
    list_project_folder_files as _list_project_folder_files,
)
from backend.operations_projects import (
    load_projects_meta as _load_projects_meta_impl,
)
from backend.operations_projects import (
    read_kanban_project_file_text as _read_kanban_project_file_text,
)
from backend.operations_projects import (
    read_raw_original_response as _read_raw_original_response,
)
from backend.operations_projects import (
    read_vault_file_text as _read_vault_file_text,
)
from backend.operations_projects import (
    resolve_task_obsidian_rel as _resolve_task_obsidian_rel_impl,
)
from backend.operations_projects import (
    save_projects_meta as _save_projects_meta_impl,
)
from backend.operations_projects import (
    search_vault_files as _search_vault_files,
)
from backend.operations_projects import (
    update_project_meta_entry as _update_project_meta_entry,
)
from backend.operations_review import (
    QualityReviewOverrideRequest as QualityReviewOverrideRequest,
)
from backend.operations_review import (
    QualityReviewRequest as QualityReviewRequest,
)
from backend.operations_review import (
    QualityReviewVerdict as QualityReviewVerdict,
)
from backend.operations_review import (
    ReviewDeps as _ReviewDeps,
)
from backend.operations_review import (
    _identity_tokens as _identity_tokens,
)
from backend.operations_review import (
    current_quality_review as _current_quality_review_impl,
)
from backend.operations_review import (
    require_four_eyes_override as _require_four_eyes_override,
)
from backend.operations_review import (
    run_quality_review as _run_quality_review,
)
from backend.operations_review import (
    run_quality_review_override as _run_quality_review_override,
)
from backend.operations_review import (
    task_created_by as _task_created_by_impl,
)
from backend.operations_review import (
    task_status as _task_status_impl,
)
from backend.platform_paths import HERMES_HOME
from backend.rbac_guards import forbid_viewer_writes, require_admin_or_503, require_session_actor

logger = logging.getLogger("archon_os.operations_api")


# ---------------------------------------------------------------------------
# D11: schema-validierte Payloads an der Kanban→Agent-Kante und im Review-Gate.
# ---------------------------------------------------------------------------
# F030/W3-A: das kanonische Handoff-Schema liegt ausschliesslich in
# `archon/core/delegation.py` (HandoffDelegationPayload, extra="forbid").
# Diese Modul konsumiert es nur noch ueber `canonicalize_delegation_payload`;
# eine lokale zweite Schema-Definition wuerde M75-Isolation und A2A-
# Korrelation erneut durch eine model_dump()-Projektion verlieren.


# D3/5: QualityReviewVerdict nach backend/operations_review.py ausgelagert (Re-Export am Kopf).


def _load_kanban_delegation_payload(
    raw_payload: Any, task_id: str = "", *, require_signature: bool = False
) -> Optional[Any]:
    """Konsumentenseite des kanonischen Handoffs (F030, D11-H1/H2).

    Ein einziger Aufruf der SSOT-Funktion in `archon.core.delegation`:
    HMAC-Verifikation **vor** jeder Kanonisierung -> bei signierten Payloads
    unveraenderte Uebernahme des gespeicherten Objekts -> extra="forbid"-
    Validierung. Kein lokales Schema, keine zweite model_dump()-Projektion,
    kein stiller Fallback.
    """
    if raw_payload is None:
        return None
    # Lazy import: `delegation` importiert seinerseits orchestration/mission_control.
    from archon.core.delegation import (
        HandoffDelegationPayload,
        canonicalize_delegation_payload,
        is_signed_delegation_payload,
        load_verified_delegation_payload,
    )
    try:
        if is_signed_delegation_payload(raw_payload):
            # Signierte SSOT: Verify vor Kanonisierung, unveränderte Daten.
            data = load_verified_delegation_payload(
                raw_payload, task_id=str(task_id or ""), require_signature=True
            )
        elif require_signature:
            logger.error("[KanbanWorker] Signatur fehlt — Payload abgewiesen.")
            return None
        else:
            # Unsignierte Legacy-Created-Events: dokumentierter Kanonisierungspfad.
            data = canonicalize_delegation_payload(raw_payload, task_id=str(task_id or ""))
        return HandoffDelegationPayload.model_validate(data)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.error("[KanbanWorker] Delegations-Payload/HMAC ungueltig: %s", exc)
        return None


router = APIRouter(
    prefix="/api/operations",
    tags=["operations"],
    dependencies=[Depends(forbid_viewer_writes)],
)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")


def _resolve_kanban_db_path() -> str:
    for candidate in [
        "/opt/data/kanban.db",
        os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
        os.path.join(HERMES_HOME, "kanban.db"),
        "/app/data/kanban.db",
    ]:
        if os.path.exists(candidate):
            return candidate
    return "/opt/data/kanban.db"


_DEFAULT_KANBAN_DB_PATH = _resolve_kanban_db_path()  # resolve_db-basiert, siehe Funktion
# 21.11.2026 (Fix-Sprint Paket A): dynamische Umleitung via Tenant-Context ist
# der einzige Pfad — der alte, tote Branch "KANBAN_DB_PATH != default" ist entfernt.
KANBAN_DB_PATH = _DEFAULT_KANBAN_DB_PATH

# 21.11.2026 (Fix-Sprint Paket A): gueltige Kanban-Statuswerte fuer die
# Status-Validierung an update_task_status (422 bei ungültigem Wert).
VALID_KANBAN_STATUSES = {"backlog", "todo", "in_progress", "review", "done", "blocked", "archived", "failed"}

# Zombie-Reset-Gedrossel: nur einmal pro 60 Sekunden (Paket A, Punkt 8)
_ZOMBIE_RESET_LAST_RUN = {"ts": 0.0}
_ZOMBIE_RESET_INTERVAL_S = 60.0


def _maybe_auto_reset_zombie_tasks(conn: sqlite3.Connection) -> int:
    """Auto-Crash-Recovery (Pillar 2): Tasks, die > 6 h in 'in_progress' hängen,
    auf 'todo' zurücksetzen — aber nur bei abgelaufener Lease / totem Worker
    (`trajectory_budget.zombie_eligible`). Gedrosselt auf max. 1x pro 60 s."""
    now = time.time()
    if now - _ZOMBIE_RESET_LAST_RUN["ts"] < _ZOMBIE_RESET_INTERVAL_S:
        return 0
    _ZOMBIE_RESET_LAST_RUN["ts"] = now
    cutoff_ts = now - 21600
    cutoff_iso = datetime.datetime.fromtimestamp(cutoff_ts).isoformat()

    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    extra_cols = [c for c in ("claim_expires", "claim_lock", "pid") if c in cols]
    select_cols = ", ".join(["id", "status"] + extra_cols)
    candidates = conn.execute(f"""
        SELECT {select_cols}
        FROM tasks
        WHERE status = 'in_progress'
          AND (
            (CAST(started_at AS REAL) >= 1000000000 AND CAST(started_at AS REAL) < ?)
            OR (started_at IS NOT NULL AND started_at LIKE '____-__-__%' AND started_at < ?)
            OR (started_at IS NULL AND created_at IS NOT NULL AND created_at < ?)
          )
    """, (cutoff_ts, cutoff_iso, cutoff_iso)).fetchall()
    if not candidates:
        return 0

    try:
        from backend.trajectory_budget import zombie_eligible
    except Exception as exc:
        # D07-H1: kein fail-open. Ohne verifizierten Liveness-Guard darf
        # ueberhaupt kein Task zurueckgesetzt werden (sonst doppelte
        # Seiteneffects laufender Agenten).
        logger.error(
            "[OperationsAPI] Zombie-Liveness-Guard nicht verfuegbar — kein Reset: %s", exc
        )
        try:
            from backend.audit_log import _require_audit_event

            _require_audit_event(
                "recovery",
                "zombie_guard_unavailable",
                "system",
                {"error": str(exc)[:300], "candidates": len(candidates)},
            )
        except Exception as audit_exc:
            logger.error(
                "[OperationsAPI] Audit zombie_guard_unavailable fehlgeschlagen: %s", audit_exc
            )
        return 0

    eligible_ids = []
    for row in candidates:
        row_dict = {"id": row[0], "status": row[1]}
        for idx, col_name in enumerate(extra_cols, start=2):
            row_dict[col_name] = row[idx]
        if zombie_eligible(row_dict, now=now):
            eligible_ids.append(row[0])

    if not eligible_ids:
        return 0

    reset_count = 0
    # Zustaetzlicher CAS: nur Tasks ohne aktive Lease duerfen zurueckgesetzt
    # werden — auch wenn der Guard zwischen Lesen und Schreiben veraltet.
    _cas = " AND (claim_expires IS NULL OR CAST(claim_expires AS REAL) <= ?)" if "claim_expires" in extra_cols else ""
    _cas_args = (now,) if _cas else ()
    for tid in eligible_ids:
        cur = conn.execute(
            "UPDATE tasks SET status = 'todo', started_at = NULL "
            "WHERE id = ? AND status = 'in_progress'" + _cas,
            (tid, *_cas_args),
        )
        reset_count += cur.rowcount
    if reset_count:
        print(f"[OperationsAPI] Auto-Zombie-Reset: {reset_count} Tasks zurueckgesetzt (Maintenance-Pfad).", file=sys.stderr)
    conn.commit()
    return reset_count


_KANBAN_JOURNAL_INIT = False
_KANBAN_JOURNAL_INIT_DBS: set = set()


def _get_active_kanban_db_path(company_id: Optional[str] = None) -> str:
    if not company_id and KANBAN_DB_PATH != _DEFAULT_KANBAN_DB_PATH:
        return KANBAN_DB_PATH
    try:
        from backend.tenant_context import tenant_context
        resolved = tenant_context.resolve_active_db("kanban.db", company_id)
        if resolved:
            return resolved
    except Exception as exc:
        print(f"[OperationsAPI] WARNUNG (MEDIUM) _get_active_kanban_db_path: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
    return KANBAN_DB_PATH


def _get_kanban_connection(company_id: Optional[str] = None, maintenance: bool = False):
    global _KANBAN_JOURNAL_INIT
    target_db = _get_active_kanban_db_path(company_id)
    if not os.path.exists(target_db):
        raise HTTPException(status_code=503, detail=f"kanban.db nicht gefunden unter {target_db}")
    conn = sqlite3.connect(target_db, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    if (not _KANBAN_JOURNAL_INIT) or (target_db not in _KANBAN_JOURNAL_INIT_DBS):
        try:
            if os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes"):
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            # 21.11.2026 (Fix-Sprint Paket A): Zombie-Reset läuft NICHT mehr bei
            # jedem Connect (auch reinen Lese-Connects) — er ist in die
            # _maybe_auto_reset_zombie_tasks() ausgelagert und wird nur von
            # Schreib-/Maintenance-Pfaden mit maintenance=True angestoßen.
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS task_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    author TEXT DEFAULT 'user',
                    body TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_links (
                    parent_id TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    kind TEXT DEFAULT 'subtask',
                    created_at TEXT,
                    PRIMARY KEY (parent_id, child_id)
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    run_id INTEGER,
                    kind TEXT NOT NULL,
                    payload TEXT,
                    created_at INTEGER NOT NULL
                );
                -- D08-M7: der einzige Index war (kind, id) in mission_control.py;
                -- alle heissen Lesepfade filtern aber zuerst nach task_id
                -- (delegation.py:1601/1888, operations_review.py). Ohne diesen
                -- Prefix ist jeder Taskabschluss ein Full Table Scan.
                CREATE INDEX IF NOT EXISTS idx_events_task_kind
                    ON task_events(task_id, kind, id);
            """)
            # Schema-Migration fuer aeltere kanban.db-Instanzen ohne kind/created_at auf task_links
            tl_cols = {r[1] for r in conn.execute("PRAGMA table_info(task_links)").fetchall()}
            if "kind" not in tl_cols:
                conn.execute("ALTER TABLE task_links ADD COLUMN kind TEXT DEFAULT 'subtask'")
            if "created_at" not in tl_cols:
                conn.execute("ALTER TABLE task_links ADD COLUMN created_at TEXT")
            conn.commit()
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _get_kanban_connection: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
        _KANBAN_JOURNAL_INIT = True
        _KANBAN_JOURNAL_INIT_DBS.add(target_db)
    # 21.11.2026 (Fix-Sprint Paket A): gedrosselter Zombie-Reset nur auf
    # Schreib-/Maintenance-Connects (Punkt 8) — reine Lese-Connects bleiben unberuehrt.
    if maintenance:
        try:
            _maybe_auto_reset_zombie_tasks(conn)
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _get_kanban_connection: Zombie-Reset fehlgeschlagen: {exc}", file=sys.stderr)
    conn.row_factory = sqlite3.Row
    return conn


# D3/7: Enrichment-, Profil- & Obsidian-Batch-Helfer nach
# backend/operations_enrichment.py ausgelagert (S3 Call-Time-Deps).
def _load_kanban_meta() -> Dict:
    """Sidecar-Metadaten (NICHT in kanban.db — Engine bleibt unberuehrt):
    Due-Dates/Tags pro Task sowie WIP-Limits pro Spalte."""
    from backend.kanban_sidecar import load_kanban_meta
    return load_kanban_meta()


def _save_kanban_meta(meta: Dict) -> None:
    # M-12: Diese Funktion war ein zweiter, UNGESPERRTER Writer neben
    # backend.kanban_sidecar.update_kanban_meta. Damit der naechste Aufrufer die
    # Sperre nicht umgehen kann, schreiben wir jetzt ausschliesslich ueber den
    # gelockten update_kanban_meta-Pfad (Load-Modify-Write unter threading.Lock,
    # atomar via Temp+os.replace).
    from backend.kanban_sidecar import update_kanban_meta
    update_kanban_meta(lambda _current: meta)


def _build_enrichment_deps() -> _EnrichmentDeps:
    return _EnrichmentDeps(
        profiles_file=PROFILES_FILE,
        load_kanban_meta=_load_kanban_meta,
        get_fallback_avatar=_get_fallback_avatar,
        resolve_task_obsidian_rel=_resolve_task_obsidian_rel,
    )


_register_enrichment_deps_provider(_build_enrichment_deps)


# =========================================================================
# 1. KANBAN ENDPOINTS
# =========================================================================
# D3/8: TaskCreateRequest, TaskStatusUpdateRequest und die CRUD-/Status-Logik
# liegen in backend/operations_kanban_crud.py (X-as-X Re-Exports am Kopf).


# D3/5: QualityReviewRequest, QualityReviewOverrideRequest, _identity_tokens
# und _require_four_eyes_override liegen in backend/operations_review.py
# (X-as-X Re-Exports am Kopf).


def _build_review_deps() -> _ReviewDeps:
    return _ReviewDeps(
        get_kanban_connection=_get_kanban_connection,
        load_kanban_meta=_load_kanban_meta,
        load_profiles_map=_load_profiles_map,
        current_quality_review=_current_quality_review,
        task_created_by=_task_created_by,
        task_status=_task_status,
        require_four_eyes_override=_require_four_eyes_override,
    )


def _current_quality_review(task_id: str) -> Dict[str, Any]:
    return _current_quality_review_impl(task_id, _build_review_deps())


def _task_created_by(task_id: str) -> str:
    return _task_created_by_impl(task_id, _build_review_deps())


def _task_status(task_id: str) -> str:
    return _task_status_impl(task_id, _build_review_deps())


def _build_kanban_crud_deps() -> _KanbanCrudDeps:
    return _KanbanCrudDeps(
        get_kanban_connection=_get_kanban_connection,
        load_profiles_map=_load_profiles_map,
        load_kanban_meta=_load_kanban_meta,
        build_kanban_obsidian_map=_build_kanban_obsidian_map,
        enrich_task=_enrich_task,
        sync_to_memory_bridge=_sync_to_memory_bridge,
        current_quality_review=_current_quality_review,
        task_created_by=_task_created_by,
        task_status=_task_status,
        require_four_eyes_override=_require_four_eyes_override,
        execute_kanban_task_async=_execute_kanban_task_async,
        update_task_status_db=_update_task_status_db,
        block_task_budget_allocation_failed_sync=_block_task_budget_allocation_failed_sync,
        valid_kanban_statuses=VALID_KANBAN_STATUSES,
    )


_register_kanban_crud_deps_provider(_build_kanban_crud_deps)


@router.get("/kanban/tasks")
def get_kanban_tasks(archived: bool = Query(False)):
    """Board-Daten: aktive Tasks gruppiert nach Spalten; ?archived=true liefert die flache Archiv-Liste."""
    return _list_kanban_tasks(archived=archived)


def _task_creator_actor(request: Request) -> str:
    """D14: verifizierter Ersteller aus der Session — nie Body, nie Konstante.

    Bei Service-/Self-API-Aufrufen ist keine Person zuordenbar: dann leer
    zurückgeben, damit der HITL-Override fail-closed blockiert (statt gegen
    einen Platzhalter zu prüfen).
    """
    try:
        from backend.rbac_guards import get_current_user_from_request
        user = get_current_user_from_request(request)
    except Exception:
        return ""
    if not isinstance(user, dict):
        return ""
    for key in ("username", "user_id", "sub", "email"):
        val = user.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


@router.post("/kanban/tasks")
def _block_task_budget_allocation_failed_sync(
    task_id: str,
    title: str,
    assignee: str,
    reason: str,
    subtask_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """D13/MED: Task ohne registriertes hartes Ticket-Cap nie ausfuehrbar."""
    return _block_task_budget_allocation_failed_sync_impl(
        task_id, title, assignee, reason, subtask_ids
    )


def create_kanban_task(request: Request, req: TaskCreateRequest):
    """Erstellt eine neue Aufgabe im Hermes Kanban über CLI-Execution oder direkten Insert."""
    require_admin_or_503(request)
    return _create_kanban_task_impl(req, _task_creator_actor(request))


# D3/6: Kanban Task-Ausfuehrung, Lease/Cancel-Fencing & Cross-Model-Verification
# nach backend/operations_execution.py ausgelagert (S3 Call-Time-Deps).
def _build_execution_deps() -> _ExecutionDeps:
    return _ExecutionDeps(
        get_active_kanban_db_path=_get_active_kanban_db_path,
        get_kanban_connection=_get_kanban_connection,
        load_kanban_delegation_payload=_load_kanban_delegation_payload,
        sync_to_memory_bridge=_sync_to_memory_bridge,
        load_profiles_map=_load_profiles_map,
        resolve_task_obsidian_rel=_resolve_task_obsidian_rel,
        load_kanban_meta=_load_kanban_meta,
    )


_register_execution_deps_provider(_build_execution_deps)


@router.patch("/kanban/tasks/{task_id}/status")
async def update_task_status(request: Request, task_id: str, req: TaskStatusUpdateRequest):
    """Verschiebt eine Aufgabe in eine neue Spalte / Status und startet ggf. Ausführung."""
    require_admin_or_503(request)
    actor = require_session_actor(request)
    return await _update_task_status_impl(task_id, actor, req)


# In-Memory Store für 10-Minuten Undo-Transaktionen (t-c2b384)
# D3/2: Bulk-Aktionen & 10-Minuten-Undo-Puffer nach backend/operations_bulk.py ausgelagert.
# Re-Exports (inkl. identischem _KANBAN_UNDO_STORE-Dict) liegen am Modulkopf.


def _build_bulk_deps() -> _BulkActionDeps:
    return _BulkActionDeps(
        get_kanban_connection=_get_kanban_connection,
        load_kanban_meta=_load_kanban_meta,
        sync_to_memory_bridge=_sync_to_memory_bridge,
        valid_kanban_statuses=VALID_KANBAN_STATUSES,
    )


@router.post("/kanban/bulk")
def api_kanban_bulk_action(request: Request, req: KanbanBulkActionRequest):
    """Führt eine Mehrfachaktion auf ausgewählten Kanban-Tasks aus mit 10-Minuten-Undo-Puffer (t-c2b384)."""
    require_admin_or_503(request)
    return _execute_kanban_bulk_action(req, _build_bulk_deps())


@router.post("/kanban/bulk/undo")
def api_kanban_bulk_undo(request: Request, req: KanbanBulkUndoRequest):
    """Macht eine Mehrfachaktion innerhalb des 10-Minuten-Zeitfensters rückgängig (t-c2b384)."""
    require_admin_or_503(request)
    return _execute_kanban_bulk_undo(req, _build_bulk_deps())


def _approve_kanban_task_db(task_id: str) -> dict:
    """Fix-Sprint Paket A (Punkt 1): der komplette synchrone SQLite-Block der
    Freigabe — inklusive Approved-/Unblocked-Events. Läuft via asyncio.to_thread."""
    conn = _get_kanban_connection(maintenance=True)
    try:
        row = conn.execute("SELECT id, status, block_kind FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")
        _status = row["status"] if hasattr(row, "keys") else row[1]
        _block_kind = row["block_kind"] if hasattr(row, "keys") else row[2]
        # D07: fail-closed — nur Tasks, die wirklich auf Freigabe warten.
        # Ein wegen Budget/Zero-Egress/Lease/Taint blockierter Task darf nicht
        # durch die Approval-Route freigesetzt werden.
        if str(_status) not in ("awaiting_approval", "blocked") or str(_block_kind or "") != "approval":
            raise HTTPException(status_code=409, detail={
                "reason": "NOT_APPROVABLE", "status": str(_status), "block_kind": str(_block_kind or "")
            })
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.execute(
            "UPDATE tasks SET status = 'todo', block_kind = 'approval_granted' "
            "WHERE id = ? AND status IN ('awaiting_approval','blocked') AND block_kind = 'approval'",
            (task_id,),
        )
        if not getattr(cur, "rowcount", 0):
            raise HTTPException(status_code=409, detail={"reason": "APPROVAL_RACE"})
        _previous_status = str(_status)
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'approved', ?, ?)",
            (task_id, json.dumps({"by": "owner", "previous_status": _previous_status}), now_iso),
        )
        # Sticky-Sperre aufheben (Hermes-Protokoll: 'unblocked' muss das letzte Block-Event sein)
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'unblocked', ?, ?)",
            (task_id, json.dumps({"by": "owner", "reason": "approval_granted"}), now_iso),
        )
        conn.commit()
        return {"previous_status": row["status"] if hasattr(row, "keys") else row[1]}
    finally:
        conn.close()


@router.post("/kanban/tasks/{task_id}/approve")
async def approve_kanban_task(request: Request, task_id: str):
    """Erteilt die Autonomie-Freigabe (approval) und startet die Aufgabe."""
    require_admin_or_503(request)
    await asyncio.to_thread(_approve_kanban_task_db, task_id)
    # F: to_thread gibt im aktiven Event-Loop zurück; registry-gestuetzter
    # Spawn statt nacktem create_task (Shutdown kennt den Worker sonst nicht).
    from archon.core.task_registry import spawn as _spawn_tracked
    _spawn_tracked(_execute_kanban_task_async(task_id), name=f"kanban_task:{task_id}")
    return {"status": "success", "task_id": task_id, "message": "Freigegeben und gestartet."}


@router.post("/kanban/tasks/{task_id}/quality-review")
async def trigger_quality_review(task_id: str, request: Request, req: QualityReviewRequest = Body(default=QualityReviewRequest())):
    """
    Führt ein 4-Augen-Qualitätsreview für einen Kanban-Task durch.
    Ein unabhängiger Reviewer-Agent (Standard: Katharina Völk bzw. Robert bei Eigenarbeiten)
    prüft das Arbeitsergebnis objektiv gegen den ursprünglichen Auftrag.
    """
    require_admin_or_503(request)
    actor = require_session_actor(request)
    return await _run_quality_review(task_id, actor, _build_review_deps())


@router.post("/kanban/tasks/{task_id}/quality-review/override")
async def override_quality_review(
    request: Request, task_id: str, req: QualityReviewOverrideRequest
):
    """H-14-2/F022: einziger erlaubter Weg, `changes_requested` aufzuheben."""
    require_admin_or_503(request)
    actor = require_session_actor(request)
    return await _run_quality_review_override(task_id, actor, req, _build_review_deps())


class ResetZombieTasksRequest(BaseModel):
    """D06/MED: typisierter Body statt rohem ``dict`` in einer Admin-Schreibroute."""

    model_config = ConfigDict(extra="ignore")

    assignee: str = ""
    task_id: str = ""
    target_status: Literal["todo", "blocked", "review", "done"] = "todo"


@router.post("/kanban/reset-zombies")
def reset_zombie_kanban_tasks(request: Request, payload: ResetZombieTasksRequest = Body(default_factory=ResetZombieTasksRequest)):
    """Setzt hängengebliebene 'in_progress' Tasks (optional gefiltert nach assignee oder Alter) auf 'todo' zurück."""
    require_admin_or_503(request)
    return _reset_zombie_kanban_tasks_impl(
        assignee=payload.assignee,
        task_id=payload.task_id,
        target_status=payload.target_status,
    )


# --- Kanban-Farbpalette (User-Wunsch 10.10.2026: einstellbar über Design-Tab) ---
# 10.10.2026: statt data/ (anonymer Volume, host-unsichtbar) → config/
_KANBAN_PALETTE_FILE = os.path.join(WORKSPACE_DIR, "config", "kanban_palette.json")

# Posteo-Naturpalette (Standard, wie fest im Kanban eingebaut)
KANBAN_PALETTE_DEFAULTS = {
    "triage":      {"header": "#FFF5EB", "text": "#7c6a56"},
    "todo":        {"header": "#F3E8DE", "text": "#6b5d4f"},
    "ready":       {"header": "#F1B56F", "text": "#7a4a12"},
    "in_progress": {"header": "#EED65B", "text": "#6b5c10"},
    "review":      {"header": "#7CA982", "text": "#2f4a33"},
    "blocked":     {"header": "#C15C53", "text": "#ffffff"},
    "done":        {"header": "#4A6D88", "text": "#ffffff"}
}

# D3/4: KanbanPaletteUpdate nach backend/operations_kanban_meta.py ausgelagert (Re-Export am Kopf).

# D3/3: Projekt-Zentrale, Projekt-Meta-Sidecar und Vault-/Projektdatei-Zugriff
# nach backend/operations_projects.py ausgelagert (S3 Call-Time-Deps).
_PROJECTS_META_FILE = os.path.join(WORKSPACE_DIR, "config", "projects_meta.json")


def _build_projects_deps() -> _ProjectsDeps:
    return _ProjectsDeps(
        get_kanban_connection=_get_kanban_connection,
        load_kanban_meta=_load_kanban_meta,
        fuzzy_project_exact_match=_fuzzy_project_exact_match,
        projects_meta_file=_PROJECTS_META_FILE,
    )


def _resolve_task_obsidian_rel(task_id: str, meta: Optional[dict] = None, auto_heal: bool = False) -> Optional[str]:
    """Ermittelt den relativen Obsidian-Projektordner fuer eine Task mit automatischer Reparatur/Fallback."""
    return _resolve_task_obsidian_rel_impl(task_id, _build_projects_deps(), meta=meta, auto_heal=auto_heal)


def _load_projects_meta() -> Dict:
    return _load_projects_meta_impl(_PROJECTS_META_FILE)


def _save_projects_meta(data: Dict) -> None:
    _save_projects_meta_impl(_PROJECTS_META_FILE, data)


@router.get("/projects/overview")
def get_projects_overview():
    """Liefert die konsolidierte Projekt-Zentrale fuer Operations:
    Laufende, abgeschlossene und geplante Projekte mit Unteraufgaben, Status und Direktlinks zu HTML-Berichten."""
    return _build_projects_overview(_build_projects_deps())


@router.get("/projects/{project_id}/meta")
def get_project_meta(project_id: str):
    meta = _load_projects_meta().get(project_id) or {}
    return {"status": "success", "project_id": project_id, "meta": meta}


@router.put("/projects/{project_id}/meta")
def put_project_meta(project_id: str, upd: ProjectMetaUpdate, request: Request):
    require_admin_or_503(request)
    return _update_project_meta_entry(project_id, upd, _PROJECTS_META_FILE)


@router.get("/projects/{project_id}/files")
def get_project_folder_files(project_id: str):
    """Listet alle Dateien des Projektordners 01_PROJEKTE/<id> im Obsidian-Vault (traversal-geschuetzt)."""
    return _list_project_folder_files(project_id)


@router.get("/kanban/projects/{task_id}")
def get_kanban_project_files(task_id: str):
    """Listet die Dateien des verknuepften Obsidian-Projekts einer Task (Sidecar-Bruecke)."""
    return _list_kanban_project_files(task_id, _build_projects_deps())


@router.get("/raw")
def get_raw_original(request: Request, path: str):
    """'Original oeffnen' fuer Dateien AUSSERHALB des Vaults (systeminterne
    Pfade /opt/data, /app): liefert Bytes mit inline-disposition, damit der
    Browser PDF/Bilder/MD direkt zeigt bzw. laedt. Traversal-Schutz ueber
    erlaubte Basis-Pruefung."""
    require_admin_or_503(request)
    return _read_raw_original_response(path)


@router.get("/vault/file")
def get_vault_file(request: Request, path: str):
    """SYSTEMWEITER Datei-Reader: liefert EINE Vault-Datei (01_PROJEKTE/...) als Text.
    Traversal-Schutz: safe_path_within(Vault) + Suffix-Whitelist.
    Fix-Sprint Paket A (Punkt 10): liefert sensible Vault-Inhalte -> Admin-Gate."""
    require_admin_or_503(request)
    return _read_vault_file_text(path)


@router.get("/vault/find")
def find_vault_file(request: Request, q: str, limit: int = 8):
    """Findet Vault-Dateien per Name/Teilstring (fuer nackte .md-Namen aus Chat-Texten).
    Fix-Sprint Paket A (Punkt 10): exposes Vault-Struktur -> Admin-Gate."""
    require_admin_or_503(request)
    return _search_vault_files(q, limit=limit)


@router.get("/kanban/projects/{task_id}/file")
def get_kanban_project_file(request: Request, task_id: str, path: str):
    """Liefert EINE Projektdatei als Text - nur innerhalb des Projektordners (Traversal-Schutz).
    Fix-Sprint Paket A (Punkt 10): liefert sensible Vault-Inhalte -> Admin-Gate."""
    require_admin_or_503(request)
    return _read_kanban_project_file_text(task_id, path, _build_projects_deps())


# D3/4: Kanban-Palette, Sidecar-Meta, Board-Stats, Task-Details & Kommentare
# nach backend/operations_kanban_meta.py ausgelagert (S3 Call-Time-Deps).
def _build_kanban_meta_deps() -> _KanbanMetaDeps:
    return _KanbanMetaDeps(
        get_kanban_connection=_get_kanban_connection,
        load_kanban_meta=_load_kanban_meta,
        parse_kanban_ts=_parse_kanban_ts,
        load_profiles_map=_load_profiles_map,
        get_fallback_avatar=_get_fallback_avatar,
        resolve_task_obsidian_rel=_resolve_task_obsidian_rel,
        palette_file=_KANBAN_PALETTE_FILE,
        palette_defaults=KANBAN_PALETTE_DEFAULTS,
    )


@router.get("/kanban/palette")
def get_kanban_palette():
    """Liefert die Kanban-Spaltenfarben (Gespeicherte, mit Posteo-Standard gemischt)."""
    return _load_kanban_palette(_KANBAN_PALETTE_FILE, KANBAN_PALETTE_DEFAULTS)


@router.post("/kanban/palette")
def save_kanban_palette(request: Request, req: KanbanPaletteUpdate):
    """Speichert die Kanban-Farbpalette (oder setzt mit reset=true auf Standard zurück)."""
    require_admin_or_503(request)
    return _persist_kanban_palette(req, _KANBAN_PALETTE_FILE, KANBAN_PALETTE_DEFAULTS)


@router.get("/kanban/meta")
def get_kanban_meta():
    """Sidecar-Metadaten: Due-Dates/Tags pro Task + WIP-Limits pro Spalte."""
    return {"status": "ok", **_load_kanban_meta()}


@router.post("/kanban/meta")
def save_kanban_meta(request: Request, body: KanbanMetaSaveRequest):
    """Due/Tags (kind=task) oder WIP-Limits (kind=wip) speichern. Engine-DB bleibt unberuehrt."""
    require_admin_or_503(request)
    return _persist_kanban_meta(body)


@router.get("/kanban/stats")
def kanban_stats():
    """Board-Kennzahlen: Spaltenverteilung, Durchlaufzeit, 7-Tage-Flows."""
    return _compute_kanban_stats(_build_kanban_meta_deps())


@router.get("/kpi/output-economics")
def get_output_economics(
    group_by: Literal["project", "agent_profile", "period", "output_type"] = Query("project"),
    project: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    output_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    period: Literal["day", "week", "month"] = Query("day"),
):
    """M100: Output-Wirtschaftlichkeit (done + Deliverable), rein lesend.

    Rollups nach Projekt/Agenten-Profil/Zeitraum/Output-Typ inklusive
    Zeitreihe je Output-Typ. Nutzenbewertung bleibt bewusst manuell.
    """
    from backend.output_economics import aggregate_output_economics

    return aggregate_output_economics(
        group_by=group_by,
        project=project,
        agent=agent,
        output_type=output_type,
        date_from=date_from,
        date_to=date_to,
        period=period,
    )


@router.get("/kanban/tasks/{task_id}")
def get_task_details(task_id: str):
    """Gibt Detailinformationen, Kommentare und Event-Logs eines Tasks zurück."""
    return _fetch_task_details(task_id, _build_kanban_meta_deps())


@router.post("/kanban/tasks/{task_id}/comments")
def add_task_comment(request: Request, task_id: str, author: str = Body(..., embed=True), body: str = Body(..., embed=True)):
    """Fügt einem Task einen Kommentar hinzu (Timestamp als integer Unix-Epoch für Hermes-Kompatibilität)."""
    require_admin_or_503(request)
    return _insert_task_comment(task_id, author, body, _build_kanban_meta_deps())


# =========================================================================
# OPERATIONS-UNTER-ROUTER (14): Registrierung in archon/routers/operations/
# Reihenfolge = Pfad-Praezedenz: org -> dag -> prompts -> receipts -> sysops
# -> dunning -> finetuning -> approvals -> keys -> emails -> security ->
# bot_screen -> autonomy -> pbd. backend darf archon.routers nicht importieren
# (D09/H-09-2); main.py:2752 importiert den aggregierten Router von dort.
# Die EIGENEN Endpunkte dieses Moduls (Kanban, Esign, ...) bleiben hier.
# =========================================================================
ORG_HIERARCHY_FILE = _get_org_hierarchy_file()


# =========================================================================
# ESIGN (DocuSeal) - eigene Endpunkte auf diesem Router
# =========================================================================
class EsignSubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="", max_length=300)
    signer_email: str = Field(default="", max_length=200)
    signer_name: str = Field(default="", max_length=200)
    template_id: Optional[str] = Field(default=None, max_length=100)
    kanban_task_id: Optional[str] = Field(default=None, max_length=100)
    company_id: Optional[str] = Field(default=None, max_length=100)


class EsignWebhookEvent(BaseModel):
    """DocuSeal-Webhook: bekannte Felder + restliche Event-Daten (extra="allow")."""
    model_config = ConfigDict(extra="allow")
    event_type: Optional[str] = Field(default=None, max_length=120)
    type: Optional[str] = Field(default=None, max_length=120)
    data: Dict[str, Any] = Field(default_factory=dict)


@router.post("/esign/submissions")
def api_esign_create_submission(request: Request, req: EsignSubmissionCreateRequest):
    """Erstellt eine neue digitale Signaturanfrage via DocuSeal."""
    require_admin_or_503(request)
    title = req.title.strip()
    signer_email = req.signer_email.strip()
    signer_name = req.signer_name.strip()
    template_id = req.template_id
    kanban_task_id = req.kanban_task_id

    if not title or not signer_email or not signer_name:
        raise HTTPException(status_code=400, detail="Felder 'title', 'signer_email' und 'signer_name' sind erforderlich.")

    try:
        from backend.docuseal_client import docuseal_client
        res = docuseal_client.create_submission(
            title=title,
            signer_email=signer_email,
            signer_name=signer_name,
            template_id=template_id,
            kanban_task_id=kanban_task_id,
            company_id=req.company_id,
        )
        return {"status": res.get("status", "draft_offline"), "submission": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DocuSeal Submission fehlgeschlagen: {e}")


@router.get("/esign/contracts")
def api_esign_list_contracts(
    limit: int = Query(default=50),
    company_id: Optional[str] = Query(default=None),
):
    """Listet alle Signaturverträge auf."""
    try:
        from backend.docuseal_client import docuseal_client
        contracts = docuseal_client.list_contracts(limit=limit, company_id=company_id)
        return {"status": "success", "count": len(contracts), "contracts": contracts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/esign/webhook")
def api_esign_webhook(request: Request, payload: EsignWebhookEvent):
    """Empfängt Webhooks von DocuSeal nach Unterzeichnung eines Dokuments."""
    webhook_secret = os.getenv("DOCUSEAL_WEBHOOK_SECRET")
    if webhook_secret:
        header_secret = request.headers.get("X-DocuSeal-Secret") or request.headers.get("X-Webhook-Secret") or request.query_params.get("secret")
        if not header_secret or not secrets.compare_digest(str(header_secret), str(webhook_secret)):
            raise HTTPException(status_code=403, detail="Ungueltiges Webhook-Secret.")
    else:
        # Fix-Sprint Paket A (Punkt 10): ohne konfiguriertes DOCUSEAL_WEBHOOK_SECRET
        # gibt es KEINEN stillen Admin-Fallback mehr — der Endpoint fail-closed mit 503,
        # damit Dritte nicht an die Webhook-Verarbeitung kommen koennen.
        print(
            "[OperationsAPI] WARNUNG (HIGH_SECURITY) api_esign_webhook: DOCUSEAL_WEBHOOK_SECRET ist nicht konfiguriert — Webhook-Annahme abgelehnt (503).",
            file=sys.stderr,
        )
        raise HTTPException(
            status_code=503,
            detail="DocuSeal-Webhook ist nicht konfiguriert: DOCUSEAL_WEBHOOK_SECRET fehlt. Endpoint ist abgeschaltet."
        )

    try:
        from backend.docuseal_client import docuseal_client
        res = docuseal_client.handle_webhook_event(payload.model_dump())
        return {"status": "success", "webhook_result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook Verarbeitung fehlgeschlagen: {e}")




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

from archon.core.provider_registry import get_provider
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
from backend.operations_constants import TEAMS_DEFINITION, _get_org_hierarchy_file
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


def _load_kanban_delegation_payload(raw_payload: Any, task_id: str = "") -> Optional[Any]:
    """Konsumentenseite des kanonischen Handoffs (F030).

    Ein einziger Aufruf der SSOT-Funktion in `archon.core.delegation`:
    Legacy-Aliase -> extra="forbid"-Validierung -> Server-Kontext
    (Tenant/Projekt/Cancel/Taint/Budget/Soul) -> HMAC-Signatur. Kein lokales
    Schema, keine zweite model_dump()-Projektion, kein stiller Fallback.
    """
    if raw_payload is None:
        return None
    # Lazy import: `delegation` importiert seinerseits orchestration/mission_control.
    from archon.core.delegation import (
        HandoffDelegationPayload,
        canonicalize_delegation_payload,
    )
    try:
        data = canonicalize_delegation_payload(
            raw_payload, task_id=str(task_id or "")
        )
        return HandoffDelegationPayload.model_validate(data)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.error("[KanbanWorker] Delegations-Payloadschema ungueltig: %s", exc)
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
    except Exception:
        zombie_eligible = None  # type: ignore[assignment]

    eligible_ids = []
    for row in candidates:
        row_dict = {"id": row[0], "status": row[1]}
        for idx, col_name in enumerate(extra_cols, start=2):
            row_dict[col_name] = row[idx]
        if zombie_eligible is None or zombie_eligible(row_dict, now=now):
            eligible_ids.append(row[0])

    if not eligible_ids:
        return 0

    reset_count = 0
    for tid in eligible_ids:
        cur = conn.execute(
            "UPDATE tasks SET status = 'todo', started_at = NULL WHERE id = ? AND status = 'in_progress'",
            (tid,),
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


def _parse_kanban_ts(value) -> Optional[float]:
    """Wandelt einen Kanban-Zeitstempel in Epoch-Sekunden um.

    Das Modul schreibt ISO-Strings (``datetime.now().isoformat()``), aeltere
    Zeilen koennen aber auch float-Epochs enthalten. Fuer die KPI-Berechnung
    (R-20/F-01) ist beides noetig — ``float('2026-11-08T09:00:00')`` wirft
    sonst ValueError und die KPIs bleiben dauerhaft leer.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except (TypeError, ValueError) as exc:
        print(f"[OperationsAPI] Fallback _parse_kanban_ts: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _sync_to_memory_bridge(task_id: str, title: Optional[str], assignee: Optional[str], status: str, result: Optional[str] = None):
    """Synchronisiert Kanban-Aufgaben mit der zentralen agentic_memory.db (tasks-Tabelle)."""
    try:
        from local_memory_bridge import memory_bridge
        obsidian_rel = None
        try:
            meta = _load_kanban_meta()
            obsidian_rel = ((meta.get("tasks") or {}).get(task_id) or {}).get("obsidian")
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _sync_to_memory_bridge: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
        memory_bridge.sync_task(
            task_id=task_id,
            title=title or task_id,
            role=assignee or "unassigned",
            status=status,
            result=result,
            obsidian_note=obsidian_rel
        )
    except Exception as e:
        print(f"[OperationsAPI] MemoryBridge task sync notice: {e}", file=sys.stderr)


_PROFILES_MAP_CACHE: Dict[str, Any] = {"mtime": 0.0, "data": {}}

def _load_profiles_map() -> Dict[str, Dict]:
    if os.path.exists(PROFILES_FILE):
        try:
            mtime = os.path.getmtime(PROFILES_FILE)
            if _PROFILES_MAP_CACHE["data"] and _PROFILES_MAP_CACHE["mtime"] == mtime:
                return _PROFILES_MAP_CACHE["data"]
            profiles = {}
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    profiles[item.get("id")] = item
            _PROFILES_MAP_CACHE["mtime"] = mtime
            _PROFILES_MAP_CACHE["data"] = profiles
            return profiles
        except Exception as e:
            print(f"[OperationsAPI] Error loading profiles: {e}", file=sys.stderr)
    # Audit v3 2.1.4: profile.yaml/SOUL.md des Profilordners als Ergänzung einlesen,
    # damit Profile die NUR dort existieren nicht unsichtbar bleiben.
    try:
        import yaml as _yaml

        from archon.core.profiles import get_primary_hermes_profiles_dir
        base = get_primary_hermes_profiles_dir()
        if os.path.isdir(base):
            _map = _PROFILES_MAP_CACHE["data"]
            for pid in os.listdir(base):
                pdir = os.path.join(base, pid)
                if not os.path.isdir(pdir) or pid.startswith("."):
                    continue
                entry = dict(_map.get(pid) or {})
                ypath = os.path.join(pdir, "profile.yaml")
                if os.path.exists(ypath):
                    try:
                        with open(ypath, "r", encoding="utf-8") as f:
                            ydata = _yaml.safe_load(f) or {}
                        for k in ("name", "person_name", "category", "model", "tools", "skills", "status"):
                            v = ydata.get(k)
                            if v is not None and k not in entry:
                                entry[k] = v
                    except Exception as exc:
                        print(f"[OperationsAPI] profile.yaml {pid} unlesbar: {exc}", file=sys.stderr)
                spath = os.path.join(pdir, "SOUL.md")
                if os.path.exists(spath) and not entry.get("prompt"):
                    try:
                        with open(spath, "r", encoding="utf-8", errors="ignore") as f:
                            entry["prompt"] = f.read().strip()
                    except OSError:
                        pass
                if entry:
                    _map.setdefault(pid, entry)
    except Exception as exc:
        print(f"[OperationsAPI] profile.yaml-Ergänzung fehlgeschlagen: {exc}", file=sys.stderr)
    return _PROFILES_MAP_CACHE["data"]


def _get_fallback_avatar(aid: str) -> str:
    if not aid:
        return "/static/avatars/avatar_002.jpg"
    import hashlib
    h = int(hashlib.sha256(str(aid).encode("utf-8")).hexdigest(), 16) % 108 + 1
    if h == 1:
        h = 2
    return f"/static/avatars/avatar_{h:03d}.jpg"


# ACHTUNG (10.10.2026): /app/data ist ein anonymer Volume, der den
# Host-Bind-Mount überschattet — Dateien unter data/ sind host-seitig
# UNSICHTBAR und gehen bei Container-Recreate verloren. Deshalb: config/!
# 12.10.2026: Besitzer der Sidecar-Datei ist backend/kanban_sidecar.py
# (Lock + atomares Schreiben) — hier NIE direkt auf die Datei zugreifen.


def _fuzzy_project_exact_match(needle: str, folder_names: list) -> Optional[str]:
    """Fix-Sprint Paket A (Punkt 9): exakter Match zuerst; Substring-Match nur
    bei Mindestlaenge >= 4 UND eindeutigem Treffer (genau 1), sonst kein Match
    plus sichtbarer Log-Hinweis."""
    n = str(needle or "").strip()
    if not n:
        return None
    for name in folder_names:
        if name == n:
            return name
    if len(n) < 4:
        if n:
            print(f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{n}' abgelehnt (Mindestlänge 4 unterschritten).", file=sys.stderr)
        return None
    subs = [name for name in folder_names if n in name]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        print(f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{n}' mehrdeutig ({len(subs)} Treffer) — kein Match.", file=sys.stderr)
    return None


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


def _build_kanban_obsidian_map(conn: sqlite3.Connection, rows: list, meta: Dict) -> Dict[str, Optional[str]]:
    """Loest alle Obsidian-Projektordner fuer ein Kanban-Board einmalig im Batch auf (statt O(N) DB/FS-Scans)."""
    from pathlib import Path as _P

    from backend.post_task_pipeline import get_vault_dir

    result: Dict[str, Optional[str]] = {}
    meta_tasks = meta.get("tasks") or {}
    vault = _P(get_vault_dir()).resolve()
    proj_root = vault / "01_PROJEKTE"

    # Einmalig alle Projektordner & bekannte Artefakt-Dateinamen einlesen
    proj_dirs: list = []
    if proj_root.is_dir():
        try:
            for d in proj_root.iterdir():
                if d.is_dir():
                    proj_dirs.append(d)
        except Exception:
            proj_dirs = []
    valid_proj_names = {d.name for d in proj_dirs}

    # Einmalig Parent-Child-Verknuepfungen laden
    parent_by_child: Dict[str, str] = {}
    try:
        for child_id, parent_id in conn.execute("SELECT child_id, parent_id FROM task_links WHERE COALESCE(kind, 'subtask') = 'subtask'").fetchall():
            if child_id and parent_id and child_id != parent_id and child_id not in parent_by_child:
                parent_by_child[child_id] = parent_id
    except Exception as exc:
        print(f"[OperationsAPI] WARNUNG (MEDIUM) _build_kanban_obsidian_map: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

    # Einmalig Endprodukte/Zwischenberichte nach Task-IDs durchsuchen, falls noetig
    file_hits: Dict[str, str] = {}
    for p_dir in proj_dirs:
        rel_p = f"01_PROJEKTE/{p_dir.name}"
        for sub in ("03_Endprodukte", "01_Zwischenberichte"):
            s_dir = p_dir / sub
            if s_dir.is_dir():
                try:
                    for f in s_dir.iterdir():
                        fname = f.name
                        file_hits[fname] = rel_p
                except Exception as exc:
                    print(f"[OperationsAPI] Fallback _build_kanban_obsidian_map: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

    proj_slug_parts = []
    for p_dir in proj_dirs:
        parts = [pt for pt in p_dir.name.lower().split("-") if len(pt) >= 4 and pt not in ("projekt", "delegationsprojekt", "2026")]
        proj_slug_parts.append((f"01_PROJEKTE/{p_dir.name}", p_dir.name, parts))

    row_by_id: Dict[str, Dict] = {}
    for r in rows:
        rd = dict(r)
        tid = rd.get("id")
        if tid:
            row_by_id[tid] = rd

    def _resolve_one(tid: str, depth: int = 0) -> Optional[str]:
        if tid in result:
            return result[tid]
        if depth > 4:
            return None
        t_entry = meta_tasks.get(tid) or {}
        rel = t_entry.get("obsidian")
        if rel and str(rel).strip():
            rel_s = str(rel).strip()
            # Schneller Check ohne teure Symlink-Auflösung fuer bekannte 01_PROJEKTE-Ordner
            if rel_s.startswith("01_PROJEKTE/") and rel_s.split("/", 2)[1] in valid_proj_names:
                result[tid] = rel_s
                return rel_s
            cand = (vault / rel_s).resolve()
            if str(cand).startswith(str(vault)) and cand.is_dir():
                result[tid] = rel_s
                return rel_s

        dossier = (t_entry.get("decision") or {}).get("dossier") or ""
        if "01_PROJEKTE/" in dossier:
            sub = dossier.split("01_PROJEKTE/")[1].split("/")[0]
            if sub in valid_proj_names:
                rel_s = f"01_PROJEKTE/{sub}"
                result[tid] = rel_s
                return rel_s

        pid_parent = parent_by_child.get(tid)
        if pid_parent:
            p_rel = _resolve_one(pid_parent, depth + 1)
            if p_rel:
                result[tid] = p_rel
                return p_rel

        rd = row_by_id.get(tid) or {}
        proj_id = rd.get("project_id")
        if proj_id:
            # Punkt 9: exakter Match zuerst, Substring nur >= 4 Zeichen & eindeutig
            _pl = str(proj_id).strip()
            exact = next((sp for sp in proj_slug_parts if sp[1] == _pl), None)
            if exact:
                result[tid] = exact[0]
                return exact[0]
            if len(_pl) >= 4:
                subs = [sp for sp in proj_slug_parts if _pl in sp[1]]
                if len(subs) == 1:
                    result[tid] = subs[0][0]
                    return subs[0][0]
                if len(subs) > 1:
                    print(f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für '{_pl}' mehrdeutig ({len(subs)} Treffer) — kein Match.", file=sys.stderr)

        # Task-ID-Substring nur bei eindeutigem Treffer (Punkt 9)
        _tid_hits = [sp for sp in proj_slug_parts if len(tid) >= 4 and tid in sp[1]]
        if len(_tid_hits) == 1:
            result[tid] = _tid_hits[0][0]
            return _tid_hits[0][0]
        if len(_tid_hits) > 1:
            print(f"[OperationsAPI] Hinweis: Fuzzy-Projekt-Match für Task-ID '{tid}' mehrdeutig ({len(_tid_hits)} Treffer) — kein Match.", file=sys.stderr)

        for fname, rel_p in file_hits.items():
            if tid in fname:
                result[tid] = rel_p
                return rel_p

        combined = ((rd.get("title") or "") + " " + (rd.get("body") or "")).lower()
        if combined.strip():
            for rel_p, _dname, parts in proj_slug_parts:
                if any(pt in combined for pt in parts):
                    result[tid] = rel_p
                    return rel_p

        result[tid] = None
        return None

    for tid in list(row_by_id.keys()):
        _resolve_one(tid)
    return result


def _enrich_task(
    task_dict: Dict,
    profiles: Dict,
    meta: Dict,
    obsidian_map: Optional[Dict[str, Optional[str]]] = None,
) -> Dict:
    assignee_id = task_dict.get("assignee")
    prof = profiles.get(assignee_id, {})
    task_dict["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
    task_dict["assignee_role"] = prof.get("category") or prof.get("role") or "Spezialist"
    task_dict["assignee_avatar"] = prof.get("avatar") or _get_fallback_avatar(assignee_id or "")
    tmeta = (meta.get("tasks") or {}).get(task_dict.get("id")) or {}
    task_dict["due_date"] = tmeta.get("due") or None
    task_dict["tags"] = tmeta.get("tags") or []
    tid = task_dict.get("id")
    if obsidian_map is not None:
        task_dict["obsidian"] = obsidian_map.get(tid)  # type: ignore[arg-type]
    else:
        task_dict["obsidian"] = _resolve_task_obsidian_rel(tid, meta)  # type: ignore[arg-type]
    task_dict["tokens"] = tmeta.get("tokens") or None
    task_dict["cost"] = tmeta.get("cost") or None
    task_dict["quality_review"] = tmeta.get("quality_review") or None
    task_dict["soul_mode"] = tmeta.get("soul_mode") or None
    task_dict["reasoning_effort"] = tmeta.get("reasoning_effort") or None
    task_dict["tool_preset"] = tmeta.get("tool_preset") or None
    task_dict["token_budget"] = tmeta.get("token_budget") or None
    task_dict["cost_limit_usd"] = tmeta.get("cost_limit_usd") or None
    task_dict["require_hitl"] = bool(tmeta.get("require_hitl"))
    task_dict["cron_schedule"] = tmeta.get("cron_schedule") or None
    task_dict["depends_on"] = tmeta.get("depends_on") or None
    task_dict["trusted_input"] = bool(tmeta.get("trusted_input"))
    _dec = tmeta.get("decision") or None
    task_dict["decision"] = ({"typ": _dec.get("typ"),
                              "status": _dec.get("status") or "offen",
                              "titel": _dec.get("titel")} if isinstance(_dec, dict) else None)
    return task_dict


# =========================================================================
# 1. KANBAN ENDPOINTS
# =========================================================================

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


@router.get("/kanban/tasks")
def get_kanban_tasks(archived: bool = Query(False)):
    """Board-Daten: aktive Tasks gruppiert nach Spalten; ?archived=true liefert die flache Archiv-Liste."""
    if hasattr(archived, "default"):
        archived = archived.default
    archived = bool(archived)
    conn = _get_kanban_connection()

    profiles = _load_profiles_map()
    meta = _load_kanban_meta()
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
        if archived:
            cursor.execute(base_select + " WHERE status = 'archived' ORDER BY completed_at DESC")
            arch_rows = cursor.fetchall()
            obs_map = _build_kanban_obsidian_map(conn, arch_rows, meta)
            tasks = [_enrich_task(dict(r), profiles, meta, obsidian_map=obs_map) for r in arch_rows]
            return {"status": "success", "archived": True, "tasks": tasks, "total": len(tasks)}

        cursor.execute(base_select + " ORDER BY priority DESC, created_at DESC")
        rows = cursor.fetchall()
        obs_map = _build_kanban_obsidian_map(conn, rows, meta)

        columns: Dict[str, List[Any]] = {
            "triage": [],
            "todo": [],
            "ready": [],
            "in_progress": [],
            "review": [],
            "done": [],
            "blocked": [],
            "scheduled": [],
            "failed": []
        }

        active_rows = 0
        for r in rows:
            task_dict = dict(r)
            st = (task_dict.get("status") or "todo").lower()
            if st == "archived":
                # 2-Stufen-Archiv (10.10.2026): archiviert gehoert nicht aufs Board
                # (vorher fiel archived still in den todo-Bucket)
                continue
            # Freigabe-Status ist verbindlich: unabhaengig davon, was ein fremder
            # Schreiber (Hermes-Kanban-Worker teilt dieselbe DB) am Status aendert.
            if (task_dict.get("block_kind") or "").lower() == "approval":
                st = "blocked"
            _enrich_task(task_dict, profiles, meta, obsidian_map=obs_map)
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
            "wip": meta.get("wip", {})
        }
    finally:
        conn.close()


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
    """D13/MED: Task ohne registriertes hartes Ticket-Cap nie ausfuehrbar.

    Die Allokation in ``task_budget_allocations`` ist die einzige Grundlage
    fuer den Task-Cap in ``BudgetBank.reserve``. Schlaegt sie fehl, werden
    Root (und bereits angelegte Subtasks) atomar auf ``blocked`` gesetzt,
    der Grund in task_events und in die HMAC-Auditkette geschrieben.
    """
    now_iso = datetime.datetime.now().isoformat()
    detail = f"budget_allocation_failed: {reason}"[:500]
    conn = _get_kanban_connection(maintenance=True)
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
    _sync_to_memory_bridge(task_id, title, assignee, "blocked", detail)
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="recovery",
            action="budget_allocation_failed",
            agent_id="system",
            payload={"task_id": task_id, "reason": detail[:300]},
        )
    except Exception as audit_exc:
        # Audit-Schreibfehler nie still verschlucken (§0).
        logger.error("[OperationsAPI] Budget-Audit fehlgeschlagen: %s", audit_exc)
    return {"blocked": True, "task_id": task_id, "reason": detail}


def create_kanban_task(request: Request, req: TaskCreateRequest):
    """Erstellt eine neue Aufgabe im Hermes Kanban über CLI-Execution oder direkten Insert."""
    require_admin_or_503(request)
    conn = _get_kanban_connection(maintenance=True)
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()
        
        # Generiere kurze ID wie t-XXXX
        import secrets
        task_id = f"t-{secrets.token_hex(3)}"
        
        target_status = req.column if req.column in ["triage", "todo", "ready", "in_progress", "review", "done", "blocked", "scheduled"] else "todo"
        
        # Falls Team angegeben, aber kein spezifischer Agent: Auto-Routing zum Department Lead
        target_assignee = req.assignee
        team_name = ""
        if req.team_id:
            team_match = next((t for t in TEAMS_DEFINITION if t["id"] == req.team_id), None)
            if team_match:
                team_name = team_match["name"]  # type: ignore[assignment]
                if not target_assignee:
                    target_assignee = team_match["lead_id"]  # type: ignore[assignment]
                    
        # Optionales Team-Präfix im Body
        task_body = req.body or ""
        if team_name and f"[Team: {team_name}]" not in task_body:
            task_body = f"[Team: {team_name}]\n{task_body}".strip()
            
        cursor.execute("""
            INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, model_override, provider_override, block_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            req.title,
            task_body,
            target_assignee,
            target_status,
            req.priority or 0,
            _task_creator_actor(request),
            now_iso,
            req.model_override,
            req.provider_override,
            "hitl_gate" if req.require_hitl else None
        ))

        if req.depends_on and str(req.depends_on).strip():
            dep_id = str(req.depends_on).strip()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO task_links (parent_id, child_id, kind, created_at) VALUES (?, ?, 'blocks', ?)",
                    (dep_id, task_id, now_iso)
                )
            except Exception as exc:
                print(f"[OperationsAPI] WARNUNG (MEDIUM) create_kanban_task: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
        
        # Log event
        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "created", json.dumps({
            "title": req.title,
            "assignee": target_assignee,
            "team": req.team_id,
            "status": target_status,
            "soul_mode": req.soul_mode,
            "reasoning_effort": req.reasoning_effort,
            "tool_preset": req.tool_preset,
        }), now_iso))
        
        conn.commit()
        _sync_to_memory_bridge(task_id, req.title, target_assignee, target_status)

        # Sidecar-Metadaten (SOUL, Reasoning, Tool-Preset, Budget, HITL, Due, Cron, Dependency, CEO-Hiring)
        eff_cost_eur = req.cost_limit_eur if req.cost_limit_eur is not None else (
            round(float(req.cost_limit_usd) * 0.92, 2) if req.cost_limit_usd is not None else None
        )
        if any([
            req.soul_mode, req.reasoning_effort, req.tool_preset,
            req.token_budget, req.cost_limit_usd, eff_cost_eur, req.require_hitl,
            req.due_date, req.cron_schedule, req.depends_on, req.trusted_input,
            req.allow_autonomous_hiring
        ]):
            try:
                from backend.kanban_sidecar import update_kanban_meta
                def _save_create_meta(meta):
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

        decomposition_plan = None
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
                for idx, sub in enumerate(decomposition_plan.get("subtasks", [])):
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
                    def _save_sub_budgets(meta):
                        for idx, sub in enumerate(decomposition_plan.get("subtasks", [])):
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
                # D13/MED: frueher nur stderr — der Task blieb ausfuehrbar,
                # obwohl kein hartes Ticket-Cap in task_budget_allocations
                # registriert war. Fail-closed: Task + evtl. Subtasks blocken.
                logger.error(
                    "[OperationsAPI] Budget-Decompose fehlgeschlagen — Task %s wird blockiert: %s",
                    task_id, dec_err,
                )
                _block_task_budget_allocation_failed_sync(
                    task_id, req.title, target_assignee, str(dec_err), created_subtask_ids  # type: ignore[arg-type]
                )
                return {
                    "status": "blocked", "task_id": task_id,
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
                    task_id, alloc_err,
                )
                _block_task_budget_allocation_failed_sync(
                    task_id, req.title, target_assignee, str(alloc_err)  # type: ignore[arg-type]
                )
                return {
                    "status": "blocked", "task_id": task_id,
                    "block_kind": "budget_allocation_failed",
                    "reason": f"budget_allocation_failed: {alloc_err}",
                }

        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "created", "task_id": task_id, "status": target_status})
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) create_kanban_task: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        resp_out = {
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
    von update_task_status — wird via asyncio.to_thread ausgefuehrt.

    H-14-2/F022: der `status_changed`-Event traegt Actor, force, reason und
    (bei erzwungenem `done`) den verifizierten 4-Augen-Evidence-Block.
    """
    conn = _get_kanban_connection(maintenance=True)
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        cursor.execute("SELECT id, title, assignee, status FROM tasks WHERE id = ?", (task_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")

        old_status = existing["status"]

        # 4-Augen Qualitäts-Gate Prüfung: Wenn Task auf 'done' verschoben werden soll,
        # prüfen ob ein Review mit 'changes_requested' vorliegt (es sei denn, force=True)
        if new_status == "done" and not force:
            meta = _load_kanban_meta()
            t_meta = (meta.get("tasks") or {}).get(task_id, {})
            q_rev = t_meta.get("quality_review")
            if q_rev and q_rev.get("status") == "changes_requested":
                critique_msg = ", ".join(q_rev.get("critique_points") or []) or q_rev.get("summary") or "Nachbesserung erforderlich"
                raise HTTPException(
                    status_code=400,
                    detail=f"4-Augen-Review blockiert Abschluss: {q_rev.get('reviewer', 'Qualitätsprüfer')} fordert Nachbesserung! ({critique_msg})"
                )

        cursor.execute("""
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
        """, (new_status, new_status, new_status, now_iso, new_status, now_iso, result, task_id))

        status_payload: Dict[str, Any] = {
            "from": old_status,
            "to": new_status,
            "actor": str(actor or ""),
            "force": bool(force),
            "reason": str(reason or "") or None,
        }
        if force and new_status == "done":
            status_payload["four_eyes_evidence"] = override_evidence or {}
            q_rev = _current_quality_review(task_id)
            status_payload["previous_review"] = {
                "status": q_rev.get("status"),
                "reviewer_id": q_rev.get("reviewer_id"),
                "reviewer": q_rev.get("reviewer"),
            }
        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "status_changed", json.dumps(status_payload, ensure_ascii=False), now_iso))

        conn.commit()
        return {
            "old_status": old_status,
            "title": existing["title"],
            "assignee": existing["assignee"],
            "now_iso": now_iso,
        }
    finally:
        conn.close()


@router.patch("/kanban/tasks/{task_id}/status")
async def update_task_status(request: Request, task_id: str, req: TaskStatusUpdateRequest):
    """Verschiebt eine Aufgabe in eine neue Spalte / Status und startet ggf. Ausführung."""
    require_admin_or_503(request)
    # H-14-2/F022: Actor ausschliesslich aus der verifizierten Session.
    actor = require_session_actor(request)
    new_status = (req.status or "").lower()
    # Punkt 3 (Fix-Sprint Paket A): Status-Validierung
    if new_status not in VALID_KANBAN_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Ungültiger Status '{req.status}'. Erlaubt sind: {', '.join(sorted(VALID_KANBAN_STATUSES))}"
        )

    # H-14-2/F022: `force=true` auf `done` ist ein Hoheitsakt. Ohne zweite,
    # identitaetsverschiedene Person + an Task gebundenen HITL-Proof bleibt
    # der Task unveraendert (403). Das gilt auch bei `changes_requested`.
    override_evidence: Optional[Dict[str, Any]] = None
    if bool(req.force) and new_status == "done":
        review = await asyncio.to_thread(_current_quality_review, task_id)
        created_by = await asyncio.to_thread(_task_created_by, task_id)
        old_status_before_force = await asyncio.to_thread(_task_status, task_id)
        override_evidence = _require_four_eyes_override(
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
            _require_audit_event(
                "governance", "status_forced", actor,
                {
                    "task_id": task_id, "from": old_status_before_force, "to": new_status,
                    "force": True, "old_review": review, "reason": req.reason or "",
                    "approval_id": override_evidence.get("approval_id"),
                },
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    # Fix-Sprint Paket A (Punkt 2): SQLite-/Datei-IO blockiert den Event-Loop nicht mehr
    info = await asyncio.to_thread(
        _update_task_status_db, task_id, new_status, req.result, bool(req.force),
        actor, req.reason or "", override_evidence,
    )
    old_status = info["old_status"]

    try:
        await asyncio.to_thread(
            _sync_to_memory_bridge, task_id, info["title"], info["assignee"], new_status, req.result
        )
    except Exception as exc:
        print(f"[OperationsAPI] WARNUNG (MEDIUM) update_task_status: Memory-Bridge fehlgeschlagen: {exc}", file=sys.stderr)

    # Autonome LLM-Ausführung starten, wenn Task auf 'in_progress' oder von 'review'/'failed'/'blocked' auf 'todo' gesetzt wurde
    # (Fix-Sprint Paket A, Punkt 1: create_task läuft hier garantiert im aktiven Event-Loop)
    # F: Fire-and-Forget-Tasks muessen in der zentralen Registry landen, sonst
    # kennt weder GracefulShutdown noch task_registry.cancel_all() sie.
    from archon.core.task_registry import spawn as _spawn_tracked
    if new_status == "in_progress" and old_status != "in_progress":
        _spawn_tracked(_execute_kanban_task_async(task_id), name=f"kanban_task:{task_id}")
    elif new_status == "todo" and old_status in ("review", "failed", "blocked", "done"):
        _spawn_tracked(_execute_kanban_task_async(task_id), name=f"kanban_task:{task_id}")

    # 12.10.2026 (Decision-Service, Richtung Kanban -> Telegram): Wird ein
    # Entscheidungs-Task (Sidecar-Block 'decision') ueber die Oberflaeche
    # verschoben, informiert der Owner-Kanal. NICHT beim Aufruf durch den
    # Decision-Service (source == 'decision') - der bestaetigt selbst.
    if old_status == "review" and new_status != "review" and (req.source or "") != "decision":
        try:
            _dm = (await asyncio.to_thread(_load_kanban_meta)).get("tasks", {}).get(task_id, {}).get("decision")
            if _dm:
                from telegram_notify import send_telegram_message
                _verb = ("✅ freigegeben" if new_status in ("todo", "in_progress", "done")
                         else "⛔ abgelehnt/verworfen")
                await asyncio.to_thread(
                    send_telegram_message,
                    f"{_verb} — {_dm.get('titel') or task_id}\n"
                    f"(im Kanban verschoben: review → {new_status})")
        except Exception as _tg_err:
            print(f"[OperationsAPI] Telegram-Benachrichtigung fehlgeschlagen: {_tg_err}", file=sys.stderr)

    try:
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": old_status, "to": new_status})
    except Exception as exc:
        print(f"[OperationsAPI] WARNUNG (MEDIUM) update_task_status: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

    return {"status": "success", "task_id": task_id, "old_status": old_status, "new_status": new_status}


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
    conn = _get_kanban_connection(maintenance=True)
    try:
        assignee = (payload.assignee or "").strip()
        task_id = (payload.task_id or "").strip()
        target_status = payload.target_status
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        if task_id:
            cursor.execute("SELECT id, title, assignee FROM tasks WHERE id = ? AND status = 'in_progress'", (task_id,))
        elif assignee:
            cursor.execute("SELECT id, title, assignee FROM tasks WHERE status = 'in_progress' AND LOWER(assignee) = LOWER(?)", (assignee,))
        else:
            cursor.execute("SELECT id, title, assignee FROM tasks WHERE status = 'in_progress'")

        rows = cursor.fetchall()
        reset_ids = []
        for r in rows:
            tid = r["id"]
            cursor.execute("UPDATE tasks SET status = ?, started_at = NULL WHERE id = ?", (target_status, tid))
            cursor.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (tid, "zombie_reset", json.dumps({"from": "in_progress", "to": target_status, "by": "user_or_watchdog"}), now_iso)
            )
            _sync_to_memory_bridge(tid, r["title"], r["assignee"], target_status)
            reset_ids.append(tid)

        conn.commit()
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event") and reset_ids:
                main.broadcast_event("kanban_updated", {"action": "zombie_reset", "task_ids": reset_ids, "to": target_status})
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) reset_zombie_kanban_tasks: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        return {"status": "ok", "reset_count": len(reset_ids), "task_ids": reset_ids, "target_status": target_status}
    finally:
        conn.close()


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




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
import re
import secrets
import sqlite3
import sys
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from archon.core.provider_registry import get_provider
from backend.handoff_desk import mark_truncated, require_accepted_handoff
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


class QualityReviewVerdict(BaseModel):
    """Fail-closed-Schema der Reviewer-Antwort (R-16)."""

    model_config = ConfigDict(extra="ignore")

    verdict: str = "changes_requested"
    score: int = 0
    summary: str = ""
    critique_points: List[str] = Field(default_factory=list)
    actionable_next_steps: List[str] = Field(default_factory=list)


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


class QualityReviewRequest(BaseModel):
    """H-14-2/F022: kein Body-Actor und kein erzwungenes Verdict mehr.

    `force_verdict` und `reviewer_id` waren direkt aus dem Body faehig, das
    Vier-Augen-Gate zu faelschen (hartcodierter Reviewer `operator`). Die
    Verifikation läuft jetzt immer ueber den Reviewer-Agenten; eine manuelle
    Aufhebung von `changes_requested` nur ueber
    ``POST /kanban/tasks/{id}/quality-review/override`` mit Session-Actor,
    zweiter Identitaet und HITL-Proof.
    """

    model_config = ConfigDict(extra="ignore")

    comment: Optional[str] = Field(default=None, max_length=4000)


class QualityReviewOverrideRequest(BaseModel):
    """Expliziter 4-Augen-Override eines `changes_requested`-Reviews."""

    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=10, max_length=4000)
    passkey_proof_token: Optional[str] = None
    approval_id: Optional[str] = None


# --- H-14-2/F022: gemeinsame Hoheits-Gates (4 Augen + HITL + Audit) ----------

def _identity_tokens(actor: str) -> set:
    """Normalisierte Identitaets-Tokens (wie in approval_policy_engine)."""
    s = str(actor or "").strip().lower()
    if not s:
        return set()
    tokens = {s}
    if " (i.v. " in s:
        main_p, sub_p = s.split(" (i.v. ", 1)
        tokens.add(main_p.strip())
        sub_clean = sub_p.rstrip(")").strip()
        if sub_clean:
            tokens.add(sub_clean)
            tokens.add(sub_clean.split(" ")[0])
    else:
        tokens.add(s.split(" ")[0])
    return {t for t in tokens if t}


def _current_quality_review(task_id: str) -> Dict[str, Any]:
    """Liest das Review aus der Sidecar-SSOT (fail-closed bei Fehlern)."""
    try:
        meta = _load_kanban_meta()
        return dict(((meta.get("tasks") or {}).get(task_id) or {}).get("quality_review") or {})
    except Exception as exc:
        logger.error("[4-Augen] Review-Sidecar nicht lesbar (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="quality_review_state_unavailable")


def _task_created_by(task_id: str) -> str:
    conn = _get_kanban_connection(maintenance=True)
    try:
        row = conn.execute("SELECT created_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return str((row["created_by"] if row else "") or "")
    finally:
        conn.close()


def _task_status(task_id: str) -> str:
    conn = _get_kanban_connection(maintenance=True)
    try:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return str((row["status"] if row else "") or "")
    finally:
        conn.close()


def _require_four_eyes_override(
    *,
    task_id: str,
    actor: str,
    review: Dict[str, Any],
    reason: str,
    proof_token: Optional[str],
    action: str,
    created_by: str = "",
    approval_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Prueft die Hoheits-Kette fuer `done`-Overrides (fail-closed).

    Rueckgabe: signierfaehiger Evidence-Block. Jede Verletzung fuehrt zu 403;
    nicht verfuegbare HITL-Konfiguration zu 503. Der Actor stammt ausschliesslich
    aus ``require_session_actor(request)``.
    """
    who = str(actor or "").strip()
    why = str(reason or "").strip()
    if not who:
        raise HTTPException(status_code=401, detail="Keine verifizierte Session-Identitaet.")
    if len(why) < 10:
        raise HTTPException(400, detail="Begruendung des 4-Augen-Overrides fehlt oder zu kurz (min. 10 Zeichen).")

    actor_tokens = _identity_tokens(who)
    other_ids = [
        str(review.get("reviewer_id") or ""),
        str(review.get("reviewer") or ""),
        str(created_by or ""),
    ]
    for other in other_ids:
        if other and actor_tokens & _identity_tokens(other):
            raise HTTPException(
                status_code=403,
                detail="Vier-Augen-Prinzip: der Override muss durch eine andere Person erfolgen "
                       "als der Reviewer oder der Ersteller des Tasks.",
            )

    from backend.passkey_hitl import consume_hitl_proof_token

    # Hoheitsakt: der Passkey-Proof ist IMMER zwingend und an action+resource
    # gebunden. `is_passkey_required()` darf hier nicht zum Freigang fuehren —
    # auch im Single-User-Modus ohne Passkey-Config bleibt der Akt gesperrt.
    token = str(proof_token or "").strip()
    try:
        ok = consume_hitl_proof_token(
            token, who, "system", action=action, resource=task_id, consume=True
        )
    except Exception as exc:
        logger.error("[4-Augen] HITL-Pruefung fehlgeschlagen (fail-closed): %s", exc)
        raise HTTPException(status_code=503, detail="hitl_proof_check_unavailable")
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Passkey-Proof erforderlich/ungueltig fuer diesen 4-Augen-Override "
                   "(action/resource nicht gebunden).",
        )

    evidence = {
        "actor": who,
        "reason": why,
        "action": action,
        "resource": task_id,
        "approval_id": str(approval_id or "").strip() or None,
        "first_reviewer_id": str(review.get("reviewer_id") or ""),
        "previous_review_status": str(review.get("status") or ""),
        "hitl_proof_verified": True,
        "verified_at": datetime.datetime.now().isoformat(),
    }
    try:
        from backend.audit_log import _require_audit_event
        _require_audit_event(
            "governance", "four_eyes_override_verified", who,
            {"task_id": task_id, **evidence},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return evidence


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


_CONSECUTIVE_FAILURES_MIGRATED_DBS: set = set()


def _ensure_consecutive_failures_column(conn: sqlite3.Connection) -> None:
    """Fix-Sprint Paket A (Punkt 10): Retry-Zaehler-Spalte nachziehen, falls das
    Schema aelter ist. Wird einmal pro DB-Pfad ausgefuehrt."""
    target_db = _get_active_kanban_db_path()
    if target_db in _CONSECUTIVE_FAILURES_MIGRATED_DBS:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "consecutive_failures" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN consecutive_failures INTEGER DEFAULT 0")
        conn.commit()
        print(f"[OperationsAPI] Schema-Migration: tasks.consecutive_failures hinzugefuegt ({target_db}).", file=sys.stderr)
    _CONSECUTIVE_FAILURES_MIGRATED_DBS.add(target_db)


def _accept_loaded_handoff(conn, task_id: str, model: Any) -> None:
    """D11 (A8): Empfänger-Worker quittiert das geladene A2A-Envelope.

    Der automatische Delegationspfad hatte bisher nur einen Produzenten
    (``create_handoff``) und einen HMAC-Check, aber keinen Konsumenten. Hier
    wird der autorisierte Empfänger aus dem gespeicherten (signierten)
    Envelope gelesen, die Annahme ausgeführt und das Ergebnis in
    ``task_events`` sowie im signierten Audit sichtbar gemacht.
    """
    try:
        from backend.handoff_desk import handoff_desk
        h_id = str(handoff_desk.latest_handoff_id_for_task(task_id) or "").strip()
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
            # Bevorzugt die aus dem signierten Envelope verifizierten Werte.
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
    """D11 (A8): Prompt-Ref + Korrelations-IDs nach ``mc_task_meta`` spiegeln.

    Bestehende Budget-/Trajectory-Werte bleiben erhalten (Merge, kein
    Ueberschreiben). Die Whitelist in ``mission_control.py`` wird nicht
    erweitert (fremde Datei).
    """
    if not task_id or not facts:
        return
    conn = _get_kanban_connection(maintenance=True)
    try:
        # Idempotent: dieselbe Tabelle wie mission_control._init_db (keine
        # Datenmigration, nur Select/Spiegelung).
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


def _kanban_load_task_sync(task_id: str):
    """F-055: SQLite-Punktabfrage im Worker-Thread statt im Event-Loop.

    D11/S-11.1: Das strukturierte ``created``-Event ist SSOT der Delegation;
    die ``tasks``-Zeile bleibt nur Anzeige-Kopie. Das validierte Modell wird
    unter ``_delegation_payload`` (dict) und ``_delegation_payload_model``
    mitgefuehrt und vom Worker als strukturierter Kontext an den Dispatch
    uebergeben.
    """
    conn = _get_kanban_connection(maintenance=True)
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
            model = _load_kanban_delegation_payload(raw_payload, task_id=task_id)
            if model is not None:
                task["_delegation_payload"] = model.model_dump()
                task["_delegation_payload_model"] = model
                # D11 (A8): der Empfänger-Worker quittiert das geladene
                # Envelope (Produzent → HMAC-Check → Annahme → Effekt).
                _accept_loaded_handoff(conn, task_id, model)
        return task
    finally:
        conn.close()


def _kanban_autonomy_gate_sync(task_id: str, autonomy: str) -> str:
    """F-055: Autonomie-/Freigabe-Gate im Worker-Thread. Liefert die Aktion."""
    gate = _get_kanban_connection(maintenance=True)
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
    conn = _get_kanban_connection(maintenance=True)
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
    conn = _get_kanban_connection(maintenance=True)
    try:
        now = datetime.datetime.now().isoformat()
        conn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", ("default", task_id))
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'auto_assigned_orchestrator', ?, ?)",
            (task_id, json.dumps({"assignee": "default", "reason": "Kein Profil gesetzt — automatische Zuweisung an Orchestrator"}), now),
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
    """D08/H-08-3: kompletter Terminalstatus-Persistenzblock im Worker-Thread.

    Vorher oeffnete die ``async`` Kanban-Ausfuehrung direkt im Event-Loop bis
    zu drei Mal eine SQLite-Verbindung (busy_timeout=5000) und schrieb UPDATEs
    plus task_events — ein einziger Write-Lock blockierte Dispatcher und SSE.
    Alle Pfade (Ergebnis, Exception, Cancel) laufen jetzt durch EINE Funktion
    und werden per ``asyncio.to_thread`` aufgerufen. Cas-/Cancel-Semantik und
    Event-Inhalte bleiben unveraendert.
    """
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
                    (task_id, json.dumps({"block_kind": verdict["block_kind"], "options": verdict.get("hitl_options", []), "reason": verdict.get("reason"), **facts}), now_iso),
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
                    (task_id, json.dumps({
                        **facts,
                        "status": "failed",
                        "summary": mark_truncated(reply, 200, artifact=f"tasks.result/{task_id}"),
                        "truncated": len(reply) > 200,
                        "original_length": len(reply),
                        "verified": False,
                    }), now_iso),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status = ?, completed_at = ?, result = ?, consecutive_failures = 0 WHERE id = ?",
                    (target_status, now_iso, reply, task_id),
                )
                conn.execute("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'completed', ?, ?)",
                             (task_id, json.dumps({
                                 **facts,
                                 "status": target_status,
                                 "summary": mark_truncated(reply, 200, artifact=f"tasks.result/{task_id}"),
                                 "truncated": len(reply) > 200,
                                 "original_length": len(reply),
                                 "verified": is_success,
                             }), now_iso))
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
            _sync_to_memory_bridge(task_id, title, assignee, persisted_status, reply)
    finally:
        conn.close()
    return {"mode": mode, "status": persisted_status, "task_id": task_id}


async def _execute_kanban_task_async(task_id: str):
    """CAS-gesicherter Einstieg: nur ein Worker darf einen Task ausführen.

    Ohne Lease sah der 30-s-Deadlock-Watchdog jeden laufenden Task als
    'stagnierend' und setzte ihn nach 120 s auf todo — ein zweiter Worker
    startete, während der erste noch im LLM-Call steckte (doppelte Kosten,
    doppelte E-Mails/Zahlungen). Der Lease wird hier erworben, per Heartbeat
    gehalten und im finally freigegeben.
    """
    lease_token = ""
    heartbeat_task = None
    try:
        from backend.deadlock_supervisor import deadlock_supervisor
        claim = await asyncio.to_thread(deadlock_supervisor.acquire_lease, task_id)
        if not claim.get("acquired"):
            # task_exists=False ist z.B. in isolierten Tests legitime — dort
            # ohne Lease ausfuehren, aber niemals bei aktivem fremden Claim.
            if claim.get("task_exists"):
                logger.debug(
                    "[KanbanWorker] Lease fuer '%s' nicht erworben (anderer Worker aktiv) — Skip.",
                    task_id,
                )
                return {"skipped": "lease_held", "task_id": task_id}
        else:
            lease_token = str(claim.get("lease_token") or "")

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
                            cancel_token.cancel("lease_lost")  # type: ignore[union-attr]
                            return
                    except Exception as exc:
                        # H8 (Audit 23.11.2026): ein fehlgeschlagener
                        # Lease-Renew darf NICHT unbemerkt zum Ablauf der Lease
                        # führen, während der Task weiterläuft (Doppel-Execution,
                        # doppelte LLM-Kosten). Gleicher Fail-Closed-Pfad wie
                        # in archon/core/orchestration.py.
                        logger.warning(
                            "[KanbanWorker] Heartbeat fehlgeschlagen — Task %s wird abgebrochen: %s",
                            task_id, exc,
                        )
                        cancel_token.cancel("lease_heartbeat_failed")  # type: ignore[union-attr]
                        return

            heartbeat_task = asyncio.create_task(_hb(), name=f"kanban_lease_{task_id}")
    except Exception as exc:
        # C11: Fail-Closed wie im Mission-Control-Pfad (orchestration.py:250-260).
        # Ein nicht auswertbarer Lease-Claim darf nicht heissen "kein anderer
        # Worker" — sonst fuehren zwei Worker denselben Task parallel aus.
        import os as _os
        if _os.environ.get("ARCHON_LEASE_FAIL_OPEN", "").strip().lower() in ("1", "true", "yes"):
            logger.warning(
                "[KanbanWorker] Lease-Claim fehlgeschlagen (%s) — ARCHON_LEASE_FAIL_OPEN aktiv, Ausfuehrung ohne Claim.", exc
            )
        else:
            logger.warning(
                "[KanbanWorker] Lease-Claim fehlgeschlagen (%s) — Task %s wird nicht ausgefuehrt (fail-closed).",
                exc, task_id,
            )
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


async def _execute_kanban_task_inner(task_id: str, *, lease_token: str = ""):
    """Führt eine Kanban-Aufgabe autonom über core_dispatcher aus (alter dag_scheduler entfernt)."""
    import asyncio

    import core_dispatcher
    # Abbruch (Operator-Cancel oder Lease-Verlust) muss den laufenden
    # LLM-Call wirklich stoppen (Audit 23.11.2026).
    _cancel_token = None

    def _check_cancel() -> None:
        if _cancel_token is not None:
            _cancel_token.check()

    try:
        from backend.cancellation import get_token as _get_cancel_token
        _cancel_token = _get_cancel_token(f"task:{task_id}")
        _current = asyncio.current_task()
        if _current is not None:
            _cancel_token.register_task(_current)  # type: ignore[union-attr]
        _cancel_token.check()  # type: ignore[union-attr]
    except asyncio.CancelledError as cancel_exc:
        # E: dieser Check liegt VOR dem grossen try/finally unten — ohne
        # eigenen Status-Update stuerbt der Worker als stille BaseException
        # und der Task bleibt in_progress (danach Deadlock-Rollover).
        logger.warning("[KanbanWorker] Cancel-Token vor Ausfuehrung: %s", cancel_exc)
        try:
            # D08/H-08-3: auch der Cancel-Pfad schreibt im Worker-Thread.
            await asyncio.to_thread(
                _persist_kanban_result_sync, task_id,
                mode="cancelled", reply=f"Aufgabe abgebrochen: {cancel_exc}"[:500],
            )
        except Exception as exc:
            print(f"[OperationsAPI] Cancel-Status nicht persistiert: {exc}", file=sys.stderr)
        raise
    except ImportError as cancel_import_exc:
        # D07/MED: fehlte frueher `pass` → _check_cancel() war ein No-op und der
        # kostenpflichtige Dispatch lief unabbrechbar weiter. Fail-closed:
        # Status 'blocked' persistieren und RuntimeError werfen, nie still
        # weiterlaufen lassen.
        logger.error(
            "[KanbanWorker] Cancel-Token-Modul nicht verfuegbar — Dispatch verweigert (fail-closed): %s",
            cancel_import_exc,
        )
        try:
            await asyncio.to_thread(
                _persist_kanban_result_sync, task_id,
                mode="result", target_status="blocked",
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
        return

    # G: Registrierung erst unmittelbar vor dem geschuetzten Hauptblock.
    # Vorher lag sie vor mehreren Early-Returns (dag-*/Autonomie-Gate), die
    # kein unregister_task() erreichten — der Task blieb dauerhaft "aktiv".

    # Fall 1: DAG-Epics des ALTEN 2-Tier-Schedulers — Scheduler ist entfernt (21.11.2026).
    if t_dict["id"].startswith("dag-") and not any(t_dict["id"].endswith(f"-{s}") for s in ["1", "2", "3", "4", "syn"]):
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Task {task_id} ist ein dag-*-Epic des entfernten "
            "dag_scheduler — Ausfuehrung nicht moeglich. Nachfolger: Workflow-Engine (/api/v2/workflows/templates/{id}/run).",
            file=sys.stderr,
        )
        return

    # Autonomie-Gate: der Eigentümer entscheidet, ob Operations selbst handeln dürfen.
    try:
        from backend.model_routing import autonomy_level
        _autonomy = autonomy_level("operations")
    except Exception:
        _autonomy = "approval"

    if _autonomy != "autonomous":
        # F-055: komplettes Gate im Worker-Thread — vorher blockierte dieses
        # SQLite-Bündel den Event-Loop bei jedem Kanban-Task.
        if await asyncio.to_thread(_kanban_autonomy_gate_sync, task_id, _autonomy) != "continue":
            return

    # Fall 2: Einzelaufgabe
    # Sofort als 'in_progress' markieren, damit im Kanban und UI der aktive Lauf sichtbar ist
    try:
        await asyncio.to_thread(_kanban_mark_started_sync, task_id, t_dict.get("assignee") or "")
    except Exception as exc:
        print(f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

    from backend.agent_aliases import resolve_agent_id
    raw_assignee = (t_dict.get("assignee") or "").strip()
    if not raw_assignee:
        # Kein Profil manuell zugewiesen -> automatisch an den Root-Orchestrator ('default') uebergeben
        raw_assignee = "default"
        try:
            await asyncio.to_thread(_kanban_assign_orchestrator_sync, task_id)
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
    assignee = resolve_agent_id(raw_assignee)
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title

    async def _handoff_gate_ok() -> bool:
        """F030/W3-A: harter Konsument-Gate vor jedem kostenpflichtigen Dispatch.

        ``require_accepted_handoff`` ist die SSOT: ohne akzeptierte, HMAC-
        verifizierte Uebergabe (bei vorhandener A2A-Kante) darf kein Call
        starten. Bei Gate-Fehler fail-closed, nie still weiterlaufen.
        """
        try:
            gate = await asyncio.to_thread(require_accepted_handoff, task_id, assignee)
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
            _persist_kanban_result_sync, task_id,
            mode="result", title=title, assignee=assignee,
            target_status="blocked",
            verdict={
                "block_kind": "handoff_not_accepted",
                "hitl_options": ["retry", "abort"],
                "reason": reason,
            },
            reply=f"Dispatch verweigert: {reason}"[:500],
        )
        return False

    profiles = await asyncio.to_thread(_load_profiles_map)
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
    system_prompt = prof.get("prompt") or prof.get("system_prompt") or f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."

    # D11/S-11.1: strukturierte Delegation (SSOT task_events.created) statt
    # f-String-Prosa. Der Block ist JSON und damit maschinell auswertbar.
    _delegation_model = t_dict.get("_delegation_payload_model")
    _dispatch_reasoning = "medium"
    if _delegation_model is not None:
        structured = _delegation_model.model_dump(exclude_defaults=True)
        structured.setdefault("task_id", task_id)
        structured.setdefault(
            "correlation_id", str(structured.get("correlation_id") or f"task:{task_id}")
        )
        _dispatch_reasoning = str(_delegation_model.reasoning_level or "medium")
        system_prompt = (
            f"{system_prompt}\n\n[STRUKTURIERTE_DELEGATION_JSON]\n"
            + json.dumps(structured, sort_keys=True, ensure_ascii=False)
            + "\n[/STRUKTURIERTE_DELEGATION_JSON]"
        )

    try:
        # G: Registrierung NUN innerhalb des try/finally-Blocks, der unten
        # immer unregister_task() aufruft (auch bei CancelledError/Exception).
        try:
            from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
            graceful_shutdown_coordinator.register_task(
                task_id=task_id,
                title=t_dict.get("title", task_id),
                agent_name=t_dict.get("assignee", "system"),
                total_steps=1,
                current_step=0,
                state_payload={"task_id": task_id, "status": t_dict.get("status")}
            )
        except Exception as exc:
            print(f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        proj_context = ""
        p_rel = _resolve_task_obsidian_rel(task_id)
        if p_rel:
            try:
                from pathlib import Path as _P

                from backend.post_task_pipeline import get_vault_dir
                vault = _P(get_vault_dir()).resolve()
                p_dir = vault / p_rel
                proj_context = f"\n\nPROJEKT-ORDNER IM OBSIDIAN VAULT: `{p_rel}`\n"
                end_dir = p_dir / "03_Endprodukte"
                if end_dir.is_dir():
                    files = [f.name for f in end_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
                    if files:
                        proj_context += "Bereits vorhandene Projektergebnisse in 03_Endprodukte:\n" + "\n".join(f"- {fn}" for fn in files[:12]) + "\n"
            except Exception as exc:
                print(f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        # M91: Praezedenzfall-Gedaechtnis (strikt pro Mandant/Projekt isoliert)
        precedent_block = ""
        try:
            from backend.precedent_log import (
                find_matching_precedents,
                format_precedents_for_prompt,
                resolve_task_tenant_id,
            )
            # F030/W3-A: kanonischer Mandant — die Kanban-Spalte `tenant` ist
            # SSOT, kein hartes "default" und kein Body-Feld `tenant_id`.
            _tenant_id = resolve_task_tenant_id(t_dict)
            _project_id = str(t_dict.get("project_id") or "")
            _matched_precs = await asyncio.to_thread(
                find_matching_precedents, _tenant_id, _project_id, f"{title} {body}"
            )
            precedent_block = format_precedents_for_prompt(_matched_precs)
        except Exception as exc:
            print(f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        task_prompt = f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\nTITEL: {title}\nAUFTRAG / DETAILS:\n{body}{proj_context}{precedent_block}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte."
        # F-011/F-012: Fencing + Cancel unmittelbar vor dem kostenpflichtigen
        # Dispatch. heartbeat().False beweist verlorenen Lease (fail-closed).
        _check_cancel()
        if lease_token:
            from backend.deadlock_supervisor import deadlock_supervisor as _fence
            if not await asyncio.to_thread(_fence.heartbeat, task_id, lease_token):
                if _cancel_token is not None:
                    _cancel_token.cancel("lease_lost")
                raise asyncio.CancelledError("lease_lost")
        # F030/W3-A: A2A-Handoff-Konsument mit echtem Effekt (vor dem Call).
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
            task_id=task_id
        )
        # M76: Verifizierte Kanban-Cards mit Token-Budget & Proof-Gate
        raw_reply = (res.get("content") or "").strip()
        _token_used = int(
            res.get("total_tokens")
            or res.get("tokens_used")
            or ((res.get("input_tokens") or 0) + (res.get("output_tokens") or 0))
            or 0
        )
        _sidecar_tmeta: Dict[str, Any] = {}
        try:
            _sidecar_tmeta = ((_load_kanban_meta().get("tasks") or {}).get(task_id) or {})
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
            # F-011/F-012: auch vor dem Retry-Dispatch erneut pruefen.
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
                # D13/H-13-1: zaehlerbegrenzte Wiederholung desselben Agenten,
                # kein A→B→A-Zyklus (siehe Trajectory-Engine `retry:`).
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

        # D11 (A8): verifizierte Prompt-/Korrelationsfakten aus dem Dispatcher
        # in task_events.payload UND mc_task_meta spiegeln (keine erfundenen IDs).
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

        # D14/MED: echter Cross-Modell-Verifier im REGULAEREN Abschlusspfad
        # (nicht nur im HITL-Override). Ohne bestandene Zweitpruefung kein done.
        _cross = await _cross_model_verify_task_result(
            task_id=task_id, result_text=raw_reply, primary_model=str(model or ""),
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
        # D08/H-08-3: ganzer SQLite-/Memory-Bridge-Block im Worker-Thread.
        await asyncio.to_thread(
            _persist_kanban_result_sync, task_id,
            mode="result", title=title, assignee=assignee,
            target_status=target_status, reply=reply,
            verdict=verdict, proof_facts=_proof_facts, is_success=is_success,
        )
            
        # Obsidian-Dokumentation & Projekt-Artefakte synchronisieren
        try:
            from pathlib import Path as _P

            from backend.post_task_pipeline import get_vault_dir
            vault = _P(get_vault_dir()).resolve()
            p_rel = _resolve_task_obsidian_rel(task_id)
            obs_status_label = "ABGESCHLOSSEN" if target_status == "done" else target_status.upper()
            if p_rel:
                p_dir = vault / p_rel
                end_dir = p_dir / "03_Endprodukte"
                if end_dir.is_dir():
                    matched = False
                    for f in end_dir.iterdir():
                        if task_id in f.name and f.suffix == ".md":
                            f.write_text(f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** {obs_status_label}\n\n{reply}\n", encoding="utf-8")
                            matched = True
                            break
                    if not matched:
                        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:40].strip("-")
                        (end_dir / f"{task_id}-{slug}.md").write_text(f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** {obs_status_label}\n\n{reply}\n", encoding="utf-8")
        except Exception as e_upd:
            print(f"[OperationsAPI] Could not update obsidian markdown: {e_upd}", file=sys.stderr)

        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": target_status})
                main.broadcast_event("ticker_update", {"agent": agent_name, "message": f"Aufgabe '{title[:30]}...' ({target_status}).", "time": datetime.datetime.now().strftime("%H:%M:%S")})
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
            
    except asyncio.CancelledError:
        # Abgebrochene Aufgabe darf nicht vom Deadlock-Watchdog reaktiviert
        # werden (Audit 23.11.2026). Persistenz im Worker-Thread, aber vor
        # dem `raise` abgeschlossen (kein awaiting nach dem Cancel verloren).
        try:
            await asyncio.to_thread(
                _persist_kanban_result_sync, task_id,
                mode="cancelled", reply="Aufgabe abgebrochen (Cancel oder Lease-Verlust)",
            )
        except Exception as exc:
            print(f"[OperationsAPI] Cancel-Status nicht persistiert: {exc}", file=sys.stderr)
        raise
    except Exception as ex:
        print(f"[OperationsAPI] Execution failed for {task_id}: {ex}", file=sys.stderr)
        await asyncio.to_thread(
            _persist_kanban_result_sync, task_id,
            mode="error", title=title, assignee=assignee,
            reply=f"Fehler bei Ausführung: {ex}",
        )
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": "blocked"})
        except Exception as exc:
            print(f"[OperationsAPI] WARNUNG (MEDIUM) _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)
    finally:
        try:
            from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
            graceful_shutdown_coordinator.unregister_task(task_id)
        except Exception as exc:
            print(f"[OperationsAPI] Fallback _execute_kanban_task_async: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)


async def _cross_model_verify_task_result(
    *, task_id: str, result_text: str, primary_model: str, diff_text: str = "",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """D14/MED: echter Cross-Modell-Call im regulären Abschluss-Gate.

    ``cross_model_verify_card()`` lieferte bisher nur einen Modellnamens-
    String und `passed=True` ohne Dispatch (Theater). Hier wird das Ergebnis
    zusaetzlich von einer ANDEREN Modellfamilie geprueft; bei Fehler/unklarer
    Antwort fail-closed (HITL), nie still `passed`.
    """
    from backend.kanban_verifier import cross_model_verify_card

    # Ein zu kurzes Ergebnis (z.B. reines "erledigt") bietet keine substanzielle
    # Grundlage fuer eine Zweitmeinung; hier wird der (kostenpflichtige) Call
    # ausgelassen; ueber env kann der Call explizit erzwungen werden.
    min_chars = 200
    try:
        min_chars = int(os.environ.get("ARCHON_CROSS_MODEL_VERIFY_MIN_CHARS", "200"))
    except (TypeError, ValueError):
        pass
    forced = str(os.environ.get("ARCHON_CROSS_MODEL_VERIFY", "") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not forced and len(str(result_text or "").strip()) < min_chars and not str(diff_text or "").strip():
        return {
            "passed": True, "requires_hitl": False, "block_kind": None,
            "reason": "Kein substantielles Ergebnis — kein Cross-Modell-Call noetig.",
            "verifier_model": None, "model_call": False, "skipped": True,
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
            "passed": False, "requires_hitl": True,
            "block_kind": "cross_model_unavailable_hitl",
            "reason": "Kein unabhaengiges Verifier-Modell bestimmbar (fail-closed).",
            "verifier_model": verifier_model, "model_call": False,
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
        # Der Verifier erhält denselben rollen-/delegationsgebundenen System-
        # Kontext wie der Writer, damit er das Ergebnis gegen den ursprünglichen
        # Auftrag prüfen kann (kein kontextloser Rat).
        verifier_system = (
            str(system_prompt or "").strip()
            + "\n\n[ROLLENWECHSEL] Du bist jetzt der UNABHAENGIGE Cross-Modell-Verifier "
              "einer anderen Modellfamilie. Antworte ausschliesslich mit reinem JSON "
              "{\"passed\": bool, \"reason\": str}."
        )
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="qa_test_engineer",
            agent_name="Cross-Model Verifier",
            prompt=prompt,
            role="Independent QA verifier (different model family)",
            system_prompt=verifier_system,
            model=verifier_model,
            task_id=task_id,
            # D13/H-13-1: Verifier-Call ist ein Tool-Call im selben Ticket,
            # kein Agentwechsel-Zyklus; Trajectory-Engine zaehlt ihn als Hop.
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
            "passed": False, "requires_hitl": True,
            "block_kind": "cross_model_verification_failed_hitl",
            "reason": f"Cross-Modell-Verifikation nicht abschliessbar: {exc}"[:1000],
            "verifier_model": verifier_model, "model_call": True,
        }


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
    # H-14-2/F022: der ausloesende Mensch kommt aus der Session, nicht aus dem
    # Body. Er wird als `requested_by` im Review dokumentiert.
    actor = require_session_actor(request)
    def _fetch_task_sync() -> dict:
        conn = _get_kanban_connection(maintenance=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, title, body, assignee, status, result FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Task nicht gefunden.")
            return dict(row)
        finally:
            conn.close()

    t_dict = await asyncio.to_thread(_fetch_task_sync)
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title
    from backend.agent_aliases import resolve_agent_id
    raw_assignee = (t_dict.get("assignee") or "").strip()
    if not raw_assignee:
        # Kein Profil manuell zugewiesen -> automatisch an den Root-Orchestrator ('default') uebergeben
        raw_assignee = "default"

        def _auto_assign_sync() -> None:
            try:
                c_asgn = _get_kanban_connection(maintenance=True)
                try:
                    now_asgn_iso = datetime.datetime.now().isoformat()
                    c_asgn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", (raw_assignee, task_id))
                    c_asgn.execute(
                        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'auto_assigned_orchestrator', ?, ?)",
                        (task_id, json.dumps({"assignee": raw_assignee, "reason": "Kein Profil gesetzt — automatische Zuweisung an Orchestrator"}), now_asgn_iso),
                    )
                    c_asgn.commit()
                finally:
                    c_asgn.close()
            except Exception as exc:
                print(f"[OperationsAPI] WARNUNG (MEDIUM) trigger_quality_review: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

        await asyncio.to_thread(_auto_assign_sync)
    assignee = resolve_agent_id(raw_assignee)
    result = t_dict.get("result") or ""
    now_iso = datetime.datetime.now().isoformat()

    if not result:
        raise HTTPException(status_code=400, detail="Aufgabe hat noch kein Arbeitsergebnis zur Prüfung hinterlegt.")

    # H-14-2/F022: es gibt KEINEN Body-Override mehr. `force_verdict` und
    # `reviewer_id` wurden aus dem Request-Modell entfernt. Das Verdict stammt
    # ausschliesslich aus dem Reviewer-Dispatch; eine Aufhebung von
    # `changes_requested` nur ueber den separaten, 4-Augen-gesicherten
    # Override-Endpoint (siehe unten).
    # Autonomer Reviewer-Agent (Katharina Völk für QM/Compliance oder Robert für CEO/Strategie)
    profiles = await asyncio.to_thread(_load_profiles_map)
    if assignee in ("katharina", "katharina-voelk", "katharina_voelk"):
        reviewer_id = "robert"
    else:
        reviewer_id = "katharina"

    prof = profiles.get(reviewer_id, {})
    reviewer_name = prof.get("name") or ("Katharina Völk" if reviewer_id == "katharina" else "Robert")
    reviewer_role = prof.get("category") or prof.get("role") or "Qualitäts- & Compliance-Auditor"

    audit_prompt = f"""Du bist unabhängiger Qualitätsprüfer im 4-Augen-Review-Gate von Archon OS.
Prüfe das vorgelegte Teilergebnis für die folgende Projektaufgabe unbestechlich und sachlich:

TITEL: {title}
BRIEFING / AUFGABENSTELLUNG:
{body}

BEARBEITER: {assignee}
ERGEBNIS ZUR BEWERTUNG:
{result}

PRÜF-KRITERIEN:
1. Vollständigkeit: Wurde der Auftrag vollumfänglich und ohne Auslassungen beantwortet?
2. Substanz & Evidenz: Gibt es Platzhalter, vage Floskeln oder unplausible Annahmen?
3. Handlungsfähigkeit: Enthält das Ergebnis klare, anwendbare nächste Schritte oder konkrete Resultate?

Liefere deine Bewertung AUSSCHLIESSLICH als valides JSON in exakt folgendem Schema (ohne Begleittext, ohne Markdown):
{{
    "verdict": "approved",
    "score": 88,
    "summary": "1-2 prägnante Sätze zur Qualität",
    "critique_points": ["Punkt 1", "Punkt 2"],
    "actionable_next_steps": ["Schritt 1", "Schritt 2"]
}}
(Wähle "changes_requested" als verdict, falls wesentliche Aspekte fehlen oder unvollständig sind, andernfalls "approved".)
"""
    try:
        import core_dispatcher
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=reviewer_id,
            agent_name=reviewer_name,
            prompt=audit_prompt,
            role=reviewer_role,
            system_prompt="Du bist ein strikter QM-Auditor. Gib ausschließlich reines JSON ohne Markdown-Ticks aus.",
            model="deepseek/deepseek-chat",
            task_id=task_id
        )
        content = res.get("content", "").strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            parsed = QualityReviewVerdict.model_validate(json.loads(json_match.group(0)))
        else:
            # Fail-closed (R-16): liefert der Reviewer kein JSON, darf das Gate
            # NICHT freigeben — sonst gilt ein Timeout/Prosa-Antwort als Quality-Pass.
            parsed = QualityReviewVerdict(
                verdict="changes_requested",
                score=0,
                summary="Reviewer-Antwort enthielt kein auswertbares JSON — Review gilt als nicht bestanden, Nachfassung erforderlich.",
                critique_points=["Reviewer-Lauf lieferte keine strukturierte Bewertung."],
                actionable_next_steps=["Review erneut anstoßen."],
            )
    except Exception as e:
        # Fail-closed (R-16): Fehler im Review-Dispatch darf die Freigabe nicht
        # erfinden — der Task bleibt in 'review', damit kein ungeprüftes Ergebnis
        # als done verbucht wird.
        parsed = QualityReviewVerdict(
            verdict="changes_requested",
            score=0,
            summary=f"Reviewer-Prüfung konnte nicht abgeschlossen werden ({e}).",
            critique_points=["Reviewer-Lauf fehlgeschlagen."],
            actionable_next_steps=["Review erneut anstoßen."],
        )

    verdict = parsed.verdict
    if verdict not in ("approved", "changes_requested"):
        verdict = "changes_requested"

    review_data = {
        "status": verdict,
        # H-14-2/F022: Reviewer-Identitaet stammt aus dem verifizierten Profil
        # (nicht aus dem Body); der ausloesende Mensch ist separat dokumentiert.
        "reviewer": reviewer_name,
        "reviewer_id": reviewer_id,
        "requested_by": actor,
        "score": parsed.score,
        "summary": parsed.summary,
        "critique_points": parsed.critique_points,
        "actionable_next_steps": parsed.actionable_next_steps,
        "reviewed_at": now_iso,
        "source": "reviewer_agent",
    }

    # In Sidecar-Metadaten speichern
    from backend.kanban_sidecar import update_kanban_meta
    def _apply_meta(meta):
        meta.setdefault("tasks", {})
        meta["tasks"].setdefault(task_id, {})
        meta["tasks"][task_id]["quality_review"] = review_data
        return meta
    await asyncio.to_thread(update_kanban_meta, _apply_meta)

    # In task_events und DB vermerken
    def _record_review_sync() -> None:
        c = _get_kanban_connection(maintenance=True)
        try:
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, f"quality_review_{verdict}", json.dumps(review_data), now_iso)
            )
            if verdict == "approved" and t_dict.get("status") == "review":
                c.execute("UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", (now_iso, task_id))
            elif verdict == "changes_requested":
                c.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (task_id,))
            c.commit()
        finally:
            c.close()
    await asyncio.to_thread(_record_review_sync)

    try:
        from backend.audit_log import _require_audit_event
        _require_audit_event(
            "governance", "quality_review_completed", actor,
            {
                "task_id": task_id, "verdict": verdict, "reviewer_id": reviewer_id,
                "requested_by": actor, "score": parsed.score,
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("kanban_updated", {
                "action": "quality_review",
                "task_id": task_id,
                "review": review_data
            })
            main.broadcast_event("ticker_update", {
                "agent": review_data.get("reviewer", "Reviewer"),
                "message": f"4-Augen-Review ({verdict.upper()}): {review_data.get('summary', '')[:40]}",  # type: ignore[index]
                "time": datetime.datetime.now().strftime("%H:%M:%S")
            })
    except Exception as exc:
        print(f"[OperationsAPI] Fallback trigger_quality_review: Exception im Fehler-/Fallback-Pfad: {exc}", file=sys.stderr)

    return {
        "status": "success",
        "task_id": task_id,
        "quality_review": review_data
    }


@router.post("/kanban/tasks/{task_id}/quality-review/override")
async def override_quality_review(
    request: Request, task_id: str, req: QualityReviewOverrideRequest
):
    """H-14-2/F022: einziger erlaubter Weg, `changes_requested` aufzuheben.

    Der zweite Approver kommt aus der verifizierten Session (nie aus dem Body),
    muss sich von Reviewer und Task-Ersteller unterscheiden und einen an
    ``action`` + ``resource=task_id`` gebundenen Einmal-Passkey-Proof vorlegen.
    Jede Verletzung bricht mit 403 ab, ohne Review oder Status zu veraendern.
    """
    require_admin_or_503(request)
    actor = require_session_actor(request)
    review = await asyncio.to_thread(_current_quality_review, task_id)
    if not review:
        raise HTTPException(status_code=409, detail="Kein Quality-Review vorhanden — Override nicht zulaessig.")

    created_by = await asyncio.to_thread(_task_created_by, task_id)
    old_status = await asyncio.to_thread(_task_status, task_id)
    evidence = _require_four_eyes_override(
        task_id=task_id, actor=actor, review=review, reason=req.reason,
        proof_token=req.passkey_proof_token, action="quality_review_override",
        created_by=created_by, approval_id=req.approval_id,
    )
    now_iso = datetime.datetime.now().isoformat()
    override_review: Dict[str, Any] = {
        "status": "approved",
        "reviewer": actor,
        "reviewer_id": actor,
        "requested_by": review.get("requested_by") or review.get("reviewer_id") or "",
        "score": 100,
        "summary": str(req.reason or "").strip(),
        "critique_points": [],
        "actionable_next_steps": [],
        "reviewed_at": now_iso,
        "source": "four_eyes_override",
        "four_eyes_evidence": evidence,
        "overrides": {
            "previous_status": review.get("status"),
            "previous_reviewer_id": review.get("reviewer_id"),
        },
    }
    from backend.kanban_sidecar import update_kanban_meta

    def _apply_meta(meta):
        meta.setdefault("tasks", {}).setdefault(task_id, {})["quality_review"] = override_review
        return meta

    await asyncio.to_thread(update_kanban_meta, _apply_meta)

    def _record_sync() -> None:
        c = _get_kanban_connection(maintenance=True)
        try:
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, "quality_review_override", json.dumps(override_review, ensure_ascii=False), now_iso),
            )
            c.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, "status_changed", json.dumps({
                    "from": old_status, "to": "done", "actor": actor, "force": True,
                    "reason": req.reason, "four_eyes_evidence": evidence,
                    "previous_review": review,
                }, ensure_ascii=False), now_iso),
            )
            if old_status == "review":
                c.execute(
                    "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ? AND status = 'review'",
                    (now_iso, task_id),
                )
            c.commit()
        finally:
            c.close()

    await asyncio.to_thread(_record_sync)
    return {"status": "success", "task_id": task_id, "quality_review": override_review}


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




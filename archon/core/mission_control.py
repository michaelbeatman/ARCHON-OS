"""Mission-Control-Store (SQLite-backed über kanban.db mit atomarem Adapter).

Seit v0.5.1 (Ablösung von mission_control_data.json):
- Primärer Persistenzspeicher in Produktion ist ``kanban.db`` (Tabellen ``tasks``,
  ``task_links``, ``task_events`` plus die kompakten Erweiterungstabellen
  ``mc_task_meta`` und ``mc_kv``).
- Existiert beim ersten Zugriff noch eine historische ``mission_control_data.json``,
  werden alle Einträge einmalig nach ``kanban.db`` migriert und die JSON-Datei nach
  ``mission_control_data.json.bak`` verschoben.
- Legacy-Kompatibilität für isolierte Unit-Tests: Wird ``MISSION_CONTROL_FILE``
  explizit auf eine Test-Datei umgebogen, greift für diesen Testpfad weiterhin
  der atomare Temp+fsync+os.replace-Dateimodus.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import MEMORY_DIR, WORKSPACE_DIR, logger

MISSION_CONTROL_FILE = os.path.join(MEMORY_DIR, "mission_control_data.json")
_DEFAULT_MISSION_CONTROL_FILE = MISSION_CONTROL_FILE

# Optionaler Override für gezielte SQLite-Unit-Tests
KANBAN_DB_PATH: Optional[str] = None

# Thread-Lock (RLock, verschachtelbar) und Async-Lock zur Serialisierung von RMW-Sequenzen.
_MC_DATA_LOCK = threading.RLock()
_MC_ASYNC_LOCK = asyncio.Lock()

# State-Cache für /api/mission-control/state (3s TTL)
_MC_STATE_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}

_MIGRATION_DONE = False

_EXTENDED_TASK_KEYS = (
    "plan",
    "agent_name",
    "estimated_tokens",
    "estimated_cost_eur",
    "subagents_count",
    "artifact_path",
    "parent_project_id",
    "parent_project_title",
    "parent_task_id",
    "kanban_task_id",
    "subtask_ids",
    "target_action",
    "phase",
    "active_tool",
    "created_via",
    "synthesis_started",
    "synthesis_draft_path",
    "synthesis_finalized",
    "paperclip_issue",
    "mc_status",
    "capture_input",
    "created_at_str",
    "completed_at_str",
    "result_summary",
    "started_at",
    "completed_at",
)


def _is_file_override() -> bool:
    """True, wenn Tests MISSION_CONTROL_FILE auf eine eigene Testdatei umgeleitet haben."""
    return os.path.abspath(MISSION_CONTROL_FILE) != os.path.abspath(_DEFAULT_MISSION_CONTROL_FILE)


def _resolve_kanban_db_path() -> str:
    """Ermittelt den autoritativen Pfad zu kanban.db."""
    if KANBAN_DB_PATH:
        return KANBAN_DB_PATH
    env_override = os.environ.get("ARCHON_MC_KANBAN_DB", "").strip()
    if env_override:
        return env_override
    try:
        import backend.operations_api as ops_api

        ops_path = getattr(ops_api, "KANBAN_DB_PATH", None)
        if ops_path and os.path.exists(ops_path):
            return ops_path
    except Exception:
        pass
    for candidate in (
        "/opt/data/kanban.db",
        os.path.join(OPT_DATA_DIR, "kanban.db"),
        os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
        os.path.expanduser("~/.hermes/kanban.db"),
    ):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(WORKSPACE_DIR, "data", "kanban.db")


_KANBAN_PRAGMA_INITIALIZED: set[str] = set()


class _ClosingKanbanConnection(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _connect_kanban(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = os.path.abspath(db_path or _resolve_kanban_db_path())
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0, factory=_ClosingKanbanConnection)
    conn.execute("PRAGMA busy_timeout=10000;")
    if path not in _KANBAN_PRAGMA_INITIALIZED:
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            _KANBAN_PRAGMA_INITIALIZED.add(path)
        except Exception:
            pass
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_mc_tables(conn: sqlite3.Connection) -> None:
    """Stellt sicher, dass Kern- und MC-Erweiterungstabellen in kanban.db existieren."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            assignee TEXT,
            status TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            created_by TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            project_id TEXT,
            result TEXT,
            model_override TEXT
        );
        CREATE TABLE IF NOT EXISTS task_links (
            parent_id TEXT NOT NULL,
            child_id TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS mc_task_meta (
            task_id TEXT PRIMARY KEY,
            meta_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mc_kv (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mc_events_kind ON task_events(kind, id);
        """
    )


def _mc_status_to_db(mc_status: Optional[str]) -> str:
    s = (mc_status or "").strip().lower()
    if s in ("completed", "done", "finished"):
        return "done"
    if s in ("in_progress", "running", "active"):
        return "in_progress"
    if s in ("approval", "waiting_approval", "review", "gate"):
        return "review"
    if s in ("failed", "blocked"):
        return "blocked"
    if s == "archived":
        return "archived"
    if s == "ready":
        return "ready"
    return "todo"


def _db_status_to_mc(db_status: Optional[str], meta_mc_status: Optional[str] = None) -> str:
    s = (db_status or "").strip().lower()
    m = (meta_mc_status or "").strip().lower()
    if s in ("done", "completed", "finished", "archived"):
        return "completed"
    if s == "in_progress":
        return "active" if m == "active" else "in_progress"
    if s in ("review", "waiting_approval", "approval", "gate"):
        return "approval"
    if s in ("blocked", "failed"):
        return "failed"
    return "backlog"


def _parse_epoch(value: Any, fallback: Optional[int] = None) -> int:
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip():
        s = value.strip()
        try:
            return int(float(s))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return int(datetime.datetime.strptime(s[:19], fmt).timestamp())
            except ValueError:
                continue
        try:
            return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return fallback if fallback is not None else int(time.time())


def _format_created_str(epoch_val: Any, stored_str: Optional[str] = None) -> str:
    if stored_str:
        return str(stored_str)
    try:
        if isinstance(epoch_val, (int, float)) and epoch_val > 0:
            return datetime.datetime.fromtimestamp(float(epoch_val)).strftime("%Y-%m-%d %H:%M")
        if isinstance(epoch_val, str) and epoch_val.strip():
            return epoch_val.strip()[:16]
    except Exception:
        pass
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _extract_meta_payload(task: Dict[str, Any]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for k in _EXTENDED_TASK_KEYS:
        if k in task and task[k] is not None:
            meta[k] = task[k]
    if task.get("status"):
        meta["mc_status"] = task["status"]
    if isinstance(task.get("created_at"), str):
        meta["created_at_str"] = task["created_at"]
    if isinstance(task.get("completed_at"), str):
        meta["completed_at_str"] = task["completed_at"]
    return meta


def _upsert_task_in_conn(conn: sqlite3.Connection, task: Dict[str, Any], *, overwrite: bool = True) -> None:
    tid = str(task.get("id") or "").strip()
    if not tid:
        return
    title = str(task.get("title") or tid)
    body = task.get("capture_input") if task.get("capture_input") is not None else task.get("body") or ""
    assignee = task.get("agent_id") if task.get("agent_id") is not None else task.get("assignee")
    db_status = _mc_status_to_db(task.get("status"))
    created_epoch = _parse_epoch(task.get("created_at"))
    started_val = task.get("started_at")
    if isinstance(started_val, str):
        started_val = _parse_epoch(started_val, None)
    completed_val = task.get("completed_at")
    if isinstance(completed_val, str):
        completed_val = _parse_epoch(completed_val, None)
    project_id = task.get("parent_project_id") or task.get("parent_task_id") or task.get("project_id")
    if project_id == tid:
        project_id = None
    result_text = task.get("result_summary") if task.get("result_summary") is not None else task.get("result")
    model_val = task.get("model") if task.get("model") is not None else task.get("model_override")
    created_by = task.get("created_by") or task.get("created_via") or "mission_control"

    if overwrite:
        conn.execute(
            """
            INSERT INTO tasks (
                id, title, body, assignee, status, priority, created_by,
                created_at, started_at, completed_at, project_id, result, model_override
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                body = COALESCE(NULLIF(excluded.body, ''), tasks.body),
                assignee = COALESCE(excluded.assignee, tasks.assignee),
                status = excluded.status,
                started_at = COALESCE(excluded.started_at, tasks.started_at),
                completed_at = COALESCE(excluded.completed_at, tasks.completed_at),
                project_id = COALESCE(excluded.project_id, tasks.project_id),
                result = COALESCE(NULLIF(excluded.result, ''), tasks.result),
                model_override = COALESCE(excluded.model_override, tasks.model_override)
            """,
            (
                tid,
                title,
                str(body or ""),
                assignee,
                db_status,
                int(task.get("priority") or 0),
                created_by,
                created_epoch,
                started_val,
                completed_val,
                project_id,
                result_text,
                model_val,
            ),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO tasks (
                id, title, body, assignee, status, priority, created_by,
                created_at, started_at, completed_at, project_id, result, model_override
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                title,
                str(body or ""),
                assignee,
                db_status,
                int(task.get("priority") or 0),
                created_by,
                created_epoch,
                started_val,
                completed_val,
                project_id,
                result_text,
                model_val,
            ),
        )

    meta = _extract_meta_payload(task)
    meta_json = json.dumps(meta, ensure_ascii=False)
    now_ts = time.time()
    if overwrite:
        conn.execute(
            """
            INSERT INTO mc_task_meta (task_id, meta_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                meta_json = excluded.meta_json,
                updated_at = excluded.updated_at
            """,
            (tid, meta_json, now_ts),
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO mc_task_meta (task_id, meta_json, updated_at) VALUES (?, ?, ?)",
            (tid, meta_json, now_ts),
        )

    if project_id:
        conn.execute(
            "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
            (str(project_id), tid),
        )
    for sub_id in task.get("subtask_ids") or []:
        if sub_id and str(sub_id) != tid:
            conn.execute(
                "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
                (tid, str(sub_id)),
            )


def migrate_mission_control_json_to_sqlite(json_path: Optional[str] = None, *, backup: bool = True) -> int:
    """Migriert bestehende Einträge aus mission_control_data.json einmalig nach kanban.db."""
    global _MIGRATION_DONE
    src = json_path or _DEFAULT_MISSION_CONTROL_FILE
    if not os.path.exists(src):
        _MIGRATION_DONE = True
        return 0

    with _MC_DATA_LOCK:
        if not os.path.exists(src):
            _MIGRATION_DONE = True
            return 0
        try:
            with open(src, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.warning(f"[MissionControl] Migration: konnte {src} nicht lesen: {e}")
            return 0

        if not isinstance(raw, dict):
            raw = {}

        tasks = raw.get("tasks") if isinstance(raw.get("tasks"), list) else []
        audit_logs = raw.get("audit_logs") if isinstance(raw.get("audit_logs"), list) else []
        migrated_count = 0

        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_mc_tables(conn)
            for t in tasks:
                if isinstance(t, dict) and t.get("id"):
                    _upsert_task_in_conn(conn, t, overwrite=False)
                    migrated_count += 1
            for entry in reversed(audit_logs):
                if isinstance(entry, dict):
                    conn.execute(
                        "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, NULL, 'mc_audit', ?, ?)",
                        ("_system", json.dumps(entry, ensure_ascii=False), int(time.time())),
                    )
            for k, v in raw.items():
                if k not in ("tasks", "audit_logs", "source"):
                    conn.execute(
                        "INSERT OR IGNORE INTO mc_kv (key, value_json, updated_at) VALUES (?, ?, ?)",
                        (str(k), json.dumps(v, ensure_ascii=False), time.time()),
                    )
            conn.commit()
        finally:
            conn.close()

        if backup:
            bak_path = f"{src}.bak"
            try:
                os.replace(src, bak_path)
                logger.info(f"[MissionControl] {migrated_count} Task(s) nach kanban.db migriert; JSON archiviert -> {bak_path}")
            except Exception as mv_err:
                logger.warning(f"[MissionControl] Konnte {src} nicht nach {bak_path} verschieben: {mv_err}")

        _MIGRATION_DONE = True
        return migrated_count


def _maybe_auto_migrate() -> None:
    if _is_file_override():
        return
    if not _MIGRATION_DONE or os.path.exists(_DEFAULT_MISSION_CONTROL_FILE):
        migrate_mission_control_json_to_sqlite(_DEFAULT_MISSION_CONTROL_FILE, backup=True)


def _load_sqlite_state_from_conn(conn: sqlite3.Connection) -> Dict[str, Any]:
    _ensure_mc_tables(conn)

    link_rows = conn.execute("SELECT parent_id, child_id FROM task_links").fetchall()
    children_map: Dict[str, List[str]] = {}
    parent_map: Dict[str, str] = {}
    for lr in link_rows:
        p_id = str(lr["parent_id"])
        c_id = str(lr["child_id"])
        children_map.setdefault(p_id, []).append(c_id)
        parent_map.setdefault(c_id, p_id)

    rows = conn.execute(
        """
        SELECT t.id, t.title, t.body, t.assignee, t.status, t.priority, t.created_by,
               t.created_at, t.started_at, t.completed_at, t.project_id, t.result,
               t.model_override, m.meta_json
        FROM tasks t
        LEFT JOIN mc_task_meta m ON m.task_id = t.id
        WHERE LOWER(COALESCE(t.status, '')) != 'archived'
        ORDER BY t.created_at DESC
        """
    ).fetchall()

    tasks: List[Dict[str, Any]] = []
    for r in rows:
        tid = r["id"]
        meta: Dict[str, Any] = {}
        if r["meta_json"]:
            try:
                parsed = json.loads(r["meta_json"])
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                pass

        mc_status = _db_status_to_mc(r["status"], meta.get("mc_status"))
        agent_id = r["assignee"] or "system"
        agent_name = meta.get("agent_name") or agent_id or "System Agent"
        parent_pid = r["project_id"] or meta.get("parent_project_id") or meta.get("parent_task_id") or parent_map.get(tid)
        if parent_pid == tid:
            parent_pid = None

        sub_ids: List[str] = []
        for sid in (meta.get("subtask_ids") or []) + children_map.get(tid, []):
            if sid and sid not in sub_ids and sid != tid:
                sub_ids.append(sid)

        task_dict: Dict[str, Any] = {
            "id": tid,
            "title": r["title"] or tid,
            "capture_input": meta.get("capture_input") if meta.get("capture_input") is not None else (r["body"] or ""),
            "plan": meta.get("plan") if isinstance(meta.get("plan"), list) else ["Autonomer Task aus kanban.db"],
            "agent_id": agent_id,
            "agent_name": agent_name,
            "model": r["model_override"] or "omniroute/best-free",
            "estimated_tokens": meta.get("estimated_tokens", 15000),
            "estimated_cost_eur": meta.get("estimated_cost_eur", 0.0),
            "subagents_count": meta.get("subagents_count", max(1, len(sub_ids))),
            "status": mc_status,
            "created_at": _format_created_str(r["created_at"], meta.get("created_at_str")),
            "result_summary": r["result"] if r["result"] is not None else meta.get("result_summary", ""),
            "artifact_path": meta.get("artifact_path", ""),
            "parent_project_id": parent_pid,
            "subtask_ids": sub_ids,
            "target_action": meta.get("target_action", "none"),
            "phase": meta.get("phase", "execution"),
        }
        for opt_k in (
            "parent_project_title",
            "parent_task_id",
            "kanban_task_id",
            "active_tool",
            "created_via",
            "synthesis_started",
            "synthesis_draft_path",
            "synthesis_finalized",
            "paperclip_issue",
        ):
            if opt_k in meta and meta[opt_k] is not None:
                task_dict[opt_k] = meta[opt_k]
        if r["started_at"] is not None:
            task_dict["started_at"] = r["started_at"]
        elif meta.get("started_at") is not None:
            task_dict["started_at"] = meta["started_at"]
        if meta.get("completed_at_str"):
            task_dict["completed_at"] = meta["completed_at_str"]
        elif r["completed_at"] is not None:
            task_dict["completed_at"] = r["completed_at"]

        tasks.append(task_dict)

    ev_rows = conn.execute(
        "SELECT payload, created_at FROM task_events WHERE kind = 'mc_audit' ORDER BY id DESC LIMIT 25"
    ).fetchall()
    audit_logs: List[Dict[str, Any]] = []
    for er in ev_rows:
        try:
            item = json.loads(er["payload"] or "{}")
            if isinstance(item, dict):
                audit_logs.append(item)
        except Exception:
            pass

    state: Dict[str, Any] = {
        "tasks": tasks,
        "metrics": {
            "tpm_current": 0,
            "tpm_limit": 0,
            "cost_today_usd": 0.0,
            "cost_limit_usd": 0.0,
        },
        "audit_logs": audit_logs,
        "source": "kanban.db",
    }

    kv_rows = conn.execute("SELECT key, value_json FROM mc_kv").fetchall()
    for kv in kv_rows:
        try:
            state[kv["key"]] = json.loads(kv["value_json"])
        except Exception:
            pass

    return state


def _save_sqlite_state_to_conn(
    conn: sqlite3.Connection,
    data: Dict[str, Any],
    *,
    previous_ids: Optional[set] = None,
    previous_audit_sigs: Optional[set] = None,
) -> None:
    _ensure_mc_tables(conn)
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    new_ids = {str(t.get("id")) for t in tasks if isinstance(t, dict) and t.get("id")}

    if previous_ids is not None:
        removed_ids = previous_ids - new_ids
        for rid in removed_ids:
            conn.execute("DELETE FROM tasks WHERE id = ?", (rid,))
            conn.execute("DELETE FROM mc_task_meta WHERE task_id = ?", (rid,))
            conn.execute("DELETE FROM task_links WHERE parent_id = ? OR child_id = ?", (rid, rid))

    for t in tasks:
        if isinstance(t, dict) and t.get("id"):
            _upsert_task_in_conn(conn, t, overwrite=True)

    # Neue audit_logs in task_events schreiben (listen sind newest-first)
    audit_logs = data.get("audit_logs") if isinstance(data.get("audit_logs"), list) else []
    seen_sigs = previous_audit_sigs if previous_audit_sigs is not None else set()
    new_entries: List[Dict[str, Any]] = []
    for entry in audit_logs:
        if not isinstance(entry, dict):
            continue
        sig = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        if sig in seen_sigs:
            if previous_audit_sigs is not None:
                break
            continue
        new_entries.append(entry)
    for entry in reversed(new_entries):
        conn.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, NULL, 'mc_audit', ?, ?)",
            ("_system", json.dumps(entry, ensure_ascii=False), int(time.time())),
        )

    for k, v in data.items():
        if k not in ("tasks", "audit_logs", "source"):
            conn.execute(
                """
                INSERT INTO mc_kv (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (str(k), json.dumps(v, ensure_ascii=False), time.time()),
            )


def mc_load_state_from_sqlite() -> Dict[str, Any]:
    """Lädt den vollständigen Mission-Control-State direkt aus kanban.db."""
    _maybe_auto_migrate()
    conn = _connect_kanban()
    try:
        return _load_sqlite_state_from_conn(conn)
    finally:
        conn.close()


def mc_get_task_sqlite(task_id: str) -> Optional[Dict[str, Any]]:
    """Lädt einen einzelnen Task samt Erweiterungs-Metadaten direkt aus kanban.db."""
    if not task_id:
        return None
    if _is_file_override():
        data = _load_mission_control_data()
        return next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
    state = mc_load_state_from_sqlite()
    return next((t for t in state.get("tasks", []) if str(t.get("id")) == str(task_id)), None)


def mc_append_audit_sqlite(
    source: str,
    msg: str,
    task_id: str = "_system",
    time_str: Optional[str] = None,
) -> None:
    """Schreibt einen Mission-Control-Audit-Eintrag direkt nach kanban.db (task_events)."""
    entry = {
        "time": time_str or datetime.datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "msg": msg,
    }
    if _is_file_override():
        def _mut(d: dict) -> None:
            d.setdefault("audit_logs", []).insert(0, entry)
            d["audit_logs"] = d["audit_logs"][:25]
        update_mission_control_data(_mut)
        return

    _maybe_auto_migrate()
    with _MC_DATA_LOCK:
        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_mc_tables(conn)
            conn.execute(
                "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, NULL, 'mc_audit', ?, ?)",
                (task_id or "_system", json.dumps(entry, ensure_ascii=False), int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()


def mc_capture_task_sqlite(
    new_task: Dict[str, Any],
    audit_entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Legt einen neuen Task samt optionalem Audit-Eintrag atomar in kanban.db an."""
    if _is_file_override():
        def _mut(d: dict) -> dict:
            d.setdefault("tasks", []).insert(0, new_task)
            if audit_entry:
                d.setdefault("audit_logs", []).insert(0, audit_entry)
                d["audit_logs"] = d["audit_logs"][:25]
            return new_task
        return update_mission_control_data(_mut)

    _maybe_auto_migrate()
    with _MC_DATA_LOCK:
        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_mc_tables(conn)
            _upsert_task_in_conn(conn, new_task, overwrite=True)
            if audit_entry:
                conn.execute(
                    "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, NULL, 'mc_audit', ?, ?)",
                    (str(new_task.get("id") or "_system"), json.dumps(audit_entry, ensure_ascii=False), int(time.time())),
                )
            conn.commit()
        finally:
            conn.close()
    _MC_STATE_CACHE["ts"] = 0.0
    return new_task


def mc_update_task_sqlite(
    task_id: str,
    updates: Dict[str, Any],
    audit_entry: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Aktualisiert gezielt Felder eines Tasks in kanban.db."""
    if _is_file_override():
        def _mut(d: dict) -> Optional[dict]:
            t = next((x for x in d.get("tasks", []) if x.get("id") == task_id), None)
            if not t:
                return None
            t.update(updates)
            if audit_entry:
                d.setdefault("audit_logs", []).insert(0, audit_entry)
                d["audit_logs"] = d["audit_logs"][:25]
            return t
        return update_mission_control_data(_mut)

    _maybe_auto_migrate()
    with _MC_DATA_LOCK:
        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            state = _load_sqlite_state_from_conn(conn)
            t = next((x for x in state.get("tasks", []) if str(x.get("id")) == str(task_id)), None)
            if t is None:
                conn.rollback()
                return None
            t.update(updates)
            _upsert_task_in_conn(conn, t, overwrite=True)
            if audit_entry:
                conn.execute(
                    "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, NULL, 'mc_audit', ?, ?)",
                    (str(task_id), json.dumps(audit_entry, ensure_ascii=False), int(time.time())),
                )
            conn.commit()
            return t
        finally:
            conn.close()


def mc_link_subtask_sqlite(
    parent_id: str,
    child_id: str,
    *,
    parent_defaults: Optional[Dict[str, Any]] = None,
    child_updates: Optional[Dict[str, Any]] = None,
) -> str:
    """Verknüpft Parent und Child über task_links + project_id direkt in kanban.db."""
    if _is_file_override():
        def _mut(d: dict) -> str:
            tasks = d.setdefault("tasks", [])
            parent = next((x for x in tasks if x.get("id") == parent_id), None)
            if parent is None and parent_defaults:
                parent = dict(parent_defaults)
                parent["id"] = parent_id
                tasks.append(parent)
            p_title = str((parent or {}).get("title") or (parent_defaults or {}).get("title") or parent_id)
            child = next((x for x in tasks if x.get("id") == child_id), None)
            if child is not None:
                child["parent_project_id"] = parent_id
                child["parent_project_title"] = p_title
                if child_updates:
                    child.update(child_updates)
            elif child_updates:
                new_c = dict(child_updates)
                new_c.setdefault("id", child_id)
                new_c["parent_project_id"] = parent_id
                new_c["parent_project_title"] = p_title
                tasks.append(new_c)
            return p_title
        return update_mission_control_data(_mut)

    _maybe_auto_migrate()
    with _MC_DATA_LOCK:
        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_mc_tables(conn)
            p_row = conn.execute("SELECT id, title FROM tasks WHERE id = ?", (parent_id,)).fetchone()
            if p_row is None:
                p_doc = dict(parent_defaults or {})
                p_doc["id"] = parent_id
                p_doc.setdefault("title", f"Delegationsprojekt {parent_id}")
                p_doc.setdefault("status", "active")
                p_doc.setdefault("phase", "in_progress")
                p_doc.setdefault("created_via", "delegation_bridge")
                _upsert_task_in_conn(conn, p_doc, overwrite=True)
                p_title = str(p_doc["title"])
            else:
                p_title = str(p_row["title"] or parent_id)

            if child_id:
                conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (parent_id, child_id))
                conn.execute(
                    "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
                    (parent_id, child_id),
                )
                c_meta_row = conn.execute(
                    "SELECT meta_json FROM mc_task_meta WHERE task_id = ?", (child_id,)
                ).fetchone()
                c_meta: Dict[str, Any] = {}
                if c_meta_row and c_meta_row["meta_json"]:
                    try:
                        c_meta = json.loads(c_meta_row["meta_json"]) or {}
                    except Exception:
                        c_meta = {}
                c_meta["parent_project_id"] = parent_id
                c_meta["parent_project_title"] = p_title
                c_meta["kanban_task_id"] = child_id
                if child_updates:
                    for k, v in child_updates.items():
                        if v is not None:
                            c_meta[k] = v
                conn.execute(
                    """
                    INSERT INTO mc_task_meta (task_id, meta_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET meta_json = excluded.meta_json, updated_at = excluded.updated_at
                    """,
                    (child_id, json.dumps(c_meta, ensure_ascii=False), time.time()),
                )
            conn.commit()
            return p_title
        finally:
            conn.close()


def mc_get_parent_context_sqlite(task_id: str) -> tuple[Optional[str], Optional[str]]:
    """Liefert (parent_project_id, parent_project_title) zu einem Child-Task aus kanban.db."""
    if _is_file_override():
        mc = _load_mission_control_data()
        for t in mc.get("tasks", []):
            if t.get("id") == task_id or t.get("kanban_task_id") == task_id:
                return t.get("parent_project_id"), t.get("parent_project_title")
        return None, None

    _maybe_auto_migrate()
    conn = _connect_kanban()
    try:
        _ensure_mc_tables(conn)
        row = conn.execute(
            """
            SELECT t.project_id, l.parent_id, m.meta_json
            FROM tasks t
            LEFT JOIN task_links l ON l.child_id = t.id
            LEFT JOIN mc_task_meta m ON m.task_id = t.id
            WHERE t.id = ?
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if not row:
            return None, None
        meta: Dict[str, Any] = {}
        if row["meta_json"]:
            try:
                meta = json.loads(row["meta_json"]) or {}
            except Exception:
                meta = {}
        parent_id = row["project_id"] or row["parent_id"] or meta.get("parent_project_id")
        parent_title = meta.get("parent_project_title")
        if parent_id and not parent_title:
            pr = conn.execute("SELECT title FROM tasks WHERE id = ?", (parent_id,)).fetchone()
            if pr:
                parent_title = pr["title"]
        return parent_id, parent_title
    finally:
        conn.close()


def _write_mc_atomic(data: dict):
    """Atomarer MC-Store-Write.

    In Produktion schreibt diese Funktion direkt nach ``kanban.db``; nur wenn
    Tests ``MISSION_CONTROL_FILE`` explizit umleiten, nutzt sie atomares
    Temp-Datei + fsync + os.replace auf die Test-JSON-Datei.
    """
    with _MC_DATA_LOCK:
        if not _is_file_override():
            conn = _connect_kanban()
            try:
                conn.execute("BEGIN IMMEDIATE")
                _save_sqlite_state_to_conn(conn, data)
                conn.commit()
            finally:
                conn.close()
            _MC_STATE_CACHE["ts"] = 0.0
            return

        _dir = os.path.dirname(os.path.abspath(MISSION_CONTROL_FILE)) or "."
        os.makedirs(_dir, exist_ok=True)
        _fd, _tmp = tempfile.mkstemp(dir=_dir, prefix=".mission_control_", suffix=".tmp")
        try:
            with os.fdopen(_fd, "w", encoding="utf-8") as _f:
                json.dump(data, _f, indent=2, ensure_ascii=False)
                _f.flush()
                os.fsync(_f.fileno())
            os.replace(_tmp, MISSION_CONTROL_FILE)
        except BaseException:
            try:
                os.unlink(_tmp)
            except OSError:
                pass
            raise


def _load_mission_control_data() -> dict:
    """Lädt den Mission-Control-State (kanban.db in Produktion; JSON nur bei Test-Override)."""
    if not _is_file_override():
        try:
            return mc_load_state_from_sqlite()
        except Exception as e:
            logger.warning(f"[MissionControl] Fehler beim Laden aus kanban.db: {e}")

    if os.path.exists(MISSION_CONTROL_FILE):
        try:
            with open(MISSION_CONTROL_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("tasks"), list):
                    return d
        except Exception as e:
            print(f"Error loading mission_control_data: {e}")

    # Test-Fallback ohne Store: keine erfundenen Telemetriewerte (Z-08)
    return {
        "tasks": [],
        "metrics": {
            "tpm_current": 0,
            "tpm_limit": 0,
            "cost_today_usd": 0.0,
            "cost_limit_usd": 0.0,
        },
        "audit_logs": [],
        "source": "fallback_no_store",
    }


_ORIG_WRITE_MC = _write_mc_atomic
_ORIG_LOAD_MC = _load_mission_control_data


def _save_mission_control_data(data: dict):
    """Schreibt den Store. Serialisiert gegen alle anderen Schreiber."""
    try:
        _write_mc_atomic(data)
    except Exception as e:
        logger.error(f"[MissionControl] Speichern fehlgeschlagen: {e}", exc_info=True)


def update_mission_control_data(mutator):
    """Atomares Read-Modify-Write unter EINEM Lock (kanban.db BEGIN IMMEDIATE bzw. Test-JSON)."""
    with _MC_DATA_LOCK:
        if _is_file_override() or _load_mission_control_data is not _ORIG_LOAD_MC or _write_mc_atomic is not _ORIG_WRITE_MC:
            data = _load_mission_control_data()
            result = mutator(data)
            _write_mc_atomic(data)
            return result

        _maybe_auto_migrate()
        conn = _connect_kanban()
        try:
            conn.execute("BEGIN IMMEDIATE")
            data = _load_sqlite_state_from_conn(conn)
            before_ids = {
                str(t.get("id")) for t in data.get("tasks", [])
                if isinstance(t, dict) and t.get("id")
            }
            before_audit_sigs = {
                json.dumps(x, sort_keys=True, ensure_ascii=False)
                for x in (data.get("audit_logs") or [])
                if isinstance(x, dict)
            }
            result = mutator(data)
            _save_sqlite_state_to_conn(
                conn,
                data,
                previous_ids=before_ids,
                previous_audit_sigs=before_audit_sigs,
            )
            conn.commit()
        finally:
            conn.close()
        _MC_STATE_CACHE["ts"] = 0.0
        return result


__all__ = [
    "MISSION_CONTROL_FILE",
    "KANBAN_DB_PATH",
    "_MC_DATA_LOCK",
    "_MC_ASYNC_LOCK",
    "_write_mc_atomic",
    "_load_mission_control_data",
    "_save_mission_control_data",
    "update_mission_control_data",
    "migrate_mission_control_json_to_sqlite",
    "mc_load_state_from_sqlite",
    "mc_get_task_sqlite",
    "mc_capture_task_sqlite",
    "mc_update_task_sqlite",
    "mc_link_subtask_sqlite",
    "mc_get_parent_context_sqlite",
    "mc_append_audit_sqlite",
    "_MC_STATE_CACHE",
]

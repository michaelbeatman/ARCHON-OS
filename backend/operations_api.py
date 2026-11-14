"""
Operations API Router for Archon OS
Provides Kanban (Hermes kanban.db), Org-Chart, and Inter-Agent Communication Feed.
"""

import os
import base64

from backend.platform_paths import HERMES_HOME
import asyncio
import sys
import json
import re
import sqlite3
import datetime
import subprocess
import time
import secrets
from typing import List, Dict, Optional, Any
from fastapi import APIRouter, Request, HTTPException, Query, Body, UploadFile, File

from archon.routers._rbac import require_admin_or_503
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/operations", tags=["operations"])

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


_DEFAULT_KANBAN_DB_PATH = _resolve_kanban_db_path()
KANBAN_DB_PATH = _DEFAULT_KANBAN_DB_PATH


_KANBAN_JOURNAL_INIT = False
_KANBAN_JOURNAL_INIT_DBS: set = set()


def _get_active_kanban_db_path(company_id: Optional[str] = None) -> str:
    if KANBAN_DB_PATH != _DEFAULT_KANBAN_DB_PATH:
        return KANBAN_DB_PATH
    try:
        from backend.tenant_context import tenant_context
        resolved = tenant_context.resolve_active_db("kanban.db", company_id)
        if resolved:
            return resolved
    except Exception:
        pass
    return KANBAN_DB_PATH


def _get_kanban_connection(company_id: Optional[str] = None):
    global _KANBAN_JOURNAL_INIT
    target_db = _get_active_kanban_db_path(company_id)
    if not os.path.exists(target_db):
        raise HTTPException(status_code=503, detail=f"kanban.db nicht gefunden unter {target_db}")
    conn = sqlite3.connect(target_db, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    if (not _KANBAN_JOURNAL_INIT) or (target_db not in _KANBAN_JOURNAL_INIT_DBS):
        try:
            if str(target_db).replace("\\", "/").startswith("/opt/data"):
                conn.execute("PRAGMA journal_mode=DELETE;")
            else:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            # Auto-Crash-Recovery (Pillar 2): Tasks die länger als 6 Stunden (21600s) in 'in_progress' hängen, auf 'todo' zurücksetzen
            import time as _time
            cutoff_ts = _time.time() - 21600
            cutoff_iso = datetime.datetime.fromtimestamp(cutoff_ts).isoformat()
            conn.execute("""
                UPDATE tasks
                SET status = 'todo', started_at = NULL
                WHERE status = 'in_progress'
                  AND (
                    (CAST(started_at AS REAL) >= 1000000000 AND CAST(started_at AS REAL) < ?)
                    OR (started_at IS NOT NULL AND started_at LIKE '____-__-__%' AND started_at < ?)
                    OR (started_at IS NULL AND created_at IS NOT NULL AND created_at < ?)
                  )
            """, (cutoff_ts, cutoff_iso, cutoff_iso))
            conn.commit()
        except Exception:
            pass
        _KANBAN_JOURNAL_INIT = True
        _KANBAN_JOURNAL_INIT_DBS.add(target_db)
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
    except (TypeError, ValueError):
        pass
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _sync_to_memory_bridge(task_id: str, title: Optional[str], assignee: Optional[str], status: str, result: Optional[str] = None):
    """Synchronisiert Kanban-Aufgaben mit der zentralen agentic_memory.db (tasks-Tabelle)."""
    try:
        from local_memory_bridge import LocalMemoryBridge
        obsidian_rel = None
        try:
            meta = _load_kanban_meta()
            obsidian_rel = ((meta.get("tasks") or {}).get(task_id) or {}).get("obsidian")
        except Exception:
            pass
        LocalMemoryBridge().sync_task(
            task_id=task_id,
            title=title or task_id,
            role=assignee or "unassigned",
            status=status,
            result=result,
            obsidian_note=obsidian_rel
        )
    except Exception as e:
        print(f"[OperationsAPI] MemoryBridge task sync notice: {e}", file=sys.stderr)


_PROFILES_MAP_CACHE = {"mtime": 0.0, "data": {}}

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


def _enrich_task(task_dict: Dict, profiles: Dict, meta: Dict) -> Dict:
    assignee_id = task_dict.get("assignee")
    prof = profiles.get(assignee_id, {})
    task_dict["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
    task_dict["assignee_role"] = prof.get("category") or prof.get("role") or "Spezialist"
    task_dict["assignee_avatar"] = prof.get("avatar") or _get_fallback_avatar(assignee_id or "")
    tmeta = (meta.get("tasks") or {}).get(task_dict.get("id")) or {}
    task_dict["due_date"] = tmeta.get("due") or None
    task_dict["tags"] = tmeta.get("tags") or []
    # 2d (12.10.2026): Projektordner + Entscheidungs-Kontext auch LISTEN-seitig,
    # damit die Card das Entscheidungs-Banner und die Projektzeile zeigen kann
    # (der Detail-Dialog liefert weiterhin den vollen Block).
    task_dict["obsidian"] = _resolve_task_obsidian_rel(task_dict.get("id"), meta)
    task_dict["tokens"] = tmeta.get("tokens") or None
    task_dict["cost"] = tmeta.get("cost") or None
    task_dict["quality_review"] = tmeta.get("quality_review") or None
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
    team_id: Optional[str] = None


class TaskStatusUpdateRequest(BaseModel):
    status: str
    result: Optional[str] = None
    # 12.10.2026 (Decision-Service): "decision" = Aufruf kam vom zentralen
    # Entscheidungs-Endpoint -> dann KEIN zusaetzlicher Telegram-Ping (der
    # Service bestaetigt selbst), sonst Doppelnachricht.
    source: Optional[str] = None
    force: Optional[bool] = False


class QualityReviewRequest(BaseModel):
    reviewer_id: Optional[str] = None
    force_verdict: Optional[str] = None  # "approved" | "changes_requested"
    comment: Optional[str] = None


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
                   (SELECT count(*) FROM task_links l WHERE l.parent_id = tasks.id) AS subtask_count,
                   (SELECT count(*) FROM task_links l WHERE l.child_id = tasks.id) AS parent_count
            FROM tasks
    """
    try:
        cursor = conn.cursor()
        if archived:
            cursor.execute(base_select + " WHERE status = 'archived' ORDER BY completed_at DESC")
            tasks = [_enrich_task(dict(r), profiles, meta) for r in cursor.fetchall()]
            return {"status": "success", "archived": True, "tasks": tasks, "total": len(tasks)}

        cursor.execute(base_select + " ORDER BY priority DESC, created_at DESC")
        rows = cursor.fetchall()

        columns = {
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
            _enrich_task(task_dict, profiles, meta)
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


@router.post("/kanban/tasks")
def create_kanban_task(req: TaskCreateRequest):
    """Erstellt eine neue Aufgabe im Hermes Kanban über CLI-Execution oder direkten Insert."""
    conn = _get_kanban_connection()
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
                team_name = team_match["name"]
                if not target_assignee:
                    target_assignee = team_match["lead_id"]
                    
        # Optionales Team-Präfix im Body
        task_body = req.body or ""
        if team_name and f"[Team: {team_name}]" not in task_body:
            task_body = f"[Team: {team_name}]\n{task_body}".strip()
            
        cursor.execute("""
            INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, model_override, provider_override)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            req.title,
            task_body,
            target_assignee,
            target_status,
            req.priority or 0,
            "Archon-User",
            now_iso,
            req.model_override,
            req.provider_override
        ))
        
        # Log event
        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "created", json.dumps({"title": req.title, "assignee": target_assignee, "team": req.team_id, "status": target_status}), now_iso))
        
        conn.commit()
        _sync_to_memory_bridge(task_id, req.title, target_assignee, target_status)
        
        # Falls Decompose angefordert wurde und Hermes Container läuft:
        if req.decompose:
            try:
                from utils.docker_client import docker_cli_host_args
                # -H <Socket>: `docker exec` ist Klasse C und bleibt am Socket; ohne die
                # Bindung folgt die CLI dem globalen DOCKER_HOST (siehe docker_cli_host_args).
                subprocess.Popen(["docker", *docker_cli_host_args(),
                                  "exec", "hermes", "hermes", "kanban", "decompose", task_id])
            except Exception as e:
                print(f"[OperationsAPI] Decompose trigger error: {e}", file=sys.stderr)
        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "created", "task_id": task_id, "status": target_status})
        except Exception:
            pass

        return {"status": "success", "task_id": task_id, "title": req.title, "assigned_to": target_assignee, "team": req.team_id}
    finally:
        conn.close()


async def _execute_kanban_task_async(task_id: str):
    """Führt eine Kanban-Aufgabe autonom über core_dispatcher oder dag_scheduler aus."""
    import core_dispatcher
    conn = _get_kanban_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title, body, assignee, status, model_override, provider_override, task_type, block_kind FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return
        t_dict = dict(row)
    finally:
        conn.close()

    # Task beim GracefulShutdownCoordinator registrieren (M-14)
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
    except Exception:
        pass

    # Fall 1: Ist es ein DAG Epic?
    if t_dict["id"].startswith("dag-") and not any(t_dict["id"].endswith(f"-{s}") for s in ["1", "2", "3", "4", "syn"]):
            try:
                from backend.dag_scheduler import dag_scheduler_instance
                await dag_scheduler_instance.execute_dag(task_id)
                return
            except Exception as e:
                print(f"[OperationsAPI] DAG Execution error for {task_id}: {e}", file=sys.stderr)

    # Autonomie-Gate: der Eigentümer entscheidet, ob Operations selbst handeln dürfen.
    try:
        from backend.model_routing import autonomy_level
        _autonomy = autonomy_level("operations")
    except Exception:
        _autonomy = "approval"

    if _autonomy != "autonomous":
        _gate = _get_kanban_connection()
        try:
            _now = datetime.datetime.now().isoformat()
            _row = _gate.execute("SELECT block_kind FROM tasks WHERE id = ?", (task_id,)).fetchone()
            _block_kind = _row["block_kind"] if _row is not None and hasattr(_row, "keys") else (_row[0] if _row else None)
            if _autonomy == "manual":
                _gate.execute("UPDATE tasks SET status = 'todo' WHERE id = ?", (task_id,))
                _gate.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'autonomy_manual', ?, ?)",
                    (task_id, json.dumps({"level": "manual", "reason": "Nur Vorschlag — Ausführung gesperrt"}), _now),
                )
                _gate.commit()
                print(f"[Autonomy] Task {task_id} nicht gestartet (manual).")
                return
            if _block_kind != "approval_granted":
                _gate.execute("UPDATE tasks SET status = 'blocked', block_kind = 'approval' WHERE id = ?", (task_id,))
                _gate.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'awaiting_approval', ?, ?)",
                    (task_id, json.dumps({"level": "approval", "reason": "Freigabe erforderlich"}), _now),
                )
                # Hermes-Kanban-Protokoll: ein 'blocked'-Event macht die Sperre "sticky",
                # sonst hebt promote_ready_tasks den Task wieder auf 'ready'.
                _gate.execute(
                    "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'blocked', ?, ?)",
                    (task_id, json.dumps({"reason": "approval_required"}), _now),
                )
                _gate.commit()
                print(f"[Autonomy] Task {task_id} wartet auf Freigabe.")
                return
            # Freigabe erteilt: Marker löschen und weiterlaufen
            _gate.execute("UPDATE tasks SET block_kind = NULL WHERE id = ?", (task_id,))
            _gate.commit()
        finally:
            _gate.close()

    # Fall 2: Einzelaufgabe
    # Sofort als 'in_progress' markieren, damit im Kanban und UI der aktive Lauf sichtbar ist
    try:
        c_start = _get_kanban_connection()
        now_start_iso = datetime.datetime.now().isoformat()
        c_start.execute("UPDATE tasks SET status = 'in_progress', started_at = ? WHERE id = ?", (now_start_iso, task_id))
        c_start.execute("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'started', ?, ?)", 
                        (task_id, json.dumps({"status": "in_progress", "agent": t_dict.get("assignee")}), now_start_iso))
        c_start.commit()
        c_start.close()
    except Exception:
        pass

    from backend.agent_aliases import resolve_agent_id
    assignee = resolve_agent_id(t_dict.get("assignee") or "hermes-researcher")
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title
    model = (t_dict.get("model_override") or "").strip()
    provider_override = (t_dict.get("provider_override") or "").strip()
    if not model:
        try:
            from backend.model_routing import is_enabled, resolve, classify_task
            if is_enabled():
                _task_type = (t_dict.get("task_type") or "").strip() or classify_task(f"{title} {body}")
                _route = resolve(_task_type)
                if _route:
                    model = _route["model"]
                    provider_override = provider_override or _route["provider"]
                    print(f"[ModelRouting] Task {task_id}: '{_task_type}' -> {model} ({provider_override})")
        except Exception as _mr_err:
            print(f"[ModelRouting] Fallback auf Profilmodell: {_mr_err}")
    model = model or "deepseek/deepseek-chat"

    profiles = _load_profiles_map()
    prof = profiles.get(assignee, {})
    agent_name = prof.get("name") or assignee
    role = prof.get("category") or prof.get("role") or "Fach-Spezialist"
    system_prompt = prof.get("prompt") or prof.get("system_prompt") or f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."

    try:
        proj_context = ""
        p_rel = _resolve_task_obsidian_rel(task_id)
        if p_rel:
            try:
                from backend.post_task_pipeline import get_vault_dir
                from pathlib import Path as _P
                vault = _P(get_vault_dir()).resolve()
                p_dir = vault / p_rel
                proj_context = f"\n\nPROJEKT-ORDNER IM OBSIDIAN VAULT: `{p_rel}`\n"
                end_dir = p_dir / "03_Endprodukte"
                if end_dir.is_dir():
                    files = [f.name for f in end_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
                    if files:
                        proj_context += "Bereits vorhandene Projektergebnisse in 03_Endprodukte:\n" + "\n".join(f"- {fn}" for fn in files[:12]) + "\n"
            except Exception:
                pass

        task_prompt = f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\nTITEL: {title}\nAUFTRAG / DETAILS:\n{body}{proj_context}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte."
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=assignee,
            agent_name=agent_name,
            prompt=task_prompt,
            role=role,
            system_prompt=system_prompt,
            model=model,
            provider=provider_override,
            task_id=task_id
        )
        is_success = res.get("status") == "success" and not (res.get("content") or "").startswith("[FEHLER:")
        target_status = "done" if is_success else "failed"
        reply = res.get("content", "").strip() or f"Aufgabe '{title}' erfolgreich von {agent_name} abgeschlossen."
        now_iso = datetime.datetime.now().isoformat()
        
        c = _get_kanban_connection()
        try:
            c.execute("UPDATE tasks SET status = ?, completed_at = ?, result = ? WHERE id = ?", (target_status, now_iso, reply, task_id))
            c.execute("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'completed', ?, ?)", 
                      (task_id, json.dumps({"status": target_status, "summary": reply[:200]}), now_iso))
            c.commit()
            _sync_to_memory_bridge(task_id, title, assignee, target_status, reply)
        finally:
            c.close()
            
        # Obsidian-Dokumentation & Projekt-Artefakte synchronisieren
        try:
            from backend.post_task_pipeline import get_vault_dir
            from pathlib import Path as _P
            vault = _P(get_vault_dir()).resolve()
            p_rel = _resolve_task_obsidian_rel(task_id)
            if p_rel:
                p_dir = vault / p_rel
                end_dir = p_dir / "03_Endprodukte"
                if end_dir.is_dir():
                    matched = False
                    for f in end_dir.iterdir():
                        if task_id in f.name and f.suffix == ".md":
                            f.write_text(f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** REVIEW\n\n{reply}\n", encoding="utf-8")
                            matched = True
                            break
                    if not matched:
                        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:40].strip("-")
                        (end_dir / f"{task_id}-{slug}.md").write_text(f"# {title}\n\n**Task:** `{task_id}` | **Ziel-Agent:** `@{assignee}` | **Status:** REVIEW\n\n{reply}\n", encoding="utf-8")
        except Exception as e_upd:
            print(f"[OperationsAPI] Could not update obsidian markdown: {e_upd}", file=sys.stderr)

        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": "review"})
                main.broadcast_event("ticker_update", {"agent": agent_name, "message": f"Aufgabe '{title[:30]}...' fertiggestellt & zur Prüfung abgelegt.", "time": datetime.datetime.now().strftime("%H:%M:%S")})
        except Exception:
            pass
            
    except Exception as ex:
        print(f"[OperationsAPI] Execution failed for {task_id}: {ex}", file=sys.stderr)
        now_iso = datetime.datetime.now().isoformat()
        c = _get_kanban_connection()
        try:
            c.execute("UPDATE tasks SET status = 'blocked', result = ? WHERE id = ?", (f"Fehler bei Ausführung: {ex}", task_id))
            c.commit()
            _sync_to_memory_bridge(task_id, title, assignee, "blocked", f"Fehler: {ex}")
        finally:
            c.close()
        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": "in_progress", "to": "blocked"})
        except Exception:
            pass
    finally:
        try:
            from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
            graceful_shutdown_coordinator.unregister_task(task_id)
        except Exception:
            pass


@router.patch("/kanban/tasks/{task_id}/status")
async def update_task_status(task_id: str, req: TaskStatusUpdateRequest):
    """Verschiebt eine Aufgabe in eine neue Spalte / Status und startet ggf. Ausführung."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()

        cursor.execute("SELECT id, title, assignee, status FROM tasks WHERE id = ?", (task_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")

        old_status = existing["status"]
        new_status = req.status.lower()

        # 4-Augen Qualitäts-Gate Prüfung: Wenn Task auf 'done' verschoben werden soll,
        # prüfen ob ein Review mit 'changes_requested' vorliegt (es sei denn, force=True)
        if new_status == "done" and not req.force:
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
        """, (new_status, new_status, new_status, now_iso, new_status, now_iso, req.result, task_id))

        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "status_changed", json.dumps({"from": old_status, "to": new_status}), now_iso))

        conn.commit()
        _sync_to_memory_bridge(task_id, existing["title"], existing["assignee"], new_status, req.result)

        # Autonome LLM-Ausführung starten, wenn Task auf 'in_progress' oder von 'review'/'failed'/'blocked' auf 'todo' gesetzt wurde
        if new_status == "in_progress" and old_status != "in_progress":
            asyncio.create_task(_execute_kanban_task_async(task_id))
        elif new_status == "todo" and old_status in ("review", "failed", "blocked", "done"):
            asyncio.create_task(_execute_kanban_task_async(task_id))

        # 12.10.2026 (Decision-Service, Richtung Kanban -> Telegram): Wird ein
        # Entscheidungs-Task (Sidecar-Block 'decision') ueber die Oberflaeche
        # verschoben, informiert der Owner-Kanal. NICHT beim Aufruf durch den
        # Decision-Service (source == 'decision') - der bestaetigt selbst.
        if old_status == "review" and new_status != "review" and (req.source or "") != "decision":
            try:
                _dm = _load_kanban_meta().get("tasks", {}).get(task_id, {}).get("decision")
                if _dm:
                    from telegram_notify import send_telegram_message
                    _verb = ("\u2705 freigegeben" if new_status in ("todo", "in_progress", "done")
                             else "\u26d4 abgelehnt/verworfen")
                    send_telegram_message(
                        f"{_verb} \u2014 {_dm.get('titel') or task_id}\n"
                        f"(im Kanban verschoben: review \u2192 {new_status})")
            except Exception as _tg_err:
                print(f"[OperationsAPI] Telegram-Benachrichtigung fehlgeschlagen: {_tg_err}", file=sys.stderr)

        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {"action": "status_changed", "task_id": task_id, "from": old_status, "to": new_status})
        except Exception:
            pass

        return {"status": "success", "task_id": task_id, "old_status": old_status, "new_status": new_status}
    finally:
        conn.close()


# In-Memory Store für 10-Minuten Undo-Transaktionen (t-c2b384)
_KANBAN_UNDO_STORE: Dict[str, Dict[str, Any]] = {}

class KanbanBulkActionRequest(BaseModel):
    task_ids: List[str]
    action: str  # "move", "assign", "tag", "delete"
    payload: Dict[str, Any] = {}

class KanbanBulkUndoRequest(BaseModel):
    undo_token: str

@router.post("/kanban/bulk")
def api_kanban_bulk_action(req: KanbanBulkActionRequest):
    """Führt eine Mehrfachaktion auf ausgewählten Kanban-Tasks aus mit 10-Minuten-Undo-Puffer (t-c2b384)."""
    task_ids = [tid.strip() for tid in req.task_ids if tid and tid.strip()]
    if not task_ids:
        raise HTTPException(status_code=400, detail="Keine Aufgaben übergeben.")

    action = req.action.lower()
    if action not in ("move", "assign", "tag", "delete"):
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")

    conn = _get_kanban_connection()
    now_iso = datetime.datetime.now().isoformat()
    now_ts = time.time()
    undo_token = f"undo_{secrets.token_hex(8)}"

    try:
        cursor = conn.cursor()
        # 1. Schnappschuss der betroffenen Tasks sichern
        placeholders = ",".join("?" for _ in task_ids)
        cursor.execute(f"SELECT id, title, assignee, status FROM tasks WHERE id IN ({placeholders})", task_ids)
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Keine passenden Aufgaben gefunden.")

        meta = _load_kanban_meta()
        snapshot = []
        for r in rows:
            tid = r["id"]
            t_tags = list((meta.get("tasks", {}).get(tid, {})).get("tags", []))
            snapshot.append({
                "id": tid,
                "title": r["title"],
                "status": r["status"],
                "assignee": r["assignee"],
                "tags": t_tags
            })

        # 2. Aktion anwenden
        if action == "move":
            target_status = (req.payload.get("status") or "todo").lower()
            completed_at = now_iso if target_status == "done" else None
            started_at = now_iso if target_status == "in_progress" else None
            cursor.execute(f"""
                UPDATE tasks
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE id IN ({placeholders})
            """, [target_status, started_at, completed_at] + task_ids)

            for s in snapshot:
                cursor.execute("""
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                """, (s["id"], "bulk_status_changed", json.dumps({"from": s["status"], "to": target_status}), now_iso))
                _sync_to_memory_bridge(s["id"], s["title"], s["assignee"], target_status)

        elif action == "assign":
            target_assignee = req.payload.get("assignee")
            cursor.execute(f"""
                UPDATE tasks
                SET assignee = ?
                WHERE id IN ({placeholders})
            """, [target_assignee] + task_ids)

            for s in snapshot:
                cursor.execute("""
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                """, (s["id"], "bulk_assignee_changed", json.dumps({"from": s["assignee"], "to": target_assignee}), now_iso))
                _sync_to_memory_bridge(s["id"], s["title"], target_assignee, s["status"])

        elif action == "tag":
            tag_name = req.payload.get("tag", "").strip()
            mode = req.payload.get("tag_mode", "add")  # "add" oder "remove"
            if tag_name:
                from backend.kanban_sidecar import update_kanban_meta
                def _apply_tags(cur_meta):
                    for tid in task_ids:
                        cur_meta.setdefault("tasks", {}).setdefault(tid, {})
                        cur_tags = set(cur_meta["tasks"][tid].get("tags") or [])
                        if mode == "add":
                            cur_tags.add(tag_name)
                        elif mode == "remove":
                            cur_tags.discard(tag_name)
                        cur_meta["tasks"][tid]["tags"] = list(cur_tags)
                    return cur_meta
                update_kanban_meta(_apply_tags)

        elif action == "delete":
            # Soft-Delete über 'archived' Status, damit GoBD-konform und 100% undo-fähig
            cursor.execute(f"""
                UPDATE tasks
                SET status = 'archived'
                WHERE id IN ({placeholders})
            """, task_ids)

            for s in snapshot:
                cursor.execute("""
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                """, (s["id"], "bulk_archived", json.dumps({"from": s["status"]}), now_iso))

        conn.commit()
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="kanban",
                action=f"bulk_{action}",
                agent_id="operator",
                payload={"task_ids": task_ids, "action": action, "payload": req.payload, "affected_count": len(task_ids)}
            )
        except Exception:
            pass

        # 3. Snapshot im Undo-Puffer speichern (10 Minuten TTL)
        _KANBAN_UNDO_STORE[undo_token] = {
            "snapshot": snapshot,
            "action": action,
            "created_at": now_ts,
            "expires_at": now_ts + 600.0  # 10 Minuten
        }

        # Abgelaufene Einträge bereinigen
        for tok in list(_KANBAN_UNDO_STORE.keys()):
            if _KANBAN_UNDO_STORE[tok]["expires_at"] < now_ts:
                _KANBAN_UNDO_STORE.pop(tok, None)

        # Broadcast WebSocket Event
        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {
                    "action": f"bulk_{action}",
                    "count": len(task_ids),
                    "task_ids": task_ids
                })
        except Exception:
            pass

        return {
            "status": "success",
            "action": action,
            "affected_count": len(task_ids),
            "undo_token": undo_token,
            "expires_in_seconds": 600
        }
    finally:
        conn.close()


@router.post("/kanban/bulk/undo")
def api_kanban_bulk_undo(req: KanbanBulkUndoRequest):
    """Macht eine Mehrfachaktion innerhalb des 10-Minuten-Zeitfensters rückgängig (t-c2b384)."""
    token = req.undo_token.strip()
    entry = _KANBAN_UNDO_STORE.get(token)
    if not entry:
        raise HTTPException(status_code=404, detail="Undo-Transaktion nicht gefunden oder bereits abgelaufen.")

    now_ts = time.time()
    if now_ts > entry["expires_at"]:
        _KANBAN_UNDO_STORE.pop(token, None)
        raise HTTPException(status_code=400, detail="Das 10-Minuten-Zeitfenster für diese Aktion ist abgelaufen.")

    snapshot = entry.get("snapshot") or []
    conn = _get_kanban_connection()
    now_iso = datetime.datetime.now().isoformat()
    try:
        cursor = conn.cursor()
        for item in snapshot:
            tid = item["id"]
            cursor.execute("""
                UPDATE tasks
                SET status = ?, assignee = ?
                WHERE id = ?
            """, (item["status"], item["assignee"], tid))
            cursor.execute("""
                INSERT INTO task_events (task_id, kind, payload, created_at)
                VALUES (?, ?, ?, ?)
            """, (tid, "bulk_undo_restored", json.dumps({"restored_status": item["status"]}), now_iso))
            _sync_to_memory_bridge(tid, item["title"], item["assignee"], item["status"])

        conn.commit()

        # Tags im Sidecar wiederherstellen
        from backend.kanban_sidecar import update_kanban_meta
        def _restore_tags(cur_meta):
            for item in snapshot:
                tid = item["id"]
                cur_meta.setdefault("tasks", {}).setdefault(tid, {})
                cur_meta["tasks"][tid]["tags"] = item["tags"]
            return cur_meta
        update_kanban_meta(_restore_tags)

        # Transaktion verbraucht
        _KANBAN_UNDO_STORE.pop(token, None)
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="kanban",
                action="bulk_undo",
                agent_id="operator",
                payload={"undo_token": token, "restored_count": len(snapshot)}
            )
        except Exception:
            pass

        # Broadcast
        try:
            import main
            if hasattr(main, "broadcast_event"):
                main.broadcast_event("kanban_updated", {
                    "action": "bulk_undone",
                    "count": len(snapshot)
                })
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"{len(snapshot)} Aufgaben wurden auf ihren vorherigen Stand zurückgesetzt.",
            "restored_count": len(snapshot)
        }
    finally:
        conn.close()


@router.post("/kanban/tasks/{task_id}/approve")
def approve_kanban_task(task_id: str):
    """Erteilt die Autonomie-Freigabe (approval) und startet die Aufgabe."""
    conn = _get_kanban_connection()
    try:
        row = conn.execute("SELECT id, status, block_kind FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")
        now_iso = datetime.datetime.now().isoformat()
        conn.execute("UPDATE tasks SET status = 'todo', block_kind = 'approval_granted' WHERE id = ?", (task_id,))
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'approved', ?, ?)",
            (task_id, json.dumps({"by": "owner", "previous_status": row["status"] if hasattr(row, "keys") else row[1]}), now_iso),
        )
        # Sticky-Sperre aufheben (Hermes-Protokoll: 'unblocked' muss das letzte Block-Event sein)
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'unblocked', ?, ?)",
            (task_id, json.dumps({"by": "owner", "reason": "approval_granted"}), now_iso),
        )
        conn.commit()
    finally:
        conn.close()
    asyncio.create_task(_execute_kanban_task_async(task_id))
    return {"status": "success", "task_id": task_id, "message": "Freigegeben und gestartet."}


@router.post("/kanban/tasks/{task_id}/quality-review")
async def trigger_quality_review(task_id: str, req: QualityReviewRequest = Body(default=QualityReviewRequest())):
    """
    Führt ein 4-Augen-Qualitätsreview für einen Kanban-Task durch.
    Ein unabhängiger Reviewer-Agent (Standard: Katharina Völk bzw. Robert bei Eigenarbeiten)
    prüft das Arbeitsergebnis objektiv gegen den ursprünglichen Auftrag.
    """
    conn = _get_kanban_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title, body, assignee, status, result FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")
        t_dict = dict(row)
    finally:
        conn.close()

    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title
    from backend.agent_aliases import resolve_agent_id
    assignee = resolve_agent_id(t_dict.get("assignee") or "hermes-researcher")
    result = t_dict.get("result") or ""
    now_iso = datetime.datetime.now().isoformat()

    if not result:
        raise HTTPException(status_code=400, detail="Aufgabe hat noch kein Arbeitsergebnis zur Prüfung hinterlegt.")

    # 1. Human-in-the-Loop Override
    if req.force_verdict in ("approved", "changes_requested"):
        verdict = req.force_verdict
        score = 100 if verdict == "approved" else 45
        summary = req.comment or ("Manuelle Freigabe durch den Operator." if verdict == "approved" else "Manuelle Nachbesserungsforderung durch den Operator.")
        review_data = {
            "status": verdict,
            "reviewer": "Operator (Human-in-the-Loop)",
            "reviewer_id": "operator",
            "score": score,
            "summary": summary,
            "critique_points": [req.comment] if req.comment else [],
            "actionable_next_steps": [],
            "reviewed_at": now_iso
        }
    else:
        # 2. Autonomer Reviewer-Agent (Katharina Völk für QM/Compliance oder Robert für CEO/Strategie)
        profiles = _load_profiles_map()
        reviewer_id = req.reviewer_id
        if not reviewer_id:
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
                parsed = json.loads(json_match.group(0))
            else:
                # Fail-closed (R-16): liefert der Reviewer kein JSON, darf das Gate
                # NICHT freigeben — sonst gilt ein Timeout/Prosa-Antwort als Quality-Pass.
                parsed = {
                    "verdict": "changes_requested",
                    "score": 0,
                    "summary": "Reviewer-Antwort enthielt kein auswertbares JSON — Review gilt als nicht bestanden, Nachfassung erforderlich.",
                    "critique_points": ["Reviewer-Lauf lieferte keine strukturierte Bewertung."],
                    "actionable_next_steps": ["Review erneut anstoßen."]
                }
        except Exception as e:
            # Fail-closed (R-16): Fehler im Review-Dispatch darf die Freigabe nicht
            # erfinden — der Task bleibt in 'review', damit kein ungeprüftes Ergebnis
            # als done verbucht wird.
            parsed = {
                "verdict": "changes_requested",
                "score": 0,
                "summary": f"Reviewer-Prüfung konnte nicht abgeschlossen werden ({e}).",
                "critique_points": ["Reviewer-Lauf fehlgeschlagen."],
                "actionable_next_steps": ["Review erneut anstoßen."]
            }

        verdict = parsed.get("verdict", "changes_requested")
        if verdict not in ("approved", "changes_requested"):
            verdict = "changes_requested"

        review_data = {
            "status": verdict,
            "reviewer": reviewer_name,
            "reviewer_id": reviewer_id,
            "score": parsed.get("score", 80),
            "summary": parsed.get("summary", ""),
            "critique_points": parsed.get("critique_points", []),
            "actionable_next_steps": parsed.get("actionable_next_steps", []),
            "reviewed_at": now_iso
        }

    # In Sidecar-Metadaten speichern
    from backend.kanban_sidecar import update_kanban_meta
    def _apply_meta(meta):
        meta.setdefault("tasks", {})
        meta["tasks"].setdefault(task_id, {})
        meta["tasks"][task_id]["quality_review"] = review_data
        return meta
    update_kanban_meta(_apply_meta)

    # In task_events und DB vermerken
    c = _get_kanban_connection()
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

    try:
        import main
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("kanban_updated", {
                "action": "quality_review",
                "task_id": task_id,
                "review": review_data
            })
            main.broadcast_event("ticker_update", {
                "agent": review_data.get("reviewer", "Reviewer"),
                "message": f"4-Augen-Review ({verdict.upper()}): {review_data.get('summary', '')[:40]}",
                "time": datetime.datetime.now().strftime("%H:%M:%S")
            })
    except Exception:
        pass

    return {
        "status": "success",
        "task_id": task_id,
        "quality_review": review_data
    }


@router.post("/kanban/reset-zombies")
def reset_zombie_kanban_tasks(payload: dict = Body(default={})):
    """Setzt hängengebliebene 'in_progress' Tasks (optional gefiltert nach assignee oder Alter) auf 'todo' zurück."""
    conn = _get_kanban_connection()
    try:
        assignee = (payload.get("assignee") or "").strip()
        task_id = (payload.get("task_id") or "").strip()
        target_status = (payload.get("target_status") or "todo").strip().lower()
        if target_status not in ("todo", "blocked", "review", "done"):
            target_status = "todo"
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
            import main
            if hasattr(main, "broadcast_event") and reset_ids:
                main.broadcast_event("kanban_updated", {"action": "zombie_reset", "task_ids": reset_ids, "to": target_status})
        except Exception:
            pass

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

class KanbanPaletteUpdate(BaseModel):
    columns: Optional[Dict[str, Dict[str, str]]] = None
    reset: bool = False

def _resolve_task_obsidian_rel(task_id: str, meta: Optional[dict] = None, auto_heal: bool = False) -> Optional[str]:
    """Ermittelt den relativen Obsidian-Projektordner fuer eine Task mit automatischer Reparatur/Fallback."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    if meta is None:
        meta = _load_kanban_meta()
    t_entry = (meta.get("tasks") or {}).get(task_id) or {}
    rel = t_entry.get("obsidian")
    vault = _P(get_vault_dir()).resolve()
    if rel and str(rel).strip():
        cand = (vault / str(rel).strip()).resolve()
        if str(cand).startswith(str(vault)) and cand.is_dir():
            return str(rel).strip()

    # Fallback 1: Pruefe ob in decision ein dossier liegt
    dossier = (t_entry.get("decision") or {}).get("dossier") or ""
    if "01_PROJEKTE/" in dossier:
        try:
            sub = dossier.split("01_PROJEKTE/")[1].split("/")[0]
            cand = (vault / "01_PROJEKTE" / sub).resolve()
            if str(cand).startswith(str(vault)) and cand.is_dir():
                rel = f"01_PROJEKTE/{sub}"
        except Exception:
            pass

    # Fallback 1b: Falls Subtask, erbe Projekt vom Parent aus task_links
    if not rel:
        try:
            conn = _get_kanban_connection()
            try:
                r_parent = conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)).fetchone()
                parent_id = r_parent[0] if r_parent else None
            finally:
                conn.close()
            if parent_id and parent_id != task_id:
                parent_rel = _resolve_task_obsidian_rel(parent_id, meta)
                if parent_rel:
                    return parent_rel
        except Exception:
            pass

    # Fallback 2: Pruefe kanban.db nach project_id
    if not rel:
        try:
            conn = _get_kanban_connection()
            try:
                r = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                pid = r[0] if r else None
            finally:
                conn.close()
            if pid and (vault / "01_PROJEKTE").is_dir():
                for d in (vault / "01_PROJEKTE").iterdir():
                    if d.is_dir() and pid in d.name:
                        rel = f"01_PROJEKTE/{d.name}"
                        break
        except Exception:
            pass

    # Fallback 3: Pruefe ob Ordner mit task_id in 01_PROJEKTE existiert
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            for d in (vault / "01_PROJEKTE").iterdir():
                if d.is_dir() and task_id in d.name:
                    rel = f"01_PROJEKTE/{d.name}"
                    break
        except Exception:
            pass

    # Fallback 4: Durchsuche 01_PROJEKTE nach Dateien mit task_id (in 03_Endprodukte oder 01_Zwischenberichte)
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            for p_dir in (vault / "01_PROJEKTE").iterdir():
                if not p_dir.is_dir():
                    continue
                for sub in ("03_Endprodukte", "01_Zwischenberichte"):
                    s_dir = p_dir / sub
                    if s_dir.is_dir():
                        for f in s_dir.iterdir():
                            if task_id in f.name:
                                rel = f"01_PROJEKTE/{p_dir.name}"
                                break
                    if rel:
                        break
                if rel:
                    break
        except Exception:
            pass

    # Fallback 5: Titel/Body Keyword-Match gegen Ordnernamen in 01_PROJEKTE
    if not rel and (vault / "01_PROJEKTE").is_dir():
        try:
            conn = _get_kanban_connection()
            try:
                r_tb = conn.execute("SELECT title, body FROM tasks WHERE id = ?", (task_id,)).fetchone()
                t_title = (r_tb[0] or "") if r_tb else ""
                t_body = (r_tb[1] or "") if r_tb else ""
            finally:
                conn.close()
            combined = (t_title + " " + t_body).lower()
            for p_dir in (vault / "01_PROJEKTE").iterdir():
                if not p_dir.is_dir():
                    continue
                p_slug = p_dir.name.lower()
                for part in p_slug.split("-"):
                    if len(part) >= 4 and part in combined and part not in ("projekt", "delegationsprojekt", "2026"):
                        rel = f"01_PROJEKTE/{p_dir.name}"
                        break
                if rel:
                    break
        except Exception:
            pass

    # In-Memory Cache im uebergebenen meta-Dict aktualisieren (vermeidet N-fache Lookups)
    if rel and meta is not None:
        try:
            meta.setdefault("tasks", {}).setdefault(task_id, {})["obsidian"] = rel
        except Exception:
            pass

    # P-03: Nur bei explizitem auto_heal=True (z.B. Task-Mutation) Sidecar-fsync ausfuehren
    if rel and auto_heal:
        try:
            from backend.kanban_sidecar import update_kanban_meta
            def _heal(m):
                m.setdefault("tasks", {}).setdefault(task_id, {})["obsidian"] = rel
            update_kanban_meta(_heal)
        except Exception:
            pass

    return rel



def _get_agent_cadre_map():
    """Liest Agenten-Klarnamen und Rollen aus config/org_hierarchy.json."""
    import json
    from pathlib import Path
    mapping = {}
    cfg = Path("config/org_hierarchy.json")
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                nid = node.get("id")
                if not nid:
                    continue
                p_name = (node.get("person_name") or "").strip()
                r_name = (node.get("name") or node.get("role") or "").strip()
                short_role = r_name.split("(")[0].strip() if r_name else ""
                display = f"{p_name}, {short_role}" if p_name and short_role and p_name != short_role else (p_name or short_role or nid)
                mapping[nid] = {
                    "id": nid,
                    "person_name": p_name or nid,
                    "role": short_role,
                    "display": display
                }
        except Exception:
            pass
    return mapping


@router.get("/projects/overview")
def get_projects_overview():
    """Liefert die konsolidierte Projekt-Zentrale fuer Operations:
    Laufende, abgeschlossene und geplante Projekte mit Unteraufgaben, Status und Direktlinks zu HTML-Berichten."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    import datetime

    vault = _P(get_vault_dir()).resolve()
    p_root = vault / "01_PROJEKTE"
    cadre_map = _get_agent_cadre_map()

    # 1. Hole alle Tasks aus kanban.db gruppiert nach project_id
    tasks_by_project = {}
    conn = _get_kanban_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title, assignee, status, priority, created_at, completed_at, result, project_id FROM tasks ORDER BY rowid ASC")
        for r in cur.fetchall():
            tid, title, assignee, status, prio, cat, comp, res, pid = r
            if not pid:
                continue
            tasks_by_project.setdefault(pid, []).append({
                "id": tid,
                "title": title,
                "assignee": assignee,
                "status": status,
                "created_at": cat,
                "completed_at": comp,
                "result_preview": (res or "")[:200]
            })
    finally:
        conn.close()

    # 2. Scanne Obsidian 01_PROJEKTE
    projects = []
    seen_ids = set()

    if p_root.is_dir():
        for p_dir in sorted(p_root.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
            if not p_dir.is_dir() or p_dir.name.startswith((".", "_")):
                continue

            folder_name = p_dir.name
            proj_title = folder_name
            status = "in_progress"
            lead_agent = "executive_decision_architect"
            assignees = set()
            primary_doc = None
            has_html = False

            p_md = p_dir / "PROJEKT.md"
            if p_md.is_file():
                try:
                    txt = p_md.read_text(encoding="utf-8")
                    for line in txt.splitlines():
                        if line.startswith("title:"):
                            proj_title = line.replace("title:", "").strip().strip('"').strip("'")
                        elif line.startswith("# ") and proj_title == folder_name:
                            proj_title = line.replace("# ", "").replace("📂 Projekt:", "").strip()
                        elif line.startswith("status:"):
                            st_val = line.replace("status:", "").strip().strip('"').strip("'").lower()
                            if "complete" in st_val or "abgeschlossen" in st_val:
                                status = "completed"
                            elif "plan" in st_val:
                                status = "planned"
                except Exception:
                    pass

            end_dir = p_dir / "03_Endprodukte"
            if end_dir.is_dir():
                for f in sorted(end_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.suffix.lower() == ".html":
                        primary_doc = f"01_PROJEKTE/{folder_name}/03_Endprodukte/{f.name}"
                        has_html = True
                        break
                    elif f.suffix.lower() == ".md" and not primary_doc:
                        primary_doc = f"01_PROJEKTE/{folder_name}/03_Endprodukte/{f.name}"

            subtasks = []
            for pid, t_list in tasks_by_project.items():
                if pid.lower() in folder_name.lower() or any(part in pid.lower() for part in folder_name.lower().split("-") if len(part) >= 4 and part not in ("projekt", "2026")):
                    subtasks.extend(t_list)
                    seen_ids.add(pid)
                    for st in t_list:
                        if st.get("assignee"):
                            assignees.add(st["assignee"])

            t_total = len(subtasks)
            t_done = sum(1 for st in subtasks if st.get("status") in ("done", "review", "completed"))
            progress = int((t_done / t_total) * 100) if t_total > 0 else (100 if status == "completed" else 0)
            if t_total > 0 and t_done == t_total:
                status = "completed"

            z_count = len(list((p_dir / "01_Zwischenberichte").iterdir())) if (p_dir / "01_Zwischenberichte").is_dir() else 0
            m_count = len(list((p_dir / "02_Medien").iterdir())) if (p_dir / "02_Medien").is_dir() else 0
            e_count = len(list(end_dir.iterdir())) if end_dir.is_dir() else 0

            if proj_title == folder_name:
                clean_parts = [p for p in folder_name.split("-") if not p.isdigit() and p not in ("projekt", "delegationsprojekt")]
                proj_title = " ".join(clean_parts).title() or folder_name

            # Enrich assignees & subtasks with Klarnamen + Title
            assignee_objs = []
            for a in sorted(list(assignees)):
                a_info = cadre_map.get(a, {"id": a, "person_name": a, "role": "", "display": a})
                assignee_objs.append(a_info)

            enriched_subtasks = []
            for st in subtasks:
                st_c = dict(st)
                asg = st_c.get("assignee") or ""
                a_info = cadre_map.get(asg, {"id": asg, "person_name": asg, "role": "", "display": asg})
                st_c["assignee_person_name"] = a_info["person_name"]
                st_c["assignee_title"] = a_info["role"]
                st_c["assignee_display"] = a_info["display"]
                enriched_subtasks.append(st_c)

            projects.append({
                "id": folder_name,
                "title": proj_title,
                "status": status,
                "folder": f"01_PROJEKTE/{folder_name}",
                "lead_agent": lead_agent,
                "lead_agent_display": cadre_map.get(lead_agent, {}).get("display", lead_agent),
                "assignees": sorted(list(assignees)),
                "assignee_objects": assignee_objs,
                "progress": progress,
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "subtasks": enriched_subtasks,
                "primary_document": primary_doc,
                "has_html_report": has_html,
                "files_summary": {
                    "zwischenberichte": z_count,
                    "medien": m_count,
                    "endprodukte": e_count
                }
            })

    for pid, t_list in tasks_by_project.items():
        if pid not in seen_ids:
            t_total = len(t_list)
            t_done = sum(1 for st in t_list if st.get("status") in ("done", "review", "completed"))
            progress = int((t_done / t_total) * 100) if t_total > 0 else 0
            asg_set = sorted(list({st.get("assignee") for st in t_list if st.get("assignee")}))
            assignee_objs = [cadre_map.get(a, {"id": a, "person_name": a, "role": "", "display": a}) for a in asg_set]
            enriched_subtasks = []
            for st in t_list:
                st_c = dict(st)
                asg = st_c.get("assignee") or ""
                a_info = cadre_map.get(asg, {"id": asg, "person_name": asg, "role": "", "display": asg})
                st_c["assignee_person_name"] = a_info["person_name"]
                st_c["assignee_title"] = a_info["role"]
                st_c["assignee_display"] = a_info["display"]
                enriched_subtasks.append(st_c)

            projects.append({
                "id": pid,
                "title": pid.replace("projekt-", "").replace("-", " ").title(),
                "status": "planned" if progress == 0 else ("completed" if t_done == t_total else "in_progress"),
                "folder": f"01_PROJEKTE/{pid}",
                "lead_agent": "executive_decision_architect",
                "lead_agent_display": cadre_map.get("executive_decision_architect", {}).get("display", "Robert, CEO"),
                "assignees": asg_set,
                "assignee_objects": assignee_objs,
                "progress": progress,
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "subtasks": enriched_subtasks,
                "primary_document": None,
                "has_html_report": False,
                "files_summary": {"zwischenberichte": 0, "medien": 0, "endprodukte": 0}
            })

    return {
        "status": "success",
        "total": len(projects),
        "in_progress": [p for p in projects if p["status"] == "in_progress"],
        "completed": [p for p in projects if p["status"] == "completed"],
        "planned": [p for p in projects if p["status"] == "planned"],
        "all": projects
    }


@router.get("/kanban/projects/{task_id}")
def get_kanban_project_files(task_id: str):
    """Listet die Dateien des verknuepften Obsidian-Projekts einer Task (Sidecar-Bruecke)."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    meta = _load_kanban_meta()
    rel = _resolve_task_obsidian_rel(task_id, meta)
    if not rel:
        raise HTTPException(status_code=404, detail="Kein Obsidian-Projekt verknuepft.")
    vault = _P(get_vault_dir()).resolve()
    proj = (vault / rel).resolve()
    if not str(proj).startswith(str(vault)) or not proj.is_dir():
        raise HTTPException(status_code=404, detail=f"Projektordner fehlt: {rel}")
    files = []
    for p in sorted(proj.rglob("*")):
        if p.is_file():
            relp = p.relative_to(proj)
            files.append({
                "path": relp.as_posix(),
                "name": p.name,
                "dir": relp.parent.as_posix() if str(relp.parent) != "." else "",
                "size": p.stat().st_size,
            })
    return {"task_id": task_id, "relative": rel, "project_dir": str(proj), "files": files}


@router.get("/raw")
def get_raw_original(path: str):
    """'Original oeffnen' fuer Dateien AUSSERHALB des Vaults (systeminterne
    Pfade /opt/data, /app): liefert Bytes mit inline-disposition, damit der
    Browser PDF/Bilder/MD direkt zeigt bzw. laedt. Traversal-Schutz ueber
    erlaubte Basis-Pruefung."""
    from pathlib import Path as _P
    import mimetypes as _mt
    from fastapi.responses import Response
    raw = (path or "").strip()
    p = _P(raw)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Absoluter Pfad erwartet (z.B. /opt/data/...).")
    rp = p.resolve()
    erlaubte_basen = ("/opt/data/", "/app/")
    if not any(str(rp).startswith(b) for b in erlaubte_basen):
        raise HTTPException(status_code=403,
                            detail="Nur systeminterne Pfade sind oeffenbar (/opt/data, /app). "
                                   "Host-Dateien ausserhalb der Container-Binds: Pfad kopieren.")
    if not rp.is_file():
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {raw}")
    try:
        data = rp.read_bytes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    mime = _mt.guess_type(rp.name)[0] or "application/octet-stream"
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f'inline; filename="{rp.name}"'})


@router.get("/vault/file")
def get_vault_file(path: str):
    """SYSTEMWEITER Datei-Reader: liefert EINE Vault-Datei (01_PROJEKTE/...) als Text.
    Traversal-Schutz: resolve + startswith(Vault) + Suffix-Whitelist."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    rel = path.strip().lstrip("/\\")
    vault = _P(get_vault_dir()).resolve()
    target = (vault / rel).resolve()
    if not str(target).startswith(str(vault)) or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {rel}")
    if target.suffix.lower() not in (".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".log"):
        raise HTTPException(status_code=415, detail="Nur Textdateien (.md/.txt/...).")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    return {"path": rel, "size": target.stat().st_size, "content": content}


@router.get("/vault/find")
def find_vault_file(q: str, limit: int = 8):
    """Findet Vault-Dateien per Name/Teilstring (fuer nackte .md-Namen aus Chat-Texten)."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    q = (q or "").strip().lower()
    if not q or len(q) < 3:
        raise HTTPException(status_code=400, detail="Suchbegriff zu kurz.")
    vault = _P(get_vault_dir()).resolve()
    treffer, scanned = [], 0
    try:
        # ZUERST 01_PROJEKTE (Ergebnis-MDs), dann Rest - hart begrenzt
        for raum in (vault / "01_PROJEKTE", vault):
            if treffer:
                break
            if not raum.is_dir():
                continue
            for p in raum.rglob("*.md"):
                scanned += 1
                if scanned > 2500:
                    break
                rel = p.relative_to(vault).as_posix()
                if q in p.name.lower() or q in rel.lower():
                    treffer.append({"path": rel, "name": p.name, "size": p.stat().st_size})
                    if len(treffer) >= limit:
                        break
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suche fehlgeschlagen: {e}")
    return {"query": q, "files": treffer}


@router.get("/kanban/projects/{task_id}/file")
def get_kanban_project_file(task_id: str, path: str):
    """Liefert EINE Projektdatei als Text - nur innerhalb des Projektordners (Traversal-Schutz)."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    meta = _load_kanban_meta()
    rel = _resolve_task_obsidian_rel(task_id, meta)
    if not rel:
        raise HTTPException(status_code=404, detail="Kein Obsidian-Projekt verknuepft.")
    vault = _P(get_vault_dir()).resolve()
    proj = (vault / rel).resolve()
    if not str(proj).startswith(str(vault)):
        raise HTTPException(status_code=400, detail="Pfad ausserhalb des Vaults.")
    target = (proj / path).resolve()
    if not str(target).startswith(str(proj)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    if target.suffix.lower() not in (".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".log"):
        raise HTTPException(status_code=415, detail="Nur Textdateien (.md/.txt/.csv/...).")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lesen fehlgeschlagen: {e}")
    return {"task_id": task_id, "path": path, "size": target.stat().st_size, "content": content}


@router.get("/kanban/palette")
def get_kanban_palette():
    """Liefert die Kanban-Spaltenfarben (Gespeicherte, mit Posteo-Standard gemischt)."""
    if os.path.exists(_KANBAN_PALETTE_FILE):
        try:
            with open(_KANBAN_PALETTE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Merge: Standard + gespeicherte Überschreibungen (gespeichert gewinnt)
            merged = {}
            for col_id, defaults in KANBAN_PALETTE_DEFAULTS.items():
                merged[col_id] = {**defaults, **(saved.get(col_id) or {})}
            return {"status": "ok", "custom": True, "columns": merged}
        except Exception as e:
            print(f"[OperationsAPI] Palette load error: {e}", file=sys.stderr)
    return {"status": "ok", "custom": False, "columns": KANBAN_PALETTE_DEFAULTS}

@router.post("/kanban/palette")
def save_kanban_palette(req: KanbanPaletteUpdate):
    """Speichert die Kanban-Farbpalette (oder setzt mit reset=true auf Standard zurück)."""
    if req.reset:
        if os.path.exists(_KANBAN_PALETTE_FILE):
            try:
                os.remove(_KANBAN_PALETTE_FILE)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Reset fehlgeschlagen: {e}")
        return {"status": "ok", "reset": True, "columns": KANBAN_PALETTE_DEFAULTS}
    if not req.columns:
        raise HTTPException(status_code=400, detail="columns erforderlich")
    # Sanitize: nur gültige Hex-Farben und bekannte Spalten-IDs
    cleaned = {}
    for col_id, colors in req.columns.items():
        if col_id not in KANBAN_PALETTE_DEFAULTS:
            continue
        entry = {}
        for key in ("header", "text"):
            val = str(colors.get(key, "")).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", val):
                entry[key] = val
        if entry:
            cleaned[col_id] = entry
    os.makedirs(os.path.dirname(_KANBAN_PALETTE_FILE), exist_ok=True)
    with open(_KANBAN_PALETTE_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    return {"status": "ok", "saved": True, "columns": cleaned}


@router.get("/kanban/meta")
def get_kanban_meta():
    """Sidecar-Metadaten: Due-Dates/Tags pro Task + WIP-Limits pro Spalte."""
    return {"status": "ok", **_load_kanban_meta()}


@router.post("/kanban/meta")
def save_kanban_meta(payload: Dict[str, Any] = Body(...)):
    """Due/Tags (kind=task) oder WIP-Limits (kind=wip) speichern. Engine-DB bleibt unberuehrt."""
    # 12.10.2026 (Fix Punkt 1, Datenrisiko): die GESAMTE Load-Aendern-Speichern-
    # Sequenz laeuft unter EINER Sperre (backend.kanban_sidecar.update_kanban_meta),
    # sonst verliert paralleler Fan-in Entscheidungs-Metadaten. Validierung VORHER
    # (ohne Datei), damit kein Lock auf Fehlerpfaden gehalten wird.
    from backend.kanban_sidecar import update_kanban_meta
    kind = str(payload.get("kind") or "task")
    if kind == "wip":
        limits = payload.get("limits") or {}
        cleaned: Dict[str, int] = {}
        for col, n in limits.items():
            try:
                v = int(n)
            except (TypeError, ValueError):
                continue
            if v > 0:
                cleaned[str(col)] = v

        def _apply_wip(meta):
            meta["wip"] = cleaned

        update_kanban_meta(_apply_wip)
        return {"status": "ok", "wip": cleaned}
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id erforderlich")
    due_in = payload.get("due")
    if due_in and not payload.get("clear_due"):
        try:
            datetime.date.fromisoformat(str(due_in)[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="due muss YYYY-MM-DD sein")
    tags_in = payload.get("tags")

    def _apply_task(meta):
        tmeta = meta["tasks"].setdefault(task_id, {})
        if payload.get("clear_due"):
            tmeta.pop("due", None)
        elif due_in:
            tmeta["due"] = str(due_in)[:10]
        if tags_in is not None:
            tags = [str(t).strip()[:24] for t in tags_in if str(t).strip()][:8]
            if tags:
                tmeta["tags"] = tags
            else:
                tmeta.pop("tags", None)
        # 12.10.2026 (Decision-Service): Entscheidungs-Metadaten je Task.
        # kanban.db bleibt die Wahrheit (Status), der Sidecar traegt nur Kontext.
        obs_in = payload.get("obsidian")
        if obs_in is not None and str(obs_in).strip() != "":
            tmeta["obsidian"] = str(obs_in).strip()
        elif payload.get("clear_obsidian"):
            tmeta.pop("obsidian", None)
        dec_in = payload.get("decision")
        if isinstance(dec_in, dict):
            if dec_in.get("clear"):
                tmeta.pop("decision", None)
            else:
                dec = tmeta.setdefault("decision", {})
                for k in ("typ", "ref_id", "titel", "kurzfassung", "dossier", "body",
                          "assignee", "status", "entschieden_von", "entschieden_am", "kanal"):
                    if k in dec_in:
                        dec[k] = dec_in[k]
                tg = dec_in.get("telegram")
                if isinstance(tg, dict):
                    dec.setdefault("telegram", {}).update(tg)
                dec.setdefault("erstellt", datetime.datetime.now().isoformat())
        # Tokens & Cost (User-Erweiterung Punkt 5)
        if "tokens" in payload:
            tmeta["tokens"] = payload["tokens"]
        if "cost" in payload:
            tmeta["cost"] = payload["cost"]
        if not tmeta:
            meta["tasks"].pop(task_id, None)
        return dict(meta["tasks"].get(task_id, {}))

    _, saved = update_kanban_meta(_apply_task)
    try:
        import main
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("kanban_updated", {"action": "meta_update", "task_id": task_id})
    except Exception:
        pass
    return {"status": "ok", "task": saved}


@router.get("/kanban/stats")
def kanban_stats():
    """Board-Kennzahlen: Spaltenverteilung, Durchlaufzeit, 7-Tage-Flows."""
    conn = _get_kanban_connection()
    try:
        cur = conn.cursor()
        per_status: Dict[str, int] = {}
        for st, n in cur.execute("SELECT status, count(*) FROM tasks GROUP BY status"):
            per_status[st or "todo"] = n
        active = {k: v for k, v in per_status.items() if k != "archived"}
        cycles = []
        for s, e in cur.execute(
            "SELECT started_at, completed_at FROM tasks WHERE started_at IS NOT NULL AND completed_at IS NOT NULL"
        ):
            s_ts = _parse_kanban_ts(s)
            e_ts = _parse_kanban_ts(e)
            if s_ts is not None and e_ts is not None:
                cycles.append((e_ts - s_ts) / 3600.0)
        avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else None
        now = datetime.datetime.now()
        created_7d = cur.execute(
            "SELECT count(*) FROM tasks WHERE created_at >= ?", ((now - datetime.timedelta(days=7)).isoformat(),)
        ).fetchone()[0]
        epoch_7d = (now - datetime.timedelta(days=7)).timestamp()
        done_7d = 0
        for (e,) in cur.execute("SELECT completed_at FROM tasks WHERE completed_at IS NOT NULL"):
            e_ts = _parse_kanban_ts(e)
            if e_ts is not None and e_ts >= epoch_7d:
                done_7d += 1
        return {
            "status": "ok",
            "active_total": sum(active.values()),
            "per_status": active,
            "archived_total": per_status.get("archived", 0),
            "blocked": per_status.get("blocked", 0),
            "done_7d": done_7d,
            "created_7d": created_7d,
            "avg_cycle_hours": avg_cycle,
        }
    finally:
        conn.close()


@router.get("/kanban/tasks/{task_id}")
def get_task_details(task_id: str):
    """Gibt Detailinformationen, Kommentare und Event-Logs eines Tasks zurück."""
    conn = _get_kanban_connection()
    profiles = _load_profiles_map()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT rowid AS task_num, * FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")
            
        task = dict(task_row)
        assignee_id = task.get("assignee")
        prof = profiles.get(assignee_id, {})
        task["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
        task["assignee_avatar"] = prof.get("avatar") or _get_fallback_avatar(assignee_id)

        # Obsidian-Projekt-Bruecke (Sidecar config/kanban_meta.json, Option A 11.10.2026)
        _meta_all = _load_kanban_meta()
        task["obsidian"] = _resolve_task_obsidian_rel(task_id, _meta_all)
        # 2b (12.10.2026): Entscheidungs-Kontext mitliefern (Sidecar-Block), damit der
        # Detail-Dialog Typ, Status, Kurzfassung und das Bericht-Dossier anzeigen kann.
        task["decision"] = ((_meta_all.get("tasks") or {}).get(task_id) or {}).get("decision") or None
        
        cursor.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        comments = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        events = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("""
            SELECT l.parent_id, l.child_id, t.title 
            FROM task_links l 
            JOIN tasks t ON l.child_id = t.id 
            WHERE l.parent_id = ?
        """, (task_id,))
        children = [dict(r) for r in cursor.fetchall()]
        
        return {
            "status": "success",
            "task": task,
            "comments": comments,
            "events": events,
            "subtasks": children
        }
    finally:
        conn.close()


@router.post("/kanban/tasks/{task_id}/comments")
def add_task_comment(task_id: str, author: str = Body(..., embed=True), body: str = Body(..., embed=True)):
    """Fügt einem Task einen Kommentar hinzu (Timestamp als integer Unix-Epoch für Hermes-Kompatibilität)."""
    conn = _get_kanban_connection()
    try:
        now_ts = int(time.time())
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_comments (task_id, author, body, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, author, body, now_ts))
        conn.commit()
        return {"status": "success", "task_id": task_id, "created_at": now_ts}
    finally:
        conn.close()


# =========================================================================
# ORG-CHART, TEAMS, COMM-FEED, HIERARCHY & CONCURRENCY
# Ausgelagert nach archon/routers/operations_org.py
# =========================================================================
from archon.routers.operations_org import (
    router as _org_router,
    TEAMS_DEFINITION,
    get_org_chart,
    CommBroadcastRequest,
    broadcast_comm_message,
    get_communication_feed,
    stream_comm_feed,
    _get_org_hierarchy_file,
    _generate_default_hierarchy,
    OrgHierarchySaveRequest,
    get_org_hierarchy,
    save_org_hierarchy,
    reset_org_hierarchy,
    ConcurrencyUpdateRequest,
    get_concurrency_settings,
    update_concurrency_settings,
    get_audit_log_entries,
    verify_audit_log_chain,
    export_audit_log,
)
ORG_HIERARCHY_FILE = _get_org_hierarchy_file()
router.include_router(_org_router)


# =========================================================================
# DAG-SCHEDULER, WORKFLOW CHECKPOINTS & OTEL TRACING
# Ausgelagert nach archon/routers/operations_dag.py
# =========================================================================
from archon.routers.operations_dag import (
    router as _dag_router,
    DecomposeTaskRequest,
    api_dag_decompose_task,
    api_dag_execute_task,
    WorkflowCheckpointCreateRequest,
    api_create_workflow_checkpoint,
    api_list_workflow_checkpoints,
    api_resume_workflow_checkpoint,
    api_list_otel_traces,
    api_get_otel_trace_tree,
)
router.include_router(_dag_router)

# =========================================================================
# PROMPT REGISTRY, VERSIONING, CANARY & ROLLBACK
# Ausgelagert nach archon/routers/operations_prompts.py
# =========================================================================
from archon.routers.operations_prompts import (
    router as _prompts_router,
    api_list_prompt_versions,
    api_save_prompt_version,
    api_diff_prompt_versions,
    api_rollback_prompt_version,
    api_set_prompt_canary,
    api_promote_prompt_canary,
)
router.include_router(_prompts_router)

# =========================================================================
# BELEGVERARBEITUNG & OCR (RECEIPTS ENGINE)
# Ausgelagert nach archon/routers/operations_receipts.py
# =========================================================================
from archon.routers.operations_receipts import (
    router as _receipts_router,
    api_receipts_process,
    api_receipts_list,
    api_receipt_image,
    api_receipt_patch,
    api_receipts_upload,
)
router.include_router(_receipts_router)

# =========================================================================
# FEEDBACK, NOTIFICATIONS, MCP, STREAMING, BACKUP, GDPR & CHAOS
# Ausgelagert nach archon/routers/operations_sysops.py
# =========================================================================
from archon.routers.operations_sysops import (
    router as _sysops_router,
    HumanFeedbackSubmitRequest,
    api_submit_human_feedback,
    api_get_feedback_stats,
    api_get_task_feedback,
    api_validate_system_config,
    api_get_metrics_summary,
    api_get_notification_policy,
    api_update_notification_policy,
    api_get_suppressed_digest,
    api_get_mcp_tools,
    api_call_mcp_tool,
    api_stream_task_execution,
    api_broadcast_task_chunk,
    api_get_restore_test_history,
    api_trigger_restore_test,
    api_gdpr_export,
    api_gdpr_erase,
    api_gdpr_audit_log,
    api_chaos_run,
    api_chaos_results,
)
router.include_router(_sysops_router)



@router.post("/esign/submissions")
def api_esign_create_submission(req: Dict[str, Any] = Body(...)):
    """Erstellt eine neue digitale Signaturanfrage via DocuSeal."""
    title = req.get("title", "").strip()
    signer_email = req.get("signer_email", "").strip()
    signer_name = req.get("signer_name", "").strip()
    template_id = req.get("template_id")
    kanban_task_id = req.get("kanban_task_id")

    if not title or not signer_email or not signer_name:
        raise HTTPException(status_code=400, detail="Felder 'title', 'signer_email' und 'signer_name' sind erforderlich.")

    try:
        from backend.docuseal_client import docuseal_client
        res = docuseal_client.create_submission(
            title=title,
            signer_email=signer_email,
            signer_name=signer_name,
            template_id=template_id,
            kanban_task_id=kanban_task_id
        )
        return {"status": "success", "submission": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DocuSeal Submission fehlgeschlagen: {e}")


@router.get("/esign/contracts")
def api_esign_list_contracts(limit: int = Query(default=50)):
    """Listet alle Signaturverträge auf."""
    try:
        from backend.docuseal_client import docuseal_client
        contracts = docuseal_client.list_contracts(limit=limit)
        return {"status": "success", "count": len(contracts), "contracts": contracts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/esign/webhook")
def api_esign_webhook(request: Request, payload: Dict[str, Any] = Body(...)):
    """Empfängt Webhooks von DocuSeal nach Unterzeichnung eines Dokuments."""
    webhook_secret = os.getenv("DOCUSEAL_WEBHOOK_SECRET")
    if webhook_secret:
        header_secret = request.headers.get("X-DocuSeal-Secret") or request.headers.get("X-Webhook-Secret") or request.query_params.get("secret")
        if not header_secret or not secrets.compare_digest(str(header_secret), str(webhook_secret)):
            raise HTTPException(status_code=403, detail="Ungueltiges Webhook-Secret.")
    else:
        # Fallback auf Admin-Rollenzaun, falls kein Secret konfiguriert ist
        require_admin_or_503(request)

    try:
        from backend.docuseal_client import docuseal_client
        res = docuseal_client.handle_webhook_event(payload)
        return {"status": "success", "webhook_result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook Verarbeitung fehlgeschlagen: {e}")


# =========================================================================
# MAHNWESEN & DEBITORENMANAGEMENT (DUNNING ENGINE)
# Ausgelagert nach archon/routers/operations_dunning.py
# =========================================================================
from archon.routers.operations_dunning import (
    router as _dunning_router,
    api_dunning_invoices,
    api_dunning_create_invoice,
    api_dunning_generate_draft,
    api_dunning_approve,
    api_dunning_mark_paid,
)
router.include_router(_dunning_router)

# ==============================================================================
# FINE-TUNING PIPELINE ENDPOINTS (t-56ff9d)
# Ausgelagert nach archon/routers/operations_finetuning.py
# ==============================================================================
from archon.routers.operations_finetuning import (
    router as _finetuning_router,
    api_finetuning_status,
    api_finetuning_prepare,
)
router.include_router(_finetuning_router)



# ==============================================================================
# APPROVAL POLICIES & ESKALATION ENDPOINTS (t-5596bd)
# Ausgelagert nach archon/routers/operations_approvals.py
# ==============================================================================
from archon.routers.operations_approvals import (
    router as _approvals_router,
    api_get_approval_policies,
    api_update_approval_policy,
    api_get_approval_requests,
    api_create_approval_request,
    api_approve_request,
    api_reject_request,
    api_get_delegation,
    api_set_delegation,
    api_get_approval_audit_chain,
    api_verify_approval_audit,
)
router.include_router(_approvals_router)

# ==============================================================================
# API-KEYS & SCOPES ACCESS MANAGEMENT (t-6fad7a)
# Ausgelagert nach archon/routers/operations_keys.py
# ==============================================================================
from archon.routers.operations_keys import (
    router as _keys_router,
    api_list_keys,
    api_create_key,
    api_revoke_key,
    api_delete_key,
    api_get_keys_audit,
)
router.include_router(_keys_router)



# ==============================================================================
# EMAIL DRAFT APPROVAL QUEUE (t-7ca8cd)
# Ausgelagert nach archon/routers/operations_emails.py
# ==============================================================================
from archon.routers.operations_emails import (
    router as _emails_router,
    api_list_email_drafts,
    api_create_email_draft,
    api_get_email_draft,
    api_approve_email_draft,
    api_edit_email_draft,
    api_snooze_email_draft,
    api_regenerate_email_draft,
    api_reject_email_draft,
)
router.include_router(_emails_router)

# =========================================================================
# AGENT SCORECARDS, DUAL-LLM GUARD & BREAK-GLASS PROTOCOL
# Ausgelagert nach archon/routers/operations_security.py
# =========================================================================
from archon.routers.operations_security import (
    router as _sec_router,
    api_get_agent_scorecard,
    api_save_agent_operator_notes,
    api_sanitize_input,
    api_get_trusted_sources,
    api_toggle_trusted_source,
    api_get_break_glass_status,
    api_create_break_glass_vault,
    api_download_break_glass_kit,
)
router.include_router(_sec_router)




# =========================================================================
# BOT SCREEN & HUMAN TAKEOVER (VIRTUAL DESKTOP INTEGRATION)
# Ausgelagert nach archon/routers/operations_bot_screen.py
# =========================================================================
from archon.routers.operations_bot_screen import (
    router as _bot_screen_router,
    _bot_screen_state,
    TakeoverRequestModel,
    ScreenInteractionModel,
    get_bot_screen_status,
    request_human_takeover,
    resume_from_human_takeover,
    interact_with_bot_screen,
    abort_bot_screen_execution,
)
router.include_router(_bot_screen_router)



# ==============================================================================
# AUTONOMIE-SYSTEME (Features 6, 8, 10, 13)
# Ausgelagert nach archon/routers/operations_autonomy.py
# ==============================================================================
from archon.routers.operations_autonomy import (
    router as _autonomy_router,
    ToolEvolutionRequest,
    MCTSSimulationRequest,
    PrefetchRequest,
    JITPersonaTaskRequest,
    list_evolved_tools,
    trigger_tool_evolution,
    simulate_mcts_trajectories,
    trigger_speculative_prefetch,
    execute_jit_persona_task,
    list_ephemeral_personas,
)
router.include_router(_autonomy_router)



# ==============================================================================
# MEILENSTEIN 26: AUTONOMOUS COMPUTER-USE & PbD (Programming by Demonstration)
# Ausgelagert nach archon/routers/operations_pbd.py
# ==============================================================================
from archon.routers.operations_pbd import (
    router as _pbd_router,
    PBDStartRequest,
    PBDEventRequest,
    PBDStopRequest,
    TrajectoryRequest,
    A11yPruneRequest,
    start_pbd_recording,
    record_pbd_event,
    get_pbd_status,
    stop_pbd_and_synthesize,
    calculate_ghost_cursor_trajectory,
    prune_a11y_tree,
)
router.include_router(_pbd_router)





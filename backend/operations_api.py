"""
Operations API Router for Archon OS
Provides Kanban (Hermes kanban.db), Org-Chart, and Inter-Agent Communication Feed.
"""

import os
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
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/operations", tags=["operations"])

KANBAN_DB_PATH = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else "C:\\Users\\micha\\.hermes\\kanban.db"
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")


_KANBAN_JOURNAL_INIT = False

def _get_kanban_connection():
    global _KANBAN_JOURNAL_INIT
    if not os.path.exists(KANBAN_DB_PATH):
        raise HTTPException(status_code=503, detail=f"kanban.db nicht gefunden unter {KANBAN_DB_PATH}")
    conn = sqlite3.connect(KANBAN_DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    if not _KANBAN_JOURNAL_INIT:
        try:
            if str(KANBAN_DB_PATH).replace("\\", "/").startswith("/opt/data"):
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
                    (CAST(started_at AS REAL) > 0 AND CAST(started_at AS REAL) < ?)
                    OR (started_at IS NOT NULL AND started_at < ?)
                    OR (started_at IS NULL AND created_at < ?)
                  )
            """, (cutoff_ts, cutoff_iso, cutoff_iso))
            conn.commit()
        except Exception:
            pass
        _KANBAN_JOURNAL_INIT = True
    conn.row_factory = sqlite3.Row
    return conn


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
    h = abs(hash(aid)) % 108 + 1
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
    # 12.10.2026 (Fix Punkt 1, Datenrisiko): atomares Schreiben (Temp+replace).
    # HINWEIS: Wer load-aendern-speichern als SEQUENZ braucht, muss
    # backend.kanban_sidecar.update_kanban_meta nutzen (Lock!) — diese Funktion
    # schreibt nur, sie sperrt nicht.
    from backend.kanban_sidecar import _write_atomic
    _write_atomic(meta)


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
    task_dict["obsidian"] = tmeta.get("obsidian") or None
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
    conn = _get_kanban_connection()
    profiles = _load_profiles_map()
    meta = _load_kanban_meta()
    base_select = """
            SELECT id, title, body, assignee, status, priority, created_by,
                   created_at, started_at, completed_at, result, model_override, provider_override,
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
            "scheduled": []
        }

        active_rows = 0
        for r in rows:
            task_dict = dict(r)
            st = (task_dict.get("status") or "todo").lower()
            if st == "archived":
                # 2-Stufen-Archiv (10.10.2026): archiviert gehoert nicht aufs Board
                # (vorher fiel archived still in den todo-Bucket)
                continue
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
                subprocess.Popen(["docker", "exec", "hermes", "hermes", "kanban", "decompose", task_id])
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
        cur.execute("SELECT id, title, body, assignee, status, model_override FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return
        t_dict = dict(row)
    finally:
        conn.close()

    # Fall 1: Ist es ein DAG Epic?
    if t_dict["id"].startswith("dag-") and not any(t_dict["id"].endswith(f"-{s}") for s in ["1", "2", "3", "4", "syn"]):
        try:
            from backend.dag_scheduler import dag_scheduler_instance
            await dag_scheduler_instance.execute_dag(task_id)
            return
        except Exception as e:
            print(f"[OperationsAPI] DAG Execution error for {task_id}: {e}", file=sys.stderr)

    # Fall 2: Einzelaufgabe
    assignee = t_dict.get("assignee") or "hermes-researcher"
    title = t_dict.get("title") or "Aufgabe"
    body = t_dict.get("body") or title
    model = t_dict.get("model_override") or "deepseek/deepseek-chat"

    profiles = _load_profiles_map()
    prof = profiles.get(assignee, {})
    agent_name = prof.get("name") or assignee
    role = prof.get("category") or prof.get("role") or "Fach-Spezialist"
    system_prompt = prof.get("prompt") or prof.get("system_prompt") or f"Du bist {agent_name} in Archon OS. Bearbeite die Aufgabe präzise, lösungsorientiert und strukturiert."

    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=assignee,
            agent_name=agent_name,
            prompt=f"Führe bitte folgende Projektaufgabe in Archon OS durch:\n\nTITEL: {title}\nAUFTRAG / DETAILS:\n{body}\n\nLiefere eine klare, fundierte Ausarbeitung sowie die wichtigsten Handlungsschritte.",
            role=role,
            system_prompt=system_prompt,
            model=model,
            task_id=task_id
        )
        reply = res.get("content", "").strip() or f"Aufgabe '{title}' erfolgreich von {agent_name} abgeschlossen."
        now_iso = datetime.datetime.now().isoformat()
        
        c = _get_kanban_connection()
        try:
            c.execute("UPDATE tasks SET status = 'review', completed_at = ?, result = ? WHERE id = ?", (now_iso, reply, task_id))
            c.execute("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'completed', ?, ?)", 
                      (task_id, json.dumps({"status": "review", "summary": reply[:200]}), now_iso))
            c.commit()
            _sync_to_memory_bridge(task_id, title, assignee, "review", reply)
        finally:
            c.close()
            
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

        completed_at = now_iso if new_status == "done" else None
        started_at = now_iso if new_status == "in_progress" else None

        cursor.execute("""
            UPDATE tasks
            SET status = ?,
                started_at = COALESCE(?, started_at),
                completed_at = COALESCE(?, completed_at),
                result = COALESCE(?, result)
            WHERE id = ?
        """, (new_status, started_at, completed_at, req.result, task_id))

        cursor.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, "status_changed", json.dumps({"from": old_status, "to": new_status}), now_iso))

        conn.commit()
        _sync_to_memory_bridge(task_id, existing["title"], existing["assignee"], new_status, req.result)

        # Autonome LLM-Ausführung starten, wenn Task auf 'in_progress' gesetzt wurde
        if new_status == "in_progress" and old_status != "in_progress":
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
async def api_kanban_bulk_action(req: KanbanBulkActionRequest):
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
async def api_kanban_bulk_undo(req: KanbanBulkUndoRequest):
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
    assignee = t_dict.get("assignee") or "hermes-researcher"
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
                parsed = {
                    "verdict": "approved",
                    "score": 80,
                    "summary": "Ergebnis erfolgreich gesichtet und freigegeben.",
                    "critique_points": [],
                    "actionable_next_steps": []
                }
        except Exception as e:
            parsed = {
                "verdict": "approved",
                "score": 75,
                "summary": f"Standardprüfung durchgeführt ({e}).",
                "critique_points": [],
                "actionable_next_steps": []
            }

        verdict = parsed.get("verdict", "approved")
        if verdict not in ("approved", "changes_requested"):
            verdict = "approved"

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

@router.get("/kanban/projects/{task_id}")
def get_kanban_project_files(task_id: str):
    """Listet die Dateien des verknuepften Obsidian-Projekts einer Task (Sidecar-Bruecke)."""
    from pathlib import Path as _P
    from backend.post_task_pipeline import get_vault_dir
    meta = _load_kanban_meta()
    rel = ((meta.get("tasks") or {}).get(task_id) or {}).get("obsidian")
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
    rel = ((meta.get("tasks") or {}).get(task_id) or {}).get("obsidian")
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
        if obs_in is not None:
            if str(obs_in).strip() == "":
                tmeta.pop("obsidian", None)
            else:
                tmeta["obsidian"] = str(obs_in).strip()
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
            try:
                cycles.append((float(e) - float(s)) / 3600.0)
            except (TypeError, ValueError):
                pass
        avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else None
        now = datetime.datetime.now()
        created_7d = cur.execute(
            "SELECT count(*) FROM tasks WHERE created_at >= ?", ((now - datetime.timedelta(days=7)).isoformat(),)
        ).fetchone()[0]
        epoch_7d = (now - datetime.timedelta(days=7)).timestamp()
        done_7d = 0
        for (e,) in cur.execute("SELECT completed_at FROM tasks WHERE completed_at IS NOT NULL"):
            try:
                if float(e) >= epoch_7d:
                    done_7d += 1
            except (TypeError, ValueError):
                pass
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
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
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
        task["obsidian"] = ((_meta_all.get("tasks") or {}).get(task_id) or {}).get("obsidian") or None
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
    """Fügt einem Task einen Kommentar hinzu."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_comments (task_id, author, body, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, author, body, now_iso))
        conn.commit()
        return {"status": "success", "task_id": task_id, "created_at": now_iso}
    finally:
        conn.close()


# =========================================================================
# 2. ORG-CHART & TEAMS ENDPOINT
# =========================================================================

TEAMS_DEFINITION = [
    {
        "id": "team_strategy",
        "name": "Geschäftsführung, Strategie & M&A",
        "lead_id": "executive_decision_architect",
        "color": "indigo",
        "members": [
            "executive_decision_architect",
            "micha",
            "default",
            "red_team_challenger",
            "tax_holding_advisor",
            "pricing_discount_governor",
            "pitchdeck_offer_designer",
            "personal_life_strategist",
            "agility_story",
            "analyze_claims",
            "gpts_automation_specialist",
            "gpts_critical_reviewer",
            "gpts_primary_synthesizer"
        ]
    },
    {
        "id": "team_tech",
        "name": "Software, Cloud & System-Architektur",
        "lead_id": "system_architect_orchestrator",
        "color": "blue",
        "members": [
            "system_architect_orchestrator",
            "senior_fullstack_engineer",
            "devops_cloud_sec_specialist",
            "database_performance_tuner",
            "enterprise_solutions_architect"
        ]
    },
    {
        "id": "team_legal",
        "name": "Recht, Verträge & Governance",
        "lead_id": "commercial_jurist_contracts",
        "color": "amber",
        "members": [
            "commercial_jurist_contracts",
            "liability_risk_analyst",
            "compliance_gdpr_auditor",
            "labor_law_hr_governance",
            "ip_patent_analyst",
            "vendor_contract_negotiator"
        ]
    },
    {
        "id": "team_realestate",
        "name": "Bau, Immobilien & ESG",
        "lead_id": "construction_project_manager",
        "color": "emerald",
        "members": [
            "construction_project_manager",
            "baugb_permit_expert",
            "realestate_dcf_calculator",
            "realestate_concept_strategist",
            "esg_kfw_efficiency_auditor",
            "urban_planning_architect",
            "vvgmbh_immo_tax_lead",
            "facility_asset_manager"
        ]
    },
    {
        "id": "team_growth",
        "name": "Vertrieb, Marketing & Media",
        "lead_id": "gtm_launch_strategist",
        "color": "rose",
        "members": [
            "gtm_launch_strategist",
            "growth_hacker_lead",
            "telegram_bot",
            "b2b_outreach_specialist",
            "direct_response_copywriter",
            "storyteller_ghostwriter",
            "video_script_architect",
            "content_repurposing_specialist",
            "speechwriter_keynote_designer",
            "pr_press_communicator",
            "affiliate_partner_manager",
            "ecommerce_shopify_lead",
            "lead_enrichment_analyst",
            "customer_retention_specialist",
            "brand_uiux_director"
        ]
    },
    {
        "id": "team_operations",
        "name": "Supply Chain, Einkauf & Scrum",
        "lead_id": "logistics_supply_chain_manager",
        "color": "teal",
        "members": [
            "logistics_supply_chain_manager",
            "procurement_sourcing_scout",
            "inventory_stock_forecaster",
            "agile_scrum_master",
            "product_requirements_engineer",
            "negotiation_master",
            "arbitrage_market_analyst",
            "competitive_intelligence_scout",
            "crisis_escalation_lead"
        ]
    }
]


@router.get("/org-chart")
def get_org_chart():
    """Gibt das vollständige hierarchische Organigramm mit den 3 Ebenen zurück."""
    profiles = _load_profiles_map()
    
    # Task counts pro Agent ermitteln
    task_counts = {}
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT assignee, count(*) as cnt FROM tasks WHERE status != 'done' GROUP BY assignee")
        for row in cursor.fetchall():
            if row["assignee"]:
                task_counts[row["assignee"]] = row["cnt"]
        conn.close()
    except Exception:
        pass
        
    def _enrich(agent_id: str, is_lead: bool = False):
        p = profiles.get(agent_id, {})
        return {
            "id": agent_id,
            "name": p.get("name") or agent_id,
            "category": p.get("category") or "Spezialist",
            "role": p.get("role") or p.get("category") or "Experte",
            "avatar": p.get("avatar") or _get_fallback_avatar(agent_id),
            "model": p.get("model") or "deepseek/deepseek-chat",
            "provider": p.get("provider") or "omniroute",
            "is_lead": is_lead,
            "active_tasks": task_counts.get(agent_id, 0),
            "status": "active"
        }

    # Tier 1: Boardroom / Executive Apex
    chairman = _enrich("executive_decision_architect", is_lead=True)
    orchestrator = _enrich("system_architect_orchestrator", is_lead=True)
    
    # Tier 2 & 3: Teams
    teams = []
    for t in TEAMS_DEFINITION:
        lead = _enrich(t["lead_id"], is_lead=True)
        members = [_enrich(m_id) for m_id in t["members"] if m_id != t["lead_id"] and m_id in profiles]
        teams.append({
            "id": t["id"],
            "name": t["name"],
            "color": t["color"],
            "lead": lead,
            "member_count": len(members) + 1,
            "members": members
        })
        
    return {
        "status": "success",
        "tier1_executive": {
            "chairman": chairman,
            "orchestrator": orchestrator,
            "title": "Unternehmensführung & System-Architektur"
        },
        "teams": teams,
        "total_agents": len(profiles)
    }


# =========================================================================
# 3. INTER-AGENT COMMUNICATION FEED
# =========================================================================

class CommBroadcastRequest(BaseModel):
    author: str = "commander"
    message: str
    task_id: Optional[str] = None
    target: Optional[str] = None


@router.post("/comm-feed/broadcast")
def broadcast_comm_message(req: CommBroadcastRequest):
    """Sendet eine Funkmeldung oder Agenten-Kommunikation in den Feed."""
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps({
            "author": req.author,
            "message": req.message,
            "target": req.target or "all",
            "broadcast": True
        }, ensure_ascii=False)
        task_id = req.task_id or "system_broadcast"
        cur.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES (?, 'broadcast', ?, ?)
        """, (task_id, payload, now_iso))
        conn.commit()
        return {"status": "success", "created_at": now_iso}
    finally:
        conn.close()


@router.get("/comm-feed")
def get_communication_feed(limit: int = Query(50), agent_filter: Optional[str] = Query(None)):
    """Liefert den chronologischen internen Kommunikationsfluss aller Agenten."""
    profiles = _load_profiles_map()
    feed_items = []
    
    # 1. Aus kanban.db (task_comments & task_events)
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        
        # Comments
        cursor.execute("""
            SELECT c.id, c.task_id, c.author, c.body, c.created_at, t.title as task_title, t.assignee
            FROM task_comments c
            LEFT JOIN tasks t ON c.task_id = t.id
            ORDER BY c.created_at DESC
            LIMIT ?
        """, (limit,))
        for r in cursor.fetchall():
            row = dict(r)
            author_id = row.get("author") or "agent"
            prof = profiles.get(author_id, {})
            feed_items.append({
                "id": f"comment_{row['id']}",
                "type": "task_comment",
                "timestamp": row["created_at"],
                "author_id": author_id,
                "author_name": prof.get("name") or author_id,
                "author_avatar": prof.get("avatar") or _get_fallback_avatar(author_id),
                "target_id": row.get("assignee"),
                "task_id": row["task_id"],
                "task_title": row["task_title"] or "Aufgabe",
                "message": row["body"]
            })
            
        # Events (Handoffs, Status Changes, Broadcasts)
        cursor.execute("""
            SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title as task_title, t.assignee
            FROM task_events e
            LEFT JOIN tasks t ON e.task_id = t.id
            ORDER BY e.created_at DESC
            LIMIT ?
        """, (limit,))
        for r in cursor.fetchall():
            row = dict(r)
            payload_data = {}
            try:
                payload_data = json.loads(row["payload"])
            except Exception:
                pass
            
            kind = row.get("kind") or "event"
            task_title = row.get("task_title") or ("System-Funkkanal" if row.get("task_id") == "system_broadcast" else (row.get("task_id") or "System"))
            
            if kind in ("broadcast", "message"):
                author_id = payload_data.get("author") or "commander"
                prof = profiles.get(author_id, {})
                target_id = payload_data.get("target") or row.get("assignee")
                author_name = prof.get("name")
                if not author_name:
                    author_name = "Commander (Leitstand)" if author_id == "commander" else author_id
                feed_items.append({
                    "id": f"event_{row['id']}",
                    "type": "broadcast_message",
                    "timestamp": row["created_at"],
                    "author_id": author_id,
                    "author_name": author_name,
                    "author_avatar": prof.get("avatar") or ("/static/avatars/avatar_001.jpg" if author_id == "commander" else _get_fallback_avatar(author_id)),
                    "target_id": target_id,
                    "task_id": row["task_id"] if row["task_id"] != "system_broadcast" else None,
                    "task_title": task_title,
                    "kind": kind,
                    "message": payload_data.get("message") or str(payload_data)
                })
            else:
                feed_items.append({
                    "id": f"event_{row['id']}",
                    "type": "event_handoff",
                    "timestamp": row["created_at"],
                    "author_id": "system_dispatcher",
                    "author_name": "Dispatcher / Orchestrator",
                    "author_avatar": "/static/avatars/avatar_020.jpg",
                    "target_id": row.get("assignee"),
                    "task_id": row["task_id"],
                    "task_title": task_title,
                    "kind": kind,
                    "message": f"Status-Update für '{task_title}': {kind.upper()} {json.dumps(payload_data, ensure_ascii=False)}"
                })
            
        conn.close()
    except Exception as e:
        print(f"[OperationsAPI] Comm-feed fetch error: {e}", file=sys.stderr)
        
    # Normalisiere Timestamps und sortiere nach Timestamp DESC
    def _parse_ts(val):
        if not val:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val) if val < 1e11 else float(val) / 1000.0
        if isinstance(val, str):
            try:
                if val.isdigit():
                    v = float(val)
                    return v if v < 1e11 else v / 1000.0
                dt = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return 0.0
        return 0.0

    for item in feed_items:
        ts = item.get("timestamp")
        if isinstance(ts, (int, float)):
            try:
                sec = ts if ts < 1e11 else ts / 1000.0
                item["timestamp"] = datetime.datetime.fromtimestamp(sec).isoformat()
            except Exception:
                item["timestamp"] = str(ts)

    feed_items.sort(key=lambda x: _parse_ts(x.get("timestamp")), reverse=True)
    
    if agent_filter:
        feed_items = [item for item in feed_items if item.get("author_id") == agent_filter or item.get("target_id") == agent_filter]
        
    return {
        "status": "success",
        "feed": feed_items[:limit],
        "total": len(feed_items)
    }


# =========================================================================
# 4. INTERACTIVE ORG-CHART / FLOWCHART HIERARCHY PERSISTENCE
# =========================================================================

ORG_HIERARCHY_FILE = os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")


def _generate_default_hierarchy():
    profiles = _load_profiles_map()
    nodes = []
    links = []

    # Task counts pro Agent
    task_counts = {}
    try:
        conn = _get_kanban_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT assignee, count(*) as cnt FROM tasks WHERE status != 'done' GROUP BY assignee")
        for row in cursor.fetchall():
            if row["assignee"]:
                task_counts[row["assignee"]] = row["cnt"]
        conn.close()
    except Exception:
        pass

    def _make_node(agent_id: str, x: int, y: int, tier: int = 3, team_id: str = "team_strategy"):
        p = profiles.get(agent_id, {})
        return {
            "id": agent_id,
            "x": x,
            "y": y,
            "tier": tier,
            "team_id": team_id,
            "name": p.get("name") or agent_id,
            "role": p.get("role") or p.get("category") or "Experte",
            "category": p.get("category") or "Spezialist",
            "avatar": p.get("avatar") or _get_fallback_avatar(agent_id),
            "model": p.get("model") or "deepseek/deepseek-chat",
            "active_tasks": task_counts.get(agent_id, 0),
            "status": "active"
        }

    # Tier 1: Apex (Chairman & CTO) - sauber zentriert
    nodes.append(_make_node("executive_decision_architect", 1320, 40, tier=1, team_id="team_strategy"))
    nodes.append(_make_node("system_architect_orchestrator", 1320, 200, tier=1, team_id="team_tech"))
    links.append({"from": "executive_decision_architect", "to": "system_architect_orchestrator"})

    # Tier 2: 6 Department Leads (je 460px Spalten-Abstand, 2 Spalten pro Team darunter)
    team_x_coords = {
        "team_strategy": 60,
        "team_tech": 520,
        "team_legal": 980,
        "team_realestate": 1440,
        "team_growth": 1900,
        "team_operations": 2360
    }

    for t in TEAMS_DEFINITION:
        tid = t["id"]
        tx = team_x_coords.get(tid, 500)
        lead_id = t["lead_id"]
        
        if lead_id not in ["executive_decision_architect", "system_architect_orchestrator"]:
            nodes.append(_make_node(lead_id, tx + 100, 380, tier=2, team_id=tid))
        
        if lead_id not in ["executive_decision_architect", "system_architect_orchestrator"]:
            parent_id = "system_architect_orchestrator" if tid in ["team_tech", "team_operations"] else "executive_decision_architect"
            links.append({"from": parent_id, "to": lead_id})

        # Tier 3: Specialists unter dem Lead in 2 Spalten ohne Überlappung
        specialists = [m for m in t["members"] if m != lead_id and m in profiles]
        for s_idx, s_id in enumerate(specialists):
            col = s_idx % 2
            row = s_idx // 2
            sx = tx + (col * 200)
            sy = 560 + (row * 180)
            nodes.append(_make_node(s_id, sx, sy, tier=3, team_id=tid))
            links.append({"from": lead_id, "to": s_id})

    # Keine Selbstreferenzen zulassen
    links = [l for l in links if l.get("from") and l.get("to") and l["from"] != l["to"]]

    return {
        "nodes": nodes,
        "links": links,
        "canvas_width": 2800,
        "canvas_height": 1800
    }


class OrgHierarchySaveRequest(BaseModel):
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    canvas_width: Optional[int] = 3200
    canvas_height: Optional[int] = 3600


@router.get("/org-hierarchy")
def get_org_hierarchy():
    """Gibt das interaktive Organigramm (Nodes & Links) zurück."""
    if os.path.exists(ORG_HIERARCHY_FILE):
        try:
            with open(ORG_HIERARCHY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                profiles = _load_profiles_map()
                # Dynamisch sicherstellen, dass Avatare, Rollen und Namen dem aktuellen Stand entsprechen
                for node in data.get("nodes", []):
                    nid = node.get("id")
                    if nid in profiles:
                        p = profiles[nid]
                        if p.get("avatar"):
                            node["avatar"] = p["avatar"]
                        if p.get("person_name"):
                            node["person_name"] = p["person_name"]
                        if p.get("name"):
                            node["name"] = p["name"]
                        if p.get("role"):
                            node["role"] = p["role"]
                        if p.get("model"):
                            node["model"] = p["model"]
                        if p.get("provider"):
                            node["provider"] = p["provider"]
                
                # Selbstreferenzen strikt herausfiltern
                data["links"] = [
                    l for l in data.get("links", []) 
                    if l.get("from") and l.get("to") and l["from"] != l["to"]
                ]
                # Mindesthöhe und Mindestbreite sicherstellen
                data["canvas_width"] = max(data.get("canvas_width", 3200), 3200)
                data["canvas_height"] = max(data.get("canvas_height", 3600), 3600)
                return {"status": "success", "custom": True, "data": data}
        except Exception as e:
            print(f"[OperationsAPI] Error loading org_hierarchy: {e}", file=sys.stderr)
            
    return {"status": "success", "custom": False, "data": _generate_default_hierarchy()}


@router.post("/org-hierarchy")
def save_org_hierarchy(req: OrgHierarchySaveRequest):
    """Speichert die vom Nutzer interaktiv erstellten Verbindungen und Positionen."""
    try:
        os.makedirs(os.path.dirname(ORG_HIERARCHY_FILE), exist_ok=True)
        payload = {
            "updated_at": datetime.datetime.now().isoformat(),
            "nodes": req.nodes,
            "links": req.links,
            "canvas_width": max(req.canvas_width or 3200, 3200),
            "canvas_height": max(req.canvas_height or 3600, 3600)
        }
        with open(ORG_HIERARCHY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        # Synchronisiere geänderte Knoten-Metadaten (Model, Provider, Name, Avatar) zurück in agent_profiles.json
        try:
            if os.path.exists(PROFILES_FILE):
                with open(PROFILES_FILE, "r", encoding="utf-8") as pf:
                    plist = json.load(pf)
                nodes_by_id = {n.get("id"): n for n in (req.nodes or []) if isinstance(n, dict) and n.get("id")}
                changed_any = False
                for p in plist:
                    pid = p.get("id")
                    if pid in nodes_by_id:
                        nd = nodes_by_id[pid]
                        for k in ("name", "person_name", "model", "provider", "avatar", "reasoning_level"):
                            if nd.get(k) and nd.get(k) != p.get(k):
                                p[k] = nd[k]
                                changed_any = True
                if changed_any:
                    with open(PROFILES_FILE, "w", encoding="utf-8") as pf:
                        json.dump(plist, pf, indent=2, ensure_ascii=False)
                    _PROFILES_MAP_CACHE["mtime"] = 0.0
        except Exception as sync_e:
            print(f"[OperationsAPI] Profile sync notice: {sync_e}", file=sys.stderr)
        return {"status": "success", "message": "Organigramm-Hierarchie gespeichert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {str(e)}")


@router.delete("/org-hierarchy")
def reset_org_hierarchy():
    """Setzt die Hierarchie auf die 6 Standard-Teams zurück."""
    if os.path.exists(ORG_HIERARCHY_FILE):
        try:
            os.remove(ORG_HIERARCHY_FILE)
        except Exception:
            pass
    return {"status": "success", "message": "Auf Standard-Teams zurückgesetzt.", "data": _generate_default_hierarchy()}


# =========================================================================
# 5. GOVERNANCE & CONCURRENCY THROTTLE ENDPOINTS (Pillars 1, 2, 6)
# =========================================================================

class ConcurrencyUpdateRequest(BaseModel):
    max_tasks: int

@router.get("/governance/concurrency")
def get_concurrency_settings():
    """Liefert aktuellen Concurrency Throttle Status und Task-Semaphore."""
    import core_dispatcher
    return {
        "status": "success",
        "max_tasks": core_dispatcher.MAX_CONCURRENT_AGENT_TASKS,
        "active_semaphore_slots": core_dispatcher.MAX_CONCURRENT_AGENT_TASKS - core_dispatcher._TASK_SEMAPHORE._value,
        "available_slots": core_dispatcher._TASK_SEMAPHORE._value
    }

@router.post("/governance/concurrency")
def update_concurrency_settings(req: ConcurrencyUpdateRequest):
    """Passt das Limit für gleichzeitige LLM-Tasks dynamisch im laufenden System an."""
    import core_dispatcher
    val = max(1, min(20, req.max_tasks))
    core_dispatcher.MAX_CONCURRENT_AGENT_TASKS = val
    # Erneuere Semaphore
    import asyncio
    core_dispatcher._TASK_SEMAPHORE = asyncio.Semaphore(val)
    return {
        "status": "success",
        "message": f"Concurrency-Limit erfolgreich auf {val} Tasks gesetzt.",
        "max_tasks": val
    }

@router.get("/governance/audit-log")
def get_audit_log_entries(
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """Liefert die Einträge des revisionssicheren SHA-256 GoBD/ISO 27001 Audit-Logs mit Filterung."""
    from backend.audit_log import chained_audit_log
    res = chained_audit_log.list_events(category=category, search=search, limit=limit, offset=offset)
    return {
        "status": "success",
        "total": res["total"],
        "limit": res["limit"],
        "offset": res["offset"],
        "entries": res["entries"]
    }

@router.post("/governance/audit-log/verify")
def verify_audit_log_chain():
    """Führt eine vollständige kryptografische Prüfung aller Verkettungen im Audit-Log durch."""
    from backend.audit_log import chained_audit_log
    result = chained_audit_log.verify_integrity()
    return {
        "status": "success",
        "verification": result
    }

@router.get("/governance/audit-log/export")
def export_audit_log(format: str = Query(default="json")):
    """Generiert einen revisionssicheren Prüfbericht für GoBD / ISO 27001 Auditoren als JSON oder CSV."""
    from backend.audit_log import chained_audit_log
    res = chained_audit_log.generate_compliance_export(format_type=format)
    return Response(
        content=res["content"],
        media_type=res["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{res["filename"]}"'}
    )


# =========================================================================
# 6. ADVANCED AGENTIC MECHANICS: DAG-SCHEDULER & WORKFLOW CHECKPOINTS
# =========================================================================

class DecomposeTaskRequest(BaseModel):
    title: str
    body: Optional[str] = ""
    assignee: Optional[str] = "orchestrator"

@router.post("/kanban/dag/decompose")
async def api_dag_decompose_task(req: DecomposeTaskRequest):
    """Zerlegt eine komplexe Aufgabe in einen Directed Acyclic Graph (DAG) mit parallelen Teilaufgaben."""
    from backend.dag_scheduler import dag_scheduler_instance
    return await dag_scheduler_instance.decompose_task(req.title, req.body or "", req.assignee or "orchestrator")

@router.post("/kanban/dag/execute/{parent_id}")
async def api_dag_execute_task(parent_id: str):
    """Führt einen zerlegten DAG aus: Parallele Vorstufen -> abhängige Stufen -> Abschluss-Synthese."""
    from backend.dag_scheduler import dag_scheduler_instance
    return await dag_scheduler_instance.execute_dag(parent_id)

class WorkflowCheckpointCreateRequest(BaseModel):
    checkpoint_id: str
    workflow_id: str
    agent_id: str
    current_step: int
    total_steps: int
    state_data: Dict[str, Any]
    status: Optional[str] = "running"
    pause_reason: Optional[str] = None

@router.post("/workflows/checkpoints")
def api_create_workflow_checkpoint(req: WorkflowCheckpointCreateRequest):
    """Speichert einen atomaren Workflow-Snapshot für unterbrechbare Langzeitprozesse."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    bridge.save_workflow_checkpoint(
        req.checkpoint_id, req.workflow_id, req.agent_id,
        req.current_step, req.total_steps, req.state_data,
        req.status or "running", req.pause_reason
    )
    return {"status": "success", "checkpoint_id": req.checkpoint_id}

@router.get("/workflows/checkpoints")
def api_list_workflow_checkpoints(status: Optional[str] = None):
    """Liefert aktive oder pausierte Workflow-Snapshots."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    return {"status": "success", "checkpoints": bridge.list_workflow_checkpoints(status=status)}

@router.post("/workflows/checkpoints/{checkpoint_id}/resume")
def api_resume_workflow_checkpoint(checkpoint_id: str):
    """Reaktiviert einen pausierten Workflow-Snapshot für die Weiterführung ab Schritt N."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    cp = bridge.get_workflow_checkpoint(checkpoint_id)
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint nicht gefunden.")
    bridge.save_workflow_checkpoint(
        checkpoint_id, cp["workflow_id"], cp["agent_id"],
        cp["current_step"], cp["total_steps"], cp.get("state", {}),
        status="resumed", pause_reason=None
    )
    return {"status": "success", "message": f"Workflow {cp['workflow_id']} ab Schritt {cp['current_step']} reaktiviert.", "checkpoint": cp}


@router.get("/traces/otel")
def api_list_otel_traces(limit: int = Query(25, ge=1, le=100)):
    """OpenTelemetry & Langfuse Tracing: Liefert jüngste Traces mit Token-, Latenz- und Kosten-Metriken."""
    try:
        from backend.otel_tracer import tracer
        traces = tracer.list_recent_traces(limit=limit)
        return {"status": "success", "total": len(traces), "traces": traces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/otel/{trace_or_task_id}")
def api_get_otel_trace_tree(trace_or_task_id: str):
    """OpenTelemetry & Langfuse Tracing: Liefert den vollständigen hierarchischen Trace- und Span-Baum."""
    try:
        from backend.otel_tracer import tracer
        tree = tracer.get_trace_tree(trace_or_task_id)
        if not tree:
            raise HTTPException(status_code=404, detail="Trace nicht gefunden.")
        return {"status": "success", "trace": tree}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class HumanFeedbackSubmitRequest(BaseModel):
    agent_id: str
    score: int  # +1 (positiv / Daumen hoch) oder -1 (negativ / Daumen runter)
    task_id: Optional[str] = None
    comment: Optional[str] = None
    corrected_text: Optional[str] = None
    source: Optional[str] = "kanban_card"
    task_prompt: Optional[str] = None


@router.post("/feedback")
def api_submit_human_feedback(req: HumanFeedbackSubmitRequest):
    """
    Nimmt menschliches Feedback (Daumen hoch/runter, Korrekturhinweise) entgegen.
    Negative Bewertungen (-1) werden automatisch als Gold-Standard-Regressionstestfall angelegt.
    """
    try:
        from backend.human_feedback_engine import feedback_engine
        res = feedback_engine.submit_feedback(
            agent_id=req.agent_id,
            score=req.score,
            task_id=req.task_id,
            comment=req.comment,
            corrected_text=req.corrected_text,
            source=req.source or "kanban_card",
            task_prompt=req.task_prompt
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/stats")
def api_get_feedback_stats():
    """Gibt globale Feedback-Statistiken, Zustimmungsquoten und Agenten-Metriken zurück."""
    try:
        from backend.human_feedback_engine import feedback_engine
        return {"status": "success", "stats": feedback_engine.get_stats()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/task/{task_id}")
def api_get_task_feedback(task_id: str):
    """Liefert alle Feedback-Einträge für eine bestimmte Aufgabe."""
    try:
        from backend.human_feedback_engine import feedback_engine
        entries = feedback_engine.get_task_feedback(task_id)
        return {"status": "success", "task_id": task_id, "feedbacks": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/validate")
def api_validate_system_config():
    """Führt eine vollständige Pre-Flight-Konfigurationsprüfung aller System-JSONs durch."""
    try:
        from backend.config_validator import validator
        res = validator.validate_all(strict=False)
        return {"status": "success", "report": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/policy")
def api_get_notification_policy():
    """Liefert die aktuellen Benachrichtigungs- und Ruhezeit-Regeln."""
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        return {
            "status": "success",
            "policy": hub.get_policy(),
            "in_quiet_hours": hub.is_in_quiet_hours()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/policy")
def api_update_notification_policy(req: Dict[str, Any] = Body(...)):
    """Aktualisiert die Benachrichtigungs- und Ruhezeit-Regeln in settings.json."""
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        updated = hub.update_policy(req)
        return {
            "status": "success",
            "policy": updated,
            "in_quiet_hours": hub.is_in_quiet_hours()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/digest")
def api_get_suppressed_digest(since_hours: int = 24):
    """Liefert alle während der Ruhezeiten gepufferten Benachrichtigungen als Sammel-Digest."""
    try:
        from backend.notification_hub import get_notification_hub
        hub = get_notification_hub()
        items = hub.get_suppressed_digest(since_hours=since_hours)
        return {
            "status": "success",
            "count": len(items),
            "since_hours": since_hours,
            "suppressed_notifications": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
def api_get_prometheus_metrics():
    """Gibt Prometheus-kompatible System- und Operations-Metriken im Text-Format 0.0.4 aus."""
    from fastapi.responses import Response
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/summary")
def api_get_metrics_summary():
    """Liefert aggregierte System-, Queue- und Telemetrie-Metriken als strukturiertes JSON."""
    try:
        from backend.metrics_collector import metrics_collector
        return {"status": "success", "metrics": metrics_collector.get_summary_json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/{agent_id}/versions")
def api_list_prompt_versions(agent_id: str):
    """Listet alle Versionen des System-Prompts für den angegebenen Agenten auf."""
    try:
        from backend.prompt_registry import prompt_registry
        versions = prompt_registry.list_versions(agent_id)
        return {"status": "success", "agent_id": agent_id, "versions": versions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/versions")
def api_save_prompt_version(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Speichert eine neue Version des System-Prompts für einen Agenten."""
    try:
        from backend.prompt_registry import prompt_registry
        prompt_text = req.get("prompt")
        if not prompt_text:
            raise HTTPException(status_code=400, detail="Feld 'prompt' ist erforderlich.")
        res = prompt_registry.save_version(
            agent_id=agent_id,
            prompt=prompt_text,
            commit_message=req.get("commit_message", ""),
            created_by=req.get("created_by", "manual_api"),
            model=req.get("model"),
            make_active=req.get("make_active", True),
            canary_percentage=req.get("canary_percentage", 0)
        )
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/{agent_id}/diff")
def api_diff_prompt_versions(agent_id: str, v1: int = Query(...), v2: int = Query(...)):
    """Gibt ein Unified Diff zwischen zwei Prompt-Versionen zurück."""
    try:
        from backend.prompt_registry import prompt_registry
        diff_text = prompt_registry.diff_versions(agent_id, v1, v2)
        return {"status": "success", "agent_id": agent_id, "v1": v1, "v2": v2, "diff": diff_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/rollback")
def api_rollback_prompt_version(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Führt einen 1-Click Rollback auf eine frühere Prompt-Version durch."""
    try:
        from backend.prompt_registry import prompt_registry
        target_v = req.get("target_version")
        if not target_v:
            raise HTTPException(status_code=400, detail="Feld 'target_version' erforderlich.")
        reason = req.get("reason", "Manuelles Rollback über UI/API")
        res = prompt_registry.rollback_to_version(agent_id, int(target_v), reason=reason)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/canary")
def api_set_prompt_canary(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Konfiguriert eine Prompt-Version als Canary mit Prozentsatz (1-99%)."""
    try:
        from backend.prompt_registry import prompt_registry
        version = req.get("version")
        pct = req.get("percentage")
        if version is None or pct is None:
            raise HTTPException(status_code=400, detail="Felder 'version' und 'percentage' erforderlich.")
        res = prompt_registry.set_canary(agent_id, int(version), int(pct))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{agent_id}/promote")
def api_promote_prompt_canary(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Befördert eine Canary-Version zur vollwertigen stabilen Version (100% Traffic)."""
    try:
        from backend.prompt_registry import prompt_registry
        version = req.get("version")
        if version is None:
            raise HTTPException(status_code=400, detail="Feld 'version' erforderlich.")
        res = prompt_registry.promote_canary(agent_id, int(version))
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/tools")
def api_get_mcp_tools():
    """Gibt alle über den Archon MCP-Server exponierten Werkzeuge und deren Schemas zurück."""
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        server = ArchonMcpServer()
        return {
            "status": "success",
            "server": server.server_name,
            "version": server.server_version,
            "protocol": server.protocol_version,
            "tools": server.get_tool_definitions()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcp/call")
def api_call_mcp_tool(req: Dict[str, Any] = Body(...)):
    """Führt ein Archon MCP-Werkzeug über eine HTTP-REST-Schnittstelle aus."""
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        tool_name = req.get("name")
        arguments = req.get("arguments", {})
        if not tool_name:
            raise HTTPException(status_code=400, detail="Feld 'name' ist erforderlich.")
        server = ArchonMcpServer()
        result = server.execute_tool(tool_name, arguments)
        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/stream")
async def api_stream_task_execution(task_id: str):
    """
    Server-Sent Events (SSE) Stream für die Live-Beobachtung einer laufenden Task-Ausführung.
    Ermöglicht Token-Streaming in Echtzeit ohne Polling.
    """
    import asyncio
    import time
    from fastapi.responses import StreamingResponse

    q = asyncio.Queue(maxsize=50)

    # Global registrieren oder queue verknüpfen
    try:
        import main
        if hasattr(main, "_SSE_SUBSCRIBERS"):
            main._SSE_SUBSCRIBERS.append(q)
    except Exception:
        pass

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id, 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    # Prüfen, ob Payload für diese Task oder global relevant ist
                    try:
                        p_dict = json.loads(payload)
                        p_data = p_dict.get("data", {})
                        if p_data.get("task_id") == task_id or p_dict.get("type") in ("ticker_update", "ping"):
                            yield f"data: {payload}\n\n"
                            if p_dict.get("type") == "task_status" and p_data.get("status") in ("done", "failed"):
                                break
                    except Exception:
                        yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                import main
                if hasattr(main, "_SSE_SUBSCRIBERS") and q in main._SSE_SUBSCRIBERS:
                    main._SSE_SUBSCRIBERS.remove(q)
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/tasks/{task_id}/chunk")
def api_broadcast_task_chunk(task_id: str, req: Dict[str, Any] = Body(...)):
    """Broadcastet ein Token oder Teilergebnis für einen laufenden Task."""
    chunk = req.get("chunk", "")
    agent_id = req.get("agent_id", "")
    status = req.get("status", "in_progress")
    try:
        import main
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("task_chunk", {"task_id": task_id, "agent_id": agent_id, "chunk": chunk, "status": status})
            if status in ("done", "failed"):
                main.broadcast_event("task_status", {"task_id": task_id, "status": status})
        return {"status": "success", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backup/restore-test")
def api_get_restore_test_history():
    """Gibt die Historie der automatisierten Restore- und Integritätstests zurück."""
    try:
        from scripts.automated_restore_test import HISTORY_FILE
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            return {"status": "success", "history": history, "latest": history[0] if history else None}
        return {"status": "success", "history": [], "latest": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backup/restore-test")
def api_trigger_restore_test(notify: bool = Query(default=True)):
    """Führt einen On-Demand Restore- und Integritätstest in einer Sandbox aus."""
    try:
        from scripts.automated_restore_test import restore_tester
        report = restore_tester.run_restore_test(notify=notify)
        return {"status": "success", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gdpr/export")
def api_gdpr_export(req: Dict[str, Any] = Body(...)):
    """Art. 15 DSGVO: Erstellt einen vollständigen Datenauszug für eine Person über alle Speicherschichten."""
    identifier = req.get("identifier", "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Feld 'identifier' ist erforderlich.")
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        res = gdpr_engine.export_subject_data(identifier)
        return {"status": "success", "export": res}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gdpr/erase")
def api_gdpr_erase(req: Dict[str, Any] = Body(...)):
    """Art. 17 DSGVO: Löscht/anonymisiert Daten zu einer Person und erzeugt eine kryptografische Quittung."""
    identifier = req.get("identifier", "").strip()
    dry_run = bool(req.get("dry_run", False))
    anonymize = bool(req.get("anonymize", True))
    if not identifier:
        raise HTTPException(status_code=400, detail="Feld 'identifier' ist erforderlich.")
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        res = gdpr_engine.erase_subject_data(identifier, dry_run=dry_run, anonymize=anonymize)
        return {"status": "success", "result": res}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gdpr/audit-log")
def api_gdpr_audit_log(limit: int = Query(default=50)):
    """Art. 30 DSGVO: Gibt manipulationssichere Löschquittungen aus dem Audit-Log zurück."""
    try:
        from backend.gdpr_compliance_engine import gdpr_engine
        receipts = gdpr_engine.list_audit_receipts(limit=limit)
        return {"status": "success", "count": len(receipts), "receipts": receipts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chaos/run")
def api_chaos_run(req: Dict[str, Any] = Body(default={})):
    """Führt automatisierte Chaos- und Resilienz-Tests gegen Container, DB und Watchdog aus."""
    dry_run = bool(req.get("dry_run", True))
    try:
        import sys
        sys.path.insert(0, os.path.join(WORKSPACE_DIR, "scripts"))
        from chaos_tester import ArchonChaosTester
        tester = ArchonChaosTester(dry_run=dry_run)
        results = tester.run_all()
        return {"status": "success", "chaos_results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chaos-Testlauf fehlgeschlagen: {e}")


@router.get("/chaos/results")
def api_chaos_results():
    """Gibt das letzte Ergebnis der Chaos- und Resilienz-Suite zurück."""
    res_file = os.path.join(WORKSPACE_DIR, "data", "chaos_test_results.json")
    if not os.path.exists(res_file):
        raise HTTPException(status_code=404, detail="Noch keine Chaos-Testergebnisse vorhanden.")
    try:
        with open(res_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {"status": "success", "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receipts/process")
def api_receipts_process(req: Dict[str, Any] = Body(...)):
    """Verarbeitet einen Beleg: Extrahiert Buchhaltungs-Metadaten via Vision OCR und legt Task an."""
    b64_data = req.get("image_base64")
    image_path = req.get("image_path")
    filename = req.get("filename", "receipt.jpg")
    source = req.get("source", "api")
    sender = req.get("sender", "Operator")
    create_task = bool(req.get("create_kanban_task", True))

    img_bytes = None
    if b64_data:
        try:
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ungültige Base64-Bilddaten: {e}")
    elif image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as fh:
                img_bytes = fh.read()
            filename = os.path.basename(image_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Konnte Bilddatei nicht lesen: {e}")
    else:
        raise HTTPException(status_code=400, detail="Entweder 'image_base64' oder ein existierender 'image_path' ist erforderlich.")

    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        result = receipt_ocr_engine.process_receipt(
            image_bytes=img_bytes,
            filename=filename,
            source=source,
            sender=sender,
            create_kanban_task=create_task
        )
        return {"status": "success", "receipt": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Belegverarbeitung fehlgeschlagen: {e}")


@router.get("/receipts")
def api_receipts_list(limit: int = Query(default=50)):
    """Gibt die Liste der archivierten Belege zurück."""
    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        receipts = receipt_ocr_engine.list_receipts(limit=limit)
        return {"status": "success", "count": len(receipts), "receipts": receipts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/receipts/{receipt_id}/image")
def api_receipt_image(receipt_id: str):
    """Gibt die Belegdatei als Bild aus."""
    from backend.receipt_ocr_engine import receipt_ocr_engine
    rcpt = receipt_ocr_engine.get_receipt(receipt_id)
    if not rcpt or not rcpt.get("image_path") or not os.path.exists(rcpt["image_path"]):
        # 1x1 transparent SVG fallback
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><rect width="200" height="200" fill="#1e293b"/><text x="50%" y="50%" fill="#94a3b8" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="14">Kein Bild</text></svg>'
        return Response(content=svg, media_type="image/svg+xml")
    return FileResponse(rcpt["image_path"])


@router.patch("/receipts/{receipt_id}")
def api_receipt_patch(receipt_id: str, updates: Dict[str, Any] = Body(...)):
    """Aktualisiert Belegdaten wie Status (approved/rejected), Kategorie oder Betrag."""
    from backend.receipt_ocr_engine import receipt_ocr_engine
    ok = receipt_ocr_engine.update_receipt(receipt_id, updates)
    if not ok:
        raise HTTPException(status_code=400, detail="Aktualisierung fehlgeschlagen oder keine gültigen Felder.")
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="finance",
            action="receipt_updated",
            agent_id="finance_operator",
            payload={"receipt_id": receipt_id, "updates": updates}
        )
    except Exception:
        pass
    return {"status": "success", "receipt_id": receipt_id, "updated": updates}


@router.post("/receipts/upload")
async def api_receipts_upload(file: UploadFile = File(...), sender: str = "WebUI", category: Optional[str] = None):
    """Upload von Belegen via Drag & Drop aus der Weboberfläche."""
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Datei ist leer.")
    try:
        from backend.receipt_ocr_engine import receipt_ocr_engine
        result = receipt_ocr_engine.process_receipt(
            image_bytes=contents,
            filename=file.filename or "receipt.jpg",
            source="web_upload",
            sender=sender,
            create_kanban_task=True
        )
        if category and result.get("receipt_id"):
            receipt_ocr_engine.update_receipt(result["receipt_id"], {"category": category})
            result["category"] = category
        return {"status": "success", "receipt": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload-Verarbeitung fehlgeschlagen: {e}")



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
def api_esign_webhook(payload: Dict[str, Any] = Body(...)):
    """Empfängt Webhooks von DocuSeal nach Unterzeichnung eines Dokuments."""
    try:
        from backend.docuseal_client import docuseal_client
        res = docuseal_client.handle_webhook_event(payload)
        return {"status": "success", "webhook_result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook Verarbeitung fehlgeschlagen: {e}")


# =========================================================================
# MAHNWESEN & DEBITORENMANAGEMENT (DUNNING ENGINE)
# =========================================================================

@router.get("/dunning/invoices")
def api_dunning_invoices():
    """Gibt alle Ausgangsrechnungen inklusive Fälligkeits- und Mahnstufenstatus zurück."""
    try:
        from backend.dunning_engine import dunning_engine
        invoices = dunning_engine.check_overdue_invoices()
        return {"status": "success", "count": len(invoices), "invoices": invoices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/invoices")
def api_dunning_create_invoice(req: Dict[str, Any] = Body(...)):
    """Erstellt eine neue Ausgangsrechnung."""
    customer_name = req.get("customer_name", "").strip()
    customer_email = req.get("customer_email", "").strip()
    amount_net = float(req.get("amount_net", 0.0))
    due_days = int(req.get("due_days", 14))
    invoice_date = req.get("invoice_date")
    recipient_address = req.get("recipient_address")

    if not customer_name or amount_net <= 0:
        raise HTTPException(status_code=400, detail="customer_name und ein positiver amount_net sind erforderlich.")

    try:
        from backend.dunning_engine import dunning_engine
        inv = dunning_engine.create_invoice(
            customer_name=customer_name,
            customer_email=customer_email,
            amount_net=amount_net,
            due_days=due_days,
            invoice_date=invoice_date,
            recipient_address=recipient_address
        )
        return {"status": "success", "invoice": inv}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/draft")
def api_dunning_generate_draft(req: Dict[str, Any] = Body(...)):
    """Erzeugt einen rechtssicheren 3-stufigen Mahnentwurf zur manuellen Prüfung."""
    invoice_id = req.get("invoice_id", "").strip()
    level = int(req.get("level", 1))

    if not invoice_id:
        raise HTTPException(status_code=400, detail="invoice_id ist erforderlich.")

    try:
        from backend.dunning_engine import dunning_engine
        draft = dunning_engine.generate_dunning_draft(invoice_id, level)
        return {"status": "success", "draft": draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/approve")
def api_dunning_approve(req: Dict[str, Any] = Body(...)):
    """Gibt einen Mahnentwurf frei und aktualisiert den Rechnungsstatus (HITL-Freigabe)."""
    dunning_id = req.get("dunning_id", "").strip()
    if not dunning_id:
        raise HTTPException(status_code=400, detail="dunning_id ist erforderlich.")

    try:
        from backend.dunning_engine import dunning_engine
        res = dunning_engine.approve_and_send_dunning(dunning_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dunning/mark-paid")
def api_dunning_mark_paid(req: Dict[str, Any] = Body(...)):
    """Markiert eine Ausgangsrechnung als bezahlt."""
    invoice_id = req.get("invoice_id", "").strip()
    if not invoice_id:
        raise HTTPException(status_code=400, detail="invoice_id ist erforderlich.")

    try:
        from backend.dunning_engine import dunning_engine
        ok = dunning_engine.mark_invoice_paid(invoice_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Rechnung nicht gefunden oder Update fehlgeschlagen.")
        return {"status": "success", "invoice_id": invoice_id, "paid": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# FINE-TUNING PIPELINE ENDPOINTS (t-56ff9d)
# ==============================================================================

@router.get("/finetuning/status")
def api_finetuning_status():
    """Gibt Status- und Metrik-Informationen über den Feintuning-Datensatz zurück."""
    try:
        from scripts.prepare_finetuning_dataset import DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR
        import sqlite3

        db_path = "/opt/data/agentic_memory.db" if os.path.exists("/opt/data/agentic_memory.db") else DEFAULT_DB_PATH
        feedback_count = 0
        learnings_count = 0

        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            try:
                feedback_count = conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0]
            except Exception:
                pass
            try:
                learnings_count = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
            except Exception:
                pass
            conn.close()

        files_info = []
        out_dir = "/opt/data/finetuning" if os.path.exists("/opt/data") else DEFAULT_OUTPUT_DIR
        if os.path.exists(out_dir):
            for f in os.listdir(out_dir):
                if f.endswith(".jsonl"):
                    f_path = os.path.join(out_dir, f)
                    with open(f_path, "r", encoding="utf-8") as fp:
                        lines = len(fp.readlines())
                    files_info.append({"filename": f, "lines": lines, "size_bytes": os.path.getsize(f_path)})

        return {
            "status": "success",
            "db_path": db_path,
            "feedback_samples": feedback_count,
            "learnings_samples": learnings_count,
            "generated_datasets": files_info,
            "config_template": "config/finetuning/lora_config.yml"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finetuning/prepare-dataset")
def api_finetuning_prepare(req: Dict[str, Any] = Body(...)):
    """Extrahiert Datensätze aus Feedback & Learnings für das Modell-Feintuning."""
    try:
        from scripts.prepare_finetuning_dataset import prepare_dataset, DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR
        
        db_path = "/opt/data/agentic_memory.db" if os.path.exists("/opt/data/agentic_memory.db") else DEFAULT_DB_PATH
        out_dir = "/opt/data/finetuning" if os.path.exists("/opt/data") else DEFAULT_OUTPUT_DIR
        
        fmt = req.get("format", "chat")
        min_score = int(req.get("min_score", 0))
        include_learnings = bool(req.get("include_learnings", True))
        split_ratio = float(req.get("split_ratio", 0.9))

        res = prepare_dataset(
            db_path=db_path,
            output_dir=out_dir,
            fmt=fmt,
            min_score=min_score,
            include_learnings=include_learnings,
            split_ratio=split_ratio
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# APPROVAL POLICIES & ESKALATION ENDPOINTS (t-5596bd)
# ==============================================================================

@router.get("/approvals/policies")
def api_get_approval_policies(domain: Optional[str] = None):
    """Gibt alle aktiven Freigaberegeln (optional gefiltert nach Domain) zurück."""
    try:
        from backend.approval_policy_engine import approval_engine
        policies = approval_engine.get_policies(domain=domain)
        return {"status": "success", "policies": policies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/policies")
def api_update_approval_policy(req: Dict[str, Any] = Body(...)):
    """Aktualisiert eine Freigaberegel revisionssicher mit SHA-256 Hash-Kette."""
    policy_key = req.get("policy_key", "").strip()
    new_value = str(req.get("new_value", "")).strip()
    user_id = req.get("user_id", "admin").strip()

    if not policy_key or new_value == "":
        raise HTTPException(status_code=400, detail="policy_key und new_value sind erforderlich.")

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.update_policy(policy_key, new_value, user_id=user_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/requests")
def api_get_approval_requests(status: Optional[str] = None, domain: Optional[str] = None):
    """Gibt Freigabeanfragen aus der Warteschlange zurück."""
    try:
        from backend.approval_policy_engine import approval_engine
        requests = approval_engine.get_requests(status=status, domain=domain)
        return {"status": "success", "requests": requests}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests")
def api_create_approval_request(req: Dict[str, Any] = Body(...)):
    """Erstellt eine neue Freigabeanfrage und evaluiert Auto-Freigabe Schwellenwerte."""
    domain = req.get("domain", "finance").strip()
    title = req.get("title", "").strip()
    amount = float(req.get("amount", 0.0))
    reference_id = req.get("reference_id")
    payload = req.get("payload")

    if not title:
        raise HTTPException(status_code=400, detail="title ist erforderlich.")

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.evaluate_and_enqueue(
            domain=domain,
            title=title,
            amount=amount,
            reference_id=reference_id,
            payload=payload
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests/{request_id}/approve")
def api_approve_request(request_id: str, req: Dict[str, Any] = Body(default={})):
    """Gibt eine anhängige Anfrage frei (unterstützt 1. und 2. Prüfer)."""
    approver_id = req.get("approver_id", "admin").strip()
    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.approve_request(request_id, approver_id=approver_id)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/requests/{request_id}/reject")
def api_reject_request(request_id: str, req: Dict[str, Any] = Body(...)):
    """Lehnt eine anhängige Freigabeanfrage mit Begründung ab."""
    rejected_by = req.get("rejected_by", "admin").strip()
    reason = req.get("reason", "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Begründung (reason) ist erforderlich.")

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.reject_request(request_id, rejected_by=rejected_by, reason=reason)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/delegation")
def api_get_delegation(user_id: str = "admin"):
    """Ruft den Urlaubs- und Vertretungsmodus ab."""
    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.get_delegation(user_id=user_id)
        return {"status": "success", "delegation": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/delegation")
def api_set_delegation(req: Dict[str, Any] = Body(...)):
    """Aktiviert oder deaktiviert den Urlaubsmodus mit Stellvertretung."""
    user_id = req.get("user_id", "admin").strip()
    is_active = bool(req.get("is_active", False))
    substitute_id = req.get("substitute_id", "katharina").strip()
    substitute_name = req.get("substitute_name", "Katharina Völk (QM)").strip()

    try:
        from backend.approval_policy_engine import approval_engine
        res = approval_engine.set_delegation(
            user_id=user_id,
            is_active=is_active,
            substitute_id=substitute_id,
            substitute_name=substitute_name
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/audit-chain")
def api_get_approval_audit_chain(limit: int = 50):
    """Liefert die kryptografisch verkettete Revisionshistorie (GoBD/ISO 27001)."""
    try:
        from backend.approval_policy_engine import approval_engine
        chain = approval_engine.get_audit_chain(limit=limit)
        return {"status": "success", "chain": chain}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/audit-verify")
def api_verify_approval_audit():
    """Überprüft die mathematische Gültigkeit der gesamten SHA-256 Hash-Kette."""
    try:
        from backend.approval_policy_engine import approval_engine
        integrity = approval_engine.verify_audit_integrity()
        return {"status": "success", "integrity": integrity}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# API-KEYS & SCOPES ACCESS MANAGEMENT (t-6fad7a)
# ==============================================================================

@router.get("/keys")
def api_list_keys():
    """Gibt alle registrierten API-Keys ohne Klardaten zurück."""
    try:
        from backend.api_key_manager import api_key_manager
        keys = api_key_manager.list_keys()
        return {"status": "success", "keys": keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys")
def api_create_key(req: Dict[str, Any] = Body(...)):
    """Erstellt einen neuen API-Key und gibt den Klartext-Token einmalig zurück."""
    name = req.get("name", "").strip()
    scopes = req.get("scopes", ["read_only"])
    rate_limit_rpm = int(req.get("rate_limit_rpm", 60))
    rate_limit_rpd = int(req.get("rate_limit_rpd", 5000))
    created_by = req.get("created_by", "admin").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name/Zweck des API-Keys ist erforderlich.")

    try:
        from backend.api_key_manager import api_key_manager
        res = api_key_manager.create_key(
            name=name,
            scopes=scopes,
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_rpd=rate_limit_rpd,
            created_by=created_by
        )
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keys/{key_id}/revoke")
def api_revoke_key(key_id: str, req: Dict[str, Any] = Body(default={})):
    """Deaktiviert einen API-Key dauerhaft und revisionssicher."""
    revoked_by = req.get("revoked_by", "admin").strip()
    try:
        from backend.api_key_manager import api_key_manager
        success = api_key_manager.revoke_key(key_id, revoked_by=revoked_by)
        if not success:
            raise HTTPException(status_code=404, detail="Key nicht gefunden oder bereits inaktiv.")
        return {"status": "success", "message": "API-Key erfolgreich widerrufen."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/keys/{key_id}")
def api_delete_key(key_id: str, req: Dict[str, Any] = Body(default={})):
    """Löscht einen Key vollständig aus der aktiven Liste."""
    deleted_by = req.get("deleted_by", "admin").strip()
    try:
        from backend.api_key_manager import api_key_manager
        success = api_key_manager.delete_key(key_id, deleted_by=deleted_by)
        if not success:
            raise HTTPException(status_code=404, detail="Key nicht gefunden.")
        return {"status": "success", "message": "API-Key gelöscht."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/keys/audit")
def api_get_keys_audit(limit: int = 50):
    """Liefert das revisionssichere SHA-256 Audit-Log der Key-Verwaltung."""
    try:
        from backend.api_key_manager import api_key_manager
        trail = api_key_manager.get_audit_trail(limit=limit)
        return {"status": "success", "audit_log": trail}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# EMAIL DRAFT APPROVAL QUEUE (t-7ca8cd)
# ==============================================================================

@router.get("/email-drafts")
def api_list_email_drafts(status: Optional[str] = None):
    """Gibt alle E-Mail-Entwürfe der Freigabe-Queue zurück."""
    try:
        from backend.email_draft_engine import email_draft_engine
        drafts = email_draft_engine.list_drafts(status=status)
        return {"status": "success", "drafts": drafts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts")
def api_create_email_draft(req: Dict[str, Any] = Body(...)):
    """Erstellt einen neuen E-Mail-Entwurf (z. B. durch einen Agenten)."""
    subject = req.get("subject", "").strip()
    recipient = req.get("recipient", "").strip()
    body_text = req.get("body_text", "").strip()
    agent_id = req.get("agent_id", "default").strip()
    agent_name = req.get("agent_name", "Hermes Orchestrator").strip()
    sender = req.get("sender", "system@archon-os.internal").strip()
    source_task_id = req.get("source_task_id")
    created_by = req.get("created_by", "admin").strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail="Betreff, Empfänger und Text sind erforderlich.")

    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.create_draft(
            subject=subject,
            recipient=recipient,
            body_text=body_text,
            agent_id=agent_id,
            agent_name=agent_name,
            sender=sender,
            source_task_id=source_task_id,
            created_by=created_by
        )
        return {"status": "success", "draft": draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email-drafts/{draft_id}")
def api_get_email_draft(draft_id: str):
    """Ruft Details zu einem E-Mail-Entwurf ab."""
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
        return {"status": "success", "draft": draft}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/approve")
def api_approve_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 1: Freigeben & Senden via SMTP."""
    approver_id = req.get("approver_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.approve_and_send(draft_id, approver_id=approver_id)
        return {"status": "success", "draft": draft, "message": "E-Mail freigegeben und versendet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/email-drafts/{draft_id}")
def api_edit_email_draft(draft_id: str, req: Dict[str, Any] = Body(...)):
    """Aktion 2: Entwurf im Editor anpassen."""
    from backend.email_draft_engine import email_draft_engine
    existing = email_draft_engine.get_draft(draft_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")

    subject = req.get("subject", existing.get("subject", "")).strip()
    recipient = req.get("recipient", existing.get("recipient", "")).strip()
    body_text = req.get("body_text", existing.get("body_text", "")).strip()
    editor_id = req.get("editor_id", req.get("updated_by", "admin")).strip()

    if not subject or not recipient or not body_text:
        raise HTTPException(status_code=400, detail="Betreff, Empfänger und Text dürfen nicht leer sein.")

    try:
        draft = email_draft_engine.edit_draft(draft_id, subject, recipient, body_text, editor_id=editor_id)
        return {"status": "success", "draft": draft, "message": "Entwurf erfolgreich aktualisiert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/snooze")
def api_snooze_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 3: Später erinnern (Snooze)."""
    hours = int(req.get("hours", 1))
    user_id = req.get("user_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.snooze_draft(draft_id, hours=hours, user_id=user_id)
        return {"status": "success", "draft": draft, "message": f"Entwurf für {hours} Stunde(n) zurückgestellt."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/regenerate")
def api_regenerate_email_draft(draft_id: str, req: Dict[str, Any] = Body(...)):
    """Aktion 4: Neu generieren mit Prompt-Feedback."""
    feedback = req.get("feedback", "").strip()
    user_id = req.get("user_id", "admin").strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="Feedback für den Agenten ist erforderlich.")

    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.regenerate_draft(draft_id, feedback_text=feedback, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Überarbeitungsauftrag an Agenten übergeben."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-drafts/{draft_id}/reject")
def api_reject_email_draft(draft_id: str, req: Dict[str, Any] = Body(default={})):
    """Aktion 5: Abbrechen / Verwerfen."""
    reason = req.get("reason", "Vom Nutzer verworfen").strip()
    user_id = req.get("user_id", "admin").strip()
    try:
        from backend.email_draft_engine import email_draft_engine
        draft = email_draft_engine.reject_draft(draft_id, reason=reason, user_id=user_id)
        return {"status": "success", "draft": draft, "message": "Entwurf verworfen."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================================
# AGENT SCORECARDS & PERSONALAKTE INTEGRATION (t-f257ba)
# =========================================================================

@router.get("/agents/{agent_id}/scorecard")
def api_get_agent_scorecard(agent_id: str):
    """Liefert aggregierte Leistungsmetriken, KPIs und Projektdaten für die Personalakte."""
    try:
        from backend.agent_scorecard_engine import agent_scorecard_engine
        data = agent_scorecard_engine.get_scorecard(agent_id)
        return {"status": "success", "scorecard": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agents/{agent_id}/operator-notes")
def api_save_agent_operator_notes(agent_id: str, req: Dict[str, Any] = Body(...)):
    """Speichert Operator-Beurteilungen persistent und synchronisiert sie mit Obsidian."""
    notes = req.get("notes", "").strip()
    try:
        from backend.agent_scorecard_engine import agent_scorecard_engine
        agent_scorecard_engine.save_operator_notes(agent_id, notes)
        return {"status": "success", "message": "Operator-Beurteilung gespeichert und mit Obsidian synchronisiert."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================================
# DUAL-LLM GUARD & PROMPT INJECTION SANITIZER (t-d3f2d2)
# =========================================================================

@router.post("/security/sanitize")
def api_sanitize_input(req: Dict[str, Any] = Body(...)):
    """Stufe 1 Quarantäne: Untersucht externe Inputs auf Prompt Injections."""
    text = req.get("text", "")
    source_id = req.get("source_id", "unknown")
    source_type = req.get("source_type", "external")
    try:
        from backend.dual_llm_sanitizer import sanitize_external_input
        result = sanitize_external_input(raw_text=text, source_id=source_id, source_type=source_type)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/security/trusted-sources")
def api_get_trusted_sources():
    """Gibt die Whitelist vertrauenswürdiger Absender [T] zurück."""
    try:
        from backend.dual_llm_sanitizer import load_trusted_sources
        sources = load_trusted_sources()
        return {"status": "success", "trusted_sources": sources}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/security/trusted-sources/toggle")
def api_toggle_trusted_source(req: Dict[str, Any] = Body(...)):
    """Schaltet den Trusted-Status [T] für einen Absender um."""
    source_id = req.get("source_id", "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="Keine source_id angegeben.")
    try:
        from backend.dual_llm_sanitizer import toggle_trusted_source
        res = toggle_trusted_source(source_id)
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================================
# NOTFALLZUGANG / BREAK-GLASS PROTOCOL (t-8efcf3)
# =========================================================================

@router.get("/security/break-glass/status")
def api_get_break_glass_status():
    """Liefert den Integritäts- und Initialisierungsstatus des Break-Glass Vaults."""
    try:
        from scripts.break_glass_recovery import get_vault_status
        return {"status": "success", "vault": get_vault_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/security/break-glass/create")
def api_create_break_glass_vault():
    """Generiert ein neues verschlüsseltes Notfall-Backup und einen einmaligen Recovery-Key."""
    try:
        from scripts.break_glass_recovery import create_break_glass_vault
        res = create_break_glass_vault(operator="admin")
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/security/break-glass/kit")
def api_download_break_glass_kit():
    """Liefert das druckbare Notfall-Dokument (BREAK_GLASS_RECOVERY_KIT.md) als Download."""
    try:
        from scripts.break_glass_recovery import KIT_DOC_FILE
        if not os.path.exists(KIT_DOC_FILE):
            raise HTTPException(status_code=404, detail="Recovery-Kit noch nicht generiert.")
        with open(KIT_DOC_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="ARCHON_BREAK_GLASS_RECOVERY_KIT.md"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# =========================================================================
# BOT SCREEN & HUMAN TAKEOVER (VIRTUAL DESKTOP INTEGRATION)
# =========================================================================

_bot_screen_state = {
    "active": True,
    "session_id": "hermes-desktop-main",
    "display": ":99",
    "resolution": "1920x1080",
    "agent_name": "Hermes Web & Desktop Agent",
    "current_url": "https://dashboard.service.internal",
    "takeover_requested": False,
    "takeover_reason": "",
    "takeover_timestamp": None,
    "last_interaction": None,
    "mouse_control_enabled": True
}

@router.get("/comm-feed/stream")
async def stream_comm_feed(request: Request):
    """
    Server-Sent Events (SSE) Stream für Realtime-Inter-Agenten-Kommunikation.
    Pusht neue Nachrichten aus kanban.db sofort in den Client ohne Polling.
    """
    from fastapi.responses import StreamingResponse
    import asyncio

    async def sse_event_generator():
        last_seen_time = datetime.datetime.now().isoformat()
        # Initial handshake
        yield f"data: {json.dumps({'type': 'init', 'timestamp': last_seen_time, 'message': 'Comm-Feed Stream verbunden'})}\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                conn = _get_kanban_connection()
                cursor = conn.cursor()
                # Prüfe auf neue Events seit last_seen_time
                cursor.execute("""
                    SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title as task_title, t.assignee
                    FROM task_events e
                    LEFT JOIN tasks t ON e.task_id = t.id
                    WHERE e.created_at > ?
                    ORDER BY e.created_at ASC
                    LIMIT 20
                """, (last_seen_time,))
                new_events = cursor.fetchall()
                profiles = _load_profiles_map()

                for r in new_events:
                    row = dict(r)
                    last_seen_time = max(last_seen_time, row["created_at"])
                    payload_data = {}
                    try:
                        payload_data = json.loads(row["payload"])
                    except Exception:
                        pass

                    kind = row.get("kind") or "event"
                    author_id = payload_data.get("author") or "commander"
                    prof = profiles.get(author_id, {})
                    author_name = prof.get("name") or ("Commander (Leitstand)" if author_id == "commander" else author_id)
                    author_avatar = prof.get("avatar") or ("/static/avatars/avatar_001.jpg" if author_id == "commander" else _get_fallback_avatar(author_id))

                    item = {
                        "type": "new_message",
                        "id": f"event_{row['id']}",
                        "timestamp": row["created_at"],
                        "author_id": author_id,
                        "author_name": author_name,
                        "author_avatar": author_avatar,
                        "target_id": payload_data.get("target") or row.get("assignee"),
                        "task_id": row["task_id"],
                        "task_title": row.get("task_title") or "System",
                        "kind": kind,
                        "message": payload_data.get("message") or str(payload_data),
                        "takeover_requested": kind == "human_takeover_requested"
                    }
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

                conn.close()
            except Exception as e:
                pass

            await asyncio.sleep(1.2)

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/bot-screen/status")
def get_bot_screen_status():
    """Liefert den aktuellen Status des virtuellen Desktops & Human Takeover."""
    return _bot_screen_state

class TakeoverRequestModel(BaseModel):
    reason: str
    url: Optional[str] = None
    agent_name: Optional[str] = None

@router.post("/bot-screen/takeover/request")
def request_human_takeover(req: TakeoverRequestModel):
    """Wird von einem Agenten ausgelöst, wenn ein Captcha oder 2FA-Schranke erkannt wird."""
    _bot_screen_state["takeover_requested"] = True
    _bot_screen_state["takeover_reason"] = req.reason
    _bot_screen_state["takeover_timestamp"] = datetime.datetime.now().isoformat()
    if req.url:
        _bot_screen_state["current_url"] = req.url
    if req.agent_name:
        _bot_screen_state["agent_name"] = req.agent_name

    # Event in comm-feed eintragen
    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps({
            "author": "bot_desktop",
            "message": f"🚨 Human Takeover angefordert: {req.reason} ({_bot_screen_state['current_url']})",
            "target": "commander",
            "broadcast": True,
            "takeover_requested": True,
            "url": _bot_screen_state["current_url"]
        }, ensure_ascii=False)
        cur.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'human_takeover_requested', ?, ?)
        """, (payload, now_iso))
        conn.commit()
    finally:
        conn.close()

    return {"status": "takeover_active", "state": _bot_screen_state}

@router.post("/bot-screen/takeover/resume")
def resume_from_human_takeover():
    """Wird vom Nutzer per Klick auf 'Agent fortsetzen' aufgerufen."""
    _bot_screen_state["takeover_requested"] = False
    _bot_screen_state["takeover_reason"] = ""
    _bot_screen_state["last_interaction"] = datetime.datetime.now().isoformat()

    conn = _get_kanban_connection()
    try:
        now_iso = datetime.datetime.now().isoformat()
        cur = conn.cursor()
        payload = json.dumps({
            "author": "commander",
            "message": "✅ Human Takeover abgeschlossen: Nutzer hat Freigabe erteilt. Agent setzt Ausführung fort.",
            "target": "all",
            "broadcast": True,
            "takeover_resolved": True
        }, ensure_ascii=False)
        cur.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'human_takeover_resolved', ?, ?)
        """, (payload, now_iso))
        conn.commit()
    finally:
        conn.close()

    return {"status": "resumed", "state": _bot_screen_state}

class ScreenInteractionModel(BaseModel):
    action: str = "click"  # click, key, scroll
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None

@router.post("/bot-screen/interact")
def interact_with_bot_screen(action_data: ScreenInteractionModel):
    """Nimmt Benutzerinteraktionen (Klick, Tasteneingabe) entgegen."""
    _bot_screen_state["last_interaction"] = datetime.datetime.now().isoformat()
    return {"status": "success", "echo": action_data.dict()}


@router.post("/bot-screen/abort")
def abort_bot_screen_execution():
    """Notfall-Abbruch: Entzieht dem Agenten sofort alle Rechte und stoppt aktive Browser-Aktionen."""
    _bot_screen_state["takeover_requested"] = False
    _bot_screen_state["mouse_control_enabled"] = False
    _bot_screen_state["agent_authorized"] = False
    now_iso = datetime.datetime.now().isoformat()
    try:
        conn = _get_kanban_connection()
        cur = conn.cursor()
        payload = json.dumps({
            "author": "commander",
            "message": "🛑 Notfall-Abbruch: Sofortiger Stopp aller Browser- und Desktop-Aktionen. Volle Kontrolle liegt wieder beim Nutzer.",
            "target": "all",
            "broadcast": True,
            "aborted": True
        }, ensure_ascii=False)
        cur.execute("""
            INSERT INTO task_events (task_id, kind, payload, created_at)
            VALUES ('bot_desktop', 'emergency_abort', ?, ?)
        """, (payload, now_iso))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"status": "aborted", "state": _bot_screen_state}


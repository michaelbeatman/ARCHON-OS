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
from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Query, Body
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
def get_audit_log_entries(limit: int = 50):
    """Liefert die neuesten Einträge des manipulationssicheren SHA-256 Audit-Logs."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, agent_id, action, payload, prev_hash, hash, timestamp 
            FROM audit_log 
            ORDER BY id DESC 
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        return {
            "status": "success",
            "entries": rows,
            "total_returned": len(rows)
        }

@router.post("/governance/audit-log/verify")
def verify_audit_log_chain():
    """Führt eine vollständige kryptografische Prüfung aller Verkettungen im Audit-Log durch."""
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    result = bridge.verify_audit_chain()
    return {
        "status": "success",
        "verification": result
    }



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

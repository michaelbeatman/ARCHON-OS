"""Kanban-Farbpalette, Sidecar-Metadaten, Board-Stats, Task-Details & Kommentare (D3/4).

Ausgelagert aus ``backend/operations_api.py`` nach dem S3-Muster
(Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``backend.operations_api``.
* Kein Import aus ``archon.routers.*`` (wahrt Layer-Contract D09/H-09-2).
* Alle Monkeypatches auf ``backend.operations_api.*`` greifen unveraendert.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from archon.core.provider_registry import get_provider


class KanbanPaletteUpdate(BaseModel):
    columns: Optional[Dict[str, Dict[str, str]]] = None
    reset: bool = False


class KanbanMetaSaveRequest(BaseModel):
    """Bekannte Sidecar-Felder; unbekannte Felder werden ignoriert (Kompatibilitaet)."""

    model_config = ConfigDict(extra="ignore")
    kind: str = Field(default="task", max_length=32)
    limits: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = Field(default=None, max_length=200)
    due: Optional[str] = Field(default=None, max_length=32)
    clear_due: bool = False
    tags: Optional[List[str]] = Field(default=None, max_length=50)
    obsidian: Optional[str] = Field(default=None, max_length=500)
    clear_obsidian: bool = False
    decision: Optional[Dict[str, Any]] = None
    tokens: Optional[Any] = None
    cost: Optional[Any] = None
    soul_mode: Optional[str] = Field(default=None, max_length=100)
    reasoning_effort: Optional[str] = Field(default=None, max_length=100)
    tool_preset: Optional[str] = Field(default=None, max_length=100)
    cron_schedule: Optional[str] = Field(default=None, max_length=200)
    depends_on: Optional[str] = Field(default=None, max_length=200)
    token_budget: Optional[Any] = None
    cost_limit_usd: Optional[Any] = None
    require_hitl: Optional[bool] = None


class KanbanMetaDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Abhaengigkeiten aus backend.operations_api."""

    get_kanban_connection: Callable[..., Any]
    load_kanban_meta: Callable[[], Dict[str, Any]]
    parse_kanban_ts: Callable[[Any], Optional[float]]
    load_profiles_map: Callable[[], Dict[str, Any]]
    get_fallback_avatar: Callable[[Any], str]
    resolve_task_obsidian_rel: Callable[..., Optional[str]]
    palette_file: str
    palette_defaults: Dict[str, Dict[str, str]]


def load_kanban_palette(
    palette_file: str,
    palette_defaults: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """Liefert die Kanban-Spaltenfarben (Gespeicherte, mit Posteo-Standard gemischt)."""
    if os.path.exists(palette_file):
        try:
            with open(palette_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged: Dict[str, Dict[str, str]] = {}
            for col_id, defaults in palette_defaults.items():
                merged[col_id] = {**defaults, **(saved.get(col_id) or {})}
            return {"status": "ok", "custom": True, "columns": merged}
        except Exception as e:
            print(f"[OperationsAPI] Palette load error: {e}", file=sys.stderr)
    return {"status": "ok", "custom": False, "columns": palette_defaults}


def persist_kanban_palette(
    req: KanbanPaletteUpdate,
    palette_file: str,
    palette_defaults: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """Speichert die Kanban-Farbpalette (oder setzt mit reset=true auf Standard zurueck)."""
    if req.reset:
        if os.path.exists(palette_file):
            try:
                os.remove(palette_file)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Reset fehlgeschlagen: {e}")
        return {"status": "ok", "reset": True, "columns": palette_defaults}
    if not req.columns:
        raise HTTPException(status_code=400, detail="columns erforderlich")
    cleaned: Dict[str, Dict[str, str]] = {}
    for col_id, colors in req.columns.items():
        if col_id not in palette_defaults:
            continue
        entry: Dict[str, str] = {}
        for key in ("header", "text"):
            val = str(colors.get(key, "")).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", val):
                entry[key] = val
        if entry:
            cleaned[col_id] = entry
    os.makedirs(os.path.dirname(palette_file), exist_ok=True)
    with open(palette_file, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    return {"status": "ok", "saved": True, "columns": cleaned}


def persist_kanban_meta(body: KanbanMetaSaveRequest) -> Dict[str, Any]:
    """Due/Tags (kind=task) oder WIP-Limits (kind=wip) speichern. Engine-DB bleibt unberuehrt."""
    payload = body.model_dump(exclude_unset=True)
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

        def _apply_wip(meta: Dict[str, Any]) -> None:
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

    def _apply_task(meta: Dict[str, Any]) -> Dict[str, Any]:
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
                for k in (
                    "typ",
                    "ref_id",
                    "titel",
                    "kurzfassung",
                    "dossier",
                    "body",
                    "assignee",
                    "status",
                    "entschieden_von",
                    "entschieden_am",
                    "kanal",
                ):
                    if k in dec_in:
                        dec[k] = dec_in[k]
                tg = dec_in.get("telegram")
                if isinstance(tg, dict):
                    dec.setdefault("telegram", {}).update(tg)
                dec.setdefault("erstellt", datetime.datetime.now().isoformat())
        if "tokens" in payload:
            tmeta["tokens"] = payload["tokens"]
        if "cost" in payload:
            tmeta["cost"] = payload["cost"]
        for mk in ("soul_mode", "reasoning_effort", "tool_preset", "cron_schedule", "depends_on"):
            if mk in payload:
                val = str(payload[mk] or "").strip()
                if val:
                    tmeta[mk] = val
                else:
                    tmeta.pop(mk, None)
        if "token_budget" in payload:
            tb = payload["token_budget"]
            if tb is not None and str(tb).strip() != "":
                try:
                    tmeta["token_budget"] = int(tb)
                except (TypeError, ValueError) as exc:
                    print(
                        f"[OperationsAPI] FEHLER (HIGH_SECURITY) save_kanban_meta: Exception im Fehler-/Fallback-Pfad: {exc}",
                        file=sys.stderr,
                    )
            else:
                tmeta.pop("token_budget", None)
        if "cost_limit_usd" in payload:
            cl = payload["cost_limit_usd"]
            if cl is not None and str(cl).strip() != "":
                try:
                    tmeta["cost_limit_usd"] = float(cl)
                except (TypeError, ValueError) as exc:
                    print(
                        f"[OperationsAPI] Fallback save_kanban_meta: Exception im Fehler-/Fallback-Pfad: {exc}",
                        file=sys.stderr,
                    )
            else:
                tmeta.pop("cost_limit_usd", None)
        if "require_hitl" in payload:
            if payload["require_hitl"]:
                tmeta["require_hitl"] = True
            else:
                tmeta.pop("require_hitl", None)
        if not tmeta:
            meta["tasks"].pop(task_id, None)
        return dict(meta["tasks"].get(task_id, {}))

    _, saved = update_kanban_meta(_apply_task)
    try:
        main = get_provider("app_main")
        if hasattr(main, "broadcast_event"):
            main.broadcast_event("kanban_updated", {"action": "meta_update", "task_id": task_id})
    except Exception as exc:
        print(
            f"[OperationsAPI] WARNUNG (MEDIUM) save_kanban_meta: Exception im Fehler-/Fallback-Pfad: {exc}",
            file=sys.stderr,
        )
    return {"status": "ok", "task": saved}


def compute_kanban_stats(deps: KanbanMetaDeps) -> Dict[str, Any]:
    """Board-Kennzahlen: Spaltenverteilung, Durchlaufzeit, 7-Tage-Flows."""
    conn = deps.get_kanban_connection()
    try:
        cur = conn.cursor()
        per_status: Dict[str, int] = {}
        for st, n in cur.execute("SELECT status, count(*) FROM tasks GROUP BY status"):
            per_status[st or "todo"] = n
        active = {k: v for k, v in per_status.items() if k != "archived"}
        cycles: List[float] = []
        for s, e in cur.execute(
            "SELECT started_at, completed_at FROM tasks WHERE started_at IS NOT NULL AND completed_at IS NOT NULL"
        ):
            s_ts = deps.parse_kanban_ts(s)
            e_ts = deps.parse_kanban_ts(e)
            if s_ts is not None and e_ts is not None:
                cycles.append((e_ts - s_ts) / 3600.0)
        avg_cycle = round(sum(cycles) / len(cycles), 1) if cycles else None
        now = datetime.datetime.now()
        created_7d = cur.execute(
            "SELECT count(*) FROM tasks WHERE created_at >= ?",
            ((now - datetime.timedelta(days=7)).isoformat(),),
        ).fetchone()[0]
        epoch_7d = (now - datetime.timedelta(days=7)).timestamp()
        done_7d = 0
        for (e,) in cur.execute("SELECT completed_at FROM tasks WHERE completed_at IS NOT NULL"):
            e_ts = deps.parse_kanban_ts(e)
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


def fetch_task_details(task_id: str, deps: KanbanMetaDeps) -> Dict[str, Any]:
    """Gibt Detailinformationen, Kommentare und Event-Logs eines Tasks zurueck."""
    conn = deps.get_kanban_connection()
    profiles = deps.load_profiles_map()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT rowid AS task_num, * FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            raise HTTPException(status_code=404, detail="Task nicht gefunden.")

        task = dict(task_row)
        assignee_id = task.get("assignee")
        prof = profiles.get(assignee_id or "", {})
        task["assignee_name"] = prof.get("name") or assignee_id or "Nicht zugewiesen"
        task["assignee_avatar"] = prof.get("avatar") or deps.get_fallback_avatar(assignee_id)

        _meta_all = deps.load_kanban_meta()
        task["obsidian"] = deps.resolve_task_obsidian_rel(task_id, _meta_all)
        task["decision"] = ((_meta_all.get("tasks") or {}).get(task_id) or {}).get("decision") or None

        cursor.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        comments = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
        events = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT l.parent_id, l.child_id, t.title
            FROM task_links l
            JOIN tasks t ON l.child_id = t.id
            WHERE l.parent_id = ?
            """,
            (task_id,),
        )
        children = [dict(r) for r in cursor.fetchall()]

        return {
            "status": "success",
            "task": task,
            "comments": comments,
            "events": events,
            "subtasks": children,
        }
    finally:
        conn.close()


def insert_task_comment(
    task_id: str,
    author: str,
    body: str,
    deps: KanbanMetaDeps,
) -> Dict[str, Any]:
    """Fuegt einem Task einen Kommentar hinzu (Timestamp als integer Unix-Epoch)."""
    conn = deps.get_kanban_connection(maintenance=True)
    try:
        now_ts = int(time.time())
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO task_comments (task_id, author, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, author, body, now_ts),
        )
        conn.commit()
        return {"status": "success", "task_id": task_id, "created_at": now_ts}
    finally:
        conn.close()

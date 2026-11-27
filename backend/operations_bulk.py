"""Kanban Bulk-Aktionen und 10-Minuten-Undo-Puffer (D3/2 aus backend/operations_api.py).

Reine Extraktion nach dem S3-Muster (Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``backend.operations_api``.
* ``_KANBAN_UNDO_STORE`` wird in ``backend.operations_api`` als identisches Dict
  re-exportiert.
* Alle Monkeypatches auf ``backend.operations_api._get_kanban_connection``,
  ``_load_kanban_meta`` und ``_sync_to_memory_bridge`` greifen unveraendert.
"""

from __future__ import annotations

import datetime
import json
import secrets
import sys
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

from fastapi import HTTPException
from pydantic import BaseModel

from archon.core.provider_registry import get_provider

# D09-M6: der Store bleibt bewusst ein reines Dict (operations_api re-exportiert
# ihn by identity, tests/test_d3_bulk_characterization.py prueft das). Alle
# Mutationen laufen jetzt ueber _UNDO_LOCK. RLock statt Lock, damit
# _prune_undo_store() aus bereits gesperrten Pfaden reentrant gerufen werden kann.
_KANBAN_UNDO_STORE: Dict[str, Dict[str, Any]] = {}
_KANBAN_UNDO_STORE_MAX_SIZE = 100
_UNDO_LOCK = threading.RLock()


class BulkActionDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Kanban-Abhaengigkeiten aus backend.operations_api."""

    get_kanban_connection: Callable[..., Any]
    load_kanban_meta: Callable[[], Dict[str, Any]]
    sync_to_memory_bridge: Callable[[str, Any, Any, Any], Any]
    valid_kanban_statuses: Set[str]


def _prune_undo_store() -> None:
    """Fix-Sprint Paket A (Punkt 7): raeumt den Undo-Store bei jedem Zugriff auf —
    TTL-Abfluss + Hartes Maximum von 100 Eintraegen (aelteste werden verworfen).

    D09-M6: Iteration, TTL-Pruefung und Pop laufen atomisch unter _UNDO_LOCK.
    Sonst konnten zwei Request-Threads dieselbe Map gleichzeitig veraendern
    (RuntimeError: dictionary changed size during iteration / verlorene Tokens).
    """
    with _UNDO_LOCK:
        now_ts = time.time()
        for tok in list(_KANBAN_UNDO_STORE.keys()):
            entry = _KANBAN_UNDO_STORE.get(tok)
            if not entry or float(entry.get("expires_at") or 0) < now_ts:
                _KANBAN_UNDO_STORE.pop(tok, None)
        while len(_KANBAN_UNDO_STORE) > _KANBAN_UNDO_STORE_MAX_SIZE:
            oldest_tok = min(
                _KANBAN_UNDO_STORE,
                key=lambda t: float(_KANBAN_UNDO_STORE[t].get("created_at") or 0.0),
            )
            _KANBAN_UNDO_STORE.pop(oldest_tok, None)


class KanbanBulkActionRequest(BaseModel):
    task_ids: List[str]
    action: str  # "move", "assign", "tag", "delete"
    payload: Dict[str, Any] = {}
    assignee: Optional[str] = None


class KanbanBulkUndoRequest(BaseModel):
    undo_token: str


def execute_kanban_bulk_action(
    req: KanbanBulkActionRequest,
    deps: BulkActionDeps,
) -> Dict[str, Any]:
    """Fuehrt eine Mehrfachaktion auf ausgewaehlten Kanban-Tasks aus (10-Minuten-Undo)."""
    task_ids = [tid.strip() for tid in req.task_ids if tid and tid.strip()]
    if not task_ids:
        raise HTTPException(status_code=400, detail="Keine Aufgaben übergeben.")

    action = req.action.lower()
    if action not in ("move", "assign", "tag", "delete"):
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")

    _prune_undo_store()
    conn = deps.get_kanban_connection(maintenance=True)
    now_iso = datetime.datetime.now().isoformat()
    now_ts = time.time()
    undo_token = f"undo_{secrets.token_hex(8)}"

    try:
        cursor = conn.cursor()
        # 1. Schnappschuss der betroffenen Tasks sichern
        placeholders = ",".join("?" for _ in task_ids)
        cursor.execute(
            f"SELECT id, title, assignee, status, block_kind, result FROM tasks WHERE id IN ({placeholders})",
            task_ids,
        )
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Keine passenden Aufgaben gefunden.")

        meta = deps.load_kanban_meta()
        snapshot: List[Dict[str, Any]] = []
        for r in rows:
            tid = r["id"]
            t_tags = list((meta.get("tasks", {}).get(tid, {})).get("tags", []))
            snapshot.append({
                "id": tid,
                "title": r["title"],
                "status": r["status"],
                "assignee": r["assignee"],
                "tags": t_tags,
                # Fix-Sprint Paket A (Punkt 6): block_kind & result mitsichern
                "block_kind": r["block_kind"] if "block_kind" in r.keys() else None,
                "result": r["result"] if "result" in r.keys() else None,
            })

        # 2. Aktion anwenden
        if action == "move":
            target_status = (req.payload.get("status") or "todo").lower()
            if target_status not in deps.valid_kanban_statuses:
                raise HTTPException(
                    status_code=422,
                    detail=f"Ungültiger Status '{target_status}'. Erlaubt sind: {', '.join(sorted(deps.valid_kanban_statuses))}",
                )
            # Fix-Sprint Paket A (Punkt 5): Cycle-Time/Zombie-Erkennung korrekt
            # — beim Zurueckbewegen Timestamps explizit NULL setzen statt COALESCE.
            if target_status in ("backlog", "todo"):
                cursor.execute(
                    f"""
                    UPDATE tasks
                    SET status = ?,
                        started_at = NULL,
                        completed_at = NULL
                    WHERE id IN ({placeholders})
                    """,
                    [target_status] + task_ids,
                )
            elif target_status == "in_progress":
                cursor.execute(
                    f"""
                    UPDATE tasks
                    SET status = ?,
                        started_at = COALESCE(started_at, ?),
                        completed_at = NULL
                    WHERE id IN ({placeholders})
                    """,
                    [target_status, now_iso] + task_ids,
                )
            elif target_status == "done":
                cursor.execute(
                    f"""
                    UPDATE tasks
                    SET status = ?,
                        completed_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [target_status, now_iso] + task_ids,
                )
            else:
                # review/blocked/failed/archived etc.: altes Verhalten (kein Touch der Timestamps)
                cursor.execute(
                    f"""
                    UPDATE tasks
                    SET status = ?,
                        started_at = COALESCE(NULL, started_at),
                        completed_at = COALESCE(NULL, completed_at)
                    WHERE id IN ({placeholders})
                    """,
                    [target_status] + task_ids,
                )

            for s in snapshot:
                cursor.execute(
                    """
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        s["id"],
                        "bulk_status_changed",
                        json.dumps({"from": s["status"], "to": target_status}),
                        now_iso,
                    ),
                )
                deps.sync_to_memory_bridge(s["id"], s["title"], s["assignee"], target_status)

        elif action == "assign":
            target_assignee = req.payload.get("assignee")
            if target_assignee is None:
                target_assignee = req.assignee
            if target_assignee is None:
                raise HTTPException(status_code=400, detail="Kein Ziel-Agent übergeben.")
            cursor.execute(
                f"""
                UPDATE tasks
                SET assignee = ?
                WHERE id IN ({placeholders})
                """,
                [target_assignee] + task_ids,
            )

            for s in snapshot:
                cursor.execute(
                    """
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        s["id"],
                        "bulk_assignee_changed",
                        json.dumps({"from": s["assignee"], "to": target_assignee}),
                        now_iso,
                    ),
                )
                deps.sync_to_memory_bridge(s["id"], s["title"], target_assignee, s["status"])

        elif action == "tag":
            tag_name = req.payload.get("tag", "").strip()
            mode = req.payload.get("tag_mode", "add")  # "add" oder "remove"
            if tag_name:
                from backend.kanban_sidecar import update_kanban_meta

                def _apply_tags(cur_meta: Dict[str, Any]) -> Dict[str, Any]:
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
            # Soft-Delete ueber 'archived' Status, damit GoBD-konform und 100% undo-faehig
            cursor.execute(
                f"""
                UPDATE tasks
                SET status = 'archived'
                WHERE id IN ({placeholders})
                """,
                task_ids,
            )

            for s in snapshot:
                cursor.execute(
                    """
                    INSERT INTO task_events (task_id, kind, payload, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (s["id"], "bulk_archived", json.dumps({"from": s["status"]}), now_iso),
                )

        conn.commit()
        try:
            from backend.audit_log import chained_audit_log

            chained_audit_log.record_event(
                category="kanban",
                action=f"bulk_{action}",
                agent_id="operator",
                payload={
                    "task_ids": task_ids,
                    "action": action,
                    "payload": req.payload,
                    "affected_count": len(task_ids),
                },
            )
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback api_kanban_bulk_action: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        # 3. Snapshot im Undo-Puffer speichern (10 Minuten TTL).
        # Schreiben + Pruning in EINEM kritischen Abschnitt: der neue Token
        # darf nicht zwischen Pruning und Insert von einem anderen Thread
        # wieder entfernt werden (D09-M6).
        with _UNDO_LOCK:
            _KANBAN_UNDO_STORE[undo_token] = {
                "snapshot": snapshot,
                "action": action,
                "created_at": now_ts,
                "expires_at": now_ts + 600.0,  # 10 Minuten
            }
            _prune_undo_store()  # RLock: reentrant, kein Deadlock

        # Broadcast WebSocket Event
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event(
                    "kanban_updated",
                    {
                        "action": f"bulk_{action}",
                        "count": len(task_ids),
                        "task_ids": task_ids,
                    },
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback api_kanban_bulk_action: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        return {
            "status": "success",
            "action": action,
            "affected_count": len(task_ids),
            "undo_token": undo_token,
            "expires_in_seconds": 600,
        }
    finally:
        conn.close()


def execute_kanban_bulk_undo(
    req: KanbanBulkUndoRequest,
    deps: BulkActionDeps,
) -> Dict[str, Any]:
    """Macht eine Mehrfachaktion innerhalb des 10-Minuten-Zeitfensters rueckgaengig."""
    token = req.undo_token.strip()
    with _UNDO_LOCK:
        # D09-M6: das explizite TTL-Urteil (400) MUSS vor dem generellen
        # Pruning stehen — sonst ist der Token bereits weg und der Aufrufer
        # bekommt fälschlich 404 „nicht gefunden" statt „abgelaufen".
        entry = _KANBAN_UNDO_STORE.get(token)
        if entry and time.time() > float(entry.get("expires_at") or 0):
            _KANBAN_UNDO_STORE.pop(token, None)
            raise HTTPException(
                status_code=400,
                detail="Das 10-Minuten-Zeitfenster für diese Aktion ist abgelaufen.",
            )

        _prune_undo_store()  # RLock: reentrant, kein Deadlock
        entry = _KANBAN_UNDO_STORE.get(token)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail="Undo-Transaktion nicht gefunden oder bereits abgelaufen.",
            )

        # CAS: atomisch verbrauchen, BEVOR die DB-Arbeit beginnt. Ein zweiter,
        # paralleler Request sieht den Token nicht mehr und laeuft in den
        # 404-Pfad — genau ein Aufrufer darf den Snapshot zurueckspielen.
        _KANBAN_UNDO_STORE.pop(token, None)

    snapshot = entry.get("snapshot") or []
    conn = deps.get_kanban_connection(maintenance=True)
    now_iso = datetime.datetime.now().isoformat()
    try:
        cursor = conn.cursor()
        for item in snapshot:
            tid = item["id"]
            cursor.execute(
                """
                UPDATE tasks
                SET status = ?, assignee = ?,
                    block_kind = ?, result = ?
                WHERE id = ?
                """,
                (
                    item["status"],
                    item["assignee"],
                    item.get("block_kind"),
                    item.get("result"),
                    tid,
                ),
            )
            cursor.execute(
                """
                INSERT INTO task_events (task_id, kind, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    tid,
                    "bulk_undo_restored",
                    json.dumps({"restored_status": item["status"]}),
                    now_iso,
                ),
            )
            deps.sync_to_memory_bridge(tid, item["title"], item["assignee"], item["status"])

        conn.commit()

        # Tags im Sidecar wiederherstellen
        from backend.kanban_sidecar import update_kanban_meta

        def _restore_tags(cur_meta: Dict[str, Any]) -> Dict[str, Any]:
            for item in snapshot:
                tid = item["id"]
                cur_meta.setdefault("tasks", {}).setdefault(tid, {})
                cur_meta["tasks"][tid]["tags"] = item["tags"]
            return cur_meta

        update_kanban_meta(_restore_tags)

        # Token wurde bereits beim Eintritt atomisch verbraucht (CAS).
        # Kein zweites pop(): das koennte einen zwischenzeitlich neu
        # angelegten Token mit gleichem Wert loeschen (D09-M6).
        try:
            from backend.audit_log import chained_audit_log

            chained_audit_log.record_event(
                category="kanban",
                action="bulk_undo",
                agent_id="operator",
                payload={"undo_token": token, "restored_count": len(snapshot)},
            )
        except Exception as exc:
            print(
                f"[OperationsAPI] FEHLER (HIGH_SECURITY) api_kanban_bulk_undo: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        # Broadcast
        try:
            main = get_provider("app_main")
            if hasattr(main, "broadcast_event"):
                main.broadcast_event(
                    "kanban_updated",
                    {"action": "bulk_undone", "count": len(snapshot)},
                )
        except Exception as exc:
            print(
                f"[OperationsAPI] Fallback api_kanban_bulk_undo: Exception im Fehler-/Fallback-Pfad: {exc}",
                file=sys.stderr,
            )

        return {
            "status": "success",
            "message": f"{len(snapshot)} Aufgaben wurden auf ihren vorherigen Stand zurückgesetzt.",
            "restored_count": len(snapshot),
        }
    finally:
        conn.close()

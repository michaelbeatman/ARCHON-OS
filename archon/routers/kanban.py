from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""
Kanban Persistenz Router fuer Archon OS.
Verwaltet /api/kanban Endpunkte (Karten lesen und synchronisieren in kanban.db und JSON).
Extrahiert aus main.py zur Modularisierung.
"""

import os
import sys
import json
import sqlite3
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request
from archon.core.runtime import atomic_write_json, logger
from archon.core.paths import KANBAN_CARDS_FILE, KANBAN_DB_PATH
from backend.platform_paths import HERMES_HOME
from backend.db_paths import get_db_connection

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["kanban"])


def _get_kanban_cards_file() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "KANBAN_CARDS_FILE"):
        cand = getattr(main_mod, "KANBAN_CARDS_FILE")
        if cand != KANBAN_CARDS_FILE:
            return cand
    try:
        from backend.tenant_context import tenant_context, PRIMARY_TENANT_IDS
        tid = tenant_context.get_active_tenant_id()
        if tid not in PRIMARY_TENANT_IDS:
            return os.path.join(tenant_context.get_tenant_dir(tid), "kanban_cards.json")
    except Exception:
        pass
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
        from backend.tenant_context import tenant_context, PRIMARY_TENANT_IDS
        tid = tenant_context.get_active_tenant_id()
        if tid not in PRIMARY_TENANT_IDS:
            return tenant_context.resolve_active_db("kanban.db", tid)
    except Exception:
        pass
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
        except Exception:
            pass
    return []


@router.post("/api/kanban")
async def api_save_kanban(request: Request):
    try:
        cards = await request.json()
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
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

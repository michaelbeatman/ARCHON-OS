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

router = APIRouter(tags=["kanban"])


def _get_kanban_cards_file() -> str:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "KANBAN_CARDS_FILE"):
        return getattr(main_mod, "KANBAN_CARDS_FILE")
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


@router.get("/api/kanban")
def api_get_kanban():
    hermes_home = _get_hermes_home()
    kanban_db = KANBAN_DB_PATH if os.path.exists(KANBAN_DB_PATH) else os.path.join(hermes_home, "kanban.db")
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
        hermes_home = _get_hermes_home()
        kanban_db = KANBAN_DB_PATH if os.path.exists(KANBAN_DB_PATH) else os.path.join(hermes_home, "kanban.db")
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

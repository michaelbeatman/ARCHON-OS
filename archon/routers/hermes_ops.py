"""Router fuer Hermes Core Config (/api/hermes/config) und Memory Purge."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Dict

from fastapi import APIRouter, Body, HTTPException, Request

from archon.core.paths import HERMES_CONFIG_YAML, OPT_DATA_DIR, STATE_DB_PATH

logger = logging.getLogger("archon.routers.hermes_ops")

router = APIRouter(tags=["hermes_ops"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def _get_hermes_config_path() -> str:
    import main as app_main

    memory_dir = getattr(app_main, "MEMORY_DIR", os.path.join(OPT_DATA_DIR, "memory"))
    candidates = [
        HERMES_CONFIG_YAML,
        os.path.join(OPT_DATA_DIR, "hermes_config.json"),
        os.path.expanduser("~/.hermes/config.yaml"),
        os.path.expanduser("~/.hermes/hermes_config.json"),
        os.path.join(memory_dir, "hermes_config.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(memory_dir, "hermes_config.json")


@router.get("/api/hermes/config")
def api_get_hermes_config():
    import main as app_main

    cfg_file = _get_hermes_config_path()
    try:
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
                    try:
                        import yaml

                        data = yaml.safe_load(f) or {}
                    except Exception:
                        data = {"raw": f.read()}
                else:
                    data = json.load(f)
            return {"status": "success", "file": cfg_file, "config": data}
    except Exception as e:
        logger.warning(f"[Hermes Config] Error reading {cfg_file}: {e}")

    default_tools = getattr(
        app_main, "DEFAULT_HERMES_TOOLS", ["execute_command", "read_file", "write_file"]
    )
    return {
        "status": "success",
        "file": cfg_file,
        "config": {
            "default_model": "auto/best-free",
            "default_temperature": 0.7,
            "global_tools": default_tools,
        },
    }


@router.post("/api/hermes/config")
def api_save_hermes_config(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    import main as app_main

    cfg_file = _get_hermes_config_path()
    os.makedirs(os.path.dirname(os.path.abspath(cfg_file)), exist_ok=True)
    if hasattr(app_main, "create_rolling_backup"):
        app_main.create_rolling_backup(cfg_file, max_backups=3)

    config_data = payload.get("config", payload)
    try:
        if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
            try:
                import yaml

                with open(cfg_file, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, allow_unicode=True)
            except Exception:
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
        else:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "file": cfg_file, "config": config_data}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Fehler beim Speichern der Konfiguration: {e}"
        )


def _purge_state_memory(purge_options: Dict) -> Dict:
    """DB-Zugriff als separate Hilfsfunktion ausserhalb des AST-Routers."""
    import main as app_main

    state_db_path = getattr(app_main, "STATE_DB_PATH", STATE_DB_PATH)
    cleared_sessions = 0
    cleared_messages = 0
    conn = sqlite3.connect(state_db_path, timeout=20.0)
    conn.execute("PRAGMA busy_timeout=20000;")
    try:
        cur = conn.cursor()
        mode = purge_options.get("mode", "empty_and_orphaned")
        if mode == "all_sessions":
            cur.execute("DELETE FROM messages")
            cleared_messages = cur.rowcount
            cur.execute("DELETE FROM sessions")
            cleared_sessions = cur.rowcount
        else:
            cur.execute("DELETE FROM sessions WHERE message_count = 0 OR message_count IS NULL")
            cleared_sessions = cur.rowcount
            cur.execute("DELETE FROM messages WHERE session_id NOT IN (SELECT id FROM sessions)")
            cleared_messages = cur.rowcount

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM session_model_usage")
        usage_count_after = cur.fetchone()[0]

        return {
            "status": "success",
            "cleared_sessions": cleared_sessions,
            "cleared_messages": cleared_messages,
            "model_usage_records_preserved": usage_count_after,
        }
    finally:
        conn.close()


@router.post("/api/hermes/memory/purge")
def api_hermes_memory_purge(request: Request, purge_options: Dict = Body(default={})):
    """Cleans sessions and chat messages while strictly preserving session_model_usage."""
    _require_admin(request)
    try:
        return _purge_state_memory(purge_options)
    except Exception as e:
        logger.error(f"[Memory Purge Error]: {e}")
        raise HTTPException(
            status_code=500, detail=f"Fehler bei der Speicherbereinigung: {str(e)}"
        )

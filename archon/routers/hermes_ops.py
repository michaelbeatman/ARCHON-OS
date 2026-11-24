"""Router fuer Hermes Core Config (/api/hermes/config) und Memory Purge."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import json
import logging
import os
import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request

from archon.core.paths import HERMES_CONFIG_YAML, OPT_DATA_DIR, STATE_DB_PATH

logger = logging.getLogger("archon.routers.hermes_ops")

from archon.routers._validated_body import PassthroughBody, as_payload
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["hermes_ops"])


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


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


def _mask_config_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(tok in kl for tok in ("api_key", "token", "secret", "password", "passwd", "pat")) and isinstance(v, str) and v.strip():
                try:
                    from utils.secret_files import mask_secret
                    masked[k] = mask_secret(v)
                except Exception:
                    masked[k] = "••••••••"
            else:
                masked[k] = _mask_config_secrets(v)
        return masked
    if isinstance(obj, list):
        return [_mask_config_secrets(x) for x in obj]
    return obj


@router.get("/api/hermes/config")
def api_get_hermes_config(request: Request):
    _require_admin(request)
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
                        data = {"raw": "[YAML-Parse-Fehler - Rohinhalt aus Sicherheitsgruenden ausgeblendet]"}
                else:
                    data = json.load(f)
            return {"status": "success", "file": cfg_file, "config": _mask_config_secrets(data)}
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


def _restore_masked_dict_secrets(existing: Any, updated: Any) -> Any:
    """Stellt maskierte Secret-Werte (z. B. '••••') rekursiv aus der bestehenden Config wieder her."""
    if isinstance(updated, dict) and isinstance(existing, dict):
        out: Dict[str, Any] = {}
        for k, v in updated.items():
            if isinstance(v, str) and ("\u2022" in v or "•" in v) and k in existing:
                out[k] = existing[k]
            elif isinstance(v, (dict, list)) and k in existing:
                out[k] = _restore_masked_dict_secrets(existing[k], v)
            else:
                out[k] = v
        return out
    return updated


@router.post("/api/hermes/config")
def api_save_hermes_config(request: Request, payload: PassthroughBody = Body(...)):
    _require_admin(request)
    payload = as_payload(payload)
    import main as app_main

    cfg_file = _get_hermes_config_path()
    os.makedirs(os.path.dirname(os.path.abspath(cfg_file)), exist_ok=True)
    if hasattr(app_main, "create_rolling_backup"):
        app_main.create_rolling_backup(cfg_file, max_backups=3)

    config_data = payload.get("config", payload)
    # Vorhandene Secrets wiederherstellen, falls Client maskierte '••••'-Werte zuruecksendet
    if os.path.exists(cfg_file) and isinstance(config_data, dict):
        try:
            with open(cfg_file, "r", encoding="utf-8") as rf:
                if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
                    try:
                        import yaml
                        existing_obj = yaml.safe_load(rf) or {}
                    except Exception:
                        existing_obj = {}
                else:
                    existing_obj = json.load(rf) or {}
            config_data = _restore_masked_dict_secrets(existing_obj, config_data)
        except Exception as _exc:
            logger.debug("[hermes_ops] Ignorierte Ausnahme (Z.141): %s", _exc)
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
            status_code=500, detail={"code": "hermes_ops_config_save_failed", "params": {"error": str(e)}}
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
def api_hermes_memory_purge(request: Request, purge_options: PassthroughBody = Body(default={})):
    """Cleans sessions and chat messages while strictly preserving session_model_usage."""
    _require_admin(request)
    purge_options = as_payload(purge_options)
    try:
        return _purge_state_memory(purge_options)
    except Exception as e:
        logger.error(f"[Memory Purge Error]: {e}")
        raise HTTPException(
            status_code=500, detail={"code": "hermes_ops_cleanup_failed", "params": {"error": str(e)}}
        )

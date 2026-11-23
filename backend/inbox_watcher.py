"""
backend/inbox_watcher.py
Konfigurierbarer Ordner-Watcher für Archon OS / Robert.
Überwacht ein vom Benutzer in den Einstellungen definiertes Verzeichnis (Drop-Zone)
auf neue Dokumente, Notizen oder Medien und erstellt vollautonom Kanban-Aufgaben dafür.
"""
import logging
_archon_exc_logger = logging.getLogger("inbox_watcher")

import os
import sys
import time
import json
import asyncio
import uuid
import datetime
import shutil
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")
DEFAULT_WATCH_DIR = "/opt/data/inbox" if os.path.isdir("/opt/data/inbox") else os.path.join(WORKSPACE_DIR, "data", "inbox")

def get_inbox_config() -> Dict[str, Any]:
    cfg = {
        "enabled": True,
        "watch_folder": DEFAULT_WATCH_DIR,
        "processed_folder": os.path.join(DEFAULT_WATCH_DIR, "processed"),
        "interval_seconds": 10,
        "auto_assignee": "hermes-researcher"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                if "inbox_watcher" in s and isinstance(s["inbox_watcher"], dict):
                    cfg.update(s["inbox_watcher"])
        except Exception as _exc:
            _archon_exc_logger.debug("[inbox_watcher] Ignorierte Ausnahme (Z.36): %s", _exc)
    return cfg

def save_inbox_config(new_cfg: Dict[str, Any]) -> bool:
    try:
        from backend.settings_json import atomic_update_settings

        def _apply(current):
            current["inbox_watcher"] = new_cfg

        atomic_update_settings(SETTINGS_FILE, _apply)
        return True
    except Exception as e:
        print(f"[InboxWatcher] Error saving config: {e}", file=sys.stderr)
        return False

def _scan_and_process_inbox_sync() -> Dict[str, Any]:
    """Synchrone Ausfuehrung fuer scan_and_process_inbox (laeuft ueber asyncio.to_thread).

    KRITISCH (Wiring-Audit): es gab ZWEI Scanner — diesen hier und
    ``event_mesh.scan_inbox_directory``. Beide erzeugten Kanban-Tasks und
    Workflow-Events fuer dieselbe Datei. Jetzt gibt es nur noch EINEN Scanner
    (Event-Mesh inkl. Cursor-Dedup `.event_mesh_processed.json`); dieser
    Watcher ist nur noch ein konfigurierter Aufrufer davon und verschiebt
    erfolgreich verarbeitete Dateien in den `processed`-Ordner.
    """
    cfg = get_inbox_config()
    watch_dir = cfg.get("watch_folder", DEFAULT_WATCH_DIR)
    proc_dir = cfg.get("processed_folder") or os.path.join(watch_dir, "processed")

    if not os.path.exists(watch_dir):
        try:
            os.makedirs(watch_dir, exist_ok=True)
            os.makedirs(proc_dir, exist_ok=True)
        except Exception:
            return {"status": "error", "message": f"Ordner {watch_dir} konnte nicht erstellt werden."}

    try:
        from backend.event_mesh import event_mesh
        scan = event_mesh.scan_inbox_directory(watch_dir, channel="inbox")
    except Exception as exc:
        return {"status": "error", "message": f"Event-Mesh-Scan fehlgeschlagen: {exc}"}

    os.makedirs(proc_dir, exist_ok=True)
    processed_files = []
    for evt in (scan.get("events") or []):
        fname = str(evt.get("file_name") or "")
        if not fname or evt.get("status") == "duplicate":
            continue
        src = os.path.join(watch_dir, fname)
        if not os.path.isfile(src):
            continue
        target = os.path.join(proc_dir, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{fname}")
        try:
            shutil.move(src, target)
            processed_files.append({
                "file": fname,
                "task_id": evt.get("kanban_task_id"),
                "size": evt.get("file_size"),
                "processed_path": target,
            })
        except Exception as exc:
            print(f"[InboxWatcher] Move file error: {exc}", file=sys.stderr)

    return {
        "status": scan.get("status", "success"),
        "watch_folder": watch_dir,
        "scanned_files": scan.get("scanned_files", 0),
        "processed_count": len(processed_files),
        "processed_items": processed_files,
        "dedup_strategy": "event_mesh_cursor",
    }


async def scan_and_process_inbox() -> Dict[str, Any]:
    """
    Durchsucht den konfigurierten Watch-Ordner nach neuen Dateien,
    ignoriert temporäre oder unvollständige Uploads und überführt fertige Dateien in Kanban.
    """
    return await asyncio.to_thread(_scan_and_process_inbox_sync)

async def inbox_watcher_background_loop():
    """Dauerschleife für den Watcher (wird als FastAPI Background-Task gestartet)."""
    while True:
        try:
            cfg = get_inbox_config()
            if cfg.get("enabled", True):
                await scan_and_process_inbox()
            interval = max(5, int(cfg.get("interval_seconds", 10)))
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(10)

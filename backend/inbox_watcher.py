"""
backend/inbox_watcher.py
Konfigurierbarer Ordner-Watcher für Archon OS / Robert.
Überwacht ein vom Benutzer in den Einstellungen definiertes Verzeichnis (Drop-Zone)
auf neue Dokumente, Notizen oder Medien und erstellt vollautonom Kanban-Aufgaben dafür.
"""

import os
import sys
import time
import json
import asyncio
import datetime
import shutil
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")
DEFAULT_WATCH_DIR = os.path.join(WORKSPACE_DIR, "agent_workspace", "inbox")

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
        except Exception:
            pass
    return cfg

def save_inbox_config(new_cfg: Dict[str, Any]) -> bool:
    try:
        current = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        current["inbox_watcher"] = new_cfg
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[InboxWatcher] Error saving config: {e}", file=sys.stderr)
        return False

async def scan_and_process_inbox() -> Dict[str, Any]:
    """
    Durchsucht den konfigurierten Watch-Ordner nach neuen Dateien,
    ignoriert temporäre oder unvollständige Uploads und überführt fertige Dateien in Kanban.
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

    os.makedirs(proc_dir, exist_ok=True)

    processed_files = []
    now = time.time()

    try:
        entries = os.listdir(watch_dir)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    for fname in entries:
        fpath = os.path.join(watch_dir, fname)
        if not os.path.isfile(fpath):
            continue
        # Ignoriere versteckte Dateien oder bereits im Zielordner
        if fname.startswith(".") or fname.startswith("~"):
            continue

        # Debouncing: Datei muss mindestens 2 Sekunden alt sein (Upload/Kopiervorgang beendet)
        try:
            mtime = os.path.getmtime(fpath)
            if now - mtime < 2.0:
                continue
            fsize = os.path.getsize(fpath)
        except Exception:
            continue

        # Datei-Inhalt / Preview auslesen
        ext = os.path.splitext(fname)[1].lower()
        content_preview = ""
        if ext in (".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml"):
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as tf:
                    content_preview = tf.read(2000)
            except Exception:
                content_preview = f"[Textdatei {fname}, Groesse: {fsize} Bytes]"
        else:
            content_preview = f"[Binaerdatei {fname}, Typ: {ext}, Groesse: {fsize} Bytes]"

        # Task in Kanban & Operations erstellen
        task_id = f"inbox-{datetime.datetime.now().strftime('%m%d%H%M%S')}"
        title = f"[INBOX-DROP] {fname}"
        body = (
            f"Automatisch ueber den Ingest-Watcher erfasst:\n"
            f"- Datei: {fname}\n"
            f"- Groesse: {fsize} Bytes\n"
            f"- Erfassungszeit: {datetime.datetime.now().isoformat()}\n\n"
            f"VORSCHAU / METADATEN:\n{content_preview}\n"
        )

        try:
            from local_memory_bridge import LocalMemoryBridge
            bridge = LocalMemoryBridge()
            bridge.sync_task(
                task_id=task_id,
                title=title,
                role=cfg.get("auto_assignee", "hermes-researcher"),
                status="todo"
            )
        except Exception as e:
            print(f"[InboxWatcher] Task sync notice: {e}", file=sys.stderr)

        # Verschiebe Datei in processed Ordner
        target_path = os.path.join(proc_dir, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{fname}")
        try:
            shutil.move(fpath, target_path)
            processed_files.append({"file": fname, "task_id": task_id, "size": fsize})
        except Exception as e:
            print(f"[InboxWatcher] Move file error: {e}", file=sys.stderr)

    return {
        "status": "success",
        "watch_folder": watch_dir,
        "processed_count": len(processed_files),
        "processed_items": processed_files
    }

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

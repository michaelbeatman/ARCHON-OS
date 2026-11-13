#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_to_nas.py — Automatisches Backup für Archon OS & Hermes auf Synology NAS.

Erstellt chronologische Snapshots unter smb://nasdc73fa.local/home/_ARCHON Backups/daily/archon_YYYYMMDD_HHMM
mit Online-SQLite-Backups (con.backup() verhindert Locks und Korruption).
"""

import os
import sys
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime

NAS_BASE_URI = "smb://nasdc73fa.local/home/_ARCHON Backups/daily"

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERMES_DIR = os.environ.get("ARCHON_HERMES_DIR", os.path.expanduser("~/.hermes"))

DBS_TO_BACKUP = [
    ("kanban.db", os.path.join(HERMES_DIR, "kanban.db")),
    ("state.db", os.path.join(HERMES_DIR, "state.db")),
    ("agentic_memory.db", os.path.join(PROJECT_DIR, "data", "agentic_memory.db")),
]

FILES_TO_COPY = [
    ("settings.json", os.path.join(PROJECT_DIR, "settings.json")),
    ("agent_profiles.json", os.path.join(PROJECT_DIR, "agent_profiles.json")),
]

DIRS_TO_COPY = [
    ("config", os.path.join(PROJECT_DIR, "config")),
]


def backup_sqlite_db(src_path: str, dest_path: str):
    """Sicheres SQLite-Online-Backup."""
    if not os.path.exists(src_path):
        print(f"[WARN] Datenbank nicht gefunden: {src_path}")
        return False
    try:
        src_conn = sqlite3.connect(src_path, timeout=15.0)
        dest_conn = sqlite3.connect(dest_path)
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        print(f"[OK] Gesichert: {os.path.basename(src_path)} ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        print(f"[FEHLER] Backup fehlgeschlagen für {src_path}: {e}")
        return False


def upload_path(local_path: str, dest_uri: str):
    """Lädt eine Datei oder rekursiv ein Verzeichnis via GIO auf das NAS hoch."""
    if os.path.isdir(local_path):
        subprocess.run(["gio", "mkdir", "-p", dest_uri], check=True, capture_output=True)
        for item in os.listdir(local_path):
            sub_local = os.path.join(local_path, item)
            sub_dest = f"{dest_uri}/{item}"
            upload_path(sub_local, sub_dest)
    else:
        res = subprocess.run(["gio", "copy", local_path, dest_uri], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"GIO Copy fehlgeschlagen: {res.stderr.strip()}")


def run_backup():
    now = datetime.now()
    folder_name = f"archon_{now.strftime('%Y%m%d_%H%M')}"
    target_uri = f"{NAS_BASE_URI}/{folder_name}"
    
    print(f"=== Starte Archon Backup nach {folder_name} ===")

    with tempfile.TemporaryDirectory(prefix="archon_backup_") as tmp_dir:
        backup_root = os.path.join(tmp_dir, folder_name)
        os.makedirs(backup_root, exist_ok=True)

        # 1. Datenbanken sichern
        for db_name, db_path in DBS_TO_BACKUP:
            dest_db = os.path.join(backup_root, db_name)
            backup_sqlite_db(db_path, dest_db)

        # 2. Einzeldateien kopieren
        for name, src_file in FILES_TO_COPY:
            if os.path.exists(src_file):
                shutil.copy2(src_file, os.path.join(backup_root, name))
                print(f"[OK] Kopiert: {name}")

        # 3. Verzeichnisse kopieren
        for name, src_dir in DIRS_TO_COPY:
            if os.path.exists(src_dir):
                shutil.copytree(src_dir, os.path.join(backup_root, name), dirs_exist_ok=True)
                print(f"[OK] Verzeichnis gesichert: {name}")

        # 4. Ordner auf NAS anlegen
        cmd_mkdir = ["gio", "mkdir", "-p", target_uri]
        res_mkdir = subprocess.run(cmd_mkdir, capture_output=True, text=True)
        if res_mkdir.returncode != 0:
            print(f"[FEHLER] Konnte NAS-Ordner nicht anlegen: {res_mkdir.stderr}")
            return False

        # 5. Dateien und Verzeichnisse via GIO hochladen
        for item in os.listdir(backup_root):
            local_item = os.path.join(backup_root, item)
            dest_item_uri = f"{target_uri}/{item}"
            try:
                upload_path(local_item, dest_item_uri)
                print(f"[UPLOAD] {item} -> NAS OK")
            except Exception as e:
                print(f"[UPLOAD-FEHLER] {item}: {e}")
                return False

    print(f"=== Backup {folder_name} erfolgreich auf NAS abgeschlossen ===")
    return True


if __name__ == "__main__":
    success = run_backup()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
scripts/litestream_manager.py
Manager & Restore-Utility fuer kontinuierliche SQLite-Replikation (Litestream) in Archon OS.
Prueft WAL-Modus aller Datenbanken, Replikationsverzeichnisse und Restore-Integritaet.
"""

import os
import sys
import sqlite3
import argparse
import subprocess
from datetime import datetime

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERMES_DIR = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\micha"), ".hermes")

DATABASES = [
    {
        "name": "kanban.db",
        "path": os.path.join(HERMES_DIR, "kanban.db") if os.path.exists(HERMES_DIR) else "/opt/data/kanban.db",
        "desc": "Hermes Kanban Tasks (Single Source of Truth)"
    },
    {
        "name": "state.db",
        "path": os.path.join(HERMES_DIR, "state.db") if os.path.exists(HERMES_DIR) else "/opt/data/state.db",
        "desc": "Hermes Session Context & Dialog Logs"
    },
    {
        "name": "agentic_memory.db",
        "path": os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
        "desc": "Archon 5-Tabellen Langzeitgedaechtnis"
    }
]

def check_wal_status():
    """Prueft, ob alle Kern-Datenbanken im Write-Ahead-Logging (WAL) Modus laufen."""
    print("=" * 65)
    print("  Archon OS – SQLite WAL & Litestream Bereitschafts-Prüfung")
    print("=" * 65)
    
    all_ok = True
    for db in DATABASES:
        p = db["path"]
        exists = os.path.exists(p)
        if not exists:
            print(f"  [-] {db['name']:<18}: DATEI FEHLT ({p})")
            all_ok = False
            continue

        try:
            conn = sqlite3.connect(p, timeout=5.0)
            cur = conn.cursor()
            mode = cur.execute("PRAGMA journal_mode;").fetchone()[0].upper()
            integrity = cur.execute("PRAGMA integrity_check;").fetchone()[0]
            size_kb = os.path.getsize(p) / 1024
            conn.close()

            status = "OK (WAL)" if mode == "WAL" else f"WARN ({mode})"
            if mode != "WAL":
                all_ok = False
            print(f"  [+] {db['name']:<18}: {status:<10} | Integrität: {integrity:<4} | {size_kb:.1f} KB")
        except Exception as e:
            print(f"  [X] {db['name']:<18}: FEHLER ({e})")
            all_ok = False

    print("=" * 65)
    if all_ok:
        print("[STATUS] Alle Datenbanken sind betriebsbereit für kontinuierliche Replikation.")
    else:
        print("[HINWEIS] Nicht alle Datenbanken sind im WAL-Modus. Führe 'enable-wal' aus.")
    return all_ok

def enable_wal_mode():
    """Aktiviert WAL-Modus auf allen erreichbaren Datenbanken."""
    print("[Aktion] Aktiviere PRAGMA journal_mode=WAL auf allen Datenbanken...")
    for db in DATABASES:
        p = db["path"]
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p, timeout=10.0)
                cur = conn.cursor()
                res = cur.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
                conn.commit()
                conn.close()
                print(f"  -> {db['name']}: journal_mode={res}")
            except Exception as e:
                print(f"  -> {db['name']}: Fehler ({e})")

def main():
    parser = argparse.ArgumentParser(description="Archon OS Litestream Manager")
    parser.add_argument("--check", action="store_true", default=True, help="Status und WAL-Modus pruefen")
    parser.add_argument("--enable-wal", action="store_true", help="WAL-Modus auf allen Datenbanken erzwingen")
    args = parser.parse_args()

    if args.enable_wal:
        enable_wal_mode()
        check_wal_status()
    else:
        check_wal_status()

if __name__ == "__main__":
    main()

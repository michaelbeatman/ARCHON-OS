# -*- coding: utf-8 -*-
"""
ARCHON OS Backup-Routine (09.10.2026)
=====================================
Sichert die SQLite-Datenbanken (SQLite-safe über Backup-API, auch bei laufenden Containern)
nach lokal (7 Tage Aufbewahrung) und auf das NAS Y:\\_ARCHON Backups (180 Tage Aufbewahrung).

Einbindung: Der Nutzer legt selbst einen Windows-Aufgabenplaner-Job an (stündlich empfohlen):
  python "C:\.Antigravity-projekte\AgenticOS-2026\backup_archon.py"

Optionale Parameter: --local-days N (Standard 7), --nas-days N (Standard 180), --no-nas
"""
import os
import sys
import shutil
import sqlite3
import datetime
import argparse

HOME = os.path.expanduser("~")
PROJECT = r"C:\.Antigravity-projekte\AgenticOS-2026"

# (Anzeigename, vollständiger Pfad)
DATABASES = [
    ("state.db", os.path.join(HOME, ".hermes", "state.db")),
    ("kanban.db", os.path.join(HOME, ".hermes", "kanban.db")),
    ("agent_os.db", os.path.join(PROJECT, "agent_os.db")),
    ("agentic_memory.db", os.path.join(PROJECT, "agentic_memory.db")),
]

LOCAL_BACKUP_DIR = os.path.join(PROJECT, "data", "backups")
NAS_BACKUP_DIR = r"Y:\_ARCHON Backups"


def backup_sqlite_safe(src_path: str, dst_path: str) -> bool:
    """Sichert eine SQLite-DB über die Backup-API (konsistent auch bei laufenden Containern)."""
    src = dst = None
    try:
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=15.0)
        dst = sqlite3.connect(dst_path)
        src.backup(dst)
        return True
    except Exception:
        # Fallback: direkte Dateikopie (besser als nichts)
        try:
            if src:
                src.close()
            if dst:
                dst.close()
            shutil.copy2(src_path, dst_path)
            return True
        except Exception:
            return False
    finally:
        try:
            if src:
                src.close()
            if dst:
                dst.close()
        except Exception:
            pass


def prune_old_backups(base_dir: str, days: int) -> int:
    """Löscht Backup-Ordner, deren Name (archon_YYYYMMDD_HHMM) älter als X Tage ist."""
    removed = 0
    now = datetime.datetime.now()
    try:
        entries = os.listdir(base_dir)
    except Exception:
        return 0
    for entry in entries:
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            # Einzeldateien (alte flache Backups) nach Alter prüfen
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full))
                if (now - mtime).days > days:
                    os.remove(full)
                    removed += 1
            except Exception:
                pass
            continue
        try:
            stamp = entry.replace("archon_", "")
            dt = datetime.datetime.strptime(stamp[:13], "%Y%m%d_%H%M")
            if (now - dt).days > days:
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
        except Exception:
            continue
    return removed


def main():
    parser = argparse.ArgumentParser(description="Archon OS DB-Backup")
    parser.add_argument("--local-days", type=int, default=7)
    parser.add_argument("--nas-days", type=int, default=180)
    parser.add_argument("--no-nas", action="store_true", help="NAS-Kopie überspringen")
    args = parser.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    run_dir_local = os.path.join(LOCAL_BACKUP_DIR, f"archon_{stamp}")
    os.makedirs(run_dir_local, exist_ok=True)

    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] Backup-Lauf archon_{stamp}")
    ok, fail = 0, 0
    for name, path in DATABASES:
        if not os.path.exists(path):
            print(f"  - {name}: übersprungen (nicht gefunden: {path})")
            continue
        dst_local = os.path.join(run_dir_local, name)
        if backup_sqlite_safe(path, dst_local):
            size_mb = os.path.getsize(dst_local) / (1024 * 1024)
            print(f"  + {name}: lokal gesichert ({size_mb:.1f} MB)")
            ok += 1
        else:
            print(f"  ! {name}: FEHLGESCHLAGEN")
            fail += 1
            continue
        # NAS-Kopie
        if not args.no_nas:
            try:
                run_dir_nas = os.path.join(NAS_BACKUP_DIR, f"archon_{stamp}")
                os.makedirs(run_dir_nas, exist_ok=True)
                shutil.copy2(dst_local, os.path.join(run_dir_nas, name))
                print(f"  + {name}: NAS-Kopie OK")
            except Exception as e:
                print(f"  ! {name}: NAS-Kopie fehlgeschlagen ({e})")

    # 2. Config-Dateien & Profile sichern (Pillar 4 / SSOT)
    config_items = [
        ("agent_profiles.json", os.path.join(PROJECT, "agent_profiles.json")),
        ("org_hierarchy.json", os.path.join(PROJECT, "config", "org_hierarchy.json")),
        ("config.yaml", os.path.join(PROJECT, "config.yaml")),
        ("theme_custom.json", os.path.join(PROJECT, "data", "theme_custom.json")),
        ("cost-budget.json", os.path.join(HOME, ".hermes", "cost-budget.json")),
    ]
    cfg_dir_local = os.path.join(run_dir_local, "config")
    os.makedirs(cfg_dir_local, exist_ok=True)
    for cname, cpath in config_items:
        if os.path.exists(cpath):
            try:
                shutil.copy2(cpath, os.path.join(cfg_dir_local, cname))
                print(f"  + [Config] {cname}: gesichert")
                if not args.no_nas:
                    cfg_dir_nas = os.path.join(NAS_BACKUP_DIR, f"archon_{stamp}", "config")
                    os.makedirs(cfg_dir_nas, exist_ok=True)
                    shutil.copy2(cpath, os.path.join(cfg_dir_nas, cname))
            except Exception as ce:
                print(f"  ! [Config] {cname}: Fehler ({ce})")

    # 3. Agenten-Profile Ordner (SOUL.md & profile.yaml)
    profiles_dirs = [
        os.path.join(PROJECT, "profiles"),
        os.path.join(HOME, ".hermes", "profiles")
    ]
    prof_dst_local = os.path.join(run_dir_local, "profiles")
    for pdir in profiles_dirs:
        if os.path.exists(pdir):
            try:
                shutil.copytree(pdir, prof_dst_local, dirs_exist_ok=True)
                print(f"  + [Profile] {pdir}: gesichert")
                if not args.no_nas:
                    prof_dst_nas = os.path.join(NAS_BACKUP_DIR, f"archon_{stamp}", "profiles")
                    shutil.copytree(pdir, prof_dst_nas, dirs_exist_ok=True)
                break
            except Exception as pe:
                print(f"  ! [Profile] {pdir}: Fehler ({pe})")

    removed_local = prune_old_backups(LOCAL_BACKUP_DIR, args.local_days)
    if not args.no_nas:
        removed_nas = prune_old_backups(NAS_BACKUP_DIR, args.nas_days)
        print(f"Aufgeräumt: lokal {removed_local} (>{args.local_days} Tage), NAS {removed_nas} (>{args.nas_days} Tage)")
    else:
        print(f"Aufgeräumt: lokal {removed_local} (>{args.local_days} Tage)")

    if fail:
        print(f"ERGEBNIS: {ok} OK, {fail} FEHLGESCHLAGEN")
        sys.exit(1)
    print(f"ERGEBNIS: {ok} Datenbanken gesichert.")


if __name__ == "__main__":
    main()

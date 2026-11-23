# -*- coding: utf-8 -*-
"""
ARCHON OS Backup-Routine (09.10.2026)
=====================================
Sichert die SQLite-Datenbanken (SQLite-safe über Backup-API, auch bei laufenden Containern)
nach lokal (7 Tage Aufbewahrung) und auf das NAS Y:\\_ARCHON Backups (180 Tage Aufbewahrung).

Einbindung: Der Nutzer legt selbst einen Windows-Aufgabenplaner-Job an (stündlich empfohlen):
  python ".\backup_archon.py"

Optionale Parameter: --local-days N (Standard 7), --nas-days N (Standard 180), --no-nas
"""
import logging
_archon_exc_logger = logging.getLogger("backup_archon")
import os
import sys
import shutil
import sqlite3
import datetime
import argparse

HOME = os.path.expanduser("~")
PROJECT = r"."

# (Anzeigename, vollständiger Pfad, Pflicht?)
# Pfade decken sich mit config/litestream.yml (Hermes-Home, Konsolidierungs-DBs)
# und den lokalen Root-DBs. "optional" = konsolidierte DB, die erst nach
# Aktivierung der 28→3-Migration existiert; fehlt sie, wird das explizit
# gemeldet statt still als Erfolg gezählt.
DATABASES = [
    ("hermes_state.db", os.path.join(HOME, ".hermes", "state.db"), True),
    ("hermes_kanban.db", os.path.join(HOME, ".hermes", "kanban.db"), True),
    ("agent_os.db", os.path.join(PROJECT, "agent_os.db"), True),
    ("agentic_memory.db", os.path.join(PROJECT, "agentic_memory.db"), True),
    ("ops.db", os.path.join(PROJECT, "data", "ops.db"), False),
    ("business.db", os.path.join(PROJECT, "data", "business.db"), True),
    ("memory.db", os.path.join(PROJECT, "data", "memory.db"), False),
    ("kanban.db", os.path.join(PROJECT, "data", "kanban.db"), True),
    ("contracts.db", os.path.join(PROJECT, "data", "contracts.db"), True),
    ("deals.db", os.path.join(PROJECT, "data", "deals.db"), True),
    ("workflow_schedules.db", os.path.join(PROJECT, "data", "workflow_schedules.db"), True),
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
    except Exception as exc:
        # KRITISCH (Audit 23.11.2026): copy2 einer laufenden WAL-DB erzeugt
        # eine inkonsistente Kopie (letzte Commits fehlen), die sogar
        # integrity_check bestehen kann. Kein stiller Fallback — hart failen.
        _archon_exc_logger.error("[backup_archon] Online-Backup %s fehlgeschlagen: %s", src_path, exc)
        return False
    finally:
        try:
            if src:
                src.close()
            if dst:
                dst.close()
        except Exception as _exc:
            _archon_exc_logger.debug("[backup_archon] Ignorierte Ausnahme (Z.60): %s", _exc)


def prune_old_backups(base_dir: str, days: int) -> int:
    """Löscht Backup-Ordner, deren Name (archon_YYYYMMDD_HHMM) älter als X Tage ist."""
    removed = 0
    now = datetime.datetime.now()
    try:
        entries = os.listdir(base_dir)
    except Exception:
        return 0
    # KRITISCH (Audit 23.11.2026): die Rotation darf NUR eigene Backup-
    # Artefakte löschen. Der Break-Glass-Vault liegt im selben Verzeichnis
    # und würde sonst nach `--local-days` (7) still gelöscht.
    keep_files = {"break_glass_vault.enc", "break_glass_meta.json"}
    db_names = {name for name, _path, _required in DATABASES}
    for entry in entries:
        full = os.path.join(base_dir, entry)
        if not os.path.isdir(full):
            if entry in keep_files or entry not in db_names:
                continue
            # Einzeldateien (alte flache Backups) nach Alter prüfen
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full))
                if (now - mtime).days > days:
                    os.remove(full)
                    removed += 1
            except Exception as _exc:
                _archon_exc_logger.debug("[backup_archon] Ignorierte Ausnahme (Z.81): %s", _exc)
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
    ok, fail, nas_fail = 0, 0, 0
    for name, path, required in DATABASES:
        if not os.path.exists(path):
            if required:
                print(f"  ! {name}: FEHLT (Pflicht-DB nicht gefunden: {path})")
                fail += 1
            else:
                print(f"  - {name}: nicht vorhanden (Konsolidierung inaktiv: {path})")
            continue
        dst_local = os.path.join(run_dir_local, name)
        if not backup_sqlite_safe(path, dst_local):
            print(f"  ! {name}: FEHLGESCHLAGEN")
            fail += 1
            continue
        # Integritätsprüfung der gesicherten Kopie (sonst ist "OK" wertlos)
        try:
            check = sqlite3.connect(f"file:{dst_local}?mode=ro", uri=True)
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            check.close()
            if integrity != "ok":
                print(f"  ! {name}: Integritätsprüfung fehlgeschlagen ({integrity})")
                fail += 1
                continue
        except Exception as e:
            print(f"  ! {name}: Integritätsprüfung nicht möglich ({e})")
            fail += 1
            continue
        size_mb = os.path.getsize(dst_local) / (1024 * 1024)
        print(f"  + {name}: lokal gesichert ({size_mb:.1f} MB, integrity ok)")
        ok += 1
        # NAS-Kopie: Fehler zählen jetzt zum Exit-Code, statt nur gedruckt zu werden
        if not args.no_nas:
            try:
                run_dir_nas = os.path.join(NAS_BACKUP_DIR, f"archon_{stamp}")
                os.makedirs(run_dir_nas, exist_ok=True)
                shutil.copy2(dst_local, os.path.join(run_dir_nas, name))
                print(f"  + {name}: NAS-Kopie OK")
            except Exception as e:
                print(f"  ! {name}: NAS-Kopie fehlgeschlagen ({e})")
                nas_fail += 1

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

    if fail or nas_fail:
        print(f"ERGEBNIS: {ok} OK, {fail} FEHLGESCHLAGEN, {nas_fail} NAS-Fehler")
        sys.exit(1)
    print(f"ERGEBNIS: {ok} Datenbanken gesichert (lokal + NAS).")


if __name__ == "__main__":
    main()

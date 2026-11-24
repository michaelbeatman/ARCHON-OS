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
import argparse
import datetime
import os
import shutil
import sqlite3
import sys

HOME = os.path.expanduser("~")
# Audit 23.11.2026: relativ zum CWD bedeutete "falsche Datei je nach Aufrufort".
PROJECT = os.path.dirname(os.path.abspath(__file__))
try:
    from backend.db_paths import APP_DATA_DIR, DB_BUSY_TIMEOUT_MS
except Exception:  # pragma: no cover - Standalone-Aufruf ohne Package-Kontext
    APP_DATA_DIR = os.path.join(PROJECT, "data")
    DB_BUSY_TIMEOUT_MS = 5000

# (Anzeigename, vollständiger Pfad, Pflicht?)
# Pfade decken sich mit config/litestream.yml (Hermes-Home, Konsolidierungs-DBs)
# und den lokalen Root-DBs. "optional" = konsolidierte DB, die erst nach
# Aktivierung der 28→3-Migration existiert; fehlt sie, wird das explizit
# gemeldet statt still als Erfolg gezählt.
DATABASES = [
    ("hermes_state.db", os.path.join(HOME, ".hermes", "state.db"), True),
    ("hermes_kanban.db", os.path.join(HOME, ".hermes", "kanban.db"), True),
    # D03/MED: veraltete Root-Pfade sind OPTIONAL — die produktiven Daten
    # liegen unter APP_DATA_DIR/tenants/<tid>/. Als required=True erzeugten sie
    # routinemaessig Exit 1, obwohl nichts fehlte.
    ("agent_os.db", os.path.join(PROJECT, "agent_os.db"), False),
    ("agentic_memory.db", os.path.join(PROJECT, "agentic_memory.db"), False),
    ("ops.db", os.path.join(APP_DATA_DIR, "ops.db"), False),
    ("business.db", os.path.join(APP_DATA_DIR, "business.db"), True),
    ("memory.db", os.path.join(APP_DATA_DIR, "memory.db"), False),
    # W2: die echte Kanban-DB liegt laut backend/db_paths.py in ~/.hermes
    # (siehe hermes_kanban.db oben). data/kanban.db ist ein Legacy-Leerpfad
    # und löste此前 Fehlalarme mit Exit-Code 1 aus — nicht mehr Pflicht.
    ("kanban.db", os.path.join(PROJECT, "data", "kanban.db"), False),
    ("contracts.db", os.path.join(APP_DATA_DIR, "contracts.db"), False),
    ("deals.db", os.path.join(APP_DATA_DIR, "deals.db"), False),
    ("workflow_schedules.db", os.path.join(PROJECT, "data", "workflow_schedules.db"), False),
    # KRITISCH (Audit 23.11.2026, K2): die CRM-Hauptdatenbank war in KEINEM
    # wiederkehrenden Backup enthalten. Kontakte, nachrichtenverlauf und
    # DSGVO-Felder wären bei Datenverlust dauerhaft weg. Online-Backup über
    # die SQLite Backup-API (siehe backup_sqlite_safe) ist WAL-sicher.
    ("pb_data.db", os.path.join(PROJECT, "pocketbase", "pb_data", "data.db"), True),
]

# Audit D03/D10: bei FULL_TENANT_ISOLATION liegen die echten Mandanten-DBs
# unter data/tenants/<tid>/. Der regelmäßige Backup-Job kannte sie nicht und
# sicherte nur stale Root-Dateien. Dynamisch ergänzen (optional: ein leerer
# oder gelöschter Mandant darf den Lauf nicht scheitern lassen).
_TENANT_ROOTS = [
    os.path.join(APP_DATA_DIR, "tenants"),
    os.path.join(PROJECT, "data", "tenants"),  # Workspace-Legacy
]
_seen_tenant_paths = set()
for _root in _TENANT_ROOTS:
    if not os.path.isdir(_root):
        continue
    for _tid in sorted(os.listdir(_root)):
        _tdir = os.path.join(_root, _tid)
        if not os.path.isdir(_tdir) or _tid.startswith("."):
            continue
        # D03/HIGH: alle produktiven Mandanten-DBs sichern, nicht nur drei
        # konsolidierte Namen (erp/kanban/crm/contracts/deals fehlten).
        for _name in sorted(os.listdir(_tdir)):
            if not _name.endswith(".db"):
                continue
            _path = os.path.abspath(os.path.join(_tdir, _name))
            if os.path.isfile(_path) and _path not in _seen_tenant_paths:
                _seen_tenant_paths.add(_path)
                _stem = _name[:-3]
                DATABASES.append((f"tenant_{_tid}_{_stem}", _path, False))

LOCAL_BACKUP_DIR = os.path.join(PROJECT, "data", "backups")
NAS_BACKUP_DIR = r"Y:\_ARCHON Backups"


def backup_sqlite_safe(src_path: str, dst_path: str) -> bool:
    """Sichert eine SQLite-DB über die Backup-API (konsistent auch bei laufenden Containern)."""
    src = dst = None
    try:
        src = sqlite3.connect(
            f"file:{src_path}?mode=ro", uri=True, timeout=DB_BUSY_TIMEOUT_MS / 1000.0
        )
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
            # D03/MED: relationale Konsistenz gehoert in die Backup-Verifikation.
            fk_violations = check.execute("PRAGMA foreign_key_check").fetchall()
            check.close()
            if integrity != "ok" or fk_violations:
                print(
                    f"  ! {name}: Verifikation fehlgeschlagen "
                    f"(integrity={integrity}, fk_violations={len(fk_violations)})"
                )
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

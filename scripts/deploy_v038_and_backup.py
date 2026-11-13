#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deploy_v038_and_backup.py

Vollstaendiges Release- und Backup-Skript fuer Archon OS v0.3.8 (Enterprise ERP & CRM Release).

1. Erstellt ein vollstaendiges Tages-Backup:
   - Online-Backup aller SQLite-Datenbanken (kanban.db, agent_os.db, agentic_memory.db, data.db)
   - settings.json, agent_profiles.json, config/, data/snapshots/
   - Ziel: /mnt/raid/_ARCHON Backups/daily\\archon_YYYYMMDD_HHMM (wenn verbunden)
     sowie data/backups/daily/archon_YYYYMMDD_HHMM (lokal)

2. Baut das vollstaendige Release-Paket v0.3.8:
   - AgenticOS-2026_GitBundle_v0.3.8.bundle
   - AgenticOS-2026_Homeserver_Deploy_v0.3.8.zip (blank / standard)
   - AgenticOS-2026_Homeserver_Deploy_v0.3.8_inkl.Wissensdatenbank.zip
   - docker-compose.yml, Dockerfile, setup_homeserver.ps1, setup_homeserver.sh
   - Installationsanweisung fuer Menschen.txt
   - SERVER_HANDOVER.md
   - Ziel: /mnt/raid/_ARCHON Backups/releases\\Archon v0.3.8 (wenn verbunden)
     sowie backups/Archon_v0.3.8 (lokal)
"""

import os
import sys
import shutil
import sqlite3
import subprocess
import zipfile
import time
from datetime import datetime
from pathlib import Path

VERSION = "v0.3.8"
BASE_DIR = Path(__file__).resolve().parent.parent

# NAS Pfade
NAS_ROOT = Path(r"Y:\_ARCHON Backups")
NAS_RELEASES = NAS_ROOT / "releases" / f"Archon {VERSION}"
NAS_DAILY = NAS_ROOT / "daily"

# Lokale Fallback- & Bereitstellungspfade
LOCAL_RELEASES = BASE_DIR / "backups" / f"Archon_{VERSION}"
LOCAL_DAILY = BASE_DIR / "data" / "backups" / "daily"

EXCLUDE_DIRS = {
    ".git", ".venv", ".venv-tools", "venv", "env", "__pycache__", "node_modules",
    ".hermes", "_archive_legacy", "backups", "_ARCHON Backups", "LinkedIn-backup",
    "OpenMontage", "paperclip", "paperclip_data", "library", "archive", "static_backup",
    "browser-use", "antigravity_complete_skills_package", "dist", "build", "staging",
    "agent_workspace", "obsidian_vault", "pocketbase-media", "omniroute_data",
    "quartz_app", "pb_data", "audio_cache", "obsidian-config", "inbox",
    "exported_vault", "hermes_profiles", "quickchat_sessions", "autogen", "logs",
    "frontend", "prime-agent", "chrome-extension", "scratch"
}

EXCLUDE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".bak", ".tmp", ".zip", ".tar.gz", ".tar", ".gz",
    ".bundle", ".mp4", ".mp3", ".wav", ".ogg", ".webm", ".mov", ".avi",
    ".pdf", ".db", ".sqlite", ".sqlite3", ".db-shm", ".db-wal", ".db-journal",
    ".xlsx", ".csv"
}

SENSITIVE_PATTERNS = [
    "api-key", "apikey", "credentials", "gmail_token", "google_token",
    "protokoll", "protocol", "bewerbung", "lebenslauf", "korrespondenz",
    "outreach", "vakanz", "anzeige", "diagnostik", "adhs", "delst",
    "vorlage_pre_", "vorlage_inline", "handoff_2026", "handover_2026",
    "session_handoff", "migration_handoff", "keller", "pe_haeuser"
]


def backup_sqlite(src_path: Path, dest_path: Path):
    if not src_path.exists():
        print(f"[WARN] Datenbank nicht gefunden: {src_path}")
        return False
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        # WAL-freundliche URI-Verbindung
        src_uri = f"file:{src_path.resolve().as_posix()}?mode=ro"
        src_conn = sqlite3.connect(src_uri, uri=True, timeout=15.0)
        dest_conn = sqlite3.connect(str(dest_path))
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
        size_kb = dest_path.stat().st_size / 1024
        print(f"[OK] Gesichert: {dest_path.name} ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"[FEHLER] Backup fehlgeschlagen fuer {src_path}: {e}")
        return False


def run_daily_backup(target_dirs):
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    
    for base_target in target_dirs:
        backup_folder = base_target / f"archon_{now_str}"
        backup_folder.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Erstelle System-Backup in: {backup_folder} ===")

        # 1. Datenbanken
        kanban_src = Path(r"~/.hermes\kanban.db")
        if not kanban_src.exists():
            kanban_src = BASE_DIR / "kanban.db"
        backup_sqlite(kanban_src, backup_folder / "kanban.db")

        agent_os_src = BASE_DIR / "agent_os.db"
        backup_sqlite(agent_os_src, backup_folder / "agent_os.db")

        memory_src = BASE_DIR / "data" / "agentic_memory.db"
        backup_sqlite(memory_src, backup_folder / "agentic_memory.db")

        pb_src = BASE_DIR / "pocketbase" / "pb_data" / "data.db"
        backup_sqlite(pb_src, backup_folder / "data.db")

        erp_src = BASE_DIR / "data" / "tenants" / "archon-systems" / "erp.db"
        if erp_src.exists():
            backup_sqlite(erp_src, backup_folder / "erp.db")

        # 2. Configs & Settings
        for f in ["settings.json", "agent_profiles.json", "requirements.txt"]:
            sp = BASE_DIR / f
            if sp.exists():
                shutil.copy2(sp, backup_folder / f)
                print(f"[OK] Kopiert: {f}")

        # 3. Verzeichnisse
        for d in ["config", "docs", "plugins"]:
            sd = BASE_DIR / d
            if sd.exists():
                shutil.copytree(sd, backup_folder / d, dirs_exist_ok=True)
                print(f"[OK] Verzeichnis gesichert: {d}")

        # Snapshots wenn vorhanden
        snap_dir = BASE_DIR / "data" / "snapshots"
        if snap_dir.exists():
            shutil.copytree(snap_dir, backup_folder / "snapshots", dirs_exist_ok=True)
            print("[OK] Snapshots gesichert.")

        print(f"[ERFOLG] Backup abgeschlossen unter: {backup_folder}")


def is_forbidden(rel_path: str, filename: str) -> bool:
    nl = filename.lower()
    pl = rel_path.lower()

    if nl.startswith(".env") and filename != ".env.example":
        return True
    if any(k in nl for k in ("token.json", "credential", "secret.json", "tree_cache", "synced_")):
        return True
    if any(nl.endswith(ext) for ext in EXCLUDE_EXTS):
        if nl in {"fabric_patterns_de.csv", "skills_marketplace_catalog.json"}:
            pass
        else:
            return True
    if any(pat in pl for pat in SENSITIVE_PATTERNS):
        return True
    return False


def build_deploy_zip(target_zip: Path, include_full_wissen: bool = False):
    print(f"\n[ZIP] Erstelle Deploy-Archiv ({'inkl. Wissen' if include_full_wissen else 'Clean/Standard'}): {target_zip.name}...")
    target_zip.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    counter = [0, 0]

    with zipfile.ZipFile(target_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            for file in sorted(files):
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, BASE_DIR).replace("\\", "/")

                if is_forbidden(rel, file):
                    continue

                zf.write(fp, arcname=rel)
                counter[0] += 1
                counter[1] += os.path.getsize(fp)

        # Optionale externe Wissensbibliothek
        wissen_source = Path(r"./obsidian_vault\02_Wissensbibliothek")
        if include_full_wissen and check_path_exists(wissen_source):
            print(f"  -> Binde Wissensbibliothek ein aus: {wissen_source}")
            for root, dirs, files in os.walk(wissen_source):
                for file in sorted(files):
                    fp = os.path.join(root, file)
                    rel_sub = os.path.relpath(fp, wissen_source).replace("\\", "/")
                    arcname = f"obsidian_vault/02_Wissensbibliothek/{rel_sub}"
                    if not is_forbidden(arcname, file):
                        zf.write(fp, arcname=arcname)
                        counter[0] += 1
                        counter[1] += os.path.getsize(fp)

    elapsed = time.time() - t0
    size_mb = target_zip.stat().st_size / (1024 * 1024)
    print(f"[OK] {target_zip.name}: {counter[0]} Dateien, {size_mb:.1f} MB (Dauer: {elapsed:.1f}s)")


def create_git_bundle(target_bundle: Path):
    print(f"\n[Git Bundle] Erstelle Git Bundle: {target_bundle.name}...")
    target_bundle.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["git", "bundle", "create", str(target_bundle), "HEAD", "main"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True
    )
    if res.returncode == 0:
        size_mb = target_bundle.stat().st_size / (1024 * 1024)
        print(f"[OK] Git Bundle erfolgreich erstellt ({size_mb:.1f} MB)")
    else:
        print(f"[WARN] Git Bundle Fehler: {res.stderr}")


def write_instructions(release_dir: Path):
    txt_path = release_dir / "Installationsanweisung für Menschen.txt"
    content = f"""Installationshinweise Archon OS — Release {VERSION} (02. November 2026)

1. Dateien auf den Homeserver kopieren (z. B. via NAS smb://nasdc73fa.local/home/_ARCHON Backups/releases/Archon {VERSION}, SCP, SFTP oder USB-Stick).

2. Beliebigen Agenten (Antigravity, Codex, Claude Code etc.) auf dem Homeserver aktivieren mit folgendem Prompt:

"Hier liegt die AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip. Bitte entpacke das Archiv, lies das darin enthaltene SERVER_HANDOVER.md und aktualisiere Archon OS auf Version {VERSION}."

Damit uebernimmt der dortige Agent eigenstaendig die Konfiguration, Container-Aktualisierung und Datenbankmigrationen.

Neue Kernfunktionen in Version {VERSION} (Enterprise ERP & CRM Release):
- Säule 3: WIRTSCHAFT & ERP (Hauptnavigation):
  * Adressen & CRM (nav-addresses):
    - 6-Tab Enterprise ERP Kontakt-Drawer (Übersicht 50/50, Nachrichten-Timeline, Kaufmännische Stammdaten, Belege & Vorgänge, Ansprechpartner, DSGVO).
    - Ergonomische Fenstersteuerung: Schließen via Backdrop-Klick, Escape-Taste, Abbrechen-Button oder ✕ oben rechts.
    - DSGVO & Compliance: 1-Klick JSON-Export (Art. 15/20) & rechtssichere Anonymisierung (Art. 17).
    - Editierbare Werbeeinwilligungen (E-Mail, Telefon, Post), Rechtsgrundlagen-Auswahl (Art. 6) und Werbewiderspruch-Sperre (Art. 21).
  * Artikel & Leistungen (nav-items):
    - Modularer Artikel-Drawer mit 80px-Header und 4 Teilansichten: Stammdaten, Preise & Staffeln (Marge, SKR03/04), Bestand & Konditionen (SaaS/Abo, Disposition) und Beleg-Verkaufshistorie.
  * Vorgänge & Verträge (nav-operations-erp):
    - DIN-5008 Belegdruck & PDF-Export für Angebote (ANG) und Auftragsbestätigungen (AB).
    - Direkte Belegkalkulation mit Positionsauswahl aus dem Artikelstamm im Kontakt-Drawer.
    - 1-Klick-Wandlung: Angebot -> Auftrag -> GoBD-Ausgangsrechnung (RE).
  * Corporate & Vorlagen (nav-corporate):
    - Multi-Tenant Mandantenverwaltung und DIN-5008 Vorlagen-Studio.
- Vollstaendige Git-Historie bis {VERSION} (AgenticOS-2026_GitBundle_{VERSION}.bundle).
"""
    txt_path.write_text(content, encoding="utf-8")
    print(f"[OK] Installationsanweisung geschrieben: {txt_path.name}")


def check_path_exists(p: Path) -> bool:
    try:
        return p.exists()
    except (PermissionError, OSError):
        return False


def run():
    print("=" * 65)
    print(f"STARTE BACKUP & RELEASE {VERSION}")
    print("=" * 65)

    nas_available = check_path_exists(NAS_ROOT)
    target_daily = [LOCAL_DAILY]
    if nas_available:
        target_daily.append(NAS_DAILY)
        print(f"[NAS] NAS-Verbindung erkannt: {NAS_ROOT}")
    else:
        print(f"[HINWEIS] NAS ({NAS_ROOT}) aktuell nicht gemountet. Erstelle vollstaendiges Release lokal in {LOCAL_RELEASES}.")

    # 1. Tages-Backup
    run_daily_backup(target_daily)

    # 2. Release-Ziele definieren
    release_targets = [LOCAL_RELEASES]
    if nas_available:
        release_targets.append(NAS_RELEASES)

    for rel_dir in release_targets:
        rel_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Erstelle Release {VERSION} in: {rel_dir} ===")

        # Root-Dateien kopieren
        for f in ["docker-compose.yml", "Dockerfile", "setup_homeserver.ps1", "setup_homeserver.sh", "SERVER_HANDOVER.md"]:
            sp = BASE_DIR / f
            if sp.exists():
                shutil.copy2(sp, rel_dir / f)
                print(f"[OK] Bereitgestellt: {f}")

        # Handbuecher mitkopieren
        for docx_file in ["ARCHON_OS_SYSTEM_HANDBUCH_2026.docx", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"]:
            sp = BASE_DIR / "docs" / "system" / docx_file
            if sp.exists():
                shutil.copy2(sp, rel_dir / docx_file)
                print(f"[OK] Handbuch bereitgestellt: {docx_file}")

        # Instructions
        write_instructions(rel_dir)

        # Git Bundle
        bundle_path = rel_dir / f"AgenticOS-2026_GitBundle_{VERSION}.bundle"
        create_git_bundle(bundle_path)

        # Deploy ZIPs
        zip_blank = rel_dir / f"AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip"
        build_deploy_zip(zip_blank, include_full_wissen=False)

        zip_wissen = rel_dir / f"AgenticOS-2026_Homeserver_Deploy_{VERSION}_inkl.Wissensdatenbank.zip"
        build_deploy_zip(zip_wissen, include_full_wissen=True)

    # 3. Synchronisations-Hilfsskript fuer NAS erstellen
    sync_bat = BASE_DIR / "scripts" / "copy_v038_to_nas.bat"
    sync_bat_content = f"""@echo off
chcp 65001 >nul
echo =======================================================
echo   Archon OS {VERSION} - Synchronisation zum Synology NAS
echo =======================================================
echo.

if exist "Y:\\_ARCHON Backups" (
    set "DEST=/mnt/raid/_ARCHON Backups/releases\\Archon {VERSION}"
) else (
    echo [WARNUNG] Laufwerk Y: ist nicht verbunden!
    echo Versuche Netzwerkpfad \\\\nasdc73fa.local\\home\\_ARCHON Backups ...
    set "DEST=\\\\nasdc73fa.local\\home\\_ARCHON Backups\\releases\\Archon {VERSION}"
)

echo Zielverzeichnis: %DEST%
mkdir "%DEST%" 2>nul

echo.
echo Kopiere Release-Dateien...
robocopy "{LOCAL_RELEASES}" "%DEST%" /E /Z /R:2 /W:2

echo.
echo =======================================================
echo   Synchronisation abgeschlossen!
echo =======================================================
pause
"""
    sync_bat.write_text(sync_bat_content, encoding="utf-8")
    print(f"\n[OK] NAS-Sync-Hilfsskript erstellt: {sync_bat}")

    print("\n" + "=" * 65)
    print(f"RELEASE {VERSION} & BACKUP ERFOLGREICH ABGESCHLOSSEN!")
    print(f"Lokaler Pfad: {LOCAL_RELEASES}")
    if nas_available:
        print(f"NAS Pfad:    {NAS_RELEASES}")
    print("=" * 65)


if __name__ == "__main__":
    run()

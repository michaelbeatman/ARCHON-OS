#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deploy_v035_and_backup.py

1. Erstellt ein vollständiges Tages-Backup auf dem NAS:
   Y:\_ARCHON Backups\daily\archon_YYYYMMDD_HHMM
   - Online-Backup von kanban.db, agent_os.db, agentic_memory.db
   - settings.json, agent_profiles.json, config/, data/snapshots/

2. Baut das vollständige Release-Paket v0.3.5 auf dem NAS:
   Y:\_ARCHON Backups\releases\Archon v0.3.5
   - AgenticOS-2026_GitBundle_v0.3.5.bundle
   - AgenticOS-2026_Homeserver_Deploy_v0.3.5.zip (blank / standard)
   - AgenticOS-2026_Homeserver_Deploy_v0.3.5_inkl.Wissensdatenbank.zip
   - docker-compose.yml, Dockerfile, setup_homeserver.ps1, setup_homeserver.sh
   - Installationsanweisung für Menschen.txt
   - SERVER_HANDOVER.md
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

VERSION = "v0.3.5"
BASE_DIR = Path(__file__).resolve().parent.parent

NAS_RELEASES = Path(r"Y:\_ARCHON Backups\releases") / f"Archon {VERSION}"
NAS_DAILY = Path(r"Y:\_ARCHON Backups\daily")

# Excluded directories for deploy zip
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
        src_conn = sqlite3.connect(str(src_path), timeout=15.0)
        dest_conn = sqlite3.connect(str(dest_path))
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
        size_kb = dest_path.stat().st_size / 1024
        print(f"[OK] Gesichert: {dest_path.name} ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"[FEHLER] Backup fehlgeschlagen für {src_path}: {e}")
        return False


def run_daily_backup():
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    backup_folder = NAS_DAILY / f"archon_{now_str}"
    backup_folder.mkdir(parents=True, exist_ok=True)
    print(f"\n=== 1. Erstelle tägliches System-Backup in: {backup_folder} ===")

    # 1. Datenbanken
    kanban_src = Path(r"C:\Users\micha\.hermes\kanban.db")
    if not kanban_src.exists():
        kanban_src = BASE_DIR / "kanban.db"
    backup_sqlite(kanban_src, backup_folder / "kanban.db")

    agent_os_src = BASE_DIR / "agent_os.db"
    backup_sqlite(agent_os_src, backup_folder / "agent_os.db")

    memory_src = BASE_DIR / "data" / "agentic_memory.db"
    backup_sqlite(memory_src, backup_folder / "agentic_memory.db")

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

    print(f"[ERFOLG] Tages-Backup abgeschlossen unter: {backup_folder}")
    return backup_folder


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
    if nl.startswith("~$") or ".bak" in nl:
        return True
    if not filename.endswith(".py"):
        for pat in SENSITIVE_PATTERNS:
            if pat in nl or pat in pl:
                return True
    return False


def should_exclude(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS or p.startswith("~$") or p.startswith(".cache"):
            return True
    return is_forbidden(rel_path, parts[-1])


def build_deploy_zip(target_zip: Path, include_full_wissen: bool = False):
    print(f"\n[Deploy-Paket] Erstelle: {target_zip.name} (Wissensdatenbank={include_full_wissen})...")
    t0 = time.time()
    counter = [0, 0]

    with zipfile.ZipFile(target_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Walk main workspace
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BASE_DIR).replace("\\", "/")

                if should_exclude(rel_path):
                    continue

                zf.write(full_path, arcname=rel_path)
                counter[0] += 1
                counter[1] += os.path.getsize(full_path)

        # Curated Obsidian folders
        root_vault = BASE_DIR / "obsidian_vault"
        if root_vault.exists():
            for root, dirs, files in os.walk(root_vault):
                for file in sorted(files):
                    fp = os.path.join(root, file)
                    rel_in = os.path.relpath(fp, root_vault).replace("\\", "/")
                    arcname = f"obsidian_vault/{rel_in}"
                    if not is_forbidden(arcname, file):
                        zf.write(fp, arcname=arcname)
                        counter[0] += 1
                        counter[1] += os.path.getsize(fp)

        # Wissensbibliothek
        wissen_source = Path(r"C:\Mein Obsidian\02_Wissensbibliothek")
        if include_full_wissen and wissen_source.exists():
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
    content = f"""Installationshinweise Archon OS — Release {VERSION} (28. Oktober 2026)

1. Dateien auf den Homeserver kopieren (z. B. via Google Drive, SCP, SFTP, USB oder Netzwerkfreigabe smb://nasdc73fa.local/home/_ARCHON Backups/releases/Archon {VERSION}).

2. Beliebigen Agenten (Antigravity, Codex, Claude Code etc.) auf dem Homeserver aktivieren mit folgendem kurzen Prompt:

"Hier liegt die AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip. Bitte entpacke das Archiv, lies das darin enthaltene SERVER_HANDOVER.md und richte Archon OS (Version {VERSION}) komplett eigenständig ein."

Damit weiß der dortige Agent sofort Bescheid, richtet das virtuelle Environment ein, prüft die Datenbanken und nimmt den Server in Betrieb.

Neue Kernfunktionen in Version {VERSION}:
- 1-Klick Updatesystem & GitHub-Sync:
  * Integriertes Continuous Deployment zwischen Entwicklungsrechner und Homeserver.
  * Automatische Pre-Update Snapshots aller SQLite-Datenbanken (WAL) in data/snapshots/ vor jedem Git-Pull.
  * 1-Klick Rollback-Funktion bei Fehlern oder fehlgeschlagenen Migrationen.
  * Git-Flags für minimale Stat-Prüfungen (-c core.checkstat=minimal) zur Vermeidung von Bind-Mount Timeouts.
- Standardisiertes Pluginsystem & Runtime-Hooks:
  * Modulare Erweiterungs-Architektur unter plugins/<plugin_id>/ mit plugin.json Manifest.
  * Lifecycle-Hooks (on_load, on_enable, on_disable, on_unload) und Tool-Interzeptoren (before_tool_execute, after_tool_execute).
  * 3 vorinstallierte Starter-Plugins: System Metrics (Hardware-Telemetrie), Security Audit Hook (Befehlsfilter & Secret-Maskierung) und Cost Guard (Token-Budget).
  * Live-Management und Konfiguration im System Control Center (Tab PLUGINS).
- Autonome Tiefenrecherche & Reflexionsschleife v2 (Research Lab):
  * Re-Search Loop: Zerlegung in 3–5 Teilfragen mit autonomer Lückenanalyse und bis zu 3 Nachfolge-Suchläufen.
  * Multi-Provider Fallback: Grokipedia / SearXNG mit nahtlosem Fallback auf Jina Reader API.
  * SSRF-Schutzfilter gegen Zugriffe auf lokale Subnetze und Cloud-Metadaten.
- Kanban Qualitäts-Gate (4-Augen-Review):
  * Automatisches Peer-Review vor Verschieben einer Aufgabe auf 'done'.
  * Katharina Völk (QM/Compliance) oder Robert bewertet das Ergebnis nach Vollständigkeit, Substanz und Handlungsfähigkeit.
  * Status-Sperre bei 'changes_requested' und Human-in-the-Loop Override.
- Interaktive Showroom-Sandbox & Live-Runner:
  * Direkte Ausführung von Python- und Code-Dateien aus dem Showroom heraus mit 12s Timeout.
  * Ausklappbares Terminal-Drawer mit STDOUT, STDERR, Exit-Code und Millisekunden-Laufzeit.
- Telegram Voice-Pipeline & Sprachausgabe:
  * Audio-Transkription eingehender Sprachmemos (.ogg/Opus) via Whisper/Gemini.
  * Automatisches Rufnamen-Routing an den zuständigen Agenten (/robert, /anwalt, etc.).
  * Natürliche Sprachausgabe via edge-tts (de-DE-ConradNeural) als Telegram-Sprachnachricht.
- Vollständige Git-Historie bis {VERSION} (AgenticOS-2026_GitBundle_{VERSION}.bundle).

Viel Erfolg!
"""
    txt_path.write_text(content, encoding="utf-8")
    print(f"[OK] Installationsanweisung geschrieben: {txt_path.name}")


def run():
    print("=" * 65)
    print(f"STARTE BACKUP & RELEASE {VERSION} FÜR NAS")
    print("=" * 65)

    # 1. Tages-Backup
    run_daily_backup()

    # 2. Release-Verzeichnis
    NAS_RELEASES.mkdir(parents=True, exist_ok=True)
    print(f"\n=== 2. Erstelle Release {VERSION} in: {NAS_RELEASES} ===")

    # Root-Dateien kopieren
    for f in ["docker-compose.yml", "Dockerfile", "setup_homeserver.ps1", "setup_homeserver.sh", "SERVER_HANDOVER.md"]:
        sp = BASE_DIR / f
        if sp.exists():
            shutil.copy2(sp, NAS_RELEASES / f)
            print(f"[OK] Bereitgestellt: {f}")

    # Instructions
    write_instructions(NAS_RELEASES)

    # Git Bundle
    bundle_path = NAS_RELEASES / f"AgenticOS-2026_GitBundle_{VERSION}.bundle"
    create_git_bundle(bundle_path)

    # Deploy ZIPs
    zip_blank = NAS_RELEASES / f"AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip"
    build_deploy_zip(zip_blank, include_full_wissen=False)

    zip_wissen = NAS_RELEASES / f"AgenticOS-2026_Homeserver_Deploy_{VERSION}_inkl.Wissensdatenbank.zip"
    build_deploy_zip(zip_wissen, include_full_wissen=True)

    print("\n" + "=" * 65)
    print(f"RELEASE {VERSION} & TAGES-BACKUP ERFOLGREICH AUF NAS ABGELEGT!")
    print(f"Pfad: {NAS_RELEASES}")
    print("=" * 65)


if __name__ == "__main__":
    run()

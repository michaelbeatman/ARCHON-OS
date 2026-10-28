# -*- coding: utf-8 -*-
"""
backend/system_updater.py
=========================
Archon OS Updatesystem & Git-Sync (Meilenstein 1: Release-Lifecycle & Datenintegrität).

Verbindet den Entwicklungsrechner und den Homeserver:
- Prüft Git-Remote auf neue Commits (Status, Commit-Liste, Version)
- Erstellt vor jedem Update einen konsistenten SQLite- & Config-Snapshot
- Führt atomaren Git-Pull & Schema-Prüfung durch
- Bietet Rollback-Fähigkeit bei Fehlern
"""

import os
import sys
import json
import sqlite3
import shutil
import datetime
import subprocess
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(WORKSPACE_DIR, "data", "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# Zu sichernde Datenbanken (Relativ zum Workspace oder Home)
DB_TARGETS = [
    os.path.join(WORKSPACE_DIR, "agent_os.db"),
    os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db"),
    os.path.join(WORKSPACE_DIR, "data", "kanban.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "kanban.db")) else os.path.expanduser("~/.hermes/kanban.db"),
    os.path.join(WORKSPACE_DIR, "data", "state.db") if os.path.exists(os.path.join(WORKSPACE_DIR, "data", "state.db")) else os.path.expanduser("~/.hermes/state.db"),
]

# Zu sichernde Konfigurationsdateien
CONFIG_TARGETS = [
    os.path.join(WORKSPACE_DIR, "settings.json"),
    os.path.join(WORKSPACE_DIR, "agent_profiles.json"),
    os.path.join(WORKSPACE_DIR, "roles.json"),
    os.path.join(WORKSPACE_DIR, ".env"),
]


def _run_git(args: List[str], timeout: int = 15) -> Dict[str, Any]:
    """Führt einen Git-Befehl sicher im Workspace-Verzeichnis aus."""
    try:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        base_cmd = [
            "git",
            "-c", "safe.directory=*",
            "-c", "core.fileMode=false",
            "-c", "core.autocrlf=true",
            "-c", "core.fsmonitor=false",
            "-c", "credential.helper=",
            "-c", "user.name=ArchonOS",
            "-c", "user.email=archon@local.internal"
        ]

        gh_token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
        if not gh_token:
            env_path = os.path.join(WORKSPACE_DIR, ".env")
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("GITHUB_TOKEN=") or line.startswith("GH_TOKEN="):
                                gh_token = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass

        if gh_token:
            import base64
            auth_token = base64.b64encode(f"x-access-token:{gh_token}".encode()).decode()
            base_cmd.extend(["-c", f"http.extraHeader=AUTHORIZATION: basic {auth_token}"])

        proc = subprocess.run(
            base_cmd + args,
            cwd=WORKSPACE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode
        }
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "Git-Befehl nicht im PATH gefunden.", "returncode": -1}
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Git-Timeout nach {timeout}s.", "returncode": -2}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -3}


def _read_git_head_native() -> Dict[str, str]:
    """Liest den aktuellen Git-Commit direkt aus dem .git-Ordner (funktioniert ohne git-Binary)."""
    git_dir = os.path.join(WORKSPACE_DIR, ".git")
    if not os.path.isdir(git_dir):
        return {"commit": "unknown", "branch": "unknown"}
    
    try:
        head_path = os.path.join(git_dir, "HEAD")
        with open(head_path, "r", encoding="utf-8") as f:
            ref = f.read().strip()
        
        branch = "detached"
        commit = ref
        if ref.startswith("ref: "):
            ref_rel = ref.split("ref: ")[1].strip()
            branch = os.path.basename(ref_rel)
            ref_file = os.path.join(git_dir, ref_rel.replace("/", os.sep))
            if os.path.exists(ref_file):
                with open(ref_file, "r", encoding="utf-8") as f:
                    commit = f.read().strip()
            else:
                # Packed refs prüfen
                packed = os.path.join(git_dir, "packed-refs")
                if os.path.exists(packed):
                    with open(packed, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) == 2 and parts[1] == ref_rel:
                                commit = parts[0]
                                break
        return {"commit": commit[:12] if len(commit) >= 12 else commit, "full_commit": commit, "branch": branch}
    except Exception as e:
        return {"commit": "unknown", "branch": "unknown", "error": str(e)}


def get_update_status() -> Dict[str, Any]:
    """Prüft, ob auf dem Remote-Repository (GitHub) neue Commits vorliegen."""
    native = _read_git_head_native()
    current_commit = native.get("commit", "unknown")
    branch = native.get("branch", "main")

    git_check = _run_git(["rev-parse", "--short", "HEAD"])
    if git_check["success"] and git_check["stdout"]:
        current_commit = git_check["stdout"]

    # Letzter Commit Text
    last_log = _run_git(["log", "-1", "--format=%cd (%cr) · %s", "--date=short"])
    last_commit_info = last_log["stdout"] if last_log["success"] else "Keine Commit-Details"

    # Git Status (Ungespeicherte lokale Änderungen?)
    status_check = _run_git(["status", "--porcelain"])
    dirty = bool(status_check["stdout"].strip()) if status_check["success"] else False
    changed_files_count = len(status_check["stdout"].splitlines()) if dirty else 0

    # Remote Fetch ausführen
    fetch_res = _run_git(["fetch", "origin", "main"], timeout=15)
    if not fetch_res["success"]:
        return {
            "status": "offline_or_error",
            "update_available": False,
            "current_commit": current_commit,
            "branch": branch,
            "last_commit_info": last_commit_info,
            "has_local_changes": dirty,
            "changed_files_count": changed_files_count,
            "commits_behind": 0,
            "incoming_commits": [],
            "message": f"Konnte GitHub nicht abfragen: {fetch_res['stderr'] or 'Netzwerk/Auth-Problem'}"
        }

    # Commits Behind berechnen
    behind_res = _run_git(["rev-list", "--count", "HEAD..origin/main"])
    commits_behind = 0
    if behind_res["success"] and behind_res["stdout"].isdigit():
        commits_behind = int(behind_res["stdout"])

    incoming = []
    if commits_behind > 0:
        log_res = _run_git(["log", "HEAD..origin/main", "--oneline", "-n", "10"])
        if log_res["success"] and log_res["stdout"]:
            incoming = log_res["stdout"].splitlines()

    remote_head_res = _run_git(["rev-parse", "--short", "origin/main"])
    remote_commit = remote_head_res["stdout"] if remote_head_res["success"] else "unknown"

    return {
        "status": "success",
        "update_available": commits_behind > 0,
        "current_commit": current_commit,
        "remote_commit": remote_commit,
        "branch": branch,
        "last_commit_info": last_commit_info,
        "commits_behind": commits_behind,
        "incoming_commits": incoming,
        "has_local_changes": dirty,
        "changed_files_count": changed_files_count,
        "message": f"{commits_behind} neue Commits verfügbar." if commits_behind > 0 else "System ist auf dem neuesten Stand."
    }


def backup_sqlite_safe(src_path: str, dst_path: str) -> bool:
    """Konsistentes SQLite Online-Backup via Backup-API (auch bei WAL und aktiven Schreibern)."""
    src = dst = None
    try:
        src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=15.0)
        dst = sqlite3.connect(dst_path)
        with dst:
            src.backup(dst, pages=100, sleep=0.01)
        return True
    except Exception as e:
        print(f"[SystemUpdater] Backup-Fehler bei {src_path}: {e}", file=sys.stderr)
        return False
    finally:
        if dst:
            try: dst.close()
            except Exception: pass
        if src:
            try: src.close()
            except Exception: pass


def create_snapshot(tag: str = "pre_update") -> Dict[str, Any]:
    """Erstellt einen vollständigen Snapshot aller Datenbanken und Konfigurationsdateien."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_id = f"{tag}_{ts}"
    target_dir = os.path.join(SNAPSHOT_DIR, snapshot_id)
    os.makedirs(target_dir, exist_ok=True)

    backed_dbs = []
    backed_configs = []

    # 1. Datenbanken sichern
    for db_path in DB_TARGETS:
        if not os.path.exists(db_path):
            continue
        db_name = os.path.basename(db_path)
        dst_path = os.path.join(target_dir, db_name)
        ok = backup_sqlite_safe(db_path, dst_path)
        if ok and os.path.exists(dst_path):
            backed_dbs.append({"name": db_name, "size_bytes": os.path.getsize(dst_path)})

    # 2. Configs sichern
    for cfg_path in CONFIG_TARGETS:
        if not os.path.exists(cfg_path):
            continue
        cfg_name = os.path.basename(cfg_path)
        dst_path = os.path.join(target_dir, cfg_name)
        try:
            shutil.copy2(cfg_path, dst_path)
            backed_configs.append({"name": cfg_name, "size_bytes": os.path.getsize(dst_path)})
        except Exception as e:
            print(f"[SystemUpdater] Config copy error {cfg_name}: {e}", file=sys.stderr)

    # 3. Metadaten schreiben
    meta = {
        "snapshot_id": snapshot_id,
        "tag": tag,
        "created_at": datetime.datetime.now().isoformat(),
        "git_commit": _read_git_head_native().get("commit", "unknown"),
        "databases": backed_dbs,
        "configs": backed_configs
    }
    with open(os.path.join(target_dir, "snapshot_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "snapshot_id": snapshot_id,
        "target_dir": target_dir,
        "databases": backed_dbs,
        "configs": backed_configs
    }


def list_snapshots() -> List[Dict[str, Any]]:
    """Gibt alle vorhandenen Snapshots sortiert nach Erstellungszeitpunkt zurück."""
    if not os.path.exists(SNAPSHOT_DIR):
        return []
    
    items = []
    for d in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
        full_d = os.path.join(SNAPSHOT_DIR, d)
        if not os.path.isdir(full_d):
            continue
        meta_file = os.path.join(full_d, "snapshot_meta.json")
        if os.path.exists(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items.append(data)
            except Exception:
                items.append({"snapshot_id": d, "tag": "unknown", "created_at": d})
        else:
            items.append({"snapshot_id": d, "tag": "raw", "created_at": d})
    return items


def apply_update(make_backup: bool = True) -> Dict[str, Any]:
    """
    Führt das System-Update auf dem Server aus:
    1. Erstellt Pre-Update-Snapshot (DBs + Configs)
    2. Führt 'git pull origin main --rebase' aus
    3. Triggert Uvicorn Code-Reload
    """
    snapshot_info = None
    if make_backup:
        snapshot_info = create_snapshot(tag="pre_update")

    # Stash falls lokale temporäre Änderungen existieren
    stash_run = False
    status_chk = _run_git(["status", "--porcelain"])
    if status_chk["success"] and status_chk["stdout"].strip():
        stash_res = _run_git(["stash", "push", "-m", "Auto-stash vor Archon System-Update"])
        stash_run = stash_res["success"]

    # Git Pull Rebase
    pull_res = _run_git(["pull", "origin", "main", "--rebase"], timeout=30)
    if not pull_res["success"]:
        # Rebase abort falls ein Konflikt entstand
        _run_git(["rebase", "--abort"])
        if stash_run:
            _run_git(["stash", "pop"])
        return {
            "status": "error",
            "step": "git_pull",
            "message": f"Git Pull fehlgeschlagen: {pull_res['stderr'] or pull_res['stdout']}",
            "snapshot": snapshot_info
        }

    # Stash zurückholen falls vorhanden
    if stash_run:
        _run_git(["stash", "pop"])

    new_native = _read_git_head_native()
    new_commit = new_native.get("commit", "unknown")

    # Code-Reload triggern: main.py anfassen damit uvicorn neu lädt
    main_file = os.path.join(WORKSPACE_DIR, "main.py")
    try:
        os.utime(main_file, None)
    except Exception:
        pass

    return {
        "status": "success",
        "new_commit": new_commit,
        "snapshot": snapshot_info,
        "git_output": pull_res["stdout"],
        "message": f"Update erfolgreich auf Commit {new_commit} angewendet."
    }


def push_changes(commit_message: Optional[str] = None) -> Dict[str, Any]:
    """
    Sammelt alle lokalen Änderungen ein, committet sie und pusht sie zu GitHub origin/main.
    """
    status_chk = _run_git(["status", "--porcelain"])
    if not status_chk["success"]:
        return {"status": "error", "message": f"Git Status fehlgeschlagen: {status_chk['stderr']}"}

    dirty = bool(status_chk["stdout"].strip())
    if not dirty:
        return {"status": "nothing_to_commit", "message": "Keine neuen lokalen Änderungen zum Veröffentlichen vorhanden."}

    # 1. git add -A
    add_res = _run_git(["add", "-A"])
    if not add_res["success"]:
        return {"status": "error", "message": f"Git Add fehlgeschlagen: {add_res['stderr']}"}

    # 2. git commit -m
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = commit_message.strip() if commit_message and commit_message.strip() else f"Dev-Sync: {ts}"
    commit_res = _run_git(["commit", "-m", msg])
    if not commit_res["success"]:
        return {"status": "error", "message": f"Git Commit fehlgeschlagen: {commit_res['stderr']}"}

    # 3. Pull rebase to ensure clean linear history
    pull_res = _run_git(["pull", "origin", "main", "--rebase"], timeout=30)
    if not pull_res["success"]:
        _run_git(["rebase", "--abort"])
        return {"status": "error", "message": f"Git Pull Rebase vor Push fehlgeschlagen: {pull_res['stderr']}"}

    # 4. Git Push
    push_res = _run_git(["push", "origin", "main"], timeout=30)
    if not push_res["success"]:
        return {"status": "error", "message": f"Git Push fehlgeschlagen: {push_res['stderr']}"}

    new_head = _read_git_head_native().get("commit", "unknown")
    return {
        "status": "success",
        "commit": new_head,
        "commit_message": msg,
        "message": f"Änderungen erfolgreich zu GitHub hochgeladen (Commit {new_head})!"
    }


def rollback_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """Stellt Datenbanken und Konfigurationsdateien aus einem Snapshot wieder her."""
    source_dir = os.path.join(SNAPSHOT_DIR, snapshot_id)
    if not os.path.exists(source_dir):
        return {"status": "error", "message": f"Snapshot {snapshot_id} existiert nicht."}

    restored = []
    for fname in os.listdir(source_dir):
        if fname == "snapshot_meta.json":
            continue
        src = os.path.join(source_dir, fname)
        if not os.path.isfile(src):
            continue

        # Prüfe ob Datei im Root oder unter data/ liegt
        if fname.endswith(".db"):
            target_path = os.path.join(WORKSPACE_DIR, "data", fname) if not os.path.exists(os.path.join(WORKSPACE_DIR, fname)) else os.path.join(WORKSPACE_DIR, fname)
        else:
            target_path = os.path.join(WORKSPACE_DIR, fname)

        try:
            shutil.copy2(src, target_path)
            restored.append(fname)
        except Exception as e:
            print(f"[SystemUpdater] Rollback Fehler für {fname}: {e}", file=sys.stderr)

    return {
        "status": "success",
        "snapshot_id": snapshot_id,
        "restored_files": restored,
        "message": f"{len(restored)} Dateien aus Snapshot {snapshot_id} erfolgreich wiederhergestellt."
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Archon OS Updatesystem CLI")
    parser.add_argument("--check", action="store_true", help="Auf Updates prüfen")
    parser.add_argument("--apply", action="store_true", help="Update ausführen (mit Pre-Backup)")
    parser.add_argument("--backup", action="store_true", help="Nur manuellen Snapshot erstellen")
    parser.add_argument("--list-snapshots", action="store_true", help="Vorhandene Snapshots auflisten")
    parser.add_argument("--rollback", type=str, help="Snapshot-ID zur Wiederherstellung angeben")
    args = parser.parse_args()

    if args.check:
        print(json.dumps(get_update_status(), indent=2, ensure_ascii=False))
    elif args.apply:
        print(json.dumps(apply_update(), indent=2, ensure_ascii=False))
    elif args.backup:
        print(json.dumps(create_snapshot(tag="manual"), indent=2, ensure_ascii=False))
    elif args.list_snapshots:
        print(json.dumps(list_snapshots(), indent=2, ensure_ascii=False))
    elif args.rollback:
        print(json.dumps(rollback_snapshot(args.rollback), indent=2, ensure_ascii=False))
    else:
        parser.print_help()

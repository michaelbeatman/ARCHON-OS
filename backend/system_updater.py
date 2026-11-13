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
import logging
from typing import Dict, Any, List, Optional, Tuple

from archon.core.cache import ttl_cache, invalidate  # noqa: E402

logger = logging.getLogger(__name__)

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


def _run_git(args: List[str], timeout: int = 60) -> Dict[str, Any]:
    """Führt einen Git-Befehl sicher im Workspace-Verzeichnis aus."""
    try:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        # Sicherstellen, dass Git-Hooks den laufenden Python-Interpreter priorisieren
        if sys.executable:
            env["ARCHON_PYTHON"] = sys.executable
            env["PYTHON_EXE"] = sys.executable
            py_dir = os.path.dirname(sys.executable)
            if py_dir:
                env["PATH"] = py_dir + os.pathsep + env.get("PATH", "")
        base_cmd = [
            "git",
            "-c", "safe.directory=*",
            "-c", "core.fileMode=false",
            "-c", "core.checkstat=minimal",
            "-c", "core.trustctime=false",
            "-c", "core.autocrlf=" + ("true" if sys.platform == "win32" else "input"),
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


def parse_porcelain_status(stdout: str) -> List[Dict[str, str]]:
    """Parst die Ausgabe von `git status --porcelain` in strukturierte Datei-Objekte."""
    import re
    files = []
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([ MADRCU?!]{1,2})\s+(.+)$", line)
        if m:
            code = m.group(1).strip()
            path = m.group(2).strip()
        else:
            parts = line.split(maxsplit=1)
            code = parts[0] if parts else "M"
            path = parts[1] if len(parts) > 1 else line.strip()

        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        
        label = "Geändert"
        color = "amber"
        if "??" in code:
            label = "Neu / Ungetrackt"
            color = "sky"
        elif "A" in code:
            label = "Hinzugefügt"
            color = "emerald"
        elif "D" in code:
            label = "Gelöscht"
            color = "rose"
        elif "R" in code:
            label = "Umbenannt"
            color = "purple"
        elif "M" in code:
            label = "Geändert"
            color = "amber"
            
        files.append({
            "code": code,
            "path": path,
            "label": label,
            "color": color
        })
    return files


@ttl_cache(seconds=120)
def get_local_changes() -> Dict[str, Any]:
    """Gibt detaillierte Informationen zu allen ungespeicherten lokalen Änderungen zurück."""
    status_check = _run_git(["status", "--porcelain"])
    dirty = bool(status_check["stdout"].strip()) if status_check["success"] else False
    changed_files = parse_porcelain_status(status_check["stdout"]) if dirty and status_check["success"] else []
    return {
        "status": "success",
        "has_local_changes": dirty,
        "total": len(changed_files),
        "files": changed_files
    }


def get_system_version_info() -> Dict[str, Any]:
    """Liest Versionsdaten aus config/version.json."""
    vpath = os.path.join(WORKSPACE_DIR, "config", "version.json")
    if os.path.exists(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": "unbekannt", "codename": ""}


def get_github_auth_info() -> Dict[str, Any]:
    """Prüft, ob auf dieser Instanz ein autorisierter GitHub Master-Push-Token vorliegt."""
    env = os.environ.copy()
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

    settings_path = os.path.join(WORKSPACE_DIR, "settings.json")
    is_master = False
    allow_push = True
    owner = "michaelbeatman"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as sf:
                sdata = json.load(sf)
                gh_conf = sdata.get("github_sync", {})
                is_master = gh_conf.get("is_master", False)
                allow_push = gh_conf.get("allow_push", True)
                owner = gh_conf.get("owner", "michaelbeatman")
        except Exception:
            pass

    has_token = bool(gh_token and len(gh_token) > 8)
    can_push = bool(has_token and is_master and allow_push)
    
    masked = None
    if has_token:
        masked = gh_token[:4] + "..." + gh_token[-4:]

    role_label = "👑 Michael (Master: Push autorisiert)" if can_push else "🔒 Read-Only Client (Push gesperrt)"
    return {
        "is_master": is_master,
        "can_push": can_push,
        "has_token": has_token,
        "token_masked": masked,
        "owner": owner,
        "role_label": role_label
    }


def calculate_next_version(current_ver: str, step: str = "subpatch") -> str:
    """
    Berechnet die nächste Version basierend auf dem gewählten Step:
    - 'none': Aktuelle Version bleibt unverändert
    - 'subpatch': +0.0.0.1 (z. B. v0.3.8 -> v0.3.8.1, v0.3.8.1 -> v0.3.8.2)
    - 'patch': +0.0.1 (z. B. v0.3.8 -> v0.3.9)
    - 'minor': +0.1.0 (z. B. v0.3.8 -> v0.4.0)
    """
    import re
    cur = (current_ver or "v0.3.8").strip()
    if not cur.startswith("v"):
        cur = f"v{cur}"

    if step == "none":
        return cur

    m4 = re.match(r"^v?(\d+)\.(\d+)\.(\d+)\.(\d+)$", cur)
    m3 = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", cur)

    if step == "subpatch":
        if m4:
            maj, minr, patch, sub = int(m4.group(1)), int(m4.group(2)), int(m4.group(3)), int(m4.group(4))
            return f"v{maj}.{minr}.{patch}.{sub + 1}"
        elif m3:
            maj, minr, patch = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
            return f"v{maj}.{minr}.{patch}.1"
        return f"{cur}.1"

    if step == "patch":
        if m4:
            maj, minr, patch, _ = int(m4.group(1)), int(m4.group(2)), int(m4.group(3)), int(m4.group(4))
            return f"v{maj}.{minr}.{patch + 1}"
        elif m3:
            maj, minr, patch = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
            return f"v{maj}.{minr}.{patch + 1}"
        return "v0.3.9"

    if step == "minor":
        m = m4 or m3
        if m:
            maj, minr = int(m.group(1)), int(m.group(2))
            return f"v{maj}.{minr + 1}.0"
        return "v0.4.0"

    return cur


def set_custom_version(target_version: Optional[str] = None, step: str = "custom", reason: str = "") -> Tuple[str, str]:
    """Setzt oder berechnet die Zielversion in config/version.json."""
    vpath = os.path.join(WORKSPACE_DIR, "config", "version.json")
    vdata = {}
    if os.path.exists(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                vdata = json.load(f)
        except Exception:
            pass

    cur_version = vdata.get("version", "v0.3.8")

    if target_version and target_version.strip():
        new_version = target_version.strip()
        if not new_version.startswith("v"):
            new_version = f"v{new_version}"
    elif step == "none":
        new_version = cur_version
    else:
        new_version = calculate_next_version(cur_version, step=step)

    vdata["previous_version"] = cur_version
    vdata["version"] = new_version
    vdata["released_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if reason:
        vdata["last_bump_reason"] = reason

    os.makedirs(os.path.dirname(vpath), exist_ok=True)
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump(vdata, f, indent=2, ensure_ascii=False)

    return cur_version, new_version


def _build_version_steps(sys_version: str) -> Dict[str, str]:
    """Berechnet alle Release-Schritt-Varianten fuer eine aktuelle Systemversion."""
    return {
        "none": sys_version,
        "subpatch": calculate_next_version(sys_version, "subpatch"),
        "patch": calculate_next_version(sys_version, "patch"),
        "minor": calculate_next_version(sys_version, "minor")
    }


def get_local_update_status() -> Dict[str, Any]:
    """Liefert lokale Versions-, Commit- und Berechtigungsdaten sofort ohne langsamen Git-Status/Fetch."""
    vinfo = get_system_version_info()
    sys_version = vinfo.get("version", "unbekannt")
    sys_codename = vinfo.get("codename", "")
    version_steps = _build_version_steps(sys_version)
    next_version = version_steps["subpatch"]
    auth = get_github_auth_info()

    native = _read_git_head_native()
    raw_commit = native.get("commit", "unknown")
    current_commit = raw_commit[:7] if raw_commit and raw_commit != "unknown" else "unknown"
    branch = native.get("branch", "main")

    last_commit_info = ""
    last_log = _run_git(["log", "-1", "--format=%cd (%cr) · %s", "--date=short"], timeout=3)
    if last_log["success"] and last_log["stdout"]:
        last_commit_info = last_log["stdout"]

    return {
        "status": "local_only",
        "local_only": True,
        "version": sys_version,
        "version_codename": sys_codename,
        "next_version": next_version,
        "version_steps": version_steps,
        "auth": auth,
        "current_commit": current_commit,
        "branch": branch,
        "last_commit_info": last_commit_info,
        "message": "Lokale Versionsdaten geladen. GitHub-Abgleich läuft..."
    }


@ttl_cache(seconds=60)
def get_update_status() -> Dict[str, Any]:
    """Prüft, ob auf dem Remote-Repository (GitHub) neue Commits vorliegen."""
    vinfo = get_system_version_info()
    sys_version = vinfo.get("version", "unbekannt")
    sys_codename = vinfo.get("codename", "")
    version_steps = _build_version_steps(sys_version)
    next_version = version_steps["subpatch"]
    auth = get_github_auth_info()

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
    changed_files = parse_porcelain_status(status_check["stdout"]) if dirty and status_check["success"] else []
    changed_files_count = len(changed_files)

    # Remote Fetch ausführen
    fetch_res = _run_git(["fetch", "origin", "main"], timeout=30)
    if not fetch_res["success"]:
        return {
            "status": "offline_or_error",
            "version": sys_version,
            "version_codename": sys_codename,
            "next_version": next_version,
            "version_steps": version_steps,
            "auth": auth,
            "update_available": False,
            "current_commit": current_commit,
            "branch": branch,
            "last_commit_info": last_commit_info,
            "has_local_changes": dirty,
            "changed_files_count": changed_files_count,
            "changed_files": changed_files,
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
        "version": sys_version,
        "version_codename": sys_codename,
        "next_version": next_version,
        "version_steps": version_steps,
        "auth": auth,
        "update_available": commits_behind > 0,
        "current_commit": current_commit,
        "remote_commit": remote_commit,
        "branch": branch,
        "last_commit_info": last_commit_info,
        "commits_behind": commits_behind,
        "incoming_commits": incoming,
        "has_local_changes": dirty,
        "changed_files_count": changed_files_count,
        "changed_files": changed_files,
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
            try:
                dst.close()
            except Exception as e:
                logger.warning("Fehler beim Schliessen der Ziel-Datenbankverbindung: %s", e, exc_info=True)
        if src:
            try:
                src.close()
            except Exception as e:
                logger.warning("Fehler beim Schliessen der Quell-Datenbankverbindung: %s", e, exc_info=True)


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

    # 0. Temporär --skip-worktree Flags auf Config-Dateien aufheben, damit Stash und Pull greifen
    config_protect = ["settings.json", "agent_profiles.json", "config/kanban_meta.json"]
    for cf in config_protect:
        _run_git(["update-index", "--no-skip-worktree", cf])

    # Stash falls lokale temporäre Änderungen existieren
    stash_run = False
    status_chk = _run_git(["status", "--porcelain"])
    if status_chk["success"] and status_chk["stdout"].strip():
        stash_res = _run_git(["stash", "push", "-u", "-m", "Auto-stash vor Archon System-Update"])
        stash_run = stash_res["success"]

    # Git Pull Rebase
    pull_res = _run_git(["pull", "origin", "main", "--rebase"], timeout=60)
    if not pull_res["success"]:
        # Rebase abort falls ein Konflikt entstand
        _run_git(["rebase", "--abort"])
        if stash_run:
            _run_git(["stash", "pop"])
        for cf in config_protect:
            _run_git(["update-index", "--skip-worktree", cf])
        return {
            "status": "error",
            "step": "git_pull",
            "message": f"Git Pull fehlgeschlagen: {pull_res['stderr'] or pull_res['stdout']}",
            "snapshot": snapshot_info
        }

    # Stash zurückholen falls vorhanden
    if stash_run:
        pop_res = _run_git(["stash", "pop"])
        if not pop_res["success"]:
            # Bei Stash-Konflikten in Configs: lokale/Snapshot-Stände priorisieren und Index bereinigen
            for cf in config_protect:
                _run_git(["checkout", "--theirs", "--", cf])
                _run_git(["reset", "HEAD", "--", cf])
            # Verbleibende unmerged Dateien auflösen (Upstream-Stand behalten), damit kein UU-Zustand bleibt
            unmerged = _run_git(["diff", "--name-only", "--diff-filter=U"])
            if unmerged["success"] and unmerged["stdout"].strip():
                for uf in unmerged["stdout"].splitlines():
                    uf = uf.strip()
                    if uf:
                        _run_git(["checkout", "--ours", "--", uf])
                        _run_git(["reset", "HEAD", "--", uf])
            _run_git(["stash", "drop"])

    # Configs wieder vor versehentlichem Überschreiben schützen
    for cf in config_protect:
        _run_git(["update-index", "--skip-worktree", cf])

    new_native = _read_git_head_native()
    new_commit = new_native.get("commit", "unknown")

    invalidate(get_update_status)
    invalidate(get_local_changes)

    return {
        "status": "success",
        "new_commit": new_commit,
        "snapshot": snapshot_info,
        "git_output": pull_res["stdout"],
        "message": f"Update erfolgreich auf Commit {new_commit} angewendet."
    }


def schedule_delayed_reload(delay: float = 2.0):
    """Führt einen verzögerten Code-Reload durch, damit die HTTP-Response sauber beendet werden kann."""
    import time
    time.sleep(delay)
    main_file = os.path.join(WORKSPACE_DIR, "main.py")
    try:
        os.utime(main_file, None)
    except Exception:
        pass


def push_changes(commit_message: Optional[str] = None, custom_version: Optional[str] = None, version_step: str = "custom") -> Dict[str, Any]:
    """
    Sammelt alle lokalen Änderungen ein, wendet die gewünschte Version an,
    prüft Master-Autorisierung, committet und pusht zu GitHub origin/main inklusive Release-Tag.
    """
    auth = get_github_auth_info()
    if not auth["can_push"]:
        return {
            "status": "forbidden",
            "message": "Push verweigert: Diese Instanz ist als Read-Only Client konfiguriert oder besitzt keinen autorisierten GitHub Master-Token. Nur Michael darf Releases auf GitHub pushen."
        }

    status_chk = _run_git(["status", "--porcelain"])
    if not status_chk["success"]:
        return {"status": "error", "message": f"Git Status fehlgeschlagen: {status_chk['stderr']}"}

    dirty = bool(status_chk["stdout"].strip())
    if not dirty:
        invalidate(get_update_status)
        invalidate(get_local_changes)
        return {"status": "nothing_to_commit", "message": "Keine neuen lokalen Aenderungen zum Veroeffentlichen vorhanden."}

    # 1. Flexible Versionierung (Benutzer-Eingabe oder Step)
    user_note = commit_message.strip() if commit_message else ""
    old_ver, new_ver = set_custom_version(target_version=custom_version, step=version_step, reason=user_note)

    # 2. git add -A (inklusive aktualisierter config/version.json)
    add_res = _run_git(["add", "-A"])
    if not add_res["success"]:
        return {"status": "error", "message": f"Git Add fehlgeschlagen: {add_res['stderr']}"}

    # 3. git commit -m
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if user_note:
        msg = f"Release {new_ver}: {user_note}"
    else:
        msg = f"Release {new_ver}: Dev-Sync {ts}"

    commit_res = _run_git(["commit", "-m", msg])
    if not commit_res["success"]:
        return {"status": "error", "message": f"Git Commit fehlgeschlagen: {commit_res['stderr'] or commit_res['stdout']}"}

    # 4. Release-Tag setzen
    tag_res = {"success": True}
    if new_ver != old_ver:
        tag_res = _run_git(["tag", "-a", new_ver, "-m", f"Release {new_ver}: {msg}"])
    if not tag_res["success"]:
        _run_git(["tag", "-f", "-a", new_ver, "-m", f"Release {new_ver}: {msg}"])

    # 5. Pull rebase to ensure clean linear history
    pull_res = _run_git(["pull", "origin", "main", "--rebase"], timeout=60)
    if not pull_res["success"]:
        _run_git(["rebase", "--abort"], timeout=30)
        return {"status": "error", "message": f"Git Pull Rebase vor Push fehlgeschlagen: {pull_res['stderr'] or pull_res['stdout']}"}

    # 6. Git Push mit Tags
    push_res = _run_git(["push", "origin", "main", "--tags"], timeout=60)
    if not push_res["success"]:
        # Fallback: Push Branch zuerst, dann Tag einzeln
        push_branch = _run_git(["push", "origin", "main"], timeout=60)
        if not push_branch["success"]:
            return {"status": "error", "message": f"Git Push fehlgeschlagen: {push_branch['stderr']}"}
        _run_git(["push", "origin", new_ver], timeout=30)

    new_head = _read_git_head_native().get("commit", "unknown")
    invalidate(get_update_status)
    invalidate(get_local_changes)
    return {
        "status": "success",
        "commit": new_head,
        "version": new_ver,
        "previous_version": old_ver,
        "commit_message": msg,
        "message": f"Release {new_ver} erfolgreich zu GitHub hochgeladen (Commit {new_head})!"
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
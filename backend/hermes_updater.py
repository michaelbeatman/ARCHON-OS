# -*- coding: utf-8 -*-
"""
backend/hermes_updater.py
=========================
Hermes Agent Core Update & Release-Lifecycle Manager (NousResearch/hermes-agent).

Verwaltet die Abfrage und Aktualisierung des übergeordneten Hermes Agent Kernsystems:
- Prüft die installierte Hermes Core Version (z.B. v0.20.0 · Build 24ba8662)
- Ruft Live-Releases und tägliche Commits direkt von GitHub (NousResearch/hermes-agent) ab
- Vergleicht Upstream-Stände und ermittelt verfügbare Updates
- Ermöglicht Administratoren das sichere Einleiten von Updates (Docker Image Pull & Container Restart)
"""

import os
import sys
import time
import json
import socket
import logging
import urllib.request
import urllib.error
import http.client
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hermes.updater")

HERMES_REPO = "NousResearch/hermes-agent"
GITHUB_API_BASE = f"https://api.github.com/repos/{HERMES_REPO}"

# Bekannte Basis-Informationen bei Offline-Betrieb oder Fallback
DEFAULT_INSTALLED_VERSION = "v0.20.0"
DEFAULT_INSTALLED_CODENAME = "2026.8.3"
DEFAULT_INSTALLED_SHA = "24ba86627515ad5fda69a39ef338c365713448bc"

# In-Memory Cache gegen GitHub API Rate-Limits (60 Sekunden TTL)
_cache_lock_time = 0
_cached_update_data: Optional[Dict[str, Any]] = None
CACHE_TTL_SECONDS = 60


class DockerSocketClient:
    """Schlanker Client für Docker-Engine-API über /var/run/docker.sock."""

    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self.socket_path = socket_path

    def _request(self, method: str, endpoint: str, body: Optional[bytes] = None, headers: Optional[dict] = None) -> Tuple[int, bytes]:
        if not os.path.exists(self.socket_path):
            raise FileNotFoundError(f"Docker socket not found at {self.socket_path}")

        class UHTTPConnection(http.client.HTTPConnection):
            def __init__(conn_self, sock_path):
                super().__init__("localhost")
                conn_self.sock_path = sock_path

            def connect(conn_self):
                conn_self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                conn_self.sock.settimeout(120)
                conn_self.sock.connect(conn_self.sock_path)

        conn = UHTTPConnection(self.socket_path)
        req_headers = headers or {}
        if body and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

        conn.request(method, endpoint, body=body, headers=req_headers)
        res = conn.getresponse()
        resp_body = res.read()
        status = res.status
        conn.close()
        return status, resp_body

    def get_json(self, endpoint: str) -> Optional[Dict[str, Any]]:
        try:
            status, data = self._request("GET", endpoint)
            if status in (200, 201):
                return json.loads(data.decode("utf-8", errors="ignore"))
            return None
        except Exception as e:
            logger.debug(f"[DockerSocketClient] GET {endpoint} error: {e}")
            return None

    def post(self, endpoint: str, body: Optional[bytes] = None) -> Tuple[int, str]:
        status, data = self._request("POST", endpoint, body=body)
        return status, data.decode("utf-8", errors="ignore")


def get_installed_hermes_info() -> Dict[str, Any]:
    """
    Ermittelt die aktuell installierte Hermes Core Version und den Build-SHA.
    Fragt wenn möglich das Docker Image hermes-agent-plus:latest bzw. den hermes-Container ab.
    """
    info = {
        "version": DEFAULT_INSTALLED_VERSION,
        "version_codename": DEFAULT_INSTALLED_CODENAME,
        "installed_sha": DEFAULT_INSTALLED_SHA,
        "installed_sha_short": DEFAULT_INSTALLED_SHA[:8],
        "container_name": "hermes",
        "container_status": "unknown",
        "image": "hermes-agent-plus:latest",
        "install_method": "docker",
        "repo": HERMES_REPO
    }

    try:
        docker_cli = DockerSocketClient()
        # Container-Status prüfen
        c_data = docker_cli.get_json("/containers/hermes/json")
        if c_data and isinstance(c_data, dict):
            state = c_data.get("State", {})
            info["container_status"] = state.get("Status", "exited")
            info["image"] = c_data.get("Config", {}).get("Image", info["image"])

        # Image Labels abfragen
        img_data = docker_cli.get_json(f"/images/{info['image']}/json")
        if img_data and isinstance(img_data, dict):
            labels = img_data.get("Config", {}).get("Labels", {}) or {}
            rev = labels.get("org.opencontainers.image.revision")
            if rev:
                info["installed_sha"] = rev
                info["installed_sha_short"] = rev[:8]
    except Exception as e:
        logger.warning(f"[HermesUpdater] Error inspecting docker container/image: {e}")

    return info


def check_hermes_updates(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Fragt GitHub API nach den neuesten Releases und täglichen Commits von NousResearch/hermes-agent ab.
    Vergleicht den Stand mit der installierten Hermes Core Version.
    """
    global _cache_lock_time, _cached_update_data

    now = time.time()
    if not force_refresh and _cached_update_data and (now - _cache_lock_time < CACHE_TTL_SECONDS):
        return _cached_update_data

    installed = get_installed_hermes_info()

    result = {
        "status": "success",
        "target": "Hermes Agent Core",
        "repo": HERMES_REPO,
        "repo_url": f"https://github.com/{HERMES_REPO}",
        "installed_version": installed["version"],
        "installed_codename": installed["version_codename"],
        "installed_sha": installed["installed_sha"],
        "installed_sha_short": installed["installed_sha_short"],
        "container_status": installed["container_status"],
        "update_available": False,
        "commits_behind": 0,
        "latest_release": None,
        "latest_release_tag": None,
        "latest_release_name": None,
        "latest_release_date": None,
        "latest_release_url": None,
        "release_notes": "",
        "latest_commit_sha": None,
        "latest_commit_sha_short": None,
        "latest_commit_date": None,
        "latest_commit_msg": None,
        "incoming_commits": [],
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    headers = {
        "User-Agent": "Archon-OS/2026 (Hermes-Core-Updater)",
        "Accept": "application/vnd.github.v3+json"
    }

    # 1. Neuestes Release von GitHub abfragen
    try:
        req_rel = urllib.request.Request(f"{GITHUB_API_BASE}/releases/latest", headers=headers)
        with urllib.request.urlopen(req_rel, timeout=10) as resp:
            if resp.status == 200:
                rel_data = json.loads(resp.read().decode("utf-8"))
                tag_name = rel_data.get("tag_name", "")
                result["latest_release_tag"] = tag_name
                result["latest_release_name"] = rel_data.get("name") or tag_name
                result["latest_release_date"] = rel_data.get("published_at", "")[:10]
                result["latest_release_url"] = rel_data.get("html_url", "")
                body_text = rel_data.get("body", "") or ""
                # Kürzere Vorschau der Release Notes
                result["release_notes"] = body_text[:600] + ("..." if len(body_text) > 600 else "")

                # Versionsvergleich (z.B. v0.20.0 vs v0.22.6)
                if tag_name and tag_name.lstrip("v") != installed["version"].lstrip("v"):
                    result["update_available"] = True
    except Exception as e:
        logger.warning(f"[HermesUpdater] Failed to fetch latest release from GitHub: {e}")

    # 2. Neueste Commits von GitHub abfragen (tägliche Core-Entwicklung)
    try:
        req_commits = urllib.request.Request(f"{GITHUB_API_BASE}/commits?per_page=15", headers=headers)
        with urllib.request.urlopen(req_commits, timeout=10) as resp:
            if resp.status == 200:
                commits_data = json.loads(resp.read().decode("utf-8"))
                parsed_commits = []
                for c in commits_data:
                    sha = c.get("sha", "")
                    commit_obj = c.get("commit", {})
                    msg = commit_obj.get("message", "").split("\n")[0]
                    author_date = commit_obj.get("author", {}).get("date", "")[:10]
                    author_name = commit_obj.get("author", {}).get("name", "")
                    parsed_commits.append({
                        "sha": sha,
                        "short_sha": sha[:8],
                        "message": msg,
                        "date": author_date,
                        "author": author_name,
                        "formatted": f"{sha[:8]} · {msg} ({author_date})"
                    })

                if parsed_commits:
                    latest = parsed_commits[0]
                    result["latest_commit_sha"] = latest["sha"]
                    result["latest_commit_sha_short"] = latest["short_sha"]
                    result["latest_commit_date"] = latest["date"]
                    result["latest_commit_msg"] = latest["message"]
                    result["incoming_commits"] = [c["formatted"] for c in parsed_commits]

                    # Wenn der aktuelle Build-SHA nicht dem neuesten Commit entspricht
                    if installed["installed_sha"] != latest["sha"]:
                        result["update_available"] = True
    except Exception as e:
        logger.warning(f"[HermesUpdater] Failed to fetch latest commits from GitHub: {e}")

    # 3. Compare API abfragen zur exakten Bestimmung der Anzahl ausstehender Commits
    try:
        compare_url = f"{GITHUB_API_BASE}/compare/{installed['installed_sha_short']}...main"
        req_comp = urllib.request.Request(compare_url, headers=headers)
        with urllib.request.urlopen(req_comp, timeout=10) as resp:
            if resp.status == 200:
                comp_data = json.loads(resp.read().decode("utf-8"))
                ahead_by = comp_data.get("ahead_by", 0)
                total_commits = comp_data.get("total_commits", ahead_by)
                if ahead_by > 0 or total_commits > 0:
                    result["commits_behind"] = ahead_by if ahead_by > 0 else total_commits
                    result["update_available"] = True
                elif comp_data.get("status") == "identical":
                    result["commits_behind"] = 0
                    result["update_available"] = False
    except Exception as e:
        logger.debug(f"[HermesUpdater] Compare API not available or rate limited: {e}")
        # Fallback auf Commit-Anzahl
        if result["update_available"] and not result["commits_behind"]:
            result["commits_behind"] = len(result["incoming_commits"])

    _cached_update_data = result
    _cache_lock_time = now
    return result


def recreate_container_with_new_image(docker_cli: DockerSocketClient, container_name: str, new_image: str) -> Tuple[bool, str]:
    """
    Erstellt den Docker-Container atomar mit dem neuen Image neu:
    1. Konfiguration des bestehenden Containers sichern
    2. Alten Container stoppen & umbenennen (hermes_old_backup)
    3. Neuen Container aus neuem Image erstellen
    4. Neuen Container starten
    5. Alten Backup-Container löschen (bei Fehler automatisches Rollback)
    """
    c_data = docker_cli.get_json(f"/containers/{container_name}/json")
    if not c_data:
        return False, f"Container '{container_name}' existiert nicht."

    config = c_data.get("Config", {})
    host_config = c_data.get("HostConfig", {})
    net_config = c_data.get("NetworkSettings", {}).get("Networks", {})
    was_running = c_data.get("State", {}).get("Running", False)

    # 1. Stoppen
    if was_running:
        docker_cli.post(f"/containers/{container_name}/stop?t=5")

    # 2. Umbenennen als Backup
    backup_name = f"{container_name}_old_backup"
    # Sicherstellen, dass kein altes Backup im Weg ist
    docker_cli._request("DELETE", f"/containers/{backup_name}?v=false")
    docker_cli.post(f"/containers/{container_name}/rename?name={backup_name}")

    # 3. Create Payload mit neuem Image
    create_body = {
        "Image": new_image,
        "Cmd": config.get("Cmd"),
        "Env": config.get("Env"),
        "Entrypoint": config.get("Entrypoint"),
        "WorkingDir": config.get("WorkingDir"),
        "Labels": config.get("Labels"),
        "HostConfig": host_config,
        "NetworkingConfig": {
            "EndpointsConfig": net_config
        }
    }

    status, resp = docker_cli.post(f"/containers/create?name={container_name}", body=json.dumps(create_body).encode("utf-8"))
    if status in (200, 201):
        if was_running:
            docker_cli.post(f"/containers/{container_name}/start")
        # Altes Backup löschen
        docker_cli._request("DELETE", f"/containers/{backup_name}?v=false")
        return True, f"Container '{container_name}' erfolgreich mit Image {new_image} neu instanziiert."
    else:
        # Rollback: Altes Backup wieder aktivieren
        docker_cli.post(f"/containers/{backup_name}/rename?name={container_name}")
        if was_running:
            docker_cli.post(f"/containers/{container_name}/start")
        return False, f"Fehler bei Neu-Instanziierung ({status}): {resp[:200]}"


def apply_hermes_update(channel: str = "latest", auto_restart: bool = True) -> Dict[str, Any]:
    """
    Führt das Hermes Agent Core Update aus:
    1. Zieht das neueste Docker Image von Docker Hub (nousresearch/hermes-agent:latest)
    2. Kennzeichnet/Taggt das Image als hermes-agent-plus:latest
    3. Erstellt den hermes-Container atomar mit dem neuen Image neu
    """
    t0 = time.time()
    docker_cli = DockerSocketClient()

    log_messages = []
    log_messages.append(f"Starte Hermes Core Update ({HERMES_REPO})...")

    # Schritt 1: Image Pull über Docker Engine API
    pull_endpoint = f"/images/create?fromImage=nousresearch/hermes-agent&tag={channel}"
    try:
        log_messages.append(f"Lade Docker Image nousresearch/hermes-agent:{channel} herunter...")
        status, resp = docker_cli.post(pull_endpoint)
        if status not in (200, 204):
            return {
                "status": "error",
                "message": f"Docker Pull fehlgeschlagen (HTTP {status}): {resp[:300]}",
                "logs": log_messages
            }
        log_messages.append("Neues Hermes Docker Image erfolgreich empfangen.")
    except Exception as e:
        return {
            "status": "error",
            "message": f"Fehler bei Docker Image Pull: {e}",
            "logs": log_messages
        }

    # Schritt 2: Tagge als hermes-agent-plus:latest für Docker Compose Kompatibilität
    try:
        tag_endpoint = f"/images/nousresearch/hermes-agent:{channel}/tag?repo=hermes-agent-plus&tag=latest"
        status, resp = docker_cli.post(tag_endpoint)
        if status in (200, 201, 204):
            log_messages.append("Image erfolgreich als hermes-agent-plus:latest registriert.")
        else:
            log_messages.append(f"Hinweis: Tagging ergab Status {status}: {resp[:150]}")
    except Exception as e:
        log_messages.append(f"Tagging-Hinweis: {e}")

    # Schritt 3: Container atomar neu instanziieren (damit das neue Image greift)
    recreated = False
    if auto_restart:
        try:
            ok, msg = recreate_container_with_new_image(docker_cli, "hermes", "hermes-agent-plus:latest")
            log_messages.append(msg)
            recreated = ok
        except Exception as e:
            log_messages.append(f"Container-Recreation fehlgeschlagen: {e}")
            # Fallback auf reinen Restart
            try:
                docker_cli.post("/containers/hermes/restart?t=10")
                log_messages.append("Fallback: Bestehender hermes-Container neu gestartet.")
            except Exception as re_err:
                log_messages.append(f"Fallback-Restart fehlgeschlagen: {re_err}")

    duration = round(time.time() - t0, 2)

    # Cache invalidieren
    global _cached_update_data, _cache_lock_time
    _cached_update_data = None
    _cache_lock_time = 0

    return {
        "status": "success",
        "message": f"Hermes Agent Core erfolgreich auf neuestes Docker Image aktualisiert ({duration}s).",
        "duration_seconds": duration,
        "channel": channel,
        "container_restarted": recreated,
        "logs": log_messages
    }

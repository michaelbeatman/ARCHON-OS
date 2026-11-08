# -*- coding: utf-8 -*-
"""
backend/hermes_updater.py
=========================
Hermes Agent Core Update & Release-Lifecycle Manager (NousResearch/hermes-agent).

Verwaltet die Abfrage und Aktualisierung des übergeordneten Hermes Agent Kernsystems:
- Ermittelt dynamisch die installierte Hermes Core Version (z.B. v0.22.6 · Build f0d94882)
- Ruft Live-Releases und tägliche Commits direkt von GitHub (NousResearch/hermes-agent) ab
- Vergleicht Upstream-Stände und ermittelt verfügbare Updates
- Ermöglicht Administratoren das sichere Einleiten von Updates (Docker Image Pull & atomare Container-Neu-Instanziierung)
"""

import os
import sys
import re
import time
import json
import socket
import logging
import urllib.request
import urllib.error
import http.client
from typing import Dict, Any, List, Optional, Tuple, Protocol

logger = logging.getLogger("hermes.updater")


class DockerApiClient(Protocol):
    """Gemeinsame Oberflaeche von DockerSocketClient und DockerAdminAdapter."""

    def _request(self, method: str, endpoint: str, body: Optional[bytes] = None,
                 headers: Optional[dict] = None) -> Tuple[int, bytes]: ...

    def get_json(self, endpoint: str) -> Optional[Dict[str, Any]]: ...

    def post(self, endpoint: str, body: Optional[bytes] = None) -> Tuple[int, str]: ...


HERMES_REPO = "NousResearch/hermes-agent"
GITHUB_API_BASE = f"https://api.github.com/repos/{HERMES_REPO}"

# Container-Name des Hermes Core in DIESEM Stack: `hermes-agent` (Container-Name und
# Netz-Alias, per `docker inspect` belegt). Der Compose-Eintrag `hermes` laeuft hier
# nicht — er stammt aus der Windows-Variante von docker-compose.yml.
HERMES_CORE_CONTAINER = "hermes-agent"

# Bekannte Basis-Informationen bei Offline-Betrieb oder Fallback
DEFAULT_INSTALLED_VERSION = "v0.22.6"
DEFAULT_INSTALLED_CODENAME = "2026.9.24"
DEFAULT_INSTALLED_SHA = "f0d94882"

# ---------------------------------------------------------------------------
# Transport-Umschaltung (Etappe 1: vorbereitet, Default = heutiges Verhalten)
#
# HERMES_UPDATER_DOCKER_CLIENT:
#   unset / "0"  -> roher Unix-Socket wie bisher (DockerSocketClient)
#   "1" / "true" -> utils.docker_client.DockerAdminClient ueber DOCKER_HOST
#                   bzw. Unix-Socket, mit eigener Admin-Allowlist
# HERMES_UPDATER_PULL_TIMEOUT:
#   Sekunden fuer den GESAMTEN Pull (Default 1800). Heute gilt pauschal
#   settimeout(120) pro recv — ein langsam fliessender Pull bricht damit mit
#   socket.timeout ab, obwohl der Daemon korrekt arbeitet.
# ---------------------------------------------------------------------------
_USE_DOCKER_CLIENT_ENV = "HERMES_UPDATER_DOCKER_CLIENT"
_PULL_TIMEOUT_ENV = "HERMES_UPDATER_PULL_TIMEOUT"
_REQUEST_TIMEOUT_ENV = "HERMES_UPDATER_REQUEST_TIMEOUT"

_DEFAULT_PULL_TIMEOUT = 1800.0
# Entspricht dem pauschalen Socket-Timeout des rohen Clients (hermes_updater.py:64).
_DEFAULT_REQUEST_TIMEOUT = 120.0


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"[HermesUpdater] {name}={raw!r} ist keine Zahl — nutze {default}s")
        return default
    return value if value > 0 else default

# In-Memory Cache gegen GitHub API Rate-Limits (15 Minuten TTL)
_cache_lock_time = 0
_cached_update_data: Optional[Dict[str, Any]] = None
CACHE_TTL_SECONDS = 900


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


class DockerAdminAdapter:
    """Gleiche Oberflaeche wie DockerSocketClient, Transport ueber DockerAdminClient.

    Zweck: der Updater (und nur der) bekommt die Admin-Allowlist, ohne dass sich
    eine einzige Aufrufstelle aendern muss — `_request` liefert (status, bytes),
    `post` liefert (status, str), `get_json` liefert dict|None. Genau diese
    Signaturen nutzen `get_installed_hermes_info`, `recreate_container_with_new_image`
    und `apply_hermes_update`.

    Der Pull bekommt einen eigenen Timeout: die Retry-/Abbruchgrenze eines
    Image-Transfers haengt an der Bildgroesse, nicht an der Daemon-Latenz.
    """

    _PULL_PATH_PREFIX = "/images/create"

    def __init__(self, client=None) -> None:
        if client is None:
            from utils.docker_client import DockerAdminClient

            client = DockerAdminClient()
        self._client = client
        self._request_timeout = _env_seconds(_REQUEST_TIMEOUT_ENV, _DEFAULT_REQUEST_TIMEOUT)
        self._pull_timeout = _env_seconds(_PULL_TIMEOUT_ENV, _DEFAULT_PULL_TIMEOUT)

    def _timeout_for(self, endpoint: str) -> float:
        return self._pull_timeout if endpoint.startswith(self._PULL_PATH_PREFIX) else self._request_timeout

    def _request(self, method: str, endpoint: str, body: Optional[bytes] = None,
                 headers: Optional[dict] = None) -> Tuple[int, bytes]:
        payload = None
        if body:
            payload = json.loads(body.decode("utf-8"))
        return self._client.request_status(method, endpoint, payload,
                                           timeout=self._timeout_for(endpoint))

    def get_json(self, endpoint: str) -> Optional[Dict[str, Any]]:
        try:
            status, data = self._request("GET", endpoint)
            if status in (200, 201):
                return json.loads(data.decode("utf-8", errors="ignore"))
            return None
        except Exception as e:
            logger.debug(f"[DockerAdminAdapter] GET {endpoint} error: {e}")
            return None

    def post(self, endpoint: str, body: Optional[bytes] = None) -> Tuple[int, str]:
        status, data = self._request("POST", endpoint, body=body)
        return status, data.decode("utf-8", errors="ignore")


def _make_docker_client():
    """Transport fuer den Updater: Schalter an = Admin-Client, aus = roher Socket (heute)."""
    if _env_flag(_USE_DOCKER_CLIENT_ENV):
        return DockerAdminAdapter()
    return DockerSocketClient()


def get_installed_hermes_info(force_check: bool = False) -> Dict[str, Any]:
    """
    Ermittelt die tatsächlich installierte Hermes Core Version und den Build-SHA.
    Fragt den aktiven Core-Container (`hermes-agent`) direkt per `hermes --version` ab.
    """
    info = {
        "version": DEFAULT_INSTALLED_VERSION,
        "version_codename": DEFAULT_INSTALLED_CODENAME,
        "installed_sha": DEFAULT_INSTALLED_SHA,
        "installed_sha_short": DEFAULT_INSTALLED_SHA[:8],
        "container_name": HERMES_CORE_CONTAINER,
        "container_status": "unknown",
        "image": "hermes-agent-plus:latest",
        "install_method": "docker",
        "repo": HERMES_REPO
    }

    try:
        docker_cli = _make_docker_client()
        c_data = docker_cli.get_json(f"/containers/{HERMES_CORE_CONTAINER}/json")
        if c_data and isinstance(c_data, dict):
            state = c_data.get("State", {})
            is_running = state.get("Running", False)
            info["container_status"] = state.get("Status", "exited")
            info["image"] = c_data.get("Config", {}).get("Image", info["image"])

            # 1. Wenn der Container läuft, Version dynamisch per 'hermes --version' abfragen
            if is_running:
                try:
                    exec_payload = {
                        "AttachStdout": True,
                        "AttachStderr": True,
                        "Cmd": ["hermes", "--version"]
                    }
                    s, res = docker_cli.post(f"/containers/{HERMES_CORE_CONTAINER}/exec", body=json.dumps(exec_payload).encode("utf-8"))
                    if s in (200, 201):
                        exec_id = json.loads(res).get("Id")
                        if exec_id:
                            start_payload = {"Detach": False, "Tty": True}
                            s2, out = docker_cli.post(f"/exec/{exec_id}/start", body=json.dumps(start_payload).encode("utf-8"))
                            m = re.search(r'Hermes Agent (v[0-9.]+)\s*\(([^)]+)\)\s*(?:·\s*upstream\s*([0-9a-fA-F]+))?', out)
                            if m:
                                info["version"] = m.group(1)
                                info["version_codename"] = m.group(2)
                                if m.group(3):
                                    info["installed_sha"] = m.group(3)
                                    info["installed_sha_short"] = m.group(3)[:8]
                except Exception as ex_err:
                    logger.debug(f"[HermesUpdater] Exec version error: {ex_err}")

        # 2. Image Labels als Fallback
        img_data = docker_cli.get_json(f"/images/{info['image']}/json")
        if img_data and isinstance(img_data, dict):
            labels = img_data.get("Config", {}).get("Labels", {}) or {}
            rev = labels.get("org.opencontainers.image.revision")
            if rev and info["installed_sha"] == DEFAULT_INSTALLED_SHA:
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

    installed = get_installed_hermes_info(force_check=force_refresh)

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
        "is_latest_release": True,
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
                result["release_notes"] = body_text[:600] + ("..." if len(body_text) > 600 else "")

                # Release-Vergleich (z.B. v0.22.6 vs v0.20.0)
                if tag_name and tag_name.lstrip("v") != installed["version"].lstrip("v"):
                    result["update_available"] = True
                    result["is_latest_release"] = False
                else:
                    result["update_available"] = False
                    result["is_latest_release"] = True
    except Exception as e:
        logger.warning(f"[HermesUpdater] Failed to fetch latest release from GitHub: {e}")

    # 2. Neueste Commits von GitHub abfragen (tägliche Core-Entwicklung zur Information)
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
    except Exception as e:
        logger.warning(f"[HermesUpdater] Failed to fetch latest commits from GitHub: {e}")

    _cached_update_data = result
    _cache_lock_time = now
    return result


def recreate_container_with_new_image(docker_cli: "DockerApiClient", container_name: str, new_image: str) -> Tuple[bool, str]:
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
    3. Erstellt den Core-Container (hermes-agent) atomar mit dem neuen Image neu
    """
    t0 = time.time()
    docker_cli = _make_docker_client()

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
            ok, msg = recreate_container_with_new_image(docker_cli, HERMES_CORE_CONTAINER, "hermes-agent-plus:latest")
            log_messages.append(msg)
            recreated = ok
            # hermes-dashboard wird bewusst NICHT mit neu instanziiert: der Container laeuft,
            # und seine Compose-Datei (docker-compose.hermes.yml) fehlt — ein Recreate waere
            # nicht rueckholbar. Wer das aendert, muss die Compose-Datei zuerst wiederherstellen.
        except Exception as e:
            log_messages.append(f"Container-Recreation fehlgeschlagen: {e}")

    duration = round(time.time() - t0, 2)

    # Cache invalidieren
    global _cached_update_data, _cache_lock_time
    _cached_update_data = None
    _cache_lock_time = 0

    # Aktuelle Version ermitteln
    updated_info = get_installed_hermes_info(force_check=True)

    # R-12: ein fehlgeschlagener Container-Recreate ist KEIN erfolgreiches Update.
    # Vorher war `recreated` nur kosmetisch — Antwort war immer success mit
    # "erfolgreich aktualisiert", obwohl der alte Container (und damit die alte
    # Version) weiterlief.
    if auto_restart and not recreated:
        return {
            "status": "error",
            "message": f"Image aktualisiert, aber Container '{HERMES_CORE_CONTAINER}' konnte NICHT neu erstellt werden — die alte Version {updated_info['version']} ({updated_info['installed_sha_short']}) läuft weiter.",
            "duration_seconds": duration,
            "channel": channel,
            "installed_version": updated_info["version"],
            "installed_sha": updated_info["installed_sha"],
            "container_restarted": False,
            "logs": log_messages
        }

    return {
        "status": "success",
        "message": f"Hermes Agent Core erfolgreich auf {updated_info['version']} ({updated_info['installed_sha_short']}) aktualisiert ({duration}s).",
        "duration_seconds": duration,
        "channel": channel,
        "installed_version": updated_info["version"],
        "installed_sha": updated_info["installed_sha"],
        "container_restarted": recreated,
        "logs": log_messages
    }

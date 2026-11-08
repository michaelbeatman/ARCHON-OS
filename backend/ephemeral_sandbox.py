"""
backend/ephemeral_sandbox.py
Flüchtige Code-Sandboxen (Ephemeral Micro-Containers / Runner).
Führt Agenten-Code in isolierten, flüchtigen Umgebungen mit harten Limits
(RAM, CPU, Timeout, optional Netzwerk-Sperre) aus und zerstört den Container sofort danach (Pillar 2 & 6).
"""

import os
import sys
import time
import uuid
import subprocess
import json
import shlex
import socket
from typing import Dict, Any, Optional

from utils.docker_client import docker_client, DockerError, docker_cli_host_args

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_TEMP_DIR = "/opt/data/archon_sandbox_runs"

# F5 (Cluster 3): Das Image war ungepinnt (`python:3.11-alpine`) — ein
# nachgeschobener Tag haette beliebigen Code in die Sandbox gebracht.
# Digest am 2026-11-08 per `docker image inspect python:3.11-alpine` ermittelt.
# Override bleibt moeglich, wird aber gegen validate_image_ref geprueft und
# muss einen @sha256:-Digest tragen.
SANDBOX_IMAGE_DEFAULT = (
    "python:3.11-alpine@sha256:bb1d70c1df30d8ee1e05214dbe82d6cdfd29833c1f47ce917f20991aca93acaa"
)
# Netz fuer den Opt-in-Fall: intern (kein Egress), eigener Name, kein Default-Bridge.
SANDBOX_NETWORK = os.environ.get("ARCHON_SANDBOX_NETWORK", "archon-sandbox_net")
# Nicht root in der Sandbox.
SANDBOX_USER = os.environ.get("ARCHON_SANDBOX_USER", "1000:1000")
SANDBOX_PIDS_LIMIT = 50


def _sandbox_image() -> str:
    """Gepinntes Sandbox-Image (Env-Override nur mit Digest)."""
    ref = (os.environ.get("ARCHON_SANDBOX_IMAGE") or "").strip()
    if not ref:
        return SANDBOX_IMAGE_DEFAULT
    if "@sha256:" not in ref or ".." in ref or " " in ref:
        # Fail-safe: ungueltiger Override wird ignoriert, nicht "best effort" benutzt.
        return SANDBOX_IMAGE_DEFAULT
    return ref


def _ensure_sandbox_network() -> None:
    """Legt `archon-sandbox_net` als internes Docker-Netz an (idempotent).

    `--internal` heisst: kein Gateway, kein NAT, kein Egress. Der Opt-in
    `network_enabled=true` gibt Code also nur Kontakt zu anderem Sandbox-Code,
    nicht ins Internet. Bereits vorhandenes Netz wird ignoriert.
    """
    try:
        subprocess.run(
            ["docker", *docker_cli_host_args(), "network", "create",
             "--internal", SANDBOX_NETWORK],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        # Nicht fatal fuer den Start; das `docker run` scheitert sichtbar,
        # falls das Netz wirklich fehlt.
        pass


def _ensure_sandbox_temp_dir():
    """Lazy directory creation - only when actually needed."""
    try:
        os.makedirs(SANDBOX_TEMP_DIR, exist_ok=True)
    except PermissionError:
        # Fallback for test environments without /opt/data access
        import tempfile
        fallback = os.path.join(tempfile.gettempdir(), "archon_sandbox_runs")
        os.makedirs(fallback, exist_ok=True)
        return fallback
    return SANDBOX_TEMP_DIR


def _resolve_host_path(container_path: str) -> Optional[str]:
    """
    Löst einen Container-Pfad auf den entsprechenden Host-Pfad über die gemounteten Volumes auf.

    Priorität:
    1. ARCHON_SANDBOX_HOST_DIR Environment Variable (Override, hat Vorrang)
    2. Automatisch über Docker API: eigenen Container inspizieren, Mounts prüfen,
       längsten Destination-Präfix-Match finden

    Returns:
        Host-Pfad als String, oder None wenn nicht auflösbar.
    """
    # 1. Override per Environment Variable
    override = os.environ.get("ARCHON_SANDBOX_HOST_DIR")
    if override:
        return os.path.abspath(override)

    # 2. Eigene Container-ID ermitteln
    container_id = os.environ.get("HOSTNAME") or socket.gethostname()
    if not container_id:
        return None

    # Container-Info via docker_client holen (Allowlist: GET /containers/{id}/json)
    try:
        raw = docker_client.request("GET", f"/containers/{container_id}/json", timeout=5.0)
        info = json.loads(raw.decode("utf-8"))
    except (DockerError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None

    mounts = info.get("Mounts", [])
    if not mounts:
        return None

    # Pfad normalisieren
    container_path = os.path.abspath(container_path)

    # Mount mit längstem Destination-Präfix finden, der container_path abdeckt
    best_match = None
    best_len = -1

    for mount in mounts:
        dest = mount.get("Destination", "")
        src = mount.get("Source", "")
        if not dest or not src:
            continue
        dest = os.path.abspath(dest)
        src = os.path.abspath(src)

        # Prüfen ob container_path unter dest liegt (oder genau dest ist)
        try:
            rel = os.path.relpath(container_path, dest)
            if not rel.startswith(".."):
                # container_path ist unter dest
                if len(dest) > best_len:
                    best_len = len(dest)
                    best_match = (src, dest, rel)
        except ValueError:
            # Kreuz-Device, nicht relativierbar
            continue

    if best_match is None:
        return None

    src, dest, rel = best_match
    if rel == ".":
        return src
    return os.path.join(src, rel)


def _terminate_container(name: str) -> bool:
    """Killt einen Sandbox-Container hart und entfernt ihn (Best effort)."""
    killed = False
    for action in (["kill", name], ["rm", "-f", name]):
        try:
            res = subprocess.run(
                ["docker", *docker_cli_host_args(), *action],
                capture_output=True, text=True, timeout=10,
            )
            if action[0] == "kill" and res.returncode == 0:
                killed = True
        except Exception:
            continue
    return killed


class EphemeralSandbox:
    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or _ensure_sandbox_temp_dir()

    def execute_in_sandbox(
        self,
        code: str,
        language: str = "python",
        memory_limit_mb: Optional[int] = None,
        cpu_limit: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
        network_enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Führt den Code in einem flüchtigen, temporären Docker-Container aus.
        Gibt Ausgaben, Laufzeit, Speicherverbrauch und Exit-Code zurück.
        """
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("ephemeral_sandbox")
            if not cfg.get("enabled", True):
                return {"status": "disabled", "error": "Ephemeral Sandbox ist in den Einstellungen deaktiviert.", "destroyed": True}
            if memory_limit_mb is None:
                memory_limit_mb = int(cfg.get("memory_limit_mb", 512))
            if cpu_limit is None:
                cpu_limit = float(cfg.get("cpu_limit", 1.0))
            if timeout_seconds is None:
                timeout_seconds = int(cfg.get("timeout_seconds", 30))
            if network_enabled is None:
                network_enabled = bool(cfg.get("network_enabled", False))
        except Exception:
            memory_limit_mb = memory_limit_mb or 512
            cpu_limit = cpu_limit or 1.0
            timeout_seconds = timeout_seconds or 30
            network_enabled = bool(network_enabled)

        run_id = f"sandbox-{uuid.uuid4().hex[:8]}"
        run_file = os.path.join(self.temp_dir, f"{run_id}.py" if language == "python" else f"{run_id}.sh")

        try:
            with open(run_file, "w", encoding="utf-8") as f:
                f.write(code)

            t0 = time.time()
            # Netz-Isolation: Default ist `none`. Der Opt-in-Fall haengt am
            # internen Sandbox-Netz (kein Egress), nicht am Default-Bridge.
            if network_enabled:
                _ensure_sandbox_network()
                net_flag = ["--network", SANDBOX_NETWORK]
            else:
                net_flag = ["--network", "none"]

            # Host-Pfad für den Volume-Mount auflösen
            host_temp_dir = _resolve_host_path(self.temp_dir)
            if not host_temp_dir:
                return {
                    "status": "error",
                    "run_id": run_id,
                    "error": "Sandbox-Host-Pfad nicht auflösbar — Ausführung verweigert (Docker-outside-of-Docker Mount fehlgeschlagen).",
                    "engine": "unavailable",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Cannot resolve container path to host path for volume mount.",
                    "duration_seconds": 0,
                    "memory_limit_mb": memory_limit_mb,
                    "network_enabled": network_enabled,
                    "limits_enforced": False,
                    "destroyed": True
                }

            # Docker-Kommando als Liste bauen (kein shell=True, daher sicheres Quoting)
            # shlex.quote ist bei Liste nicht nötig, aber Host-Pfad kann Leerzeichen enthalten
            # `-H <Socket>` ist Pflicht, nicht Kosmetik: `docker run --rm` braucht
            # attach/wait, die der Proxy absichtlich sperrt (Klasse C, siehe
            # utils.docker_client.docker_cli_host_args). Ohne die Bindung folgt die CLI
            # dem globalen DOCKER_HOST und bricht erst mitten in der Ausführung ab.
            docker_cmd = [
                "docker", *docker_cli_host_args(), "run", "--rm",
                "--name", run_id,
            ]
            docker_cmd.extend(net_flag)
            docker_cmd.extend([
                # F5: Container-Haertung. Ohne diese Flags lief Agenten-Code als
                # root, mit vollen Capabilities, unbeschraenkter PID-Zahl und
                # beschreibbarem Rootfs.
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--read-only",
                "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m",
                f"--pids-limit={SANDBOX_PIDS_LIMIT}",
                f"--user={SANDBOX_USER}",
                "-m", f"{memory_limit_mb}m",
                "--cpus", str(cpu_limit),
                # Nur lesend: der Code liegt im Mount, die Sandbox schreibt nichts zurueck.
                "-v", f"{host_temp_dir}:/sandbox:ro",
                "-w", "/sandbox",
                _sandbox_image(),
                "python", f"/sandbox/{os.path.basename(run_file)}"
            ])

            # Prüfe, ob Docker verfügbar ist; andernfalls fail-closed
            use_docker = True
            try:
                chk = subprocess.run(["docker", *docker_cli_host_args(), "info"],
                                     capture_output=True, text=True, timeout=3)
                if chk.returncode != 0:
                    use_docker = False
            except Exception:
                use_docker = False

            if use_docker:
                proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout_seconds)
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
                limits_enforced = True
            else:
                # FAIL-CLOSED: Ohne Docker-Isolation KEINE Ausführung.
                return {
                    "status": "error",
                    "run_id": run_id,
                    "error": "Sandbox-Ausführung ohne Docker-Isolation verweigert (S6-Hardening). Docker CLI oder Daemon nicht verfügbar.",
                    "engine": "unavailable",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Docker not available; host execution prohibited by S6 policy.",
                    "duration_seconds": 0,
                    "memory_limit_mb": memory_limit_mb,
                    "network_enabled": network_enabled,
                    "limits_enforced": False,
                    "destroyed": True
                }

            duration = round(time.time() - t0, 3)

            return {
                "status": "success" if exit_code == 0 else "failed",
                "run_id": run_id,
                "engine": "docker_micro_container",
                "language": language,
                "exit_code": exit_code,
                "stdout": stdout[:4000],
                "stderr": stderr[:4000],
                "duration_seconds": duration,
                "memory_limit_mb": memory_limit_mb,
                "network_enabled": network_enabled,
                "limits_enforced": limits_enforced,
                "destroyed": True
            }

        except subprocess.TimeoutExpired:
            # `--rm` greift erst, wenn der Container endet. Der CLI-Timeout toetet
            # nur den Client — der Container lief weiter. Deshalb hier explizit
            # killen (und als Sicherheitsnetz entfernen).
            terminated = _terminate_container(run_id)
            return {
                "status": "timeout",
                "run_id": run_id,
                "container": run_id,
                "error": f"Ausführung überschritt das Timeout-Limit von {timeout_seconds}s.",
                "killed": terminated,
                "destroyed": True
            }
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "error": str(e),
                "destroyed": True
            }
        finally:
            if os.path.exists(run_file):
                try:
                    os.remove(run_file)
                except Exception:
                    pass


ephemeral_sandbox = EphemeralSandbox()
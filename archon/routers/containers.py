from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""
Docker Container Management Router fuer Archon OS.
Verwaltet /api/v1/container/ Endpunkte (Settings, Logs, Metrics, Files, Actions, Inject Config).
Extrahiert aus main.py zur Modularisierung.
"""

import os
import re
import sys
import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, Body, Request
from fastapi.responses import Response as _HttpResponse, JSONResponse
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import add_ticker, logger, WORKSPACE_DIR
from archon.core.config import config
from archon.core.paths import CONFIG_FILE, OPT_DATA_DIR
from archon.core.cache import ttl_cache
from utils.docker_client import (
    docker_client as _dc,
    DockerError as _DErr,
    parse_docker_stream,
    parse_docker_stream_bytes,
)

_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert Dependencies (z.B. detect_container_port, post_docker_container_action)."""
    _DEPS.update(deps)

from archon.routers._validated_body import PassthroughBody, as_payload
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["containers"])


def load_agent_configs() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_agent_config(container_name: str, config: Dict[str, Any]) -> None:
    configs = load_agent_configs()
    configs[container_name] = config
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")


def docker_socket_request(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> bytes:
    """Deprecated-Fassade: leitet auf den abgesicherten DockerClient weiter."""
    try:
        return _dc.request(method, path, payload, timeout=timeout)
    except _DErr as e:
        print(f"[Docker] Abgelehnt/fehlgeschlagen: {e}", file=sys.stderr)
        return b""
    except Exception as e:
        print(f"[Docker] Socket-Request Fehler: {e}", file=sys.stderr)
        return b""


def _dsr(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> bytes:
    """Delegiert an main.docker_socket_request falls dort gepatcht (fuer Test-Mocks)."""
    main_mod = sys.modules.get("main")
    fn = getattr(main_mod, "docker_socket_request", None) if main_mod else None
    if fn and fn is not docker_socket_request:
        return fn(method, path, payload=payload, timeout=timeout)
    return docker_socket_request(method, path, payload=payload, timeout=timeout)


@router.get("/api/v1/container/settings")
def get_container_settings(container_name: str):
    configs = load_agent_configs()
    if not configs:
        for cpath in [os.path.join(WORKSPACE_DIR, "config", "coupled_agents.json"), os.path.join(WORKSPACE_DIR, "agents.json")]:
            if os.path.exists(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        configs = json.load(f)
                        if isinstance(configs, list):
                            configs = {item.get("id"): item for item in configs if isinstance(item, dict)}
                        break
                except Exception as exc:
                    logger.debug(f"[Containers] Kupplungs-Config nicht lesbar ({cpath}): {exc}")
    if not isinstance(configs, dict):
        configs = {}
    cfg = configs.get(container_name, {})
    port_detector = _DEPS.get("detect_container_port")
    port = port_detector(container_name) if port_detector else 8082
    if not cfg:
        cfg = {"web_ui_url": f"http://localhost:{port}", "web_ui_port": port}
    elif "web_ui_url" not in cfg:
        port = cfg.get("web_ui_port") or cfg.get("dashboard_port") or port
        cfg["web_ui_url"] = f"http://localhost:{port}"
    return cfg


@router.post("/api/v1/container/settings")
def save_container_settings(request: Request, container_name: str, config: PassthroughBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    config = as_payload(config)
    save_agent_config(container_name, config)
    return {"status": "success"}


@router.get("/api/v1/container/logs")
def get_container_logs_api(request: Request, container_name: str, tail: int = 150):
    require_admin_or_503(request)  # RBAC: Logs koennen Env-Secrets enthalten
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", container_name):
        raise HTTPException(status_code=400, detail="Ungueltiger container_name (erlaubt: a-zA-Z0-9_.-)")
    logs_raw = _dsr("GET", f"/containers/{container_name}/logs?tail={tail}&stdout=true&stderr=true")
    if not logs_raw:
        return {"logs": ""}
    logs = parse_docker_stream(logs_raw)

    ignore_patterns = [
        "Python 3 is missing from this system",
        "Launching a Python runner in internal mode",
        "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
        "native fetch fallback ALSO failed",
        "combo trace combo-",
        "RuntimeError: The current task is not holding this lock",
        "Temporary failure in name resolution",
        "Telegram polling degraded",
        "Telegram network error",
        "All connection attempts failed",
        "failed initial connection after 3 attempts, parking until a reconnect is requested",
        "Server disconnected without sending a response"
    ]
    filtered_logs = []
    for line in logs.splitlines():
        if line.strip() and not any(p in line for p in ignore_patterns):
            filtered_logs.append(line)
    logs = "\n".join(filtered_logs)

    return {"logs": logs}


def _read_file_tail(file_path: str, max_lines: int = 150, max_bytes: int = 131072) -> List[str]:
    """Liest die letzten ``max_lines`` Zeilen einer Logdatei ohne Voll-Einlesen in den RAM."""
    if max_lines <= 0:
        return []
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        return []
    with open(file_path, "rb") as f:
        if file_size > max_bytes:
            f.seek(file_size - max_bytes)
            f.readline()  # Teilzeile am Seek-Offset verwerfen
        tail_lines = deque(maxlen=max_lines)
        for raw_line in f:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if line:
                tail_lines.append(line)
        return list(tail_lines)


@router.get("/api/v1/container/all-logs")
def get_all_container_logs_api(tail: int = 40):
    containers = ["hermes", "ARCHON-OS", "n8n", "omniroute", "docker-socket-proxy"]
    if (os.environ.get("POCKETBASE_ENABLED") or "").strip().lower() in ("1", "true", "yes"):
        containers.extend(["CRM", "Pocketbase"])
    ignore_patterns = (
        "Python 3 is missing from this system",
        "Launching a Python runner in internal mode",
        "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
        "native fetch fallback ALSO failed",
        "combo trace combo-",
        "RuntimeError: The current task is not holding this lock",
        "Temporary failure in name resolution",
        "Telegram polling degraded",
        "Telegram network error",
        "All connection attempts failed",
        "failed initial connection after 3 attempts, parking until a reconnect is requested",
        "Server disconnected without sending a response",
    )

    def _fetch_one(container_name: str) -> List[str]:
        out: List[str] = []
        try:
            raw = _dsr("GET", f"/containers/{container_name}/logs?tail={tail}&stdout=true&stderr=true")
            if raw:
                parsed = parse_docker_stream(raw)
                for line in parsed.splitlines():
                    if line.strip() and not any(p in line for p in ignore_patterns):
                        out.append(f"[{container_name}] {line}")
        except Exception as exc:
            logger.debug(f"[Containers] Log-Abruf fuer '{container_name}' fehlgeschlagen: {exc}")
        return out

    combined_logs: List[str] = []
    with ThreadPoolExecutor(max_workers=min(len(containers), 8)) as pool:
        for lines_part in pool.map(_fetch_one, containers):
            combined_logs.extend(lines_part)
    return {"logs": "\n".join(combined_logs)}


@router.get("/api/v1/hermes/profile-logs")
def get_hermes_profile_logs_api(request: Request, profile_id: str, tail: int = 150):
    require_admin_or_503(request)
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9._\-]{1,128}", profile_id or "") or ".." in profile_id:
        raise HTTPException(status_code=400, detail="Invalid profile_id")
    lines = []
    hermes_home = config.hermes_home
    profile_dir = os.path.join(hermes_home, "profiles", profile_id)
    
    # 1. Profile specific logs (Tail-Read statt Voll-RAM-Einlesen)
    prof_logs_dir = os.path.join(profile_dir, "logs")
    if os.path.exists(prof_logs_dir):
        for log_file in sorted(os.listdir(prof_logs_dir)):
            if log_file.endswith(".log"):
                lp = os.path.join(prof_logs_dir, log_file)
                try:
                    for l in _read_file_tail(lp, max_lines=tail):
                        lines.append(f"[{log_file}] {l}")
                except Exception as exc:
                    logger.debug(f"[Containers] Profil-Log '{log_file}' nicht lesbar: {exc}")

    # 2. Check main logs matching profile ID (zeilenweises Streaming mit begrenztem Puffer)
    for log_name in ["agent.log", "errors.log", "gateway.log", "hermes-update.log"]:
        lp = os.path.join(hermes_home, "logs", log_name)
        if os.path.exists(lp):
            try:
                matched = deque(maxlen=max(tail, 1))
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    for l in f:
                        if profile_id in l:
                            matched.append(f"[{log_name}] {l.strip()}")
                lines.extend(matched)
            except Exception as exc:
                logger.debug(f"[Containers] Haupt-Log '{log_name}' nicht lesbar: {exc}")

    # 3. Fallback: query hermes container logs for mention of profile
    if not lines:
        for c_name in ["hermes", "hermes-agent"]:
            try:
                raw = _dsr("GET", f"/containers/{c_name}/logs?tail=300&stdout=true&stderr=true")
                if raw:
                    parsed = parse_docker_stream(raw)
                    for l in parsed.splitlines():
                        if profile_id in l:
                            lines.append(f"[{c_name}] {l}")
                    if lines:
                        break
            except Exception as exc:
                logger.debug(f"[Containers] Container-Log-Fallback '{c_name}' fehlgeschlagen: {exc}")

    if not lines:
        lines = [f"[System] Profil '{profile_id}' ist aktiv und bereit. Noch keine isolierten Hintergrund-Logs oder Fehler protokolliert."]

    return {"logs": "\n".join(lines[-tail:])}


@ttl_cache(seconds=5)
def _docker_container_stats(container_name: str) -> bytes:
    """Rohe `/stats`-Antwort von Docker — mit eigenem Timeout."""
    return _dsr(
        "GET", f"/containers/{container_name}/stats?stream=false", timeout=3.0
    )


def _container_stats_payload(stats_raw: bytes) -> Dict[str, Any]:
    """Baut die Metrik-Antwort — und unterscheidet drei Zustaende ehrlich."""
    if not stats_raw:
        return {
            "status": "unavailable",
            "cpu": 0.0,
            "memory_mb": 0.0,
            "memory_pct": 0.0,
            "hint": "Docker hat keine Statistik geliefert (Timeout oder Abfrage abgelehnt). "
                    "Der Container-Zustand ist damit unbekannt, nicht 'gestoppt'.",
        }

    try:
        stats = json.loads(stats_raw.decode("utf-8"))
    except Exception:
        return {
            "status": "unavailable",
            "cpu": 0.0,
            "memory_mb": 0.0,
            "memory_pct": 0.0,
            "hint": "Docker-Antwort war unvollstaendig oder kein JSON (abgeschnittene Antwort).",
        }

    mem_stats = stats.get("memory_stats") or {}
    cpu_stats = stats.get("cpu_stats") or {}
    precpu_stats = stats.get("precpu_stats") or {}

    if not mem_stats and not cpu_stats.get("system_cpu_usage"):
        return {"status": "Stopped", "cpu": 0.0, "memory_mb": 0.0, "memory_pct": 0.0}

    mem_usage = mem_stats.get("usage", 0)
    mem_limit = mem_stats.get("limit", 0)
    mem_mb = mem_usage / (1024 * 1024)
    mem_pct = (mem_usage / mem_limit) * 100.0 if mem_limit else 0.0

    cpu_usage = (cpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
    precpu_usage = (precpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
    system_cpu = cpu_stats.get("system_cpu_usage", 0)
    system_precpu = precpu_stats.get("system_cpu_usage", 0)
    online_cpus = cpu_stats.get("online_cpus", 1)

    cpu_percent = 0.0
    cpu_delta = cpu_usage - precpu_usage
    system_delta = system_cpu - system_precpu
    if system_delta > 0 and cpu_delta > 0:
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0

    return {
        "status": "Running",
        "cpu": min(100.0 * online_cpus, cpu_percent),
        "memory_mb": mem_mb,
        "memory_pct": mem_pct,
    }


@router.get("/api/v1/container/metrics")
def get_container_metrics_api(container_name: str):
    return _container_stats_payload(_docker_container_stats(container_name))


@router.get("/api/v1/container/files")
def get_container_files_api(request: Request, container_name: str):
    require_admin_or_503(request)
    inspect_raw = _dsr("GET", f"/containers/{container_name}/json")
    if not inspect_raw:
        return {"files": []}
    
    try:
        inspect_data = json.loads(inspect_raw.decode('utf-8'))
        working_dir = inspect_data.get("Config", {}).get("WorkingDir", "") or "/app"
    except Exception:
        working_dir = "/app"
        
    exec_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["find", ".", "-maxdepth", "3", "-type", "f"],
        "WorkingDir": working_dir
    }
    create_raw = _dsr("POST", f"/containers/{container_name}/exec", exec_payload)
    if not create_raw:
        return {"files": []}
        
    try:
        exec_id = json.loads(create_raw.decode('utf-8'))["Id"]
    except Exception:
        return {"files": []}
        
    start_payload = {"Detach": False, "Tty": False}
    start_raw = _dsr("POST", f"/exec/{exec_id}/start", start_payload)
    
    output = parse_docker_stream(start_raw)
    
    files = []
    lines = output.strip().split('\n')
    exclude_patterns = [".git/", "__pycache__/", ".venv/", "node_modules/", ".pytest_cache/"]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("./"):
            line = line[2:]
        if any(pat in line for pat in exclude_patterns):
            continue
        files.append(line)
        
    return {"files": sorted(files)}


@router.get("/api/v1/container/file/content")
def get_container_file_content(request: Request, container_name: str, filepath: str):
    require_admin_or_503(request)
    inspect_raw = _dsr("GET", f"/containers/{container_name}/json")
    if not inspect_raw:
        raise HTTPException(status_code=404, detail={"code": "containers_not_found", "params": {}})
    
    try:
        inspect_data = json.loads(inspect_raw.decode('utf-8'))
        working_dir = inspect_data.get("Config", {}).get("WorkingDir", "") or "/app"
    except Exception:
        working_dir = "/app"
        
    exec_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": ["cat", filepath],
        "WorkingDir": working_dir
    }
    create_raw = _dsr("POST", f"/containers/{container_name}/exec", exec_payload)
    if not create_raw:
        raise HTTPException(status_code=500, detail={"code": "containers_exec_create_failed", "params": {}})
        
    try:
        exec_id = json.loads(create_raw.decode('utf-8'))["Id"]
    except Exception:
        raise HTTPException(status_code=500, detail={"code": "containers_exec_parse_failed", "params": {}})
        
    start_payload = {"Detach": False, "Tty": False}
    start_raw = _dsr("POST", f"/exec/{exec_id}/start", start_payload)
    
    file_bytes = parse_docker_stream_bytes(start_raw)
    
    ext = os.path.splitext(filepath)[1].lower()
    is_binary = ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".zip", ".tar", ".gz"]
    
    if is_binary:
        import base64
        encoded = base64.b64encode(file_bytes).decode('utf-8')
        return {"content": encoded, "binary": True}
    else:
        return {"content": file_bytes.decode('utf-8', errors='ignore'), "binary": False}


class ContainerActionRequest(BaseModel):
    container_name: str
    action: str


@router.post("/api/v1/container/action")
def run_container_action(request: Request, req: ContainerActionRequest):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if req.action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail={"code": "containers_invalid_action", "params": {}})
    action_fn = _DEPS.get("post_docker_container_action")
    if not action_fn:
        raise HTTPException(status_code=500, detail={"code": "containers_action_unavailable", "params": {}})
    res = action_fn(req.container_name, req.action)
    # Fehlerpfade liefern eine JSONResponse (kein Dict) — nicht als Dict lesen.
    if isinstance(res, _HttpResponse) or not isinstance(res, dict):
        return res
    if res.get("status") == "success":
        add_ticker("SYSTEM", f"Container {req.container_name} {req.action}ed via dashboard.")
    return res


@router.post("/api/v1/container/inject_config")
async def inject_container_config(request: Request, container_name: str, config: PassthroughBody = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    config = as_payload(config)
    ports_map = {
        "odysseus": 7000,
        "hermes": 8787,
        "captain": 7001,
        "openhands": 3000
    }
    try:
        saved_configs = load_agent_configs()
        saved_cfg = saved_configs.get(container_name, {})
        custom_url = saved_cfg.get("web_ui_url", "")
        if custom_url:
            url = custom_url
        else:
            port = ports_map.get(container_name, 7000)
            url = f"http://{container_name}:{port}"
    except Exception:
        port = ports_map.get(container_name, 7000)
        url = f"http://{container_name}:{port}"

    if not url.startswith("http"):
        url = "http://" + url

    from utils.egress_guard import EgressBlocked, check_target_url
    try:
        # Container-Namen + lokale Hosts explizit zulassen, aber RFC1918/Metadaten-SSRF blockieren
        check_target_url(url, allowed=[container_name, "odysseus", "hermes", "captain", "openhands"])
    except EgressBlocked as exc:
        raise HTTPException(status_code=403, detail=f"Ziel-URL nicht erlaubt: {exc.reason}")

    config_url = url.rstrip("/") + "/config"
    
    payload = {
        "config": {
            "api_base": "http://host.docker.internal:20128/v1",
            "api_key": os.environ.get("OMNIROUTE_API_KEY", "").strip(),
            "model": config.get("model", "free-forever"),
            "system_prompt": config.get("system_prompt", "")
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(config_url, json=payload)
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = resp.text
            return {
                "status": "success",
                "target_url": config_url,
                "response": resp_data
            }
    except Exception as e:
        # Audit 23.11.2026: Fehler duerfen nicht mit HTTP 200 zurueckgehen.
        # Body-Shape bleibt unverändert (Kompatibilitaetsregel der Roadmap).
        return JSONResponse(status_code=502, content={
            "status": "error",
            "target_url": config_url,
            "message": f"Could not inject config to {config_url}: {e}"
        })

"""Router fuer Docker-Services & Model-Listing."""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from archon.core.cache import invalidate as invalidate_ttl_cache, ttl_cache
from archon.core.paths import COUPLED_AGENTS_FILE
from archon.core.runtime import _load_json
from utils.docker_client import DockerError, docker_client

logger = logging.getLogger("archon.routers.docker_services")

router = APIRouter(tags=["docker_services"])


def _require_admin(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def detect_container_port(container_identifier: str, inspected_port: int = None) -> int:
    """Ermittelt den echten Host-Port eines Docker-Containers."""
    cid_lower = str(container_identifier).lower()
    known_ports = {
        "hermes-agent": 8642,
        "prime-agent": 7681,
        "prime": 7681,
        "browser-use": 7788,
        "browser-use-webui": 7788,
        "browser": 7788,
        "gpt-researcher": 8000,
        "researcher": 8000,
        "openhands": 3000,
        "crewai-flowise": 3001,
        "flowise": 3001,
        "crewai": 3001,
        "open-webui": 8082,
        "webui": 8082,
        "autogen-studio": 8083,
        "autogen": 8083,
        "openclaw": 18789,
        "claw": 18789,
        "hermes-dashboard-proxy": 9119,
        "hermes-dashboard": 9119,
        "hermes-dash": 9119,
        "hermes": 9119,
        "odysseus-agent": 7000,
        "odysseus-odysseus-1": 7000,
        "odysseus-1": 7000,
        "odysseus": 7000,
        "omniroute": 20128,
        "n8n": 5678,
        "espocrm": 8081,
        "agent-os-container": 8501,
    }

    for key, port in known_ports.items():
        if key in cid_lower:
            return port

    if inspected_port and inspected_port not in (0,):
        return inspected_port

    return 8082


def _services_config_fallback(reason: str) -> List[Dict]:
    """Z-11: Statische Wunschliste als klar gekennzeichneter Fallback."""
    import main as app_main

    fallback = []
    services_list = app_main.load_services() if hasattr(app_main, "load_services") else []
    for svc in services_list:
        if not isinstance(svc, dict):
            continue
        item = dict(svc)
        item["source"] = "config-fallback"
        item["online"] = False
        item["running"] = False
        item["fallback_reason"] = reason
        fallback.append(item)
    return fallback


@ttl_cache(seconds=10)
def get_docker_containers_from_socket() -> List[Dict]:
    """Liest ALLE echten Docker-Container direkt vom Docker-Daemon über /var/run/docker.sock aus."""
    import main as app_main

    try:
        raw = docker_client.request("GET", "/containers/json?all=true", timeout=5.0)
        containers_data = json.loads(raw.decode("utf-8"))
    except DockerError as e:
        logger.error(f"Error querying docker socket via docker_client: {e}")
        return _services_config_fallback(f"docker_error: {e}")
    except Exception as e:
        logger.error(f"Error parsing docker response: {e}")
        return _services_config_fallback(f"parse_error: {e}")

    containers_list = []
    SYSTEM_INTERNAL_IDS = [
        "agent-os-container",
        "agent-os-ui",
        "agent-os",
        "agent_os",
        "agent_os_ui",
        "agent_os_container",
        "crm",
        "pocketbase",
        "pocketbase-crm",
    ]

    saved_configs = {}
    if os.path.exists(COUPLED_AGENTS_FILE):
        raw_saved = _load_json(COUPLED_AGENTS_FILE, [])
        if isinstance(raw_saved, list):
            for sc in raw_saved:
                saved_configs[sc.get("id") or sc.get("container_name")] = sc
        elif isinstance(raw_saved, dict):
            saved_configs = raw_saved

    for c in containers_data:
        if not isinstance(c, dict):
            continue
        raw_names = c.get("Names") or []
        c_name = raw_names[0].lstrip("/") if (raw_names and len(raw_names) > 0) else c.get("Id", "")[:12]
        c_id = c_name

        if c_name.lower() in SYSTEM_INTERNAL_IDS:
            continue

        status_str = c.get("Status", "") or ""
        is_online = "Up" in status_str
        image_str = c.get("Image", "") or ""

        saved_cfg = saved_configs.get(c_name) or saved_configs.get(c_id) or {}
        is_active = is_online
        if "active" in saved_cfg:
            is_active = bool(saved_cfg["active"])
        elif "coupled" in saved_cfg:
            is_active = bool(saved_cfg["coupled"])

        ports_list = c.get("Ports") or []
        inspected_p = None
        for p in ports_list:
            if isinstance(p, dict):
                if "PublicPort" in p:
                    inspected_p = p["PublicPort"]
                    break
                elif "PrivatePort" in p:
                    inspected_p = p["PrivatePort"]

        port_num = detect_container_port(c_name, inspected_p)
        display_name = c_name.replace("-", " ").replace("_", " ").title()

        default_role = saved_cfg.get("role") or (
            "Orchestrator & System-Architekt" if "hermes" in c_name.lower() else "Senior Coder / Software Engineer"
        )
        default_model = saved_cfg.get("model") or "free-forever"

        containers_list.append({
            "id": c_id,
            "name": display_name,
            "container_name": c_name,
            "image": image_str,
            "description": f"Docker Container '{c_name}' | Image: {image_str.split(':')[0]} | Port: {port_num}",
            "status": status_str,
            "active": is_active,
            "coupled": is_active,
            "online": is_online,
            "running": is_online,
            "port": port_num,
            "model": default_model,
            "role": default_role,
        })

    if len(containers_list) > 0:
        return containers_list
    return app_main.load_services() if hasattr(app_main, "load_services") else []


def post_docker_container_action(container_name: str, action: str = "start", raise_on_error: bool = False) -> dict:
    try:
        if action == "restart":
            docker_client.restart_container(container_name)
        else:
            docker_client.container_action(container_name, action)

        if container_name in ["hermes-dashboard", "hermes"] and action in ["start", "restart"]:
            try:
                docker_client.restart_container("hermes-dashboard-proxy")
            except Exception:
                pass

        try:
            from archon.routers.containers import _docker_container_stats
            invalidate_ttl_cache(_docker_container_stats)
        except Exception:
            pass

        return {"status": "success", "message": f"Container {container_name} {action}ed."}
    except DockerError as e:
        if raise_on_error:
            status = (
                502
                if (getattr(e, "status_code", 0) in (500, 502, 503) or "connection" in str(e).lower() or "socket" in str(e).lower())
                else (getattr(e, "status_code", 0) or 400)
            )
            raise HTTPException(status_code=status, detail=str(e))
        return {"status": "error", "message": str(e)}
    except HTTPException:
        raise
    except Exception as e:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=str(e))
        return {"status": "error", "message": str(e)}


@router.get("/api/v1/services")
@router.get("/api/services")
def api_get_services():
    return get_docker_containers_from_socket()


@router.post("/api/docker/start")
def api_docker_start(payload: Dict, request: Request):
    _require_admin(request)
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name:
        raise HTTPException(status_code=400, detail="Missing container_name")
    return post_docker_container_action(c_name, "start", raise_on_error=True)


@router.post("/api/docker/stop")
def api_docker_stop(payload: Dict, request: Request):
    _require_admin(request)
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name:
        raise HTTPException(status_code=400, detail="Missing container_name")
    return post_docker_container_action(c_name, "stop", raise_on_error=True)


@router.post("/api/v1/services")
def api_save_services(request: Request, services: List[Dict]):
    _require_admin(request)
    import main as app_main

    if hasattr(app_main, "save_services"):
        app_main.save_services(services)
    return {"status": "success"}


@router.get("/api/models")
async def api_get_models(request: Request):
    if (
        "x-hermes-session-token" in request.headers
        or "x-hermes-csrf-token" in request.headers
        or "authorization" in request.headers
    ):
        import main as app_main

        return await app_main.forward_to_hermes(request)

    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "hermes-3", "gemini-1.5-pro"]

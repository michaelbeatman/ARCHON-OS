"""Router fuer Hermes Gateway Lifecycle (Start, Stop, Autostart, Config)."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request

logger = logging.getLogger("archon.routers.gateway")

router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])

_idle_stop_running = False


def _run_docker_exec(cmd: list) -> tuple[int, str, str]:
    """Run a command inside the hermes container via docker_client (allowlisted)."""
    import main as app_main

    if hasattr(app_main, "_run_docker_exec") and app_main._run_docker_exec is not _run_docker_exec:
        return app_main._run_docker_exec(cmd)

    from utils.docker_client import DockerError, docker_client, parse_docker_stream

    target_containers = ["hermes-webui", "hermes", "hermes-agent"]
    for c_name in target_containers:
        try:
            output_bytes = docker_client.exec_command(c_name, cmd, timeout=25.0)
            stdout = parse_docker_stream(output_bytes)
            return 0, stdout, ""
        except DockerError:
            continue
        except Exception:
            continue

    return 1, "", "Failed to execute in hermes container (tried hermes-agent, hermes)"


def _parse_gateway_list(stdout: str) -> list:
    """Parses the hermes gateway list output into a list of dicts."""
    if not stdout:
        return []

    text = stdout.strip()
    if not text:
        return []

    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
        if isinstance(parsed, dict):
            for key in ("profiles", "gateways", "data"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [p for p in value if isinstance(p, dict)]

    profiles = []
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        if set(line) <= set("-|=+ \t"):
            continue
        cells = [c for c in line.replace("|", " ").split() if c]
        if len(cells) < 2:
            continue
        if index == 0 and cells[0].lower() in ("id", "profile", "name"):
            continue
        profile_id = cells[0].strip("* ")
        status = cells[1].lower()
        if not profile_id:
            continue
        profiles.append({
            "id": profile_id,
            "status": "running" if "run" in status or "up" in status or "active" in status else status,
        })
    return profiles


async def _gateway_idle_stop_loop():
    global _idle_stop_running
    if _idle_stop_running:
        logger.warning("[GatewayManager] Idle-Stop-Loop laeuft bereits - kein zweiter Start.")
        return
    _idle_stop_running = True
    try:
        while True:
            await asyncio.sleep(300)
            try:
                cfg = _load_gateway_config()
                timeout_min = cfg.get("idle_timeout_minutes", 30)
                last_used = cfg.get("last_used", {})
                autostart = cfg.get("autostart", {})
                now = datetime.datetime.now()
                rc, stdout, _ = _run_docker_exec(["hermes", "gateway", "list"])
                if rc != 0:
                    continue
                running_profiles = [
                    p["id"]
                    for p in _parse_gateway_list(stdout)
                    if p.get("status") == "running" and p["id"] != "default"
                ]
                for pid in running_profiles:
                    if autostart.get(pid, False):
                        continue
                    last = last_used.get(pid)
                    if last:
                        try:
                            last_dt = datetime.datetime.fromisoformat(last)
                            idle_min = (now - last_dt).total_seconds() / 60
                            if idle_min >= timeout_min:
                                _run_docker_exec(["hermes", "gateway", "stop", pid])
                                print(f"[GatewayManager] Auto-stopped idle gateway: {pid} (idle {idle_min:.0f}m)")
                        except Exception:
                            pass
            except Exception as e:
                print(f"[GatewayManager] Idle-stop loop error: {e}")
    finally:
        _idle_stop_running = False


def _require_admin(request: Request):
    import main as app_main
    if hasattr(app_main, "require_admin"):
        app_main.require_admin(request)


def _load_gateway_config() -> Dict:
    import main as app_main
    cfg = app_main._load_json(app_main.GATEWAY_CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("idle_timeout_minutes", 30)
    cfg.setdefault("autostart", {"default": True})
    cfg.setdefault("last_used", {})
    return cfg


def _save_gateway_config(cfg: Dict):
    import main as app_main
    app_main._save_json(app_main.GATEWAY_CONFIG_FILE, cfg)


def _get_all_installed_profiles() -> list[str]:
    """List profile names from the mounted profiles volume directory."""
    import main as app_main
    candidates = ["/opt/data/profiles", os.path.join(app_main.MEMORY_DIR, "hermes_profiles")]
    for d in candidates:
        if os.path.exists(d) and os.path.isdir(d):
            try:
                entries = [e for e in os.listdir(d) if os.path.isdir(os.path.join(d, e))]
                if entries:
                    if "default" not in entries:
                        entries.insert(0, "default")
                    return sorted(entries)
            except Exception:
                pass
    return ["default"]


def _update_profile_status(profile_id: str, new_status: str):
    import main as app_main
    try:
        prof_file = os.path.join(app_main.WORKSPACE_DIR, "agent_profiles.json")
        if os.path.exists(prof_file):
            with open(prof_file, "r", encoding="utf-8") as f:
                profs = json.load(f)
            updated = False
            for p in profs:
                if p.get("id") == profile_id:
                    p["status"] = new_status
                    updated = True
                    break
            if updated:
                with open(prof_file, "w", encoding="utf-8") as f:
                    json.dump(profs, f, indent=2, ensure_ascii=False)
        hier_file = os.path.join(app_main.WORKSPACE_DIR, "config", "org_hierarchy.json")
        if os.path.exists(hier_file):
            with open(hier_file, "r", encoding="utf-8") as f:
                hier = json.load(f)
            for n in hier.get("nodes", []):
                if n.get("id") == profile_id:
                    n["status"] = new_status
                    break
            with open(hier_file, "w", encoding="utf-8") as f:
                json.dump(hier, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Error updating profile status for {profile_id}: {e}")


@router.get("/list")
def api_gateway_list():
    import main as app_main
    all_profiles = app_main._get_all_installed_profiles()
    cfg = app_main._load_gateway_config()
    autostart_map = cfg.get("autostart", {})
    last_used_map = cfg.get("last_used", {})
    active_gateways = cfg.get("active_gateways", {})

    gw_state_file = "/opt/data/gateway_state.json"
    is_master_running = False
    if os.path.exists(gw_state_file):
        try:
            gw_data = app_main._load_json(gw_state_file, {})
            is_master_running = gw_data.get("gateway_state") == "running"
        except Exception:
            pass

    profiles = []
    for pid in all_profiles:
        if pid == "default":
            status = "running" if is_master_running else "stopped"
        else:
            status = "running" if active_gateways.get(pid, False) else "stopped"

        profiles.append({
            "id": pid,
            "status": status,
            "autostart": autostart_map.get(pid, pid == "default"),
            "last_used": last_used_map.get(pid, None)
        })

    return {"profiles": profiles, "idle_timeout_minutes": cfg.get("idle_timeout_minutes", 30)}


@router.post("/start")
async def api_gateway_start(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")

    cmd = ["hermes", "gateway", "start"] if profile_id == "default" else ["hermes", "--profile", profile_id, "gateway", "start"]
    import main as app_main
    rc, stdout, stderr = await asyncio.to_thread(app_main._run_docker_exec, cmd)
    if rc != 0:
        logger.error(f"[Gateway] Start fuer '{profile_id}' fehlgeschlagen (rc={rc}): {stderr or stdout}")
        raise HTTPException(
            status_code=502,
            detail=f"Gateway-Start fehlgeschlagen: {(stderr or stdout or 'unbekannter Fehler').strip()[:400]}",
        )

    cfg = app_main._load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = True
    cfg.setdefault("last_used", {})
    cfg["last_used"][profile_id] = datetime.datetime.now().isoformat()
    app_main._save_gateway_config(cfg)
    app_main._update_profile_status(profile_id, "active")

    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}


@router.post("/stop")
async def api_gateway_stop(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    if profile_id == "default":
        raise HTTPException(status_code=400, detail="default gateway cannot be stopped")

    cmd = ["hermes", "--profile", profile_id, "gateway", "stop"]
    import main as app_main
    rc, stdout, stderr = await asyncio.to_thread(app_main._run_docker_exec, cmd)
    if rc != 0:
        logger.error(f"[Gateway] Stop fuer '{profile_id}' fehlgeschlagen (rc={rc}): {stderr or stdout}")
        raise HTTPException(
            status_code=502,
            detail=f"Gateway-Stop fehlgeschlagen: {(stderr or stdout or 'unbekannter Fehler').strip()[:400]}",
        )

    cfg = app_main._load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = False
    app_main._save_gateway_config(cfg)
    app_main._update_profile_status(profile_id, "standby")

    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}


@router.get("/config")
def api_get_gateway_config():
    import main as app_main
    return app_main._load_gateway_config()


@router.post("/config")
def api_save_gateway_config_endpoint(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    import main as app_main
    cfg = app_main._load_gateway_config()
    if "idle_timeout_minutes" in payload:
        try:
            cfg["idle_timeout_minutes"] = max(1, int(payload["idle_timeout_minutes"]))
        except (ValueError, TypeError):
            pass
    if "autostart" in payload and isinstance(payload["autostart"], dict):
        cfg["autostart"].update(payload["autostart"])
    app_main._save_gateway_config(cfg)
    return cfg


@router.post("/autostart")
def api_gateway_autostart(request: Request, payload: Dict = Body(...)):
    _require_admin(request)
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    enable = bool(payload.get("autostart", False))
    import main as app_main
    cfg = app_main._load_gateway_config()
    cfg.setdefault("autostart", {})
    cfg["autostart"][profile_id] = enable
    app_main._save_gateway_config(cfg)
    return {"ok": True, "profile_id": profile_id, "autostart": enable}


@router.post("/stop-all")
def api_gateway_stop_all(request: Request):
    _require_admin(request)
    import main as app_main
    cfg = app_main._load_gateway_config()
    active_map = cfg.get("active_gateways", {})
    stopped = []
    for pid, is_active in list(active_map.items()):
        if pid == "default" or not is_active:
            continue
        cfg["active_gateways"][pid] = False
        app_main._update_profile_status(pid, "standby")
        try:
            app_main._run_docker_exec(["hermes", "--profile", pid, "gateway", "stop"])
        except Exception:
            pass
        stopped.append(pid)
    app_main._save_gateway_config(cfg)
    return {"ok": True, "stopped": stopped}

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
async def api_gateway_list():
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
async def api_gateway_stop_all(request: Request):
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

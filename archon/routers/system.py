"""/api/system/* — Health, Recovery, Drain, Backups, Diagnose."""

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from archon.core.cache import ttl_cache
from archon.core.runtime import MEMORY_DIR, SETTINGS_FILE, WORKSPACE_DIR, add_ticker, logger
from archon.core.state_db import STATE_DB_PATH, get_state_db_dep

# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# _load_json, _save_json, broadcast_event werden aus main.py per configure() injiziert
_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhängigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"_load_json", "_save_json", "broadcast_event"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] system: fehlende Dependencies {sorted(_missing)}")


router = APIRouter()

# --------------------------------------------------
# Hermes-Core-Diagnose (read-only)
# --------------------------------------------------
# Reihenfolge = Prioritaet, per Env ueberschreibbar.
# Beleg: docker-compose.yml deklariert den Core als `gateway run` auf 8642 mit
# container_name "hermes". In DIESEM Stack laeuft er als `hermes-agent`
# (Container-Name und Netz-Alias, per docker inspect); "hermes" existiert nicht.
# Die Route ist bewusst eine Diagnose: sie startet nichts (siehe Docstring dort).
HERMES_CORE_CANDIDATES: tuple = tuple(
    c.strip()
    for c in os.environ.get("ARCHON_HERMES_CORE_CONTAINER", "hermes-agent,hermes").split(",")
    if c.strip()
)


def _inspect_hermes_core(name: str) -> Optional[Dict[str, Any]]:
    """Read-only Zustandsabfrage ueber den Allowlist-Client.

    Rueckgabe: Container-JSON, oder None wenn der Container nicht existiert (404).
    Wirft DockerError, wenn Docker selbst nicht antwortet oder der Name ungueltig ist.
    """
    from utils.docker_client import DockerError, docker_client, validate_container_name

    status, raw = docker_client.request_status(
        "GET", f"/containers/{validate_container_name(name)}/json"
    )
    if status == 404:
        return None
    if status != 200:
        raise DockerError(f"Docker inspect '{name}' fehlgeschlagen (HTTP {status}): {raw[:200]!r}")
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise DockerError(f"Antwort fuer '{name}' ist kein JSON: {exc}") from exc


def _log_core_state(conn: sqlite3.Connection, target: str, state: str, started_at: float) -> None:
    """Diagnose-Ergebnis protokollieren. Fehler hier duerfen die Antwort nicht kippen."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_restart_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT,
                initiated_at REAL,
                duration_seconds REAL,
                status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO system_restart_logs (target, initiated_at, duration_seconds, status)"
            " VALUES (?, ?, ?, ?)",
            (target, started_at, round(time.time() - started_at, 2), state),
        )
        conn.commit()
    except Exception as log_err:
        logger.warning(f"[Hermes Core Log Error]: {log_err}")


async def _check_service_health(name: str, url_candidates: List[str], client: httpx.AsyncClient) -> Dict[str, Any]:
    for url in url_candidates:
        t0 = time.time()
        try:
            resp = await client.get(url, timeout=3.0)
            latency = round((time.time() - t0) * 1000, 1)
            if resp.status_code in [200, 204, 301, 302, 307, 308]:
                return {"status": "up", "latency_ms": latency, "endpoint": url}
            elif resp.status_code == 404 and name == "hermes_core":
                # Hermes root returns 404 on / if no static handler, but server is actively UP
                return {"status": "up", "latency_ms": latency, "endpoint": url}
            elif resp.status_code < 500:
                return {"status": "up", "latency_ms": latency, "endpoint": url}
        except Exception:
            continue
    return {"status": "down", "latency_ms": 0.0}


@router.get("/api/system/health")
async def api_system_health():
    """
    Returns latency and operational status for all 4 core components:
    - hermes_core
    - omniroute
    - hermes_dashboard
    - docker_proxy
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        t_core = _check_service_health(
            "hermes_core",
            ["http://hermes-agent:8642", "http://hermes:8642", "http://hermes:8644",
             "http://host.docker.internal:8644"],
            client
        )
        t_omni = _check_service_health(
            "omniroute",
            ["http://omniroute:20128/v1/models", "http://omniroute:20128", "http://host.docker.internal:20128"],
            client
        )
        t_dash = _check_service_health(
            "hermes_dashboard",
            ["http://hermes-dashboard:9119", "http://hermes-dashboard:9120", "http://host.docker.internal:9119"],
            client
        )
        t_docker = _check_service_health(
            "docker_proxy",
            ["http://docker-socket-proxy:2375/_ping", "http://docker-socket-proxy:2375/version"],
            client
        )
        core_res, omni_res, dash_res, docker_res = await asyncio.gather(
            t_core, t_omni, t_dash, t_docker
        )

    all_up = (
        core_res["status"] == "up" and
        omni_res["status"] == "up" and
        dash_res["status"] == "up" and
        docker_res["status"] == "up"
    )
    max_latency = max(
        core_res.get("latency_ms", 0),
        omni_res.get("latency_ms", 0),
        dash_res.get("latency_ms", 0),
        docker_res.get("latency_ms", 0)
    )

    if not all_up:
        overall_status = "unhealthy"
    elif max_latency > 500:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "timestamp": time.time(),
        "services": {
            "hermes_core": core_res,
            "omniroute": omni_res,
            "hermes_dashboard": dash_res,
            "docker_proxy": docker_res
        }
    }


@router.post("/api/system/hermes/restart")
async def api_system_hermes_restart(
    conn: sqlite3.Connection = Depends(get_state_db_dep),
):
    """
    Diagnose des Hermes-Core-Containers — read-only, startet nichts.

    Der Pfad heisst historisch "/restart" und loeste einen Neustart eines Containers
    namens `hermes` aus, den es in diesem Stack nicht gibt (jeder Aufruf endete 500).
    Diese Route startet bewusst KEINEN Container: der Core-Ableger `hermes-agent`
    faehrt `gateway run` und wuerde mit dem laufenden Host-Gateway um denselben
    Bot-Token konkurrieren (Telegram-getUpdates-Konflikt — beide Instanzen verlieren
    Nachrichten). Der Start bleibt ein manueller Eingriff (`docker start <name>`).

    Die State-DB kommt per FastAPI-Dependency (A7-Pilot); sie protokolliert den Befund.

    Antworten (stabil):
      200 {"status":"ok","target":…,"running":true,"image":…,"hint":…}
      409 {"status":"not_running","target":…,"running":false,"image":…,"hint":…}
      409 {"status":"absent","tried":[…],"hint":…}
      502 {"status":"docker_error","hint":…}
    """
    t0 = time.time()
    tried: List[str] = []
    found_name: Optional[str] = None
    found_data: Dict[str, Any] = {}

    for name in HERMES_CORE_CANDIDATES:
        try:
            data = _inspect_hermes_core(name)
        except Exception as exc:
            logger.error(f"[Hermes Core Probe Failed]: {exc}")
            return JSONResponse(status_code=502, content={
                "status": "docker_error",
                "hint": f"Docker-Abfrage fehlgeschlagen ({name}): {exc}",
            })
        tried.append(name)
        if data is not None:
            found_name, found_data = name, data
            break

    if found_name is None:
        hint = (
            f"Kein Hermes-Core-Container vorhanden (versucht: {', '.join(tried)}). "
            "Diese Route startet bewusst keinen Container — bitte manuell starten."
        )
        _log_core_state(conn, "none", "absent", t0)
        add_ticker("Hermes System", f"Hermes Core nicht vorhanden ({', '.join(tried)}).")
        return JSONResponse(status_code=409, content={
            "status": "absent",
            "tried": tried,
            "hint": hint,
        })

    running = bool(found_data.get("State", {}).get("Running", False))
    image = str(found_data.get("Config", {}).get("Image") or "")

    if running:
        outcome, code = "ok", 200
        hint = f"Container {found_name} laeuft (Image: {image or 'unbekannt'})."
        ticker_text = f"Hermes Core {found_name}: laeuft."
    else:
        outcome, code = "not_running", 409
        hint = (
            f"Container {found_name} ist gestoppt (RestartPolicy=no). "
            f"Start ist bewusst NICHT Teil dieser Route — bitte manuell: docker start {found_name}"
        )
        ticker_text = f"Hermes Core {found_name}: gestoppt (kein Start ausgeloest)."

    _log_core_state(conn, found_name, outcome, t0)
    add_ticker("Hermes System", ticker_text)
    return JSONResponse(status_code=code, content={
        "status": outcome,
        "target": found_name,
        "running": running,
        "image": image,
        "hint": hint,
    })


@router.get("/api/system/language")
def get_system_language():
    s = _DEPS["_load_json"](SETTINGS_FILE, {})
    lang = s.get("system_language") or s.get("language") or "de"
    return {
        "status": "success",
        "language": lang,
        "supported": ["de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"]
    }


@router.post("/api/system/language")
def set_system_language(payload: dict = Body(...)):
    lang = (payload.get("language") or "de").strip().lower()
    supported = ["de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"]
    if lang not in supported:
        raise HTTPException(status_code=400, detail=f"Nicht unterstützte Sprache: {lang}")
    s = _DEPS["_load_json"](SETTINGS_FILE, {})
    s["system_language"] = lang
    s["language"] = lang
    s["default_language"] = lang
    _DEPS["_save_json"](SETTINGS_FILE, s)
    return {"status": "success", "language": lang}


@router.get("/api/v1/system/update/check")
def api_system_update_check():
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    return system_updater.get_update_status()


@router.get("/api/v1/system/update/local-changes")
def api_system_update_local_changes():
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    return system_updater.get_local_changes()


@router.post("/api/v1/system/update/push")
def api_system_update_push(payload: dict = Body(default={})):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    msg = payload.get("message")
    version = payload.get("version")
    step = payload.get("step", "custom")
    return system_updater.push_changes(commit_message=msg, custom_version=version, version_step=step)


@router.post("/api/v1/system/update/apply")
def api_system_update_apply(payload: dict = Body(default={}), background_tasks: BackgroundTasks = None):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    make_backup = payload.get("backup", True)
    res = system_updater.apply_update(make_backup=make_backup)
    if res.get("status") == "success" and background_tasks is not None:
        background_tasks.add_task(system_updater.schedule_delayed_reload, delay=2.0)
    return res


@router.get("/api/v1/system/update/snapshots")
def api_system_update_snapshots():
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    return {"status": "success", "snapshots": system_updater.list_snapshots()}


@router.post("/api/v1/system/update/rollback")
def api_system_update_rollback(payload: dict = Body(...)):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    snapshot_id = payload.get("snapshot_id", "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="Snapshot-ID erforderlich.")
    return system_updater.rollback_snapshot(snapshot_id)


@router.post("/api/v1/system/update/backup")
def api_system_update_backup(payload: dict = Body(default={})):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    tag = payload.get("tag", "manual").strip() or "manual"
    return system_updater.create_snapshot(tag=tag)


@router.get("/api/system/drain/status")
@router.get("/api/v1/system/drain/status")
def api_drain_status():
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    return {"status": "success", "drain_status": graceful_shutdown_coordinator.get_status()}


@router.post("/api/system/drain/start")
@router.post("/api/v1/system/drain/start")
def api_start_drain(payload: dict = Body(default={})):
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "Manuell angefordertes Draining")
    grace = payload.get("grace_seconds", 15.0)
    res = graceful_shutdown_coordinator.start_draining(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


@router.post("/api/system/drain/cancel")
@router.post("/api/v1/system/drain/cancel")
def api_cancel_drain():
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    res = graceful_shutdown_coordinator.cancel_draining()
    return {"status": "success", "result": res}


@router.post("/api/system/drain/execute-shutdown")
@router.post("/api/v1/system/drain/execute-shutdown")
def api_execute_shutdown(payload: dict = Body(default={})):
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "API-gesteuerter Shutdown")
    grace = payload.get("grace_seconds", 5.0)
    res = graceful_shutdown_coordinator.execute_graceful_shutdown_sync(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


@router.post("/api/system/standup/run")
async def api_run_morning_standup():
    """Generiert ein proaktives Morgen-Briefing über Tasks, Flotte, Inbox und Token-Kosten."""
    from backend.autonomous_standup import generate_morning_standup
    res = await generate_morning_standup()
    add_ticker("Morgen-Standup", f"Tages-Briefing für {res.get('date')} erstellt.")
    _DEPS["broadcast_event"]("morning_briefing", res)
    return res


@router.get("/api/system/standup/latest")
async def api_get_latest_morning_standup():
    """Liefert das aktuellste Morgen-Briefing aus dem Obsidian Vault."""
    try:
        from local_memory_bridge import LocalMemoryBridge
        bridge = LocalMemoryBridge()
        out_dir = os.path.join(bridge.vault_path, "01_PROJEKTE", "Daily_Briefings")
        if os.path.exists(out_dir):
            _entries = await asyncio.to_thread(os.listdir, out_dir)
            files = sorted([f for f in _entries if f.startswith("Briefing_") and f.endswith(".md")], reverse=True)
            if files:
                def _read_latest():
                    with open(os.path.join(out_dir, files[0]), "r", encoding="utf-8") as bf:
                        return bf.read()
                _content = await asyncio.to_thread(_read_latest)
                return {"status": "success", "filename": files[0], "content": _content}
    except Exception:
        pass
    from backend.autonomous_standup import generate_morning_standup
    return await generate_morning_standup()


@router.post("/api/system/deadlock-check")
def api_deadlock_check(timeout_seconds: int = 45):
    from backend.deadlock_supervisor import deadlock_supervisor
    return deadlock_supervisor.detect_and_resolve_deadlocks(stagnation_threshold_seconds=timeout_seconds)


@router.post("/api/system/backup-db")
def api_backup_databases():
    from backend.db_backup_manager import db_backup_manager
    return db_backup_manager.checkpoint_and_backup()


@router.get("/api/system/backup-db/list")
def api_list_db_backups():
    from backend.db_backup_manager import db_backup_manager
    return {"status": "success", "backups": db_backup_manager.list_backups()}


@router.post("/api/system/optimize-db")
def api_optimize_db():
    from backend.db_optimizer import optimize_all_databases
    return optimize_all_databases()


@router.get("/api/system/health-score")
@ttl_cache(seconds=30)
def api_get_health_score():
    from backend.system_diagnostics import get_system_health_score
    return get_system_health_score()


@router.post("/api/system/generate-dossier")
def api_generate_dossier():
    from backend.system_dossier_generator import generate_system_dossier
    return generate_system_dossier()


@router.post("/api/system/consolidate-memory")
def api_trigger_memory_consolidation(payload: Dict = Body(default={})):
    from backend.memory_consolidator import run_sleep_cycle_consolidation
    force = bool(payload.get("force", True))
    return run_sleep_cycle_consolidation(force=force)


@router.post("/api/system/write-batcher/enqueue")
def api_write_batcher_enqueue(payload: Dict = Body(...)):
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.enqueue(
        event_type=payload.get("event_type", "telemetry"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {})
    )


@router.post("/api/system/write-batcher/flush")
def api_write_batcher_flush():
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.flush()


@router.get("/api/system/write-batcher/stats")
def api_write_batcher_stats():
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.get_stats()


@router.get("/api/system/resource-backpressure")
def api_check_resource_backpressure(simulate_overload: bool = False):
    from backend.resource_backpressure import resource_backpressure_protector
    return resource_backpressure_protector.check_health_and_backpressure(simulate_overload=simulate_overload)

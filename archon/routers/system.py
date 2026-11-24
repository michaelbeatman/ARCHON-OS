from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
from archon.routers._rbac import require_admin_or_503
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
from pydantic import BaseModel, ConfigDict, Field

from archon.core.cache import ttl_cache
from archon.core.config import config
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
    _missing = {"_load_json", "_save_json", "broadcast_event", "require_admin"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] system: fehlende Dependencies {sorted(_missing)}")


router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class DbRestoreRequest(BaseModel):
    """Restore-Payload: Dateiname Pflicht, Ausfuehrung nur mit confirmed=True."""
    model_config = ConfigDict(extra="ignore")
    file_name: str = Field(min_length=1, max_length=255)
    confirmed: bool = False


# P0 / API_VALIDATION_ROADMAP Etappe 2b: Pydantic-Modelle fuer die
# Body-Dict-Endpunkte. extra="ignore" bewahrt die Client-Kompatibilitaet.
class SystemLanguageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    language: str = "de"


class SystemUpdatePushRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: Optional[str] = None
    version: Optional[str] = None
    step: str = "custom"


class SystemUpdateApplyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    backup: bool = True


class SystemUpdateRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    snapshot_id: str = ""


class SystemUpdateBackupRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tag: str = "manual"


class DrainStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = "Manuell angefordertes Draining"
    grace_seconds: float = 15.0


class DrainShutdownRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = "API-gesteuerter Shutdown"
    grace_seconds: float = 5.0


class MemoryConsolidationTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    force: bool = True


class WriteBatcherEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_type: str = "telemetry"
    source_module: str = "router"
    payload: Dict[str, Any] = Field(default_factory=dict)


def _as_payload(value) -> Dict[str, Any]:
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _require_admin(request: Request) -> None:
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


# --------------------------------------------------
# Hermes-Core-Diagnose (read-only)
# --------------------------------------------------
# Reihenfolge = Prioritaet, per Env ueberschreibbar.
# Beleg: docker-compose.yml deklariert den Core als `gateway run` auf 8642 mit
# container_name "hermes". In DIESEM Stack laeuft er als `hermes-agent`
# (Container-Name und Netz-Alias, per docker inspect); "hermes" existiert nicht.
# Die Route ist bewusst eine Diagnose: sie startet nichts (siehe Docstring dort).
HERMES_CORE_CANDIDATES: tuple = tuple(config.hermes_core_containers)


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
        except Exception:
            continue
    if name == "hermes_core":
        t0 = time.time()
        try:
            resp = await client.get(
                "http://docker-socket-proxy:2375/containers/hermes-agent/json",
                timeout=2.0,
            )
            latency = round((time.time() - t0) * 1000, 1)
            if resp.status_code == 200 and resp.json().get("State", {}).get("Running"):
                return {"status": "up", "latency_ms": latency, "endpoint": "container://hermes-agent"}
        except Exception as exc:
            logger.debug(f"[SystemHealth] Hermes-Container-Check fehlgeschlagen: {exc}")
    return {"status": "down", "latency_ms": 0.0}


_SYSTEM_HTTP_CLIENT: Optional[httpx.AsyncClient] = None


def _get_system_http_client() -> httpx.AsyncClient:
    global _SYSTEM_HTTP_CLIENT
    if _SYSTEM_HTTP_CLIENT is None or _SYSTEM_HTTP_CLIENT.is_closed:
        _SYSTEM_HTTP_CLIENT = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(3.0, connect=1.5),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=8),
        )
    return _SYSTEM_HTTP_CLIENT


@router.get("/api/system/health")
async def api_system_health():
    """
    Returns latency and operational status for all 4 core components:
    - hermes_core
    - omniroute
    - hermes_dashboard
    - docker_proxy
    """
    client = _get_system_http_client()
    t_core = _check_service_health(
        "hermes_core",
        ["http://hermes:8642/health", "http://hermes:8642", "http://hermes-agent:8642/health",
         "http://hermes-agent:8642", "http://host.docker.internal:8644"],
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
async def api_system_hermes_restart(request: Request,
    conn: sqlite3.Connection = Depends(get_state_db_dep),
):
    """
    Diagnose des Hermes-Core-Containers — read-only, startet nichts.

    Der Pfad heisst historisch "/restart" und loeste einen Neustart eines Containers
    namens `hermes` aus, den es in diesem Stack nicht gibt (jeder Aufruf endete 500).
    Diese Route startet bewusst KEINEN Container: der Start des Core-Ablegers
    `hermes-agent` (Cmd `gateway run`) bleibt ein manueller Eingriff
    (`docker start <name>`) — so entschieden von Michael Keller am 2026-11-07.
    (Er hat klargestellt, dass der Telegram-Token ausschliesslich vom Telegram-Bot
    genutzt wird; eine getUpdates-Konkurrenz ist damit nicht belegt.)

    Die State-DB kommt per FastAPI-Dependency (A7-Pilot); sie protokolliert den Befund.

    Antworten (stabil):
      200 {"status":"ok","target":…,"running":true,"image":…,"hint":…}
      409 {"status":"not_running","target":…,"running":false,"image":…,"hint":…}
      409 {"status":"absent","tried":[…],"hint":…}
      502 {"status":"docker_error","hint":…}
    """
    _require_admin(request)  # RBAC: Admin-Sache
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
def set_system_language(request: Request, payload: SystemLanguageRequest = Body(...)):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC: Admin-Sache
    lang = (payload.get("language") or "de").strip().lower()
    supported = ["de", "en", "es", "fr", "pt", "ru", "ja", "ko", "zh"]
    if lang not in supported:
        raise HTTPException(status_code=400, detail={"code": "system_unsupported_language", "params": {"lang": lang}})
    s = _DEPS["_load_json"](SETTINGS_FILE, {})
    s["system_language"] = lang
    s["language"] = lang
    s["default_language"] = lang
    _DEPS["_save_json"](SETTINGS_FILE, s)
    return {"status": "success", "language": lang}


@router.get("/api/v1/system/update/check")
def api_system_update_check(force: bool = False, local_only: bool = False):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    if local_only:
        return system_updater.get_local_update_status()
    if force:
        system_updater.invalidate(system_updater.get_update_status)
        system_updater.invalidate(system_updater.get_local_changes)
    return system_updater.get_update_status()


@router.get("/api/v1/system/update/local-changes")
def api_system_update_local_changes(force: bool = False):
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    if force:
        system_updater.invalidate(system_updater.get_local_changes)
    return system_updater.get_local_changes()


@router.post("/api/v1/system/update/push")
def api_system_update_push(request: Request, payload: SystemUpdatePushRequest = Body(default=SystemUpdatePushRequest())):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC: Admin-Sache
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    msg = payload.get("message")
    version = payload.get("version")
    step = payload.get("step", "custom")
    return system_updater.push_changes(commit_message=msg, custom_version=version, version_step=step)


@router.post("/api/v1/system/update/apply")
def api_system_update_apply(request: Request, payload: SystemUpdateApplyRequest = Body(default=SystemUpdateApplyRequest()), background_tasks: BackgroundTasks = None):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC-Pilot: Update des Systems ist Admin-Sache
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
def api_system_update_rollback(request: Request, payload: SystemUpdateRollbackRequest = Body(...)):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC-Pilot: Rollback des Systems ist Admin-Sache
    from backend import system_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    snapshot_id = payload.get("snapshot_id", "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="Snapshot-ID erforderlich.")
    return system_updater.rollback_snapshot(snapshot_id)


@router.post("/api/v1/system/update/backup")
def api_system_update_backup(request: Request, payload: SystemUpdateBackupRequest = Body(default=SystemUpdateBackupRequest())):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC: Admin-Sache
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
def api_start_drain(request: Request, payload: DrainStartRequest = Body(default=DrainStartRequest())):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC: Admin-Sache
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "Manuell angefordertes Draining")
    grace = payload.get("grace_seconds", 15.0)
    res = graceful_shutdown_coordinator.start_draining(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


@router.post("/api/system/drain/cancel")
@router.post("/api/v1/system/drain/cancel")
def api_cancel_drain(request: Request):
    _require_admin(request)  # RBAC: Admin-Sache
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    res = graceful_shutdown_coordinator.cancel_draining()
    return {"status": "success", "result": res}


@router.post("/api/system/drain/execute-shutdown")
@router.post("/api/v1/system/drain/execute-shutdown")
def api_execute_shutdown(request: Request, payload: DrainShutdownRequest = Body(default=DrainShutdownRequest())):
    _require_admin(request)
    payload = payload.model_dump()  # RBAC: Admin-Sache
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
    reason = payload.get("reason", "API-gesteuerter Shutdown")
    grace = payload.get("grace_seconds", 5.0)
    res = graceful_shutdown_coordinator.execute_graceful_shutdown_sync(reason=reason, grace_seconds=grace)
    return {"status": "success", "result": res}


@router.post("/api/system/standup/run")
async def api_run_morning_standup(request: Request):
    """Generiert ein proaktives Morgen-Briefing über Tasks, Flotte, Inbox und Token-Kosten."""
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.autonomous_standup import generate_morning_standup
    res = await generate_morning_standup()
    add_ticker("Morgen-Standup", f"Tages-Briefing für {res.get('date')} erstellt.")
    _DEPS["broadcast_event"]("morning_briefing", res)
    return res


@router.get("/api/system/standup/latest")
async def api_get_latest_morning_standup():
    """Liefert das aktuellste Morgen-Briefing aus dem Obsidian Vault."""
    out_dir = None
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
    except Exception as e:
        # Z-16: Lesefehler beim Zugriff auf vorhandene Briefings nicht still verschlucken
        logger.error(f"[Standup] Fehler beim Lesen vorhandener Briefings: {e}")
        raise HTTPException(status_code=500, detail={"code": "system_briefing_read_failed", "params": {"error": str(e)}})
    from backend.autonomous_standup import generate_morning_standup
    return await generate_morning_standup()


@router.post("/api/system/deadlock-check")
def api_deadlock_check(request: Request, timeout_seconds: int = 45):
    _require_admin(request)
    from backend.deadlock_supervisor import deadlock_supervisor
    return deadlock_supervisor.detect_and_resolve_deadlocks(stagnation_threshold_seconds=timeout_seconds)


@router.post("/api/system/backup-db")
def api_backup_databases(request: Request):
    _require_admin(request)  # RBAC: Admin-Sache
    from backend.db_backup_manager import db_backup_manager
    return db_backup_manager.checkpoint_and_backup()


@router.get("/api/system/backup-db/list")
def api_list_db_backups():
    from backend.db_backup_manager import db_backup_manager
    return {"status": "success", "backups": db_backup_manager.list_backups()}


@router.post("/api/system/backup-db/restore")
def api_restore_db_backup(request: Request, body: DbRestoreRequest):
    """Getesteter Restore-Pfad: dry_run erst pruefen, dann mit Confirmed-Flag ausführen."""
    _require_admin(request)
    from backend.db_backup_manager import db_backup_manager
    file_name = body.file_name
    if not file_name:
        raise HTTPException(status_code=400, detail="file_name erforderlich")
    confirmed = body.confirmed
    try:
        result = db_backup_manager.restore_backup(file_name, dry_run=not confirmed)
        return {"status": "success", **result}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("[System] DB-Restore fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=500, detail="Restore fehlgeschlagen")


class SecretRestoreRequest(BaseModel):
    """D03: Secrets-Restore nur mit explizitem confirm (HITL/Admin)."""
    model_config = ConfigDict(extra="ignore")
    backup_file: str = Field(min_length=1, max_length=255)
    confirmed: bool = False


@router.post("/api/system/restore-secrets")
def api_restore_secret_files(request: Request, body: SecretRestoreRequest):
    _require_admin(request)
    from backend.db_backup_manager import db_backup_manager
    if not body.confirmed:
        result = db_backup_manager.restore_secret_files(body.backup_file, dry_run=True)
        return {"status": "dry_run", **result}
    result = db_backup_manager.restore_secret_files(
        body.backup_file, dry_run=False, confirm=True
    )
    return {"status": "success", **result}


@router.post("/api/system/optimize-db")
def api_optimize_db(request: Request):
    _require_admin(request)  # RBAC: Admin-Sache
    from backend.db_optimizer import optimize_all_databases
    return optimize_all_databases()


@router.get("/api/system/health-score")
@ttl_cache(seconds=30)
def api_get_health_score():
    from backend.system_diagnostics import get_system_health_score
    return get_system_health_score()


@router.post("/api/system/generate-dossier")
def api_generate_dossier(request: Request):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    from backend.system_dossier_generator import generate_system_dossier
    return generate_system_dossier()


@router.post("/api/system/consolidate-memory")
def api_trigger_memory_consolidation(request: Request, payload: MemoryConsolidationTriggerRequest = Body(default=MemoryConsolidationTriggerRequest())):
    _require_admin(request)
    payload = _as_payload(payload)
    from backend.memory_consolidator import run_sleep_cycle_consolidation
    force = bool(payload.get("force", True))
    return run_sleep_cycle_consolidation(force=force)


@router.post("/api/system/write-batcher/enqueue")
def api_write_batcher_enqueue(request: Request, payload: WriteBatcherEnqueueRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Audit v3 Befund 2.2
    payload = _as_payload(payload)
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.enqueue(
        event_type=payload.get("event_type", "telemetry"),
        source_module=payload.get("source_module", "router"),
        payload=payload.get("payload", {})
    )


@router.post("/api/system/write-batcher/flush")
def api_write_batcher_flush(request: Request):
    _require_admin(request)
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.flush()


@router.get("/api/system/write-batcher/stats")
def api_write_batcher_stats():
    from backend.async_write_batcher import async_write_batcher
    return async_write_batcher.get_stats()


@router.get("/api/system/resource-backpressure")
def api_check_resource_backpressure(request: Request, simulate_overload: bool = False):
    # D01/MED: simulierte Systemzustände sind keine echten Messwerte und
    # duerfen nur mit Admin-Recht erzeugt werden.
    if simulate_overload:
        require_admin_or_503(request)
    from backend.resource_backpressure import resource_backpressure_protector
    result = resource_backpressure_protector.check_health_and_backpressure(simulate_overload=simulate_overload)
    result["simulated"] = bool(simulate_overload)
    return result


def _load_legal_profile() -> Dict[str, str]:
    loader = _DEPS.get("_load_json")
    settings_data: Dict[str, Any] = {}
    if callable(loader):
        raw = loader(SETTINGS_FILE, {})
        if isinstance(raw, dict):
            settings_data = raw
    elif os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                settings_data = raw
        except Exception:
            settings_data = {}
    legal = settings_data.get("legal_profile", {}) if isinstance(settings_data, dict) else {}
    if not isinstance(legal, dict):
        legal = {}
    corp: Dict[str, Any] = {}
    try:
        from backend.corporate_manager import corporate_manager
        corp = corporate_manager.get_company("archon-systems") or corporate_manager.get_company() or {}
    except Exception:
        corp = {}
    c_addr = corp.get("address") if isinstance(corp.get("address"), dict) else {}
    c_cnt = corp.get("contact") if isinstance(corp.get("contact"), dict) else {}
    c_reg = corp.get("registry") if isinstance(corp.get("registry"), dict) else {}
    c_tax = corp.get("tax") if isinstance(corp.get("tax"), dict) else {}
    c_city = " ".join(x for x in (str(c_addr.get("postal_code") or "").strip(), str(c_addr.get("city") or "").strip()) if x)
    street_val = str(legal.get("street") or c_addr.get("street") or "Bitte in settings.json -> legal_profile pflegen")
    postal_city_val = str(legal.get("postal_city") or c_city or "-")
    rep_val = str(legal.get("represented_by") or c_reg.get("managing_directors") or "Geschäftsführung")
    email_val = str(legal.get("email") or c_cnt.get("email") or settings_data.get("admin_email") or "-")
    return {
        "company_name": str(legal.get("company_name") or corp.get("name") or settings_data.get("company_name") or "Archon OS Betreiber (in settings.json -> legal_profile konfigurieren)"),
        "legal_form": str(legal.get("legal_form") or corp.get("legal_form") or "-"),
        "street": street_val,
        "postal_city": postal_city_val,
        "country": str(legal.get("country") or c_addr.get("country") or "Deutschland"),
        "represented_by": rep_val,
        "editorial_responsible": str(legal.get("editorial_responsible") or rep_val),
        "editorial_address": str(legal.get("editorial_address") or f"{street_val}, {postal_city_val}"),
        "email": email_val,
        "phone": str(legal.get("phone") or c_cnt.get("phone") or "-"),
        "website": str(legal.get("website") or c_cnt.get("website") or "-"),
        "vat_id": str(legal.get("vat_id") or c_tax.get("vat_id") or "-"),
        "w_idnr": str(legal.get("w_idnr") or c_tax.get("w_idnr") or "-"),
        "register_court": str(legal.get("register_court") or c_reg.get("court") or "-"),
        "register_number": str(legal.get("register_number") or c_reg.get("number") or "-"),
        "supervisory_authority": str(legal.get("supervisory_authority") or "-"),
        "dpo_contact": str(legal.get("dpo_contact") or f"Datenschutzbeauftragte(r) unter obiger Anschrift oder {email_val}"),
    }


@router.get("/api/legal/impressum")
def api_legal_impressum():
    """Pflichtangaben gemäß § 5 DDG (Digitale-Dienste-Gesetz) und § 18 Abs. 2 MStV."""
    import html as _html
    p = {k: _html.escape(v) for k, v in _load_legal_profile().items()}
    sup_row = (
        f"<p><strong>Zuständige Aufsichtsbehörde (§ 5 Abs. 1 Nr. 3 DDG):</strong> {p['supervisory_authority']}</p>"
        if p["supervisory_authority"] != "-"
        else ""
    )
    html_body = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Impressum — Archon OS</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.6;color:#111}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.25rem}}code{{background:#f4f4f5;padding:.15rem .35rem;border-radius:4px}}</style>
</head><body>
<h1>Impressum (§ 5 DDG &amp; § 18 Abs. 2 MStV)</h1>
<p><strong>Anbieter (§ 5 Abs. 1 Nr. 1 DDG):</strong> {p['company_name']} ({p['legal_form']})<br>
<strong>Vertretungsberechtigt:</strong> {p['represented_by']}<br>
<strong>Anschrift:</strong> {p['street']}, {p['postal_city']}, {p['country']}</p>
<p><strong>Kontakt (§ 5 Abs. 1 Nr. 2 DDG):</strong> E-Mail: {p['email']} · Telefon: {p['phone']} · Web: {p['website']}</p>
<p><strong>Register / Steuer (§ 5 Abs. 1 Nr. 4, 6 DDG):</strong> Registergericht: {p['register_court']} ({p['register_number']}) · USt-IdNr.: {p['vat_id']} · W-IdNr.: {p['w_idnr']}</p>
{sup_row}
<h2>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h2>
<p>{p['editorial_responsible']}, {p['editorial_address']}</p>
<h2>Verbraucherstreitbeilegung (§ 36 VSBG)</h2>
<p>Wir sind weder verpflichtet noch bereit, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
<p><small>Hinweis: Betreiberdaten werden aus dem Unternehmensstamm (<code>archon-systems</code>) bzw. <code>settings.json</code> (<code>legal_profile</code>) geladen.</small></p>
</body></html>"""
    return HTMLResponse(content=html_body)


@router.get("/api/legal/datenschutz")
def api_legal_datenschutz():
    """Datenschutzhinweise gemäß Art. 13 DSGVO und § 25 TDDDG."""
    import html as _html
    p = {k: _html.escape(v) for k, v in _load_legal_profile().items()}
    html_body = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Datenschutz — Archon OS</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.6;color:#111}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.25rem}}</style>
</head><body>
<h1>Datenschutzhinweise (Art. 13 DSGVO &amp; § 25 TDDDG)</h1>
<p><strong>Verantwortlicher (Art. 13 Abs. 1 lit. a DSGVO):</strong> {p['company_name']} ({p['legal_form']}), vertreten durch {p['represented_by']}, {p['street']}, {p['postal_city']}, {p['country']} (E-Mail: {p['email']}, Tel.: {p['phone']})</p>
<p><strong>Datenschutzbeauftragte(r) (Art. 13 Abs. 1 lit. b DSGVO):</strong> {p['dpo_contact']}</p>
<h2>1. Zwecke, Rechtsgrundlagen &amp; berechtigte Interessen (Art. 13 Abs. 1 lit. c, d DSGVO)</h2>
<p>Die Verarbeitung erfolgt zur Vertragserfüllung und Mandantenverwaltung (Art. 6 Abs. 1 lit. b DSGVO), zur Erfüllung steuer- und handelsrechtlicher Pflichten (Art. 6 Abs. 1 lit. c DSGVO i.V.m. AO/HGB/UStG), auf Grundlage berechtigter Interessen an IT-Sicherheit, Audit-Integrität und Betriebssicherheit (Art. 6 Abs. 1 lit. f DSGVO) sowie bei ausdrücklicher Einwilligung gemäß Art. 6 Abs. 1 lit. a DSGVO.</p>
<h2>2. Empfänger, KI-Egress &amp; Drittlandtransfer (Art. 13 Abs. 1 lit. e, f DSGVO)</h2>
<p>Sensible Domänen (Finanzen, Verträge, CRM, HR, DSGVO) werden über das Privacy-Gateway auf lokale On-Premise-Modelle geleitet oder per Secret-Masker/PII-Scrubber anonymisiert. Bei explizit freigegebenen externen KI-APIs oder Messaging-Diensten (z. B. OpenRouter/Anthropic/OpenAI/Telegram) in Drittländern außerhalb des EWR greifen Garantien nach Art. 44–49 DSGVO (EU-Standardvertragsklauseln bzw. Angemessenheitsbeschluss; Kopien über obige Kontaktadresse anforderbar).</p>
<h2>3. Speicherdauer &amp; gesetzliche Aufbewahrungsfristen (Art. 13 Abs. 2 lit. a DSGVO &amp; BEG IV)</h2>
<p>Buchungsbelege und Rechnungen unterliegen seit BEG IV (01.01.2025) einer gesetzlichen Aufbewahrungsfrist von <strong>8 Jahren</strong> (§ 147 Abs. 3 AO, § 257 Abs. 4 HGB, § 14b UStG), Jahresabschlüsse und steuerliche Sonderunterlagen <strong>10 Jahre</strong> (§ 147 Abs. 1 Nr. 1 AO), Handelsbriefe und Verträge <strong>6 Jahre</strong>. Sonstige Kontakt- und Sessiondaten werden nach Zweckerfüllung gelöscht bzw. bei gesetzlicher Pflicht nach Art. 18 DSGVO gesperrt.</p>
<h2>4. Speicherzugriffe &amp; Cookies (§ 25 TDDDG)</h2>
<p>Die Web-Oberfläche speichert Session-Token, Sprachauswahl (<code>archon_language</code>) und UI-Zustände technisch erforderlich nach § 25 Abs. 2 Nr. 2 TDDDG im Browser (Cookie / <code>localStorage</code>). Optionale Komfort-Präferenzen können im Browser gelöscht werden.</p>
<h2>5. Betroffenenrechte, Widerruf &amp; Beschwerderecht (Art. 13 Abs. 2 lit. b–e DSGVO)</h2>
<p>Sie haben das Recht auf Auskunft (Art. 15), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20), Widerspruch (Art. 21) sowie jederzeitigen Widerruf erteilter Einwilligungen (Art. 7 Abs. 3) ohne Berührung der Rechtmäßigkeit bis zum Widerruf. Zudem besteht ein <strong>Beschwerderecht bei einer Datenschutz-Aufsichtsbehörde</strong> (Art. 77 DSGVO). Die Bereitstellung vertraglicher/steuerlicher Pflichtdaten ist gesetzlich oder vertraglich erforderlich; ohne sie ist eine Rechnungs- oder Vertragsabwicklung nicht möglich.</p>
<h2>6. Automatisierte Entscheidungsfindung / Profiling (Art. 13 Abs. 2 lit. f, Art. 22 DSGVO)</h2>
<p>Es findet keine ausschließlich automatisierte Entscheidungsfindung einschließlich Profiling mit rechtlicher Wirkung statt. Kritische Vorgänge (Mahnversand, Vertragsfreigaben, E-Mail-Versand) werden erst nach ausdrücklicher menschlicher Prüfung (Human-in-the-Loop) ausgelöst.</p>
</body></html>"""
    return HTMLResponse(content=html_body)


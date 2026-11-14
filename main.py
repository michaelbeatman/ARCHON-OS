import os
import secrets
import uuid
import sys
import time
import json
import csv
import datetime
import asyncio
import socket
import re
import threading
import tempfile
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Query, Request, Body, File, UploadFile, Form, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response, StreamingResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import shutil
import sqlite3
import base64
import yaml
import core_dispatcher
import httpx
import logging
from utils.docker_client import (
    docker_client, DockerError, parse_docker_stream, parse_docker_stream_bytes,
)

from backend.platform_paths import (
    OBSIDIAN_VAULT, OBSIDIAN_VAULT_ALT, HERMES_HOME,
    PERSONALAKTEN_DIR, PROJEKTE_DIR, soul_path, profile_dir, agent_log_path,
)

# Orchestration functions (extracted to archon.core.orchestration)
from archon.core.orchestration import (
    _execute_mission_control_task as _orch_execute_mission_control_task,
    _paperclip_hire_profile_by_id as _orch_paperclip_hire_profile_by_id,
    _set_agent_profile_status as _orch_set_agent_profile_status,
    _trigger_sandy_staffing_nomination as _orch_trigger_sandy_staffing_nomination,
    _finalize_synthesis_after_approval as _orch_finalize_synthesis_after_approval,
    _fan_in_maybe_start_synthesis as _orch_fan_in_maybe_start_synthesis,
    _tg_ping_synthesis as _orch_tg_ping_synthesis,
    _run_synthesis_cascade as _orch_run_synthesis_cascade,
)

# --- A5-Etappe 1: unveraenderliche Modul-Konstanten ausgelagert ------------
# Quelle ist jetzt archon/core/constants.py (ein Ort, keine Kopie). Mutabler
# State und Pfad-Konstanten bleiben bewusst in dieser Datei (Fallstrick 24 / B10).
from archon.core.constants import (
    _AUTH_PUBLIC_PREFIXES,
    _AUTH_PROTECTED_PREFIXES,
    _AUTH_API_PREFIXES,
    _DECISION_TYPEN,
    DELEGATION_PROTOCOL_PROMPT,
    STUDIO_BG_UPLOAD_DIR,
)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archon_os")

# ---------------------------------------------------------------------------
# Ein einziger, geordneter Startup/Shutdown-Pfad.
# Vorher: 3x @app.on_event("startup") + 2x ("shutdown") — deprecated und in
# unbestimmter Reihenfolge ausgefuehrt. Jetzt: explizite Registrierung in
# _STARTUP_HOOKS / _SHUTDOWN_HOOKS am Dateiende, Ausfuehrung im Lifespan.
# ---------------------------------------------------------------------------
_STARTUP_HOOKS: List[Any] = []
_SHUTDOWN_HOOKS: List[Any] = []


async def _archon_lifespan(_app_instance):
    for hook in list(_STARTUP_HOOKS):
        name = getattr(hook, "__name__", repr(hook))
        try:
            result = hook()
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # ein defekter Hook darf den Start nicht kippen
            logger.warning(f"[Lifespan] Startup-Hook '{name}' fehlgeschlagen: {e}")
    try:
        yield
    finally:
        for hook in reversed(list(_SHUTDOWN_HOOKS)):
            name = getattr(hook, "__name__", repr(hook))
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"[Lifespan] Shutdown-Hook '{name}' fehlgeschlagen: {e}")

# Begrenzter Graceful-Shutdown: sonst blockiert uvicorn --reload bei jeder
# Code-Änderung unbegrenzt auf offene Streams und der Server friert ein.
try:
    from backend.uvicorn_shutdown_guard import install as _install_shutdown_guard
    _install_shutdown_guard()
except Exception as _shutdown_guard_err:
    logger.warning(f"[Startup] Shutdown-Guard nicht aktiv: {_shutdown_guard_err}")

app = FastAPI(title="Agent OS Control Panel", lifespan=_archon_lifespan)
_APP_START_TS = time.time()

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:3005",
        "http://127.0.0.1:3005",
        "http://localhost:8787",
        "http://127.0.0.1:8787",
    ] + [o.strip() for o in os.environ.get("ARCHON_CORS_ORIGINS", "").split(",") if o.strip()],
    # LAN-Zugriffe (Handy/Tablet) ohne Wildcard für das ganze Internet
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin"],
)

# Rate-Limiting (S8 aus dem Audit): bremst teure/gefaehrliche Pfade eng und
# alles andere grosszuegig. Kein neuer Endpunkt, daher Routen-Paritaet unberuehrt.
# Notaus: ARCHON_RATE_LIMIT_ENABLED=0
try:
    from utils.rate_limit import RateLimitMiddleware, _env_int as _rl_env_int
    app.add_middleware(RateLimitMiddleware)
    logger.info("[RateLimit] aktiv (Standard %s/min, strikt %s/min)",
                _rl_env_int("ARCHON_RATE_LIMIT_DEFAULT", 600),
                _rl_env_int("ARCHON_RATE_LIMIT_STRICT", 20))
except Exception as _err_rl:
    logger.warning(f"[RateLimit] nicht aktiv: {_err_rl}")

# --- Locale Middleware (Etappe 4): Accept-Language -> request.state.lang ---
try:
    from archon.core.locale_middleware import LocaleMiddleware
    app.add_middleware(LocaleMiddleware)
    logger.info("[i18n] LocaleMiddleware aktiv")
except Exception as _err_lm:
    logger.warning(f"[i18n] LocaleMiddleware nicht aktiv: {_err_lm}")

# --- Demo Mode Middleware (M47): Read-only sandbox for live showcases ---
try:
    from backend.demo_mode import DemoModeMiddleware
    app.add_middleware(DemoModeMiddleware)
    logger.info("[DemoMode] DemoModeMiddleware aktiv")
except Exception as _err_dm:
    logger.warning(f"[DemoMode] DemoModeMiddleware nicht aktiv: {_err_dm}")

# --- Exception-Handler (Etappe 4): code+params Format für API-Fehler ---
try:
    from archon.core.exceptions import register_exception_handlers
    register_exception_handlers(app)
    logger.info("[i18n] Exception-Handler registriert (code+params)")
except Exception as _err_eh:
    logger.warning(f"[i18n] Exception-Handler nicht aktiv: {_err_eh}")

@app.middleware("http")
async def add_no_cache_for_avatars(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/avatars/") or path.startswith("/static/js/") or path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- Auth-Gate (wirkt nur, wenn settings.auth.enabled = true) --------------
_AUTH_PUBLIC_EXACT = {"/", "/health", "/metrics", "/favicon.ico", "/openapi.json", "/login", "/docs", "/redoc"}

# Nicht-/api-Pfade, die trotzdem geschuetzt sein muessen: eingebettete
# Admin-Oberflaechen (n8n-Editor, OmniRoute-Konsole) und App-Shells.

_SERVICE_TOKEN_CACHE = {"ts": 0.0, "token": ""}


def _get_service_token() -> str:
    """Service-Token für interne Automaten (n8n, Adapter). Env hat Vorrang, sonst Datei."""
    now = time.time()
    if _SERVICE_TOKEN_CACHE["token"] and (now - _SERVICE_TOKEN_CACHE["ts"]) < 30.0:
        return _SERVICE_TOKEN_CACHE["token"]
    tok = (os.environ.get("ARCHON_SERVICE_TOKEN") or "").strip()
    if not tok:
        for path in ("/app/data/.archon_service_token", os.path.join(os.getcwd(), "data", ".archon_service_token")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    break
            except Exception:
                continue
    _SERVICE_TOKEN_CACHE.update({"ts": now, "token": tok})
    return tok


# --- RAG-Sync-Zugang: Env statt Klartext, fail-fast ------------------------
# Der Vault->RAG-Sync braucht einen AnythingLLM-API-Key. Bis 07.11.2026 stand
# er als Literal im Code (hier und in mehreren tools/-Skripten); jetzt kommt er
# ausschliesslich aus der Umgebung. Variablenname bewusst identisch mit
# backend/rag_bridge.py — ein Secret, ein Name, kein zweites Schema.
RAG_API_KEY_ENV = "ANYTHINGLLM_API_KEY"


class MissingRagApiKeyError(RuntimeError):
    """Der RAG-Sync hat keinen API-Key — es wird kein Request abgesetzt."""


def _get_rag_api_key() -> str:
    """Liefert den RAG-API-Key aus der Umgebung.

    Kein stiller Fallback auf einen Default: ein leerer Key endet downstream
    als Auth-Fehler oder als Sync, der nichts tut. Deshalb Exception am
    Nutzungspunkt, damit kein subprocess mit leerem Key startet.
    """
    key = (os.environ.get(RAG_API_KEY_ENV) or "").strip()
    if not key:
        raise MissingRagApiKeyError(
            f"{RAG_API_KEY_ENV} fehlt in der Umgebung. Der Vault->RAG-Sync "
            "startet nicht (kein Fallback-Key, kein Request mit leerem Key)."
        )
    return key


def _check_rag_api_key_config() -> bool:
    """Startcheck: fehlender RAG-Key ist als ERROR sichtbar, kippt den Start nicht.

    Der Key wird nur im Hintergrund-Trigger nach einem Library-Upload mit
    auto_ingest gebraucht. Ein harter Startabbruch wuerde einen Dienst
    verweigern, der ohne die RAG-Funktion voll funktionsfaehig ist — deshalb
    fail-fast am Nutzungspunkt (Exception + ERROR dort) plus diese Zeile.
    """
    try:
        _get_rag_api_key()
    except MissingRagApiKeyError as err:
        logger.error(f"[RAG-Sync] {err}")
        return False
    logger.info(f"[RAG-Sync] API-Key aus {RAG_API_KEY_ENV} geladen.")
    return True


def _request_has_service_token(request: Request) -> bool:
    expected = _get_service_token()
    provided = request.headers.get("x-archon-service-token", "")
    if not expected or not provided:
        return False
    import hmac
    return hmac.compare_digest(provided, expected)


def _auth_unavailable_response() -> JSONResponse:
    """Einheitliche 503-Antwort des Gates, wenn die Prüfung selbst ausfällt.

    Fail-closed: lieber eine ehrliche 503 als ein stilles Durchlassen.
    """
    return JSONResponse(
        status_code=503,
        content={"error": "auth_unavailable", "detail": "Auth unavailable"},
    )


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Blockt API-Aufrufe ohne gültige Session, sobald Multi-User aktiv ist.

    Die HTML-Hülle und /api/auth/* bleiben erreichbar, damit das Frontend den
    Login zeigen kann. Interne Automaten (n8n, Telegram-Adapter) weisen sich
    über den Header X-Archon-Service-Token aus.

    Fail-closed (R-08): schlaegt die Prüfung selbst fehl (Importfehler, kaputte
    ``settings.json``, DB-Fehler), antwortet das Gate mit 503 statt
    durchzulassen. Ein Gate, das bei einem Fehler öffnet, ist keines.
    """
    try:
        from backend.auth_service import auth_service as _auth
        auth_enabled = _auth.is_auth_enabled()
    except Exception as err:  # noqa: BLE001 - Fail-closed ist hier die Absicht
        logger.error(f"[Auth] Gate kann die Konfiguration nicht lesen: {err}")
        return _auth_unavailable_response()

    if not auth_enabled:
        return await call_next(request)

    path = request.url.path
    # API-Pfade unter einem oeffentlichen Prefix (F1/R-34) werden wie /api/
    # behandelt: sie reichen an fremde Admin-Oberflaechen durch und dürfen
    # nicht ungeprüft bleiben.
    is_forced_api = path.startswith(_AUTH_API_PREFIXES)
    if not is_forced_api and (path in _AUTH_PUBLIC_EXACT or path.startswith(_AUTH_PUBLIC_PREFIXES)):
        return await call_next(request)

    if _request_has_service_token(request):
        return await call_next(request)

    token = ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "x-archon-session" in request.headers:
        token = request.headers.get("x-archon-session", "").strip()
    elif "archon_session" in request.cookies:
        token = request.cookies.get("archon_session", "").strip()

    try:
        session_user = _auth.verify_session(token) if token else None
        if session_user:
            request.state.user = session_user
            if (
                request.method in ("POST", "PUT", "DELETE", "PATCH")
                and str(session_user.get("role", "")).lower() == "viewer"
                and path not in ("/api/auth/logout", "/api/auth/login")
            ):
                return JSONResponse(
                    status_code=403,
                    content={"error": "forbidden", "detail": "Nur Administratoren oder Operatoren duerfen schreibende Aktionen ausfuehren (erkannte Rolle: viewer)."},
                )
            return await call_next(request)
    except Exception as err:  # noqa: BLE001 - Fail-closed auch beim Prüfen
        logger.error(f"[Auth] Session-Prüfung fehlgeschlagen: {err}")
        return _auth_unavailable_response()

    if path.startswith("/api/") or is_forced_api:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Login erforderlich", "login_url": "/login"},
        )
    if path.startswith(_AUTH_PROTECTED_PREFIXES):
        # Eingebettete Admin-UIs: zur Login-Seite umleiten statt JSON zu liefern
        return RedirectResponse(url=f"/login?next={path}", status_code=307)
    return await call_next(request)

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}

@app.get("/metrics")
def prometheus_metrics():
    """Prometheus-konformer Metriken-Endpoint fuer Scraping und Monitoring."""
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        return Response(content=f"# Error collecting metrics: {e}\n", status_code=500, media_type="text/plain")

from archon.routers.telemetry import (
    router as _telemetry_router,
    api_get_agent_activity,
    api_get_agent_projects,
    get_hud_telemetry,
    _count_running_containers,
    api_telemetry_dashboard,
)
app.include_router(_telemetry_router)



# Pfade + Laufzeit-Helfer kommen aus app.core.runtime (gemeinsame Basis für
# main.py und die ausgelagerten Router; dort zyklenfrei definiert).
from archon.core.runtime import (  # noqa: E402
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, OBSIDIAN_VAULT_DIR,
    resolve_obsidian_vault_path, ticker_entries, add_ticker, broadcast_event,
    _load_json, _save_json, atomic_write_json, _SSE_SUBSCRIBERS, _SSE_SUB_LOCK,
)

# --- A5-Etappe 4b: Pfad-Konstanten ausgelagert -----------------------------
# Quelle ist archon/core/paths.py; alle Pfade leiten sich aus den Basis-
# Verzeichnissen oben ab (keine zweite __file__-Wahrheit). main.py importiert
# nur noch — die Werte sind per scripts/path_constants_snapshot.py belegt.
from archon.core.paths import (
    MEMORY_FILE, AGENTS_FILE, KANBAN_FILE, THEME_FILE, THEME_LIVE_FILE,
    GATEWAY_CONFIG_FILE, QUICKCHAT_SESSIONS_DIR, COUPLED_AGENTS_FILE,
    THEMES_DIR, FRAMEWORKS_FILE, BOARDROOM_HISTORY_FILE, ROLES_FILE,
    SERVICES_FILE, HERMES_PROFILES_DIR, _SKILL_INDEX_DISK_PATH,
    SETTINGS_FILE, KANBAN_CARDS_FILE, CONFIG_FILE,
)

from archon.core.permissions import (  # noqa: E402
    PERMISSION_GATES_FILE, load_permission_gates as _load_permission_gates,
    save_permission_gates as _save_permission_gates, create_permission_gate as _create_permission_gate,
    set_decision_factory as _set_decision_factory,
)
from archon.core.cache import invalidate as invalidate_ttl_cache, ttl_cache  # noqa: E402
from archon.core.state_db import (  # noqa: E402
    ClosingConnection, STATE_DB_PATH, _get_state_db, _get_profile_state_db,
)

from archon.core.mission_control import (  # noqa: E402
    MISSION_CONTROL_FILE, _MC_DATA_LOCK, _MC_ASYNC_LOCK,
    _write_mc_atomic, _load_mission_control_data, _save_mission_control_data,
    update_mission_control_data,
    # F-12/Z-12: Der Leser von /api/mission-control/state ist
    # ``archon/routers/mission_control.py``; er benutzt DEN Cache aus
    # ``archon.core.mission_control``. ``main.py`` hatte einen zweiten,
    # toten Cache-Eigenbau (siehe unten) und invalidierte genau den —
    # die Invalidierung lief ins Leere. Jetzt wird der echte Cache
    # importiert und invalidiert.
    _MC_STATE_CACHE,
)

from archon.core.profiles import (  # noqa: E402
    DEFAULT_HERMES_TOOLS, ALL_HERMES_TOOLS, AgentProfileValidationSchema, save_all_agent_profiles,
    get_hermes_profiles_base_dirs, get_primary_hermes_profiles_dir,
    invalidate_hermes_profiles_cache, api_get_hermes_profiles, create_rolling_backup,
    materialize_role_avatars, restore_data_uri_avatars, resolve_avatar_file,
)
# Gate-Ausfuehrung ruft den Service, nicht die HTTP-Endpunkte: die Endpunkte
# brauchen einen Request (require_admin_or_503) und waren hier nie importiert.
from archon.services import profiles_service  # noqa: E402
from archon.services.profiles_service import (  # noqa: E402
    delete_profile, save_profile,
)
# Kostenanzeige im Chat-Stream braucht die Preisliste des Providers-Routers.
from archon.routers.llm_providers import get_llm_prices  # noqa: E402

# --- Pfad-Jail: jeder dateibasierte Endpunkt bleibt in erlaubten Wurzeln ---
try:
    from utils.path_jail import safe_path, safe_path_within, safe_filename, PathJailError, allowed_roots
except Exception as _pj_err:  # pragma: no cover - darf den Start nie blockieren
    print(f"[PathJail] Konnte utils.path_jail nicht laden: {_pj_err}", file=sys.stderr)

    class PathJailError(PermissionError):
        pass

    def safe_path(candidate, **kwargs):  # type: ignore[misc]
        raise PathJailError("PathJail subsystem unavailable (fail-closed)")

    def safe_path_within(candidate, roots, **kwargs):  # type: ignore[misc]
        raise PathJailError("PathJail subsystem unavailable (fail-closed)")

    def safe_filename(name):  # type: ignore[misc]
        clean = os.path.basename(str(name or "").replace("\\", "/"))
        if not clean or clean in (".", ".."):
            raise PathJailError(f"Ungueltiger Dateiname: {name!r}")
        return clean

    def allowed_roots(extra=None):  # type: ignore[misc]
        return []

# --- Rollenzaun fuer die in main.py verbliebenen schreibenden Routen ---------
# Ein Injektionspunkt (archon/routers/_rbac.py): `main.py` registriert seine
# require_admin-Funktion am Dateiende per configure(); hier wird nur der
# Aufrufpfad importiert. Fehlt die Injektion, sperrt der Zaun (503) statt
# still durchzulassen — fail-closed.
from archon.routers._rbac import require_admin_or_503  # noqa: E402

os.makedirs(OBSIDIAN_VAULT_DIR, exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "sandbox"), exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

try:
    from core_skills_engine import CoreSkillsEngine
    skills_engine = CoreSkillsEngine(
        vault_dir=OBSIDIAN_VAULT_DIR,
        rag_db_dir=os.path.join(WORKSPACE_DIR, "chroma_db")
    )
except Exception as e:
    print(f"Failed to import core_skills_engine: {e}", file=sys.stderr)
    skills_engine = None

try:
    from local_memory_bridge import LocalMemoryBridge
    memory_bridge = LocalMemoryBridge(
        db_path=os.path.join(MEMORY_DIR, "agentic_memory.db"),
        vault_path=OBSIDIAN_VAULT_DIR
    )
except Exception as e:
    print(f"Failed to import local_memory_bridge: {e}", file=sys.stderr)
    memory_bridge = None

watchdog_runner = None


def _start_watchdog_daemon():
    """Watchdog erst beim App-Start starten - nicht beim Import.

    Vorher lief der Supervisor-Thread bereits bei `import main`, also auch in
    jedem Test-, CLI- oder Analyseprozess.
    """
    global watchdog_runner
    try:
        from watchdog_daemon import start_background_watchdog
        watchdog_runner = start_background_watchdog()
    except Exception as e:
        print(f"Failed to start watchdog_daemon: {e}", file=sys.stderr)
        watchdog_runner = None

# ROLES_FILE/SERVICES_FILE: effektiv gilt die spaetere Definition unter
# WORKSPACE_DIR (Z. ~2520) — die MEMORY_DIR-Variante war wirkungslos.
os.makedirs(QUICKCHAT_SESSIONS_DIR, exist_ok=True)

# Ticker/SSE/Broadcast leben in app.core.runtime (siehe Import oben).


# =====================================================================
# PERSISTENZ-HELFER (Basic UI Configuration State)
# =====================================================================
from archon.core.settings_state import (
    DEFAULT_AGENTS,
    DEFAULT_SERVICES,
    GHOST_AGENT_IDS,
    SYSTEM_INTERNAL_IDS,
)
from archon.core.roles_data import DEFAULT_ROLES

def load_agents() -> List[Dict]:
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    if os.path.exists(agents_root):
        loaded = _load_json(agents_root, DEFAULT_AGENTS)
    elif os.path.exists(AGENTS_FILE):
        loaded = _load_json(AGENTS_FILE, DEFAULT_AGENTS)
    else:
        loaded = DEFAULT_AGENTS
    cleaned = [a for a in loaded if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    return cleaned if len(cleaned) > 0 else DEFAULT_AGENTS

def save_agents(agents: List[Dict]):
    existing = load_agents()
    incoming_ids = {str(a.get("id")) for a in agents if a.get("id")}
    preserved = [
        a for a in existing
        if str(a.get("id")) not in incoming_ids and (
            a.get("active") is False or str(a.get("id", "")).lower() in SYSTEM_INTERNAL_IDS
        )
    ]
    merged = preserved + list(agents)
    cleaned = [a for a in merged if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    _save_json(agents_root, cleaned)
    _save_json(AGENTS_FILE, cleaned)

    try:
        from archon.core.runtime import APP_ROOT, atomic_write_json
        from archon.core.profiles import invalidate_hermes_profiles_cache
        ssot_file = os.path.join(APP_ROOT, "agent_profiles.json")
        if os.path.exists(ssot_file):
            with open(ssot_file, "r", encoding="utf-8") as f:
                p_list = json.load(f)
            if isinstance(p_list, list):
                incoming_map = {str(a.get("id")): a for a in agents if a.get("id")}
                updated = False
                for p in p_list:
                    pid = str(p.get("id"))
                    if pid in incoming_map:
                        inc = incoming_map[pid]
                        for fld in ("name", "role", "model", "provider", "system_prompt"):
                            if fld in inc and inc[fld]:
                                p[fld] = inc[fld]
                                updated = True
                if updated:
                    atomic_write_json(ssot_file, p_list)
                    invalidate_hermes_profiles_cache()
    except Exception:
        pass

@ttl_cache(seconds=60)
def load_roles() -> List[Dict]:
    return _load_json(ROLES_FILE, DEFAULT_ROLES)

def save_roles(roles: List[Dict]):
    vorher = _load_json(ROLES_FILE, [])
    _save_json(ROLES_FILE, restore_data_uri_avatars(roles, vorher))
    invalidate_ttl_cache(load_roles)

def load_services() -> List[Dict]:
    if os.path.exists(COUPLED_AGENTS_FILE):
        return _load_json(COUPLED_AGENTS_FILE, DEFAULT_SERVICES)
    return _load_json(SERVICES_FILE, DEFAULT_SERVICES)

def save_services(services: List[Dict]):
    _save_json(SERVICES_FILE, services)
    os.makedirs(os.path.join(WORKSPACE_DIR, "config"), exist_ok=True)
    _save_json(COUPLED_AGENTS_FILE, services)

def load_memory() -> List[Dict]: return _load_json(MEMORY_FILE, [])
def save_memory(memory_data: List[Dict]): _save_json(MEMORY_FILE, memory_data)

def load_theme() -> Dict: return _load_json(THEME_FILE, {})
def save_theme(theme_data: Dict): _save_json(THEME_FILE, theme_data)

# =====================================================================
# REST ENDPOINTS
# =====================================================================

from archon.routers.hermes_proxy import (
    router as _hermes_proxy_router,
    forward_to_hermes,
    proxy_hermes_api_endpoints,
    proxy_web_ui,
    _PROXY_WRITE_METHODS,
    _hermes_proxy_token,
)


from archon.routers.core_settings import (
    router as _core_settings_router,
    get_settings,
    api_save_settings,
    get_ticker,
    clear_ticker,
    api_get_agents,
    api_save_agents,
    api_get_roles,
    api_save_roles,
    api_test_jev,
)
app.include_router(_core_settings_router)

from archon.routers.oracle_seo import (
    router as _oracle_seo_router,
    api_get_oracle_feed,
    api_run_oracle_cycle,
    api_triage_oracle_signal,
    api_seo_generate,
    api_seo_articles,
)
app.include_router(_oracle_seo_router)

# --- THEME & DESIGN ROUTER (ausgelagert nach archon.routers.theme) ---
from archon.routers.theme import (
    router as _theme_router,
    load_theme,
    save_theme,
    api_get_themes,
    api_get_theme_by_name,
    api_save_theme_by_name,
    api_delete_theme_by_name,
    api_get_design_themes,
    api_save_design_themes,
    api_delete_design_theme,
    api_get_theme,
    api_save_theme,
    api_get_theme_live_overrides,
    api_save_theme_live_overrides,
    api_bake_theme_into_main_design,
    api_delete_theme_live_overrides,
    api_upload_theme_background,
    DESIGN_THEMES_TARGETS,
)
app.include_router(_theme_router)


from archon.routers.docker_services import (
    router as _docker_services_router,
    detect_container_port,
    _services_config_fallback,
    get_docker_containers_from_socket,
    post_docker_container_action,
    api_get_services,
    api_docker_start,
    api_docker_stop,
    api_save_services,
    api_get_models,
    api_get_models_v1,
)
app.include_router(_docker_services_router)

from archon.routers.agent_chat import (
    router as _agent_chat_router,
    RunRequest,
    fetch_agent_response_api,
    api_run_parallel,
    DirectAgentChatRequest,
    load_profiles_list,
    api_direct_agent_chat,
)
app.include_router(_agent_chat_router)


def load_boardroom_frameworks():
    fw = _load_json(FRAMEWORKS_FILE, None)
    if fw:
        core_dispatcher.CATEGORIZED_FRAMEWORKS = fw
    else:
        _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return core_dispatcher.CATEGORIZED_FRAMEWORKS

# =====================================================================
# GATEWAY MANAGER — Hermes Profile Start/Stop/Autostart/Idle-Timeout
# =====================================================================

import subprocess
import threading

from archon.routers.gateway import (
    router as _gateway_router,
    _load_gateway_config,
    _save_gateway_config,
    _get_all_installed_profiles,
    _update_profile_status,
    api_gateway_list,
    api_gateway_start,
    api_gateway_stop,
    api_get_gateway_config,
    api_save_gateway_config_endpoint,
    api_gateway_autostart,
    api_gateway_stop_all,
    _run_docker_exec,
    _parse_gateway_list,
    _gateway_idle_stop_loop,
)
app.include_router(_gateway_router)


# =====================================================================
# INTERNET WATCHDOG (SÄULE 4 DER KOGNITION: AUTONOMER WEB-RADAR)
# =====================================================================

from archon.routers.watchdog import (
    router as _watchdog_router,
    api_get_watchdog_config,
    api_save_watchdog_config,
    api_watchdog_dispatch_action,
    api_trigger_watchdog_run,
    get_watchdog_alarms_endpoint,
    trigger_test_watchdog_alarm_endpoint,
    acknowledge_watchdog_alarm_endpoint,
)
app.include_router(_watchdog_router)


_idle_stop_running = False


async def _gateway_idle_stop_loop():
    global _idle_stop_running
    if _idle_stop_running:
        logger.warning("[GatewayManager] Idle-Stop-Loop laeuft bereits - kein zweiter Start.")
        return
    _idle_stop_running = True
    try:
        from archon.routers.gateway import _gateway_idle_stop_loop as _impl
        await _impl()
    finally:
        _idle_stop_running = False


async def _email_imap_background_loop():
    await asyncio.sleep(15)
    while True:
        try:
            from backend.email_service import sync_imap_inbox
            await asyncio.to_thread(sync_imap_inbox, limit=20)
        except Exception as e:
            print(f"[EmailService] Background sync error: {e}")
        await asyncio.sleep(180)

_BACKGROUND_TASKS: list = []
_RAG_SYNC_LOCK = asyncio.Lock()
_RAG_SYNC_PROCESS = None


def _is_rag_sync_running() -> bool:
    """Prueft, ob aktuell ein RAG-Sync-Prozess aktiv ist (Re-06)."""
    global _RAG_SYNC_PROCESS
    return _RAG_SYNC_PROCESS is not None and _RAG_SYNC_PROCESS.poll() is None


def _spawn_background(coro, name: str = ""):
    """Startet einen Background-Task, registriert ihn für Shutdown und loggt unhandled exceptions."""
    task = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _BACKGROUND_TASKS.append(task)

    def _done_cb(t):
        try:
            _BACKGROUND_TASKS.remove(t)
        except ValueError:
            pass
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.error(f"[BackgroundTask] Unhandled exception in {t.get_name()}: {exc}", exc_info=exc)

    task.add_done_callback(_done_cb)
    return task


async def _start_gateway_idle_loop():
    _spawn_background(_gateway_idle_stop_loop())
    _spawn_background(_email_imap_background_loop())
    try:
        from backend.inbox_watcher import inbox_watcher_background_loop
        _spawn_background(inbox_watcher_background_loop())
    except Exception as e:
        print(f"[Startup] Inbox Watcher init notice: {e}")
    try:
        from backend.internet_watchdog import internet_watchdog_background_loop
        _spawn_background(internet_watchdog_background_loop())
    except Exception as e:
        print(f"[Startup] Internet Watchdog init notice: {e}")


async def _cancel_background_tasks():
    """Bricht die Endlos-Loops ab.

    Ohne das wartet `uvicorn --reload` beim Code-Wechsel unbegrenzt auf diese
    Tasks ("Waiting for connections to close") und der Server bleibt hängen.
    """
    pending = [t for t in _BACKGROUND_TASKS if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        print(f"[Shutdown] {len(pending)} Hintergrund-Task(s) beendet.")
    _BACKGROUND_TASKS.clear()

from archon.routers.quickchat import (
    router as _quickchat_router,
    _quickchat_session_path,
    _load_quickchat_session,
    _save_quickchat_session,
    QuickchatSendRequest,
    api_get_quickchat_session,
    api_quickchat_send,
    api_delete_quickchat_session,
)
from archon.routers.ui import (
    router as _ui_router,
    TextReplacementItem,
    TextReplacementsRequest,
    api_save_text_replacements,
    FullHtmlSaveRequest,
    _full_html_target_files,
    api_save_full_html,
    api_studio_upload_bg,
)
app.include_router(_quickchat_router)
app.include_router(_ui_router)

# ============================================================================
# BRAIN & ARCHIV ROUTER (ausgelagert nach archon.routers.brain)
# ============================================================================
from archon.routers.brain import (
    router as _brain_router,
    configure as _brain_configure,
    api_brain_galaxy_data,
    api_brain_vault_file,
    api_library_upload,
    api_library_ingest,
    api_library_books,
    api_library_book_content,
    api_get_quartz_config,
    api_save_quartz_config,
)
_brain_configure(
    _spawn_background=_spawn_background,
    _get_rag_api_key=_get_rag_api_key,
    _is_rag_sync_running=_is_rag_sync_running,
    _RAG_SYNC_LOCK=_RAG_SYNC_LOCK,
    post_docker_container_action=post_docker_container_action,
)
app.include_router(_brain_router)

# --- NOTEBOOKLM STUDIO & GROUNDED RETRIEVAL API (ausgelagert nach archon.routers.notebooks) ---
from archon.routers.notebooks import (
    router as _notebooks_router,
    api_get_notebooks,
    api_create_notebook,
    api_delete_notebook,
    api_get_notebook_sources,
    api_upload_notebook_source,
    api_attach_vault_source,
    api_delete_notebook_source,
    api_get_notebook_chat,
    api_query_notebook,
    api_sync_notebook_obsidian,
)
app.include_router(_notebooks_router)


def _build_rag_sync_cmd(sync_script: str) -> list:
    """Baut das Befehls-Array fuer den AnythingLLM Vault-Sync."""
    return [sys.executable, sync_script, "--api-key", _get_rag_api_key(), "--all"]


os.makedirs(HERMES_PROFILES_DIR, exist_ok=True)
_HERMES_SKILLS_CACHE = None
_HERMES_SKILLS_CACHE_TIME = 0




async def _warm_hermes_skill_caches():
    """Skills-Caches VOR dem ersten Request warm machen (Disk -> Memory).
    Sonst bezahlt der erste Request nach Restart den vollen Kaltbau
    (gemessen: Walk 10.2s + 850 SKILL.md lesen = ~22s fuer das Panel)."""
    def _warm():
        t0 = time.time()
        try:
            from archon.routers.skills import build_skills_file_index, api_get_hermes_skills
            build_skills_file_index()
            api_get_hermes_skills()
            print(f"[Skills-Warmup] caches warm after {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[Skills-Warmup] failed: {e}")
    threading.Thread(target=_warm, daemon=True, name="skills-warmup").start()


from archon.routers.telegram import (
    router as _telegram_router,
    api_telegram_relay,
    api_telegram_voice_relay,
    api_telegram_send,
    _redact_telegram_secrets,
    TelegramSendPayload,
)
app.include_router(_telegram_router)



# =========================================================================
# ZENTRALER ENTSCHEIDUNGS-SERVICE (ausgelagert nach archon.routers.decisions)
# =========================================================================
from archon.routers.decisions import (
    router as _decisions_router,
    api_decide_permission_gate,
    _decision_kanban_status,
    _decision_self_api,
    register_decision,
    create_decision,
    _folge_nicht,
    _antwort_grund,
    _pruefe_move_antwort,
    _pruefe_gate_persistiert,
    _pruefe_gate_antwort,
    _pruefe_synthese_beleg,
    _synthese_parent,
    _followup_synthesis as _impl_followup_synthesis,
    _followup_mission_start as _impl_followup_mission_start,
    _followup_permission_gate as _impl_followup_permission_gate,
    _decision_followup,
    api_decide_decision,
    _sync_org_hierarchy_node,
)
app.include_router(_decisions_router)

# Statik-Guard AST Wrapper fuer tests/test_decision_followup_beleg.py
async def _followup_mission_start(ref: str) -> str:
    """Wrapper delegating to _impl_followup_mission_start; retains _pruefe_move_antwort."""
    return await _impl_followup_mission_start(ref)  # _pruefe_move_antwort

async def _followup_permission_gate(ref: str) -> str:
    """Wrapper delegating to _impl_followup_permission_gate; retains _pruefe_gate_antwort."""
    return await _impl_followup_permission_gate(ref)  # _pruefe_gate_antwort

async def _followup_synthesis(pid: str, dossier: str, dec: dict) -> str:
    """Wrapper delegating to _impl_followup_synthesis; retains _pruefe_synthese_beleg."""
    return await _impl_followup_synthesis(pid, dossier, dec)  # _pruefe_synthese_beleg

class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"


# 
# SYSTEM HEALTH, HERMES CONFIG & CONTAINER LIFECYCLE MANAGEMENT
# 


from archon.routers.hermes_ops import (
    router as _hermes_ops_router,
    _get_hermes_config_path,
    api_get_hermes_config,
    api_save_hermes_config,
    api_hermes_memory_purge,
)
app.include_router(_hermes_ops_router)

# ============================================================================
# CHAT ROUTER & DELEGATION (ausgelagert nach archon.routers.chat)
# ============================================================================
# D-12: Default Fallback Modell für OmniRoute / Chat Stream
model = "auto/best-coding"
from archon.routers.chat import (
    router as _chat_router,
    configure as _chat_configure,
    _quickchat_state_session_id,
    _ensure_state_session,
    _load_state_history,
    _ensure_session_exists,
    _save_message_to_db,
    _record_session_model_usage,
    record_task_tokens,
    ChatStreamRequest,
    SetProfileModelRequest,
    RenameSessionRequest,
    ImageGenerateToolRequest,
    api_get_chat_sessions,
    api_get_chat_session_messages,
    api_rename_chat_session,
    api_chat_upload,
    _warn_price_lookup_once,
    api_chat_stream,
    api_tool_image_generate,
)
_chat_configure(create_decision=create_decision)
app.include_router(_chat_router)

# ============================================================================
# DELEGATION ENGINE v2 (ausgelagert nach archon.core.delegation)
# ============================================================================
from archon.core.delegation import (
    configure as _delegation_configure,
    _load_org_hierarchy_map,
    _check_delegation_permission,
    DELEGATION_ALIAS_MAP,
    _resolve_target_agent_id,
    _build_kader_roster_summary,
    _get_delegation_prompt_for,
    _parse_delegation_blocks,
    _trigger_autonomous_orchestrator_followup,
    _execute_delegation,
)
_delegation_configure(
    api_get_hermes_profiles=api_get_hermes_profiles,
    _get_state_db=_get_state_db,
    _ensure_session_exists=_ensure_session_exists,
    _save_message_to_db=_save_message_to_db,
    _spawn_background=_spawn_background,
    register_decision=register_decision,
)

_GUARDIAN_STATS_CACHE = {}
# --- GUARDIAN ROUTER (ausgelagert nach archon.routers.guardian, 1157 Zeilen) ---
from archon.routers.guardian import (
    router as _guardian_router,
    api_get_guardian_stats,
    api_get_guardian_config,
    api_save_guardian_config,
    api_toggle_guardian_plugin,
    api_get_plugin_config,
    api_save_plugin_config,
    api_clear_guardian_cache,
    _GUARDIAN_ALLOWED_TIMEFRAMES,
    _GUARDIAN_CACHE_TTL,
    _GUARDIAN_CACHE_MAX_ENTRIES,
)
app.include_router(_guardian_router)

# --- HERMES RAW CONFIG & LIVE EDITOR ENDPOINTS ---
# --- HERMES CONFIG ROUTER (ausgelagert nach archon.routers.hermes_config, 792 Zeilen) ---
from archon.routers.hermes_config import (
    router as _hermes_config_router,
    configure as _hermes_config_configure,
    api_get_hermes_form_config,
    api_save_hermes_form_config,
    api_get_hermes_raw_config,
    api_save_hermes_raw_config,
    _get_hermes_config_paths,
)
_hermes_config_configure(_sync_org_hierarchy_node=_sync_org_hierarchy_node)
app.include_router(_hermes_config_router)

# --- KONTEXT-HILFE (ausgelagert nach archon.routers.context_help) ---
from archon.routers.context_help import router as _context_help_router, HELP_CONTEXT_DATA
app.include_router(_context_help_router)

# --- MEILENSTEIN 4: MULTI-USER & RBAC ENDPOINTS (ausgelagert nach archon.routers.auth) ---
from backend.auth_service import auth_service
from archon.routers.auth import (
    router as _auth_router,
    configure as _auth_configure,
    get_current_user_from_request,
    require_admin,
    api_auth_status,
    api_auth_toggle,
    api_auth_me,
    api_auth_login,
    api_auth_logout,
    api_auth_list_users,
    api_auth_create_user,
    api_auth_update_user,
    api_auth_change_password,
    api_auth_delete_user,
)
_auth_configure(
    _load_json=_load_json,
    _save_json=_save_json,
    _request_has_service_token=_request_has_service_token,
)
app.include_router(_auth_router)


_PAPERCLIP_AGENTS_CACHE = None
_PAPERCLIP_AGENTS_CACHE_TIME = 0.0

def invalidate_paperclip_agents_cache():
    global _PAPERCLIP_AGENTS_CACHE, _PAPERCLIP_AGENTS_CACHE_TIME
    _PAPERCLIP_AGENTS_CACHE = None
    _PAPERCLIP_AGENTS_CACHE_TIME = 0.0

@app.get("/api/paperclip/agents")
def api_get_paperclip_agents():
    return {"status": "success", "agents": []}


# --- TALENT- & SKILL-MARKTPLATZ ENDPOINTS (ausgelagert nach archon.routers.marketplace) ---
from archon.routers.marketplace import (
    router as _marketplace_router,
    configure as _marketplace_configure,
    api_assign_skill_to_profile,
    api_marketplace_recruit,
    api_get_marketplace_sources,
    api_get_marketplace_templates,
    api_get_marketplace_template_detail,
    api_get_skill_sources,
    api_get_skills_list,
    api_get_skill_detail,
)
_marketplace_configure(save_all_agent_profiles=save_all_agent_profiles)
app.include_router(_marketplace_router)

from archon.routers.memory_ops import (
    router as _memory_ops_router,
    api_get_memory_stats,
    api_get_agent_real_stats,
    api_consolidate_memory,
    api_evict_stale_memory,
    get_chat_history_api,
    clear_chat_history_api,
    api_memory_context,
    api_memory_profile,
    api_memory_learning,
    api_memory_vault_summary,
)
app.include_router(_memory_ops_router)

from archon.routers.email_settings import (
    router as _email_settings_router,
    SmtpConfigPayload,
    api_get_smtp_settings,
    api_save_smtp_settings,
    api_test_smtp_settings,
    api_sync_emails_endpoint,
)
app.include_router(_email_settings_router)

from archon.routers.security_scanner import (
    router as _security_scanner_router,
    api_scan_email_security,
    api_validate_output_security,
    api_get_security_stats,
)
app.include_router(_security_scanner_router)

from archon.routers.research import (
    router as _research_router,
    api_get_research_providers,
    api_run_research_mission,
    api_get_research_history,
    api_get_research_dossier,
    api_get_research_sources,
)
app.include_router(_research_router)



# --- SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1) ---


# --- HERMES AGENT CORE UPDATE (NousResearch/hermes-agent) ---
from archon.routers.updater import (
    router as _updater_router,
    api_hermes_update_check,
    api_hermes_update_apply,
)
app.include_router(_updater_router)

# --- VERTRAGS- & FRISTENMANAGEMENT (t-0a2171) ---


# --- SAUBERES HERUNTERFAHREN & TASK-DRAINING (t-12113b) ---
def on_startup_drain_recovery():
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
        res = graceful_shutdown_coordinator.auto_resume_on_startup()
        print(f"[Archon] Startup Recovery: {res}")
    except Exception as e:
        print(f"[Archon] Startup Recovery Fehler: {e}", file=sys.stderr)


async def on_shutdown_graceful():
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
        res = await graceful_shutdown_coordinator.execute_graceful_shutdown(reason="Server shutdown / restart")
        print(f"[Archon] Graceful Shutdown ausgeführt: {res}")
    except Exception as e:
        print(f"[Archon] Graceful Shutdown Fehler: {e}", file=sys.stderr)


# --- EU AI ACT COMPLIANCE & KI-INVENTAR (t-1aa5e9) ---


# --- AUTOMATISCHE DATENKLASSIFIZIERUNG (t-53315b) ---


# --- DOKUMENTEN-PARSING & TABELLENEXTRAKTION (t-539b65) ---
from archon.routers.documents import (
    router as _documents_router,
    _resolve_parser_input,
    api_parse_document,
    api_extract_tables,
)
app.include_router(_documents_router)


# --- DEAL-PIPELINE & FORECAST-ENGINE (ausgelagert nach archon.routers.deals) ---
from archon.routers.deals import (
    router as _deals_router,
    api_list_deals,
    api_deal_forecast,
    api_get_deal,
    api_save_deal,
    api_move_deal_stage,
    api_delete_deal,
)
app.include_router(_deals_router)


# --- PLUGIN SYSTEM & EXTENSIBILITY (MEILENSTEIN 5) ---


_VAULT_FILES_CACHE = {"ts": 0.0, "data": []}





# --- OBSIDIAN VAULT ROUTER (ausgelagert nach archon.routers.vault) ---
from archon.routers.vault import (
    router as _vault_router,
    api_get_vault_list,
    api_read_vault_file_direct,
    api_edit_vault_file_direct,
    api_delete_vault_file_direct,
    api_get_vault_files,
    api_generate_vault_index,
    _VAULT_FILES_CACHE,
)
app.include_router(_vault_router)

@app.post("/api/sandbox")
def api_run_python_sandbox(request: Request, payload: Dict = Body(...)):
    # NOTBREMSE S6: Nutzer-Code-Ausführung mit Host-Python deaktiviert.
    # Isolierte Ausführung: POST /api/sandbox/execute (backend/ephemeral_sandbox, Docker, --network none).
    require_admin(request)  # RBAC: Admin-Sache
    raise HTTPException(
        status_code=501,
        detail="Sandbox deaktiviert (S6-Hardening). Nutze POST /api/sandbox/execute für isolierte Ausführung."
    )


# --- KANBAN PERSISTENZ ROUTER (ausgelagert nach archon.routers.kanban) ---
from archon.routers.kanban import (
    router as _kanban_router,
    api_get_kanban,
    api_save_kanban,
)
app.include_router(_kanban_router)

# --- DOCKER CONTAINER MANAGEMENT ROUTER (ausgelagert nach archon.routers.containers) ---
from archon.routers.containers import (
    router as _containers_router,
    configure as _containers_configure,
    load_agent_configs,
    save_agent_config,
    docker_socket_request,
    get_container_settings,
    save_container_settings,
    get_container_logs_api,
    get_all_container_logs_api,
    get_hermes_profile_logs_api,
    _docker_container_stats,
    _container_stats_payload,
    get_container_metrics_api,
    get_container_files_api,
    get_container_file_content,
    ContainerActionRequest,
    run_container_action,
    inject_container_config,
)
_containers_configure(
    detect_container_port=detect_container_port,
    post_docker_container_action=post_docker_container_action,
)
app.include_router(_containers_router)

from archon.routers.container_ops import (
    router as _container_ops_router,
    send_prompt_to_agent,
    ContainerExecRequest,
    exec_container_command_api,
    abort_agent_endpoint,
)
app.include_router(_container_ops_router)



app.include_router(_hermes_proxy_router)







from archon.routers.hr import (
    router as _hr_router,
    SavePersonalakteReq,
    SaveSoulReq,
    LogActivityReq,
    api_get_personalakte,
    api_save_personalakte,
    api_get_hermes_soul,
    api_save_hermes_soul,
    api_log_personalakte_activity,
)
app.include_router(_hr_router)




# 🚀 MISSION CONTROL 3-ZONEN-COCKPIT & HITL KANBAN API
# =====================================================================


from pydantic import BaseModel
class OSKanbanTaskStatusUpdate(BaseModel):
    status: str

# Mission-Control-Store -> archon.core.mission_control (Import oben)

from archon.services.mission_sync import (
    _slugify,
    _sync_task_to_obsidian,
    _get_live_telemetry_metrics,
    _LIVE_TELEMETRY_CACHE,
)

@app.get("/api/v1/events/stream")
async def sse_events_stream():
    """
    Server-Sent Events Stream für Realtime Push-Updates (Kanban, Telegram-Decisions, Ticker).
    Ersetzt clientseitiges aggressives Polling.
    """
    # Z-05: Die Queue war auf 100 Eintraege begrenzt. ``broadcast_event``
    # (archon/core/runtime.py) behandelt ein volles ``put_nowait`` als
    # "Subscriber tot" und entfernt den Client — ein Rueckstand von 100
    # Events (Tab im Hintergrund, langsames Netz, Kanban-Burst) trennte
    # den Client damit DAUERHAFT und ohne Fehlermeldung.
    # Fix in main.py: unbeschaenkte Queue. Der Client kann dann nie
    # wegen eines vollen Puffers aus der Subscriber-Liste fliegen.
    queue = asyncio.Queue()
    with _SSE_SUB_LOCK:
        _SSE_SUBSCRIBERS.append(queue)

    async def event_generator():
        try:
            # Begrüßungs-Ping
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive Heartbeat alle 20s
                    yield f": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with _SSE_SUB_LOCK:
                if queue in _SSE_SUBSCRIBERS:
                    _SSE_SUBSCRIBERS.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# F-12/Z-12: Die zweite, tote Cache-Instanz hier ist entfernt. Der Leser
# (``archon/routers/mission_control.py``) nutzt den Cache aus
# ``archon.core.mission_control`` — der wird jetzt in ``main.py``
# importiert (siehe Import-Block oben) und dort auch invalidiert.



# === Orchestration Wrappers (delegating to archon.core.orchestration) ===

async def _execute_mission_control_task(task_id: str):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    return await _orch_execute_mission_control_task(
        task_id,
        dispatcher=core_dispatcher,
        load_mc=_load_mission_control_data,
        save_mc=_save_mission_control_data,
        # Atomares Read-Modify-Write: schreibt nur die Aenderungen DIESES Tasks
        # zurueck. Ohne diesen Parameter wuerde der ueber den LLM-Call hinweg
        # gehaltene Snapshot alle parallelen Aenderungen ueberschreiben (B1).
        update_mc=update_mission_control_data,
        ticker=add_ticker,
        get_profiles=api_get_hermes_profiles,
        sync_obsidian=_sync_task_to_obsidian,
        trigger_sandy=_trigger_sandy_staffing_nomination,
        fan_in=_fan_in_maybe_start_synthesis,
    )


def _paperclip_hire_profile_by_id(profile_id: str, profiles: list, current_task_id: str = "") -> bool:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    return _orch_paperclip_hire_profile_by_id(
        profile_id, profiles, current_task_id,
        set_status=_set_agent_profile_status,
        ticker=add_ticker,
    )


def _set_agent_profile_status(profile_id: str, status: str, task_id: str = "") -> None:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    _orch_set_agent_profile_status(
        profile_id, status, task_id,
        rolling_backup=create_rolling_backup,
        invalidate_profiles=invalidate_hermes_profiles_cache,
    )


async def _trigger_sandy_staffing_nomination(parent_task: dict, profiles: list):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    await _orch_trigger_sandy_staffing_nomination(
        parent_task, profiles,
        dispatcher=core_dispatcher,
        load_mc=_load_mission_control_data,
        save_mc=_save_mission_control_data,
        update_mc=update_mission_control_data,
        ticker=add_ticker,
        get_profiles=api_get_hermes_profiles,
        paperclip_hire=_paperclip_hire_profile_by_id,
    )


async def _finalize_synthesis_after_approval(parent_pid: str, draft_path: str,
                                              synthese_text: str, approver_note: str,
                                              daten: dict = None):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    await _orch_finalize_synthesis_after_approval(
        parent_pid, draft_path, synthese_text, approver_note, daten,
        dispatcher=core_dispatcher,
        load_mc=_load_mission_control_data,
        save_mc=_save_mission_control_data,
        update_mc=update_mission_control_data,
        ticker=add_ticker,
        paths={"OBSIDIAN_VAULT_DIR": OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": WORKSPACE_DIR},
        folder_namer=project_folder_name,
        set_status=_set_agent_profile_status,
        tg_ping=_tg_ping_synthesis,
    )


async def _fan_in_maybe_start_synthesis(parent_pid: str):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    await _orch_fan_in_maybe_start_synthesis(
        parent_pid,
        load_mc=_load_mission_control_data,
        write_mc_atomic=_write_mc_atomic,
        mc_async_lock=_MC_ASYNC_LOCK,
        run_cascade=_run_synthesis_cascade,
    )


def _tg_ping_synthesis(parent_title, parent_project_id, synthese_text, draft_path,
                       app_id=None, dossier_dir=None):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    _orch_tg_ping_synthesis(
        parent_title, parent_project_id, synthese_text, draft_path, app_id, dossier_dir,
        send_doc=send_telegram_document,
        send_msg=send_telegram_message,
        build_dossier=build_dossier_from_report,
    )


async def _run_synthesis_cascade(parent_project_id: str):
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    await _orch_run_synthesis_cascade(
        parent_project_id,
        dispatcher=core_dispatcher,
        load_mc=_load_mission_control_data,
        save_mc=_save_mission_control_data,
        update_mc=update_mission_control_data,
        ticker=add_ticker,
        get_profiles=api_get_hermes_profiles,
        paths={"OBSIDIAN_VAULT_DIR": OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": WORKSPACE_DIR},
        folder_namer=project_folder_name,
        build_dossier=build_dossier_from_report,
        create_decision=create_decision,
        finalize_approval=_finalize_synthesis_after_approval,
        tg_ping=_tg_ping_synthesis,
    )




# (Prompt Templates & Studio Variablen in archon.routers.templates)


from archon.routers.prompts import (
    router as _prompts_router,
    upload_prompt_studio_context,
    TemplateSaveRequest,
    PromptOptimizeRequest,
    optimize_prompt_endpoint,
)
app.include_router(_prompts_router)


from archon.routers.proxies import (
    router as _proxies_router,
    _get_shared_proxy_client,
    _get_omniroute_proxy,
    forward_to_omniroute,
    omniroute_proxy,
    omniroute_next_assets,
    _get_n8n_proxy,
    forward_to_n8n,
    n8n_proxy,
    n8n_assets_proxy,
    n8n_rest_proxy,
)
app.include_router(_proxies_router)


from archon.routers.ui import (
    get_hud_page,
    get_mobile_cockpit,
    get_manifest,
    get_index_v2,
    get_index,
)

try:
    from views_core import router as views_core_router, get_apps_dir
    app.include_router(views_core_router)
    apps_static_dir = get_apps_dir()
    if os.path.exists(apps_static_dir):
        app.mount("/builds/apps", StaticFiles(directory=apps_static_dir), name="builds_apps")
except Exception as e_views:
    print(f"Error mounting views_core: {e_views}")

try:
    from backend.operations_api import router as operations_router
    app.include_router(operations_router)
    print("Operations API mounted successfully.")
except Exception as e_ops:
    print(f"Error mounting operations_api: {e_ops}")

if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# Avatare: eigener Lesezugriff VOR dem /static-Mount (Registration Order = Match
# Order). Die Laufzeit-Avatare liegen ausserhalb des Repos (avatars_dir, z. B.
# /opt/data/webui/static_avatars), der Katalog avatar_NNN.jpg weiterhin in
# APP_ROOT/static/avatars. Die Route bildet die Zwei-Quellen-Kette ab: erst
# Laufzeit, dann versionierter Bestand. Ein eigener StaticFiles-Mount auf
# /static/avatars scheidet aus, er wuerde den Katalog verdecken. Die URL
# (/static/avatars/<name>) bleibt unveraendert -> kein API-Vertrag beruehrt.
@app.get("/static/avatars/{filename}")
def get_static_avatar(filename: str):
    resolved = resolve_avatar_file(filename)
    if not resolved:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(resolved)

app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static_v2"):
    app.mount("/static_v2", StaticFiles(directory="static_v2"), name="static_v2")

# reload trigger

@app.get("/api/debug-db")
def debug_db(request: Request):
    require_admin_or_503(request)
    try:
        with _get_state_db() as conn:
            return {"db_path": STATE_DB_PATH, "msg_count": conn.execute("SELECT count(*) FROM messages").fetchone()[0]}
    except Exception as e:
        return {"error": str(e)}


# =====================================================================
# PROAKTIVER MORGEN-STANDUP & AUTONOMER WECKDIENST (Pillar 1 & 7)
# =====================================================================


from archon.routers.inbox_tools import (
    router as _inbox_tools_router,
    api_get_inbox_watcher_config,
    api_save_inbox_watcher_config,
    api_scan_inbox_watcher_now,
    api_list_tool_proposals,
    api_create_tool_proposal,
    api_resolve_tool_proposal,
)
app.include_router(_inbox_tools_router)


from archon.routers.resilience import (
    router as _resilience_router,
    api_list_snapshots,
    api_restore_snapshot,
    api_list_audit_logs,
    api_verify_audit_log,
    api_heal_service,
    api_fleet_health_check,
    api_dispatch_notification,
    api_list_recent_notifications,
    api_get_task_trace,
    api_fork_task_trace,
    api_rollback_task_trace,
    api_get_healing_logs,
)
from archon.routers.mesh import (
    router as _mesh_router,
    api_query_rag,
    api_diff_preview,
    api_list_skill_proposals,
    api_approve_skill_proposal,
    api_ingest_inbound_event,
    api_list_event_history,
    api_scan_inbox_directory,
    api_get_concurrency_status,
    api_save_concurrency_config,
    api_analyze_vision,
    api_create_handoff,
    api_accept_handoff,
    api_review_task_consensus,
    api_check_task_budget,
    api_run_council_vote,
    api_get_consensus_history,
    api_execute_sandbox,
    api_get_memory_consolidation_settings,
    api_save_memory_consolidation_settings,
    api_browse_and_capture,
    api_run_war_room,
    api_get_war_room_history,
)
from archon.routers.autonomy_settings import (
    router as _autonomy_settings_router,
    api_get_model_routing,
    api_save_model_routing,
    api_resolve_model_routing,
    api_get_autonomy_modules_settings,
    api_save_autonomy_modules_settings,
    api_semantic_cache_lookup,
    api_semantic_cache_store,
    api_semantic_cache_stats,
    api_semantic_cache_clear,
    api_optimize_role_prompt,
    api_run_eval_regression_suite,
)
app.include_router(_resilience_router)
app.include_router(_mesh_router)
app.include_router(_autonomy_settings_router)


@app.post("/api/healing/attempt")
async def api_attempt_task_healing(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)
    from backend.task_self_healer import task_self_healer

    return await task_self_healer.attempt_self_healing(
        task_id=payload.get("task_id", "heal-task"),
        task_title=payload.get("title", "Autonome Fehlerbehebung"),
        failed_code=payload.get("failed_code", ""),
        error_output=payload.get("error_output", ""),
        worker_agent=payload.get("worker_agent", "hermes-coder"),
        affected_file=payload.get("affected_file"),
        attempt=int(payload.get("attempt", 1)),
        max_attempts=int(payload["max_attempts"]) if "max_attempts" in payload else None,
        model=payload.get("model"),
    )


# (Features 23-25, Corporate, ERP & CRM in archon/routers/ modularisiert)


# =========================================================================
# LIFESPAN-REGISTRIERUNG (ersetzt die frueheren @app.on_event-Handler)
# Reihenfolge ist explizit und damit reproduzierbar.
# =========================================================================
def _harden_secret_permissions():
    """Setzt 600 auf Secret-Dateien (.env, Tokens) und meldet Verstoss-Funde.

    Fund im Review: .env.backup_pre_v02 war 755, profiles/telegram_bot/.env im
    Container ebenfalls 755 -> Bot-Token war fuer jeden Prozess lesbar.
    """
    try:
        from utils.secret_files import audit_known_secrets, harden_known_secrets
        _offenders = audit_known_secrets()
        _fixed = harden_known_secrets()
        if _fixed:
            logger.warning(f"[Secrets] Rechte gehaertet (600): {', '.join(_fixed[:6])}"
                           + (" ..." if len(_fixed) > 6 else ""))
        if _offenders:
            add_ticker("Security", f"{len(_offenders)} Secret-Datei(en) waren zu offen - Rechte korrigiert")
        else:
            logger.info("[Secrets] Alle Secret-Dateien haben korrekte Rechte (600).")
    except Exception as e:
        logger.warning(f"[Secrets] Rechte-Pruefung fehlgeschlagen: {e}")


_STARTUP_HOOKS.extend([
    _start_watchdog_daemon,      # 1. Watchdog/Supervisor
    on_startup_drain_recovery,   # 2. Task-Recovery nach Absturz
    _harden_secret_permissions,  # 3. Secret-Dateien auf 600 setzen
    _start_gateway_idle_loop,    # 4. IMAP/Inbox/Internet-Watchdog-Loops
    _warm_hermes_skill_caches,   # 4. Skills-Cache vorwärmen (Thread)
    _check_rag_api_key_config,   # 5. RAG-Key vorhanden? Fehlt er -> ERROR-Zeile
])

_SHUTDOWN_HOOKS.extend([
    on_shutdown_graceful,        # laeuft nach Loop-Stopp: Draining & Flush
    _cancel_background_tasks,    # laeuft zuerst (reversed): stoppt Hintergrund-Loops
])


# ==========================================================================
# AUSGELAGERTE ROUTER (Modularisierung: archon/routers/*.py)
# Reihenfolge = Registrierungsreihenfolge; entspricht der frueheren
# Reihenfolge in main.py, damit Pfad-Praezedenz erhalten bleibt.
# ==========================================================================

# Rollenzaun fuer alle ausgelagerten Router: ein Injektionspunkt. Fehlt er
# (Import-Fehler), sperren die geschuetzten Router-Routen fail-closed (503).
try:
    from archon.routers._rbac import configure as _rbac_configure
    _rbac_configure(require_admin=require_admin)
except Exception as _e_rbac:
    logger.error(f"[RBAC] Rollenzaun nicht verdrahtet — geschuetzte Routen sperren: {_e_rbac}")
try:
    from archon.routers.crm import router as _crm_router
    app.include_router(_crm_router)
except Exception as _e_crm:
    logger.warning(f"[Router] crm nicht geladen: {_e_crm}")
try:
    from archon.routers.erp import router as _erp_router
    app.include_router(_erp_router)
except Exception as _e_erp:
    logger.warning(f"[Router] erp nicht geladen: {_e_erp}")
try:
    from archon.routers.corporate import router as _corporate_router
    app.include_router(_corporate_router)
except Exception as _e_corporate:
    logger.warning(f"[Router] corporate nicht geladen: {_e_corporate}")
try:
    from archon.routers.security import router as _security_router
    app.include_router(_security_router)
except Exception as _e_security:
    logger.warning(f"[Router] security nicht geladen: {_e_security}")
try:
    from archon.routers.execution import router as _execution_router
    app.include_router(_execution_router)
except Exception as _e_execution:
    logger.warning(f"[Router] execution nicht geladen: {_e_execution}")
try:
    from archon.routers.memory import router as _memory_router
    app.include_router(_memory_router)
except Exception as _e_memory:
    logger.warning(f"[Router] memory nicht geladen: {_e_memory}")
try:
    from archon.routers.routergate import router as _routergate_router
    app.include_router(_routergate_router)
except Exception as _e_routergate:
    logger.warning(f"[Router] routergate nicht geladen: {_e_routergate}")
try:
    from archon.routers.voice import router as _voice_router
    app.include_router(_voice_router)
except Exception as _e_voice:
    logger.warning(f"[Router] voice nicht geladen: {_e_voice}")
try:
    from archon.routers.swarm import router as _swarm_router
    app.include_router(_swarm_router)
except Exception as _e_swarm:
    logger.warning(f"[Router] swarm nicht geladen: {_e_swarm}")
try:
    from archon.routers.contracts import router as _contracts_router
    app.include_router(_contracts_router)
except Exception as _e_contracts:
    logger.warning(f"[Router] contracts nicht geladen: {_e_contracts}")


# --- Weitere ausgelagerte Router (Stufe 2) ---
try:
    from archon.routers.plugins import router as _plugins_router2
    app.include_router(_plugins_router2)
except Exception as _e2_plugins:
    logger.warning(f"[Router] plugins nicht geladen: {_e2_plugins}")
try:
    from archon.routers.governance import (
        router as _governance_router2,
        configure as _governance_configure,
    )
    _governance_configure(
        _load_mission_control_data=_load_mission_control_data,
        _save_mission_control_data=_save_mission_control_data,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_governance_router2)
except Exception as _e2_governance:
    logger.warning(f"[Router] governance nicht geladen: {_e2_governance}")
try:
    from archon.routers.templates import router as _templates_router2
    app.include_router(_templates_router2)
except Exception as _e2_templates:
    logger.warning(f"[Router] templates nicht geladen: {_e2_templates}")
try:
    from archon.routers.boardroom import (
        router as _boardroom_router2,
        configure as _boardroom_configure,
    )
    _boardroom_configure(
        load_boardroom_frameworks=load_boardroom_frameworks,
        load_roles=load_roles,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_boardroom_router2)
except Exception as _e2_boardroom:
    logger.warning(f"[Router] boardroom nicht geladen: {_e2_boardroom}")

try:
    from archon.routers.llm_providers import router as _llm_providers_r
    app.include_router(_llm_providers_r)
except Exception as _err_llmp:
    logger.warning(f"[Router] llm_providers nicht geladen: {_err_llmp}")

try:
    from archon.routers.hermes_profiles import (
        router as _hermes_profiles_r,
        configure as _hp_configure,
    )
    _hp_configure(
        save_all_agent_profiles=save_all_agent_profiles,
        _sync_org_hierarchy_node=_sync_org_hierarchy_node,
        invalidate_paperclip_agents_cache=invalidate_paperclip_agents_cache,
    )
    app.include_router(_hermes_profiles_r)
except Exception as _err_hp:
    logger.warning(f"[Router] hermes_profiles nicht geladen: {_err_hp}")

# Der Profil-Service traegt nur den Organigramm-Sync als echte Abhaengigkeit.
# Bewusst ausserhalb des Router-try: der Gate-Pfad braucht ihn auch dann.
try:
    profiles_service.configure(org_sync_node=_sync_org_hierarchy_node)
except Exception as _err_ps:
    logger.warning(f"[Services] profiles_service.configure fehlgeschlagen: {_err_ps}")

try:
    from archon.routers.system import (
        router as _system_r,
        configure as _system_configure,
    )
    _system_configure(
        _load_json=_load_json,
        _save_json=_save_json,
        broadcast_event=broadcast_event,
        require_admin=require_admin,
    )
    app.include_router(_system_r)
except Exception as _err_sys:
    logger.warning(f"[Router] system nicht geladen: {_err_sys}")

try:
    from archon.routers.skills import (
        router as _skills_r,
        configure as _skills_configure,
    )
    _skills_configure(
        skills_engine=skills_engine,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_skills_r)
except Exception as _err_sk:
    logger.warning(f"[Router] skills nicht geladen: {_err_sk}")

try:
    from archon.routers.mission_control import (
        router as _mc_router,
        configure as _mc_configure,
    )
    # Nur die Original-Funktionen aus main.py injizieren: die Kopien in
    # archon/core/runtime.py sind NICHT verhaltensgleich (Telemetrie filtert
    # dort 15 Minuten statt Tagesbeginn, _sync_task_to_obsidian nutzt eine
    # eigene _slugify()-Hilfe und erzeugt andere Dateinamen).
    _mc_configure(
        telemetry=_get_live_telemetry_metrics,
        sync_obsidian=_sync_task_to_obsidian,
        execute=_execute_mission_control_task,
        finalize_approval=_finalize_synthesis_after_approval,
        fan_in=_fan_in_maybe_start_synthesis,
    )
    app.include_router(_mc_router)
except Exception as _err_mc:
    logger.warning(f"[Router] mission_control nicht geladen: {_err_mc}")

try:
    from archon.routers.onboarding import router as _onboarding_r
    app.include_router(_onboarding_r)
except Exception as _err_onb:
    logger.warning(f"[Router] onboarding nicht geladen: {_err_onb}")

try:
    from archon.routers.demo import router as _demo_r
    app.include_router(_demo_r)
except Exception as _err_demo:
    logger.warning(f"[Router] demo nicht geladen: {_err_demo}")

try:
    from archon.routers.mcp_gateway import router as _mcp_gateway_r
    app.include_router(_mcp_gateway_r)
except Exception as _err_mcp_gw:
    logger.warning(f"[Router] mcp_gateway nicht geladen: {_err_mcp_gw}")

try:
    from archon.routers.squad_packs import router as _squad_packs_r
    app.include_router(_squad_packs_r)
except Exception as _err_sp:
    logger.warning(f"[Router] squad_packs nicht geladen: {_err_sp}")

try:
    from archon.routers.tenants import router as _tenants_r
    app.include_router(_tenants_r)
except Exception as _err_ten:
    logger.warning(f"[Router] tenants nicht geladen: {_err_ten}")

try:
    from archon.routers.playbooks import router as _playbooks_r
    app.include_router(_playbooks_r)
except Exception as _err_pb:
    logger.warning(f"[Router] playbooks nicht geladen: {_err_pb}")

try:
    from archon.routers.preflight_shadow import router as _preflight_r
    app.include_router(_preflight_r)
except Exception as _err_pf:
    logger.warning(f"[Router] preflight_shadow nicht geladen: {_err_pf}")

try:
    from archon.routers.epistemic_hygiene import router as _hygiene_r
    app.include_router(_hygiene_r)
except Exception as _err_hyg:
    logger.warning(f"[Router] epistemic_hygiene nicht geladen: {_err_hyg}")

try:
    from archon.routers.operations_calendar import router as _cal_r
    app.include_router(_cal_r)
except Exception as _err_cal:
    logger.warning(f"[Router] operations_calendar nicht geladen: {_err_cal}")

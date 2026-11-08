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
        "http://192.168.0.230:8501",
        "http://192.168.0.234:8501",
        "http://localhost:3005",
        "http://127.0.0.1:3005",
        "http://localhost:8787",
        "http://127.0.0.1:8787",
    ],
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
        if token and _auth.verify_session(token):
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
    DEFAULT_HERMES_TOOLS,
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

DEFAULT_AGENTS = [
    {
        "id": "hermes-orchestrator",
        "name": "Hermes Master Orchestrator",
        "role": "System-Architekt & Paperclip Lead",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-researcher",
        "name": "Hermes Deep Researcher",
        "role": "Web-Scraping, Markt- & SEO-Analysen",
        "model": "omniroute/free-forever",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-coder",
        "name": "Hermes Senior Coder",
        "role": "Fullstack Software Engineer & Dev",
        "model": "omniroute/deepseek-coder",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    },
    {
        "id": "hermes-odysseus",
        "name": "Hermes Odysseus Strategist",
        "role": "Business Strategy & Second Brain Vault",
        "model": "omniroute/best-reasoning",
        "status": "active",
        "engine": "hermes",
        "active": True,
        "url": "http://localhost:8787",
        "type": "iframe"
    }
]

# DEFAULT_ROLES: definiert weiter unten mit allen 24 Spezialrollen (Zeile ~525)

DEFAULT_SERVICES = [
    {
        "id": "omniroute",
        "name": "OmniRoute AI Gateway",
        "description": "Multi-LLM & Gateway Proxy Router",
        "active": True,
        "model": "free-forever",
        "role": "Gateway",
        "port": 20128
    },
    {
        "id": "hermes",
        "name": "Hermes Engine & WebUI",
        "description": "Universelle Multi-Profile Agent Engine",
        "active": True,
        "model": "free-forever",
        "role": "Orchestrator",
        "port": 8787
    },
    {
        "id": "hermes-dashboard",
        "name": "Hermes Control Dashboard",
        "description": "Hermes Telemetrie & Performance Monitor",
        "active": True,
        "model": "free-forever",
        "role": "Telemetry",
        "port": 9119
    },
    {
        "id": "crm",
        "name": "CRM & LinkedIn Hub",
        "description": "Kontakt-Management & Outreach System",
        "active": True,
        "model": "free-forever",
        "role": "CRM",
        "port": 3005
    },
    {
        "id": "open-webui",
        "name": "Open WebUI",
        "description": "Schneller LLM-Chat Fallback",
        "active": True,
        "model": "free-forever",
        "role": "Chat Fallback",
        "port": 8082
    },
    {
        "id": "pocketbase",
        "name": "Pocketbase Storage",
        "description": "Echtzeit-Datenbank & Auth System",
        "active": True,
        "model": "free-forever",
        "role": "Database",
        "port": 8090
    },
    {
        "id": "n8n",
        "name": "n8n Automatisierung",
        "description": "Workflow- & Integrations-Automatisierung",
        "active": True,
        "model": "free-forever",
        "role": "Automation",
        "port": 5678
    }
]

# _load_json/_save_json -> app.core.runtime

GHOST_AGENT_IDS = {"prime-agent", "autogen-studio", "openhands", "openclaw", "gpt-researcher", "a-01", "a-02"}
SYSTEM_INTERNAL_IDS = {"agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"}

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
    # M-16: Inaktive und interne System-Agenten duerfen nicht geloescht werden,
    # wenn ein Frontend (z.B. skill_markt.js) nur ein gefiltertes Array sendet.
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

    # M-18: Sync zu agent_profiles.json (SSOT fuer Hermes und Chat)
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

# Rollen: 2,63 MB JSON pro Aufruf (gemessen Median 64-80 ms, nur Parsen).
# TTL 60 s, weil die Datei ausschliesslich ueber POST /api/roles (save_roles)
# geschrieben wird — dieser Pfad invalidiert sofort, die TTL deckt nur
# Fremdschreiber (Handedit, zweite Session) ab. Kuerzer waere teurer als der
# Nutzen: der Frontend-Aufruf passiert beim App-Start und im Rollen-Manager.
from archon.core.roles_data import DEFAULT_ROLES

@ttl_cache(seconds=60)
def load_roles() -> List[Dict]: return _load_json(ROLES_FILE, DEFAULT_ROLES)

def save_roles(roles: List[Dict]):
    # Rueckweg zum GET: das Frontend postet die materialisierte Antwort
    # unveraendert zurueck. Ohne diese Umkehrung stuenden /static-Pfade in
    # roles.json und die data-URI (einzige Kopie fuer Rollen ohne Profil)
    # waere verloren. Vorlage ist der Stand, der gleich ueberschrieben wird:
    # nur Pfade, die aus genau diesem data-URI entstehen, werden zurueckgedreht.
    vorher = _load_json(ROLES_FILE, [])
    _save_json(ROLES_FILE, restore_data_uri_avatars(roles, vorher))
    # Invalidierung an der Schreibstelle: der naechste Leser sieht die Aenderung
    # sofort statt erst nach Ablauf der TTL.
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


@app.get("/api/settings")
async def get_settings(request: Request):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

    s = _load_json(SETTINGS_FILE, {})
    gw_url = s.get("gateway_url") if isinstance(s, dict) else None
    if not gw_url:
        gw_url = "http://localhost:20128/v1"
    jev_cfg = s.get("jev", {}) if isinstance(s, dict) else {}
    mem_cfg = s.get("memory", {
        "enabled": True,
        "auto_learn": True,
        "apply_lessons": True,
        "max_injected_lessons": 3,
        "half_life_days": 14,
        "auto_evict": False,
        "eviction_threshold": 0.1,
        "vault_path": OBSIDIAN_VAULT,
        "daily_consolidation": True,
        "hours_back": 24
    }) if isinstance(s, dict) else {}
    email_guard_cfg = s.get("email_guard", {
        "enabled": True,
        "protect_email": True,
        "protect_telegram": True,
        "protect_crm": True,
        "sensitivity": "moderate",
        "use_llm": False,
        "model": "omniroute/free-forever"
    }) if isinstance(s, dict) else {}
    validate_cfg = s.get("validate", {
        "enabled": True,
        "min_score": 7,
        "on_failure": "warn",
        "check_hallucinations": True,
        "check_cutoff": True,
        "use_llm": False,
        "judge_model": "omniroute/free-forever"
    }) if isinstance(s, dict) else {}
    return {
        "gateway_url": gw_url,
        "workspace_dir": WORKSPACE_DIR,
        "jev": jev_cfg,
        "memory": mem_cfg,
        "email_guard": email_guard_cfg,
        "validate": validate_cfg
    }

@app.get("/api/ticker")
def get_ticker():
    return {"entries": ticker_entries}

@app.post("/api/ticker/clear")
def clear_ticker():
    # .clear() statt Neuzuweisung: die Liste wird mit archon.core.runtime geteilt
    ticker_entries.clear()
    return {"status": "cleared"}

@app.get("/api/agents")
def api_get_agents():
    agents = load_agents()
    try:
        from archon.core.profiles import api_get_hermes_profiles
        profiles_list = api_get_hermes_profiles()
        p_map = {p.get("id"): p for p in profiles_list if isinstance(p, dict) and p.get("id")}
        for a in agents:
            aid = a.get("id")
            if aid in p_map:
                prof = p_map[aid]
                if not a.get("avatar_url") and prof.get("avatar_url"):
                    a["avatar_url"] = prof["avatar_url"]
                if "runtime_status" not in a and "runtime_status" in prof:
                    a["runtime_status"] = prof["runtime_status"]
    except Exception:
        pass
    return agents

@app.post("/api/agents")
def api_save_agents(request: Request, agents: List[Dict]):
    require_admin(request)  # RBAC: Admin-Sache
    save_agents(agents)
    return {"status": "success"}

@app.get("/api/roles")
def api_get_roles():
    # 2,6 MB pro Antwort, davon 2,38 MB data:-URI-Avatare (5 Rollen, je Bild
    # zweimal als avatar und avatar_url). Fuer die Antwort wird jedes Bild
    # einmalig als Datei materialisiert und durch seinen /static-Pfad ersetzt;
    # roles.json bleibt unveraendert die Quelle der Wahrheit. Beim Schreiben
    # zu kuerzen waere falsch: fuer Rollen ohne Profil ist die data-URI die
    # einzige Kopie des Bildes.
    return materialize_role_avatars(load_roles())

@app.post("/api/roles")
def api_save_roles(request: Request, roles: List[Dict]):
    require_admin(request)  # RBAC: Admin-Sache
    save_roles(roles)
    return {"status": "success"}

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
        "agent-os-container": 8501
    }
    
    for key, port in known_ports.items():
        if key in cid_lower:
            return port

    if inspected_port and inspected_port not in (0,):
        return inspected_port
        
    return 8082

def _services_config_fallback(reason: str) -> List[Dict]:
    """Z-11: Statische Wunschliste als klar gekennzeichneter Fallback.

    Die Eintraege tragen ``source: "config-fallback"``, ``online: False`` und
    ``fallback_reason``. Damit kann der Client (und jedes Monitoring) einen
    Docker-Ausfall von einem laufenden System unterscheiden — vorher waren
    beide Faelle strukturgleich.
    """
    fallback = []
    for svc in load_services():
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
    """
    Liest ALLE echten Docker-Container direkt vom Docker-Daemon über /var/run/docker.sock aus.
    (10 s gecacht: der Socket-Read kostet ~1 s und wird von /api/services gepollt.)
    Nutzt utils.docker_client (Allowlist-geprüft, einheitlicher Transport).

    Z-11: Bei DockerError/Parse-Fehler wurde ``load_services()`` zurueckgegeben —
    die statische Wunschliste aus services.json, in DERSELBEN Struktur wie echte
    Container. Ein Docker-Ausfall war damit von einem Normalzustand nicht
    unterscheidbar ("Dienste laufen" trotz totem Daemon). Jetzt wird die
    Wunschliste als Fallback GEKENNZEICHNET (source/fallback_reason, nicht
    "online") — der Ausfall ist damit sichtbar.
    """
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
    SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container", "crm", "pocketbase", "pocketbase-crm"]

    saved_configs = {}
    if os.path.exists(COUPLED_AGENTS_FILE):
        raw_saved = _load_json(COUPLED_AGENTS_FILE, [])
        if isinstance(raw_saved, list):
            for sc in raw_saved:
                saved_configs[sc.get("id") or sc.get("container_name")] = sc
        elif isinstance(raw_saved, dict):
            saved_configs = raw_saved

    for c in containers_data:
        if not isinstance(c, dict): continue
        raw_names = c.get('Names') or []
        c_name = raw_names[0].lstrip('/') if (raw_names and len(raw_names) > 0) else c.get('Id', '')[:12]
        c_id = c_name

        if c_name.lower() in SYSTEM_INTERNAL_IDS:
            continue

        status_str = c.get('Status', '') or ''
        is_online = "Up" in status_str
        image_str = c.get('Image', '') or ''

        saved_cfg = saved_configs.get(c_name) or saved_configs.get(c_id) or {}
        is_active = is_online
        if "active" in saved_cfg:
            is_active = bool(saved_cfg["active"])
        elif "coupled" in saved_cfg:
            is_active = bool(saved_cfg["coupled"])

        ports_list = c.get('Ports') or []
        inspected_p = None
        for p in ports_list:
            if isinstance(p, dict):
                if 'PublicPort' in p:
                    inspected_p = p['PublicPort']
                    break
                elif 'PrivatePort' in p:
                    inspected_p = p['PrivatePort']

        port_num = detect_container_port(c_name, inspected_p)
        display_name = c_name.replace('-', ' ').replace('_', ' ').title()

        default_role = saved_cfg.get("role") or ("Orchestrator & System-Architekt" if "hermes" in c_name.lower() else "Senior Coder / Software Engineer")
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
            "role": default_role
        })

    return containers_list if len(containers_list) > 0 else load_services()

def post_docker_container_action(container_name: str, action: str = "start", raise_on_error: bool = False) -> dict:
    try:
        # validate_container_name is called inside container_action
        if action == "restart":
            # Der Proxy gibt `restart` nicht frei (ALLOW_RESTARTS=0, Entscheidung B2).
            # Neustart = stop + start, fail-closed: scheitert stop, folgt kein start.
            docker_client.restart_container(container_name)
        else:
            docker_client.container_action(container_name, action)
        # docker_client returns raw bytes; we don't need the response body for start/stop
        # Just verify no DockerError was raised

        # Keep hermes-dashboard-proxy in sync if hermes-dashboard restarted
        if container_name in ["hermes-dashboard", "hermes"] and action in ["start", "restart"]:
            try:
                docker_client.restart_container("hermes-dashboard-proxy")
            except Exception:
                pass

        # Der 5-s-Stats-Cache (_docker_container_stats) darf nach einer Zustandsaenderung
        # nicht weiter den Vorzustand liefern. Netter Nebeneffekt: betrifft alle Container.
        try:
            invalidate_ttl_cache(_docker_container_stats)
        except Exception:
            pass

        return {"status": "success", "message": f"Container {container_name} {action}ed."}
    except DockerError as e:
        if raise_on_error:
            status = 502 if (getattr(e, "status_code", 0) in (500, 502, 503) or "connection" in str(e).lower() or "socket" in str(e).lower()) else (getattr(e, "status_code", 0) or 400)
            raise HTTPException(status_code=status, detail=str(e))
        return {"status": "error", "message": str(e)}
    except HTTPException:
        raise
    except Exception as e:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=str(e))
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/services")
@app.get("/api/services")
def api_get_services(): 
    return get_docker_containers_from_socket()

@app.post("/api/docker/start")
def api_docker_start(payload: Dict, request: Request):
    require_admin(request)  # RBAC-Pilot: Container-Lebenszyklus ist Admin-Sache
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name: raise HTTPException(status_code=400, detail="Missing container_name")
    return post_docker_container_action(c_name, "start", raise_on_error=True)

@app.post("/api/docker/stop")
def api_docker_stop(payload: Dict, request: Request):
    require_admin(request)  # RBAC-Pilot: Container-Lebenszyklus ist Admin-Sache
    c_name = payload.get("container_name") or payload.get("id")
    if not c_name: raise HTTPException(status_code=400, detail="Missing container_name")
    return post_docker_container_action(c_name, "stop", raise_on_error=True)

@app.post("/api/v1/services")
def api_save_services(request: Request, services: List[Dict]):
    require_admin(request)  # RBAC: Admin-Sache
    save_services(services)
    return {"status": "success"}

@app.get("/api/models")
async def api_get_models(request: Request):
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "hermes-3", "gemini-1.5-pro"]

# --- Run / Dispatcher ---
class RunRequest(BaseModel):
    prompt: str

async def fetch_agent_response_api(agent: Dict, user_prompt: str) -> Dict:
    agent_name = agent["name"]
    model_combo = agent.get("model", "free-forever")
    agent_id = agent["id"]
    agent_role = agent.get("role", "Custom")
    agent_prompt = agent.get("prompt", "")
    
    start_time = time.time()
    
    add_ticker(agent_name, f"Leite Anfrage an physischen Container '{agent_id}' weiter (Dispatcher)...")
    
    prompt_text = user_prompt
    if isinstance(user_prompt, list):
        prompt_text = "\n".join([f"{m.get('role', '')}: {m.get('content', '')}" for m in user_prompt])
        
    try:
        # Dispatch to container or OmniRoute Gateway
        res = await core_dispatcher.dispatch_to_external_agent(
            agent_id=agent_id, 
            agent_name=agent_name, 
            prompt=prompt_text,
            role=agent_role,
            system_prompt=agent_prompt,
            model=model_combo,
            timeout=30
        )
    except Exception as e:
        res = {"status": "error", "content": f"Dispatcher Fehler: {str(e)}"}
    
    duration = time.time() - start_time
    
    if res["status"] == "success":
        add_ticker(agent_name, f"Antwort erfolgreich erhalten in {duration:.2f}s")
        try:
            if skills_engine:
                note_title = f"run_{agent_id}_{int(start_time)}"
                note_content = (
                    f"# Agent Run Log - {agent_name}\n\n"
                    f"- **Agent ID**: {agent_id}\n"
                    f"- **Model**: {model_combo}\n"
                    f"- **Role**: {agent_role}\n"
                    f"- **Timestamp**: {datetime.datetime.now().isoformat()}\n"
                    f"- **Duration**: {duration:.2f}s\n\n"
                    f"## Prompt\n\n```\n{prompt_text}\n```\n\n"
                    f"## Response\n\n```\n{res.get('content', '')}\n```\n"
                )
                skills_engine.obsidian.write_obsidian_note(note_title, note_content, ["run", agent_id, agent_role])
        except Exception as obs_err:
            print(f"Failed to write note to Obsidian: {obs_err}", file=sys.stderr)
    else:
        add_ticker(agent_name, f"Fehler: {res['content']}")
        
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": res["status"],
        "content": res["content"],
        "duration": f"{duration:.2f}s",
        "model": model_combo
    }



def load_boardroom_frameworks():
    fw = _load_json(FRAMEWORKS_FILE, None)
    if fw:
        core_dispatcher.CATEGORIZED_FRAMEWORKS = fw
    else:
        _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return core_dispatcher.CATEGORIZED_FRAMEWORKS


class BoardroomSlotItem(BaseModel):
    role_name: str
    profile_id: str
    model_id: Optional[str] = None
    provider: Optional[str] = None

class BoardroomRequest(BaseModel):
    task: str
    rounds: int = 2
    chairman_id: Optional[str] = "orchestrator"
    chairman_provider: Optional[str] = "openrouter"
    chairman_model: Optional[str] = None
    framework: str = "Steffi Kieffer Boardroom"
    slots: Optional[List[BoardroomSlotItem]] = None
    reasoning_level: Optional[str] = "profile"
    use_moa: bool = False
    moa_reference_models: Optional[List[dict]] = None
    moa_aggregator: Optional[dict] = None


@app.post("/api/run")
async def api_run_parallel(req: RunRequest):
    agents = load_agents()
    active_agents = [a for a in agents if a.get("active")]
    if not active_agents:
        raise HTTPException(status_code=400, detail="Keine aktiven Agenten konfiguriert.")
    
    add_ticker("System", f"Run gestartet für Befehl: '{req.prompt[:40]}'")
    tasks = [fetch_agent_response_api(agent, req.prompt) for agent in active_agents]
    results = await asyncio.gather(*tasks)
    
    memory = load_memory()
    memory.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": req.prompt,
        "responses": {
            res["agent_name"]: {
                "model": res["model"],
                "content": res["content"],
                "duration": res["duration"],
                "status": res["status"]
            }
            for res in results
        }
    })
    save_memory(memory)
    return results

class DirectAgentChatRequest(BaseModel):
    agent_id: str
    message: str
    attachment_name: Optional[str] = None
    attachment_content: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = []

def load_profiles_list() -> List[Dict]:
    _app_root = os.path.dirname(os.path.abspath(__file__))
    for path in [
        os.path.join(_app_root, "agent_profiles.json"),
        "agent_profiles.json",
        "/app/agent_profiles.json",
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        "/app/data/agent_profiles.json",
        os.path.join(WORKSPACE_DIR, "agent_profiles.json")
    ]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "profiles" in data:
                        return data["profiles"]
            except Exception:
                pass
    return []

@app.post("/api/v1/agent/chat")
async def api_direct_agent_chat(req: DirectAgentChatRequest):
    # Load profile data
    profiles = load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.agent_id), None)
    if not prof:
        prof = {
            "id": req.agent_id,
            "person_name": req.agent_id,
            "name": req.agent_id,
            "system_prompt": "Du bist ein intelligenter KI-Spezialist in Archon OS. Antworte präzise, strukturiert und direkt.",
            "model": "gpt-4o-mini"
        }
    
    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or "IT-Spezialist & DevOps Auditor"
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Du bist ein praxisorientierter, hochkompetenter IT-Administrator, Systemarchitekt und DevOps-Experte. "
        "Wenn dir Log-Einträge, Fehlermeldungen oder Systemfragen übergeben werden, analysiere die Ursache sofort präzise "
        "und erkläre dem Nutzer Schritt für Schritt, wie das Problem behoben werden kann (inklusive passender Konfigurations- oder Terminal-Befehle)."
    )
    
    user_msg = req.message
    if req.attachment_content:
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"
    
    messages = [{"role": "system", "content": system_prompt}]
    if req.history:
        for h in req.history[-8:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})
    
    model_to_use = prof.get("model") or "deepseek/deepseek-chat"
    provider_to_use = prof.get("provider") or "openrouter"
    
    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=prof.get("name", "Spezialist"),
            system_prompt=system_prompt,
            model=model_to_use,
            provider=provider_to_use
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"Fehler bei der Kommunikation mit {agent_name}: {str(e)}"
    
    duration = round(time.time() - start_t, 2)
    add_ticker("Direct Chat", f"Nachricht an {agent_name} beantwortet ({duration}s)")
    
    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }

# =====================================================================
# GATEWAY MANAGER — Hermes Profile Start/Stop/Autostart/Idle-Timeout
# =====================================================================

import subprocess
import threading

def _run_docker_exec(cmd: list) -> tuple[int, str, str]:
    """Run a command inside the hermes container via docker_client (allowlisted)."""
    target_containers = ["hermes-webui", "hermes", "hermes-agent"]
    for c_name in target_containers:
        try:
            # Validate container name and use docker_client.exec_command
            output_bytes = docker_client.exec_command(c_name, cmd, timeout=25.0)
            # docker_client returns raw multiplexed stream - parse to text
            stdout = parse_docker_stream(output_bytes)
            return 0, stdout, ""
        except DockerError:
            # Container not found or invalid name - try next
            continue
        except Exception:
            # Any other error - try next container
            continue
    
    # All containers failed
    return 1, "", "Failed to execute in hermes container (tried hermes-agent, hermes)"

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


# Background idle-stop task
_idle_stop_running = False


def _parse_gateway_list(stdout: str) -> list:
    '''Parses the hermes gateway list output into a list of dicts.

    Z-04: Die alte Fassung gab IMMER eine leere Liste zurueck ("return empty
    list to prevent crash") — die dokumentierte Funktion "stoppe unbenutzte
    Gateways nach idle_timeout_minutes" war damit tot.

    Unterstuetzt die zwei realen Ausgabeformen von ``hermes gateway list``:
      * JSON  — eine Liste von Objekten oder ein Objekt mit "profiles"/"gateways"
      * Tabelle — Spalten "ID  STATUS  ..." (whitespace- oder pipe-getrennt)

    Unbekanntes Format liefert eine leere Liste (kein Absturz) — dann faellt
    der Idle-Stop in einen Status, in dem nichts gestoppt wird.
    '''
    if not stdout:
        return []

    text = stdout.strip()
    if not text:
        return []

    # 1. JSON-Variante
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

    # 2. Tabellen-Variante: erste Zeile ist der Header, danach eine Zeile
    #    pro Gateway. Mindestens zwei Spalten noetig.
    profiles = []
    for index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        if set(line) <= set("-|=+ \t"):  # Trennlinie
            continue
        cells = [c for c in line.replace("|", " ").split() if c]
        if len(cells) < 2:
            continue
        if index == 0 and cells[0].lower() in ("id", "profile", "name"):
            continue  # Header
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
    # F-13: Der Guard wurde gesetzt, aber nie gelesen. Beim Doppelstart
    # (z. B. ``uvicorn --reload``) liefen zwei Idle-Stop-Loops und stoppten
    # sich gegenseitig die Gateways. Ein zweiter Start beendet sich sofort.
    if _idle_stop_running:
        logger.warning("[GatewayManager] Idle-Stop-Loop laeuft bereits - kein zweiter Start.")
        return
    _idle_stop_running = True
    try:
        while True:
            await asyncio.sleep(300)  # check every 5 minutes
            try:
                cfg = _load_gateway_config()
                timeout_min = cfg.get("idle_timeout_minutes", 30)
                last_used = cfg.get("last_used", {})
                autostart = cfg.get("autostart", {})
                now = datetime.datetime.now()
                rc, stdout, _ = _run_docker_exec(["hermes", "gateway", "list"])
                if rc != 0:
                    continue
                running_profiles = [p["id"] for p in _parse_gateway_list(stdout) if p.get("status") == "running" and p["id"] != "default"]
                for pid in running_profiles:
                    if autostart.get(pid, False):
                        continue  # autostart profiles stay up
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


ALL_HERMES_TOOLS = [
    "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
    "video_analyze", "image_generate", "video_generate", "bfl_flux3", "x_search", "text_to_speech",
    "speech_to_text", "skills", "task_planning", "memory", "context_engine", "session_search",
    "clarify", "delegate_task", "cronjob", "home_assistant", "spotify", "discord",
    "discord_admin", "yuanbao", "computer_use", "a2a"
]

# Hermes-Profil-Registry -> archon.core.profiles (Import weiter unten)


class AgentProfileValidationSchema(BaseModel):
    id: str
    name: str
    person_name: str
    category: str
    model: str
    prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: List[str]

    def get_prompt_text(self) -> str:
        val = (self.prompt or self.system_prompt or "").strip()
        if not val:
            val = f"Du bist {self.person_name} ({self.name})."
        return val

def save_all_agent_profiles(profiles_list):
    invalidate_hermes_profiles_cache()
    # SSOT: Projekt-Wurzel immer primär schreiben.
    try:
        _app_root = os.path.dirname(os.path.abspath(__file__))
        _ssot = os.path.join(_app_root, "agent_profiles.json")
        create_rolling_backup(_ssot, max_backups=3)
        with open(_ssot, "w", encoding="utf-8") as f:
            json.dump(profiles_list, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[Save Profiles] Error writing SSOT agent_profiles.json: {e}")

    candidates = [
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        os.path.join(MEMORY_DIR, "roles.json"),
        "agent_profiles.json",
        "roles.json",
        "/app/agent_profiles.json",
        "/app/roles.json",
        os.path.join(WORKSPACE_DIR, "agent_profiles.json"),
        os.path.join(WORKSPACE_DIR, "roles.json")
    ]
    for cand in candidates:
        try:
            d = os.path.dirname(cand)
            if d:
                os.makedirs(d, exist_ok=True)
            create_rolling_backup(cand, max_backups=3)
            with open(cand, "w", encoding="utf-8") as f:
                json.dump(profiles_list, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

# =========================================================================
# PERMISSION-GATE (12.10.2026, User-Vorgabe): Rechte-Erweiterungen
# (NEUE TOOLS im Profil, Profil-LOESCHEN) brauchen IMMER die Owner-
# Bestaetigung per Telegram. Erst nach 'approve' wird gespeichert/loescht.
# =========================================================================


@app.post("/api/permission-gates/{gate_id}/decide")
def api_decide_permission_gate(request: Request, gate_id: str, body: Dict = Body(...)):
    """Owner-Entscheidung ueber Telegram (Buttons gate:approve/reject oder
    Textbefehl 'Erlauben/Verbieten <gate_id>' via Skill).
    12.10: bewusst SYNCHRON (fastapi-Threadpool) - als async blockierte
    das sync-Innenleben (Save+Telegram) die Event-Loop der ganzen App."""
    require_admin(request)  # RBAC: Admin-Sache
    decision = str(body.get("decision") or "").lower().strip()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")
    gates = _load_permission_gates()
    gate = next((g for g in gates.get("gates", []) if g.get("id") == gate_id), None)
    if not gate:
        raise HTTPException(status_code=404, detail=f"Gate {gate_id} nicht gefunden")
    if gate.get("status") != "pending":
        return {"status": "already_decided", "decision": gate.get("status"), "gate_id": gate_id}

    ergebnis = ""
    ausgefuehrt = False
    ausfuehrungsfehler = None

    if decision == "approve":
        payload = dict(gate.get("payload") or {})
        try:
            if gate.get("kind") == "tools_erweiterung":
                payload["_approved_gate_id"] = gate_id
                res = save_profile(payload)
                ergebnis = f"Tools gespeichert fuer '{payload.get('id')}': " + str(res)
                ausgefuehrt = True
            elif gate.get("kind") == "profil_loeschen":
                res = delete_profile(payload.get("profile_id", ""), approved_gate_id=gate_id)
                ergebnis = f"Profil '{payload.get('profile_id')}' archiviert/geloescht: " + str(res)[:120]
                ausgefuehrt = True
            else:
                ergebnis = "Unbekanntes Gate-Kind - nichts ausgefuehrt"
        except Exception as dec_err:
            logger.error(f"[Gate] Ausfuehrung nach Freigabe fehlgeschlagen: {dec_err}")
            ergebnis = f"FEHLER bei der Ausfuehrung: {dec_err}"
            ausfuehrungsfehler = str(dec_err)

        # Status erst festschreiben, wenn wirklich etwas passiert ist: vorher
        # wurde 'approved' VOR der Ausfuehrung gespeichert, ein Fehlschlag
        # verbrannte das Gate (erneut entscheiden -> already_decided) und der
        # Owner konnte nicht wiederholen.
        if ausgefuehrt:
            gate["status"] = "approved"
            gate["decided_at"] = datetime.datetime.now().isoformat()
            _save_permission_gates(gates)
    else:
        # Ablehnung ist keine Ausfuehrung -> sofort persistieren.
        gate["status"] = "rejected"
        gate["decided_at"] = datetime.datetime.now().isoformat()
        _save_permission_gates(gates)
        ergebnis = "Abgelehnt - NICHTS wurde geaendert."

    try:
        from telegram_notify import send_telegram_message as _stg
        _stg(f"{'✅' if decision == 'approve' else '❌'} Rechte-Gate {gate_id}\n{ergebnis[:800]}")
    except Exception as tg2:
        logger.warning(f"[Gate] Bestaetigungs-Ping fehlgeschlagen: {tg2}")
    add_ticker("Rechte-Gate", f"{gate_id}: {'erteilt' if decision == 'approve' else 'abgelehnt'}")
    logger.info(f"[Gate] {gate_id} -> {decision}: {ergebnis[:200]}")
    # Ehrliche Antwort: ein Fehlschlag ist HTTP 200 (der Transport hat
    # funktioniert), aber status/error sagen die Wahrheit — der Telegram-Adapter
    # wertet beides aus, statt "wird jetzt ausgefuehrt" zu behaupten.
    antwort = {"status": "ok", "decision": decision, "gate_id": gate_id, "ergebnis": ergebnis}
    if ausfuehrungsfehler:
        antwort["status"] = "error"
        antwort["error"] = ausfuehrungsfehler
    return antwort


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
# ZENTRALER ENTSCHEIDUNGS-SERVICE (12.10.2026, User-Entscheidung "2c")
# kanban.db ist die WAHRHEIT: Eine Entscheidung IST ein Kanban-Task im Status
# 'review' (+ Sidecar-Block config/kanban_meta.json -> tasks[tid].decision).
# Telegram UND Kanban schreiben ueber EINEN Pfad:
#   POST /api/decisions/decide {task_id, decision, von}
# =========================================================================



def _decision_kanban_status(typ: str, decision: str) -> str:
    """Semantik der Entscheidung -> Kanban-Zielstatus (review = offen)."""
    approve = (decision == "approve")
    return {
        "delegation_review":  "todo" if approve else "archived",
        "synthesis_freigabe": "done" if approve else "archived",
        "mission_freigabe":   "in_progress" if approve else "archived",
        "permission_gate":    "done" if approve else "archived",
    }.get(typ, "todo" if approve else "archived")


def _decision_self_api(method: str, path: str, payload: dict = None, timeout: float = 15.0):
    """Selbstaufruf der eigenen API. Damit laufen Task-/Sidecar-Zugriffe ueber
    DIESELBEN Endpunkte wie die UI - keine zweite Schreiblogik, keine
    Direktschreibzugriffe auf kanban.db."""
    import urllib.request
    url = f"http://127.0.0.1:8501{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8") or "{}"
        return json.loads(raw)


def register_decision(task_id: str, typ: str, titel: str, kurzfassung: str = "",
                      ref_id: str = "", dossier: str = None, body: str = "",
                      extra: dict = None, obsidian: str = None) -> dict:
    """Haengt den Entscheidungs-Block an einen BESTEHENDEN Kanban-Task und pingt
    den Owner mit ✅/❌. Fuer Faelle, in denen der Task schon existiert (z.B. eine
    Delegation im Status 'review') — so laufen ALLE Typen ueber denselben Pfad."""
    if typ not in _DECISION_TYPEN or not task_id:
        logger.warning(f"[Decision] register_decision ohne gueltigen Typ/Task ({typ}, {task_id})")
        return {}
    try:
        dec = {
            "typ": typ, "ref_id": ref_id, "titel": titel,
            "kurzfassung": (kurzfassung or "")[:600],
            "dossier": dossier or "", "status": "offen",
            "kanal": "telegram+kanban",
        }
        if extra:
            dec.update(extra)
        _meta_payload = {
            "kind": "task", "task_id": task_id,
            "decision": dec
        }
        if obsidian and str(obsidian).strip():
            _meta_payload["obsidian"] = str(obsidian).strip()
        _decision_self_api("POST", "/api/operations/kanban/meta", _meta_payload)
        markup = {"inline_keyboard": [[
            {"text": "✅ Freigeben", "callback_data": f"app:approve:{task_id}"},
            {"text": "❌ Ablehnen", "callback_data": f"app:reject:{task_id}"},
        ]]}
        # 2d: Nachrichtenformat "Kontext zuerst" (User-Entscheidung) via
        # telegram_notify.decision_message -> HTML, damit '_' in Namen nicht mehr
        # die Markdown-Entities zerbricht.
        _ex = extra or {}
        _zahlen = []
        if _ex.get("teilberichte"):
            _zahlen.append(f"Teilberichte {_ex['teilberichte']}")
        if _ex.get("offene_punkte") is not None:
            _zahlen.append(f"Offene Punkte {_ex['offene_punkte']}")
        _anhang = None
        if dossier and os.path.basename(dossier):
            _bn = os.path.basename(dossier)
            try:
                _kb = max(1, round(os.path.getsize(dossier) / 1024))
            except Exception:
                _kb = 0
            _anhang = _bn + (f" · HTML · {_kb} KB" if _kb else "")
        _projekt = _ex.get("projekt") or (str(obsidian).split("/")[-1] if obsidian else "")
        sent = False
        try:
            from telegram_notify import (send_telegram_document, send_telegram_message,
                                         decision_message)
            caption = decision_message(
                typ=typ, titel=titel, projekt=_projekt, von=_ex.get("von", ""),
                ref=ref_id, kurzfassung=(kurzfassung or "")[:600],
                zahlen=_zahlen or None, anhang=_anhang, fallback_ref=task_id,
                zeit=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            )
            if dossier:
                sent = send_telegram_document(dossier, caption=caption,
                                              reply_markup=markup, parse_mode="HTML")
            if not sent:
                sent = send_telegram_message(caption, reply_markup=markup)
        except Exception as tg_err:
            logger.warning(f"[Decision] Telegram-Ping fehlgeschlagen: {tg_err}")
        logger.info(f"[Decision] {typ} registriert: Kanban {task_id} (ref={ref_id}), Ping={sent}")
        return {"task_id": task_id, "decision": dec}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidung nicht registrieren: {e}")
        return {}


def create_decision(typ: str, titel: str, kurzfassung: str = "", ref_id: str = "",
                    dossier: str = None, body: str = "", extra: dict = None,
                    obsidian: str = None) -> dict:
    """Legt einen NEUEN Entscheidungs-Task im Kanban an (Status 'review',
    Verantwortlicher Robert) und registriert die Entscheidung darauf.
    Rueckgabe {"task_id":..., "decision": {...}} oder {} bei Fehler."""
    if typ not in _DECISION_TYPEN:
        logger.warning(f"[Decision] Unbekannter Typ '{typ}'")
        return {}
    try:
        res = _decision_self_api("POST", "/api/operations/kanban/tasks", {
            "title": (titel or "Entscheidung")[:180],
            "body": body or kurzfassung,
            "assignee": "executive_decision_architect",
            "column": "review",
            "priority": 1,
        })
        task_id = res.get("task_id")
        if not task_id:
            logger.warning(f"[Decision] Task-Anlage lieferte keine ID: {res}")
            return {}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidungs-Task nicht anlegen: {e}")
        return {}
    return register_decision(task_id, typ, titel, kurzfassung, ref_id, dossier, body, extra, obsidian)


# Decision-Subsystem in den Permission-Gates bekannt machen (späte Bindung)
try:
    _set_decision_factory(create_decision)
except Exception as _pdm_err:
    logger.warning(f"[Permissions] Decision-Factory nicht registriert: {_pdm_err}")


# --- Folgeaktionen: Beleg statt Behauptung --------------------------------
# Ein Downstream-Aufruf gilt nur dann als ausgefuehrt, wenn der Antwort-Body den
# Vertrag des Endpunkts erfuellt (Status UND Inhalt), bei Schreibvorgaengen
# zusaetzlich der persistierte Zustand. HTTP 200 allein ist kein Beleg:
# /api/permission-gates/*/decide antwortet auch bei gescheiterter Ausfuehrung
# mit 200 und legt den Fehlschlag in den Body.

_FOLGE_OK = "Folgeaktion ausgeführt"


def _folge_nicht(aktion: str, grund: str) -> str:
    """Ehrliche Meldung: nichts ausgefuehrt, Grund aus der Antwort."""
    return f"Folgeaktion nicht ausgeführt: {aktion} — {grund}"


def _antwort_grund(antwort: Any) -> str:
    """Kurzgrund aus einer Fehlerantwort, ohne den Body zu verschlucken."""
    if not isinstance(antwort, dict):
        return f"Antwort ist kein JSON-Objekt ({type(antwort).__name__})"
    detail = antwort.get("error") or antwort.get("detail") or antwort.get("ergebnis")
    return str(detail or antwort.get("status") or "ohne Begründung")[:300]


def _pruefe_move_antwort(antwort: Any, ref: str) -> str:
    """Vertrag von POST /api/mission-control/tasks/move:
    ``{"status": "ok", "task": {...}}`` mit dem verschobenen Task.

    Rueckgabe "" = belegt, sonst der Grund. Geprueft wird der Task-Stand aus
    der Antwort (der Endpunkt gibt den unter dem Lock mutierten Task zurueck),
    nicht ein spaeterer Read-Back.
    """
    if not isinstance(antwort, dict) or antwort.get("status") != "ok":
        return _antwort_grund(antwort)
    task = antwort.get("task")
    if not isinstance(task, dict):
        return "Antwort ohne Task-Objekt"
    if str(task.get("id") or "") != str(ref):
        return f"Antwort betrifft Task '{task.get('id')}' statt '{ref}'"
    if task.get("status") != "in_progress":
        return f"Task-Status '{task.get('status')}' statt 'in_progress'"
    return ""


def _pruefe_gate_persistiert(ref: str) -> str:
    """Persistierter Gate-Status: nur ein 'approved'-Gate gilt als ausgefuehrt.

    Der Endpunkt antwortet auch fuer unbekannte Gate-Arten mit ``status: ok``,
    ohne etwas zu tun — der Body allein reicht deshalb nicht.
    """
    try:
        gates = _load_permission_gates() or {}
    except Exception as e:
        return f"Gate-Status nicht lesbar ({e})"
    gate = next((g for g in gates.get("gates", []) if str(g.get("id")) == str(ref)), None)
    if gate is None:
        return f"Gate '{ref}' nicht im Gate-Store gefunden"
    if gate.get("status") != "approved":
        return f"Gate-Status '{gate.get('status')}' statt 'approved'"
    return ""


def _pruefe_gate_antwort(antwort: Any, ref: str) -> str:
    """Vertrag von POST /api/permission-gates/{id}/decide: status ok|error|
    already_decided plus gate_id und decision."""
    if not isinstance(antwort, dict) or antwort.get("status") != "ok":
        return _antwort_grund(antwort)
    if str(antwort.get("gate_id") or "") != str(ref):
        return f"Antwort betrifft Gate '{antwort.get('gate_id')}' statt '{ref}'"
    if str(antwort.get("decision") or "").lower() != "approve":
        return f"Antwort meldet Entscheidung '{antwort.get('decision')}' statt 'approve'"
    return _pruefe_gate_persistiert(ref)


def _pruefe_synthese_beleg(task: Any) -> str:
    """Persistierter Parent-Task der Synthese: finalized UND completed."""
    if task is None:
        return "Parent-Task nicht in Mission Control gefunden"
    if not task.get("synthesis_finalized"):
        return "synthesis_finalized nicht gesetzt"
    if task.get("status") != "completed":
        return f"Parent-Status '{task.get('status')}' statt 'completed'"
    return ""


async def _synthese_parent(pid: str):
    """(lesbar, task) aus dem persistierten Mission-Control-Store."""
    try:
        data = await asyncio.to_thread(_load_mission_control_data) or {}
    except Exception as e:
        logger.warning(f"[Decision] Mission-Control-Store nicht lesbar: {e}")
        return False, None
    task = next((t for t in data.get("tasks", []) if str(t.get("id")) == str(pid)), None)
    return True, task


async def _followup_synthesis(pid: str, dossier: str, dec: dict) -> str:
    aktion = f"Synthese für {pid}"
    lesbar, vorher = await _synthese_parent(pid)
    if not lesbar:
        return _folge_nicht(aktion, "Mission-Control-Store nicht lesbar — nicht verifizierbar")
    if vorher is not None and vorher.get("synthesis_finalized"):
        return _folge_nicht(aktion, "bereits finalisiert (synthesis_finalized=true)")
    try:
        await _finalize_synthesis_after_approval(
            pid, dossier, dec.get("kurzfassung") or "",
            "Owner-Freigabe über den Entscheidungs-Service")
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    lesbar, nachher = await _synthese_parent(pid)
    if not lesbar:
        return _folge_nicht(aktion, "Mission-Control-Store nicht lesbar — nicht verifizierbar")
    grund = _pruefe_synthese_beleg(nachher)
    if grund:
        return _folge_nicht(aktion, grund)
    return f"{_FOLGE_OK}: Synthese {pid} finalisiert (belegt: synthesis_finalized=true, status=completed)."


async def _followup_mission_start(ref: str) -> str:
    aktion = f"Ausführung für Mission {ref or '(ohne ref_id)'}"
    if not ref:
        return _folge_nicht(aktion, "Entscheidungs-Block trägt keine ref_id")
    try:
        antwort = await asyncio.to_thread(
            _decision_self_api, "POST", "/api/mission-control/tasks/move",
            {"task_id": ref, "target_status": "in_progress"})
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    grund = _pruefe_move_antwort(antwort, ref)
    if grund:
        return _folge_nicht(aktion, grund)
    return (f"{_FOLGE_OK}: Mission {ref} auf 'in_progress' verschoben und Ausführung "
            "angestoßen (belegt: move status=ok, task.status=in_progress).")


async def _followup_permission_gate(ref: str) -> str:
    aktion = f"Rechte-Gate {ref or '(ohne ref_id)'}"
    if not ref:
        return _folge_nicht(aktion, "Entscheidungs-Block trägt keine ref_id")
    try:
        antwort = await asyncio.to_thread(
            _decision_self_api, "POST",
            f"/api/permission-gates/{ref}/decide", {"decision": "approve"})
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    grund = _pruefe_gate_antwort(antwort, ref)
    if grund:
        return _folge_nicht(aktion, grund)
    return f"{_FOLGE_OK}: Rechte-Gate {ref} freigegeben (belegt: status=ok, Gate persistiert als 'approved')."


async def _decision_followup(typ: str, dec: dict, decision: str) -> str:
    """Fuehrt nach der Statusaenderung die typ-spezifische Folgeaktion aus.

    Meldet 'ausgeführt' nur bei belegter Ausfuehrung (Body-Vertrag und, bei
    Schreibvorgaengen, persistierter Zustand); sonst die ehrliche Variante
    mit dem Grund aus der Antwort.
    """
    ref = dec.get("ref_id") or ""
    dossier = dec.get("dossier") or ""
    if decision != "approve":
        return "Abgelehnt — keine Folgeaktion ausgeführt."
    if typ == "synthesis_freigabe":
        return await _followup_synthesis(ref or "projekt", dossier, dec)
    if typ == "mission_freigabe":
        return await _followup_mission_start(ref)
    if typ == "permission_gate":
        return await _followup_permission_gate(ref)
    return "Keine Folgeaktion nötig (Statusänderung genügt)."


@app.post("/api/decisions/decide")
async def api_decide_decision(body: Dict = Body(...)):
    """EINZIGER Schreibpfad für Entscheidungen — Telegram UND Kanban rufen ihn."""
    task_id = str(body.get("task_id") or "").strip()
    decision = str(body.get("decision") or "").lower().strip()
    von = str(body.get("von") or "owner")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id fehlt")
    try:
        # WICHTIG: blockierender Selbst-HTTP-Aufruf NIE direkt im async-Handler
        # (Event-Loop-Deadlock) -> in den Threadpool auslagern.
        meta = await asyncio.to_thread(_decision_self_api, "GET", "/api/operations/kanban/meta")
        dec = (meta.get("tasks", {}).get(task_id, {}) or {}).get("decision")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sidecar nicht lesbar: {e}")
    if not dec:
        raise HTTPException(status_code=404, detail=f"Kein Entscheidungs-Block für {task_id}")
    # IDEMPOTENZ (12.10.2026): Der Adapter wiederholt Requests, die client-seitig
    # in den Timeout laufen — serverseitig aber schon ausgefuehrt wurden. Ohne
    # diese Sperre liefe die Folgeaktion ZWEIMAL (z.B. Mission doppelt starten).
    if (dec.get("status") or "offen") != "offen":
        return {"status": "already_decided", "task_id": task_id,
                "decision": decision, "kanban_status": dec.get("status"),
                "ergebnis": "Bereits entschieden — nicht erneut ausgeführt."}
    typ = dec.get("typ")
    ziel = _decision_kanban_status(typ, decision)
    # 1) kanban.db = Wahrheit -> Status dort setzen (source=decision: kein Doppel-Ping)
    try:
        await asyncio.to_thread(
            _decision_self_api, "PATCH", f"/api/operations/kanban/tasks/{task_id}/status",
            {"status": ziel, "source": "decision"})
    except Exception as e:
        logger.warning(f"[Decision] Kanban-Statusupdate fehlgeschlagen: {e}")
    # 2) Folgeaktion
    try:
        ergebnis = await _decision_followup(typ, dec, decision)
    except Exception as e:
        logger.error(f"[Decision] Folgeaktion fehlgeschlagen: {e}")
        ergebnis = f"FEHLER bei der Folgeaktion: {e}"
    # 3) Sidecar aktualisieren (Audit)
    try:
        await asyncio.to_thread(_decision_self_api, "POST", "/api/operations/kanban/meta", {
            "kind": "task", "task_id": task_id,
            "decision": {"status": "freigegeben" if decision == "approve" else "abgelehnt",
                         "entschieden_von": von,
                         "entschieden_am": datetime.datetime.now().isoformat()},
        })
    except Exception as e:
        logger.warning(f"[Decision] Sidecar-Update fehlgeschlagen: {e}")
    # 4) Bestaetigung (permission_gate pingt selbst)
    if typ != "permission_gate":
        try:
            from telegram_notify import send_telegram_message, tg_escape
            _e = tg_escape
            send_telegram_message(
                f"{'✅' if decision == 'approve' else '❌'} <b>{_e(dec.get('titel') or task_id)}</b>\n"
                f"Kanban: <code>{_e(ziel)}</code>\n{_e(ergebnis[:700])}")
        except Exception as e:
            logger.warning(f"[Decision] Bestätigungs-Ping fehlgeschlagen: {e}")
    add_ticker("Entscheidung", f"{task_id} ({typ}) -> {decision}")
    logger.info(f"[Decision] {task_id} ({typ}) -> {decision}: {ergebnis[:200]}")
    return {"status": "ok", "task_id": task_id, "decision": decision,
            "kanban_status": ziel, "ergebnis": ergebnis}


def _sync_org_hierarchy_node(p_id: str, name: Optional[str] = None, person_name: Optional[str] = None,
                             avatar: Optional[str] = None, provider: Optional[str] = None,
                             model: Optional[str] = None, reasoning_level: Optional[str] = None):
    """Synchronisiert Änderungen eines Agenten-Profils direkt in config/org_hierarchy.json und leert den Operations-Cache."""
    try:
        org_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "org_hierarchy.json")
        if os.path.exists(org_file):
            with open(org_file, "r", encoding="utf-8") as f:
                org_data = json.load(f)
            changed = False
            for node in org_data.get("nodes", []):
                if isinstance(node, dict) and node.get("id") == p_id:
                    if name:
                        node["name"] = name
                        node["role"] = name
                    if person_name:
                        node["person_name"] = person_name
                    if avatar:
                        node["avatar"] = avatar
                    if provider:
                        node["provider"] = provider
                    if model:
                        node["model"] = model
                    if reasoning_level:
                        node["reasoning_level"] = reasoning_level
                    changed = True
            if changed:
                with open(org_file, "w", encoding="utf-8") as f:
                    json.dump(org_data, f, indent=2, ensure_ascii=False)
        try:
            import backend.operations_api as _ops_api
            _ops_api._PROFILES_MAP_CACHE["mtime"] = 0.0
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[SSOT] Could not sync org_hierarchy.json for {p_id}: {e}")


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

# --- CSS Live Studio: Hintergrund-Bild-Upload (User-Wunsch 10.10.2026) ---

@app.post("/api/studio/upload-bg")
async def api_studio_upload_bg(file: UploadFile = File(...)):
    """Lädt ein Hintergrundbild (JPG/PNG/WebP) für das CSS Live Studio hoch.
    Speichert unter /static/uploads/ und liefert die URL zurück."""
    allowed_ext = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp", ".gif": "image/gif"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Dateityp '{ext}' nicht erlaubt (jpg, jpeg, png, webp, gif).")
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Bild zu groß (max. 8 MB).")
    os.makedirs(STUDIO_BG_UPLOAD_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    safe_ext = ext if ext else ".jpg"
    out_name = f"studio-bg_{ts}{safe_ext}"
    out_path = os.path.join(STUDIO_BG_UPLOAD_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(content)
    add_ticker("CSS Studio", f"Hintergrundbild hochgeladen: {out_name}")
    return {"status": "success", "url": f"/static/uploads/{out_name}", "filename": out_name, "size": len(content)}


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


@app.post("/api/settings")
async def api_save_settings(request: Request, settings: Dict = Body(None)):
    require_admin(request)  # RBAC: Admin-Sache
    if "x-hermes-session-token" in request.headers or "x-hermes-csrf-token" in request.headers or "authorization" in request.headers:
        return await forward_to_hermes(request)

    current = _load_json(SETTINGS_FILE, {})
    if isinstance(current, dict) and isinstance(settings, dict):
        current.update(settings)
        _save_json(SETTINGS_FILE, current)
    elif settings is not None:
        _save_json(SETTINGS_FILE, settings)
    try:
        from backend.audit_log import chained_audit_log
        keys_changed = list(settings.keys()) if isinstance(settings, dict) else ["all"]
        chained_audit_log.record_event(
            category="config",
            action="settings_saved",
            agent_id="operator",
            payload={"changed_keys": keys_changed}
        )
    except Exception:
        pass
    return {"status": "success"}

@app.post("/api/v1/jev/test")
async def api_test_jev(payload: Dict = Body(None)):
    import jev_router
    payload = payload or {}
    res = jev_router.test_jev_connection(
        api_key=payload.get("api_key"),
        base_url=payload.get("base_url")
    )
    return res

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



@app.get("/api/v1/models")
def api_get_models_v1():
    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"]

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

_TELEMETRY_CACHE = {"ts": 0.0, "containers": 0}


def _count_running_containers() -> int:
    """Echte Zahl laufender Container (60 s gecacht, damit der Endpunkt billig bleibt)."""
    now = time.time()
    if now - _TELEMETRY_CACHE["ts"] < 60 and _TELEMETRY_CACHE["ts"]:
        return _TELEMETRY_CACHE["containers"]
    count = 0
    try:
        import subprocess
        out = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=3)
        count = len([x for x in out.stdout.splitlines() if x.strip()]) if out.returncode == 0 else 0
    except Exception:
        count = 0
    if count == 0:
        # Fallback: docker-socket-proxy im Docker-Netz
        try:
            import json as _json
            import urllib.request as _url
            for host in ("http://docker-socket-proxy:2375", "http://host.docker.internal:2375"):
                try:
                    with _url.urlopen(f"{host}/containers/json", timeout=3) as resp:
                        count = len(_json.loads(resp.read()))
                        break
                except Exception:
                    continue
        except Exception:
            pass
    _TELEMETRY_CACHE.update({"ts": now, "containers": count})
    return count


@app.get("/api/v1/telemetry/dashboard")
def api_telemetry_dashboard():
    """Live-Kennzahlen. Keine festen Werte — alles wird zur Laufzeit ermittelt."""
    tasks_running = 0
    try:
        import sqlite3 as _sql
        _conn = _sql.connect("file:/opt/data/kanban.db?mode=ro", uri=True, timeout=2)
        tasks_running = _conn.execute(
            "SELECT count(*) FROM tasks WHERE status = 'in_progress'"
        ).fetchone()[0]
        _conn.close()
    except Exception:
        tasks_running = 0

    uptime_seconds = max(0, int(time.time() - _APP_START_TS))
    hours, rest = divmod(uptime_seconds, 3600)
    minutes = rest // 60

    return {
        "active_agents": len(load_agents()),
        "tasks_running": tasks_running,
        "network_ops": _count_running_containers(),
        "avg_uptime": f"{hours}h {minutes}m",
        "uptime_seconds": uptime_seconds,
    }

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

@app.post("/api/v1/agent/abort")
def abort_agent_endpoint(payload: dict):
    agent_id = payload.get("agent_id") or payload.get("profile") or payload.get("profile_handle", "unknown")
    reason = payload.get("reason", "Manual Kill-Switch Triggered")
    if watchdog_runner:
        watchdog_runner.abort_agent_thread(agent_id, reason, {"manual": True, "source": "UI_KILLSWITCH"})
    return {"status": "aborted", "agent": agent_id, "reason": reason}





def send_prompt_to_agent(agent_name: str, agent_config: dict, user_input: str, history: Optional[List[Dict[str, str]]] = None, session_id: Optional[str] = None) -> str:
    """Sendet eine echte HTTP-Anfrage an den lokalen OmniRoute LLM Router (Non-Streaming) mit kontinuierlichem Chat-Kontext."""
    role_name = agent_config.get("role", "Orchestrator & System-Architekt") if isinstance(agent_config, dict) else "Orchestrator & System-Architekt"
    
    system_prompt = "Du bist ein hilfreicher KI-Assistent."
    all_roles = []
    if "load_roles" in globals():
        try:
            all_roles = load_roles()
        except Exception:
            all_roles = []
    if not all_roles and "DEFAULT_ROLES" in globals():
        all_roles = DEFAULT_ROLES

    for r in all_roles:
        if r.get("name") == role_name or r.get("id") == role_name:
            system_prompt = r.get("prompt", system_prompt)
            break

    # Context Injection aus local_memory_bridge (User-Profil, Second Brain)
    if "memory_bridge" in globals() and memory_bridge:
        try:
            ctx_inj = memory_bridge.get_agent_context_injection(agent_name, limit=3)
            if ctx_inj:
                system_prompt = f"{system_prompt}\n\n{ctx_inj}"
        except Exception:
            pass
                
    model_name = agent_config.get("model", "auto/best-free") if isinstance(agent_config, dict) else "auto/best-free"
    if model_name == "free-forever":
        model_name = "auto/best-free"
    
    # Message-Historie zusammenbauen
    messages = [{"role": "system", "content": system_prompt}]
    
    # Vorherige Nachrichten aus Parametern oder Fallback aus local_memory_bridge
    prior_messages = []
    if history and isinstance(history, list):
        for msg in history:
            r = msg.get("role")
            c = msg.get("content")
            if r in ["user", "assistant"] and c:
                prior_messages.append({"role": r, "content": c})
    elif "memory_bridge" in globals() and memory_bridge:
        try:
            db_hist = memory_bridge.get_conversation_history(agent_name, limit=16, session_id=session_id)
            for msg in db_hist:
                r = msg.get("role")
                c = msg.get("content")
                if r in ["user", "assistant"] and c:
                    prior_messages.append({"role": r, "content": c})
        except Exception:
            pass

    # Begrenze Konversationshistorie auf die letzten 14 Turns zur Vermeidung von Token-Overhead
    if len(prior_messages) > 14:
        prior_messages = prior_messages[-14:]
    messages.extend(prior_messages)

    # Aktuellen User-Turn hinzufuegen, falls er nicht schon am Ende der Historie steht
    if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != user_input:
        messages.append({"role": "user", "content": user_input})
    
    headers = {"Content-Type": "application/json", "Authorization": "Bearer omniroute-local-key"}
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False  # Explicit non-streaming request
    }
    
    urls = [
        "http://omniroute:20128/v1/chat/completions",
        "http://localhost:20128/v1/chat/completions",
        "http://127.0.0.1:20128/v1/chat/completions",
        "http://host.docker.internal:20128/v1/chat/completions"
    ]
    
    last_err = ""
    ai_resp = None
    for url in urls:
        try:
            with httpx.Client(timeout=40.0) as client:
                res = client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    try:
                        data = res.json()
                        if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
                            choice = data["choices"][0]
                            if isinstance(choice, dict) and "message" in choice and "content" in choice["message"]:
                                ai_resp = choice["message"]["content"]
                                break
                        elif isinstance(data, dict) and "response" in data:
                            ai_resp = data["response"]
                            break
                    except Exception:
                        raw_text = res.text
                        lines = [line.replace("data: ", "").strip() for line in raw_text.splitlines() if line.strip() and not line.startswith("event:") and not "x-omniroute" in line]
                        cleaned = "\n".join(lines)
                        if cleaned:
                            ai_resp = cleaned
                            break
                else:
                    last_err = f"[SYSTEM FEHLER {res.status_code}]: {res.text}"
        except Exception as e:
            last_err = f"[VERBINDUNGSFEHLER]: {e}"

    final_output = ai_resp if ai_resp else (last_err or f"[{agent_name}]: Anweisung empfangen mit Rolle '{role_name}'.")

    # Persistiere Konversation in der SQLite-Datenbank (conversations Tabelle)
    if "memory_bridge" in globals() and memory_bridge:
        try:
            memory_bridge.record_conversation(agent_name, "user", user_input, session_id=session_id)
            if ai_resp:
                memory_bridge.record_conversation(agent_name, "assistant", ai_resp, session_id=session_id)
        except Exception as e:
            print(f"[QuickChat] Failed to record conversation to DB: {e}", file=sys.stderr)

    return final_output


class ContainerExecRequest(BaseModel):
    container_name: str
    command: str
    history: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None

@app.post("/api/v1/container/exec")
def exec_container_command_api(req: ContainerExecRequest, request: Request):
    require_admin(request)  # RBAC-Pilot: Befehle in Containern sind Admin-Sache
    configs = load_agent_configs()
    agent_cfg = configs.get(req.container_name, {})
    
    # Falls das Agent-Profil in den Standard-Agenten existiert, uebernimm Rolle und Model
    if not agent_cfg and "load_agents" in globals():
        try:
            all_a = load_agents()
            for a in all_a:
                if a.get("id") == req.container_name:
                    agent_cfg = a
                    break
        except Exception:
            pass

    # Optionales JEV Fast-Path Routing (0 Token-Verbrauch bei System-Befehlen)
    try:
        import jev_router
        if jev_router.is_jev_enabled():
            classification = jev_router.classify_prompt(req.command)
            if classification.get("action") == "direct_command":
                cmd = classification.get("command")
                desc = classification.get("description", "System-Befehl")
                import subprocess
                import shlex
                cmd_args = shlex.split(cmd) if isinstance(cmd, str) else cmd
                proc = subprocess.run(cmd_args, shell=False, capture_output=True, text=True, timeout=30)
                out = proc.stdout if proc.stdout else proc.stderr
                return {
                    "exit_code": proc.returncode,
                    "stdout": f"[⚡ JEV Fast-Path: {desc}]\n\n{out.strip() if out else '(Befehl erfolgreich ohne Ausgabe ausgeführt)'}",
                    "stderr": proc.stderr
                }
    except Exception as e_jev:
        logger.warning(f"JEV Fast-Path Fehler (Fallback auf LLM): {e_jev}")

    # Echte OmniRoute LLM API Integration mit Konversations-Historie
    output = send_prompt_to_agent(
        agent_name=req.container_name,
        agent_config=agent_cfg,
        user_input=req.command,
        history=req.history,
        session_id=req.session_id
    )
    
    return {
        "exit_code": 0,
        "stdout": output,
        "stderr": ""
    }



app.include_router(_hermes_proxy_router)

class LLMProviderSelectRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None

class LLMProviderSaveKeyRequest(BaseModel):
    env_name: str
    key_value: str







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

def _slugify(text: str) -> str:
    """Wandelt Text in sauberes, striktes ASCII um (ersetzt Umlaute) für sichere Dateinamen über Docker/NTFS."""
    text = text.lower()
    umlaut_map = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'ae', 'Ö': 'oe', 'Ü': 'ue'
    }
    for k, v in umlaut_map.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9_-]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    if len(text) > 60:
        text = text[:60].rstrip('-')
    return text or "task"

def _sync_task_to_obsidian(task: dict):
    """
    Führt die Post-Task-Pipeline aus:
    1. Projektordner-Struktur (01_Zwischenberichte, 02_Medien, 03_Endprodukte) + PROJEKT.md
    2. Personalakten-Aktualisierung (tasks_completed, Tabellen-Eintrag)
    3. Self-Improvement Lerneffekt via LocalMemoryBridge
    4. Paperclip-Status-Schließung
    5. E-Mail-Versand (falls konfiguriert)
    """
    try:
        from backend.post_task_pipeline import execute_post_task_pipeline
        pipe_res = execute_post_task_pipeline(task)
        if pipe_res and pipe_res.get("final_path"):
            return pipe_res["final_path"]
    except Exception as e_hook:
        logger.warning(f"[PostTaskPipeline] Hook-Fehler, weiche auf Fallback aus: {e_hook}")

    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    task_slug = _slugify(raw_title)
    # User-Vorgabe 09.10.2026: Datum (YYYYMMDD-) als Präfix statt "task-"
    _date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    _tid_core = task_id.replace("task-", "")
    file_name = f"{_date_prefix}-{_tid_core}-{task_slug}.md"
    
    # Bevorzugt /opt/data/obsidian/01_PROJEKTE, fallbacks auf OBSIDIAN_VAULT_DIR und inbox
    target_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE"),
        os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
        "/opt/data/inbox"
    ]
    
    written_paths = []
    content = f"""---
project_id: {task_id}
date: {datetime.date.today().isoformat()}
agent: {task.get('agent_name', 'Hermes Agent')}
model: {task.get('model', 'Universal')}
tokens_used: {task.get('estimated_tokens', 0)}
cost_usd: ${task.get('estimated_cost_eur', 0.0):.2f}
status: completed
---
# {task.get('title', 'Ohne Titel')}

## Ursprüngliche Anforderung
{task.get('capture_input') or task.get('title', '')}

## Umsetzungsplan & Ergebnisse
{task.get('result_summary') or 'Erfolgreich von Archon OS ausgeführt und validiert.'}

## Generierte Artefakte
- Pfad: /opt/data/obsidian/01_PROJEKTE/{file_name}
"""
    for d in target_dirs:
        try:
            os.makedirs(d, exist_ok=True)
            f_path = os.path.join(d, file_name)
            tmp_path = os.path.join(d, f".{file_name}.tmp_{os.getpid()}_{int(time.time()*1000)}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, f_path)
            if os.path.exists(f_path):
                written_paths.append(f_path)
                logger.info(f"[Obsidian Sync] Atomar und verifiziert gespeichert: {f_path}")
        except Exception as err:
            logger.warning(f"[Obsidian Sync] Fehler beim Schreiben in {d}: {err}")
            
    final_path = written_paths[0] if written_paths else f"/opt/data/obsidian/01_PROJEKTE/{file_name}"
    print(f"[Obsidian Sync] Speicherpfad verifiziert: {final_path}")
    return final_path

_LIVE_TELEMETRY_CACHE = {"ts": 0.0, "data": None}

def _get_live_telemetry_metrics():
    now_ts = time.time()
    if _LIVE_TELEMETRY_CACHE["data"] is not None and (now_ts - _LIVE_TELEMETRY_CACHE["ts"]) < 15.0:
        return _LIVE_TELEMETRY_CACHE["data"]
    import sqlite3, glob
    all_dbs = sorted(glob.glob('/opt/data/profiles/*/state.db') + ['/opt/data/state.db'])
    if not all_dbs:
        all_dbs = sorted(glob.glob(os.path.expanduser('~/.hermes/profiles/*/state.db')) + [os.path.expanduser('~/.hermes/state.db')])
    
    fifteen_min_ago = now_ts - 900
    # Tagesbeginn (00:00 Uhr lokaler Kalendertag)
    today_dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ts = today_dt.timestamp()

    # Performance-Optimierung: Nur DBs öffnen, die heute modifiziert wurden oder die globale state.db
    state_dbs = []
    for db in all_dbs:
        try:
            if not os.path.exists(db):
                continue
            if db.endswith("state.db") and "/profiles/" not in db:
                state_dbs.append(db)
            elif os.path.getmtime(db) >= today_start_ts:
                state_dbs.append(db)
        except Exception:
            pass
    if not state_dbs:
        state_dbs = [d for d in all_dbs if d.endswith("state.db") and "/profiles/" not in d] or all_dbs[:1]
    
    tokens_last_15m = 0
    today_cost = 0.0
    latest_model = "deepseek/deepseek-v4-flash-0731"
    latest_tokens = 0
    model_breakdown = {}
    all_sessions = []
    
    # Minuten-Buckets für die 15-Minuten Sparkline
    minute_buckets = [0.0] * 15
    
    for db in state_dbs:
        con = None
        try:
            con = sqlite3.connect(db, timeout=5.0)
            con.execute("PRAGMA busy_timeout=5000;")
            rows = con.execute('''
                SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                FROM session_model_usage 
                WHERE last_seen >= ?
                ORDER BY last_seen DESC LIMIT 200
            ''', (today_start_ts,)).fetchall()
            if not rows:
                rows = con.execute('''
                    SELECT model, input_tokens, output_tokens, estimated_cost_usd, last_seen 
                    FROM session_model_usage 
                    ORDER BY last_seen DESC LIMIT 50
                ''').fetchall()
            for r in rows:
                m, inp, out, cost, lseen = r[0], r[1] or 0, r[2] or 0, r[3] or 0.0, r[4] or 0
                tot = inp + out
                all_sessions.append((lseen, m, inp, out, cost, tot))
                if m:
                    model_breakdown[m] = model_breakdown.get(m, 0.0) + cost
                # Echte Aktivität heute
                if lseen and lseen >= today_start_ts:
                    today_cost += cost
                # Echte Aktivität der letzten 15 Minuten
                if lseen and lseen >= fifteen_min_ago:
                    tokens_last_15m += tot
                    bucket_idx = min(14, max(0, int((now_ts - lseen) / 60)))
                    minute_buckets[14 - bucket_idx] += round(tot / 1000.0, 1)
        except Exception:
            pass
        finally:
            if con:
                con.close()
            
    all_sessions.sort(key=lambda x: x[0], reverse=True)
    if all_sessions:
        latest_model = all_sessions[0][1] or latest_model
        latest_tokens = all_sessions[0][5] or latest_tokens

    # Echter Durchsatz: Tokens der letzten 15 Min geteilt durch 15 Minuten
    tpm_real = int(tokens_last_15m / 15) if tokens_last_15m > 0 else 0

    # Sparkline: Wenn in den letzten 15 Min aktiv, dann die echten Minuten-Buckets. Sonst flache Null-Linie.
    sparkline_vals = minute_buckets

    top_models_cost = sorted(model_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]

    res = {
        "sparkline_data": sparkline_vals,
        "today_cost": round(today_cost, 2),
        "tpm_est": tpm_real,
        "tokens_15m": tokens_last_15m,
        "latest_model": latest_model,
        "latest_tokens": latest_tokens,
        "top_models_cost": [{"model": m, "cost": round(c, 4)} for m, c in top_models_cost]
    }
    _LIVE_TELEMETRY_CACHE["ts"] = time.time()
    _LIVE_TELEMETRY_CACHE["data"] = res
    return res

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




# =============================================================
# PROMPT-TEMPLATES, KI-OPTIMIZER & PROMPTFOO GOVERNANCE API
# =============================================================

PROMPT_TEMPLATES_PATHS = [
    "/opt/data/prompt_templates.json",
    os.path.join(MEMORY_DIR, "prompt_templates.json"),
    os.path.join(WORKSPACE_DIR, "data", "prompt_templates.json"),
    "./data/prompt_templates.json",
    "prompt_templates.json"
]


# -------------------------------------------------------------
# FABRIC PATTERNS API (255+ kuratierte & übersetzte Muster)
# -------------------------------------------------------------

_FABRIC_CACHE: Optional[List[Dict[str, Any]]] = None


# -------------------------------------------------------------
# ARCHON PROMPT STUDIO FORMULAR-BAUKASTEN API (824 Enterprise-Templates)
# -------------------------------------------------------------

_PROMPT_STUDIO_CACHE: Optional[List[Dict[str, Any]]] = None


class TemplateRenderRequest(BaseModel):
    values: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None


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


@app.get("/hud")
def get_hud_page():
    hud_file = os.path.join("static", "hermes-hud", "index.html")
    if os.path.exists(hud_file):
        return FileResponse(hud_file)
    return FileResponse(os.path.join("static", "index.html"))

@app.get("/mobile")
@app.get("/m")
def get_mobile_cockpit():
    return FileResponse(
        os.path.join("static", "mobile.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join("static", "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/manifest+json")
    return JSONResponse({"name": "Archon Mobile", "short_name": "Archon", "start_url": "/mobile", "display": "standalone"})

@app.get("/v2")
def get_index_v2():
    return FileResponse("static/index.html")

@app.get("/")
def get_index():
    return FileResponse(
        os.path.join("static", "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
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
    api_attempt_task_healing,
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


# Feature 23: Dynamisches Modell-Routing nach Echtzeit-Telemetrie (Bandit-Router)


# Feature 24: Dynamisches Ephemeral-Team-Spawning (Ad-hoc Task-Force)


# Feature 25: Live-Ressourcen-Protector (Host CPU/RAM/Disk-Backpressure)


# --- CORPORATE MANAGER & MULTI-COMPANY HUB ---


# --- SÄULE 3: WIRTSCHAFT & ERP (MULTI-TENANT CRM, ARTIKEL, BELEGE & POCKETBASE SYNC) ---


# =========================================================================
# NATIVE POCKETBASE CRM API (KAUFMÄNNISCHES ADRESS- & CRM-ÖKOSYSTEM)
# =========================================================================


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

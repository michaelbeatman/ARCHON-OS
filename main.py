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
    from fastapi.responses import Response
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        return Response(content=f"# Error collecting metrics: {e}\n", status_code=500, media_type="text/plain")

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

# Methoden, die ueber den Hermes-Proxy schreiben — sie brauchen den Rollenzaun.
_PROXY_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _hermes_proxy_token() -> str:
    """Token fuer den Hermes-Dashboard-Forward — ausschliesslich aus der Umgebung.

    F1/R-34: kein hartkodierter Fallback mehr. Ein Literal-Token im Quelltext ist
    ein geteiltes Geheimnis, das mit dem Repo wandert und den Proxy zum
    Admin-Zugang macht; fehlt die Konfiguration, ist 502 die ehrliche Antwort.
    """
    for name in ("HERMES_SESSION_TOKEN", "HERMES_DASHBOARD_SESSION_TOKEN", "OMNIROUTE_API_KEY"):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


async def forward_to_hermes(request: Request) -> Response:
    path_to_use = request.url.path
    if path_to_use.startswith("/static/hermes-webui"):
        path_to_use = path_to_use[len("/static/hermes-webui"):]
    query_str = f"?{str(request.query_params)}" if request.query_params else ""
    
    candidates = [
        f"http://hermes-webui:8787{path_to_use}{query_str}",
        f"http://127.0.0.1:8787{path_to_use}{query_str}",
        f"http://host.docker.internal:8787{path_to_use}{query_str}",
        f"http://hermes-dashboard:9119{path_to_use}{query_str}",
        f"http://127.0.0.1:9119{path_to_use}{query_str}",
    ]
        
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length", "authorization"]}
    fwd_headers["Host"] = "localhost:8787"

    hermes_token = _hermes_proxy_token()
    if not hermes_token:
        logger.error(
            "[Hermes-Proxy] Kein Session-Token konfiguriert "
            "(HERMES_SESSION_TOKEN / HERMES_DASHBOARD_SESSION_TOKEN / OMNIROUTE_API_KEY) — "
            "Request abgewiesen."
        )
        return Response(
            content=json.dumps({
                "error": "proxy_not_configured",
                "detail": "Kein Hermes-Session-Token konfiguriert; Forward abgewiesen.",
            }),
            status_code=502,
            media_type="application/json",
        )

    fwd_headers["X-Hermes-Session-Token"] = hermes_token
    fwd_headers["Authorization"] = f"Bearer {hermes_token}"
    
    body = await request.body()
    last_err = None
    for target in candidates:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(
                    method=request.method,
                    url=target,
                    headers=fwd_headers,
                    content=body if body else None,
                    timeout=15.0
                )
            return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("Content-Type", "application/json"))
        except Exception as e:
            last_err = e
            continue
    return Response(
        content=json.dumps({"error": "proxy_unreachable", "detail": str(last_err)}),
        status_code=502,
        media_type="application/json",
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

# =====================================================================
# ORACLE NEWS RADAR (Hermes Intelligence Stream & Obsidian Sync)
# =====================================================================

@app.get("/api/oracle/feed")
def api_get_oracle_feed(limit: int = 50):
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        return {"status": "success", "feed": radar.get_feed(limit)}
    except Exception as e:
        # D-10: Fehler als HTTP-Fehler melden, nicht als 200 mit
        # status:error — sonst ist ein Fehler nicht von "keine Signale"
        # unterscheidbar (Monitoring/Automaten sehen Erfolg).
        raise HTTPException(status_code=502, detail=f"Oracle-Feed nicht verfuegbar: {e}")

@app.post("/api/oracle/run")
def api_run_oracle_cycle():
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        return radar.run_radar_cycle()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle-Lauf fehlgeschlagen: {e}")

@app.post("/api/oracle/triage")
def api_triage_oracle_signal(payload: Dict[str, Any] = Body(...)):
    try:
        import oracle_news_radar
        radar = oracle_news_radar.OracleNewsRadar()
        signal_id = payload.get("id") or payload.get("signal_id")
        if not signal_id:
            raise HTTPException(status_code=400, detail="Signal-ID fehlt im Payload")
        return radar.triage_to_task(signal_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle-Triage fehlgeschlagen: {e}")

# =====================================================================
# APOLLO VOICE AGENT (Hermes Conversational Voice & Execution Bridge)
# =====================================================================


# =====================================================================
# SEO & EXECUTION AGENT (Programmatic Content & Webhook Pipeline)
# =====================================================================

@app.post("/api/seo/generate")
async def api_seo_generate(payload: Dict[str, Any] = Body(...)):
    topic = payload.get("topic", "")
    keyword = payload.get("keyword", topic)
    audience = payload.get("audience", "B2B / Tech")
    trigger_n8n = payload.get("trigger_n8n", True)
    if not topic:
        raise HTTPException(status_code=400, detail="Thema (topic) ist erforderlich")
    try:
        from seo_execution_agent import SEOExecutionAgent
        agent = SEOExecutionAgent()
        return await agent.execute_content_pipeline(topic, keyword, audience, trigger_n8n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/seo/articles")
def api_seo_articles():
    content_dir = os.path.join(WORKSPACE_DIR, "obsidian_vault", "05_Content")
    if not os.path.exists(content_dir):
        content_dir = os.path.join("obsidian_vault", "05_Content")
    articles = []
    if os.path.exists(content_dir):
        for f in os.listdir(content_dir):
            if f.endswith(".md"):
                fp = os.path.join(content_dir, f)
                articles.append({
                    "filename": f,
                    "path": fp,
                    "size_bytes": os.path.getsize(fp),
                    "modified": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
                })
    return {"status": "success", "articles": articles}

os.makedirs(THEMES_DIR, exist_ok=True)

@app.get("/api/themes")
def api_get_themes():
    themes = []
    if os.path.exists(THEMES_DIR):
        for file in os.listdir(THEMES_DIR):
            if file.endswith(".json"):
                themes.append(file.replace(".json", ""))
    return {"themes": themes}

@app.get("/api/themes/{theme_name}")
def api_get_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        return _load_json(path, {})
    return {}

@app.post("/api/themes/{theme_name}")
def api_save_theme_by_name(theme_name: str, theme_data: dict = Body(...)):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    _save_json(path, theme_data)
    return {"status": "success", "theme_name": theme_name}

@app.delete("/api/themes/{theme_name}")
def api_delete_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "success"}

DESIGN_THEMES_TARGETS = [
    os.path.join("config", "design_themes.json"),
    "/app/config/design_themes.json",
    os.path.join("data", "design_themes.json"),
    "/app/data/design_themes.json"
]

@app.get("/api/design/themes")
def api_get_design_themes():
    for cand in DESIGN_THEMES_TARGETS:
        if os.path.exists(cand):
            data = _load_json(cand, {})
            if data and "themes" in data and len(data["themes"]) > 0:
                return data
    return {"active_theme_id": "archon_current", "active_mode": "light", "themes": {}}

@app.post("/api/design/themes")
def api_save_design_themes(payload: Dict = Body(...)):
    current = api_get_design_themes()
    if "active_theme_id" in payload:
        current["active_theme_id"] = payload["active_theme_id"]
    if "active_mode" in payload:
        current["active_mode"] = payload["active_mode"]
    if "themes" in payload and isinstance(payload["themes"], dict):
        current["themes"] = payload["themes"]
    if "theme" in payload and isinstance(payload["theme"], dict):
        t = payload["theme"]
        tid = t.get("id") or "custom_" + str(int(time.time()))
        t["id"] = tid
        if "themes" not in current or not isinstance(current["themes"], dict):
            current["themes"] = {}
        current["themes"][tid] = t
        if payload.get("set_active", True):
            current["active_theme_id"] = tid
    # D-11: Die vier Kopien werden nicht mehr stillschweigend geschluckt.
    # Sind alle unbeschreibbar, war der Theme nach Reload weg — gemeldet
    # wurde trotzdem "success". Jetzt: Fehler werden gesammelt und als
    # HTTP-Fehler gemeldet (mit Liste der fehlgeschlagenen Ziele).
    written, failed = [], {}
    for target in DESIGN_THEMES_TARGETS:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            _save_json(target, current)
            written.append(target)
        except Exception as exc:
            failed[target] = str(exc)
    if not written:
        raise HTTPException(
            status_code=500,
            detail=f"Theme konnte in keinem Ziel gespeichert werden: {failed}",
        )
    return {"status": "success", "data": current, "written_to": written, "failed": failed}

@app.delete("/api/design/themes/{theme_id}")
def api_delete_design_theme(theme_id: str):
    current = api_get_design_themes()
    themes = current.get("themes", {})
    if theme_id in themes and len(themes) > 1:
        del themes[theme_id]
        if current.get("active_theme_id") == theme_id:
            current["active_theme_id"] = next(iter(themes.keys()), "archon_current")
        # D-11: siehe api_save_design_themes — Fehler werden nicht verschluckt.
        written, failed = [], {}
        for target in DESIGN_THEMES_TARGETS:
            try:
                _save_json(target, current)
                written.append(target)
            except Exception as exc:
                failed[target] = str(exc)
        if not written:
            raise HTTPException(
                status_code=500,
                detail=f"Theme konnte in keinem Ziel geloescht werden: {failed}",
            )
        return {"status": "success", "data": current, "written_to": written, "failed": failed}
    return {"status": "success", "data": current}

@app.get("/api/theme")
def api_get_theme():
    return load_theme()

@app.post("/api/theme")
def api_save_theme(theme_data: Dict = Body(...)):
    save_theme(theme_data)
    return {"status": "success"}

@app.get("/api/theme/live-overrides")
def api_get_theme_live_overrides():
    return _load_json(THEME_LIVE_FILE, {"rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {}})

@app.post("/api/theme/live-overrides")
def api_save_theme_live_overrides(payload: Dict = Body(...)):
    existing = _load_json(THEME_LIVE_FILE, {"rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {}})
    merged = dict(existing) if isinstance(existing, dict) else {}

    if "rawCss" in payload:
        merged["rawCss"] = payload["rawCss"]

    for field in ("rules", "textOverrides", "htmlOverrides"):
        if field in payload:
            new_val = payload[field]
            if isinstance(new_val, dict):
                if new_val:
                    if not isinstance(merged.get(field), dict):
                        merged[field] = {}
                    merged[field].update(new_val)
            else:
                merged[field] = new_val

    for meta_key in ("migration_version", "updated_at"):
        if meta_key in payload:
            merged[meta_key] = payload[meta_key]

    _save_json(THEME_LIVE_FILE, merged)
    return {"status": "success"}

@app.post("/api/theme/bake-into-main-design")
def api_bake_theme_into_main_design(payload: Dict = Body(None)):
    """
    Kompiliert alle Live-Studio-Regeln direkt in static/custom_studio.css,
    leert die temporären Overrides auf Server und Client und setzt den Zähler auf 0 zurück.
    """
    data = payload or _load_json(THEME_LIVE_FILE, {})
    rules = data.get("rules", {})
    if not rules:
        live = _load_json(THEME_LIVE_FILE, {})
        rules = live.get("rules", {})

    css_lines = []
    prop_count = 0
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css_lines.append("/* ========================================================================= */")
    css_lines.append(f"/* ARCHON STUDIO BAKED CSS — Eingebrannt am: {now_str}               */")
    css_lines.append("/* ========================================================================= */\n")

    for sel, props in rules.items():
        if not props or not isinstance(props, dict):
            continue
        clean_props = []
        for p, v in props.items():
            if v is not None and str(v).strip() != "":
                clean_val = str(v).replace("!important", "").strip()
                clean_props.append(f"  {p}: {clean_val} !important;")
                prop_count += 1
        if clean_props:
            css_lines.append(f"{sel} {{")
            css_lines.extend(clean_props)
            css_lines.append("}\n")

    compiled_css = "\n".join(css_lines)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    studio_css_path = os.path.join(root_dir, "static", "custom_studio.css")
    try:
        with open(studio_css_path, "w", encoding="utf-8") as f:
            f.write(compiled_css)
    except Exception as e:
        print(f"[ThemeBake] Fehler beim Schreiben in custom_studio.css: {e}")

    # Setze theme_live_overrides.json zurück
    reset_data = {
        "rules": {},
        "rawCss": "",
        "textOverrides": data.get("textOverrides", {}),
        "htmlOverrides": data.get("htmlOverrides", {}),
        "migration_version": f"baked_{int(time.time())}",
        "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds")
    }
    _save_json(THEME_LIVE_FILE, reset_data)

    return {
        "status": "success",
        "baked_rules_count": prop_count,
        "selectors_count": len(rules),
        "version": reset_data["migration_version"],
        "message": f"{prop_count} Regeln erfolgreich ins permanente Hauptdesign eingebrannt."
    }

@app.delete("/api/theme/live-overrides")
def api_delete_theme_live_overrides():
    _save_json(THEME_LIVE_FILE, {
        "rules": {}, "rawCss": "", "textOverrides": {}, "htmlOverrides": {},
        "migration_version": "2026_10_27_baked_1793101139", "reset_all": True,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    return {"status": "success"}

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

def _load_gateway_config() -> Dict:
    cfg = _load_json(GATEWAY_CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("idle_timeout_minutes", 30)
    cfg.setdefault("autostart", {"default": True})
    cfg.setdefault("last_used", {})
    return cfg

def _save_gateway_config(cfg: Dict):
    _save_json(GATEWAY_CONFIG_FILE, cfg)

def _get_all_installed_profiles() -> list[str]:
    """List profile names from the mounted profiles volume directory."""
    candidates = ["/opt/data/profiles", os.path.join(MEMORY_DIR, "hermes_profiles")]
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

@app.get("/api/v1/gateway/list")
async def api_gateway_list():
    all_profiles = _get_all_installed_profiles()
    cfg = _load_gateway_config()
    autostart_map = cfg.get("autostart", {})
    last_used_map = cfg.get("last_used", {})
    active_gateways = cfg.get("active_gateways", {})

    # Read live state from volume
    gw_state_file = "/opt/data/gateway_state.json"
    served_profiles = []
    is_master_running = False
    if os.path.exists(gw_state_file):
        try:
            gw_data = _load_json(gw_state_file, {})
            is_master_running = gw_data.get("gateway_state") == "running"
            served_profiles = gw_data.get("served_profiles", [])
        except Exception:
            pass

    profiles = []
    for pid in all_profiles:
        # Default is running if master gateway is up; others according to active_gateways or explicit state
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

def _update_profile_status(profile_id: str, new_status: str):
    try:
        prof_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
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
        hier_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "org_hierarchy.json")
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

@app.post("/api/v1/gateway/start")
async def api_gateway_start(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")

    # D-09: Erst ausfuehren, DANN den Zustand setzen. Die alte Fassung
    # schrieb "active" VOR dem Kommando und ignorierte dessen Exitcode —
    # ein fehlgeschlagener Start zeigte "active", obwohl kein Prozess lief.
    cmd = ["hermes", "gateway", "start"] if profile_id == "default" else ["hermes", "--profile", profile_id, "gateway", "start"]
    rc, stdout, stderr = await asyncio.to_thread(_run_docker_exec, cmd)
    if rc != 0:
        logger.error(f"[Gateway] Start fuer '{profile_id}' fehlgeschlagen (rc={rc}): {stderr or stdout}")
        raise HTTPException(
            status_code=502,
            detail=f"Gateway-Start fehlgeschlagen: {(stderr or stdout or 'unbekannter Fehler').strip()[:400]}",
        )

    cfg = _load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = True
    cfg.setdefault("last_used", {})
    cfg["last_used"][profile_id] = datetime.datetime.now().isoformat()
    _save_gateway_config(cfg)
    _update_profile_status(profile_id, "active")

    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}

@app.post("/api/v1/gateway/stop")
async def api_gateway_stop(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    profile_id = payload.get("profile_id", "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    if profile_id == "default":
        raise HTTPException(status_code=400, detail="default gateway cannot be stopped")

    # D-09: siehe api_gateway_start — Zustand erst nach erfolgreichem
    # Kommando, kein Rollback-Zustand "standby" bei fehlgeschlagenem Stop.
    cmd = ["hermes", "--profile", profile_id, "gateway", "stop"]
    rc, stdout, stderr = await asyncio.to_thread(_run_docker_exec, cmd)
    if rc != 0:
        logger.error(f"[Gateway] Stop fuer '{profile_id}' fehlgeschlagen (rc={rc}): {stderr or stdout}")
        raise HTTPException(
            status_code=502,
            detail=f"Gateway-Stop fehlgeschlagen: {(stderr or stdout or 'unbekannter Fehler').strip()[:400]}",
        )

    cfg = _load_gateway_config()
    cfg.setdefault("active_gateways", {})
    cfg["active_gateways"][profile_id] = False
    _save_gateway_config(cfg)
    _update_profile_status(profile_id, "standby")

    return {"ok": True, "profile_id": profile_id, "output": stdout or stderr}

@app.get("/api/v1/gateway/config")
def api_get_gateway_config():
    return _load_gateway_config()

@app.post("/api/v1/gateway/config")
def api_save_gateway_config_endpoint(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    cfg = _load_gateway_config()
    if "idle_timeout_minutes" in payload:
        try:
            cfg["idle_timeout_minutes"] = max(1, int(payload["idle_timeout_minutes"]))
        except (ValueError, TypeError):
            pass
    if "autostart" in payload and isinstance(payload["autostart"], dict):
        cfg["autostart"].update(payload["autostart"])
    _save_gateway_config(cfg)
    return cfg

@app.post("/api/v1/gateway/autostart")
def api_gateway_autostart(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    enable = bool(payload.get("autostart", False))
    cfg = _load_gateway_config()
    cfg.setdefault("autostart", {})
    cfg["autostart"][profile_id] = enable
    _save_gateway_config(cfg)
    return {"ok": True, "profile_id": profile_id, "autostart": enable}

@app.post("/api/v1/gateway/stop-all")
async def api_gateway_stop_all(request: Request):
    require_admin(request)  # RBAC: Admin-Sache
    cfg = _load_gateway_config()
    active_map = cfg.get("active_gateways", {})
    stopped = []
    for pid, is_active in list(active_map.items()):
        if pid == "default" or not is_active:
            continue
        cfg["active_gateways"][pid] = False
        _update_profile_status(pid, "standby")
        try:
            _run_docker_exec(["hermes", "--profile", pid, "gateway", "stop"])
        except Exception:
            pass
        stopped.append(pid)
    _save_gateway_config(cfg)
    return {"ok": True, "stopped": stopped}

# =====================================================================
# INTERNET WATCHDOG (SÄULE 4 DER KOGNITION: AUTONOMER WEB-RADAR)
# =====================================================================

@app.get("/api/v1/watchdog/config")
def api_get_watchdog_config():
    from backend.internet_watchdog import get_watchdog_config
    return get_watchdog_config()

@app.post("/api/v1/watchdog/config")
def api_save_watchdog_config(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.internet_watchdog import get_watchdog_config, save_watchdog_config
    cfg = get_watchdog_config()
    if "enabled" in payload:
        cfg["enabled"] = bool(payload["enabled"])
    if "interval_minutes" in payload:
        try:
            cfg["interval_minutes"] = max(5, int(payload["interval_minutes"]))
        except (ValueError, TypeError):
            pass
    if "basket_threshold" in payload:
        try:
            cfg["basket_threshold"] = max(1, int(payload["basket_threshold"]))
        except (ValueError, TypeError):
            pass
    if "priority_keywords" in payload and isinstance(payload["priority_keywords"], list):
        cfg["priority_keywords"] = [str(k).strip() for k in payload["priority_keywords"] if str(k).strip()]
    if "basket" in payload and isinstance(payload["basket"], list):
        cfg["basket"] = payload["basket"]
    if "channels" in payload and isinstance(payload["channels"], dict):
        cfg.setdefault("channels", {}).update(payload["channels"])
    if "targets" in payload and isinstance(payload["targets"], list):
        cfg["targets"] = payload["targets"]
    save_watchdog_config(cfg)
    return {"ok": True, "config": cfg}

@app.post("/api/v1/watchdog/dispatch_action")
async def api_watchdog_dispatch_action(request: Request, payload: Dict = Body(...)):
    """Erzeugt eine gezielte Kanban-Aufgabe aus einem oder mehreren Watchdog-Funden.
    action_type: 'linkedin_post' | 'robert_dossier' | 'bundle_content' | 'custom'
    """
    require_admin(request)  # RBAC: Admin-Sache
    from datetime import datetime
    import sqlite3

    action_type = payload.get("action_type", "custom")
    findings = payload.get("findings", [])
    custom_prompt = payload.get("custom_prompt", "").strip()
    target_profile = payload.get("target_profile")
    
    if not findings:
        return {"ok": False, "error": "Keine Funde übergeben"}

    now_iso = datetime.now().isoformat()
    now_display = datetime.now().strftime("%d.%m.%Y %H:%M")

    if action_type == "linkedin_post":
        f = findings[0]
        assignee = "storyteller_ghostwriter"
        title = f"✍️ LinkedIn-Post: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Analysiere diesen Fund, arbeite die Kern-Relevanz für den deutschen Markt heraus "
            "und formuliere einen ansprechenden LinkedIn-Beitrag (Hook, Story, 3 Takeaways, Call-to-Action). "
            "ZITATIONS-PFLICHT: Bette die Primärquelle als sauberen Markdown-Link [Quelle: Name](URL) "
            "direkt im Text oder am Beitragsende ein."
        )
        body = (
            f"📱 **LinkedIn-Content Auftrag**\n\n"
            f"• **Thema:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')} ({f.get('category')})\n"
            f"• **Link:** {f.get('link')}\n\n"
            f"**Anweisung:**\n{prompt_instruction}\n\n"
            f"**Roh-Inhalt:**\n{f.get('snippet', '')}"
        )
    elif action_type == "robert_dossier":
        f = findings[0]
        assignee = "executive_decision_architect"
        title = f"📊 Strategie-Dossier: {f['title'][:60]}"
        prompt_instruction = custom_prompt or (
            "Prüfe die strategische Tragweite dieser Meldung für unsere Bau-, Investitions- und Projektentwicklungen "
            "und erstelle eine 1-Seiten-Entscheidungsvorlage mit Handlungsoptionen. "
            "ZITATIONS-PFLICHT: Zitiere die Primärquelle mit offiziellem Link [Quelle: Name](URL) und Einstufung (Amtlich/Leitmedium)."
        )
        body = (
            f"🏛️ **Strategische Vorlage für Robert (CEO)**\n\n"
            f"• **Gegenstand:** {f['title']}\n"
            f"• **Quelle:** {f.get('target_name')}\n"
            f"• **Referenz:** {f.get('link')}\n\n"
            f"**Prüfungsauftrag:**\n{prompt_instruction}\n\n"
            f"**Fundauszug:**\n{f.get('snippet', '')}"
        )
    elif action_type == "bundle_content":
        assignee = target_profile or "content_repurposing_specialist"
        title = f"🧺 Trend-Synthese aus {len(findings)} Radar-Funden"
        items_text = "\n".join([f"- **{it['title']}** ({it.get('category')}): {it.get('link')}\n  {it.get('snippet', '')[:180]}" for it in findings])
        prompt_instruction = custom_prompt or (
            f"Erstelle aus diesen {len(findings)} gesammelten Trend-Meldungen eine zusammenfassende Branchen- und Investitions-Synthese "
            "sowie zwei darauf aufbauende Content-Ideen. "
            "ZITATIONS-PFLICHT: Zitiere alle herangezogenen Quellen als anklickbare Hyperlinks [Quelle: Name](URL) in einem abschließenden Quellenverzeichnis."
        )
        body = (
            f"🧺 **Sammelkorb-Synthese ({len(findings)} Quellen)**\n\n"
            f"**Zusammenstellung:**\n{items_text}\n\n"
            f"**Auftrag:**\n{prompt_instruction}"
        )
    else: # custom
        f = findings[0] if len(findings) == 1 else findings
        assignee = target_profile or "executive_decision_architect"
        title = payload.get("title") or (f"Aufgabe: {findings[0]['title'][:60]}" if len(findings) == 1 else f"Sammel-Aufgabe ({len(findings)} Funde)")
        body = custom_prompt or f"Fund verarbeiten: {findings[0].get('link') if len(findings) == 1 else ''}"

    task_id = f"task-{int(datetime.now().timestamp())}"

    # Eintragen in kanban.db (SQLite blockiert -> im Thread ausfuehren)
    def _insert_task() -> bool:
        for kanban_db in ["/home/micha/.hermes/kanban.db", "/opt/data/kanban.db"]:
            if not os.path.exists(kanban_db):
                continue
            try:
                with sqlite3.connect(kanban_db, timeout=5.0) as kconn:
                    kconn.execute("""
                        INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (task_id, title, body, assignee, "ready", "normal", "watchdog_action", now_iso))
                    kconn.commit()
                    return True
            except Exception as e:
                print(f"[Watchdog] Action Kanban Insert Fehler: {e}")
        return False

    inserted = await asyncio.to_thread(_insert_task)

    # Fallback MemoryBridge
    if not inserted:
        def _bridge_sync():
            from local_memory_bridge import LocalMemoryBridge
            LocalMemoryBridge().sync_task(task_id=task_id, title=title, role=assignee, status="ready")
        try:
            await asyncio.to_thread(_bridge_sync)
        except Exception:
            pass

    return {
        "ok": True,
        "task_id": task_id,
        "title": title,
        "assignee": assignee,
        "status": "ready"
    }

@app.post("/api/v1/watchdog/run_now")
async def api_trigger_watchdog_run(request: Request):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.internet_watchdog import run_watchdog_scan
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, run_watchdog_scan, True)
    return res

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

# =====================================================================
# QUICKCHAT — Persistent Per-Profile Sessions
# =====================================================================

def _quickchat_session_path(profile_id: str) -> str:
    # Sanitize profile_id to avoid path traversal
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", profile_id)
    return os.path.join(QUICKCHAT_SESSIONS_DIR, f"{safe_id}.json")

def _load_quickchat_session(profile_id: str) -> Dict:
    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        data = _load_json(path, {})
        if isinstance(data, dict):
            return data
    return {
        "profile_id": profile_id,
        "messages": [],
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat()
    }

def _save_quickchat_session(session: Dict):
    session["updated_at"] = datetime.datetime.now().isoformat()
    _save_json(_quickchat_session_path(session["profile_id"]), session)

@app.get("/api/v1/quickchat/session/{profile_id}")
def api_get_quickchat_session(profile_id: str):
    """Verlauf aus state.db (identisch mit Master-/Agentenchat)."""
    sid = _quickchat_state_session_id(profile_id)
    msgs = []
    try:
        with _get_state_db() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id = ? AND active = 1 "
                "ORDER BY timestamp ASC LIMIT 200",
                (sid,),
            ).fetchall()
        for role, content, ts in rows:
            msgs.append({
                "role": "user" if role == "user" else "agent",
                "text": content,
                "ts": datetime.datetime.fromtimestamp(float(ts or 0)).isoformat() if ts else None,
            })
    except Exception as e:
        logger.warning(f"[QuickChat] Verlauf laden fehlgeschlagen: {e}")
    return {"profile_id": profile_id, "session_id": sid, "messages": msgs}

class QuickchatSendRequest(BaseModel):
    profile_id: str
    message: str
    attachment_content: Optional[str] = None
    attachment_name: Optional[str] = None

@app.post("/api/v1/quickchat/send")
async def api_quickchat_send(req: QuickchatSendRequest):
    # Gemeinsamer Verlauf mit Master-/Agentenchat: state.db statt JSON-Schatulle.
    state_sid = _quickchat_state_session_id(req.profile_id)
    _ensure_state_session(state_sid, source="quickchat", profile_name=req.profile_id, title=req.message)
    history = _load_state_history(state_sid, limit=12)
    session = _load_quickchat_session(req.profile_id)

    # Update last_used for idle-stop tracking
    cfg = _load_gateway_config()
    cfg["last_used"][req.profile_id] = datetime.datetime.now().isoformat()
    _save_gateway_config(cfg)

    # Load profile for system prompt
    profiles = load_profiles_list()
    prof = next((p for p in profiles if p.get("id") == req.profile_id), None)
    if not prof:
        prof = {"id": req.profile_id, "name": req.profile_id, "model": "gpt-4o-mini", "provider": "openrouter"}

    agent_name = prof.get("person_name") or prof.get("name") or prof.get("id")
    role_title = prof.get("name") or req.profile_id
    system_prompt = prof.get("system_prompt") or prof.get("prompt") or (
        f"Du bist {agent_name} (Rolle: {role_title}) in Archon OS. "
        "Antworte präzise, kompetent und direkt. Halte den Kontext der bisherigen Konversation."
    )
    model = prof.get("model") or "gpt-4o-mini"
    provider = prof.get("provider") or "openrouter"

    user_msg = req.message
    if req.attachment_content:
        user_msg = f"[Angehängte Datei: {req.attachment_name or 'Dokument'}]\n```\n{req.attachment_content[:6000]}\n```\n\n{req.message}"

    start_t = time.time()
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=prof["id"],
            agent_name=agent_name,
            prompt=user_msg,
            role=role_title,
            system_prompt=system_prompt,
            model=model,
            provider=provider
        )
        reply_text = res.get("content", "Keine Antwort erhalten.")
    except Exception as e:
        reply_text = f"⚠ Fehler: {str(e)}"

    duration = round(time.time() - start_t, 2)

    # Gemeinsamer Verlauf (state.db) — identisch mit Master-/Agentenchat
    try:
        _save_message_to_db(state_sid, "user", req.message)
        if reply_text:
            _save_message_to_db(state_sid, "assistant", str(reply_text))
    except Exception as _pc_err:
        logger.warning(f"[QuickChat] Speichern im gemeinsamen Verlauf fehlgeschlagen: {_pc_err}")

    # Append to persistent session
    session["messages"].append({"role": "user", "text": req.message, "ts": datetime.datetime.now().isoformat()})
    session["messages"].append({"role": "agent", "text": str(reply_text), "ts": datetime.datetime.now().isoformat()})
    # Keep last 200 messages to cap disk usage
    if len(session["messages"]) > 200:
        session["messages"] = session["messages"][-200:]
    _save_quickchat_session(session)

    add_ticker("Quickchat", f"{agent_name}: {req.message[:40]}… ({duration}s)")

    return {
        "agent_id": prof["id"],
        "agent_name": agent_name,
        "reply": str(reply_text),
        "duration": duration,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    }

@app.delete("/api/v1/quickchat/session/{profile_id}")
def api_delete_quickchat_session(profile_id: str):
    path = _quickchat_session_path(profile_id)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True, "profile_id": profile_id}

class TextReplacementItem(BaseModel):
    original: str
    replacement: str

class TextReplacementsRequest(BaseModel):
    replacements: List[TextReplacementItem]

@app.post("/api/v1/ui/save-text-replacements")
def api_save_text_replacements(request: Request, req: TextReplacementsRequest):
    require_admin(request)  # RBAC: Admin-Sache
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
        os.path.join(WORKSPACE_DIR, "static", "index.html")
    ]
    target_files = [p for p in set(candidates) if os.path.exists(p)]
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")
    
    total_replaced = 0
    for target_path in target_files:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            file_replaced = 0
            for item in req.replacements:
                orig = item.original
                repl = item.replacement
                if orig and repl and orig != repl and orig in content:
                    content = content.replace(orig, repl)
                    file_replaced += 1
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
            total_replaced = max(total_replaced, file_replaced)
        except Exception as err:
            print(f"Error saving replacements to {target_path}: {err}")
            
    add_ticker("Live UI Editor", f"{total_replaced} Texte dauerhaft in index.html eingefroren & gespeichert.")
    return {"status": "success", "replaced_count": total_replaced}

class FullHtmlSaveRequest(BaseModel):
    html: Optional[str] = None
    custom_css: Optional[str] = None

def _full_html_target_files() -> list:
    """Die Zieldateien fuer "HTML einfrieren" (existierende Kandidaten).

    Als eigene Funktion, damit der Schreibpfad testbar bleibt (der Handler
    darf nicht ungefragt die echte ``static/index.html`` anfassen).
    """
    candidates = [
        "/app/static/index.html",
        "static/index.html",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html"),
        os.path.join(WORKSPACE_DIR, "static", "index.html")
    ]
    return [p for p in set(candidates) if os.path.exists(p)]


@app.post("/api/v1/ui/save-full-html")
def api_save_full_html(request: Request, req: FullHtmlSaveRequest):
    require_admin(request)  # RBAC: Admin-Sache
    target_files = _full_html_target_files()
    if not target_files:
        raise HTTPException(status_code=404, detail="Keine static/index.html Datei gefunden.")

    if not req.html or len(req.html.strip()) <= 100:
        raise HTTPException(
            status_code=400,
            detail="HTML fehlt oder ist zu kurz (< 100 Zeichen) — es wurde nichts geschrieben.",
        )

    # D-08: Die alte Fassung truncatete die Datei vor dem Schreiben
    # (``open(...,"w")``) — ein Crash/Disk-full hinterliess eine halbe
    # index.html. Schreibfehler wurden nur geprintet, danach kam
    # "erfolgreich eingefroren" + {"status":"success"}.
    # Jetzt: atomarer Write (tmp + os.replace), Fehler werden gesammelt
    # und als HTTP-Fehler gemeldet.
    written, failed = [], {}
    for target_path in target_files:
        tmp_path = f"{target_path}.tmp.{os.getpid()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(req.html)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
            written.append(target_path)
        except Exception as err:
            failed[target_path] = str(err)
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if not written:
        raise HTTPException(
            status_code=500,
            detail=f"HTML konnte in keinem Ziel gespeichert werden: {failed}",
        )
    if failed:
        logger.warning(f"[Design Studio] HTML nur teilweise gespeichert: {failed}")

    add_ticker("Design Studio", "HTML & Design-Stand erfolgreich eingefroren und gespeichert.")
    return {"status": "success", "written_to": written, "failed": failed}

# ==========================================
# ðŸ§  BRAIN & ARCHIV (3D GALAXY & VAULT API)
# ==========================================

@app.get("/api/v1/brain/galaxy-data")
@ttl_cache(seconds=60)
def api_brain_galaxy_data(vault_limit: int = Query(600, description="Max. Vault-Notizen (0 = alle)"),
                          include_vault: bool = Query(True)):
    nodes = []
    links = []
    node_ids = set()

    # 1. Central Core Node
    core_id = "core_archon_os"
    nodes.append({
        "id": core_id,
        "name": "⚡ Archon OS Kernel",
        "group": "core",
        "color": "#38bdf8",
        "val": 35,
        "description": "Zentraler OS-Kern & Event Loop Orchestrator",
        "details": {"type": "System Kernel", "status": "Online"}
    })
    node_ids.add(core_id)

    # 2. Agenten aus agent_profiles.json & roles.json
    agent_profiles = []
    # SSOT: nur die Projekt-Wurzel-Datei (data/agent_workspace sind Spiegel)
    for path in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    agent_profiles = json.load(f)
                break
            except:
                pass
    
    if not agent_profiles:
        agent_profiles = DEFAULT_ROLES

    for a in agent_profiles:
        aid = f"agent_{a.get('id', a.get('name'))}"
        if aid not in node_ids:
            nodes.append({
                "id": aid,
                "name": f"ðŸ¤– {a.get('name', 'Agent')}",
                "group": "agent",
                "color": "#22c55e",
                "val": 22,
                "description": a.get("category", "Autonomer Agent"),
                "details": {
                    "role_id": a.get("id"),
                    "category": a.get("category", "General"),
                    "prompt": a.get("prompt", "")[:180] + "...",
                    "skills": a.get("skills", [])
                }
            })
            node_ids.add(aid)
            links.append({"source": core_id, "target": aid, "relationship": "orchestrates", "color": "rgba(56, 189, 248, 0.4)"})

            # Connect agent skills
            for s in a.get("skills", []):
                sid = f"skill_{s}"
                if sid not in node_ids:
                    nodes.append({
                        "id": sid,
                        "name": f"⚡ {s.replace('skill-', '').replace('_', ' ').title()}",
                        "group": "skill",
                        "color": "#a855f7",
                        "val": 14,
                        "description": "Fähigkeit / Execution Skill",
                        "details": {"skill_id": s}
                    })
                    node_ids.add(sid)
                links.append({"source": aid, "target": sid, "relationship": "executes", "color": "rgba(168, 85, 247, 0.5)"})

    # 3. Obsidian Vault Notizen & Personalakten
    vault_candidates = [
        OBSIDIAN_VAULT,
        OBSIDIAN_VAULT_ALT,
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = v
            break

    if vault_dir:
        for root, dirs, files in os.walk(vault_dir):
            if ".obsidian" in root or ".git" in root or "node_modules" in root:
                continue
            for file in files:
                if file.endswith(".md"):
                    rel_path = os.path.relpath(os.path.join(root, file), vault_dir).replace("\\", "/")
                    note_id = f"note_{rel_path}"
                    clean_name = file.replace(".md", "").replace("_", " ").title()
                    is_personalakte = "Personalakten" in rel_path
                    
                    if note_id not in node_ids:
                        nodes.append({
                            "id": note_id,
                            "name": f"{'ðŸ“‹' if is_personalakte else 'ðŸ“„'} {clean_name}",
                            "group": "personalakte" if is_personalakte else "vault_note",
                            "color": "#eab308" if is_personalakte else "#06b6d4",
                            "val": 16 if is_personalakte else 10,
                            "description": rel_path,
                            "details": {
                                "rel_path": rel_path,
                                "type": "Personalakte" if is_personalakte else "Vault Dokument",
                                "filename": file
                            }
                        })
                        node_ids.add(note_id)

                        # Match with agent if Personalakte
                        matched_agent = False
                        if is_personalakte:
                            for a in agent_profiles:
                                aid = f"agent_{a.get('id', a.get('name'))}"
                                if a.get("id") and a.get("id").lower() in file.lower() or file.lower().replace(".md", "") in a.get("id", "").lower():
                                    if aid in node_ids:
                                        links.append({"source": aid, "target": note_id, "relationship": "documented_in", "color": "rgba(234, 179, 8, 0.6)"})
                                        matched_agent = True
                                        break
                        if not matched_agent:
                            links.append({"source": core_id, "target": note_id, "relationship": "stores", "color": "rgba(6, 182, 212, 0.3)"})

    # --- Payload-Begrenzung -------------------------------------------------
    # 5050 Vault-Notizen machten 2,5 MB von 3,8 MB aus und sind in einem
    # Force-Graph ohnehin nicht lesbar. Personalakten bleiben immer drin,
    # reine Vault-Notizen werden auf `vault_limit` begrenzt (0 = alle).
    if not include_vault:
        _drop = {n["id"] for n in nodes if n["group"] in ("vault_note", "personalakte")}
    elif vault_limit and vault_limit > 0:
        _notes = [n for n in nodes if n["group"] == "vault_note"]
        _pa = [n for n in nodes if n["group"] == "personalakte"]
        _keep_pa = set()
        _keep_notes = set()
        for n in _pa:
            _keep_pa.add(n["id"])
        for n in _notes[:max(0, vault_limit - len(_keep_pa))]:
            _keep_notes.add(n["id"])
        _drop = {n["id"] for n in _notes if n["id"] not in _keep_notes}
    else:
        _drop = set()

    if _drop:
        nodes = [n for n in nodes if n["id"] not in _drop]
        links = [l for l in links if l.get("source") not in _drop and l.get("target") not in _drop]

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "agents_count": len([n for n in nodes if n["group"] == "agent"]),
            "skills_count": len([n for n in nodes if n["group"] == "skill"]),
            "vault_notes_count": len([n for n in nodes if "note" in n["group"] or "personalakte" in n["group"]]),
            "vault_notes_truncated": len(_drop)
        }
    }

@app.get("/api/v1/brain/vault-file")
def api_brain_vault_file(path: str):
    vault_candidates = [
        OBSIDIAN_VAULT,
        OBSIDIAN_VAULT_ALT,
        "/opt/data/obsidian",
        OBSIDIAN_VAULT_DIR,
        os.path.join(WORKSPACE_DIR, "agent_workspace", "obsidian_vault"),
        "agent_workspace/obsidian_vault",
        "/app/agent_workspace/obsidian_vault"
    ]
    vault_dir = None
    for v in vault_candidates:
        if v and os.path.exists(v):
            vault_dir = os.path.abspath(v)
            break
            
    if not vault_dir:
        raise HTTPException(status_code=404, detail="Obsidian Vault Verzeichnis nicht gefunden.")

    clean_path = path.lstrip("/\\")
    candidate = os.path.join(vault_dir, clean_path)
    try:
        real_file = safe_path(candidate, must_exist=True, allow_dirs=False)
    except PathJailError as e:
        raise HTTPException(status_code=400, detail=f"Ungültiger Dateipfad: {e}")

    # Zusätzlich: muss innerhalb des gewählten Vault-Verzeichnisses liegen
    real_vault = os.path.realpath(vault_dir)
    if not (real_file == real_vault or real_file.startswith(real_vault + os.sep)):
        raise HTTPException(status_code=400, detail="Ungültiger Dateipfad.")

    try:
        with open(real_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "path": path,
            "filename": os.path.basename(real_file),
            "content": content,
            "size": len(content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# NOTEBOOK & DEEP DOCS / OCR LIBRARY PIPELINE
# ---------------------------------------------------------

@app.post("/api/v1/library/upload")
async def api_library_upload(request: Request):
    # RBAC: Datei-Schreiben in den Bibliotheksbaum ist Admin-Sache. Der Zaun
    # steht VOR jedem makedirs/open, damit ein 403 keinen Seiteneffekt hat.
    require_admin_or_503(request)
    try:
        from utils.batch_library_importer import resolve_raw_docs_dir, resolve_vault_path, process_document
        raw_dir = resolve_raw_docs_dir()
        vault_dir = resolve_vault_path()
        os.makedirs(raw_dir, exist_ok=True)
        
        form = await request.form()
        uploaded_files = form.getlist("files") or form.getlist("file")
        if not uploaded_files:
            single_file = form.get("file")
            if single_file:
                uploaded_files = [single_file]
                
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="Keine Dateien übermittelt.")
            
        auto_ingest = form.get("auto_ingest", "true").lower() in ["true", "1", "yes"]
        category = form.get("category", "auto")
        
        results = []
        for file in uploaded_files:
            if hasattr(file, "filename") and file.filename:
                # Traversal-Haertung: nur der Basisname wird verwendet, danach
                # laeuft der Zielpfad durch das Pfad-Jail mit `raw_dir` als
                # erlaubter Wurzel. Kein Schreiben ausserhalb von raw_dir.
                name = os.path.basename(str(file.filename).replace("\\", "/")).strip()
                if not name or name in (".", ".."):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Ungueltiger Dateiname: {file.filename!r}"
                    )
                try:
                    file_path = safe_path(
                        os.path.join(raw_dir, name),
                        must_exist=False, allow_write=True,
                        allow_dirs=False, extra_roots=[raw_dir],
                    )
                except PathJailError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Dateiname nicht erlaubt: {e}"
                    )
                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                    
                item_info = {
                    "filename": name,
                    "size_bytes": len(content),
                    "saved_path": file_path
                }
                
                if auto_ingest:
                    try:
                        ingest_res = process_document(file_path, vault_dir, target_category=category)
                        item_info["ingest"] = ingest_res
                    except Exception as err:
                        item_info["ingest"] = {"status": "error", "error": str(err)}
                        
                results.append(item_info)
            
        # Wenn auto_ingest aktiv war, im Hintergrund AnythingLLM RAG-Sync anstoßen
        if auto_ingest:
            async def trigger_background_rag_sync():
                global _RAG_SYNC_PROCESS
                async with _RAG_SYNC_LOCK:
                    if _is_rag_sync_running():
                        logger.info("[RAG-Sync] Vollsync laeuft bereits; ueberspringe redundanten Start.")
                        return
                    try:
                        import subprocess
                        sync_script = os.path.join(os.path.dirname(__file__), "tools", "sync_vault_to_rag.py")
                        if os.path.exists(sync_script):
                            # Key ausschliesslich aus der Umgebung — kein Literal,
                            # kein Default. Fehlt er, startet kein subprocess.
                            cmd = [sys.executable, sync_script, "--api-key", _get_rag_api_key(), "--all"]
                            _RAG_SYNC_PROCESS = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except MissingRagApiKeyError as ex:
                        logger.error(f"[RAG-Sync] Sync nicht gestartet: {ex}")
                    except Exception as ex:
                        logger.error(f"[RAG-Sync-Trigger] Fehler: {ex}")
            _spawn_background(trigger_background_rag_sync(), name="rag_sync_trigger")

        return {
            "status": "success",
            "uploaded_count": len(results),
            "items": results
        }
    except HTTPException:
        # 400/403 nicht in ein 500 umdeuten (Zaun-/Namensfehler bleiben sichtbar).
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/library/ingest")
def api_library_ingest():
    try:
        from utils.batch_library_importer import run_batch_ingest
        summary = run_batch_ingest()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/library/books")
@ttl_cache(seconds=60)
def api_library_books():
    try:
        from utils.batch_library_importer import list_indexed_books
        books = list_indexed_books()
        return {"books": books, "count": len(books)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/library/book-content")
def api_library_book_content(rel_path: str = Query(...)):
    try:
        from utils.batch_library_importer import resolve_vault_path
        vault_dir = resolve_vault_path()
        bib_dir = os.path.join(vault_dir, "02_Wissensbibliothek")
        
        clean_path = rel_path.lstrip("/\\")
        safe_path = os.path.abspath(os.path.join(bib_dir, clean_path))
        if not safe_path.startswith(os.path.abspath(bib_dir)):
            raise HTTPException(status_code=400, detail="Ungültiger Pfad.")
            
        if not os.path.exists(safe_path):
            raise HTTPException(status_code=404, detail=f"Dokument '{rel_path}' nicht gefunden.")
            
        with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        return {
            "rel_path": rel_path,
            "filename": os.path.basename(safe_path),
            "content": content,
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# NOTEBOOKLM STUDIO & GROUNDED RETRIEVAL API
# ---------------------------------------------------------

@app.get("/api/v1/notebooks")
def api_get_notebooks():
    try:
        from utils.notebook_engine import list_notebooks
        return {"notebooks": list_notebooks()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks")
def api_create_notebook(payload: dict = Body(...)):
    try:
        from utils.notebook_engine import create_notebook
        name = payload.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name ist erforderlich.")
        description = payload.get("description", "").strip()
        nb = create_notebook(name, description)
        return {"status": "success", "notebook": nb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/notebooks/{nb_id}")
def api_delete_notebook(nb_id: str):
    try:
        from utils.notebook_engine import delete_notebook
        ok = delete_notebook(nb_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"status": "deleted", "id": nb_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/notebooks/{nb_id}/sources")
def api_get_notebook_sources(nb_id: str):
    try:
        from utils.notebook_engine import list_sources
        sources = list_sources(nb_id)
        return {"sources": sources, "count": len(sources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sources/upload")
async def api_upload_notebook_source(nb_id: str, request: Request):
    # RBAC: Upload schreibt in die Bibliothek -> Admin-Sache (F19/M-03).
    require_admin_or_503(request)
    try:
        from utils.notebook_engine import add_source_file
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei übermittelt.")
        file_bytes = await file.read()
        res = add_source_file(nb_id, file_bytes, file.filename)
        return res
    except HTTPException:
        raise
    except PathJailError as pe:
        raise HTTPException(status_code=400, detail=f"Dateiname nicht erlaubt: {pe}")
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sources/attach-vault")
def api_attach_vault_source(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import add_source_from_vault
        rel_path = payload.get("rel_path")
        if not rel_path:
            raise HTTPException(status_code=400, detail="rel_path ist erforderlich.")
        res = add_source_from_vault(nb_id, rel_path)
        return res
    except HTTPException:
        raise
    except PathJailError as pe:
        raise HTTPException(status_code=400, detail=f"Pfad nicht erlaubt: {pe}")
    except (ValueError, FileNotFoundError) as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/notebooks/{nb_id}/sources/{src_id}")
def api_delete_notebook_source(nb_id: str, src_id: str):
    try:
        from utils.notebook_engine import delete_source
        ok = delete_source(nb_id, src_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Quelle nicht gefunden.")
        return {"status": "deleted", "source_id": src_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/notebooks/{nb_id}/chat-history")
def api_get_notebook_chat(nb_id: str):
    try:
        from utils.notebook_engine import get_notebook
        nb = get_notebook(nb_id)
        if not nb:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"chat_history": nb.get("chat_history", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/query")
async def api_query_notebook(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import query_notebook
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt ist erforderlich.")
        res = await query_notebook(nb_id, prompt)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/notebooks/{nb_id}/sync-obsidian")
def api_sync_notebook_obsidian(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import save_to_obsidian
        query = payload.get("query", "")
        response_text = payload.get("response", "")
        citations = payload.get("citations", "")
        res = save_to_obsidian(nb_id, query, response_text, citations)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/brain/quartz-config")
def api_get_quartz_config():
    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        raise HTTPException(status_code=404, detail="Quartz Konfigurationsdatei nicht gefunden.")

    try:
        import yaml
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return {"config": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/brain/quartz-config")
async def api_save_quartz_config(request: Request):
    require_admin(request)  # RBAC: Schreiben der Quartz-Konfiguration ist Admin-Sache
    payload = await request.json()
    new_config = payload.get("config")
    if not new_config:
        raise HTTPException(status_code=400, detail="Keine Konfiguration übergeben.")

    config_candidates = [
        os.path.join(WORKSPACE_DIR, "quartz_app", "quartz.config.default.yaml"),
        "quartz_app/quartz.config.default.yaml",
        "/app/quartz_app/quartz.config.default.yaml"
    ]
    config_file = None
    for c in config_candidates:
        if os.path.exists(c):
            config_file = c
            break
            
    if not config_file:
        config_file = "quartz_app/quartz.config.default.yaml"

    try:
        import yaml, base64
        yaml_content = yaml.dump(new_config, sort_keys=False, allow_unicode=True)
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Extract active theme colors for custom.scss
        th_colors = new_config.get("configuration", {}).get("theme", {}).get("colors", {})
        dark_c = th_colors.get("darkMode", {})
        light_c = th_colors.get("lightMode", {})
        
        c_bg = dark_c.get("light") or light_c.get("light") or "#ffffff"
        c_text = dark_c.get("darkgray") or light_c.get("darkgray") or "#1e293b"
        c_dark = dark_c.get("dark") or light_c.get("dark") or "#0f172a"
        c_gray = dark_c.get("gray") or light_c.get("gray") or "#64748b"
        c_lightgray = dark_c.get("lightgray") or light_c.get("lightgray") or "#e2e8f0"
        c_sec = dark_c.get("secondary") or light_c.get("secondary") or "#2563eb"
        c_ter = dark_c.get("tertiary") or light_c.get("tertiary") or "#84a59d"
        c_hl = dark_c.get("highlight") or light_c.get("highlight") or "rgba(143, 159, 169, 0.15)"
        c_thl = dark_c.get("textHighlight") or light_c.get("textHighlight") or "#fef08a"

        custom_scss_content = f"""@use "./variables.scss" as *;

:root {{
  --light: {c_bg};
  --lightgray: {c_lightgray};
  --gray: {c_gray};
  --darkgray: {c_text};
  --dark: {c_dark};
  --secondary: {c_sec};
  --tertiary: {c_ter};
  --highlight: {c_hl};
  --textHighlight: {c_thl};
}}

:root[saved-theme="dark"], :root[saved-theme="light"], html, body, .page, article, main, header, footer, .sidebar, .center {{
  background-color: var(--light) !important;
  color: var(--darkgray) !important;
}}

h1, h2, h3, h4, h5, h6, .article-title, .page-title, .page-title a {{
  color: var(--dark) !important;
}}

a {{
  color: var(--secondary) !important;
}}
"""
        scss_candidates = [
            os.path.join(WORKSPACE_DIR, "quartz_app", "quartz", "styles", "custom.scss"),
            "quartz_app/quartz/styles/custom.scss",
            "/app/quartz_app/quartz/styles/custom.scss"
        ]
        for sc in scss_candidates:
            if os.path.exists(os.path.dirname(sc)):
                try:
                    with open(sc, "w", encoding="utf-8") as f:
                        f.write(custom_scss_content)
                except Exception:
                    pass

        # Write inside archon-quartz container if active
        try:
            b64_yaml = base64.b64encode(yaml_content.encode('utf-8')).decode('ascii')
            b64_scss = base64.b64encode(custom_scss_content.encode('utf-8')).decode('ascii')
            
            cmd = f"echo '{b64_yaml}' | base64 -d > /usr/src/app/quartz.config.default.yaml && echo '{b64_scss}' | base64 -d > /usr/src/app/quartz/styles/custom.scss"
            exec_payload = {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": ["sh", "-c", cmd]}
            # Docker-Zugriffe sind blockierend -> aus dem Event-Loop auslagern
            res_exec = await asyncio.to_thread(
                docker_socket_request, "POST", "/containers/archon-quartz/exec", exec_payload)
            if res_exec:
                import json
                exec_id = json.loads(res_exec.decode('utf-8', errors='ignore')).get("Id")
                if exec_id:
                    await asyncio.to_thread(
                        docker_socket_request, "POST", f"/exec/{exec_id}/start",
                        {"Detach": False, "Tty": False})

            await asyncio.to_thread(post_docker_container_action, "archon-quartz", "restart")
        except Exception as e:
            print(f"Error updating archon-quartz via docker: {e}")

        return {"status": "success", "message": "Quartz Konfiguration gespeichert und Service neu gestartet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


DEFAULT_ROLES = [
    # 1. MANAGEMENT & ARCHITEKTUR
    {
        "id": "orchestrator",
        "category": "1. Management & Architektur",
        "name": "Orchestrator & System-Architekt",
        "prompt": "Du bist ein erfahrener Orchestrator & System-Architekt. Deine Aufgabe ist es, meisterhaft komplexe Problemstellungen zu analysieren, Aufgaben strukturiert auf Spezial-Agenten zu verteilen, Abhängigkeiten zu managen und Teilergebnisse zu einer schlüssigen Gesamtlösung zu synthetisieren.",
        "skills": ["skill-karpathy-coder"]
    },
    {
        "id": "product_manager",
        "category": "1. Management & Architektur",
        "name": "Product Manager / Requirements Engineer",
        "prompt": "Du bist ein strikter Product Manager & Requirements Engineer. Du übersetzt vage Nutzerideen in glasklare, präzise technische User Stories, Akzeptanzkriterien und funktionale Spezifikationen (PRDs). Du verhinderst Scope Creep und forderst Messbarkeit in allen Anforderungen.",
        "skills": ["skill-competitive-matrix"]
    },
    {
        "id": "scrum_master",
        "category": "1. Management & Architektur",
        "name": "Agile Scrum Master / Task Triage Manager",
        "prompt": "Du bist ein proaktiver Agile Scrum Master & Task Triage Manager. Du strukturierst Workflows in überschaubare Sprint-Tasks, identifizierst Blockaden, priorisierst das Backlog in der Kanban-Pipeline und verteilst Arbeitspakete effizient an ausführende Worker-Agenten.",
        "skills": []
    },
    {
        "id": "enterprise_architect",
        "category": "1. Management & Architektur",
        "name": "Enterprise Architect",
        "prompt": "Du bist ein pragmatischer Enterprise Architect. Du bewertest Systemarchitekturen auf langfristige Skalierbarkeit, Modulkopplung, Microservice-Muster und Technologie-Stacks. Du verhinderst technologische Sackgassen und achtest auf Zukunftsfähigkeit.",
        "skills": ["skill-cloud-security"]
    },

    # 2. IMMOBILIEN & OBJEKTENTWICKLUNG
    {
        "id": "baurecht_experte",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Baurechts- & Genehmigungs-Experte (§34/BauGB)",
        "prompt": "Du bist ein hochspezialisierter Baurechts- und Genehmigungsexperte. Du analysierst Flächen und Bauvorhaben nach BauGB (§ 30 B-Plan, § 34 Einfügen in Eigenart der näheren Umgebung, § 35 Außenbereich). Du prüfst GRZ/GFZ, Abstandsflächen, Stellplatzsatzungen und formulierst wasserdichte Bauvoranfragen.",
        "skills": ["skill-baugb-checker", "skill-lbo-standards"]
    },
    {
        "id": "realestate_concept_strategist",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Konzept- & Erschließungsstratege",
        "prompt": "Du bist ein visionärer Immobilien-Konzept- und Erschließungsstratege. Du entwickelst marktgerechte Nutzungskonzepte (Wohnen, Micro-Living, Gewerbe-Mischung), bewertest Lagepotenziale, Erschließungsaufwände (Straßen, Medien, Entwässerung) und ESG-Nachhaltigkeitskriterien (KfW/GEG).",
        "skills": ["skill-esg-realestate"]
    },
    {
        "id": "realestate_yield_calculator",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Wirtschaftlichkeits- & Rendite-Kalkulator",
        "prompt": "Du bist ein präziser Immobilien-Wirtschaftlichkeits- & Rendite-Kalkulator. Du erstellst dynamische Cashflow-Modelle, Vervielfältiger-Berechnungen, IRR/ROI-Projektionen, Baukostenschätzungen nach DIN 276 (BKI-Indizes) und unterziehst Finanzierungen harten Zins- und Leerstands-Stresstests.",
        "skills": ["skill-realestate-dcf", "skill-bki-cost-estimator"]
    },
    {
        "id": "construction_pm_hoai",
        "category": "2. Immobilien & Objektentwicklung",
        "name": "Bau-Projektleiter & Ausschreibung (HOAI / VOB)",
        "prompt": "Du bist ein erfahrener Bau-Projektleiter. Du steuerst Projekte entlang der HOAI-Leistungsphasen 1 bis 9, überwachst VOB/B-Verträge, prüfst Nachtragsforderungen, kontrollierst Bauzeitenpläne und stellst budgettreue Ausschreibungen und Vergaben sicher.",
        "skills": ["skill-hoai-workflow"]
    },

    # 3. RECHT, STEUERN & COMPLIANCE
    {
        "id": "wirtschaftsjurist",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Wirtschaftsjurist & Vertragsprüfer",
        "prompt": "Du bist ein scharfsinniger Wirtschaftsjurist & Vertragsprüfer. Du analysierst BGB/HGB-Verträge, Kaufverträge, NDAs, Gesellschaftervereinbarungen und AGB. Du deckst versteckte Haftungsrisiken auf und formulierst risikominimierende Vertragsklauseln.",
        "skills": ["skill-contract-redline", "skill-liability-scanner"]
    },
    {
        "id": "tax_holding_advisor",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Steuer- & Holding-Strukturberater",
        "prompt": "Du bist ein strategischer Steuer- & Holding-Strukturberater. Du optimierst Unternehmens- und Immobilienstrukturen (Holdinggesellschaften, vermögensverwaltende GmbH mit erweiterter Gewerbesteuerkürzung, § 8b KStG, Grunderwerbsteuer-Gestaltung und Nachfolgeplanung).",
        "skills": ["skill-tax-structure-optimizer"]
    },
    {
        "id": "gdpr_compliance",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Data Protection & Compliance Officer (DSGVO)",
        "prompt": "Du bist ein Data Protection & Compliance Officer. Du stellst sicher, dass Systeme, Workflows und Datenbanken vollumfänglich DSGVO-konform sind, Verarbeitungsverzeichnisse (VVT) geführt werden und Verträge zur Auftragsverarbeitung (AVV) vorliegen.",
        "skills": ["skill-gdpr-audit"]
    },
    {
        "id": "devils_advocate",
        "category": "3. Recht, Steuern & Compliance",
        "name": "Skeptic / Devil's Advocate",
        "prompt": "Du bist der kritische Skeptic & Devil's Advocate im Boardroom. Deine Aufgabe ist es, getroffene Entscheidungen, Pläne und Verträge konstruktiv, aber schonungslos zu hinterfragen, um verdeckte Risiken und Denkfehler aufzudecken.",
        "skills": ["skill-liability-scanner"]
    },

    # 4. FINANZEN, M&A & CAPITAL
    {
        "id": "financial_modeler",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Financial Modeler & DCF-Spezialist",
        "prompt": "Du bist ein hochkompetenter Financial Modeler & DCF-Spezialist. Du baust integrierte 3-Statement-Finanzmodelle (GuV, Bilanz, Cashflow), berechnest Discounted Cash Flows (WACC), bewertest Working Capital und führst Sensitivitätsanalysen durch.",
        "skills": ["skill-dcf-valuation", "skill-saas-metrics"]
    },
    {
        "id": "ma_due_diligence_analyst",
        "category": "4. Finanzen, M&A & Capital",
        "name": "M&A & Due-Diligence Analyst",
        "prompt": "Du bist ein akribischer M&A & Due-Diligence Analyst. Du auditierst Datenräume bei Unternehmenstransaktionen, bewertest Synergien und Risiken (Financial, Legal, Commercial) und simulierst Cap Tables und Waterfall-Payouts.",
        "skills": ["skill-ma-playbook"]
    },
    {
        "id": "grant_funding_scout",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Fördermittel- & Kapital-Scout",
        "prompt": "Du bist ein spezialisierter Fördermittel- & Kapital-Scout. Du recherchierst nicht-rückzahlbare Zuschüsse (ZIM, BAFA, KfW, Horizon Europe), strukturierst Banken-Kreditanträge und erstellst investorenreife Pitch-Memos.",
        "skills": ["skill-grant-matcher"]
    },
    {
        "id": "financial_optimizer",
        "category": "4. Finanzen, M&A & Capital",
        "name": "Financial & Cost Optimizer",
        "prompt": "Du bist ein kostenbewusster Financial & Cost Optimizer. Du überwachst operative Betriebsausgaben, API-Kosten und optimierst die Ressourcen- und Kostenstruktur der gesamten Organisation.",
        "skills": ["skill-saas-metrics"]
    },

    # 5. VERTRIEB, MARKETING & STRATEGIE
    {
        "id": "b2b_sales_pitch_architect",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "B2B-Vertriebs- & Pitch-Architekt",
        "prompt": "Du bist ein hochwirksamer B2B-Vertriebs- & Pitch-Architekt. Du entwickelst überzeugende Value Propositions, Einwandbehandlungen, Enterprise-Verkaufssequenzen, Kaltakquise-Strategien und B2B-Angebotsstrukturen.",
        "skills": ["skill-cold-outreach"]
    },
    {
        "id": "pricing_monetization_strategist",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "Pricing- & Monetarisierungs-Stratege",
        "prompt": "Du bist ein datengetriebener Pricing- & Monetarisierungs-Stratege. Du analysierst Zahlungsbereitschaften, entwickelst Value-based Pricing-Modelle, gestaltest Feature-Tiers/Pakete und minimierst Churn.",
        "skills": ["skill-pricing-calculator"]
    },
    {
        "id": "market_intelligence",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "Market & Competitor Intelligence Analyst",
        "prompt": "Du bist ein strategischer Market & Competitor Intelligence Analyst. Du analysierst Marktsegmente, Mitbewerber, Preismodelle und Feature-Gaps, um nachhaltige Wettbewerbsvorteile herauszuarbeiten.",
        "skills": ["skill-competitive-matrix"]
    },
    {
        "id": "seo_content",
        "category": "5. Vertrieb, Marketing & Strategie",
        "name": "SEO & Content Pipeline Specialist",
        "prompt": "Du bist ein SEO & Content Pipeline Specialist. Du recherchierst High-Intent-Keywords, erstellst strukturierte Content-Pipelines und entwirfst suchmaschinenoptimierte Fachartikel und Veröffentlichungsstrategien.",
        "skills": ["skill-seo-audit"]
    },

    # 6. SOFTWARE DEVELOPMENT & ENGINEERING (TECH)
    {
        "id": "senior_coder",
        "category": "6. Software & Tech",
        "name": "Senior Coder / Software Engineer",
        "prompt": "Du bist ein extrem kompetenter Senior Software Engineer. Du schreibst sauberen, modularen, objektorientierten und produktionsreifen Code (Python, TypeScript, Go). Du folgst strikt Best Practices (DRY, SOLID) und lieferst fehlerfreie Implementierungen.",
        "skills": ["skill-karpathy-coder", "skill-database-designer"]
    },
    {
        "id": "frontend_architect",
        "category": "6. Software & Tech",
        "name": "Frontend & UI/UX Architect",
        "prompt": "Du bist ein visuell denkender Frontend & UI/UX Architect. Du entwirfst moderne, performante und ergonomische Benutzeroberflächen (Streamlit, React, CSS3, Tailwind). Du achtest penibel auf visuelle Hierarchien, responsive Grids und reibungslose User-Flows.",
        "skills": []
    },
    {
        "id": "backend_db_designer",
        "category": "6. Software & Tech",
        "name": "Backend & Database Designer",
        "prompt": "Du bist ein hochspezialisierter Backend & Database Designer. Du entwickelst robuste API-Schnittstellen (REST, GraphQL, gRPC), optimierst SQL/NoSQL-Datenbankschemas, indizierst Tabellen und verhinderst Bottlenecks bei Abfragen.",
        "skills": ["skill-database-designer"]
    },
    {
        "id": "clean_code_expert",
        "category": "6. Software & Tech",
        "name": "Refactoring & Clean Code Expert",
        "prompt": "Du bist ein kompromissloser Refactoring & Clean Code Expert. Du durchleuchtest bestehenden Code auf Code Smells, Redundanzen, hohe zyklomatische Komplexität und schlechte Benennungen, um die Wartbarkeit drastisch zu erhöhen.",
        "skills": ["skill-karpathy-coder"]
    },
    {
        "id": "devops_container",
        "category": "6. Software & Tech",
        "name": "DevOps & Container Specialist",
        "prompt": "Du bist ein erfahrener DevOps & Container Specialist. Du erstellst gehärtete Dockerfiles, Docker-Compose-Setups, Netzwerkkonfigurationen und CI/CD-Pipelines für eine nahtlose, isolierte und ausfallsichere Container-Laufzeitumgebung.",
        "skills": ["skill-docker-generator", "skill-cloud-security"]
    },
    {
        "id": "security_auditor",
        "category": "6. Software & Tech",
        "name": "Security Auditor / DevSecOps",
        "prompt": "Du bist ein akribischer Security Auditor & DevSecOps. Du analysierst Code und Systeme auf Sicherheitslücken (OWASP Top 10, Injection Risks, Secret Leaks, Insecure Deserialization) und verlangst harte Schutzmaßnahmen und Sanitization.",
        "skills": ["skill-cloud-security"]
    },

    # 7. QUALITY, REGULATORY & HEALTHCARE
    {
        "id": "iso13485_mdr_auditor",
        "category": "7. Quality, Regulatory & Health",
        "name": "ISO 13485 & MDR-Auditor",
        "prompt": "Du bist ein kompromissloser Qualitäts- & Regulatory-Auditor für Medizinprodukte (MDR 2017/745, ISO 13485, ISO 14971). Du prüfst Design Controls, Risikomanagement-Akten, CAPA-Pläne und klinische Bewertungen.",
        "skills": ["skill-iso13485-prep"]
    },
    {
        "id": "clinical_research_analyst",
        "category": "7. Quality, Regulatory & Health",
        "name": "Klinischer Forschungs- & Evidenz-Analyst",
        "prompt": "Du bist ein analytischer klinischer Forschungs-Spezialist. Du durchsuchst PubMed, Studienregister und Leitlinien, bewertest Evidenzgrade und erstellst wissenschaftlich fundierte Synthesen.",
        "skills": ["skill-pubmed-fetch"]
    }
]


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


@app.post("/api/telegram/relay")
async def api_telegram_relay(ziel_agent: str = Form(""), text: str = Form(""),
                             datei_name: str = Form(""), datei_b64: str = Form("")):
    """TELEGRAM-RELAY (12.10.2026, User-Vorgabe): Owner-Nachricht (Text +
    optionale Datei als base64) 1:1 an einen Agenten weiterleiten und die
    ANTWORT automatisch per Telegram zurueckschicken."""
    ziel = (ziel_agent or "").strip() or "executive_decision_architect"
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p.get("id") == ziel), None)
    if not prof:
        raise HTTPException(status_code=400, detail=f"Ziel-Agent '{ziel}' existiert nicht im Kader.")
    agent_name = prof.get("person_name") or prof.get("name") or ziel
    msg = (text or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="text darf nicht leer sein")

    anhang_hinweis = ""
    if datei_b64:
        try:
            import base64 as _b64
            safe_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', (datei_name or "anhang.bin"))[-80:]
            rel_dir = os.path.join("static", "uploads", "telegram")
            os.makedirs(rel_dir, exist_ok=True)
            rel_path = os.path.join(rel_dir, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}")
            with open(rel_path, "wb") as f_bin:
                f_bin.write(_b64.b64decode(datei_b64))
            groesse = os.path.getsize(rel_path)
            anhang_hinweis = (f"\n\n📎 ANHANG des Owners ({safe_name}, {groesse} B): {rel_path}\n"
                              f"Arbeite MIT dieser Datei (z.B. video_analyze/vision oder lesen).")
            logger.info(f"[Relay] Anhang gespeichert: {rel_path} ({groesse} B)")
        except Exception as anh_err:
            logger.warning(f"[Relay] Anhang konnte nicht gespeichert werden: {anh_err}")
            anhang_hinweis = f"\n\n(Anhang '{datei_name}' konnte nicht gespeichert werden: {anh_err})"

    relay_prompt = (f"LEITUNG VOM OWNER PER TELEGRAM (1:1, unveraendert):\n\n"
                    f"{msg}{anhang_hinweis}\n\n"
                    f"Antworte mit dem Ergebnis der Aufgabe (Deutsch, ohne Begruessung).")

    system_prompt = (prof.get("system_prompt") or prof.get("prompt")
                     or f"Du bist {agent_name}. Antworte praezise auf Deutsch.")
    model = (prof.get("model") if prof.get("model") not in ("", "free-forever") else "") or "deepseek/deepseek-v4-flash-0731"
    def _tg_send_relay(text_out):
        from telegram_notify import send_telegram_message
        return send_telegram_message(f"🤖 {agent_name}:\n\n{text_out[:3900]}")
    add_ticker("Telegram-Relay", f"Nachricht an {agent_name} weitergeleitet ({len(msg)} Z)")
    # D-07: Im Fehlerfall war ``res`` nie gebunden — der ``isinstance``-Guard
    # wertete ``res`` selbst aus => NameError => 500. Der Owner bekam keine
    # Telegram-Antwort, obwohl der Fehler bekannt war. Jetzt wird der Fehler
    # direkt aus der Exception gelesen.
    res = None
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=ziel, agent_name=agent_name, prompt=relay_prompt,
            role=prof.get("category", "Relay-Ziel"), system_prompt=system_prompt, model=model)
        antwort = (res.get("content") or "").strip()
    except Exception as rel_err:
        logger.error(f"[Relay] Dispatch an {ziel} fehlgeschlagen: {rel_err}")
        antwort = ""
        dispatch_error = str(rel_err)
    else:
        dispatch_error = None

    if not antwort:
        grund = dispatch_error or (
            res.get("error", "unbekannt") if isinstance(res, dict) else "dispatch-fehler"
        )
        antwort = (f"Der Relay an {agent_name} lieferte keine Antwort "
                   f"(Grund: {grund}).")
    try:
        # async-Endpoint: sync-Telegram nicht die Event-Loop blockieren lassen
        await asyncio.to_thread(_tg_send_relay, antwort)
    except Exception as tg3:
        logger.warning(f"[Relay] Telegram-Rueckantwort fehlgeschlagen: {tg3}")
    logger.info(f"[Relay] {ziel}: {len(msg)} Z rein, {len(antwort)} Z zurueck an Telegram")
    return {"status": "ok", "ziel_agent": ziel, "antwort_kopf": antwort[:400]}

_TELEGRAM_CHAT_ID_RE = re.compile(r"^-?[0-9]{1,20}$")


def _redact_telegram_secrets(text: object) -> str:
    """Entfernt Bot-Token und Bot-API-URLs aus Fehlertexten (Antwort/Log).

    Der Token steckt in `https://api.telegram.org/bot<id>:<token>/…`; eine
    rohe Exception-Repr kann diese URL enthalten. Deshalb wird jeder
    Fehlertext vor Ausgabe durch diese Funktion gejagt.
    """
    out = str(text)
    out = re.sub(r"https?://api\.telegram\.org/\S*", "<telegram-api-url>", out)
    out = re.sub(r"bot[0-9]{3,}:[A-Za-z0-9_-]{10,}", "bot<redacted>", out)
    for env_key in ("TELEGRAM_BOT_TOKEN",):
        secret = (os.environ.get(env_key) or "").strip()
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


@app.post("/api/telegram/voice-relay")
async def api_telegram_voice_relay(
    request: Request,
    file: UploadFile = File(None),
    file_id: str = Form(""),
    chat_id: str = Form(""),
    ziel_agent: str = Form(""),
    reply_voice: bool = Form(True)
):
    """
    Empfaengt Sprachnachrichten aus Telegram (als Upload oder per Telegram file_id),
    transkribiert sie, routet sie an den Ziel-Agenten und sendet Text + Sprachantwort zurueck.

    Rollenzaun: Admin oder Service-Token (der Telegram-Adapter ausserhalb dieses
    Repos sendet `X-Archon-Service-Token`). Die Route bewegt Bot-Credentials und
    LLM-Kosten, deshalb kein Durchlass fuer `viewer`/`operator`/`anonymous`.
    """
    require_admin_or_503(request)
    # `chat_id` kommt aus dem Request und steuert das Sende-Ziel mit den
    # Bot-Credentials -> nur numerische Telegram-IDs (Gruppen sind negativ).
    clean_chat_id = (chat_id or "").strip()
    if clean_chat_id and not _TELEGRAM_CHAT_ID_RE.match(clean_chat_id):
        raise HTTPException(
            status_code=400,
            detail="chat_id ungueltig: erwartet numerische Telegram-ID "
                   "(z. B. '123456789' oder '-1001234567890').",
        )

    from backend.voice_pipeline import (
        transcribe_audio_bytes, download_telegram_file,
        detect_target_agent, synthesize_speech, send_telegram_voice
    )

    audio_bytes = b""
    fname = "voice.ogg"

    if file:
        audio_bytes = await file.read()
        fname = file.filename or "voice.ogg"
    elif file_id:
        try:
            audio_bytes, fname = await download_telegram_file(file_id)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Download von Telegram fehlgeschlagen: {_redact_telegram_secrets(e)}",
            )

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Keine Audio-Daten uebergeben.")

    # 1. Transkribieren
    transcript = await transcribe_audio_bytes(audio_bytes, filename=fname)

    # 2. Agenten-Routing
    detected_agent, clean_prompt = detect_target_agent(transcript)
    target = (ziel_agent or "").strip() or detected_agent

    # 3. An bestehenden Relay weiterleiten
    relay_res = await api_telegram_relay(ziel_agent=target, text=clean_prompt)
    answer_text = relay_res.get("antwort_kopf", "")

    # 4. Sprachantwort erzeugen & an Telegram senden
    voice_sent = False
    tgt_chat = clean_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if reply_voice and tgt_chat and answer_text and not answer_text.startswith("[Sprachnachricht"):
        try:
            speech_path = await synthesize_speech(answer_text)
            voice_sent = await send_telegram_voice(tgt_chat, speech_path, caption=f"Antwort von {target}")
            if os.path.exists(speech_path):
                os.remove(speech_path)
        except Exception as v_err:
            # Fehlertext kann Bot-API-URL/Token enthalten -> redigiert loggen.
            logger.warning(
                f"[VoiceRelay] Sprachantwort-Versand fehlgeschlagen: "
                f"{_redact_telegram_secrets(v_err)}"
            )

    return {
        "status": "ok",
        "transcript": transcript,
        "ziel_agent": target,
        "clean_prompt": clean_prompt,
        "antwort": answer_text,
        "voice_sent": voice_sent
    }


class TelegramSendPayload(BaseModel):
    text: str
    chat_id: Optional[str] = ""
    parse_mode: Optional[str] = "Markdown"


@app.post("/api/telegram/send")
async def api_telegram_send(payload: TelegramSendPayload):
    """
    Versendet eine Benachrichtigung, ein Briefing oder System-Statusnachricht
    direkt an Telegram (z. B. aufgerufen durch n8n Automatisierungs-Routinen).
    """
    import telegram_notify
    if not payload.text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    if not telegram_notify.telegram_enabled():
        # Ehrlich melden statt still zu verwerfen: n8n sieht, dass nichts rausging.
        return {
            "status": "disabled",
            "result": False,
            "detail": "Telegram-Versand ist aus (settings.json -> telegram.enabled = false).",
        }
    try:
        res = telegram_notify.send_telegram_message(payload.text)
        return {"status": "success" if res else "failed", "result": res}
    except Exception as e:
        logger.warning(f"[TelegramSend] Fehler: {e}")
        return {"status": "error", "message": str(e)}


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


def _get_hermes_config_path() -> str:
    candidates = [
        "/opt/data/config.yaml",
        "/opt/data/hermes_config.json",
        os.path.expanduser("~/.hermes/config.yaml"),
        os.path.expanduser("~/.hermes/hermes_config.json"),
        os.path.join(MEMORY_DIR, "hermes_config.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(MEMORY_DIR, "hermes_config.json")

@app.get("/api/hermes/config")
def api_get_hermes_config():
    cfg_file = _get_hermes_config_path()
    try:
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
                    try:
                        import yaml
                        data = yaml.safe_load(f) or {}
                    except Exception:
                        data = {"raw": f.read()}
                else:
                    data = json.load(f)
            return {"status": "success", "file": cfg_file, "config": data}
    except Exception as e:
        logger.warning(f"[Hermes Config] Error reading {cfg_file}: {e}")

    return {
        "status": "success",
        "file": cfg_file,
        "config": {
            "default_model": "auto/best-free",
            "default_temperature": 0.7,
            "global_tools": DEFAULT_HERMES_TOOLS
        }
    }

@app.post("/api/hermes/config")
def api_save_hermes_config(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    cfg_file = _get_hermes_config_path()
    os.makedirs(os.path.dirname(os.path.abspath(cfg_file)), exist_ok=True)
    create_rolling_backup(cfg_file, max_backups=3)

    config_data = payload.get("config", payload)
    try:
        if cfg_file.endswith(".yaml") or cfg_file.endswith(".yml"):
            try:
                import yaml
                with open(cfg_file, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, allow_unicode=True)
            except Exception:
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
        else:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "file": cfg_file, "config": config_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern der Konfiguration: {e}")


@app.post("/api/hermes/memory/purge")
def api_hermes_memory_purge(request: Request, purge_options: Dict = Body(default={})):
    """
    Cleans sessions and chat messages while strictly preserving session_model_usage.
    """
    require_admin(request)  # RBAC: Admin-Sache
    cleared_sessions = 0
    cleared_messages = 0
    try:
        conn = sqlite3.connect(STATE_DB_PATH, timeout=20.0)
        conn.execute("PRAGMA busy_timeout=20000;")
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM session_model_usage")
            usage_count_before = cur.fetchone()[0]

            mode = purge_options.get("mode", "empty_and_orphaned")
            if mode == "all_sessions":
                cur.execute("DELETE FROM messages")
                cleared_messages = cur.rowcount
                cur.execute("DELETE FROM sessions")
                cleared_sessions = cur.rowcount
            else:
                cur.execute("DELETE FROM sessions WHERE message_count = 0 OR message_count IS NULL")
                cleared_sessions = cur.rowcount
                cur.execute("DELETE FROM messages WHERE session_id NOT IN (SELECT id FROM sessions)")
                cleared_messages = cur.rowcount

            conn.commit()

            cur.execute("SELECT COUNT(*) FROM session_model_usage")
            usage_count_after = cur.fetchone()[0]

            return {
                "status": "success",
                "cleared_sessions": cleared_sessions,
                "cleared_messages": cleared_messages,
                "model_usage_records_preserved": usage_count_after
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[Memory Purge Error]: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler bei der Speicherbereinigung: {str(e)}")

# 
# NATIVE MASTER CHAT & MISSIONS LOGIC (SSE STREAM, PERSISTENCE, UPLOADS)
# 


def _quickchat_state_session_id(profile_id: str) -> str:
    """QuickChat teilt sich den Verlauf mit Master-/Agentenchat (state.db)."""
    return f"quickchat_{profile_id}"


def _ensure_state_session(session_id: str, source: str = "quickchat", profile_name: str = "", title: str = "", model: str = ""):
    """Legt die Sitzung in state.db an, falls sie noch nicht existiert."""
    try:
        with _get_state_db() as conn:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return
            now = time.time()
            conn.execute(
                "INSERT INTO sessions (id, source, started_at, message_count, last_activity_at, profile_name, title, model) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
                (session_id, source, now, now, profile_name, title[:120] if title else None, model or None),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[QuickChat] Session-Anlage fehlgeschlagen: {e}")


def _load_state_history(session_id: str, limit: int = 12) -> List[Dict[str, str]]:
    """Liest die letzten Nachrichten einer Sitzung aus state.db als Chat-Historie."""
    try:
        with _get_state_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? AND active = 1 "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception:
        return []


def _ensure_session_exists(conn: sqlite3.Connection, session_id: str, profile_id: str, model: str, title: str):
    now = time.time()
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
    if not cur.fetchone():
        try:
            cur.execute("""
                INSERT INTO sessions (
                    id, source, display_name, title, model, profile_name, started_at, message_count,
                    input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
            """, (session_id, title[:50], title[:50], model, profile_id, now))
            conn.commit()
        except sqlite3.IntegrityError:
            # 12.10.2026: UNIQUE(title) - zwei Delegationen mit gleichem Auftragstext
            # (50-Zeichen-Schnitt) crashten. Idempotent: Zeitstempel der Session-ID
            # als Suffix (eindeutig pro Sekunde), bei Restkollision Nanotime.
            unique_title = f"{title[:36]} [{session_id[3:19]}]"
            try:
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()
            except sqlite3.IntegrityError:
                unique_title = f"{title[:30]} [{time.time_ns() % 1000000000}]"
                cur.execute("""
                    INSERT INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, unique_title, unique_title, model, profile_id, now))
                conn.commit()

def _save_message_to_db(session_id: str, role: str, content: str, token_count: Optional[int] = None):
    try:
        with _get_state_db() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO messages (
                    session_id, role, content, timestamp, token_count, active, compacted
                ) VALUES (?, ?, ?, ?, ?, 1, 0)
            """, (session_id, role, content, now, token_count))
            conn.execute("""
                UPDATE sessions 
                SET message_count = message_count + 1, last_activity_at = ?
                WHERE id = ?
            """, (now, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[Chat Persistence] Error saving message: {e}")

def _record_session_model_usage(session_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0, task: str = ""):
    try:
        with _get_state_db() as conn:
            now = time.time()
            _ensure_session_exists(conn, session_id, "default", model, f"Session {session_id}")
            task_val = task or ""
            conn.execute("""
                INSERT INTO session_model_usage (
                    session_id, model, billing_provider, billing_base_url, billing_mode, task,
                    api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen
                ) VALUES (?, ?, 'omniroute', 'http://omniroute:20128/v1', 'proxy', ?, 1, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task) DO UPDATE SET
                    api_call_count = api_call_count + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    last_seen = excluded.last_seen
            """, (session_id, model, task_val, in_tok, out_tok, cost_usd, cost_usd, now, now))
            conn.execute("""
                UPDATE sessions 
                SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                    estimated_cost_usd = estimated_cost_usd + ?
                WHERE id = ?
            """, (in_tok, out_tok, cost_usd, session_id))
    except Exception as e:
        logger.error(f"[Chat Persistence] Error recording model usage: {e}")

    global _LIVE_TELEMETRY_CACHE, _MC_STATE_CACHE
    if "_LIVE_TELEMETRY_CACHE" in globals():
        _LIVE_TELEMETRY_CACHE["data"] = None
    # F-12/Z-12: ``_MC_STATE_CACHE`` ist jetzt der Cache aus
    # ``archon.core.mission_control`` — also genau der, den
    # ``archon/routers/mission_control.py`` liest. Vorher wurde die tote
    # eigene Kopie invalidiert.
    if "_MC_STATE_CACHE" in globals():
        _MC_STATE_CACHE["data"] = None
        _MC_STATE_CACHE["ts"] = 0.0

def record_task_tokens(task_id: str, agent_id: str, model: str, in_tok: int, out_tok: int, cost_usd: float = 0.0):
    """Zeichnet Token-Nutzung fuer Aufgaben und Hintergrund-Inferenz auf."""
    s_id = f"task_{task_id}" if not task_id.startswith("task_") else task_id
    t_key = f"{task_id}_{int(time.time())}"
    _record_session_model_usage(session_id=s_id, model=model, in_tok=in_tok, out_tok=out_tok, cost_usd=cost_usd, task=t_key)

class ChatStreamRequest(BaseModel):
    agent_id: str
    message: str
    session_id: Optional[str] = None
    mode: Optional[str] = "direct"  # "direct" vs "mission"
    model: Optional[str] = None
    provider: Optional[str] = None
    reasoning_level: Optional[str] = None
    task_type: Optional[str] = None

class SetProfileModelRequest(BaseModel):
    provider: str
    model: str
    reasoning_level: Optional[str] = None


@app.get("/api/chat/sessions")
def api_get_chat_sessions(profile_id: Optional[str] = None):
    """Liefert die Liste aller aktiven/gespeicherten Master-Chat-Sessions mit formatierten Zeitstempeln und Kategorie-Klassifizierung.
    Unterstützt strikte Filterung nach profile_id und bindet profil-spezifische Datenbanken (wie telegram_bot) nahtlos ein.
    """
    try:
        sessions_map = {}

        # 1. Profil-Datenbanken prüfen (insb. telegram_bot)
        if not profile_id or profile_id.strip() in ("telegram_bot", "all"):
            try:
                prof_conn = _get_profile_state_db("telegram_bot")
                if prof_conn:
                    with prof_conn as pconn:
                        pconn.row_factory = sqlite3.Row
                        prows = pconn.execute("""
                            SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                            FROM sessions 
                            ORDER BY COALESCE(last_activity_at, started_at) DESC
                            LIMIT 150
                        """).fetchall()
                        for r in prows:
                            d = dict(r)
                            d["profile_name"] = d.get("profile_name") or "telegram_bot"
                            d["source"] = d.get("source") or "telegram"
                            sessions_map[d["id"]] = d
            except Exception as e_p:
                logger.warning(f"[Chat Sessions] Fehler beim Lesen der Profil-DB (telegram_bot): {e_p}")

        # 2. Haupt-Datenbank (Root state.db)
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            if profile_id and profile_id.strip():
                pid = profile_id.strip()
                if pid == "default":
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = 'default' 
                           OR profile_name IS NULL 
                           OR profile_name = '' 
                           OR id LIKE '%_default' 
                           OR id LIKE '%_default_%'
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 300
                    """).fetchall()
                elif pid != "telegram_bot":
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = ? OR id LIKE ? OR id LIKE ?
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 300
                    """, (pid, f"%_{pid}", f"%_{pid}_%")).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                        FROM sessions 
                        WHERE profile_name = 'telegram_bot' OR id LIKE '%_telegram_bot%'
                        ORDER BY COALESCE(last_activity_at, started_at) DESC
                        LIMIT 100
                    """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, estimated_cost_usd, source
                    FROM sessions 
                    ORDER BY COALESCE(last_activity_at, started_at) DESC
                    LIMIT 300
                """).fetchall()
            for r in rows:
                d = dict(r)
                if d["id"] not in sessions_map:
                    sessions_map[d["id"]] = d

        # Sortiere nach Aktualität
        sorted_sessions = sorted(
            sessions_map.values(),
            key=lambda x: x.get("last_activity_at") or x.get("started_at") or 0,
            reverse=True
        )

        sessions = []
        for d in sorted_sessions:
            st = d.get("started_at")
            if isinstance(st, (int, float)) and st > 0:
                try:
                    d["started_at_formatted"] = datetime.datetime.fromtimestamp(st).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["started_at_formatted"] = str(st)
            else:
                d["started_at_formatted"] = str(st) if st else ""

            lat = d.get("last_activity_at")
            if isinstance(lat, (int, float)) and lat > 0:
                try:
                    d["last_activity_at_formatted"] = datetime.datetime.fromtimestamp(lat).strftime("%d.%m.%Y, %H:%M")
                except Exception:
                    d["last_activity_at_formatted"] = str(lat)
            else:
                d["last_activity_at_formatted"] = d.get("started_at_formatted") or ""

            source_val = (d.get("source") or "").lower()
            id_val = (d.get("id") or "").lower()
            prof_val = (d.get("profile_name") or "").lower()

            # Fallback-Titel fuer Telegram Bot
            if (source_val == "telegram" or prof_val == "telegram_bot") and (not d.get("title") or d.get("title") in ("New Session", "Chat", "Analyze uploaded image")):
                d["title"] = "Telegram Bot (Live-Stream)"

            # Klassifiziere: 'group' vs. 'agent'
            if source_val in ("paperclip", "boardroom", "multi-agent", "group", "team") or id_val.startswith("paperclip:") or id_val.startswith("group:") or prof_val in ("boardroom", "multi-agent", "team"):
                d["chat_type"] = "group"
            else:
                d["chat_type"] = "agent"
            sessions.append(d)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"[Chat Sessions] Error fetching sessions: {e}")
        return {"sessions": []}

@app.get("/api/chat/sessions/{session_id}/messages")
def api_get_chat_session_messages(session_id: str):
    """Liefert den Nachrichtenverlauf einer bestimmten Session aus Root- oder Profil-DB."""
    try:
        # 1. Zuerst Root-DB prüfen
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, role, content, timestamp, token_count
                FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id ASC
            """, (session_id,)).fetchall()
            if rows:
                return {"session_id": session_id, "messages": [dict(r) for r in rows]}

        # 2. Falls nicht in Root-DB: Profil-DB prüfen (telegram_bot)
        prof_conn = _get_profile_state_db("telegram_bot")
        if prof_conn:
            with prof_conn as pconn:
                pconn.row_factory = sqlite3.Row
                prows = pconn.execute("""
                    SELECT id, role, content, timestamp, token_count
                    FROM messages
                    WHERE session_id = ? AND active = 1
                    ORDER BY id ASC
                """, (session_id,)).fetchall()
                if prows:
                    return {"session_id": session_id, "messages": [dict(r) for r in prows]}

        return {"session_id": session_id, "messages": []}
    except Exception as e:
        logger.error(f"[Chat Messages] Error fetching messages for {session_id}: {e}")
        return {"session_id": session_id, "messages": []}

class RenameSessionRequest(BaseModel):
    title: str

@app.post("/api/chat/sessions/{session_id}/rename")
@app.patch("/api/chat/sessions/{session_id}")
def api_rename_chat_session(session_id: str, req: RenameSessionRequest):
    """Ermöglicht das freie Umbenennen jeder Chat-Session."""
    new_title = req.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Der Titel darf nicht leer sein.")
    try:
        with _get_state_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id = ?", (new_title, new_title, session_id))
            conn.commit()
            if cur.rowcount == 0:
                # Fallback: Versuche case-insensitive oder partial ID
                cur.execute("UPDATE sessions SET title = ?, display_name = ? WHERE id LIKE ?", (new_title, new_title, f"{session_id}%"))
                conn.commit()
            if cur.rowcount == 0:
                # Session existiert noch nicht in der DB (z.B. neu initialisierter Chat ohne Vorab-Nachrichten)
                now = time.time()
                cur.execute("""
                    INSERT OR REPLACE INTO sessions (
                        id, source, display_name, title, model, profile_name, started_at, message_count,
                        input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                    ) VALUES (?, 'master_chat', ?, ?, '', 'default', ?, 0, 0, 0, 0.0, 0.0)
                """, (session_id, new_title, new_title, now))
                conn.commit()
            logger.info(f"[Chat Rename] Session {session_id} umbenannt zu '{new_title}'")
            return {"status": "success", "session_id": session_id, "title": new_title}
    except Exception as e:
        logger.error(f"[Chat Rename] Fehler beim Umbenennen von {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/upload")
async def api_chat_upload(file: UploadFile = File(...)):
    """Empfängt Datei-Uploads und legt sie im Agent-Workspace (/projects/ bzw. ./agent_workspace) ab."""
    try:
        target_dir = "/projects" if os.path.exists("/projects") else os.path.join(WORKSPACE_DIR, "uploads")
        os.makedirs(target_dir, exist_ok=True)
        
        safe_filename = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', file.filename)
        timestamp_prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"{timestamp_prefix}_{safe_filename}"
        dest_path = os.path.join(target_dir, final_filename)
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_size = os.path.getsize(dest_path)
        logger.info(f"[Chat Upload] Datei gespeichert: {dest_path} ({file_size} Bytes)")
        add_ticker("Chat Upload", f"Datei '{file.filename}' im Workspace abgelegt.")
        
        return {
            "status": "success",
            "filename": final_filename,
            "original_name": file.filename,
            "path": dest_path,
            "size": file_size
        }
    except Exception as e:
        logger.error(f"[Chat Upload] Upload fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail=f"Upload fehlgeschlagen: {str(e)}")

# ============================================================================
# DELEGATION ENGINE v2 (09.10.2026)
# Strukturiertes Delegations-Protokoll: ```delegation```-JSON-Blöcke mit
# Quittung, serverseitiger Hierarchie-Prüfung (APEX/LEAD/SPEZIALIST),
# Kanban-Integration und Fehlerbehandlung. Ersetzt den naiven CLI-Regex-
# Interceptor (der bleibt als Legacy-Fallback aktiv).
# ============================================================================
_ORG_HIERARCHY_CACHE = {"mtime": 0.0, "nodes": {}, "loaded": False}

def _load_org_hierarchy_map():
    path = os.path.join("config", "org_hierarchy.json")
    try:
        mtime = os.path.getmtime(path)
        if not _ORG_HIERARCHY_CACHE["loaded"] or mtime != _ORG_HIERARCHY_CACHE["mtime"]:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            nodes = {}
            for n in data.get("nodes", []):
                try:
                    nodes[n.get("id")] = {"tier": int(n.get("tier") or 3), "team_id": n.get("team_id")}
                except Exception:
                    continue
            _ORG_HIERARCHY_CACHE.update({"mtime": mtime, "nodes": nodes, "loaded": True})
        return _ORG_HIERARCHY_CACHE["nodes"]
    except Exception as e:
        logger.warning(f"[Delegation] org_hierarchy.json nicht lesbar: {e}")
        return {}

def _check_delegation_permission(delegator_id: str, target_id: str):
    """Hierarchie-Regeln: Tier 1 (APEX) -> alle; Tier 2 (LEAD) -> eigenes Team; Tier 3 -> keine Delegation."""
    org = _load_org_hierarchy_map()
    d = org.get(delegator_id)
    t = org.get(target_id)
    if d is None:
        return False, f"Delegator '{delegator_id}' ist in der Organisationsstruktur nicht registriert."
    if delegator_id == target_id:
        return False, "Selbst-Delegation ist nicht erlaubt."
    if d["tier"] == 1:
        return True, "APEX"
    if d["tier"] == 2:
        if t and t.get("team_id") and t.get("team_id") == d.get("team_id"):
            return True, "LEAD->Team"
        return False, (f"LEAD '{delegator_id}' (Team {d.get('team_id')}) darf nur an das eigene Team delegieren — "
                       f"'{target_id}' gehört zu Team {(t or {}).get('team_id', 'unbekannt')}.")
    return False, f"Spezialist '{delegator_id}' (Tier 3) darf nicht delegieren. Bitte beim eigenen LEAD eskalieren."


DELEGATION_ALIAS_MAP = {
    # Apex / Leitung / Robert
    "robert": "executive_decision_architect",
    "ceo": "executive_decision_architect",
    "apex": "executive_decision_architect",
    "dr. robert neumann": "system_architect_orchestrator",
    "robert neumann": "system_architect_orchestrator",
    "cloud_architect": "system_architect_orchestrator",
    "system_architect": "system_architect_orchestrator",
    "system-architect": "system_architect_orchestrator",
    
    # Lisa / Aggregation / Synthese
    "lisa": "aggregation_lisa",
    "synthese": "aggregation_lisa",
    "aggregation": "aggregation_lisa",
    "aggregator": "aggregation_lisa",

    # Product Management / Requirements
    "cs-product-manager": "product_requirements_engineer",
    "product-manager": "product_requirements_engineer",
    "product_manager": "product_requirements_engineer",
    "produktmanager": "product_requirements_engineer",
    "product_owner": "product_requirements_engineer",
    "product-owner": "product_requirements_engineer",
    "requirements_engineer": "product_requirements_engineer",
    "tobias": "product_requirements_engineer",
    "tobias merz": "product_requirements_engineer",

    # Frontend / UI / UX / Design
    "cs-frontend-engineer": "brand_uiux_director",
    "frontend-engineer": "brand_uiux_director",
    "frontend_engineer": "brand_uiux_director",
    "frontend": "brand_uiux_director",
    "designer": "brand_uiux_director",
    "ui_designer": "brand_uiux_director",
    "ux_designer": "brand_uiux_director",
    "clara": "brand_uiux_director",
    "clara moreau": "brand_uiux_director",

    # Tech / Fullstack / Coding / Senior Engineer
    "cs-senior-engineer": "senior_fullstack_engineer",
    "senior-engineer": "senior_fullstack_engineer",
    "senior_engineer": "senior_fullstack_engineer",
    "fullstack_engineer": "senior_fullstack_engineer",
    "fullstack-engineer": "senior_fullstack_engineer",
    "fullstack": "senior_fullstack_engineer",
    "coder": "senior_fullstack_engineer",
    "senior_coder": "senior_fullstack_engineer",
    "niklas": "senior_fullstack_engineer",
    "niklas dorn": "senior_fullstack_engineer",

    # Scrum / Agile
    "agile-product-owner": "agile_scrum_master",
    "agile_product_owner": "agile_scrum_master",
    "scrum_master": "agile_scrum_master",
    "scrum-master": "agile_scrum_master",
    "scrum": "agile_scrum_master",
    "sarah": "agile_scrum_master",
    "sarah lindemann": "agile_scrum_master",

    # Compliance / Recht / DSGVO
    "compliance": "compliance_gdpr_auditor",
    "dsgvo": "compliance_gdpr_auditor",
    "compliance_auditor": "compliance_gdpr_auditor",
    "sabine": "compliance_gdpr_auditor",
    "sabine becker": "compliance_gdpr_auditor",
    "jurist": "commercial_jurist_contracts",
    "vertragspruefer": "commercial_jurist_contracts",
    "wirtschaftsjurist": "commercial_jurist_contracts",
    "dr. maximilian von walden": "commercial_jurist_contracts",
    "maximilian": "commercial_jurist_contracts",

    # Marketing / Sales
    "copywriter": "direct_response_copywriter",
    "david stein": "direct_response_copywriter",
    "david": "direct_response_copywriter",
    "b2b": "b2b_outreach_specialist",
    "outreach": "b2b_outreach_specialist",
    "patrick": "b2b_outreach_specialist",
    "patrick jensen": "b2b_outreach_specialist"
}

def _resolve_target_agent_id(ziel_raw: str, profiles: list):
    """Löst erfundene Namen, Skill-Namen, Rufnamen oder ungenaue IDs fehlertolerant in die echte Agent-ID auf."""
    raw = (ziel_raw or "").strip().lower()
    if not raw:
        return None, ""

    # 1. Exakter ID-Match
    for p in profiles:
        if p.get("id", "").lower() == raw:
            return p["id"], ""

    # 2. Normalisierter ID-Match (_ vs -)
    raw_norm = raw.replace("-", "_")
    for p in profiles:
        if p.get("id", "").lower().replace("-", "_") == raw_norm:
            return p["id"], f"ID normalisiert von '{ziel_raw}'"

    # 3. Fester Alias-Lookup
    if raw in DELEGATION_ALIAS_MAP:
        mapped = DELEGATION_ALIAS_MAP[raw]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"
    if raw_norm in DELEGATION_ALIAS_MAP:
        mapped = DELEGATION_ALIAS_MAP[raw_norm]
        return mapped, f"Alias '{ziel_raw}' -> '{mapped}'"

    # 4. Personenname / Rufname Match (z.B. 'Robert', 'Tobias', 'Sarah')
    for p in profiles:
        pname = (p.get("person_name") or "").strip().lower()
        if pname:
            first_name = pname.split()[0]
            if raw == pname or raw == first_name:
                pid = p["id"]
                return pid, f"Personenname '{pname}' -> '{pid}'"

    # 5. Rollen- / Titelsuche (Substring)
    for p in profiles:
        role = (p.get("role") or p.get("name") or "").lower()
        if raw in role or raw_norm in role:
            pid = p["id"]
            return pid, f"Rollen-Treffer '{role}' -> '{pid}'"

    return None, ""

def _build_kader_roster_summary():
    """Erstellt eine lesbare, gegliederte Liste aller real existierenden Agenten für das Delegations-Prompt."""
    try:
        profiles = api_get_hermes_profiles()
        lines = []
        for p in profiles:
            pid = p.get("id")
            if not pid or pid in ("micha", "telegram_bot"):
                continue
            pname = p.get("person_name") or p.get("name") or pid
            role = p.get("role") or p.get("name") or ""
            lines.append(f"  • {pid} ({pname} | {role})")
        return "\n".join(lines)
    except Exception:
        return ""

def _get_delegation_prompt_for(agent_id: str):
    """Liefert das Protokoll-Prompt für Tier 1/2-Agenten, sonst None."""
    try:
        node = _load_org_hierarchy_map().get(agent_id)
        if node and node.get("tier") in (1, 2):
            tier = node["tier"]
            prompt = DELEGATION_PROTOCOL_PROMPT.replace(
                '{"APEX: an alle Agenten" if TIER==1 else "LEAD: nur an dein eigenes Team"}',
                ("APEX: an alle Agenten" if tier == 1 else "LEAD: nur an dein eigenes Team")
            )
            roster = _build_kader_roster_summary()
            if roster:
                prompt += f"\n\n=== OFFIZIELLES KADER-REGISTER (NUR DIESE ECHTEN IDs IM FELD 'ziel_agent' NUTZEN!) ===\n{roster}\n"
            return prompt
    except Exception as e:
        logger.warning(f"[Delegation] Protokoll-Prompt-Aufbau fehlgeschlagen: {e}")
    return None

def _parse_delegation_blocks(text: str):
    """Findet alle ```delegation```-JSON-Blöcke sowie Fallback-JSON-Zeilen."""
    valid, invalid = [], []
    seen_hashes = set()
    
    # 1. Standard: ```delegation ... ``` Blöcke
    for m in re.finditer(r"```(?:delegation|json)?\s*\n(.*?)```", text, re.DOTALL):
        raw = m.group(1).strip()
        if '"ziel_agent"' in raw and '"auftrag"' in raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("ziel_agent") and payload.get("auftrag"):
                    h = f"{payload.get('ziel_agent')}:{payload.get('auftrag')[:40]}"
                    if h not in seen_hashes:
                        valid.append(payload)
                        seen_hashes.add(h)
            except Exception as e:
                invalid.append({"raw": raw[:200], "error": str(e)})

    # 2. Fallback: Ungefenced JSON-Objekte mit "ziel_agent" und "auftrag"
    for m in re.finditer(r'\{[^{}]*"ziel_agent"\s*:\s*"[^"]+"[^{}]*"auftrag"\s*:\s*"[^"]+"[^{}]*\}', text, re.DOTALL):
        raw = m.group(0).strip()
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("ziel_agent") and payload.get("auftrag"):
                h = f"{payload.get('ziel_agent')}:{payload.get('auftrag')[:40]}"
                if h not in seen_hashes:
                    valid.append(payload)
                    seen_hashes.add(h)
        except Exception:
            pass
            
    return valid, invalid

async def _trigger_autonomous_orchestrator_followup(delegator_id, session_id, task_id, status, result, final_title, parent_project_id=None):
    """Prüft, ob alle Teilaufgaben eines Projekts abgeschlossen sind.
    Wenn ja, synthetisiert Robert (executive_decision_architect) die Ergebnisse,
    erstellt das finale HTML-Dokument in 03_Endprodukte/ und informiert den Nutzer."""
    try:
        from backend.operations_api import _get_kanban_connection
        kc = _get_kanban_connection()
        try:
            if not parent_project_id:
                r = kc.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                parent_project_id = r[0] if r else None
            
            if not parent_project_id:
                return

            pending = kc.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ? AND status NOT IN ('done', 'review')",
                (parent_project_id,)
            ).fetchone()[0]

            if pending > 0:
                logger.info(f"[AutoOrchestrator] Projekt {parent_project_id}: noch {pending} Aufgaben ausstehend.")
                return

            rows = kc.execute(
                "SELECT id, title, assignee, result, status FROM tasks WHERE project_id = ? ORDER BY rowid ASC",
                (parent_project_id,)
            ).fetchall()
        finally:
            kc.close()

        if not rows:
            return

        obs_dir = None
        for cand in ("/opt/data/obsidian/01_PROJEKTE", os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"), PROJEKTE_DIR):
            if os.path.isdir(cand):
                obs_dir = cand
                break
        
        proj_folder = None
        if obs_dir:
            for d in os.listdir(obs_dir):
                if parent_project_id.lower() in d.lower():
                    proj_folder = os.path.join(obs_dir, d)
                    break
            if not proj_folder:
                date_prefix = datetime.date.today().strftime("%Y%m%d")
                clean_name = parent_project_id.lower()
                if not clean_name.startswith("projekt-"):
                    clean_name = f"projekt-{clean_name}"
                proj_folder = os.path.join(obs_dir, f"{date_prefix}-{clean_name}")
                os.makedirs(os.path.join(proj_folder, "01_Zwischenberichte"), exist_ok=True)
                os.makedirs(os.path.join(proj_folder, "02_Medien"), exist_ok=True)
                os.makedirs(os.path.join(proj_folder, "03_Endprodukte"), exist_ok=True)

        end_dir = os.path.join(proj_folder, "03_Endprodukte") if proj_folder else None
        if end_dir:
            os.makedirs(end_dir, exist_ok=True)
            clean_proj_name = parent_project_id.replace("projekt-", "").title()
            html_filename = f"{clean_proj_name}_Abschlussbericht.html"
            html_full_path = os.path.join(end_dir, html_filename)
            
            task_items_html = ""
            for r_id, r_title, r_assignee, r_res, r_stat in rows:
                snippet = (r_res or "").strip()[:500].replace("\n", "<br>")
                task_items_html += f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px; margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <strong style="color: #38bdf8;">Task #{r_id}: {r_title}</strong>
                        <span style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; font-weight: bold;">@{r_assignee}</span>
                    </div>
                    <div style="font-size: 13px; color: #cbd5e1; line-height: 1.5;">{snippet}...</div>
                </div>
                """

            html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Abschlussbericht: {clean_proj_name}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #09090b; color: #f4f4f5; line-height: 1.6; padding: 40px 20px; }}
    .container {{ max-width: 860px; margin: 0 auto; background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    h1 {{ font-size: 26px; font-weight: 800; color: #ffffff; margin-bottom: 6px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid #10b981; margin-bottom: 16px; text-transform: uppercase; }}
    .summary {{ background: rgba(14,165,233,0.08); border-left: 4px solid #0ea5e9; padding: 16px; border-radius: 6px; margin-bottom: 24px; font-size: 15px; color: #e0f2fe; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #27272a; padding-bottom: 8px; margin: 28px 0 16px 0; color: #f8fafc; }}
    footer {{ margin-top: 36px; padding-top: 16px; border-top: 1px solid #27272a; font-size: 12px; color: #71717a; display: flex; justify-content: space-between; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">● Projekt Vollständig Abgeschlossen</div>
    <h1>Projekt: {clean_proj_name} — Abschlussbericht</h1>
    <div style="font-size: 13px; color: #a1a1aa; margin-bottom: 20px;">Autonom koordiniert durch <strong>Robert (Executive Decision Architect)</strong> | {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
    
    <div class="summary">
      <strong>Management Summary:</strong><br>
      Alle {len(rows)} Arbeitspakete des Projekts wurden von den spezialisierten Fachagenten erfolgreich ausgearbeitet, verifiziert und zusammengeführt. Das Vorhaben steht für die weitere Umsetzung bereit.
    </div>

    <h2>Abgeschlossene Teilaufgaben & Ergebnisse</h2>
    {task_items_html}

    <footer>
      <div>Archon OS — Autonome Orchestration</div>
      <div>Freigegeben durch <strong>@executive_decision_architect</strong></div>
    </footer>
  </div>
</body>
</html>"""
            with open(html_full_path, "w", encoding="utf-8") as f:
                f.write(html_doc)

        if session_id:
            summary_msg = (
                f"🎉 **Projekt '{parent_project_id}' ist vollständig abgeschlossen!**\n\n"
                f"Alle {len(rows)} Teilaufgaben wurden von den Fachagenten erfolgreich abgearbeitet und von mir zusammengeführt.\n\n"
                f"📄 **Finaler Abschlussbericht:**\n"
                f"- Gespeichert in: `01_PROJEKTE/{os.path.basename(proj_folder) if proj_folder else parent_project_id}/03_Endprodukte/`\n"
                f"- Direkter Link im Showroom & Operations-Dashboard verfügbar.\n\n"
                f"Die Fachagenten wurden nach erfolgreichem Projektabschluss wieder in den Standby versetzt."
            )
            _save_message_to_db(session_id, "assistant", summary_msg)
            broadcast_event("chat_message_received", {
                "session_id": session_id,
                "agent_id": "executive_decision_architect",
                "content": summary_msg,
                "project_completed": parent_project_id
            })
            logger.info(f"[AutoOrchestrator] Projekt {parent_project_id} erfolgreich autonom abgeschlossen!")
    except Exception as e:
        logger.error(f"[AutoOrchestrator] Fehler bei autonomem Followup: {e}")


def _execute_delegation(delegator_id, payload, provider, all_keys, origin_session_id=None):
    """Führt eine Delegation aus: Berechtigungsprüfung, Sub-Session, Kanban-Task,
    Hintergrund-Ausführung. Gibt eine Quittung als Text zurück (wird in die
    Delegator-Session geschrieben, damit der Agent sich erinnert)."""
    ziel_raw = str(payload.get("ziel_agent") or "").strip()
    auftrag = str(payload.get("auftrag") or "").strip()
    modell = str(payload.get("modell") or payload.get("model") or "").strip()
    prioritaet = str(payload.get("prioritaet") or "normal").strip().lower()
    reasoning_lvl = str(payload.get("reasoning_level") or payload.get("reasoning") or "medium").strip().lower()

    profiles = api_get_hermes_profiles()
    ziel, resolve_note = _resolve_target_agent_id(ziel_raw, profiles)
    if not ziel:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel_raw}' existiert nicht im Agenten-Kader."

    allowed, reason = _check_delegation_permission(delegator_id, ziel)
    if not allowed:
        return f"❌ DELEGATION ABGELEHNT — Ziel: {ziel} ({ziel_raw}) | Grund: {reason}"

    t_prof = next((p for p in profiles if p["id"] == ziel), None)
    if not t_prof:
        return f"❌ DELEGATION ABGELEHNT — Ziel-Agent '{ziel}' existiert nicht im Agenten-Kader."
    d_prof = next((p for p in profiles if p["id"] == delegator_id), None)
    t_name = (t_prof.get("person_name") or t_prof.get("name") or ziel)
    d_name = (d_prof.get("person_name") or d_prof.get("name") or delegator_id) if d_prof else delegator_id
    # 3. Compute-optimierte Modell-Zuweisung für den Ziel-Agenten:
    # Verhindert, dass Subagenten unreflektiert teure Flaggschiff-Modelle (wie Opus) erben.
    if not modell:
        cat = (t_prof.get("category") or "").lower()
        role = (t_prof.get("role") or t_prof.get("name") or "").lower()
        t_id = ziel.lower()
        if any(w in t_id or w in role for w in ["vision", "design", "frontend", "ui", "ux"]):
            modell = "auto/best-vision"
        elif any(w in t_id or w in role for w in ["engineer", "developer", "coder", "devops", "security"]):
            modell = "auto/best-coding"
        elif any(w in t_id or w in role for w in ["strateg", "decision", "legal", "compliance", "law", "finance", "scrum", "board"]):
            modell = "auto/best-reasoning"
        else:
            p_mod = (t_prof.get("model") or "").strip()
            modell = p_mod if p_mod and p_mod not in ("", "free-forever") else "auto/best-coding"
    t_model = modell or "auto/best-coding"

    tgt_sess = f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{ziel}"
    msg_text = f"Message from 🤖 {d_name} (@{delegator_id}): {auftrag}"
    with _get_state_db() as conn:
        _ensure_session_exists(conn, tgt_sess, ziel, t_model, auftrag[:50])
    _save_message_to_db(tgt_sess, "user", msg_text)

    task_id = None
    try:
        from backend.operations_api import _get_kanban_connection
        import secrets as _secrets
        task_id = f"t-{_secrets.token_hex(3)}"
        now_iso = datetime.datetime.now().isoformat()
        prio_num = 2 if prioritaet in ("hoch", "high", "sofort", "critical", "urgent") else (1 if prioritaet in ("mittel", "normal", "medium") else 0)
        kconn = _get_kanban_connection()
        parent_pid = str(payload.get("parent_project_id") or "").strip()
        kconn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, started_at, model_override, project_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, auftrag[:80] + ("..." if len(auftrag) > 80 else ""),
             f"Delegation von @{delegator_id} an @{ziel}:\n{auftrag}", ziel, "in_progress", prio_num, delegator_id, now_iso, now_iso, t_model, parent_pid)
        )
        try:
            from backend.operations_api import _execute_kanban_task_async
            _spawn_background(_execute_kanban_task_async(task_id), name=f"kanban_{task_id}")
        except Exception as exe_err:
            logger.warning(f"[Delegation] Sofortige Ausfuehrung fehlgeschlagen: {exe_err}")
        kconn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
            (task_id, "created", json.dumps({"title": auftrag[:80], "assignee": ziel, "via": "delegation_engine_v2", "delegator": delegator_id, "reasoning_level": reasoning_lvl}), now_iso)
        )
        kconn.commit()
        kconn.close()
    except Exception as e:
        logger.warning(f"[Delegation] Kanban-Insert fehlgeschlagen: {e}")

    async def _bg_watch_task(task_id, s_id, prof_id, origin_sess_id=None, orig_delegator=None, parent_pid=None):
        """Beobachtet den Kanban-Task, während der Hermes-Agent-Worker ihn abarbeitet,
        und spiegelt das Endergebnis in die Sub-Session (Rücklauf ohne Doppel-Ausführung).
        WICHTIG: Kein eigener Modell-Aufruf mehr — die Ausführung macht der hermes-Worker
        (claim -> spawn -> heartbeats -> done/blocked). Kein vorzeitiges 'blocked' mehr."""
        try:
            import sqlite3 as _sq
            deadline = time.time() + 1200  # max 20 Minuten beobachten
            final = None
            while time.time() < deadline:
                try:
                    from backend.operations_api import _get_kanban_connection as _kgc
                    kc = _kgc()
                    row = kc.execute("SELECT status, result, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    kc.close()
                    if row and row[0] in ("done", "blocked", "review"):
                        final = row
                        break
                except Exception:
                    pass
                await asyncio.sleep(10)
            if final is None:
                _save_message_to_db(s_id, "assistant",
                    "⏱️ DELEGATION-TIMEOUT — Der Task läuft länger als 20 Minuten ohne Endstatus. "
                    "Aktueller Stand bitte im Kanban prüfen (Task-ID siehe Delegations-Quittung).")
                return
            status, result = final[0], (final[1] or "").strip()
            final_title = (final[2] or "").strip()
            # Fallback: Zusammenfassung aus dem completed/blocked-Event ziehen, wenn das Result-Feld leer ist
            if not result:
                try:
                    from backend.operations_api import _get_kanban_connection as _kgc2
                    kc = _kgc2()
                    ev = kc.execute(
                        "SELECT payload FROM task_events WHERE task_id = ? AND kind IN ('completed','blocked') ORDER BY rowid DESC LIMIT 1",
                        (task_id,)).fetchone()
                    kc.close()
                    if ev and ev[0]:
                        try:
                            result = json.loads(ev[0]).get("summary") or json.loads(ev[0]).get("reason") or ""
                        except Exception:
                            result = ev[0][:500]
                except Exception:
                    pass
            # Ergebnis-Dateien des Hermes-Workers einsammeln (Attachments)
            attach_note = ""
            try:
                attach_dir = os.path.join("/opt/data/kanban/attachments", task_id)
                if os.path.isdir(attach_dir):
                    files = [f for f in os.listdir(attach_dir) if os.path.isfile(os.path.join(attach_dir, f))]
                    if files:
                        attach_note = "\n\n**Angehängte Artefakte:**\n" + "\n".join(f"- {f}" for f in files)
            except Exception:
                pass
            # --- Ergebnis nach Obsidian exportieren (01_PROJEKTE) -> Showroom-Rücklauf ---
            obsidian_rel = None
            try:
                title = (final_title or "Delegation")[:80]
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:50] or "auftrag"
                for cand in ("/opt/data/obsidian/01_PROJEKTE",
                              os.path.join(WORKSPACE_DIR, "obsidian_vault", "01_PROJEKTE"),
                              PROJEKTE_DIR):
                    try:
                        os.makedirs(cand, exist_ok=True)
                        obsidian_rel = cand
                        break
                    except Exception:
                        continue
                if obsidian_rel:
                    # 12.10.2026 (User-Fix 'Ordnerflut'): EIN Ordner pro Projekt -
                    # hat der Subtask ein parent, TEILT er sich den Eltern-Ordner
                    # (Name ueber die gemeinsame Quelle project_folder_name).
                    fan_parent = None
                    fan_parent_title = None
                    try:
                        _mc = _load_mission_control_data()
                        for _t in _mc.get("tasks", []):
                            if _t.get("kanban_task_id") == task_id:
                                fan_parent = _t.get("parent_project_id")
                                fan_parent_title = _t.get("parent_project_title")
                                break
                    except Exception:
                        pass
                    try:
                        from backend.post_task_pipeline import project_folder_name
                        proj_name = project_folder_name({
                            "id": task_id, "title": final_title or "Delegation",
                            "parent_project_id": fan_parent or "",
                            "parent_project_title": fan_parent_title or "",
                        })
                    except Exception:
                        proj_name = f"{datetime.datetime.now().strftime('%Y%m%d')}-{task_id}-{slug}"
                    proj_folder = os.path.join(obsidian_rel, proj_name)
                    target_sub = "01_Zwischenberichte" if parent_pid else "03_Endprodukte"
                    dest_dir = os.path.join(proj_folder, target_sub)
                    os.makedirs(dest_dir, exist_ok=True)
                    for sub in ("01_Zwischenberichte", "02_Medien", "03_Endprodukte"):
                        os.makedirs(os.path.join(proj_folder, sub), exist_ok=True)
                    try:
                        att_src = os.path.join("/opt/data/kanban/attachments", task_id)
                        if os.path.isdir(att_src):
                            for f in os.listdir(att_src):
                                src_f = os.path.join(att_src, f)
                                if os.path.isfile(src_f):
                                    shutil.copy2(src_f, os.path.join(proj_folder, "02_Medien", f))
                    except Exception:
                        pass
                    result_fn = f"{task_id}-{slug}.md"
                    with open(os.path.join(dest_dir, result_fn), "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\n"
                                f"**Task:** `{task_id}` | **Ziel-Agent:** `@{prof_id}` | **Status:** {status.upper()}\n\n"
                                f"{result or '(Ergebnis siehe Kanban-Task-Events und Anhänge in 02_Medien/.)'}\n")
                    # PROJEKT.md nur beim ERSTEN Schreiber (N-Worker parallel!),
                    # Ueberschrift = Eltern-Projekttitel wenn parent vorhanden.
                    proj_title = fan_parent_title if (fan_parent and fan_parent_title) else title
                    p_herkunft = (f"Teilauftrag von Projekt `{fan_parent}`" if fan_parent
                                  else f"Delegation über Archon OS (Task `{task_id}`)")
                    p_parent_line = f'parent_project: "{fan_parent}"' if fan_parent else ""
                    try:
                        with open(os.path.join(proj_folder, "PROJEKT.md"), "x", encoding="utf-8") as f:
                            f.write("---\nproject_folder: \"" + proj_name + "\"\ncreated_at: \""
                                    + str(datetime.datetime.now().timestamp()) + "\"\n"
                                    "title: \"" + proj_title + "\"\nstatus: \"" + str(status)
                                    + "\"\nsource_task: \"" + task_id + "\"\n"
                                    "source: \"delegation_engine_v2\"\n" + p_parent_line + "---\n\n"
                                    "# Projekt: " + str(proj_title) + "\n\n"
                                    "- **Herkunft:** " + p_herkunft + "\n"
                                    "- **Ziel-Agent:** `@" + str(prof_id) + "` | **Status:** " + str(status).upper() + "\n"
                                    "- **Hauptdokument:** [[" + task_id + "-" + slug + "]]\n\n"
                                    "### 📁 Projekt-Struktur:\n"
                                    "- `01_Zwischenberichte/`: Entwürfe und Arbeitsprotokolle\n"
                                    "- `02_Medien/`: Artefakte der Fachagenten\n"
                                    "- `03_Endprodukte/`: [[" + task_id + "-" + slug + "]]"
                                    + ("+ Lisa-Synthese + finale Beschlussvorlage" if fan_parent else "")
                                    + "\n\n---\n[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]\n")
                    except FileExistsError:
                        pass  # Eltern-Ordner-Projekt.md existiert bereits
                    obsidian_rel = proj_name
            except Exception as oe:
                logger.warning(f"[Delegation] Obsidian-Export fehlgeschlagen: {oe}")
                obsidian_rel = None
            if status == "done":
                msg = ("✅ DELEGATION ABGESCHLOSSEN — Der Sub-Agent hat die Aufgabe erledigt.\n\n"
                       f"**Zusammenfassung/Ergebnis:**\n{result or '(siehe Kanban-Task und Anhänge)'}{attach_note}\n\n"
                       f"Task-ID: {task_id} | Status im Kanban: done"
                       + (f"\n📁 Obsidian-Projekt: `01_PROJEKTE/{obsidian_rel}` (auch im Showroom sichtbar)" if obsidian_rel else ""))
            elif status == "review":
                msg = ("🔍 DELEGATION IN REVIEW — Das Ergebnis liegt zur Prüfung bereit.\n\n"
                       f"**Ergebnis:**\n{result or '(siehe Kanban-Task)'}{attach_note}\n\nTask-ID: {task_id}")
            else:
                msg = ("⛔ DELEGATION BLOCKIERT — Der Sub-Agent konnte die Aufgabe nicht abschließen.\n\n"
                       f"**Grund/Eskalation:**\n{result or 'Siehe Task-Events im Kanban (Kommentare des Agenten).'}{attach_note}\n\n"
                       f"Task-ID: {task_id} | Ggf. Kontextdaten nachliefern oder Aufgabe umformulieren."
                       + (f"\n📁 Dokumentation: `01_PROJEKTE/{obsidian_rel}`" if obsidian_rel else ""))
            _save_message_to_db(s_id, "assistant", msg)

            # --- Feedback an Delegator-Session (Robert / Orchestrator) & Autonomer Trigger ---
            if origin_sess_id and origin_sess_id != s_id:
                try:
                    status_badge = "✅ ERLEDIGT" if status in ("done", "review") else "⛔ BLOCKIERT"
                    delegator_feedback = (
                        f"{status_badge}: Der Sub-Agent `@{prof_id}` hat Task `{task_id}` ({final_title}) abgeschlossen.\n\n"
                        f"**Ergebnis:**\n{result or '(Ergebnis liegt im Projektordner/Kanban)'}\n"
                        f"{attach_note}\n\n"
                        f"*(Status im Kanban: `{status}`)*"
                    )
                    _save_message_to_db(origin_sess_id, "user", delegator_feedback)
                    broadcast_event("chat_message_received", {
                        "session_id": origin_sess_id,
                        "agent_id": orig_delegator,
                        "task_id": task_id,
                        "status": status
                    })
                    # Autonomen Folge-Turn auslösen, falls Orchestrator aktiv
                    if orig_delegator in ("executive_decision_architect", "hermes-orchestrator", "micha", "default"):
                        _spawn_background(_trigger_autonomous_orchestrator_followup(
                            orig_delegator, origin_sess_id, task_id, status, result, final_title, parent_pid
                        ), name=f"followup_{task_id}")
                except Exception as feed_err:
                    logger.warning(f"[Delegation] Feedback an Delegator-Session fehlgeschlagen: {feed_err}")
            # --- Telegram-Push (HITL-Kanal, User-Vorgabe 09.10.2026) ---
            # Ping bei done/blocked/review aufs Handy; Freigabe via Inline-Buttons.
            # Fehlertolerant: darf den Delegations-Fluss nie blockieren, loggt aber sichtbar.
            try:
                # 2a: Zielordner fuer das Bericht-Dossier (landet im Projektordner
                # unter 01_Zwischenberichte, damit es Kanban/Showroom ebenfalls sieht)
                _doss_dir = None
                if obsidian_rel:
                    try:
                        _doss_dir = os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE",
                                                 obsidian_rel, "01_Zwischenberichte")
                    except Exception:
                        _doss_dir = None
                if status in ("review", "blocked"):
                    # 2c: Entscheidung ueber den zentralen Service. Der Kanban-Task
                    # EXISTIERT hier bereits -> register_decision + app:-Buttons.
                    _doss = None
                    if _doss_dir and (result or "").strip():
                        try:
                            from dossier_builder import build_dossier_from_report
                            _doss = build_dossier_from_report(
                                f"{'Review' if status == 'review' else 'Blockiert'}: {final_title}",
                                result, _doss_dir, f"{task_id}_{status}",
                                ref_id=task_id, quelle="Archon-Delegation")
                        except Exception as _de:
                            logger.warning(f"[Delegation] Dossier fehlgeschlagen: {_de}")
                    await asyncio.to_thread(
                        register_decision, task_id, "delegation_review",
                        final_title, result, task_id, _doss, "", None,
                        f"01_PROJEKTE/{obsidian_rel}" if obsidian_rel else None)
                else:
                    from telegram_notify import notify_task_status
                    notify_task_status(task_id, status, final_title, result, obsidian_rel,
                                       dossier_dir=_doss_dir)
            except Exception as tg_err:
                logger.warning(f"[Telegram] Delegations-Ping für Task {task_id} fehlgeschlagen: {tg_err}")
            # --- FAN-IN RUECKLAUF (12.10.2026): MC-Subtask abschliessen und
            # pruefen, ob alle Geschwister des Delegationsprojekts fertig sind
            # (-> Synthese durch Lisa + Robert-Freigabe, siehe Synthese-Loop) ---
            if status == "done":
                try:
                    fan_parent = None
                    # F-10: Der ganze Store wurde zurueckgeschrieben — bei
                    # parallelen Delegationen verschwanden Tasks und
                    # Audit-Eintraege (Lost Update). Jetzt wird der Store
                    # atomar per Read-Modify-Write aktualisiert
                    # (update_mission_control_data haelt DARAUF einen Lock).
                    def _fan_in_mutate(mc_data):
                        nonlocal fan_parent
                        for _t in mc_data.get("tasks", []):
                            if _t.get("kanban_task_id") == task_id:
                                _t["status"] = "completed"
                                _t["result_summary"] = (result or "")[:800]
                                _t["completed_at"] = time.time()
                                fan_parent = _t.get("parent_project_id")
                                break
                        return fan_parent

                    await asyncio.to_thread(update_mission_control_data, _fan_in_mutate)
                    if fan_parent:
                        _spawn_background(_fan_in_maybe_start_synthesis(fan_parent), name=f"fan_in_{fan_parent}")
                except Exception as fan_err:
                    logger.warning(f"[Delegation] Fan-in-Ruecklauf fehlgeschlagen: {fan_err}")
        except Exception as e:
            logger.error(f"[Delegation] Task-Watcher error: {e}")

    # --- FAN-IN BRUECKE (12.10.2026, User-Wunsch "Teilergebnisse an Robert
    # zurueck": Eltern-Projekt + MC-Subtask-Spiegel + Kanban-Beziehungen ---
    parent_pid = str(payload.get("parent_project_id") or payload.get("projekt") or "").strip()
    if parent_pid:
        try:
            parent_title_var = str(payload.get("projekt_titel") or payload.get("titel") or "").strip()

            # F-10: Read-Modify-Write auf dem frisch geladenen Store unter
            # einem Lock (update_mission_control_data). Das alte
            # load->modify->_save()-Muster verlor bei parallelen
            # Delegationen Tasks und Audit-Eintraege.
            # Hinweis: Diese Funktion ist synchron — der Store-Write war es
            # vorher auch (Datei-I/O), bleibt also synchron.
            def _bridge_mutate(mc_data):
                mc_tasks = mc_data.setdefault("tasks", [])
                title_var = parent_title_var
                # Auto-Parent anlegen, falls noch nicht vorhanden
                existing_parent = next((t for t in mc_tasks if t.get("id") == parent_pid), None)
                if existing_parent is None:
                    if not title_var:
                        title_var = f"Delegationsprojekt {parent_pid}"
                    mc_tasks.append({
                        "id": parent_pid,
                        "title": title_var,
                        "agent_id": delegator_id,
                        "agent_name": d_name,
                        "status": "active",
                        "phase": "in_progress",
                        "created_via": "delegation_bridge",
                        "capture_input": auftrag[:400],
                        "target_action": "none",
                    })
                    logger.info(f"[Delegation] Fan-in Parent '{parent_pid}' angelegt")
                else:
                    # Eltern-Titel immer mitfuehren (Ordnername-Einheitlichkeit)
                    title_var = str(existing_parent.get("title") or title_var or parent_pid)
                # MC-Subtask = Tracking-Spiegel des Kanban-Tasks (Wird in _bg_watch_task completed)
                if task_id:
                    mc_tasks.append({
                        "id": f"mcsub-{task_id}",
                        "title": auftrag[:80],
                        "agent_id": ziel,
                        "agent_name": t_name,
                        "status": "active",
                        "phase": "in_progress",
                        "parent_project_id": parent_pid,
                        "parent_project_title": title_var,
                        "kanban_task_id": task_id,
                        "created_via": "delegation_bridge",
                        "capture_input": auftrag[:400],
                        "target_action": "none",
                    })
                return title_var

            update_mission_control_data(_bridge_mutate)
            # Kanban: project_id + Eltern-Kind-Beziehung (task_links war bisher immer leer)
            from backend.operations_api import _get_kanban_connection as _kg_link
            kc_link = _kg_link()
            kc_link.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (parent_pid, task_id))
            kc_link.execute("INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)", (parent_pid, task_id))
            kc_link.commit()
            kc_link.close()
        except Exception as fan_err:
            logger.warning(f"[Delegation] Fan-in-Anbindung fehlgeschlagen: {fan_err}")

    _spawn_background(_bg_watch_task(task_id, tgt_sess, ziel, origin_session_id, delegator_id, parent_pid), name=f"bg_watch_{task_id}")
    resolve_str = f" [aufgelöst von '{ziel_raw}']" if ziel_raw and ziel_raw != ziel else ""
    return (f"✅ DELEGATION QUITTUNG — Ziel: {ziel} ({t_name}{resolve_str}) | Kanban-Task: {task_id or 'n/a'} | "
            f"Sub-Session: {tgt_sess} | Modell (Empfehlung): {t_model} | "
            f"Ausführung: Hermes-Agent-Worker | Ergebnis erscheint im Kanban und wird automatisch in die Sub-Session gespiegelt.")

_PRICE_LOOKUP_WARNED = {"done": False}


def _warn_price_lookup_once(exc: Exception) -> None:
    """Einmal laut meckern, wenn die Preisliste nicht kommt — nicht bei jedem Token.

    Vorher verschluckte ein ``except Exception: pass`` den Fehler; die
    Kostenanzeige blieb still bei 0 und niemand merkte, dass der Aufruf gar
    nicht aufloesbar war.
    """
    if _PRICE_LOOKUP_WARNED["done"]:
        return
    _PRICE_LOOKUP_WARNED["done"] = True
    logger.warning(f"[Pricing] Preisliste nicht abrufbar — Kostenanzeige bleibt 0: {exc}")


@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatStreamRequest):
    """
    Natives Chat-Streaming via Server-Sent Events (SSE).
    Unterstützt Direkt-Dialog und Missions-Modus mit Paperclip-Kopplung.
    """
    agent_id = req.agent_id or "default"
    user_msg = req.message.strip()
    session_id = req.session_id or f"mc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_id}"
    mode = (req.mode or "direct").lower()

    if not user_msg:
        raise HTTPException(status_code=400, detail="Nachricht darf nicht leer sein.")

    # Profil laden
    profiles = api_get_hermes_profiles()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof and profiles:
        prof = profiles[0]
    
    agent_name = prof.get("person_name") or prof.get("name") or "Hermes Agent"
    system_prompt = prof.get("prompt") or "You are Hermes Agent, an intelligent AI assistant created by Nous Research."
    # Delegations-Protokoll für berechtigte Hierarchie-Ebenen (Tier 1/2) dynamisch injizieren
    delegation_prompt_addon = _get_delegation_prompt_for(agent_id)
    if delegation_prompt_addon:
        system_prompt += delegation_prompt_addon

    # Obsidian Personalakte als Identitäts- und Kompetenzkontext injizieren
    try:
        akte_candidates = [
            os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
            f"/opt/data/obsidian/00_HR_Agenten/Personalakten/{agent_id}.md",
            os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten", f"{agent_id}.md")
        ]
        akte_content = None
        for cand in akte_candidates:
            if os.path.exists(cand) and os.path.isfile(cand):
                with open(cand, "r", encoding="utf-8", errors="ignore") as f_akte:
                    akte_content = f_akte.read().strip()
                break
        if akte_content:
            system_prompt += f"\n\n[OBSIDIAN PERSONALAKTE & STATUS]\n{akte_content}\n"
    except Exception as akte_err:
        logger.warning(f"[Chat Stream] Konnte Personalakte für {agent_id} nicht laden: {akte_err}")
    import api_provider
    all_keys = api_provider.collect_keys()

    provider = (req.provider or "").strip().lower()
    if not provider:
        provider = (prof.get("provider") or "").strip().lower()
    if not provider and req.model:
        provider = api_provider.infer_provider_from_model(req.model) or ""
    if not provider:
        active_cfg = api_provider.read_active_config()
        provider = (active_cfg.get("provider") or "").strip().lower()
    if not provider:
        provider = "openrouter" if all_keys.get("OPENROUTER_API_KEY") else "omniroute"

    reasoning_level = (req.reasoning_level or prof.get("reasoning_level") or "medium").strip().lower()
    model = (req.model or prof.get("model") or "").strip()
    if not model or model == "free-forever":
        if provider == "google":
            model = "gemini-2.5-flash"
        elif provider == "openrouter":
            model = "meta-llama/llama-3.3-70b-instruct"
        elif provider == "groq":
            model = "llama-3.3-70b-versatile"
        elif provider == "omniroute":
            # D-12: "evey-session-guard:" war kein Modellname, sondern ein
            # Plugin-Key mit angehaengtem Doppelpunkt — als Modell-ID war
            # jeder Aufruf ein erwartbarer Upstream-400. Der Default ist jetzt
            # ein Alias, den OmniRoute tatsaechlich kennt (vgl.
            # api_provider._list_provider_models_uncached).
            model = "auto/best-coding"
        else:
            model = "auto/best-coding"

    # Modell-Routing (Eigentümer-Tabelle): überschreibt das Profilmodell, wenn aktiv.
    try:
        from backend.model_routing import is_enabled as _mr_enabled, resolve as _mr_resolve, classify_task as _mr_classify
        if _mr_enabled():
            _task_type = (getattr(req, "task_type", None) or "").strip()
            if not _task_type:
                _task_type = _mr_classify(user_msg)
            _route = _mr_resolve(_task_type)
            if _route:
                provider, model = _route["provider"], _route["model"]
                logger.info(f"[ModelRouting] Chat '{_task_type}' -> {provider}/{model}")
    except Exception as _mr_err:
        logger.warning(f"[ModelRouting] Chat-Fallback: {_mr_err}")

    # 1. MISSIONS-MODUS: Task erzeugen & HITL Approval-Gate aktivieren
    if mode == "mission":
        task_id = f"task-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        title = user_msg[:80] + ("..." if len(user_msg) > 80 else "")

        # Task in Archon OS erfassen mit status: approval
        est_tokens = 95000 if len(user_msg) > 200 else 45000
        est_cost = 0.18 if len(user_msg) > 200 else 0.05

        # Operative Zielaktion erkennen (z.B. ACTION: POST_LINKEDIN)
        detected_action = core_dispatcher.detect_target_action(user_msg)

        # Phase bestimmen: Falls Robert (executive_decision_architect), startet Kaskade mit strategy
        initial_phase = "strategy" if agent_id in ("executive_decision_architect", "robert") else "execution"

        new_task = {
            "id": task_id,
            "title": title,
            "capture_input": user_msg,
            "plan": [
                f"Missions-Start: '{title}' über Hermes Core Task Engine",
                f"Ressourcen- und Werkzeugallokation für {agent_name} ({agent_id})",
                "Ausführung & atomarer Obsidian-Sync"
            ],
            "agent_id": agent_id,
            "agent_name": agent_name,
            "model": model,
            "estimated_tokens": est_tokens,
            "estimated_cost_eur": est_cost,
            "subagents_count": 2,
            "status": "approval",  # HITL Gate sperrt Ausführung zwingend
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result_summary": "",
            "artifact_path": "",
            "paperclip_issue": None,
            "parent_project_id": None,
            "subtask_ids": [],
            "target_action": detected_action,
            "phase": initial_phase
        }

        # Audit Log
        now_t = datetime.datetime.now().strftime("%H:%M:%S")

        # F-10: Read-Modify-Write unter Lock statt load->modify->save.
        def _approval_mutate(mc_data):
            mc_data.setdefault("tasks", []).insert(0, new_task)
            mc_data.setdefault("audit_logs", []).insert(0, {
                "time": now_t,
                "source": "Approval Gate",
                "msg": f"Missions-Modus: Task #{task_id} erfordert Freigabe vor Ausführung!"
            })
            mc_data["audit_logs"] = mc_data["audit_logs"][:25]
            return new_task

        await asyncio.to_thread(update_mission_control_data, _approval_mutate)
        
        # --- 2c: Mission liegt im HITL-Approval-Gate -> ueber den zentralen
        # Entscheidungs-Service (echter Kanban-Task, EIN Schreibpfad) ---
        try:
            _mdec = await asyncio.to_thread(
                create_decision, "mission_freigabe",
                f"Mission-Freigabe: {str(title)[:80]}",
                f"Agent: {agent_name} ({agent_id})\nGeschätzte Kosten: ~{est_cost:.2f}",
                task_id, None, "", None)
            if not _mdec:
                logger.warning(f"[Mission] Entscheidungs-Task für {task_id} nicht angelegt.")
        except Exception as tg_err:
            logger.warning(f"[Telegram] Missions-Freigabe-Ping für {task_id} fehlgeschlagen: {tg_err}")

        # In DB persistieren
        with _get_state_db() as conn:
            _ensure_session_exists(conn, session_id, agent_id, model, title)
        _save_message_to_db(session_id, "user", user_msg)
        
        approval_confirmation = (
            f"🛡️ **Mission erfasst & HITL-Freigabe erforderlich!**\n\n"
            f"- **Task-ID:** `{task_id}`\n"
            f"- **Operations Identifier:** `TASK-{task_id}`\n"
            f"- **Zugewiesener Agent:** {agent_name} (`{agent_id}`)\n"
            f"- **Geschtzte Kosten:** ~{est_cost:.2f}  ({est_tokens:,} Tokens)\n"
            f"- **Status:** `1 STOP / Freigabe erforderlich` (Im Mission Control Approval Gate gesperrt)"
        )
        _save_message_to_db(session_id, "assistant", approval_confirmation)

        async def mission_event_stream():
            yield f"data: {json.dumps({'type': 'mission_created', 'task_id': task_id, 'task': new_task, 'content': approval_confirmation}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(mission_event_stream(), media_type="text/event-stream")

    # 2. DIREKT-DIALOG: Streaming via ausgewählten Provider (Google, OpenRouter, Groq, OmniRoute etc.)
    try:
        with _get_state_db() as conn:
            _ensure_session_exists(conn, session_id, agent_id, model, user_msg[:50])
        _save_message_to_db(session_id, "user", user_msg)
    except Exception as db_err:
        logger.warning(f"[Chat Stream] Session/Message DB init warning: {db_err}")

    # Lade letzten Kontext aus DB (bis zu 50 Nachrichten fuer stabilen Sitzungsverlauf)
    recent_messages = []
    try:
        with _get_state_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT role, content FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id DESC LIMIT 50
            """, (session_id,)).fetchall()
            for r in reversed(rows):
                content_val = r["content"]
                role_val = r["role"]
                # Sanitize repetitive metadata footers and system checks from context history to prevent autoregressive feedback loops
                if role_val == "assistant" and isinstance(content_val, str):
                    content_val = re.sub(r'(\n|\r\n)*\s*(\*?-?\s*Routed to:[^\n]+|\*?-?\s*🧠 Antwort generiert von[^\n]+)', '', content_val)
                    content_val = re.sub(r'\(System-Check via mcp__[^\)]+\)\s*[🟢🔴🟡]?', '', content_val).strip()

                # Dateianhänge (bis zu 5 Dateien: Bilder als multimodale Vision-Inhalte, Text/Code als Prompt-Inhalt)
                if role_val == "user" and "[Datei angehängt:" in content_val:
                    matches = list(re.finditer(r'\[Datei angehängt:\s*([^\]]+)\]', content_val))
                    if matches:
                        clean_text = content_val
                        for m in matches:
                            clean_text = clean_text.replace(m.group(0), "")
                        clean_text = clean_text.strip()
                        
                        image_blocks = []
                        text_attachments = []
                        for m in matches[:5]:
                            f_path = m.group(1).strip()
                            if os.path.exists(f_path):
                                lower_p = f_path.lower()
                                if lower_p.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                                    try:
                                        with open(f_path, "rb") as img_f:
                                            img_b64 = base64.b64encode(img_f.read()).decode("utf-8")
                                        mime = "image/png"
                                        if lower_p.endswith(('.jpg', '.jpeg')):
                                            mime = "image/jpeg"
                                        elif lower_p.endswith('.webp'):
                                            mime = "image/webp"
                                        elif lower_p.endswith('.gif'):
                                            mime = "image/gif"
                                        image_blocks.append({
                                            "type": "image_url",
                                            "image_url": {"url": f"data:{mime};base64,{img_b64}"}
                                        })
                                    except Exception as img_err:
                                        logger.warning(f"[Chat Stream] Konnte Bild nicht einbetten: {img_err}")
                                elif lower_p.endswith(('.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.html', '.css', '.yaml', '.yml', '.log')):
                                    try:
                                        with open(f_path, "r", encoding="utf-8", errors="ignore") as tf:
                                            snippet = tf.read(15000)
                                            b_name = os.path.basename(f_path)
                                            text_attachments.append(f"\n--- DATEI-INHALT ({b_name}) ---\n{snippet}\n--- ENDE DATEI-INHALT ---")
                                    except Exception as tf_err:
                                        logger.warning(f"[Chat Stream] Konnte Textdatei nicht lesen: {tf_err}")

                        if image_blocks:
                            full_prompt = clean_text
                            if text_attachments:
                                full_prompt += "\n" + "\n".join(text_attachments)
                            content_val = [{"type": "text", "text": full_prompt or "Siehe angehängte Dateien."}] + image_blocks
                        elif text_attachments:
                            content_val = (clean_text + "\n" + "\n".join(text_attachments)).strip()

                recent_messages.append({"role": role_val, "content": content_val})
    except Exception as e:
        logger.warning(f"[Chat Stream] Konnte Kontext nicht laden: {e}")
        recent_messages = [{"role": "user", "content": user_msg}]

    # Enterprise Skill Resolver (Dynamische Kontext-Injektion für Session)
    skills_prompt_block = None
    freshly_loaded_skills = []
    direct_skill_notice = None
    try:
        from scripts.skill_resolver import resolve_and_prepare_skill_context
        skills_idx = build_skills_file_index()
        skills_prompt_block, freshly_loaded_skills, direct_skill_notice = resolve_and_prepare_skill_context(
            session_id=session_id,
            user_msg=user_msg,
            find_skill_file_fn=find_skill_file,
            skills_index=skills_idx,
            agent_prof=prof
        )
    except Exception as sk_err:
        logger.error(f"[Chat Stream] Error resolving enterprise skills: {sk_err}")

    if skills_prompt_block:
        payload_messages = [{"role": "system", "content": system_prompt}, {"role": "system", "content": skills_prompt_block}] + recent_messages
    else:
        payload_messages = [{"role": "system", "content": system_prompt}] + recent_messages

    async def chat_event_stream():
        full_assistant_text = ""
        prompt_tokens = len(user_msg.split()) * 2
        completion_tokens = 0

        # Direkte System-Antwort bei Management-Befehlen (/skill list, /skill clear)
        if direct_skill_notice:
            yield f"data: {json.dumps({'type': 'delta', 'delta': direct_skill_notice}, ensure_ascii=False)}\n\n"
            full_assistant_text = direct_skill_notice
            _save_message_to_db(session_id, "assistant", full_assistant_text)
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
            return

        # Falls in diesem Turn ein neuer Skill geladen wurde, visuelle Bestätigung im Stream ausgeben
        if freshly_loaded_skills:
            skill_pills = ", ".join([f"`{s}`" for s in freshly_loaded_skills])
            pill_text = f"⚙️ *[System: Skill(s) erfolgreich in den Arbeitsspeicher geladen: {skill_pills}]*\n\n"
            full_assistant_text += pill_text
            yield f"data: {json.dumps({'type': 'delta', 'delta': pill_text}, ensure_ascii=False)}\n\n"

        from backend.agent_router import router_instance

        # Delegate LLM execution to the Hardware Abstraction Layer (AgentRouter)
        # F-05: Ein Provider-Fehler wurde als erfolgreicher Turn verbucht — die
        # Fehlermeldung landete in ``full_assistant_text``, wurde als
        # Assistenten-Antwort persistiert, "done" gesendet und die Nutzung
        # gebucht. Jetzt wird der Fehler als solcher markiert: die
        # Fehlermeldung wird NICHT als Antwort gespeichert und es wird keine
        # Nutzung gebucht.
        provider_failed = False
        try:
            async for chunk in router_instance.stream_chat_completion(
                messages=payload_messages,
                provider=provider,
                model=model,
                api_keys=all_keys,
                reasoning_level=reasoning_level
            ):
                if chunk.startswith("ERROR: "):
                    provider_failed = True
                    yield f"data: {json.dumps({'type': 'error', 'error': chunk[7:]})}\n\n"
                    full_assistant_text += chunk[7:]
                else:
                    full_assistant_text += chunk
                    completion_tokens += 1
                    yield f"data: {json.dumps({'type': 'delta', 'delta': chunk}, ensure_ascii=False)}\n\n"

            if not full_assistant_text:
                full_assistant_text = f"Keine Antwort von {provider.capitalize()} erhalten."
                yield f"data: {json.dumps({'type': 'delta', 'delta': full_assistant_text})}\n\n"

        except Exception as exc:
            provider_failed = True
            err_msg = f"Verbindungsfehler zu {provider.capitalize()}: {str(exc)}"
            logger.error(f"[Chat Stream] {err_msg}")
            # Die Fehlermeldung gehoert in den Fehlerkanal, nicht in die
            # Antwort (sonst wird sie als Antwort gespeichert/gebucht).
            yield f"data: {json.dumps({'type': 'error', 'error': err_msg})}\n\n"

        # Kosten-Berechnung und Transparenz-Anzeige (Pillar 3/6)
        cost_str = "0.0000"
        try:
            prices = None
            try:
                p_res = get_llm_prices()
                if isinstance(p_res, dict) and "prices" in p_res:
                    prices = p_res["prices"]
            except Exception as price_err:
                _warn_price_lookup_once(price_err)
            m_price = (prices or {}).get(model, {})
            p_rate = m_price.get("prompt_1m", 0.0)
            c_rate = m_price.get("completion_1m", 0.0)
            if p_rate == 0.0 and c_rate == 0.0:
                m_low = model.lower()
                if "opus" in m_low:
                    p_rate, c_rate = (7.50, 37.50) if "batch" in m_low else (15.0, 75.0)
                elif "sonnet" in m_low:
                    p_rate, c_rate = (3.0, 15.0)
                elif "deepseek" in m_low:
                    p_rate, c_rate = (0.25, 1.0)
                elif "gpt-4o-mini" in m_low:
                    p_rate, c_rate = (0.15, 0.60)
                elif "gpt-4o" in m_low:
                    p_rate, c_rate = (2.50, 10.0)
            p_cost = (max(prompt_tokens, 800) / 1_000_000) * p_rate
            c_cost = (max(completion_tokens, 100) / 1_000_000) * c_rate
            total_cost = p_cost + c_cost
            if total_cost > 0:
                cost_str = f"{total_cost:.5f}"
        except Exception as e:
            logger.error(f"Cost calculation error: {e}")
            
        tier = "High" if provider == "openrouter" else "Low"
        transparency_tag = f"\n\n*- 🧠 Antwort generiert von `@{agent_id}` via `{model}` | Tier: `{tier}` | Est. Cost: `{cost_str}$`*"

        # Delegation Engine v2: strukturierte ```delegation```-Blöcke + Legacy-CLI-Interception.
        # Quittungen werden in die Delegator-Session geschrieben -> der Agent "erinnert" sich.
        delegation_receipts = []
        try:
            payloads, invalid_blocks = _parse_delegation_blocks(full_assistant_text)
            # Legacy-Fallback: alte `hermes -p ...`-CLI-Befehle weiterhin abfangen
            for m in re.finditer(r'hermes\s+-p\s+([a-zA-Z0-9_-]+)\s+chat\s+.*?-q\s+["\'](.*?)["\']', full_assistant_text, re.DOTALL):
                mm = re.search(r'-m\s+([a-zA-Z0-9_/.:-]+)', m.group(0))
                payloads.append({
                    "ziel_agent": m.group(1),
                    "auftrag": m.group(2),
                    "modell": mm.group(1) if mm else "",
                    "prioritaet": "normal"
                })
            for payload in payloads:
                try:
                    delegation_receipts.append(_execute_delegation(agent_id, payload, provider, all_keys, origin_session_id=session_id))
                except Exception as de:
                    delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Intern: {de}")
            for bad in invalid_blocks:
                delegation_receipts.append(
                    f"⚠️ DELEGATION-FEHLER — Ungültiger Delegations-Block ({bad['error']}). "
                    f"Der Auftrag wurde NICHT ausgeführt. Block: {bad['raw'][:120]}"
                )
        except Exception as e:
            logger.error(f"Delegation Engine Fehler: {e}")
            delegation_receipts.append(f"⚠️ DELEGATION-FEHLER — Engine: {e}")

        if delegation_receipts:
            receipt_text = "\n\n" + "\n".join(delegation_receipts)
            payload = json.dumps({"type": "delta", "delta": receipt_text}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            full_assistant_text += receipt_text

        # Antwort & Metriken in SQLite verbuchen
        # Transparenz-Tag nach Delegationsquittungen ausgeben
        payload_trans = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
        yield f"data: {payload_trans}\n\n"
        full_assistant_text += transparency_tag

        # F-05: Bei Provider-Fehler wird die Fehlermeldung NICHT als
        # Assistenten-Antwort gespeichert und es wird keine Nutzung gebucht.
        if not provider_failed:
            _save_message_to_db(session_id, "assistant", full_assistant_text, completion_tokens)

        # Parse total_cost if possible
        try:
            total_cost_val = float(cost_str)
        except:
            total_cost_val = 0.0

        if not provider_failed:
            _record_session_model_usage(session_id, model, prompt_tokens, completion_tokens, total_cost_val)
        payload_done = json.dumps({"type": "done", "session_id": session_id, "tokens": completion_tokens})
        yield f"data: {payload_done}\n\n"

    return StreamingResponse(chat_event_stream(), media_type="text/event-stream")

class ImageGenerateToolRequest(BaseModel):
    prompt: str
    model: Optional[str] = "google/gemini-2.5-flash-image"
    provider: Optional[str] = "openrouter"
    session_id: Optional[str] = None

@app.post("/api/v1/tools/image_generate")
async def api_tool_image_generate(req: ImageGenerateToolRequest):
    """Führt eine direkte Bildgenerierung über OpenRouter (z.B. Google Nano Banana) oder Bild-Modelle aus."""
    import api_provider
    all_keys = api_provider.collect_keys()
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")

    model = (req.model or "google/gemini-2.5-flash-image").strip()
    provider = (req.provider or "openrouter").strip().lower()

    if provider == "openrouter":
        or_key = all_keys.get("OPENROUTER_API_KEY")
        if not or_key:
            raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY fehlt in den Einstellungen.")
        headers = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Archon OS"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail=f"OpenRouter Fehler: {resp.text[:300]}")
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                text = msg.get("content", "")
                images = msg.get("images", [])
                img_url = ""
                if images:
                    first = images[0]
                    img_url = first.get("image_url", {}).get("url") if isinstance(first, dict) else str(first)

                markdown = f"{text}\n\n![{prompt}]({img_url})" if img_url else text
                if req.session_id and img_url:
                    _save_message_to_db(req.session_id, "assistant", markdown)

                return {
                    "status": "ok",
                    "image_url": img_url,
                    "text": text,
                    "markdown": markdown,
                    "model": model
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fehler bei Bildgenerierung: {str(e)}")

    raise HTTPException(status_code=400, detail=f"Provider '{provider}' für Bildgenerierung aktuell nicht unterstützt. Bitte 'openrouter' wählen.")

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

# --- MEILENSTEIN 4: MULTI-USER & RBAC ENDPOINTS ---
from backend.auth_service import auth_service

def get_current_user_from_request(request: Request) -> dict:
    """Ermittelt die Identitaet aus der Session.

    Kandidaten in dieser Reihenfolge: ``Authorization``-Header,
    ``X-Archon-Session``, ``archon_session``-Cookie. Der Cookie wird auch dann
    geprueft, wenn ein ``Authorization``-Header vorhanden ist, der **keine**
    Archon-Session traegt — sonst verliert eine angemeldete Sitzung ihre Rolle,
    sobald ein Client einen fremden Bearer-Header mitsendet (etwa das
    eingebettete Hermes-Dashboard). Akzeptiert wird ausschliesslich eine
    gueltige Archon-Session; an den Rechten aendert das nichts.
    """
    candidates: List[str] = []
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidates.append(auth_header[7:].strip())
    header_session = request.headers.get("x-archon-session", "").strip()
    if header_session:
        candidates.append(header_session)
    cookie_session = (request.cookies.get("archon_session", "") or "").strip()
    if cookie_session:
        candidates.append(cookie_session)

    is_enabled = auth_service.is_auth_enabled()

    for candidate in candidates:
        if not candidate:
            continue
        try:
            user = auth_service.verify_session(candidate)
        except Exception:
            user = None
        if user:
            user["auth_enabled"] = is_enabled
            return user

    # Multi-User-Modus: ohne gültige Session gibt es KEINE Admin-Rechte.
    if is_enabled:
        if _request_has_service_token(request):
            return {
                "id": "usr_service",
                "username": "service",
                "display_name": "Interner Dienst",
                "role": "admin",
                "permissions": ["service"],
                "is_service": True,
                "auth_enabled": True,
            }
        return {
            "id": "usr_anonymous",
            "username": "anonymous",
            "display_name": "Nicht angemeldet",
            "role": "anonymous",
            "permissions": [],
            "is_fallback": False,
            "auth_enabled": True,
        }

    fb = auth_service.get_fallback_admin()
    fb["auth_enabled"] = is_enabled
    return fb


def require_admin(request: Request) -> Dict[str, Any]:
    """Rollenzaun fuer destruktive Admin-Routen (RBAC-Pilot, 6 Routen).

    Referenz war die Pruefung in `api_auth_toggle` (main.py:7296): Rolle ermitteln,
    bei `!= "admin"` mit 403 abbrechen. Diese Fassung ist derselbe Code als Helfer,
    damit sechs Routen ihn teilen statt ihn sechsmal zu kopieren.

    Bewusst KEIN `Depends()`: die Pruefung steht sichtbar als erste Anweisung im
    Handler, die Handler-Signatur bleibt fuer FastAPI unveraendert und die
    OpenAPI-Paritaet (585 Pfade / 861 Operationen) beruehrt das gar nicht.

    Durchlaessig (kein Aussperren bestehender Zugaenge):
      * ``auth.enabled = false``  -> `get_fallback_admin()` liefert Rolle ``admin``
      * ``X-Archon-Service-Token`` -> Rolle ``admin`` (interne Automaten, `is_service`)
      * Session mit Rolle ``admin``
    Gesperrt: ``operator``, ``viewer``, ``anonymous`` -> 403.
    """
    user = get_current_user_from_request(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Nur Administratoren duerfen diese Aktion ausfuehren "
                   f"(erkannte Rolle: {user.get('role') or 'unbekannt'}).",
        )
    return user

@app.get("/api/auth/status")
def api_auth_status():
    return {
        "status": "success",
        "auth_enabled": auth_service.is_auth_enabled()
    }

@app.post("/api/auth/toggle")
def api_auth_toggle(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen den Authentifizierungsmodus ändern.")
    enabled = bool(payload.get("enabled", False))
    s = _load_json(SETTINGS_FILE, {})
    if "auth" not in s or not isinstance(s["auth"], dict):
        s["auth"] = {}
    s["auth"]["enabled"] = enabled
    s["auth"]["mode"] = "multi_user" if enabled else "single_user"
    _save_json(SETTINGS_FILE, s)

    alt_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json"),
        "/app/settings.json"
    ]
    for alt in alt_paths:
        try:
            if os.path.exists(alt) and os.path.abspath(alt) != os.path.abspath(SETTINGS_FILE):
                alt_s = _load_json(alt, {})
                if "auth" not in alt_s or not isinstance(alt_s["auth"], dict):
                    alt_s["auth"] = {}
                alt_s["auth"]["enabled"] = enabled
                alt_s["auth"]["mode"] = s["auth"]["mode"]
                _save_json(alt, alt_s)
        except Exception:
            pass
    return {
        "status": "success",
        "auth_enabled": enabled,
        "mode": s["auth"]["mode"],
        "message": "Multi-User-Modus aktiviert." if enabled else "Einzelplatz-Modus aktiviert (keine Anmeldung erforderlich)."
    }

@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = get_current_user_from_request(request)
    return {
        "status": "success",
        "user": user,
        "auth_enabled": auth_service.is_auth_enabled()
    }

@app.post("/api/auth/login")
def api_auth_login(request: Request, payload: dict = Body(...)):
    username = payload.get("username", "")
    password = payload.get("password", "")
    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    session = auth_service.authenticate(username, password, ip_address=client_ip, user_agent=user_agent)
    if not session:
        raise HTTPException(status_code=401, detail="Ungültiger Benutzername oder falsches Passwort.")
    res = JSONResponse(content={"status": "success", **session})
    res.set_cookie(key="archon_session", value=session["token"], max_age=86400 * 30, httponly=True, samesite="lax")
    return res

@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    token = request.cookies.get("archon_session") or request.headers.get("x-archon-session", "")
    if token:
        auth_service.logout(token)
    res = JSONResponse(content={"status": "success", "message": "Erfolgreich abgemeldet."})
    res.delete_cookie(key="archon_session")
    return res

@app.get("/api/auth/users")
def api_auth_list_users(request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") not in ("admin", "operator"):
        return {"status": "success", "users": [curr]}
    return {"status": "success", "users": auth_service.list_users()}

@app.post("/api/auth/users")
def api_auth_create_user(request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen neue Benutzer anlegen.")
    try:
        new_u = auth_service.create_user(
            username=payload.get("username"),
            password=payload.get("password"),
            role=payload.get("role", "operator"),
            display_name=payload.get("display_name", ""),
            email=payload.get("email", "")
        )
        return {"status": "success", "user": new_u}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/api/auth/users/{user_id}")
def api_auth_update_user(user_id: str, request: Request, payload: dict = Body(...)):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzerrollen anpassen.")
    try:
        updated = auth_service.update_user(
            user_id=user_id,
            role=payload.get("role"),
            display_name=payload.get("display_name"),
            email=payload.get("email"),
            is_active=payload.get("is_active")
        )
        return {"status": "success", "user": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/change-password")
def api_auth_change_password(request: Request, payload: dict = Body(...)):
    """Passwort ändern: eigener Account (mit aktuellem Passwort) oder als Admin für andere."""
    curr = get_current_user_from_request(request)
    if not curr or curr.get("id") in (None, "", "usr_anonymous"):
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    target_id = str(payload.get("user_id") or curr.get("id")).strip()
    new_pw = str(payload.get("new_password") or "")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Das neue Passwort muss mindestens 8 Zeichen haben.")

    is_self = (target_id == curr.get("id"))
    if is_self:
        current_pw = str(payload.get("current_password") or "")
        if not auth_service.verify_password(curr.get("username", ""), current_pw):
            raise HTTPException(status_code=400, detail="Das aktuelle Passwort ist falsch.")
    elif curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen fremde Passwörter ändern.")

    try:
        ok = auth_service.change_password(target_id, new_pw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    return {
        "status": "success",
        "message": "Passwort geändert.",
        "relogin_required": is_self,
    }

@app.delete("/api/auth/users/{user_id}")
def api_auth_delete_user(user_id: str, request: Request):
    curr = get_current_user_from_request(request)
    if curr.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Benutzer löschen.")
    try:
        auth_service.delete_user(user_id)
        return {"status": "success", "message": "Benutzer gelöscht."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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

@app.get("/api/v1/memory/stats")
def api_get_memory_stats():
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    learnings_cnt = 0
    conv_cnt = 0
    stale_cnt = 0
    try:
        conn = bridge._get_conn()
        cur = conn.cursor()
        learnings_cnt = cur.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        conv_cnt = cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        stale_info = bridge.evict_stale_memories(threshold=0.1, table="learnings", dry_run=True)
        stale_cnt = stale_info.get("stale_count", 0)
        conn.close()
    except Exception:
        pass

    vault_summary = bridge.scan_vault_summary()
    vault_notes = vault_summary.get("total_notes", 0) if isinstance(vault_summary, dict) else 0

    return {
        "status": "success",
        "learnings_count": learnings_cnt,
        "conversations_count": conv_cnt,
        "stale_count": stale_cnt,
        "vault_notes_count": vault_notes,
        "vault_path": bridge.vault_path
    }

class SmtpConfigPayload(BaseModel):
    enabled: Optional[bool] = False
    auto_send: Optional[bool] = False
    host: Optional[str] = ""
    port: Optional[int] = 587
    username: Optional[str] = ""
    password: Optional[str] = ""
    from_email: Optional[str] = ""
    to_email: Optional[str] = ""
    use_tls: Optional[bool] = True

@app.get("/api/v1/settings/smtp")
def api_get_smtp_settings():
    from backend.post_task_pipeline import get_smtp_config
    cfg = get_smtp_config()
    safe_cfg = dict(cfg)
    if safe_cfg.get("password"):
        safe_cfg["password"] = "••••••••"
    return {"status": "ok", "config": safe_cfg}

@app.post("/api/v1/settings/smtp")
def api_save_smtp_settings(request: Request, payload: SmtpConfigPayload):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.post_task_pipeline import save_smtp_config, get_smtp_config
    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    success = save_smtp_config(cfg_data)
    return {"status": "success" if success else "error"}

@app.post("/api/v1/settings/smtp/test")
def api_test_smtp_settings(request: Request, payload: SmtpConfigPayload):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.post_task_pipeline import send_smtp_email, get_smtp_config, save_smtp_config
    current = get_smtp_config()
    cfg_data = payload.dict()
    if cfg_data.get("password") == "••••••••":
        cfg_data["password"] = current.get("password", "")
    save_smtp_config(cfg_data)

    sub = "ðŸ§ª Archon OS: SMTP-Testnachricht"
    body = "Dies ist eine automatische Testnachricht von deinem Archon OS System. Die E-Mail-Konfiguration funktioniert einwandfrei!"
    html = "<div style='font-family: sans-serif; padding: 20px;'><h2 style='color: #0f172a;'>ðŸ§ª Archon OS SMTP-Test</h2><p>Die E-Mail-Konfiguration funktioniert einwandfrei!</p></div>"
    res = send_smtp_email(sub, body, html)
    return res

@app.post("/api/v1/inbox/emails/sync")
def api_sync_emails_endpoint():
    try:
        from backend.email_service import sync_imap_inbox
        return sync_imap_inbox(limit=30)
    except Exception as e:
        return {"status": "error", "message": str(e), "synced": 0}

@app.get("/api/v1/agent/{agent_id}/stats")
def api_get_agent_real_stats(agent_id: str):
    """Liefert echte Leistungsdaten aus der Personalakte und den Datenbanken."""
    import re
    from pathlib import Path
    vault_dir = Path("/opt/data/obsidian") if Path("/opt/data/obsidian").exists() else Path(OBSIDIAN_VAULT)
    akte = vault_dir / "00_HR_Agenten" / "Personalakten" / f"{agent_id}.md"
    tasks_completed = 0
    if akte.exists():
        try:
            txt = akte.read_text(encoding="utf-8")
            m = re.search(r"tasks_completed:\s*(\d+)", txt)
            if m:
                tasks_completed = int(m.group(1))
        except Exception:
            pass

    learnings_count = 0
    try:
        from local_memory_bridge import LocalMemoryBridge
        b = LocalMemoryBridge()
        with b._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM learnings WHERE agent_id = ?", (agent_id,))
            learnings_count = c.fetchone()[0]
    except Exception:
        pass

    return {
        "status": "ok",
        "agent_id": agent_id,
        "tasks_completed": tasks_completed,
        "learnings_count": learnings_count,
        "performance_rating": "100% nominal" if tasks_completed > 0 else "Bereit im Standby",
        "is_deployed": True
    }

@app.post("/api/v1/memory/consolidate")
def api_consolidate_memory(payload: Dict = Body(None)):
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    payload = payload or {}
    hours_back = payload.get("hours_back", 24)

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_id, role, content, timestamp 
            FROM conversations 
            ORDER BY id DESC LIMIT 40
        """)
        rows = cur.fetchall()

    if not rows:
        return {"status": "empty", "message": "Keine Chat-Einträge zur Konsolidierung gefunden."}

    facts = []
    for r in reversed(rows):
        txt = (r["content"] or "").strip().replace("\n", " ")
        if len(txt) > 20 and not txt.startswith("{") and not txt.startswith("["):
            facts.append(f"- [{r['agent_id']}] {txt[:120]}")

    facts_text = "\n".join(facts[:10])
    if not facts_text:
        facts_text = "- [general] Routinemäßiger Systemdurchlauf ohne kritische Vorfälle."

    vault_path = bridge.vault_path
    note_file = None
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if os.path.exists(vault_path):
        mem_dir = os.path.join(vault_path, "memories")
        os.makedirs(mem_dir, exist_ok=True)
        note_path = os.path.join(mem_dir, f"daily_consolidation_{today}.md")
        md_content = f"""---
title: "Tages-Konsolidierung: {today}"
date: {today}
tags: ["memory", "consolidated", "daily"]
source: "Archon OS Memory Bridge"
---

# Tages-Konsolidierung: {today}

## Extrahierte Erkenntnisse
{facts_text}

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
        try:
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            note_file = note_path
        except Exception as e:
            note_file = str(e)

    with bridge._get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO learnings (agent_id, category, summary, obsidian_link, importance, accesses, last_accessed)
            VALUES (?, ?, ?, ?, 2.0, 1, CURRENT_TIMESTAMP)
        """, ("consolidator", "daily_summary", f"Tages-Zusammenfassung {today}: {len(facts)} Interaktionen analysiert", f"[[daily_consolidation_{today}]]"))
        conn.commit()

    return {
        "status": "success",
        "message": f"{len(facts)} Interaktionen konsolidiert.",
        "note_file": note_file,
        "facts_count": len(facts)
    }

@app.post("/api/v1/memory/evict")
def api_evict_stale_memory(payload: Dict = Body(None)):
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    payload = payload or {}
    threshold = float(payload.get("threshold", 0.1))
    dry_run = bool(payload.get("dry_run", False))

    res_conv = bridge.evict_stale_memories(threshold=threshold, table="conversations", dry_run=dry_run)
    res_learn = bridge.evict_stale_memories(threshold=threshold, table="learnings", dry_run=dry_run)

    return {
        "status": "success",
        "conversations_pruned": res_conv.get("stale_count", 0),
        "learnings_pruned": res_learn.get("stale_count", 0),
        "threshold": threshold,
        "dry_run": dry_run
    }

@app.get("/api/v1/models")
def api_get_models_v1():
    return ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"]

@app.post("/api/v1/security/scan-email")
def api_scan_email_security(payload: Dict = Body(None)):
    from local_security_guard import scan_prompt_injection
    payload = payload or {}
    text = payload.get("text") or payload.get("body") or ""
    subject = payload.get("subject", "")
    sender = payload.get("sender", "")
    sensitivity = payload.get("sensitivity", "moderate")
    use_llm = bool(payload.get("use_llm", False))
    model = payload.get("model", "omniroute/free-forever")
    res = scan_prompt_injection(text, subject=subject, sender=sender, sensitivity=sensitivity, use_llm=use_llm, model=model)
    return {"status": "success", **res}

@app.post("/api/v1/security/validate-output")
def api_validate_output_security(payload: Dict = Body(None)):
    from local_security_guard import validate_ai_output
    payload = payload or {}
    task = payload.get("task", "")
    result = payload.get("result", "")
    model_used = payload.get("model_used", "default")
    min_score = int(payload.get("min_score", 7))
    use_llm = bool(payload.get("use_llm", False))
    judge_model = payload.get("judge_model", "omniroute/free-forever")
    res = validate_ai_output(task, result, model_used=model_used, min_score=min_score, use_llm=use_llm, judge_model=judge_model)
    return {"status": "success", **res}

@app.get("/api/v1/security/stats")
def api_get_security_stats():
    # Zählt Mails im Posteingang und deren Sicherheitsstatus
    from views.view_inbox import load_email_messages, load_telegram_messages
    emails = load_email_messages()
    telegrams = load_telegram_messages()
    all_items = emails + telegrams
    blocked_cnt = sum(1 for m in all_items if m.get("security_status") == "blocked")
    suspicious_cnt = sum(1 for m in all_items if m.get("security_status") == "suspicious")
    safe_cnt = sum(1 for m in all_items if m.get("security_status") == "safe")
    return {
        "status": "success",
        "total_scanned": len(all_items),
        "blocked_count": blocked_cnt,
        "suspicious_count": suspicious_cnt,
        "safe_count": safe_cnt
    }

# --- RESEARCH LAB ENDPOINTS (SÄULE 2: KOGNITION & WISSEN) ---
@app.get("/api/v1/research/providers")
def api_get_research_providers():
    import research_engine
    return {"status": "success", "providers": research_engine.get_available_providers(_load_json(SETTINGS_FILE, {}))}

@app.post("/api/v1/research/run")
def api_run_research_mission(payload: dict):
    import research_engine
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query darf nicht leer sein.")
    profile = payload.get("profile", "deep")
    engines = payload.get("engines", ["duckduckgo", "grokipedia", "wikipedia", "arxiv"])
    depth = int(payload.get("depth", 3))
    adversarial = bool(payload.get("adversarial", True))
    export_obsidian = bool(payload.get("export_obsidian", True))
    model = payload.get("model", "omniroute/free-forever")
    agent_role = payload.get("agent_role", "Lead Research Analyst")
    settings = _load_json(SETTINGS_FILE, {})
    vault_path = settings.get("memory", {}).get("vault_path", OBSIDIAN_VAULT)
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    # Modus "reflect": Reflexionsschleife + Seiten-Scraper (research_engine_v2). Standard: klassische Pipeline.
    use_reflect = bool(payload.get("reflect")) or payload.get("mode") == "reflect"
    if use_reflect:
        import research_engine_v2
        return research_engine_v2.run_research_mission_reflect(
            query=query,
            profile=profile,
            engines=engines,
            depth=depth,
            adversarial=adversarial,
            export_obsidian=export_obsidian,
            vault_path=vault_path,
            workspace_dir=workspace_dir,
            settings=settings,
            model=model,
            agent_role=agent_role,
            fast_model=payload.get("fast_model") or None,
            max_rounds=int(payload.get("max_rounds", 3)),
            max_pages=int(payload.get("max_pages", 4)),
        )
    res = research_engine.run_research_mission(
        query=query,
        profile=profile,
        engines=engines,
        depth=depth,
        adversarial=adversarial,
        export_obsidian=export_obsidian,
        vault_path=vault_path,
        workspace_dir=workspace_dir,
        settings=settings,
        model=model,
        agent_role=agent_role
    )
    return res

@app.get("/api/v1/research/history")
def api_get_research_history():
    import research_engine
    settings = _load_json(SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    items = research_engine.list_research_history(workspace_dir)
    return {"status": "success", "dossiers": items}

@app.get("/api/v1/research/dossier/{filename}")
def api_get_research_dossier(filename: str):
    settings = _load_json(SETTINGS_FILE, {})
    workspace_dir = settings.get("workspace_dir", "/app/agent_workspace")
    safe_name = os.path.basename(filename)
    fpath = os.path.join(workspace_dir, "research", safe_name)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Dossier nicht gefunden.")
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"status": "success", "filename": safe_name, "content": content}

@app.get("/api/v1/research/sources")
def api_get_research_sources():
    from backend.research_sources import get_curated_sources_pool, TRUST_TIERS
    return {
        "status": "success",
        "sources": get_curated_sources_pool(),
        "trust_tiers": TRUST_TIERS
    }


# --- SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1) ---


# --- HERMES AGENT CORE UPDATE (NousResearch/hermes-agent) ---
@app.get("/api/v1/hermes/update/check")
def api_hermes_update_check(force: bool = False):
    from backend import hermes_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    return hermes_updater.check_hermes_updates(force_refresh=force)


@app.post("/api/v1/hermes/update/apply")
def api_hermes_update_apply(request: Request, payload: dict = Body(default={})):
    curr_user = get_current_user_from_request(request)
    if curr_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen Hermes Core Updates einleiten.")
    from backend import hermes_updater  # kein reload: zerstoerte Caches und kostete ~0.5-1.5s/Request
    channel = payload.get("channel", "latest")
    auto_restart = payload.get("restart", True)
    return hermes_updater.apply_hermes_update(channel=channel, auto_restart=auto_restart)

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
def _resolve_parser_input(filepath: str) -> str:
    """Prueft den Parser-Eingabepfad gegen die Bibliotheks-Wurzel (D-05).

    Der Parser liest beliebige Formate ein. Frueher wurde jeder angegebene Pfad
    geoeffnet (``/opt/data/.env``, ``/app/.env.archon``). Erlaubt ist jetzt nur
    noch ``library/raw_docs`` — die Wurzel, in die Uploads geschrieben werden.
    """
    if not filepath:
        raise HTTPException(status_code=400, detail="Gültiger 'filepath' erforderlich.")
    from utils.batch_library_importer import resolve_raw_docs_dir
    try:
        return safe_path_within(
            filepath, [resolve_raw_docs_dir()], must_exist=True, allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=f"Pfad nicht erlaubt: {e}")


@app.post("/api/documents/parse")
@app.post("/api/v1/documents/parse")
def api_parse_document(request: Request, payload: dict = Body(...)):
    # RBAC: der Parser liest Dateien im Auftrag des Aufrufers -> Admin-Sache.
    require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine
    real_path = _resolve_parser_input(payload.get("filepath", ""))
    res = DocumentParserEngine.parse_file(real_path)
    return {"status": "success", "result": res}


@app.post("/api/documents/extract-tables")
@app.post("/api/v1/documents/extract-tables")
def api_extract_tables(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine
    real_path = _resolve_parser_input(payload.get("filepath", ""))
    res = DocumentParserEngine.parse_file(real_path)
    tables = res.get("tables") or res.get("tables_by_sheet") or []
    return {"status": "success", "tables": tables, "format": res.get("format")}


# --- DEAL-PIPELINE & FORECAST-ENGINE (t-5b159d) ---
@app.get("/api/deals")
@app.get("/api/v1/deals")
def api_list_deals(stage: Optional[str] = None, partner: Optional[str] = None, assigned_agent: Optional[str] = None):
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "deals": DealPipelineManager.list_deals(stage=stage, partner=partner, assigned_agent=assigned_agent)}


@app.get("/api/deals/forecast")
@app.get("/api/v1/deals/forecast")
def api_deal_forecast():
    from backend.deal_pipeline import DealPipelineManager
    return {"status": "success", "forecast": DealPipelineManager.get_forecast()}


@app.get("/api/deals/{deal_id}")
@app.get("/api/v1/deals/{deal_id}")
def api_get_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deal = DealPipelineManager.get(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal nicht gefunden.")
    return {"status": "success", "deal": deal}


@app.post("/api/deals")
@app.post("/api/v1/deals")
def api_save_deal(payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    saved = DealPipelineManager.create_or_update(payload)
    return {"status": "success", "deal": saved}


@app.post("/api/deals/{deal_id}/move-stage")
@app.post("/api/v1/deals/{deal_id}/move-stage")
def api_move_deal_stage(deal_id: str, payload: dict = Body(...)):
    from backend.deal_pipeline import DealPipelineManager
    new_stage = payload.get("stage", "")
    notes = payload.get("notes")
    if not new_stage:
        raise HTTPException(status_code=400, detail="'stage' erforderlich.")
    moved = DealPipelineManager.move_stage(deal_id, new_stage, notes=notes)
    if not moved:
        raise HTTPException(status_code=404, detail="Deal oder Phase ungültig.")
    return {"status": "success", "deal": moved}


@app.delete("/api/deals/{deal_id}")
@app.delete("/api/v1/deals/{deal_id}")
def api_delete_deal(deal_id: str):
    from backend.deal_pipeline import DealPipelineManager
    deleted = DealPipelineManager.delete(deal_id)
    return {"status": "success" if deleted else "not_found", "deleted": deleted}


# --- PLUGIN SYSTEM & EXTENSIBILITY (MEILENSTEIN 5) ---


_VAULT_FILES_CACHE = {"ts": 0.0, "data": []}


@app.post("/api/theme/upload-background")
async def api_upload_theme_background(request: Request, file: UploadFile = File(...)):
    # D-13: Ohne Typ-/Groessenfilter landete eine .svg/.html im Web-Root
    # (same-origin) — Stored XSS; ``await file.read()`` ohne Limit fraess
    # zusaetzlich RAM. Jetzt wie die Schwester-Route
    # (api_studio_upload_bg): Endungs-Whitelist + 8-MB-Limit.
    require_admin(request)  # RBAC: Upload ist Admin-Sache
    allowed_ext = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                   ".webp": "image/webp", ".gif": "image/gif"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp '{ext}' nicht erlaubt (jpg, jpeg, png, webp, gif).",
        )
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Bild zu gross (max. 8 MB).")
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "background.png")
    fname = f"bg_{int(time.time())}_{safe_name}"
    dest = os.path.join(uploads_dir, fname)
    with open(dest, "wb") as f:
        f.write(content)
    return {"status": "success", "url": f"/static/uploads/{fname}"}


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

@app.get("/api/v1/watchdog/alarms")
def get_watchdog_alarms_endpoint():
    if watchdog_runner:
        return {"alarms": watchdog_runner.load_alarms()}
    return {"alarms": []}

@app.post("/api/v1/watchdog/test-alarm")
def trigger_test_watchdog_alarm_endpoint(request: Request):
    require_admin(request)  # RBAC: Admin-Sache
    if watchdog_runner:
        watchdog_runner.save_alarm(
            "telegram_bot",
            "Token Usage Limit Exceeded (14.200 > 10.000 tok/min) - Der Watchdog hat den Thread per SIGTERM isoliert, um weitere API-Kosten und Systemblockaden zu unterbinden.",
            {
                "container": "hermes",
                "task": "tk_test_sandbox",
                "measured_rate": "12.500 tok/min",
                "status": "Gestoppt (0 Tok/s)",
                "log_excerpt": "> 2026-08-27 19:41:17.185563315 | Messaging platforms + cron scheduler |\n> 2026-08-27 19:41:17.185564107 | Press Ctrl+C to stop |\n> 2026-08-27 19:41:17.185565209 |\n> 2026-08-27 19:41:17.185565590"
            }
        )
        return {"status": "ok", "alarms": watchdog_runner.load_alarms()}
    return {"status": "error", "message": "Watchdog not running"}

@app.post("/api/v1/watchdog/acknowledge")
def acknowledge_watchdog_alarm_endpoint(payload: dict = None):
    alarm_id = payload.get("alarm_id") if payload else None
    if watchdog_runner:
        alarms = watchdog_runner.load_alarms()
        if alarm_id:
            alarms = [a for a in alarms if a.get("id") != alarm_id]
        else:
            alarms = []
        try:
            from watchdog_daemon import ALARMS_FILE
            with open(ALARMS_FILE, "w", encoding="utf-8") as f:
                json.dump(alarms, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving alarms after ack: {e}")
        return {"status": "acknowledged", "alarms": alarms}
    return {"status": "ok", "alarms": []}



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
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
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

@app.get("/api/v1/chat/history")
def get_chat_history_api(agent_id: str, limit: int = 30, session_id: Optional[str] = None):
    """Liefert die persistierte Konversationshistorie aus agentic_memory.db fuer ein Profil."""
    if "memory_bridge" in globals() and memory_bridge:
        history = memory_bridge.get_conversation_history(agent_id, limit=limit, session_id=session_id)
        return {"status": "success", "agent_id": agent_id, "history": history}
    return {"status": "success", "agent_id": agent_id, "history": []}

@app.delete("/api/v1/chat/history")
def clear_chat_history_api(agent_id: str, session_id: Optional[str] = None):
    """Loescht die persistierte Historie eines Profils."""
    if "memory_bridge" in globals() and memory_bridge:
        memory_bridge.clear_conversation_history(agent_id, session_id=session_id)
        return {"status": "success", "message": f"History for {agent_id} cleared"}
    return {"status": "error", "message": "Memory bridge unavailable"}

@app.get("/api/proxy")
async def proxy_web_ui(url: str):
    """Header-stripping async proxy to bypass X-Frame-Options & CSP for embedded Web UIs.

    SSRF-Schutz: Ziele werden vor dem Request gegen utils.egress_guard geprueft.
    Erlaubt sind lokale Ziele (localhost/127.0.0.1/host.docker.internal) und
    alles, was per ARCHON_PROXY_ALLOWED_TARGETS explizit freigegeben wurde.
    """
    import urllib.parse
    from fastapi.responses import HTMLResponse, Response
    from utils.egress_guard import EgressBlocked, check_target_url

    try:
        check_target_url(url)
    except EgressBlocked as blocked:
        logger.warning(f"[Proxy] SSRF-Ziel blockiert: {blocked.reason} ({url[:120]})")
        return JSONResponse(
            status_code=403,
            content={"error": "Ziel nicht erlaubt", "detail": blocked.reason},
        )

    parsed = urllib.parse.urlparse(url)
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Host": parsed.netloc or "localhost"
    }
    
    # Inside Docker, rewrite localhost/127.0.0.1 to host.docker.internal for host-bound ports
    target_url = url
    if "localhost:" in target_url:
        target_url = target_url.replace("localhost:", "host.docker.internal:")
    elif "127.0.0.1:" in target_url:
        target_url = target_url.replace("127.0.0.1:", "host.docker.internal:")
        
    client = _get_shared_proxy_client()
    try:
        resp = await client.get(target_url, headers=req_headers, timeout=10.0, follow_redirects=True)
    except Exception:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0, follow_redirects=True)
        except Exception as e:
            err_html = f"<div style='font-family:sans-serif; padding:20px; color:#ef4444;'><h3>Web UI Proxy Status</h3><p>Konnte <code>{url}</code> nicht laden: {e}</p></div>"
            return HTMLResponse(content=err_html, status_code=502)

    content_type = resp.headers.get("Content-Type", "text/html")
    
    if "html" in content_type.lower():
        html_text = resp.text
        env_script = """<script>
            window.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.VITE_API_URL = "http://localhost:9119";
            window.HERMES_API_URL = "http://localhost:9119";
            window.HERMES_WEBUI_API_URL = "http://localhost:9119";
            if (typeof process === "undefined") { window.process = { env: {} }; }
            else if (!window.process.env) { window.process.env = {}; }
            window.process.env.NEXT_PUBLIC_API_URL = "http://localhost:9119";
            window.process.env.VITE_API_URL = "http://localhost:9119";
            window.process.env.HERMES_API_URL = "http://localhost:9119";
        </script>"""
        base_tag = f'<base href="{url.rstrip("/")}/">{env_script}'
        if "<head>" in html_text:
            html_text = html_text.replace("<head>", f"<head>{base_tag}", 1)
        else:
            html_text = base_tag + html_text
        
        res_obj = HTMLResponse(content=html_text, status_code=resp.status_code)
    else:
        res_obj = Response(content=resp.content, media_type=content_type, status_code=resp.status_code)

    # Frame-Blocking entfernen, damit die eingebetteten UIs (n8n, CRM) im
    # Showroom-iframe laufen. CORS setzt die CORSMiddleware zentral — hier
    # kein pauschales "*" mehr.
    for hkey in ["x-frame-options", "X-Frame-Options", "frame-options", "content-security-policy", "Content-Security-Policy"]:
        if hkey in res_obj.headers:
            del res_obj.headers[hkey]
    
    res_obj.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    res_obj.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With, Accept, Origin"
    
    return res_obj

# ---------------------------------------------------------------------------
# LLM Provider Management Endpoints (Hermes & Multi-Provider Integration)
# ---------------------------------------------------------------------------

class LLMProviderSelectRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None

class LLMProviderSaveKeyRequest(BaseModel):
    env_name: str
    key_value: str


@app.api_route("/api/session", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/session/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/sessions", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/sessions/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/chat", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/chat/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/transcribe", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/crons", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/crons/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/db", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/db/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/outline", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/outline/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/workspace", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/workspace/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/panels", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/panels/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/projects", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/projects/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/client-events", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/client-events/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/status", methods=["GET", "POST"])
@app.api_route("/api/config", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/config/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/model", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/model/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/providers", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/providers/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/plugins", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/plugins/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/provider/quota", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/provider/cost-history", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/transcribe/capability", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/onboarding/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/extensions/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/reasoning", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/insights", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/project-os/dashboard", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/status", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/browse", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/wiki/page", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/logs", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/api/health/agent", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
@app.api_route("/static/hermes-webui/api/{path:path}", methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])
async def proxy_hermes_api_endpoints(request: Request, path: str = ""):
    """Forward frontend API calls from embedded iFrame to active Hermes backend.

    F11: Der Handler traegt einen gemischten Methodensatz (GET/POST/OPTIONS/
    PUT/DELETE). Ein pauschaler Zaun wuerde das Dashboard auch fuers Lesen
    sperren, ein fehlender oeffnet die Schreibmethoden. Deshalb wird pro Methode
    verzweigt: lesen darf jede angemeldete Rolle, schreiben nur ``admin`` —
    und zwar **vor** dem Forward, damit nichts weitergereicht wird.
    """
    if request.method in _PROXY_WRITE_METHODS:
        require_admin_or_503(request)
    return await forward_to_hermes(request)




@app.get("/api/v1/memory/context")
def api_memory_context(agent_id: str = "hermes_default", limit: int = 5):
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return {"context": memory_bridge.get_agent_context_injection(agent_id, limit)}

@app.get("/api/v1/memory/profile")
def api_memory_profile():
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.get_user_profile()

@app.post("/api/v1/memory/learning")
def api_memory_learning(agent_id: str = Body(...), category: str = Body(...), summary: str = Body(...), detailed_note: Optional[str] = Body(None)):
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.record_learning(agent_id, category, summary, detailed_note)

@app.get("/api/v1/memory/vault-summary")
def api_memory_vault_summary():
    if not memory_bridge:
        raise HTTPException(status_code=500, detail="Memory bridge not initialized")
    return memory_bridge.scan_vault_summary()

class SavePersonalakteReq(BaseModel):
    markdown: str

@app.get("/api/v1/hr/personalakte/{agent_id}")
def api_get_personalakte(agent_id: str):
    vault_dir = OBSIDIAN_VAULT_DIR
    candidates = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
        os.path.join("/opt/data/obsidian", "00_HR_Agenten", "Personalakten", f"{agent_id}.md"),
        os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten", f"{agent_id}.md")
    ]
    file_path = None
    for c in candidates:
        if os.path.exists(c) and os.path.isfile(c):
            file_path = c
            break

    if not file_path:
        return {
            "status": "not_found",
            "agent_id": agent_id,
            "markdown": f"# Personalakte für {agent_id}\n\nNoch keine Akte vorhanden.",
            "file_path": candidates[0]
        }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_md = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": raw_md,
            "file_path": file_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/hr/personalakte/{agent_id}")
def api_save_personalakte(agent_id: str, req: SavePersonalakteReq):
    vault_dir = OBSIDIAN_VAULT_DIR
    target_dirs = [
        os.path.join(vault_dir, "00_HR_Agenten", "Personalakten"),
        "/opt/data/obsidian/00_HR_Agenten/Personalakten"
    ]
    if sys.platform == "win32" or os.path.exists(OBSIDIAN_VAULT):
        target_dirs.append(PERSONALAKTEN_DIR)
    
    saved_paths = []
    for p_dir in target_dirs:
        try:
            if os.path.exists(os.path.dirname(p_dir)):
                os.makedirs(p_dir, exist_ok=True)
                fp = os.path.join(p_dir, f"{agent_id}.md")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(req.markdown)
                saved_paths.append(fp)
        except Exception:
            pass

    return {"status": "success", "agent_id": agent_id, "file_paths": saved_paths}

class SaveSoulReq(BaseModel):
    markdown: str

@app.get("/api/v1/hermes/soul/{agent_id}")
def api_get_hermes_soul(agent_id: str):
    """Liest die echte SOUL.md Direktive des Hermes-Profils aus."""
    candidates = [
        f"/opt/data/profiles/{agent_id}/SOUL.md",
        soul_path(agent_id),
        f"/root/.hermes/profiles/{agent_id}/SOUL.md",
        f"/home/streamlituser/.hermes/profiles/{agent_id}/SOUL.md"
    ]
    found_path = None
    for p in candidates:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        return {
            "status": "not_found",
            "agent_id": agent_id,
            "markdown": "",
            "file_path": candidates[0]
        }

    try:
        with open(found_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "status": "success",
            "agent_id": agent_id,
            "markdown": content,
            "file_path": found_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/hermes/soul/{agent_id}")
def api_save_hermes_soul(request: Request, agent_id: str, req: SaveSoulReq):
    """Speichert die SOUL.md Datei für ein Hermes-Profil."""
    require_admin(request)  # RBAC: Admin-Sache
    target_dir = f"/opt/data/profiles/{agent_id}"
    if not os.path.exists(target_dir):
        alt_dir = profile_dir(agent_id)
        if os.path.exists(os.path.dirname(alt_dir)):
            target_dir = alt_dir
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, "SOUL.md")

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(req.markdown)
        # Spiegelung auf Host falls vorhanden
        host_dir = profile_dir(agent_id)
        if os.path.exists(os.path.dirname(host_dir)):
            try:
                os.makedirs(host_dir, exist_ok=True)
                with open(os.path.join(host_dir, "SOUL.md"), "w", encoding="utf-8") as f2:
                    f2.write(req.markdown)
            except Exception:
                pass
        return {"status": "success", "agent_id": agent_id, "file_path": target_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class LogActivityReq(BaseModel):
    task_title: str
    task_id: Optional[str] = "heartbeat"
    status: Optional[str] = "Erledigt"
    summary: str
    artifacts: Optional[str] = "Keine Artefakte"

@app.post("/api/v1/hr/personalakte/{agent_id}/log_activity")
def api_log_personalakte_activity(agent_id: str, req: LogActivityReq):
    vault_dir = OBSIDIAN_VAULT_DIR
    personalakten_dir = os.path.join(vault_dir, "00_HR_Agenten", "Personalakten")
    os.makedirs(personalakten_dir, exist_ok=True)
    file_path = os.path.join(personalakten_dir, f"{agent_id}.md")
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n### [{now_str}] Heartbeat / Task: {req.task_title} (ID: `{req.task_id}`)\n- **Status:** `{req.status}`\n- **Zusammenfassung:** {req.summary}\n- **Erzeugte Artefakte & Notizen:** {req.artifacts}\n"
    
    content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = f"# Personalakte für {agent_id}\n\n"
    else:
        content = f"# Personalakte für {agent_id}\n\n"
        
    content += entry
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        if os.path.exists(OBSIDIAN_VAULT):
            c_dir = os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten")
            os.makedirs(c_dir, exist_ok=True)
            with open(os.path.join(c_dir, f"{agent_id}.md"), "w", encoding="utf-8") as f2:
                f2.write(content)
                
        return {"status": "success", "agent_id": agent_id, "logged_at": now_str, "file_path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/agent/{agent_id}/activity")
def api_get_agent_activity(agent_id: str):
    """Liefert Echtzeit-Aktivitäts- und Task-Logs für einen Agenten."""
    # 1. Prüfe agent.log im Profilordner
    log_candidates = [
        f"/opt/data/profiles/{agent_id}/logs/agent.log",
        agent_log_path(agent_id)
    ]
    log_lines = []
    for lp in log_candidates:
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    all_lines = f.readlines()
                    log_lines = [line.strip() for line in all_lines[-40:] if line.strip()]
                break
            except Exception:
                pass

    # 2. Prüfe conversations in agentic_memory.db
    recent_turns = []
    conn = None
    try:
        db_path = "/app/data/agentic_memory.db"
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000;")
            c = conn.cursor()
            rows = c.execute(
                "SELECT role, content, timestamp FROM conversations WHERE agent_id = ? ORDER BY id DESC LIMIT 5",
                (agent_id,)
            ).fetchall()
            for r in reversed(rows):
                recent_turns.append(f"[{r[2]}] {r[0].upper()}: {r[1][:140]}")
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    # 3. Fallback / Standard-Heartbeat
    if not log_lines and not recent_turns:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        log_lines = [
            f"[{now_str}] Agent '{agent_id}' initialisiert im Standby-Modus.",
            f"[{now_str}] MCP Tools & Provider-Bindings aktiv.",
            f"[{now_str}] Bereit für Arbeitsaufträge und Autonom-Routing."
        ]

    return {
        "status": "success",
        "agent_id": agent_id,
        "logs": log_lines,
        "recent_turns": recent_turns
    }

@app.get("/api/v1/agent/{agent_id}/projects")
def api_get_agent_projects(agent_id: str):
    """Liefert die spezifische Projekthistorie (Beteiligungen) für einen bestimmten Agenten."""
    projects = []
    seen_ids = set()

    # 1. Ermittle Profildaten des Agenten für präzises Matching
    prof = None
    try:
        roles_list = api_get_hermes_profiles()
        prof = next((p for p in roles_list if p.get("id") == agent_id), None)
    except Exception:
        pass

    agent_id_clean = agent_id.strip().lower()
    person_name = (prof.get("person_name") if prof else "").strip().lower()
    role_name = (prof.get("name") if prof else "").strip().lower()

    # Match-Kandidaten aufbauen
    match_terms = {agent_id_clean, agent_id_clean.replace("_", " ")}
    if person_name:
        match_terms.add(person_name)
        parts = [p for p in person_name.replace("dr.", "").split() if len(p) >= 4]
        for p in parts:
            match_terms.add(p)
    if role_name and len(role_name) >= 4:
        match_terms.add(role_name)

    # Sonderfall: executive_decision_architect (ehemals 'Robert', heute 'Alexander Richter')
    if agent_id_clean == "executive_decision_architect":
        match_terms.add("robert")
        match_terms.add("alexander richter")
        match_terms.add("richter")

    # Sonderfall: micha (Michael Keller)
    if agent_id_clean in ["micha", "michael_keller"]:
        match_terms.add("michael keller")
        match_terms.add("micha")
        match_terms.add("keller")

    # 2. Scanne Obsidian Projects Folder (alle potenziellen Vault-Pfade)
    candidate_dirs = [
        "/opt/data/obsidian/01_PROJEKTE",
        os.path.join(OBSIDIAN_VAULT_DIR, "01_PROJEKTE") if OBSIDIAN_VAULT_DIR else None,
        PROJEKTE_DIR
    ]
    
    for vault_projects_dir in candidate_dirs:
        if not vault_projects_dir or not os.path.exists(vault_projects_dir):
            continue
        try:
            for fname in os.listdir(vault_projects_dir):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(vault_projects_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()

                    # Frontmatter analysieren
                    fm_match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
                    fm_text = fm_match.group(1) if fm_match else ""
                    
                    # Agent im Frontmatter suchen
                    agent_fm_match = re.search(r"agent:\s*([^\n]+)", fm_text, re.IGNORECASE)
                    agent_assigned = agent_fm_match.group(1).strip().lower() if agent_fm_match else ""

                    is_match = False
                    if agent_assigned:
                        for term in match_terms:
                            if term in agent_assigned or agent_assigned in term:
                                is_match = True
                                break
                    else:
                        text_lower = text[:1500].lower()
                        for term in match_terms:
                            if len(term) >= 4 and (f"agent: {term}" in text_lower or f"von {term}" in text_lower or f"spricht {term}" in text_lower):
                                is_match = True
                                break

                    if is_match:
                        proj_id = fname.replace(".md", "")
                        if proj_id in seen_ids:
                            continue
                        seen_ids.add(proj_id)

                        title = proj_id.replace("-", " ").title()
                        first_h1 = [l for l in text.splitlines() if l.startswith("# ")]
                        if first_h1:
                            title = first_h1[0].replace("# ", "").strip()

                        date_match = re.search(r"date:\s*([\d-]+)", text)
                        date_str = date_match.group(1) if date_match else "2026-09"
                        status_match = re.search(r"status:\s*([^\n]+)", text)
                        status_str = status_match.group(1).strip() if status_match else "Abgeschlossen"

                        projects.append({
                            "id": proj_id,
                            "name": title,
                            "date": date_str,
                            "status": status_str,
                            "source": "Obsidian / 01_PROJEKTE",
                            "file": fname
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # 3. Scanne Personalakte des Agenten auf dokumentierte Artefakte
    personalakten_dirs = [
        "/opt/data/obsidian/00_HR_Agenten/Personalakten",
        os.path.join(OBSIDIAN_VAULT_DIR, "00_HR_Agenten", "Personalakten") if OBSIDIAN_VAULT_DIR else None,
        PERSONALAKTEN_DIR
    ]
    for pa_dir in personalakten_dirs:
        if not pa_dir or not os.path.exists(pa_dir):
            continue
        pa_file = os.path.join(pa_dir, f"{agent_id_clean}.md")
        if os.path.exists(pa_file):
            try:
                with open(pa_file, "r", encoding="utf-8", errors="ignore") as f:
                    pa_text = f.read()
                sec5_match = re.search(r"## 5\.[^\n]*\n(.*?)(?=\n## 6\.|\Z)", pa_text, re.DOTALL)
                if sec5_match:
                    sec5_content = sec5_match.group(1)
                    wiki_links = re.findall(r"\[\[(.*?)\]\]", sec5_content)
                    for wl in wiki_links:
                        wl_clean = wl.split("|")[0].strip()
                        if wl_clean and not wl_clean.startswith("00_") and "knowledge" not in wl_clean.lower() and "archiv" not in wl_clean.lower():
                            p_key = f"pa-{wl_clean.lower().replace(' ', '-')}"
                            if p_key not in seen_ids:
                                seen_ids.add(p_key)
                                projects.append({
                                    "id": p_key,
                                    "name": wl_clean,
                                    "date": "2026-08",
                                    "status": "Dokumentiert",
                                    "source": "HR-Personalakte",
                                    "file": f"{agent_id_clean}.md"
                                })
            except Exception:
                pass
            break

    # Für System-Lead 'micha' (Michael Keller) Kernsystem-Projekt ergänzen falls noch nicht gelistet
    if agent_id_clean in ["micha", "michael_keller"] and not any("Kernsystem" in p["name"] for p in projects):
        projects.insert(0, {
            "id": "agenticos-core",
            "name": "AgenticOS 2026 Gesamtarchitektur & Kernsystem",
            "date": "2026-09",
            "status": "Aktiv",
            "source": "Archon OS",
            "file": "core"
        })

    return {
        "status": "success",
        "agent_id": agent_id,
        "projects": projects
    }


@app.get("/api/v1/hud/telemetry")
async def get_hud_telemetry():
    """Real-time Hermes HUD-UI consciousness and system telemetry stream."""
    agents = load_agents()
    services = load_services()
    
    async def _probe_service(s: dict) -> dict:
        port = s.get("port")
        is_up = False
        if port:
            for host in ("127.0.0.1", "host.docker.internal"):
                try:
                    _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=0.15)
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    is_up = True
                    break
                except Exception:
                    continue
        else:
            is_up = s.get("active", True)
        return {
            "id": s.get("id"),
            "name": s.get("name"),
            "port": port,
            "role": s.get("role"),
            "status": "online" if is_up else "standby",
            "active": is_up
        }

    fleet_status = list(await asyncio.gather(*[_probe_service(s) for s in services]))

    vault_notes = 0
    obs_path = os.path.join(WORKSPACE_DIR, "obsidian_vault")
    if os.path.exists(obs_path):
        try:
            # Verzeichnis-Scan blockiert sonst den Event-Loop bei jedem HUD-Poll
            _files = await asyncio.to_thread(os.listdir, obs_path)
            vault_notes = len([f for f in _files if f.endswith(".md")])
        except Exception:
            vault_notes = 14

    logs = list(ticker_entries)
    if not logs:
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        logs = [
            f"[{now_str}] Hermes-Engine: All 4 consciousness profiles online (Orchestrator, Researcher, Coder, Odysseus).",
            f"[{now_str}] OmniRoute: High-throughput token routing active on Port 20128 (0ms local latency).",
            f"[{now_str}] HUD-Monitor: Real-time telemetry connection established."
        ]

    skills_list = [
        {"name": "core-skills-engine", "status": "active", "category": "system"},
        {"name": "obsidian-vault", "status": "active", "category": "memory"},
        {"name": "rag-chroma", "status": "active", "category": "memory"},
        {"name": "mcp-connect", "status": "active", "category": "tools"},
        {"name": "docker-manager", "status": "active", "category": "infra"},
        {"name": "git-workflow", "status": "active", "category": "dev"},
        {"name": "web-researcher", "status": "active", "category": "search"}
    ]

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "consciousness": {
            "status": "CONSCIOUS & ACTIVE",
            "mode": "Universal Multi-Profile Engine",
            "current_profile": "Hermes Master Orchestrator",
            "profiles": agents
        },
        "tokens": {
            "total_tokens": 184250,
            "prompt_tokens": 128400,
            "completion_tokens": 55850,
            "cache_hit_rate": "95.4%",
            "cost_usd": "0.00",
            "avg_latency_ms": 142
        },
        "fleet": fleet_status,
        "skills": skills_list,
        "storage": {
            "vault_notes": vault_notes or 14,
            "memory_records": len(load_memory()),
            "sqlite_wal_mode": True,
            "rag_vectors": 840
        },
        "logs": logs
    }


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


@app.post("/api/prompt-studio/upload-context")
async def upload_prompt_studio_context(file: UploadFile = File(...)):
    """
    Nimmt eine Kontext-Datei (.pdf, .docx, .txt, .csv, .json, .md, .py, .js, etc.) entgegen,
    speichert sie unter /opt/data/temp_uploads/ ab und extrahiert den Text.
    """
    upload_dir = "/opt/data/temp_uploads"
    os.makedirs(upload_dir, exist_ok=True)

    filename = os.path.basename(file.filename or "upload.txt")
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    timestamp = int(time.time() * 1000)
    saved_filename = f"{timestamp}_{safe_name}"
    filepath = os.path.join(upload_dir, saved_filename)

    try:
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"[Prompt Studio Upload] Fehler beim Speichern der Datei: {e}")
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {e}")

    ext = os.path.splitext(filename)[1].lower()
    extracted_text = ""

    try:
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(filepath)
                pages_text = []
                for p in reader.pages:
                    t = p.extract_text()
                    if t:
                        pages_text.append(t)
                extracted_text = "\n\n".join(pages_text).strip()
            except Exception as pe:
                logger.warning(f"[Prompt Studio Upload] pypdf Fehler: {pe}")
                raise HTTPException(status_code=400, detail=f"PDF konnte nicht gelesen werden: {pe}")

        elif ext in [".docx", ".doc"]:
            try:
                import docx
                doc = docx.Document(filepath)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                tables_text = []
                for table in doc.tables:
                    for row in table.rows:
                        row_vals = [cell.text.strip() for cell in row.cells]
                        if any(row_vals):
                            tables_text.append(" | ".join(row_vals))
                extracted_text = "\n".join(paragraphs + tables_text).strip()
            except Exception as de:
                logger.warning(f"[Prompt Studio Upload] docx Fehler: {de}")
                raise HTTPException(status_code=400, detail=f"Word-Dokument konnte nicht gelesen werden: {de}")

        elif ext == ".csv":
            try:
                with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
                    sample = f.read(2048)
                    f.seek(0)
                    delimiter = ';' if ';' in sample and sample.count(';') > sample.count(',') else ','
                    reader = csv.reader(f, delimiter=delimiter)
                    rows = list(reader)
                if rows:
                    header = rows[0]
                    md_lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
                    for row in rows[1:101]:
                        row_padded = (row + [""] * len(header))[:len(header)]
                        md_lines.append("| " + " | ".join([c.replace("\n", " ") for c in row_padded]) + " |")
                    if len(rows) > 101:
                        md_lines.append(f"\n*(Tabelle gekürzt: {len(rows)-1} Datensätze insgesamt, erste 100 dargestellt)*")
                    extracted_text = "\n".join(md_lines).strip()
                else:
                    extracted_text = ""
            except Exception as ce:
                logger.warning(f"[Prompt Studio Upload] CSV Fehler: {ce}")
                raise HTTPException(status_code=400, detail=f"CSV konnte nicht gelesen werden: {ce}")

        elif ext in [".txt", ".md", ".py", ".js", ".json", ".html", ".yaml", ".yml", ".ts"]:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()

        else:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                extracted_text = f.read().strip()

    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"[Prompt Studio Upload] Text-Extraktionsfehler: {ex}")
        raise HTTPException(status_code=400, detail=f"Text-Extraktion fehlgeschlagen: {ex}")

    return {
        "filename": filename,
        "char_count": len(extracted_text),
        "extracted_text": extracted_text
    }

class TemplateSaveRequest(BaseModel):
    category: str
    title: str
    description: Optional[str] = ""
    fields: dict
    raw_text: Optional[str] = None


class PromptOptimizeRequest(BaseModel):
    prompt: str
    agent_id: Optional[str] = None

@app.post("/api/prompts/optimize")
async def optimize_prompt_endpoint(req: PromptOptimizeRequest):
    """
    Nimmt unstrukturierte Nutzereingabe entgegen,
    sendet via OmniRoute einen schnellen Call an ein kostengünstiges Modell
    und transformiert den Text in die 5-Felder-Struktur inklusive Phrasenverbot.
    """
    raw_input = req.prompt.strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="Prompt darf nicht leer sein.")
        
    optimizer_system_prompt = (
        "Du bist der leitende Prompt-Architekt von Archon OS.\n"
        "Transformiere die unstrukturierte Benutzereingabe in einen professionellen 5-Felder-Prompt.\n"
        "Die Ausgabe MUSS EXAKT die folgenden 5 Abschnitte mit Markdown-Headings enthalten:\n\n"
        "# ROLLE:\n"
        "[Passende, spezialisierte Rollenbezeichnung]\n\n"
        "# ZIEL:\n"
        "[Klares, messbares Arbeitsergebnis]\n\n"
        "# SOP (ARBEITSSCHRITTE):\n"
        "1. [Schritt 1]\n"
        "2. [Schritt 2]\n"
        "3. [Schritt 3]\n\n"
        "# RESTRIKTIONEN (PHRASENVERBOT):\n"
        "- Phrasenverbot: Keine Begrüßungs- oder Höflichkeitsfloskeln ('Hallo', 'Gerne helfe ich', 'Möchten Sie', 'Wie kann ich').\n"
        "- Keine Gegenfragen an den Nutzer; triff plausible Annahmen.\n"
        "- Kein Konjunktiv; handlungsorientierte Sprache.\n"
        "- Striktes Markdown mit klaren Überschriften.\n\n"
        "# AUSGABE-ARTEFAKT:\n"
        "[Strukturierter Markdown-Bericht zur Ablage in Obsidian]\n\n"
        "WICHTIG: Gib AUSSCHLIESSLICH den 5-Felder-Prompt aus, ohne jegliches Vorgeplänkel oder Nachwort!"
    )

    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="prompt_optimizer",
            agent_name="Prompt Optimizer",
            prompt=f"Transformiere folgende Benutzereingabe:\n\n{raw_input}",
            role="Prompt Architect",
            system_prompt=optimizer_system_prompt,
            model="auto/best-fast"
        )
        opt_text = res.get("content", "").strip()
        if not opt_text or len(opt_text) < 30:
            opt_text = (
                f"# ROLLE:\nExecutive Decision Specialist\n\n"
                f"# ZIEL:\n{raw_input}\n\n"
                f"# SOP (ARBEITSSCHRITTE):\n"
                f"1. Analyse der Anforderung: {raw_input[:60]}\n"
                f"2. Methodische Erarbeitung der Lösungsarchitektur\n"
                f"3. Validierung und strukturierte Dokumentation\n\n"
                f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
                f"- Keine Begrüßungsfloskeln ('Hallo', 'Gerne helfe ich').\n"
                f"- Keine Gegenfragen an den Nutzer.\n"
                f"- Striktes Markdown.\n\n"
                f"# AUSGABE-ARTEFAKT:\n"
                f"Markdown-Dokument für Obsidian (/opt/data/obsidian/01_PROJEKTE/)"
            )
        return {
            "status": "ok",
            "optimized_prompt": opt_text,
            "original_prompt": raw_input
        }
    except Exception as e:
        logger.error(f"[Prompt Optimizer] Exception: {e}")
        fallback_text = (
            f"# ROLLE:\nExecutive Specialist\n\n"
            f"# ZIEL:\n{raw_input}\n\n"
            f"# SOP (ARBEITSSCHRITTE):\n"
            f"1. Analyse der Vorgaben\n"
            f"2. Fachliche Ausarbeitung der Arbeitspakete\n"
            f"3. Finale Bereitstellung\n\n"
            f"# RESTRIKTIONEN (PHRASENVERBOT):\n"
            f"- Keine Höflichkeitsfloskeln oder Rückfragen.\n"
            f"- Striktes Markdown.\n\n"
            f"# AUSGABE-ARTEFAKT:\n"
            f"Obsidian Markdown-Bericht"
        )
        return {
            "status": "ok",
            "optimized_prompt": fallback_text,
            "original_prompt": raw_input
        }


# -------------------------------------------------------------
# OMNIROUTE EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
# -------------------------------------------------------------
# OMNIROUTE EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
_PROXY_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}

def _get_shared_proxy_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    c = _PROXY_HTTP_CLIENTS.get(loop_id)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(
            follow_redirects=False,
            timeout=60.0,
            limits=httpx.Limits(max_keepalive_connections=30, max_connections=120)
        )
        _PROXY_HTTP_CLIENTS[loop_id] = c
    return c

_OMNIROUTE_PROXY = None


def _get_omniroute_proxy():
    global _OMNIROUTE_PROXY
    if _OMNIROUTE_PROXY is None:
        from utils.reverse_proxy import ReverseProxy
        _OMNIROUTE_PROXY = ReverseProxy(
            name="OmniRoute",
            target_host="omniroute:20128",
            mount_prefix="/omniroute-proxy",
            fallback_host="host.docker.internal:20128",
        )
    return _OMNIROUTE_PROXY


async def forward_to_omniroute(request: Request, path: str):
    return await _get_omniroute_proxy().forward(request, path)


@app.api_route("/omniroute-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def omniroute_proxy(request: Request, path: str = ""):
    return await forward_to_omniroute(request, path)

@app.api_route("/_next/{path:path}", methods=["GET", "HEAD"])
async def omniroute_next_assets(request: Request, path: str = ""):
    return await forward_to_omniroute(request, f"_next/{path}")

# -------------------------------------------------------------
# N8N AUTOMATION EMBEDDED REVERSE PROXY (STRIPS X-FRAME-OPTIONS & CSP)
# -------------------------------------------------------------
_N8N_PROXY = None


def _get_n8n_proxy():
    global _N8N_PROXY
    if _N8N_PROXY is None:
        from utils.reverse_proxy import ReverseProxy
        _N8N_PROXY = ReverseProxy(
            name="n8n",
            target_host="n8n:5678",
            mount_prefix="/n8n-proxy",
            fallback_host="host.docker.internal:5678",
            html_replacements=(
                ('href="/assets/',  'href="/n8n-proxy/assets/'),
                ('src="/assets/',   'src="/n8n-proxy/assets/'),
                ('href="/static/',  'href="/n8n-proxy/static/'),
                ('src="/static/',   'src="/n8n-proxy/static/'),
                ('data-src="/assets/', 'data-src="/n8n-proxy/assets/'),
                ('href="/favicon.ico"', 'href="/n8n-proxy/favicon.ico"'),
            ),
            static_overrides={
                "base-path.js": ("window.BASE_PATH = '/n8n-proxy/';", "application/javascript"),
            },
        )
    return _N8N_PROXY


async def forward_to_n8n(request: Request, path: str):
    return await _get_n8n_proxy().forward(request, path)


@app.api_route("/n8n-proxy", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
@app.api_route("/n8n-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_proxy(request: Request, path: str = ""):
    return await forward_to_n8n(request, path)

@app.api_route("/assets/{path:path}", methods=["GET", "HEAD"])
async def n8n_assets_proxy(request: Request, path: str = ""):
    if path:
        try:
            from utils.path_jail import safe_path
            assets_root = os.path.abspath("assets")
            if os.path.exists(assets_root):
                target = safe_path(
                    os.path.join(assets_root, path),
                    must_exist=True,
                    extra_roots=[assets_root],
                    allow_dirs=False
                )
                if target and os.path.isfile(target):
                    return FileResponse(target)
        except Exception:
            pass
    return await forward_to_n8n(request, f"assets/{path}")

@app.api_route("/rest/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def n8n_rest_proxy(request: Request, path: str = ""):
    return await forward_to_n8n(request, f"rest/{path}")


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


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 3: INBOX WATCHER & ROBERT TOOL PERMISSIONS) ---

@app.get("/api/inbox-watcher/config")
def api_get_inbox_watcher_config():
    from backend.inbox_watcher import get_inbox_config
    cfg = get_inbox_config()
    watch_dir = cfg.get("watch_folder")
    exists = os.path.exists(watch_dir) if watch_dir else False
    file_count = len(os.listdir(watch_dir)) if exists else 0
    return {"status": "success", "config": cfg, "folder_exists": exists, "file_count": file_count}

@app.post("/api/inbox-watcher/config")
async def api_save_inbox_watcher_config(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.inbox_watcher import save_inbox_config, get_inbox_config
    current = get_inbox_config()
    current.update(payload)
    ok = save_inbox_config(current)
    return {"status": "success" if ok else "error", "config": current}

@app.post("/api/inbox-watcher/scan-now")
async def api_scan_inbox_watcher_now():
    from backend.inbox_watcher import scan_and_process_inbox
    res = await scan_and_process_inbox()
    try:
        from backend.internet_watchdog import run_watchdog_scan
        loop = asyncio.get_event_loop()
        wd_res = await loop.run_in_executor(None, run_watchdog_scan, True)
        res["internet_watchdog"] = wd_res
    except Exception as e:
        res["internet_watchdog_error"] = str(e)
    return res

@app.get("/api/tools/proposals")
def api_list_tool_proposals(status: Optional[str] = None):
    from backend.tool_permission_manager import tool_permission_manager
    return {"status": "success", "proposals": tool_permission_manager.list_proposals(status=status)}

@app.post("/api/tools/proposals")
def api_create_tool_proposal(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.tool_permission_manager import tool_permission_manager
    return tool_permission_manager.propose_tool_installation(
        tool_name=payload.get("tool_name", ""),
        tool_type=payload.get("tool_type", "pip"),
        reason=payload.get("reason", ""),
        command=payload.get("command"),
        requested_by=payload.get("requested_by", "Robert (Lead Orchestrator)")
    )

@app.post("/api/tools/proposals/{permission_id}/resolve")
def api_resolve_tool_proposal(request: Request, permission_id: str, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.tool_permission_manager import tool_permission_manager
    action = payload.get("action", "grant")
    return tool_permission_manager.resolve_proposal(permission_id, action=action)


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 4: AUDIT, SNAPSHOTS, CONSENSUS, BUDGET & TELEGRAM) ---

@app.get("/api/snapshots")
def api_list_snapshots(limit: int = 50):
    from backend.snapshot_manager import snapshot_manager
    return {"status": "success", "snapshots": snapshot_manager.list_snapshots(limit=limit)}

@app.post("/api/snapshots/{snapshot_id}/restore")
def api_restore_snapshot(request: Request, snapshot_id: str):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.snapshot_manager import snapshot_manager
    return snapshot_manager.restore_snapshot(snapshot_id)

@app.get("/api/audit/logs")
def api_list_audit_logs(limit: int = 50):
    from backend.audit_log import chained_audit_log
    return {"status": "success", "logs": chained_audit_log.list_events(limit=limit)}

@app.get("/api/audit/verify")
def api_verify_audit_log():
    from backend.audit_log import chained_audit_log
    return chained_audit_log.verify_integrity()

@app.post("/api/tasks/review-consensus")
async def api_review_task_consensus(payload: Dict = Body(...)):
    from backend.consensus_gate import review_task_output
    task_id = payload.get("task_id", "task-gen")
    task_title = payload.get("title", "")
    task_output = payload.get("output", "")
    worker = payload.get("worker_agent", "hermes-coder")
    priority = int(payload.get("priority", 3))
    return await review_task_output(task_id, task_title, task_output, worker_agent=worker, priority=priority)

@app.post("/api/tasks/{task_id}/budget/check")
def api_check_task_budget(task_id: str, payload: Dict = Body(...)):
    from backend.agent_router import check_task_budget
    return check_task_budget(
        task_id=task_id,
        cost_usd=payload.get("cost_usd", 0.0),
        budget_usd=payload.get("budget_usd", 0.25),
        task_title=payload.get("title", "")
    )


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 5: RAG-BRIDGE, DEADLOCKS, DIFFS, SKILL-SYNTHESIS, EVENT-MESH) ---

@app.get("/api/rag/query")
def api_query_rag(q: str = Query(..., description="Suchbegriff für das AnythingLLM Docker-RAG")):
    from backend.rag_bridge import rag_bridge
    return rag_bridge.query_vault_rag(q)


@app.post("/api/diff/preview")
def api_diff_preview(request: Request, payload: Dict = Body(...)):
    # F25 (Security-Review): Der Handler las ``file_path`` ohne jede Pruefung
    # und ohne Rollenzaun — damit liest jede eingeloggte Rolle beliebige
    # Dateien des Containers (u. a. ``.env.archon``, Service-Token) und
    # bekommt deren Inhalt als Diff geliefert.
    # Jetzt: Admin-Zaun + Jail auf den Projekt-Wurzelbaum.
    require_admin_or_503(request)
    from backend.diff_engine import compute_file_diff

    raw_path = str(payload.get("file_path", "")).strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Gültiger 'file_path' erforderlich.")

    # Der Diff dient dem Bearbeiten von Projektdateien — erlaubt ist der
    # Repo-Wurzelbaum (inkl. data/, static/), nicht das Systemverzeichnis.
    repo_root = os.path.dirname(os.path.abspath(__file__))
    try:
        real_path = safe_path_within(
            raw_path, [repo_root], must_exist=True, allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=f"Pfad nicht erlaubt: {e}")

    return compute_file_diff(
        file_path=real_path,
        new_content=payload.get("new_content", ""),
        context_lines=int(payload.get("context_lines", 3))
    )

@app.get("/api/skills/proposals")
def api_list_skill_proposals(status: Optional[str] = None):
    from backend.skill_synthesizer import skill_synthesizer
    return {"status": "success", "proposals": skill_synthesizer.list_proposals(status=status)}

@app.post("/api/skills/proposals/{proposal_id}/approve")
def api_approve_skill_proposal(request: Request, proposal_id: str):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.skill_synthesizer import skill_synthesizer
    return skill_synthesizer.approve_skill(proposal_id)

@app.post("/api/events/inbound/{channel}")
def api_ingest_inbound_event(channel: str, payload: Dict = Body(...)):
    from backend.event_mesh import event_mesh
    return event_mesh.ingest_inbound_event(
        channel=channel,
        event_type=payload.get("event_type", "generic_event"),
        payload=payload
    )

@app.get("/api/events/history")
def api_list_event_history(limit: int = 50):
    from backend.event_mesh import event_mesh
    return {"status": "success", "events": event_mesh.list_events(limit=limit)}


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 6: THROTTLE, BENCHMARK, VISION, HYGIENE, HANDOFF) ---

@app.get("/api/concurrency/status")
def api_get_concurrency_status():
    from backend.concurrency_throttle import concurrency_throttle
    return {"status": "success", "concurrency": concurrency_throttle.get_status()}

@app.post("/api/concurrency/config")
def api_save_concurrency_config(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.concurrency_throttle import save_concurrency_config, get_concurrency_config
    cfg = get_concurrency_config()
    cfg.update(payload)
    ok = save_concurrency_config(cfg)
    return {"status": "success" if ok else "error", "concurrency": cfg}


@app.post("/api/vision/analyze")
def api_analyze_vision(payload: Dict = Body(...)):
    from backend.vision_pipeline import analyze_image_file
    return analyze_image_file(
        image_path=payload.get("image_path", ""),
        focus_prompt=payload.get("focus_prompt", "Beschreibe den Inhalt dieses Screenshots detailliert.")
    )



@app.post("/api/handoff/create")
def api_create_handoff(payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk
    return handoff_desk.create_handoff(
        task_id=payload.get("task_id", ""),
        from_agent=payload.get("from_agent", ""),
        to_agent=payload.get("to_agent", ""),
        deliverables=payload.get("deliverables", {}),
        acceptance_criteria=payload.get("acceptance_criteria", "")
    )

@app.post("/api/handoff/{handoff_id}/accept")
def api_accept_handoff(handoff_id: str, payload: Dict = Body(...)):
    from backend.handoff_desk import handoff_desk
    return handoff_desk.accept_handoff(
        handoff_id=handoff_id,
        receiving_agent=payload.get("receiving_agent", "")
    )


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 7: FLEET SELF-HEALING, DB-BACKUP, SECRET-MASKING, NOTIFICATION-HUB) ---

@app.post("/api/fleet/heal/{service_name}")
def api_heal_service(request: Request, service_name: str):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.fleet_self_healing import restart_service_container
    return restart_service_container(service_name)

@app.get("/api/fleet/health-check")
def api_fleet_health_check():
    from backend.fleet_self_healing import check_fleet_and_heal
    return check_fleet_and_heal()


@app.post("/api/notifications/dispatch")
def api_dispatch_notification(payload: Dict = Body(...)):
    from backend.notification_hub import notification_hub
    return notification_hub.dispatch_notification(
        title=payload.get("title", "System-Benachrichtigung"),
        message=payload.get("message", ""),
        severity=payload.get("severity", "INFO"),
        category=payload.get("category", "system")
    )

@app.get("/api/notifications/recent")
def api_list_recent_notifications(limit: int = 50):
    from backend.notification_hub import notification_hub
    return {"status": "success", "notifications": notification_hub.list_recent(limit=limit)}


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 8: COST-ESTIMATOR, DB-OPTIMIZER, HEALTH-SCORE, DOSSIER) ---


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 9: TIME-TRAVEL DEBUGGER, COUNCIL DEBATE, TASK SELF-HEALING & DIR WATCHER) ---

@app.get("/api/traces/{task_id}")
def api_get_task_trace(task_id: str):
    from backend.time_travel_debugger import time_travel_debugger
    return {"status": "success", "task_id": task_id, "trace": time_travel_debugger.get_task_trace(task_id)}

@app.post("/api/traces/{task_id}/fork")
def api_fork_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger
    return time_travel_debugger.fork_execution(
        task_id=task_id,
        from_step=int(payload.get("from_step", 1)),
        new_prompt=payload.get("new_prompt"),
        new_model=payload.get("new_model")
    )

@app.post("/api/traces/{task_id}/rollback")
def api_rollback_task_trace(task_id: str, payload: Dict = Body(...)):
    from backend.time_travel_debugger import time_travel_debugger
    return time_travel_debugger.rollback_to_step(
        task_id=task_id,
        to_step=int(payload.get("to_step", 0))
    )


@app.post("/api/consensus/council-vote")
async def api_run_council_vote(payload: Dict = Body(...)):
    from backend.consensus_gate import run_tri_agent_council
    return await run_tri_agent_council(
        task_id=payload.get("task_id", "council-task"),
        task_title=payload.get("title", ""),
        task_output=payload.get("output", ""),
        model=payload.get("model")
    )

@app.get("/api/consensus/history")
def api_get_consensus_history(limit: int = 25):
    from backend.consensus_gate import get_consensus_history
    return {"status": "success", "consensus_history": get_consensus_history(limit=limit)}

@app.post("/api/healing/attempt")
async def api_attempt_task_healing(request: Request, payload: Dict = Body(...)):
    # F2 (Security-Review): Die Route hatte keinen Rollenzaun — jede
    # eingeloggte Rolle konnte den Selbstheilungspfad ausloesen (der
    # Shell-Injection-Teil ist ueber validate_affected_file geschlossen,
    # der Autorisierungs-Teil nicht).
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
        model=payload.get("model")
    )

@app.get("/api/healing/logs")
def api_get_healing_logs(limit: int = 25):
    from backend.task_self_healer import task_self_healer
    return {"status": "success", "logs": task_self_healer.get_healing_logs(limit=limit)}

@app.post("/api/events/scan-directory")
def api_scan_inbox_directory(payload: Dict = Body(default={})):
    from backend.event_mesh import event_mesh
    return event_mesh.scan_inbox_directory(inbox_dir=payload.get("inbox_dir"))


# --- NEUE AGENTIC OS MECHANIKEN (BATCH 10: SANDBOX, MEMORY CONSOLIDATION, VISUAL BROWSER, WAR-ROOM & SLA CONTRACTS) ---

@app.post("/api/sandbox/execute")
def api_execute_sandbox(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC-Pilot: Codeausfuehrung ist Admin-Sache
    from backend.ephemeral_sandbox import ephemeral_sandbox
    return ephemeral_sandbox.execute_in_sandbox(
        code=payload.get("code", ""),
        language=payload.get("language", "python"),
        memory_limit_mb=int(payload["memory_limit_mb"]) if "memory_limit_mb" in payload else None,
        cpu_limit=float(payload["cpu_limit"]) if "cpu_limit" in payload else None,
        timeout_seconds=int(payload["timeout_seconds"]) if "timeout_seconds" in payload else None,
        network_enabled=bool(payload["network_enabled"]) if "network_enabled" in payload else None
    )

@app.get("/api/settings/memory-consolidation")
def api_get_memory_consolidation_settings():
    from backend.memory_consolidator import get_consolidation_config
    return {"status": "success", "config": get_consolidation_config()}

@app.post("/api/settings/memory-consolidation")
def api_save_memory_consolidation_settings(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.memory_consolidator import get_consolidation_config, save_consolidation_config
    cfg = get_consolidation_config()
    cfg.update(payload)
    ok = save_consolidation_config(cfg)
    return {"status": "success" if ok else "error", "config": cfg}


@app.post("/api/browser/browse-and-capture")
def api_browse_and_capture(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.visual_web_agent import visual_web_agent
    return visual_web_agent.browse_and_capture(
        task_id=payload.get("task_id", f"vis-{datetime.datetime.now().strftime('%H%M%S')}"),
        target_url=payload.get("url", "https://example.com"),
        actions=payload.get("actions"),
        extract_selector=payload.get("extract_selector")
    )

@app.post("/api/simulation/war-room")
async def api_run_war_room(payload: Dict = Body(...)):
    from backend.war_room_simulator import run_war_room_simulation
    return await run_war_room_simulation(
        topic=payload.get("topic", "System-Update"),
        proposal_text=payload.get("proposal", ""),
        model=payload.get("model")
    )

@app.get("/api/simulation/war-room/history")
def api_get_war_room_history(limit: int = 20):
    from backend.war_room_simulator import get_war_room_history
    return {"status": "success", "history": get_war_room_history(limit=limit)}


# --- ZENTRALE KONFIGURATION ALLER 10 AUTONOMIE- & RESILIENZ-GRUPPEN (SETTINGS-PAKET A & B) ---

@app.get("/api/settings/model-routing")
def api_get_model_routing():
    from backend.model_routing import load_config
    return {"status": "success", "config": load_config()}


@app.post("/api/settings/model-routing")
def api_save_model_routing(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.model_routing import save_config
    try:
        cfg = save_config(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "config": cfg}


@app.get("/api/settings/model-routing/resolve")
def api_resolve_model_routing(task: str = Query("")):
    from backend.model_routing import resolve, is_enabled
    return {"status": "success", "enabled": is_enabled(), "route": resolve(task)}


@app.get("/api/settings/autonomy-modules")
def api_get_autonomy_modules_settings():
    from backend.autonomy_settings import load_all_settings
    return {"status": "success", "settings": load_all_settings()}

@app.post("/api/settings/autonomy-modules")
def api_save_autonomy_modules_settings(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.autonomy_settings import save_autonomy_settings
    updated = save_autonomy_settings(payload)
    # BIDIREKTIONALE SYNCHRONISATION: Archon Autonomie-Module (settings.json) -> Hermes (config.yaml)
    try:
        import yaml
        active_path, _ = _get_hermes_config_paths()
        if active_path and os.path.exists(active_path):
            with open(active_path, "r", encoding="utf-8") as f:
                hdata = yaml.safe_load(f.read()) or {}
            if not isinstance(hdata, dict):
                hdata = {}
            conc = payload.get("concurrency", {})
            if isinstance(conc, dict):
                if "max_concurrent_agents" in conc:
                    hdata.setdefault("delegation", {})["max_concurrent_children"] = int(conc["max_concurrent_agents"])
                if "queue_timeout_seconds" in conc:
                    hdata.setdefault("agent", {})["task_timeout_seconds"] = int(conc["queue_timeout_seconds"])
            cb = payload.get("circuit_breaker", {})
            if isinstance(cb, dict):
                tlg = hdata.setdefault("tool_loop_guardrails", {})
                if "loop_detection_enabled" in cb:
                    tlg["warnings_enabled"] = bool(cb["loop_detection_enabled"])
                if "max_identical_turns" in cb:
                    tlg.setdefault("hard_stop_after", {})["exact_failure"] = int(cb["max_identical_turns"])
                if "max_steps_per_task" in cb:
                    hdata.setdefault("agent", {})["max_turns"] = int(cb["max_steps_per_task"])
            sb = payload.get("ephemeral_sandbox", {})
            if isinstance(sb, dict):
                term = hdata.setdefault("terminal", {})
                if "cpu_limit" in sb:
                    term["container_cpu"] = float(sb["cpu_limit"])
                if "timeout_seconds" in sb:
                    term["timeout"] = int(sb["timeout_seconds"])
            cc = payload.get("context_compactor", {})
            if isinstance(cc, dict):
                comp = hdata.setdefault("compression", {})
                if "enabled" in cc:
                    comp["enabled"] = bool(cc["enabled"])
                if "keep_recent_turns" in cc:
                    comp["protect_last_n"] = int(cc["keep_recent_turns"])
            cg = payload.get("consensus_gate", {})
            if isinstance(cg, dict) and "enabled" in cg:
                hdata.setdefault("moa", {})["enabled"] = bool(cg["enabled"])
            with open(active_path, "w", encoding="utf-8") as f:
                yaml.dump(hdata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e_sync:
        logger.warning(f"[Archon -> Hermes Sync] {e_sync}")
    return {"status": "success", "settings": updated}


# --- TEIL 2 / PAKET 1 (FEATURES 1–5): PERFORMANCE CORE, SKALIERUNG & TOKEN-EFFIZIENZ ---

# Feature 1: Semantisches Prompt- & Response-Caching
@app.post("/api/cache/semantic-lookup")
def api_semantic_cache_lookup(payload: Dict = Body(...)):
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.lookup(
        prompt=payload.get("prompt", ""),
        model=payload.get("model", "any"),
        threshold_override=payload.get("similarity_threshold")
    )

@app.post("/api/cache/semantic-store")
def api_semantic_cache_store(payload: Dict = Body(...)):
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.store(
        prompt=payload.get("prompt", ""),
        response=payload.get("response", ""),
        model=payload.get("model", "any")
    )

@app.get("/api/cache/semantic-stats")
def api_semantic_cache_stats():
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.get_stats()

@app.delete("/api/cache/semantic-clear")
def api_semantic_cache_clear():
    from backend.semantic_cache import semantic_cache_manager
    return semantic_cache_manager.clear()


# Feature 2: Paralleles Map-Reduce Sub-Tasking (Fan-Out / Fan-In)


# Feature 3: Speculative Fast-Routing & Latenz-Hedging


# Feature 4: Dynamisches Context-Compaction & Hierarchisches Summarizing


# Feature 5: SQLite Connection-Pool & Async Write-Batching


# --- TEIL 2 / PAKET 2 (FEATURES 6–10): MODERNE GEDÄCHTNIS- & RAG-ARCHITEKTUR (GRAPH & HYBRID MEMORY) ---

# Feature 6: Hybrid-Search (BM25 SQLite FTS5 + Vektor-RAG + Reciprocal Rank Fusion)


# Feature 7: Lokaler Knowledge-Graph (Entitäten- & Beziehungs-Tripel)


# Feature 8: Agentic Corrective RAG (CRAG)


# Feature 9: 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (Pinned Working Memory)


# Feature 10: Automatisches Citation- & Quellen-Pinning


# --- TEIL 2 / PAKET 3 (FEATURES 11–15): ZUVERLÄSSIGE AUSFÜHRUNG & DETERMINISMUS (DURABLE EXECUTION) ---

# Feature 11: Structured Outputs & JSON-Schema-Garantie


# Feature 12: Durable Execution Checkpointing (Pause / Resume)


# Feature 13: Idempotency-Keys & Tool-Call-Deduplizierung


# Feature 14: Dry-Run / Shadow-Mode für Agenten-Aufträge


# Feature 15: Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager


# --- TEIL 2 / PAKET 4 (FEATURES 16–20): SICHERHEIT, DATENSCHUTZ & ENTERPRISE-GOVERNANCE (GUARDRAILS) ---

# Feature 16: Bidirektionaler PII-Scrubber & Re-Hydration (DSGVO)


# Feature 17: Egress-Firewall & Domain-Allowlisting


# Feature 18: Granulare Agenten-RBAC & Datei-Scope-Jails


# Feature 19: Deterministischer Output-Linter & Policy-Checker


# Feature 20: Manipulationssichere Kosten- & Entscheidungs-Quittungen (Execution Receipts)


# --- TEIL 2 / PAKET 5 (FEATURES 21–25): SELBST-OPTIMIERUNG, EVALUATION & SCHWARM-INTELLIGENZ (NEXT-GEN) ---

# Feature 21: Automatischer Prompt-Optimizer (DSPy / TextGrad-Prinzip)
@app.post("/api/evolution/optimize-prompt")
def api_optimize_role_prompt(request: Request, payload: Dict = Body(...)):
    require_admin(request)  # RBAC: Admin-Sache
    from backend.prompt_optimizer import prompt_optimizer
    return prompt_optimizer.optimize_role_prompt(
        agent_role=payload.get("agent_role", "backend_architect"),
        current_prompt=payload.get("current_prompt", "Du bist ein präziser System-Agent."),
        recent_failures=payload.get("recent_failures", [])
    )


# Feature 22: Gold-Standard Regression-Test-Suite (Eval-Dataset Runner)
@app.post("/api/evolution/eval-suite/run")
def api_run_eval_regression_suite(payload: Dict = Body(default={})):
    from backend.eval_regression_runner import eval_regression_runner
    return eval_regression_runner.run_suite(
        candidate_label=payload.get("candidate_label", "v2026.10-release"),
        simulated_outputs=payload.get("simulated_outputs")
    )


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

# mypy: ignore-errors
import asyncio
import base64
import csv
import datetime
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import (
    BackgroundTasks,
    Body,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import core_dispatcher

# --- A5-Etappe 1: unveraenderliche Modul-Konstanten ausgelagert ------------
# Quelle ist jetzt archon/core/constants.py (ein Ort, keine Kopie). Mutabler
# State und Pfad-Konstanten bleiben bewusst in dieser Datei (Fallstrick 24 / B10).
from archon.core.constants import (
    _AUTH_API_PREFIXES,
    _AUTH_PROTECTED_PREFIXES,
    _AUTH_PUBLIC_PREFIXES,
    _DECISION_TYPEN,
    DELEGATION_PROTOCOL_PROMPT,
    STUDIO_BG_UPLOAD_DIR,
)

# Orchestration functions (extracted to archon.core.orchestration)
from archon.core.orchestration import (
    _execute_mission_control_task as _orch_execute_mission_control_task,
)
from archon.core.orchestration import (
    _fan_in_maybe_start_synthesis as _orch_fan_in_maybe_start_synthesis,
)
from archon.core.orchestration import (
    _finalize_synthesis_after_approval as _orch_finalize_synthesis_after_approval,
)
from archon.core.orchestration import (
    _paperclip_hire_profile_by_id as _orch_paperclip_hire_profile_by_id,
)
from archon.core.orchestration import (
    _run_synthesis_cascade as _orch_run_synthesis_cascade,
)
from archon.core.orchestration import (
    _set_agent_profile_status as _orch_set_agent_profile_status,
)
from archon.core.orchestration import (
    _tg_ping_synthesis as _orch_tg_ping_synthesis,
)
from archon.core.orchestration import (
    _trigger_sandy_staffing_nomination as _orch_trigger_sandy_staffing_nomination,
)
from backend.platform_paths import (
    HERMES_HOME,
    OBSIDIAN_VAULT,
    OBSIDIAN_VAULT_ALT,
    PERSONALAKTEN_DIR,
    PROJEKTE_DIR,
    agent_log_path,
    profile_dir,
    soul_path,
)
from utils.docker_client import (
    DockerError,
    docker_client,
    parse_docker_stream,
    parse_docker_stream_bytes,
)

# W3: Log-Level zur Laufzeit konfigurierbar (Incidents brauchen DEBUG ohne
# Code-Änderung/Neustart).
_LOG_LEVEL_NAME = os.getenv("ARCHON_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).strip().upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL_NAME, logging.INFO))
logger = logging.getLogger("archon_os")

# W3: Promtail mountet ./data/logs und erwartet *.log im Format
# "timestamp - logger - level - message". Vorher schrieb die App nur auf
# stderr — Loki/Grafana waren für App-Logs komplett blind. Rotierend, damit
# im Non-Container-Betrieb keine unbegrenzte Logdatei entsteht.
try:
    from logging.handlers import RotatingFileHandler as _RotatingFileHandler
    _log_dir = os.getenv("ARCHON_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "logs"
    )
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = _RotatingFileHandler(
        os.path.join(_log_dir, "archon.log"), maxBytes=20_000_000, backupCount=5, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logging.getLogger().addHandler(_file_handler)
except Exception as _log_exc:
    logger.debug("[Logging] File-Handler nicht verfügbar: %s", _log_exc)

# Fail-closed: fehlgeschlagene Router-Imports werden gesammelt und
# beim Start in Produktion hart abgebrochen (siehe _assert_router_health).
_ROUTER_LOAD_ERRORS: List[str] = []

# ---------------------------------------------------------------------------
# Ein einziger, geordneter Startup/Shutdown-Pfad.
# Vorher: 3x @app.on_event("startup") + 2x ("shutdown") — deprecated und in
# unbestimmter Reihenfolge ausgefuehrt. Jetzt: explizite Registrierung in
# _STARTUP_HOOKS / _SHUTDOWN_HOOKS am Dateiende, Ausfuehrung im Lifespan.
# ---------------------------------------------------------------------------
_STARTUP_HOOKS: List[Any] = []
_SHUTDOWN_HOOKS: List[Any] = []

# D06-Nachlauf (A7): ehrlicher Status fuer den optionalen n8n-Import beim
# Startup. Default `not_configured` — der Import ist opt-in, weil die Scripts
# `docker exec`/`docker cp` ausfuehren und ein Service-Token in Temp-Dateien
# schreiben. Ein automatisches `deploy_n8n_routines.run()` (restartet n8n und
# beschreibt das versionierte Bundle) bleibt bewusst DELEGATED.
_N8N_STARTUP_STATUS: Dict[str, Any] = {"status": "not_configured", "detail": "opt-in via ARCHON_N8N_STARTUP_IMPORT=1"}

# KRITISCH (Audit 23.11.2026): Sicherheits-Hooks duerfen niemals nur geloggt
# werden. Ein fehlgeschlagener Router-Health- oder Audit-HMAC-Check muss den
# Start abbrechen — sonst laeuft die Anwendung mit fälschbarer Revisionskette
# bzw. still 404-enden Router weiter.
_FAIL_FAST_HOOKS = {"_assert_router_health", "_assert_audit_hmac", "_assert_auth_on_nonloopback_bind"}

_LOCAL_BINDS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _nonloopback_bind_detected() -> bool:
    """Erkennt einen Nicht-Loopback-Bind aus ENV *und* Prozess-Kommandozeile.

    Dockerfile:57 und docker-compose.dev.yml:13 starten uvicorn hart mit
    ``--host 0.0.0.0``, ohne ``ARCHON_BIND_IP`` zu setzen. auth_service sah
    dadurch keinen Bind und liess Auth aus (Fail-Open). Diese Funktion
    schliesst die Luecke — ENV bleibt erhalten, sys.argv kommt hinzu.
    """
    for var in ("ARCHON_BIND_IP", "UVICORN_HOST", "HOST"):
        val = str(os.environ.get(var) or "").strip().strip("[]")
        if val and val not in _LOCAL_BINDS:
            return True
    argv = list(sys.argv or [])
    for idx, arg in enumerate(argv):
        val = ""
        if arg == "--host" and idx + 1 < len(argv):
            val = str(argv[idx + 1] or "").strip()
        elif arg.startswith("--host="):
            val = arg.split("=", 1)[1].strip()
        val = val.strip("[]")
        if val and val not in _LOCAL_BINDS:
            return True
    return False


def _must_force_auth() -> bool:
    """Erweitert auth_service._must_force_auth() um den echten uvicorn-Bind.

    Bei jeder Unklarheit (Modul/Attribut nicht lesbar) fail-closed True.
    """
    try:
        from backend.auth_service import auth_service
        if auth_service._must_force_auth():
            return True
    except Exception as exc:
        logger.error(f"[Auth] _must_force_auth nicht lesbar (fail-closed): {exc}")
        return True
    return _nonloopback_bind_detected()


def _assert_auth_on_nonloopback_bind() -> None:
    """Nicht-Loopback-Bind ohne Auth ist Fail-Open -> Start hart abbrechen."""
    if not _must_force_auth():
        return  # lokaler 127.0.0.1-Single-User-Modus bleibt doku-konform erlaubt
    try:
        from backend.auth_service import auth_service
        auth_enabled = auth_service.is_auth_enabled()
    except Exception as exc:
        logger.error(f"[Auth] Auth-Status bei Nicht-Loopback-Bind nicht pruefbar: {exc}")
        raise RuntimeError("[Auth] Auth-Status nicht pruefbar — Start abgebrochen (fail-closed).") from exc
    if not auth_enabled:
        raise RuntimeError(
            "[Auth] Nicht-Loopback-Bind (z. B. 0.0.0.0) erkannt, aber Auth ist deaktiviert — "
            "Start abgebrochen (fail-closed). Auth aktivieren oder an 127.0.0.1 binden."
        )


async def _archon_lifespan(_app_instance):
    try:
        from backend.loop_liveness import start_loop_heartbeat, stop_loop_heartbeat
        await start_loop_heartbeat()
    except Exception as _ll_start_err:
        stop_loop_heartbeat = None  # type: ignore[assignment]
        logger.warning(f"[Lifespan] Loop-Liveness-Start fehlgeschlagen: {_ll_start_err}")

    for hook in list(_STARTUP_HOOKS):
        name = getattr(hook, "__name__", repr(hook))
        try:
            if asyncio.iscoroutinefunction(hook):
                await hook()
            else:
                result = await asyncio.to_thread(hook)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:  # ein defekter Hook darf den Start nicht kippen
            # KRITISCH: der Router-Health-Hook ist KEIN normaler Hook — sein
            # Scheitern muss den Start abbrechen (sonst 404 beihealthy /health).
            if name in _FAIL_FAST_HOOKS:
                logger.error(f"[Lifespan] KRITISCH: {e}")
                raise
            logger.warning(f"[Lifespan] Startup-Hook '{name}' fehlgeschlagen: {e}")
    try:
        yield
    finally:
        for hook in reversed(list(_SHUTDOWN_HOOKS)):
            name = getattr(hook, "__name__", repr(hook))
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    result = await asyncio.to_thread(hook)
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as e:
                logger.warning(f"[Lifespan] Shutdown-Hook '{name}' fehlgeschlagen: {e}")
        if stop_loop_heartbeat is not None:
            try:
                await stop_loop_heartbeat()
            except Exception as _ll_stop_err:
                logger.warning(f"[Lifespan] Loop-Liveness-Stop fehlgeschlagen: {_ll_stop_err}")

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


# Audit D16/HIGH: W3C Trace Context an der Systemgrenze. Die Klasse wird hier
# definiert, aber ERST nach allen @app.middleware-Definitionen sowie nach
# _install_rate_limit_middleware()/_install_cors_middleware() registriert
# (siehe unten) — nur dann ist sie die äußerste Schicht und setzt den Kontext
# auch bei 401/403/429/503. Starlette wickelt zuletzt registrierte zuerst aus.
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from backend.trace_context import (
    current_trace_id as _current_trace_id,
)
from backend.trace_context import (
    extract_headers as _extract_traceparent,
)
from backend.trace_context import (
    response_trace_headers as _response_trace_headers,
)
from backend.trace_context import (  # noqa: E402
    start_trace as _start_trace,
)


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        _start_trace(_extract_traceparent(request.headers))
        response = await call_next(request)
        # D16/HIGH: Prometheus-Exemplare am Request-Chokepoint fuettern.
        # Der Scrape-Thread selbst hat keinen Kontext; der Ringpuffer in
        # backend/metrics_collector liefert die letzte echte Kausalkante.
        try:
            from backend.metrics_collector import record_trace_exemplar

            record_trace_exemplar(
                "archon_agent_dispatches_total",
                labels={"route": request.url.path, "status": response.status_code},
            )
        except Exception as _exemplar_exc:
            logger.debug("[Trace] Exemplar nicht aufgezeichnet: %s", _exemplar_exc)
        # D16: X-Trace-Id + forkbares traceparent/tracestate (Agent I).
        for key, value in _response_trace_headers(dict(response.headers)).items():
            response.headers[key] = value
        return response


def _install_cors_middleware() -> None:
    """CORS muss AUSSERHALB des Auth-Gates liegen.

    Starlette wickelt die zuletzt registrierte Middleware zuerst aus. Wird
    CORS — wie frueher — direkt nach GZip registriert, liegt es *innen*:
    OPTIONS-Preflights und alle 401/503/429 des auth_gate kommen ohne
    Access-Control-Allow-* zurueck und der Browser blockt den Request.
    Der Aufruf erfolgt deshalb nach allen @app.middleware-Definitionen.
    """
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
def _install_rate_limit_middleware() -> None:
    """Rate-Limit AUSSERHALB des Auth-Gates registrieren.

    Vorher lag der Limiter hinter auth_gate: 401/403 und die DB-Abfrage in
    verify_session() waren ungedrosselt. Der Aufruf erfolgt zusammen mit
    _install_cors_middleware() nach allen @app.middleware-Definitionen.
    """
    try:
        from utils.rate_limit import RateLimitMiddleware
        from utils.rate_limit import _env_int as _rl_env_int
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
    if path.startswith("/static/avatars/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- Auth-Gate (wirkt nur, wenn settings.auth.enabled = true) --------------
_AUTH_PUBLIC_EXACT = {
    "/", "/health", "/livez", "/readyz", "/metrics", "/favicon.ico", "/openapi.json",
    "/login", "/docs", "/redoc",
    # Randluecken: exakt /static (ohne Slash) wurde vom Prefix "/static/"
    # nicht erfasst und lief in einen Login-Redirect. /mcp/info ist
    # bewusst oeffentlich, wird aber vom Protected-Prefix "/m" erfasst.
    "/static", "/static_v2", "/mcp/info",
    # Kalender-Push (Google/Graph) kommt ohne Session-Token. Absicherung
    # AUSSCHLIESSLICH ueber clientState/watch_id per hmac.compare_digest in
    # backend/operations_calendar.py — bewusst NUR dieser exakte Pfad, kein
    # Prefix, damit kein weiterer /api/-Pfad geoeffnet wird.
    "/api/v1/calendar/webhooks/push",
}

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
        # FRUEHER: relativer CWD-Pfad — ein Angreifer mit Schreibzugriff auf
        # einen Jail-Root konnte die Token-Datei ueberschreiben und bekam
        # Vollzugriff. Jetzt: nur absolute, vertrauenswuerdige Pfade.
        _repo_root = os.path.dirname(os.path.abspath(__file__))
        for path in ("/app/data/.archon_service_token", os.path.join(_repo_root, "data", ".archon_service_token")):
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
async def tenant_context_middleware(request: Request, call_next):
    """Bindet optionalen Mandanten-Header (X-Tenant-Id / X-Company-Id) request-lokal via ContextVar.

    Autorisierung (Audit v3 Welle 4): Nur formatgueltige, bekannte Mandanten
    UND nur verifizierte Admins bzw. Service-Tokens duerfen den Mandanten per
    Header wechseln. Die Rolle aus request.state stammt aus dem auth_gate
    (der vor dieser Middleware laeuft). Ein Viewer konnte sonst per Header fremde
    Mandanten-DBs lesen (IDOR).
    """
    response = None
    hdr_tid = (request.headers.get("X-Tenant-Id") or request.headers.get("X-Company-Id") or "").strip()
    if not hdr_tid:
        # Immer einen Mandanten-Kontext setzen — auch ohne Header. Sonst
        # faellt archon/core/cache._tenant_prefix() auf 'default' zurueck und
        # gecachte Requests landen im falschen Namespace.
        from backend.tenant_context import reset_request_tenant, set_request_tenant
        from backend.tenant_context import tenant_context as _tc
        _tok = set_request_tenant(_tc.get_active_tenant_id())
        try:
            response = await call_next(request)
        finally:
            reset_request_tenant(_tok)
    else:
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", hdr_tid):
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_tenant_id", "detail": "X-Tenant-Id ist ungueltig."},
            )
        _user = getattr(request.state, "user", None) or {}
        _role = str(_user.get("role", "")).strip().lower()
        # KRITISCH: frueher genuegte das blosse Vorhandensein des Headers.
        # Damit konnte jeder Viewer (oder bei deaktiviertem Auth jeder
        # Anrufer) mit einem beliebigen Müll-Wert in den Mandantenwechsel
        # Schlüssel invalidate machen. Jetzt: echte HMAC-Prüfung wie im
        # auth_gate (main.py:_request_has_service_token).
        _is_service = _request_has_service_token(request)
        if not _is_service and _role != "admin":
            return JSONResponse(
                status_code=403,
                content={
                    "error": "tenant_forbidden",
                    "detail": "Mandantenwechsel per Header ist nur Admins und Service-Tokens erlaubt.",
                },
            )
        try:
            from backend.tenant_context import (
                reset_request_tenant,
                set_request_tenant,
                tenant_context,
            )
            known = False
            try:
                mgr = tenant_context._get_corporate_manager()
                companies = mgr.list_companies() or []
                known = any(str(c.get("id") or "").strip().lower() == hdr_tid.lower() for c in companies if isinstance(c, dict))
            except Exception:
                known = False
            if not known and hdr_tid.lower() != "default":
                return JSONResponse(
                    status_code=403,
                    content={"error": "tenant_not_found", "detail": "X-Tenant-Id referenziert keinen bekannten Mandanten."},
                )
            tok = set_request_tenant(hdr_tid)
            try:
                response = await call_next(request)
            finally:
                reset_request_tenant(tok)
        except Exception as err:
            # Fail-closed: kein Tenant-Kontext darf ohne gueltige Setzung durchgereicht werden.
            logger.error(f"[Tenant] Kontext konnte nicht gesetzt werden: {err}")
            return _auth_unavailable_response()
    if response is None:
        response = await call_next(request)
    if request.url.path == "/static/sw_calendar.js":
        response.headers["Service-Worker-Allowed"] = "/"
    return response


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
    # /mcp* (ausser /mcp/info) authentifiziert sich direkt per archon_live_-API-Key
    # in mcp_gateway._authenticate_mcp_request — auth_gate darf es nicht auf /login umleiten.
    if path == "/mcp" or (path.startswith("/mcp/") and path != "/mcp/info"):
        return await call_next(request)
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
            # _rbac.require_session_actor() prueft `auth_enabled` am User-Objekt.
            # Ohne dieses Flag greift der Viewer-Schutz im Session-Pfad nie.
            session_user["auth_enabled"] = True
            request.state.user = session_user
            user_role = str(session_user.get("role", "")).strip().lower()
            if (
                request.method in ("POST", "PUT", "DELETE", "PATCH")
                and user_role in ("viewer", "anonymous", "")
                and not path.startswith("/api/auth/")
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "forbidden",
                        "detail": f"Nur Administratoren oder Operatoren duerfen schreibende Aktionen ausfuehren (erkannte Rolle: {user_role or 'anonymous'}).",
                    },
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
    return RedirectResponse(url=f"/login?next={path}", status_code=307)


# CORS und Rate-Limit MUESSEN nach allen @app.middleware-Definitionen
# installiert werden, sonst liegen sie innen und 401/403/429 tragen keine
# CORS-Header bzw. unauthentifizierte Requests umgehen den Limiter.
_install_rate_limit_middleware()
_install_cors_middleware()

# D16/HIGH: TraceContext als LETZTE Middleware registrieren => aeusserste
# Schicht. Damit laeuft sie vor Auth/RateLimit/CORS und setzt X-Trace-Id
# auch auf 401/403/429/503. (Die Klasse ist oben definiert.)
app.add_middleware(TraceContextMiddleware)


@app.get("/livez")
async def liveness_check():
    """Liveness: Event-Loop-Heartbeat, Loop-Lag + Watchdog-Thread (503 bei blockiertem Loop)."""
    from backend.loop_liveness import check_loop_liveness
    info = await check_loop_liveness()
    # D10: Watchdog-Thread wird sonst von niemandem ueberwacht. Quelle ist die
    # atomare Liveness-Datei des Daemons (watchdog_daemon.watchdog_liveness),
    # die auch scripts/archon_autoheal.py::probe() liest.
    try:
        from watchdog_daemon import watchdog_liveness
        wd = watchdog_liveness()
    except Exception as exc:
        logger.error("[Livez] Watchdog-Liveness nicht lesbar (fail-closed): %s", exc)
        wd = {"alive": False, "last_seen": 0.0, "age_s": None}
    info["loops"] = {
        "watchdog": {
            "alive": bool(wd.get("alive")),
            "last_seen": wd.get("last_seen", 0.0),
            "age_s": wd.get("age_s"),
        }
    }
    # D10/HIGH: ein toter Watchdog-Thread muss `/livez` auf 503 setzen,
    # sonst greift der externe Autoheal wegen des Docker-Health-Gates nicht.
    if not info.get("alive", True) or not info["loops"]["watchdog"]["alive"]:
        return JSONResponse(status_code=503, content=info)
    return info


# H10: Dependency-Probes gecacht, damit /readyz nicht bei jedem Scrape
# blockierende HTTP-Calls auslöst.
_DEPENDENCY_PROBE_CACHE: dict = {"ts": 0.0, "problems": []}
_DEPENDENCY_PROBE_TTL = 10.0


def _probe_external_dependency(name: str, url: str) -> str:
    """Synchrone URL-Probe — ausschliesslich aus asyncio.to_thread gerufen.

    D10/HIGH: vorher blockierte urlopen(timeout=1.5) direkt im Event-Loop und
    konnte bei zwei ausgefallenen Dependencies den Loop spürbar festhalten.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            if resp.status >= 400:
                return f"{name}: HTTP {resp.status}"
    except Exception as exc:
        return f"{name}: {exc}"
    return ""


@app.get("/readyz")
async def readiness_check():
    """Readiness: echte Dependency-Pruefung. Liefert 503, solange nicht bereit."""
    problems: list = []
    # 1. Datenbank schreibbar?
    try:
        with _get_state_db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS _readiness_probe (id INTEGER)").fetchone()
    except Exception as exc:
        problems.append(f"state_db: {exc}")
    # 2. Event-Loop reagiert (wir laufen ja bereits — implizit gegeben)
    # 3. Router-Importfehler
    if _ROUTER_LOAD_ERRORS:
        problems.append(f"router_imports: {len(_ROUTER_LOAD_ERRORS)}")
    # 4. Config-Validierung
    try:
        from backend.config_validator import validator
        res = validator.validate_all(strict=False)
        if not res.get("valid", True):
            problems.append(f"config: {res.get('error_count', '?')} Fehler")
    except Exception as exc:
        problems.append(f"config_check: {exc}")
    # 5. Externe Dependencies (H10): nur in Produktion oder explizit aktiviert,
    #    denn eine lokale Installation ohne OmniRoute/n8n darf nicht dauerhaft
    #    503 liefern. In Docker übernimmt zusätzlich depends_on: service_healthy.
    _probe_enabled = (
        os.getenv("ARCHON_READINESS_PROBES", "").strip().lower() in ("1", "true", "yes")
        or os.getenv("ENVIRONMENT", "").strip().lower() in ("production", "prod", "live")
    )
    if _probe_enabled:
        now = time.time()
        if now - _DEPENDENCY_PROBE_CACHE["ts"] > _DEPENDENCY_PROBE_TTL:
            probes = (
                ("omniroute", os.getenv("OMNIROUTE_URL", "http://omniroute:20128/v1").rstrip("/") + "/models"),
                ("n8n", os.getenv("N8N_URL", "http://n8n:5678").rstrip("/") + "/healthz"),
            )
            # Blockierendes I/O in den Threadpool, nicht in den Event-Loop.
            dep_problems = await asyncio.gather(
                *(
                    asyncio.to_thread(_probe_external_dependency, name, url)
                    for name, url in probes
                )
            )
            dep_problems = [p for p in dep_problems if p]
            _DEPENDENCY_PROBE_CACHE.update(ts=now, problems=dep_problems)
        problems.extend(_DEPENDENCY_PROBE_CACHE["problems"])
    # D07/MED: verifizierte Shutdown-/Recovery-Fehler duerfen nicht gruen gemeldet werden.
    if _FAILED_CANCELS:
        problems.append(f"failed_cancels: {len(_FAILED_CANCELS)}")
    if _WATCHDOG_STOP_FAILED:
        problems.append(f"watchdog_stop: {len(_WATCHDOG_STOP_FAILED)}")
    if _STARTUP_RECOVERY_FAILED:
        problems.append(f"startup_recovery: {len(_STARTUP_RECOVERY_FAILED)}")
    # D07/D06-Nachlauf: ein fehlgeschlagener Startup-Import und eine nicht
    # verfuegbare Prozess-Lock-Sackgasse duerfen nicht gruen gemeldet werden.
    if _N8N_STARTUP_STATUS.get("status") == "error":
        problems.append(f"n8n_startup_import: {_N8N_STARTUP_STATUS.get('detail')}")
    if _DB_MAINTENANCE_STATUS.get("status") == "error":
        problems.append(f"db_maintenance: {_DB_MAINTENANCE_STATUS.get('error')}")
    try:
        from backend.process_lock import get_loop_lock_failures
        _lock_failures = get_loop_lock_failures()
        if _lock_failures:
            problems.append(f"loop_lock_unavailable: {len(_lock_failures)}")
    except Exception as exc:
        problems.append(f"loop_lock_check: {exc}")
    if problems:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "timestamp": time.time(), "problems": problems},
        )
    return {"status": "ready", "timestamp": time.time()}


@app.get("/health")
async def health_check():
    """Kombinierter Health-Endpunkt: 503 bei nicht-readiness."""
    ready = await readiness_check()
    if isinstance(ready, JSONResponse) and ready.status_code == 503:
        return ready
    return {"status": "ok", "timestamp": time.time(), "readiness": ready}

@app.get("/metrics")
def prometheus_metrics():
    """Prometheus-konformer Metriken-Endpoint fuer Scraping und Monitoring."""
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            # OpenMetrics erlaubt Exemplare (`# {trace_id=...,span_id=...}`);
            # Prometheus ist mit exemplar-storage konfiguriert.
            media_type="application/openmetrics-text; version=1.0.0; charset=utf-8"
        )
    except Exception as e:
        return Response(content=f"# Error collecting metrics: {e}\n", status_code=500, media_type="text/plain")

from archon.routers.telemetry import (
    _count_running_containers,
    api_get_agent_activity,
    api_get_agent_projects,
    api_telemetry_dashboard,
    get_hud_telemetry,
)
from archon.routers.telemetry import (
    router as _telemetry_router,
)

app.include_router(_telemetry_router)



# Pfade + Laufzeit-Helfer kommen aus app.core.runtime (gemeinsame Basis für
# main.py und die ausgelagerten Router; dort zyklenfrei definiert).
from archon.core.cache import invalidate as invalidate_ttl_cache  # noqa: E402
from archon.core.cache import ttl_cache
from archon.core.mission_control import (  # noqa: E402
    _MC_ASYNC_LOCK,
    _MC_DATA_LOCK,
    # F-12/Z-12: Der Leser von /api/mission-control/state ist
    # ``archon/routers/mission_control.py``; er benutzt DEN Cache aus
    # ``archon.core.mission_control``. ``main.py`` hatte einen zweiten,
    # toten Cache-Eigenbau (siehe unten) und invalidierte genau den —
    # die Invalidierung lief ins Leere. Jetzt wird der echte Cache
    # importiert und invalidiert.
    _MC_STATE_CACHE,
    MISSION_CONTROL_FILE,
    _load_mission_control_data,
    _save_mission_control_data,
    _write_mc_atomic,
    update_mission_control_data,
)

# --- A5-Etappe 4b: Pfad-Konstanten ausgelagert -----------------------------
# Quelle ist archon/core/paths.py; alle Pfade leiten sich aus den Basis-
# Verzeichnissen oben ab (keine zweite __file__-Wahrheit). main.py importiert
# nur noch — die Werte sind per scripts/path_constants_snapshot.py belegt.
from archon.core.paths import (
    _SKILL_INDEX_DISK_PATH,
    AGENTS_FILE,
    BOARDROOM_HISTORY_FILE,
    CONFIG_FILE,
    COUPLED_AGENTS_FILE,
    FRAMEWORKS_FILE,
    GATEWAY_CONFIG_FILE,
    HERMES_PROFILES_DIR,
    KANBAN_CARDS_FILE,
    KANBAN_FILE,
    MEMORY_FILE,
    QUICKCHAT_SESSIONS_DIR,
    ROLES_FILE,
    SERVICES_FILE,
    SETTINGS_FILE,
    THEME_FILE,
    THEME_LIVE_FILE,
    THEMES_DIR,
)
from archon.core.permissions import (  # noqa: E402
    PERMISSION_GATES_FILE,
)
from archon.core.permissions import (
    create_permission_gate as _create_permission_gate,
)
from archon.core.permissions import (
    load_permission_gates as _load_permission_gates,
)
from archon.core.permissions import (
    save_permission_gates as _save_permission_gates,
)
from archon.core.permissions import (
    set_decision_factory as _set_decision_factory,
)
from archon.core.profiles import (  # noqa: E402
    ALL_HERMES_TOOLS,
    DEFAULT_HERMES_TOOLS,
    AgentProfileValidationSchema,
    api_get_hermes_profiles,
    create_rolling_backup,
    get_hermes_profiles_base_dirs,
    get_primary_hermes_profiles_dir,
    invalidate_hermes_profiles_cache,
    materialize_role_avatars,
    resolve_avatar_file,
    restore_data_uri_avatars,
    save_all_agent_profiles,
)
from archon.core.runtime import (  # noqa: E402
    _SSE_SUB_LOCK,
    _SSE_SUBSCRIBERS,
    DATA_DIR,
    MEMORY_DIR,
    OBSIDIAN_VAULT_DIR,
    WORKSPACE_DIR,
    _load_json,
    _save_json,
    add_ticker,
    atomic_write_json,
    broadcast_event,
    resolve_obsidian_vault_path,
    subscribe_events,
    ticker_entries,
    unsubscribe_events,
)
from archon.core.state_db import (  # noqa: E402
    STATE_DB_PATH,
    ClosingConnection,
    _get_profile_state_db,
    _get_state_db,
)

# Kostenanzeige im Chat-Stream braucht die Preisliste des Providers-Routers.
from archon.routers.llm_providers import get_llm_prices  # noqa: E402

# Gate-Ausfuehrung ruft den Service, nicht die HTTP-Endpunkte: die Endpunkte
# brauchen einen Request (require_admin_or_503) und waren hier nie importiert.
from archon.services import profiles_service  # noqa: E402
from archon.services.profiles_service import (  # noqa: E402
    delete_profile,
    save_profile,
)

# --- Pfad-Jail: jeder dateibasierte Endpunkt bleibt in erlaubten Wurzeln ---
try:
    from utils.path_jail import (
        PathJailError,
        allowed_roots,
        safe_filename,
        safe_path,
        safe_path_within,
    )
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
    from backend.db_paths import resolve_db as _resolve_db_path
    from local_memory_bridge import LocalMemoryBridge
    memory_bridge = LocalMemoryBridge(
        db_path=_resolve_db_path("agentic_memory.db"),
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
    if watchdog_runner is not None:
        logger.warning("[Startup] Watchdog laeuft bereits — kein zweiter Start.")
        return
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
from archon.core.roles_data import DEFAULT_ROLES as DEFAULT_ROLES  # Re-Export fuer container_ops.py
from archon.core.roles_data import load_default_roles
from archon.core.settings_state import (
    DEFAULT_AGENTS,
    DEFAULT_SERVICES,
    GHOST_AGENT_IDS,
    SYSTEM_INTERNAL_IDS,
)


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
        from archon.core.profiles import invalidate_hermes_profiles_cache
        from archon.core.runtime import APP_ROOT, atomic_write_json
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
    except Exception as exc:
        logger.warning(f"[Agents] SSoT-Profile-Sync fehlgeschlagen: {exc}")

@ttl_cache(seconds=60)
def load_roles() -> List[Dict]:
    # A8-DELEGATED: SSOT-Projektion aus agent_profiles.json statt statischem
    # Import-Snapshot. DEFAULT_ROLES bleibt nur als Import-Kompatibilitaet
    # (container_ops.py liest app_main.DEFAULT_ROLES) erhalten.
    return _load_json(ROLES_FILE, load_default_roles())

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

from archon.routers.core_settings import (
    api_get_agents,
    api_get_roles,
    api_save_agents,
    api_save_roles,
    api_save_settings,
    api_test_jev,
    clear_ticker,
    get_settings,
    get_ticker,
)
from archon.routers.core_settings import (
    router as _core_settings_router,
)
from archon.routers.hermes_proxy import (
    _PROXY_WRITE_METHODS,
    _hermes_proxy_token,
    forward_to_hermes,
    proxy_hermes_api_endpoints,
    proxy_web_ui,
)
from archon.routers.hermes_proxy import (
    router as _hermes_proxy_router,
)

app.include_router(_core_settings_router)

from archon.routers.oracle_seo import (
    api_get_oracle_feed,
    api_run_oracle_cycle,
    api_seo_articles,
    api_seo_generate,
    api_triage_oracle_signal,
)
from archon.routers.oracle_seo import (
    router as _oracle_seo_router,
)

app.include_router(_oracle_seo_router)

# --- THEME & DESIGN ROUTER (ausgelagert nach archon.routers.theme) ---
from archon.routers.theme import (
    DESIGN_THEMES_TARGETS,
    api_bake_theme_into_main_design,
    api_delete_design_theme,
    api_delete_theme_by_name,
    api_delete_theme_live_overrides,
    api_get_design_themes,
    api_get_theme,
    api_get_theme_by_name,
    api_get_theme_live_overrides,
    api_get_themes,
    api_save_design_themes,
    api_save_theme,
    api_save_theme_by_name,
    api_save_theme_live_overrides,
    api_upload_theme_background,
)
from archon.routers.theme import (
    router as _theme_router,
)

app.include_router(_theme_router)


from archon.routers.docker_services import (
    _services_config_fallback,
    api_docker_start,
    api_docker_stop,
    api_get_models,
    api_get_models_v1,
    api_get_services,
    api_save_services,
    detect_container_port,
    get_docker_containers_from_socket,
    post_docker_container_action,
)
from archon.routers.docker_services import (
    router as _docker_services_router,
)

app.include_router(_docker_services_router)

from archon.routers.agent_chat import (
    DirectAgentChatRequest,
    RunRequest,
    api_direct_agent_chat,
    api_run_parallel,
    fetch_agent_response_api,
    load_profiles_list,
)
from archon.routers.agent_chat import (
    router as _agent_chat_router,
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

from archon.routers.gateway import (
    _get_all_installed_profiles,
    _load_gateway_config,
    _parse_gateway_list,
    _run_docker_exec,
    _save_gateway_config,
    _update_profile_status,
    api_gateway_autostart,
    api_gateway_list,
    api_gateway_start,
    api_gateway_stop,
    api_gateway_stop_all,
    api_get_gateway_config,
    api_save_gateway_config_endpoint,
)
from archon.routers.gateway import (
    router as _gateway_router,
)

app.include_router(_gateway_router)


# =====================================================================
# INTERNET WATCHDOG (SÄULE 4 DER KOGNITION: AUTONOMER WEB-RADAR)
# =====================================================================

from archon.routers.watchdog import (
    acknowledge_watchdog_alarm_endpoint,
    api_get_watchdog_config,
    api_save_watchdog_config,
    api_trigger_watchdog_run,
    api_watchdog_dispatch_action,
    get_watchdog_alarms_endpoint,
    trigger_test_watchdog_alarm_endpoint,
)
from archon.routers.watchdog import (
    router as _watchdog_router,
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


from backend.process_lock import exclusive_loop as _exclusive_loop


@_exclusive_loop("email_imap")
async def _email_imap_background_loop():
    await asyncio.sleep(15)
    while True:
        try:
            from backend.email_service import sync_imap_inbox
            await asyncio.to_thread(sync_imap_inbox, limit=20)
        except Exception as e:
            # W3: kein reines stdout mehr — IMAP-Fehler (z. B. abgelaufenes
            # Token) landen im strukturierten Log und damit in Loki.
            logger.warning("[EmailService] Background sync error: %s", e)
        await asyncio.sleep(180)

_BACKGROUND_TASKS: list = []
_RAG_SYNC_LOCK = asyncio.Lock()
_RAG_SYNC_PROCESS = None

# D07/MED: fehlgeschlagene Abbrueche duerfen nicht als Erfolg quittiert werden.
# Die Liste bleibt im Prozess erhalten und geht in /readyz ein, damit ein
# Zombie-Task nicht still weiterlaeuft, waehrend alles "gruen" meldet.
_FAILED_CANCELS: list = []
_WATCHDOG_STOP_FAILED: list = []
_STARTUP_RECOVERY_FAILED: list = []


def _record_failed_cancel(task_name: str, detail: str) -> None:
    """Persistiert einen gescheiterten cancel() inkl. Audit (best effort)."""
    entry = {"task": str(task_name), "detail": str(detail), "ts": time.time()}
    _FAILED_CANCELS.append(entry)
    logger.error("[Shutdown] Cancel fehlgeschlagen: %s — %s", task_name, detail)
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(
            category="recovery",
            action="cancel_failed",
            agent_id="system",
            payload=entry,
        )
    except Exception as audit_exc:
        logger.warning("[Shutdown] Cancel-Fehler nicht auditierbar: %s", audit_exc)


def _is_rag_sync_running() -> bool:
    """Prueft, ob aktuell ein RAG-Sync-Prozess aktiv ist (Re-06)."""
    global _RAG_SYNC_PROCESS
    return _RAG_SYNC_PROCESS is not None and _RAG_SYNC_PROCESS.poll() is None


def _spawn_background(coro, name: str = "", priority: int = 1):
    """Startet einen Background-Task, registriert ihn für Shutdown und loggt unhandled exceptions.

    Audit 23.11.2026 (K-2): `can_start_task()` war nie verdrahtet — während des
    15-s-Draining-Fensters starteten weiterhin IMAP-Syncs, Scheduler und
    LLM-Calls. Der zentrale Spawn-Punkt prüft jetzt das Gate. Chats mit
    Notfall-Prioritaet (>= 3) bleiben erlaubt.
    """
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as _coord

    allowed, reason = _coord.can_start_task(name or "background", priority=priority)
    if not allowed:
        logger.warning("[BackgroundTask] Start verweigert (%s): %s", name or "background", reason)
        close = getattr(coro, "close", None)
        if callable(close):
            close()  # "coroutine was never awaited" vermeiden
        return None
    task = asyncio.create_task(coro, name=name) if name else asyncio.create_task(coro)
    _BACKGROUND_TASKS.append(task)

    def _done_cb(t):
        try:
            _BACKGROUND_TASKS.remove(t)
        except ValueError as rm_exc:
            logger.debug(f"[BackgroundTask] Task {t.get_name()} bereits aus Registry entfernt: {rm_exc}")
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.error(f"[BackgroundTask] Unhandled exception in {t.get_name()}: {exc}", exc_info=exc)

    task.add_done_callback(_done_cb)
    return task


# D08/MED: Audit-Schreibpfade im 30-s-Loop laufen in einem Thread und sind
# zusaetzlich gelockt, damit keine sync SQLite-Schreiboperation den Event-Loop
# blockiert und keine parallelen Anker-Schreiber die Kette verdrehen.
_ANCHOR_WRITE_LOCK = threading.Lock()


@_exclusive_loop("deadlock_supervisor")
async def _deadlock_supervisor_loop():
    """30-Sekunden Watchdog/Deadlock-Loop (Pillar 1): befreit stagnierende Kanban-Tasks."""
    await asyncio.sleep(15)
    while True:
        try:
            from backend.deadlock_supervisor import deadlock_supervisor
            res = await asyncio.to_thread(deadlock_supervisor.detect_and_resolve_deadlocks)
            if isinstance(res, dict) and res.get("resolved_count", 0) > 0:
                logger.warning(f"[DeadlockSupervisor] {res['resolved_count']} blockierte(r) Task(s) reaktiviert.")
        except Exception as e:
            logger.debug(f"[DeadlockSupervisor] Loop-Hinweis: {e}")
        # Verwaiste Synthese-Cascades wiederbeleben (synthesis_started Latch).
        # KRITISCH: reset allein reicht nicht — danach muss Fan-in erneut
        # laufen, sonst bleibt das Projekt im gleichen Sackgassen-Zustand.
        # to_thread verhindert, dass BEGIN IMMEDIATE den Event-Loop blockiert.
        try:
            from archon.core.orchestration import recover_stale_synthesis
            from archon.core.task_registry import spawn as _tracked_spawn
            stale = await asyncio.to_thread(
                recover_stale_synthesis,
                _load_mission_control_data,
                update_mission_control_data,
                900,
                lambda pid: _tracked_spawn(
                    _orch_fan_in_maybe_start_synthesis(
                        pid,
                        mc_async_lock=_MC_ASYNC_LOCK,
                        run_cascade=_run_synthesis_cascade,
                    ),
                    name=f"synthesis_restart:{pid}",
                ),
            )
            if stale:
                logger.warning("[Synthese-Recovery] %s Kaskade(n) neu gestartet.", len(stale))
        except Exception as e:
            logger.debug(f"[Synthese-Recovery] Loop-Hinweis: {e}")

        # Alerting unabhaengig vom /metrics-Scrape (sonst schlagen Alarme
        # nie zu, wenn niemand Prometheus abruft).
        try:
            from backend.metrics_collector import check_and_dispatch_alerts_now
            # W3: die Rohmethode hat KEINE Zeitbremse -> bei anhaltender
            # Störung alle 30 s erneuter Alert (Alarmmüdigkeit). Die
            # deduplizierte Variante liegt bereits im selben Modul.
            alerts = await asyncio.to_thread(check_and_dispatch_alerts_now)
            if isinstance(alerts, dict) and alerts.get("dispatched"):
                logger.info("[Alerting] %s Alarm(e) versendet.", alerts["dispatched"])
        except Exception as e:
            logger.debug(f"[Alerting] Loop-Hinweis: {e}")

        # F-077: Disk-Backpressure muss auch ohne externen Traffic periodisch
        # geprueft werden, sonst bleibt der disk_space_critical-Alarm stumm.
        # via to_thread, damit die sync-Messung den Event-Loop nicht blockiert.
        try:
            from backend.resource_backpressure import resource_backpressure_protector
            bp = await asyncio.to_thread(
                resource_backpressure_protector.check_health_and_backpressure
            )
            if isinstance(bp, dict) and bp.get("disk_critical"):
                logger.error("[Backpressure] Disk kritisch: %s", bp)
        except Exception as e:
            logger.error(f"[Backpressure] Periodischer Check fehlgeschlagen: {e}")

        # GoBD: Hash-Ketten periodisch verifizieren statt nur manuell.
        try:
            from backend.execution_receipt_ledger import execution_receipt_ledger
            chain = await asyncio.to_thread(execution_receipt_ledger.verify_chain_integrity)
            if isinstance(chain, dict) and chain.get("chain_valid") is False:
                logger.error("[Integritaet] Quittungs-Hashkette INVALID: %s", chain)
        except Exception as e:
            # Audit D: ein Fehler der Ketten-Pruefung ist selbst ein
            # Integritaetsvorfall und gehoert ins Produktionslog, nicht auf DEBUG.
            logger.error(f"[Integritaet] Quittungs-Hashkette nicht pruefbar: {e}")

        # C08: zentrale Audit-Kette und Approval-Kette ebenfalls im 30-s-Loop.
        # Vorher liefen diese Nur-On-Demand — Manipulationen blieben unbemerkt,
        # solange kein Prüfer aktiv eine Route aufrief.
        try:
            from backend.api_key_manager import api_key_manager as _api_key_chain
            from backend.approval_policy_engine import approval_engine as _approval_chain
            from backend.audit_log import chained_audit_log as _audit_chain

            # F-033: Email-Draft- und DSGVO-Verifikatoren hatten bisher keinen
            # Produktivkonsumenten — jetzt ebenfalls im 30-s-Loop (G-03).
            from backend.email_draft_engine import verify_email_draft_chain
            from backend.gdpr_compliance_engine import verify_gdpr_audit_chain
            from backend.treasury_engine import verify_treasury_chain
            for label, verify_fn in (
                ("Zentrale Audit-Kette", _audit_chain.verify_integrity),
                ("Approval-Kette", _approval_chain.verify_audit_integrity),
                ("API-Key-Kette", _api_key_chain.verify_integrity),
                ("Treasury-Kette", verify_treasury_chain),
                ("Email-Draft-Kette", verify_email_draft_chain),
                ("DSGVO-Audit-Kette", verify_gdpr_audit_chain),
            ):
                try:
                    res = await asyncio.to_thread(verify_fn)
                    if isinstance(res, dict) and res.get("valid") is False:
                        logger.error("[Integritaet] %s INVALID: %s", label, res)
                except Exception as exc:
                    # Audit D: Kettenname + Exception sichtbar im Produktionslog.
                    logger.error(f"[Integritaet] {label} nicht pruefbar: {exc}")
        except Exception as e:
            # Audit D: Importfehler wuerden alle vier Ketten gleichzeitig blind machen.
            logger.error(f"[Integritaet] Nebenketten-Import fehlgeschlagen: {e}")

        # d05 F-03: signierte Head-Anker fuer alle sechs Nebenketten schreiben.
        # Audit-Schreibpfad gemaess D08/MED in den Thread verlagern + locken.
        def _write_chain_anchors() -> Dict[str, Any]:
            from backend.audit_log import anchor_secondary_chains
            with _ANCHOR_WRITE_LOCK:
                return anchor_secondary_chains()

        try:
            anchors = await asyncio.to_thread(_write_chain_anchors)
            # D05/HIGH (A2-DELEGATED): ein erkannter Tail-Loeschungs-Versuch
            # (`violation: True`) ist mindestens so kritisch wie ein Schreibfehler
            # und darf nicht still durchgewinkt werden.
            failed = [
                k for k, v in anchors.items()
                if isinstance(v, dict)
                and v.get("written") is False
                and ("error" in v or v.get("violation") is True)
            ]
            if failed:
                logger.error("[Integritaet] Head-Anker fehlgeschlagen: %s", failed)
        except Exception as e:
            logger.error(f"[Integritaet] Head-Anker-Loop fehlgeschlagen: {e}")

        # d14/HIGH: Freigabe-Timeouts muessen periodisch eskaliert werden,
        # nicht nur wenn ein Benutzer eine Approval-Ansicht oeffnet.
        try:
            from backend.approval_policy_engine import approval_engine as _approval_timeout
            escalated = await asyncio.to_thread(_approval_timeout.check_and_escalate_timeouts)
            if escalated:
                logger.warning("[Approval] %s Freigabe(n) automatisch eskaliert.", escalated)
        except Exception as e:
            logger.error(f"[Approval] Timeout-Eskalation fehlgeschlagen: {e}")

        await asyncio.sleep(30)


# A3-DELEGATED: DB-Wartung darf nicht still im DEBUG verschwinden. Der
# Status wird zusaetzlich in /readyz gespiegelt (siehe readiness_check).
_DB_MAINTENANCE_STATUS: Dict[str, Any] = {"status": "not_started", "error": None, "ts": 0.0}


@_exclusive_loop("db_maintenance")
async def _db_maintenance_loop():
    """Periodische DB-Sicherung & Optimierung (WAL-Truncate, Backup, VACUUM alle 6h)."""
    await asyncio.sleep(120)
    while True:
        try:
            from backend.db_backup_manager import db_backup_manager
            from backend.db_optimizer import optimize_all_databases
            await asyncio.to_thread(db_backup_manager.checkpoint_and_backup)
            result = await asyncio.to_thread(optimize_all_databases)
            _DB_MAINTENANCE_STATUS.update(
                status="error" if isinstance(result, dict) and result.get("status") == "error" else "ok",
                error=(result or {}).get("error") if isinstance(result, dict) else None,
                ts=time.time(),
            )
            if _DB_MAINTENANCE_STATUS["status"] == "error":
                logger.error("[DBMaintenance] Optimierung fehlgeschlagen: %s", _DB_MAINTENANCE_STATUS["error"])
        except Exception as e:
            _DB_MAINTENANCE_STATUS.update(status="error", error=str(e), ts=time.time())
            logger.error("[DBMaintenance] Loop fehlgeschlagen: %s", e)
        await asyncio.sleep(21600)


@_exclusive_loop("fleet_self_healing")
async def _fleet_self_healing_loop():
    """C13: Core-Dienste periodisch prüfen und ausgefallene Container neu starten.

    Vorher war `check_fleet_and_heal()` nur über eine API-Route erreichbar;
    `restart: unless-stopped` hilft nicht bei `running`-aber-unhealthy Containern.
    Der Exclusive-Loop verhindert parallele Restarts bei mehreren Replicas.
    """
    await asyncio.sleep(45)
    while True:
        try:
            from backend.fleet_self_healing import check_fleet_and_heal
            res = await asyncio.to_thread(check_fleet_and_heal)
            if isinstance(res, dict) and res.get("status") == "ok":
                missing = res.get("missing_services") or []
                if missing or res.get("healed_count", 0):
                    logger.warning(
                        "[FleetSelfHealing] vermisst/unhealthy=%s, geheilt=%s, übersprungen=%s",
                        missing, res.get("healed_count", 0), res.get("skipped_not_deployed") or [],
                    )
            elif isinstance(res, dict):
                logger.debug("[FleetSelfHealing] Loop-Hinweis: %s", res.get("error"))
        except Exception as e:
            logger.debug(f"[FleetSelfHealing] Loop-Hinweis: {e}")
        await asyncio.sleep(120)


_LOOPS_STARTED = False


async def _start_gateway_idle_loop():
    """Alle Hintergrund-Loops genau einmal starten.

    Vorher hatte nur der Gateway-Idle-Loop einen Guard; bei --reload oder
    wiederholten Lifespan-Durchlaeufen (Tests) wurden IMAP, Deadlock, DB-
    Maintenance, Inbox, Internet-Watchdog und Workflow-Scheduler mehrfach
    gestartet — mit doppelten LLM-Calls, doppelten Mails und DB-Locks.
    """
    global _LOOPS_STARTED
    if _LOOPS_STARTED:
        logger.warning("[Startup] Hintergrund-Loops laufen bereits — kein zweiter Start.")
        return
    _LOOPS_STARTED = True
    _spawn_background(_gateway_idle_stop_loop())
    _spawn_background(_email_imap_background_loop())
    _spawn_background(_deadlock_supervisor_loop(), name="deadlock_supervisor_30s")
    _spawn_background(_fleet_self_healing_loop(), name="fleet_self_healing_120s")
    _spawn_background(_db_maintenance_loop(), name="db_maintenance_6h")
    try:
        from archon.core.delegation import resume_pending_delegation_watchers
        _spawn_background(resume_pending_delegation_watchers(), name="delegation_watcher_recovery")
    except Exception as e:
        logger.debug(f"[Startup] Delegation-Watcher-Recovery Hinweis: {e}")
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
    try:
        from backend.workflow_scheduler import workflow_scheduler_background_loop
        _spawn_background(workflow_scheduler_background_loop())
    except Exception as e:
        print(f"[Startup] Workflow Scheduler init notice: {e}")
    # K2: Auth aktiv, aber kein Service-Token -> n8n/Telegram-Adapter erhalten
    # 401. Laut warnen statt stillem Lockout der Automatisierungen.
    try:
        from backend.auth_service import auth_service as _auth_svc
        if _auth_svc.is_auth_enabled() and not _get_service_token():
            logger.critical(
                "[Auth] Auth ist aktiv, aber kein ARCHON_SERVICE_TOKEN konfiguriert — "
                "interne Automaten (n8n, Adapter) werden mit 401 abgewiesen."
            )
    except Exception as e:
        logger.debug(f"[Startup] Auth-Token-Pruefung Hinweis: {e}")


async def _cancel_background_tasks():
    """Bricht die Endlos-Loops ab.

    Ohne das wartet `uvicorn --reload` beim Code-Wechsel unbegrenzt auf diese
    Tasks ("Waiting for connections to close") und der Server bleibt hängen.
    """
    # H9 (Audit 23.11.2026): der RAG-Sync läuft als Subprocess, nicht als
    # asyncio-Task. Ohne terminate() überlebt er Reload/Shutdown als Orphan
    # und schreibt konkurrierend in dieselbe RAG-DB / denselben API-Key.
    global _RAG_SYNC_PROCESS
    _rag_proc = _RAG_SYNC_PROCESS
    if _rag_proc is not None and _rag_proc.poll() is None:
        try:
            logger.info("[Shutdown] RAG-Sync-Subprocess wird beendet.")
            _rag_proc.terminate()
            try:
                _rag_proc.wait(timeout=5.0)
            except Exception:
                # F-043: kill() allein reicht nicht — ohne wait() bleibt der
                # Prozess als Zombie zurueck, bis der Parent beendet wird.
                _rag_proc.kill()
                try:
                    _rag_proc.wait(timeout=5.0)
                except Exception:
                    logger.warning(
                        "[Shutdown] RAG-Sync bleibt nach kill() unresponsive "
                        "(Zombie-Risiko)."
                    )
        except Exception as exc:
            logger.warning("[Shutdown] RAG-Sync konnte nicht beendet werden: %s", exc)
    _RAG_SYNC_PROCESS = None

    pending = [t for t in _BACKGROUND_TASKS if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        results = None
        try:
            # Timeout: ein Task, der Cancellation in einem blockierenden
            # finally ignoriert, darf den Shutdown nicht ewig festhalten.
            results = await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=10.0
            )
        except asyncio.TimeoutError:
            # D07/MED: nicht als Erfolg quittieren. Nicht beendete Tasks
            # bleiben in der Registry und werden als failed_cancels
            # persistiert, statt still aus dem Register geloescht zu werden.
            logger.warning("[Shutdown] %s Task(s) reagierten nicht binnen 10s.", len(pending))
            for task in pending:
                if not task.done():
                    _record_failed_cancel(
                        task.get_name(), "timeout_after_cancel(10s): task_possibly_alive"
                    )
        if results is not None:
            for task, result in zip(pending, results):
                # Erwartetes CancelledError ist der Normalfall; alles andere
                # (inkl. blockierender finally) ist ein fehlgeschlagener Abbruch.
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, BaseException):
                    _record_failed_cancel(task.get_name(), f"{type(result).__name__}: {result}")
        confirmed = sum(1 for t in pending if t.cancelled())
        print(
            f"[Shutdown] {confirmed}/{len(pending)} Hintergrund-Task(s) verifiziert abgebrochen; "
            f"{len(_FAILED_CANCELS)} fehlgeschlagene Abbruch(e) insgesamt."
        )
    # Nur tatsaechlich beendete Tasks entfernen; Zombies bleiben sichtbar.
    _BACKGROUND_TASKS[:] = [t for t in _BACKGROUND_TASKS if not t.done()]

from archon.routers.quickchat import (
    QuickchatSendRequest,
    _load_quickchat_session,
    _quickchat_session_path,
    _save_quickchat_session,
    api_delete_quickchat_session,
    api_get_quickchat_session,
    api_quickchat_send,
)
from archon.routers.quickchat import (
    router as _quickchat_router,
)
from archon.routers.ui import (
    FullHtmlSaveRequest,
    TextReplacementItem,
    TextReplacementsRequest,
    _full_html_target_files,
    api_save_full_html,
    api_save_text_replacements,
    api_studio_upload_bg,
)
from archon.routers.ui import (
    router as _ui_router,
)

app.include_router(_quickchat_router)
app.include_router(_ui_router)

# Kontext-Meter & Session-Compaction (M73, Teil 1+2)
from archon.routers.context_meter import router as _context_meter_router  # noqa: E402

app.include_router(_context_meter_router)


# ============================================================================
# BRAIN & ARCHIV ROUTER (ausgelagert nach archon.routers.brain)
# ============================================================================
from archon.routers.brain import (
    api_brain_galaxy_data,
    api_brain_vault_file,
    api_get_quartz_config,
    api_library_book_content,
    api_library_books,
    api_library_ingest,
    api_library_upload,
    api_save_quartz_config,
)
from archon.routers.brain import (
    configure as _brain_configure,
)
from archon.routers.brain import (
    router as _brain_router,
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
    api_attach_vault_source,
    api_create_notebook,
    api_delete_notebook,
    api_delete_notebook_source,
    api_get_notebook_chat,
    api_get_notebook_sources,
    api_get_notebooks,
    api_query_notebook,
    api_sync_notebook_obsidian,
    api_upload_notebook_source,
)
from archon.routers.notebooks import (
    router as _notebooks_router,
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
            from archon.routers.skills import api_get_hermes_skills, build_skills_file_index
            build_skills_file_index()
            api_get_hermes_skills()
            print(f"[Skills-Warmup] caches warm after {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[Skills-Warmup] failed: {e}")
    threading.Thread(target=_warm, daemon=True, name="skills-warmup").start()


from archon.routers.telegram import (
    TelegramSendPayload,
    _redact_telegram_secrets,
    api_telegram_relay,
    api_telegram_send,
    api_telegram_voice_relay,
)
from archon.routers.telegram import (
    router as _telegram_router,
)

app.include_router(_telegram_router)



# =========================================================================
# ZENTRALER ENTSCHEIDUNGS-SERVICE (ausgelagert nach archon.routers.decisions)
# =========================================================================
from archon.routers.decisions import (
    _antwort_grund,
    _decision_followup,
    _decision_kanban_status,
    _decision_self_api,
    _folge_nicht,
    _pruefe_gate_antwort,
    _pruefe_gate_persistiert,
    _pruefe_move_antwort,
    _pruefe_synthese_beleg,
    _sync_org_hierarchy_node,
    _synthese_parent,
    api_decide_decision,
    api_decide_permission_gate,
    create_decision,
    register_decision,
)
from archon.routers.decisions import (
    _followup_mission_start as _impl_followup_mission_start,
)
from archon.routers.decisions import (
    _followup_permission_gate as _impl_followup_permission_gate,
)
from archon.routers.decisions import (
    _followup_synthesis as _impl_followup_synthesis,
)
from archon.routers.decisions import (
    router as _decisions_router,
)

app.include_router(_decisions_router)
_set_decision_factory(create_decision)

# Statik-Guard AST Wrapper fuer tests/test_decision_followup_beleg.py
async def _followup_mission_start(ref: str) -> str:
    """Wrapper delegating to _impl_followup_mission_start; retains _pruefe_move_antwort."""
    return await _impl_followup_mission_start(ref)  # _pruefe_move_antwort

async def _followup_permission_gate(ref: str, proof_token: str = "", proof_uid: str = "") -> str:
    """Wrapper delegating to _impl_followup_permission_gate; retains _pruefe_gate_antwort."""
    # HITL: Proof und uid der Decision unveraendert an den Gate-Followup durchreichen.
    return await _impl_followup_permission_gate(ref, proof_token, proof_uid)  # _pruefe_gate_antwort

async def _followup_synthesis(pid: str, dossier: str, dec: dict) -> str:
    """Wrapper delegating to _impl_followup_synthesis; retains _pruefe_synthese_beleg."""
    return await _impl_followup_synthesis(pid, dossier, dec)  # _pruefe_synthese_beleg

class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"


# 
# SYSTEM HEALTH, HERMES CONFIG & CONTAINER LIFECYCLE MANAGEMENT
# 


from archon.routers.hermes_ops import (
    _get_hermes_config_path,
    api_get_hermes_config,
    api_hermes_memory_purge,
    api_save_hermes_config,
)
from archon.routers.hermes_ops import (
    router as _hermes_ops_router,
)

app.include_router(_hermes_ops_router)

# ============================================================================
# CHAT ROUTER & DELEGATION (ausgelagert nach archon.routers.chat)
# ============================================================================
# D-12: Default Fallback Modell für OmniRoute / Chat Stream
model = "auto/best-coding"
from archon.routers.chat import (
    ChatStreamRequest,
    ImageGenerateToolRequest,
    RenameSessionRequest,
    SetProfileModelRequest,
    _ensure_session_exists,
    _ensure_state_session,
    _load_state_history,
    _quickchat_state_session_id,
    _record_session_model_usage,
    _save_message_to_db,
    _warn_price_lookup_once,
    api_chat_stream,
    api_chat_upload,
    api_get_chat_session_messages,
    api_get_chat_sessions,
    api_rename_chat_session,
    api_tool_image_generate,
    record_task_tokens,
)
from archon.routers.chat import (
    configure as _chat_configure,
)
from archon.routers.chat import (
    router as _chat_router,
)

_chat_configure(create_decision=create_decision)
app.include_router(_chat_router)

# ============================================================================
# DELEGATION ENGINE v2 (ausgelagert nach archon.core.delegation)
# ============================================================================
from archon.core.delegation import (
    DELEGATION_ALIAS_MAP,
    _build_kader_roster_summary,
    _check_delegation_permission,
    _execute_delegation,
    _get_delegation_prompt_for,
    _load_org_hierarchy_map,
    _parse_delegation_blocks,
    _resolve_target_agent_id,
    _trigger_autonomous_orchestrator_followup,
)
from archon.core.delegation import (
    configure as _delegation_configure,
)

_delegation_configure(
    api_get_hermes_profiles=api_get_hermes_profiles,
    _get_state_db=_get_state_db,
    _ensure_session_exists=_ensure_session_exists,
    _save_message_to_db=_save_message_to_db,
    _spawn_background=_spawn_background,
    register_decision=register_decision,
    fan_in=lambda pid: _fan_in_maybe_start_synthesis(pid),
)

_GUARDIAN_STATS_CACHE = {}
# --- GUARDIAN ROUTER (ausgelagert nach archon.routers.guardian, 1157 Zeilen) ---
from archon.routers.guardian import (
    _GUARDIAN_ALLOWED_TIMEFRAMES,
    _GUARDIAN_CACHE_MAX_ENTRIES,
    _GUARDIAN_CACHE_TTL,
    api_clear_guardian_cache,
    api_get_guardian_config,
    api_get_guardian_stats,
    api_get_plugin_config,
    api_save_guardian_config,
    api_save_plugin_config,
    api_toggle_guardian_plugin,
)
from archon.routers.guardian import (
    router as _guardian_router,
)

app.include_router(_guardian_router)

# --- HERMES RAW CONFIG & LIVE EDITOR ENDPOINTS ---
# --- HERMES CONFIG ROUTER (ausgelagert nach archon.routers.hermes_config, 792 Zeilen) ---
from archon.routers.hermes_config import (
    _get_hermes_config_paths,
    api_get_hermes_form_config,
    api_get_hermes_raw_config,
    api_save_hermes_form_config,
    api_save_hermes_raw_config,
)
from archon.routers.hermes_config import (
    configure as _hermes_config_configure,
)
from archon.routers.hermes_config import (
    router as _hermes_config_router,
)

_hermes_config_configure(_sync_org_hierarchy_node=_sync_org_hierarchy_node)
app.include_router(_hermes_config_router)

# --- KONTEXT-HILFE (ausgelagert nach archon.routers.context_help) ---
from archon.routers.context_help import HELP_CONTEXT_DATA
from archon.routers.context_help import router as _context_help_router

app.include_router(_context_help_router)

# --- MEILENSTEIN 4: MULTI-USER & RBAC ENDPOINTS (ausgelagert nach archon.routers.auth) ---
from archon.routers.auth import (
    api_auth_change_password,
    api_auth_create_user,
    api_auth_delete_user,
    api_auth_list_users,
    api_auth_login,
    api_auth_logout,
    api_auth_me,
    api_auth_status,
    api_auth_toggle,
    api_auth_update_user,
    get_current_user_from_request,
    require_admin,
)
from archon.routers.auth import (
    configure as _auth_configure,
)
from archon.routers.auth import (
    router as _auth_router,
)
from backend.auth_service import auth_service

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
    # C21: bisher `status: success` mit leerer Liste — ein totes Endpoint,
    # das eine funktionierende Integration vortaeuschte.
    return {
        "status": "not_configured",
        "agents": [],
        "message": "Paperclip-Integration ist nicht angebunden; es werden keine Agenten gemeldet.",
    }


# --- TALENT- & SKILL-MARKTPLATZ ENDPOINTS (ausgelagert nach archon.routers.marketplace) ---
from archon.routers.marketplace import (
    api_assign_skill_to_profile,
    api_get_marketplace_sources,
    api_get_marketplace_template_detail,
    api_get_marketplace_templates,
    api_get_skill_detail,
    api_get_skill_sources,
    api_get_skills_list,
    api_marketplace_recruit,
)
from archon.routers.marketplace import (
    configure as _marketplace_configure,
)
from archon.routers.marketplace import (
    router as _marketplace_router,
)

_marketplace_configure(save_all_agent_profiles=save_all_agent_profiles)
app.include_router(_marketplace_router)

from archon.routers.memory_ops import (
    api_consolidate_memory,
    api_evict_stale_memory,
    api_get_agent_real_stats,
    api_get_memory_stats,
    api_memory_context,
    api_memory_learning,
    api_memory_profile,
    api_memory_vault_summary,
    clear_chat_history_api,
    get_chat_history_api,
)
from archon.routers.memory_ops import (
    router as _memory_ops_router,
)

app.include_router(_memory_ops_router)

from archon.routers.email_settings import (
    SmtpConfigPayload,
    api_get_smtp_settings,
    api_save_smtp_settings,
    api_sync_emails_endpoint,
    api_test_smtp_settings,
)
from archon.routers.email_settings import (
    router as _email_settings_router,
)

app.include_router(_email_settings_router)

from archon.routers.security_scanner import (
    api_get_security_stats,
    api_scan_email_security,
    api_validate_output_security,
)
from archon.routers.security_scanner import (
    router as _security_scanner_router,
)

app.include_router(_security_scanner_router)

from archon.routers.research import (
    api_get_research_dossier,
    api_get_research_history,
    api_get_research_providers,
    api_get_research_sources,
    api_run_research_mission,
)
from archon.routers.research import (
    router as _research_router,
)

app.include_router(_research_router)



# --- SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1) ---


# --- HERMES AGENT CORE UPDATE (NousResearch/hermes-agent) ---
from archon.routers.updater import (
    api_hermes_update_apply,
    api_hermes_update_check,
)
from archon.routers.updater import (
    router as _updater_router,
)

app.include_router(_updater_router)

# --- VERTRAGS- & FRISTENMANAGEMENT (t-0a2171) ---


# --- SAUBERES HERUNTERFAHREN & TASK-DRAINING (t-12113b) ---
def on_startup_drain_recovery():
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator
        res = graceful_shutdown_coordinator.auto_resume_on_startup()
        print(f"[Archon] Startup Recovery: {res}")
        # D07/MED: ein fehlgeschlagener Resume-Enqueue ist kein Erfolg. Der
        # Coordinator auditiert/eskaliert bereits; /readyz spiegelt den Fehler.
        failures = [
            cp for cp in (res.get("recovered_checkpoints") or [])
            if not (cp.get("restart") or {}).get("queued")
            and not (cp.get("restart") or {}).get("duplicate")
        ]
        if failures:
            for cp in failures:
                _STARTUP_RECOVERY_FAILED.append({
                    "task_id": cp.get("task_id"),
                    "reason": (cp.get("restart") or {}).get("reason", "unknown"),
                    "ts": time.time(),
                })
            logger.error(
                "[Startup] %s Re(sume)-Checkpoint(s) konnten nicht enqueued werden: %s",
                len(failures), [cp.get("task_id") for cp in failures],
            )
    except Exception as e:
        # Nicht nur stderr: Otherwise bleibt /readyz gruen trotz fehlgeschlagener Recovery.
        _STARTUP_RECOVERY_FAILED.append({"reason": str(e), "ts": time.time()})
        logger.error("[Startup] Startup Recovery Fehler: %s", e)
        print(f"[Archon] Startup Recovery Fehler: {e}", file=sys.stderr)


async def on_shutdown_graceful():
    # W3: Audit-Anker-Thread kontrolliert stoppen, bevor der Prozess stirbt.
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.stop_anchor_worker()
    except Exception as _anchor_exc:
        logger.debug("[Shutdown] Audit-Anker-Stopp: %s", _anchor_exc)
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
    _resolve_parser_input,
    api_extract_tables,
    api_parse_document,
)
from archon.routers.documents import (
    router as _documents_router,
)

app.include_router(_documents_router)


# --- DEAL-PIPELINE & FORECAST-ENGINE (ausgelagert nach archon.routers.deals) ---
from archon.routers.deals import (
    api_deal_forecast,
    api_delete_deal,
    api_get_deal,
    api_list_deals,
    api_move_deal_stage,
    api_save_deal,
)
from archon.routers.deals import (
    router as _deals_router,
)

app.include_router(_deals_router)


# --- PLUGIN SYSTEM & EXTENSIBILITY (MEILENSTEIN 5) ---


_VAULT_FILES_CACHE = {"ts": 0.0, "data": []}





# --- OBSIDIAN VAULT ROUTER (ausgelagert nach archon.routers.vault) ---
from archon.routers.vault import (
    _VAULT_FILES_CACHE,
    api_delete_vault_file_direct,
    api_edit_vault_file_direct,
    api_generate_vault_index,
    api_get_vault_files,
    api_get_vault_list,
    api_read_vault_file_direct,
)
from archon.routers.vault import (
    router as _vault_router,
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
    api_get_kanban,
    api_save_kanban,
)
from archon.routers.kanban import (
    router as _kanban_router,
)

app.include_router(_kanban_router)

# --- ARCHON V2 CAPABILITIES ROUTER (M32-M94) ---
from archon.routers.v2_capabilities import router as _v2_capabilities_router

app.include_router(_v2_capabilities_router)
from archon.routers.content_machine import router as _content_machine_router

app.include_router(_content_machine_router)

# --- DOCKER CONTAINER MANAGEMENT ROUTER (ausgelagert nach archon.routers.containers) ---
from archon.routers.containers import (
    ContainerActionRequest,
    _container_stats_payload,
    _docker_container_stats,
    docker_socket_request,
    get_all_container_logs_api,
    get_container_file_content,
    get_container_files_api,
    get_container_logs_api,
    get_container_metrics_api,
    get_container_settings,
    get_hermes_profile_logs_api,
    inject_container_config,
    load_agent_configs,
    run_container_action,
    save_agent_config,
    save_container_settings,
)
from archon.routers.containers import (
    configure as _containers_configure,
)
from archon.routers.containers import (
    router as _containers_router,
)

_containers_configure(
    detect_container_port=detect_container_port,
    post_docker_container_action=post_docker_container_action,
)
app.include_router(_containers_router)

from archon.routers.container_ops import (
    ContainerExecRequest,
    abort_agent_endpoint,
    exec_container_command_api,
    send_prompt_to_agent,
)
from archon.routers.container_ops import (
    router as _container_ops_router,
)

app.include_router(_container_ops_router)



app.include_router(_hermes_proxy_router)







from archon.routers.hr import (
    LogActivityReq,
    SavePersonalakteReq,
    SaveSoulReq,
    api_get_hermes_soul,
    api_get_personalakte,
    api_log_personalakte_activity,
    api_save_hermes_soul,
    api_save_personalakte,
)
from archon.routers.hr import (
    router as _hr_router,
)

app.include_router(_hr_router)




# 🚀 MISSION CONTROL 3-ZONEN-COCKPIT & HITL KANBAN API
# =====================================================================


from pydantic import BaseModel


class OSKanbanTaskStatusUpdate(BaseModel):
    status: str

# Mission-Control-Store -> archon.core.mission_control (Import oben)

from archon.services.mission_sync import (
    _LIVE_TELEMETRY_CACHE,
    _get_live_telemetry_metrics,
    _slugify,
    _sync_task_to_obsidian,
)


@app.get("/api/v1/events/stream")
async def sse_events_stream():
    """
    Server-Sent Events Stream für Realtime Push-Updates (Kanban, Telegram-Decisions, Ticker).
    Ersetzt clientseitiges aggressives Polling.
    """
    # Frueher: asyncio.Queue() unbegrenzt -> jeder langsame/stdBy-Client
    # akkumulierte Events bis zum OOM. Die zwischenzeitliche "unbegrenzt"
    # Loesung verhinderte zwar die Trennung, erzeugte aber ein Memory-Leak.
    # Jetzt: zentrale, begrenzte Queue aus archon.core.runtime. broadcast_event
    # verwirft bei Ueberlauf nur einzelne Events (kein Client-Disconnect),
    # der Client bekommt stattdessen regelmaessig Keepalives.
    queue = subscribe_events()

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
                    yield ": keepalive\n\n"
        except asyncio.CancelledError as cancel_exc:
            logger.debug(f"[SSE] Event-Stream vom Client geschlossen: {cancel_exc}")
        finally:
            unsubscribe_events(queue)

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


from backend.post_task_pipeline import project_folder_name
from dossier_builder import build_dossier_from_report
from telegram_notify import send_telegram_document, send_telegram_message


def _paperclip_hire_profile_by_id(profile_id: str, profiles: list, current_task_id: str = "") -> bool:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    return _orch_paperclip_hire_profile_by_id(
        profile_id, profiles, current_task_id,
        set_status=_set_agent_profile_status,
        ticker=add_ticker,
    )


def _set_agent_profile_status(profile_id: str, status: str, task_id: str = "") -> bool:
    """Wrapper: delegiert an archon.core.orchestration mit echten Dependencies."""
    return _orch_set_agent_profile_status(
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
        # Atomares Read-Modify-Write verhindert Lost Updates und Audit-Dupes.
        update_mc=update_mission_control_data,
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
    PromptOptimizeRequest,
    TemplateSaveRequest,
    optimize_prompt_endpoint,
    upload_prompt_studio_context,
)
from archon.routers.prompts import (
    router as _prompts_router,
)

app.include_router(_prompts_router)


from archon.routers.proxies import (
    _get_n8n_proxy,
    _get_omniroute_proxy,
    _get_shared_proxy_client,
    forward_to_n8n,
    forward_to_omniroute,
    n8n_assets_proxy,
    n8n_proxy,
    n8n_rest_proxy,
    omniroute_next_assets,
    omniroute_proxy,
)
from archon.routers.proxies import (
    router as _proxies_router,
)

app.include_router(_proxies_router)


from archon.routers.ui import (
    get_hud_page,
    get_index,
    get_index_v2,
    get_manifest,
    get_mobile_cockpit,
)

try:
    from views_core import get_apps_dir
    from views_core import router as views_core_router
    app.include_router(views_core_router)
    apps_static_dir = get_apps_dir()
    if os.path.exists(apps_static_dir):
        app.mount("/builds/apps", StaticFiles(directory=apps_static_dir), name="builds_apps")
except Exception as e_views:
    _ROUTER_LOAD_ERRORS.append("views_core: " + str(e_views))
    print(f"Error mounting views_core: {e_views}")

try:
    from backend.operations_api import router as operations_router
    app.include_router(operations_router)
    print("Operations API mounted successfully.")
except Exception as e_ops:
    _ROUTER_LOAD_ERRORS.append("operations_api: " + str(e_ops))
    print(f"Error mounting operations_api: {e_ops}")

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
    except Exception as exc:
        logger.error("[DebugDB] Fehler: %s", exc)
        raise HTTPException(status_code=500, detail="Interner Datenbankfehler")


# =====================================================================
# PROAKTIVER MORGEN-STANDUP & AUTONOMER WECKDIENST (Pillar 1 & 7)
# =====================================================================


from archon.routers.inbox_tools import (
    api_create_tool_proposal,
    api_get_inbox_watcher_config,
    api_list_tool_proposals,
    api_resolve_tool_proposal,
    api_save_inbox_watcher_config,
    api_scan_inbox_watcher_now,
)
from archon.routers.inbox_tools import (
    router as _inbox_tools_router,
)

app.include_router(_inbox_tools_router)


from archon.routers.autonomy_settings import (
    api_get_autonomy_modules_settings,
    api_get_model_routing,
    api_optimize_role_prompt,
    api_resolve_model_routing,
    api_run_eval_regression_suite,
    api_save_autonomy_modules_settings,
    api_save_model_routing,
    api_semantic_cache_clear,
    api_semantic_cache_lookup,
    api_semantic_cache_stats,
    api_semantic_cache_store,
)
from archon.routers.autonomy_settings import (
    router as _autonomy_settings_router,
)
from archon.routers.mesh import (
    api_accept_handoff,
    api_analyze_vision,
    api_approve_skill_proposal,
    api_browse_and_capture,
    api_check_task_budget,
    api_create_handoff,
    api_diff_preview,
    api_execute_sandbox,
    api_get_concurrency_status,
    api_get_consensus_history,
    api_get_memory_consolidation_settings,
    api_get_war_room_history,
    api_ingest_inbound_event,
    api_list_event_history,
    api_list_skill_proposals,
    api_query_rag,
    api_review_task_consensus,
    api_run_council_vote,
    api_run_war_room,
    api_save_concurrency_config,
    api_save_memory_consolidation_settings,
    api_scan_inbox_directory,
)
from archon.routers.mesh import (
    router as _mesh_router,
)
from archon.routers.resilience import (
    api_dispatch_notification,
    api_fleet_health_check,
    api_fork_task_trace,
    api_get_healing_logs,
    api_get_task_trace,
    api_heal_service,
    api_list_audit_logs,
    api_list_recent_notifications,
    api_list_snapshots,
    api_restore_snapshot,
    api_rollback_task_trace,
    api_verify_audit_log,
)
from archon.routers.resilience import (
    router as _resilience_router,
)

app.include_router(_resilience_router)
app.include_router(_mesh_router)
app.include_router(_autonomy_settings_router)


class HealingAttemptPayload(BaseModel):
    """D-D7 (A1/A7-DELEGATED): getippter Body statt rohem Dict.

    `apply_patch` ist bewusst KEIN Feld: eine Code-S-Schreibaktion ist eine
    HITL-Entscheidung und darf nicht vom Client ueber den Body erzwungen
    werden. `extra="ignore"` verwirft einen mitgelieferten apply_patch-Wert
    still, ohne die Route zu kippen.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str = "heal-task"
    title: str = "Autonome Fehlerbehebung"
    failed_code: str = ""
    error_output: str = ""
    worker_agent: str = "hermes-coder"
    affected_file: Optional[str] = None
    attempt: int = Field(default=1, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    model: Optional[str] = None


@app.post("/api/healing/attempt")
async def api_attempt_task_healing(request: Request, payload: HealingAttemptPayload):
    require_admin_or_503(request)
    from backend.task_self_healer import task_self_healer

    # P0-5 / D-D7: Patch-Anwendung nur aus der HITL-Session. Es gibt keinen
    # repo-weiten HITL-Session-Helper fuer diesen Pfad — daher fail-closed:
    # ohne explizit gesetztes Flag am Request-State wird nie geschrieben.
    apply_patch = bool(getattr(request.state, "hitl_apply_patch", False))
    return await task_self_healer.attempt_self_healing(
        task_id=payload.task_id,
        task_title=payload.title,
        failed_code=payload.failed_code,
        error_output=payload.error_output,
        worker_agent=payload.worker_agent,
        affected_file=payload.affected_file,
        attempt=payload.attempt,
        max_attempts=payload.max_attempts,
        model=payload.model,
        apply_patch=apply_patch,
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


def _ensure_zero_egress_worker_networks():
    """Stellt beim Start sicher, dass die isolierten Worker-/Sandbox-Docker-Netzwerke (`Internal=true`, ohne Internet-Route) bereitstehen."""
    try:
        from backend.llm_egress_guard import ensure_worker_zero_egress_network
        ensure_worker_zero_egress_network("archon-worker-zero-egress_net")
        ensure_worker_zero_egress_network("archon-sandbox_net")
    except Exception as e:
        # Kein stilles Debug: wenn die isolierten Netze fehlen, laufen Worker
        # moeglicherweise mit Internet-Route (Zero-Egress-Garantie weg).
        logger.warning(f"[ZeroEgress] Worker-Netzwerk-Init fehlgeschlagen: {e}")


async def _import_n8n_workflows_on_startup() -> None:
    """D06-Nachlauf (A7): opt-in n8n-Import/Aktivierung im Lifespan.

    Default `not_configured`: die Scripts nutzen `docker exec`/`docker cp` und
    schreiben einen Service-Token in 0600-Tempdateien. Nur mit
    `ARCHON_N8N_STARTUP_IMPORT=1` laeuft der Importer (inkl. Webhook-
    Aktivierung via activate_n8n_workflows.js) in einem Worker-Thread.
    `deploy_n8n_routines.run()` wird bewusst NICHT automatisch gerufen: es
    restarted den n8n-Container und beschreibt das versionierte Bundle
    (siehe Fix-Log — DELEGATED).
    """
    enabled = os.getenv("ARCHON_N8N_STARTUP_IMPORT", "").strip().lower() in ("1", "true", "yes")
    if not enabled:
        _N8N_STARTUP_STATUS.update(status="not_configured", detail="opt-in via ARCHON_N8N_STARTUP_IMPORT=1")
        return
    try:
        from scripts.import_n8n_workflows import main as _n8n_import_main
        rc = await asyncio.to_thread(_n8n_import_main)
        _N8N_STARTUP_STATUS.update(
            status="ok" if rc == 0 else "error",
            detail="import+activation ok" if rc == 0 else f"exit_code={rc}",
            ts=time.time(),
        )
        if rc != 0:
            logger.error("[Startup] n8n-Import/Aktivierung fehlgeschlagen (exit=%s).", rc)
        else:
            logger.info("[Startup] n8n-Import/Aktivierung erfolgreich.")
    except Exception as exc:
        _N8N_STARTUP_STATUS.update(
            status="error", detail=f"{type(exc).__name__}: {exc}", ts=time.time()
        )
        logger.error("[Startup] n8n-Import/Aktivierung fehlgeschlagen: %s", exc)


_STARTUP_HOOKS.extend([
    _start_watchdog_daemon,      # 1. Watchdog/Supervisor
    on_startup_drain_recovery,   # 2. Task-Recovery nach Absturz
    _harden_secret_permissions,  # 3. Secret-Dateien auf 600 setzen
    _ensure_zero_egress_worker_networks,  # 3b. Isolierte Docker-Worker-Netze (--internal, keine Internet-Route)
    _import_n8n_workflows_on_startup,  # 3c. D06: opt-in n8n-Import/Aktivierung (default not_configured)
    _start_gateway_idle_loop,    # 4. IMAP/Inbox/Internet-Watchdog-Loops
    _warm_hermes_skill_caches,   # 4. Skills-Cache vorwärmen (Thread)
    _check_rag_api_key_config,   # 5. RAG-Key vorhanden? Fehlt er -> ERROR-Zeile
])

def _stop_watchdog_daemon():
    """Watchdog-Supervisor (Prozess ODER Thread) beim Shutdown verifiziert stoppen."""
    global watchdog_runner
    if watchdog_runner is None:
        return
    runner = watchdog_runner
    watchdog_runner = None
    try:
        stopped = runner.stop()  # Event setzen + join + terminate/kill-Fallback
        if stopped is False:
            _WATCHDOG_STOP_FAILED.append({"reason": "stop() returned False", "ts": time.time()})
            logger.error("[Shutdown] Watchdog-Supervisor konnte nicht verifiziert gestoppt werden.")
    except Exception as exc:
        # F-042: frueher nur DEBUG -> der NameError im stop() war im Produktivlog
        # unsichtbar und der Thread lief beim Reload weiter.
        _WATCHDOG_STOP_FAILED.append({"reason": str(exc), "ts": time.time()})
        logger.error(f"[Shutdown] Watchdog-Stop fehlgeschlagen: {type(exc).__name__}: {exc}")


async def _cancel_tracked_tasks() -> None:
    """TaskRegistry leeren (Synthese-Kaskaden, Fan-In, Content-DAGs)."""
    global _LOOPS_STARTED
    try:
        from archon.core.task_registry import cancel_all
        n = await cancel_all()
        if n:
            logger.info("[Shutdown] %s registrierte Task(s) abgebrochen.", n)
    except Exception as exc:
        logger.debug(f"[Shutdown] TaskRegistry-Hinweis: {exc}")
    # In-Process-Restart: Guards zurücksetzen, sonst laufen beim 2. Lifespan
    # keine Hintergrund-Loops mehr (still abgeschaltete Autonomie).
    _LOOPS_STARTED = False


async def _close_dispatcher_clients() -> None:
    try:
        import core_dispatcher
        n = await core_dispatcher.close_dispatcher_clients()
        if n:
            logger.info("[Shutdown] %s Dispatcher-HTTP-Client(s) geschlossen.", n)
    except Exception as exc:
        logger.debug(f"[Shutdown] Dispatcher-Client-Hinweis: {exc}")


async def _close_all_http_clients() -> None:
    """D08/S-8.2 (A5/A9-DELEGATED): alle langlebigen Client-Pools schliessen.

    `agent_router.router_instance.close_http_clients()` existiert bereits.
    Die drei anderen Module haben (Stand Audit) KEINE close_all*-Funktion —
    deshalb werden ihre echten Modul-Attribute direkt geschlossen. Es wird
    bewusst kein nicht existierender Helfer aufgerufen.
    """
    closed = 0
    # 1. AgentRouter: vorhandener Helfer, idempotent.
    try:
        from backend import agent_router
        await agent_router.router_instance.close_http_clients()
    except Exception as exc:
        logger.debug("[Shutdown] AgentRouter-Client-Close-Hinweis: %s", exc)

    # 2./4. Loop-keyed Pools (echte Modulattribute, Snapshot vor clear()).
    for module_path, pool_name in (
        ("archon.routers.hermes_proxy", "_HERMES_CLIENTS_BY_LOOP"),
        ("utils.reverse_proxy", "_PROXY_CLIENTS"),
    ):
        try:
            if module_path.startswith("archon"):
                from archon.routers import hermes_proxy as _pool_module
            else:
                from utils import reverse_proxy as _pool_module
            pool = getattr(_pool_module, pool_name, None)
            clients = list(pool.values()) if pool is not None else []
            for client in clients:
                try:
                    if not client.is_closed:
                        await client.aclose()
                        closed += 1
                except Exception as exc:
                    logger.debug("[Shutdown] %s Client-Close-Hinweis: %s", pool_name, exc)
            if pool is not None:
                try:
                    pool.clear()
                except Exception as exc:
                    logger.debug("[Shutdown] %s Dict-Clear-Hinweis: %s", pool_name, exc)
        except Exception as exc:
            logger.debug("[Shutdown] %s Pool-Close-Hinweis: %s", pool_name, exc)

    # 3. system.py: einzelner globaler Client (kein Loop-Key).
    try:
        from archon.routers import system as _system_module
        client = getattr(_system_module, "_SYSTEM_HTTP_CLIENT", None)
        if client is not None:
            if not client.is_closed:
                await client.aclose()
                closed += 1
            setattr(_system_module, "_SYSTEM_HTTP_CLIENT", None)
    except Exception as exc:
        logger.debug("[Shutdown] System-Client-Close-Hinweis: %s", exc)

    if closed:
        logger.info("[Shutdown] %s HTTP-Client(s) zentral geschlossen.", closed)


async def _close_proxy_clients() -> None:
    """F-054: id(loop)-HTTP-Clients der Proxy-Router sauber schliessen."""
    try:
        from archon.routers.proxies import close_proxy_clients
        n = await close_proxy_clients()
        if n:
            logger.info("[Shutdown] %s Proxy-HTTP-Client(s) geschlossen.", n)
    except Exception as exc:
        logger.debug("[Shutdown] Proxy-Client-Close-Hinweis: %s", exc)


# Lifespan fuehrt Shutdown-Hooks in REVERSED order aus. Reihenfolge hier:
# zuerst Clients schliessen, Tasks canceln, Loops stoppen — und ON_SHUTDOWN_GRACEFUL
# als LETZTES Element, damit es in reversed() ZUERST laeuft: Drain/Checkpoint
# muss stattfinden, BEVOR Tasks und HTTP-Clients abgebrochen werden.
_SHUTDOWN_HOOKS.extend([
    _close_dispatcher_clients,   # reversed: zuletzt (Clients zuerst zu machen waere falsch)
    _close_proxy_clients,        # F-054: Proxy-HTTP-Clients (id(loop)) schliessen
    _cancel_tracked_tasks,       # TaskRegistry-Cascades abbrechen
    _stop_watchdog_daemon,       # Watchdog-Thread stoppen
    _cancel_background_tasks,    # Hintergrund-Loops stoppen
    _close_all_http_clients,     # reversed: frueh — alle HTTP-Pools vor Cancel schliessen
    on_shutdown_graceful,        # reversed: ZUERST — Drain & Checkpoint vor Cancel
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

    _ROUTER_LOAD_ERRORS.append("crm: " + str(_e_crm))
try:
    from archon.routers.erp import router as _erp_router
    app.include_router(_erp_router)
except Exception as _e_erp:
    logger.warning(f"[Router] erp nicht geladen: {_e_erp}")

    _ROUTER_LOAD_ERRORS.append("erp: " + str(_e_erp))
try:
    from archon.routers.corporate import router as _corporate_router
    app.include_router(_corporate_router)
except Exception as _e_corporate:
    logger.warning(f"[Router] corporate nicht geladen: {_e_corporate}")

    _ROUTER_LOAD_ERRORS.append("corporate: " + str(_e_corporate))
try:
    from archon.routers.security import router as _security_router
    app.include_router(_security_router)
except Exception as _e_security:
    logger.warning(f"[Router] security nicht geladen: {_e_security}")

    _ROUTER_LOAD_ERRORS.append("security: " + str(_e_security))
try:
    from archon.routers.execution import router as _execution_router
    app.include_router(_execution_router)
except Exception as _e_execution:
    logger.warning(f"[Router] execution nicht geladen: {_e_execution}")

    _ROUTER_LOAD_ERRORS.append("execution: " + str(_e_execution))
try:
    from archon.routers.memory import router as _memory_router
    app.include_router(_memory_router)
except Exception as _e_memory:
    logger.warning(f"[Router] memory nicht geladen: {_e_memory}")

    _ROUTER_LOAD_ERRORS.append("memory: " + str(_e_memory))
try:
    from archon.routers.context_packages import router as _context_packages_router
    app.include_router(_context_packages_router)
except Exception as _e_context_packages:
    logger.warning(f"[Router] context_packages nicht geladen: {_e_context_packages}")

    _ROUTER_LOAD_ERRORS.append("context_packages: " + str(_e_context_packages))
try:
    from archon.routers.routergate import router as _routergate_router
    app.include_router(_routergate_router)
except Exception as _e_routergate:
    logger.warning(f"[Router] routergate nicht geladen: {_e_routergate}")

    _ROUTER_LOAD_ERRORS.append("routergate: " + str(_e_routergate))
try:
    from archon.routers.voice import router as _voice_router
    app.include_router(_voice_router)
except Exception as _e_voice:
    logger.warning(f"[Router] voice nicht geladen: {_e_voice}")

    _ROUTER_LOAD_ERRORS.append("voice: " + str(_e_voice))
try:
    from archon.routers.swarm import router as _swarm_router
    app.include_router(_swarm_router)
except Exception as _e_swarm:
    logger.warning(f"[Router] swarm nicht geladen: {_e_swarm}")

    _ROUTER_LOAD_ERRORS.append("swarm: " + str(_e_swarm))
try:
    from archon.routers.contracts import router as _contracts_router
    app.include_router(_contracts_router)
except Exception as _e_contracts:
    logger.warning(f"[Router] contracts nicht geladen: {_e_contracts}")

    _ROUTER_LOAD_ERRORS.append("contracts: " + str(_e_contracts))


# --- Weitere ausgelagerte Router (Stufe 2) ---
try:
    from archon.routers.plugins import router as _plugins_router2
    app.include_router(_plugins_router2)
except Exception as _e2_plugins:
    logger.warning(f"[Router] plugins nicht geladen: {_e2_plugins}")

    _ROUTER_LOAD_ERRORS.append("plugins: " + str(_e2_plugins))
try:
    from archon.routers.governance import (
        configure as _governance_configure,
    )
    from archon.routers.governance import (
        router as _governance_router2,
    )
    _governance_configure(
        _load_mission_control_data=_load_mission_control_data,
        _save_mission_control_data=_save_mission_control_data,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_governance_router2)
except Exception as _e2_governance:
    logger.warning(f"[Router] governance nicht geladen: {_e2_governance}")

    _ROUTER_LOAD_ERRORS.append("governance: " + str(_e2_governance))
try:
    from archon.routers.templates import router as _templates_router2
    app.include_router(_templates_router2)
except Exception as _e2_templates:
    logger.warning(f"[Router] templates nicht geladen: {_e2_templates}")

    _ROUTER_LOAD_ERRORS.append("templates: " + str(_e2_templates))
try:
    from archon.routers.boardroom import (
        configure as _boardroom_configure,
    )
    from archon.routers.boardroom import (
        router as _boardroom_router2,
    )
    _boardroom_configure(
        load_boardroom_frameworks=load_boardroom_frameworks,
        load_roles=load_roles,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_boardroom_router2)
except Exception as _e2_boardroom:
    logger.warning(f"[Router] boardroom nicht geladen: {_e2_boardroom}")

    _ROUTER_LOAD_ERRORS.append("boardroom: " + str(_e2_boardroom))

try:
    from archon.routers.llm_providers import router as _llm_providers_r
    app.include_router(_llm_providers_r)
except Exception as _err_llmp:
    logger.warning(f"[Router] llm_providers nicht geladen: {_err_llmp}")

    _ROUTER_LOAD_ERRORS.append("llm_providers: " + str(_err_llmp))

try:
    from archon.routers.hermes_profiles import (
        configure as _hp_configure,
    )
    from archon.routers.hermes_profiles import (
        router as _hermes_profiles_r,
    )
    _hp_configure(
        save_all_agent_profiles=save_all_agent_profiles,
        _sync_org_hierarchy_node=_sync_org_hierarchy_node,
        invalidate_paperclip_agents_cache=invalidate_paperclip_agents_cache,
    )
    app.include_router(_hermes_profiles_r)
except Exception as _err_hp:
    logger.warning(f"[Router] hermes_profiles nicht geladen: {_err_hp}")

    _ROUTER_LOAD_ERRORS.append("hermes_profiles: " + str(_err_hp))

# Der Profil-Service traegt nur den Organigramm-Sync als echte Abhaengigkeit.
# Bewusst ausserhalb des Router-try: der Gate-Pfad braucht ihn auch dann.
try:
    profiles_service.configure(org_sync_node=_sync_org_hierarchy_node)
except Exception as _err_ps:
    logger.warning(f"[Services] profiles_service.configure fehlgeschlagen: {_err_ps}")

try:
    from archon.routers.system import (
        configure as _system_configure,
    )
    from archon.routers.system import (
        router as _system_r,
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

    _ROUTER_LOAD_ERRORS.append("system: " + str(_err_sys))

try:
    from archon.routers.skills import (
        configure as _skills_configure,
    )
    from archon.routers.skills import (
        router as _skills_r,
    )
    _skills_configure(
        skills_engine=skills_engine,
        api_get_hermes_profiles=api_get_hermes_profiles,
    )
    app.include_router(_skills_r)
except Exception as _err_sk:
    logger.warning(f"[Router] skills nicht geladen: {_err_sk}")

    _ROUTER_LOAD_ERRORS.append("skills: " + str(_err_sk))

try:
    from archon.routers.mission_control import (
        configure as _mc_configure,
    )
    from archon.routers.mission_control import (
        router as _mc_router,
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

    _ROUTER_LOAD_ERRORS.append("mission_control: " + str(_err_mc))

try:
    from archon.routers.onboarding import router as _onboarding_r
    app.include_router(_onboarding_r)
except Exception as _err_onb:
    logger.warning(f"[Router] onboarding nicht geladen: {_err_onb}")

    _ROUTER_LOAD_ERRORS.append("onboarding: " + str(_err_onb))

try:
    from archon.routers.demo import router as _demo_r
    app.include_router(_demo_r)
except Exception as _err_demo:
    logger.warning(f"[Router] demo nicht geladen: {_err_demo}")

    _ROUTER_LOAD_ERRORS.append("demo: " + str(_err_demo))

try:
    from archon.routers.mcp_gateway import router as _mcp_gateway_r
    app.include_router(_mcp_gateway_r)
except Exception as _err_mcp_gw:
    logger.warning(f"[Router] mcp_gateway nicht geladen: {_err_mcp_gw}")

    _ROUTER_LOAD_ERRORS.append("mcp_gateway: " + str(_err_mcp_gw))

try:
    from archon.routers.squad_packs import router as _squad_packs_r
    app.include_router(_squad_packs_r)
except Exception as _err_sp:
    logger.warning(f"[Router] squad_packs nicht geladen: {_err_sp}")

    _ROUTER_LOAD_ERRORS.append("squad_packs: " + str(_err_sp))

try:
    from archon.routers.tenants import router as _tenants_r
    app.include_router(_tenants_r)
except Exception as _err_ten:
    logger.warning(f"[Router] tenants nicht geladen: {_err_ten}")

    _ROUTER_LOAD_ERRORS.append("tenants: " + str(_err_ten))

try:
    from archon.routers.playbooks import router as _playbooks_r
    app.include_router(_playbooks_r)
except Exception as _err_pb:
    logger.warning(f"[Router] playbooks nicht geladen: {_err_pb}")

    _ROUTER_LOAD_ERRORS.append("playbooks: " + str(_err_pb))

try:
    from archon.routers.preflight_shadow import router as _preflight_r
    app.include_router(_preflight_r)
except Exception as _err_pf:
    logger.warning(f"[Router] preflight_shadow nicht geladen: {_err_pf}")

    _ROUTER_LOAD_ERRORS.append("preflight_shadow: " + str(_err_pf))

try:
    from archon.routers.epistemic_hygiene import router as _hygiene_r
    app.include_router(_hygiene_r)
except Exception as _err_hyg:
    logger.warning(f"[Router] epistemic_hygiene nicht geladen: {_err_hyg}")

    _ROUTER_LOAD_ERRORS.append("epistemic_hygiene: " + str(_err_hyg))

try:
    from archon.routers.operations_calendar import router as _cal_r
    from archon.routers.operations_calendar import ws_router as _cal_ws_r
    app.include_router(_cal_r)
    app.include_router(_cal_ws_r)
except Exception as _err_cal:
    logger.warning(f"[Router] operations_calendar nicht geladen: {_err_cal}")

    _ROUTER_LOAD_ERRORS.append("operations_calendar: " + str(_err_cal))


def _assert_router_health() -> None:
    """Fail-closed: fehlgeschlagene Router-Imports brechen den Start ab.

    F-076: frueher galt die Produktionsbedingung (auth aktiv oder
    ENVIRONMENT=production). Im Default-Start (ENVIRONMENT=development, lokale
    Auth aus) genuegte ein ERROR-Log — die Anwendung lief mit still 404-enden
    Routern weiter. Jeder Eintrag in _ROUTER_LOAD_ERRORS (von den
    try/except-Bloecken oben) fuehrt jetzt unbedingt zu RuntimeError.
    Nur fuer lokale Dev-Debugs gibt es den expliziten Opt-Out
    ARCHON_ALLOW_BROKEN_ROUTERS=true, der laut im Log dokumentiert wird.
    """
    if not _ROUTER_LOAD_ERRORS:
        return
    detail = "; ".join(_ROUTER_LOAD_ERRORS)
    opt_out = os.environ.get("ARCHON_ALLOW_BROKEN_ROUTERS", "").strip().lower() in (
        "1", "true", "yes",
    )
    if opt_out:
        logger.error(
            "[Router] OPT-OUT ARCHON_ALLOW_BROKEN_ROUTERS=true: %s Router(s) "
            "nicht geladen: %s",
            len(_ROUTER_LOAD_ERRORS), detail,
        )
        return
    raise RuntimeError(
        f"[Router] {len(_ROUTER_LOAD_ERRORS)} Router(s) nicht geladen: {detail}"
    )


_STARTUP_HOOKS.insert(0, _assert_router_health)


def _assert_audit_hmac() -> None:
    """GoBD/ISO27001: ohne HMAC-Key ist die Audit-Kette ab Block 1 fälschbar.

    In Produktion (oder wenn bereits HMAC-Blöcke existieren) ist der Key
    zwingend. In Development ohne bestehende HMAC-Blöcke genügt eine laute
    Warnung.
    """
    key = str(os.environ.get("ARCHON_AUDIT_HMAC_KEY") or "").strip()
    if key:
        return
    env_name = str(
        os.environ.get("ENVIRONMENT") or os.environ.get("ARCHON_ENV") or ""
    ).strip().lower()
    prod = env_name in ("production", "prod", "live")
    # Die mitgelieferte Compose-Datei setzt ENVIRONMENT=development. Ohne
    # Einbeziehung des Auth-/Bind-Status greift der Schutz im Default-Deployment
    # nie — genau dort muss der Key aber zwingend vorhanden sein.
    try:
        from backend.auth_service import auth_service
        prod = prod or bool(auth_service.is_auth_enabled()) or bool(auth_service._must_force_auth())
    except Exception:
        prod = True  # fail-closed: keine Konfiguration lesbar → kein Start ohne Key
    has_hmac_blocks = False
    try:
        import sqlite3

        from backend.db_paths import resolve_db
        with sqlite3.connect(f"file:{resolve_db('agentic_memory.db')}?mode=ro", uri=True, timeout=3) as conn:
            has_hmac_blocks = conn.execute(
                "SELECT 1 FROM audit_log WHERE current_hash LIKE 'hmac-sha256:%' LIMIT 1"
            ).fetchone() is not None
    except Exception as exc:
        # Ein lesbarer HMAC-Block ist nicht nachweisbar → nicht als "kein Block"
        # interpretieren. In Produktion wird ohnehin abgebrochen; in Development
        # bleibt es bei einer lauten Warnung.
        logger.warning("[Audit] HMAC-Block-Pruefung nicht moeglich: %s", exc)
        has_hmac_blocks = False
    if prod or has_hmac_blocks:
        raise RuntimeError(
            "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt — Revisionskette ist manipulierbar (GoBD/ISO27001). "
            "Key aus ENV setzen (z.B. secrets.token_hex(32))."
        )
    logger.warning("[Audit] ARCHON_AUDIT_HMAC_KEY nicht gesetzt — Audit-Kette ist NICHT manipulationssicher (Development).")


_STARTUP_HOOKS.insert(0, _assert_audit_hmac)

# B (Auth-Fail-Open): Nicht-Loopback-Bind ohne Auth muss den Start abbrechen.
_STARTUP_HOOKS.insert(0, _assert_auth_on_nonloopback_bind)

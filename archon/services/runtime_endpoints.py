"""Runtime-Endpoints, Middleware-Installer und Lifecycle-Hooks fuer main.py (M4).

Kapselt:
- ``TraceContextMiddleware``, ``install_cors_middleware``, ``install_rate_limit_middleware``
- ``sse_events_stream`` (SSE-Push-Stream)
- ``HealingAttemptPayload`` & ``run_task_healing``
- ``on_startup_drain_recovery``, ``on_shutdown_graceful``, ``_cancel_tracked_tasks``,
  ``_warm_hermes_skill_caches``, ``_assert_router_health``

Alle zustandstragenden Contracts aus ``main.py`` (``_STARTUP_RECOVERY_FAILED``,
``_ROUTER_LOAD_ERRORS``, ``_reset_loops_started``) werden per S3-Call-Time-Injektion
bereitgestellt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from typing import Any, AsyncIterator, Callable, NamedTuple, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from archon.core.runtime import subscribe_events, unsubscribe_events
from backend.trace_context import extract_headers as _extract_traceparent
from backend.trace_context import response_trace_headers as _response_trace_headers
from backend.trace_context import start_trace as _start_trace

logger = logging.getLogger("archon_os")


class RuntimeEndpointsDeps(NamedTuple):
    startup_recovery_failed: list[dict[str, Any]]
    router_load_errors: list[str]
    reset_loops_started: Callable[[], None]


_DEPS_PROVIDER: Optional[Callable[[], RuntimeEndpointsDeps]] = None


def register_runtime_endpoints_deps_provider(
    provider: Callable[[], RuntimeEndpointsDeps],
) -> None:
    """Registriert den Call-Time-Dependency-Provider aus main.py (S3)."""
    global _DEPS_PROVIDER
    _DEPS_PROVIDER = provider


def _deps() -> RuntimeEndpointsDeps:
    if _DEPS_PROVIDER is None:
        raise RuntimeError(
            "RuntimeEndpointsDeps provider not registered "
            "(call register_runtime_endpoints_deps_provider first)"
        )
    return _DEPS_PROVIDER()


class TraceContextMiddleware(BaseHTTPMiddleware):
    """Audit D16/HIGH: W3C Trace Context an der Systemgrenze (aeusserste Schicht)."""

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Any:
        _start_trace(_extract_traceparent(request.headers))
        response = await call_next(request)
        try:
            from backend.metrics_collector import record_trace_exemplar

            record_trace_exemplar(
                "archon_agent_dispatches_total",
                labels={"route": request.url.path, "status": response.status_code},
            )
        except Exception as _exemplar_exc:
            logger.debug("[Trace] Exemplar nicht aufgezeichnet: %s", _exemplar_exc)
        for key, value in _response_trace_headers(dict(response.headers)).items():
            response.headers[key] = value
        return response


def install_cors_middleware(app: FastAPI) -> None:
    """CORS muss AUSSERHALB des Auth-Gates liegen."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8501",
            "http://127.0.0.1:8501",
            "http://localhost:3005",
            "http://127.0.0.1:3005",
            "http://localhost:8787",
            "http://127.0.0.1:8787",
        ]
        + [
            o.strip()
            for o in os.environ.get("ARCHON_CORS_ORIGINS", "").split(",")
            if o.strip()
        ],
        # LAN-Zugriffe (Handy/Tablet) ohne Wildcard für das ganze Internet
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "Accept",
            "Origin",
        ],
    )


def install_rate_limit_middleware(app: FastAPI) -> None:
    """Rate-Limit AUSSERHALB des Auth-Gates registrieren."""
    try:
        from utils.rate_limit import RateLimitMiddleware
        from utils.rate_limit import _env_int as _rl_env_int

        app.add_middleware(RateLimitMiddleware)
        logger.info(
            "[RateLimit] aktiv (Standard %s/min, strikt %s/min)",
            _rl_env_int("ARCHON_RATE_LIMIT_DEFAULT", 600),
            _rl_env_int("ARCHON_RATE_LIMIT_STRICT", 20),
        )
    except Exception as _err_rl:
        logger.warning(f"[RateLimit] nicht aktiv: {_err_rl}")


async def sse_events_stream() -> StreamingResponse:
    """
    Server-Sent Events Stream für Realtime Push-Updates (Kanban, Telegram-Decisions, Ticker).
    Ersetzt clientseitiges aggressives Polling.
    """
    queue = subscribe_events()

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
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
            "X-Accel-Buffering": "no",
        },
    )


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


async def run_task_healing(
    request: Request, payload: HealingAttemptPayload
) -> Any:
    """Fuehrt den Task-Self-Healing-Pfad fail-closed (HITL-Flag) aus."""
    from backend.task_self_healer import task_self_healer

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


async def _warm_hermes_skill_caches() -> None:
    """Skills-Caches VOR dem ersten Request warm machen (Disk -> Memory)."""

    def _warm() -> None:
        t0 = time.time()
        try:
            from archon.routers.skills import (
                api_get_hermes_skills,
                build_skills_file_index,
            )

            build_skills_file_index()
            api_get_hermes_skills()
            print(f"[Skills-Warmup] caches warm after {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[Skills-Warmup] failed: {e}")

    threading.Thread(target=_warm, daemon=True, name="skills-warmup").start()


def on_startup_drain_recovery() -> None:
    """Task-Recovery nach Absturz; Fehler werden fuer /readyz protokolliert."""
    d = _deps()
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

        res = graceful_shutdown_coordinator.auto_resume_on_startup()
        print(f"[Archon] Startup Recovery: {res}")
        failures = [
            cp
            for cp in (res.get("recovered_checkpoints") or [])
            if not (cp.get("restart") or {}).get("queued")
            and not (cp.get("restart") or {}).get("duplicate")
        ]
        if failures:
            for cp in failures:
                d.startup_recovery_failed.append(
                    {
                        "task_id": cp.get("task_id"),
                        "reason": (cp.get("restart") or {}).get("reason", "unknown"),
                        "ts": time.time(),
                    }
                )
            logger.error(
                "[Startup] %s Re(sume)-Checkpoint(s) konnten nicht enqueued werden: %s",
                len(failures),
                [cp.get("task_id") for cp in failures],
            )
    except Exception as e:
        d.startup_recovery_failed.append({"reason": str(e), "ts": time.time()})
        logger.error("[Startup] Startup Recovery Fehler: %s", e)
        print(f"[Archon] Startup Recovery Fehler: {e}", file=sys.stderr)


def _audit_shutdown_failure(action: str, detail: str, **extra: Any) -> None:
    """D07-M6: Shutdown-Fehler signiert melden; Strict-Modus bricht hart ab."""
    from backend.audit_log import _is_audit_strict, _require_audit_event

    payload: dict[str, Any] = {"detail": detail, "ts": time.time(), **extra}
    try:
        _require_audit_event(
            category="shutdown", action=action, agent_id="system", payload=payload
        )
    except RuntimeError:
        if _is_audit_strict():
            raise
        logger.error("[Shutdown] Pflicht-Event %s nicht geschrieben (Strict aus)", action)


async def on_shutdown_graceful() -> None:
    """W3: Audit-Anker-Thread kontrolliert stoppen und Graceful Shutdown ausfuehren."""
    try:
        from backend.audit_log import chained_audit_log

        await asyncio.to_thread(chained_audit_log.stop_anchor_worker)
    except Exception as _anchor_exc:
        logger.error("[Shutdown] Audit-Anker-Stopp fehlgeschlagen: %s", _anchor_exc)
        _audit_shutdown_failure("anchor_stop_failed", str(_anchor_exc))
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

        res = await graceful_shutdown_coordinator.execute_graceful_shutdown(
            reason="Server shutdown / restart"
        )
        print(f"[Archon] Graceful Shutdown ausgeführt: {res}")
    except Exception as e:
        logger.error("[Shutdown] Graceful Shutdown fehlgeschlagen: %s", e)
        print(f"[Archon] Graceful Shutdown Fehler: {e}", file=sys.stderr)
        _audit_shutdown_failure("graceful_shutdown_failed", str(e))


async def _cancel_tracked_tasks() -> None:
    """TaskRegistry leeren (Synthese-Kaskaden, Fan-In, Content-DAGs)."""
    d = _deps()
    try:
        from archon.core.task_registry import cancel_all

        n = await cancel_all()
        if n:
            logger.info("[Shutdown] %s registrierte Task(s) abgebrochen.", n)
    except Exception as exc:
        logger.debug(f"[Shutdown] TaskRegistry-Hinweis: {exc}")
    d.reset_loops_started()


def _assert_router_health() -> None:
    """Fail-closed: fehlgeschlagene Router-Imports brechen den Start ab."""
    d = _deps()
    if not d.router_load_errors:
        return
    detail = "; ".join(d.router_load_errors)
    opt_out = os.environ.get("ARCHON_ALLOW_BROKEN_ROUTERS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if opt_out:
        logger.error(
            "[Router] OPT-OUT ARCHON_ALLOW_BROKEN_ROUTERS=true: %s Router(s) "
            "nicht geladen: %s",
            len(d.router_load_errors),
            detail,
        )
        return
    raise RuntimeError(
        f"[Router] {len(d.router_load_errors)} Router(s) nicht geladen: {detail}"
    )

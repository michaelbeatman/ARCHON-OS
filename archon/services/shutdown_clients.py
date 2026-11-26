"""Startup-Hardening (Secrets/Zero-Egress/n8n) & Shutdown HTTP-Client-Close (M2 aus main.py).

Reine Extraktion ohne Rueckimport auf ``main``:
* ``_N8N_STARTUP_STATUS`` wird in ``main.py`` als identisches Dict re-exportiert.
* ``_STARTUP_HOOKS.extend([...])`` und ``_SHUTDOWN_HOOKS.extend([...])``
  bleiben physisch in ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict

from archon.core.runtime import add_ticker

logger = logging.getLogger("archon_os")

_N8N_STARTUP_STATUS: Dict[str, Any] = {
    "status": "not_configured",
    "detail": "opt-in via ARCHON_N8N_STARTUP_IMPORT=1",
}


def _harden_secret_permissions() -> None:
    """Setzt 600 auf Secret-Dateien (.env, Tokens) und meldet Verstoss-Funde."""
    try:
        from utils.secret_files import audit_known_secrets, harden_known_secrets

        _offenders = audit_known_secrets()
        _fixed = harden_known_secrets()
        if _fixed:
            logger.warning(
                f"[Secrets] Rechte gehaertet (600): {', '.join(_fixed[:6])}"
                + (" ..." if len(_fixed) > 6 else "")
            )
        if _offenders:
            add_ticker("Security", f"{len(_offenders)} Secret-Datei(en) waren zu offen - Rechte korrigiert")
        else:
            logger.info("[Secrets] Alle Secret-Dateien haben korrekte Rechte (600).")
    except Exception as e:
        logger.warning(f"[Secrets] Rechte-Pruefung fehlgeschlagen: {e}")


def _ensure_zero_egress_worker_networks() -> None:
    """Stellt beim Start sicher, dass die isolierten Worker-/Sandbox-Docker-Netzwerke bereitstehen."""
    try:
        from backend.llm_egress_guard import ensure_worker_zero_egress_network

        ensure_worker_zero_egress_network("archon-worker-zero-egress_net")
        ensure_worker_zero_egress_network("archon-sandbox_net")
    except Exception as e:
        logger.warning(f"[ZeroEgress] Worker-Netzwerk-Init fehlgeschlagen: {e}")


async def _import_n8n_workflows_on_startup() -> None:
    """D06-Nachlauf (A7): opt-in n8n-Import/Aktivierung im Lifespan."""
    enabled = os.getenv("ARCHON_N8N_STARTUP_IMPORT", "").strip().lower() in ("1", "true", "yes")
    if not enabled:
        _N8N_STARTUP_STATUS.update(
            status="not_configured",
            detail="opt-in via ARCHON_N8N_STARTUP_IMPORT=1",
        )
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


async def _close_dispatcher_clients() -> None:
    try:
        import core_dispatcher

        result = await core_dispatcher.close_dispatcher_clients()
        if isinstance(result, dict):
            closed = int(result.get("closed", 0) or 0)
            failed = int(result.get("failed_closes", 0) or 0)
            if closed:
                logger.info("[Shutdown] %s Dispatcher-HTTP-Client(s) geschlossen.", closed)
            if failed:
                from core_dispatcher import _record_failed_cancel

                for detail in result.get("failed_clients") or []:
                    _record_failed_cancel("dispatcher_http_client_close", str(detail))
                logger.error("[Shutdown] %s Dispatcher-Client-Close(s) fehlgeschlagen.", failed)
        elif result:
            logger.info("[Shutdown] %s Dispatcher-HTTP-Client(s) geschlossen.", result)
    except Exception as exc:
        logger.error(f"[Shutdown] Dispatcher-Client-Close fehlgeschlagen: {exc}")


def _record_client_close_failure(pool_name: str, exc: BaseException) -> None:
    """D07-M6: Client-Close-Fehler als ERROR + signiertes Audit, nie nur DEBUG."""
    detail = f"{pool_name}: {type(exc).__name__}: {exc}"
    logger.error("[Shutdown] %s", detail)
    entry: dict[str, Any] = {
        "task": f"client_close:{pool_name}",
        "detail": str(exc),
        "ts": time.time(),
        "audit_status": "pending",
    }
    try:
        from archon.services.background_loops import _FAILED_CANCELS

        _FAILED_CANCELS.append(entry)
    except Exception:
        logger.debug("[Shutdown] _FAILED_CANCELS-Spiegelung nicht verfügbar: %s", pool_name)

    from backend.audit_log import _is_audit_strict, _require_audit_event

    try:
        _require_audit_event(
            category="shutdown",
            action="client_close_failed",
            agent_id="system",
            payload={"pool": pool_name, "detail": detail, "ts": time.time()},
        )
        entry["audit_status"] = "ok"
    except RuntimeError:
        entry["audit_status"] = "error"
        if _is_audit_strict():
            raise
        logger.error("[Shutdown] Client-Close-Audit fehlgeschlagen (Strict aus): %s", pool_name)


async def _close_all_http_clients() -> None:
    """D08/S-8.2: alle langlebigen Client-Pools schliessen."""
    closed = 0
    try:
        from backend import agent_router

        await agent_router.router_instance.close_http_clients()
    except Exception as exc:
        _record_client_close_failure("agent_router", exc)

    for module_path, pool_name in (
        ("archon.routers.hermes_proxy", "_HERMES_CLIENTS_BY_LOOP"),
        ("utils.reverse_proxy", "_PROXY_CLIENTS"),
    ):
        try:
            if module_path.startswith("archon"):
                from archon.routers import hermes_proxy as _pool_module
            else:
                from utils import reverse_proxy as _pool_module  # type: ignore[no-redef]
            pool = getattr(_pool_module, pool_name, None)
            clients = list(pool.values()) if pool is not None else []
            for client in clients:
                try:
                    if not client.is_closed:
                        await client.aclose()
                        closed += 1
                except Exception as exc:
                    _record_client_close_failure(pool_name, exc)
            if pool is not None:
                try:
                    pool.clear()
                except Exception as exc:
                    _record_client_close_failure(f"{pool_name}.clear", exc)
        except Exception as exc:
            _record_client_close_failure(f"{pool_name}.pool", exc)

    try:
        from archon.routers import system as _system_module

        client = getattr(_system_module, "_SYSTEM_HTTP_CLIENT", None)
        if client is not None:
            if not client.is_closed:
                await client.aclose()
                closed += 1
            setattr(_system_module, "_SYSTEM_HTTP_CLIENT", None)
    except Exception as exc:
        _record_client_close_failure("system", exc)

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

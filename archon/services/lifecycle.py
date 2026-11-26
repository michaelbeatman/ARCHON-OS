"""2b — App-Lifespan (Startup-/Shutdown-Pfad) aus main.py extrahiert.

Reine Extraktion: der Koerper von ``main._archon_lifespan`` (frueher Zeilen
764-813) ist 1:1 hierher gewandert. Alle stabilen Contracts bleiben PHYSISCH
in ``main.py`` und werden zur Aufrufzeit als Parameter uebergeben:

* ``_STARTUP_HOOKS`` + die 5 ``insert(0, ...)``-Stellen (Ausfuehrungsreihenfolge)
* ``_SHUTDOWN_HOOKS`` in ``reversed()``
* ``_FAIL_FAST_HOOKS`` (raise statt Log)
* ``_init_readiness_probe_table`` (D08/H-08-2: einmalig im Lifespan)

Dependency-Injection (S3): kein Modul-Level-Rueckimport nach ``main``. Der
Logger-Name bleibt bewusst ``archon_os`` (kein stiller Kanal-Wechsel, vgl. B9).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, List, Set

logger = logging.getLogger("archon_os")

__all__ = ["lifespan_context"]

# D07-M7: Gesamtbudget fuer den kompletten Shutdown (Hooks + Liveness-Stop).
_SHUTDOWN_BUDGET_SECONDS = 10.0


def _audit_shutdown_hook(name: str, status: str, duration_ms: float) -> None:
    """D07-M7: Hook-Name und Dauer im signierten Pflicht-Audit festhalten."""
    from backend.audit_log import _is_audit_strict, _require_audit_event

    try:
        _require_audit_event(
            category="shutdown",
            action="shutdown_hook",
            agent_id="system",
            payload={
                "hook": name,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "ts": time.time(),
            },
        )
    except RuntimeError:
        if _is_audit_strict():
            raise
        logger.error("[Lifespan] Shutdown-Hook-Audit fehlgeschlagen: %s", name)


@asynccontextmanager
async def lifespan_context(
    *,
    startup_hooks: List[Any],
    shutdown_hooks: List[Any],
    fail_fast_hooks: Set[str],
    init_readiness_probe_table: Callable[[], None],
) -> AsyncIterator[None]:
    """Einziger geordneter Startup/Shutdown-Pfad der App.

    Fail-Fast-Hooks raisen (Start bricht ab); alle uebrigen Hook-Fehler werden
    nur geloggt. Shutdown laeuft in ``reversed()`` und ist durch ``finally``
    auch bei GeneratorExit/Exceptions garantiert.
    """
    try:
        from backend.loop_liveness import start_loop_heartbeat, stop_loop_heartbeat

        await start_loop_heartbeat()
    except Exception as _ll_start_err:
        stop_loop_heartbeat = None  # type: ignore[assignment]
        logger.warning(f"[Lifespan] Loop-Liveness-Start fehlgeschlagen: {_ll_start_err}")

    # D08/H-08-2: die Readiness-Schreibprobe wird EINMAL im Lifespan angelegt,
    # nicht bei jedem Healthcheck-Scrape (vorher CREATE TABLE pro /readyz).
    try:
        await asyncio.to_thread(init_readiness_probe_table)
    except Exception as _probe_err:
        # Kein Fail-Fast: /readyz meldet den Fehler ueber _readiness_sync_checks.
        logger.warning(f"[Lifespan] Readiness-Probe-Tabelle nicht anlegbar: {_probe_err}")

    for hook in list(startup_hooks):
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
            # Scheitern muss den Start abbrechen (sonst 404 bei healthy /health).
            if name in fail_fast_hooks:
                logger.error(f"[Lifespan] KRITISCH: {e}")
                raise
            logger.warning(f"[Lifespan] Startup-Hook '{name}' fehlgeschlagen: {e}")

    try:
        yield
    finally:
        # D07-M7: ein haengender Hook darf den Prozess nicht unbegrenzt
        # blockieren. Ein einziges Budget gilt fuer ALLE Hooks; der
        # Liveness-Stop laeuft in einem inneren finally immer weiter.
        _deadline = time.monotonic() + _SHUTDOWN_BUDGET_SECONDS
        try:
            for hook in reversed(list(shutdown_hooks)):
                name = getattr(hook, "__name__", repr(hook))
                _started = time.monotonic()
                _remaining = _deadline - time.monotonic()
                if _remaining <= 0:
                    logger.error(f"[Lifespan] Shutdown-Budget erschöpft — Hook '{name}' übersprungen")
                    _audit_shutdown_hook(name, "budget_exhausted", 0.0)
                    continue
                try:
                    if asyncio.iscoroutinefunction(hook):
                        _awaited = hook()
                    else:

                        def _invoke() -> Any:
                            result = hook()
                            return result if asyncio.iscoroutine(result) else None

                        _awaited = asyncio.to_thread(_invoke)
                    await asyncio.wait_for(_awaited, timeout=_remaining)
                    _audit_shutdown_hook(
                        name, "ok", (time.monotonic() - _started) * 1000.0
                    )
                except Exception as e:
                    _duration_ms = (time.monotonic() - _started) * 1000.0
                    logger.error(f"[Lifespan] Shutdown-Hook '{name}' fehlgeschlagen: {e}")
                    _audit_shutdown_hook(
                        name, f"failed: {type(e).__name__}", _duration_ms
                    )
        finally:
            if stop_loop_heartbeat is not None:
                try:
                    # Der Stop darf NIE entfallen (finally immer ausfuehren).
                    # Ist das Hook-Budget aufgebraucht, bekommt er eine kleine
                    # eigene Restfrist statt still übersprungen zu werden.
                    _remaining = max(0.05, _deadline - time.monotonic())
                    await asyncio.wait_for(stop_loop_heartbeat(), timeout=_remaining)
                except Exception as _ll_stop_err:
                    logger.warning(f"[Lifespan] Loop-Liveness-Stop fehlgeschlagen: {_ll_stop_err}")

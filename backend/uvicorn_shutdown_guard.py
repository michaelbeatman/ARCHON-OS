"""Begrenzt uvicorns Graceful-Shutdown.

Problem: `uvicorn --reload` wartet beim Code-Wechsel unbegrenzt auf offene
Connections/Streams ("Waiting for connections to close"), weil
`timeout_graceful_shutdown` standardmäßig None ist. Jede Dateiänderung friert
den Server dadurch dauerhaft ein.

Dieses Modul patcht `Server._wait_tasks_to_complete` beim Import: nach
`SHUTDOWN_GRACE_SECONDS` wird `force_exit` gesetzt, uvicorn bricht die
Warteschleife ab und führt anschließend den Lifespan-Shutdown aus (der unsere
Hintergrund-Tasks abbricht).

Der Patch ist idempotent und greift nur, wenn uvicorn geladen ist.

D10-M7: zusaetzlich wird ``Server.shutdown`` (Connection-Drain + Lifespan)
begrenzt. Der Lifespan selbst hat sein eigenes 10-s-Budget in
``archon.services.lifecycle``; dieser Patch ist nur der letzte Rueckhalt,
damit ein haengender Shutdown den Container nicht unbegrenzt festhaelt.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("archon.shutdown_guard")

SHUTDOWN_GRACE_SECONDS = 5.0
# 5 s Connection-Drain + 10 s Lifespan-Budget (lifecycle._SHUTDOWN_BUDGET_SECONDS).
LIFESPAN_BUDGET_SECONDS = 10.0
TOTAL_SHUTDOWN_BUDGET_SECONDS = SHUTDOWN_GRACE_SECONDS + LIFESPAN_BUDGET_SECONDS


def install() -> bool:
    try:
        import uvicorn.server as uv_server
    except Exception:
        return False

    server_cls = uv_server.Server
    if getattr(server_cls, "_archon_shutdown_patched", False):
        return True

    original = server_cls._wait_tasks_to_complete

    async def _wait_bounded(self):
        try:
            await asyncio.wait_for(original(self), timeout=SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:
            pending = len(getattr(self.server_state, "connections", []) or []) + len(
                getattr(self.server_state, "tasks", []) or []
            )
            logger.warning(
                "[shutdown_guard] Graceful Shutdown nach %.0fs abgebrochen (%d offene Verbindung/Task).",
                SHUTDOWN_GRACE_SECONDS,
                pending,
            )
            self.force_exit = True

    setattr(server_cls, "_wait_tasks_to_complete", _wait_bounded)
    setattr(server_cls, "_archon_shutdown_patched", True)

    if not getattr(server_cls, "_archon_total_shutdown_patched", False):
        original_shutdown = server_cls.shutdown

        async def _shutdown_bounded(self):
            try:
                await asyncio.wait_for(
                    original_shutdown(self), timeout=TOTAL_SHUTDOWN_BUDGET_SECONDS
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[shutdown_guard] Gesamt-Shutdown nach %.0fs abgebrochen.",
                    TOTAL_SHUTDOWN_BUDGET_SECONDS,
                )
                self.force_exit = True

        setattr(server_cls, "shutdown", _shutdown_bounded)
        setattr(server_cls, "_archon_total_shutdown_patched", True)

    logger.info(
        "[shutdown_guard] aktiv (drain=%.0fs, gesamt=%.0fs)",
        SHUTDOWN_GRACE_SECONDS,
        TOTAL_SHUTDOWN_BUDGET_SECONDS,
    )
    return True

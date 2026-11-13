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
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("archon.shutdown_guard")

SHUTDOWN_GRACE_SECONDS = 5.0


def install() -> bool:
    try:
        import uvicorn.server as uv_server  # type: ignore
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

    server_cls._wait_tasks_to_complete = _wait_bounded
    setattr(server_cls, "_archon_shutdown_patched", True)
    logger.info("[shutdown_guard] aktiv (grace=%.0fs)", SHUTDOWN_GRACE_SECONDS)
    return True

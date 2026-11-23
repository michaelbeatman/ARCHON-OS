"""Zentrale Registry für Fire-and-Forget-Coroutines.

Problem: ``asyncio.create_task(...)`` ohne Referenz. Der Event Loop haelt nur
Weak References; Tasks koennen vor oder waehrend der Ausführung
garbage-collected werden, und Exceptions bleiben unbeobachtet. In Archon
betraf das Sandy-Staffing, den Fan-In und die komplette Synthese-Kaskade —
Projekte blieben dauerhaft im Zustand "alle Ergebnisse da, Synthese nie
gestartet".

Dieses Modul ist bewusst zyklenfrei (kein Import aus main.py), damit es aus
archon.core.orchestration und archon.routers.* genutzt werden kann.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Coroutine, Dict, List, Optional

logger = logging.getLogger("archon_os.tasks")

_TASKS: Dict[asyncio.Task, str] = {}


def spawn(coro: Coroutine, name: str = "") -> asyncio.Task:
    """Startet eine Coroutine mit stabiler Referenz und Exception-Logging."""
    task = asyncio.create_task(coro, name=name or None)

    def _done(done: asyncio.Task) -> None:
        _TASKS.pop(done, None)
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.error(
                "[TaskRegistry] Unhandled exception in '%s': %s",
                name or done.get_name(), exc, exc_info=exc,
            )

    _TASKS[task] = name or task.get_name()
    task.add_done_callback(_done)
    return task


def pending() -> List[str]:
    return [name for task, name in _TASKS.items() if not task.done()]


async def cancel_all() -> int:
    """Bricht alle registrierten Tasks ab (Shutdown).

    Audit 23.11.2026: begrenztes Warten, sonst kann ein Task, der Cancellation
    ignoriert, den Shutdown beliebig lange blockieren.
    """
    tasks = [t for t in list(_TASKS) if not t.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[TaskRegistry] %s Task(s) haben Cancellation nicht innerhalb "
                "von 10 s beendet — Shutdown fährt fort.", len(tasks),
            )
    for task in tasks:
        _TASKS.pop(task, None)
    return len(tasks)


def get(name: str) -> Optional[asyncio.Task]:
    for task, task_name in _TASKS.items():
        if task_name == name and not task.done():
            return task
    return None

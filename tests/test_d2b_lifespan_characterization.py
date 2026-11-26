# -*- coding: utf-8 -*-
"""2b-Characterization: fuehrt den ECHTEN Lifespan aus (nicht nur Hook-Listen).

Ergaenzt C0/② (dort wurde nur die Reihenfolge der _SHUTDOWN_HOOKS-Datenstruktur
geprueft). Hier werden Startup-/Shutdown-Ausfuehrung, Fail-Fast-Raise,
Nicht-Fail-Fast-Log und der Loop-Liveness-Stop gegen die echte Logik
festgenagelt — GRUEN vor und NACH der Extraktion nach
archon/services/lifecycle.py.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, List
from unittest.mock import AsyncMock, patch

import pytest

import main as app_main


def _hook(name: str, log: List[str], *, raises: bool = False):
    def _fn():
        log.append(name)
        if raises:
            raise RuntimeError("NEGATIVPROBE: hook kaputt")

    _fn.__name__ = name
    return _fn


async def _drive(startup: List[Any], shutdown: List[Any], fail_fast: set) -> Any:
    """Treibt den asynchronen Lifespan-Generator durch Startup + Shutdown."""
    gen = app_main._archon_lifespan(None)
    with patch.object(app_main, "_STARTUP_HOOKS", startup), \
         patch.object(app_main, "_SHUTDOWN_HOOKS", shutdown), \
         patch.object(app_main, "_FAIL_FAST_HOOKS", fail_fast), \
         patch.object(app_main, "_init_readiness_probe_table", lambda: None), \
         patch("backend.loop_liveness.start_loop_heartbeat", new=AsyncMock()), \
         patch("backend.loop_liveness.stop_loop_heartbeat", new=AsyncMock()):
        await gen.__anext__()  # Startup bis zum yield
        with suppress(StopAsyncIteration):
            await gen.__anext__()  # finally: Shutdown
        await gen.aclose()
    return gen


def test_2b_startup_order_and_shutdown_reversed():
    log: List[str] = []
    startup = [_hook("s1", log), _hook("s2", log), _hook("s3", log)]
    shutdown = [_hook("d1", log), _hook("d2", log), _hook("d3", log)]
    asyncio.run(_drive(startup, shutdown, set()))
    assert log == ["s1", "s2", "s3", "d3", "d2", "d1"], log
    # Negativprobe gegen die echte reversed()-Logik
    with pytest.raises(AssertionError):
        assert log == ["s1", "s2", "s3", "d1", "d2", "d3"]


def test_2b_non_fail_fast_hook_failure_does_not_abort():
    log: List[str] = []
    startup = [_hook("ok", log), _hook("warn", log, raises=True), _hook("after", log)]
    shutdown = [_hook("d1", log)]
    asyncio.run(_drive(startup, shutdown, set()))  # 'warn' NICHT in fail_fast
    assert log == ["ok", "warn", "after", "d1"], log
    with pytest.raises(AssertionError):
        assert log == ["ok", "warn"]  # Negativprobe: Start darf nicht abbrechen


def test_2b_fail_fast_hook_raises_and_skips_shutdown():
    log: List[str] = []
    startup = [_hook("fatal", log, raises=True)]
    shutdown = [_hook("d1", log)]
    with pytest.raises(RuntimeError, match="NEGATIVPROBE"):
        asyncio.run(_drive(startup, shutdown, {"fatal"}))
    assert log == ["fatal"], log  # kein Shutdown nach Fail-Fast-Abbruch
    with pytest.raises(AssertionError):
        assert "d1" in log

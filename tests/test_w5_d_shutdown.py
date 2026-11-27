# -*- coding: utf-8 -*-
"""W5-D — Regressionstests fuer D10-M7 (Shutdown-Budget/-Reihenfolge).

Produktivpfad (§0): Lifespan -> Shutdown-Hooks -> Audit/Cancel-Spiegel ->
Uvicorn-Gesamtbudget; Graceful-Shutdown-Coordinator -> Drain -> Phasen ->
Audit. Kein PostgreSQL/DSN/Migration, kein Coroutine-Replay, keine fremden
Dateien, keine Secrets. DB-Isolation wie ueblich ueber conftest.py.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _audit_sink(events: list[dict]) -> Callable[..., dict]:
    """Zeichnet signierte Pflicht-Events auf statt die echte Audit-DB zu schreiben."""

    def _record(**kwargs: object) -> dict:
        events.append(kwargs)
        return {}

    return _record


def _named_hook(name: str, order: list[str]) -> Any:
    async def _hook() -> None:
        order.append(name)

    _hook.__name__ = name
    return _hook


# ---------------------------------------------------------------------------
# D10-M7 / D07-M7 — Lifespan: Gesamtbudget, Einzelfenster, cancel_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_shutdown_timeout_is_bounded_and_audited(monkeypatch):
    import backend.audit_log as audit_log
    import backend.loop_liveness as liveness
    from archon.services import lifecycle as lc
    from archon.services.background_loops import _FAILED_CANCELS

    events: list[dict] = []
    monkeypatch.setattr(audit_log, "_require_audit_event", _audit_sink(events))
    monkeypatch.setattr(lc, "_SHUTDOWN_BUDGET_SECONDS", 0.20)
    monkeypatch.setattr(lc, "_HOOK_TIMEOUT_SECONDS", 0.10)
    start_mock = AsyncMock()
    stop_mock = AsyncMock()
    monkeypatch.setattr(liveness, "start_loop_heartbeat", start_mock)
    monkeypatch.setattr(liveness, "stop_loop_heartbeat", stop_mock)

    order: list[str] = []

    async def _hang():
        order.append("hang")
        await asyncio.sleep(5)

    _hang.__name__ = "hang"

    before = len(_FAILED_CANCELS)
    try:
        loop = asyncio.get_running_loop()
        async with lc.lifespan_context(
            startup_hooks=[],
            shutdown_hooks=[_hang, _named_hook("fast_1", order), _hang],
            fail_fast_hooks=set(),
            init_readiness_probe_table=lambda: None,
        ):
            started = loop.time()
        elapsed = loop.time() - started

        # Zwei haengende Hooks je 0.10 s + Restfrist fuer den Liveness-Stop.
        assert elapsed < 1.0, f"Shutdown blockierte {elapsed:.2f}s"
        assert order.count("fast_1") == 1 and order.count("hang") == 2, order
        # Inneres finally aus D07-M7 muss weiterhin immer greifen.
        stop_mock.assert_awaited_once()

        hook_events = [e for e in events if e.get("action") == "shutdown_hook"]
        hang_events = [e for e in hook_events if e["payload"]["hook"] == "hang"]
        assert len(hang_events) == 2, hook_events
        assert all(
            "failed: TimeoutError" == e["payload"]["status"] for e in hang_events
        ), hook_events
        cancel_events = [e for e in events if e.get("action") == "cancel_failed"]
        assert len(cancel_events) == 2, events
        assert all(
            e["payload"]["task"] == "shutdown_hook:hang" for e in cancel_events
        ), cancel_events
        assert len(_FAILED_CANCELS) == before + 2, _FAILED_CANCELS[-3:]
    finally:
        # /readyz konsumiert _FAILED_CANCELS — keine Testreste hinterlassen.
        del _FAILED_CANCELS[before:]


@pytest.mark.asyncio
async def test_lifecycle_stops_loops_before_closing_http_pools(monkeypatch):
    """Die Produktiv-Hook-Namen aus main.py müssen Loops vor Pools stoppen."""
    import backend.audit_log as audit_log
    import backend.loop_liveness as liveness
    from archon.services import lifecycle as lc

    monkeypatch.setattr(
        audit_log, "_require_audit_event", _audit_sink([])
    )
    monkeypatch.setattr(liveness, "start_loop_heartbeat", AsyncMock())
    monkeypatch.setattr(liveness, "stop_loop_heartbeat", AsyncMock())

    order: list[str] = []
    # Registrierungsreihenfolge wie in main.py::_SHUTDOWN_HOOKS.
    hooks = [
        _named_hook("_close_dispatcher_clients", order),
        _named_hook("_close_proxy_clients", order),
        _named_hook("_cancel_tracked_tasks", order),
        _named_hook("_stop_watchdog_daemon", order),
        _named_hook("_cancel_background_tasks", order),
        _named_hook("_close_all_http_clients", order),
        _named_hook("on_shutdown_graceful", order),
    ]

    async with lc.lifespan_context(
        startup_hooks=[],
        shutdown_hooks=hooks,
        fail_fast_hooks=set(),
        init_readiness_probe_table=lambda: None,
    ):
        pass

    assert order[0] == "on_shutdown_graceful", order
    assert order.index("_cancel_background_tasks") < order.index(
        "_close_all_http_clients"
    ), order
    assert order.index("_cancel_background_tasks") < order.index(
        "_close_dispatcher_clients"
    ), order


# ---------------------------------------------------------------------------
# D10-M7 — Graceful-Shutdown-Coordinator: Drain <= 5 s, Phasen begrenzt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_shutdown_clamps_drain_and_bounds_phases(monkeypatch):
    import backend.audit_log as audit_log
    import backend.graceful_shutdown_coordinator as gs

    events: list[dict] = []

    def _record(**kwargs: object) -> dict:
        events.append(kwargs)
        return {}

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _record)
    monkeypatch.setattr(gs, "_SHUTDOWN_PHASE_TIMEOUT_SECONDS", 0.05)

    coord = gs.GracefulShutdownCoordinator()
    assert coord._default_grace_seconds <= gs._MAX_DRAIN_GRACE_SECONDS

    def _slow_checkpoint():
        time.sleep(0.3)  # haengender Worker-Thread darf den Shutdown nicht halten
        return []

    monkeypatch.setattr(coord, "checkpoint_remaining_tasks", _slow_checkpoint)
    monkeypatch.setattr(
        coord, "flush_all_databases",
        lambda: {"status": "success", "flushed_databases": [], "errors": []},
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await coord.execute_graceful_shutdown(
        reason="W5-D-Test", grace_seconds=60.0
    )
    elapsed = loop.time() - started

    assert elapsed < 1.0, f"Graceful Shutdown blockierte {elapsed:.2f}s"
    assert coord._default_grace_seconds <= gs._MAX_DRAIN_GRACE_SECONDS
    assert result["checkpoints_created"] == [], result
    assert result["wal_flush"]["status"] == "success", result
    actions = [e.get("action") for e in events]
    assert "shutdown_phase_timeout" in actions, events
    assert any(e.get("payload", {}).get("phase") == "checkpoint" for e in events), events


# ---------------------------------------------------------------------------
# D10-M7 — Uvicorn-Guard: Connection-Drain UND Gesamt-Shutdown begrenzt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uvicorn_guard_bounds_connection_drain_and_total_shutdown(monkeypatch):
    from backend import uvicorn_shutdown_guard as guard

    class _FakeServer:
        def __init__(self):
            self.force_exit = False
            self.server_state = types.SimpleNamespace(connections=[1], tasks=[1])

        async def _wait_tasks_to_complete(self):
            await asyncio.sleep(10)

        async def shutdown(self):
            await asyncio.sleep(10)

    fake_module = types.ModuleType("uvicorn.server")
    setattr(fake_module, "Server", _FakeServer)
    fake_parent = types.ModuleType("uvicorn")
    setattr(fake_parent, "server", fake_module)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_parent)
    monkeypatch.setitem(sys.modules, "uvicorn.server", fake_module)
    monkeypatch.setattr(guard, "SHUTDOWN_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(guard, "TOTAL_SHUTDOWN_BUDGET_SECONDS", 0.10)

    assert guard.install() is True
    assert guard.install() is True, "Patch muss idempotent sein"

    conn_server = _FakeServer()
    await asyncio.wait_for(conn_server._wait_tasks_to_complete(), timeout=1.0)
    assert conn_server.force_exit is True

    total_server = _FakeServer()
    await asyncio.wait_for(total_server.shutdown(), timeout=1.0)
    assert total_server.force_exit is True

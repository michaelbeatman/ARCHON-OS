"""F32 (D08): /livez watchdog_liveness und Shutdown stop_anchor_worker in asyncio.to_thread."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi.responses import JSONResponse


def test_f32_livez_watchdog_liveness_is_non_blocking_and_returns_503(monkeypatch):
    """Langsame Watchdog-Liveness-Datei blockiert Event-Loop nicht; alive=False bleibt 503."""
    import archon.services.health_probes as hp
    import backend.loop_liveness as ll
    import watchdog_daemon

    async def _healthy_loop():
        return {"alive": True, "lag_ms": 0.5}

    def _slow_dead_watchdog():
        time.sleep(0.25)
        return {"alive": False, "last_seen": 100.0, "age_s": 500.0}

    monkeypatch.setattr(ll, "check_loop_liveness", _healthy_loop)
    monkeypatch.setattr(watchdog_daemon, "watchdog_liveness", _slow_dead_watchdog)

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        res, _ = await asyncio.gather(hp.run_liveness_check(), _heartbeat())
        assert isinstance(res, JSONResponse)
        assert res.status_code == 503
        body = json.loads(res.body.decode("utf-8"))
        assert body["loops"]["watchdog"]["alive"] is False
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

    asyncio.run(_run())


def test_f32_shutdown_stop_anchor_worker_is_non_blocking_and_preserves_order(monkeypatch):
    """stop_anchor_worker laeuft in to_thread und vor execute_graceful_shutdown."""
    import archon.services.runtime_endpoints as re_mod
    from backend.audit_log import chained_audit_log
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

    order = []

    def _slow_stop_anchor():
        time.sleep(0.25)
        order.append("stop_anchor_worker")

    async def _fake_graceful_shutdown(reason: str = ""):
        order.append("execute_graceful_shutdown")
        return {"status": "shutdown_ready", "reason": reason}

    monkeypatch.setattr(chained_audit_log, "stop_anchor_worker", _slow_stop_anchor)
    monkeypatch.setattr(
        graceful_shutdown_coordinator, "execute_graceful_shutdown", _fake_graceful_shutdown
    )

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        await asyncio.gather(re_mod.on_shutdown_graceful(), _heartbeat())
        assert order == ["stop_anchor_worker", "execute_graceful_shutdown"]
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

    asyncio.run(_run())

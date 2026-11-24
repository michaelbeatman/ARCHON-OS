# -*- coding: utf-8 -*-
"""
Loop-Liveness Tests fuer `/livez` (backend/loop_liveness.py + main.py).
"""
import asyncio
import pytest


def test_loop_liveness_monitor_healthy_stale_lag_and_crashed_task():
    from backend.loop_liveness import LoopLivenessMonitor

    async def _run():
        mon = LoopLivenessMonitor(interval_s=0.05)
        mon.start()
        try:
            await asyncio.sleep(0.12)
            ok = await mon.check(max_heartbeat_age_s=2.0, max_loop_lag_ms=2000.0)
            assert ok["alive"] is True
            assert ok["status"] == "alive"
            assert ok["heartbeat_started"] is True
            assert ok["tick_count"] >= 1
            assert ok["reason"] is None

            # Simuliere stale heartbeat (Event-Loop hing)
            mon._last_tick_mono -= 30.0
            stale = await mon.check(max_heartbeat_age_s=5.0, max_loop_lag_ms=2000.0)
            assert stale["alive"] is False
            assert stale["status"] == "unhealthy"
            assert str(stale["reason"]).startswith("heartbeat_stale:")

            # Simuliere zu hohen Loop-Lag
            mon._last_tick_mono = asyncio.get_running_loop().time()
            mon._last_lag_ms = 6500.0
            lagged = await mon.check(max_heartbeat_age_s=5.0, max_loop_lag_ms=5000.0)
            assert lagged["alive"] is False
            assert str(lagged["reason"]).startswith("loop_lag_exceeded:")
        finally:
            await mon.stop()

    asyncio.run(_run())


def test_livez_endpoint_returns_200_with_lifespan_and_503_when_unhealthy(monkeypatch):
    from fastapi.testclient import TestClient
    import main as app_main
    from backend import loop_liveness as ll

    ll.loop_liveness_monitor.reset()
    with TestClient(app_main.app) as client:
        r_ok = client.get("/livez")
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["status"] == "alive"
        assert body["heartbeat_started"] is True
        assert "heartbeat_age_s" in body
        assert "loop_lag_ms" in body

        async def _fake_unhealthy():
            return {
                "alive": False,
                "status": "unhealthy",
                "mode": "heartbeat",
                "heartbeat_started": True,
                "heartbeat_age_s": 24.5,
                "loop_lag_ms": 6200.0,
                "reason": "heartbeat_stale: 24.5s > 15.0s",
            }

        monkeypatch.setattr(ll, "check_loop_liveness", _fake_unhealthy)
        r_bad = client.get("/livez")
        assert r_bad.status_code == 503
        assert r_bad.json()["alive"] is False
        assert "heartbeat_stale" in r_bad.json()["reason"]
    ll.loop_liveness_monitor.reset()

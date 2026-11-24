# -*- coding: utf-8 -*-
"""
Loop-Liveness Tests fuer `/livez` (backend/loop_liveness.py + main.py).
"""
import asyncio
import time
from pathlib import Path

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


def test_default_thresholds_match_docker_healthcheck():
    """Audit E2E: /livez muss vor dem 3-s-Healthcheck-Timeout auf 503 gehen."""
    from backend.loop_liveness import (
        DEFAULT_MAX_HEARTBEAT_AGE_S, DEFAULT_MAX_LOOP_LAG_MS, DEFAULT_INTERVAL_S,
    )

    assert 0 < DEFAULT_MAX_HEARTBEAT_AGE_S <= 8.0
    assert 0 < DEFAULT_MAX_LOOP_LAG_MS <= 2000.0
    assert DEFAULT_INTERVAL_S < DEFAULT_MAX_HEARTBEAT_AGE_S


def test_compose_wires_livez_healthcheck_and_external_autoheal():
    """Damit aus einem 503 wieder ein Neustart wird (Docker restartet nur bei Exit)."""
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "urlopen('http://localhost:8501/livez'" in compose
    assert "archon-autoheal:" in compose
    assert "ALLOW_START=1" in compose and "ALLOW_STOP=1" in compose
    assert "ARCHON_LIVEZ_MAX_HEARTBEAT_AGE_S" in compose
    assert "ARCHON_LIVEZ_MAX_LOOP_LAG_MS" in compose
    assert "ARCHON_HEARTBEAT_ALERTMANAGER_URL" in compose
    assert (root / "scripts" / "archon_autoheal.py").is_file()


def test_livez_returns_503_during_real_event_loop_blockade(monkeypatch):
    """Kontrollierte echte Blockade (kein Fake) im separaten Test-Event-Loop."""
    from fastapi.testclient import TestClient
    import main as app_main
    from backend import loop_liveness as ll

    ll.loop_liveness_monitor.reset()

    try:
        with TestClient(app_main.app) as client:
            assert client.get("/livez").status_code == 200

            # Sensible Schwellen ERST nach dem Baseline-Check setzen: der
            # App-Startup darf die enge 1-s-Grenze nicht schon verbrauchen.
            monkeypatch.setenv("ARCHON_LIVEZ_MAX_HEARTBEAT_AGE_S", "1.0")
            monkeypatch.setenv("ARCHON_LIVEZ_MAX_LOOP_LAG_MS", "300")

            async def _get_loop():
                return asyncio.get_running_loop()

            portal = getattr(client, "portal", None) or client._portal
            loop = portal.call(_get_loop)

            async def _block(seconds):
                started = time.monotonic()
                time.sleep(seconds)  # absichtlich blockierend
                return time.monotonic() - started

            future = asyncio.run_coroutine_threadsafe(_block(3.0), loop)
            time.sleep(0.3)
            blocked = client.get("/livez", timeout=15)
            assert blocked.status_code == 503
            assert blocked.json()["alive"] is False
            assert blocked.json()["reason"]
            assert round(future.result(timeout=10), 1) >= 2.9

            monkeypatch.delenv("ARCHON_LIVEZ_MAX_HEARTBEAT_AGE_S")
            monkeypatch.delenv("ARCHON_LIVEZ_MAX_LOOP_LAG_MS")
            time.sleep(2.5)
            assert client.get("/livez").status_code == 200
    finally:
        ll.loop_liveness_monitor.reset()

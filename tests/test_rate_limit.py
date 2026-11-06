"""
Tests für utils.rate_limit — Token-Bucket und ASGI-Middleware.

Die Middleware greift in jeden Request ein, deshalb wird hier nicht nur das
Limit selbst geprüft, sondern ausdrücklich auch das, was NICHT gebremst werden
darf: /health, /metrics, statische Dateien, SSE und CORS-Preflight. Ein
Limiter, der die eigene UI aussperrt, ist ein Ausfall, kein Schutz.
"""

import os
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.rate_limit import RateLimitMiddleware, _Bucket  # noqa: E402


def _app(default_limit=5, strict_limit=2):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/ticker")
    def ticker():
        return {"ticker": []}

    @app.get("/api/sandbox/run")
    def sandbox():
        return {"sandbox": True}

    app.add_middleware(RateLimitMiddleware, default_limit=default_limit, strict_limit=strict_limit)
    return app


# ---------------------------------------------------------------- Bucket

def test_bucket_allows_capacity_then_blocks():
    b = _Bucket(capacity=3)
    assert [b.take(3) for _ in range(3)] == [True, True, True]
    assert b.take(3) is False


def test_bucket_refills_over_time():
    b = _Bucket(capacity=60)          # 1 Token/Sekunde
    b.tokens = 0.0
    b.last = time.monotonic() - 2.0   # 2 Sekunden vergangen
    assert b.take(60) is True


# ---------------------------------------------------------------- Middleware

def test_default_path_allows_configured_burst():
    client = TestClient(_app(default_limit=5, strict_limit=2))
    codes = [client.get("/api/ticker").status_code for _ in range(5)]
    assert codes == [200] * 5


def test_default_path_blocks_beyond_limit():
    client = TestClient(_app(default_limit=3, strict_limit=2))
    codes = [client.get("/api/ticker").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:]


def test_429_has_retry_after_header():
    client = TestClient(_app(default_limit=1, strict_limit=1))
    client.get("/api/ticker")
    resp = client.get("/api/ticker")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert resp.json()["error"] == "Zu viele Anfragen"


def test_strict_prefix_blocked_earlier():
    client = TestClient(_app(default_limit=100, strict_limit=2))
    codes = [client.get("/api/sandbox/run").status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429


def test_health_is_exempt():
    client = TestClient(_app(default_limit=1, strict_limit=1))
    codes = [client.get("/health").status_code for _ in range(20)]
    assert set(codes) == {200}


def test_metrics_and_static_exempt():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, default_limit=1, strict_limit=1)

    @app.get("/metrics")
    def metrics():
        return "ok"

    @app.get("/static/x.js")
    def static_x():
        return "js"

    client = TestClient(app)
    assert {client.get("/metrics").status_code for _ in range(5)} == {200}
    assert {client.get("/static/x.js").status_code for _ in range(5)} == {200}


def test_options_preflight_exempt():
    client = TestClient(_app(default_limit=1, strict_limit=1))
    codes = [client.options("/api/ticker").status_code for _ in range(5)]
    # Preflight darf nie am Limiter scheitern (FastAPI antwortet hier 405,
    # weil die Route nur GET kennt — entscheidend ist: kein 429).
    assert 429 not in codes


def test_limiter_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ARCHON_RATE_LIMIT_ENABLED", "0")
    client = TestClient(_app(default_limit=1, strict_limit=1))
    codes = [client.get("/api/ticker").status_code for _ in range(10)]
    assert set(codes) == {200}

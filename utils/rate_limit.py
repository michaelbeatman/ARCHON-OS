"""
Rate-Limiting als ASGI-Middleware (In-Memory, Token-Bucket).

Ausgangslage: 200+ Endpunkte ohne jede Bremse — darunter teure und gefährliche
Ziele wie `/api/sandbox`, `/api/v1/container/exec`, die Update-Endpunkte und die
Proxy-Pfade. Ein einzelner Client konnte den Stack mit wenigen hundert
Requests/s ausbremsen.

Bewusste Entscheidungen:

* **Kein neues Paket.** `slowapi`/`limits` sind nicht installiert und ein
  Paket-Nachinstallieren in einem live laufenden Container ist ein eigenes
  Risiko. Der Bucket ist ~60 Zeilen und reicht für einen Single-Host-Deployment.
* **Kein neuer Endpunkt.** Routen-Parität (585 Pfade / 861 Operationen) bleibt
  unangetastet; alles passiert in der Middleware.
* **Zwei Klassen statt eines Limits.** Die UI pollt legitim alle 10–30 s; ein
  pauschales hartes Limit würde das Dashboard treffen. Deshalb ein großzügiges
  Standardlimit und ein enges Limit für teure/gefährliche Pfade.
* **Ausnahmen.** `/health` (Liveness, muss immer antworten), `/metrics`,
  statische Dateien, SSE-Stream und die OpenAPI-Dokumente.

Konfiguration über Umgebung:
  ARCHON_RATE_LIMIT_ENABLED=0        schaltet den Limiter ab (Notaus)
  ARCHON_RATE_LIMIT_DEFAULT=600      Requests/Minute pro Client (Standard)
  ARCHON_RATE_LIMIT_STRICT=20        Requests/Minute für STRICT_PREFIXES
  ARCHON_RATE_LIMIT_TRUST_FORWARDED=1  X-Forwarded-For auswerten (nur hinter Proxy)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from archon.core.config import config

__all__ = ["RateLimitMiddleware", "STRICT_PREFIXES", "EXEMPT_PREFIXES"]

# Teure oder gefaehrliche Ziele: enges Limit.
STRICT_PREFIXES: Tuple[str, ...] = (
    "/api/sandbox",
    "/api/v1/container/exec",
    "/api/hermes/update",
    "/api/system/update",
    "/api/proxy",
    "/api/router/hedged",
    "/api/auth",
    "/api/healing/attempt",
    "/api/fleet/heal",
    "/api/documents/parse",
    "/api/llm-providers/test-connection",
    "/api/v1/library/upload",
)

# Muss immer antworten bzw. wird nicht als "Nutzung" gezaehlt.
EXEMPT_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/metrics",
    "/static/",
    "/favicon",
    "/docs",
    "/openapi.json",
    "/api/v1/events/stream",
)

_PRIVATE_PREFIXES = ("127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.",
                     "172.19.", "172.2", "172.30.", "172.31.", "::1", "localhost")


def _env_int(name: str, default: int) -> int:
    return config.rate_limit_value(name, default)


def _enabled() -> bool:
    return config.rate_limit_enabled


def _trust_forwarded() -> bool:
    return config.rate_limit_trust_forwarded


class _Bucket:
    """Token-Bucket: capacity = Limit pro Minute, Nachfuellung gleichmaessig."""

    __slots__ = ("tokens", "last")

    def __init__(self, capacity: int) -> None:
        self.tokens = float(capacity)
        self.last = time.monotonic()

    def take(self, capacity: int) -> bool:
        now = time.monotonic()
        rate = capacity / 60.0  # Tokens pro Sekunde
        self.tokens = min(float(capacity), self.tokens + (now - self.last) * rate)
        self.last = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, default_limit: Optional[int] = None,
                 strict_limit: Optional[int] = None) -> None:
        super().__init__(app)
        self.default_limit = default_limit or _env_int("ARCHON_RATE_LIMIT_DEFAULT", 600)
        self.strict_limit = strict_limit or _env_int("ARCHON_RATE_LIMIT_STRICT", 20)
        self._buckets: Dict[Tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()
        self._blocked_log: Dict[str, float] = {}

    # ---------------- intern ----------------

    @staticmethod
    def _exempt(path: str) -> bool:
        return any(path == p or path.startswith(p) for p in EXEMPT_PREFIXES)

    @staticmethod
    def _strict(path: str) -> bool:
        return any(path.startswith(p) for p in STRICT_PREFIXES)

    @staticmethod
    def _client_key(request: Request) -> str:
        client = request.client.host if request.client else "unknown"
        if _trust_forwarded():
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded and any(client.startswith(p) for p in _PRIVATE_PREFIXES):
                return forwarded.split(",")[0].strip()
        return client

    def _prune(self) -> None:
        """Entfernt leere Buckets, damit der Speicher nicht monoton waechst."""
        now = time.monotonic()
        if now - self._last_prune < 300:
            return
        self._last_prune = now
        stale = [k for k, b in self._buckets.items() if now - b.last > 600]
        for k in stale:
            self._buckets.pop(k, None)
        if len(self._blocked_log) > 1000:
            self._blocked_log.clear()

    def _log_block(self, key: str, path: str) -> None:
        """Ein Log-Eintrag pro Client und Minute statt pro Request."""
        now = time.monotonic()
        if now - self._blocked_log.get(key, 0.0) < 60:
            return
        self._blocked_log[key] = now
        print(f"[RateLimit] 429 fuer {key} auf {path}", flush=True)

    # ---------------- ASGI ----------------

    async def dispatch(self, request: Request, call_next):
        if not _enabled():
            return await call_next(request)

        path = request.url.path
        if request.method == "OPTIONS" or self._exempt(path):
            return await call_next(request)

        strict = self._strict(path)
        limit = self.strict_limit if strict else self.default_limit
        bucket_key = (self._client_key(request), "strict" if strict else "default")

        with self._lock:
            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _Bucket(limit)
                self._buckets[bucket_key] = bucket
            allowed = bucket.take(limit)
            self._prune()

        if not allowed:
            self._log_block(bucket_key[0], path)
            retry_after = max(1, int(60 / limit))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Zu viele Anfragen",
                    "detail": f"Limit: {limit} Anfragen/Minute auf diesem Pfad",
                    "retry_after_s": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

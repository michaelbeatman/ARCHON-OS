"""Kleiner TTL-Cache für teure Lese-Endpunkte.

Motivation: mehrere GET-Endpunkte (Fleet-Health, Vault-Scans, Health-Score)
haben bei jedem Poll neu gerechnet bzw. `docker ps` / Verzeichnis-Walks
ausgeführt — gemessen 1,0–3,5 s pro Aufruf. Ein kurzer TTL-Cache macht sie
billig, ohne die Aussagekraft zu verlieren.

Bewusst schlicht (thread-safe, prozesslokal, keine Abhängigkeiten):
    @ttl_cache(seconds=30)
    def expensive(): ...
"""

from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable, Dict, Tuple

__all__ = ["ttl_cache", "invalidate", "clear_all"]

_LOCK = threading.Lock()
# (created_at, expires_at, value) — pro Eintrag, nicht pro Decorator.
_STORE: Dict[str, Tuple[float, float, Any]] = {}
_INFLIGHT: Dict[str, threading.Event] = {}


def _tenant_prefix() -> str:
    """C4: Cache-Keys mandanten-scopen (Request-Kontext, sonst 'default')."""
    try:
        from backend.tenant_context import _REQUEST_TENANT_VAR
        tenant = _REQUEST_TENANT_VAR.get()
    except Exception:
        tenant = None
    return f"{tenant or 'default'}"


def _key(fn: Callable, args: tuple, kwargs: dict) -> str:
    prefix = _tenant_prefix()
    try:
        return f"{prefix}|{fn.__module__}.{fn.__qualname__}|{args!r}|{sorted(kwargs.items())!r}"
    except Exception:
        return f"{prefix}|{fn.__module__}.{fn.__qualname__}|fallback|{id(args)}|{id(kwargs)}"


def ttl_cache(seconds: float = 30.0, maxsize: int = 256):
    """Cached das Ergebnis für `seconds` (max `maxsize` Einträge).

    Der globale Store war frueher decorator-weit: ein kurzlebiger Cache
    loeschte beim Prunen auch gueltige 3600-s-Eintraege anderer Funktionen.
    Jetzt traegt jeder Eintrag seine eigene Ablaufzeit. Zusaetzlich verhindert
    ein Single-Flight-Event, dass N parallele Misses dieselbe teure Funktion
    N-mal berechnen (thundering herd).
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            k = _key(fn, args, kwargs)
            now = time.time()
            with _LOCK:
                hit = _STORE.get(k)
                if hit and hit[1] > now:
                    return hit[2]
                event = _INFLIGHT.get(k)
                if event is not None:
                    compute = False
                else:
                    event = threading.Event()
                    _INFLIGHT[k] = event
                    compute = True
            if not compute:
                event.wait(timeout=30.0)
                with _LOCK:
                    hit = _STORE.get(k)
                    if hit:
                        return hit[2]
                return fn(*args, **kwargs)

            try:
                value = fn(*args, **kwargs)
                post_exec_now = time.time()
                with _LOCK:
                    # Nur wirklich abgelaufene Eintraege entfernen.
                    expired = [ek for ek, ev in _STORE.items() if ev[1] <= post_exec_now]
                    for ek in expired:
                        _STORE.pop(ek, None)
                    while len(_STORE) >= maxsize:
                        # gueltigen Eintrag mit dem fruehesten Ablauf entfernen
                        oldest = min(_STORE, key=lambda key: _STORE[key][1])
                        _STORE.pop(oldest, None)
                    _STORE[k] = (post_exec_now, post_exec_now + seconds, value)
                return value
            finally:
                with _LOCK:
                    _INFLIGHT.pop(k, None)
                    event.set()

        wrapper._ttl_seconds = seconds  # type: ignore[attr-defined]
        wrapper._maxsize = maxsize  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate(fn: Callable | None = None) -> None:
    """Leert den Cache - für eine Funktion oder komplett."""
    with _LOCK:
        if fn is None:
            _STORE.clear()
            return
        # C4: der Tenant-Prefix steht VOR dem Funktionsnamen — daher substring.
        needle = f"|{fn.__module__}.{fn.__qualname__}|"
        for key in [k for k in _STORE if needle in k]:
            _STORE.pop(key, None)


def clear_all() -> None:
    invalidate(None)
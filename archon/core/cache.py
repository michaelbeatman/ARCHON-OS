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
_STORE: Dict[str, Tuple[float, Any]] = {}


def _key(fn: Callable, args: tuple, kwargs: dict) -> str:
    try:
        return f"{fn.__module__}.{fn.__qualname__}|{args!r}|{sorted(kwargs.items())!r}"
    except Exception:
        return f"{fn.__module__}.{fn.__qualname__}|fallback"


def ttl_cache(seconds: float = 30.0):
    """Cached das Ergebnis für `seconds`. None-Ergebnisse werden mitgecacht."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            k = _key(fn, args, kwargs)
            now = time.time()
            with _LOCK:
                hit = _STORE.get(k)
                if hit and (now - hit[0]) < seconds:
                    return hit[1]
            value = fn(*args, **kwargs)
            with _LOCK:
                _STORE[k] = (now, value)
            return value

        wrapper._ttl_seconds = seconds  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate(fn: Callable | None = None) -> None:
    """Leert den Cache - für eine Funktion oder komplett."""
    with _LOCK:
        if fn is None:
            _STORE.clear()
            return
        prefix = f"{fn.__module__}.{fn.__qualname__}|"
        for key in [k for k in _STORE if k.startswith(prefix)]:
            _STORE.pop(key, None)


def clear_all() -> None:
    invalidate(None)
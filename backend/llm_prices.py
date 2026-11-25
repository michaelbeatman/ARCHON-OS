"""OpenRouter-Modellpreise — SSOT (F1a).

Aus ``archon/routers/llm_providers.py`` hierher verlagert: ``backend/**`` darf
``archon.routers.*`` nicht importieren (D09/H-09-2). Der Router re-exportiert
``get_llm_prices`` / ``_get_llm_prices_impl``, damit ``main.py:1093`` und
``archon/routers/chat.py:50`` unveraendert bleiben.

Single-Flight bewusst mit ``threading.Lock`` (KEIN ``asyncio.Lock``): die
Funktion wird auch aus Sync-Pfaden aufgerufen; async Caller nutzen
``asyncio.to_thread``, dann haelt ein Worker-Thread das Lock, nie der Event-Loop.

Rueckgabeform (unveraendert, Body-Shape-Kompatibilitaet):
    {"status": "ok"|"error", "prices": {model_id: {
        "name", "prompt_1m", "completion_1m", "context_length"}}}
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any, Dict, Optional

_price_cache: Optional[Dict[str, Any]] = None
_price_timestamp: float = 0.0
_price_lock = threading.Lock()
_PRICE_TTL_SECONDS = 3600


def get_price_cache() -> Optional[Dict[str, Any]]:
    """Lesender Zugriff fuer die OpenRouter-Modellliste im Router.

    Ersetzt den frueheren direkten Zugriff auf ``_openrouter_price_cache``
    (``llm_providers.py:152-154``); eine blinde Modul-Referenz waere nach einem
    Refresh stale geworden.
    """
    return _price_cache


def _get_llm_prices_locked(refresh: int = 0) -> Dict[str, Any]:
    global _price_cache, _price_timestamp
    try:
        now = time.time()
        if (
            refresh
            or _price_cache is None
            or (now - _price_timestamp > _PRICE_TTL_SECONDS)
        ):
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])
            formatted: Dict[str, Any] = {}
            for m in data:
                pricing = m.get("pricing", {})
                formatted[m["id"]] = {
                    "name": m.get("name") or m["id"],
                    "prompt_1m": float(pricing.get("prompt", 0)) * 1000000,
                    "completion_1m": float(pricing.get("completion", 0)) * 1000000,
                    "context_length": m.get("context_length", 0),
                }
            _price_cache = formatted
            _price_timestamp = now
            return {"status": "ok", "prices": formatted}
        return {"status": "ok", "prices": _price_cache}
    except Exception as e:
        return {"status": "error", "message": str(e), "prices": _price_cache or {}}


def _get_llm_prices_impl(refresh: int = 0) -> Dict[str, Any]:
    """Kernlogik; liefert immer ein Dict (alter Body-Shape)."""
    with _price_lock:
        return _get_llm_prices_locked(refresh=refresh)


def get_llm_prices(refresh: int = 0) -> Dict[str, Any]:
    """Interner Helfer (chat.py, llm_kernel.py, main.py): immer ein Dict."""
    return _get_llm_prices_impl(refresh=refresh)


__all__ = ("get_llm_prices", "_get_llm_prices_impl", "get_price_cache")

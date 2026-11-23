"""Echter Provider-Circuit-Breaker (W3 / Audit Domäne 10).

Die vorhandene `circuit_breaker`-Konfiguration in `agent_router.py` erkennt
wiederholte Agenten-AUSGABEN (Loop/Ping-Pong), nicht ausgefallene HTTP-
Provider. Bei einem downen LLM-Provider wurde deshalb jeder Request erneut
versucht (Thundering Herd) und die gesamte Fallback-Kette kaskadierend
ausgeschöpft.

Dieser Breaker arbeitet pro Provider/Endpoint:
  - N aufeinanderfolgende Fehler (>=500, 429 oder Exception) -> OPEN
  - OPEN für `cooldown` Sekunden -> danach ein Half-Open-Probe
  - Erfolg -> geschlossen, Reset; Misserfolg -> wieder OPEN
"""

import threading
import time
from typing import Dict, Any


class ProviderCircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_seconds: float = 30.0):
        self.threshold = max(1, int(threshold))
        self.cooldown = float(cooldown_seconds)
        self._state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def allow(self, provider: str) -> bool:
        key = str(provider or "unknown").strip().lower()
        with self._lock:
            st = self._state.get(key)
            if not st:
                return True
            open_until = float(st.get("open_until") or 0.0)
            if open_until <= 0:
                return True
            if time.time() >= open_until:
                # M1 (Audit-Lauf 5): bisher wurde `probing` gesetzt, aber nie
                # geprüft -> after cooldown dürfen ALLE wartenden Threads
                # gleichzeitig durch (Thundering Herd). Genau ein Probe.
                if st.get("probing"):
                    return False
                st["probing"] = True
                return True
            return False

    def record_failure(self, provider: str) -> None:
        key = str(provider or "unknown").strip().lower()
        with self._lock:
            st = self._state.setdefault(key, {"fails": 0, "open_until": 0.0, "probing": False})
            st["fails"] = int(st.get("fails", 0)) + 1
            st["probing"] = False
            if st["fails"] >= self.threshold:
                st["open_until"] = time.time() + self.cooldown

    def record_success(self, provider: str) -> None:
        key = str(provider or "unknown").strip().lower()
        with self._lock:
            self._state[key] = {"fails": 0, "open_until": 0.0, "probing": False}

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._state.items()}


provider_breaker = ProviderCircuitBreaker()

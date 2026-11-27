"""Echter Provider-Circuit-Breaker (W3 / Audit Domäne 10, erweitert in M111).

Die vorhandene `circuit_breaker`-Konfiguration in `agent_router.py` erkennt
wiederholte Agenten-AUSGABEN (Loop/Ping-Pong), nicht ausgefallene HTTP-
Provider. Bei einem downen LLM-Provider wurde deshalb jeder Request erneut
versucht (Thundering Herd) und die gesamte Fallback-Kette kaskadierend
ausgeschöpft.

Dieser Breaker arbeitet pro Provider/Endpoint:
  - N aufeinanderfolgende Fehler (>=500, 429 oder Exception) -> OPEN
  - OPEN für `cooldown` Sekunden -> danach ein Half-Open-Probe
  - Erfolg -> geschlossen, Reset; Misserfolg -> wieder OPEN

M111 ergänzt additiv:
  - explizite Zustandsmaschine ``closed`` / ``open`` / ``half_open``,
  - ein Backpressure-Signal (Restzeit bis zum naechsten Probe),
  - eine kanonische Fallback-Hierarchie OmniRoute -> OpenRouter -> lokal.

Bestehende Aufrufer (``allow``/``record_failure``/``record_success``/
``snapshot``) behalten unveraendertes Verhalten.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# Fallback-Hierarchie der SSOT. "local" umfasst Ollama/LM Studio/vLLM.
DEFAULT_FALLBACK_CHAIN: Tuple[str, ...] = ("omniroute", "openrouter", "local")

_PROVIDER_ALIASES: Dict[str, str] = {
    "omni-route": "omniroute",
    "omni_route": "omniroute",
    "open-router": "openrouter",
    "open_router": "openrouter",
    "ollama": "local",
    "lmstudio": "local",
    "lm_studio": "local",
    "vllm": "local",
    "onprem": "local",
}


class BreakerState(str, Enum):
    """Zustandsmaschine des Breakers (str-Enum: JSON-/Log-faehig)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def normalize_provider_name(provider: Any) -> str:
    """Kanonischer Provider-Name ohne Secrets und ohne Gross-/Kleinschreibung."""
    key = str(provider or "unknown").strip().lower()
    return _PROVIDER_ALIASES.get(key, key) or "unknown"


def _state_from_record(record: Dict[str, Any], moment: float, threshold: int) -> BreakerState:
    """Zustandsableitung OHNE Lock (ruft aus bereits gesperrten Pfaden).

    Nach Ablauf des Cooldowns ist der Breaker HALF_OPEN — auch bevor ein
    Thread den Probe tatsaechlich gestartet hat. Damit ist der Zustand
    beobachtbar und das Backpressure-Signal ehrlich.
    """
    open_until = float(record.get("open_until") or 0.0)
    if open_until > moment:
        return BreakerState.OPEN
    if bool(record.get("probing")) or int(record.get("fails", 0)) >= threshold:
        return BreakerState.HALF_OPEN
    return BreakerState.CLOSED


def normalize_fallback_chain(
    preferred: Any = "",
    chain: Optional[Tuple[str, ...]] = None,
) -> Tuple[str, ...]:
    """Baut die Fallback-Kette; der gewuenschte Provider steht zuerst.

    Der explizite Provider darf die Hierarchie nicht wegfallen lassen: nach
    ihm kommen immer OpenRouter und lokal. Duplikate werden entfernt.
    """
    base = tuple(chain) if chain is not None else DEFAULT_FALLBACK_CHAIN
    pref = normalize_provider_name(preferred) if preferred else ""
    ordered: List[str] = []
    for item in ([pref] if pref else []) + [normalize_provider_name(p) for p in base]:
        if item and item not in ordered:
            ordered.append(item)
    return tuple(ordered)


class ProviderCircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_seconds: float = 30.0):
        self.threshold = max(1, int(threshold))
        self.cooldown = float(cooldown_seconds)
        self._state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, provider: Any) -> str:
        # Bestehendes Verhalten (M111 additiv): der State-Key bleibt exakt die
        # bisherige Normalisierung. Aliase werden NUR in der neuen Fallback-
        # SSOT (normalize_fallback_chain/select_provider) aufgeloest.
        return str(provider or "unknown").strip().lower()

    def allow(self, provider: str) -> bool:
        key = self._key(provider)
        with self._lock:
            st = self._state.get(key)
            if not st:
                return True
            open_until = float(st.get("open_until") or 0.0)
            if open_until <= 0:
                return True
            now = time.time()
            if now >= open_until:
                # M1 (Audit-Lauf 5): bisher wurde `probing` gesetzt, aber nie
                # geprüft -> after cooldown dürfen ALLE wartenden Threads
                # gleichzeitig durch (Thundering Herd). Genau ein Probe.
                if st.get("probing"):
                    # B (Härtungsaudit): Stream-Generatoren koennen nach dem
                    # Probe-Start durch den Konsumenten geschlossen werden
                    # (GeneratorExit/CancelledError) — dann erreicht uns kein
                    # record_failure() und `probing` haelt den Provider
                    # dauerhaft gesperrt. Ein verwaister Probe verfällt nach
                    # der Cooldown-Zeit und darf erneut gestartet werden.
                    probe_at = float(st.get("probe_at") or 0.0)
                    if probe_at and (now - probe_at) > (self.cooldown if self.cooldown > 0 else 5.0):
                        st["probing"] = False
                        st["probe_at"] = 0.0
                    else:
                        return False
                st["probing"] = True
                st["probe_at"] = now
                return True
            return False

    def record_failure(self, provider: str) -> None:
        key = self._key(provider)
        with self._lock:
            st = self._state.setdefault(key, {"fails": 0, "open_until": 0.0, "probing": False, "probe_at": 0.0})
            st["fails"] = int(st.get("fails", 0)) + 1
            st["probing"] = False
            st["probe_at"] = 0.0
            if st["fails"] >= self.threshold:
                st["open_until"] = time.time() + self.cooldown

    def record_success(self, provider: str) -> None:
        key = self._key(provider)
        with self._lock:
            self._state[key] = {"fails": 0, "open_until": 0.0, "probing": False, "probe_at": 0.0}

    def state(self, provider: Any, *, now: Optional[float] = None) -> BreakerState:
        """Leitet den Zustand aus dem bestehenden State-Dict ab (read-only)."""
        key = self._key(provider)
        moment = float(now if now is not None else time.time())
        with self._lock:
            st = self._state.get(key)
            if not st:
                return BreakerState.CLOSED
            return _state_from_record(st, moment, self.threshold)

    def backpressure(self, provider: Any, *, now: Optional[float] = None) -> Dict[str, Any]:
        """Backpressure-Signal: OPEN blockiert, HALF_OPEN erlaubt genau einen Probe."""
        key = self._key(provider)
        moment = float(now if now is not None else time.time())
        with self._lock:
            st = self._state.get(key)
            open_until = float(st.get("open_until") or 0.0) if st else 0.0
            fails = int(st.get("fails", 0)) if st else 0
        current = self.state(key, now=moment)
        retry = round(max(0.0, open_until - moment), 3)
        return {
            "provider": key,
            "state": current.value,
            "backpressure_active": current is not BreakerState.CLOSED,
            "retry_after_seconds": retry if current is BreakerState.OPEN else 0.0,
            "probe_in_flight": current is BreakerState.HALF_OPEN,
            "consecutive_failures": fails,
        }

    def select_provider(
        self,
        preferred: Any = "",
        *,
        chain: Optional[Tuple[str, ...]] = None,
        now: Optional[float] = None,
        probe: bool = False,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Waehlt den ersten verfuegbaren Provider der Fallback-Hierarchie.

       Standardmässig ``probe=False``: die Auswahl ist rein lesend und verbraucht
       KEINEN Half-Open-Probe. Erst der echte Provider-Hop ruft ``allow()``.
        Mit ``probe=True`` wird der gewaehlte Provider reserviert (nur fuer
        explizite Dispatch-Pfade gedacht).
        """
        ordered = normalize_fallback_chain(preferred, chain)
        skipped: List[Dict[str, Any]] = []
        moment = float(now if now is not None else time.time())
        chosen: Optional[str] = None
        for candidate in ordered:
            bp = self.backpressure(candidate, now=moment)
            if bp["state"] == BreakerState.OPEN.value or (not probe and bp["backpressure_active"]):
                skipped.append({
                    "provider": candidate,
                    "state": bp["state"],
                    "retry_after_seconds": bp["retry_after_seconds"],
                })
                continue
            if probe and not self.allow(candidate):
                skipped.append({
                    "provider": candidate,
                    "state": self.state(candidate, now=moment).value,
                    "retry_after_seconds": 0.0,
                })
                continue
            chosen = candidate
            break
        worst_retry = max((s["retry_after_seconds"] for s in skipped), default=0.0)
        plan: Dict[str, Any] = {
            "selected": chosen,
            "chain": list(ordered),
            "skipped": skipped,
            "backpressure_active": chosen is None,
            "retry_after_seconds": worst_retry if chosen is None else 0.0,
        }
        return chosen, plan

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            out: Dict[str, Dict[str, Any]] = {}
            moment = time.time()
            for key, value in self._state.items():
                item = dict(value)
                item["state"] = _state_from_record(value, moment, self.threshold).value
                out[key] = item
            return out


provider_breaker = ProviderCircuitBreaker()

__all__ = (
    "BreakerState",
    "DEFAULT_FALLBACK_CHAIN",
    "ProviderCircuitBreaker",
    "normalize_provider_name",
    "normalize_fallback_chain",
    "provider_breaker",
)

# -*- coding: utf-8 -*-
"""
backend/loop_liveness.py
========================
Event-Loop-Liveness-Monitor fuer `/livez`.

Misst kontinuierlich ueber einen schlanken Background-Task im laufenden
Asyncio-Event-Loop:
1. `heartbeat_age_s`: Zeit seit dem letzten erfolgreichen Event-Loop-Tick.
2. `loop_lag_ms`: Abweichung (Scheduling-Verzoegerung) zwischen Soll-Intervall
   und tatsaechlicher Aufwachzeit — erkennt blockierende Sync-Calls im Loop.

Faellt der Heartbeat aus oder ueberschreitet der Loop-Lag das Limit, meldet
`check_loop_liveness()` `alive=False` (HTTP 503 auf `/livez`), sodass Docker
oder ein externer Probe-Runner einen eingefrorenen Prozess neu starten kann.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("archon.loop_liveness")

DEFAULT_INTERVAL_S = 2.0
# Audit 24.11.2026 (E2E): die Defaults muessen zum Docker-Healthcheck passen.
# Dessen urlopen-Timeout betraegt 3 s; ein 3-5 s langer Event-Loop-Hang muss
# daher noch vor dem Healthcheck-Timeout als 503 sichtbar werden. 8 s/2000 ms
# lassen dem 2-s-Heartbeat vier Ticks Toleranz, schlagen aber bei kurzen
# Blockaden zuverlaessig an (alt: 15 s/5000 ms — dort blieb /livez bei einem
# 4-s-Hang auf 200, vgl. audit_reports/2026-11-24_E2E_REGRESSION_RESULT.md).
DEFAULT_MAX_HEARTBEAT_AGE_S = 8.0
DEFAULT_MAX_LOOP_LAG_MS = 2000.0


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return val if val > 0 else default
    except ValueError:
        return default


class LoopLivenessMonitor:
    """Thread-sicherer, leichter Event-Loop-Heartbeat fuer `/livez`."""

    def __init__(self, interval_s: float = DEFAULT_INTERVAL_S) -> None:
        self.interval_s = max(0.05, float(interval_s))
        self._task: Optional[asyncio.Task] = None
        self._started = False
        self._last_tick_mono: float = 0.0
        self._last_lag_ms: float = 0.0
        self._max_lag_ms: float = 0.0
        self._tick_count: int = 0
        self._last_error: str = ""

    def reset(self) -> None:
        self._task = None
        self._started = False
        self._last_tick_mono = 0.0
        self._last_lag_ms = 0.0
        self._max_lag_ms = 0.0
        self._tick_count = 0
        self._last_error = ""

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        self._last_tick_mono = loop.time()
        try:
            while True:
                t_before = loop.time()
                await asyncio.sleep(self.interval_s)
                t_after = loop.time()
                lag_ms = max(0.0, (t_after - t_before - self.interval_s) * 1000.0)
                self._last_tick_mono = t_after
                self._last_lag_ms = round(lag_ms, 2)
                if lag_ms > self._max_lag_ms:
                    self._max_lag_ms = round(lag_ms, 2)
                self._tick_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("[LoopLiveness] Heartbeat-Task abgestuerzt: %s", exc)

    def start(self) -> None:
        """Startet den Event-Loop-Heartbeat im aktuell laufenden Loop (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._last_tick_mono = loop.time()
        self._last_error = ""
        self._started = True
        self._task = loop.create_task(self._run(), name="archon_loop_liveness")

    async def stop(self) -> None:
        """Beendet den Heartbeat-Task sauber beim Shutdown."""
        task = self._task
        self._task = None
        self._started = False
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def check(
        self,
        *,
        max_heartbeat_age_s: Optional[float] = None,
        max_loop_lag_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Bewertet die Event-Loop-Liveness fuer `/livez`."""
        max_age = (
            float(max_heartbeat_age_s)
            if max_heartbeat_age_s is not None
            else _env_float("ARCHON_LIVEZ_MAX_HEARTBEAT_AGE_S", DEFAULT_MAX_HEARTBEAT_AGE_S)
        )
        max_lag = (
            float(max_loop_lag_ms)
            if max_loop_lag_ms is not None
            else _env_float("ARCHON_LIVEZ_MAX_LOOP_LAG_MS", DEFAULT_MAX_LOOP_LAG_MS)
        )

        # Kurze kooperative Yield-Probe: wenn der Event-Loop ueberhaupt noch
        # aufwacht, misst sie auch on-demand den aktuellen Scheduling-Lag.
        t0 = time.monotonic()
        await asyncio.sleep(0)
        on_demand_lag_ms = round(max(0.0, (time.monotonic() - t0) * 1000.0), 2)

        if not self._started:
            # Lifespan nicht gestartet (z. B. reiner Unit-Test ohne Lifespan):
            # on-demand Probe entscheidet.
            alive = on_demand_lag_ms <= max_lag
            return {
                "alive": alive,
                "status": "alive" if alive else "degraded",
                "mode": "on_demand",
                "heartbeat_started": False,
                "heartbeat_age_s": 0.0,
                "loop_lag_ms": on_demand_lag_ms,
                "max_loop_lag_ms": self._max_lag_ms,
                "tick_count": self._tick_count,
                "reason": None if alive else f"on_demand loop lag {on_demand_lag_ms}ms > {max_lag}ms",
                "timestamp": time.time(),
            }

        try:
            now_mono = asyncio.get_running_loop().time()
        except RuntimeError:
            now_mono = time.monotonic()
        age_s = round(max(0.0, now_mono - self._last_tick_mono), 3)
        effective_lag_ms = max(self._last_lag_ms, on_demand_lag_ms)

        reason: Optional[str] = None
        if self._task is not None and self._task.done() and not self._task.cancelled():
            reason = f"heartbeat_task_stopped: {self._last_error or 'unknown'}"
        elif age_s > max_age:
            reason = f"heartbeat_stale: {age_s}s > {max_age}s"
        elif effective_lag_ms > max_lag:
            reason = f"loop_lag_exceeded: {effective_lag_ms}ms > {max_lag}ms"

        alive = reason is None
        return {
            "alive": alive,
            "status": "alive" if alive else "unhealthy",
            "mode": "heartbeat",
            "heartbeat_started": True,
            "heartbeat_age_s": age_s,
            "loop_lag_ms": effective_lag_ms,
            "max_loop_lag_ms": self._max_lag_ms,
            "tick_count": self._tick_count,
            "reason": reason,
            "timestamp": time.time(),
        }


loop_liveness_monitor = LoopLivenessMonitor()


async def start_loop_heartbeat() -> None:
    loop_liveness_monitor.start()


async def stop_loop_heartbeat() -> None:
    await loop_liveness_monitor.stop()


async def check_loop_liveness() -> Dict[str, Any]:
    return await loop_liveness_monitor.check()

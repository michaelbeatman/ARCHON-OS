#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Externer Autoheal fuer ARCHON-OS (Audit D10 / E2E 24.11.2026).

Der Docker-Healthcheck erkennt Haenger, restartet aber nicht; der
In-App-Self-Healing laeuft im eingefrorenen Prozess und kann ihn daher nicht
melden. Dieser schlanke Prozess fragt `/livez` von aussen ab und stoppt/
startet den Zielcontainer nach N aufeinanderfolgenden Fehlschlagen.

Sicherheitsgrenzen:
* nur GET/POST ueber den freigegebenen docker-socket-proxy (ALLOW_START/STOP)
* Eingriff NUR wenn Docker den Container selbst als `unhealthy` markiert
* Cooldown gegen Restart-Storms, kein Eingriff bei laufendem Draining
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

TARGET = os.environ.get("AUTOHEAL_TARGET_URL", "http://archon-os:8501/livez").strip()
CONTAINER = os.environ.get("AUTOHEAL_CONTAINER", "ARCHON-OS").strip()
INTERVAL = max(5.0, float(os.environ.get("AUTOHEAL_INTERVAL_S", "30")))
FAILURES = max(2, int(os.environ.get("AUTOHEAL_FAILURES", "5")))
COOLDOWN = max(60.0, float(os.environ.get("AUTOHEAL_COOLDOWN_S", "900")))
PROBE_TIMEOUT = max(1.0, float(os.environ.get("AUTOHEAL_PROBE_TIMEOUT_S", "5")))
HEALTH_GATE = os.environ.get("AUTOHEAL_HEALTH_GATE", "1").strip() not in ("0", "false", "no")

_DOCKER_HOST = os.environ.get("DOCKER_HOST", "tcp://docker-socket-proxy:2375")
_DOCKER_BASE = "http://" + _DOCKER_HOST.replace("tcp://", "").replace("http://", "").rstrip("/")


def log(message: str) -> None:
    print(f"[archon-autoheal] {message}", flush=True)


def probe() -> bool:
    try:
        with urllib.request.urlopen(TARGET, timeout=PROBE_TIMEOUT) as response:
            return int(response.status) == 200
    except Exception as exc:  # 503, Timeout, ConnectionRefused zaehlen alle als Fehlschlag
        log(f"probe {TARGET} fehlgeschlagen: {type(exc).__name__}")
        return False


def docker_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        _DOCKER_BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        raw = response.read(256 * 1024)
    return json.loads(raw.decode("utf-8")) if raw else {}


def container_state() -> dict:
    try:
        info = docker_request("GET", f"/containers/{CONTAINER}/json")
        state = info.get("State", {}) or {}
        return {
            "status": str(state.get("Status", "")),
            "health": str((state.get("Health", {}) or {}).get("Status", "")),
        }
    except Exception as exc:
        log(f"docker inspect fehlgeschlagen: {type(exc).__name__}")
        return {}


def main() -> None:
    log(f"gestartet: target={TARGET} container={CONTAINER} "
        f"failures={FAILURES} interval={INTERVAL}s cooldown={COOLDOWN}s health_gate={HEALTH_GATE}")
    consecutive = 0
    last_action = 0.0
    time.sleep(15.0)  # Startphase des Ziels nicht als Hang fehlinterpretieren

    while True:
        if probe():
            if consecutive:
                log("wieder gesund — Fehlerzaehler zurueckgesetzt")
            consecutive = 0
            time.sleep(INTERVAL)
            continue

        consecutive += 1
        log(f"Fehlschlag {consecutive}/{FAILURES}")
        if consecutive < FAILURES or (time.time() - last_action) < COOLDOWN:
            time.sleep(INTERVAL)
            continue

        state = container_state()
        if state.get("status") != "running":
            log(f"kein Eingriff: Container-Status={state.get('status')!r}")
        elif HEALTH_GATE and state.get("health") != "unhealthy":
            log(f"kein Eingriff: Docker-Health={state.get('health')!r} (noch nicht unhealthy)")
        else:
            log("eskaliere: stop + start (Healthcheck und /livez beide rot)")
            try:
                docker_request("POST", f"/containers/{CONTAINER}/stop")
                docker_request("POST", f"/containers/{CONTAINER}/start")
                last_action = time.time()
                consecutive = 0
                log("Neustart ausgeloest; Cooldown aktiv")
            except Exception as exc:
                log(f"Neustart fehlgeschlagen: {type(exc).__name__}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

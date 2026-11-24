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

Audit D10: zusaetzlich zur Event-Loop-Liveness wird `loops.watchdog` aus
`/livez` geprueft. Ein toter Watchdog-Thread liess `/livez` frueher gruen —
jetzt zaehlt ein stale `last_seen` als Fehlschlag und fuehrt zum Neustart.
Fehlt das Feld (aelteres main.py), gilt der Watchdog als unbekannt und wird
nicht als stale gewertet (Rueckwaertskompatibilitaet).
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
WATCHDOG_MAX_AGE = max(30.0, float(os.environ.get("AUTOHEAL_WATCHDOG_MAX_AGE_S", "120")))

_DOCKER_HOST = os.environ.get("DOCKER_HOST", "tcp://docker-socket-proxy:2375")
_DOCKER_BASE = "http://" + _DOCKER_HOST.replace("tcp://", "").replace("http://", "").rstrip("/")


def log(message: str) -> None:
    print(f"[archon-autoheal] {message}", flush=True)


def _watchdog_stale_from_body(raw: bytes) -> tuple[bool, str]:
    """Liest ``loops.watchdog`` aus JEDEM /livez-Body (auch bei HTTP 503)."""
    try:
        payload = json.loads(raw.decode("utf-8", errors="ignore"))
        loops = payload.get("loops") or {}
        wd = loops.get("watchdog") or {}
        if wd:
            last_seen = float(wd.get("last_seen") or 0.0)
            age = (time.time() - last_seen) if last_seen > 0 else float("inf")
            alive = wd.get("alive")
            if alive is False or age > WATCHDOG_MAX_AGE:
                return True, f"watchdog last_seen age={age:.1f}s > {WATCHDOG_MAX_AGE}s"
            return False, f"watchdog age={age:.1f}s OK"
    except Exception as exc:
        return False, f"watchdog field unavailable ({type(exc).__name__})"
    return False, ""


def probe() -> dict:
    """Prueft /livez inkl. Watchdog-Heartbeat.

    Rueckgabe: ``{"ok": bool, "watchdog_stale": bool, "detail": str}``.
    503, Timeout, ConnectionRefused und ein stale Watchdog zaehlen als
    Fehlschlag (`ok=False`) und erhoehen den Zaehler in main().

    D10/MED: frueher branchte die Funktion bei HTTP 503 sofort ab, ohne den
    JSON-Body zu lesen. /livez liefert bei totem Watchdog genau dann 503 mit
    ``loops.watchdog.alive=False`` — der spezielle ``watchdog_stale``-Pfad war
    damit unerreichbar. Jetzt wird der Body auch aus HTTPError gelesen.
    """
    status = 0
    raw = b""
    try:
        with urllib.request.urlopen(TARGET, timeout=PROBE_TIMEOUT) as response:
            status = int(response.status)
            raw = response.read(256 * 1024)
    except urllib.error.HTTPError as exc:
        # urlopen wirft bei 503; der Body enthaelt die Watchdog-Diagnose.
        status = int(exc.code)
        try:
            raw = exc.read(256 * 1024) or b""
        except Exception:
            raw = b""
    except Exception as exc:  # Timeout, ConnectionRefused zaehlen als Fehlschlag
        log(f"probe {TARGET} fehlgeschlagen: {type(exc).__name__}")
        return {"ok": False, "watchdog_stale": False, "detail": type(exc).__name__}

    watchdog_stale, wd_detail = _watchdog_stale_from_body(raw)
    detail = wd_detail or f"HTTP {status}"
    if status != 200 and not watchdog_stale:
        detail = f"HTTP {status}" + (f" ({wd_detail})" if wd_detail else "")

    return {
        "ok": status == 200 and not watchdog_stale,
        "watchdog_stale": watchdog_stale,
        "detail": detail,
    }


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


def _do_restart() -> bool:
    """stop+start ueber den Proxy; nur bei Erfolg Cooldown/Zaehler zuruecksetzen."""
    try:
        docker_request("POST", f"/containers/{CONTAINER}/stop")
        docker_request("POST", f"/containers/{CONTAINER}/start")
        log("Neustart ausgeloest; Cooldown aktiv")
        return True
    except Exception as exc:
        log(f"Neustart fehlgeschlagen: {type(exc).__name__}")
        return False


def main() -> None:
    log(f"gestartet: target={TARGET} container={CONTAINER} "
        f"failures={FAILURES} interval={INTERVAL}s cooldown={COOLDOWN}s health_gate={HEALTH_GATE} "
        f"watchdog_max_age={WATCHDOG_MAX_AGE}s")
    consecutive = 0
    last_action = 0.0
    time.sleep(15.0)  # Startphase des Ziels nicht als Hang fehlinterpretieren

    while True:
        result = probe()
        if result["ok"]:
            if consecutive:
                log("wieder gesund — Fehlerzaehler zurueckgesetzt")
            consecutive = 0
            time.sleep(INTERVAL)
            continue

        consecutive += 1
        detail = f" ({result['detail']})" if result["detail"] else ""
        log(f"Fehlschlag {consecutive}/{FAILURES}{detail}")
        if consecutive < FAILURES or (time.time() - last_action) < COOLDOWN:
            time.sleep(INTERVAL)
            continue

        state = container_state()
        if state.get("status") != "running":
            log(f"kein Eingriff: Container-Status={state.get('status')!r}")
        elif result.get("watchdog_stale"):
            # D10/MED: eigener Eingriffspfad — der Watchdog ist tot, auch wenn
            # Docker den Container noch als healthy markiert (Healthcheck
            # deaktiviert oder spaeter Greift-Zeitfenster).
            log("eskaliere: stop + start (watchdog_stale)")
            if _do_restart():
                last_action = time.time()
                consecutive = 0
        elif HEALTH_GATE and state.get("health") != "unhealthy" and not result.get("watchdog_stale"):
            log(f"kein Eingriff: Docker-Health={state.get('health')!r} (noch nicht unhealthy)")
        else:
            log("eskaliere: stop + start (Healthcheck und /livez beide rot)")
            if _do_restart():
                last_action = time.time()
                consecutive = 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

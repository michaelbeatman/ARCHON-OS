"""Liveness-, Readiness- und Dependency-Probes (M3 aus main.py).

Reine Extraktion nach dem S3-Muster (Call-Time-Dependency-Injection):
* Kein Rueckimport auf ``main``.
* ``_DEPENDENCY_PROBE_CACHE``, ``_DEPENDENCY_PROBE_TTL`` und
  ``_READINESS_PROBE_READY`` werden in ``main.py`` als identische Objekte
  re-exportiert.
* Die ``@app.get("/livez")`` / ``"/readyz"`` / ``"/health"`` / ``"/metrics"``-
  Routen bleiben an exakt ihrer alten Position in ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import urllib.request
from typing import Any, Callable, Dict, List, NamedTuple, Tuple

from fastapi.responses import JSONResponse

logger = logging.getLogger("archon_os")

_DEPENDENCY_PROBE_CACHE: Dict[str, Any] = {"ts": 0.0, "problems": []}
_DEPENDENCY_PROBE_TTL: float = 10.0
_READINESS_PROBE_READY: Dict[str, bool] = {"ok": False}


class HealthProbeDeps(NamedTuple):
    """Zur Aufrufzeit injizierte Readiness-Abhaengigkeiten aus main.py."""

    get_state_db: Callable[[], Any]
    router_load_errors: List[str]
    audit_compromised: Dict[str, Any]
    failed_cancels: List[Dict[str, Any]]
    watchdog_stop_failed: List[Dict[str, Any]]
    startup_recovery_failed: List[Dict[str, Any]]
    n8n_startup_status: Dict[str, Any]
    db_maintenance_status: Dict[str, Any]
    probe_external_dependency: Callable[[str, str], str]
    readiness_sync_checks: Callable[[], List[str]]


def _readiness_probe_targets() -> List[Tuple[str, str]]:
    """Konfigurierbare externe Probes (H-10-1/F043)."""
    raw = os.getenv("ARCHON_READINESS_PROBE_URLS")
    if raw is None:
        omniroute = os.getenv("OMNIROUTE_URL", "http://omniroute:20128/v1").rstrip("/")
        raw = f"omniroute={omniroute}/models"
    targets: List[Tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            name, url = entry.split("=", 1)
        else:
            name, url = entry, entry
        name, url = name.strip() or url.strip(), url.strip()
        if url:
            targets.append((name, url))
    return targets


def _probe_external_dependency(name: str, url: str) -> str:
    """Synchrone URL-Probe — ausschliesslich aus asyncio.to_thread gerufen."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            if resp.status >= 400:
                return f"{name}: HTTP {resp.status}"
    except Exception as exc:
        return f"{name}: {exc}"
    return ""


def init_readiness_probe_table(get_state_db: Callable[[], Any]) -> None:
    """DDL einmalig (Lifespan) — nicht mehr pro Healthcheck-Scrape."""
    with get_state_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _readiness_probe (id INTEGER)")
    _READINESS_PROBE_READY["ok"] = True


def run_readiness_sync_checks(get_state_db: Callable[[], Any]) -> List[str]:
    """Alle blockierenden Readiness-Checks gebuendelt im Worker-Thread."""
    problems: List[str] = []
    if not _READINESS_PROBE_READY["ok"]:
        try:
            init_readiness_probe_table(get_state_db)
        except Exception as exc:
            problems.append(f"state_db: {exc}")
    if _READINESS_PROBE_READY["ok"]:
        try:
            with get_state_db() as conn:
                conn.execute("INSERT OR IGNORE INTO _readiness_probe (id) VALUES (1)")
        except Exception as exc:
            problems.append(f"state_db: {exc}")
    try:
        from backend.config_validator import validator

        res = validator.validate_all(strict=False)
        if not res.get("valid", True):
            problems.append(f"config: {res.get('error_count', '?')} Fehler")
    except Exception as exc:
        problems.append(f"config_check: {exc}")
    try:
        from backend.process_lock import get_loop_lock_failures

        _lock_failures = get_loop_lock_failures()
        if _lock_failures:
            problems.append(f"loop_lock_unavailable: {len(_lock_failures)}")
    except Exception as exc:
        problems.append(f"loop_lock_check: {exc}")
    return problems


async def run_liveness_check() -> Any:
    """Liveness: Event-Loop-Heartbeat, Loop-Lag + Watchdog-Thread (503 bei blockiertem Loop)."""
    from backend.loop_liveness import check_loop_liveness

    info = await check_loop_liveness()
    try:
        from watchdog_daemon import watchdog_liveness

        wd = await asyncio.to_thread(watchdog_liveness)
    except Exception as exc:
        logger.error("[Livez] Watchdog-Liveness nicht lesbar (fail-closed): %s", exc)
        wd = {"alive": False, "last_seen": 0.0, "age_s": None}
    info["loops"] = {
        "watchdog": {
            "alive": bool(wd.get("alive")),
            "last_seen": wd.get("last_seen", 0.0),
            "age_s": wd.get("age_s"),
        }
    }
    if not info.get("alive", True) or not info["loops"]["watchdog"]["alive"]:
        return JSONResponse(status_code=503, content=info)
    return info


async def run_readiness_check(
    deps: HealthProbeDeps,
    probe_targets: List[Tuple[str, str]],
) -> Any:
    """Readiness: echte Dependency-Pruefung. Liefert 503, solange nicht bereit."""
    problems: List[str] = []
    problems.extend(await asyncio.to_thread(deps.readiness_sync_checks))
    if deps.router_load_errors:
        problems.append(f"router_imports: {len(deps.router_load_errors)}")
    if deps.audit_compromised.get("compromised"):
        problems.append(f"audit_compromised: {deps.audit_compromised.get('reason')}")
    _probe_enabled = (
        os.getenv("ARCHON_READINESS_PROBES", "").strip().lower() in ("1", "true", "yes")
        or os.getenv("ENVIRONMENT", "").strip().lower() in ("production", "prod", "live")
    )
    probes = probe_targets if _probe_enabled else []
    if probes:
        now = time.time()
        if now - float(_DEPENDENCY_PROBE_CACHE["ts"]) > _DEPENDENCY_PROBE_TTL:
            dep_problems = await asyncio.gather(
                *(
                    asyncio.to_thread(deps.probe_external_dependency, name, url)
                    for name, url in probes
                )
            )
            cleaned_problems = [p for p in dep_problems if p]
            _DEPENDENCY_PROBE_CACHE.update(ts=now, problems=cleaned_problems)
        problems.extend(_DEPENDENCY_PROBE_CACHE["problems"])
    if deps.failed_cancels:
        problems.append(f"failed_cancels: {len(deps.failed_cancels)}")
    if deps.watchdog_stop_failed:
        problems.append(f"watchdog_stop: {len(deps.watchdog_stop_failed)}")
    if deps.startup_recovery_failed:
        problems.append(f"startup_recovery: {len(deps.startup_recovery_failed)}")
    if deps.n8n_startup_status.get("status") == "error":
        problems.append(f"n8n_startup_import: {deps.n8n_startup_status.get('detail')}")
    if deps.db_maintenance_status.get("status") == "error":
        problems.append(f"db_maintenance: {deps.db_maintenance_status.get('error')}")
    if problems:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "timestamp": time.time(), "problems": problems},
        )
    return {"status": "ready", "timestamp": time.time()}

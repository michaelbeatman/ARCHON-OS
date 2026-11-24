"""
backend/fleet_self_healing.py
Autonome Flotten-Selbstheilung für Docker-Core-Dienste (Pillar 1 & 3).
Überwacht Core-Dienste (omniroute, anything-llm, n8n, CRM).
Stellt ein Container-Ausfall fest, führt das Modul einen gezielten Neustart aus
und alarmiert das System über den Notification Hub und das Audit-Log.
"""

import os
import sys
import time
import json
import datetime
import logging
import urllib.request
from typing import Dict, Any, List, Optional

from archon.core.cache import ttl_cache  # noqa: E402
from utils.docker_client import DockerClient, DockerError, validate_container_name

logger = logging.getLogger("archon.fleet_self_healing")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KNOWN_SERVICES = {
    "omniroute": "omniroute",
    "anything-llm": "anything-llm",
    "n8n": "n8n",
    "crm": "ef47f1b25a78_CRM",
    "freellmapi": "freellmapi"
}

# F26/R-05: Der Container-Name kam ungefiltert aus dem URL-Pfad in einen
# Shell-String. Erlaubt sind jetzt nur noch die Aliasse/Targets aus
# KNOWN_SERVICES plus explizit per Env freigegebene Namen (jeder einzeln
# gegen die Docker-Namensregel validiert).
_EXTRA_ALLOWLIST_ENV = "ARCHON_FLEET_EXTRA_CONTAINERS"

# --- E/F: Dead-Man-Switch + Selbst-Check des Hauptprozesses ---------------
_HEARTBEAT_WEBHOOK_LAST_TS = 0.0
_HEARTBEAT_WEBHOOK_MIN_INTERVAL = 120.0
_SELF_HEARTBEAT_MAX_AGE = 300.0


def _status_config_paths() -> List[str]:
    paths: List[str] = []
    try:
        from archon.core.runtime import MEMORY_DIR
        paths.append(os.path.join(MEMORY_DIR, "plugins_config", "evey-status.json"))
    except Exception as exc:
        logger.debug("[DeadManSwitch] MEMORY_DIR nicht verfuegbar: %s", exc)
    try:
        from archon.core.paths import OPT_DATA_DIR
        paths.append(os.path.join(OPT_DATA_DIR, "plugins_config", "evey-status.json"))
    except Exception as exc:
        logger.debug("[DeadManSwitch] OPT_DATA_DIR nicht verfuegbar: %s", exc)
    return paths


def _get_heartbeat_webhook_url() -> str:
    """Liest die bestehende evey-status-Plugin-Config (guardian.py)."""
    for path in _status_config_paths():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if isinstance(cfg, dict):
                url = str(cfg.get("heartbeat_webhook_url") or "").strip()
                if url:
                    return url
        except (OSError, ValueError) as exc:
            logger.debug("[DeadManSwitch] Config nicht lesbar (%s): %s", path, exc)
    return ""


def _post_heartbeat_webhook(status: str, *, force: bool = False, **extra: Any) -> bool:
    """POST an den konfigurierten Dead-Man-Switch (timeout=5). Keine URL = no-op."""
    url = _get_heartbeat_webhook_url()
    if not url:
        return False
    global _HEARTBEAT_WEBHOOK_LAST_TS
    now = time.time()
    if not force and (now - _HEARTBEAT_WEBHOOK_LAST_TS) < _HEARTBEAT_WEBHOOK_MIN_INTERVAL:
        return False
    payload = {
        "service": "archon-os",
        "status": status,
        "timestamp": datetime.datetime.now().isoformat(),
        **extra,
    }
    # F-036: exakt dieselbe kompakte Serialisierung wie alle anderen HMAC-Sender,
    # damit ein n8n-Empfaenger mit JSON.stringify() dieselben Bytes signiert.
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    try:
        try:
            from utils.safe_http import safe_http_request, webhook_signature_headers
            headers.update(webhook_signature_headers(body))
            safe_http_request(url, method="POST", headers=headers, data=body, timeout=5.0)
        except ImportError:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp.read(1024)
    except Exception as exc:
        # URL/key nie loggen — nur den Fehlertyp.
        logger.warning("[DeadManSwitch] Heartbeat-Webhook nicht erreichbar: %s", type(exc).__name__)
        return False
    _HEARTBEAT_WEBHOOK_LAST_TS = now
    return True


def _check_main_process_heartbeat() -> Dict[str, Any]:
    """F: die 5 Aliasse healden die archon-os selbst nie — jetzt mit Selbst-Check."""
    try:
        from backend.metrics_collector import get_last_heartbeat_ts, report_external_alert
    except Exception as exc:
        logger.debug("[SelfHealing] Heartbeat-Modul nicht verfuegbar: %s", exc)
        return {"status": "unknown"}
    ts = float(get_last_heartbeat_ts() or 0.0)
    if ts <= 0:
        return {"status": "unknown", "reason": "no_heartbeat_yet"}
    age = round(time.time() - ts, 1)
    stale = age > _SELF_HEARTBEAT_MAX_AGE
    if stale:
        logger.error("[SelfHealing] ARCHON-Hauptprozess stale: letzter Alert-Heartbeat vor %.1f s", age)
        report_external_alert(
            "main_process_stale", "CRITICAL", "archon-os",
            f"Kein Alert-Heartbeat seit {age} s.",
            active=True, title="Archon-Hauptprozess stale",
        )
        sent = _post_heartbeat_webhook("stale", force=True, heartbeat_age_seconds=age)
    else:
        report_external_alert("main_process_stale", "CRITICAL", "archon-os", "", active=False)
        sent = False
    return {"status": "stale" if stale else "ok", "age_seconds": age, "webhook_sent": sent}


def _allowed_container_names() -> set:
    names = {str(v) for v in KNOWN_SERVICES.values()}
    for entry in (os.environ.get(_EXTRA_ALLOWLIST_ENV) or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            names.add(validate_container_name(entry))
        except DockerError:
            continue
    return names


def resolve_container_target(service_name: str) -> str:
    """Loest Alias/Namen auf einen Container-Namen auf der Allowlist auf.

    Raises:
        DockerError: bei ungueltigem Namen oder nicht freigegebenem Container.
    """
    raw = str(service_name or "").strip()
    if not raw:
        raise DockerError("service_name ist leer")
    svc_key = raw.lower()
    if svc_key in KNOWN_SERVICES:
        return KNOWN_SERVICES[svc_key]
    target = validate_container_name(raw)
    if target not in _allowed_container_names():
        raise DockerError(
            f"Container {raw!r} steht nicht auf der Fleet-Allowlist "
            f"(siehe {_EXTRA_ALLOWLIST_ENV})"
        )
    return target


def _docker_client() -> DockerClient:
    """Proxy-faehiger Docker-Client.

    C13-BLOCKER: Der Container hat keinen Docker-Socket gemountet, sondern nur
    ``DOCKER_HOST=tcp://docker-socket-proxy:2375``. Die fruehere docker-CLI mit
    ``-H unix://...`` lief deshalb gegen einen nicht existierenden Socket, lieferte
    leere Ausgabe und der Self-Healing-Loop meldete ``status: ok`` ohne Effekt.
    ``DockerClient`` respektiert DOCKER_HOST und prueft den HTTP-Status; der Proxy
    sperrt ``restart`` (ALLOW_RESTARTS=0), deshalb ``restart_container()`` als
    stop+start ueber freigegebene Aktionen verwenden.
    """
    return DockerClient()


def _list_containers() -> Dict[str, str]:
    """Liefert ``{name: status}`` ueber den Proxy (GET /containers/json?all=1)."""
    raw = _docker_client().request("GET", "/containers/json?all=1", timeout=10.0)
    items = json.loads(raw.decode("utf-8", errors="replace") or "[]")
    result: Dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        names = item.get("Names") or []
        name = str(names[0]).lstrip("/") if names else str(item.get("Id") or "")
        status = str(item.get("Status") or item.get("State") or "")
        if name:
            result[name] = status
    return result


def restart_service_container(service_name: str) -> Dict[str, Any]:
    """Startet einen ausgefallenen Docker-Container autonom neu (via Socket-Proxy)."""
    now_iso = datetime.datetime.now().isoformat()
    try:
        container_target = resolve_container_target(service_name)
    except DockerError as exc:
        return {"status": "error", "service": service_name,
                "container": None, "error": str(exc)}

    try:
        _docker_client().restart_container(container_target)
        success = True
        output = "stop+start via docker-socket-proxy"
    except Exception as exc:
        success = False
        output = f"{type(exc).__name__}: {exc}"

    # Audit und Benachrichtigung MUESSEN auf beiden Pfaden laufen (Erfolg wie
    # Fehler), sonst verschwindet der Nachweis ueber die Selbstheilung.
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="resilience",
            action="FLEET_SELF_HEALING_RESTART",
            agent_id="Watchdog-Daemon",
            payload={"service": service_name, "container": container_target,
                     "success": success, "log": output[:200]}
        )
    except Exception as exc:
        logger.debug("Audit-Log-Eintrag für Selbstheilung von '%s' fehlgeschlagen: %s", service_name, exc)

    try:
        from backend.notification_hub import notification_hub
        severity = "INFO" if success else "CRITICAL"
        msg = (f"Dienst '{service_name}' wurde autonom neugestartet." if success
               else f"Selbstheilung von '{service_name}' fehlgeschlagen: {output[:150]}")
        notification_hub.dispatch_notification(
            title=f"Flotten-Selbstheilung: {service_name}",
            message=msg,
            severity=severity,
            category="fleet_health"
        )
    except Exception as exc:
        logger.debug("Benachrichtigung über Selbstheilung von '%s' konnte nicht versendet werden: %s", service_name, exc)

    return {
        "status": "success" if success else "failed",
        "service": service_name,
        "container": container_target,
        "restarted_at": now_iso,
        "output": output
    }

@ttl_cache(seconds=30)
def check_fleet_and_heal(services: Optional[List[str]] = None) -> Dict[str, Any]:
    """Prüft den Zustand der Core-Dienste und heilt ausgefallene Dienste automatisch.

    C13: Es werden nur Container betrachtet, die überhaupt existieren. Ein
    nicht deployter Dienst (z. B. CRM in einer Minimal-Installation) wird
    übersprungen statt alle 2 Minuten einen erfolglosen Neustart zu versuchen.
    Als ausgefallen gilt auch ein laufender Container mit `unhealthy`-Status —
    `restart: unless-stopped` greift in diesem Fall nicht.
    """
    auto_restart = True
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("fleet_and_hygiene")
        auto_restart = bool(cfg.get("auto_container_restart", True))
    except Exception as exc:
        logger.debug("Fleet-Konfiguration 'fleet_and_hygiene' nicht lesbar, nutze Default auto_container_restart=True: %s", exc)

    try:
        containers = _list_containers()
        aliases = [a for a in KNOWN_SERVICES if services is None or a in services]
        healed = []
        missing = []
        skipped_not_deployed = []
        for s_alias in aliases:
            c_name = KNOWN_SERVICES[s_alias]
            status = next(
                (st for name, st in containers.items() if name == c_name or c_name in name),
                None,
            )
            if status is None:
                skipped_not_deployed.append(s_alias)
                continue
            is_healthy = status.startswith("Up") and "unhealthy" not in status.lower()
            if not is_healthy:
                missing.append(s_alias)
                if auto_restart:
                    res = restart_service_container(s_alias)
                    healed.append(res)

        # F: Selbst-Check + E: Dead-Man-Switch. Der 120-s-Loop in main.py
        # ruft diese Funktion; der Webhook wird zusaetzlich auf 120 s gedrosselt.
        self_heartbeat = _check_main_process_heartbeat()
        webhook_sent = (
            bool(self_heartbeat.get("webhook_sent"))
            if self_heartbeat.get("status") == "stale"
            else _post_heartbeat_webhook("ok")
        )

        return {
            "status": "ok",
            "auto_restart_enabled": auto_restart,
            "checked_services_count": len(aliases),
            "skipped_not_deployed": skipped_not_deployed,
            "missing_services": missing,
            "healed_count": len(healed),
            "healed_services": healed,
            "self_heartbeat": self_heartbeat,
            "heartbeat_webhook_sent": webhook_sent
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "healed_count": 0}
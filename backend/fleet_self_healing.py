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
import subprocess
import datetime
from typing import Dict, Any, List

from archon.core.cache import ttl_cache  # noqa: E402
from utils.docker_client import DockerError, docker_cli_host_args, validate_container_name

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


def restart_service_container(service_name: str) -> Dict[str, Any]:
    """Startet einen ausgefallenen Docker-Container autonom neu."""
    now_iso = datetime.datetime.now().isoformat()
    try:
        container_target = resolve_container_target(service_name)
    except DockerError as exc:
        return {"status": "error", "service": service_name,
                "container": None, "error": str(exc)}

    # argv-Liste, kein shell=True; -H pinnt den Socket (M-21): die CLI folgt sonst
    # dem globalen DOCKER_HOST und laeuft in den Proxy, der `restart` sperrt.
    cmd = ["docker", *docker_cli_host_args(), "restart", container_target]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        success = proc.returncode == 0
        output = proc.stdout.strip() if success else proc.stderr.strip()

        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                event_type="FLEET_SELF_HEALING_RESTART",
                agent_id="Watchdog-Daemon",
                payload={"service": service_name, "container": container_target, "success": success, "log": output[:200]}
            )
        except Exception:
            pass

        try:
            from backend.notification_hub import notification_hub
            severity = "INFO" if success else "CRITICAL"
            msg = f"Dienst '{service_name}' wurde autonom neugestartet." if success else f"Selbstheilung von '{service_name}' fehlgeschlagen: {output[:150]}"
            notification_hub.dispatch_notification(
                title=f"Flotten-Selbstheilung: {service_name}",
                message=msg,
                severity=severity,
                category="fleet_health"
            )
        except Exception:
            pass

        return {
            "status": "success" if success else "failed",
            "service": service_name,
            "container": container_target,
            "restarted_at": now_iso,
            "output": output
        }
    except Exception as e:
        return {"status": "error", "service": service_name, "error": str(e)}

@ttl_cache(seconds=30)
def check_fleet_and_heal() -> Dict[str, Any]:
    """Prüft den Zustand der Core-Dienste und heilt ausgefallene Dienste automatisch (sofern in settings.json aktiviert)."""
    auto_restart = True
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("fleet_and_hygiene")
        auto_restart = bool(cfg.get("auto_container_restart", True))
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["docker", *docker_cli_host_args(), "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        lines = proc.stdout.strip().splitlines()
        running_names = [l.split("\t")[0].strip() for l in lines if l.strip()]

        healed = []
        missing = []
        for s_alias, c_name in KNOWN_SERVICES.items():
            if not any(c_name in r for r in running_names):
                missing.append(s_alias)
                if auto_restart:
                    res = restart_service_container(s_alias)
                    healed.append(res)

        return {
            "status": "ok",
            "auto_restart_enabled": auto_restart,
            "checked_services_count": len(KNOWN_SERVICES),
            "missing_services": missing,
            "healed_count": len(healed),
            "healed_services": healed
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "healed_count": 0}
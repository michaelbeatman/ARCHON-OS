"""
backend/resource_backpressure.py
Paket 5 (Feature 25): Live-Ressourcen-Protector (Host CPU-, RAM- & Disk-Backpressure).
Misst die aktuelle Systemlast (CPU-Last, RAM-Belegung, freier Festplattenspeicher).
Überschreitet ein Wert die konfigurierten Schwellenwerte (`max_cpu_pct`, `max_ram_pct`, `min_free_disk_gb`),
aktiviert der Protector automatisch Backpressure (Pausieren niedrig priorisierter Hintergrund-Jobs).

F-077: Schwellen decken sich jetzt mit den Prometheus-Regeln — 2 GiB (2*1024**3
Bytes, nicht 2.0 dezialmal-GB) und 90 % Belegung. Der Check laeuft zusaetzlich
periodisch im 30-s-Loop (main.py), damit der Alarm auch ohne Requests feuert.
"""
import logging
_archon_exc_logger = logging.getLogger("resource_backpressure")

import os
import json
import shutil
from typing import Dict, Any

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("resource_backpressure")
    except Exception:
        return {
            "enabled": True,
            "max_cpu_pct": 85,
            "max_ram_pct": 85,
            "min_free_disk_gb": 2.0,
            "throttle_action": "pause_low_priority"
        }


def _read_host_metrics() -> Dict[str, Any]:
    # D10/HIGH (Disk-Fail-Closed): ein Messfehler ist KEIN Grund zur
    # Entwarnung. Defaults sind die schlechtesten plausiblen Werte, damit
    # Backpressure und Disk-Alarm zuverlaessig ausloesen.
    cpu_pct = 100.0
    ram_pct = 100.0
    measurement_failed: list = []
    try:
        import psutil
        cpu_pct = float(psutil.cpu_percent(interval=0.05))
        ram_pct = float(psutil.virtual_memory().percent)
    except Exception as exc:
        measurement_failed.append("cpu_ram")
        _archon_exc_logger.error("[resource_backpressure] CPU/RAM-Messung fehlgeschlagen: %s", exc)
        try:
            if hasattr(os, "getloadavg"):
                load1, _, _ = os.getloadavg()
                cores = os.cpu_count() or 1
                cpu_pct = round(min(100.0, (load1 / cores) * 100.0), 1)
        except Exception as load_exc:
            _archon_exc_logger.error("[resource_backpressure] Loadavg-Fallback fehlgeschlagen: %s", load_exc)

    free_disk_gb = 0.0
    free_disk_bytes = 0
    disk_used_percent = 100.0
    try:
        usage = shutil.disk_usage(WORKSPACE_DIR)
        # F-077: Roh-Bytes fuer die exakte 2-GiB-Schwelle behalten (das auf
        # 2 Nachkommastellen gerundete free_disk_gb kann 1,999 GiB als 2.0
        # ausgeben und damit den Alarm unterdruecken).
        free_disk_bytes = int(usage.free)
        free_disk_gb = round(free_disk_bytes / (1024 ** 3), 2)
        # shutil.disk_usage liefert kein .percent — selbst berechnen.
        disk_used_percent = round(float(usage.used) / float(usage.total) * 100.0, 1) if usage.total else 100.0
    except Exception as exc:
        measurement_failed.append("disk")
        _archon_exc_logger.error("[resource_backpressure] Disk-Messung fehlgeschlagen: %s", exc)

    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "free_disk_gb": free_disk_gb,
        "free_disk_bytes": free_disk_bytes,
        "disk_used_percent": disk_used_percent,
        "measurement_failed": measurement_failed,
    }


_MIN_FREE_DISK_BYTES = 2 * 1024 ** 3  # F-077: 2 GiB (Prometheus: 2147483648)


def _get_max_disk_usage_percent() -> float:
    """G: guardian 'disk-cleanup'.max_disk_usage_percent (Default 90) als Schwelle lesen."""
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("disk_cleanup")
        if cfg and cfg.get("max_disk_usage_percent") is not None:
            return float(cfg["max_disk_usage_percent"])
    except Exception:
        pass
    try:
        from archon.core.runtime import MEMORY_DIR
        cfg_path = os.path.join(MEMORY_DIR, "plugins_config", "disk-cleanup.json")
        with open(cfg_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict) and saved.get("max_disk_usage_percent") is not None:
            return float(saved["max_disk_usage_percent"])
    except Exception:
        pass
    return 90.0


class ResourceBackpressureProtector:
    def check_health_and_backpressure(self, simulate_overload: bool = False) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        max_cpu = float(cfg.get("max_cpu_pct", 85))
        max_ram = float(cfg.get("max_ram_pct", 85))
        min_disk = float(cfg.get("min_free_disk_gb", 2.0))
        action = str(cfg.get("throttle_action", "pause_low_priority"))

        metrics = _read_host_metrics()
        if simulate_overload:
            metrics["cpu_pct"] = 94.5
            metrics["ram_pct"] = 89.0

        reasons = []
        if enabled:
            if metrics["cpu_pct"] > max_cpu:
                reasons.append(f"CPU ({metrics['cpu_pct']}%) > {max_cpu}%")
            if metrics["ram_pct"] > max_ram:
                reasons.append(f"RAM ({metrics['ram_pct']}%) > {max_ram}%")
            if metrics.get("free_disk_bytes", metrics["free_disk_gb"] * 1024 ** 3) < float(min_disk) * 1024 ** 3:
                reasons.append(f"Disk Free ({metrics['free_disk_gb']} GiB) < {min_disk} GiB")

        backpressure_active = len(reasons) > 0

        # G/F-077: die Disk-Schwelle war bisher reine Config und hatte keine
        # Wirkung. Kritisch: < 2 GiB frei ODER belegt > max_disk_usage_percent
        # (Default 90 %). Nur Alarm/Log — kein harter Stop (zu riskant fuer
        # laufende Dienste). Roh-Bytes vermeiden Rundungs-Unterschleife.
        max_disk_pct = _get_max_disk_usage_percent()
        disk_critical = (
            metrics.get("free_disk_bytes", metrics["free_disk_gb"] * 1024 ** 3) < _MIN_FREE_DISK_BYTES
            or metrics["disk_used_percent"] > max_disk_pct
        )
        try:
            from backend.metrics_collector import report_external_alert
            if disk_critical:
                msg = (
                    f"Kritischer Disk-Platz: {metrics['free_disk_gb']} GiB frei, "
                    f"{metrics['disk_used_percent']} % belegt (Limit {max_disk_pct} %). "
                    f"Empfehlung: {action}."
                )
                _archon_exc_logger.error("[Backpressure] %s", msg)
                report_external_alert(
                    "disk_space_critical", "CRITICAL", "workspace", msg,
                    active=True, title="Kritischer Disk-Platz",
                )
            else:
                report_external_alert("disk_space_critical", "CRITICAL", "workspace", "", active=False)
        except Exception as exc:
            _archon_exc_logger.debug("[Backpressure] Disk-Alarm nicht versendet: %s", exc)

        return {
            "enabled": enabled,
            "simulated": bool(simulate_overload),
            "measurement_failed": list(metrics.get("measurement_failed") or []),
            "disk_critical": disk_critical,
            "backpressure_active": backpressure_active,
            "recommended_action": action if backpressure_active else "normal_operation",
            "overload_reasons": reasons,
            "metrics": metrics,
            "thresholds": {
                "max_cpu_pct": max_cpu,
                "max_ram_pct": max_ram,
                "min_free_disk_gb": min_disk,
                "max_disk_usage_percent": max_disk_pct
            }
        }


resource_backpressure_protector = ResourceBackpressureProtector()

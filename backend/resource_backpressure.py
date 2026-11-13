"""
backend/resource_backpressure.py
Paket 5 (Feature 25): Live-Ressourcen-Protector (Host CPU-, RAM- & Disk-Backpressure).
Misst die aktuelle Systemlast (CPU-Last, RAM-Belegung, freier Festplattenspeicher).
Überschreitet ein Wert die konfigurierten Schwellenwerte (`max_cpu_pct`, `max_ram_pct`, `min_free_disk_gb`),
aktiviert der Protector automatisch Backpressure (Pausieren niedrig priorisierter Hintergrund-Jobs).
"""

import os
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


def _read_host_metrics() -> Dict[str, float]:
    cpu_pct = 15.0
    ram_pct = 35.0
    try:
        import psutil
        cpu_pct = float(psutil.cpu_percent(interval=0.05))
        ram_pct = float(psutil.virtual_memory().percent)
    except Exception:
        try:
            if hasattr(os, "getloadavg"):
                load1, _, _ = os.getloadavg()
                cores = os.cpu_count() or 1
                cpu_pct = round(min(100.0, (load1 / cores) * 100.0), 1)
        except Exception:
            pass

    try:
        usage = shutil.disk_usage(WORKSPACE_DIR)
        free_disk_gb = round(usage.free / (1024 ** 3), 2)
    except Exception:
        free_disk_gb = 25.0

    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "free_disk_gb": free_disk_gb
    }


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
            if metrics["free_disk_gb"] < min_disk:
                reasons.append(f"Disk Free ({metrics['free_disk_gb']} GB) < {min_disk} GB")

        backpressure_active = len(reasons) > 0
        return {
            "enabled": enabled,
            "backpressure_active": backpressure_active,
            "recommended_action": action if backpressure_active else "normal_operation",
            "overload_reasons": reasons,
            "metrics": metrics,
            "thresholds": {
                "max_cpu_pct": max_cpu,
                "max_ram_pct": max_ram,
                "min_free_disk_gb": min_disk
            }
        }


resource_backpressure_protector = ResourceBackpressureProtector()

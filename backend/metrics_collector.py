"""
backend/metrics_collector.py
Zentraler Prometheus- & System-Metriken-Kollektor für Archon OS.
Generiert konforme Metriken im Prometheus Exposition Text-Format (0.0.4)
für Prometheus, Grafana, Uptime Kuma und interne Health-Monitore.
"""

import os
import sys
import time
import sqlite3
import datetime
from typing import Dict, Any, List

START_TIME = time.time()
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolve_db_path(name: str) -> str:
    """Findet den tatsächlichen Pfad einer Datenbank (Host oder Container-Mount)."""
    candidates = [
        f"/opt/data/{name}",
        os.path.expanduser(f"~/.hermes/{name}"),
        os.path.join(WORKSPACE_DIR, "data", name),
        os.path.join(WORKSPACE_DIR, name)
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    return candidates[0]

def get_kanban_db() -> str:
    return resolve_db_path("kanban.db")

def get_memory_db() -> str:
    return resolve_db_path("agentic_memory.db")

def get_state_db() -> str:
    return resolve_db_path("state.db")



class MetricsCollector:
    """Sammelt und formatiert Archon OS Metriken im Prometheus-Format."""

    def __init__(self):
        self.last_scrape_time = 0.0

    def _get_kanban_metrics(self) -> Dict[str, Any]:
        """Liest Task-Status-Zähler und Queue-Tiefe aus kanban.db."""
        counts = {"ready": 0, "in_progress": 0, "review": 0, "done": 0, "blocked": 0, "archived": 0}
        total = 0
        kdb = get_kanban_db()
        if os.path.exists(kdb):
            try:
                conn = sqlite3.connect(kdb, timeout=2.0)
                cur = conn.cursor()
                cur.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
                for st, cnt in cur.fetchall():
                    if st in counts:
                        counts[st] = cnt
                    total += cnt
                conn.close()
            except Exception as e:
                print(f"[MetricsCollector] Fehler beim Lesen von kanban.db ({kdb}): {e}", file=sys.stderr)
        return {"status_counts": counts, "total_tasks": total, "queue_depth": counts.get("ready", 0)}

    def _get_execution_and_telemetry(self) -> Dict[str, Any]:
        """Liest Dispatches, Fehler und Token-Nutzung aus agentic_memory.db."""
        telemetry = {
            "total_dispatches": 0,
            "successful_dispatches": 0,
            "failed_dispatches": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "error_rate_pct": 0.0,
            "daily_cost_est_usd": 0.0
        }
        mdb = get_memory_db()
        if os.path.exists(mdb):
            try:
                conn = sqlite3.connect(mdb, timeout=2.0)
                cur = conn.cursor()
                # Prüfen, ob otel_spans existiert
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='otel_spans'")
                if cur.fetchone():
                    cur.execute("""
                        SELECT 
                            COUNT(*),
                            SUM(CASE WHEN status = 'success' OR status = 'OK' THEN 1 ELSE 0 END),
                            SUM(CASE WHEN status = 'error' OR status = 'failed' THEN 1 ELSE 0 END),
                            SUM(total_tokens),
                            AVG(duration_ms),
                            SUM(cost_usd)
                        FROM otel_spans
                    """)
                    row = cur.fetchone()
                    if row and row[0]:
                        total = row[0] or 0
                        ok = row[1] or 0
                        err = row[2] or 0
                        tokens = row[3] or 0
                        lat = row[4] or 0.0
                        cost = row[5] or 0.0
                        telemetry["total_dispatches"] = total
                        telemetry["successful_dispatches"] = ok
                        telemetry["failed_dispatches"] = err
                        telemetry["total_tokens"] = tokens
                        telemetry["avg_latency_ms"] = round(lat, 2)
                        telemetry["error_rate_pct"] = round((err / total * 100.0), 2) if total > 0 else 0.0
                        telemetry["daily_cost_est_usd"] = round(cost, 4) if cost > 0 else round((tokens / 1000.0) * 0.002, 4)
                conn.close()
            except Exception as e:
                print(f"[MetricsCollector] Fehler beim Lesen von telemetry ({mdb}): {e}", file=sys.stderr)
        return telemetry

    def _get_storage_metrics(self) -> Dict[str, int]:
        """Gibt Dateigrößen in Bytes für die Kern-Datenbanken zurück."""
        sizes = {}
        for name, path in [("kanban_db", get_kanban_db()), ("memory_db", get_memory_db()), ("state_db", get_state_db())]:
            if os.path.exists(path):
                sizes[name] = os.path.getsize(path)
            else:
                sizes[name] = 0
        return sizes

    def _get_system_resources(self) -> Dict[str, Any]:
        """Liest CPU-, RAM- und Prozessdaten."""
        cpu_pct = 0.0
        ram_bytes = 0
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_bytes = mem.used
        except Exception:
            pass
        return {"cpu_percent": cpu_pct, "ram_bytes": ram_bytes}

    def check_and_dispatch_alerts(self, kanban: Dict[str, Any], telemetry: Dict[str, Any]) -> List[str]:
        """Prüft Schwellenwerte und sendet Alarme über den NotificationHub."""
        alerts = []
        try:
            from backend.notification_hub import get_notification_hub
            hub = get_notification_hub()

            # 1. Hohe Fehlerquote (> 25% bei mind. 10 Dispatches)
            if telemetry["total_dispatches"] >= 10 and telemetry["error_rate_pct"] > 25.0:
                msg = f"Kritische Fehlerquote bei Agenten-Aufrufen: {telemetry['error_rate_pct']}% ({telemetry['failed_dispatches']} Fehler bei {telemetry['total_dispatches']} Tasks)."
                hub.dispatch_notification(
                    title="Hohe Agenten-Fehlerquote",
                    message=msg,
                    severity="WARNING",
                    category="telemetry_alert"
                )
                alerts.append(msg)

            # 2. Hohe Warteschlangen-Stagnation (> 50 unbearbeitete Ready-Tasks)
            if kanban["queue_depth"] > 50:
                msg = f"Hohe Task-Queue-Tiefe: {kanban['queue_depth']} Aufgaben warten auf Zuteilung."
                hub.dispatch_notification(
                    title="Task-Queue Stau",
                    message=msg,
                    severity="INFO",
                    category="queue_depth"
                )
                alerts.append(msg)
        except Exception as e:
            print(f"[MetricsCollector] Alerting-Check Fehler: {e}", file=sys.stderr)
        return alerts

    def generate_prometheus_metrics(self) -> str:
        """Erzeugt Text im Prometheus-Format (0.0.4)."""
        now = time.time()
        uptime = round(now - START_TIME, 2)
        kanban = self._get_kanban_metrics()
        telemetry = self._get_execution_and_telemetry()
        storage = self._get_storage_metrics()
        system = self._get_system_resources()

        # Alert-Prüfung alle 60 Sekunden beim Scrape
        if now - self.last_scrape_time > 60:
            self.check_and_dispatch_alerts(kanban, telemetry)
            self.last_scrape_time = now

        lines = [
            "# HELP archon_uptime_seconds Betriebszeit des Archon OS Prozesses in Sekunden.",
            "# TYPE archon_uptime_seconds gauge",
            f"archon_uptime_seconds {uptime}",
            "",
            "# HELP archon_tasks_total Gesamtzahl der Aufgaben im Kanban-Board nach Status.",
            "# TYPE archon_tasks_total gauge",
        ]
        for st, count in kanban["status_counts"].items():
            lines.append(f'archon_tasks_total{{status="{st}"}} {count}')

        lines.extend([
            "",
            "# HELP archon_queue_depth Anzahl der anstehenden Aufgaben in der Queue (ready).",
            "# TYPE archon_queue_depth gauge",
            f"archon_queue_depth {kanban['queue_depth']}",
            "",
            "# HELP archon_agent_dispatches_total Anzahl der durchgefuehrten Agenten-Aufrufe.",
            "# TYPE archon_agent_dispatches_total counter",
            f'archon_agent_dispatches_total{{status="ok"}} {telemetry["successful_dispatches"]}',
            f'archon_agent_dispatches_total{{status="error"}} {telemetry["failed_dispatches"]}',
            "",
            "# HELP archon_agent_error_rate_percent Prozentuale Fehlerquote bei Agenten-Aufrufen.",
            "# TYPE archon_agent_error_rate_percent gauge",
            f"archon_agent_error_rate_percent {telemetry['error_rate_pct']}",
            "",
            "# HELP archon_tokens_total Kumulierte Token-Nutzung aller LLM-Aufrufe.",
            "# TYPE archon_tokens_total counter",
            f"archon_tokens_total {telemetry['total_tokens']}",
            "",
            "# HELP archon_estimated_cost_usd Geschaetzte LLM-Kosten in USD.",
            "# TYPE archon_estimated_cost_usd counter",
            f"archon_estimated_cost_usd {telemetry['daily_cost_est_usd']}",
            "",
            "# HELP archon_database_size_bytes Groesse der SQLite-Datenbankdateien in Bytes.",
            "# TYPE archon_database_size_bytes gauge",
        ])
        for db_name, bsize in storage.items():
            lines.append(f'archon_database_size_bytes{{database="{db_name}"}} {bsize}')

        lines.extend([
            "",
            "# HELP archon_system_cpu_percent Aktuelle CPU-Auslastung in Prozent.",
            "# TYPE archon_system_cpu_percent gauge",
            f"archon_system_cpu_percent {system['cpu_percent']}",
            "",
            "# HELP archon_system_memory_used_bytes Genutzter Arbeitsspeicher in Bytes.",
            "# TYPE archon_system_memory_used_bytes gauge",
            f"archon_system_memory_used_bytes {system['ram_bytes']}",
            ""
        ])

        return "\n".join(lines)

    def get_summary_json(self) -> Dict[str, Any]:
        """Gibt aggregierte Metriken als JSON für Frontend und REST-Clients zurück."""
        kanban = self._get_kanban_metrics()
        telemetry = self._get_execution_and_telemetry()
        storage = self._get_storage_metrics()
        system = self._get_system_resources()
        return {
            "uptime_seconds": round(time.time() - START_TIME, 2),
            "kanban": kanban,
            "telemetry": telemetry,
            "storage_bytes": storage,
            "system": system,
            "timestamp": datetime.datetime.now().isoformat()
        }


metrics_collector = MetricsCollector()

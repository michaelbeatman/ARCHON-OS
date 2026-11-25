"""
backend/metrics_collector.py
Zentraler Prometheus- & System-Metriken-Kollektor für Archon OS.
Generiert konforme Metriken im Prometheus Exposition Text-Format (0.0.4)
für Prometheus, Grafana, Uptime Kuma und interne Health-Monitore.
"""
import logging

_archon_exc_logger = logging.getLogger("metrics_collector")

import datetime
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

START_TIME = time.time()

# D16/MED: Prometheus-Exemplare. Der Scrape-Thread hat KEINEN Request-Kontext,
# daher wird der aktive W3C-Kontext am Chokepoint (child_span-Hop / Middleware)
# in einen begrenzten Ringpuffer geschrieben und beim Rendern der Metriken
# als OpenMetrics-Exemplar angehaengt.
# Der Puffer ist pro (metric_name, series_labels) getrennt: frueher wurde das
# letzte Sample unabhaengig von status/route an die OK-Serie gehaengt (falsche
# Trace-to-Metric-Korrelation bei parallelen Requests).
_EXEMPLAR_MAX = 128
_EXEMPLAR_KEY = Tuple[str, Tuple[Tuple[str, str], ...]]
_TRACE_EXEMPLARS: Dict[_EXEMPLAR_KEY, "deque[Dict[str, Any]]"] = {}
_EXEMPLAR_LOCK = threading.Lock()
_EXEMPLAR_RE = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_DISPATCH_METRIC = "archon_agent_dispatches_total"


def _normalized_status(value: Any) -> str:
    """HTTP-Code oder Statuswort auf die Metriken-Serie ``ok``/``error`` mappen."""
    raw = str(value or "").strip().lower()
    if raw.isdigit():
        return "ok" if int(raw) < 400 else "error"
    if raw in ("ok", "success", "succeeded", "2xx", "3xx"):
        return "ok"
    if raw in ("error", "failed", "failure", "blocked", "5xx", "4xx"):
        return "error"
    return raw


def _series_labels_for(metric_name: str, labels: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Nur die Labels, die auch Bestandteil der Ziel-Serie sind.

    ``archon_agent_dispatches_total`` hat exakt ein ``status``-Label; Route und
    Span-Typ bleiben reine Exemplar-Labels. Alle restlichen Metriken sind
    ungelabelt und landen folglich unter dem leeren Serien-Schluessel.
    """
    raw = dict(labels or {})
    if metric_name == _DISPATCH_METRIC and "status" in raw:
        return {"status": _normalized_status(raw["status"])}
    return {}


def _series_key(series_labels: Optional[Dict[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (series_labels or {}).items()))


def record_trace_exemplar(
    *metric_names: str,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    labels: Optional[Dict[str, Any]] = None,
    series_labels: Optional[Dict[str, Any]] = None,
) -> None:
    """Merkt sich trace_id/span_id aus dem aktiven Kontext fuer /metrics.

    Ohne explizite IDs wird ``backend.trace_context.current_trace_id()`` /
    ``current_span_id()`` gelesen. Ungueltige oder fehlende IDs werden
    verworfen — ein Exemplar darf niemals eine erfundene Kante zeigen.
    Der Ringpuffer wird pro Ziel-Serie gefuehrt; ``series_labels`` kann die
    Ableitung aus ``labels`` explizit ueberschreiben.
    """
    if trace_id is None or span_id is None:
        try:
            from backend.trace_context import current_span_id, current_trace_id

            trace_id = trace_id or current_trace_id()
            span_id = span_id or current_span_id()
        except Exception as exc:
            _archon_exc_logger.warning("[Metrics] Exemplar-Kontext nicht lesbar: %s", exc)
            return
    tid = str(trace_id or "").strip().lower()
    sid = str(span_id or "").strip().lower()
    if not _EXEMPLAR_RE.fullmatch(tid) or not _SPAN_ID_RE.fullmatch(sid):
        return
    sample = {"trace_id": tid, "span_id": sid, "labels": dict(labels or {})}
    with _EXEMPLAR_LOCK:
        for name in metric_names or (_DISPATCH_METRIC,):
            metric = str(name)
            key_series = (
                dict(series_labels)
                if series_labels is not None
                else _series_labels_for(metric, labels)
            )
            buf = _TRACE_EXEMPLARS.setdefault(
                (metric, _series_key(key_series)), deque(maxlen=_EXEMPLAR_MAX)
            )
            buf.append(sample)


def _exemplar_line(
    metric_name: str, value: Any, series_labels: Optional[Dict[str, Any]] = None
) -> str:
    """OpenMetrics-Exemplar-Suffix der PASSENDEN Serie oder leerer String.

    Ohne ``series_labels`` wird die ungelabelte Serie ``()`` gelesen; es wird
    niemals ein Sample einer fremden Serie (z. B. status=error an status=ok)
    ausgewaehlt.
    """
    key = (metric_name, _series_key(_series_labels_for(metric_name, series_labels)))
    with _EXEMPLAR_LOCK:
        buf = _TRACE_EXEMPLARS.get(key)
        sample = dict(buf[-1]) if buf else None
    if not sample:
        return ""
    labels = ",".join(
        [f'trace_id="{sample["trace_id"]}"', f'span_id="{sample["span_id"]}"']
        + [f'{k}="{str(v)}"' for k, v in sorted((sample.get("labels") or {}).items())]
    )
    return f" # {{{labels}}} {value}"


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolve_db_path(name: str) -> str:
    """Autoritativer DB-Resolver (Audit 23.11.2026).

    Vorher hatte der Metriken-Kollektor einen eigenen Kandidaten-Pfad und
    las bei aktiver Mandanten-Isolation eine veraltete/leere Legacy-DB —
    Alerting-Blindflug. Jetzt gilt backend.db_paths.resolve_db als SSOT.
    """
    try:
        from backend.db_paths import resolve_db
        return resolve_db(name)
    except Exception as exc:
        _archon_exc_logger.warning("[Metrics] resolve_db(%s) fehlgeschlagen: %s", name, exc)
        return os.path.join(WORKSPACE_DIR, "data", name)

def get_kanban_db() -> str:
    return resolve_db_path("kanban.db")

def get_memory_db() -> str:
    return resolve_db_path("agentic_memory.db")

def get_state_db() -> str:
    return resolve_db_path("state.db")


# --- Zustandsbasierte Alert-Dedup (Audit-Phase 1) -------------------------
# Der 30-s-Loop und der Prometheus-Scrape rufen denselben Check auf. Ohne
# Inhalts-Dedup ging bei anhaltender Stoerung alle 30 s ein Neuer Alarm raus.
# Key = (alert_type, severity, entity). Wiederholungen eskalieren 1h/6h/24h;
# entfaellt die Bedingung, folgt genau EIN RESOLVED-Event. Kein externer Dienst.
_ALERT_STATE: Dict[tuple, Dict[str, Any]] = {}
_EXTERNAL_ALERTS: Dict[tuple, Dict[str, Any]] = {}
_ALERT_REPEAT_AFTER = (3600.0, 6 * 3600.0, 24 * 3600.0)
_EXTERNAL_ALERT_TTL = 600.0
_LAST_HEARTBEAT_TS = 0.0


def _notification_hub():
    from backend.notification_hub import get_notification_hub
    return get_notification_hub()


def _dispatch_one(key: tuple, info: Dict[str, Any], severity: str, *, resolved: bool = False, repeat: bool = False) -> Optional[str]:
    """Sendet genau ein Event ueber den bestehenden NotificationHub."""
    alert_type, _sev, entity = key
    title = f"[RESOLVED] {info['title']}" if resolved else info["title"]
    if repeat and not resolved:
        title = f"[WIEDERHOLUNG] {title}"
    message = info["message"]
    category = "alert_resolved" if resolved else info.get("category", alert_type)
    try:
        _notification_hub().dispatch_notification(
            title=title,
            message=message,
            severity="INFO" if resolved else severity,
            category=category,
        )
        return message
    except Exception as exc:
        _archon_exc_logger.warning("[Metrics] Alert-Dispatch fehlgeschlagen (%s/%s): %s", alert_type, entity, exc)
        return None


def _sync_alert_state(observed: Dict[tuple, Dict[str, Any]]) -> List[str]:
    """Dedup + Auto-Resolve + eskalierende Wiederholung. Gibt gesendete Events zurueck."""
    now = time.time()
    dispatched: List[str] = []

    # Externe Quellen (z. B. Disk-Backpressure) melden sich selbst ab; wenn
    # sie ganz wegfallen, uebernimmt der TTL die automatische Aufloesung.
    for key, ext in list(_EXTERNAL_ALERTS.items()):
        if (now - float(ext.get("last_seen", 0.0))) > _EXTERNAL_ALERT_TTL:
            _EXTERNAL_ALERTS.pop(key, None)
        else:
            observed.setdefault(key, ext)

    # Auto-Resolve: Bedingung nicht mehr aktiv -> genau ein RESOLVED-Event.
    for key in list(_ALERT_STATE.keys()):
        if key in observed:
            continue
        entry = _ALERT_STATE[key]
        resolved_info = {
            "title": entry.get("title") or key[0],
            "message": f"Bedingung nicht mehr aktiv (Typ {key[0]}, Entitaet {key[2]}). Dauer: {int(now - entry.get('first_seen', now))} s.",
        }
        msg = _dispatch_one(key, resolved_info, "INFO", resolved=True)
        if msg:
            _ALERT_STATE.pop(key, None)
            dispatched.append(msg)

    for key, info in observed.items():
        entry = _ALERT_STATE.get(key)  # type: ignore[assignment]
        escalate = False
        if entry is not None:
            idx = int(entry.get("repeat_index", 0))
            wait = _ALERT_REPEAT_AFTER[min(idx, len(_ALERT_REPEAT_AFTER) - 1)]
            if (now - float(entry.get("last_dispatched", 0.0))) < wait:
                entry["last_seen"] = now
                continue
            escalate = True
        msg = _dispatch_one(key, info, key[1], repeat=escalate)
        if not msg:
            continue
        if entry is None:
            entry = {"first_seen": now, "repeat_index": 0, "title": info["title"]}
            _ALERT_STATE[key] = entry
        entry["last_seen"] = now
        entry["last_dispatched"] = now
        entry["repeat_index"] = int(entry.get("repeat_index", 0)) + (1 if escalate else 0)
        entry["title"] = info["title"]
        dispatched.append(msg)

    return dispatched


def report_external_alert(
    alert_type: str,
    severity: str,
    entity: str,
    message: str,
    *,
    active: bool = True,
    title: Optional[str] = None,
) -> None:
    """Alarm anderer Module (Disk, Self-Healing) in dieselbe Dedup-Kette einspeisen.

    `active=False` nimmt den Alarm aus dem Snapshot; der naechste Check
    erzeugt dann das RESOLVED-Event. Kein neuer Service, kein Alertmanager.
    """
    key = (str(alert_type), str(severity), str(entity))
    if not active:
        _EXTERNAL_ALERTS.pop(key, None)
        return
    _EXTERNAL_ALERTS[key] = {
        "title": title or str(alert_type).replace("_", " ").title(),
        "message": str(message),
        "category": str(alert_type),
        "last_seen": time.time(),
    }


def touch_heartbeat() -> float:
    """Lebenszeichen des aktiven Prozesses (vom 30-s-Alert-Loop gepflegt)."""
    global _LAST_HEARTBEAT_TS
    _LAST_HEARTBEAT_TS = time.time()
    return _LAST_HEARTBEAT_TS


def get_last_heartbeat_ts() -> float:
    return _LAST_HEARTBEAT_TS


class MetricsCollector:
    """Sammelt und formatiert Archon OS Metriken im Prometheus-Format."""

    def __init__(self):
        self.last_scrape_time = 0.0

    def _get_kanban_metrics(self) -> Dict[str, Any]:
        """Liest Task-Status-Zähler und Queue-Tiefe aus kanban.db."""
        counts = {"todo": 0, "ready": 0, "in_progress": 0, "review": 0, "done": 0, "blocked": 0, "archived": 0}
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
        return {
            "status_counts": counts,
            "total_tasks": total,
            "queue_depth": counts.get("todo", 0) + counts.get("ready", 0),
        }

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
                            SUM(CASE WHEN LOWER(status) IN ('success', 'ok') THEN 1 ELSE 0 END),
                            SUM(CASE WHEN LOWER(status) IN ('error', 'failed') THEN 1 ELSE 0 END),
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
        except Exception as _exc:
            _archon_exc_logger.debug("[metrics_collector] Ignorierte Ausnahme (Z.139): %s", _exc)
        return {"cpu_percent": cpu_pct, "ram_bytes": ram_bytes}

    def check_and_dispatch_alerts(
        self,
        kanban: Optional[Dict[str, Any]] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Prüft Schwellenwerte und sendet Alarme über den NotificationHub.

        Beide Argumente sind optional: ohne Argumente werden die Werte frisch
        aus den DBs gelesen. Damit ist die Funktion unabhängig vom
        ``/metrics``-Scrape aufrufbar (Commit des main.py-Loops).
        """
        if kanban is None:
            kanban = self._get_kanban_metrics()
        if telemetry is None:
            telemetry = self._get_execution_and_telemetry()
        observed: Dict[tuple, Dict[str, Any]] = {}

        # 1. Hohe Fehlerquote (> 25% bei mind. 10 Dispatches)
        if telemetry["total_dispatches"] >= 10 and telemetry["error_rate_pct"] > 25.0:
            msg = f"Kritische Fehlerquote bei Agenten-Aufrufen: {telemetry['error_rate_pct']}% ({telemetry['failed_dispatches']} Fehler bei {telemetry['total_dispatches']} Tasks)."
            observed[("agent_error_rate", "WARNING", "agent_dispatch")] = {
                "title": "Hohe Agenten-Fehlerquote",
                "message": msg,
                "category": "telemetry_alert",
            }

        # 2. Hohe Warteschlangen-Stagnation (> 50 unbearbeitete Ready-Tasks)
        if kanban["queue_depth"] > 50:
            msg = f"Hohe Task-Queue-Tiefe: {kanban['queue_depth']} Aufgaben warten auf Zuteilung."
            observed[("task_queue_depth", "INFO", "kanban_queue")] = {
                "title": "Task-Queue Stau",
                "message": msg,
                "category": "queue_depth",
            }

        try:
            alerts = _sync_alert_state(observed)
        except Exception as e:
            print(f"[MetricsCollector] Alerting-Check Fehler: {e}", file=sys.stderr)
            alerts = []
        return {
            "dispatched": len(alerts),
            "alerts": alerts,
            "active_alerts": len(_ALERT_STATE),
            "checked_at": datetime.datetime.now().isoformat(),
        }

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
            "# HELP archon_heartbeat_timestamp_seconds Letztes Lebenszeichen des aktiven Prozesses als Unix-Timestamp.",
            "# TYPE archon_heartbeat_timestamp_seconds gauge",
            f"archon_heartbeat_timestamp_seconds {float(_LAST_HEARTBEAT_TS):.6f}",
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
            f'archon_agent_dispatches_total{{status="ok"}} {telemetry["successful_dispatches"]}'
            + _exemplar_line(
                _DISPATCH_METRIC, telemetry["successful_dispatches"], {"status": "ok"}
            ),
            f'archon_agent_dispatches_total{{status="error"}} {telemetry["failed_dispatches"]}'
            + _exemplar_line(
                _DISPATCH_METRIC, telemetry["failed_dispatches"], {"status": "error"}
            ),
            "",
            "# HELP archon_agent_error_rate_percent Prozentuale Fehlerquote bei Agenten-Aufrufen.",
            "# TYPE archon_agent_error_rate_percent gauge",
            f"archon_agent_error_rate_percent {telemetry['error_rate_pct']}",
            "",
            "# HELP archon_tokens_total Kumulierte Token-Nutzung aller LLM-Aufrufe.",
            "# TYPE archon_tokens_total counter",
            f"archon_tokens_total {telemetry['total_tokens']}"
            + _exemplar_line("archon_tokens_total", telemetry["total_tokens"]),
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

        # Disk-Alarm: echter freier Platz des Workspace-Volumens (kein
        # node_exporter nötig). Bei Fehler negative Werte -> Alert greift nicht.
        try:
            _du = shutil.disk_usage(WORKSPACE_DIR)
            _free_bytes = int(_du.free)
            _disk_pct = round(float(_du.used) / float(_du.total) * 100.0, 1) if _du.total else -1
        except Exception:
            _free_bytes, _disk_pct = -1, -1
        lines.extend([
            "",
            "# HELP archon_free_disk_bytes Freier Diskplatz des Workspace-Volumens in Bytes.",
            "# TYPE archon_free_disk_bytes gauge",
            f"archon_free_disk_bytes {_free_bytes}",
            "",
            "# HELP archon_disk_used_percent Belegter Diskplatz des Workspace-Volumens in Prozent.",
            "# TYPE archon_disk_used_percent gauge",
            f"archon_disk_used_percent {_disk_pct}",
        ])

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

        # OpenMetrics-Abschluss: Prometheus nutzt Exemplare nur bei gueltigem
        # OpenMetrics-Payload (Content-Type in main.py:/metrics).
        return "\n".join(lines) + "\n# EOF\n"

    def get_summary_json(self) -> Dict[str, Any]:
        """Gibt aggregierte Metriken als JSON für Frontend und REST-Clients zurück."""
        kanban = self._get_kanban_metrics()
        telemetry = self._get_execution_and_telemetry()
        storage = self._get_storage_metrics()
        system = self._get_system_resources()
        return {
            "uptime_seconds": round(time.time() - START_TIME, 2),
            "heartbeat_timestamp_seconds": float(_LAST_HEARTBEAT_TS),
            "kanban": kanban,
            "telemetry": telemetry,
            "storage_bytes": storage,
            "system": system,
            "timestamp": datetime.datetime.now().isoformat()
        }


metrics_collector = MetricsCollector()


# Eigene 60s-Funktion fuer main.py: Alerting passiert auch dann, wenn niemand
# Prometheus scrappt. Der Scrape ruft check_and_dispatch_alerts() weiterhin
# direkt; dieser Hook ist zusaetzlich und idempotent im Intervall. Die
# Inhalts-Dedup liegt in _sync_alert_state() und greift auch bei force=True.
_LAST_ALERT_DISPATCH_TS = 0.0


def check_and_dispatch_alerts_now(force: bool = False) -> Dict[str, Any]:
    """Einmalige Alert-Pruefung (min. 60s Abstand), unabhaengig vom Scrape."""
    global _LAST_ALERT_DISPATCH_TS
    now = time.time()
    # Jeder Aufruf ist ein Lebenszeichen des Hauptprozesses (Self-Healing F).
    touch_heartbeat()
    if not force and (now - _LAST_ALERT_DISPATCH_TS) < 60:
        return {"dispatched": 0, "alerts": [], "skipped": "interval", "checked_at": datetime.datetime.now().isoformat()}
    _LAST_ALERT_DISPATCH_TS = now
    return metrics_collector.check_and_dispatch_alerts()


async def alert_dispatch_loop(interval_seconds: int = 60) -> None:
    """Hintergrund-Loop, der von main.py als Background-Task gestartet wird."""
    import asyncio
    while True:
        try:
            await asyncio.to_thread(check_and_dispatch_alerts_now, True)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"[MetricsCollector] Alert-Dispatch-Loop Fehler: {exc}", file=sys.stderr)
        await asyncio.sleep(max(5, int(interval_seconds)))

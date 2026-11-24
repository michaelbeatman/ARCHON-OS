# -*- coding: utf-8 -*-
"""Audit D10: Dead-Man-Switch ueber Prometheus-Metrik + absent()-Regel.

Die expiring Alertmanager-POSTs sind entfernt: bei Ausfall lieferte
Alertmanager 'resolved/info' statt 'firing/critical' (semantisch invertiert).
Der echte Dead-Man ist die Gauge `archon_heartbeat_timestamp_seconds` plus
die Regeln `time() - ... > 300` und `absent(...)`.
"""
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_heartbeat_metric_is_exported_to_prometheus():
    from backend import metrics_collector as mc

    mc.touch_heartbeat()
    ts = mc.get_last_heartbeat_ts()
    assert ts > 0
    assert abs(time.time() - ts) < 10

    text = mc.MetricsCollector().generate_prometheus_metrics()
    assert "# TYPE archon_heartbeat_timestamp_seconds gauge" in text
    assert "archon_heartbeat_timestamp_seconds " in text


def test_dead_man_rules_watch_metric_and_absence():
    rules = (ROOT / "config" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "time() - archon_heartbeat_timestamp_seconds > 300" in rules
    assert "absent(archon_heartbeat_timestamp_seconds)" in rules
    assert "ArchonHeartbeatStale" in rules
    assert "ArchonHeartbeatMetricAbsent" in rules
    assert "severity: critical" in rules
    assert "slo: dead_man_switch" in rules


def test_expiring_alertmanager_posts_are_removed():
    from backend import fleet_self_healing as fsh

    assert not hasattr(fsh, "_ALERTMANAGER_LAST_TS")
    assert not hasattr(fsh, "_post_alertmanager_heartbeat")
    src = (ROOT / "backend" / "fleet_self_healing.py").read_text(encoding="utf-8")
    assert "_ALERTMANAGER_LAST_TS" not in src
    assert "endsAt" not in src

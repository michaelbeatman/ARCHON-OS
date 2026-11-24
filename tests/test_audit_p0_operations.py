"""Audit D10/P0: Produktiv-Deploy, Readiness, Dead-Man-Switch, DR-Ziel."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ansible_uses_production_compose_and_readyz():
    vars_text = (ROOT / "ansible/roles/archon_node/vars/main.yml").read_text(encoding="utf-8")
    assert 'archon_compose_file: "docker-compose.yml"' in vars_text
    tasks_text = (ROOT / "ansible/roles/archon_node/tasks/main.yml").read_text(encoding="utf-8")
    assert "archon_readycheck_url" in tasks_text
    assert "--remove-orphans" in tasks_text


def test_dead_man_switch_has_env_override_and_status():
    text = (ROOT / "backend/fleet_self_healing.py").read_text(encoding="utf-8")
    ast.parse(text)
    assert "ARCHON_HEARTBEAT_WEBHOOK_URL" in text
    assert "dead_man_switch_configured" in text


def test_otel_collector_wired_from_p1_handoff():
    import yaml

    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    collector = (doc.get("services") or {}).get("otel-collector")
    assert collector is not None
    assert "4317" in str(collector.get("ports", ""))
    assert "4318" in str(collector.get("ports", ""))
    assert "tracing" in (collector.get("profiles") or [])
    assert "OTEL_SERVICE_NAME" in text


def test_dr_replica_is_configurable():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ARCHON_LITESTREAM_REPLICA_DIR" in compose
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ARCHON_LITESTREAM_REPLICA_DIR" in env_example
    assert "ARCHON_HEARTBEAT_WEBHOOK_URL" in env_example

"""Audit D10/D08: Docker-Healthcheck auf /livez, Heartbeat-Env, UI-Batches."""

from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_healthcheck_uses_livez_and_injects_heartbeat():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    hc = doc["services"]["archon-os"]["healthcheck"]["test"]
    assert any("localhost:8501/livez" in str(x) for x in hc), hc
    env = doc["services"]["archon-os"]["environment"]
    assert any(str(x).startswith("ARCHON_HEARTBEAT_WEBHOOK_URL=") for x in env)


def test_prompt_studio_batches_and_debounces():
    text = (ROOT / "static/js/prompt_studio.js").read_text(encoding="utf-8")
    assert "let spVisibleCount = 60" in text
    assert "}, 180);" in text
    assert "function spLoadMore()" in text
    assert "filtered.slice(0, spVisibleCount)" in text

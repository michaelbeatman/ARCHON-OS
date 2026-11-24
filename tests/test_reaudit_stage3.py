"""Re-Audit Etappe 3 — D06: OmniRoute-Key darf nicht nach openrouter.ai fliessen."""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.omniroute_healthcheck as oh

ROOT = Path(__file__).resolve().parents[1]


def test_d06_candidates_uses_only_external_key():
    src = (ROOT / "scripts" / "omniroute_healthcheck.py").read_text(encoding="utf-8")
    block = src.split("def candidates(", 1)[1].split("\ndef ", 1)[0]
    assert "extern_key" in block
    assert "{key}" not in block
    assert "OPENROUTER_API_KEY" in src
    assert "candidates(extern_key, set(models))" in src


def test_d06_candidates_fails_closed_without_key():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        oh.candidates("", set())


def test_d06_env_first_prefers_environment(monkeypatch):
    monkeypatch.setenv("ARCHON_TEST_ALLOWLIST", " model-a,model-b ")
    assert oh._env_first("ARCHON_TEST_ALLOWLIST") == "model-a,model-b"

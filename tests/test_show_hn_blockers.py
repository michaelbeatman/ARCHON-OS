"""Verification tests for the Show HN blockers (i18n SOUL sync, OmniRoute fallback, auth_gate RBAC)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sync_soul_modes_defaults_to_en_and_writes_english_prompts(tmp_path, monkeypatch):
    from scripts import sync_soul_modes as ssm

    monkeypatch.delenv("ARCHON_LANGUAGE", raising=False)
    monkeypatch.setattr(ssm, "SETTINGS_PATHS", [str(tmp_path / "missing_settings.json")])
    assert ssm.resolve_soul_language() == "en"
    assert ssm.resolve_soul_language("de") == "de"
    monkeypatch.setenv("ARCHON_LANGUAGE", "de_DE")
    assert ssm.resolve_soul_language() == "de"

    # Full isolated compact sync with ARCHON_LANGUAGE=en
    app_root = tmp_path / "app"
    hermes_dir = tmp_path / "hermes" / "profiles"
    app_root.mkdir()
    hermes_dir.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "agent_profiles.json", app_root / "agent_profiles.json")

    monkeypatch.setenv("ARCHON_LANGUAGE", "en")
    monkeypatch.setattr(ssm, "APP_ROOT", str(app_root))
    monkeypatch.setattr(ssm, "PROFILES_JSON_PATH", str(app_root / "agent_profiles.json"))
    monkeypatch.setattr(ssm, "SETTINGS_PATHS", [str(app_root / "settings.json")])
    monkeypatch.setattr(ssm, "get_profile_directories", lambda: [str(hermes_dir)])

    res = ssm.apply_soul_mode(mode="compact", lang="en")
    assert res["status"] == "success"
    assert res["lang"] == "en"
    expected_count = len(json.loads((app_root / "agent_profiles.json").read_text(encoding="utf-8")))
    assert expected_count >= 70
    assert res["updated_profiles"] == expected_count

    updated = json.loads((app_root / "agent_profiles.json").read_text(encoding="utf-8"))
    for prof in updated:
        assert "Antworte auf Deutsch" not in prof["prompt"], prof["id"]
        assert "Antworte auf Deutsch" not in prof["system_prompt"], prof["id"]
        soul_txt = (hermes_dir / prof["id"] / "SOUL.md").read_text(encoding="utf-8")
        assert "Antworte auf Deutsch" not in soul_txt, prof["id"]


def test_core_dispatcher_omniroute_alias_and_ollama_fallback(monkeypatch):
    import asyncio
    import core_dispatcher as cd

    assert cd._resolve_openrouter_fallback_model("omniroute/best-reasoning") == "deepseek/deepseek-r1"
    assert cd._resolve_openrouter_fallback_model("omniroute/free-forever") == "google/gemini-2.5-flash"
    assert cd._resolve_openrouter_fallback_model("omniroute/deepseek-coder") == "deepseek/deepseek-chat"

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    posted_urls = []

    class FakeResp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.text = json.dumps(payload)

        def json(self):
            return json.loads(self.text)

    async def fake_post(url, **kwargs):
        posted_urls.append((url, kwargs.get("json", {}).get("model")))
        if "11434" in url:
            return FakeResp(200, {"choices": [{"message": {"content": "Local Ollama fallback response OK"}}]})
        raise ConnectionError("omniroute unreachable")

    fake_client = SimpleNamespace(post=fake_post)
    monkeypatch.setattr(cd, "_get_dispatcher_http_client", lambda: fake_client)

    with patch("api_provider.collect_keys", return_value={}):
        res = asyncio.run(
            cd._dispatch_to_omniroute_or_container_exec(
                agent_id="hermes-orchestrator",
                agent_name="Hermes Master Orchestrator",
                prompt="Say hello cleanly",
                model="omniroute/best-reasoning",
                provider="omniroute",
            )
        )

    assert res["status"] == "success"
    assert res["provider"] == "ollama"
    assert "Local Ollama fallback response OK" in res["content"]
    assert any("11434" in u for u, _ in posted_urls)


def test_auth_gate_blocks_viewer_writes_and_allows_reads_and_auth(monkeypatch):
    import main as app_main

    monkeypatch.setattr("utils.rate_limit._enabled", lambda: False)
    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        app_main.auth_service,
        "verify_session",
        lambda tok: {"id": "u_v", "username": "viewer1", "role": "viewer", "permissions": {}}
        if tok == "tok_viewer"
        else (
            {"id": "u_a", "username": "anon", "role": "anonymous", "permissions": {}}
            if tok == "tok_anon"
            else {"id": "u_op", "username": "op1", "role": "operator", "permissions": {}}
        ),
    )

    client = TestClient(app_main.app)

    # Viewer & anonymous get 403 on write endpoints
    for tok in ("tok_viewer", "tok_anon"):
        r = client.post(
            "/api/kanban",
            json={"title": "Test"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 403

    # Viewer can still read GET endpoints
    r_get = client.get("/api/auth/me", headers={"Authorization": "Bearer tok_viewer"})
    assert r_get.status_code == 200

    # /api/auth/* logout stays reachable for viewer
    r_logout = client.post("/api/auth/logout", headers={"Authorization": "Bearer tok_viewer"})
    assert r_logout.status_code == 200

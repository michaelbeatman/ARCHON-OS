"""
Tests for Milestone 30: Interactive First-Run Web Setup Wizard & Onboarding.

All filesystem paths are strictly redirected to pytest's `tmp_path` via an
`autouse=True` fixture so real `settings.json`, `agent_workspace/settings.json`,
`data/tenants/primary/company_profile.json`, and `.env` are NEVER mutated.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.routers import _rbac
from archon.routers.auth import require_admin
from archon.routers.onboarding import router as onboarding_router
from backend import onboarding_wizard
from backend.auth_service import auth_service

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_onboarding_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    """Redirects every onboarding path and env variable away from the real repository."""
    root_settings = tmp_path / "settings.json"
    ws_settings = tmp_path / "agent_workspace" / "settings.json"
    tenant_profile = tmp_path / "data" / "tenants" / "primary" / "company_profile.json"
    env_file = tmp_path / ".env"
    profiles_file = tmp_path / "agent_profiles.json"

    monkeypatch.setattr(onboarding_wizard, "ROOT_SETTINGS_FILE", str(root_settings))
    monkeypatch.setattr(onboarding_wizard, "WORKSPACE_SETTINGS_FILE", str(ws_settings))
    monkeypatch.setattr(onboarding_wizard, "TENANT_PROFILE_FILE", str(tenant_profile))
    monkeypatch.setattr(onboarding_wizard, "ENV_FILE", str(env_file))
    monkeypatch.setattr(onboarding_wizard, "PROFILES_FILE", str(profiles_file))

    for env_var in (
        "ARCHON_DEMO_MODE",
        "ARCHON_LANGUAGE",
        "PRIVACY_ZERO_EGRESS",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OLLAMA_BASE_URL",
        "LM_STUDIO_URL",
        "OMNIROUTE_API_KEY",
        "OMNIROUTE_URL",
        "SMTP_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(env_var, raising=False)

    # Wire standard single-user RBAC fallback unless overridden in a specific test
    monkeypatch.setattr(auth_service, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(_rbac, "_checker", require_admin)

    return {
        "tmp": tmp_path,
        "root_settings": root_settings,
        "ws_settings": ws_settings,
        "tenant_profile": tenant_profile,
        "env_file": env_file,
        "profiles_file": profiles_file,
    }


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(onboarding_router)
    return TestClient(app)


class _DummyResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def test_fresh_status_auto_opens_with_8_domains_and_70_specialists(client: TestClient) -> None:
    resp = client.get("/api/onboarding/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert data["auto_open"] is True
    assert data["should_show_wizard"] is True
    assert data["onboarding_completed"] is False
    assert data["dismissed"] is False
    assert data["demo_mode"] is False
    assert data["language"] == "en"
    assert data["total_domains"] == 8
    assert data["total_specialists"] == 70
    assert len(data["specialist_domains"]) == 8
    assert sum(d["specialist_count"] for d in data["specialist_domains"]) == 70

    expected_providers = {
        "openrouter",
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "ollama",
        "lm_studio",
        "omniroute",
    }
    assert set(data["detected_providers"].keys()) == expected_providers
    assert all(isinstance(v, bool) and v is False for v in data["detected_providers"].values())


def test_status_masks_all_secrets_and_exposes_booleans_only(
    client: TestClient,
    isolated_onboarding_paths: Dict[str, Path],
) -> None:
    env_file = isolated_onboarding_paths["env_file"]
    secret_or = "sk-or-v1-ULTRA_SECRET_OPENROUTER_KEY_9911"
    secret_oa = "sk-proj-ULTRA_SECRET_OPENAI_KEY_8822"
    secret_tg = "77665544:AAH_SUPER_SECRET_TELEGRAM_TOKEN_XYZ"
    secret_pw = "SuperSecretSmtpAppPassword!42"

    env_file.write_text(
        "\n".join(
            [
                f"OPENROUTER_API_KEY={secret_or}",
                f"OPENAI_API_KEY={secret_oa}",
                f"TELEGRAM_BOT_TOKEN={secret_tg}",
                f"SMTP_PASSWORD={secret_pw}",
                "ARCHON_LANGUAGE=de",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resp = client.get("/api/onboarding/status")
    assert resp.status_code == 200
    raw_body = resp.text
    for secret in (secret_or, secret_oa, secret_tg, secret_pw, "9911", "8822"):
        assert secret not in raw_body, f"Secret fragment leaked in status response: {secret}"

    data = resp.json()
    assert data["language"] == "de"
    assert data["detected_providers"]["openrouter"] is True
    assert data["detected_providers"]["openai"] is True
    assert data["detected_providers"]["anthropic"] is False
    assert data["detected_providers"]["gemini"] is False
    assert data["channels"]["telegram_bot_configured"] is True
    assert data["channels"]["email_password_configured"] is True


def test_provider_connection_cloud_and_local_probes_mocked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: List[Dict[str, Any]] = []

    class FakeHttpxClient:
        def __init__(self, *, timeout: float = 5.0, follow_redirects: bool = False) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self) -> "FakeHttpxClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str, headers: Dict[str, str] | None = None) -> _DummyResponse:
            captured_calls.append(
                {
                    "url": url,
                    "headers": dict(headers or {}),
                    "timeout": self.timeout,
                    "follow_redirects": self.follow_redirects,
                }
            )
            if "11434/api/tags" in url:
                return _DummyResponse(200, {"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:14b"}]})
            if "googleapis.com" in url:
                return _DummyResponse(200, {"models": [{"name": "models/gemini-2.5-flash"}]})
            return _DummyResponse(200, {"data": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]})

    monkeypatch.setattr(onboarding_wizard.httpx, "Client", FakeHttpxClient)

    # 1. OpenRouter cloud probe via API endpoint
    r1 = client.post(
        "/api/onboarding/test-provider",
        json={"provider": "openrouter", "api_key": "sk-or-test-key"},
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["ok"] is True
    assert d1["provider"] == "openrouter"
    assert d1["models_detected"] == 3
    assert isinstance(d1["latency_ms"], (int, float)) and d1["latency_ms"] >= 0
    assert captured_calls[-1]["url"] == "https://openrouter.ai/api/v1/models"
    assert captured_calls[-1]["headers"]["Authorization"] == "Bearer sk-or-test-key"
    assert captured_calls[-1]["timeout"] == 5.0
    assert captured_calls[-1]["follow_redirects"] is False

    # 2. Gemini uses x-goog-api-key header (never leaking key into URL query string)
    r2 = client.post(
        "/api/onboarding/test-provider",
        json={"provider": "gemini", "api_key": "AIzaSyTestKey123"},
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    assert r2.json()["models_detected"] == 1
    assert "AIzaSyTestKey123" not in captured_calls[-1]["url"]
    assert captured_calls[-1]["headers"]["x-goog-api-key"] == "AIzaSyTestKey123"

    # 3. Ollama local probe (host.docker.internal allowed, no API key required)
    r3 = client.post(
        "/api/onboarding/test-provider",
        json={"provider": "ollama", "base_url": "http://host.docker.internal:11434"},
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["ok"] is True
    assert d3["models_detected"] == 2
    assert captured_calls[-1]["url"] == "http://host.docker.internal:11434/api/tags"


def test_provider_connection_ssrf_guard_blocks_unsafe_urls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_if_network_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("httpx.Client must never be invoked for SSRF-rejected URLs!")

    monkeypatch.setattr(onboarding_wizard.httpx, "Client", _fail_if_network_called)

    unsafe_cases = [
        # Cloud provider downgraded to plain HTTP
        ("openai", "sk-test", "http://api.openai.com/v1"),
        # Cloud provider redirected to attacker host
        ("openrouter", "sk-test", "https://attacker.example.com/v1"),
        # Cloud provider pointing at loopback
        ("anthropic", "sk-test", "https://127.0.0.1:8501/v1"),
        # Local provider pointing at cloud metadata IP
        ("ollama", "", "http://169.254.169.254/latest/meta-data"),
        # Local provider pointing at RFC1918 LAN IP
        ("lm_studio", "", "http://192.168.1.40:1234/v1"),
        # Local provider pointing at external internet host
        ("omniroute", "", "https://evil.example.org/v1"),
        # Local provider with embedded URL credentials
        ("ollama", "", "http://admin:secret@localhost:11434"),
        # Local provider targeting blocked Docker socket proxy port 2375
        ("ollama", "", "http://localhost:2375"),
    ]

    for provider, key, bad_url in unsafe_cases:
        res = client.post(
            "/api/onboarding/test-provider",
            json={"provider": provider, "api_key": key, "base_url": bad_url},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is False, f"Expected SSRF rejection for {provider} -> {bad_url}"
        assert "SSRF" in body["detail"] or "rejected" in body["detail"]


def test_complete_4_steps_persists_atomically_chmods_env_600_and_syncs_souls(
    client: TestClient,
    isolated_onboarding_paths: Dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import sync_soul_modes

    soul_calls: List[Dict[str, Any]] = []

    def _mock_apply_soul_mode(mode: str = "compact", target_agent_id: str | None = None, lang: str | None = None) -> Dict[str, Any]:
        soul_calls.append({"mode": mode, "lang": lang})
        return {"status": "success", "mode": mode, "updated_profiles": 70}

    monkeypatch.setattr(sync_soul_modes, "apply_soul_mode", _mock_apply_soul_mode)

    payload = {
        "company_profile": {
            "company_name": "Nordlicht Ventures GmbH",
            "legal_form": "GmbH",
            "address": "Hafenplatz 10, 20457 Hamburg, Germany",
            "tax_id": "48/712/00123",
            "vat_id": "de 123456789",
            "iban": "DE89 3704 0044 0532 0130 00",
            "bic": "COBADEFFXXX",
            "currency": "eur",
            "language": "de",
        },
        "zero_egress": True,
        "providers": {
            "api_keys": {
                "openrouter": "sk-or-v1-live-test-12345",
                "groq": "gsk_live_test_67890",
            },
            "base_urls": {
                "ollama": "http://localhost:11434",
            },
        },
        "channels": {
            "imap_host": "imap.nordlicht.example",
            "imap_port": 993,
            "smtp_host": "smtp.nordlicht.example",
            "smtp_port": 587,
            "email_user": "ops@nordlicht.example",
            "email_password": "AppPasswordSecret99!",
            "bot_token": "123456789:ABCDEF_bot_token_1234567890",
            "chat_id": "987654321",
            "obsidian_vault_path": "/srv/vaults/nordlicht",
        },
        "active_domains": [
            "strategy_leadership",
            "legal_tax_compliance",
            "sales_crm_growth",
            "tech_software_data",
        ],
    }

    resp = client.post("/api/onboarding/complete", json=payload)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "ok"
    assert out["onboarding_completed"] is True
    assert out["completed_at"].endswith("Z")
    assert out["providers"]["zero_egress"] is True
    assert out["providers"]["detected_providers"]["openrouter"] is True
    assert out["providers"]["detected_providers"]["groq"] is True
    assert out["domains"]["active_domain_count"] == 4
    assert out["domains"]["active_specialists"] == 12 + 11 + 11 + 8
    assert out["domains"]["soul_sync"]["synced"] is True
    assert soul_calls == [{"mode": "compact", "lang": "de"}]

    # Ensure zero raw secrets leaked in completion response
    for secret in ("sk-or-v1-live-test-12345", "gsk_live_test_67890", "AppPasswordSecret99!", "ABCDEF_bot_token"):
        assert secret not in resp.text

    # Verify tenant profile JSON
    tenant_doc = json.loads(isolated_onboarding_paths["tenant_profile"].read_text(encoding="utf-8"))
    assert tenant_doc["tenant_id"] == "primary"
    assert tenant_doc["company_name"] == "Nordlicht Ventures GmbH"
    assert tenant_doc["vat_id"] == "DE123456789"
    assert tenant_doc["currency"] == "EUR"
    assert tenant_doc["language"] == "de"

    # Verify BOTH settings.json and agent_workspace/settings.json
    for sp in (isolated_onboarding_paths["root_settings"], isolated_onboarding_paths["ws_settings"]):
        assert sp.exists()
        raw_txt = sp.read_text(encoding="utf-8")
        assert "AppPasswordSecret99!" not in raw_txt
        assert "ABCDEF_bot_token" not in raw_txt
        sdata = json.loads(raw_txt)
        assert sdata["onboarding_completed"] is True
        assert sdata["onboarding"]["completed"] is True
        assert sdata["privacy"]["zero_egress"] is True
        assert sdata["active_domains"] == [
            "strategy_leadership",
            "legal_tax_compliance",
            "sales_crm_growth",
            "tech_software_data",
        ]
        assert sdata["channels"]["email"]["password_configured"] is True
        assert sdata["channels"]["telegram"]["bot_token_configured"] is True
        assert sdata["obsidian"]["vault_path"] == "/srv/vaults/nordlicht"

    # Verify .env has strict 0600 permissions and holds secrets
    env_file = isolated_onboarding_paths["env_file"]
    assert env_file.exists()
    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    assert mode == 0o600, f"Expected 0600 on .env, got {oct(mode)}"
    parsed_env = onboarding_wizard.parse_env_file(str(env_file))
    assert parsed_env["OPENROUTER_API_KEY"] == "sk-or-v1-live-test-12345"
    assert parsed_env["GROQ_API_KEY"] == "gsk_live_test_67890"
    assert parsed_env["PRIVACY_ZERO_EGRESS"] == "true"
    assert parsed_env["SMTP_PASSWORD"] == "AppPasswordSecret99!"
    assert parsed_env["TELEGRAM_BOT_TOKEN"] == "123456789:ABCDEF_bot_token_1234567890"

    # Subsequent status call must NOT auto-open wizard
    status_after = client.get("/api/onboarding/status").json()
    assert status_after["auto_open"] is False
    assert status_after["onboarding_completed"] is True


def test_complete_preserves_existing_secrets_when_masked_or_empty(
    client: TestClient,
    isolated_onboarding_paths: Dict[str, Path],
) -> None:
    env_file = isolated_onboarding_paths["env_file"]
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-keep-me-intact\nTELEGRAM_BOT_TOKEN=998877:KEEP_TG_TOKEN_INTACT_123456\n",
        encoding="utf-8",
    )

    resp = client.post(
        "/api/onboarding/complete",
        json={
            "company_profile": {"company_name": "Keep Secrets Corp", "language": "en"},
            "providers": {
                "api_keys": {
                    "openrouter": "••••••••tact",
                    "openai": "",
                    "anthropic": "sk-ant-newly-added-key",
                }
            },
            "channels": {
                "bot_token": "",
                "chat_id": "112233",
            },
        },
    )
    assert resp.status_code == 200
    parsed = onboarding_wizard.parse_env_file(str(env_file))
    assert parsed["OPENROUTER_API_KEY"] == "sk-or-keep-me-intact"
    assert parsed["TELEGRAM_BOT_TOKEN"] == "998877:KEEP_TG_TOKEN_INTACT_123456"
    assert parsed["ANTHROPIC_API_KEY"] == "sk-ant-newly-added-key"
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600


def test_upfront_validation_prevents_partial_writes_and_soul_failure_is_safe(
    client: TestClient,
    isolated_onboarding_paths: Dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Invalid domain in Step 4 must abort BEFORE writing Step 1 tenant_profile
    bad_resp = client.post(
        "/api/onboarding/complete",
        json={
            "company_profile": {"company_name": "Atomic Check Inc", "language": "en"},
            "active_domains": ["non_existent_domain_xyz"],
        },
    )
    assert bad_resp.status_code == 400
    assert not isolated_onboarding_paths["tenant_profile"].exists()

    # 2. Non-blocking soul mode sync: exception inside apply_soul_mode must not break completion
    from scripts import sync_soul_modes

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Simulated soul sync error")

    monkeypatch.setattr(sync_soul_modes, "apply_soul_mode", _boom)
    ok_resp = client.post(
        "/api/onboarding/complete",
        json={"company_profile": {"company_name": "Resilient Corp", "language": "en"}},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["domains"]["soul_sync"]["synced"] is False


def test_skip_endpoint_sets_dismissed_and_suppresses_wizard(
    client: TestClient,
    isolated_onboarding_paths: Dict[str, Path],
) -> None:
    skip_resp = client.post("/api/onboarding/skip")
    assert skip_resp.status_code == 200
    assert skip_resp.json()["dismissed"] is True
    assert skip_resp.json()["auto_open"] is False

    for sp in (isolated_onboarding_paths["root_settings"], isolated_onboarding_paths["ws_settings"]):
        sdata = json.loads(sp.read_text(encoding="utf-8"))
        assert sdata["onboarding"]["dismissed"] is True

    st = client.get("/api/onboarding/status").json()
    assert st["dismissed"] is True
    assert st["onboarding_completed"] is False
    assert st["auto_open"] is False


@pytest.mark.parametrize("demo_val", ["1", "true", "TRUE", "yes"])
def test_demo_mode_suppresses_auto_open_and_blocks_mutations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    demo_val: str,
) -> None:
    monkeypatch.setenv("ARCHON_DEMO_MODE", demo_val)

    st_resp = client.get("/api/onboarding/status")
    assert st_resp.status_code == 200
    st = st_resp.json()
    assert st["demo_mode"] is True
    assert st["auto_open"] is False
    assert st["should_show_wizard"] is False

    for path, body in [
        ("/api/onboarding/skip", {}),
        ("/api/onboarding/test-provider", {"provider": "ollama"}),
        ("/api/onboarding/complete", {"company_profile": {"company_name": "Demo Blocked"}}),
    ]:
        mut = client.post(path, json=body)
        assert mut.status_code == 403


def test_rbac_viewer_and_non_admin_rejected_403_in_multiuser_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = {
        "tok_viewer": {"id": "u_v", "username": "viewer1", "role": "viewer", "permissions": []},
        "tok_operator": {"id": "u_o", "username": "op1", "role": "operator", "permissions": []},
        "tok_admin": {"id": "u_a", "username": "admin1", "role": "admin", "permissions": ["all"]},
    }
    monkeypatch.setattr(auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_service, "verify_session", lambda tok: dict(sessions[tok]) if tok in sessions else None)

    write_targets = [
        ("/api/onboarding/test-provider", {"provider": "openrouter", "api_key": ""}),
        ("/api/onboarding/complete", {"company_profile": {"company_name": "RBAC Corp"}}),
        ("/api/onboarding/skip", {}),
    ]

    # Viewer MUST get 403 on all write endpoints (forbid_viewer_writes)
    for endpoint, payload in write_targets:
        r_view = client.post(endpoint, json=payload, headers={"Authorization": "Bearer tok_viewer"})
        assert r_view.status_code == 403, f"Viewer must get 403 on {endpoint}, got {r_view.status_code}"

    # Operator & anonymous MUST also get 403 when multi-user auth is enabled (admin check)
    for endpoint, payload in write_targets:
        r_op = client.post(endpoint, json=payload, headers={"Authorization": "Bearer tok_operator"})
        assert r_op.status_code == 403, f"Operator must get 403 on {endpoint}, got {r_op.status_code}"
        r_anon = client.post(endpoint, json=payload)
        assert r_anon.status_code == 403, f"Anonymous must get 403 on {endpoint}, got {r_anon.status_code}"

    # Admin succeeds with 200
    r_adm_probe = client.post(
        "/api/onboarding/test-provider",
        json={"provider": "openrouter", "api_key": ""},
        headers={"Authorization": "Bearer tok_admin"},
    )
    assert r_adm_probe.status_code == 200
    assert r_adm_probe.json()["ok"] is False  # Missing key, but authorized

    r_adm_skip = client.post(
        "/api/onboarding/skip",
        json={},
        headers={"Authorization": "Bearer tok_admin"},
    )
    assert r_adm_skip.status_code == 200
    assert r_adm_skip.json()["dismissed"] is True


def test_frontend_wizard_js_contains_required_hooks_and_theme_vars() -> None:
    js_path = REPO_ROOT / "static" / "js" / "onboarding_wizard.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    for required_token in (
        "window.openArchonSetupWizard",
        "var(--card",
        "var(--foreground",
        "var(--border",
        "archon_lang",
        "/api/onboarding/status",
        "/api/onboarding/test-provider",
        "/api/onboarding/complete",
        "/api/onboarding/skip",
        "1. Company & Tenant",
        "1. Unternehmen & Mandant",
    ):
        assert required_token in content, f"Missing token in onboarding_wizard.js: {required_token}"


def test_telegram_getme_verification_and_token_redaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reject malformed token before hitting network
    bad = onboarding_wizard.verify_telegram_bot("not-a-valid-token")
    assert bad["ok"] is False

    class FakeTgClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeTgClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str) -> _DummyResponse:
            assert url.endswith("/getMe")
            return _DummyResponse(200, {"ok": True, "result": {"username": "archon_exec_bot"}})

    monkeypatch.setattr(onboarding_wizard.httpx, "Client", FakeTgClient)
    resp = client.post(
        "/api/onboarding/complete",
        json={
            "company_profile": {"company_name": "Telegram Test Ltd", "language": "en"},
            "channels": {
                "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWX_12345",
                "chat_id": "44556677",
                "verify_telegram": True,
            },
        },
    )
    assert resp.status_code == 200
    tg_ver = resp.json()["telegram_verification"]
    assert tg_ver["ok"] is True
    assert tg_ver["bot_username"] == "archon_exec_bot"
    assert "ABCDEFGHIJKLMNOPQRSTUVWX" not in resp.text


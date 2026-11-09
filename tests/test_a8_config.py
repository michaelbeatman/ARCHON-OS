"""Tests für die zentrale Umgebungs-Konfiguration (A8-Etappe 4)."""

import os
import pytest
from archon.core.config import ArchonConfig, config


def test_config_singleton_exists():
    assert isinstance(config, ArchonConfig)


def test_avatars_dir(monkeypatch):
    monkeypatch.delenv("ARCHON_AVATARS_DIR", raising=False)
    assert config.avatars_dir == ""

    monkeypatch.setenv("ARCHON_AVATARS_DIR", "/custom/avatars")
    assert config.avatars_dir == "/custom/avatars"


def test_obsidian_vault_path(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert config.obsidian_vault_path is None

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/vault/path")
    assert config.obsidian_vault_path == "/vault/path"


def test_hermes_home(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    # Default ist platform-abhängig (z.B. /opt/data auf Linux)
    assert bool(config.hermes_home)

    monkeypatch.setenv("HERMES_HOME", "/custom/hermes")
    assert config.hermes_home == "/custom/hermes"


def test_file_roots(monkeypatch):
    monkeypatch.delenv("ARCHON_FILE_ROOTS", raising=False)
    assert config.file_roots == []

    monkeypatch.setenv("ARCHON_FILE_ROOTS", f"/root1{os.pathsep}/root2")
    assert config.file_roots == ["/root1", "/root2"]


def test_tokens(monkeypatch):
    monkeypatch.delenv("ARCHON_SERVICE_TOKEN", raising=False)
    assert config.archon_service_token == ""

    monkeypatch.setenv("ARCHON_SERVICE_TOKEN", "secret-token")
    assert config.archon_service_token == "secret-token"

    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    assert config.omniroute_api_key == "sk-archon-local-dev"

    monkeypatch.setenv("OMNIROUTE_API_KEY", "sk-custom")
    assert config.omniroute_api_key == "sk-custom"

    monkeypatch.delenv("ANYTHINGLLM_API_KEY", raising=False)
    assert config.anythingllm_api_key == ""

    monkeypatch.setenv("ANYTHINGLLM_API_KEY", "rag-key-123")
    assert config.anythingllm_api_key == "rag-key-123"


def test_hermes_proxy_tokens(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "session-tok")
    monkeypatch.setenv("HERMES_DASHBOARD_TOKEN", "dash-tok")
    assert config.get_hermes_proxy_token("HERMES_SESSION_TOKEN") == "session-tok"
    assert config.get_hermes_proxy_token("HERMES_DASHBOARD_TOKEN") == "dash-tok"
    assert config.get_hermes_proxy_token("NON_EXISTENT") == ""


def test_telegram_config(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert config.telegram_webhook_secret == ""
    assert config.telegram_chat_id == ""

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "tg-sec")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    assert config.telegram_webhook_secret == "tg-sec"
    assert config.telegram_chat_id == "123456"


def test_hermes_core_containers(monkeypatch):
    monkeypatch.delenv("ARCHON_HERMES_CORE_CONTAINER", raising=False)
    assert config.hermes_core_containers == ["hermes-agent", "hermes"]

    monkeypatch.setenv("ARCHON_HERMES_CORE_CONTAINER", "custom-agent,custom-core,worker")
    assert config.hermes_core_containers == ["custom-agent", "custom-core", "worker"]


def test_docker_config(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_ADMIN_HOST", raising=False)
    monkeypatch.delenv("DOCKER_SOCKET", raising=False)

    assert config.docker_host == ""
    assert config.docker_admin_host == ""
    assert config.docker_socket == "/var/run/docker.sock"

    monkeypatch.setenv("DOCKER_HOST", "tcp://proxy:2375")
    monkeypatch.setenv("DOCKER_ADMIN_HOST", "tcp://admin-proxy:2375")
    monkeypatch.setenv("DOCKER_SOCKET", "/custom/docker.sock")

    assert config.docker_host == "tcp://proxy:2375"
    assert config.docker_admin_host == "tcp://admin-proxy:2375"
    assert config.docker_socket == "/custom/docker.sock"


def test_rate_limit_config(monkeypatch):
    monkeypatch.delenv("ARCHON_RATE_LIMIT_ENABLED", raising=False)
    assert config.rate_limit_enabled is True

    monkeypatch.setenv("ARCHON_RATE_LIMIT_ENABLED", "0")
    assert config.rate_limit_enabled is False

    monkeypatch.delenv("ARCHON_RATE_LIMIT_TRUST_FORWARDED", raising=False)
    assert config.rate_limit_trust_forwarded is False

    monkeypatch.setenv("ARCHON_RATE_LIMIT_TRUST_FORWARDED", "1")
    assert config.rate_limit_trust_forwarded is True

    assert config.rate_limit_value("ARCHON_RATE_LIMIT_STANDARD", 600) == 600
    monkeypatch.setenv("ARCHON_RATE_LIMIT_STANDARD", "1200")
    assert config.rate_limit_value("ARCHON_RATE_LIMIT_STANDARD", 600) == 1200

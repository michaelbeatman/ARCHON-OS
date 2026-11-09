"""Zentrale Umgebungs-Konfiguration (A8-Etappe 4).

Konsolidiert verstreute ``os.environ``- und ``os.getenv``-Aufrufe an einer
Stelle mit einheitlichen Defaults und Typkonvertierungen.

Werte werden dynamisch aus ``os.environ`` bezogen, damit Tests mit
``monkeypatch.setenv()`` und Container-Umgebungen unmittelbar wirksam sind.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from backend.platform_paths import (
    HERMES_HOME,
    OBSIDIAN_VAULT,
    OBSIDIAN_VAULT_ALT,
)


class ArchonConfig:
    """Zentraler Zugriffspunkt für alle Laufzeit-Umgebungsvariablen."""

    # --- Pfade & Mounts ---

    @property
    def avatars_dir(self) -> str:
        """Override-Pfad für Avatar-Ablage (Env: ARCHON_AVATARS_DIR)."""
        return os.environ.get("ARCHON_AVATARS_DIR", "").strip()

    @property
    def obsidian_vault_path(self) -> Optional[str]:
        """Expliziter Obsidian-Vault-Pfad aus Env (Env: OBSIDIAN_VAULT_PATH)."""
        val = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        return val if val else None

    @property
    def obsidian_vault_path_alt(self) -> Optional[str]:
        """Alternativer Vault-Pfad (Env: OBSIDIAN_VAULT_PATH_ALT)."""
        val = os.environ.get("OBSIDIAN_VAULT_PATH_ALT", "").strip()
        return val if val else None

    @property
    def hermes_home(self) -> str:
        """Hermes-Basisverzeichnis (Env: HERMES_HOME)."""
        return os.environ.get("HERMES_HOME", HERMES_HOME)

    @property
    def file_roots(self) -> List[str]:
        """Erlaubte Datei-Wurzeln (Env: ARCHON_FILE_ROOTS)."""
        raw = os.environ.get("ARCHON_FILE_ROOTS", "")
        return [r.strip() for r in raw.split(os.pathsep) if r.strip()]

    # --- Tokens & Secrets ---

    @property
    def archon_service_token(self) -> str:
        """Interner Service-Token (Env: ARCHON_SERVICE_TOKEN)."""
        return os.environ.get("ARCHON_SERVICE_TOKEN", "").strip()

    @property
    def omniroute_api_key(self) -> str:
        """API-Key für Omniroute (Env: OMNIROUTE_API_KEY)."""
        return os.getenv("OMNIROUTE_API_KEY", "sk-archon-local-dev").strip()

    @property
    def anythingllm_api_key(self) -> str:
        """API-Key für AnythingLLM (Env: ANYTHINGLLM_API_KEY)."""
        return os.environ.get("ANYTHINGLLM_API_KEY", "").strip()

    @property
    def telegram_webhook_secret(self) -> str:
        """Secret für Telegram-Webhooks (Env: TELEGRAM_WEBHOOK_SECRET)."""
        return os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

    @property
    def telegram_bot_token(self) -> str:
        """Telegram Bot Token (Env: TELEGRAM_BOT_TOKEN)."""
        return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    @property
    def telegram_chat_id(self) -> str:
        """Standard Telegram Chat ID (Env: TELEGRAM_CHAT_ID)."""
        return os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    def get_hermes_proxy_token(self, token_name: str) -> str:
        """Liest Proxy-Tokens (HERMES_SESSION_TOKEN, HERMES_DASHBOARD_TOKEN, OMNIROUTE_API_KEY)."""
        return (os.getenv(token_name) or "").strip()

    # --- Container & Netze ---

    @property
    def hermes_core_containers(self) -> List[str]:
        """Kommaseparierte Liste der Core-Container (Env: ARCHON_HERMES_CORE_CONTAINER)."""
        raw = os.environ.get("ARCHON_HERMES_CORE_CONTAINER", "hermes-agent,hermes")
        return [c.strip() for c in raw.split(",") if c.strip()]

    @property
    def proxy_allowed_targets(self) -> str:
        """Erlaubte Egress-Ziele (Env: ARCHON_PROXY_ALLOWED_TARGETS)."""
        return os.environ.get("ARCHON_PROXY_ALLOWED_TARGETS", "").strip()

    @property
    def docker_host(self) -> str:
        """Docker Daemon Host URL (Env: DOCKER_HOST)."""
        return os.environ.get("DOCKER_HOST", "").strip()

    @property
    def docker_admin_host(self) -> str:
        """Docker Admin Host URL (Env: DOCKER_ADMIN_HOST)."""
        return os.environ.get("DOCKER_ADMIN_HOST", "").strip()

    @property
    def docker_socket(self) -> str:
        """Docker Socket Pfad (Env: DOCKER_SOCKET)."""
        return os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock").strip()

    # --- Rate Limiting ---

    @property
    def rate_limit_enabled(self) -> bool:
        """Rate-Limiter aktiv (Env: ARCHON_RATE_LIMIT_ENABLED)."""
        return os.environ.get("ARCHON_RATE_LIMIT_ENABLED", "1") not in ("0", "false", "False", "no")

    @property
    def rate_limit_trust_forwarded(self) -> bool:
        """X-Forwarded-For vertrauen (Env: ARCHON_RATE_LIMIT_TRUST_FORWARDED)."""
        return os.environ.get("ARCHON_RATE_LIMIT_TRUST_FORWARDED", "0") in ("1", "true", "True", "yes")

    def rate_limit_value(self, name: str, default: int) -> int:
        """Liest Rate-Limit Integer-Werte (ARCHON_RATE_LIMIT_STANDARD / _STRICT)."""
        try:
            return max(1, int(os.environ.get(name, str(default))))
        except (TypeError, ValueError):
            return default


# Singleton-Instanz
config = ArchonConfig()

__all__ = ["ArchonConfig", "config"]

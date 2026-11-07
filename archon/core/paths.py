"""Pfad-Konstanten der Anwendung (A5-Etappe 4b).

Alle Pfade werden ausschliesslich aus den Basis-Verzeichnissen in
``archon.core.runtime`` abgeleitet. Es gibt hier bewusst **keine** eigene
``__file__``-Ableitung: aus ``archon/core/`` heraus wuerde sie auf
``/app/archon/core/...`` zeigen statt auf ``/app/...`` — genau dieser Fehler
ist bei ``STUDIO_BG_UPLOAD_DIR`` in ``constants.py`` vermieden worden.

Warum eine eigene Datei und nicht ``constants.py``: dort liegen
Anwendungs-Konstanten (Auth-Praefixe, Prompts), hier das Datei-Layout. Zwei
Zustaendigkeiten in einer Datei waeren bei 18 weiteren Namen unuebersichtlich;
die B10-Config-Schicht wird an dieser Datei andocken.

Wer Werte aendert, aendert sie hier — ``main.py`` importiert nur noch.
Beweis, dass sich nichts verschoben hat: ``scripts/path_constants_snapshot.py``
(Baselines unter ``scripts/parity_baselines/paths_before_*.json``).
"""

from __future__ import annotations

import os

from archon.core.runtime import DATA_DIR, MEMORY_DIR, WORKSPACE_DIR

# --- Daten unter MEMORY_DIR (/app/data im Container, "." auf dem Host) ------
MEMORY_FILE = os.path.join(MEMORY_DIR, "agent_memory.json")
AGENTS_FILE = os.path.join(MEMORY_DIR, "agents.json")
THEME_FILE = os.path.join(MEMORY_DIR, "theme_custom.json")
THEME_LIVE_FILE = os.path.join(MEMORY_DIR, "theme_live_overrides.json")
GATEWAY_CONFIG_FILE = os.path.join(MEMORY_DIR, "gateway_config.json")
QUICKCHAT_SESSIONS_DIR = os.path.join(MEMORY_DIR, "quickchat_sessions")
HERMES_PROFILES_DIR = os.path.join(MEMORY_DIR, "hermes_profiles")

# --- Daten unter DATA_DIR (heute identisch zu MEMORY_DIR) -------------------
_SKILL_INDEX_DISK_PATH = os.path.join(DATA_DIR, "hermes_skills_index.json")
KANBAN_CARDS_FILE = os.path.join(DATA_DIR, "kanban_cards.json")

# --- Daten unter WORKSPACE_DIR (/app/agent_workspace) ------------------------
KANBAN_FILE = os.path.join(WORKSPACE_DIR, "kanban_data.json")
COUPLED_AGENTS_FILE = os.path.join(WORKSPACE_DIR, "config", "coupled_agents.json")
THEMES_DIR = os.path.join(WORKSPACE_DIR, "themes")
FRAMEWORKS_FILE = os.path.join(WORKSPACE_DIR, "frameworks.json")
BOARDROOM_HISTORY_FILE = os.path.join(WORKSPACE_DIR, "boardroom_history.json")
ROLES_FILE = os.path.join(WORKSPACE_DIR, "roles.json")
SERVICES_FILE = os.path.join(WORKSPACE_DIR, "services.json")
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "obsidian_vault", "agent_configs.json")

__all__ = (
    "MEMORY_FILE",
    "AGENTS_FILE",
    "KANBAN_FILE",
    "THEME_FILE",
    "THEME_LIVE_FILE",
    "GATEWAY_CONFIG_FILE",
    "QUICKCHAT_SESSIONS_DIR",
    "COUPLED_AGENTS_FILE",
    "THEMES_DIR",
    "FRAMEWORKS_FILE",
    "BOARDROOM_HISTORY_FILE",
    "ROLES_FILE",
    "SERVICES_FILE",
    "HERMES_PROFILES_DIR",
    "_SKILL_INDEX_DISK_PATH",
    "SETTINGS_FILE",
    "KANBAN_CARDS_FILE",
    "CONFIG_FILE",
)

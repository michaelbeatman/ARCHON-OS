"""Plattformabhängige Basis-Pfade für Archon OS.

Vorher lagen `C:\\...`-Literale verstreut in main.py, views_core.py und
Backend-Modulen. Auf Linux sind sie tote Fallbacks — an zwei Stellen aber
funktional schädlich (Default-`vault_path`, API-Antwort), weil dort ein
Windows-Pfad als *aktiver* Wert zurückfällt und damit ein Verzeichnis namens
`C:\\Mein Obsidian` im Workspace entsteht.

Hier gibt es genau eine Quelle der Wahrheit. Auf Windows bleiben die alten
Pfade unverändert, auf Linux zeigen sie auf die gemounteten Verzeichnisse.
"""

from __future__ import annotations

import os
import sys

IS_WINDOWS = sys.platform == "win32"

# Unveränderte Windows-Originale (nur als Fallback auf win32)
WINDOWS_VAULT = r"C:\Mein Obsidian"
WINDOWS_VAULT_ALT = r"C:\.Mein Obsidian"
WINDOWS_HERMES = r"C:\Users\micha\.hermes"

# Aktive Pfade
OBSIDIAN_VAULT = os.environ.get("OBSIDIAN_VAULT_PATH") or (
    WINDOWS_VAULT if IS_WINDOWS else "/opt/data/obsidian"
)
OBSIDIAN_VAULT_ALT = os.environ.get("OBSIDIAN_VAULT_PATH_ALT") or (
    WINDOWS_VAULT_ALT if IS_WINDOWS else "/opt/data/obsidian"
)
HERMES_HOME = os.environ.get("HERMES_HOME") or (
    WINDOWS_HERMES if IS_WINDOWS else "/opt/data"
)

# Unterordner-Konventionen
PERSONALAKTEN_DIR = os.path.join(OBSIDIAN_VAULT, "00_HR_Agenten", "Personalakten")
PROJEKTE_DIR = os.path.join(OBSIDIAN_VAULT, "01_PROJEKTE")


def soul_path(agent_id: str) -> str:
    return os.path.join(HERMES_HOME, "profiles", agent_id, "SOUL.md")


def profile_dir(agent_id: str) -> str:
    return os.path.join(HERMES_HOME, "profiles", agent_id)


def agent_log_path(agent_id: str) -> str:
    return os.path.join(HERMES_HOME, "profiles", agent_id, "logs", "agent.log")

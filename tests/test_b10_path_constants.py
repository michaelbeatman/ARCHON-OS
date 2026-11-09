"""Test fuer Paket 3 / B10: Pfad-Zentralisierung in archon/core/paths.py.

Stellt sicher:
1. archon.core.paths exportiert zentrale Pfad-Konstanten (OPT_DATA_DIR, HERMES_PROFILES_BASE, etc.).
2. archon/routers/hr.py und archon/routers/telemetry.py nutzen die zentralen Pfade/Helfer.
"""

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_paths_exports_central_constants():
    from archon.core import paths

    assert hasattr(paths, "OPT_DATA_DIR")
    assert hasattr(paths, "HERMES_PROFILES_BASE")
    assert hasattr(paths, "STATE_DB_PATH")
    assert hasattr(paths, "KANBAN_DB_PATH")
    assert hasattr(paths, "HERMES_CONFIG_YAML")
    assert hasattr(paths, "PERSONALAKTEN_DIR")
    assert hasattr(paths, "PROJEKTE_DIR")


def test_hr_router_no_hardcoded_opt_data_literals():
    hr_file = REPO_ROOT / "archon" / "routers" / "hr.py"
    code = hr_file.read_text(encoding="utf-8")
    assert "/opt/data/obsidian" not in code, "archon/routers/hr.py enthaelt noch /opt/data/obsidian"
    assert "/opt/data/profiles" not in code, "archon/routers/hr.py enthaelt noch /opt/data/profiles"


def test_telemetry_router_uses_path_helpers():
    telem_file = REPO_ROOT / "archon" / "routers" / "telemetry.py"
    code = telem_file.read_text(encoding="utf-8")
    assert "/opt/data/profiles" not in code, "archon/routers/telemetry.py enthaelt noch /opt/data/profiles"

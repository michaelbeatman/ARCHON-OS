# -*- coding: utf-8 -*-
"""D3/1 Characterization-Tests fuer ``_get_ops_deps()`` und ``OpsDeps``.

Sichert den Contract des 6-Tupels in ``archon/routers/operations_org.py`` ab:
* exakte Reihenfolge und ``is``-Identitaet gegen ``backend.operations_api``,
* Abwaertskompatibilitaet fuer positionales Entpacken und Index-Zugriff,
* Aufloesung zur Aufrufzeit (Monkeypatches auf ``backend.operations_api.*``
  wie ``_get_kanban_connection`` bleiben wirksam),
* In-Place-Cache-Invalidierung ueber ``deps.profiles_map_cache``,
* keine anonymen positionalen Entpacker mehr in ``operations_org.py``.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

import pytest

import archon.routers.operations_org as ops_org
import backend.operations_api as ops_api

_EXPECTED_FIELDS = (
    "load_profiles_map",
    "get_fallback_avatar",
    "get_kanban_connection",
    "profiles_file",
    "workspace_dir",
    "profiles_map_cache",
)

_EXPECTED_API_ATTRS = (
    "_load_profiles_map",
    "_get_fallback_avatar",
    "_get_kanban_connection",
    "PROFILES_FILE",
    "WORKSPACE_DIR",
    "_PROFILES_MAP_CACHE",
)


def _find_positional_ops_deps_unpacks(tree: ast.AST) -> List[int]:
    """Findet Zuweisungen der Form ``a, b, ... = _get_ops_deps()``."""
    lines: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_get_ops_deps"
        ):
            continue
        if any(isinstance(t, (ast.Tuple, ast.List)) for t in node.targets):
            lines.append(node.lineno)
    return lines


def test_d3_1_ops_deps_namedtuple_contract_and_identity() -> None:
    """OpsDeps wahrt Feldnamen, Reihenfolge, Tuple-Kompatibilitaet und Identitaet."""
    deps = ops_org._get_ops_deps()

    assert isinstance(deps, ops_org.OpsDeps)
    assert isinstance(deps, tuple)
    assert len(deps) == 6
    assert ops_org.OpsDeps._fields == _EXPECTED_FIELDS

    # Positionales Unpacking + Index-Zugriff + benannter Zugriff zeigen per ``is``
    # auf exakt dieselben Objekte in backend.operations_api.
    unpacked = tuple(deps)
    for idx, (field, api_attr) in enumerate(zip(_EXPECTED_FIELDS, _EXPECTED_API_ATTRS)):
        expected_obj = getattr(ops_api, api_attr)
        assert getattr(deps, field) is expected_obj, f"Feld {field} driftet von ops_api.{api_attr}"
        assert deps[idx] is expected_obj, f"Index [{idx}] driftet von ops_api.{api_attr}"
        assert unpacked[idx] is expected_obj, f"Unpack [{idx}] driftet von ops_api.{api_attr}"


def test_d3_2_ops_deps_resolves_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negativprobe gegen Import-Time-Freeze: Monkeypatch auf ops_api muss greifen."""
    original_conn_fn = ops_api._get_kanban_connection
    sentinel = object()
    monkeypatch.setattr(ops_api, "_get_kanban_connection", sentinel)

    deps = ops_org._get_ops_deps()
    assert deps.get_kanban_connection is sentinel
    assert deps[2] is sentinel
    assert deps.get_kanban_connection is not original_conn_fn


def test_d3_3_broadcast_uses_patched_kanban_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Live-Verhalten: Patch auf backend.operations_api._get_kanban_connection erreicht operations_org."""
    db_path = tmp_path / "kanban_probe.db"
    setup_conn = sqlite3.connect(str(db_path))
    setup_conn.execute(
        """
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            kind TEXT,
            payload TEXT,
            created_at TEXT
        )
        """
    )
    setup_conn.commit()
    setup_conn.close()

    def _patched_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(ops_api, "_get_kanban_connection", _patched_conn)

    res = ops_org.broadcast_comm_message(
        ops_org.CommBroadcastRequest(
            author="commander",
            message="d3-ops-deps-probe",
            task_id="task-d3-1",
            target="squad",
        )
    )
    assert res["status"] == "success"

    verify_conn = _patched_conn()
    rows = verify_conn.execute(
        "SELECT task_id, kind, payload FROM task_events WHERE task_id = ?",
        ("task-d3-1",),
    ).fetchall()
    verify_conn.close()

    assert len(rows) == 1
    assert rows[0]["kind"] == "broadcast"
    payload = json.loads(rows[0]["payload"])
    assert payload["message"] == "d3-ops-deps-probe"
    assert payload["author"] == "commander"


def test_d3_4_save_org_hierarchy_invalidates_profiles_cache_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """save_org_hierarchy aktualisiert PROFILES_FILE und setzt _PROFILES_MAP_CACHE['mtime'] = 0.0."""
    org_file = tmp_path / "org_hierarchy.json"
    profiles_file = tmp_path / "agent_profiles.json"
    profiles_file.write_text(
        json.dumps([{"id": "agent_alpha", "name": "Alt", "model": "m1"}]),
        encoding="utf-8",
    )
    fake_cache = {"mtime": 99999.0, "data": {"agent_alpha": {"name": "Alt"}}}

    monkeypatch.setattr(ops_org, "_get_org_hierarchy_file", lambda: str(org_file))
    monkeypatch.setattr(ops_org, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(ops_api, "PROFILES_FILE", str(profiles_file))
    monkeypatch.setattr(ops_api, "_PROFILES_MAP_CACHE", fake_cache)

    fake_req: Any = MagicMock()

    # Fall 1 (Negativprobe): unveraendertes Profil darf den Cache NICHT invalidieren.
    unchanged = ops_org.OrgHierarchySaveRequest(
        nodes=[{"id": "agent_alpha", "name": "Alt", "model": "m1"}],
        links=[],
    )
    res_unchanged = ops_org.save_org_hierarchy(fake_req, unchanged)
    assert res_unchanged["status"] == "success"
    assert fake_cache["mtime"] == 99999.0

    # Fall 2: geaendertes Profil schreibt PROFILES_FILE und setzt mtime in-place auf 0.0.
    changed = ops_org.OrgHierarchySaveRequest(
        nodes=[{"id": "agent_alpha", "name": "Neu", "model": "m2"}],
        links=[],
    )
    res_changed = ops_org.save_org_hierarchy(fake_req, changed)
    assert res_changed["status"] == "success"
    assert fake_cache["mtime"] == 0.0

    saved_profiles = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert saved_profiles[0]["name"] == "Neu"
    assert saved_profiles[0]["model"] == "m2"


def test_d3_5_no_anonymous_positional_unpack_left_in_operations_org() -> None:
    """Kein anonymes 6-Tupel-Unpacking mehr in operations_org.py (mit echter Negativprobe)."""
    org_path = Path(__file__).resolve().parents[1] / "archon" / "routers" / "operations_org.py"
    tree = ast.parse(org_path.read_text(encoding="utf-8"))
    assert _find_positional_ops_deps_unpacks(tree) == []

    # Echte Negativprobe gegen denselben AST-Helper:
    bad_tree = ast.parse("def f():\n    a, b, c, d, e, g = _get_ops_deps()\n")
    assert _find_positional_ops_deps_unpacks(bad_tree) == [2]

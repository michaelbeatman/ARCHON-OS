# -*- coding: utf-8 -*-
"""D3/2 Characterization-Tests fuer Kanban Bulk-Aktionen & Undo-Store-TTL.

Deckt die in ANALYSIS_GOD_OBJECTS.md §6 dokumentierte Luecke (Undo-Store-TTL)
sowie den Re-Export- & Verhaltens-Contract zwischen ``backend.operations_api``
und ``backend.operations_bulk`` ab.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import backend.operations_api as ops_api
import backend.operations_bulk as ops_bulk


def _init_kanban_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            assignee TEXT,
            status TEXT,
            block_kind TEXT,
            result TEXT,
            started_at TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute(
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
    conn.execute(
        """
        INSERT INTO tasks (id, title, assignee, status, block_kind, result, started_at, completed_at)
        VALUES ('t-1', 'Aufgabe 1', 'agent_a', 'blocked', 'approval', 'alte-notiz', '2026-11-26T08:00:00', NULL)
        """
    )
    conn.commit()
    conn.close()


def _conn_factory(db_path: Path) -> Any:
    def _connect(maintenance: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    return _connect


def test_d3_bulk_store_identity_reexport() -> None:
    """_KANBAN_UNDO_STORE in operations_api ist identisch zum Store in operations_bulk."""
    assert ops_api._KANBAN_UNDO_STORE is ops_bulk._KANBAN_UNDO_STORE
    assert ops_api._KANBAN_UNDO_STORE_MAX_SIZE == 100
    assert ops_api._prune_undo_store is ops_bulk._prune_undo_store


def test_d3_bulk_prune_undo_store_ttl_and_max_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """_prune_undo_store entfernt abgelaufene Tokens und kappt ueber 100 die aeltesten."""
    store = ops_bulk._KANBAN_UNDO_STORE
    monkeypatch.setattr(ops_bulk, "_KANBAN_UNDO_STORE", {})
    # Re-bind auch fuer den Test-Zugriff
    local_store = ops_bulk._KANBAN_UNDO_STORE
    now = time.time()

    local_store["expired_tok"] = {"created_at": now - 700, "expires_at": now - 10, "snapshot": []}
    for i in range(105):
        local_store[f"live_{i:03d}"] = {
            "created_at": now + i,
            "expires_at": now + 600,
            "snapshot": [],
        }

    ops_bulk._prune_undo_store()

    assert "expired_tok" not in local_store
    assert len(local_store) == 100
    # Die 5 aeltesten (live_000 .. live_004) wurden verworfen, live_005 .. live_104 bleiben.
    for i in range(5):
        assert f"live_{i:03d}" not in local_store
    assert "live_005" in local_store
    assert "live_104" in local_store
    # Sicherstellen, dass der globale Original-Store nicht verschmutzt wurde
    assert store is not local_store


def test_d3_bulk_move_and_undo_roundtrip_restores_block_kind_and_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bulk move -> todo loescht Timestamps; Undo stellt Status, block_kind & result wieder her."""
    db_path = tmp_path / "kanban_bulk.db"
    _init_kanban_db(db_path)

    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_load_kanban_meta", lambda: {"tasks": {"t-1": {"tags": ["vip"]}}})
    monkeypatch.setattr(ops_api, "_sync_to_memory_bridge", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "backend.kanban_sidecar.update_kanban_meta",
        lambda fn: fn({"tasks": {}}),
    )

    fake_req: Any = MagicMock()
    res = ops_api.api_kanban_bulk_action(
        fake_req,
        ops_api.KanbanBulkActionRequest(
            task_ids=["t-1"],
            action="move",
            payload={"status": "todo"},
        ),
    )
    assert res["status"] == "success"
    assert res["affected_count"] == 1
    assert res["expires_in_seconds"] == 600
    token = res["undo_token"]
    assert token in ops_api._KANBAN_UNDO_STORE

    # Nach move -> todo muessen status='todo' und started_at/completed_at NULL sein.
    c = _conn_factory(db_path)()
    row = c.execute("SELECT status, started_at, completed_at FROM tasks WHERE id = 't-1'").fetchone()
    c.close()
    assert row["status"] == "todo"
    assert row["started_at"] is None
    assert row["completed_at"] is None

    # Undo stellt blocked + block_kind='approval' + result='alte-notiz' wieder her.
    undo_res = ops_api.api_kanban_bulk_undo(
        fake_req,
        ops_api.KanbanBulkUndoRequest(undo_token=token),
    )
    assert undo_res["status"] == "success"
    assert undo_res["restored_count"] == 1
    assert token not in ops_api._KANBAN_UNDO_STORE

    c2 = _conn_factory(db_path)()
    restored = c2.execute(
        "SELECT status, assignee, block_kind, result FROM tasks WHERE id = 't-1'"
    ).fetchone()
    c2.close()
    assert restored["status"] == "blocked"
    assert restored["assignee"] == "agent_a"
    assert restored["block_kind"] == "approval"
    assert restored["result"] == "alte-notiz"

    # Negativprobe: verbrauchtes Token liefert 404.
    with pytest.raises(HTTPException) as exc_info:
        ops_api.api_kanban_bulk_undo(fake_req, ops_api.KanbanBulkUndoRequest(undo_token=token))
    assert exc_info.value.status_code == 404


def test_d3_bulk_invalid_status_raises_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Negativprobe: ungueltiger Ziel-Status wird mit 422 abgewiesen."""
    db_path = tmp_path / "kanban_bulk_422.db"
    _init_kanban_db(db_path)

    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_load_kanban_meta", lambda: {"tasks": {}})

    with pytest.raises(HTTPException) as exc_info:
        ops_api.api_kanban_bulk_action(
            MagicMock(),
            ops_api.KanbanBulkActionRequest(
                task_ids=["t-1"],
                action="move",
                payload={"status": "nicht_existent"},
            ),
        )
    assert exc_info.value.status_code == 422

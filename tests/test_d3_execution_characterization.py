# -*- coding: utf-8 -*-
"""D3/6 Characterization-Tests fuer Kanban-Ausfuehrung & Cross-Model-Verification."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import backend.operations_api as ops_api
import backend.operations_execution as ops_exec


def _init_exec_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            block_kind TEXT,
            result TEXT,
            consecutive_failures INTEGER DEFAULT 0
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
        "INSERT INTO tasks (id, title, body, assignee, status) VALUES ('t-ex-1', 'Test', 'Body', 'coder', 'todo')"
    )
    conn.commit()
    conn.close()


def _conn_factory(db_path: Path) -> Any:
    def _connect(maintenance: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    return _connect


def test_d3_6_reexports_and_identity() -> None:
    """operations_api re-exportiert die echten Funktionen aus operations_execution."""
    assert ops_api._execute_kanban_task_async is ops_exec._execute_kanban_task_async
    assert ops_api._execute_kanban_task_inner is ops_exec._execute_kanban_task_inner
    assert ops_api._persist_kanban_result_sync is ops_exec._persist_kanban_result_sync
    assert ops_api._cross_model_verify_task_result is ops_exec._cross_model_verify_task_result


def test_d3_6_cancel_import_failure_is_fail_closed_behavior(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Echte Verhaltensprobe: fehlendes backend.cancellation -> blocked + RuntimeError."""
    db_path = tmp_path / "exec_cancel.db"
    _init_exec_db(db_path)

    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_sync_to_memory_bridge", lambda *_a, **_kw: None)
    monkeypatch.setitem(sys.modules, "backend.cancellation", None)

    with pytest.raises(RuntimeError, match="cancellation unavailable"):
        asyncio.run(ops_api._execute_kanban_task_inner("t-ex-1"))

    c = _conn_factory(db_path)()
    row = c.execute("SELECT status, block_kind FROM tasks WHERE id = 't-ex-1'").fetchone()
    c.close()
    assert row["status"] == "blocked"
    assert row["block_kind"] == "cancellation_unavailable"


def test_d3_6_cross_model_verify_skips_short_and_fails_closed_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kurze Ergebnisse ueberspringen den Verifier; Fehler im Verifier-Call -> fail-closed."""
    monkeypatch.delenv("ARCHON_CROSS_MODEL_VERIFY", raising=False)
    short_res = asyncio.run(
        ops_api._cross_model_verify_task_result(
            task_id="t-ex-1", result_text="Kurz.", primary_model="gpt-5"
        )
    )
    assert short_res["passed"] is True
    assert short_res["skipped"] is True

    # Fail-closed bei Dispatch-Exception
    import core_dispatcher

    monkeypatch.setattr(
        "backend.kanban_verifier.cross_model_verify_card",
        lambda *_a, **_kw: {"passed": True, "verifier_model": "claude-sonnet"},
    )
    monkeypatch.setattr(
        core_dispatcher,
        "dispatch_to_omniroute_or_container",
        AsyncMock(side_effect=RuntimeError("verifier down")),
    )
    long_text = "A" * 250
    fail_res = asyncio.run(
        ops_api._cross_model_verify_task_result(
            task_id="t-ex-1", result_text=long_text, primary_model="gpt-5"
        )
    )
    assert fail_res["passed"] is False
    assert fail_res["requires_hitl"] is True
    assert fail_res["block_kind"] == "cross_model_verification_failed_hitl"

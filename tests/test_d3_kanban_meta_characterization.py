# -*- coding: utf-8 -*-
"""D3/4 Characterization-Tests fuer Kanban-Palette, Sidecar-Meta, Stats & Task-Details."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import backend.operations_api as ops_api


def _init_meta_kanban_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            assignee TEXT,
            status TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE task_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            author TEXT,
            body TEXT,
            created_at INTEGER
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
        CREATE TABLE task_links (
            parent_id TEXT,
            child_id TEXT,
            kind TEXT
        )
        """
    )
    now = datetime.datetime.now()
    t0 = (now - datetime.timedelta(hours=4)).isoformat()
    t1 = (now - datetime.timedelta(hours=2)).isoformat()
    conn.execute(
        """
        INSERT INTO tasks (id, title, assignee, status, created_at, started_at, completed_at)
        VALUES
            ('t-done', 'Done Task', 'coder', 'done', ?, ?, ?),
            ('t-arch', 'Archived Task', 'coder', 'archived', ?, NULL, NULL),
            ('t-blk', 'Blocked Task', 'qa', 'blocked', ?, NULL, NULL)
        """,
        (t0, t0, t1, t0, t0),
    )
    conn.commit()
    conn.close()


def _conn_factory(db_path: Path) -> Any:
    def _connect(maintenance: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    return _connect


def test_d3_4_palette_sanitize_and_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """save_kanban_palette filtert ungueltige Hex-Werte/Spalten und reset=True entfernt Datei."""
    palette_file = tmp_path / "config" / "kanban_palette.json"
    monkeypatch.setattr(ops_api, "_KANBAN_PALETTE_FILE", str(palette_file))
    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)

    assert ops_api.get_kanban_palette()["custom"] is False

    # Negativprobe: leeres columns -> 400
    with pytest.raises(HTTPException) as exc_empty:
        ops_api.save_kanban_palette(MagicMock(), ops_api.KanbanPaletteUpdate(columns={}))
    assert exc_empty.value.status_code == 400

    res = ops_api.save_kanban_palette(
        MagicMock(),
        ops_api.KanbanPaletteUpdate(
            columns={
                "todo": {"header": "#112233", "text": "not-a-hex"},
                "unbekannte_spalte": {"header": "#abcdef"},
            }
        ),
    )
    assert res["saved"] is True
    assert res["columns"] == {"todo": {"header": "#112233"}}
    loaded = ops_api.get_kanban_palette()
    assert loaded["custom"] is True
    assert loaded["columns"]["todo"]["header"] == "#112233"

    reset_res = ops_api.save_kanban_palette(MagicMock(), ops_api.KanbanPaletteUpdate(reset=True))
    assert reset_res["reset"] is True
    assert not palette_file.exists()


def test_d3_4_save_kanban_meta_wip_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """save_kanban_meta schreibt WIP & Task-Meta ueber update_kanban_meta und weist bad due ab."""
    state: Dict[str, Any] = {"tasks": {}, "wip": {}}

    def _fake_update(fn: Any) -> Any:
        res = fn(state)
        return state, res

    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr("backend.kanban_sidecar.update_kanban_meta", _fake_update)

    wip = ops_api.save_kanban_meta(
        MagicMock(),
        ops_api.KanbanMetaSaveRequest(kind="wip", limits={"in_progress": 3, "bad": "x", "zero": 0}),
    )
    assert wip == {"status": "ok", "wip": {"in_progress": 3}}

    saved = ops_api.save_kanban_meta(
        MagicMock(),
        ops_api.KanbanMetaSaveRequest(
            task_id="t-1",
            due="2026-12-01",
            tags=["urgent", "  "],
            require_hitl=True,
        ),
    )
    assert saved["status"] == "ok"
    assert saved["task"]["due"] == "2026-12-01"
    assert saved["task"]["tags"] == ["urgent"]
    assert saved["task"]["require_hitl"] is True

    # Negativprobe: ungueltiges Datum -> 400
    with pytest.raises(HTTPException) as exc_due:
        ops_api.save_kanban_meta(
            MagicMock(),
            ops_api.KanbanMetaSaveRequest(task_id="t-1", due="kein-datum"),
        )
    assert exc_due.value.status_code == 400


def test_d3_4_kanban_stats_details_and_comments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """kanban_stats trennt archived/active & berechnet avg_cycle_hours; details/comments Roundtrip."""
    db_path = tmp_path / "kanban_stats.db"
    _init_meta_kanban_db(db_path)

    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_load_kanban_meta", lambda: {"tasks": {}})
    monkeypatch.setattr(ops_api, "_resolve_task_obsidian_rel", lambda *_a, **_kw: None)

    stats = ops_api.kanban_stats()
    assert stats["active_total"] == 2
    assert stats["archived_total"] == 1
    assert stats["blocked"] == 1
    assert stats["avg_cycle_hours"] == 2.0

    comment_res = ops_api.add_task_comment(MagicMock(), "t-done", author="micha", body="Sieht gut aus")
    assert comment_res["status"] == "success"
    assert isinstance(comment_res["created_at"], int)

    details = ops_api.get_task_details("t-done")
    assert details["task"]["id"] == "t-done"
    assert len(details["comments"]) == 1
    assert details["comments"][0]["body"] == "Sieht gut aus"

    # Negativprobe: unbekannter Task -> 404
    with pytest.raises(HTTPException) as exc_404:
        ops_api.get_task_details("t-gibts-nicht")
    assert exc_404.value.status_code == 404

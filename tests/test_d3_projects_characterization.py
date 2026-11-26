# -*- coding: utf-8 -*-
"""D3/3 Characterization-Tests fuer Projekt-Zentrale, Meta-Sidecar & Pfadjail.

Deckt die in ANALYSIS_GOD_OBJECTS.md §6 dokumentierten Luecken ab:
* ``_resolve_task_obsidian_rel`` (direkter Meta-Treffer, Fallbacks 3/4, Pfadjail),
* ``get_projects_overview`` (Aggregation aus Kanban-DB + Obsidian-Vault + Sidecar),
* ``put_project_meta`` / ``get_project_meta`` (inkl. 422-Negativprobe),
* Traversal- & Suffix-Schutz in ``get_project_folder_files`` und
  ``get_kanban_project_file``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import backend.operations_api as ops_api
import backend.post_task_pipeline as ptp


def _init_projects_kanban_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            priority TEXT,
            created_at TEXT,
            completed_at TEXT,
            result TEXT,
            project_id TEXT,
            session_id TEXT,
            model_override TEXT,
            skills TEXT
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
    conn.execute(
        """
        INSERT INTO tasks (id, title, body, assignee, status, priority, created_at, completed_at, result, project_id, session_id, model_override, skills)
        VALUES
            ('t-alpha-1', 'Alpha Analyse', 'Body 1', 'coder', 'done', 'high', '2026-11-20T10:00:00', '2026-11-20T12:00:00', 'Fertig', 'alpha-launch', NULL, 'gpt-5', '["search"]'),
            ('t-alpha-2', 'Alpha Review', 'Body 2', 'qa', 'in_progress', 'medium', '2026-11-21T10:00:00', NULL, '', 'alpha-launch', NULL, NULL, NULL)
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


def test_d3_projects_resolve_task_obsidian_rel_direct_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Direkter Meta-Treffer und Fallback 3 (Ordner mit task_id) + Fallback 4 (Endprodukt-Datei)."""
    vault = tmp_path / "vault"
    p1 = vault / "01_PROJEKTE" / "projekt-alpha"
    p2 = vault / "01_PROJEKTE" / "projekt-t-fb3"
    p3 = vault / "01_PROJEKTE" / "projekt-gamma" / "03_Endprodukte"
    p1.mkdir(parents=True)
    p2.mkdir(parents=True)
    p3.mkdir(parents=True)
    (p3 / "report_t-fb4.md").write_text("# Report", encoding="utf-8")

    db_path = tmp_path / "kanban_rel.db"
    _init_projects_kanban_db(db_path)

    monkeypatch.setattr(ptp, "get_vault_dir", lambda: str(vault))
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))

    # Direkter Treffer ueber meta
    meta = {"tasks": {"t-direct": {"obsidian": "01_PROJEKTE/projekt-alpha"}}}
    assert ops_api._resolve_task_obsidian_rel("t-direct", meta=meta) == "01_PROJEKTE/projekt-alpha"

    # Fallback 3: Ordnername enthaelt task_id
    meta_fb3: dict[str, Any] = {"tasks": {}}
    assert ops_api._resolve_task_obsidian_rel("t-fb3", meta=meta_fb3) == "01_PROJEKTE/projekt-t-fb3"

    # Fallback 4: Datei in 03_Endprodukte enthaelt task_id
    meta_fb4: dict[str, Any] = {"tasks": {}}
    assert ops_api._resolve_task_obsidian_rel("t-fb4", meta=meta_fb4) == "01_PROJEKTE/projekt-gamma"

    # Negativprobe: unbekannte Task liefert None
    assert ops_api._resolve_task_obsidian_rel("t-unbekannt-xyz", meta={"tasks": {}}) is None


def test_d3_projects_overview_aggregation_and_meta_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_projects_overview aggregiert Kanban-DB, Obsidian-Vault (HTML-Report) & Sidecar-Meta."""
    vault = tmp_path / "vault"
    proj_dir = vault / "01_PROJEKTE" / "alpha-launch"
    end_dir = proj_dir / "03_Endprodukte"
    end_dir.mkdir(parents=True)
    (proj_dir / "PROJEKT.md").write_text('title: "Alpha Launch"\nstatus: in_progress\n', encoding="utf-8")
    (end_dir / "summary.html").write_text("<h1>OK</h1>", encoding="utf-8")

    db_path = tmp_path / "kanban_ov.db"
    _init_projects_kanban_db(db_path)
    meta_file = tmp_path / "config" / "projects_meta.json"

    monkeypatch.setattr(ptp, "get_vault_dir", lambda: str(vault))
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_PROJECTS_META_FILE", str(meta_file))
    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)

    ov = ops_api.get_projects_overview()
    assert ov["status"] == "success"
    assert ov["total"] == 1
    proj = ov["all"][0]
    assert proj["id"] == "alpha-launch"
    assert proj["title"] == "Alpha Launch"
    assert proj["tasks_total"] == 2
    assert proj["tasks_completed"] == 1
    assert proj["progress"] == 50
    assert proj["has_html_report"] is True
    assert proj["primary_document"] == "01_PROJEKTE/alpha-launch/03_Endprodukte/summary.html"

    # Sidecar-Override via put_project_meta
    put_res = ops_api.put_project_meta(
        "alpha-launch",
        ops_api.ProjectMetaUpdate(goal="Release V1", status="completed"),
        MagicMock(),
    )
    assert put_res["status"] == "success"
    assert ops_api.get_project_meta("alpha-launch")["meta"]["goal"] == "Release V1"

    ov2 = ops_api.get_projects_overview()
    assert ov2["all"][0]["status"] == "completed"
    assert ov2["all"][0]["goal"] == "Release V1"

    # Negativprobe: ungueltiger Status im Sidecar-Update -> 422
    with pytest.raises(HTTPException) as exc_info:
        ops_api.put_project_meta(
            "alpha-launch",
            ops_api.ProjectMetaUpdate(status="ungueltig"),
            MagicMock(),
        )
    assert exc_info.value.status_code == 422


def test_d3_projects_path_jail_blocks_traversal_and_binary_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Traversal-Schutz blockiert '../' und unzulaessige Dateiendungen."""
    vault = tmp_path / "vault"
    proj_dir = vault / "01_PROJEKTE" / "safe-proj"
    proj_dir.mkdir(parents=True)
    (proj_dir / "notes.md").write_text("Hallo", encoding="utf-8")
    (proj_dir / "binary.exe").write_bytes(b"MZ")
    (tmp_path / "secret.md").write_text("TOP SECRET", encoding="utf-8")

    monkeypatch.setattr(ptp, "get_vault_dir", lambda: str(vault))
    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(
        ops_api,
        "_load_kanban_meta",
        lambda: {"tasks": {"t-safe": {"obsidian": "01_PROJEKTE/safe-proj"}}},
    )

    # 1. get_project_folder_files blockiert Traversal mit 400
    with pytest.raises(HTTPException) as exc_dir:
        ops_api.get_project_folder_files("../../outside")
    assert exc_dir.value.status_code == 400

    # 2. get_kanban_project_file liest erlaubte .md-Datei
    ok = ops_api.get_kanban_project_file(MagicMock(), "t-safe", "notes.md")
    assert ok["content"] == "Hallo"

    # 3. Negativprobe: Traversal aus Projektordner -> 404
    with pytest.raises(HTTPException) as exc_trav:
        ops_api.get_kanban_project_file(MagicMock(), "t-safe", "../../../secret.md")
    assert exc_trav.value.status_code == 404

    # 4. Negativprobe: .exe -> 415 Unsupported Media Type
    with pytest.raises(HTTPException) as exc_bin:
        ops_api.get_kanban_project_file(MagicMock(), "t-safe", "binary.exe")
    assert exc_bin.value.status_code == 415

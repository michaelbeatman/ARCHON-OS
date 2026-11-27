# -*- coding: utf-8 -*-
"""W4-D / Domäne 01 — Regressionstests im Produktivpfad.

D01-H1: PbD-Synthese darf simulierte Ausführung nie als Erfolg durchreichen.
D01-H2: „Anweisung an Agenten" muss einen echten Task erzeugen; Erfolg nur
        bei nicht leerem ``task_id``, Fehler fail-closed.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import archon.routers.operations_org as ops_org
import backend.computer_use_pbd as pbd
import backend.operations_api as ops_api

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pbd_tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Hält die PbD-Synthese vom Repo fern (SKILLS/SCRIPTS/TRACES nach tmp)."""
    scripts = tmp_path / "scripts"
    skills = tmp_path / "skills"
    traces = tmp_path / "traces"
    for directory in (scripts, skills, traces):
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pbd, "SCRIPTS_DIR", str(scripts))
    monkeypatch.setattr(pbd, "SKILLS_DIR", str(skills))
    monkeypatch.setattr(pbd, "PBD_TRACES_DIR", str(traces))
    return tmp_path


def _synthesize_sample() -> dict[str, Any]:
    recorder = pbd.DemonstrationRecorder()
    recorder.start_recording("W4-D Demo", "https://example.invalid", "test_agent")
    recorder.record_event("navigate", {"url": "https://example.invalid"})
    recorder.record_event("click", {"selector": "#demo", "x": 12, "y": 34})
    recorder.record_event("type", {"field": "Suche", "text": "Testbegriff"})
    return recorder.stop_and_synthesize_skill("w4d_demo_skill")


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module is not None
    return module


def _make_kanban_db(path: Path, *, with_tasks: bool = True) -> None:
    conn = sqlite3.connect(str(path))
    try:
        if with_tasks:
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    priority INTEGER,
                    created_by TEXT,
                    created_at TEXT,
                    project_id TEXT
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
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# D01-H1 — PbD: simulierte Ausführung darf nie als Erfolg durchgereicht werden
# ---------------------------------------------------------------------------


def test_d01_h1_synthesis_result_declares_demo_only(
    pbd_tmp_dirs: Path,
) -> None:
    """Die Synthese meldet den echten Effekt, verneint aber Ausfuehrbarkeit."""
    res = _synthesize_sample()

    # "synthesized" beschreibt das tatsaechlich geschriebene Artefakt.
    assert res["status"] == "synthesized"
    # Nie stillschweigend als ausfuehrbare Automatisierung ausgeben.
    assert res["demo_only"] is True
    assert res["simulated"] is True
    assert res["executable"] is False
    assert res["runtime"] == "unavailable"
    assert "erfolgreich" not in res["message"]
    assert Path(res["script_path"]).is_file()
    assert Path(res["skill_path"]).is_file()


def test_d01_h1_generated_script_never_reports_completed(
    pbd_tmp_dirs: Path,
) -> None:
    """Generierter Quelltext enthaelt weder Fake-Erfolg noch Aktions-Kosmetik."""
    res = _synthesize_sample()
    source = Path(res["script_path"]).read_text(encoding="utf-8")

    assert "DEMO_ONLY = True" in source
    assert "SIMULATED = True" in source
    assert "EXECUTABLE = False" in source
    assert "RuntimeError" in source
    assert "RECORDED_STEPS" in source
    assert '"status": "completed"' not in source
    assert "erfolgreich abgeschlossen" not in source
    # Keine print()/sleep()-Simulation mehr, die eine Aktion vortaeuscht.
    assert "print(" not in source
    assert "time.sleep(" not in source


def test_d01_h1_generated_execute_fails_closed(
    pbd_tmp_dirs: Path,
) -> None:
    """Echter Aufruf des generierten Skills wirft RuntimeError, kein success."""
    res = _synthesize_sample()
    module = _load_module(Path(res["script_path"]), "w4d_generated_skill")

    assert module.EXECUTABLE is False
    with pytest.raises(RuntimeError, match="CUA-Runtime"):
        module.execute_w4d_demo_skill()


def test_d01_h1_skill_md_marks_artifact_non_executable(
    pbd_tmp_dirs: Path,
) -> None:
    """Auch das SKILL.md muss die fehlende Runtime sichtbar machen."""
    res = _synthesize_sample()
    skill_md = Path(res["skill_path"]).read_text(encoding="utf-8")

    assert "demo_only: true" in skill_md
    assert "executable: false" in skill_md
    assert "runtime: unavailable" in skill_md
    assert "Keine CUA-Runtime angebunden" in skill_md
    assert "RuntimeError" in skill_md
    assert "Automations-Skript aus" not in skill_md


def test_d01_h1_shipped_dynamic_tool_artifact_fails_closed() -> None:
    """Das ausgelieferte Screener-Skript darf ebenfalls keinen Erfolg melden."""
    artifact = (
        REPO_ROOT / "scripts" / "dynamic_tools" / "auto_senior_applicant_screener.py"
    )
    source = artifact.read_text(encoding="utf-8")

    assert '"status": "completed"' not in source
    assert "erfolgreich abgeschlossen" not in source
    assert "DEMO_ONLY = True" in source
    assert "EXECUTABLE = False" in source

    module = _load_module(artifact, "w4d_shipped_screener")
    assert module.DEMO_ONLY is True
    assert module.EXECUTABLE is False
    with pytest.raises(RuntimeError, match="CUA-Runtime"):
        module.execute_auto_senior_applicant_screener()


# ---------------------------------------------------------------------------
# D01-H2 — Agenten-Anweisung erzeugt einen echten Task (task_id)
# ---------------------------------------------------------------------------


def test_d01_h2_route_is_registered_at_operations_tasks() -> None:
    """Partition C braucht genau POST /api/operations/tasks mit task_id."""
    registered = [
        route
        for route in ops_org.router.routes
        if getattr(route, "path", None) == "/tasks"
        and "POST" in (getattr(route, "methods", None) or set())
    ]
    assert registered, "POST /api/operations/tasks nicht registriert"


def test_d01_h2_creates_real_task_and_returns_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nach dem Aufruf existiert ein Task mit agent_id; Antwort nennt task_id."""
    db_path = tmp_path / "w4d_kanban.db"
    _make_kanban_db(db_path)

    def _patched_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(ops_api, "_get_kanban_connection", _patched_conn)

    res = ops_org.create_agent_instruction_task(
        ops_org.AgentInstructionRequest(
            author="commander",
            message="Pruefe die Bewerbungen und gib Senior-Profile frei.",
            agent_id="recruiter_specialist",
            parent_project_id="project-42",
            title="Senior-Screening",
        )
    )

    task_id = res.get("task_id")
    assert isinstance(task_id, str) and task_id, "Antwort ohne task_id"
    assert res["agent_id"] == "recruiter_specialist"

    verify = _patched_conn()
    try:
        row = verify.execute(
            "SELECT id, title, assignee, status, project_id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None, "Kein echter Task in der Kanban-DB angelegt"
        assert row["assignee"] == "recruiter_specialist"
        assert row["status"] == "review"
        assert row["project_id"] == "project-42"

        feed = verify.execute(
            "SELECT task_id, kind, payload FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        assert len(feed) == 1
        assert feed[0]["kind"] == "broadcast"
        assert json.loads(feed[0]["payload"])["instruction_task_id"] == task_id
    finally:
        verify.close()


def test_d01_h2_db_error_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fehlt die tasks-Tabelle: HTTP-Fehler, kein Erfolg, keine task_id."""
    db_path = tmp_path / "w4d_broken_kanban.db"
    _make_kanban_db(db_path, with_tasks=False)

    def _patched_conn() -> sqlite3.Connection:
        return sqlite3.connect(str(db_path))

    monkeypatch.setattr(ops_api, "_get_kanban_connection", _patched_conn)

    with pytest.raises(HTTPException) as excinfo:
        ops_org.create_agent_instruction_task(
            ops_org.AgentInstructionRequest(
                message="Anweisung an Agenten",
                agent_id="recruiter_specialist",
            )
        )
    assert excinfo.value.status_code == 500
    assert "task_id" not in str(excinfo.value.detail)


def test_d01_h2_empty_agent_id_is_rejected() -> None:
    """Ohne Ziel-Agenten darf kein Task (und kein Erfolg) entstehen."""
    with pytest.raises(HTTPException) as excinfo:
        ops_org.create_agent_instruction_task(
            ops_org.AgentInstructionRequest(message="Anweisung", agent_id="")
        )
    assert excinfo.value.status_code == 400

"""Regressionstest R-16: Vier-Augen-Qualitätstor muss fail-closed sein.

Reviewer-LLM-Ausfall (Exception) oder fehlendes JSON im Review-Response darf
den Task NICHT auf 'done' laufen lassen. Vor dem Fix wurden beide Fehlerfaelle
als {"verdict": "approved", "score": 75/80} erfunden (R-16).
"""

import asyncio
import json
import os
import sqlite3
import sys
import types
from unittest import mock

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.operations_api as ops  # noqa: E402


def _temp_kanban_db(task_status="review"):
    """Dateibasierte Temp-DB (jede `_get_kanban_connection`-Verbindung sieht dieselben Daten)."""
    import tempfile
    _tmpdir = tempfile.mkdtemp(prefix="orangeb_r16_")
    db_path = os.path.join(_tmpdir, "kanban.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT,
            status TEXT, result TEXT, created_at TEXT, started_at TEXT,
            completed_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT,
            payload TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO tasks (id, title, body, assignee, status, result) "
        "VALUES ('t-a', 'Task A', 'Briefing', 'katharina', ?, 'Ergebnis hier')",
        (task_status,),
    )
    conn.commit()
    conn.close()

    def _open():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    return _open, db_path


@pytest.mark.asyncio
async def test_reviewer_exception_verdict_changes_requested():
    """Exception im Reviewer-Dispatch → changes_requested, Task bleibt in review."""
    from backend.operations_api import QualityReviewRequest
    open_db, db_path = _temp_kanban_db()
    dispatcher = types.SimpleNamespace()
    async def _boom(**kwargs):
        raise RuntimeError("Reviewer-LLM down")
    dispatcher.dispatch_to_omniroute_or_container = _boom

    with mock.patch.object(ops, "_get_kanban_connection", side_effect=open_db), \
         mock.patch.object(ops, "_load_profiles_map", return_value={}), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.agent_aliases.resolve_agent_id", side_effect=lambda a: a), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", QualityReviewRequest())

    assert res["quality_review"]["status"] == "changes_requested"
    assert res["quality_review"]["score"] == 0
    with sqlite3.connect(db_path) as check:
        cur = check.execute("SELECT status FROM tasks WHERE id = 't-a'")
        assert cur.fetchone()[0] == "review"


@pytest.mark.asyncio
async def test_reviewer_prose_answer_no_json_fail_closed():
    """Antwort ohne JSON (Prosa/Timeout) → changes_requested statt invented approval."""
    from backend.operations_api import QualityReviewRequest
    open_db, db_path = _temp_kanban_db()
    dispatcher = types.SimpleNamespace()
    async def _prose(**kwargs):
        return {"content": "Alles gut, sieht sauber aus!"}
    dispatcher.dispatch_to_omniroute_or_container = _prose

    with mock.patch.object(ops, "_get_kanban_connection", side_effect=open_db), \
         mock.patch.object(ops, "_load_profiles_map", return_value={}), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.agent_aliases.resolve_agent_id", side_effect=lambda a: a), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", QualityReviewRequest())

    assert res["quality_review"]["status"] == "changes_requested"
    assert res["quality_review"]["score"] == 0
    with sqlite3.connect(db_path) as check:
        cur = check.execute("SELECT status FROM tasks WHERE id = 't-a'")
        assert cur.fetchone()[0] == "review"


@pytest.mark.asyncio
async def test_explicit_approval_still_works():
    """Human-in-the-Loop Override (force_verdict) bleibt funktionsfaehig."""
    from backend.operations_api import QualityReviewRequest
    open_db, db_path = _temp_kanban_db()
    dispatcher = types.SimpleNamespace()
    async def _unused(**kwargs):
        raise AssertionError("Override muss keinen LLM rufen")
    dispatcher.dispatch_to_omniroute_or_container = _unused

    req = QualityReviewRequest(force_verdict="approved", comment="Freigegeben")
    with mock.patch.object(ops, "_get_kanban_connection", side_effect=open_db), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", req)

    assert res["quality_review"]["status"] == "approved"
    assert res["quality_review"]["score"] == 100
    with sqlite3.connect(db_path) as check:
        cur = check.execute("SELECT status FROM tasks WHERE id = 't-a'")
        assert cur.fetchone()[0] == "done"

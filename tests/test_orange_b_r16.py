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

    def _open(*_a, **_kw):
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
         mock.patch.object(ops, "require_admin_or_503", return_value={"role": "admin"}), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.agent_aliases.resolve_agent_id", side_effect=lambda a: a), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", None, QualityReviewRequest())

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
         mock.patch.object(ops, "require_admin_or_503", return_value={"role": "admin"}), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.agent_aliases.resolve_agent_id", side_effect=lambda a: a), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", None, QualityReviewRequest())

    assert res["quality_review"]["status"] == "changes_requested"
    assert res["quality_review"]["score"] == 0
    with sqlite3.connect(db_path) as check:
        cur = check.execute("SELECT status FROM tasks WHERE id = 't-a'")
        assert cur.fetchone()[0] == "review"


@pytest.mark.asyncio
async def test_body_force_verdict_cannot_approve_and_four_eyes_override_still_works():
    """W2-C/W5: `force_verdict` ist wirkungslos; Freigabe nur ueber 4 Augen.

    Der alte Test erwartete, dass ein Body-Feld ``force_verdict='approved'``
    das Review freigibt. Genau das war H-14-2 (faelschbares Vier-Augen-Gate)
    und wurde entfernt. Der legitime Weg ist der separate Override-Endpunkt
    mit Session-Actor, zweiter Identitaet und HITL-Proof.
    """
    from backend.operations_api import (
        QualityReviewOverrideRequest,
        QualityReviewRequest,
    )
    open_db, db_path = _temp_kanban_db()
    dispatcher = types.SimpleNamespace()

    async def _boom(**kwargs):
        raise RuntimeError("Reviewer-LLM down")

    dispatcher.dispatch_to_omniroute_or_container = _boom

    # 1) Body-Override darf nichts bewirken — das Review bleibt fail-closed.
    req = QualityReviewRequest(force_verdict="approved", comment="Freigegeben")
    assert not hasattr(req, "force_verdict")
    with mock.patch.object(ops, "_get_kanban_connection", side_effect=open_db), \
         mock.patch.object(ops, "_load_profiles_map", return_value={}), \
         mock.patch.object(ops, "require_admin_or_503", return_value={"role": "admin"}), \
         mock.patch.dict(sys.modules, {"core_dispatcher": dispatcher}), \
         mock.patch("backend.agent_aliases.resolve_agent_id", side_effect=lambda a: a), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}}, None)):
        res = await ops.trigger_quality_review("t-a", None, req)
    assert res["quality_review"]["status"] == "changes_requested"

    # 2) Der vorgesehene 4-Augen-Weg funktioniert weiterhin — aber nur mit
    #    verifiziertem Session-Actor und passkey-gebundenem Einmal-Proof.
    meta = {"tasks": {"t-a": {"quality_review": {
        "status": "changes_requested", "reviewer_id": "robert",
        "reviewer": "robert", "score": 0,
    }}}}

    def _apply_meta(fn):
        return fn(meta)

    override_req = QualityReviewOverrideRequest(
        reason="Zweiter Reviewer hat den Einwand geprueft", passkey_proof_token="proof-token"
    )
    with mock.patch.object(ops, "_get_kanban_connection", side_effect=open_db), \
         mock.patch.object(ops, "require_admin_or_503", return_value=None), \
         mock.patch.object(ops, "require_session_actor", return_value="supervisor-b"), \
         mock.patch.object(ops, "_current_quality_review", return_value=dict(meta["tasks"]["t-a"]["quality_review"])), \
         mock.patch.object(ops, "_task_created_by", return_value="katharina"), \
         mock.patch("backend.passkey_hitl.consume_hitl_proof_token", return_value=True) as proof, \
         mock.patch("backend.audit_log._require_audit_event", lambda *a, **k: None), \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=_apply_meta):
        override = await ops.override_quality_review(None, "t-a", override_req)

    assert override["quality_review"]["status"] == "approved"
    assert override["quality_review"]["source"] == "four_eyes_override"
    proof.assert_called_once()
    assert proof.call_args.args[1:] == ("supervisor-b", "system")
    assert proof.call_args.kwargs["action"] == "quality_review_override"
    assert proof.call_args.kwargs["resource"] == "t-a"
    with sqlite3.connect(db_path) as check:
        cur = check.execute("SELECT status FROM tasks WHERE id = 't-a'")
        assert cur.fetchone()[0] == "done"

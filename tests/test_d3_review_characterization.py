# -*- coding: utf-8 -*-
"""D3/5 Characterization-Tests fuer 4-Augen-Qualitaetsreview & Hoheits-Override."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import backend.operations_api as ops_api


def _init_review_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            result TEXT,
            created_by TEXT,
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
        INSERT INTO tasks (id, title, body, assignee, status, result, created_by, completed_at)
        VALUES ('t-rev-1', 'Audit', 'Pruefe Bericht', 'coder', 'review', 'Ergebnis liegt vor', 'alice', NULL)
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


def test_d3_5_four_eyes_override_fail_closed_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selbstfreigabe (Ersteller/Reviewer) -> 403, ungueltiger Proof -> 403, zweiter Approver -> Evidence."""
    review = {"reviewer_id": "katharina", "reviewer": "Katharina", "status": "changes_requested"}

    # 1. Negativprobe: Task-Ersteller darf nicht selbst overridet werden -> 403
    with pytest.raises(HTTPException) as exc_self:
        ops_api._require_four_eyes_override(
            task_id="t-rev-1",
            actor="alice",
            review=review,
            reason="Ausreichend lange Begruendung fuer Override",
            proof_token="tok-1",
            action="quality_review_override",
            created_by="alice",
        )
    assert exc_self.value.status_code == 403

    # 2. Negativprobe: ungueltiger Passkey-Proof -> 403
    monkeypatch.setattr("backend.passkey_hitl.consume_hitl_proof_token", lambda *_a, **_kw: False)
    with pytest.raises(HTTPException) as exc_proof:
        ops_api._require_four_eyes_override(
            task_id="t-rev-1",
            actor="bob",
            review=review,
            reason="Ausreichend lange Begruendung fuer Override",
            proof_token="bad-tok",
            action="quality_review_override",
            created_by="alice",
        )
    assert exc_proof.value.status_code == 403

    # 3. Positivfall: zweiter Approver + gueltiger Proof + Audit -> Evidence-Block
    monkeypatch.setattr("backend.passkey_hitl.consume_hitl_proof_token", lambda *_a, **_kw: True)
    monkeypatch.setattr("backend.audit_log._require_audit_event", lambda *_a, **_kw: None)
    ev = ops_api._require_four_eyes_override(
        task_id="t-rev-1",
        actor="bob",
        review=review,
        reason="Ausreichend lange Begruendung fuer Override",
        proof_token="good-tok",
        action="quality_review_override",
        created_by="alice",
    )
    assert ev["actor"] == "bob"
    assert ev["hitl_proof_verified"] is True
    assert ev["first_reviewer_id"] == "katharina"


def test_d3_5_trigger_quality_review_fail_closed_and_approved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prosa ohne JSON -> fail-closed changes_requested (score=0); valides JSON -> approved -> done."""
    db_path = tmp_path / "kanban_rev.db"
    _init_review_db(db_path)

    meta_state: Dict[str, Any] = {"tasks": {}}
    monkeypatch.setattr(ops_api, "require_admin_or_503", lambda _req: None)
    monkeypatch.setattr(ops_api, "require_session_actor", lambda _req: "micha")
    monkeypatch.setattr(ops_api, "_get_kanban_connection", _conn_factory(db_path))
    monkeypatch.setattr(ops_api, "_load_profiles_map", lambda: {})
    monkeypatch.setattr("backend.kanban_sidecar.update_kanban_meta", lambda fn: (meta_state, fn(meta_state)))
    monkeypatch.setattr("backend.audit_log._require_audit_event", lambda *_a, **_kw: None)

    import core_dispatcher

    # 1. Fail-closed: Prosa ohne JSON
    monkeypatch.setattr(
        core_dispatcher,
        "dispatch_to_omniroute_or_container",
        AsyncMock(return_value={"content": "Sieht super aus, passt!"}),
    )
    res_bad = asyncio.run(ops_api.trigger_quality_review("t-rev-1", MagicMock()))
    assert res_bad["quality_review"]["status"] == "changes_requested"
    assert res_bad["quality_review"]["score"] == 0

    # 2. Valides JSON -> approved -> Task-Status wechselt von review auf done
    approved_json = json.dumps({
        "verdict": "approved",
        "score": 92,
        "summary": "Vollstaendig und belastbar.",
        "critique_points": [],
        "actionable_next_steps": [],
    })
    monkeypatch.setattr(
        core_dispatcher,
        "dispatch_to_omniroute_or_container",
        AsyncMock(return_value={"content": approved_json}),
    )
    res_ok = asyncio.run(ops_api.trigger_quality_review("t-rev-1", MagicMock()))
    assert res_ok["quality_review"]["status"] == "approved"
    assert res_ok["quality_review"]["score"] == 92

    c = _conn_factory(db_path)()
    row = c.execute("SELECT status FROM tasks WHERE id = 't-rev-1'").fetchone()
    c.close()
    assert row["status"] == "done"

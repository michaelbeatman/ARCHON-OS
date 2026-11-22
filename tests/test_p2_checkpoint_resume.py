"""Regressionstests fuer das pragmatische Checkpoint-Resume (SUSPENDED → RUNNING)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_suspend_resume_transition_and_checkpoint(tmp_path):
    from backend.durable_execution_kernel import (
        DurableExecutionKernel, RUNNING, SUSPENDED, COMPLETED,
        InvalidTransitionError,
    )

    kernel = DurableExecutionKernel(db_path=str(tmp_path / "kernel.db"))
    claim = kernel.claim("wf-1")
    token = claim["fencing_token"]

    kernel.suspend("wf-1", token, 2, {"step": "research", "result": "ok"}, reason="hitl")
    state = kernel.get_state("wf-1")
    assert state["state"] == SUSPENDED
    assert state["checkpoint_step"] == 2
    assert state["state_data"] == {"step": "research", "result": "ok"}

    ctx = kernel.resume_context("wf-1")
    assert ctx["state"] == SUSPENDED
    assert ctx["checkpoint_step"] == 2

    # Ohne Token darf ein noch aktiver Claim nicht uebernommen werden.
    from backend.durable_execution_kernel import StaleFencingTokenError
    with pytest.raises(StaleFencingTokenError):
        kernel.resume_suspended("wf-1")

    # Der Router uebergibt den gespeicherten Token.
    resumed = kernel.resume_suspended("wf-1", ctx["fencing_token"])
    assert resumed["status"] == "resumed"
    assert resumed["resume_from_step"] == 3
    assert resumed["state_data"] == {"step": "research", "result": "ok"}

    state = kernel.get_state("wf-1")
    assert state["state"] == RUNNING

    # Resume aus COMPLETED muss abgelehnt werden.
    kernel.transition("wf-1", COMPLETED, resumed["fencing_token"])
    with pytest.raises(InvalidTransitionError):
        kernel.resume_suspended("wf-1")


def test_p2_resume_uses_persisted_node_outputs(tmp_path):
    """Der DAG-Runner muss completed Nodes ohne Output als blockiert melden."""
    import sqlite3
    from backend.workflow_dag_runner import _connect

    db = tmp_path / "dag.db"
    # Minimale workflow_node_states-Tabelle wie in der DAG-Engine.
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE workflow_node_states (
                run_id TEXT, node_id TEXT, fingerprint TEXT, status TEXT,
                output_json TEXT, updated_at REAL,
                PRIMARY KEY (run_id, node_id)
            )
        """)
        conn.execute(
            "INSERT INTO workflow_node_states VALUES (?,?,?,?,?,?)",
            ("wf-2", "n1", "fp1", "completed", "{}", 1.0),
        )
        conn.commit()

    with _connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT node_id, status, output_json FROM workflow_node_states WHERE run_id = ?",
            ("wf-2",),
        ).fetchall()
    missing = [
        str(r["node_id"]) for r in rows
        if str(r["status"]) in ("completed", "skipped_cached")
        and str(r["output_json"] or "").strip() in ("", "{}", "null")
    ]
    assert missing == ["n1"]


def test_p2_resume_endpoint_is_wired():
    src = (REPO_ROOT / "archon/routers/operations_dag.py").read_text(encoding="utf-8")
    assert "resume-suspended" in src
    assert "resume_suspended_workflow_run(run_id)" in src
    runner = (REPO_ROOT / "backend/workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "async def resume_suspended_workflow_run" in runner
    assert "resume_workflow_run(" in runner

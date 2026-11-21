# -*- coding: utf-8 -*-
"""E2E-Regressionstest der Workflow-/DAG-Engine (Meilenstein Workflow Phase 2/3).

Deckt den Live-E2E-Lauf vom 21.11.2026 dauerhaft ab — mit Mock-Executor,
ohne Live-LLM-Kosten und ohne echte Kanban-DB (db_path/temp):

Template-Nodes -> DAG-Def (Fan-In mit 2 Parents) -> Gate-Pause
-> decide approve (resume) -> completed -> Kanban-Spiegel-Aufrufe.

Ausfuehrung: ./.ci_venv/Scripts/python.exe -m pytest tests/test_workflow_dag_e2e.py -q
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.workflow_templates import _build_dag_def_from_template  # noqa: E402
from backend.workflow_dag_runner import (  # noqa: E402
    get_workflow_run,
    resume_workflow_run,
    run_workflow_dag,
)

TPL = {
    "id": "tpl-e2e",
    "title": "E2E-Regression",
    "inputs": [{"key": "thema", "label": "Thema", "default": "Test"}],
    "nodes": [
        {"id": "n1", "type": "agent", "title": "Schritt {{thema}}", "prompt": "Mach {{thema}}",
         "agent_id": "lisa", "depends_on": []},
        {"id": "n2a", "type": "agent", "title": "Tech", "depends_on": ["n1"]},
        {"id": "n2b", "type": "agent", "title": "Markt", "depends_on": ["n1"]},
        {"id": "n3", "type": "agent", "title": "Synthese (Fan-In 2 Parents)", "depends_on": ["n2a", "n2b"]},
        {"id": "g1", "type": "gate", "title": "Freigabe", "depends_on": ["n3"]},
        {"id": "n4", "type": "agent", "title": "Nachlauf", "depends_on": ["g1"]},
    ],
    "edges": [
        {"from": "n1", "to": "n2a", "condition": "on_success", "data_mode": "full"},
        {"from": "n1", "to": "n2b", "condition": "always", "data_mode": "summary"},
        {"from": "g1", "to": "n4", "condition": "on_success", "data_mode": "full"},
    ],
}


def test_dag_def_baust_fan_in_vollstaendig():
    task_by_node = {n["id"]: f"t-{n['id']}" for n in TPL["nodes"]}
    dag = _build_dag_def_from_template(TPL, {"thema": "Demo"}, task_by_node)
    n3 = next(n for n in dag["nodes"] if n["id"] == "n3")
    assert n3["depends_on"] == ["n2a", "n2b"], "Fan-In darf keine Parents verlieren"
    n1 = dag["nodes"][0]
    assert n1["title"] == "Schritt Demo" and n1["prompt"] == "Mach Demo"
    assert all(n["kanban_task_id"] for n in dag["nodes"])
    assert len(dag["edges"]) == 3


class _MockKanban:
    """Zeichnet _update_kanban_task_status-Aufrufe auf (Kanban-Spiegel, ohne echte DB)."""

    def __init__(self):
        self.updates = []

    def __call__(self, task_id, status, **kwargs):
        self.updates.append((task_id, status, kwargs.get("block_kind")))


def _run(coro):
    return asyncio.run(coro)


def test_full_dag_gate_pause_resume_and_mirror(tmp_path):
    db = str(tmp_path / "workflow_dags.db")
    dag = _build_dag_def_from_template(TPL, {"thema": "Demo"}, {n["id"]: f"t-{n['id']}" for n in TPL["nodes"]})
    mirror = _MockKanban()

    async def mock_exec(node, upstream):
        return {"status": "success", "content": f"done:{node['id']}"}

    async def _flow():
        # 1) Erster Lauf: laeuft bis zum Gate und pausiert
        with patch("backend.workflow_dag_runner._update_kanban_task_status", mirror):
            r1 = await run_workflow_dag(dag_def=dag, executor_fn=mock_exec, run_id="e2etest", db_path=db)
        assert r1["status"] == "paused", r1["node_statuses"]
        assert r1["node_statuses"]["g1"] == "awaiting_gate"
        assert "n4" not in r1["node_statuses"]
        # Gate-Knoten wurde im Kanban auf blocked gesetzt (Spiegel)
        assert ("t-g1", "blocked", "hitl_gate") in mirror.updates, mirror.updates

        # 2) Ablehnung: Downstream wird skipped_condition, Run failed
        r2 = await resume_workflow_run(run_id="e2etest", gate_approvals={"g1": False}, executor_fn=mock_exec, db_path=db)
        assert r2["status"] == "failed"
        assert r2["node_statuses"]["n4"] == "skipped_condition"

        # 3) Freigabe auf frischem Run: Gate completed, Nachlauf laeuft, Run completed
        r3 = await run_workflow_dag(
            dag_def=dag, executor_fn=mock_exec, run_id="e2etest2", db_path=db, gate_approvals={"g1": True}
        )
        assert r3["status"] == "completed"
        assert r3["node_statuses"]["g1"] == "completed"
        assert r3["node_statuses"]["n4"] == "completed"

        # 4) Persistenz: get_workflow_run liefert DAG + Knotenstatus
        st = get_workflow_run("e2etest", db_path=db)
        assert st["status"] == "failed"
        assert set(st["nodes"].keys()) == {"n1", "n2a", "n2b", "n3", "g1", "n4"}

    _run(_flow())


def test_edge_condition_on_failure_skips_downstream(tmp_path):
    db = str(tmp_path / "wf_edge.db")
    dag = {
        "id": "edge-test",
        "nodes": [
            {"id": "a", "type": "agent", "depends_on": []},
            {"id": "b", "type": "agent", "depends_on": ["a"]},
        ],
        "edges": [{"from": "a", "to": "b", "condition": "on_success", "data_mode": "full"}],
    }

    async def failing_exec(node, upstream):
        return {"status": "error", "error": "absichtlich fehlgeschlagen"}

    async def _flow():
        return await run_workflow_dag(dag_def=dag, executor_fn=failing_exec, run_id="edge", db_path=db)

    r = _run(_flow())
    assert r["status"] == "failed"
    assert r["node_statuses"]["a"] == "failed"
    assert r["node_statuses"]["b"] == "skipped_condition"

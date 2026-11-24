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
    # D13-Haertung: fehlendes Run-Cap ist fail-closed (Plan-Validator).
    "max_budget_eur": 10.0,
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

        # 3) Freigabe auf frischem Run: Gate completed, Nachlauf laeuft, Run completed.
        # D13: eine neue Trajectory braucht ein eigenes root_ticket_id (sonst
        # erbt der Lauf Replan-Count/State des vorherigen Runs).
        dag_fresh = {**dag, "root_ticket_id": "ticket-e2etest2", "trajectory_id": "", "_replan_count": 0}
        r3 = await run_workflow_dag(
            dag_def=dag_fresh, executor_fn=mock_exec, run_id="e2etest2", db_path=db, gate_approvals={"g1": True}
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
        "max_budget_eur": 10.0,
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


# --- Fix-Sprint-Regressionen (Anweisung 21.11.2026, Abschnitt 6.1) ---

def test_fanout_without_branches_runs_as_single_node(tmp_path):
    """Fix-Sprint-Test 1: Builtin-Templates typisieren Parallel-Kinder als fanout OHNE
    branches — der Knoten muss als normaler Einzel-Task laufen, nicht als Quorum-Fail."""
    db = str(tmp_path / "wf_fanout.db")
    dag = {
        "id": "fanout-test",
        "max_budget_eur": 10.0,
        "nodes": [
            {"id": "f", "type": "fanout", "agent_id": "lisa", "depends_on": []},  # keine branches!
        ],
        "edges": [],
    }

    async def mock_exec(node, upstream):
        return {"status": "success", "content": f"done:{node['id']}"}

    async def _flow():
        return await run_workflow_dag(dag_def=dag, executor_fn=mock_exec, run_id="fanout", db_path=db)

    r = _run(_flow())
    assert r["status"] == "completed", r["node_statuses"]
    assert r["node_statuses"]["f"] == "completed"


def test_unknown_dependency_and_cycle_fail_with_diagnosis(tmp_path):
    """Fix-Sprint-Test 2: Unbekannte depends_on-ID und Zyklus enden sofort als failed
    mit klarer Fehlermeldung statt endlos paused."""
    db = str(tmp_path / "wf_diag.db")

    async def mock_exec(node, upstream):
        return {"status": "success"}

    async def _flow_unknown():
        return await run_workflow_dag(
            dag_def={"id": "d1", "nodes": [{"id": "a", "type": "agent", "depends_on": ["ghost"]}], "edges": []},
            executor_fn=mock_exec, run_id="diag-unknown", db_path=db,
        )

    r = _run(_flow_unknown())
    assert r["status"] == "failed"
    _msg = str(r.get("error") or r.get("outputs", {}).get("a", {}).get("error") or "")
    # Der Pre-Execution Plan Validator (M110) liefert die Meldung auf Deutsch;
    # ältere Pfade lieferten "Unknown dependency". Beide sind gültig.
    assert ("Unknown dependency" in _msg or "Unbekannte Abhängigkeit" in _msg or "Plan-Validator" in _msg), r

    async def _flow_cycle():
        return await run_workflow_dag(
            dag_def={"id": "d2", "nodes": [
                {"id": "a", "type": "agent", "depends_on": ["b"]},
                {"id": "b", "type": "agent", "depends_on": ["a"]},
            ], "edges": []},
            executor_fn=mock_exec, run_id="diag-cycle", db_path=db,
        )

    r2 = _run(_flow_cycle())
    assert r2["status"] == "failed"
    _msg2 = str(r2.get("error") or "")
    assert ("Cycle" in _msg2 or "Zyklus" in _msg2 or "Plan-Validator" in _msg2), r2


def test_corrupt_custom_templates_block_save_and_backup(tmp_path, monkeypatch):
    """Fix-Sprint-Test 3: Korrupte Template-Datei darf beim naechsten save NICHT still
    alle Templates loeschen — Backup + RuntimeError, atomarer Write bleibt intakt."""
    import backend.workflow_templates as wt

    store = tmp_path / "workflow_templates.json"
    store.write_text("{kaputt-kein-json", encoding="utf-8")
    monkeypatch.setattr(wt, "CUSTOM_TEMPLATES_PATH", str(store))
    # Globales Korrupt-Flag mit eigener Testinstanz isolieren (Save/Restore)
    flag_seen = []

    orig_load = wt._load_custom_templates

    def guarded_load():
        res = orig_load()
        flag_seen.append(wt._CUSTOM_TEMPLATES_CORRUPT)
        return res

    monkeypatch.setattr(wt, "_load_custom_templates", guarded_load)

    # Lesen eines korrupten Stores: liefert [] , aber setzt Flag + Backup
    assert wt._load_custom_templates() == []
    assert wt._CUSTOM_TEMPLATES_CORRUPT is True
    backup = Path(str(store) + ".corrupt")
    assert backup.exists(), "Korrupt-Backup fehlt"
    assert backup.read_text(encoding="utf-8") == "{kaputt-kein-json", "Backup-Inhalt verfaelscht"

    # save/delete duerfen den Store jetzt NICHT still ueberschreiben (Guard in den Callern)
    with pytest.raises(RuntimeError):
        wt.save_workflow_template({"id": "x", "title": "Test", "nodes": [{"id": "n1"}]})
    with pytest.raises(RuntimeError):
        wt.delete_workflow_template("x")

    # Reparatur (gueltige Datei) hebt die Sperre wieder auf
    store.write_text("[]", encoding="utf-8")
    assert wt._load_custom_templates() == []
    assert wt._CUSTOM_TEMPLATES_CORRUPT is False


def test_approve_kanban_task_is_async_and_threaded():
    """Fix-Sprint-Test 4: approve_kanban_task ist async def und arbeitet über
    asyncio.to_thread — kein asyncio.create_task aus einem sync-Threadpool mehr."""
    import ast
    src = Path(BASE_DIR / "backend" / "operations_api.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "approve_kanban_task")
    assert isinstance(fn, ast.AsyncFunctionDef), "approve_kanban_task muss async def sein"
    body_src = ast.get_source_segment(src, fn) or ""
    assert "to_thread" in body_src, "SQLite-Block muss via asyncio.to_thread laufen"
    assert 'VALID_KANBAN_STATUSES' in src, "Status-Validierung fehlt"


def test_parallel_resume_deduplicated_by_per_run_lock(tmp_path):
    """Fix-Sprint-Test 5: Zwei parallele Läufe auf dieselbe run_id — der zweite
    bekommt already_running statt doppeltem Loop."""
    db = str(tmp_path / "wf_lock.db")
    dag = {"id": "lock-test", "max_budget_eur": 10.0, "nodes": [{"id": "a", "type": "agent", "depends_on": []}], "edges": []}

    async def slow_exec(node, upstream):
        await asyncio.sleep(0.4)
        return {"status": "success", "content": "ok"}

    async def _flow():
        t1 = asyncio.ensure_future(run_workflow_dag(dag_def=dag, executor_fn=slow_exec, run_id="lockrun", db_path=db))
        await asyncio.sleep(0.05)  # t1 laeuft sicher im Loop
        r2 = await run_workflow_dag(dag_def=dag, executor_fn=slow_exec, run_id="lockrun", db_path=db)
        r1 = await t1
        return r1, r2

    r1, r2 = _run(_flow())
    assert r1["status"] == "completed"
    assert r2.get("status") == "already_running", r2


def test_omnichannel_content_workflow_quality_gate_and_template(tmp_path):
    """Prueft, dass die Content-Maschine als natives Workflow-Template mit
    deterministischem quality_gate-Node direkt ueber die DAG-Engine laeuft."""
    from backend import workflow_templates as wt

    tpls = {t["id"]: t for t in wt.list_workflow_templates()}
    assert "omnichannel_content_engine" in tpls
    tpl = tpls["omnichannel_content_engine"]
    node_types = {n["id"]: n["type"] for n in tpl["nodes"]}
    assert node_types["cm_slop_gate"] == "quality_gate"
    assert node_types["cm_hitl_release"] == "gate"

    # 1. Sauberer Content passiert das deterministische quality_gate
    db = str(tmp_path / "wf_qgate.db")
    dag_ok = {
        "id": "qgate-ok",
        "max_budget_eur": 10.0,
        "nodes": [
            {"id": "draft", "type": "agent", "depends_on": []},
            {"id": "qgate", "type": "quality_gate", "channel": "linkedin", "min_quality_score": 70, "depends_on": ["draft"]},
        ],
        "edges": [{"from": "draft", "to": "qgate", "condition": "on_success", "data_mode": "full"}],
    }

    async def clean_exec(node, upstream):
        return {
            "status": "success",
            "content": (
                "Wir haben 28 SQLite-Dateien in 3 WAL-Datenbanken konsolidiert und die Latenz um 64 Prozent gesenkt.\n\n"
                "Durch klare Domaenen-Trennung in ops.db, business.db und memory.db laufen 12 Agenten parallel ohne Locks.\n\n"
                "Wie viele Datenbanken verwaltet euer Stack aktuell?"
            ),
        }

    res_ok = _run(run_workflow_dag(dag_def=dag_ok, executor_fn=clean_exec, db_path=db))
    assert res_ok["status"] == "completed"
    assert res_ok["node_statuses"]["qgate"] == "completed"
    assert res_ok["outputs"]["qgate"]["quality_score"] >= 85

    # 2. Slop-lastiger Content wird vom quality_gate hart gestoppt
    dag_slop = {**dag_ok, "id": "qgate-slop"}

    async def slop_exec(node, upstream):
        return {
            "status": "success",
            "content": "In today's fast-paced world we delve into a paradigm shift — a vibrant tapestry — that serves as a game-changer. Moreover, we leverage cutting-edge solutions.",
        }

    res_slop = _run(run_workflow_dag(dag_def=dag_slop, executor_fn=slop_exec, db_path=db))
    assert res_slop["status"] == "failed"
    assert res_slop["node_statuses"]["qgate"] == "failed"
    assert len(res_slop["outputs"]["qgate"]["quality_report"]["slop_hits"]) >= 3


def test_map_dynamic_fanout_node(tmp_path):
    """Punkt 3.2.3: map-Node erzeugt dynamisch N parallele Sub-Nodes aus Upstream-Array."""
    db = str(tmp_path / "wf_map.db")
    dag_map = {
        "id": "wf-map-test",
        "max_budget_eur": 10.0,
        "nodes": [
            {
                "id": "news_fetch",
                "type": "agent",
                "depends_on": [],
            },
            {
                "id": "news_map",
                "type": "map",
                "depends_on": ["news_fetch"],
                "max_items": 3,
                "max_budget_eur": 0.50,
            },
        ],
        "edges": [{"from": "news_fetch", "to": "news_map", "condition": "on_success", "data_mode": "full"}],
    }

    async def mock_exec(node, upstream):
        nid = node.get("id", "")
        if nid == "news_fetch":
            return {
                "status": "success",
                "parsed_output": [
                    {"headline": "News A", "score": 90},
                    {"headline": "News B", "score": 85},
                    {"headline": "News C", "score": 80},
                    {"headline": "News D (ignored by max_items)", "score": 70},
                ],
            }
        # map sub-execution
        item = node.get("map_item") or {}
        return {
            "status": "success",
            "content": f"Analysiert: {item.get('headline')}",
            "cost_usd": 0.002,
        }

    res = _run(run_workflow_dag(dag_def=dag_map, executor_fn=mock_exec, db_path=db))
    assert res["status"] == "completed"
    assert res["node_statuses"]["news_map"] == "completed"
    map_out = res["outputs"]["news_map"]
    assert map_out["items_count"] == 3
    assert map_out["ok_count"] == 3
    assert len(map_out["map_results"]) == 3
    assert round(map_out["cost_usd"], 4) == 0.006


def test_cheap_first_cost_telemetry_persisted(tmp_path):
    """Punkt 3.2.6: total_cost_usd wird pro Run und Node persistiert."""
    db = str(tmp_path / "wf_cost.db")
    dag_cost = {
        "id": "wf-cost-test",
        "max_budget_eur": 10.0,
        "nodes": [
            {"id": "node_a", "type": "agent", "depends_on": []},
            {"id": "node_b", "type": "agent", "depends_on": ["node_a"]},
        ],
        "edges": [{"from": "node_a", "to": "node_b", "condition": "on_success", "data_mode": "full"}],
    }

    async def mock_exec(node, upstream):
        nid = node.get("id")
        cost = 0.0015 if nid == "node_a" else 0.0035
        return {"status": "success", "content": f"done {nid}", "cost_usd": cost}

    res = _run(run_workflow_dag(dag_def=dag_cost, executor_fn=mock_exec, db_path=db))
    assert res["status"] == "completed"
    r = get_workflow_run(res["run_id"], db_path=db)
    assert r is not None
    assert round(float(r.get("total_cost_usd") or 0.0), 4) == 0.0050

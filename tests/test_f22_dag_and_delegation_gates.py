"""F22 (D02): unbekannte agent_id fail-closed, deterministic_script blockiert, DAG-Cap, reserve_hop."""
from __future__ import annotations

import asyncio
import uuid

from backend.agent_router import AgentRouter
from backend.workflow_dag_runner import default_agent_node_executor, run_workflow_dag


def test_f22_unknown_explicit_agent_id_is_blocked_fail_closed(monkeypatch):
    import archon.core.profiles as core_profiles

    monkeypatch.setattr(
        core_profiles,
        "api_get_hermes_profiles",
        lambda: [{"id": "robert", "name": "Robert", "prompt": "Test"}],
    )
    res = asyncio.run(
        default_agent_node_executor(
            {"id": "n-ghost", "type": "agent", "agent_id": "nonexistent_ghost_agent"},
            {},
        )
    )
    assert res["status"] == "blocked"
    assert res["error_code"] == "UNKNOWN_AGENT_ID"


def test_f22_deterministic_script_without_executor_is_blocked(monkeypatch):
    import backend.execution_routing_guard as erg_mod

    monkeypatch.setattr(
        erg_mod,
        "classify_execution_layer",
        lambda *_a, **_kw: {"layer": "deterministic_script", "confidence": 0.99},
    )
    router = AgentRouter()
    out = asyncio.run(
        router._check_deterministic_execution_layer(
            [{"role": "user", "content": "Fuehre deterministisches Skript aus"}],
            agent_id="coder",
            tid="t-f22-det",
        )
    )
    assert out is not None
    assert out["blocked"] is True
    assert out["error_code"] == "DETERMINISTIC_SCRIPT_NO_EXECUTOR"


def test_f22_dag_cap_blocks_unpriced_downstream_node_when_spent_reaches_cap(tmp_path):
    """Unbezifferter Folge-Node (ohne eigenes max_budget_eur) wird blockiert, sobald Run-Cap erschoepft ist."""
    called = []

    async def _exec(node, _up):
        called.append(node["id"])
        if node["id"] == "n1":
            return {"status": "success", "content": "done", "cost_usd": 1.0}
        return {"status": "success", "content": "should not run"}

    dag = {
        "id": "wf_f22_cap",
        "max_budget_eur": 1.0,
        "root_ticket_id": f"f22-cap-{uuid.uuid4().hex[:8]}",
        "nodes": [
            {"id": "n1", "type": "agent"},
            {"id": "n2", "type": "agent", "depends_on": ["n1"]},
        ],
    }
    res = asyncio.run(run_workflow_dag(dag, executor_fn=_exec, db_path=str(tmp_path / "dag.db")))
    assert called == ["n1"], f"n2 haette durch Budget-Cap blockiert werden muessen: {called}"
    assert res["outputs"]["n2"]["status"] == "blocked"
    assert res["outputs"]["n2"]["failure_reason"] == "BUDGET_EXHAUSTED"


def test_f22_rejected_delegations_do_not_consume_hop_budget(monkeypatch):
    """5 abgelehnte Delegationen duerfen keinen Hop aus trajectory_budget verbrauchen."""
    import archon.core.delegation as dlg
    import backend.trajectory_budget as tb

    reserved_calls = []
    orig_reserve = tb.reserve_hop

    def _spy_reserve(*args, **kwargs):
        reserved_calls.append((args, kwargs))
        return orig_reserve(*args, **kwargs)

    monkeypatch.setattr(tb, "reserve_hop", _spy_reserve)
    monkeypatch.setattr(
        dlg,
        "api_get_hermes_profiles",
        lambda: [{"id": "robert", "name": "Robert"}, {"id": "coder", "name": "Coder"}],
    )
    monkeypatch.setattr(dlg, "_check_delegation_permission", lambda _d, _z: (False, "hierarchie_verboten"))

    tid = f"traj-f22-{uuid.uuid4().hex[:8]}"
    for _ in range(5):
        out = dlg._execute_delegation(
            "coder",
            {"ziel_agent": "robert", "auftrag": "Test", "root_ticket_id": tid},
            provider="openrouter",
            all_keys={},
            origin_session_id=tid,
        )
        assert "DELEGATION ABGELEHNT" in str(out)
    assert reserved_calls == [], f"Abgelehnte Delegationen durften keinen Hop reservieren: {reserved_calls}"

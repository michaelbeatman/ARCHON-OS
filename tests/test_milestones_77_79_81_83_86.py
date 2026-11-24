# -*- coding: utf-8 -*-
import asyncio
import uuid

from backend.agent_router import (
    chat_with_verification_escalation,
    select_quota_and_escalation_route,
)
from backend.flightlog_backtester import (
    backtest_policy,
    detect_silent_failures,
    record_flight_event,
)
from backend.kanban_verifier import (
    cross_model_verify_card,
    detect_deleted_test_assertions,
    pick_independent_verifier_model,
)
from backend.offline_memory_vault import (
    aead_decrypt,
    aead_encrypt,
    load_or_create_vault_key,
    recall_memory,
    store_memory,
)
from backend.workflow_dag_runner import run_workflow_dag


def test_m77_workflow_dag_fanout_gate_and_resume(tmp_path):
    db = str(tmp_path / "wf.db")
    # Eindeutige IDs pro Testlauf: Flightlog/Trajectory-Caps sind global
    # (ops.db) und wuerden bei wiederholten Laeufen einen Tool-Loop melden.
    run_id = f"run-1-{uuid.uuid4().hex[:12]}"
    calls = []

    async def fake_exec(node, upstream):
        calls.append(node.get("branch") or node["id"])
        return {"status": "success", "val": f"ok-{node.get('branch') or node['id']}"}

    dag = {
        "id": "wf-release",
        # D13-Haertung: der Plan-Validator verlangt einen Run-Cap (fail-closed).
        "max_budget_eur": 10.0,
        # D13: eigene Trajectory pro Testlauf, sonst erbt der Lauf den
        # Hop-Cap-Zaehler einer frueheren Ausfuehrung aus der globalen ops.db.
        "root_ticket_id": f"wf-release-{uuid.uuid4().hex[:12]}",
        "nodes": [
            {"id": "fan", "type": "fanout", "branches": ["a", "b"], "quorum_min": 2},
            {"id": "approval", "type": "gate", "depends_on": ["fan"]},
            {"id": "ship", "type": "agent", "depends_on": ["approval"]},
        ],
    }

    # 1. Run until gate pauses
    r1 = asyncio.run(run_workflow_dag(dag, fake_exec, run_id=run_id, db_path=db))
    assert r1["status"] == "paused"
    assert r1["node_statuses"]["fan"] == "completed"
    assert r1["node_statuses"]["approval"] == "awaiting_gate"
    assert sorted(calls) == ["a", "b"]

    # 2. Resume with gate approved -> fan MUST be skipped_cached!
    # D13: der pausierte Lauf schliesst seine Trajectory als "failed"; der
    # Resume-Lauf braucht daher eine eigene Trajectory, sonst blockiert
    # reserve_hop den Nachlauf mit TRAJECTORY_FAILED.
    dag_resume = {
        **dag,
        "root_ticket_id": f"wf-release-{uuid.uuid4().hex[:12]}",
        "trajectory_id": "",
    }
    calls.clear()
    r2 = asyncio.run(
        run_workflow_dag(dag_resume, fake_exec, run_id=run_id,
                         gate_approvals={"approval": True}, db_path=db)
    )
    assert r2["status"] == "completed"
    assert r2["node_statuses"]["fan"] == "skipped_cached"
    assert r2["node_statuses"]["ship"] == "completed"
    assert calls == ["ship"]


def test_m79_offline_memory_vault_aead_and_recall(tmp_path):
    db = str(tmp_path / "vault.db")
    key = load_or_create_vault_key(str(tmp_path / "vault.key"))

    blob = aead_encrypt(key, b"Geheimer Vertrag 42", aad=b"holding")
    assert b"Geheimer Vertrag" not in blob
    assert aead_decrypt(key, blob, aad=b"holding") == b"Geheimer Vertrag 42"

    store_memory("holding", "Die Holding GmbH hat 25000 EUR Stammkapital.", tags=["recht"], db_path=db, key=key)
    store_memory("holding", "Server-Port ist 8420 mit WAL-Mode.", tags=["tech"], db_path=db, key=key)

    hits = recall_memory("holding", "Stammkapital Holding GmbH", top_k=1, db_path=db, key=key)
    assert len(hits) == 1
    assert "25000 EUR" in hits[0]["content"]


def test_m81_cross_model_verifier_and_assertion_guard():
    diff = """--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1,3 +1,2 @@
-    assert total == 100
+    pass
"""
    deleted = detect_deleted_test_assertions(diff)
    assert deleted == ["assert total == 100"]

    assert pick_independent_verifier_model("anthropic/claude-sonnet-4") == "deepseek/deepseek-chat"
    assert pick_independent_verifier_model("deepseek/deepseek-chat") == "google/gemini-2.5-pro"

    res = cross_model_verify_card("t-99", primary_model="anthropic/claude-sonnet-4", diff_text=diff)
    assert res["passed"] is False
    assert res["requires_hitl"] is True
    assert res["block_kind"] == "deleted_test_assertions_hitl"


def test_m83_flightlog_and_policy_backtester(tmp_path):
    db = str(tmp_path / "flight.db")
    for _ in range(3):
        record_flight_event("r-1", "coder", "terminal", {"cmd": "rm -rf /tmp/x"}, tool_ok=False, tokens_used=2000, db_path=db)

    diag = detect_silent_failures("r-1", final_status="success", final_output="ok", db_path=db)
    assert diag["silent_failure"] is True
    assert "hidden_tool_errors:3" in diag["flags"]
    assert "tool_loop:terminal" in diag["flags"]
    assert "effort_collapse" in diag["flags"]

    bt = backtest_policy({"blocked_tools": ["terminal"]}, db_path=db)
    assert bt["would_block_count"] == 3
    assert bt["would_miss_failed_count"] == 0


def test_m86_quota_and_verification_escalation():
    q_pick = select_quota_and_escalation_route("anthropic/claude-sonnet-4", remaining_quota_pct=30.0, quota_threshold_pct=51.0)
    assert q_pick["model"] == "deepseek/deepseek-chat"
    assert q_pick["reason"] == "quota_threshold_fallback"

    class _FakeRouter:
        def __init__(self):
            self.models = []

        async def chat_completion(self, messages, provider, model, api_keys, **kwargs):
            self.models.append(model)
            return "bad" if "deepseek" in model else "verified-good"

    fake = _FakeRouter()
    out = asyncio.run(
        chat_with_verification_escalation(
            router_instance=fake,
            messages=[{"role": "user", "content": "hi"}],
            provider="omniroute",
            primary_model="deepseek/deepseek-chat",
            api_keys={},
            verifier_fn=lambda txt: txt == "verified-good",
        )
    )
    assert fake.models == ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"]
    assert out["escalated"] is True
    assert out["content"] == "verified-good"

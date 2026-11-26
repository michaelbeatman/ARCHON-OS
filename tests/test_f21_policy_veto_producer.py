"""F21 (D14): Strukturierter Policy-Veto-Produzent am Dispatch-Chokepoint."""
from __future__ import annotations

import pytest

import core_dispatcher
from backend.consensus_gate import resolve_debate_consensus


@pytest.mark.asyncio
async def test_f21_dispatch_produces_structured_guardrail_result_and_triggers_hard_veto(monkeypatch):
    """End-to-End: Dispatch-Chokepoint erzeugt guardrail_result auch ohne status='blocked' -> hartes Boardroom-Veto."""
    import backend.concurrency_throttle as ct_mod
    import backend.role_budget_engine as rbe_mod
    import backend.semantic_cache as sc_mod

    async def _fake_acquire(*_a, **_kw):
        return True

    async def _fake_release(*_a, **_kw):
        return None

    monkeypatch.setattr(ct_mod.concurrency_throttle, "acquire_slot", _fake_acquire)
    monkeypatch.setattr(ct_mod.concurrency_throttle, "release_slot", _fake_release)
    monkeypatch.setattr(sc_mod.semantic_cache_manager, "lookup", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        rbe_mod.budget_bank,
        "reserve",
        lambda *_a, **_kw: {"allowed": True, "reservation_id": "res-f21"},
    )
    monkeypatch.setattr(rbe_mod.budget_bank, "settle", lambda *_a, **_kw: None)
    monkeypatch.setattr(rbe_mod.budget_bank, "release", lambda *_a, **_kw: None)

    async def _fake_exec(*_a, **_kw):
        # Bewusst NICHT status='blocked', sondern status='needs_human' mit Policy-Error-Code
        return {
            "status": "needs_human",
            "error_code": "POLICY_VIOLATION_EU_AI_ACT",
            "content": "Compliance-Stopp fuer diese Anfrage.",
            "model": "deepseek/deepseek-chat",
            "provider": "openrouter",
        }

    monkeypatch.setattr(core_dispatcher, "_dispatch_to_omniroute_or_container_exec", _fake_exec)

    res = await core_dispatcher.dispatch_to_omniroute_or_container(
        agent_id="compliance_officer",
        agent_name="Compliance Officer",
        prompt="Bewerte den Launch",
        task_id="task-f21-veto",
    )

    assert "guardrail_result" in res
    gr = res["guardrail_result"]
    assert gr["policy_violation"] is True
    assert gr["guardrail_violation"] is True
    assert gr["severity"] == "high"
    assert gr["error_code"] == "POLICY_VIOLATION_EU_AI_ACT"

    # Konsument (Boardroom + Consensus-Gate) wertet das produzierte guardrail_result als hartes Veto
    br_fields = core_dispatcher._boardroom_guardrail_result(res)
    assert br_fields["policy_violation"] is True
    assert br_fields["guardrail_violation"] is True

    consensus = resolve_debate_consensus(
        [
            {"agent_id": "founder", "tier": "executive", "content": "Zustimmung, go!"},
            {"agent_id": "cfo", "tier": "executive", "content": "Zustimmung, go!"},
            {"agent_id": "compliance_officer", "tier": "lead", "content": res["content"], **br_fields},
        ]
    )
    assert consensus["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"


@pytest.mark.asyncio
async def test_f21_clean_and_transient_error_dispatch_do_not_raise_false_policy_veto(monkeypatch):
    """Negativprobe: sauberer Dispatch und transienter Fehler setzen policy_violation=False."""
    ok_res = core_dispatcher._with_prompt_info({"status": "success", "content": "Alles gut"})
    assert ok_res["guardrail_result"]["policy_violation"] is False
    assert ok_res["guardrail_result"]["guardrail_violation"] is False

    err_res = core_dispatcher._with_prompt_info(
        {"status": "error", "error_code": "UPSTREAM_TIMEOUT", "content": "Timeout"}
    )
    assert err_res["guardrail_result"]["policy_violation"] is False
    assert err_res["guardrail_result"]["guardrail_violation"] is False

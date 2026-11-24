"""Re-Audit-MED-Welle 2A — Dispatch-/Router-Reste in eigenen Dateien.

Deckt die noch offenen MED-Funde aus domain_01/05/07/08/12/13 ab, die in
core_dispatcher.py, backend/agent_router.py und backend/llm_kernel.py liegen.
Kein Replay, keine Migration, keine DB-abhängigen Fixtures.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


async def _events(*items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# D01: leere Boardroom-Debatte darf kein "success" sein
# ---------------------------------------------------------------------------

def _run_boardroom(monkeypatch, events):
    import core_dispatcher

    monkeypatch.setattr(
        core_dispatcher,
        "stream_boardroom_debate",
        lambda *a, **k: _events(*events),
    )
    return asyncio.run(
        core_dispatcher.run_boardroom_debate(
            task="Testauftrag", max_rounds=2, chairman_id="c", active_agents=[]
        )
    )


def test_boardroom_empty_stream_is_incomplete(monkeypatch):
    res = _run_boardroom(monkeypatch, [])
    assert res["status"] == "incomplete"
    assert res["incomplete_reason"] == "no_done_event"
    assert res["synthesis"] == ""


def test_boardroom_done_without_synthesis_is_incomplete(monkeypatch):
    res = _run_boardroom(monkeypatch, [{
        "type": "done",
        "synthesis": "   ",
        "consensus_verdict": "CONSENSUS_REACHED",
    }])
    assert res["status"] == "incomplete"
    assert res["incomplete_reason"] == "empty_synthesis"


def test_boardroom_done_with_consensus_and_synthesis_is_success(monkeypatch):
    res = _run_boardroom(monkeypatch, [{
        "type": "done",
        "synthesis": "Eine echte Synthese.",
        "consensus_verdict": "CONSENSUS_REACHED",
        "consensus_reached": True,
    }])
    assert res["status"] == "success"
    assert res["is_final_decision"] is True


def test_boardroom_no_consensus_keeps_no_consensus(monkeypatch):
    res = _run_boardroom(monkeypatch, [{
        "type": "done",
        "synthesis": "Kein Konsens erreicht.",
        "consensus_verdict": "NO_CONSENSUS",
    }])
    assert res["status"] == "no_consensus"
    assert res["is_final_decision"] is False


# ---------------------------------------------------------------------------
# D13: Boardroom-Guard-Fenster + Fail-Closed
# ---------------------------------------------------------------------------

def test_boardroom_guard_uses_policy_window_and_fails_closed():
    src = _src("core_dispatcher.py")
    block = src.split("Abbruch zu Beginn jeder Runde pruefen", 1)[1].split(
        "if round_num == 1", 1
    )[0]
    assert "guard_window_size()" in block
    assert "debate_statements[-8:]" not in block
    assert "logger.error" in block
    assert "circuit_breaker_unavailable" in block


# ---------------------------------------------------------------------------
# D07: Eskalation wird reverifiziert; ohne Verifier nie "bestanden"
# ---------------------------------------------------------------------------

def _fake_router(second_reply: str):
    class _Router:
        def __init__(self):
            self.models = []

        async def chat_completion(self, messages, provider, model, api_keys, **kwargs):
            self.models.append(model)
            return "bad" if "deepseek" in model else second_reply

    return _Router()


def _escalate(router, verifier):
    from backend.agent_router import chat_with_verification_escalation

    return asyncio.run(chat_with_verification_escalation(
        router_instance=router,
        messages=[{"role": "user", "content": "hi"}],
        provider="omniroute",
        primary_model="deepseek/deepseek-chat",
        api_keys={},
        verifier_fn=verifier,
    ))


def test_escalation_output_is_reverified():
    verifier_calls = []

    def verifier(text):
        verifier_calls.append(text)
        return text == "verified-good"

    router = _fake_router("verified-good")
    out = _escalate(router, verifier)
    assert router.models == ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"]
    # erster Call + eskalierter Call => der Verifier sah BEIDE Antworten
    assert verifier_calls == ["bad", "verified-good"]
    assert out["status"] == "success"
    assert out["verification"] == "passed"


def test_escalation_failure_is_not_success():
    router = _fake_router("still-bad")
    out = _escalate(router, lambda text: text == "verified-good")
    assert out["escalated"] is True
    assert out["status"] == "verification_failed"
    assert out["needs_human"] is True
    assert out["verification"] == "failed"


def test_missing_verifier_is_marked_unverified(monkeypatch):
    from backend import agent_router

    async def first_only(self, messages, provider, model, api_keys, **kwargs):
        return "irgendwas"

    monkeypatch.setattr(agent_router.AgentRouter, "chat_completion", first_only)
    out = _escalate(object.__new__(agent_router.AgentRouter), None)
    assert out["verification"] == "unverified"
    assert out["status"] == "unverified"


# ---------------------------------------------------------------------------
# D01: suspend_task ist kein Fake-Erfolg mehr
# ---------------------------------------------------------------------------

def test_suspend_task_raises_instead_of_fake_success():
    from backend.agent_router import AgentRouter

    with pytest.raises(NotImplementedError, match="durable_execution_kernel.suspend"):
        AgentRouter.suspend_task(object.__new__(AgentRouter), "task-1")


# ---------------------------------------------------------------------------
# D12/D05/D07/D08: Kosten-Marker, Audit-Log-Level, Deadline, to_thread
# ---------------------------------------------------------------------------

def test_dispatch_cost_fallback_is_marked_unverified():
    src = _src("core_dispatcher.py")
    block = src.split("die Provider-Hops liefern meist keinen cost_usd", 1)[1].split(
        "is_ok = res.get", 1
    )[0]
    assert "estimate_model_cost_usd" in block
    assert 'res["cost_unverified"] = est_cost_unverified' in block
    assert "0.00000015" in block  # nur noch letzte Fallback-Schätzung


def test_audit_and_receipt_errors_use_error_level():
    src = _src("core_dispatcher.py")
    for marker in (
        "Silent-Failure-Audit fehlgeschlagen",
        "Receipt fehlgeschlagen",
        "Usage-Audit-Log fehlgeschlagen",
        "Cache-Content-Cleanup fehlgeschlagen",
    ):
        line = next(l for l in src.splitlines() if marker in l)
        assert "logger.error" in line


def test_cache_cleanup_failure_does_not_return_success():
    src = _src("core_dispatcher.py")
    block = src.split("Cache-Content-Cleanup fehlgeschlagen", 1)[1].split(
        "async with _get_task_semaphore", 1
    )[0]
    assert "cache_clean_ok = False" in block
    assert "if cache_clean_ok:" in block


def test_fallback_chain_has_global_deadline():
    src = _src("backend/agent_router.py")
    block = src.split("chain_deadline = time.monotonic()", 1)[1].split(
        "async def stream_chat_completion", 1
    )[0]
    assert "FALLBACK_CHAIN_DEADLINE" in block
    assert "timeout=min(90.0" in block
    assert "asyncio.wait_for" in block


def test_receipt_cost_never_claims_zero_on_estimation_error():
    src = _src("backend/agent_router.py")
    assert '["cost_unverified"] if est_cost_unverified' in src
    assert '["cost_unverified"] if _stream_cost_unverified' in src
    assert "est_cost = round((p_toks * 0.00000015)" in src


def test_key_scan_is_offloaded_to_thread():
    dispatcher = _src("core_dispatcher.py")
    kernel = _src("backend/llm_kernel.py")
    assert "await asyncio.to_thread(api_provider.collect_keys)" in dispatcher
    assert "await asyncio.to_thread(api_provider.collect_keys)" in kernel

"""Welle-1-Regression: NO_CONSENSUS, Policy-Veto, Prompts, leere Antworten.

Nur Produktivpfade: backend/consensus_gate.py, core_dispatcher.py,
archon/routers/boardroom.py. Keine PostgreSQL-Migration, kein Coroutine-Replay.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --- consensus_gate: Veto + Typisierung + Autoritaet ------------------------

def test_policy_veto_is_hard_and_not_overridable():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        {"agent_id": "a", "content": "KONSENS_ERREICHT"},
        {"agent_id": "b", "content": "AGREE"},
        {"agent_id": "c", "content": "ZUSTIMME", "policy_violation": True},
    ])
    assert res["consensus_reached"] is False
    assert res["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"
    assert res["veto_by"] == "c"
    assert res["tie_break_rule"] == "executive>lead>specialist>no_consensus"
    assert res["authority_weights"]["executive"] > res["authority_weights"]["specialist"]


def test_marker_veto_without_flag():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        {"agent_id": "a", "content": "AGREE"},
        {"agent_id": "b", "content": "POLICY_VIOLATION: EU AI Act verletzt"},
    ])
    assert res["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"
    assert res["veto_by"] == "b"


def test_debate_statement_forbids_extra_fields():
    from backend.consensus_gate import DebateStatement

    with pytest.raises(ValidationError):
        DebateStatement(agent_id="a", content="x", unknown_field=1)
    stmt = DebateStatement(
        agent_id="a", content="x", trace_id="t", session_id="s",
        correlation_id="c", policy_violation=False, severity="low",
    )
    assert stmt.trace_id == "t"


def test_authority_tie_break_executive_wins():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus(
        [
            {"agent_id": "exec", "content": "ZUSTIMME"},
            {"agent_id": "spec", "content": "WIDERSPRUCH"},
        ],
        authority={"exec": "executive", "spec": "specialist"},
    )
    assert res["consensus_reached"] is True
    assert res["verdict"] == "CONSENSUS_REACHED_BY_AUTHORITY"


# --- core_dispatcher: leere Antwort / n8n / NO_CONSENSUS --------------------

def test_parse_empty_response_raises():
    import core_dispatcher

    with pytest.raises(RuntimeError):
        core_dispatcher.parse_omniroute_response("")
    with pytest.raises(RuntimeError):
        core_dispatcher.parse_omniroute_response("not json at all")


def test_container_http200_without_payload_is_error(monkeypatch):
    import core_dispatcher

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(core_dispatcher.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr(core_dispatcher, "_gate_container_dispatch", lambda *a, **k: {
        "data_category": "general", "zero_egress_active": False,
    })

    res = asyncio.run(core_dispatcher.dispatch_to_odysseus("odysseus-agent", "prompt"))
    assert res["status"] == "error"
    assert res["error_code"] == "EMPTY_RESPONSE"


def test_n8n_http200_without_ack_is_unconfirmed(monkeypatch):
    import core_dispatcher

    class _Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(core_dispatcher.httpx, "AsyncClient", lambda *a, **k: _Client())
    res = asyncio.run(core_dispatcher.trigger_n8n_execution("p", "t", "", "c"))
    assert res["status"] == "unconfirmed"
    assert res["error_code"] == "N8N_DELIVERY_UNCONFIRMED"


async def test_no_consensus_marker_never_produces_final_decision(monkeypatch):
    import core_dispatcher

    async def _fake_dispatch(**kwargs):
        if kwargs.get("agent_id") == "exp":
            return {"content": "WIDERSPRUCH: KEIN CONSENSUS"}
        if kwargs.get("agent_id") == "boardroom-critic":
            return {"content": "Kritik: ungeloester Konflikt"}
        return {"content": "KEIN CONSENSUS ERREICHT"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_external_agent", _fake_dispatch)
    monkeypatch.setattr(
        core_dispatcher, "get_framework_info",
        lambda name, lang="": {"summary": "t", "system_instruction": "t"},
    )
    res = await core_dispatcher.run_boardroom_debate(
        task="Konfliktfall",
        max_rounds=2,
        chairman_id="chair",
        active_agents=[
            {"id": "chair", "name": "Chair", "role": "Orchestrator"},
            {"id": "exp", "name": "Expert", "role": "Expert"},
        ],
    )
    assert res["status"] == "no_consensus"
    assert res["consensus_status"].startswith("NO_CONSENSUS")
    assert res["consensus_verdict"].startswith("NO_CONSENSUS")
    assert res["is_final_decision"] is False
    finals = [e for e in res["events"] if e.get("type") == "final_synthesis"]
    assert all("Final Actionable Decision" not in str(e.get("content", "")) for e in finals)
    assert any(e.get("type") == "critique" for e in res["events"])


async def test_consensus_reached_keeps_success_status(monkeypatch):
    import core_dispatcher

    async def _fake_dispatch(**kwargs):
        return {"content": "ZUSTIMME"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_external_agent", _fake_dispatch)
    monkeypatch.setattr(
        core_dispatcher, "get_framework_info",
        lambda name, lang="": {"summary": "t", "system_instruction": "t"},
    )
    res = await core_dispatcher.run_boardroom_debate(
        task="Einfall",
        max_rounds=2,
        chairman_id="chair",
        active_agents=[
            {"id": "chair", "name": "Chair", "role": "Orchestrator"},
            {"id": "exp", "name": "Expert", "role": "Expert"},
        ],
    )
    assert res["status"] == "success"
    assert res["consensus_status"].startswith("CONSENSUS_REACHED")
    assert res["is_final_decision"] is True


# --- boardroom: Chairman-Tier -----------------------------------------------

def test_specialist_chairman_is_rejected():
    from fastapi import HTTPException
    from archon.routers import boardroom as br

    req = br.BoardroomRequest(task="t", chairman_id="content_creator")
    orig = dict(br._DEPS)
    br._DEPS["load_roles"] = lambda: [
        {"id": "content_creator", "name": "Specialist", "role": "Expert"},
        {"id": "executive_decision_architect", "name": "Exec", "role": "Chair"},
    ]
    br._DEPS["api_get_hermes_profiles"] = lambda: []
    try:
        with pytest.raises(HTTPException) as exc:
            br._prepare_boardroom_agents(req)
        assert exc.value.status_code == 400
    finally:
        br._DEPS.clear()
        br._DEPS.update(orig)

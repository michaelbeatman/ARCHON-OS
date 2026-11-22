"""Regressionstests fuer die verkabelte, offline Konsenspruefung der Boardroom-Debatte.

- backend.consensus_gate.resolve_debate_consensus() wertet explizite Marker
  deterministisch aus (M-1: Negation gewinnt, unklar = kein Konsens).
- core_dispatcher.stream_boardroom_debate() nutzt diesen Helper statt eines
  LLM-Moderators und respektiert das cancel_token.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _stmt(agent_id: str, content: str) -> dict:
    return {"agent_id": agent_id, "content": content}


# ---------------------------------------------------------------------------
# Einheitstests: resolve_debate_consensus
# ---------------------------------------------------------------------------

def test_resolve_debate_consensus_two_thirds():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        _stmt("a", "Ich stimme zu - KONSENS_ERREICHT"),
        _stmt("b", "AGREE"),
        _stmt("c", "DEBATTE_FORTSETZEN"),
    ], majority_rule="two_thirds")

    assert res["yes_votes"] == 2
    assert res["total_votes"] == 3
    assert res["required_votes"] == 2
    assert res["consensus_reached"] is True
    assert res["verdict"] == "CONSENSUS_REACHED"
    assert ("a", "KONSENS_ERREICHT") in res["evidence"]
    assert ("c", "DEBATTE_FORTSETZEN") in res["evidence"]


def test_resolve_debate_consensus_unanimous():
    from backend.consensus_gate import resolve_debate_consensus

    statements = [
        _stmt("a", "EINVERSTANDEN"),
        _stmt("b", "consensus_reached"),  # case-insensitiv
        _stmt("c", "ZUSTIMME"),
    ]
    ok = resolve_debate_consensus(statements, majority_rule="unanimous")
    assert ok["required_votes"] == 3
    assert ok["consensus_reached"] is True

    statements[2] = _stmt("c", "WIDERSPRUCH")
    no = resolve_debate_consensus(statements, majority_rule="unanimous")
    assert no["required_votes"] == 3
    assert no["yes_votes"] == 2
    assert no["consensus_reached"] is False


def test_resolve_debate_consensus_negation_wins_m1():
    """M-1: 'KEIN CONSENSUS ERREICHT' darf nie als Zustimmung gelten."""
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        _stmt("a", "KEIN CONSENSUS ERREICHT"),
        _stmt("b", "KONSENS_ERREICHT"),
    ])
    assert res["total_votes"] == 2
    assert res["yes_votes"] == 1
    assert res["consensus_reached"] is False

    # Auch wenn beide Marker im selben Text stehen, gewinnt die Negation.
    mixed = resolve_debate_consensus([
        _stmt("a", "KONSENS_ERREICHT, aber KEIN CONSENSUS ERREICHT"),
        _stmt("b", "AGREE"),
    ])
    assert mixed["yes_votes"] == 1
    assert mixed["consensus_reached"] is False


def test_resolve_debate_consensus_fail_closed():
    from backend.consensus_gate import resolve_debate_consensus

    none = resolve_debate_consensus([
        _stmt("a", "Ich denke, wir sollten das noch besprechen."),
        _stmt("b", ""),
    ])
    assert none["total_votes"] == 0
    assert none["yes_votes"] == 0
    assert none["required_votes"] == 2
    assert none["consensus_reached"] is False
    assert none["evidence"] == []

    # Ein einzelnes explizites Statement reicht nie (fail-closed).
    one = resolve_debate_consensus([_stmt("a", "KONSENS_ERREICHT")])
    assert one["total_votes"] == 1
    assert one["consensus_reached"] is False


# ---------------------------------------------------------------------------
# Quelltext-Assertions: Verkabelung im Dispatcher
# ---------------------------------------------------------------------------

def test_core_dispatcher_consensus_block_is_offline():
    src = (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")

    # Der alte LLM-Moderator-Prompt ist entfernt.
    assert "Prüfe, ob bereits voller Konsens erzielt wurde" not in src
    assert "Prüfe strikt, ob Konsens erreicht wurde." not in src

    # Der Konsensblock nutzt den offline-Helper und dispatcht nicht mehr.
    start = src.index("# 3. CONSENSUS CHECK")
    end = src.index("# 4. FINAL SYNTHESIS")
    block = src[start:end]
    assert "resolve_debate_consensus" in block
    assert "dispatch_to_external_agent" not in block
    assert '"evidence": consensus["evidence"]' in block


def test_core_dispatcher_cancel_token_wiring_in_source():
    src = (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")

    assert "cancel_token: Optional[Any] = None" in src
    assert "from backend.cancellation import get_token" in src
    assert 'f"boardroom:{task_id or chairman_id}"' in src
    assert "token.check()" in src
    assert "Debatte abgebrochen" in src
    assert "asyncio.CancelledError" in src


# ---------------------------------------------------------------------------
# Async: Abbruch produceziert ein cancelled-Event
# ---------------------------------------------------------------------------

async def test_stream_boardroom_debate_emits_cancelled_event(monkeypatch):
    import core_dispatcher
    from backend.cancellation import CancelToken

    async def _no_dispatch(**kwargs):
        raise AssertionError("Dispatch darf nach einem Abbruch nicht mehr gerufen werden")

    monkeypatch.setattr(core_dispatcher, "dispatch_to_external_agent", _no_dispatch)
    monkeypatch.setattr(
        core_dispatcher, "get_framework_info",
        lambda name, lang="": {
            "summary": "test",
            "system_instruction": "test",
        },
    )

    token = CancelToken("boardroom:test-cancel-wiring")
    token.cancel("abort")

    chairman = {"id": "chair", "name": "Moderator", "role": "Orchestrator"}
    expert = {"id": "exp", "name": "Experte", "role": "Expert"}

    events = [
        ev async for ev in core_dispatcher.stream_boardroom_debate(
            task="Test-Debatte",
            max_rounds=2,
            chairman_id="chair",
            active_agents=[chairman, expert],
            cancel_token=token,
        )
    ]

    cancelled = [ev for ev in events if ev.get("type") == "cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0]["content"] == "Debatte abgebrochen"
    assert events[-1]["type"] == "cancelled"
    assert events[0]["type"] == "start"


async def test_stream_boardroom_debate_emits_consensus_event_offline(monkeypatch):
    """Zwei explizite Ja-Marker ueber zwei Runden -> offline Konsens-Event."""
    import core_dispatcher
    from backend.cancellation import CancelToken

    calls: list = []

    async def _fake_dispatch(**kwargs):
        calls.append(kwargs.get("agent_id"))
        if kwargs.get("agent_id") == "exp":
            return {"content": "ZUSTIMME"}
        return {"content": "Synthese"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_external_agent", _fake_dispatch)
    monkeypatch.setattr(
        core_dispatcher, "get_framework_info",
        lambda name, lang="": {"summary": "test", "system_instruction": "test"},
    )

    token = CancelToken("boardroom:test-consensus-wiring")
    chairman = {"id": "chair", "name": "Moderator", "role": "Orchestrator"}
    expert = {"id": "exp", "name": "Experte", "role": "Expert"}

    events = [
        ev async for ev in core_dispatcher.stream_boardroom_debate(
            task="Test-Debatte",
            max_rounds=3,
            chairman_id="chair",
            active_agents=[chairman, expert],
            cancel_token=token,
        )
    ]

    consensus = [ev for ev in events if ev.get("type") == "consensus_reached"]
    assert len(consensus) == 1
    assert consensus[0]["yes_votes"] == 2
    assert consensus[0]["total_votes"] == 2
    assert consensus[0]["required_votes"] == 2
    assert ("exp", "ZUSTIMME") in consensus[0]["evidence"]
    assert events[-1]["type"] == "done"

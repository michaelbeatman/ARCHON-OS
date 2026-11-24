"""Re-Audit D11 — MED-Funde (nur MED-Zeilen).

Behandelt hier: ``audit_reports/reaudit/domain_11.md:19`` (S-11.4,
Korrelationsfelder des Handoffs). Die uebrigen MED-Zeilen betreffen
ausschliesslich Blacklist-Dateien und werden nicht angefasst.
"""
from __future__ import annotations

import pytest

import backend.trace_context as tc
from backend.handoff_desk import HandoffDesk, bind_handoff_context

TRACE = "a" * 32
SPAN = "b" * 16


@pytest.fixture
def desk(tmp_path):
    return HandoffDesk(db_path=str(tmp_path / "handoff.db"))


def _no_active_trace(monkeypatch):
    monkeypatch.setattr(tc, "current_trace_id", lambda: "")


def test_med1_correlation_comes_from_real_trace_context(desk, monkeypatch):
    """Kein erfundenes ``task:<id>``, wenn ein echter Trace-Kontext existiert."""
    monkeypatch.setattr(tc, "current_trace_id", lambda: TRACE)

    created = desk.create_handoff("task-med1", "agent-a", "agent-b", {"result": "x"}, "K")

    assert created["trace_id"] == TRACE
    assert created["correlation_id"] == f"trace:{TRACE}"
    assert created["correlation_id"] != "task:task-med1"
    row = desk.get_handoff(created["handoff_id"])
    assert row["trace_id"] == TRACE
    assert row["correlation_id"] == f"trace:{TRACE}"


def test_med1_bound_context_carries_session_id(desk, monkeypatch):
    """Die Session-ID der Kante landet im Envelope, statt leer zu bleiben."""
    _no_active_trace(monkeypatch)

    with bind_handoff_context(trace_id=TRACE, session_id="sess-origin"):
        created = desk.create_handoff("task-med1b", "agent-a", "agent-b", {"result": "x"}, "K")

    assert created["trace_id"] == TRACE
    assert created["session_id"] == "sess-origin"
    assert created["correlation_id"] == f"trace:{TRACE}"
    row = desk.get_handoff(created["handoff_id"])
    assert row["session_id"] == "sess-origin"
    assert row["envelope"]["session_id"] == "sess-origin"


def test_med1_context_is_restored_after_exit(desk, monkeypatch):
    """Kein Kontext-Leak in die naechste Übergabe."""
    _no_active_trace(monkeypatch)

    with bind_handoff_context(trace_id=TRACE, session_id="sess-inner"):
        pass
    after = desk.create_handoff("task-med1c", "agent-a", "agent-b", {"result": "x"}, "K")

    assert after["trace_id"] == ""
    assert after["session_id"] == ""
    assert after["correlation_id"] == "task:task-med1c"


def test_med1_explicit_arguments_win(desk, monkeypatch):
    """Explizite Korrelationswerte haben weiterhin Vorrang vor dem Kontext."""
    monkeypatch.setattr(tc, "current_trace_id", lambda: TRACE)
    with bind_handoff_context(trace_id=TRACE, session_id="ambient"):
        created = desk.create_handoff(
            "task-med1d",
            "agent-a",
            "agent-b",
            {"result": "x"},
            "K",
            trace_id="explicit-trace",
            session_id="explicit-session",
            correlation_id="explicit-correlation",
        )

    assert created["trace_id"] == "explicit-trace"
    assert created["session_id"] == "explicit-session"
    assert created["correlation_id"] == "explicit-correlation"


def test_med1_hmac_still_valid_with_trace_correlation(desk, monkeypatch):
    """Die Signatur bleibt ueber die geaenderten Korrelationsfelder gueltig."""
    monkeypatch.setattr(tc, "current_trace_id", lambda: TRACE)

    created = desk.create_handoff("task-med1e", "agent-a", "agent-b", {"result": "x"}, "K")

    assert desk.verify_payload_hash(created["handoff_id"]) is True

"""Offline-/Quelltext-Regressionstests fuer Batch D der Delegations-Kette.

Deckt die vier Batch-D-Aenderungen ab, ohne Netzwerk, echte Kanban-/State-DB
oder LLM-Dispatches zu benoetigen:

1. vollständiges A2A-Envelope (Spalten + Weitergabe im Dispatcher),
2. Akzeptanzkriterien + deterministische Ergebnis-Kompression,
3. Eval-/Promotion-Gate im Dispatch und in der Profil-Aktivierung,
4. Supervisor-Rollover inkl. expliziter ``supervisor_id`` im Org-Chart.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DELEGATION_SRC = REPO_ROOT / "archon" / "core" / "delegation.py"
HANDOFF_SRC = REPO_ROOT / "backend" / "handoff_desk.py"
PROFILES_SRC = REPO_ROOT / "archon" / "services" / "profiles_service.py"
ORG_PATH = REPO_ROOT / "config" / "org_hierarchy.json"


# ---------------------------------------------------------------------------
# 1. Vollstaendiges, typisiertes A2A-Envelope
# ---------------------------------------------------------------------------
def test_d1_handoff_schema_has_typed_a2a_columns_and_migration():
    src = HANDOFF_SRC.read_text(encoding="utf-8")
    for column in (
        "message_id",
        "reply_to",
        "correlation_id",
        "confidence REAL",
        "attachments_json",
    ):
        assert column in src
    # Additive Migration statt Neuanlage — alte Zeilen behalten Defaults.
    assert "PRAGMA table_info(agent_handoffs)" in src
    assert "ALTER TABLE agent_handoffs ADD COLUMN" in src
    assert "def summarize_for_handoff" in src


def test_d1_delegation_passes_full_envelope_and_keeps_assistant_role():
    src = DELEGATION_SRC.read_text(encoding="utf-8")
    assert 'message_id=f"msg-{secrets.token_hex(6)}"' in src
    assert 'correlation_id=f"task:{task_id}"' in src
    assert "reply_to=str(reply_to or" in src
    assert "confidence=_confidence" in src
    assert "attachments=_attachments" in src
    assert '1.0 if _status_key == "done"' in src
    assert '0.6 if _status_key == "review"' in src
    # Die K-5-Korrektur (Sub-Agent-Ergebnis ist keine User-Aussage) bleibt.
    assert '_save_message_to_db(origin_sess_id, "assistant", delegator_feedback)' in src


def test_d1_handoff_roundtrip_and_backward_compatible_defaults(tmp_path):
    from backend.handoff_desk import HandoffDesk

    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    created = desk.create_handoff(
        "task-d1", "research_scout", "coder",
        {"result": "ok", "status": "done"}, "Kriterium",
        message_id="msg-abc123",
        reply_to="handoff-parent",
        correlation_id="task:task-d1",
        confidence=0.6,
        attachments=["01_PROJEKTE/x", "projektordner"],
    )
    assert created["message_id"] == "msg-abc123"
    assert created["reply_to"] == "handoff-parent"
    assert created["correlation_id"] == "task:task-d1"
    assert created["confidence"] == 0.6

    row = desk.get_handoff(created["handoff_id"])
    assert row is not None
    assert row["message_id"] == "msg-abc123"
    assert row["reply_to"] == "handoff-parent"
    assert row["correlation_id"] == "task:task-d1"
    assert row["confidence"] == 0.6
    assert row["attachments"] == ["01_PROJEKTE/x", "projektordner"]

    # Ohne explizite Argumente: gueltige Defaults, keine Exception.
    plain = desk.create_handoff("task-d1b", "a", "b", {"result": "x"}, "K")
    assert plain["message_id"].startswith("msg-")
    assert plain["correlation_id"] == "task:task-d1b"
    assert plain["reply_to"] == ""
    assert plain["confidence"] == 1.0
    plain_row = desk.get_handoff(plain["handoff_id"])
    assert plain_row["attachments"] == []
    assert plain_row["deliverables"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# 2. Akzeptanzkriterien + Kompression
# ---------------------------------------------------------------------------
def test_d2_criteria_derivation_and_acceptance_validation_is_wired():
    src = DELEGATION_SRC.read_text(encoding="utf-8")
    assert 'payload.get("acceptance_criteria")' in src
    assert "def _resolve_handoff_criteria" in src
    assert "acceptance_criteria=_resolve_handoff_criteria(" in src

    desk_src = HANDOFF_SRC.read_text(encoding="utf-8")
    assert "if not result:" in desk_src
    assert "if not status:" in desk_src
    assert "if not criteria:" in desk_src
    assert "Akzeptanzkriterien" in desk_src
    # Keine bedingungslose Annahme mehr.
    assert "UPDATE agent_handoffs" in desk_src


def test_d2_summarize_for_handoff_is_deterministic_and_bounded():
    from backend.handoff_desk import summarize_for_handoff

    assert summarize_for_handoff("kurz") == "kurz"
    long_text = "A" * 5000
    first = summarize_for_handoff(long_text, limit=200)
    assert first == summarize_for_handoff(long_text, limit=200)
    assert len(first) <= 200
    assert "gekürzt" in first
    assert first.startswith("A") and first.endswith("A")


def test_d2_accept_rejects_empty_deliverables_and_keeps_full_result(tmp_path):
    from backend.handoff_desk import HandoffDesk

    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    no_result = desk.create_handoff("t", "a", "b", {"result": "", "status": "done"}, "K")
    assert desk.accept_handoff(no_result["handoff_id"], "b")["status"] == "error"

    no_criteria = desk.create_handoff("t", "a", "b", {"result": "x", "status": "done"}, "")
    assert desk.accept_handoff(no_criteria["handoff_id"], "b")["status"] == "error"

    full = "X" * 5000
    ok = desk.create_handoff("t", "a", "b", {"result": full, "status": "done"}, "K")
    assert len(ok["summary"]) < len(full)
    # Kompression geht nie zu Lasten der persistierten Fassung.
    assert desk.get_handoff(ok["handoff_id"])["deliverables"]["result"] == full
    assert desk.accept_handoff(ok["handoff_id"], "b")["status"] == "accepted"


# ---------------------------------------------------------------------------
# 3. Eval-/Promotion-Gates
# ---------------------------------------------------------------------------
def test_d3_eval_gate_is_wired_in_dispatch_and_profile_activation():
    src = DELEGATION_SRC.read_text(encoding="utf-8")
    for token in (
        "_check_delegation_eval_gate(",
        "require_eval_gate",
        "list_eval_runs",
        "get_scorecard",
        "data_sufficient",
        "success_rate",
        "Eval-/Promotion-Gate",
    ):
        assert token in src

    psrc = PROFILES_SRC.read_text(encoding="utf-8")
    assert "_delegation_eval_gate_required()" in psrc
    assert '"status": "eval_gate_failed"' in psrc


def test_d3_gate_default_off_then_fail_closed(monkeypatch):
    from archon.core import delegation
    import backend.agent_scorecard_engine as scorecard_mod
    import backend.eval_gates as eval_mod

    # Ohne Flag unveraendertes Verhalten — auch ohne jede Eval-Datenlage.
    monkeypatch.setattr(delegation, "_delegation_eval_gate_config", lambda: {})
    ok, reason = delegation._check_delegation_eval_gate("agent-x", {})
    assert ok is True and reason == ""

    # Flag gesetzt + keine Eval-Laeufe + unzureichende Scorecard => Ablehnung.
    monkeypatch.setattr(
        delegation, "_delegation_eval_gate_config",
        lambda: {"require_eval_gate": True},
    )
    monkeypatch.setattr(eval_mod, "list_eval_runs", lambda *a, **k: [])
    monkeypatch.setattr(
        scorecard_mod.agent_scorecard_engine,
        "get_scorecard",
        lambda agent_id: {"data_sufficient": False, "success_rate": None},
    )
    ok, reason = delegation._check_delegation_eval_gate("agent-x", {})
    assert ok is False
    assert "data_sufficient" in reason
    # Keine erfundene Erfolgsquote (frueher z. B. 98 %).
    assert "98" not in reason

    # Ein bestandener, persistierter Eval-Lauf genuegt.
    monkeypatch.setattr(
        eval_mod,
        "list_eval_runs",
        lambda *a, **k: [{"passed": True, "overall_score": 91.0, "eval_id": "eval-d3"}],
    )
    ok, reason = delegation._check_delegation_eval_gate("agent-x", {})
    assert ok is True and reason == ""


# ---------------------------------------------------------------------------
# 4. Supervisor-Rollover
# ---------------------------------------------------------------------------
def test_d4_rollover_calls_are_wired_in_delegation():
    src = DELEGATION_SRC.read_text(encoding="utf-8")
    assert (
        "from backend.supervisor_rollover import on_supervisor_failure, resolve_supervisor"
        in src
    )
    assert "resolve_supervisor(ziel)" in src
    assert 'if status in ("blocked", "failed"):' in src
    assert "on_supervisor_failure(" in src
    assert "reason=str(status)" in src
    assert '"new_supervisor"' in src
    assert "supervisor_hint" in src


def test_d4_org_hierarchy_has_explicit_supervisors_matching_links():
    data = json.loads(ORG_PATH.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data.get("nodes", [])}
    links = {(link["from"], link["to"]) for link in data.get("links", [])}
    for node_id in (
        "system_architect_orchestrator",
        "commercial_jurist_contracts",
        "construction_project_manager",
        "gtm_launch_strategist",
        "logistics_supply_chain_manager",
        "scientific_literature_synthesizer",
    ):
        supervisor = nodes[node_id].get("supervisor_id")
        assert supervisor, f"{node_id} hat kein explizites supervisor_id"
        assert (supervisor, node_id) in links

    # Die expliziten Felder duerfen die bestehende Kette nicht kaputteren.
    from backend.supervisor_rollover import escalation_chain

    chain = escalation_chain("senior_fullstack_engineer")
    assert chain[0] == "system_architect_orchestrator"
    assert "executive_decision_architect" in chain

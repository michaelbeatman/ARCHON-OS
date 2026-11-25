# -*- coding: utf-8 -*-
"""Regressionstests fuer die MED-Funde aus domain_12.md / domain_13.md.

Abgedeckt werden ausschliesslich Dateien im Ownership-Bereich:
  * D12/MED: backend/structured_output_enforcer.py (Schema-Pflicht, Bypass)
  * D13/MED: backend/role_budget_engine.py (Reservierungs-TTL, Settle nach Ablauf)
  * D13/MED (Test-Glied): backend/flightlog_backtester.py (Flag-Erkennung)

Keine Migration, kein Replay, keine Produktiv-DB.
"""
from __future__ import annotations

import datetime
import json
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# D12/MED — structured_output_enforcer
# ---------------------------------------------------------------------------

@pytest.fixture
def enforcer(monkeypatch):
    import backend.structured_output_enforcer as soe

    # Deterministische Config: keine Abhaengigkeit von settings.json.
    monkeypatch.setattr(
        soe,
        "_get_cfg",
        lambda: {
            "enabled": True,
            "auto_repair_json": True,
            "strict_schema_validation": True,
            "max_repair_attempts": 2,
        },
    )
    return soe.StructuredOutputEnforcer()


def test_d12_missing_schema_is_invalid(enforcer):
    res = enforcer.validate_and_enforce(raw_output=json.dumps({"name": "Archon"}), schema=None)
    assert res["valid"] is False
    assert res["error"] == "schema_required"
    assert res["bypassed"] is False


def test_d12_disabled_strict_validation_is_invalid(enforcer, monkeypatch):
    import backend.structured_output_enforcer as soe

    monkeypatch.setattr(
        soe,
        "_get_cfg",
        lambda: {"enabled": True, "auto_repair_json": True, "strict_schema_validation": False},
    )
    res = enforcer.validate_and_enforce(
        raw_output=json.dumps({"name": "Archon"}),
        schema={"name": "string"},
    )
    assert res["valid"] is False
    assert res["bypassed"] is True
    assert res["error"] == "strict_schema_validation_disabled"


def test_d12_missing_required_field_is_not_filled_with_default(enforcer):
    res = enforcer.validate_and_enforce(
        raw_output=json.dumps({"name": "Archon"}),
        schema={"name": "string", "amount": "integer"},
    )
    assert res["valid"] is False
    assert "amount" in res["missing_fields_filled"]
    assert res["data"].get("amount") is None  # kein erfundener Default-Wert


def test_d12_failed_coercion_is_invalid(enforcer):
    res = enforcer.validate_and_enforce(
        raw_output=json.dumps({"amount": "not-a-number"}),
        schema={"amount": "integer"},
    )
    assert res["valid"] is False
    assert "amount" in res["coercion_failures"]


def test_d12_valid_json_with_repair_is_accepted(enforcer):
    res = enforcer.validate_and_enforce(
        raw_output='```json\n{"name": "Archon", "amount": "42"}\n```',
        schema={"name": "string", "amount": "integer"},
    )
    assert res["valid"] is True
    assert res["repaired"] is True
    assert res["data"]["amount"] == 42


# ---------------------------------------------------------------------------
# D13/MED — role_budget_engine (Reservierungs-TTL / Settle)
# ---------------------------------------------------------------------------

def test_d13_reservation_ttl_covers_long_trajectories():
    from backend.role_budget_engine import BudgetBank

    # 30 min waren kuerzer als DAG (900 s) + Delegations-Watcher (1200 s).
    assert BudgetBank.RESERVATION_TTL_SECONDS >= 7200


def _ledger_tokens(db_path: str, agent_id: str) -> int:
    from backend.role_budget_engine import _today_str

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tokens_used FROM role_daily_budget_ledger "
            "WHERE agent_id = ? AND usage_date = ?",
            (agent_id, _today_str()),
        ).fetchone()
    return int(row[0]) if row else 0


def test_d13_direct_settlement_without_reservation_books_usage(tmp_path):
    """Reine Direktbuchung darf nicht an einer fehlenden Reservierung scheitern."""
    from backend.role_budget_engine import BudgetBank

    db = str(tmp_path / "budget.db")
    bank = BudgetBank(db_path=db)
    res = bank.settle(
        None,
        actual_tokens=137,
        actual_cost_usd=0.01,
        agent_id="d13_direct_agent",
        task_id="t-direct",
    )
    assert res["status"] == "settled"
    assert res["late_settlement"] is False
    assert _ledger_tokens(db, "d13_direct_agent") == 137


def test_d13_record_budget_usage_alias_books_usage(tmp_path):
    """Der Produktiv-Alias (record_budget_usage) geht ueber denselben Settle-Pfad."""
    from backend.role_budget_engine import record_budget_usage

    db = str(tmp_path / "budget.db")
    res = record_budget_usage(
        "d13_alias_agent", tokens_used=211, cost_usd=0.02,
        task_id="t-alias", db_path=db,
    )
    assert res["status"] == "settled"
    assert res["late_settlement"] is False
    assert _ledger_tokens(db, "d13_alias_agent") == 211


def test_d13_expired_reservation_still_settles_real_usage(tmp_path):
    """Abgelaufene Reservierungen duerfen Verbrauch nicht unterzaehlen.

    W3-D: ``BudgetBank.reserve`` ist fuer registrierte Tasks fail-closed.
    Der Test muss daher vor der Reservierung ein echtes Task-Cap anlegen —
    frueher wurde ohne Allokation ein stilles Fail-Open erwartet.
    """
    from backend.role_budget_engine import BudgetBank

    db = str(tmp_path / "budget.db")
    bank = BudgetBank(db_path=db)
    from backend.role_budget_engine import init_budget_tables
    init_budget_tables(db_path=db)
    now = datetime.datetime.now().isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO task_budget_allocations "
            "(task_id, agent_id, token_budget, tokens_used, cost_limit_eur, cost_used_eur, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, 0.0, ?, ?)",
            ("t-expired", "d13_expired_agent", 5000, 10.0, now, now),
        )
        conn.commit()
    r = bank.reserve(
        "d13_expired_agent", task_id="t-expired",
        estimated_tokens=500, estimated_cost_eur=0.05, ttl_seconds=1,
    )
    assert r["allowed"] is True
    rid = r["reservation_id"]

    past = (datetime.datetime.now() - datetime.timedelta(seconds=30)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE budget_reservations SET status = 'expired', expires_at = ? "
            "WHERE reservation_id = ?",
            (past, rid),
        )
        conn.commit()

    res = bank.settle(rid, actual_tokens=320, actual_cost_usd=0.03)
    assert res["status"] == "settled"
    assert res["late_settlement"] is True
    assert _ledger_tokens(db, "d13_expired_agent") == 320


def test_d13_reservation_heartbeat_extends_expiry(tmp_path):
    from backend.role_budget_engine import BudgetBank

    db = str(tmp_path / "budget.db")
    bank = BudgetBank(db_path=db)
    r = bank.reserve("d13_hb_agent", estimated_tokens=10, ttl_seconds=60)
    assert r["allowed"] is True
    rid = r["reservation_id"]

    with sqlite3.connect(db) as conn:
        before = conn.execute(
            "SELECT expires_at FROM budget_reservations WHERE reservation_id = ?", (rid,)
        ).fetchone()[0]

    res = bank.extend_reservation(rid, extra_seconds=600)
    assert res["status"] == "extended"

    with sqlite3.connect(db) as conn:
        after = conn.execute(
            "SELECT expires_at FROM budget_reservations WHERE reservation_id = ?", (rid,)
        ).fetchone()[0]
    delta = (
        datetime.datetime.fromisoformat(after) - datetime.datetime.fromisoformat(before)
    ).total_seconds()
    assert delta >= 599


# ---------------------------------------------------------------------------
# D13/MED (viertes Verdrahtungsglied: Test) — flightlog_backtester
# ---------------------------------------------------------------------------

def test_d13_flightlog_detects_hidden_tool_errors(tmp_path):
    from backend.flightlog_backtester import detect_silent_failures, record_flight_event

    db = str(tmp_path / "flightlog.db")
    record_flight_event("run-hidden", "coder", "terminal", {"cmd": "x"}, tool_ok=False, db_path=db)
    diag = detect_silent_failures("run-hidden", final_status="success", final_output="ok", db_path=db)
    assert diag["silent_failure"] is True
    assert any(f.startswith("hidden_tool_errors:") for f in diag["flags"])


def test_d13_flightlog_detects_tool_loop(tmp_path):
    from backend.flightlog_backtester import detect_silent_failures, record_flight_event

    db = str(tmp_path / "flightlog.db")
    for _ in range(3):
        record_flight_event("run-loop", "coder", "terminal", {"cmd": "same"}, tool_ok=True, db_path=db)
    diag = detect_silent_failures("run-loop", final_status="success", final_output="ok", db_path=db)
    assert diag["silent_failure"] is True
    assert any(f.startswith("tool_loop:") for f in diag["flags"])


def test_d13_flightlog_detects_token_spike_and_effort_collapse(tmp_path):
    from backend.flightlog_backtester import detect_silent_failures, record_flight_event

    db = str(tmp_path / "flightlog.db")
    record_flight_event("run-spike", "coder", "terminal", tokens_used=4000, db_path=db)
    diag = detect_silent_failures(
        "run-spike", final_status="success", final_output="ok",
        baseline_tokens=100, db_path=db,
    )
    assert any(f.startswith("token_spike:") for f in diag["flags"])
    assert "effort_collapse" in diag["flags"]


def test_d13_flightlog_isolates_runs(tmp_path):
    """Flags eines Runs duerfen nicht auf einen anderen Run durchschlagen."""
    from backend.flightlog_backtester import detect_silent_failures, record_flight_event

    db = str(tmp_path / "flightlog.db")
    record_flight_event("run-a", "coder", "terminal", tool_ok=False, db_path=db)
    diag = detect_silent_failures("run-b", final_status="success", final_output="ok", db_path=db)
    assert diag["event_count"] == 0
    assert diag["silent_failure"] is False

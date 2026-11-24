# -*- coding: utf-8 -*-
"""
Strang A — Paket A3 Regressionstests:
Mission Control Status/Meta-Persistenz, Cancellation-Killswitch-Reset,
Globaler Tages-Budget-Cap, Boardroom-Chairman/NO_CONSENSUS-Haertung,
Email-Draft-Downgrade-Schutz und Core-Dispatcher Slot-Leak-Schutz.
Referenz: d02, d05, d07, d08, d14.
"""
import asyncio
import os
import pytest


def test_mission_control_persists_cancelled_paused_and_delegation_meta(tmp_path, monkeypatch):
    from archon.core import mission_control as mc

    db_file = str(tmp_path / "kanban_a3.db")
    monkeypatch.setattr(mc, "KANBAN_DB_PATH", db_file)
    monkeypatch.setattr(mc, "_MIGRATION_DONE", True)

    task = {
        "id": "t-a3-cancel-01",
        "title": "Abgebrochener Subagent-Task",
        "status": "cancelled",
        "agent_id": "senior_coder",
        "delegation_depth": 2,
        "delegation_chain": ["default", "senior_coder"],
        "replan_count": 1,
        "failure_reason": "user_cancelled",
        "synthesis_started_at": 1700000000.0,
        "synthesis_retry_count": 2,
    }
    mc.mc_capture_task_sqlite(task)

    loaded_one = mc.mc_get_task_sqlite("t-a3-cancel-01")
    assert loaded_one is not None
    assert loaded_one["status"] == "cancelled"
    assert loaded_one["delegation_depth"] == 2
    assert loaded_one["delegation_chain"] == ["default", "senior_coder"]
    assert loaded_one["replan_count"] == 1
    assert loaded_one["failure_reason"] == "user_cancelled"
    assert loaded_one["synthesis_started_at"] == 1700000000.0
    assert loaded_one["synthesis_retry_count"] == 2

    # mc_update_task_sqlite darf die erweiterten Metafelder nicht loeschen
    mc.mc_update_task_sqlite("t-a3-cancel-01", {"status": "paused"})
    reloaded = mc.mc_get_task_sqlite("t-a3-cancel-01")
    assert reloaded is not None
    assert reloaded["status"] == "paused"
    assert reloaded["delegation_depth"] == 2
    assert reloaded["delegation_chain"] == ["default", "senior_coder"]
    assert reloaded["replan_count"] == 1
    assert reloaded["failure_reason"] == "user_cancelled"


def test_cancellation_cancel_and_reset_scope_does_not_lock_future_debates():
    from backend.cancellation import cancel_and_reset_scope, get_child_token, clear_scope

    scope_root = "boardroom_test_a3"
    t1 = get_child_token(scope_root, f"{scope_root}:run1")
    assert not t1.cancelled

    ok = cancel_and_reset_scope(scope_root, reason="global_kill_switch")
    assert ok is True
    assert t1.cancelled is True
    assert t1.reason == "global_kill_switch"

    # Neuer Lauf nach Kill-Switch darf NICHT vorab abgebrochen sein
    t2 = get_child_token(scope_root, f"{scope_root}:run2")
    assert t2.cancelled is False

    clear_scope(t2.scope)
    clear_scope(scope_root)


def test_role_budget_engine_enforces_global_daily_cost_cap(tmp_path, monkeypatch):
    from backend.role_budget_engine import BudgetBank

    db_file = str(tmp_path / "budget_a3.db")
    bank = BudgetBank(db_path=db_file)
    monkeypatch.setenv("ARCHON_GLOBAL_DAILY_COST_CAP_EUR", "1.00")

    r1 = bank.reserve(agent_id="agent_a", task_id="t1", estimated_tokens=1000, estimated_cost_eur=0.60)
    assert r1["allowed"] is True

    # Zweiter Agent wuerde zusammen mit aktiver Reservierung von agent_a > 1.00 EUR kommen
    r2 = bank.reserve(agent_id="agent_b", task_id="t2", estimated_tokens=1000, estimated_cost_eur=0.50)
    assert r2["allowed"] is False
    assert r2["error_code"] == "GLOBAL_DAILY_EUR_BUDGET_EXCEEDED"

    bank.release(r1["reservation_id"], reason="cleanup")


def test_boardroom_rejects_untrusted_chairman_id():
    from fastapi import HTTPException
    from archon.routers import boardroom as br

    req = br.BoardroomRequest(
        task="Testfrage",
        framework="six_hats",
        chairman_id="evil_nonexistent_role_xyz",
    )
    orig_deps = dict(br._DEPS)
    br._DEPS["load_roles"] = lambda: [{"id": "orchestrator", "name": "Orchestrator", "prompt": "P"}]
    br._DEPS["api_get_hermes_profiles"] = lambda: []
    try:
        with pytest.raises(HTTPException) as exc_info:
            br._prepare_boardroom_agents(req)
        assert exc_info.value.status_code == 400
    finally:
        br._DEPS.clear()
        br._DEPS.update(orig_deps)


def test_email_draft_engine_defines_workspace_dir_and_detects_hmac_downgrade(tmp_path, monkeypatch):
    import sqlite3
    from backend import email_draft_engine as ede

    assert hasattr(ede, "WORKSPACE_DIR")
    assert os.path.isdir(ede.WORKSPACE_DIR)

    db_file = str(tmp_path / "email_a3.db")
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.setenv("ARCHON_EMAIL_DRAFT_HMAC_EPOCH_FROM", "1")
    monkeypatch.setenv("ARCHON_ENFORCE_DISPATCH_AUDIT", "0")

    from backend import audit_log as al

    eng = ede.EmailDraftEngine(db_path=db_file)
    monkeypatch.setattr(al, "_dispatch_audit_enforced", lambda: False)
    eng._log_audit("d-1", "CREATED", {"subject": "Test"}, created_by="admin")

    # Jetzt HMAC-Key aktivieren: Block ID 1 >= cutoff 1 ohne HMAC muss als Downgrade fehlschlagen
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "test-secret-a3-email-chain-key-32bytes")
    res = ede.verify_email_draft_chain(db_path=db_file)
    assert res["valid"] is False
    assert "Downgrade" in res["message"]


def test_core_dispatcher_releases_throttle_slot_on_cancel_during_cache_lookup(monkeypatch):
    import core_dispatcher as cd
    from backend import concurrency_throttle as ct_mod
    from backend import semantic_cache as sc_mod

    released = []

    async def _fake_acquire(agent_id, slot_id, priority=2):
        return True

    async def _fake_release(slot_id):
        released.append(slot_id)

    def _raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError("cancelled during cache lookup")

    monkeypatch.setattr(ct_mod.concurrency_throttle, "acquire_slot", _fake_acquire)
    monkeypatch.setattr(ct_mod.concurrency_throttle, "release_slot", _fake_release)
    monkeypatch.setattr(sc_mod.semantic_cache_manager, "lookup", _raise_cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            cd.dispatch_to_external_agent(
                agent_id="senior_coder",
                agent_name="Senior Coder",
                prompt="test cancel slot leak",
                task_id="slot-a3-01",
            )
        )
    assert "slot-a3-01" in released

"""W2-A (F020) — D04 Governance/Security Remediation.

Regressionstests für H-04-1 … H-04-5 und die MED-Funde. Kein Test berührt
produktive DBs, Ankerdateien oder Secrets; alle Pfade liegen unter tmp_path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# H-04-1 — DataClassifier-Fehler fail-closed im Dispatch-Pfad
# ---------------------------------------------------------------------------
def test_container_dispatch_classifier_error_raises_zero_egress(monkeypatch):
    import core_dispatcher as cd
    from backend.data_classifier import DataClassifier
    from backend.llm_egress_guard import ZeroEgressBlockedError

    def _boom(cls, *args, **kwargs):
        raise RuntimeError("classifier-down")

    monkeypatch.setattr(DataClassifier, "classify", classmethod(_boom))
    monkeypatch.setattr(
        "backend.compliance_engine.compliance_engine.check_activation_allowed",
        lambda *a, **k: {"allowed": True},
    )
    proof_calls = []
    monkeypatch.setattr(
        "backend.llm_egress_guard._record_blocked_proof",
        lambda **kw: proof_calls.append(kw) or {"proof": True},
    )

    with pytest.raises(ZeroEgressBlockedError) as exc:
        cd._gate_container_dispatch(
            "agent_x", "openrouter", "model-x", "vertraulich", "https://api.openrouter.ai/v1"
        )
    assert exc.value.error_code == "DATA_CLASSIFIER_UNAVAILABLE"
    assert exc.value.audit_event == {"proof": True}
    assert proof_calls and proof_calls[0]["data_category"] == "confidential"


def test_main_dispatch_classifier_error_is_fail_closed_in_code():
    """Der zweite Klassifikationsfehler-Pfad (Impl-Dispatch) darf nicht
    still 'general' werden. Der Pfad liegt in einer grossen async-Funktion;
    die Quelltext-Invariante sichert den fail-closed-Ausdruck direkt.
    """
    import core_dispatcher as cd
    import inspect

    src = inspect.getsource(cd._dispatch_to_omniroute_or_container_impl)
    assert 'classified_cat = ""' in src
    block = src.split('classified_cat = ""', 1)[1].split("preflight_gate =", 1)[0]
    assert 'cloud_llm_allowed", False' in block
    assert 'classified_cat = "confidential"' in block
    assert "raise ZeroEgressBlockedError(" in block
    assert "_record_blocked_proof(" in block


# ---------------------------------------------------------------------------
# H-04-2 — API-Key-Pepper
# ---------------------------------------------------------------------------
def test_api_key_pepper_is_env_only_no_legacy_hash(monkeypatch):
    from backend import api_key_manager as akm

    assert not hasattr(akm, "KEY_SALT")
    assert not hasattr(akm, "LEGACY_KEY_SALT")
    assert not hasattr(akm.ApiKeyManager, "_legacy_hash_token")

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ARCHON_API_KEY_PEPPER", "real-pepper-value-1234567890")
    digest = akm.ApiKeyManager._hash_token("archon_live_token")
    expected = hmac.new(
        b"real-pepper-value-1234567890", b"archon_live_token", hashlib.sha256
    ).hexdigest()
    assert digest == expected


def test_api_key_pepper_missing_in_production_fails_closed(monkeypatch):
    from backend import api_key_manager as akm

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ARCHON_API_KEY_PEPPER", raising=False)
    with pytest.raises(akm.ApiKeyPepperMissingError):
        akm.ApiKeyManager._hash_token("archon_live_token")


def test_pepper_startup_hook_fails_in_production(monkeypatch):
    import main

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ARCHON_API_KEY_PEPPER", raising=False)
    with pytest.raises(RuntimeError, match="ARCHON_API_KEY_PEPPER"):
        main._assert_api_key_pepper()
    monkeypatch.setenv("ARCHON_API_KEY_PEPPER", "x" * 32)
    main._assert_api_key_pepper()  # kein raise


def test_auth_startup_hook_checks_real_config(monkeypatch):
    import main
    from backend.auth_service import AuthService

    monkeypatch.setattr(main, "_must_force_auth", lambda: True)
    monkeypatch.setattr(AuthService, "_read_auth_enabled", staticmethod(lambda: False))
    with pytest.raises(RuntimeError, match="auth.enabled"):
        main._assert_auth_on_nonloopback_bind()

    monkeypatch.setattr(AuthService, "_read_auth_enabled", staticmethod(lambda: True))
    main._assert_auth_on_nonloopback_bind()  # kein raise


# ---------------------------------------------------------------------------
# H-04-3 — requested_by durch den Taint-Chokepoint
# ---------------------------------------------------------------------------
def test_taint_approval_requires_requested_by(tmp_path):
    from backend.session_taint_guard import (
        check_egress_tool_call,
        mark_session_tainted,
        resolve_taint_approval,
    )

    db = str(tmp_path / "taint.db")
    mark_session_tainted("sess", "web_scrape:example.com", db_path=db)

    empty = check_egress_tool_call("sess", "pay", {"amount": 1}, db_path=db)
    assert empty["allowed"] is False
    assert empty["approval_id"] is None
    assert "requested_by" in empty["reason"]

    blocked = check_egress_tool_call(
        "sess", "pay", {"amount": 1}, db_path=db, requested_by="alice"
    )
    assert blocked["allowed"] is False
    assert blocked["approval_id"]
    aid = blocked["approval_id"]
    # Vier-Augen: Anforderer darf nicht selbst freigeben.
    with pytest.raises(PermissionError, match="Vier-Augen"):
        resolve_taint_approval(aid, True, reviewer="alice", db_path=db)


def test_legacy_approval_without_requested_by_is_denied(tmp_path):
    from backend.session_taint_guard import check_egress_tool_call, mark_session_tainted

    db = str(tmp_path / "legacy.db")
    mark_session_tainted("sess", "web", db_path=db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO taint_hitl_approvals "
            "(approval_id, session_id, tool_name, args_json, status, requested_by, created_at) "
            "VALUES (?, ?, ?, ?, 'approved', '', 1)",
            ("ta-legacy", "sess", "pay", '{"amount": 1}'),
        )
        conn.commit()
    finally:
        conn.close()
    res = check_egress_tool_call(
        "sess", "pay", {"amount": 1}, approval_id="ta-legacy",
        db_path=db, requested_by="bob",
    )
    assert res["allowed"] is False
    assert "Legacy" in res["reason"]


def test_requested_by_is_threaded_to_taint_gate(tmp_path, monkeypatch):
    import backend.delegation_isolation as di
    from backend.session_taint_guard import mark_session_tainted

    db = str(tmp_path / "runtime-taint.db")
    mark_session_tainted("sess", "web_scrape:example.com", db_path=db)
    seen = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        return {"allowed": True}

    monkeypatch.setattr("backend.session_taint_guard.check_egress_tool_call", _spy)
    di.enforce_runtime_tool_gate(
        "agent", "sess", "pay", {"amount": 1},
        taint_db_path=db, skip_profile_check=True, requested_by="alice",
    )
    assert seen["requested_by"] == "alice"
    assert seen["session_id"] == "sess"


def test_inbox_proposal_uses_session_actor_not_body(monkeypatch):
    from fastapi import Request
    import archon.routers.inbox_tools as it

    captured = {}

    class _FakeMgr:
        @staticmethod
        def propose_tool_installation(**kwargs):
            captured.update(kwargs)
            return {"status": "success"}

    monkeypatch.setattr(it, "_require_admin", lambda request: None)
    monkeypatch.setattr(it, "_require_session_actor", lambda request: "verified-user")
    # tool_permission_manager wird im Handler lokal importiert.
    import backend.tool_permission_manager as tpm

    monkeypatch.setattr(tpm, "tool_permission_manager", _FakeMgr())

    req = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    it.api_create_tool_proposal(req, {"tool_name": "x", "requested_by": "mallory"})
    assert captured["requested_by"] == "verified-user"


# ---------------------------------------------------------------------------
# H-04-4 — Treasury: SSOT-Schwellen + Vier-Augen + Actor aus Session
# ---------------------------------------------------------------------------
@pytest.fixture
def treasury_env(tmp_path, monkeypatch):
    import backend.treasury_engine as te
    from backend.approval_policy_engine import approval_engine

    db = str(tmp_path / "treasury.db")
    monkeypatch.setattr(te, "_resolve_treasury_db", lambda: db)
    monkeypatch.setattr(
        approval_engine, "get_policies",
        lambda domain=None: [
            {"policy_key": "finance_auto_approval_max", "policy_value": "50.00"},
            {"policy_key": "finance_four_eyes_min", "policy_value": "500.00"},
        ],
    )
    monkeypatch.setattr(
        "backend.passkey_hitl.is_passkey_required", lambda *a, **k: False
    )
    return te


def test_treasury_requester_comes_from_session(treasury_env):
    te = treasury_env
    te.upsert_account({
        "id": "acc-t", "name": "Test", "balance": 10000.0,
        "custody_mode": "passkey_hitl",
    })
    tx = te.request_payment(
        {
            "account_id": "acc-t", "amount": 600.0,
            "recipient": "Vendor", "requested_by": "mallory",
        },
        actor_id="alice",
    )
    assert tx["requested_by"] == "alice"


def test_treasury_four_eyes_at_ssot_threshold(treasury_env):
    te = treasury_env
    te.upsert_account({
        "id": "acc-t2", "name": "Test", "balance": 10000.0,
        "custody_mode": "passkey_hitl",
    })
    tx = te.request_payment(
        {"account_id": "acc-t2", "amount": 600.0, "recipient": "Vendor"},
        actor_id="alice",
    )
    with pytest.raises(PermissionError, match="four_eyes_violation"):
        te.approve_payment(tx["id"], approver_id="alice", passkey_verified=True)


def test_treasury_execute_immediately_only_below_auto_max(treasury_env):
    te = treasury_env
    te.upsert_account({
        "id": "acc-t3", "name": "Allowance", "balance": 10000.0,
        "custody_mode": "allowance_capped",
    })
    high = te.request_payment(
        {"account_id": "acc-t3", "amount": 100.0, "execute_immediately": True},
        actor_id="alice",
    )
    assert high["status"] == "pending_approval"
    low = te.request_payment(
        {"account_id": "acc-t3", "amount": 49.0, "execute_immediately": True},
        actor_id="alice",
    )
    assert low["status"] == "executed"


# ---------------------------------------------------------------------------
# H-04-5 — MCP-HITL fail-closed + Demo-Guard
# ---------------------------------------------------------------------------
def test_hitl_db_error_raises_and_denies(monkeypatch, tmp_path):
    import backend.mcp_gateway as mg

    db = tmp_path / "hitl.db"
    db.write_bytes(b"")
    monkeypatch.setattr(
        mg.ArchonMcpGateway, "_hitl_db_path", staticmethod(lambda *a, **k: str(db))
    )

    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(mg.sqlite3, "connect", _boom)
    gw = mg.ArchonMcpGateway()

    with pytest.raises(mg.HITLVerificationUnavailable):
        gw._is_hitl_consumed("hitl-1")
    with pytest.raises(mg.HITLVerificationUnavailable):
        gw._mark_hitl_consumed("hitl-2")

    allowed, pending = gw._check_hitl_gate(
        "archon__trigger_boardroom_debate",
        {"hitl_approval_id": "hitl-1"},
        {"key_id": "k1", "scopes": ["admin_full"]},
    )
    assert allowed is False
    assert "fail-closed" in pending["message"]


def test_demo_guard_exception_hard_denies(monkeypatch):
    import backend.mcp_gateway as mg

    def _boom():
        raise RuntimeError("demo config unreadable")

    monkeypatch.setattr(mg, "is_demo_mode", _boom)
    gw = mg.ArchonMcpGateway()
    code, payload = gw.execute_tool(
        "archon__create_task", {}, {"key_id": "k1", "scopes": ["admin_full"]}
    )
    assert code == -32003
    assert payload["message"] == "demo_guard_unavailable"


# ---------------------------------------------------------------------------
# MED — Warrant-Constraints, Privacy-SSOT
# ---------------------------------------------------------------------------
def test_warrant_amount_aliases_and_missing_amount_deny():
    from backend.tool_warrants import issue_warrant, verify_warrant_for_call

    secret = "w2a-warrant-secret-0123456789"
    w = issue_warrant(
        "sess", ["pay"], constraints={"max_amount": 50.0}, secret=secret
    )
    assert verify_warrant_for_call(
        w, "sess", "pay", {"value": 999.0}, secret=secret
    )["allowed"] is False
    assert verify_warrant_for_call(
        w, "sess", "pay", {"betrag": 999.0}, secret=secret
    )["allowed"] is False
    missing = verify_warrant_for_call(w, "sess", "pay", {}, secret=secret)
    assert missing["allowed"] is False
    assert "max_amount" in missing["reason"]


def test_warrant_path_alias_ssot(tmp_path):
    from backend.tool_warrants import (
        PATH_ARG_KEYS,
        issue_warrant,
        verify_warrant_for_call,
    )

    secret = "w2a-warrant-secret-0123456789"
    w = issue_warrant(
        "sess", ["read_file"],
        constraints={"allowed_path_prefixes": ["data"]}, secret=secret,
    )
    assert "destination_path" in PATH_ARG_KEYS
    res = verify_warrant_for_call(
        w, "sess", "read_file", {"destination_path": "../.env"}, secret=secret
    )
    assert res["allowed"] is False


def test_zero_egress_governance_is_real_second_source(tmp_path, monkeypatch):
    import backend.privacy_router as pr

    settings = {
        "privacy": {"zero_egress": False},
        "zero_egress_governance": {
            "zero_egress_strict": True,
            "sensitive_local_routing": False,
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(pr, "ROOT_SETTINGS_FILE", str(path))
    monkeypatch.delenv("PRIVACY_ZERO_EGRESS", raising=False)

    cfg = pr.get_privacy_config()
    assert cfg["zero_egress_strict"] is True
    # strikte Config darf nicht durch den governance-Wert false aufgeweicht werden
    assert cfg["sensitive_local_routing"] is True
    assert cfg["hard_block_on_local_offline"] is True

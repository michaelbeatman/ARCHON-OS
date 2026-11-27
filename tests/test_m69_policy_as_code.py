"""M69 — Policy-as-Code, signierte Freigabe-Tokens und 24h-Vendor-Limits."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.routers import _rbac, policy_gates
from archon.routers import auth as auth_router
from backend import approval_policy_engine as ape
from backend import audit_log as audit_mod
from backend import auth_service as auth_mod
from backend import cost_estimator as ce
from backend.approval_policy_engine import ApprovalPolicyEngine
from backend.auth_service import AuthService


def _setup_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tuple[str, ApprovalPolicyEngine]:
    db_path = str(tmp_path / "m69_engine.db")
    engine = ApprovalPolicyEngine(db_path=db_path)
    monkeypatch.setattr(ape, "approval_engine", engine)
    return db_path, engine


def _tamper(token: str) -> str:
    """Signatur bitflippen — garantiert eine echte Veraenderung der Bytes."""
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    flipped = bytearray(raw)
    flipped[-1] ^= 0x01
    return base64.urlsafe_b64encode(bytes(flipped)).rstrip(b"=").decode("ascii")


def _gate_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(policy_gates.router)
    # Der Viewer-Zaun wird in diesen Fachlogik-Tests gezielt ersetzt; die
    # RBAC-Tests weiter unten pruefen ihn separat.
    app.dependency_overrides[policy_gates.forbid_viewer_writes] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Token-Integritaet, TTL und Einmalverbrauch
# ---------------------------------------------------------------------------


def test_tampered_token_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _setup_engine(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue(
        "finance", "Rechnung", amount=800.0, requester_id="carol"
    )
    issued = ape.issue_approval_token(
        created["request_id"], "approve", db_path=db, now_epoch=1000
    )
    forged = _tamper(issued["token"])

    verified = ape.verify_approval_token(forged, db_path=db, now_epoch=1001)
    assert verified["valid"] is False
    assert verified["reason"] == "invalid_signature"

    gate = ape.evaluate_policy_gate(
        domain="finance",
        action="approve",
        amount_eur=800.0,
        approver="carol",
        request_id=created["request_id"],
        approval_token=forged,
        db_path=db,
        now_epoch=1001,
    )
    assert gate["allowed"] is False
    assert gate["reason_code"] == "approval_token_invalid"
    # Das Roh-Token darf nicht im Gate-Ergebnis auftauchen.
    assert forged not in str(gate)


def test_token_ttl_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _setup_engine(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue("finance", "Rechnung", amount=800.0)
    issued = ape.issue_approval_token(
        created["request_id"], "approve", ttl_seconds=60, db_path=db, now_epoch=1000
    )
    assert ape.verify_approval_token(
        issued["token"], db_path=db, now_epoch=1001
    )["valid"] is True
    expired = ape.verify_approval_token(issued["token"], db_path=db, now_epoch=1061)
    assert expired["valid"] is False
    assert expired["reason"] == "expired"


def test_token_single_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _setup_engine(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue("finance", "Rechnung", amount=800.0)
    issued = ape.issue_approval_token(
        created["request_id"], "approve", db_path=db, now_epoch=1000
    )
    first = ape.verify_approval_token(
        issued["token"], db_path=db, now_epoch=1001, consume=True
    )
    assert first["valid"] is True
    assert first["consumed"] is True
    second = ape.verify_approval_token(
        issued["token"], db_path=db, now_epoch=1002, consume=True
    )
    assert second["valid"] is False
    assert second["reason"] == "already_used"


def test_tampered_callback_is_denied_by_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin_rbac_bypass: Dict[str, Any]
) -> None:
    db, engine = _setup_engine(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue("finance", "Rechnung", amount=800.0)
    issued = ape.issue_approval_token(created["request_id"], "approve", db_path=db)

    client = _gate_client(monkeypatch)
    response = client.post(
        "/api/policy-gates/telegram/approve",
        json={"callback_data": f"hitl:approve:{_tamper(issued['token'])}", "chat_id": "999999"},
    )
    assert response.status_code == 400
    assert "invalid_signature" in response.json()["detail"]
    # Kein Token im Klartext in der Fehlerantwort.
    assert issued["token"] not in response.text


# ---------------------------------------------------------------------------
# 2. Rollierendes 24h-Vendor-Limit
# ---------------------------------------------------------------------------


def test_vendor_limit_uses_rolling_24h_window(tmp_path: Path) -> None:
    policy = ape.load_approval_policy()
    db = str(tmp_path / "vendor.db")
    t0 = 1_000_000.0

    first = ce.reserve_vendor_budget(
        "openai", 40.0, policy=policy, db_path=db, now_epoch=t0
    )
    assert first["allowed"] is True
    second = ce.reserve_vendor_budget(
        "openai", 40.0, policy=policy, db_path=db, now_epoch=t0 + 23 * 3600
    )
    assert second["allowed"] is True

    full = ce.check_vendor_limit(
        "openai", planned_cost_usd=40.0, policy=policy, db_path=db, now_epoch=t0 + 23 * 3600
    )
    assert full["allowed"] is False
    assert full["spent_usd"] == pytest.approx(80.0)
    assert full["calls"] == 2

    # Nach 24h faellt die erste Reservierung aus dem Fenster.
    later = t0 + 24 * 3600 + 10
    rolled = ce.check_vendor_limit(
        "openai", planned_cost_usd=40.0, policy=policy, db_path=db, now_epoch=later
    )
    assert rolled["allowed"] is True
    assert rolled["spent_usd"] == pytest.approx(40.0)
    assert rolled["calls"] == 1

    reserved = ce.reserve_vendor_budget(
        "openai", 40.0, policy=policy, db_path=db, now_epoch=later
    )
    assert reserved["allowed"] is True
    assert reserved["spent_usd"] == pytest.approx(40.0)
    assert "event_id" in reserved


def test_unknown_vendor_is_fail_closed(tmp_path: Path) -> None:
    policy = ape.load_approval_policy()
    result = ce.check_vendor_limit(
        "unlisted-vendor", policy=policy, db_path=str(tmp_path / "vendor2.db")
    )
    assert result["allowed"] is False
    with pytest.raises(ce.VendorLimitError):
        ce.enforce_vendor_limit("unlisted-vendor", policy=policy)


# ---------------------------------------------------------------------------
# 3. Ungueltige Policy -> Fail-Closed
# ---------------------------------------------------------------------------


def test_invalid_policy_is_fail_closed(tmp_path: Path) -> None:
    bad = tmp_path / "bad_schema.yaml"
    bad.write_text("schema_version: 99\npolicy_version: '1.0.0'\n", encoding="utf-8")
    with pytest.raises(ape.PolicyValidationError):
        ape.load_approval_policy(str(bad))

    gate = ape.evaluate_policy_gate(
        domain="finance", amount_eur=1000.0, policy_path=str(bad)
    )
    assert gate["allowed"] is False
    assert gate["decision"] == "deny"
    assert gate["reason_code"] == "policy_invalid"


def test_broken_threshold_invariant_is_rejected(tmp_path: Path) -> None:
    valid = Path(ape.POLICY_FILE).read_text(encoding="utf-8")
    broken = tmp_path / "broken_limits.yaml"
    broken.write_text(
        valid.replace("max_amount_eur: 50.00", "max_amount_eur: 600.00"),
        encoding="utf-8",
    )
    with pytest.raises(ape.PolicyValidationError, match="Invariante"):
        ape.load_approval_policy(str(broken))


# ---------------------------------------------------------------------------
# 4. M95-Stellvertreter-Regeln greifen weiterhin
# ---------------------------------------------------------------------------


def _setup_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Tuple[AuthService, ApprovalPolicyEngine, str]:
    db = str(tmp_path / "m69_users.db")
    monkeypatch.setenv("ARCHON_INITIAL_ADMIN_PASSWORD", "InitAdminPass123!")
    monkeypatch.setattr(auth_mod, "DB_PATH", db)
    monkeypatch.setattr(audit_mod.chained_audit_log, "db_path", db)
    auth = AuthService()
    monkeypatch.setattr(auth_mod, "auth_service", auth)
    alice = auth.create_user("alice", "AlicePass123!", role="admin", display_name="Alice")
    auth.create_user("bob", "BobPass12345!", role="operator", display_name="Bob")
    auth.create_user("vic", "ViewerPass123!", role="viewer", display_name="Vic")
    auth.set_user_telegram_channel(alice["id"], "111111")
    engine = ApprovalPolicyEngine(db_path=db)
    monkeypatch.setattr(ape, "approval_engine", engine)
    return auth, engine, db


def test_m95_deputy_rules_still_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine, db = _setup_users(tmp_path, monkeypatch)
    engine.set_delegation("alice", True, "bob", "Bob Stellvertreter")

    delegated = ape.evaluate_policy_gate(
        domain="finance", amount_eur=900.0, approver="alice", db_path=db
    )
    assert delegated["m95"]["deputy"] == "bob"
    assert delegated["m95"]["deputy_valid"] is True
    assert delegated["decision"] == "require_approval"

    agent = ape.evaluate_policy_gate(
        domain="finance", amount_eur=900.0, approver="agent:finance_lead", db_path=db
    )
    assert agent["reason_code"] == "m95_human_approver_required"

    viewer = ape.evaluate_policy_gate(
        domain="finance", amount_eur=900.0, approver="vic", db_path=db
    )
    assert viewer["reason_code"] == "m95_insufficient_role"

    admin_only = ape.evaluate_policy_gate(
        domain="system", amount_eur=900.0, approver="bob", db_path=db
    )
    assert admin_only["reason_code"] == "m95_insufficient_role"


# ---------------------------------------------------------------------------
# 5. RBAC und Telegram-Button-Payload
# ---------------------------------------------------------------------------


def test_rbac_403_and_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin_rbac_bypass: Dict[str, Any]
) -> None:
    db, engine = _setup_engine(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue("finance", "RBAC", amount=100.0, requester_id="carol")
    issued = ape.issue_approval_token(
        created["request_id"], "approve", actor="test-actor", db_path=db
    )

    client = _gate_client(monkeypatch)
    evaluated = client.post(
        "/api/policy-gates/evaluate", json={"domain": "finance", "amount_eur": 10}
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["gate"]["decision"] == "allow"

    approved = client.post(
        "/api/policy-gates/approve",
        json={"request_id": created["request_id"], "approval_token": issued["token"]},
    )
    assert approved.status_code == 200
    assert approved.json()["actor"] == "test-actor"
    assert issued["token"] not in approved.text


def test_viewer_is_blocked_with_403(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(policy_gates.router)
    monkeypatch.setattr(
        auth_router,
        "get_current_user_from_request",
        lambda request: {
            "username": "vic",
            "role": "viewer",
            "auth_enabled": True,
            "is_service": False,
        },
    )
    response = TestClient(app).post(
        "/api/policy-gates/evaluate", json={"domain": "finance"}
    )
    assert response.status_code == 403


def test_rbac_not_configured_returns_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_rbac, "_checker", None)
    client = _gate_client(monkeypatch)
    response = client.get("/api/policy-gates/policy")
    assert response.status_code == 503


def test_telegram_button_payload_and_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin_rbac_bypass: Dict[str, Any]
) -> None:
    _, engine, db = _setup_users(tmp_path, monkeypatch)
    created = engine.evaluate_and_enqueue(
        "finance", "Telegram-Freigabe", amount=800.0, requester_id="carol"
    )
    issued = ape.issue_approval_token(
        created["request_id"], "approve", actor="alice", db_path=db
    )

    # Unautorisierter Chat -> 403 (M95-Chat-Zaun bleibt aktiv).
    client = _gate_client(monkeypatch)
    denied = client.post(
        "/api/policy-gates/telegram/approve",
        json={"callback_data": issued["callback_data"], "chat_id": "999999"},
    )
    assert denied.status_code == 403

    # Autorisisierter Chat des Genehmigers -> 200 und Freigabe.
    approved = client.post(
        "/api/policy-gates/telegram/approve",
        json={"callback_data": issued["callback_data"], "chat_id": "111111"},
    )
    assert approved.status_code == 200
    assert approved.json()["actor"] == "alice"
    assert approved.json()["result"]["status"] in ("first_approved", "approved")

    # Zweiter Klick auf denselben Button -> Einmalverbrauch blockiert.
    replay = client.post(
        "/api/policy-gates/telegram/approve",
        json={"callback_data": issued["callback_data"], "chat_id": "111111"},
    )
    assert replay.status_code == 400
    assert "already_used" in replay.json()["detail"]

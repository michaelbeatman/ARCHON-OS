"""M95 — Security- & Unit-Tests: Multi-User Urlaubs-/Vertretungsmodus & User-Telegram-Kanaele."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.routers import telegram as telegram_router
from backend import approval_policy_engine as ape
from backend import auth_service as auth_mod
from backend.approval_policy_engine import ApprovalPolicyEngine
from backend.auth_service import AuthService
from backend.telegram_gateway_v2 import (
    authorize_hitl_callback,
    resolve_user_telegram_channel,
    route_approval_telegram_notification,
)


def _setup_multi_user_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AuthService, ApprovalPolicyEngine, List[Dict[str, Any]]]:
    db_path = str(tmp_path / "agentic_memory.db")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m95-test-hmac-key-0123456789abcdef")
    monkeypatch.setenv("ARCHON_INITIAL_ADMIN_PASSWORD", "InitAdminPass123!")
    monkeypatch.setattr(auth_mod, "DB_PATH", db_path)

    audit_events: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        ape,
        "_record_central_audit",
        lambda category, action, actor, details: audit_events.append(
            {"category": category, "action": action, "actor": actor, "details": details}
        ),
    )

    auth = AuthService()
    monkeypatch.setattr(auth_mod, "auth_service", auth)

    alice = auth.create_user("alice", "AlicePass123!", role="admin", display_name="Alice Admin")
    bob = auth.create_user("bob", "BobPass12345!", role="operator", display_name="Bob Stellvertreter")
    carol = auth.create_user("carol", "CarolPass123!", role="admin", display_name="Carol Admin")
    vic = auth.create_user("vic", "ViewerPass12!", role="viewer", display_name="Vic Viewer")
    inact = auth.create_user("inactive_op", "InactPass123!", role="operator", display_name="Inaktiv Op")
    auth.update_user(inact["id"], is_active=False)

    auth.set_user_telegram_channel(alice["id"], "111111")
    auth.set_user_telegram_channel(bob["id"], "222222", telegram_bot_token="999:BOB_CUSTOM_TOKEN")
    auth.set_user_telegram_channel(carol["id"], "333333")
    auth.set_user_telegram_channel(vic["id"], "444444")

    eng = ApprovalPolicyEngine(db_path=db_path)
    return auth, eng, audit_events


# ---------------------------------------------------------------------------
# 1. Urlaubsmodus & Timeout-Eskalation: NUR menschlicher RBAC-Stellvertreter, NIE Agent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forbidden_sub",
    ["agent:finance_lead", "default", "system", "hermes", "system_watchdog", "bot_helper", ""],
)
def test_vacation_mode_never_accepts_agent_or_system_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbidden_sub: str
) -> None:
    _, eng, _ = _setup_multi_user_env(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Agenten|System-Default"):
        eng.set_delegation("alice", True, forbidden_sub, "Agent Fallback")


def test_approve_request_rejects_agent_and_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, eng, _ = _setup_multi_user_env(tmp_path, monkeypatch)
    ev = eng.evaluate_and_enqueue(
        "finance", "Rechnung 800 EUR", amount=800.0, requester_id="carol", assigned_approver="alice"
    )
    req_id = ev["request_id"]

    with pytest.raises(ValueError, match="Agenten-/System-Identitaet"):
        eng.approve_request(req_id, approver_id="agent:finance_lead")
    with pytest.raises(ValueError, match="Agenten-/System-Identitaet"):
        eng.approve_request(req_id, approver_id="default")
    with pytest.raises(ValueError, match="Rolle 'viewer'"):
        eng.approve_request(req_id, approver_id="vic")


def test_vacation_and_timeout_escalate_to_human_rbac_deputy_with_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, eng, audit_events = _setup_multi_user_env(tmp_path, monkeypatch)

    # Aktivierung & Deaktivierung werden im Audit-Log protokolliert
    res_on = eng.set_delegation("alice", True, "bob", "Bob Stellvertreter")
    assert res_on["is_active"] == 1
    assert res_on["substitute_role"] == "operator"
    assert any(e["action"] == "VACATION_MODE_ENABLED" and e["actor"] == "alice" for e in audit_events)

    # HITL-Anfrage waehrend Urlaubsmodus -> eskaliert an menschlichen Stellvertreter Bob (nie auto_approved)
    ev = eng.evaluate_and_enqueue(
        "finance",
        "Lieferantenzahlung",
        amount=750.0,
        requester_id="carol",
        assigned_approver="alice",
    )
    assert ev["status"] == "pending"
    assert ev["escalated_to"] == "bob"
    assert any(e["action"] == "DEPUTY_ESCALATION" for e in audit_events)

    # Timeout-Eskalation: expires_at in Vergangenheit setzen
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)).isoformat()
    with sqlite3.connect(eng.db_path) as conn:
        conn.execute("UPDATE approval_requests SET expires_at = ? WHERE id = ?", (past, ev["request_id"]))
        conn.commit()

    n = eng.check_and_escalate_timeouts()
    assert n == 1
    updated = eng.get_request(ev["request_id"])
    assert updated is not None
    assert updated["status"] == "escalated"
    assert updated["escalated_to"] == "bob"
    assert any(e["action"] == "ESCALATE_TO_DEPUTY" for e in audit_events)

    # Deaktivierung auditieren
    eng.set_delegation("alice", False, "bob", "Bob Stellvertreter")
    assert any(e["action"] == "VACATION_MODE_DISABLED" and e["actor"] == "alice" for e in audit_events)
    assert eng.verify_audit_integrity()["valid"] is True


# ---------------------------------------------------------------------------
# 2. Fehlender oder unberechtigter Stellvertreter -> Fail-Closed Blockade
# ---------------------------------------------------------------------------


def test_missing_or_unauthorized_deputy_blocks_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, eng, audit_events = _setup_multi_user_env(tmp_path, monkeypatch)

    # Viewer, Inaktiv, Unbekannt, Selbst-Delegation muessen abgelehnt werden
    with pytest.raises(ValueError, match="Viewer ausgeschlossen"):
        eng.set_delegation("alice", True, "vic", "Vic Viewer")
    with pytest.raises(ValueError, match="deaktiviert"):
        eng.set_delegation("alice", True, "inactive_op", "Inaktiv Op")
    with pytest.raises(ValueError, match="kein registrierter menschlicher Benutzer"):
        eng.set_delegation("alice", True, "unbekannt", "Ghost")
    with pytest.raises(ValueError, match="Selbst-Delegation"):
        eng.set_delegation("alice", True, "alice", "Alice")

    # Szenario: Stellvertreter Bob wird erst gesetzt, dann auf 'viewer' herabgestuft
    eng.set_delegation("alice", True, "bob", "Bob Stellvertreter")
    bob_user = auth.get_user_by_username("bob")
    assert bob_user is not None
    auth.update_user(bob_user["id"], role="viewer")

    # Neue Anfrage waehrend Urlaubsmodus -> fail-closed 'escalated_blocked'
    ev = eng.evaluate_and_enqueue(
        "finance",
        "Kritische Ueberweisung",
        amount=1200.0,
        requester_id="carol",
        assigned_approver="alice",
    )
    assert ev["status"] == "escalated_blocked"
    assert ev["escalated_to"] is None
    assert any(e["action"] == "ESCALATION_BLOCKED_FAIL_CLOSED" for e in audit_events)

    # Timeout ohne gueltigen Stellvertreter (carol hat keinen Stellvertreter) -> 'escalated_blocked'
    ev2 = eng.evaluate_and_enqueue(
        "finance",
        "Ohne Vertreter",
        amount=600.0,
        requester_id="alice",
        assigned_approver="carol",
    )
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)).isoformat()
    with sqlite3.connect(eng.db_path) as conn:
        conn.execute("UPDATE approval_requests SET expires_at = ? WHERE id = ?", (past, ev2["request_id"]))
        conn.commit()

    assert eng.check_and_escalate_timeouts() == 1
    rec2 = eng.get_request(ev2["request_id"])
    assert rec2 is not None
    assert rec2["status"] == "escalated_blocked"
    assert rec2["escalated_to"] is None
    assert any(e["action"] == "ESCALATE_BLOCKED_FAIL_CLOSED" for e in audit_events)


# ---------------------------------------------------------------------------
# 3. Benutzerspezifische Telegram-Kanaele & strenge Callback-Autorisierung
# ---------------------------------------------------------------------------


def test_telegram_routing_targets_deputy_channel_and_preserves_single_user_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth, eng, _ = _setup_multi_user_env(tmp_path, monkeypatch)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "777777")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000:DEFAULT_TOKEN")

    # Geheimnis-Schutz: list_users gibt keinen Klartext-Bot-Token zurueck
    bob_info = auth.get_user_by_username("bob")
    assert bob_info is not None
    assert bob_info["telegram_chat_id"] == "222222"
    assert bob_info["has_custom_bot_token"] is True
    assert "telegram_bot_token" not in bob_info

    # Urlaubsmodus Alice -> Bob: Benachrichtigung geht an Bobs chat_id + eigenen Bot-Token
    eng.set_delegation("alice", True, "bob", "Bob Stellvertreter")
    ev = eng.evaluate_and_enqueue(
        "finance", "Ausgabe 900 EUR", amount=900.0, requester_id="carol", assigned_approver="alice"
    )
    sent_calls: List[Dict[str, Any]] = []

    def _fake_sender(text: str, reply_markup: Any = None, *, chat_id: Any = None, bot_token: Any = None) -> bool:
        sent_calls.append({"text": text, "reply_markup": reply_markup, "chat_id": chat_id, "bot_token": bot_token})
        return True

    routed = route_approval_telegram_notification(ev, event_type="deputy_escalation", sender=_fake_sender)
    assert routed["sent"] is True
    assert routed["recipient"] == "bob"
    assert routed["chat_id"] == "222222"
    assert sent_calls[-1]["chat_id"] == "222222"
    assert sent_calls[-1]["bot_token"] == "999:BOB_CUSTOM_TOKEN"

    # Single-User-Fallback fuer Benutzer ohne eigene chat_id
    no_tg = auth.create_user("single_admin", "SinglePass123!", role="admin", display_name="Single Admin")
    fb_ch = resolve_user_telegram_channel(no_tg["username"])
    assert fb_ch["resolved"] is True
    assert fb_ch["source"] == "single_user_fallback"
    assert fb_ch["chat_id"] == "777777"


def test_telegram_callback_rejects_unauthorized_chats_and_allows_deputy_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, eng, _ = _setup_multi_user_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ape, "approval_engine", eng)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "777777")

    eng.set_delegation("alice", True, "bob", "Bob Stellvertreter")
    ev = eng.evaluate_and_enqueue(
        "finance", "Rechnung 300 EUR", amount=300.0, requester_id="carol", assigned_approver="alice"
    )
    req_id = ev["request_id"]
    rec = eng.get_request(req_id)
    assert rec is not None

    # Unbekannte Fremd-Chat-ID -> abgewiesen
    denied_stranger = authorize_hitl_callback(f"hitl:approve:{req_id}", "999999", approval_record=rec)
    assert denied_stranger["authorized"] is False
    assert denied_stranger["reason"] == "unauthorized_chat_id"

    # Viewer-Chat-ID -> abgewiesen
    denied_viewer = authorize_hitl_callback(f"hitl:approve:{req_id}", "444444", approval_record=rec)
    assert denied_viewer["authorized"] is False
    assert denied_viewer["reason"] == "insufficient_role"

    # Antragsteller Carols Chat-ID -> Vier-Augen-Konflikt abgewiesen
    denied_requester = authorize_hitl_callback(f"hitl:approve:{req_id}", "333333", approval_record=rec)
    assert denied_requester["authorized"] is False
    assert denied_requester["reason"] == "four_eyes_requester_conflict"

    # Falscher User-Chat (Alice statt Vertreter Bob) -> abgewiesen
    denied_wrong_user = authorize_hitl_callback(f"hitl:approve:{req_id}", "111111", approval_record=rec)
    assert denied_wrong_user["authorized"] is False
    assert denied_wrong_user["reason"] == "unauthorized_chat_for_target_user"

    # Router-Endpunkt: Fremde chat_id -> HTTP 403, Bobs chat_id -> HTTP 200 & Freigabe
    app = FastAPI()
    app.include_router(telegram_router.router)
    app.dependency_overrides[telegram_router._forbid_viewer_writes] = lambda: None
    client = TestClient(app)

    r_403 = client.post(
        "/api/telegram/hitl-callback",
        json={"callback_data": f"hitl:approve:{req_id}", "chat_id": "999999"},
    )
    assert r_403.status_code == 403

    r_200 = client.post(
        "/api/telegram/hitl-callback",
        json={"callback_data": f"hitl:approve:{req_id}", "chat_id": "222222"},
    )
    assert r_200.status_code == 200
    assert r_200.json()["actor"] == "bob"
    assert r_200.json()["result"]["status"] == "approved"

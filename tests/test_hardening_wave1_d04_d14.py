# -*- coding: utf-8 -*-
"""PoC-Tests fuer Welle 1 (D04/D14) — Fail-Closed-Haertung."""
import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.self_evolving_tooling import _validate_synthetic_imports
from backend.passkey_hitl import is_passkey_required
from backend.kanban_verifier import resolve_card_hitl_decision
from backend.session_taint_guard import (
    check_egress_tool_call,
    list_pending_taint_approvals,
    mark_session_tainted,
    resolve_taint_approval,
)


class _Req:
    headers = {"host": "localhost"}
    cookies = {}
    state = SimpleNamespace(user={"id": "usr_test", "username": "tester", "role": "admin"})

    class _URL:
        scheme = "http"

    url = _URL()


def test_poc_os_system_injection_denied():
    with pytest.raises(ValueError, match="system"):
        _validate_synthetic_imports("import math\nos.system('touch /tmp/pwned')", "tool_code")
    with pytest.raises(ValueError, match="environ"):
        _validate_synthetic_imports("import math\nx = ctx.environ['API_KEY']", "tool_code")
    # Der Harness selbst durfte frueher os/sys importieren — jetzt gilt die
    # Sperre auf den GESAMT-Script.
    with pytest.raises(ValueError):
        _validate_synthetic_imports("import sys\nimport os", "combined_script")


def test_poc_passkey_fail_closed_but_registration_begin_allowed(monkeypatch):
    import backend.passkey_hitl as pkh
    import archon.routers.auth as auth

    unconfigured = {
        "enabled": False, "scope": "all",
        "categories": dict(pkh.DEFAULT_CATEGORIES),
        "credentials": [], "has_credentials": False,
    }
    monkeypatch.setattr(pkh, "get_user_passkey_config", lambda uid: dict(unconfigured))

    # Hochrisiko ohne Credentials -> hart True (Endpoint 403/503).
    for category in ("destructive_actions", "system", "payments"):
        assert is_passkey_required("usr_test", category) is True

    # Registrierungs-Route bleibt erreichbar (kein Step-up, HTTP-200).
    monkeypatch.setattr(auth, "get_current_user_from_request", lambda r: {
        "id": "usr_test", "username": "tester", "role": "admin",
    })
    res = auth.api_passkey_register_options(
        _Req(), auth.PasskeyRegisterOptionsRequest(user_id="usr_test")
    )
    assert res["status"] == "success"
    assert res["options"]["attestation"] == "direct"


def test_poc_creator_equals_approver_denied(tmp_path):
    db = str(tmp_path / "taint.db")
    mark_session_tainted("s1", "web", db_path=db)
    blocked = check_egress_tool_call(
        "s1", "pay", {"amount": 1}, db_path=db, requested_by="alice"
    )
    aid = blocked["approval_id"]
    with pytest.raises(PermissionError):
        resolve_taint_approval(aid, True, reviewer="alice", db_path=db)
    assert list_pending_taint_approvals(db_path=db)[0]["args_json"].startswith("[MASKED")


def test_poc_decision_empty_creator_fail_closed(monkeypatch):
    import archon.routers.decisions as decisions
    import archon.routers._rbac as rbac

    tid = "t-x"
    def _fake_api(method, path, payload=None, timeout=15.0):
        if method == "GET" and path == "/api/operations/kanban/meta":
            return {"tasks": {tid: {"decision": {
                "status": "offen", "typ": "synthesis_freigabe", "created_by": ""
            }}}}
        return {}
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(_decision_self_api=_fake_api))
    monkeypatch.setattr(rbac, "require_session_actor", lambda r: "bob")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(decisions.api_decide_decision(_Req(), {"task_id": tid, "decision": "approve"}))
    assert exc.value.status_code == 403


def test_poc_card_hitl_semantics(monkeypatch):
    with pytest.raises(PermissionError):
        resolve_card_hitl_decision("retry", actor="alice", created_by="alice")
    retry = resolve_card_hitl_decision("retry", current_budget=1000, actor="bob", created_by="alice")
    assert retry["next_status"] == "todo"
    abort = resolve_card_hitl_decision("abort", current_budget=1000, actor="bob")
    assert abort["next_status"] == "failed"
    assert abort["block_kind"] == "aborted_by_human"
    override = resolve_card_hitl_decision(
        "override_budget", current_budget=1000, override_budget=2000,
        actor="bob", created_by="alice", result_text="done",
    )
    assert override["next_status"] == "todo" and override["token_budget"] == 2000

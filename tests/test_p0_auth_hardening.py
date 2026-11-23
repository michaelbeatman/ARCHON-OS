"""P0-Regression: Welle A — Governance im Auslieferungszustand.

Audit 23.11.2026 (F-01..F-03):
- Warrant-HMAC-Key liegt in data/ und war nicht im Datei-Jail blockiert.
- /warrants/verify war ein öffentliches Orakel.
- POST /approvals/requests hatte keinen Rollenzaun.
- Passkey-HITL fuer 'payments' war opt-in: ohne Config durfte direkt gebucht werden.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_warrant_hmac_key_is_blocked_by_agent_file_jail():
    from backend.agent_rbac_jail import SENSITIVE_FILENAMES

    assert "warrant_hmac.key" in SENSITIVE_FILENAMES


def test_warrant_verify_endpoint_requires_admin():
    from fastapi import HTTPException

    import archon.routers._rbac as rbac
    import archon.routers.v2_capabilities as v2

    def deny(request):
        raise HTTPException(status_code=403, detail="denied")

    previous = rbac._checker
    rbac._checker = deny
    try:
        with pytest.raises(HTTPException) as exc:
            v2.api_v2_verify_warrant(mock.MagicMock(), mock.MagicMock())
        assert exc.value.status_code == 403
    finally:
        rbac._checker = previous


def test_create_approval_request_requires_admin():
    from fastapi import HTTPException

    import archon.routers._rbac as rbac
    import archon.routers.operations_approvals as approvals

    def deny(request):
        raise HTTPException(status_code=403, detail="denied")

    previous = rbac._checker
    rbac._checker = deny
    try:
        with pytest.raises(HTTPException) as exc:
            approvals.api_create_approval_request(mock.MagicMock(), mock.MagicMock())
        assert exc.value.status_code == 403
    finally:
        rbac._checker = previous


def test_payments_passkey_is_fail_closed_without_config(monkeypatch):
    import backend.passkey_hitl as pkh

    unconfigured = {
        "enabled": False,
        "scope": "all",
        "categories": dict(pkh.DEFAULT_CATEGORIES),
        "credentials": [],
        "has_credentials": False,
    }
    monkeypatch.setattr(pkh, "get_user_passkey_config", lambda uid: unconfigured)

    assert pkh.is_passkey_required("user-without-passkey", category="payments") is True

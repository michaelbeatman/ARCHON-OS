"""Regressionstests R-15 + D-14 fuer archon/routers/llm_providers.py.

R-15: Das HTTPException(400) der save-key-Validierung lag INNERHALB des
try/except und wurde zum HTTP 200 {"status":"error"} — außerdem meldete der
Handler „erfolgreich verteilt", auch wenn deploy_keys fehlschlug.

D-14: POST /api/llm-providers/test-connection hatte keinen Rollenzaun —
jeder Session-Inhaber konnte interne Endpunkte abtasten.
"""

import os
import sys
import types
from unittest import mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import llm_providers as lp  # noqa: E402
from archon.routers.llm_providers import (  # noqa: E402
    LLMProviderSaveKeyRequest,
    api_test_provider_connection,
    save_llm_provider_key,
)


def _fake_api_provider(deploy_status="ok"):
    mod = types.ModuleType("api_provider")
    mod.ENV_PATH = ".env"
    mod.set_env_value = mock.Mock()
    mod.deploy_keys = mock.Mock(return_value={"status": deploy_status, "targets": 2})
    return mod


# ---------------------------------------------------------------- R-15

def test_save_key_empty_values_raise_http_400_not_silent_dict():
    with mock.patch.dict(sys.modules, {"api_provider": _fake_api_provider()}), \
         mock.patch.object(lp, "require_admin_or_503", return_value=None):
        with pytest.raises(HTTPException) as e:
            save_llm_provider_key(mock.Mock(), LLMProviderSaveKeyRequest(env_name="  ", key_value=""))
    assert e.value.status_code == 400


def test_save_key_honest_error_when_deploy_fails():
    with mock.patch.dict(sys.modules, {"api_provider": _fake_api_provider("no_keys_found")}), \
         mock.patch.object(lp, "require_admin_or_503", return_value=None):
        res = save_llm_provider_key(mock.Mock(), LLMProviderSaveKeyRequest(env_name="MY_KEY", key_value="sk-123"))
    assert res["status"] == "error"
    assert "Verteilung fehlgeschlagen" in res["message"]


def test_save_key_success_message_only_when_deploy_ok():
    with mock.patch.dict(sys.modules, {"api_provider": _fake_api_provider("ok")}), \
         mock.patch.object(lp, "require_admin_or_503", return_value=None):
        res = save_llm_provider_key(mock.Mock(), LLMProviderSaveKeyRequest(env_name="MY_KEY", key_value="sk-123"))
    assert res["status"] == "ok"
    assert "erfolgreich hinterlegt und verteilt" in res["message"]


# ---------------------------------------------------------------- D-14

def test_test_connection_requires_admin():
    with mock.patch.object(lp, "require_admin_or_503", side_effect=HTTPException(503, "keine admin-session")), \
         mock.patch("backend.privacy_router.test_endpoint_sync") as tst:
        with pytest.raises(HTTPException) as e:
            api_test_provider_connection(mock.Mock(), {"provider": "local", "url": "http://127.0.0.1:11434/v1"})
    assert e.value.status_code == 503
    tst.assert_not_called()


def test_test_connection_runs_for_admin():
    with mock.patch.object(lp, "require_admin_or_503", return_value=None), \
         mock.patch("backend.privacy_router.test_endpoint_sync", return_value={"available": True}):
        res = api_test_provider_connection(mock.Mock(), {"provider": "local", "url": "http://127.0.0.1:11434/v1"})
    assert res["status"] == "ok"
    assert res["result"]["available"] is True

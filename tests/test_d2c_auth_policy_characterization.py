# -*- coding: utf-8 -*-
"""2c-Characterization: Auth-/RAG-Policy ueber die main.*-Attribute.

Festgenagelt VOR der Extraktion nach archon/middleware/auth_policy.py und
gueltig NACH dem X-as-X-Re-Export. Alle Assertions laufen ueber Attribut-
zugriffe, nicht ueber main.py-Quelltext -> kein S-Test (ANALYSIS Anhang D.1).
"""

from __future__ import annotations

import pytest

import main as app_main


def test_2c_public_health_paths_stay_public():
    for path in ("/", "/health", "/livez", "/readyz", "/metrics"):
        assert path in app_main._AUTH_PUBLIC_EXACT
    # Kalender-Webhook ist bewusst NUR als exakter Pfad offen.
    assert "/api/v1/calendar/webhooks/push" in app_main._AUTH_PUBLIC_EXACT
    with pytest.raises(AssertionError):  # Negativprobe
        assert "/api/admin" in app_main._AUTH_PUBLIC_EXACT


def test_2c_rag_key_is_fail_closed_and_env_driven(monkeypatch):
    monkeypatch.delenv("ANYTHINGLLM_API_KEY", raising=False)
    with pytest.raises(app_main.MissingRagApiKeyError):
        app_main._get_rag_api_key()
    monkeypatch.setenv("ANYTHINGLLM_API_KEY", "rag-key-probe")
    assert app_main._get_rag_api_key() == "rag-key-probe"
    assert app_main.RAG_API_KEY_ENV == "ANYTHINGLLM_API_KEY"
    with pytest.raises(AssertionError):  # Negativprobe
        assert app_main._get_rag_api_key() == ""


def test_2c_auth_unavailable_response_is_503():
    resp = app_main._auth_unavailable_response()
    assert resp.status_code == 503
    assert b"auth_unavailable" in resp.body
    with pytest.raises(AssertionError):
        assert resp.status_code == 200


def test_2c_rag_startup_hook_and_service_token_contract_stay_in_main():
    # Diese beiden bleiben PHYSISCH in main.py (siehe Modul-Docstring):
    # __file__-Abhaengigkeit bzw. stabiler Contract D2 §295.
    assert app_main._check_rag_api_key_config in app_main._STARTUP_HOOKS
    assert callable(app_main._request_has_service_token)
    assert app_main._request_has_service_token.__module__ == "main"
    with pytest.raises(AssertionError):
        assert app_main._check_rag_api_key_config not in app_main._STARTUP_HOOKS

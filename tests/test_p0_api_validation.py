"""P0: API-Validierung — Auth-Router auf Pydantic-v2-Modelle (Roadmap Etappe 2a).

Audit 23.11.2026 (F-01): rohe `dict = Body(...)`-Parameter akzeptieren
beliebige Typen und liefern bei Fehlern HTTP 200. Die Kompatibilitätsregel
der Roadmap gilt: extra="ignore", alte Response-Shapes bleiben erhalten.
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import auth as auth_router  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router.router)
    return TestClient(app)


def test_login_rejects_wrong_types_with_422():
    response = _client().post(
        "/api/auth/login", json={"username": 12345, "password": ["not", "a", "string"]}
    )
    assert response.status_code == 422, response.text


def test_create_user_model_validates_types():
    with pytest.raises(ValidationError):
        auth_router.AuthCreateUserRequest(username=123, password="secret")


def test_passkey_verify_model_validates_alg():
    with pytest.raises(ValidationError):
        auth_router.PasskeyRegisterVerifyRequest(alg="not-an-int")


def test_request_models_ignore_unknown_client_fields():
    model = auth_router.AuthLoginRequest(
        username="alice", password="secret", created_by="spoofed-client-value"
    )
    dumped = model.model_dump()
    assert dumped["username"] == "alice"
    assert "created_by" not in dumped

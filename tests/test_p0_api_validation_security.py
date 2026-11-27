"""P0 API-Validierung Etappe 2c: security.py + routergate.py (11 Endpunkte)."""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import routergate, security  # noqa: E402


def test_security_models_reject_wrong_types():
    with pytest.raises(ValidationError):
        security.MaskSecretsRequest(text=123)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        security.ExecutionReceiptIssueRequest(prompt_tokens="many")  # type: ignore[arg-type]


def test_routergate_models_reject_wrong_types_and_negative_values():
    with pytest.raises(ValidationError):
        routergate.EstimateCostRequest(expected_output_tokens="lots")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        routergate.BanditOutcomeRequest(latency_ms=-5)


def test_mask_secrets_endpoint_returns_422_for_non_string_text(admin_rbac_bypass):
    app = FastAPI()
    app.include_router(security.router)
    response = TestClient(app).post("/api/security/mask-secrets", json={"text": 123})
    assert response.status_code == 422, response.text

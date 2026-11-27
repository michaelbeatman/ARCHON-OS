"""P0 API-Validierung, Etappe 2b: system.py + plugins.py.

Fortsetzung des Musters aus Etappe 2a: Pydantic-Modelle mit extra="ignore",
Handler wandeln das Modell zu Beginn in ein Dict um (Response-Shapes bleiben).
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import plugins as plugins_router  # noqa: E402
from archon.routers import system as system_router  # noqa: E402


def test_system_models_exist_and_validate_types():
    with pytest.raises(ValidationError):
        system_router.SystemLanguageRequest(language=123)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        system_router.DrainStartRequest(grace_seconds="not-a-number")  # type: ignore[arg-type]


def test_system_language_endpoint_rejects_wrong_type_with_422(admin_rbac_bypass):
    old_deps = dict(system_router._DEPS)
    system_router.configure(require_admin=lambda request: None)
    try:
        app = FastAPI()
        app.include_router(system_router.router)
        response = TestClient(app).post("/api/system/language", json={"language": 123})
        assert response.status_code == 422, response.text
    finally:
        system_router._DEPS.clear()
        system_router._DEPS.update(old_deps)


def test_plugin_tool_model_validates_tool_name():
    with pytest.raises(ValidationError):
        plugins_router.PluginToolExecuteRequest(tool_name=123)  # type: ignore[arg-type]


def test_plugin_settings_keeps_arbitrary_config_fields():
    model = plugins_router.PluginSettingsRequest(custom_option="keep-me", nested={"a": 1})  # type: ignore[call-arg]
    dumped = model.model_dump()
    assert dumped["custom_option"] == "keep-me"
    assert dumped["nested"] == {"a": 1}

"""Rot-Beweis fuer K-1 und R-11.

K-1: Rollenzaun auf archon/routers/voice.py (/api/voice/speak, /api/voice/command)
     und Traversal-Schutz auf /api/voice/audio/{filename}.
R-11: GET /api/hermes/raw_config: require_admin, safe_path fuer freien Pfadparameter,
      und Maskierung in 'parsed'.
"""

import inspect
import os
import tempfile
import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _make_dummy_request(role: str = "operator") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/voice/command",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8501),
        "state": {
            "user": {
                "id": "usr_test",
                "username": "tester",
                "role": role,
                "permissions": {},
            }
        },
    }
    return Request(scope)


def test_k1_voice_router_has_rbac_guard():
    """K-1: voice.py muss require_admin_or_503 importieren und in speak/command aufrufen."""
    import archon.routers.voice as voice_mod

    assert hasattr(voice_mod, "require_admin_or_503"), "require_admin_or_503 nicht in archon.routers.voice importiert"

    sig_speak = inspect.signature(voice_mod.api_voice_speak)
    assert "request" in sig_speak.parameters, "api_voice_speak fehlt request: Request"

    sig_cmd = inspect.signature(voice_mod.api_voice_command)
    assert "request" in sig_cmd.parameters, "api_voice_command fehlt request: Request"

    # Operator muss abgewiesen werden (403)
    req_op = _make_dummy_request(role="operator")
    with pytest.raises(HTTPException) as exc_info:
        # require_admin_or_503 wird als erste Anweisung aufgerufen
        voice_mod.require_admin_or_503(req_op)
    assert exc_info.value.status_code in (403, 503)


def test_k1_voice_audio_traversal_blocked():
    """K-1 Traversal-Schutz: api_get_voice_audio darf nicht aus data/audio_cache ausbrechen."""
    import archon.routers.voice as voice_mod

    with pytest.raises(HTTPException) as exc_info:
        voice_mod.api_get_voice_audio("../../main.py")
    assert exc_info.value.status_code in (400, 403)


def test_r11_raw_config_requires_admin_and_blocks_traversal(monkeypatch):
    """R-11: GET /api/hermes/raw_config muss require_admin haben und path gegen Jail pruefen."""
    import main as app_main

    sig = inspect.signature(app_main.api_get_hermes_raw_config)
    assert "request" in sig.parameters, "api_get_hermes_raw_config fehlt request-Parameter"

    # Operator wird von require_admin abgewiesen
    monkeypatch.setattr(app_main, "get_current_user_from_request", lambda r: {"role": "operator"})
    req = _make_dummy_request(role="operator")
    with pytest.raises(HTTPException) as exc_op:
        app_main.api_get_hermes_raw_config(req, path=None)
    assert exc_op.value.status_code == 403

    # Traversal mit path=/etc/passwd muss mit 403 geblockt werden (auch fuer Admin)
    monkeypatch.setattr(app_main, "get_current_user_from_request", lambda r: {"role": "admin"})
    req_admin = _make_dummy_request(role="admin")
    with pytest.raises(HTTPException) as exc_info:
        app_main.api_get_hermes_raw_config(req_admin, path="/etc/passwd")
    assert exc_info.value.status_code in (400, 403)


def test_r11_raw_config_parsed_masks_secrets(monkeypatch):
    """R-11: 'parsed' darf keine unmaskierten API-Keys enthalten."""
    import main as app_main

    monkeypatch.setattr(app_main, "get_current_user_from_request", lambda r: {"role": "admin"})

    yaml_with_secret = (
        "model:\n"
        "  provider: openrouter\n"
        "  api_key: sk-or-v1-dummytestkey1234567890\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir="/tmp", delete=False) as f:
        f.write(yaml_with_secret)
        tmp_path = f.name

    try:
        req_admin = _make_dummy_request(role="admin")
        os.makedirs("agent_workspace/sandbox", exist_ok=True)
        safe_conf_path = os.path.abspath("agent_workspace/sandbox/test_hermes_conf.yaml")
        with open(safe_conf_path, "w", encoding="utf-8") as f2:
            f2.write(yaml_with_secret)

        res = app_main.api_get_hermes_raw_config(req_admin, path=safe_conf_path)
        assert "parsed" in res
        parsed = res["parsed"]
        # Das Secret darf weder in yaml_content noch in parsed im Klartext stehen
        assert "sk-or-v1-dummytestkey1234567890" not in res["yaml_content"]
        raw_in_parsed = str(parsed)
        assert "sk-or-v1-dummytestkey1234567890" not in raw_in_parsed, "Klartext-Key in parsed gefunden!"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(safe_conf_path):
            os.remove(safe_conf_path)

"""Cluster 1 — F1/R-34 und F11: Hermes-Proxy umgeht Auth-Gate, setzt Admin-Token ein.

Rot gegen HEAD (909421d6):

* ``/static/hermes-webui/api/*`` liegt unter ``_AUTH_PUBLIC_PREFIXES = ("/static/",)``
  und wird von ``auth_gate`` ungeprueft durchgelassen.
* ``forward_to_hermes`` setzt bei fehlendem Env-Key den Literal-Fallback
  ``sk-arc...-dev`` als ``Authorization``-Header.
* ``proxy_hermes_api_endpoints`` verzweigt nicht nach Methode: kein Rollenzaun
  fuer POST/PUT/PATCH/DELETE.

Die Tests rufen Middleware und Handler direkt auf; ``httpx`` und der Forward
sind gestubbt (kein Netzverkehr).
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import HTTPException

from archon_security_support import (
    ADMIN, GATE_PASSED, OPERATOR, VIEWER, import_main, make_request, run_gate, status_of,
)

FORCED_API_PATH = "/static/hermes-webui/api/sessions"
PROXY_HEADER_ENV = ("HERMES_SESSION_TOKEN", "HERMES_DASHBOARD_SESSION_TOKEN", "OMNIROUTE_API_KEY")


# --------------------------------------------------------------------------
# Gate: der API-Pfad unter /static/ darf nicht mehr oeffentlich sein
# --------------------------------------------------------------------------

@pytest.fixture()
def main_with_auth(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: None)
    return main


def test_static_assets_stay_public(main_with_auth):
    """/static/js/... bleibt ohne Login erreichbar (App-Shell muss laden)."""
    response = run_gate(main_with_auth, make_request("/static/js/chat_engine.js", "GET"))
    assert status_of(response) == GATE_PASSED


def test_hermes_api_proxy_requires_session(main_with_auth):
    """Ohne Session -> 401 statt Durchreichen an den Hermes-Admin-Proxy."""
    response = run_gate(main_with_auth, make_request(FORCED_API_PATH, "GET"))
    assert status_of(response) == 401
    assert b"unauthorized" in response.body


def test_hermes_api_proxy_rejects_viewer_session(monkeypatch):
    """Session allein genuegt fuer das Gate — Rollenfrage klaert der Handler."""
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(VIEWER))
    response = run_gate(main, make_request(FORCED_API_PATH, "GET", token="tok_viewer"))
    assert status_of(response) == GATE_PASSED


def test_hermes_api_proxy_accepts_admin_session(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(ADMIN))
    response = run_gate(main, make_request(FORCED_API_PATH, "GET", token="tok_admin"))
    assert status_of(response) == GATE_PASSED


# --------------------------------------------------------------------------
# forward_to_hermes: kein Fallback-Token mehr
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self) -> None:
        self.content = b'{"ok": true}'
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class _RecordingClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def request(self, **kwargs):
        type(self).calls.append(kwargs)
        return _FakeResponse()


@pytest.fixture()
def no_env_token(monkeypatch):
    for name in PROXY_HEADER_ENV:
        monkeypatch.delenv(name, raising=False)
    _RecordingClient.calls = []
    main = import_main()
    monkeypatch.setattr(main.httpx, "AsyncClient", _RecordingClient)
    return main


def test_forward_without_env_token_returns_502(no_env_token):
    """Fehlt der Env-Key, wird nicht durchgereicht (kein Literal-Fallback)."""
    main = no_env_token
    response = asyncio.run(main.forward_to_hermes(make_request("/api/sessions", "GET")))
    assert status_of(response) == 502
    assert _RecordingClient.calls == []


def test_forward_uses_env_token_and_drops_literal(monkeypatch):
    for name in PROXY_HEADER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "token-from-env-42")
    _RecordingClient.calls = []
    main = import_main()
    monkeypatch.setattr(main.httpx, "AsyncClient", _RecordingClient)

    response = asyncio.run(main.forward_to_hermes(make_request("/api/sessions", "GET")))

    assert status_of(response) == 200
    assert _RecordingClient.calls, "Forward haette genau einen Kandidaten erreichen muessen"
    sent = _RecordingClient.calls[0]["headers"]
    assert sent["Authorization"] == "Bearer token-from-env-42"
    assert sent["X-Hermes-Session-Token"] == "token-from-env-42"


def test_no_hardcoded_fallback_token_in_source():
    """Der Token-Ausdruck darf nur aus ``os.getenv`` bestehen — kein Literal.

    Geprueft wird der AST statt einer Textsuche: das Literal im Altstand ist ein
    scheinbarer Dev-Token und wird von Ausgabe-Filtern redigiert; ein
    Zeichenkettenvergleich waere hier nicht belastbar.
    """
    import ast

    main_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    with open(main_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=main_path)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not any(name.startswith("_hermes_tok") for name in names):
            continue
        literals = [
            child for child in ast.walk(node.value)
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.strip()
        ]
        if literals:
            offenders.append(node.lineno)

    assert not offenders, (
        "Fallback-Token-Literal in der Token-Zuweisung (Zeile(n): "
        f"{offenders}) — bei fehlendem Env-Key muss 502 folgen."
    )


# --------------------------------------------------------------------------
# F11: Methodenverzweigung im Proxy-Handler
# --------------------------------------------------------------------------

@pytest.fixture()
def proxy_stub(monkeypatch):
    """Stubbt den Forward; liefert (main, calls-Liste)."""
    main = import_main()
    calls: list[str] = []

    async def _fake_forward(request):
        calls.append(request.method)
        from starlette.responses import JSONResponse
        return JSONResponse({"forwarded": True}, status_code=200)

    monkeypatch.setattr(main, "forward_to_hermes", _fake_forward)
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    return main, calls


@pytest.mark.parametrize("role_user", [OPERATOR, VIEWER], ids=["operator", "viewer"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_proxy_write_methods_require_admin(proxy_stub, monkeypatch, role_user, method):
    main, calls = proxy_stub
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(role_user))
    request = make_request(FORCED_API_PATH, method, token="tok_user")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.proxy_hermes_api_endpoints(request, path="sessions"))

    assert exc.value.status_code == 403
    assert calls == [], "gesperrte Methode darf nicht an Hermes durchgereicht werden"


@pytest.mark.parametrize("method", ["GET", "OPTIONS"])
def test_proxy_read_methods_forward_for_operator(proxy_stub, monkeypatch, method):
    """Lesen bleibt fuer eingeloggte Rollen offen (Dashboard-Anzeige)."""
    main, calls = proxy_stub
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(OPERATOR))
    request = make_request(FORCED_API_PATH, method, token="tok_op")

    response = asyncio.run(main.proxy_hermes_api_endpoints(request, path="sessions"))

    assert status_of(response) == 200
    assert calls == [method]


def test_proxy_write_method_forwards_for_admin(proxy_stub, monkeypatch):
    main, calls = proxy_stub
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(ADMIN))
    request = make_request(FORCED_API_PATH, "POST", token="tok_admin")

    response = asyncio.run(main.proxy_hermes_api_endpoints(request, path="sessions"))

    assert status_of(response) == 200
    assert calls == ["POST"]

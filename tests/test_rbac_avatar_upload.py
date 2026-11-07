"""Rollenzaun fuer die Avatar-Upload-Route (hermes_profiles.py).

Deckt die drei Pflichtauflagen ab:

1. fail-closed — ohne injizierte Prueffunktion sperrt die Route (503), bevor
   irgendein Schreibpfad laeuft.
2. keine Aussperrung — ``auth.enabled=false`` (Fallback-Admin), Service-Token
   interner Automaten und Admin-Session erreichen die Route jeweils mit 200.
3. Umfang — nur ``api_upload_hermes_profile_avatar`` ist Gegenstand; die Tests
   halten zusaetzlich fest, dass der Zaun die *erste* Anweisung ist.

Die Schreibseite (Datei, profile.yaml, avatars.db) wird je Test isoliert, damit
die Suite nicht in den Arbeitsbaum oder die Laufzeitdatenbank schreibt. Der
Rollenentscheid selbst faellt im echten ``main.require_admin`` — nur die
Identitaetsquellen (Session-Store, Service-Token, auth-Schalter) sind gesteuert.
"""

import base64
import inspect
import os
import sqlite3
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN = {"id": "usr_admin", "username": "admin", "role": "admin", "permissions": {},
         "is_service": False}
OPERATOR = {"id": "usr_op", "username": "lisa", "role": "operator", "permissions": {}}
VIEWER = {"id": "usr_vw", "username": "max", "role": "viewer", "permissions": {}}

AVATAR_PATH = "/api/hermes/profiles/probe/avatar"
DATA_URI = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nPROBE").decode()


def _app():
    import main  # noqa: PLC0415  (spaeter Import: Modulaufbau)
    return main


def _route():
    from archon.routers import hermes_profiles as hp  # noqa: PLC0415
    return hp


def _fake_request(method="POST", path=AVATAR_PATH, headers=None):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or [])],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "app": _app().app,
    })


@pytest.fixture()
def wired(monkeypatch):
    """Verdrahtet den gemeinsamen Zaun mit der echten Prueffunktion aus main."""
    from archon.routers import _rbac as rbac_module

    main = _app()
    monkeypatch.setattr(rbac_module, "_checker", main.require_admin)
    return main


@pytest.fixture()
def isolated(monkeypatch):
    """Isoliert alle Schreibpfade der Route; zaehlt Materialisierungen."""
    hp = _route()
    calls = {"materialize": 0}

    def fake_materialize(profile_id, data_url):
        calls["materialize"] += 1
        return f"/static/avatars/{profile_id}.png"

    monkeypatch.setattr(hp, "materialize_data_uri_avatar", fake_materialize)
    monkeypatch.setattr(hp, "get_hermes_profiles_base_dirs", lambda: [])
    monkeypatch.setattr(hp, "invalidate_hermes_profiles_cache", lambda: None)
    monkeypatch.setattr(hp, "api_get_hermes_profiles", lambda: [])

    # avatars.db-Schreibpfad: Verbindungsaufbau scheitert -> wird von der Route
    # als Warnung geschluckt, der Test bleibt ohne DB-Nebenwirkung.
    def _no_db(*args, **kwargs):
        raise RuntimeError("avatars.db im Test deaktiviert")

    monkeypatch.setattr(sqlite3, "connect", _no_db)
    return calls


def _upload(request):
    return _route().api_upload_hermes_profile_avatar(
        request, profile_id="probe", data={"image": DATA_URI},
    )


# ---------------------------------------------------------------- Nicht-Admin

@pytest.mark.parametrize("user", [OPERATOR, VIEWER], ids=["operator", "viewer"])
def test_non_admin_gets_403_before_write(wired, isolated, monkeypatch, user):
    """Nicht-Admin: 403 aus dem Zaun, kein Schreibpfad wird erreicht."""
    monkeypatch.setattr(wired.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(wired.auth_service, "verify_session", lambda tok: dict(user))

    with pytest.raises(HTTPException) as exc:
        _upload(_fake_request(headers=[("authorization", "Bearer tok_user")]))

    assert exc.value.status_code == 403
    assert "Administratoren" in str(exc.value.detail)
    assert isolated["materialize"] == 0, "Zaun stand nicht vor dem Schreibpfad"


def test_wrong_service_token_grants_nothing(wired, isolated, monkeypatch):
    """Ein falscher Service-Token oeffnet die Route nicht."""
    monkeypatch.setattr(wired.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(wired, "_get_service_token", lambda: "tok-service-test")

    with pytest.raises(HTTPException) as exc:
        _upload(_fake_request(headers=[("x-archon-service-token", "tok-falsch")]))

    assert exc.value.status_code == 403
    assert isolated["materialize"] == 0


# ------------------------------------------------------- Durchlaessigkeit (200)

def test_admin_session_returns_200(wired, isolated, monkeypatch):
    """Admin-Session passiert den Zaun und die Route antwortet 200."""
    monkeypatch.setattr(wired.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(wired.auth_service, "verify_session", lambda tok: dict(ADMIN))

    result = _upload(_fake_request(headers=[("authorization", "Bearer tok_admin")]))

    assert result["status"] == "success"
    assert result["profile_id"] == "probe"
    assert result["avatar_url"] == "/static/avatars/probe.png"
    assert isolated["materialize"] == 1


def test_service_token_returns_200(wired, isolated, monkeypatch):
    """X-Archon-Service-Token (interne Automaten) passiert den Zaun."""
    monkeypatch.setattr(wired.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(wired, "_get_service_token", lambda: "tok-service-test")

    result = _upload(_fake_request(
        headers=[("x-archon-service-token", "tok-service-test")],
    ))

    assert result["status"] == "success"
    assert isolated["materialize"] == 1


def test_auth_disabled_fallback_admin_returns_200(wired, isolated, monkeypatch):
    """auth.enabled=false: Fallback-Admin, das Einzelnutzer-System bleibt bedienbar."""
    monkeypatch.setattr(wired.auth_service, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(wired.auth_service, "get_fallback_admin",
                        lambda: dict(ADMIN, is_fallback=True))

    result = _upload(_fake_request())

    assert result["status"] == "success"
    assert isolated["materialize"] == 1


# ----------------------------------------------------------------- fail-closed

def test_route_fails_closed_without_injection(isolated, monkeypatch):
    """Ohne injizierte Prueffunktion sperrt die Route (503), statt zu schreiben."""
    from archon.routers import _rbac as rbac_module

    monkeypatch.setattr(rbac_module, "_checker", None)

    with pytest.raises(HTTPException) as exc:
        _upload(_fake_request())

    assert exc.value.status_code == 503
    assert "nicht verdrahtet" in str(exc.value.detail)
    assert isolated["materialize"] == 0, "fail-closed verletzt: Schreibpfad erreicht"


def test_guard_is_first_statement_of_route():
    """Der Zaun steht vor dem try-Block — kein except kann 403/503 umdeuten."""
    hp = _route()
    source = inspect.getsource(hp.api_upload_hermes_profile_avatar)
    lines = source.splitlines()
    body_start = next(i for i, line in enumerate(lines) if line.rstrip().endswith("):")) + 1
    body_lines = [line.strip() for line in lines[body_start:] if line.strip()]
    assert body_lines[0].startswith("require_admin_or_503(request)"), body_lines[0]
    guard_idx = source.index("require_admin_or_503(request)")
    try_idx = source.index("    try:")
    assert guard_idx < try_idx, "Zaun steht hinter dem try-Block"


def test_signature_accepts_request():
    """Die Signatur fuehrt ``Request``, damit der Zaun die Identitaet pruefen kann."""
    hp = _route()
    assert "request" in inspect.signature(
        hp.api_upload_hermes_profile_avatar
    ).parameters

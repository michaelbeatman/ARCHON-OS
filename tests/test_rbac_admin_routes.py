"""RBAC-Pilot: Rollenzaun auf sechs destruktiven Routen (A5).

Geprüft werden genau die sechs Routen, die der Pilot umstellt:

    POST /api/docker/start
    POST /api/docker/stop
    POST /api/v1/container/exec
    POST /api/sandbox/execute
    POST /api/v1/system/update/apply      (archon/routers/system.py)
    POST /api/v1/system/update/rollback   (archon/routers/system.py)

Je Route vier Zugangsarten:

    Rolle operator/viewer        -> 403 (und **keine** Wirkung: der Zaun steht
                                    vor der ersten fachlichen Anweisung)
    Rolle admin                  -> kein 403
    X-Archon-Service-Token       -> wie admin (interne Automaten bleiben drin)
    auth.enabled = false         -> wie admin (Einzelnutzer-Modus bleibt offen)

Dazu der Fail-closed-Test des Routers: fehlt die injizierte Prüfung, muss
``system/update/apply`` **sperren** (503) statt durchzulassen.

Alles über ``TestClient`` gegen das App-Objekt im Prozess. Es geht kein Request
an den laufenden Dienst, und jede fachliche Funktion ist durch eine Attrappe
ersetzt — ein durchgelassener Request kann deshalb nichts auslösen.
"""

import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN = {"id": "usr_admin", "username": "admin", "role": "admin", "permissions": {}}
OPERATOR = {"id": "usr_op", "username": "lisa", "role": "operator", "permissions": {}}
VIEWER = {"id": "usr_vw", "username": "max", "role": "viewer", "permissions": {}}

ROUTES = [
    pytest.param("POST", "/api/docker/start", {"container_name": "n8n"}, id="docker-start"),
    pytest.param("POST", "/api/docker/stop", {"container_name": "n8n"}, id="docker-stop"),
    pytest.param("POST", "/api/v1/container/exec",
                 {"container_name": "n8n", "command": "ls"}, id="container-exec"),
    pytest.param("POST", "/api/sandbox/execute",
                 {"code": "print(1)", "language": "python"}, id="sandbox-execute"),
    pytest.param("POST", "/api/v1/system/update/apply",
                 {"backup": False}, id="system-update-apply"),
    pytest.param("POST", "/api/v1/system/update/rollback",
                 {"snapshot_id": "snap-1"}, id="system-update-rollback"),
]


def _app():
    import main  # noqa: PLC0415  (später Import: ~1 s Modulaufbau)
    return main


# --------------------------------------------------------------- Attrappen

class Fakes:
    """Sammelstelle der ersetzten Fachfunktionen, damit Tests 'nicht gerufen' prüfen."""

    def __init__(self):
        self.docker_action = None
        self.load_configs = None
        self.send_prompt = None
        self.apply_update = None
        self.rollback_snapshot = None
        self.sandbox_execute = None
        self.jev_enabled = None

    def all_mocks(self):
        return [m for m in (self.docker_action, self.load_configs, self.send_prompt,
                            self.apply_update, self.rollback_snapshot,
                            self.sandbox_execute, self.jev_enabled) if m is not None]


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(_app().app)


@pytest.fixture
def fakes():
    """Ersetzt jede Fachfunktion der sechs Routen durch eine Attrappe."""
    import backend.system_updater as system_updater
    from backend.ephemeral_sandbox import ephemeral_sandbox
    import jev_router

    m = _app()
    f = Fakes()
    with patch.object(m, "post_docker_container_action",
                      return_value={"status": "success"}) as f.docker_action, \
            patch.object(m, "load_agent_configs", return_value={}) as f.load_configs, \
            patch.object(m, "send_prompt_to_agent", return_value="ok") as f.send_prompt, \
            patch.object(system_updater, "apply_update",
                         return_value={"status": "success"}) as f.apply_update, \
            patch.object(system_updater, "rollback_snapshot",
                         return_value={"status": "success"}) as f.rollback_snapshot, \
            patch.object(ephemeral_sandbox, "execute_in_sandbox",
                         return_value={"status": "ok"}) as f.sandbox_execute, \
            patch.object(jev_router, "is_jev_enabled", return_value=False) as f.jev_enabled:
        yield f


def _call(client, method, path, payload, *, user, auth_enabled=True,
          service_token=None, headers=None):
    """Ein Request mit gesteuerter Identität."""
    m = _app()
    hdrs = dict(headers or {})
    if user is not None:
        hdrs["Authorization"] = "Bearer tok_test"
    if service_token is not None:
        hdrs["X-Archon-Service-Token"] = service_token
    with patch.object(m.auth_service, "is_auth_enabled", return_value=auth_enabled), \
            patch.object(m.auth_service, "verify_session", return_value=user):
        return client.request(method, path, json=payload, headers=hdrs)


# ------------------------------------------------------------ Rollenzaun

@pytest.mark.parametrize("role_user", [OPERATOR, VIEWER], ids=["operator", "viewer"])
@pytest.mark.parametrize("method,path,payload", ROUTES)
def test_non_admin_role_is_forbidden(client, fakes, role_user, method, path, payload):
    """Ohne Admin-Rolle: 403 — und zwar bevor irgendetwas passiert."""
    r = _call(client, method, path, payload, user=role_user)

    assert r.status_code == 403, f"{path}: erwartet 403, bekam {r.status_code}: {r.text}"
    assert "Administratoren" in r.json().get("detail", ""), r.text
    for mock in fakes.all_mocks():
        assert not mock.called, f"{path}: Aktion lief trotz 403 ({mock})"


@pytest.mark.parametrize("method,path,payload", ROUTES)
def test_admin_role_passes(client, fakes, method, path, payload):
    """Mit Admin-Rolle: kein 403 (Verhalten wie vor dem Pilot)."""
    r = _call(client, method, path, payload, user=ADMIN)

    assert r.status_code != 403, f"{path}: Admin wurde ausgesperrt: {r.text}"
    assert r.status_code == 200, f"{path}: erwartet 200, bekam {r.status_code}: {r.text}"


@pytest.mark.parametrize("method,path,payload", ROUTES)
def test_service_token_still_passes(client, fakes, method, path, payload):
    """Service-Token bleibt Durchlass (n8n, Adapter) — automatisierte Läufe nicht aussperren."""
    m = _app()
    with patch.object(m, "_get_service_token", return_value="tok-service-test"):
        r = _call(client, method, path, payload, user=None,
                  service_token="tok-service-test")

    assert r.status_code != 403, f"{path}: Service-Token wurde gesperrt: {r.text}"
    assert r.status_code == 200, f"{path}: {r.status_code}: {r.text}"


@pytest.mark.parametrize("method,path,payload", ROUTES)
def test_auth_disabled_stays_open(client, fakes, method, path, payload):
    """auth.enabled=false (Einzelnutzer): Fallback-Admin, System bleibt bedienbar."""
    m = _app()
    with patch.object(m.auth_service, "get_fallback_admin",
                      return_value=dict(ADMIN, is_fallback=True)):
        r = _call(client, method, path, payload, user=None, auth_enabled=False)

    assert r.status_code != 403, f"{path}: Einzelnutzer-Modus wurde gesperrt: {r.text}"
    assert r.status_code == 200, f"{path}: {r.status_code}: {r.text}"


def test_wrong_service_token_grants_nothing(client, fakes):
    """Falscher Service-Token ist kein Freifahrtschein (401 aus dem Auth-Gate)."""
    m = _app()
    with patch.object(m, "_get_service_token", return_value="tok-service-test"):
        r = _call(client, "POST", "/api/docker/stop", {"container_name": "n8n"},
                  user=None, service_token="tok-falsch")

    assert r.status_code in (401, 403), f"erwartet 401/403, bekam {r.status_code}: {r.text}"
    assert not fakes.docker_action.called


# ------------------------------------------------------- Router fail-closed

def test_system_router_fails_closed_without_injected_checker(client, fakes):
    """Ohne injizierte Prüfung muss der Router sperren (503), nicht durchlassen."""
    from archon.routers import system as system_router

    saved = system_router._DEPS.pop("require_admin", None)
    assert saved is not None, "Vorbedingung: require_admin ist normalerweise injiziert"
    try:
        r = _call(client, "POST", "/api/v1/system/update/apply",
                  {"backup": False}, user=ADMIN)
    finally:
        system_router._DEPS["require_admin"] = saved

    assert r.status_code == 503, (
        f"Router ließ ohne Rollenzaun durch (Status {r.status_code}) — fail-open!"
    )
    assert not fakes.apply_update.called, "Update lief trotz fehlender Prüfung"


def test_system_router_warns_about_missing_dependency(caplog):
    """configure() ohne require_admin muss laut werden (Warnung), nicht still."""
    import logging
    from archon.routers import system as system_router

    saved = dict(system_router._DEPS)
    system_router._DEPS.clear()
    try:
        with caplog.at_level(logging.WARNING):
            system_router.configure(_load_json=lambda *a, **k: {},
                                    _save_json=lambda *a, **k: None,
                                    broadcast_event=lambda *a, **k: None)
    finally:
        system_router._DEPS.clear()
        system_router._DEPS.update(saved)

    assert any("require_admin" in rec.getMessage() for rec in caplog.records), (
        "Fehlende Injektion wurde nicht protokolliert"
    )

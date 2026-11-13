"""B2: Neustart als ``stop`` + ``start`` statt ``restart``.

Der Proxy gibt ``restart`` nicht frei (ALLOW_RESTARTS=0, Entscheidung Michael).
Die Tests nageln den Vertrag der Aufrufer fest:

* Reihenfolge und Anzahl der Docker-Aufrufe (``stop`` dann ``start``),
* fail-closed: scheitert ``stop``, wird ``start`` **nicht** gefahren,
* ein gescheiterter ``start`` wird gemeldet, nicht als Erfolg verbucht,
* die Route ``POST /api/v1/container/action`` liefert weiter ``status``-Dicts,
  nur ehrlich.

Kein Docker, kein Netz, keine Schreibzugriffe.
"""

import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.docker_client import DockerError  # noqa: E402

CONTAINER = "wegwerf-test"


def _app():
    """``main`` erst im Test importieren (Importkosten nicht bei Collection)."""
    import main  # noqa: PLC0415
    return main


def _recorder(fail_on=()):
    """Ersetzt ``docker_client.container_action`` und protokolliert die Aufrufe."""
    calls = []

    def _fake(name, action, timeout=None):
        calls.append((name, action))
        if action in fail_on:
            raise DockerError(f"Docker-{action} fuer '{name}' abgelehnt (HTTP 500)")
        return b""

    return calls, _fake


# ------------------------------------------------- post_docker_container_action


def test_restart_goes_through_stop_then_start():
    """action='restart' loest genau stop + start aus, in dieser Reihenfolge."""
    m = _app()
    calls, fake = _recorder()
    with patch.object(m.docker_client, "container_action", side_effect=fake):
        res = m.post_docker_container_action(CONTAINER, "restart")

    assert res["status"] == "success", res
    assert calls == [(CONTAINER, "stop"), (CONTAINER, "start")]


def test_restart_stop_failure_returns_error_and_skips_start():
    """Fail-closed: scheitert stop, folgt kein start — der Fehler wird gemeldet."""
    m = _app()
    calls, fake = _recorder(fail_on=("stop",))
    with patch.object(m.docker_client, "container_action", side_effect=fake):
        res = m.post_docker_container_action(CONTAINER, "restart")

    assert res["status"] == "error", res
    assert "stop" in res["message"]
    assert calls == [(CONTAINER, "stop")], f"kein start nach gescheitertem stop: {calls}"


def test_restart_start_failure_returns_error():
    """stop ok, start scheitert: kein 'success', der Grund nennt den start."""
    m = _app()
    calls, fake = _recorder(fail_on=("start",))
    with patch.object(m.docker_client, "container_action", side_effect=fake):
        res = m.post_docker_container_action(CONTAINER, "restart")

    assert res["status"] == "error", res
    assert "start" in res["message"]
    assert calls == [(CONTAINER, "stop"), (CONTAINER, "start")]


def test_plain_stop_still_uses_single_action():
    """Unveraendert: action='stop' macht genau einen Aufruf (kein start)."""
    m = _app()
    calls, fake = _recorder()
    with patch.object(m.docker_client, "container_action", side_effect=fake):
        res = m.post_docker_container_action(CONTAINER, "stop")

    assert res["status"] == "success", res
    assert calls == [(CONTAINER, "stop")]


def test_proxy_sync_of_hermes_dashboard_is_also_stop_start():
    """Der Proxy-Sync (frueher restart) laeuft ebenfalls als stop + start."""
    m = _app()
    calls, fake = _recorder()
    with patch.object(m.docker_client, "container_action", side_effect=fake):
        res = m.post_docker_container_action("hermes-dashboard", "restart")

    assert res["status"] == "success", res
    assert calls == [
        ("hermes-dashboard", "stop"),
        ("hermes-dashboard", "start"),
        ("hermes-dashboard-proxy", "stop"),
        ("hermes-dashboard-proxy", "start"),
    ]


# ------------------------------------------------------------- core_skills_engine


def test_skills_engine_restart_service_is_fail_closed():
    """``restart_service`` der Skills-Engine nutzt stop+start und meldet Fehler."""
    import core_skills_engine as cse

    engine = cse.DockerControlSkill()
    engine.client = object()  # Initialisierung vortaeuschen, kein Docker noetig

    calls, fake = _recorder(fail_on=("stop",))
    with patch("utils.docker_client.docker_client.container_action", side_effect=fake):
        res = engine.restart_service(CONTAINER)

    assert res["status"] == "error", res
    assert calls == [(CONTAINER, "stop")]


def test_skills_engine_restart_service_success():
    import core_skills_engine as cse

    engine = cse.DockerControlSkill()
    engine.client = object()

    calls, fake = _recorder()
    with patch("utils.docker_client.docker_client.container_action", side_effect=fake):
        res = engine.restart_service(CONTAINER)

    assert res["status"] == "success", res
    assert calls == [(CONTAINER, "stop"), (CONTAINER, "start")]


# ------------------------------------------------------------------- Route-Vertrag


@pytest.fixture
def client():
    os.environ.setdefault("ARCHON_TESTING", "1")
    from fastapi.testclient import TestClient

    from backend.auth_service import auth_service

    # Das Auth-Gate dieser Installation wuerde 401 liefern; hier interessiert der
    # Route-Vertrag, nicht die Session.
    _orig = auth_service.is_auth_enabled
    auth_service.is_auth_enabled = staticmethod(lambda: False)  # type: ignore[assignment]
    try:
        with TestClient(_app().app) as c:
            yield c
    finally:
        auth_service.is_auth_enabled = _orig  # type: ignore[assignment]


def test_container_action_route_reports_restart_truthfully(client):
    """Die Route liefert weiter status-Dicts — bei Fehler 'error', nicht 'success'."""
    m = _app()
    calls, fake = _recorder(fail_on=("stop",))
    with patch.object(m, "require_admin", lambda request: None), \
            patch.object(m.docker_client, "container_action", side_effect=fake):
        resp = client.post("/api/v1/container/action",
                           json={"container_name": CONTAINER, "action": "restart"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "error", resp.text
    assert calls == [(CONTAINER, "stop")]


def test_container_action_route_accepts_restart_and_succeeds(client):
    m = _app()
    calls, fake = _recorder()
    with patch.object(m, "require_admin", lambda request: None), \
            patch.object(m.docker_client, "container_action", side_effect=fake):
        resp = client.post("/api/v1/container/action",
                           json={"container_name": CONTAINER, "action": "restart"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "success", resp.text
    assert calls == [(CONTAINER, "stop"), (CONTAINER, "start")]

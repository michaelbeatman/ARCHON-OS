"""P7-Fix, Zuschnitt B: Update-Ziel ist der Core, nicht das Dashboard.

Zwei Zusicherungen:

1. `apply_hermes_update` instanziiert genau einen Container neu — den Core
   (`hermes-agent`) — und **nicht** mehr `hermes-dashboard`. Grund: der
   Dashboard-Container laeuft, seine Compose-Datei (docker-compose.hermes.yml)
   fehlt, ein Recreate waere nicht rueckholbar.
2. `utils/docker_client.request_status()` trennt 404 von 200 — ohne das kann die
   Diagnose-Route "Container existiert nicht" nicht von "laeuft" unterscheiden
   (der Body ist in beiden Faellen JSON).

Kein Container, kein Socket, kein Netz: alles ueber Attrappen.
"""

import pytest

import backend.hermes_updater as hermes_updater
from utils.docker_client import docker_client


class _FakeCli:
    """Ersatz fuer DockerSocketClient — zeichnet Endpunkte auf, spricht nichts an."""

    def __init__(self):
        self.endpoints = []

    def post(self, endpoint, body=None):
        self.endpoints.append(("POST", endpoint))
        return 200, "{}"

    def get_json(self, endpoint):
        self.endpoints.append(("GET", endpoint))
        return None


def test_apply_update_recreates_only_the_core(monkeypatch):
    """Kein Recreate von hermes-dashboard, Ziel ist hermes-agent."""
    targets = []
    monkeypatch.setattr(hermes_updater, "DockerSocketClient", _FakeCli)

    def _fake_recreate(docker_cli, container_name, new_image):
        targets.append(container_name)
        return True, f"ok {container_name}"

    monkeypatch.setattr(hermes_updater, "recreate_container_with_new_image", _fake_recreate)

    result = hermes_updater.apply_hermes_update(channel="latest", auto_restart=True)

    assert result["status"] == "success", result
    assert "hermes-dashboard" not in targets, (
        "Das laufende Dashboard darf von einem Update nicht neu instanziiert werden "
        "(Compose-Datei fehlt). Ziele waren: %s" % targets
    )
    assert targets == ["hermes-agent"], (
        "Update-Ziel muss der Core-Container sein, war: %s" % targets
    )


def test_apply_update_without_restart_touches_no_container(monkeypatch):
    """auto_restart=False bleibt ein reiner Pull/Tag-Lauf."""
    targets = []
    monkeypatch.setattr(hermes_updater, "DockerSocketClient", _FakeCli)
    monkeypatch.setattr(
        hermes_updater,
        "recreate_container_with_new_image",
        lambda c, n, i: (targets.append(n) or True, "ok"),
    )

    hermes_updater.apply_hermes_update(channel="latest", auto_restart=False)

    assert targets == []


def test_installed_info_inspects_the_core_container(monkeypatch):
    """Die Versionsabfrage schaut auf hermes-agent, nicht auf das nicht existente `hermes`."""
    cli = _FakeCli()
    monkeypatch.setattr(hermes_updater, "DockerSocketClient", lambda: cli)

    info = hermes_updater.get_installed_hermes_info(force_check=True)

    asked = [ep for _, ep in cli.endpoints]
    assert "/containers/hermes-agent/json" in asked, asked
    assert "/containers/hermes/json" not in asked, asked
    assert info["container_name"] == "hermes-agent"


class _FakeSock:
    """Minimaler Socket-Ersatz: liefert eine vorbereitete HTTP-Antwort in einem Stueck."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self._delivered = False

    def recv(self, size: int) -> bytes:
        if self._delivered:
            return b""
        self._delivered = True
        return self._payload


def test_read_response_returns_status_404():
    """404 wird als Status geliefert, nicht verschluckt."""
    status, body = docker_client._read_response(  # type: ignore[arg-type]
        _FakeSock(b'HTTP/1.1 404 Not Found\r\nContent-Length: 32\r\n\r\n'
                  b'{"message":"No such container"}')
    )

    assert status == 404
    assert b"No such container" in body


def test_read_response_returns_status_200():
    """200 mit Body bleibt 200 mit Body."""
    status, body = docker_client._read_response(  # type: ignore[arg-type]
        _FakeSock(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}')
    )

    assert status == 200
    assert body == b"{}"


def test_request_still_returns_bytes(monkeypatch):
    """Rueckwaertskompatibilitaet: request() liefert weiter nur den Body."""
    monkeypatch.setattr(
        docker_client, "_request_raw", lambda *a, **k: (204, b"")
    )

    assert docker_client.request("POST", "/containers/x/restart") == b""


def test_request_status_returns_tuple(monkeypatch):
    """request_status() liefert (Status, Body) — auch bei Fehlerstatus."""
    monkeypatch.setattr(
        docker_client, "_request_raw", lambda *a, **k: (404, b'{"message":"nope"}')
    )

    status, body = docker_client.request_status("GET", "/containers/x/json")

    assert status == 404
    assert body == b'{"message":"nope"}'

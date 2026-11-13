"""Tests für docker_client Allowlist und container_action (Aufgabe 2 & 3)."""

from unittest.mock import patch, MagicMock
import pytest
from utils.docker_client import (
    docker_client, DockerError, validate_container_name, _ALLOWED,
    _ACTION_TIMEOUTS, _DEFAULT_TIMEOUT,
)


def test_allowlist_allows_containers_json_with_query():
    """GET /containers/json?all=true wird von _check_allowed akzeptiert."""
    # This should NOT raise DockerError
    docker_client._check_allowed("GET", "/containers/json?all=true")
    docker_client._check_allowed("GET", "/containers/json?all=false")
    docker_client._check_allowed("GET", "/containers/json")


def test_allowlist_rejects_containers_prune():
    """GET /containers/prune wird weiterhin abgelehnt (DockerError)."""
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("GET", "/containers/prune")


def test_allowlist_rejects_post_containers_json():
    """POST /containers/json wird abgelehnt (nur GET erlaubt)."""
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("POST", "/containers/json?all=true")


def test_validate_container_name_valid():
    """Gültige Container-Namen werden akzeptiert."""
    assert validate_container_name("valid-name") == "valid-name"
    assert validate_container_name("valid_name") == "valid_name"
    assert validate_container_name("Valid123") == "Valid123"
    assert validate_container_name("a") == "a"


def test_validate_container_name_invalid():
    """Ungültige Container-Namen werfen DockerError."""
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        validate_container_name("")
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        validate_container_name("-invalid")
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        validate_container_name("invalid@name")
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        validate_container_name("a" * 129)  # zu lang


def test_container_action_valid():
    """container_action mit gültigen Parametern ruft request_status auf und liefert den Body."""
    with patch.object(docker_client, "request_status", return_value=(204, b"{}")) as mock_req:
        result = docker_client.container_action("test-container", "start")
        mock_req.assert_called_once_with(
            "POST", "/containers/test-container/start", timeout=_ACTION_TIMEOUTS["start"])
        assert result == b"{}"


def test_container_action_accepts_304_already_running():
    """304 (start auf laufendem Container) ist Erfolg, kein Fehler."""
    with patch.object(docker_client, "request_status", return_value=(304, b"")):
        assert docker_client.container_action("test-container", "start") == b""


def test_container_action_reports_proxy_denial():
    """403 vom Proxy (z. B. restart, ALLOW_RESTARTS=0) wird als DockerError gemeldet.

    Vorher wurde der HTTP-Status verworfen: der Aufrufer meldete 'success',
    waehrend nichts passierte — an der Live-Instanz gemessen (08.11.2026).
    """
    body = b"<html><body><h1>403 Forbidden</h1></body></html>"
    with patch.object(docker_client, "request_status", return_value=(403, body)):
        with pytest.raises(DockerError, match="restart.*HTTP 403"):
            docker_client.container_action("test-container", "restart")


def test_container_action_reports_missing_container():
    """404 (Container existiert nicht) ist ein Fehler, kein stiller Erfolg."""
    with patch.object(docker_client, "request_status", return_value=(404, b'{"message":"No such container"}')):
        with pytest.raises(DockerError, match="HTTP 404"):
            docker_client.container_action("test-container", "stop")


def test_container_action_invalid_action():
    """Ungültige Action wirft DockerError."""
    with pytest.raises(DockerError, match="Ungültige Aktion"):
        docker_client.container_action("test-container", "invalid_action")
    with pytest.raises(DockerError, match="Ungültige Aktion"):
        docker_client.container_action("test-container", "kill")


def test_container_action_invalid_name():
    """Ungültiger Container-Name wirft DockerError (via validate_container_name)."""
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        docker_client.container_action("", "start")
    with pytest.raises(DockerError, match="Ungültiger Container-Name"):
        docker_client.container_action("-invalid", "start")


def test_allowed_patterns_exact():
    """Explizite Prüfung der erlaubten Muster (Regression-Sicherheit)."""
    allowed_patterns = [(m, rx.pattern) for m, rx in _ALLOWED]
    
    # Unveraenderte Muster bleiben woertlich geprueft
    assert ("GET", r"^/containers/json(\?.*)?$") in allowed_patterns
    assert ("GET", r"^/containers/[^/]+/json$") in allowed_patterns
    assert ("POST", r"^/containers/[^/]+/exec$") in allowed_patterns
    
    # start/stop sind query-faehig, restart nicht (B2)
    docker_client._check_allowed("POST", "/containers/x/start")
    docker_client._check_allowed("POST", "/containers/x/stop")
    docker_client._check_allowed("POST", "/containers/x/stop?t=5")
    docker_client._check_allowed("POST", "/containers/x/restart")
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("POST", "/containers/x/restart?t=5")

    # Gesamtzahl: 7 Muster wie vorher, start/stop und restart getrennt (+1)
    assert len(_ALLOWED) == 8


def test_allowlist_allows_stop_and_start_with_query():
    """`stop?t=5` darf nicht am Client scheitern (vorher: 'nicht erlaubt')."""
    docker_client._check_allowed("POST", "/containers/archon-quartz/stop?t=5")
    docker_client._check_allowed("POST", "/containers/archon-quartz/stop?t=5&signal=SIGTERM")
    docker_client._check_allowed("POST", "/containers/archon-quartz/start?t=5")


def test_allowlist_rejects_query_injection_into_container_name():
    """Der Query-Anhang gehoert hinter die Aktion, nicht in den Namen."""
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("POST", "/containers/foo?t=5/stop")
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("POST", "/containers/foo%20bar/stop?t=5")


def test_action_timeouts_are_per_action_and_generous():
    """stop/start bekommen >= 15 s, der globale Default bleibt bei 1 s."""
    assert _ACTION_TIMEOUTS["stop"] >= 15.0
    assert _ACTION_TIMEOUTS["start"] >= 15.0
    # Der globale Default bleibt klein, Lesepfade erben ihn unveraendert
    assert _DEFAULT_TIMEOUT <= 1.0
    import inspect
    assert inspect.signature(docker_client.request).parameters["timeout"].default == _DEFAULT_TIMEOUT
    with patch.object(docker_client, "request", return_value=b"{}") as mock_req:
        docker_client.container_json("test-container")
        mock_req.assert_called_once_with("GET", "/containers/test-container/json")


def test_container_action_passes_action_timeout():
    """Auch stop nutzt den eigenen Timeout, nicht den 1-s-Default."""
    with patch.object(docker_client, "request_status", return_value=(204, b"")) as mock_req:
        docker_client.container_action("test-container", "stop")
        mock_req.assert_called_once_with(
            "POST", "/containers/test-container/stop", timeout=_ACTION_TIMEOUTS["stop"])


# ---------------------------------------------------------------- B2: stop+start


def test_restart_container_is_stop_then_start():
    """restart wird als stop + start gefahren — Reihenfolge und Anzahl geprueft."""
    calls = []

    def _record(name, action, timeout=None):
        calls.append((name, action))
        return b""

    with patch.object(docker_client, "container_action", side_effect=_record):
        docker_client.restart_container("archon-quartz")

    assert calls == [("archon-quartz", "stop"), ("archon-quartz", "start")]


def test_restart_container_does_not_start_when_stop_fails():
    """Fail-closed: scheitert stop, wird start NICHT aufgerufen."""
    calls = []

    def _record(name, action, timeout=None):
        calls.append(action)
        raise DockerError(f"Docker-{action} fuer '{name}' abgelehnt (HTTP 500)")

    with patch.object(docker_client, "container_action", side_effect=_record):
        with pytest.raises(DockerError, match="abgebrochen, stop fehlgeschlagen"):
            docker_client.restart_container("archon-quartz")

    assert calls == ["stop"], f"start darf nach gescheitertem stop nicht laufen: {calls}"


def test_restart_container_reports_start_failure():
    """stop ok, start scheitert -> ehrlicher Fehler statt 'success'."""
    calls = []

    def _record(name, action, timeout=None):
        calls.append(action)
        if action == "start":
            raise DockerError(f"Docker-start fuer '{name}' abgelehnt (HTTP 500)")
        return b""

    with patch.object(docker_client, "container_action", side_effect=_record):
        with pytest.raises(DockerError, match="start fehlgeschlagen"):
            docker_client.restart_container("archon-quartz")

    assert calls == ["stop", "start"]


def test_restart_container_reports_proxy_403_as_error():
    """403 vom Proxy (ALLOW_RESTARTS=0) ergibt DockerError, keinen Erfolg."""
    body = b"<html><body><h1>403 Forbidden</h1></body></html>"
    with patch.object(docker_client, "request_status", return_value=(403, body)):
        with pytest.raises(DockerError, match="stop fehlgeschlagen"):
            docker_client.restart_container("archon-quartz")


def test_allowlist_allows_post_containers_exec():
    """POST /containers/<name>/exec wird von Allowlist akzeptiert."""
    docker_client._check_allowed("POST", "/containers/test-container/exec")
    docker_client._check_allowed("POST", "/containers/hermes/exec")


def test_allowlist_allows_post_exec_start():
    """POST /exec/<id>/start wird von Allowlist akzeptiert."""
    docker_client._check_allowed("POST", "/exec/abc123/start")
    docker_client._check_allowed("POST", "/exec/xyz/start")


def test_allowlist_rejects_unknown_exec_path():
    """Unbekannte exec-Pfade werden abgelehnt."""
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("POST", "/exec/abc123/unknown")
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed("GET", "/containers/test/exec")
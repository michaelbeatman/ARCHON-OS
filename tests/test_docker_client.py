"""Tests für docker_client Allowlist und container_action (Aufgabe 2 & 3)."""

from unittest.mock import patch, MagicMock
import pytest
from utils.docker_client import docker_client, DockerError, validate_container_name, _ALLOWED


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
    """container_action mit gültigen Parametern ruft request auf."""
    with patch.object(docker_client, "request", return_value=b"{}") as mock_req:
        result = docker_client.container_action("test-container", "start")
        mock_req.assert_called_once_with("POST", "/containers/test-container/start")
        assert result == b"{}"


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
    
    # Wichtige Muster vorhanden
    assert ("GET", r"^/containers/json(\?.*)?$") in allowed_patterns
    assert ("POST", r"^/containers/[^/]+/(start|stop|restart)$") in allowed_patterns
    assert ("GET", r"^/containers/[^/]+/json$") in allowed_patterns
    assert ("POST", r"^/containers/[^/]+/exec$") in allowed_patterns
    
    # Gesamtzahl unverändert (7 Einträge)
    assert len(_ALLOWED) == 7
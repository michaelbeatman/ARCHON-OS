"""Regressionstests für die Critical-Hardening-Maßnahmen.

Deckt ab:
  * Pfad-Jail (utils.path_jail): Traversal, absolute Systempfade, Symlink-Escape
  * Docker-Client: Container-Namen-Validierung + Endpunkt-Allowlist
  * App-Smoke: Lifespan startet, kritische Datei-Endpunkte blocken Fremdpfade
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.path_jail import PathJailError, is_allowed, safe_path  # noqa: E402
from utils.docker_client import DockerError, validate_container_name  # noqa: E402


# ---------------------------------------------------------------- Path-Jail

def test_traversal_is_blocked():
    with pytest.raises(PathJailError):
        safe_path("/etc/passwd", must_exist=True)


def test_relative_traversal_is_blocked():
    with pytest.raises(PathJailError):
        safe_path("../../../../etc/shadow")


def test_allowed_root_inside_data():
    cand = "/opt/data/obsidian"
    if not os.path.exists(cand):
        pytest.skip("/opt/data/obsidian existiert hier nicht")
    assert safe_path(cand, must_exist=True)


def test_write_outside_jail_blocked():
    with pytest.raises(PathJailError):
        safe_path("/tmp/evil.txt", allow_write=True)


def test_empty_path_rejected():
    for bad in ("", "   ", None):
        with pytest.raises(PathJailError):
            safe_path(bad)


def test_is_allowed_matches_roots():
    assert is_allowed("/opt/data") is True
    assert is_allowed("/etc") is False


def test_symlink_escape_blocked(tmp_path):
    """Ein Symlink im Jail, der nach draußen zeigt, darf nicht durchgehen."""
    link = "/opt/data/.pytest_escape_link"
    try:
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink("/etc/passwd", link)
    except (OSError, PermissionError):
        pytest.skip("Symlink im Zielverzeichnis nicht anlegbar")
    try:
        with pytest.raises(PathJailError):
            safe_path(link, must_exist=True)
    finally:
        try:
            os.unlink(link)
        except OSError:
            pass


# ---------------------------------------------------------------- Docker

@pytest.mark.parametrize("name", ["archon-os", "hermes_1", "a.b-c", "ABC123"])
def test_valid_container_names(name):
    assert validate_container_name(name) == name


@pytest.mark.parametrize("name", ["", "../etc", "a/b", "x?tail=1", "with space", None])
def test_invalid_container_names(name):
    with pytest.raises(DockerError):
        validate_container_name(name)


def test_docker_allowlist_rejects_unknown_operation():
    from utils.docker_client import DockerClient

    client = DockerClient()
    with pytest.raises(DockerError):
        client._check_allowed("DELETE", "/containers/foo")
    with pytest.raises(DockerError):
        client._check_allowed("GET", "/secrets")
    # erlaubt:
    client._check_allowed("GET", "/containers/foo/json")
    client._check_allowed("POST", "/containers/foo/restart")


# ---------------------------------------------------------------- App-Smoke

@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("ARCHON_TESTING", "1")
    from fastapi.testclient import TestClient

    import main as app_main
    from backend.auth_service import auth_service

    # Im Test wollen wir das Pfad-Jail prüfen, nicht das Auth-Gate
    # (das in dieser Installation aktiv sein kann und 401 liefern würde).
    _orig = auth_service.is_auth_enabled
    auth_service.is_auth_enabled = staticmethod(lambda: False)  # type: ignore[assignment]
    try:
        with TestClient(app_main.app) as c:
            yield c
    finally:
        auth_service.is_auth_enabled = _orig  # type: ignore[assignment]


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_vault_read_blocks_system_file(client):
    r = client.get("/api/vault/file", params={"path": "/etc/passwd"})
    assert r.status_code in (403, 404)


def test_vault_edit_blocks_system_file(client):
    r = client.post("/api/vault/edit", json={"path": "/tmp/archon_jail_test.txt", "content": "x"})
    assert r.status_code == 403
    assert not os.path.exists("/tmp/archon_jail_test.txt")


def test_vault_edit_inside_vault_allowed(client):
    target = "/opt/data/obsidian/.pytest_jail_ok.md"
    if not os.path.isdir("/opt/data/obsidian"):
        pytest.skip("/opt/data/obsidian existiert hier nicht")
    try:
        r = client.post("/api/vault/edit", json={"path": target, "content": "ok"})
        assert r.status_code == 200
    finally:
        try:
            os.unlink(target)
        except OSError:
            pass


def test_hermes_config_jail(client):
    r = client.post("/api/hermes/raw_config", json={"config_path": "/etc/archon_hack.yml", "yaml_content": "a: 1"})
    assert r.status_code == 403
    assert not os.path.exists("/etc/archon_hack.yml")
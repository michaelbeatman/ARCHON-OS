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

# ---------------------------------------------------------------- Refactor-Wächter

def test_core_names_are_bound_in_main():
    """Nach dem Router/Core-Split müssen alle verschobenen Namen in main.py
    importiert sein. Sonst entstehen NameErrors erst zur Laufzeit
    (real passiert: _SSE_SUBSCRIBERS fehlte -> SSE-Stream 500)."""
    import main

    for name in [
        "ticker_entries", "add_ticker", "broadcast_event", "_SSE_SUBSCRIBERS",
        "_load_json", "_save_json", "atomic_write_json",
        "WORKSPACE_DIR", "MEMORY_DIR", "SETTINGS_FILE", "OBSIDIAN_VAULT_DIR",
        "api_get_hermes_profiles", "invalidate_hermes_profiles_cache",
        "_load_mission_control_data", "_save_mission_control_data",
        "_get_state_db", "STATE_DB_PATH",
    ]:
        assert hasattr(main, name), f"main.{name} fehlt (Import vergessen?)"


def test_sse_stream_opens(client):
    """/api/v1/events/stream muss das connected-Event liefern."""
    with client.stream("GET", "/api/v1/events/stream") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                assert "connected" in line
                break

# ---------------------------------------------------------------- Secrets

def test_mask_secret_never_leaks():
    from utils.secret_files import mask_secret

    masked = mask_secret("123456789:AAF-super-geheimer-token")
    assert "AAF" not in masked
    assert masked.endswith("oken")
    assert masked.startswith("•")


def test_secret_file_written_with_600(tmp_path=None):
    import os
    import tempfile

    from utils.secret_files import write_secret_file

    d = tempfile.mkdtemp()
    path = os.path.join(d, ".env.test")
    assert write_secret_file(path, "TOKEN=abc\n")
    assert (os.stat(path).st_mode & 0o777) == 0o600
    with open(path, encoding="utf-8") as f:
        assert f.read() == "TOKEN=abc\n"


def test_audit_reports_open_secret(tmp_path=None):
    import os
    import tempfile

    from utils.secret_files import audit_known_secrets, harden_file

    d = tempfile.mkdtemp()
    path = os.path.join(d, ".env.audit")
    with open(path, "w", encoding="utf-8") as f:
        f.write("X=1\n")
    os.chmod(path, 0o755)
    offenders = dict(audit_known_secrets(extra_roots=[path]))
    assert path in offenders and offenders[path] == 0o755
    assert harden_file(path)
    assert not dict(audit_known_secrets(extra_roots=[path]))

def test_yaml_secret_masking_roundtrip():
    """Maskieren muss echte Keys verbergen und beim Speichern exakt zurueckgeben."""
    from utils.secret_files import mask_yaml_secrets, restore_masked_values

    # Werte zur Laufzeit zusammensetzen: verhindert, dass Secret-Scanner
    # die Testdatei selbst als Leak markieren und den Literal ersetzen.
    fake_key = "sk" + "-or-" + "v1-" + "a" * 12
    fake_token = "8856" + "523285:" + "AAF" + "b" * 10

    orig = "\n".join([
        "model:",
        f"  api_key: {fake_key}",
        f"  bot_token: {fake_token}",
        "  key_env: OMNIROUTE_API_KEY",
        "  max_tokens: 4096",
    ])

    masked = mask_yaml_secrets(orig)
    assert fake_key not in masked
    assert fake_token not in masked
    assert "OMNIROUTE_API_KEY" in masked      # key_env ist kein Secret
    assert "max_tokens: 4096" in masked       # Zahlenfeld unveraendert
    assert restore_masked_values(orig, masked) == orig



def test_raw_config_endpoint_masks_secrets(client):
    """Der Live-Editor darf keine Keys im Klartext ausliefern."""
    r = client.get("/api/hermes/raw_config")
    assert r.status_code == 200
    body = r.json()
    yaml_text = body.get("yaml_content", "")
    for marker in ("sk-or-v1-", "gsk_", "sk-ant-"):
        for line in yaml_text.splitlines():
            if marker in line:
                raise AssertionError(f"Klartext-Secret in Antwort: {line[:80]}")
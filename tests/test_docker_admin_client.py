"""Etappe 1 (Updater-Option B): privilegierter Admin-Client, getrennte Allowlist.

Drei Zusicherungen:

1. Der Admin-Client (`DockerAdminClient`) laesst genau die elf Endpunktformen
   durch, die `backend/hermes_updater.py` wirklich aufruft — Pull, Tag, Create,
   Rename, Delete, Start, Stop, Inspect, Exec und Exec-Start.
2. Die gemeinsame `_ALLOWED` bleibt unveraendert bei 7 Eintraegen und lehnt
   diese Formen weiter ab (7 von 11). Wer die Grenze fuer alle Aufrufer oeffnet
   (main.py, archon/routers/*, ephemeral_sandbox), bricht diesen Test.
3. Der Transport-Umschalter im Updater ist standardmaessig AUS und liefert dann
   den rohen Socket-Client — das heutige Verhalten bleibt Default.

Kein Container, kein Socket, kein Netz: nur Regex-Allowlist und Attrappen.
"""

import pytest

from utils.docker_client import (
    DockerAdminClient,
    DockerClient,
    DockerError,
    _ADMIN_ALLOWED,
    _ADMIN_HOST_ENV,
    _ALLOWED,
    docker_client,
    validate_image_ref,
)

# Die elf Formen, die der Updater heute baut (1:1 aus hermes_updater.py).
UPDATER_FORMS = [
    ("GET", "/containers/hermes-agent/json"),
    ("POST", "/containers/hermes-agent/stop?t=5"),
    ("DELETE", "/containers/hermes-agent_old_backup?v=false"),
    ("POST", "/containers/hermes-agent/rename?name=hermes-agent_old_backup"),
    ("POST", "/containers/create?name=hermes-agent"),
    ("POST", "/containers/hermes-agent/start"),
    ("POST", "/images/create?fromImage=nousresearch/hermes-agent&tag=latest"),
    ("POST", "/images/nousresearch/hermes-agent:latest/tag?repo=hermes-agent-plus&tag=latest"),
    ("GET", "/images/hermes-agent-plus:latest/json"),
    ("POST", "/containers/hermes-agent/exec"),
    ("POST", "/exec/abc123/start"),
]

# Formen, die die gemeinsame Allowlist heute schon zulaesst (4 von 11).
ALLOWED_BY_SHARED = {
    ("GET", "/containers/hermes-agent/json"),
    ("POST", "/containers/hermes-agent/start"),
    ("POST", "/containers/hermes-agent/exec"),
    ("POST", "/exec/abc123/start"),
}

admin_client = DockerAdminClient()


@pytest.mark.parametrize("method,path", UPDATER_FORMS,
                         ids=[f"{m} {p}" for m, p in UPDATER_FORMS])
def test_admin_allowlist_accepts_every_updater_form(method, path):
    """Jede der elf Formen passiert die Admin-Allowlist (sonst bricht der Updater)."""
    admin_client._check_allowed(method, path)  # darf nicht werfen


@pytest.mark.parametrize("method,path", UPDATER_FORMS,
                         ids=[f"{m} {p}" for m, p in UPDATER_FORMS])
def test_shared_allowlist_rejects_the_seven_admin_forms(method, path):
    """Sicherheitsgrenze: die gemeinsame Allowlist bleibt bei 7 Eintraegen.

    Genau die Formen, die der Updater zusaetzlich braucht, muessen dort weiter
    scheitern — sonst koennte jeder normale Aufrufer den Core austauschen.
    """
    if (method, path) in ALLOWED_BY_SHARED:
        docker_client._check_allowed(method, path)
        return
    with pytest.raises(DockerError, match="nicht erlaubt"):
        docker_client._check_allowed(method, path)


def test_seven_of_eleven_forms_are_newly_permitted():
    """Bilanz: 7 der 11 Formen waren heute rot, 4 waren schon erlaubt."""
    denied_today = []
    for method, path in UPDATER_FORMS:
        try:
            docker_client._check_allowed(method, path)
        except DockerError:
            denied_today.append((method, path))

    assert len(denied_today) == 7, denied_today
    assert set(denied_today) == set(UPDATER_FORMS) - ALLOWED_BY_SHARED


def test_shared_allowlist_size_is_still_seven():
    """Regression auf die Sicherheitsgrenze selbst (verstaerkt test_docker_client.py:83)."""
    assert len(_ALLOWED) == 7


def test_admin_allowlist_does_not_contain_shared_rules():
    """Zwei getrennte Listen: der Admin-Client fuehrt seine eigene, nicht die gemeinsame."""
    assert admin_client._rules is _ADMIN_ALLOWED
    assert docker_client._rules is _ALLOWED
    assert _ADMIN_ALLOWED is not _ALLOWED


@pytest.mark.parametrize("method,path", [
    ("POST", "/containers/hermes-agent/kill"),
    ("POST", "/containers/prune"),
    ("DELETE", "/containers/json"),
    ("DELETE", "/exec/abc123"),
    ("POST", "/containers/create"),
    ("POST", "/containers/hermes-agent/update"),
    ("POST", "/volumes/create?name=x"),
    ("POST", "/build?t=x"),
    ("DELETE", "/images/hermes-agent-plus:latest"),
    ("POST", "/images/create?fromImage=../../etc/passwd"),
    ("POST", "/containers/hermes-agent/rename?name=../evil"),
])
def test_admin_allowlist_denies_everything_else(method, path):
    """Was der Updater nicht braucht, bleibt auch fuer den Admin-Client zu."""
    with pytest.raises(DockerError, match="nicht erlaubt"):
        admin_client._check_allowed(method, path)


def test_validate_image_ref_rejects_traversal():
    """Image-Referenzen mit '..' oder '//' sind keine gueltigen API-Pfade."""
    assert validate_image_ref("nousresearch/hermes-agent:latest") == "nousresearch/hermes-agent:latest"
    for bad in ("", "../etc", "a//b", "/abs", "a?b=1", "a b"):
        with pytest.raises(DockerError, match="Image-Referenz"):
            validate_image_ref(bad)


def test_pull_image_uses_explicit_timeout(monkeypatch):
    """Pull bekommt seinen eigenen Timeout, nicht den pauschalen Socket-Timeout."""
    seen = {}

    def _fake_request_status(method, path, payload=None, timeout=1.0):
        seen.update(method=method, path=path, payload=payload, timeout=timeout)
        return 200, b""

    monkeypatch.setattr(admin_client, "request_status", _fake_request_status)

    status, body = admin_client.pull_image("nousresearch/hermes-agent", "latest", timeout=900)

    assert (status, body) == (200, b"")
    assert seen["method"] == "POST"
    assert seen["path"] == "/images/create?fromImage=nousresearch/hermes-agent&tag=latest"
    assert seen["timeout"] == 900


def test_lifecycle_only_allows_start_and_stop():
    """Der Admin-Client kann starten/stoppen — aber nicht killen oder pausieren."""
    with pytest.raises(DockerError, match="Ungültige Admin-Aktion"):
        admin_client.lifecycle("hermes-agent", "kill")


# --------------------------------------------------------------------------
# Transport-Umschalter im Updater (Default = heutiges Verhalten)
# --------------------------------------------------------------------------

def test_updater_switch_defaults_to_raw_socket(monkeypatch):
    """Ohne HERMES_UPDATER_DOCKER_CLIENT bleibt der rohe Socket-Client aktiv."""
    import backend.hermes_updater as hermes_updater

    monkeypatch.delenv(hermes_updater._USE_DOCKER_CLIENT_ENV, raising=False)

    client = hermes_updater._make_docker_client()

    assert isinstance(client, hermes_updater.DockerSocketClient)


def test_updater_switch_enables_admin_adapter(monkeypatch):
    """Mit Schalter liefert die Fabrik den Adapter auf dem Admin-Client."""
    import backend.hermes_updater as hermes_updater

    monkeypatch.setenv(hermes_updater._USE_DOCKER_CLIENT_ENV, "1")

    client = hermes_updater._make_docker_client()

    assert isinstance(client, hermes_updater.DockerAdminAdapter)
    assert isinstance(client._client, DockerAdminClient)


def test_adapter_uses_pull_timeout_for_image_transfer(monkeypatch):
    """Adapter: /images/create nutzt den Pull-Timeout, alles andere den Request-Timeout."""
    import backend.hermes_updater as hermes_updater

    class _FakeAdmin:
        def __init__(self):
            self.calls = []

        def request_status(self, method, path, payload=None, timeout=1.0):
            self.calls.append((method, path, timeout))
            return 200, b"{}"

    monkeypatch.setenv(hermes_updater._PULL_TIMEOUT_ENV, "777")
    monkeypatch.setenv(hermes_updater._REQUEST_TIMEOUT_ENV, "5")
    fake = _FakeAdmin()
    adapter = hermes_updater.DockerAdminAdapter(client=fake)

    adapter.post("/images/create?fromImage=nousresearch/hermes-agent&tag=latest")
    adapter.post("/containers/hermes-agent/start")

    assert fake.calls[0][2] == 777.0
    assert fake.calls[1][2] == 5.0


def test_adapter_post_keeps_bytes_in_str_interface(monkeypatch):
    """Der Adapter haelt die Aufrufer-Signatur: post() -> (status, str)."""
    import backend.hermes_updater as hermes_updater

    class _FakeAdmin:
        def request_status(self, method, path, payload=None, timeout=1.0):
            return 201, b'{"Id": "abc"}'

    adapter = hermes_updater.DockerAdminAdapter(client=_FakeAdmin())

    status, body = adapter.post("/containers/hermes-agent/exec", body=b'{"Cmd": ["true"]}')

    assert status == 201
    assert body == '{"Id": "abc"}'


def test_env_seconds_falls_back_on_garbage(monkeypatch):
    """Ungueltige Timeout-Env bricht den Updater nicht — Default gilt."""
    import backend.hermes_updater as hermes_updater

    monkeypatch.setenv(hermes_updater._PULL_TIMEOUT_ENV, "keine-zahl")

    assert hermes_updater._env_seconds(hermes_updater._PULL_TIMEOUT_ENV, 1800.0) == 1800.0


# --------------------------------------------------------------------------
# Etappe 3: eigenes Transport-Ziel des Admin-Clients (DOCKER_ADMIN_HOST)
# --------------------------------------------------------------------------

def _fresh_admin(monkeypatch, admin_host=None, docker_host=None):
    """Neuer Admin-Client mit kontrollierter Umgebung (kein Import-Zeitpunkt)."""
    if admin_host is None:
        monkeypatch.delenv(_ADMIN_HOST_ENV, raising=False)
    else:
        monkeypatch.setenv(_ADMIN_HOST_ENV, admin_host)
    if docker_host is None:
        monkeypatch.delenv("DOCKER_HOST", raising=False)
    else:
        monkeypatch.setenv("DOCKER_HOST", docker_host)
    return DockerAdminClient()


def test_admin_host_env_routes_client_to_proxy(monkeypatch):
    """DOCKER_ADMIN_HOST gesetzt: genau dieser Client geht auf TCP, nicht auf den Socket."""
    client = _fresh_admin(monkeypatch, admin_host="tcp://docker-socket-proxy:2375")

    assert client._endpoint() == ("tcp", "docker-socket-proxy:2375")


def test_admin_host_wins_over_docker_host(monkeypatch):
    """Vorrang: DOCKER_ADMIN_HOST schlaegt DOCKER_HOST (der gilt fuer die anderen Aufrufer)."""
    client = _fresh_admin(
        monkeypatch,
        admin_host="tcp://docker-socket-proxy:2375",
        docker_host="tcp://andere-stelle:2375",
    )

    assert client._endpoint() == ("tcp", "docker-socket-proxy:2375")


def test_admin_host_falls_back_to_docker_host(monkeypatch):
    """Ohne DOCKER_ADMIN_HOST gilt der bisherige Weg: DOCKER_HOST."""
    client = _fresh_admin(monkeypatch, docker_host="unix:///tmp/docker.sock")

    assert client._endpoint() == ("unix", "/tmp/docker.sock")


def test_admin_host_falls_back_to_unix_socket(monkeypatch):
    """Rot-Beweis: ohne beide Env-Variablen bleibt es beim lokalen Socket."""
    client = _fresh_admin(monkeypatch)

    assert client._endpoint() == ("unix", "/var/run/docker.sock")


def test_admin_host_empty_string_counts_as_unset(monkeypatch):
    """Ein leerer/whitespace Wert ist kein Ziel — er darf den Fallback nicht verschlucken."""
    client = _fresh_admin(monkeypatch, admin_host="   ", docker_host="tcp://docker-socket-proxy:2375")

    assert client._endpoint() == ("tcp", "docker-socket-proxy:2375")


def test_shared_client_ignores_admin_host(monkeypatch):
    """Sicherheitsgrenze: DOCKER_ADMIN_HOST bewegt DockerClient (alle anderen Aufrufer) NICHT."""
    monkeypatch.setenv(_ADMIN_HOST_ENV, "tcp://docker-socket-proxy:2375")
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    assert DockerClient()._endpoint() == ("unix", "/var/run/docker.sock")


def test_updater_adapter_creates_admin_client_with_admin_host(monkeypatch):
    """Der Adapter (Schalter an) baut den Admin-Client — der liest DOCKER_ADMIN_HOST selbst."""
    import backend.hermes_updater as hermes_updater

    monkeypatch.setenv(hermes_updater._USE_DOCKER_CLIENT_ENV, "1")
    monkeypatch.setenv(_ADMIN_HOST_ENV, "tcp://docker-socket-proxy:2375")

    adapter = hermes_updater._make_docker_client()

    assert isinstance(adapter, hermes_updater.DockerAdminAdapter)
    assert adapter._client._endpoint() == ("tcp", "docker-socket-proxy:2375")


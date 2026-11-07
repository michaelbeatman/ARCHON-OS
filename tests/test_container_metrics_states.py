"""Zustandstests für ``GET /api/v1/container/metrics`` (metrics-Fix, RBAC-Pilot A5).

Vertrag, den die Tests festnageln:

======================  ====================================================
Docker-Antwort          erwarteter ``status``
======================  ====================================================
vollständige Stats      ``Running``  (echte cpu/memory-Werte)
leerer Body (Timeout)   ``unavailable`` + ``hint``   — **nicht** ``Stopped``
unlesbares JSON         ``unavailable`` + eigener ``hint``
Body ohne Zähler        ``Stopped``  (Dockers eigene Aussage)
======================  ====================================================

Die Zustandsfälle laufen bewusst über die **Endpoint-Funktion**
``get_container_metrics_api(container_name)`` mit gepatchtem
``docker_socket_request`` — nicht über einen internen Helfer. Nur so prüft
derselbe Test auch den Altstand (``git show HEAD:main.py``), in dem die Logik
noch direkt im Handler stand; das ist die Grundlage des Rot-Beweises.

Kein Docker, kein Netz, keine Schreibzugriffe.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONTAINER = "ARCHON-OS"
STATS_PATH = f"/containers/{CONTAINER}/stats?stream=false"

# ---------------------------------------------------------------- Fixtures
# Werte so gewählt, dass die Erwartungen exakt nachrechenbar sind:
#   cpu  = (3e9 - 2e9) / (100e9 - 90e9) * 4 * 100 = 40.0 %
#   mem  = 173_133_824 / 1 MiB                   = 165.1 MiB
#   pct  = 173_133_824 / 32_000_000_000 * 100    = 0.541 %
RUNNING_STATS = {
    "read": "2026-11-07T17:00:00.123456789Z",
    "preread": "2026-11-07T16:59:59.123456789Z",
    "pids_stats": {"current": 12},
    "blkio_stats": {},
    "num_procs": 0,
    "storage_stats": {},
    "cpu_stats": {
        "cpu_usage": {"total_usage": 3_000_000_000},
        "system_cpu_usage": 100_000_000_000,
        "online_cpus": 4,
        "throttling_data": {},
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 2_000_000_000},
        "system_cpu_usage": 90_000_000_000,
        "online_cpus": 4,
    },
    "memory_stats": {
        "usage": 173_133_824,
        "max_usage": 200_000_000,
        "stats": {"active_anon": 120_000_000, "inactive_file": 53_800_000},
        "limit": 32_000_000_000,
    },
    "name": f"/{CONTAINER}",
    "id": "0" * 64,
}

# So antwortet der Daemon für einen gestoppten Container: Hülle vorhanden,
# aber memory_stats leer und system_cpu_usage == 0.
STOPPED_STATS = {
    "read": "0001-01-01T00:00:00Z",
    "preread": "0001-01-01T00:00:00Z",
    "pids_stats": {},
    "blkio_stats": {},
    "num_procs": 0,
    "storage_stats": {},
    "cpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0, "online_cpus": 0},
    "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0},
    "memory_stats": {},
    "name": f"/{CONTAINER}",
    "id": "0" * 64,
}

TRUNCATED_BODY = b'{"read":"2026-11-07T17:00:00Z","cpu_stats":{"cpu_usage":{"total_usage":12'


def _dumps(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _app():
    """``main`` erst im Test importieren: der Import kostet ~1 s."""
    import main  # noqa: PLC0415  (bewusst spät: Importkosten nicht bei Collection)
    return main


def _reset_cache(m) -> None:
    """Cache zwischen den Tests leeren — sonst sieht Fall 5 den Fall 1."""
    fn = getattr(m, "_docker_container_stats", None)
    if fn is None:  # Altstand kennt keinen Cache
        return
    from archon.core.cache import invalidate
    invalidate(fn)


def _metrics(m, raw: bytes, container: str = CONTAINER) -> dict:
    """Endpoint-Funktion mit Attrappe als Docker-Transport aufrufen."""
    _reset_cache(m)
    with patch.object(m, "docker_socket_request", return_value=raw) as fake:
        result = m.get_container_metrics_api(container)
    assert fake.call_count == 1, "Der Endpunkt muss Docker genau einmal fragen"
    return result


# ------------------------------------------------------------ Zustandsfälle

def test_running_stats_report_running_with_real_values():
    """Vollständige Stats-JSON → Running mit plausiblen cpu/memory-Werten."""
    body = _metrics(_app(), _dumps(RUNNING_STATS))

    assert body["status"] == "Running"
    assert body["cpu"] == pytest.approx(40.0, abs=1e-6)
    assert body["memory_mb"] == pytest.approx(165.1, abs=0.1)
    assert body["memory_pct"] == pytest.approx(0.541, abs=0.01)
    assert "hint" not in body, "Running braucht keinen Hinweis"


def test_empty_body_is_unavailable_not_stopped():
    """Leerer Body (Timeout) → unavailable + hint. Das ist der Kern des Fixes.

    Der Altstand meldete hier ``Stopped``: ein abgeschnittener Transport ist
    aber keine Zustandsaussage über den Container.
    """
    body = _metrics(_app(), b"")

    assert body["status"] == "unavailable", (
        "Leerer Body ist ein Timeout, kein gestoppter Container"
    )
    assert body["status"] != "Stopped"
    assert body.get("hint"), "unavailable muss begründet werden"
    assert "Timeout" in body["hint"] or "keine Statistik" in body["hint"]
    assert body["cpu"] == 0.0 and body["memory_mb"] == 0.0


def test_truncated_json_is_unavailable_with_its_own_reason():
    """Abgeschnittene Antwort → unavailable, mit eigener Begründung."""
    body = _metrics(_app(), TRUNCATED_BODY)

    assert body["status"] == "unavailable"
    assert body["status"] != "Stopped"
    hint = body.get("hint") or ""
    assert hint, "unavailable muss begründet werden"
    assert "unvollstaendig" in hint or "JSON" in hint

    # Eigene Begründung: nicht derselbe Text wie beim leeren Body.
    empty_hint = _metrics(_app(), b"").get("hint")
    assert hint != empty_hint, "Timeout und kaputtes JSON brauchen getrennte Hinweise"


def test_docker_answer_without_counters_is_stopped():
    """Docker antwortet, hat aber keine Zähler → echte Aussage: Stopped."""
    body = _metrics(_app(), _dumps(STOPPED_STATS))

    assert body["status"] == "Stopped"
    assert body["cpu"] == 0.0
    assert body["memory_mb"] == 0.0
    assert "hint" not in body


# ------------------------------------------------------------------- Cache

def test_same_container_queries_docker_only_once():
    """Zwei Aufrufe, derselbe Container → eine Docker-Abfrage (Cache)."""
    m = _app()
    fn = getattr(m, "_docker_container_stats", None)
    assert fn is not None, "Cache-Wrapper _docker_container_stats fehlt"

    calls = []

    def fake(method, path, payload=None, timeout=1.0):
        calls.append(path)
        return _dumps(RUNNING_STATS)

    _reset_cache(m)
    with patch.object(m, "docker_socket_request", side_effect=fake):
        first = fn(CONTAINER)
        second = fn(CONTAINER)

    assert len(calls) == 1, f"Cache griff nicht, Docker wurde {len(calls)}× gefragt"
    assert first == second


def test_two_containers_do_not_share_cache_entries():
    """Verschiedene Container → zwei Abfragen, kein Wert-Leak über den Schlüssel."""
    m = _app()
    fn = getattr(m, "_docker_container_stats", None)
    assert fn is not None

    calls = []

    def fake(method, path, payload=None, timeout=1.0):
        calls.append(path)
        name = path.split("/")[2]  # /containers/<name>/stats?...
        payload_stats = dict(RUNNING_STATS, name=f"/{name}")
        return _dumps(payload_stats)

    _reset_cache(m)
    with patch.object(m, "docker_socket_request", side_effect=fake):
        a1 = fn("container-a")
        b1 = fn("container-b")
        a2 = fn("container-a")  # muss aus dem Cache kommen

    assert calls == [
        "/containers/container-a/stats?stream=false",
        "/containers/container-b/stats?stream=false",
    ], f"Cache-Schlüssel ist nicht container-spezifisch: {calls}"
    assert a1 == a2, "Wiederholter Aufruf muss denselben Eintrag liefern"
    assert a1 != b1, "Zwei Container dürfen nicht dieselbe Antwort sehen"
    assert json.loads(a1)["name"] == "/container-a"
    assert json.loads(b1)["name"] == "/container-b"


def test_container_action_invalidates_the_stats_cache():
    """Start/Stop muss den 5-s-Cache leeren, sonst zeigt das UI den Vorzustand."""
    m = _app()
    fn = getattr(m, "_docker_container_stats", None)
    assert fn is not None

    calls = []

    def fake_stats(method, path, payload=None, timeout=1.0):
        calls.append(path)
        return _dumps(RUNNING_STATS)

    _reset_cache(m)
    with patch.object(m, "docker_socket_request", side_effect=fake_stats), \
            patch.object(m.docker_client, "container_action", return_value=b""):
        fn(CONTAINER)
        assert len(calls) == 1

        result = m.post_docker_container_action(CONTAINER, "stop")
        assert result["status"] == "success", result

        fn(CONTAINER)

    assert len(calls) == 2, (
        "Nach post_docker_container_action muss der Stats-Cache leer sein "
        f"(Docker wurde nur {len(calls)}× gefragt)"
    )

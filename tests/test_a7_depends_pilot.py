"""A7-Pilot: `POST /api/system/hermes/restart` haengt an einem `Depends()`-Provider.

Die Route ist seit dem P7-Fix eine **Diagnose** (read-only): sie prueft die
Kandidatenliste des Hermes-Core-Containers und meldet den Zustand, startet aber
bewusst nichts (Begruendung im Handler-Docstring: Gateway-Kollision).

Drei Zusicherungen, bewusst getrennt:

1. `test_restart_route_declares_db_dependency` (AST) — die Route deklariert die
   State-DB als FastAPI-Dependency und oeffnet sie nicht mehr selbst per
   `with _get_state_db() as conn:`. Unveraendert seit dem A7-Pilot: wer den
   Handler zurueckbaut, wird rot.
2. `test_restart_route_injects_db_and_writes_log` (funktional, TestClient) —
   beweist, dass FastAPI die Dependency wirklich aufloest und der Handler die
   gelieferte Verbindung benutzt.
3. Die vier Zustandsfaelle der Diagnose (laeuft / gestoppt / nicht vorhanden /
   Docker-Fehler) plus der Nachweis, dass **kein** `container_action` laeuft.

Rot-Beweis fuer (1) gegen den Vorstand:
    ARCHON_SYSTEM_PY=/pfad/zu/altem/system.py pytest tests/test_a7_depends_pilot.py -k declares
"""

import ast
import os
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import archon.core.state_db as state_db
import archon.routers.system as system_router
from utils.docker_client import docker_client as _docker_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_PY = os.environ.get(
    "ARCHON_SYSTEM_PY", os.path.join(REPO, "archon", "routers", "system.py")
)
ROUTE_NAME = "api_system_hermes_restart"
ROUTE_PATH = "/api/system/hermes/restart"

RUNNING = {
    "State": {"Running": True, "Status": "running"},
    "Config": {"Image": "hermes-agent-plus:latest"},
}
STOPPED = {
    "State": {"Running": False, "Status": "exited"},
    "Config": {"Image": "hermes-agent-plus:latest"},
}


def _route_node(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == ROUTE_NAME:
            return node
    raise AssertionError("%s nicht in %s gefunden" % (ROUTE_NAME, path))


def _depends_params(node):
    """Namen aller Parameter, deren Default ein Depends(...)-Aufruf ist."""
    args = node.args
    positional = [a.arg for a in args.args]
    defaults = args.defaults
    if not defaults:
        return []
    bound = positional[-len(defaults):]
    return [
        name for name, default in zip(bound, defaults)
        if isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends"
    ]


def test_restart_route_declares_db_dependency():
    """Die Route holt die DB per Depends() und oeffnet sie nicht selbst."""
    node = _route_node(SYSTEM_PY)

    assert _depends_params(node) == ["conn"], (
        "Route %s muss genau einen Depends()-Parameter 'conn' deklarieren, "
        "gefunden: %s" % (ROUTE_NAME, _depends_params(node))
    )

    own_opens = [
        n for n in ast.walk(node)
        if isinstance(n, ast.With)
        and any("_get_state_db" in ast.unparse(item.context_expr) for item in n.items)
    ]
    assert not own_opens, (
        "Handler oeffnet die State-DB noch selbst per `with _get_state_db()` "
        "(Zeile %s) — sie kommt jetzt aus der Dependency"
        % [n.lineno for n in own_opens]
    )


@pytest.fixture()
def client_and_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"

    def _tmp_state_db():
        return sqlite3.connect(str(db_path), timeout=5.0)

    monkeypatch.setattr(state_db, "_get_state_db", _tmp_state_db)
    # RBAC: die Route ist eine Admin-Route. Diese Tests beschreiben den
    # Nicht-Rollen-Pfad (Depends/DB-Verhalten), deshalb wird der Rollenzaun
    # als "Admin erkannt" verdrahtet — ohne Injektion sperrt er fail-closed
    # (503) und der Test wuerde das Falsche messen.
    monkeypatch.setitem(system_router._DEPS, "require_admin",
                        lambda request: {"role": "admin"})

    app = FastAPI()
    app.include_router(system_router.router)
    return TestClient(app), db_path


def _fake_probe(monkeypatch, by_name):
    """Ersetzt die read-only Container-Abfrage.

    `by_name[name]` ist das Container-JSON; fehlt der Schluessel, existiert der
    Container nicht; eine Exception-Instanz bedeutet "Docker-Fehler".
    Rueckgabe: Liste der abgefragten Namen (Reihenfolge = Kandidatenliste).
    """
    asked = []

    def _inspect(name):
        asked.append(name)
        value = by_name.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(system_router, "_inspect_hermes_core", _inspect)
    return asked


def _rows(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT target, status FROM system_restart_logs").fetchall()
    finally:
        conn.close()


def test_restart_route_injects_db_and_writes_log(client_and_db, monkeypatch):
    """Echter Request durch die Route: 200 und Satz in der vom Depends() gelieferten DB."""
    client, db_path = client_and_db
    _fake_probe(monkeypatch, {"hermes-agent": RUNNING})

    response = client.post(ROUTE_PATH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["running"] is True
    assert body["image"] == "hermes-agent-plus:latest"
    assert "duration_seconds" not in body  # Diagnose, kein Restart-Report

    assert _rows(db_path) == [("hermes-agent", "ok")], (
        "Die per Depends() gelieferte Verbindung wurde nicht (oder falsch) "
        "beschrieben — Zeilen: %s" % _rows(db_path)
    )


def test_restart_route_reports_running_core(client_and_db, monkeypatch):
    """Laufender Kandidat -> 200 mit Ziel, running und Image."""
    client, _ = client_and_db
    asked = _fake_probe(monkeypatch, {"hermes-agent": RUNNING})

    response = client.post(ROUTE_PATH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["target"] == "hermes-agent"
    assert body["running"] is True
    assert body["image"] == "hermes-agent-plus:latest"
    assert "laeuft" in body["hint"]
    # Der erste Kandidat traegt, der zweite wird nicht mehr abgefragt.
    assert asked == ["hermes-agent"]


def test_restart_route_reports_stopped_core_without_starting(client_and_db, monkeypatch):
    """Gestoppter Kandidat -> 409 not_running mit manueller Anweisung."""
    client, db_path = client_and_db
    _fake_probe(monkeypatch, {"hermes-agent": STOPPED})

    response = client.post(ROUTE_PATH)

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["status"] == "not_running"
    assert body["target"] == "hermes-agent"
    assert body["running"] is False
    assert "docker start hermes-agent" in body["hint"]
    assert "NICHT Teil dieser Route" in body["hint"]
    assert _rows(db_path) == [("hermes-agent", "not_running")]


def test_restart_route_reports_absent_candidate(client_and_db, monkeypatch):
    """Keiner der Kandidaten existiert -> 409 absent mit Liste der Versuche."""
    client, db_path = client_and_db
    asked = _fake_probe(monkeypatch, {})

    response = client.post(ROUTE_PATH)

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["status"] == "absent"
    assert body["tried"] == ["hermes-agent", "hermes"]
    assert body["tried"] == asked
    assert "Kein Hermes-Core-Container" in body["hint"]
    assert _rows(db_path) == [("none", "absent")]


def test_restart_route_reports_docker_error_as_502(client_and_db, monkeypatch):
    """Docker nicht erreichbar -> 502, niemals 500."""
    client, _ = client_and_db
    _fake_probe(monkeypatch, {"hermes-agent": RuntimeError("Docker-Socket weg")})

    response = client.post(ROUTE_PATH)

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["status"] == "docker_error"
    assert "Docker-Socket weg" in body["hint"]


@pytest.mark.parametrize(
    "probe_map",
    [
        {"hermes-agent": RUNNING},
        {"hermes-agent": STOPPED},
        {},
        {"hermes-agent": RuntimeError("kaputt")},
    ],
    ids=["running", "stopped", "absent", "docker_error"],
)
def test_restart_route_never_starts_a_container(client_and_db, monkeypatch, probe_map):
    """Kern der Entscheidung: die Route loest NIE start/stop/restart aus."""
    client, _ = client_and_db
    _fake_probe(monkeypatch, probe_map)
    calls = []

    def _count(*args, **kwargs):
        calls.append((args, kwargs))
        return b""

    monkeypatch.setattr(_docker_client, "container_action", _count)

    client.post(ROUTE_PATH)

    assert calls == [], (
        "Die Diagnose-Route hat einen Container-Aufruf ausgeloest: %s — der Start "
        "darf ausschliesslich manuell erfolgen." % calls
    )

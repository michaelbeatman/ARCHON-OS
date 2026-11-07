"""A7-Pilot: `POST /api/system/hermes/restart` haengt an einem `Depends()`-Provider.

Zwei Zusicherungen, bewusst getrennt:

1. `test_restart_route_declares_db_dependency` (AST) — die Route deklariert die
   State-DB als FastAPI-Dependency und oeffnet sie nicht mehr selbst per
   `with _get_state_db() as conn:`. Das ist der Regressionsschutz: wer den
   Handler zurueckbaut, wird rot.
2. `test_restart_route_injects_db_and_writes_log` (funktional, TestClient) —
   beweist, dass FastAPI die Dependency wirklich aufloest und der Handler die
   gelieferte Verbindung benutzt: gemockter Docker-Aufruf (204) + temporaere DB,
   Assertion auf Statuscode, Antwortkoerper UND den geschriebenen DB-Satz.

Rot-Beweis fuer (1) gegen den Vorstand:
    ARCHON_SYSTEM_PY=/pfad/zu/altem/system.py pytest tests/test_a7_depends_pilot.py -k declares
"""

import ast
import os
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import archon.core.state_db as state_db
import archon.routers.system as system_router

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_PY = os.environ.get(
    "ARCHON_SYSTEM_PY", os.path.join(REPO, "archon", "routers", "system.py")
)
ROUTE_NAME = "api_system_hermes_restart"


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

    class _OkResponse:
        status_code = 204
        text = ""

    async def _fake_post(self, *args, **kwargs):
        return _OkResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    app = FastAPI()
    app.include_router(system_router.router)
    return TestClient(app), db_path


def test_restart_route_injects_db_and_writes_log(client_and_db):
    """Echter Request durch die Route: 200, Erfolgsbody, Satz in der DB."""
    client, db_path = client_and_db

    response = client.post("/api/system/hermes/restart")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert "duration_seconds" in body

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT target, status FROM system_restart_logs"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("hermes", "success")], (
        "Die per Depends() gelieferte Verbindung wurde nicht (oder falsch) "
        "beschrieben — Zeilen: %s" % rows
    )

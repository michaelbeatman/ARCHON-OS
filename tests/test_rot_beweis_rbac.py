"""Rot-Beweis: dieselbe 403-Erwartung gegen den Altstand (HEAD) und den neuen Stand.

Der Test wird **im HEAD-Export** ausgefuehrt und muss dort rot sein; im Repo
(live Working Tree) muss er gruen sein. Fachfunktionen sind gestubbt — es laeuft
kein Docker-Aufruf und kein Dateischreibvorgang.

Aufruf (im HEAD-Export):
    ARCHON_ROOT=<export> python -m pytest tests/rot_beweis_rbac.py -q
"""
import os
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OPERATOR = {"id": "usr_op", "username": "lisa", "role": "operator", "permissions": {}}


def _app():
    import main
    return main


def _request():
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/probe", "raw_path": b"/probe", "query_string": b"", "root_path": "",
        "headers": [(b"authorization", b"Bearer tok_op")],
        "client": ("127.0.0.1", 1), "server": ("testserver", 80), "app": _app().app,
    })


@pytest.fixture()
def stub(monkeypatch):
    """Operator-Session + gestubbte Fachfunktionen (keine Nebenwirkung)."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(OPERATOR))
    monkeypatch.setattr(main, "save_roles", lambda roles: None)
    monkeypatch.setattr(main, "save_agents", lambda agents: None)
    import backend.fleet_self_healing as fleet
    monkeypatch.setattr(fleet, "restart_service_container", lambda name: {"status": "stub"})
    import backend.system_updater as updater
    monkeypatch.setattr(updater, "create_snapshot", lambda **kw: {"status": "stub"})
    from archon.routers import system as system_router
    # Auf HEAD gibt es keine Injektion; auf dem neuen Stand muss sie durchlassen pruefen
    if hasattr(system_router, "_DEPS"):
        monkeypatch.setitem(system_router._DEPS, "require_admin", main.require_admin)
    return main


def _call(fn, *args, **kwargs):
    """Ruft den Handler mit den Argumenten, die er laut Signatur braucht."""
    import inspect
    params = list(inspect.signature(fn).parameters.values())
    if params and params[0].name == "request":
        args = (_request(),) + tuple(args)
    return fn(*args, **kwargs)


def test_guard_blocks_operator_on_save_roles(stub):
    """POST /api/roles: Operator darf Rollen nicht schreiben -> erwartet 403."""
    with pytest.raises(HTTPException) as exc:
        _call(stub.api_save_roles, [])
    assert exc.value.status_code == 403, f"kein Rollenzaun: {exc.value.status_code}"


def test_guard_blocks_operator_on_save_agents(stub):
    """POST /api/agents: Operator darf die Agentenliste nicht ueberschreiben -> 403."""
    with pytest.raises(HTTPException) as exc:
        _call(stub.api_save_agents, [])
    assert exc.value.status_code == 403, f"kein Rollenzaun: {exc.value.status_code}"


def test_guard_blocks_operator_on_fleet_heal(stub):
    """POST /api/fleet/heal/{service}: Service-Neustart ist Admin-Sache -> 403."""
    with pytest.raises(HTTPException) as exc:
        _call(stub.api_heal_service, "n8n")
    assert exc.value.status_code == 403, f"kein Rollenzaun: {exc.value.status_code}"


def test_guard_blocks_operator_on_system_update_backup(stub):
    """POST /api/v1/system/update/backup (Router): Snapshot ist Admin-Sache -> 403."""
    from archon.routers import system as system_router
    with pytest.raises(HTTPException) as exc:
        _call(system_router.api_system_update_backup, {})
    assert exc.value.status_code == 403, f"kein Rollenzaun: {exc.value.status_code}"

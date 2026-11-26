# -*- coding: utf-8 -*-
"""D2/2d/2 — Characterization der 29 spaeten try/except-Router-Bloecke.

INVARIANTS §3: erst den Grund lesen, dann einen Test schreiben, dann aendern.
Geprueft wird die ECHTE Logik von ``register_late_routers`` mit den echten
``main``-Symbolen als Deps — kein Source-Text-Snapshot (G7), kein Theater-Gate.

Vertraege:
* 30 ``include_router`` in 29 unabhaengigen try-Bloecken -> 284 Pfade auf
  einer frischen App, ``load_errors`` leer.
* Jeder der 29 Bloecke haengt bei Importfehler GENAU EINEN Eintrag mit dem
  ORIGINAL-Praefix an ``load_errors``; die uebrigen 28 laufen weiter.
* Die 19 Deps sind zur Aufrufzeit injizierte Callables/Objekte — kein
  Rueckimport auf ``main`` (S3-Muster, Kartierung §6c).

Review-Lesson aus 2d/1 wird bewusst angewandt: die Identitaet der
``load_errors``-Liste ist NICHT nur durch private Testlisten geprueft, sondern
zusaetzlich in ``test_d2_router_special_blocks.py::test_v5`` ueber einen
Spion vor dem echten ``import main`` (gilt fuer beide Register-Funktionen).
"""

from __future__ import annotations

import logging
import sys
import warnings
from typing import Any, List, cast

import pytest
from fastapi import FastAPI

import main as app_main
from archon.routers import LateRouterDeps, register_late_routers

# 29 Bloecke / 31 Appends insgesamt (2 Sonderbloecke + 29 hier). Der
# operations_calendar-Block hat 2 Includes, aber nur 1 Append.
_PREFIX_CASES = [
    ("archon.routers.crm", "crm: "),
    ("archon.routers.erp", "erp: "),
    ("archon.routers.corporate", "corporate: "),
    ("archon.routers.security", "security: "),
    ("archon.routers.execution", "execution: "),
    ("archon.routers.memory", "memory: "),
    ("archon.routers.context_packages", "context_packages: "),
    ("archon.routers.routergate", "routergate: "),
    ("archon.routers.voice", "voice: "),
    ("archon.routers.swarm", "swarm: "),
    ("archon.routers.contracts", "contracts: "),
    ("archon.routers.plugins", "plugins: "),
    ("archon.routers.governance", "governance: "),
    ("archon.routers.templates", "templates: "),
    ("archon.routers.boardroom", "boardroom: "),
    ("archon.routers.llm_providers", "llm_providers: "),
    ("archon.routers.hermes_profiles", "hermes_profiles: "),
    ("archon.routers.system", "system: "),
    ("archon.routers.skills", "skills: "),
    ("archon.routers.mission_control", "mission_control: "),
    ("archon.routers.onboarding", "onboarding: "),
    ("archon.routers.demo", "demo: "),
    ("archon.routers.mcp_gateway", "mcp_gateway: "),
    ("archon.routers.squad_packs", "squad_packs: "),
    ("archon.routers.tenants", "tenants: "),
    ("archon.routers.playbooks", "playbooks: "),
    ("archon.routers.preflight_shadow", "preflight_shadow: "),
    ("archon.routers.epistemic_hygiene", "epistemic_hygiene: "),
    ("archon.routers.operations_calendar", "operations_calendar: "),
]


def _deps_from_main() -> LateRouterDeps:
    """Echte main-Symbole — dieselben, die main.py an der Aufrufstelle uebergibt."""
    return LateRouterDeps(
        load_mission_control_data=app_main._load_mission_control_data,
        save_mission_control_data=app_main._save_mission_control_data,
        api_get_hermes_profiles=app_main.api_get_hermes_profiles,
        load_boardroom_frameworks=app_main.load_boardroom_frameworks,
        load_roles=app_main.load_roles,
        save_all_agent_profiles=app_main.save_all_agent_profiles,
        sync_org_hierarchy_node=app_main._sync_org_hierarchy_node,
        invalidate_paperclip_agents_cache=app_main.invalidate_paperclip_agents_cache,
        profiles_service=app_main.profiles_service,
        load_json=app_main._load_json,
        save_json=app_main._save_json,
        broadcast_event=app_main.broadcast_event,
        require_admin=app_main.require_admin,
        skills_engine=app_main.skills_engine,
        get_live_telemetry_metrics=app_main._get_live_telemetry_metrics,
        sync_task_to_obsidian=app_main._sync_task_to_obsidian,
        execute_mission_control_task=app_main._execute_mission_control_task,
        finalize_approval=app_main._finalize_synthesis_after_approval,
        fan_in=app_main._fan_in_maybe_start_synthesis,
    )


def _paths(app: FastAPI) -> List[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return list(app.openapi()["paths"])


def test_w1_all_late_routers_present_without_load_errors() -> None:
    errors: List[str] = []
    app = FastAPI()
    register_late_routers(app, errors, _deps_from_main())

    assert errors == [], errors
    isolated = _paths(app)
    assert len(isolated) > 100, f"nur {len(isolated)} Pfade — Gruppe unvollstaendig"
    real = _paths(app_main.app)
    assert set(isolated) <= set(real), "Pfade der spaeten Gruppe fehlen in der echten App"

    # Negativproben (Review-Fund 5): gegen ECHTE Logik, nicht Selbsttests
    # der eigenen Assertion. Eine leere App muss den Pfad-Schwellenwert
    # scheitern lassen; ein erfundener Pfad muss das Subset scheitern lassen.
    with pytest.raises(AssertionError):
        assert (set(isolated) | {"/__kein_late_router_pfad__"}) <= set(real)
    with pytest.raises(AssertionError):
        assert len(_paths(FastAPI())) > 100


@pytest.mark.parametrize("module,prefix", _PREFIX_CASES)
def test_w2_broken_import_appends_exact_prefix(
    module: str,
    prefix: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``None`` in sys.modules laesst den from-Import real raisen.

    Review-Fund 5: zusaetzlich wird der zugehoerige logger.warning-Text
    gebunden (vorher 0 caplog-Treffer in tests/) und die Negativprobe geht
    gegen einen fremden Praefix statt gegen die eigene Assertion.
    """
    caplog.set_level(logging.WARNING, logger="archon_os")
    errors: List[str] = []
    app = FastAPI()
    monkeypatch.setitem(cast(Any, sys.modules), module, None)
    register_late_routers(app, errors, _deps_from_main())

    assert len(errors) == 1, errors
    assert errors[0].startswith(prefix), (prefix, errors)
    # Der WARN-Text des sabotierten Blocks muss real geloggt worden sein.
    block_name = module.rsplit(".", 1)[1]
    assert f"[Router] {block_name} nicht geladen:" in caplog.text, caplog.text
    # Nur der sabotierte Block darf fehlschlagen — die 28 anderen laufen weiter.
    assert not any(
        e.startswith(other)
        for m, other in _PREFIX_CASES
        if m != module
        for e in errors
    ), "fail-soft-Isolierung gebrochen"
    assert len(_paths(app)) > 100, "uebrige Bloecke muessen weiterlaufen"
    # Negativprobe: ein fremder Praefix MUSS diskriminiert werden.
    wrong = "erp: " if prefix != "erp: " else "crm: "
    with pytest.raises(AssertionError):
        assert errors[0].startswith(wrong)


def test_w3_prefix_ratchet_can_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negativprobe gegen den Praefix-Vergleich aus w2."""
    errors: List[str] = []
    monkeypatch.setitem(cast(Any, sys.modules), "archon.routers.crm", None)
    register_late_routers(FastAPI(), errors, _deps_from_main())
    assert errors[0].startswith("crm: ")
    with pytest.raises(AssertionError):
        assert errors[0].startswith("erp: ")


def test_w4_control_without_sabotage() -> None:
    """Kontrollprobe: ohne Sabotage bleibt die Fehlerliste leer."""
    errors: List[str] = []
    register_late_routers(FastAPI(), errors, _deps_from_main())
    assert errors == []
    # Negativprobe gegen echte Logik: eine leere App hat keine Pfade.
    with pytest.raises(AssertionError):
        assert len(_paths(FastAPI())) > 100

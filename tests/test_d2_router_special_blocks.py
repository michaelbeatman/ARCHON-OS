# -*- coding: utf-8 -*-
"""D2/2d/1 — Characterization der zwei Sonder-Router-Bloecke vor dem Split.

INVARIANTS §3: erst den Grund lesen, dann einen Test schreiben, dann aendern.
Geprueft wird die ECHTE Logik der extrahierten Funktion, nicht Source-Text
(G7: „Umstellung auf V, nicht Loeschen"). Jeder Test enthaelt eine
Negativprobe, die bei gebrochener Logik rot wuerde (§4 Regel 5).

Review-Fix (26.11., frische Instanz): der erste Entwurf uebergab in v1-v3
jeweils eine PRIVATE Liste und pruefte in v4 nur ``== []``. Damit blieb die
zentrale Invariante — ``main.py`` reicht ``_ROUTER_LOAD_ERRORS`` als
IDENTISCHE Liste weiter — ungetestet. Ein ``list(...)`` an der Aufrufstelle
waere bei allen 4 Tests gruen geblieben und haette ``_assert_router_health()``
fuer diese zwei Router blind gemacht. v5 schliesst genau diese Luecke gegen
den echten ``main``-Import; v6/v7 sichern Mount-Bedingung, ``name``/
``directory``, ``include_router``-vor-``mount`` und die Prints ab.

Vertraege:
* ``register_special_routers`` registriert ``views_core`` und ``operations``
  auf einer frischen App, ohne Ladefehler.
* Ein fehlgeschlagener Import haengt den Fehler mit dem ORIGINAL-Praefix
  (``views_core: `` / ``operations_api: ``) an ``load_errors`` und laesst den
  Router weg — fail-closed statt still 404. Die zwei try-Bloecke sind
  unabhaengig: faellt einer, laeuft der andere trotzdem.
* In der echten App liegen die Sonderbloecke weiterhin exakt zwischen
  ``/api/paperclip/agents`` und ``/static/avatars/{filename}`` —
  Registrierungsreihenfolge ist Pfad-Praezedenz (INVARIANTS #7).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any, List, cast

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

import main as app_main
from archon.routers import naked_router_order, register_router, register_special_routers

_VIEWS_ANCHOR = "/api/views/showroom/tree"
_OPS_ANCHOR = "/api/operations/kanban/tasks"

# Kompakter Reihenfolge-Ratchet: neue Pfade duerfen kommen, die Reihenfolge
# der bestehenden Anker darf nicht kippen (INVARIANTS #10: Ratchet, nicht
# Big-Bang). Kein 799-Zeilen-Snapshot, sondern eine Subsequenz-Pruefung.
_ORDER_SENTINELS = [
    "/livez",
    "/metrics",
    "/api/paperclip/agents",
    _VIEWS_ANCHOR,
    _OPS_ANCHOR,
    "/static/avatars/{filename}",
    "/api/crm/contacts",
    "/api/context-packages",
    "/api/v1/calendar/webhooks/push",
]

# 2d/3: exakte Registrierungsreihenfolge der 43 nackten Router. INVARIANTS #7
# war „⛔ kein Test" — dieser Contract schliesst das. Bewusst als Liste und
# nicht als Zaehler: eine Vertauschung zweier Includes muss rot werden.
_EXPECTED_NAKED_ORDER = [
    "_telemetry_router",
    "_core_settings_router",
    "_oracle_seo_router",
    "_theme_router",
    "_docker_services_router",
    "_agent_chat_router",
    "_gateway_router",
    "_watchdog_router",
    "_quickchat_router",
    "_ui_router",
    "_context_meter_router",
    "_brain_router",
    "_notebooks_router",
    "_telegram_router",
    "_decisions_router",
    "_hermes_ops_router",
    "_chat_router",
    "_guardian_router",
    "_hermes_config_router",
    "_context_help_router",
    "_auth_router",
    "_marketplace_router",
    "_memory_ops_router",
    "_email_settings_router",
    "_security_scanner_router",
    "_research_router",
    "_updater_router",
    "_documents_router",
    "_deals_router",
    "_vault_router",
    "_kanban_router",
    "_v2_capabilities_router",
    "_content_machine_router",
    "_containers_router",
    "_container_ops_router",
    "_hermes_proxy_router",
    "_hr_router",
    "_prompts_router",
    "_proxies_router",
    "_inbox_tools_router",
    "_resilience_router",
    "_mesh_router",
    "_autonomy_settings_router",
]


def _paths(app: FastAPI) -> List[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return list(app.openapi()["paths"])


def _is_subsequence(needles: List[str], haystack: List[str]) -> bool:
    it = iter(haystack)
    return all(any(item == needle for item in it) for needle in needles)


def _broken(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` in sys.modules laesst ``from <module> import ...`` real raisen."""
    monkeypatch.setitem(cast(Any, sys.modules), module, None)


def test_v1_special_blocks_register_both_routers_on_fresh_app() -> None:
    errors: List[str] = []
    app = FastAPI()
    register_special_routers(app, errors)

    assert errors == [], f"unerwartete Ladefehler: {errors}"
    paths = _paths(app)
    assert _VIEWS_ANCHOR in paths, "views_core-Router nicht registriert"
    assert _OPS_ANCHOR in paths, "operations-Router nicht registriert"

    # Negativprobe: auf einer leeren App MUESSEN beide Anker fehlen.
    empty = _paths(FastAPI())
    with pytest.raises(AssertionError):
        assert _VIEWS_ANCHOR in empty
    with pytest.raises(AssertionError):
        assert _OPS_ANCHOR in empty


def test_v2_broken_views_core_import_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    errors: List[str] = []
    app = FastAPI()
    _broken("views_core", monkeypatch)
    register_special_routers(app, errors)

    assert len(errors) == 1, errors
    assert errors[0].startswith("views_core: "), errors
    assert len(errors[0]) > len("views_core: "), errors
    assert "Error mounting views_core:" in capsys.readouterr().out
    assert _VIEWS_ANCHOR not in _paths(app), "defekter Router darf nicht registriert werden"
    assert _OPS_ANCHOR in _paths(app), "zweiter try-Block muss unabhaengig weiterlaufen"

    # Kontroll-Negativprobe gegen die ECHTE Logik: ohne Sabotage bleibt die
    # Liste leer. Waere die Assertion oben ein Selbsttest, wuerde das hier
    # nicht unterscheidbar sein.
    monkeypatch.undo()
    clean_errors: List[str] = []
    register_special_routers(FastAPI(), clean_errors)
    assert clean_errors == []
    with pytest.raises(AssertionError):
        assert clean_errors == errors


def test_v3_broken_operations_import_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    errors: List[str] = []
    app = FastAPI()
    _broken("archon.routers.operations", monkeypatch)
    register_special_routers(app, errors)

    assert len(errors) == 1, errors
    assert errors[0].startswith("operations_api: "), errors
    assert len(errors[0]) > len("operations_api: "), errors
    assert "Error mounting operations_api:" in capsys.readouterr().out
    assert _OPS_ANCHOR not in _paths(app), "defekter Router darf nicht registriert werden"
    assert _VIEWS_ANCHOR in _paths(app), "erster try-Block muss unabhaengig weiterlaufen"

    monkeypatch.undo()
    clean_errors: List[str] = []
    register_special_routers(FastAPI(), clean_errors)
    assert clean_errors == []
    with pytest.raises(AssertionError):
        assert clean_errors == errors


def test_v4_real_app_pins_special_block_position() -> None:
    assert app_main._ROUTER_LOAD_ERRORS == [], "echte App darf keine Ladefehler haben"
    paths = _paths(app_main.app)
    assert len(paths) == 799, f"Pfade: {len(paths)} (Referenz = 799)"
    assert _is_subsequence(_ORDER_SENTINELS, paths), "Router-Reihenfolge gekippt"

    # Mount-Reihenfolge: /builds/apps VOR /static/avatars VOR /static.
    route_paths = [getattr(r, "path", None) for r in app_main.app.routes]
    assert route_paths.index("/builds/apps") \
        < route_paths.index("/static/avatars/{filename}") \
        < route_paths.index("/static")

    # Negativprobe: eine vertauschte Ankerliste MUSS die Ratchet-Pruefung
    # rot machen — sonst waere _is_subsequence ein Theater-Gate.
    with pytest.raises(AssertionError):
        assert _is_subsequence(list(reversed(_ORDER_SENTINELS)), paths)


def test_v5_main_call_site_passes_original_load_errors_list() -> None:
    """Schliesst den Review-Fund: Identitaet gegen den ECHTEN main-Import.

    Zwei Spione werden VOR ``import main`` auf ``archon.routers`` installiert:
    fuer ``register_special_routers`` (2d/1) und ``register_late_routers``
    (2d/2). ``main.py:166-169`` liest die Attribute zur Importzeit, die
    Aufrufstellen rufen sie auf. Damit werden BEIDE Aufrufstellen selbst
    geprueft — ohne Source-Text-Assertion (G7) und ohne ``importlib.reload``
    (wuerde ``main.app`` ersetzen und andere Tests beeinflussen).

    Zusaetzlich (2d/3): im selben frischen Prozess wird die exakte
    Reihenfolge der 43 nackten Router gegen ``_EXPECTED_NAKED_ORDER``
    geprueft — INVARIANTS #7 („Router-Reihenfolge = Pfad-Praezedenz") war
    zuvor ungetestet.
    """
    wt = str(Path(__file__).resolve().parents[1])
    code = "\n".join([
        "import sys",
        f"sys.path.insert(0, {wt!r})",
        "import archon.routers",
        "_seen_special = []",
        "_seen_late = []",
        "_orig_special = archon.routers.register_special_routers",
        "_orig_late = archon.routers.register_late_routers",
        "def _spy_special(app, load_errors):",
        "    _seen_special.append(load_errors)",
        "    return _orig_special(app, load_errors)",
        "def _spy_late(app, load_errors, deps):",
        "    _seen_late.append(load_errors)",
        "    return _orig_late(app, load_errors, deps)",
        "archon.routers.register_special_routers = _spy_special",
        "archon.routers.register_late_routers = _spy_late",
        "import main",
        "assert _seen_special, 'register_special_routers beim main-Import nicht aufgerufen'",
        "assert _seen_late, 'register_late_routers beim main-Import nicht aufgerufen'",
        "assert _seen_special[0] is main._ROUTER_LOAD_ERRORS, 'special: Kopie/Rebind'",
        "assert _seen_late[0] is main._ROUTER_LOAD_ERRORS, 'late: Kopie/Rebind'",
        # Echte Negativprobe (Review-Fund 5): die vorherige Variante war
        # tautologisch — ``list(...) is ...`` ist IMMER False, also immer rot
        # und damit immer gruen. Stattdessen wird bewiesen, dass der
        # Identitaetsvergleich zwischen einer Kopie und dem Original
        # diskriminiert.
        "_copy = list(_seen_special[0])",
        "assert _copy is not main._ROUTER_LOAD_ERRORS, "
        "'NEGATIVPROBE: is-Test diskriminiert eine Kopie nicht'",
        f"_expected_order = {_EXPECTED_NAKED_ORDER!r}",
        "assert archon.routers.naked_router_order() == _expected_order, "
        "'Naked-Router-Reihenfolge gekippt'",
        "try:",
        "    assert list(reversed(archon.routers.naked_router_order())) == _expected_order",
        "except AssertionError:",
        "    pass",
        "else:",
        "    raise AssertionError('NEGATIVPROBE: vertauschte Reihenfolge akzeptiert')",
        "print('IDENTITY_OK')",
    ])
    env = os.environ.copy()
    id_dir = Path(tempfile.gettempdir()) / "archon-2d-identity"
    id_dir.mkdir(parents=True, exist_ok=True)
    env["ARCHON_TEST_DB_ISOLATION"] = "1"
    env["ARCHON_DATA_DIR"] = str(id_dir)
    env.setdefault("ARCHON_AUDIT_HMAC_KEY", "probe-only-" + "a" * 64)
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=wt, env=env,
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "IDENTITY_OK" in proc.stdout, proc.stdout


def test_v6_missing_apps_dir_omits_mount_but_keeps_routers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Mount-Bedingung ``os.path.exists(get_apps_dir())`` ist ein Contract."""
    import views_core

    monkeypatch.setattr(
        views_core, "get_apps_dir", lambda: str(Path(tempfile.gettempdir()) / "__archon_2d_missing__")
    )
    errors: List[str] = []
    app = FastAPI()
    register_special_routers(app, errors)

    assert errors == []
    assert _VIEWS_ANCHOR in _paths(app), "Router bleibt auch ohne Apps-Verzeichnis"
    mounts = [r for r in app.routes if getattr(r, "path", None) == "/builds/apps"]
    assert mounts == [], "Mount darf bei fehlendem Verzeichnis nicht gesetzt werden"
    with pytest.raises(AssertionError):
        assert len(mounts) == 1


def test_v7_mount_contract_and_prints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``name``/``directory``, include_router VOR mount, beide Prints."""
    import views_core

    apps = tmp_path / "apps"
    apps.mkdir()
    monkeypatch.setattr(views_core, "get_apps_dir", lambda: str(apps))
    errors: List[str] = []
    app = FastAPI()
    register_special_routers(app, errors)

    assert errors == []
    mounts = [r for r in app.routes if getattr(r, "path", None) == "/builds/apps"]
    assert len(mounts) == 1
    mount = mounts[0]
    assert isinstance(mount, Mount), "Muss ein echter starlette-Mount sein"
    assert mount.name == "builds_apps"
    assert cast(StaticFiles, mount.app).directory == str(apps)

    # Falle #6 (Report §5): FastAPI kapselt include_router in
    # ``_IncludedRouter`` mit LEEREM .path -> Reihenfolge NICHT ueber
    # app.routes[].path pruefbar, sondern ueber die Routen-Objekte selbst.
    # Original-Reihenfolge: views_core -> /builds/apps-Mount -> operations.
    route_kinds = [type(r).__name__ for r in app.routes]
    mount_idx = next(
        i for i, r in enumerate(app.routes) if getattr(r, "path", None) == "/builds/apps"
    )
    included = [i for i, kind in enumerate(route_kinds) if kind == "_IncludedRouter"]
    assert len(included) == 2, "genau zwei include_router erwartet"
    assert included[0] < mount_idx < included[1], "views -> mount -> operations gekippt"
    assert "Operations API mounted successfully." in capsys.readouterr().out

    with pytest.raises(AssertionError):
        assert mount.name != "builds_apps"
    with pytest.raises(AssertionError):
        assert len(mounts) == 0
    with pytest.raises(AssertionError):
        assert mount_idx < included[0]


def test_v8_characterized_module_surface_delta() -> None:
    """Bewusste, charakterisierte Delta aus dem Review — kein stiller Drift.

    Die vier Namen waren ``main``-Globals und sind jetzt funktionslokal.
    Repo-weit 0 Referenzen; fuer externe ``getattr``/REPL-Nutzung nicht
    beweisbar. Falls jemand sie bewusst zurueckfuehrt, wird dieser Test rot
    und erzwingt eine Entscheidung statt unbemerkter Aenderung.
    """
    for name in ("views_core_router", "operations_router", "get_apps_dir", "apps_static_dir"):
        assert not hasattr(app_main, name), f"{name} ist wieder main-Global — Entscheidung pruefen"
    assert hasattr(app_main, "_ROUTER_LOAD_ERRORS")
    with pytest.raises(AssertionError):
        assert not hasattr(app_main, "_ROUTER_LOAD_ERRORS")


def test_v9_register_router_registers_and_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2d/3: echte Logik der delegierenden Funktion — kein Theater-Wrapper."""
    # Isoliere die Modul-Liste, damit dieser Test den globalen Zustand
    # (und damit test_v10 / den v5-Subprozess) nicht veraendert.
    monkeypatch.setattr("archon.routers._NAKED_ROUTER_ORDER", [])

    probe = APIRouter()

    @probe.get("/__2d3_probe__")
    def _probe_endpoint() -> dict:
        return {"ok": True}

    app = FastAPI()
    register_router(app, probe, "_probe_router")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        paths = list(app.openapi()["paths"])
    assert "/__2d3_probe__" in paths, "Router wurde nicht registriert"
    assert naked_router_order() == ["_probe_router"], "Reihenfolge nicht protokolliert"

    # Negativproben: beide Assertions sind live.
    with pytest.raises(AssertionError):
        assert "/__2d3_probe__" not in paths
    with pytest.raises(AssertionError):
        assert naked_router_order() == []


def test_v10_real_app_pins_all_43_naked_routers() -> None:
    """INVARIANTS #7: exakte Reihenfolge, nicht nur ein Pfad-Zaehler."""
    order = naked_router_order()
    assert order == _EXPECTED_NAKED_ORDER, "Reihenfolge der 43 Router gekippt"
    assert len(order) == 43

    # Negativprobe: eine Vertauschung MUSS rot werden — sonst waere der
    # Vergleich tautologisch (die Review-Lektion aus 2d/1).
    with pytest.raises(AssertionError):
        assert list(reversed(order)) == _EXPECTED_NAKED_ORDER
    swapped = list(order)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(AssertionError):
        assert swapped == _EXPECTED_NAKED_ORDER

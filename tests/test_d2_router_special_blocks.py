# -*- coding: utf-8 -*-
"""D2/2d/1 — Characterization der zwei Sonder-Router-Bloecke vor dem Split.

INVARIANTS §3: erst den Grund lesen, dann einen Test schreiben, dann aendern.
Geprueft wird die ECHTE Logik der extrahierten Funktion, nicht Source-Text
(G7: „Umstellung auf V, nicht Loeschen"). Jeder Test enthaelt eine
Negativprobe, die bei gebrochener Logik rot wuerde (§4 Regel 5).

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

import sys
import warnings
from typing import Any, List, cast

import pytest
from fastapi import FastAPI

import main as app_main
from archon.routers import register_special_routers

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
    "/api/context-packages",
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


def test_v2_broken_views_core_import_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: List[str] = []
    app = FastAPI()
    _broken("views_core", monkeypatch)
    register_special_routers(app, errors)

    assert any(e.startswith("views_core: ") for e in errors), errors
    assert _VIEWS_ANCHOR not in _paths(app), "defekter Router darf nicht registriert werden"
    assert _OPS_ANCHOR in _paths(app), "zweiter try-Block muss unabhaengig weiterlaufen"

    # Negativprobe: die Fehlerliste ist NICHT leer — genau das waere das
    # fail-open-Theater, das dieser Test verhindern soll.
    with pytest.raises(AssertionError):
        assert errors == []


def test_v3_broken_operations_import_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: List[str] = []
    app = FastAPI()
    _broken("archon.routers.operations", monkeypatch)
    register_special_routers(app, errors)

    assert any(e.startswith("operations_api: ") for e in errors), errors
    assert _OPS_ANCHOR not in _paths(app), "defekter Router darf nicht registriert werden"
    assert _VIEWS_ANCHOR in _paths(app), "erster try-Block muss unabhaengig weiterlaufen"

    with pytest.raises(AssertionError):
        assert errors == []


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

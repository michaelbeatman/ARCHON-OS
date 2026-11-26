"""Archon OS App-Paket.

D2/2d: Die Router-Registrierung wird schrittweise aus ``main.py`` hierher
gehoben. Auf Paketebene werden AUSSCHLIESSLICH stdlib-/fastapi-Importe
geladen (``os``, ``typing``, ``FastAPI``, ``StaticFiles``) — keine Router-
und kein ``main``-Import. Die Router-Imports bleiben bewusst zur Aufrufzeit
INNERHALB der Funktion: sie lagen in ``main.py`` in try/except-Bloecken
(fail-soft, ``_ROUTER_LOAD_ERRORS``) und duerfen beim blossen ``import main``
nicht hart scheitern. ``archon.routers.__init__`` wird bereits bei
``main.py:166`` ausgefuehrt; ein Router-Import zur Init-Zeit wuerde diesen
Schutz umgehen und ``import main`` bei einem fehlenden Router abbrechen.

KORREKTUR nach dem unabhaengigen Review (26.11.): die urspruengliche
Begruendung „Router-Module importieren main zurueck -> Zyklus" ist fuer
GENAU diese zwei Module nicht belegbar (0 Treffer in ``archon/routers/*.py``,
``_rbac.py:7-8`` dokumentiert das Gegenteil). Der lazy Import bleibt richtig,
die Begruendung war es nicht. Ebenso ist ``StaticFiles`` entgegen der
urspruenglichen Formulierung ein Modul-Ebenen-Import (harmlos).

Teilschritt 1: die zwei Sonderbloecke ``views_core`` und ``operations``.
Reine Extraktion der Registrierungslogik: Fehler-Praefixe, Prints,
Mount-Reihenfolge und die Identitaet der ``load_errors``-Liste bleiben 1:1
erhalten. Bewusst NICHT veraendert (INVARIANTS §3): die bedingte
``/builds/apps``-Mount-Abfrage, die beiden getrennten try/except-Bloecke
und die Reihenfolge der Aufrufe.

BEWUSSTE DELTA (kein „gar keine Veraenderung"): ``views_core_router``,
``operations_router``, ``get_apps_dir`` und ``apps_static_dir`` waren in
``main.py`` Modul-Globals und sind jetzt funktionslokal. Repo-weite Suche:
0 Referenzen, kein ``from main import *``; fuer externe ``getattr``/REPL-
Nutzung nicht beweisbar. Bewusst NICHT wiederhergestellt, weil ein
Modul-Level-Re-Import die fail-soft-Semantik zerstoeren wuerde.
"""

from __future__ import annotations

import os
from typing import List

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

__all__ = ["register_special_routers"]


def register_special_routers(app: FastAPI, load_errors: List[str]) -> None:
    """Registriert die zwei Sonder-Router an ihrer urspruenglichen Position.

    ``load_errors`` ist dieselbe Liste wie ``main._ROUTER_LOAD_ERRORS`` (kein
    Rebind): ``_assert_router_health()`` und ``/readyz`` lesen das Original.
    Die Aufrufstelle in ``main.py`` bleibt exakt zwischen ``_proxies_router``
    und dem ``/static/avatars``-Endpoint — Registrierungsreihenfolge ist
    Pfad-Praezedenz (INVARIANTS #7).
    """
    try:
        from views_core import get_apps_dir
        from views_core import router as views_core_router

        app.include_router(views_core_router)
        apps_static_dir = get_apps_dir()
        if os.path.exists(apps_static_dir):
            app.mount("/builds/apps", StaticFiles(directory=apps_static_dir), name="builds_apps")
    except Exception as e_views:
        load_errors.append("views_core: " + str(e_views))
        print(f"Error mounting views_core: {e_views}")

    try:
        from archon.routers.operations import router as operations_router

        app.include_router(operations_router)
        print("Operations API mounted successfully.")
    except Exception as e_ops:
        load_errors.append("operations_api: " + str(e_ops))
        print(f"Error mounting operations_api: {e_ops}")

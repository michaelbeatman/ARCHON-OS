"""Archon OS App-Paket.

D2/2d: Die Router-Registrierung wird schrittweise aus ``main.py`` hierher
gehoben. Bewusst NUR Funktionsdefinitionen mit lazy Imports auf Paketebene:
``archon.routers.__init__`` wird bereits beim ersten
``from archon.routers.<modul> import ...`` in ``main.py`` (Zeile ~166)
ausgefuehrt, waehrend viele Router-Module ``main`` zurueck importieren.
Ein Import der Router-Module zur Paket-Initialisierungszeit wuerde einen
Zyklus erzeugen (ANALYSIS_GOD_OBJECTS §2.3).

Teilschritt 1: die zwei Sonderbloecke ``views_core`` und ``operations``.
Reine Extraktion, keine Logikaenderung — Fehler-Praefixe, Prints,
Mount-Reihenfolge und die Identitaet der ``load_errors``-Liste bleiben 1:1
erhalten. Bewusst NICHT veraendert (INVARIANTS §3): die bedingte
``/builds/apps``-Mount-Abfrage, die beiden getrennten try/except-Bloecke
und die Reihenfolge der Aufrufe.
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

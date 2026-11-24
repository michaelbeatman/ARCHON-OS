"""Zentraler Provider-Container fuer die gestaffelte Entkopplung von ``import main``.

Zweck
-----
Router und Backend-Module sollen ihre Abhaengigkeiten nicht mehr direkt aus
``main`` ziehen. Stattdessen werden sie unter einem stabilen Namen in
``app.state`` abgelegt und ueber :func:`get` / :func:`get_provider` aufgeloest.

In dieser ersten Stufe (Kompatibilitaets-Shim) ist noch **nichts** registriert:
:func:`get` liefert daher das ``main``-Modul selbst, solange ein angefragter
Name nicht registriert ist. Die umgestellten Stellen verhalten sich dadurch
exakt wie vorher (``app_main = get_provider("app_main")`` entspricht
``import main as app_main``). Spaetere Stufen koennen einzelne Provider mit
``register(app, name, value)`` ersetzen, ohne die Konsumenten anzufassen.

Speicherort und Sperren
-----------------------
Der kanonische Storage ist ``app.state.archon_provider_registry`` (ein Dict).
Ein Modul-Global merkt sich das zuletzt registrierte ``app``, damit das
argumentlose ``get(name)`` den passenden State findet. Dieses Singleton ist
**nicht** unguetzt: alle Lese- und Schreibzugriffe laufen ueber ein
``threading.RLock``. Das Dict in ``app.state`` selbst wird nur unter dieser
Sperre angelegt und beschrieben.

Fallback-Kette von :func:`get`
------------------------------
1. Registrierter Wert in ``app.state.archon_provider_registry[name]``.
2. Attribut ``name`` des geladenen ``main``-Moduls (``getattr(main, name, main)``).
3. Das ``main``-Modul selbst (Shim; z. B. fuer Cache-Keys wie ``"app_main"``,
   die kein Attribut von ``main`` sind).

Ist ``main`` noch nicht in ``sys.modules``, wird es lazy importiert — genau wie
das bisherige ``import main`` an den Konsumenten. Damit aendert sich auch im
Cold-Start-Fall nichts.

Bekannte Konsumenten und benoetigte Attribute
---------------------------------------------
* ``archon.routers.gateway`` (13 fruehere ``import main as app_main``-Stellen):
  ``_run_docker_exec``, ``require_admin``, ``_load_json``, ``_save_json``,
  ``GATEWAY_CONFIG_FILE``, ``MEMORY_DIR``, ``WORKSPACE_DIR``,
  ``_get_all_installed_profiles``, ``_load_gateway_config``,
  ``_save_gateway_config``, ``_update_profile_status``.
* ``backend.operations_api`` (9 fruehere ``import main``-Stellen):
  ausschliesslich ``broadcast_event`` ( jeweils hinter ``hasattr``-Guards).

Diese Liste ist Dokumentation fuer die naechste Entkopplungsstufe: dort sind
genau diese Attribute als eigene Provider zu registrieren.
"""

from __future__ import annotations

import importlib
import sys
import threading
from typing import Any, Dict, Optional

__all__ = ["register", "get", "get_provider", "STATE_ATTR"]

STATE_ATTR = "archon_provider_registry"

_LOCK = threading.RLock()
_current_app: Optional[Any] = None


def register(app: Any, name: str, value: Any) -> None:
    """Registriert ``value`` unter ``name`` im ``app.state``-Provider-Container.

    Der Name muss nicht vorher bekannt sein; bereits registrierte Namen werden
    ueberschrieben (letzte Registrierung gewinnt). Das ``app`` wird unter
    :data:`_LOCK` als aktueller Kontext gemerkt, damit :func:`get` ohne
    App-Argument darauf zugreifen kann.
    """
    global _current_app

    if not isinstance(name, str) or not name:
        raise ValueError("Provider-Name muss eine nicht-leere Zeichenkette sein")

    registry: Optional[Dict[str, Any]] = getattr(app.state, STATE_ATTR, None)
    if registry is None:
        registry = {}
        setattr(app.state, STATE_ATTR, registry)

    with _LOCK:
        registry[name] = value
        _current_app = app


def _main_module() -> Any:
    """Liefert das geladene ``main``-Modul oder importiert es lazy nach."""
    main = sys.modules.get("main")
    if main is None:
        main = importlib.import_module("main")
    return main


def get(name: str) -> Any:
    """Loest einen Provider auf (siehe Modul-Docstring fuer die Fallback-Kette).

    Bei fehlender Registrierung liefert diese Funktion das ``main``-Modul
    (bzw. das gleichnamige Attribut davon) und nicht ``None`` — das ist der
    Kompatibilitaets-Shim fuer die noch nicht entkoppelten Konsumenten.
    """
    with _LOCK:
        app = _current_app
        registry = getattr(app.state, STATE_ATTR, None) if app is not None else None
        if registry is not None and name in registry:
            return registry[name]

    main = _main_module()
    return getattr(main, name, main)


# Lesbarer Name an den Konsumenten; ``get`` bleibt die kurze Kern-API.
get_provider = get

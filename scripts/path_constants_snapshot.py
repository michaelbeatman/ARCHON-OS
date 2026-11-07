#!/usr/bin/env python3
"""Snapshot der aufgeloesten Werte aller Pfad-Konstanten (A5 Etappe 4b).

Zweck: beweisen, dass die Auslagerung der Pfad-Konstanten den aufgeloesten
Wert in JEDER Umgebung unveraendert laesst. Host und Container leiten die
Pfade unterschiedlich ab (``/mnt/raid/...`` vs ``/app/...``), deshalb wird der
Snapshot in beiden Umgebungen gezogen und verglichen.

Gemessen wird die Bindung am Entry-Point ``main`` — VOR der Auslagerung steht
die Definition dort, NACH der Auslagerung der Import aus ``archon.core.paths``.
Beidesmal ist ``getattr(main, name)`` also genau der Wert, den die laufende
App sieht. Damit gibt es keine zweite Wahrheit fuer die Messung.

Ausgabe: sortiertes JSON ohne Zeitstempel -> byte-vergleichbar zwischen Laeufen.

    .venv/bin/python scripts/path_constants_snapshot.py
    docker exec -w /app ARCHON-OS python scripts/path_constants_snapshot.py
"""

import importlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# Alle Pfad-Konstanten, die aus main.py nach archon/core/paths.py wandern.
PATH_CONSTANTS = (
    "MEMORY_FILE",
    "AGENTS_FILE",
    "KANBAN_FILE",
    "THEME_FILE",
    "THEME_LIVE_FILE",
    "GATEWAY_CONFIG_FILE",
    "QUICKCHAT_SESSIONS_DIR",
    "COUPLED_AGENTS_FILE",
    "THEMES_DIR",
    "FRAMEWORKS_FILE",
    "BOARDROOM_HISTORY_FILE",
    "ROLES_FILE",
    "SERVICES_FILE",
    "HERMES_PROFILES_DIR",
    "_SKILL_INDEX_DISK_PATH",
    "SETTINGS_FILE",
    "KANBAN_CARDS_FILE",
    "CONFIG_FILE",
)


def main() -> int:
    # main.py schreibt beim Import Statuszeilen auf stdout ("Operations API
    # mounted successfully."). Die wuerden das JSON unlesbar machen, deshalb
    # waehrend des Imports nach stderr umleiten.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        module = importlib.import_module("main")
    finally:
        sys.stdout = real_stdout

    missing = [name for name in PATH_CONSTANTS if not hasattr(module, name)]
    if missing:
        print("FEHLER: nicht gebunden in main: %s" % missing, file=sys.stderr)
        return 1

    resolved = {name: str(getattr(module, name)) for name in PATH_CONSTANTS}
    print(json.dumps(resolved, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

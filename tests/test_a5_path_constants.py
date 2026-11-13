"""Regressionstest: die aufgeloesten Pfad-Konstanten bleiben unveraendert.

Die Baselines entstehen mit `scripts/path_constants_snapshot.py` und liegen
unter `scripts/parity_baselines/paths_before_{host,container}.json`. Host und
Container leiten die Pfade unterschiedlich ab (`/mnt/raid/...` vs `/app/...`),
deshalb wird je Umgebung die passende Baseline verglichen.

Ehrlich benannt: dieser Test ist **kein** Rot-Beweis fuer die Auslagerung —
die Auslagerung sollte ja gerade wertegleich sein. Er friert den Ist-Stand ein
und wird rot, sobald jemand einen Pfad aendert, ohne die Baseline mitzuziehen.
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(REPO, "scripts", "parity_baselines")

# Im Container existiert /app/data, auf dem Host nicht (dort ist MEMORY_DIR=".").
IN_CONTAINER = os.path.exists("/app/data")
BASELINE = os.path.join(
    BASELINE_DIR,
    "paths_before_container.json" if IN_CONTAINER else "paths_before_host.json",
)


def test_path_constants_match_environment_baseline():
    """Jede Pfad-Konstante in main liefert genau den Wert der Baseline."""
    assert os.path.exists(BASELINE), "Baseline fehlt: %s" % BASELINE
    expected = json.load(open(BASELINE, encoding="utf-8"))

    sys.path.insert(0, REPO)
    import main

    missing = [name for name in expected if not hasattr(main, name)]
    assert not missing, "Pfad-Konstante nicht in main gebunden: %s" % missing

    mismatches = {}
    for name, want in expected.items():
        got = str(getattr(main, name))
        if got != want:
            mismatches[name] = {"baseline": want, "jetzt": got}

    assert not mismatches, (
        "Pfad-Konstanten weichen von %s ab: %s" % (os.path.basename(BASELINE), mismatches)
    )

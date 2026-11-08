"""F-15 / F-16 — zwei Frontend-Befunde aus dem Review vom 08.11.

Rot gegen `0f6c762f` (und damit auch gegen den Ursprungsstand `3269f7e1`):

* **F-15** ``static/js/agent_profiles.js``: ``renderHermesProfilesList()`` ruft bei
  leerem Kader ``loadHermesProfilesFromServer()``, das nach dem Abruf wieder
  ``renderHermesProfilesList()`` aufruft. ``isLoadingProfiles`` wird in diesem
  Paar nie gesetzt -> Endlosschleife, dauerhaft ``GET /api/hermes/profiles``
  (110 KB je Runde), wenn der Kader legitim leer ist.
* **F-16** ``static/js/operations_kanban.js``: jedes ``kanban_updated`` /
  ``task_status`` / ``mission_created`` loest sofort ``loadOperationsData(false)``
  aus (4 parallele Fetches, kein Debounce, kein In-Flight-Guard) -> ueberlappende
  Antworten, "die aeltere gewinnt" und ueberschreibt das Board.

Geprueft wird statisch am Quelltext (wie in ``tests/test_orange_a_frontend.py``),
weil beide Dateien ohne Build-Schritt direkt ausgeliefert werden.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _func_body(source: str, signature: str) -> str:
    """Rumpf einer Funktion, naiv per Klammerzaehlung ab ``signature``."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
    raise AssertionError(f"Funktion nicht geschlossen: {signature}")


# --------------------------------------------------------------- F-15

def test_f15_load_from_server_hat_einmal_guard() -> None:
    body = _func_body(_read("static/js/agent_profiles.js"),
                      "async function loadHermesProfilesFromServer()")
    assert "_profilesFetchInFlight" in body, "kein In-Flight-Guard im Abruf"
    assert "_profilesFetchSettled" in body, "kein Einmal-Guard im Abruf"
    # Der Guard muss VOR dem fetch greifen, sonst hilft er nichts.
    assert body.index("_profilesFetchSettled") < body.index("fetch("), (
        "Guard steht hinter dem fetch() — die Schleife bleibt"
    )
    assert "finally" in body, "In-Flight-Flag wird bei Fehler nicht zurueckgesetzt"


def test_f15_render_stoesst_nur_einmal_an() -> None:
    body = _func_body(_read("static/js/agent_profiles.js"),
                      "function renderHermesProfilesList()")
    assert "_profilesFetchSettled" in body, "Render kennt den Einmal-Guard nicht"
    assert "if (!isLoadingProfiles)" not in body, (
        "alter Zustand: isLoadingProfiles wird in diesem Paar nie gesetzt"
    )
    # Genau ein Anstoss im Leerzweig, danach ein echter Leerzustand.
    assert body.count("loadHermesProfilesFromServer()") == 1
    assert "Keine Agentenprofile vorhanden." in body, "kein echter Leerzustand"


def test_f15_force_reload_setzt_guard_zurueck() -> None:
    body = _func_body(_read("static/js/agent_profiles.js"),
                      "async function loadHermesProfilesView(force = false)")
    assert re.search(r"if\s*\(\s*force\s*\)\s*_profilesFetchSettled\s*=\s*false",
                     body), "manuelles Neuladen kann den Kader nicht mehr holen"


# --------------------------------------------------------------- F-16

def test_f16_sse_handler_laedt_nicht_mehr_direkt() -> None:
    source = _read("static/js/operations_kanban.js")
    handler = _func_body(source, "_opsEventSource.onmessage = function(event)")
    assert "loadOperationsData(" not in handler, (
        "SSE-Handler ruft weiterhin ungebremst loadOperationsData()"
    )
    assert "scheduleOpsKanbanReload()" in handler, "kein gebuendelter Reload"


def test_f16_debounce_und_inflight_guard() -> None:
    source = _read("static/js/operations_kanban.js")
    sched = _func_body(source, "function scheduleOpsKanbanReload()")
    assert "setTimeout" in sched, "kein Debounce"
    assert "_opsReloadTimer" in sched, "Debounce-Timer fehlt"

    runner = _func_body(source, "async function _runOpsKanbanReload()")
    assert "_opsReloadInFlight" in runner, "kein In-Flight-Guard"
    assert runner.count("loadOperationsData(") == 1, (
        "mehr als ein Voll-Reload im Runner"
    )
    assert "_opsReloadPending" in runner, (
        "waehrend des Laufs eingetroffene Events gehen verloren"
    )
    assert "finally" in runner, "In-Flight-Flag wird bei Fehler nicht zurueckgesetzt"


def test_f16_debounce_fenster_ist_endlich() -> None:
    sched = _func_body(_read("static/js/operations_kanban.js"),
                       "function scheduleOpsKanbanReload()")
    match = re.search(r"setTimeout\([^,]+,\s*(\d+)\s*\)", sched, re.S)
    assert match, "Debounce ohne Verzoegerung"
    delay = int(match.group(1))
    assert 50 <= delay <= 2000, f"Debounce-Fenster unplausibel: {delay} ms"

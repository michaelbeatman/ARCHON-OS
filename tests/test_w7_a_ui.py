"""W7-A: Regressionstests fuer UI-/Wiring-Funde aus Domäne 01.

Geprueft werden die Produktivpfade (00_SOLL_SPEC.md §0: Produzent ->
Konsument -> Effekt -> Verifikation). Bei JS/TSX wird der ausgelieferte
Produktivcode statisch geprueft und zusaetzlich mit echten Helpern
ausgewertet; bei Python werden die echten Helper/Endpoints aufgerufen.

Funde: D01-M3 (computer_use ohne Runtime), D01-M4 (unvollstaendige MC-
Status-Map), D01-M5 (SSE-Filter ignorieren task_cancelled/task_status).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from fastapi import Request

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Echte Helper: statische Produktivpfad-Auswertung der JS/TSX-Quellen
# ---------------------------------------------------------------------------

def _source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _string_list(source: str, declaration: str) -> tuple[str, ...]:
    """Werte einer JS/TS-Array-Deklaration als echte Tuple auslesen."""
    start = source.find(declaration)
    assert start >= 0, f"Deklaration fehlt: {declaration}"
    # Erst nach dem '=' suchen: TSX hat davor `string[]` als Typannotation.
    equals = source.find("=", start)
    assert equals >= 0, f"Zuweisung fehlt: {declaration}"
    open_bracket = source.find("[", equals)
    close_bracket = source.find("]", open_bracket)
    assert 0 <= open_bracket < close_bracket, f"Array fehlt: {declaration}"
    return tuple(re.findall(r"['\"]([^'\"]+)['\"]", source[open_bracket + 1:close_bracket]))


def _object_body(source: str, declaration: str) -> str:
    """Koerper eines JS-Objekt-Literals bis zum schliessenden '};'."""
    start = source.find(declaration)
    assert start >= 0, f"Deklaration fehlt: {declaration}"
    end = source.find("};", start)
    assert end > start, f"Objektende fehlt: {declaration}"
    return source[start:end]


def _groups(source: str, declaration: str) -> dict[str, tuple[str, ...]]:
    """Statusgruppen (Spalte -> Status-Tuple) aus dem Produktivcode lesen."""
    body = _object_body(source, declaration)
    result: dict[str, tuple[str, ...]] = {}
    for col in ("todo", "in_progress", "review", "blocked", "done"):
        match = re.search(r"\b" + col + r"\s*:\s*\[([^\]]*)\]", body)
        assert match is not None, f"Spalte fehlt: {col} in {declaration}"
        result[col] = tuple(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))
    return result


def mc_column_for_status(
    groups: dict[str, tuple[str, ...]], status: str
) -> str | None:
    """Echter Helper: Spalte fuer einen Maschinen-Status (wie mcKanbanColumnForStatus)."""
    for col, statuses in groups.items():
        if status in statuses:
            return col
    return None


def _handler_block(source: str, marker: str) -> str:
    """Koerper eines useArchonEvents-Handlers bis zum schliessenden '});'."""
    start = source.find(marker)
    assert start >= 0, f"Handler fehlt: {marker}"
    end = source.find("  });", start)
    assert end > start, f"Handlerende fehlt: {marker}"
    return source[start:end]


# ---------------------------------------------------------------------------
# D01-M3 — computer_use ohne CUA-Runtime
# ---------------------------------------------------------------------------

def test_computer_use_not_in_default_tools():
    from archon.core.profiles import DEFAULT_HERMES_TOOLS

    assert "computer_use" not in DEFAULT_HERMES_TOOLS
    js = _source("static/js/agent_profiles.js")
    assert "computer_use" not in _string_list(js, "const DEFAULT_HERMES_TOOLS")


def test_tool_availability_helper_is_single_source_of_truth():
    from archon.core.profiles import (
        UNAVAILABLE_TOOLS,
        is_tool_available,
        tool_availability,
    )

    assert "computer_use" in UNAVAILABLE_TOOLS
    assert is_tool_available("computer_use") is False
    assert is_tool_available("browser") is True

    descriptor = tool_availability("computer_use")
    assert descriptor["id"] == "computer_use"
    assert descriptor["available"] is False
    assert descriptor["runtime"] == "unavailable"
    assert "keine computer-use-runtime" in str(descriptor["reason"]).lower()
    assert tool_availability("browser") == {"id": "browser", "available": True}


def test_bot_screen_endpoint_reports_honest_state(monkeypatch):
    from archon.routers import operations_bot_screen as obs

    assert obs.computer_use_runtime_available() is False
    # Konsument im Produktivpfad aufrufen, nicht nur den Quelltext lesen.
    monkeypatch.setattr(
        obs,
        "_bot_screen_state",
        dict(
            obs._bot_screen_state,
            aborted=False,
            agent_authorized=True,
            mouse_control_enabled=True,
        ),
    )
    monkeypatch.setattr(obs, "require_admin_or_503", lambda _request: None)
    result = obs.interact_with_bot_screen(
        cast(Request, object()),
        obs.ScreenInteractionModel(action="click", x=10, y=20),
    )
    assert result["status"] == "simulated"
    assert result["simulation"] is True
    assert result["tool"] == "computer_use"
    assert result["available"] is False
    assert result["runtime"] == "unavailable"
    assert result["reason"] == obs.tool_availability("computer_use")["reason"]
    assert result["echo"]["action"] == "click"


def test_js_tool_catalog_disables_computer_use():
    js = _source("static/js/agent_profiles.js")
    entry = next(line for line in js.splitlines() if 'id: "computer_use"' in line)
    assert "available: false" in entry
    assert 'runtime: "unavailable"' in entry
    assert "Autonome Steuerung" not in entry  # keine Werbung ohne Runtime
    assert "Demo" in entry

    # Echter Helper im ausgelieferten Legacy-UI muss die Zuweisung blocken.
    assert "const UNAVAILABLE_HERMES_TOOLS" in js
    assert "function isHermesToolAvailable" in js
    add_start = js.find("async function addToolToProfileById")
    assert add_start >= 0
    assert "isHermesToolAvailable(toolId)" in js[add_start:add_start + 900]


# ---------------------------------------------------------------------------
# D01-M4 — MC-Status-Map vollstaendig
# ---------------------------------------------------------------------------

def test_mc_status_groups_match_operations_groups():
    mc = _source("static/js/mission_control_cockpit.js")
    ops = _source("static/js/operations_kanban.js")
    mc_groups = _groups(mc, "const MC_KANBAN_GROUPS")
    ops_groups = _groups(ops, "const OPS_COLUMN_GROUPS")

    # Paritaet mit dem Vorbild — MC darf nicht auseinanderlaufen.
    assert mc_groups == ops_groups

    # Echter Helper: jeder erzeugte Status muss eine Rendering-Spalte haben.
    for status in ("queued", "awaiting_gate", "cancelled", "paused", "failed"):
        assert mc_column_for_status(mc_groups, status) is not None, status


def test_mc_badges_and_renderer_cover_new_statuses():
    mc = _source("static/js/mission_control_cockpit.js")
    badges = _object_body(mc, "const MC_KANBAN_BADGE_KEYS")
    for status in ("queued", "awaiting_gate", "cancelled", "paused", "failed"):
        assert f"{status}:" in badges, status

    # Der Helper ist im echten Renderpfad verdrahtet (nicht nur definiert).
    assert "function mcKanbanColumnForStatus" in mc
    assert "mcKanbanColumnForStatus(t.status)" in mc
    assert "MC_KANBAN_BADGE_KEYS[t.status]" in mc


# ---------------------------------------------------------------------------
# D01-M5 — SSE-Event-Filter zentral und vollständig
# ---------------------------------------------------------------------------

def test_sse_event_constant_is_central_and_identical():
    js = _source("static/js/operations_kanban.js")
    exec_tsx = _source("frontend/src/components/ExecutiveCockpit.tsx")
    wf_tsx = _source("frontend/src/components/WorkflowCockpit.tsx")

    js_events = _string_list(js, "const ARCHON_KANBAN_SSE_EVENTS")
    ts_events = _string_list(exec_tsx, "export const ARCHON_KANBAN_SSE_EVENTS")
    assert set(js_events) == set(ts_events)
    assert len(js_events) > 0

    for events in (js_events, ts_events):
        assert "task_cancelled" in events
        assert "task_status" in events
        assert "kanban_updated" in events

    # Beide React-Consumer nutzen dieselbe Konstante statt Literallisten.
    assert "ARCHON_KANBAN_SSE_EVENTS.includes(event.type)" in exec_tsx
    assert "ARCHON_KANBAN_SSE_EVENTS.includes(event.type)" in wf_tsx
    assert "ARCHON_KANBAN_SSE_EVENTS" in wf_tsx
    assert "from './ExecutiveCockpit'" in wf_tsx
    assert "window.ARCHON_KANBAN_SSE_EVENTS" in js


def test_board_and_cockpit_refresh_after_cancel():
    js = _source("static/js/operations_kanban.js")
    reload_events = _string_list(js, "const ARCHON_KANBAN_BOARD_RELOAD_EVENTS")
    assert "task_cancelled" in reload_events
    assert "task_status" in reload_events
    assert "ARCHON_KANBAN_BOARD_RELOAD_EVENTS.includes(evType)" in js
    assert "scheduleOpsKanbanReload();" in js

    exec_tsx = _source("frontend/src/components/ExecutiveCockpit.tsx")
    handler = _handler_block(exec_tsx, "useArchonEvents((event) => {")
    assert "if (![" not in handler  # keine verstreuten Literallisten mehr
    assert "ARCHON_KANBAN_SSE_EVENTS.includes(event.type)" in handler
    assert "listKanbanTasks()" in handler  # Refresh nach Cancel
    assert "setTasks(" in handler

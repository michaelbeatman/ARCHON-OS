"""
Differenztest für B1 in der Orchestrierung.

Kernszenario: `_execute_mission_control_task` hält den Store über einen langen
LLM-Aufruf (`await dispatcher…`) als Snapshot. In dieser Zeit verschiebt der
Nutzer einen *anderen* Task im Board.

* Ohne `update_mc` schreibt die Funktion am Ende ihren kompletten Snapshot
  zurück → die Nutzeränderung ist weg.
* Mit `update_mc` wird nur der eigene Task (plus neue Sub-Tasks) gemerged →
  die Nutzeränderung überlebt.

Der erste Test ist absichtlich so gebaut, dass er gegen das alte Verhalten
fehlschlägt — ein Test, der beide Wege grün sieht, wäre kein Beweis.
"""

import asyncio
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import archon.core.mission_control as mc  # noqa: E402
from archon.core.orchestration import _execute_mission_control_task  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mission_control_data.json"
    path.write_text(json.dumps({
        "tasks": [
            {"id": "t1", "title": "Läuft", "agent_id": "micha", "agent_name": "Micha",
             "status": "in_progress", "capture_input": "Aufgabe"},
            {"id": "t2", "title": "Anderer", "agent_id": "sandy", "agent_name": "Sandy",
             "status": "backlog"},
        ],
        "audit_logs": [],
    }), encoding="utf-8")
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(path))
    return path


def _status(path, tid):
    data = json.loads(path.read_text(encoding="utf-8"))
    return next(t for t in data["tasks"] if t["id"] == tid)["status"]


def _dispatcher_that_moves_other_task(store):
    """Simuliert den Nutzer, der waehrend des LLM-Calls t2 verschiebt."""

    class _D:
        async def dispatch_to_omniroute_or_container(self, **kwargs):
            def _move(data):
                next(t for t in data["tasks"] if t["id"] == "t2")["status"] = "in_progress"
            await asyncio.to_thread(mc.update_mission_control_data, _move)
            return {"content": "Erledigt. Keine Nominierung."}

    return _D()


async def _noop(*args, **kwargs):
    return None


def _kwargs(store, dispatcher, **extra):
    return dict(
        dispatcher=dispatcher,
        load_mc=mc._load_mission_control_data,
        save_mc=mc._save_mission_control_data,
        ticker=lambda *a, **k: None,
        get_profiles=lambda: [],
        sync_obsidian=lambda task: "/tmp/obs/bericht.md",
        trigger_sandy=_noop,
        fan_in=_noop,
        **extra,
    )


@pytest.mark.asyncio
async def test_parallel_change_survives_with_update_mc(store):
    """Mit atomarem Merge bleibt die parallele Nutzeränderung erhalten."""
    dispatcher = _dispatcher_that_moves_other_task(store)

    await _execute_mission_control_task(
        "t1", **_kwargs(store, dispatcher, update_mc=mc.update_mission_control_data)
    )

    assert _status(store, "t1") == "completed"     # eigener Task geschrieben
    assert _status(store, "t2") == "in_progress"   # Nutzeränderung erhalten


@pytest.mark.asyncio
async def test_parallel_change_is_lost_without_update_mc(store):
    """Gegenprobe: ohne update_mc überschreibt der Snapshot die Nutzeränderung.

    Dieser Test dokumentiert den Altbestand. Er muss grün sein, solange der
    alte Pfad existiert — und würde rot, wenn jemand den Fix wieder ausbaut,
    ohne den alten Pfad zu entfernen.
    """
    dispatcher = _dispatcher_that_moves_other_task(store)

    await _execute_mission_control_task("t1", **_kwargs(store, dispatcher))

    assert _status(store, "t1") == "completed"
    assert _status(store, "t2") == "backlog"       # Änderung verloren (Altverhalten)

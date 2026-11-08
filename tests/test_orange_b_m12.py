"""Regressionstest M-12: _save_kanban_meta darf die Sperre nicht umgehen.

Die Funktion war ein zweiter, ungesperrter Writer fuer kanban_meta.json
(direkt via _write_atomic). Der Fix leitet die Schreibung durch den gelockten
update_kanban_meta-Pfad, damit der naechste Aufrufer die Serialisierung nicht
unterlaufen kann.
"""

import os
import sys
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.operations_api as ops  # noqa: E402


def test_save_kanban_meta_goes_through_locked_update():
    mutator_calls = []
    meta = {"tasks": {"t1": {"quality_review": {}}}, "wip": {}}

    def fake_update(mutator):
        mutator_calls.append(mutator)
        current = {"tasks": {}, "wip": {}}
        result = mutator(current)
        return current, result

    with mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=fake_update) as upd:
        ops._save_kanban_meta(meta)

    upd.assert_called_once()
    assert len(mutator_calls) == 1
    # Der uebergebene Meta-Stand erreicht den (gelockten) Schreibpfad vollstaendig.
    assert mutator_calls[0]({"tasks": {}, "wip": {}}) == meta


def test_save_kanban_meta_does_not_call_atomic_directly():
    with mock.patch("backend.kanban_sidecar._write_atomic") as direct, \
         mock.patch("backend.kanban_sidecar.update_kanban_meta", side_effect=lambda m: ({"tasks": {}, "wip": {}}, None)):
        ops._save_kanban_meta({"tasks": {}, "wip": {}})
    direct.assert_not_called()

"""Regressionstests R-18 + R-19 fuer archon/core/orchestration.py.

R-18: _merge_task_delta duerfen NUR Tasks wieder einfuegen, die zu DIESEM
Task gehoeren — verworfene/fremde Tasks aus der alten Snapshot-Liste wurden
sonst nach dem LLM-await wiederbelebt.

R-19: Auto-Hire Default-Import zeigte auf archon.core.runtime (gibt es dort
nicht) und schrieb in die Schattenkopie archon/core/agent_profiles.json;
ein wirkungsloses Status-Update meldete trotzdem "aktiviert".
"""

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.core import orchestration as orch  # noqa: E402


# ---------------------------------------------------------------- R-18

def test_merge_task_delta_does_not_resurrect_deleted_tasks():
    fresh = {"tasks": [
        {"id": "t-1", "title": "aktuell"},
    ]}
    local_data = {"tasks": [
        {"id": "t-1", "title": "snapshot", "status": "in_progress"},
        # t-2 wurde vom Nutzer waehrend des awaits verworfen (war vor dem Lauf da);
        # t-7 ist ein fremder Task.
        {"id": "t-2", "title": "verworfen", "parent_task_id": "t-1"},
        {"id": "t-7", "title": "fremd", "parent_task_id": "anderswo"},
    ]}
    orig_ids = {"t-1", "t-2", "t-7"}

    orch._merge_task_delta(fresh, local_data, "t-1", local_data["tasks"], orig_ids)

    ids = {t["id"] for t in fresh["tasks"]}
    assert "t-2" not in ids, "verworfener Task wurde wiederbelebt"
    assert "t-7" not in ids, "fremder Task wurde wiederbelebt"


def test_merge_task_delta_keeps_newly_created_subtasks():
    fresh = {"tasks": [{"id": "t-1", "title": "aktuell"}]}
    local_data = {"tasks": [
        {"id": "t-1", "title": "snapshot", "subtask_ids": ["t-5"]},
        # t-5 ist waehrend des Laufs entstanden (id nicht in orig_ids)
        {"id": "t-5", "title": "neu vom LLM", "parent_task_id": "t-1"},
    ]}
    orig_ids = {"t-1"}

    orch._merge_task_delta(fresh, local_data, "t-1", local_data["tasks"], orig_ids)

    ids = {t["id"] for t in fresh["tasks"]}
    assert "t-5" in ids


# ---------------------------------------------------------------- R-19

def test_hire_reports_failure_when_status_update_noop():
    ticker_calls = []
    with mock.patch("archon.core.runtime.add_ticker", side_effect=lambda *a: ticker_calls.append(a)):
        ok = orch._paperclip_hire_profile_by_id(
            "agent-x", [], current_task_id="t-1",
            set_status=lambda *a, **k: False,
        )
    assert ok is False
    assert not any("aktiviert" in t[1] for t in ticker_calls), "falscher Erfolgs-Ticker"


def test_hire_reports_success_when_status_update_ok():
    with mock.patch("archon.core.runtime.add_ticker"):
        ok = orch._paperclip_hire_profile_by_id(
            "agent-x", [{"id": "agent-x", "person_name": "Agent X"}],
            set_status=lambda *a, **k: True,
        )
    assert ok is True


def test_set_agent_profile_status_writes_to_root_ssot(tmp_path):
    ssot = tmp_path / "agent_profiles.json"
    with open(ssot, "w", encoding="utf-8") as f:
        json.dump([{"id": "agent-x", "name": "X", "status": "standby"}], f)

    with mock.patch.object(orch, "APP_ROOT", str(tmp_path)), \
         mock.patch("archon.core.profiles.create_rolling_backup") as rb, \
         mock.patch("archon.core.profiles.invalidate_hermes_profiles_cache"):
        ok = orch._set_agent_profile_status("agent-x", "active", "t-1")

    assert ok is True
    with open(ssot, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["status"] == "active"
    assert data[0]["current_task_id"] == "t-1"
    rb.assert_called_once_with(str(ssot), max_backups=3)


def test_set_agent_profile_status_unknown_profile_returns_false(tmp_path):
    ssot = tmp_path / "agent_profiles.json"
    with open(ssot, "w", encoding="utf-8") as f:
        json.dump([{"id": "agent-x", "name": "X", "status": "standby"}], f)

    with mock.patch.object(orch, "APP_ROOT", str(tmp_path)):
        ok = orch._set_agent_profile_status("gibt-es-nicht", "active")

    assert ok is False
    with open(ssot, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["status"] == "standby"

"""Regressionstests fuer den Multi-Agent-Rest (H-2, H-3, H-4, M-3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------- M-3
def test_p2_scorecard_does_not_invent_metrics():
    from backend.agent_scorecard_engine import AgentScorecardEngine

    # Leere DB -> keine erfundenen 98 %/95 %.
    engine = AgentScorecardEngine(
        kanban_db=str(REPO_ROOT / "tests" / "_nonexistent_kanban.db"),
        memory_db=str(REPO_ROOT / "tests" / "_nonexistent_memory.db"),
    )
    card = engine.get_scorecard("agent_without_data")
    assert card["data_sufficient"] is False
    assert card["success_rate"] is None
    assert card["feedback_rate"] is None
    assert card["autonomy_rate"] is None


# ---------------------------------------------------------------- H-3
def test_p2_soul_mode_status_supports_per_agent():
    import scripts.sync_soul_modes as ssm

    source = Path(ssm.__file__).read_text(encoding="utf-8")
    assert "def get_current_soul_mode_status(agent_id" in source
    assert "invalidate_hermes_profiles_cache()" in source


def test_p2_apply_soul_mode_invalidates_cache():
    source = (REPO_ROOT / "scripts/sync_soul_modes.py").read_text(encoding="utf-8")
    # Die Invalidierung muss zentral in apply_soul_mode stehen, nicht nur
    # in einzelnen Aufrufern.
    assert "from archon.core.profiles import invalidate_hermes_profiles_cache" in source


# ---------------------------------------------------------------- H-4
def test_p2_supervisor_comes_from_org_chart():
    import scripts.sync_soul_modes as ssm

    sup = ssm._supervisor_from_org_chart("senior_fullstack_engineer")
    assert sup == "system_architect_orchestrator"
    unknown = ssm._supervisor_from_org_chart("does_not_exist")
    assert unknown == "executive_decision_architect"


def test_p2_supervisor_is_not_a_display_name():
    source = (REPO_ROOT / "scripts/sync_soul_modes.py").read_text(encoding="utf-8")
    assert "supervisor = _supervisor_from_org_chart(agent_id)" in source
    # Der alte Wikilink-Fallback darf nicht mehr als Supervisor dienen.
    assert 'sup_m = re.search(r"supervisor:' not in source


# ---------------------------------------------------------------- H-2
def test_p2_teams_use_real_profile_ids():
    teams = json.loads((REPO_ROOT / "config/teams.json").read_text(encoding="utf-8"))
    profiles = json.loads((REPO_ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    ids = {p["id"] for p in profiles}
    assert "hermes-lead" not in ids  # alter Phantom-Lead entfernt

    for team in teams.get("teams", []):
        assert team.get("lead_id") in ids
        for member in team.get("member_agent_ids", []):
            assert member in ids


def test_p2_domain_activation_is_fail_open():
    from backend.domain_activation import filter_active_profiles, is_domain_active

    profiles = [{"id": "a", "category": "1. Strategie, Führung & Lebensplanung"},
                {"id": "b", "category": "7. Tech, Software & Data"}]
    # Keine active_domains -> alle aktiv (Default, rueckwaerts kompatibel).
    assert len(filter_active_profiles(profiles, active_ids=[])) == 2
    # Mit active_domains -> nur passende Kategorie.
    active = filter_active_profiles(profiles, active_ids=["1"])
    assert [p["id"] for p in active] == ["a"]
    assert is_domain_active(profiles[1], active_ids=["1"]) is False


def test_p2_domain_filter_is_wired_into_profile_listing():
    source = (REPO_ROOT / "archon/core/profiles.py").read_text(encoding="utf-8")
    assert "from backend.domain_activation import filter_active_profiles" in source
    assert "enriched_profiles = filter_active_profiles(enriched_profiles)" in source

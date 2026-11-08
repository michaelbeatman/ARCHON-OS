"""Rot-Beweis fuer M-06, M-07, M-08, M-16, M-17.

M-06: backend/dag_scheduler.py: decompose_task wirft NameError auf task_id.
M-07: archon/routers/skills.py: execute_mcp_tool wirft NameError auf skills_engine.
M-08: archon/routers/hermes_profiles.py: hire/fire rufen status-Handler ohne request auf (AttributeError).
M-16: main.py: save_agents loescht inaktive und System-Agenten, wenn gefiltertes Array gepostet wird.
M-17: main.py: api_save_theme_live_overrides plaettet bestehende Studio-Rules bei reinem Custom-CSS Save.
"""

import inspect
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
from starlette.requests import Request


def _make_dummy_request(role: str = "admin") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8501),
        "state": {
            "user": {
                "id": "usr_admin",
                "username": "admin",
                "role": role,
                "permissions": {},
            }
        },
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_m06_dag_decompose_task_no_nameerror(monkeypatch):
    """M-06: decompose_task darf keinen NameError auf task_id werfen."""
    from backend.dag_scheduler import DAGScheduler
    import core_dispatcher

    scheduler = DAGScheduler()
    # Mock dispatch_to_omniroute_or_container
    mock_dispatch = AsyncMock(return_value={"content": '[]'})
    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", mock_dispatch)

    # Wenn decompose_task aufgerufen wird:
    res = await scheduler.decompose_task("Test Parent", "Test Description", "orchestrator")
    assert "parent_id" in res


@pytest.mark.asyncio
async def test_m07_skills_mcp_execute_no_nameerror(monkeypatch):
    """M-07: execute_mcp_tool_route darf keinen NameError auf skills_engine werfen."""
    import archon.routers.skills as skills_mod

    req = _make_dummy_request("admin")
    mock_engine = MagicMock()
    mock_engine.mcp.execute_mcp_tool = AsyncMock(return_value={"result": "ok"})
    skills_mod.configure(
        skills_engine=mock_engine,
        api_get_hermes_profiles=lambda: [{"id": "test_agent", "tools": ["mcp__test__tool"]}]
    )

    # Mock plugin_manager
    import backend.plugin_manager as pm_mod
    mock_pm = MagicMock()
    mock_pm.apply_before_tool_execute = AsyncMock(side_effect=lambda t, a, ctx: a)
    mock_pm.apply_after_tool_execute = AsyncMock(side_effect=lambda t, r, ctx: r)
    monkeypatch.setattr(pm_mod, "get_plugin_manager", lambda: mock_pm)

    # Injektion RBAC pass
    from archon.routers import _rbac as rbac_module
    previous = rbac_module._checker
    rbac_module.configure(require_admin=lambda r: {"role": "admin"})
    try:
        res = await skills_mod.api_skills_mcp_execute(
            req,
            tool_name="mcp__test__tool",
            arguments={},
            agent_id="test_agent"
        )
        assert res == {"result": "ok"}
    finally:
        rbac_module._checker = previous


def test_m08_hire_fire_paperclip_passes_request(monkeypatch):
    """M-08: hire/fire-paperclip muessen request an status-Handler weitergeben."""
    import archon.routers.hermes_profiles as hp

    req = _make_dummy_request("admin")

    # Injektion RBAC pass
    from archon.routers import _rbac as rbac_module
    previous = rbac_module._checker
    rbac_module.configure(require_admin=lambda r: {"role": "admin"})

    # Mock status handler to verify request is passed as first argument
    mock_status_fn = MagicMock(return_value={"status": "success", "profile_id": "test_p"})
    monkeypatch.setattr(hp, "api_update_hermes_profile_status", mock_status_fn)

    try:
        hp.api_hire_hermes_profile_paperclip(req, "test_p")
        assert mock_status_fn.called
        args, _ = mock_status_fn.call_args
        assert isinstance(args[0], Request), f"Erstes Argument muss Request sein, war: {type(args[0])}"

        mock_status_fn.reset_mock()
        hp.api_fire_hermes_profile_paperclip(req, "test_p")
        assert mock_status_fn.called
        args2, _ = mock_status_fn.call_args
        assert isinstance(args2[0], Request), f"Erstes Argument muss Request sein, war: {type(args2[0])}"
    finally:
        rbac_module._checker = previous


def test_m16_save_agents_preserves_inactive_and_system_agents(monkeypatch, tmp_path):
    """M-16: save_agents darf inaktive oder System-Agenten nicht loeschen."""
    import main as app_main

    agents_file = tmp_path / "agents.json"
    initial_agents = [
        {"id": "active_agent_1", "name": "Active 1", "active": True},
        {"id": "inactive_agent_2", "name": "Inactive 2", "active": False},
        {"id": "agent-os-container", "name": "System Internal", "active": True},
    ]
    agents_file.write_text(json.dumps(initial_agents, indent=2), encoding="utf-8")

    monkeypatch.setattr(app_main, "WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_main, "AGENTS_FILE", str(tmp_path / "data_agents.json"))

    # Client (z. B. skill_markt.js) sendet nur das gefilterte Array mit active_agent_1
    incoming = [{"id": "active_agent_1", "name": "Active 1 Updated", "active": True}]
    app_main.save_agents(incoming)

    # Nach dem Speichern muessen inactive_agent_2 und agent-os-container erhalten sein!
    saved = json.loads(agents_file.read_text(encoding="utf-8"))
    saved_ids = {a["id"] for a in saved}
    assert "active_agent_1" in saved_ids
    assert "inactive_agent_2" in saved_ids, "Inaktiver Agent wurde geloescht!"
    assert "agent-os-container" in saved_ids, "System-Agent wurde geloescht!"


def test_m17_live_overrides_merge_rules_on_raw_css_save(monkeypatch, tmp_path):
    """M-17: api_save_theme_live_overrides darf bestehende Studio-Rules bei Custom-CSS Save nicht leeren."""
    import main as app_main

    theme_file = tmp_path / "theme_live.json"
    initial_theme = {
        "rules": {
            ".navbar": {"background-color": "red", "color": "white"},
            "#sidebar": {"width": "250px"}
        },
        "rawCss": "/* initial */",
        "textOverrides": {"title": "Archon OS"},
        "htmlOverrides": {}
    }
    theme_file.write_text(json.dumps(initial_theme, indent=2), encoding="utf-8")
    monkeypatch.setattr(app_main, "THEME_LIVE_FILE", str(theme_file))

    # Customizer sendet rawCss mit leeren rules/textOverrides
    customizer_payload = {
        "rawCss": "body { font-size: 14px; }",
        "rules": {},
        "textOverrides": {},
        "htmlOverrides": {}
    }
    app_main.api_save_theme_live_overrides(customizer_payload)

    saved = json.loads(theme_file.read_text(encoding="utf-8"))
    assert saved["rawCss"] == "body { font-size: 14px; }"
    assert ".navbar" in saved["rules"], "Bestehende Live-Studio Rules wurden geloescht!"
    assert saved["textOverrides"].get("title") == "Archon OS", "Text-Overrides wurden geloescht!"

#!/usr/bin/env python3
"""
Unit tests for router configure() functions - verifies dependency injection binding.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch


def test_hermes_profiles_configure():
    """Test that hermes_profiles.configure() binds all required dependencies."""
    from archon.routers import hermes_profiles
    
    # Mock the required functions
    mock_save = MagicMock()
    mock_sync = MagicMock()
    mock_invalidate = MagicMock()
    
    hermes_profiles.configure(
        save_all_agent_profiles=mock_save,
        _sync_org_hierarchy_node=mock_sync,
        invalidate_paperclip_agents_cache=mock_invalidate,
    )
    
    assert "save_all_agent_profiles" in hermes_profiles._DEPS
    assert "_sync_org_hierarchy_node" in hermes_profiles._DEPS
    assert "invalidate_paperclip_agents_cache" in hermes_profiles._DEPS
    
    assert hermes_profiles._DEPS["save_all_agent_profiles"] is mock_save
    assert hermes_profiles._DEPS["_sync_org_hierarchy_node"] is mock_sync
    assert hermes_profiles._DEPS["invalidate_paperclip_agents_cache"] is mock_invalidate


def test_boardroom_configure():
    """Test that boardroom.configure() binds all required dependencies."""
    from archon.routers import boardroom
    
    mock_load_frameworks = MagicMock()
    mock_load_roles = MagicMock()
    mock_api_profiles = MagicMock()
    
    boardroom.configure(
        load_boardroom_frameworks=mock_load_frameworks,
        load_roles=mock_load_roles,
        api_get_hermes_profiles=mock_api_profiles,
    )
    
    assert "load_boardroom_frameworks" in boardroom._DEPS
    assert "load_roles" in boardroom._DEPS
    assert "api_get_hermes_profiles" in boardroom._DEPS
    
    assert boardroom._DEPS["load_boardroom_frameworks"] is mock_load_frameworks
    assert boardroom._DEPS["load_roles"] is mock_load_roles
    assert boardroom._DEPS["api_get_hermes_profiles"] is mock_api_profiles


def test_governance_configure():
    """Test that governance.configure() binds all required dependencies."""
    from archon.routers import governance
    
    mock_load_mc = MagicMock()
    mock_save_mc = MagicMock()
    mock_api_profiles = MagicMock()
    
    governance.configure(
        _load_mission_control_data=mock_load_mc,
        _save_mission_control_data=mock_save_mc,
        api_get_hermes_profiles=mock_api_profiles,
    )
    
    assert "_load_mission_control_data" in governance._DEPS
    assert "_save_mission_control_data" in governance._DEPS
    assert "api_get_hermes_profiles" in governance._DEPS
    
    assert governance._DEPS["_load_mission_control_data"] is mock_load_mc
    assert governance._DEPS["_save_mission_control_data"] is mock_save_mc
    assert governance._DEPS["api_get_hermes_profiles"] is mock_api_profiles


def test_skills_configure():
    """Test that skills.configure() binds all required dependencies."""
    from archon.routers import skills
    
    mock_skills_engine = MagicMock()
    mock_api_profiles = MagicMock()
    
    skills.configure(
        skills_engine=mock_skills_engine,
        api_get_hermes_profiles=mock_api_profiles,
    )
    
    assert "skills_engine" in skills._DEPS
    assert "api_get_hermes_profiles" in skills._DEPS
    
    assert skills._DEPS["skills_engine"] is mock_skills_engine
    assert skills._DEPS["api_get_hermes_profiles"] is mock_api_profiles


def test_system_configure():
    """Test that system.configure() binds all required dependencies."""
    from archon.routers import system
    
    mock_load_json = MagicMock()
    mock_save_json = MagicMock()
    mock_broadcast = MagicMock()
    
    system.configure(
        _load_json=mock_load_json,
        _save_json=mock_save_json,
        broadcast_event=mock_broadcast,
    )
    
    assert "_load_json" in system._DEPS
    assert "_save_json" in system._DEPS
    assert "broadcast_event" in system._DEPS
    
    assert system._DEPS["_load_json"] is mock_load_json
    assert system._DEPS["_save_json"] is mock_save_json
    assert system._DEPS["broadcast_event"] is mock_broadcast


def test_hermes_profiles_status_endpoint_calls_save():
    """Test that api_update_hermes_profile_status calls save_all_agent_profiles."""
    from archon.routers import hermes_profiles
    
    mock_save = MagicMock()
    mock_invalidate = MagicMock()
    
    hermes_profiles.configure(
        save_all_agent_profiles=mock_save,
        _sync_org_hierarchy_node=MagicMock(),
        invalidate_paperclip_agents_cache=mock_invalidate,
    )
    
    # Need to mock api_get_hermes_profiles since it's used in the handler
    mock_api_profiles = MagicMock(return_value=[
        {"id": "telegram_bot", "name": "Telegram Assistant", "status": "inactive"}
    ])
    # Since api_get_hermes_profiles is imported from archon.core.profiles, we need to patch it
    import archon.core.profiles as profiles_module
    original = profiles_module.api_get_hermes_profiles
    profiles_module.api_get_hermes_profiles = mock_api_profiles
    
    try:
        # Also need to mock add_ticker
        import archon.core.runtime as runtime_module
        original_ticker = runtime_module.add_ticker
        runtime_module.add_ticker = MagicMock()
        
        try:
            # RBAC: Admin-Route — dieser Test prueft das Speichern, nicht die Rolle.
            from archon.routers import _rbac as rbac_module
            previous = rbac_module._checker
            rbac_module.configure(require_admin=lambda request: {"role": "admin"})
            try:
                result = hermes_profiles.api_update_hermes_profile_status(
                    type('obj', (object,), {'headers': {}})(),
                    "telegram_bot",
                    type('obj', (object,), {'status': 'active'})()
                )
            finally:
                rbac_module._checker = previous
            assert result["status"] == "success"
            assert result["new_status"] == "active"
            mock_save.assert_called_once()
            mock_invalidate.assert_called_once()
        finally:
            runtime_module.add_ticker = original_ticker
    finally:
        profiles_module.api_get_hermes_profiles = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
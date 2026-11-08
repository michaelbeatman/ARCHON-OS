import os
import json
import pytest
from unittest.mock import patch, MagicMock


def test_m18_api_get_agents_enriches_profiles(monkeypatch):
    """M-18: /api/agents muss mit agent_profiles.json harmonisiert sein (avatar_url/runtime_status)."""
    import main as main_mod

    raw_agents = [{"id": "coder", "name": "Coder Agent", "role": "Developer"}]
    profiles = [{"id": "coder", "avatar_url": "/static/avatars/coder.png", "runtime_status": "idle"}]

    monkeypatch.setattr(main_mod, "load_agents", lambda: raw_agents)
    monkeypatch.setattr("archon.core.profiles.api_get_hermes_profiles", lambda: profiles)

    res = main_mod.api_get_agents()
    assert len(res) == 1
    assert res[0].get("avatar_url") == "/static/avatars/coder.png", "M-18 BUG: avatar_url wurde nicht aus agent_profiles angereichert!"
    assert res[0].get("runtime_status") == "idle", "M-18 BUG: runtime_status wurde nicht angereichert!"


def test_m19_hermes_profiles_writes_to_repo_root(tmp_path, monkeypatch):
    """M-19: hermes_profiles set_profile_model darf nicht in archon/routers/ schreiben."""
    import archon.routers.hermes_profiles as hp_mod
    import api_provider
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "headers": [], "state": {"user": {"role": "admin"}}}
    req_obj = Request(scope)

    # Lege SSOT in tmp_path an
    ssot_file = tmp_path / "agent_profiles.json"
    ssot_file.write_text(json.dumps([{"id": "coder", "model": "old-model", "provider": "old-prov"}]), encoding="utf-8")

    monkeypatch.setattr("archon.routers._rbac._checker", lambda r: {"role": "admin"})
    monkeypatch.setattr("archon.core.runtime.APP_ROOT", str(tmp_path))
    monkeypatch.setattr(hp_mod, "get_hermes_profiles_base_dirs", lambda: [str(tmp_path / "profiles")])
    monkeypatch.setattr(api_provider, "set_profile_model", lambda p, m, provider: {"status": "ok"})

    # Rufe api_set_hermes_profile_model auf
    req = hp_mod.SetProfileModelRequest(provider="new-prov", model="new-model")
    hp_mod.api_set_hermes_profile_model(req_obj, "coder", req)

    # Pruefe SSOT: Muss aktualisiert sein
    updated_data = json.loads(ssot_file.read_text(encoding="utf-8"))
    assert updated_data[0]["model"] == "new-model", f"M-19 BUG: SSOT agent_profiles.json wurde nicht aktualisiert: {updated_data}"


def test_m20_docker_client_singleton_reflects_env_changes(monkeypatch):
    """M-20: docker_client-Singleton muss Aenderungen an DOCKER_HOST dynamisch uebernehmen."""
    from utils.docker_client import docker_client

    monkeypatch.setenv("DOCKER_HOST", "tcp://custom-proxy:2375")
    kind, target = docker_client._endpoint()

    assert kind == "tcp", f"M-20 BUG: Singleton hat geaenderten DOCKER_HOST ignoriert (kind={kind})"
    assert target == "custom-proxy:2375", f"M-20 BUG: target stimmt nicht: {target}"

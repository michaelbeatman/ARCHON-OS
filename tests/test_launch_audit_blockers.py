"""Regression tests for Launch Audit Blockers (Blocks A, B, C)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_compose_fresh_clone_ready_and_port_collision_free():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for net_name, net_cfg in (compose.get("networks") or {}).items():
        if isinstance(net_cfg, dict):
            assert net_cfg.get("external") is not True, f"Network {net_name} must not be external: true"

    services = compose["services"]
    assert "omniroute" in services, "omniroute must be present in default docker-compose.yml"

    archon_svc = services["archon-os"]
    assert archon_svc.get("user") != "root", "archon-os must not run as root"
    vols = " ".join(archon_svc.get("volumes") or [])
    assert "docker.sock" not in vols, "archon-os must use docker-socket-proxy, not raw docker.sock"

    for pinned_svc in ("n8n", "hermes", "docker-socket-proxy", "omniroute"):
        img = services[pinned_svc]["image"]
        assert ":latest" not in img, f"{pinned_svc} image must be version-pinned, got {img}"

    n8n_env = "\n".join(services["n8n"].get("environment") or [])
    assert "4117fe5182" not in n8n_env, "Hardcoded n8n JWT secret must not appear in compose"

    host_ports: dict[str, str] = {}
    for svc_name, svc_cfg in services.items():
        for port_mapping in svc_cfg.get("ports") or []:
            parts = str(port_mapping).split(":")
            host_port = parts[-2] if len(parts) >= 2 else parts[0]
            # Extract default port if ${VAR:-PORT} syntax is used
            if ":-" in host_port and host_port.endswith("}"):
                host_port = host_port.split(":-")[-1][:-1]
            assert host_port not in host_ports, (
                f"Port collision on {host_port} between {host_ports[host_port]} and {svc_name}"
            )
            host_ports[host_port] = svc_name


def test_dockerfile_supports_arm64_and_copies_backend_packages():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "TARGETARCH" in dockerfile
    assert "aarch64" in dockerfile
    for required_dir in ("archon/", "backend/", "utils/", "plugins/", "config/", "scripts/"):
        assert required_dir in dockerfile, f"Dockerfile missing COPY for {required_dir}"
    assert "USER streamlituser" in dockerfile


def test_public_repo_hygiene_and_70_specialists_ssot():
    assert not (REPO_ROOT / "docs" / "BETRIEB_HANDBUCH_INTERN.md").exists()
    assert not (REPO_ROOT / "docs" / "LAUNCH_PLAN_1000_STARS.md").exists()
    assert not (REPO_ROOT / "archon" / "core" / "agent_profiles.json").exists()
    assert not (REPO_ROOT / "static" / "hermes-webui" / "static").exists()

    profiles = json.loads((REPO_ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    assert len(profiles) == 70
    ids = {p["id"] for p in profiles}
    assert "micha" not in ids
    assert "founder" in ids
    categories = {p["category"] for p in profiles}
    assert len(categories) == 8, f"Expected 8 domains, got {len(categories)}: {sorted(categories)}"


def test_viewer_blocked_on_write_routers_in_multiuser_mode(monkeypatch):
    import main as app_main

    monkeypatch.setattr(app_main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        app_main.auth_service,
        "verify_session",
        lambda tok: {"id": "u_vw", "username": "viewer1", "role": "viewer", "permissions": {}}
        if tok == "tok_viewer"
        else None,
    )
    client = TestClient(app_main.app)
    headers = {"Authorization": "Bearer tok_viewer"}

    for method, path in [
        ("POST", "/api/deals"),
        ("POST", "/api/operations/dunning/run"),
        ("POST", "/api/operations/emails/drafts"),
        ("POST", "/api/memory/save"),
        ("POST", "/api/kanban"),
    ]:
        resp = client.request(method, path, json={}, headers=headers)
        assert resp.status_code == 403, f"Viewer must get 403 on {method} {path}, got {resp.status_code}: {resp.text}"


def test_closing_connection_closes_sqlite_handle_on_with_exit(tmp_path):
    from archon.core.mission_control import _connect_kanban

    db_file = tmp_path / "test_mc.db"
    with _connect_kanban(str(db_file)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT * FROM t")

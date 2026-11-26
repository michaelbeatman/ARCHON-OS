"""v0.6 Satelliten-Haertungstests (PocketBase, Extension, setup_new_machine, update_dist, Plugins)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from plugins.cost_guard.plugin import CostGuardPlugin
from plugins.security_audit_hook.plugin import SecurityAuditPlugin

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_v06_security_audit_plugin_blocks_dotenv_and_sibling_traversal(tmp_path):
    ws = tmp_path / "workspace"
    evil = tmp_path / "workspace_evil"
    ws.mkdir()
    evil.mkdir()
    plugin = SecurityAuditPlugin({"id": "security_audit_hook", "config": {}}, str(ws))

    # Geschwister-Traversal blockiert
    with pytest.raises(PermissionError):
        await plugin.before_tool_execute(
            "read_file", {"path": "../workspace_evil/secret.txt"}, {"workspace_root": str(ws)}
        )

    # .env-Zugriff blockiert
    with pytest.raises(PermissionError):
        await plugin.before_tool_execute(
            "read_file", {"path": ".env"}, {"workspace_root": str(ws)}
        )

    # Normaler Workspace-Pfad erlaubt
    out = await plugin.before_tool_execute(
        "read_file", {"path": "notes/ok.md"}, {"workspace_root": str(ws)}
    )
    assert out == {"path": "notes/ok.md"}


@pytest.mark.asyncio
async def test_v06_cost_guard_plugin_persists_atomically(tmp_path):
    plugin = CostGuardPlugin({"id": "cost_guard", "config": {"daily_budget_usd": 5.0}}, str(tmp_path))
    await plugin.on_task_completed({"id": "t-1"}, {"tokens_used": 500, "cost_usd": 0.125})

    burn_file = tmp_path / "daily_burn.json"
    assert burn_file.is_file()
    data = json.loads(burn_file.read_text(encoding="utf-8"))
    assert data["total_tokens"] == 500
    assert data["spent_usd"] == pytest.approx(0.125)
    # Keine .tmp-Dateien uebrig
    assert list(tmp_path.glob("*.tmp")) == []

    # Negativprobe gegen den echten Atomicity-Fix: ein abgebrochener
    # os.replace darf die Datei nicht verfaelschen. Der im RAM akkumulierte
    # Verbrauch bleibt erhalten und wird beim naechsten sauberen Event
    # nachpersistiert (kein stillerBudget-Reset).
    disk_before = burn_file.read_text(encoding="utf-8")
    with mock.patch("os.replace", side_effect=OSError("simulated replace failure")):
        await plugin.on_task_completed({"id": "t-2"}, {"tokens_used": 900, "cost_usd": 7.0})
    assert burn_file.read_text(encoding="utf-8") == disk_before
    assert plugin.burn_data["total_tokens"] == 1400
    assert plugin.burn_data["spent_usd"] == pytest.approx(7.125)
    assert list(tmp_path.glob("*.tmp")) == []

    await plugin.on_task_completed({"id": "t-3"}, {"tokens_used": 1, "cost_usd": 0.01})
    persisted = json.loads(burn_file.read_text(encoding="utf-8"))
    assert persisted["total_tokens"] == 1401
    assert persisted["spent_usd"] == pytest.approx(7.135)


def test_v06_pocketbase_compose_binds_loopback_only():
    compose = (REPO_ROOT / "pocketbase" / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8090:8090"' in compose
    assert '"127.0.0.1:3002:3002"' in compose
    assert '"8090:8090"' not in compose
    assert '"3002:3002"' not in compose


def test_v06_extension_has_sender_check_filter_escaping_and_modal_debounce():
    bg = (REPO_ROOT / "extension" / "background.js").read_text(encoding="utf-8")
    assert "escapePbFilterValue" in bg
    assert "isAuthorizedSender" in bg
    assert "getPbAuthHeaders" in bg
    content = (REPO_ROOT / "extension" / "content.js").read_text(encoding="utf-8")
    assert "modalDebounceTimer" in content
    assert "lastModalKey" in content


def test_v06_setup_script_protects_data_dir_and_update_dist_includes_archon():
    setup_sh = (REPO_ROOT / "setup_new_machine.sh").read_text(encoding="utf-8")
    assert "chmod -R u+rwX,go-rwx data pocketbase pocketbase-media" in setup_sh
    update_py = (REPO_ROOT / "update_dist.py").read_text(encoding="utf-8")
    assert "'archon'" in update_py
    assert "ARCHON_DIST_TARGETS" in update_py

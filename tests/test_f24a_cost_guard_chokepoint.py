"""F24a (D01): on_task_completed / CostGuard-Hook im backend/tool_runtime.py-Chokepoint."""
from __future__ import annotations

import asyncio
import uuid

from backend.plugin_manager import PluginManager
from backend.tool_runtime import execute_agent_tool
from backend.tool_warrants import issue_warrant


def test_f24a_execute_agent_tool_dispatches_on_task_completed_for_usage(monkeypatch):
    """Positiv- und Negativprobe fuer apply_after_tool_execute -> on_task_completed im MCP/DAG-Pfad."""
    import backend.plugin_manager as pm_mod
    import scripts.archon_mcp_server as mcp_mod

    monkeypatch.setenv("ARCHON_WARRANT_SECRET", "f24a-warrant-secret")
    session_id = f"user:f24a-{uuid.uuid4().hex[:8]}"
    tool_name = "mcp__mail__send"
    warrant = issue_warrant(session_id=session_id, allowed_tools=[tool_name], ttl_seconds=300)

    captured_hooks = []

    class _SpyPluginManager(PluginManager):
        def __init__(self):
            self.plugins = {}

        def get_all_exported_tools(self):
            return []

        async def trigger_hook(self, hook_name, *args, **kwargs):
            captured_hooks.append((hook_name, args, kwargs))
            return []

    spy_pm = _SpyPluginManager()
    monkeypatch.setattr(pm_mod, "get_plugin_manager", lambda: spy_pm)

    # 1. Positivprobe: Tool liefert echte Verbrauchsdaten -> on_task_completed wird dispatched
    class _UsageMcpServer:
        def execute_tool(self, _name, _args):
            return {"status": "ok", "result": "sent", "tokens_used": 1200, "cost_usd": 0.042}

    monkeypatch.setattr(mcp_mod, "ArchonMcpServer", _UsageMcpServer)
    out = asyncio.run(
        execute_agent_tool(
            tool_name=tool_name,
            args={"to": "a@example.org"},
            agent_id=session_id,
            session_id=session_id,
            warrant=warrant,
            requested_by="f24a-tester",
        )
    )
    assert out["status"] == "success", out
    completed = [h for h in captured_hooks if h[0] == "on_task_completed"]
    assert len(completed) == 1
    assert completed[0][1][1]["tokens_used"] == 1200
    assert completed[0][1][1]["cost_usd"] == 0.042

    # 2. Negativprobe: Tool ohne Verbrauchsdaten (frische Session) -> kein Fake-on_task_completed
    captured_hooks.clear()
    session_id_2 = f"user:f24a-neg-{uuid.uuid4().hex[:8]}"
    warrant_2 = issue_warrant(session_id=session_id_2, allowed_tools=[tool_name], ttl_seconds=300)

    class _NoUsageMcpServer:
        def execute_tool(self, _name, _args):
            return {"status": "ok", "result": "sent"}

    monkeypatch.setattr(mcp_mod, "ArchonMcpServer", _NoUsageMcpServer)
    out2 = asyncio.run(
        execute_agent_tool(
            tool_name=tool_name,
            args={"to": "b@example.org"},
            agent_id=session_id_2,
            session_id=session_id_2,
            warrant=warrant_2,
            requested_by="f24a-tester",
        )
    )
    assert out2["status"] == "success", out2
    assert [h for h in captured_hooks if h[0] == "on_task_completed"] == []

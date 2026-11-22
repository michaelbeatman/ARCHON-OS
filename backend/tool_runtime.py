# -*- coding: utf-8 -*-
"""
backend/tool_runtime.py
=======================
Zentraler ToolRuntime-Chokepoint fuer Archon OS (Stufe 2 Konsolidierung).

Vereint:
1. M75 Rollen- & Tool-Isolation (`delegation_isolation.enforce_runtime_tool_gate`)
2. M89 Session-Taint-Guard (`session_taint_guard`)
3. M90 Kryptografische Tool-Warrants (`tool_warrants.verify_warrant_for_call`)
4. Einheitliches Event-Bus- & Audit-Logging fuer alle Tool-Ausfuehrungen
   (Plugins, MCP Gateway, SysOps MCP-REST, DAG-Multi-Turn-Agents).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.delegation_isolation import mark_session_tainted_on_tool_read

logger = logging.getLogger("archon.tool_runtime")


def _emit_tool_event(kind: str, payload: Dict[str, Any]) -> None:
    try:
        from archon.core.runtime import broadcast_event
        broadcast_event("tool_runtime", {"event": kind, **payload})
    except Exception:
        pass
    if kind == "tool.blocked":
        try:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="tool_runtime",
                action="tool_blocked",
                agent_id=str(payload.get("agent_id") or "system"),
                payload=payload,
            )
        except Exception:
            pass


def enforce_tool_execution(
    *,
    agent_id: str = "",
    session_id: str = "default_session",
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    warrant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prueft M75 Isolation, M89 Taint-Guard und optional M90 Tool-Warrant."""
    clean_tool = str(tool_name or "").strip()
    clean_agent = str(agent_id or "").strip()
    clean_session = str(session_id or "default_session").strip()

    # Zentrale PolicyEngine: M75 + M89 + M90 + RBAC an EINER Stelle.
    # Dieser Chokepoint enthält keine eigene Policy-Logik mehr.
    from backend.delegation_isolation import policy_engine

    gate = policy_engine.decide(
        agent_id=clean_agent,
        session_id=clean_session,
        tool_name=clean_tool,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
    )
    if not gate.get("allowed"):
        _emit_tool_event("tool.blocked", {
            "agent_id": clean_agent,
            "session_id": clean_session,
            "tool_name": clean_tool,
            "reason": gate.get("reason", "gate_denied"),
            "gate": gate.get("gate"),
        })
        return gate

    _emit_tool_event("tool.allowed", {
        "agent_id": clean_agent,
        "session_id": clean_session,
        "tool_name": clean_tool,
    })
    return {
        "allowed": True,
        "tool": clean_tool,
        "agent_id": clean_agent,
        "session_id": clean_session,
        "privileged": bool(gate.get("privileged")),
        "obligations": gate.get("obligations") or [],
    }


def record_tool_read_side_effect(session_id: str, tool_name: str) -> None:
    """Markiert eine Session als tainted, sobald externe/untrusted Tool-Outputs gelesen wurden."""
    try:
        mark_session_tainted_on_tool_read(str(session_id or "default_session").strip(), str(tool_name or "").strip())
    except Exception as exc:
        logger.debug(f"[ToolRuntime] Taint-Read-Marker fehlgeschlagen: {exc}")


async def execute_agent_tool(
    *,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    agent_id: str = "",
    session_id: str = "default_session",
    approval_id: Optional[str] = None,
    warrant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Einheitlicher Ausfuehrungspfad fuer Agent- und DAG-Node-Tool-Calls."""
    gate = enforce_tool_execution(
        agent_id=agent_id,
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        warrant=warrant,
    )
    if not gate.get("allowed"):
        return {"status": "blocked", "error": gate.get("reason", "Tool blockiert"), "gate": gate}

    call_args = args if isinstance(args, dict) else {}

    # 1. Zuerst PluginManager pruefen
    try:
        from backend.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        exported = {t.get("name") for t in (pm.get_all_exported_tools() or []) if isinstance(t, dict)}
        if tool_name in exported:
            res = await pm.execute_plugin_tool(tool_name, call_args)
            record_tool_read_side_effect(session_id, tool_name)
            return {"status": "success", "source": "plugin", "result": res}
    except Exception as exc:
        return {"status": "error", "source": "plugin", "error": str(exc)}

    # 2. Danach ArchonMcpServer
    try:
        from scripts.archon_mcp_server import ArchonMcpServer
        res = ArchonMcpServer().execute_tool(tool_name, call_args)
        if isinstance(res, dict) and str(res.get("status") or "").lower() in ("error", "failed", "blocked"):
            return {
                "status": "error",
                "source": "mcp",
                "error": str(res.get("message") or res.get("error") or "MCP-Tool-Fehler"),
                "result": res,
            }
        record_tool_read_side_effect(session_id, tool_name)
        return {"status": "success", "source": "mcp", "result": res}
    except Exception as exc:
        return {"status": "error", "source": "mcp", "error": str(exc)}

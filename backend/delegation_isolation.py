# -*- coding: utf-8 -*-
"""
backend/delegation_isolation.py
===============================
Meilenstein 75: Strikte Rollen- & Tool-Isolation bei Agenten-Delegation
(hermes-teammates-Pattern).

Garantiert, dass delegierte Subagenten ausschliesslich die in ihrem eigenen
Profil (agent_profiles.json) definierten Tools, Skills und Modelle erhalten.
Privilegierte Werkzeuge des aufrufenden Parent-Agenten (z. B. terminal,
filesystem, mcp) werden niemals implizit vererbt.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILES_PATH = os.path.join(WORKSPACE_DIR, "agent_profiles.json")

# Fail-closed Minimal-Set, falls ein Profil keine expliziten Tools definiert hat
MINIMAL_FALLBACK_TOOLS: List[str] = ["web_search"]
PRIVILEGED_TOOLS = frozenset({"terminal", "execute_code", "filesystem", "mcp", "computer_use", "pay", "pay-cli"})


def _load_profiles(profiles_path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = profiles_path or DEFAULT_PROFILES_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def resolve_isolated_execution_scope(
    target_agent_id: str,
    requested_model: str = "",
    profiles: Optional[List[Dict[str, Any]]] = None,
    profiles_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Liefert den strikt isolierten Ausfuehrungs-Scope fuer einen delegierten Agenten.
    Ignoriert Parent-Tools vollstaendig und nutzt nur die Profil-Definition.
    """
    prof_list = profiles if profiles is not None else _load_profiles(profiles_path)
    prof = next((p for p in prof_list if p.get("id") == target_agent_id), None)

    if target_agent_id == "workflow_engine":
        # Benannter Akteur der DAG-/Plugin-Engine: M75 attribuiert Plugin-Laeufe
        # rechenschaftsfähig, statt sie mit leerer agent_id still zu bypassen.
        return {
            "agent_id": target_agent_id,
            "found": True,
            "allowed_tools": ["node_plugin:*"],
            "allowed_skills": [],
            "model": requested_model or "auto/best-coding",
            "provider": "",
            "isolated": True,
        }

    if not prof:
        return {
            "agent_id": target_agent_id,
            "found": False,
            "allowed_tools": list(MINIMAL_FALLBACK_TOOLS),
            "allowed_skills": [],
            "model": requested_model or "auto/best-coding",
            "provider": "",
            "isolated": True,
        }

    raw_tools = prof.get("tools")
    if isinstance(raw_tools, list) and len(raw_tools) > 0:
        allowed_tools = [str(t).strip() for t in raw_tools if str(t).strip()]
    else:
        allowed_tools = list(MINIMAL_FALLBACK_TOOLS)

    raw_skills = prof.get("skills")
    allowed_skills = (
        [str(s).strip() for s in raw_skills if str(s).strip()]
        if isinstance(raw_skills, list)
        else []
    )

    profile_model = str(prof.get("model") or "").strip()
    effective_model = (requested_model or "").strip() or profile_model or "auto/best-coding"
    effective_provider = str(prof.get("provider") or "").strip()

    return {
        "agent_id": target_agent_id,
        "found": True,
        "allowed_tools": allowed_tools,
        "allowed_skills": allowed_skills,
        "model": effective_model,
        "provider": effective_provider,
        "isolated": True,
    }


def is_tool_allowed_for_agent(
    agent_id: str,
    tool_name: str,
    scope: Optional[Dict[str, Any]] = None,
    profiles: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Prueft fail-closed, ob `tool_name` im isolierten Scope des Ziel-Agenten liegt."""
    resolved = scope or resolve_isolated_execution_scope(agent_id, profiles=profiles)
    allowed = set(resolved.get("allowed_tools") or [])
    if "*" in allowed:
        return True
    norm_tool = (tool_name or "").strip()
    if not norm_tool:
        return False
    if "node_plugin:*" in allowed and norm_tool.startswith("node_plugin:"):
        return True
    if norm_tool in allowed:
        return True
    if "mcp" in allowed and (norm_tool.startswith("mcp__") or norm_tool.startswith("mcp_")):
        return True
    return False


def build_isolated_system_prompt_header(scope: Dict[str, Any]) -> str:
    """Erzeugt einen kompakten Isolation-Header fuer delegierte Subagenten."""
    tools_str = ", ".join(scope.get("allowed_tools") or MINIMAL_FALLBACK_TOOLS)
    skills_str = ", ".join(scope.get("allowed_skills") or []) or "none"
    return (
        f"[ISOLATION SCOPE | Agent: @{scope.get('agent_id')} | "
        f"Allowed Tools: {tools_str} | Allowed Skills: {skills_str}]"
    )


UNTRUSTED_INGEST_TOOLS = frozenset({
    "web_search", "browser", "fetch_url", "scrape", "read_email", "fetch_mails",
})


def enforce_runtime_tool_gate(
    agent_id: str,
    session_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    profiles: Optional[List[Dict[str, Any]]] = None,
    taint_db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Harte Laufzeit-Pruefung (M75 + M89) vor jedem Tool-Aufruf:
    1. M75: Prueft, ob `tool_name` im isolierten Profil-Toolset von `agent_id` liegt.
    2. M89: Prueft, ob `session_id` versiegelt (tainted) ist und HITL-Freigabe braucht.
    """
    if not agent_id:
        # M75 fail-closed: Ohne Agenten-Kontext ist keine Profil-Freigabe pruefbar.
        return {
            "allowed": False,
            "blocked": True,
            "gate": "m75_delegation_isolation",
            "reason": "Leere agent_id — M75 fail-closed: Aufrufe brauchen einen Agenten mit Profil-Freigabe.",
        }
    if not is_tool_allowed_for_agent(agent_id, tool_name, profiles=profiles):
        return {
            "allowed": False,
            "blocked": True,
            "gate": "m75_delegation_isolation",
            "reason": f"Agent '@{agent_id}' hat keine Profil-Freigabe fuer Tool '{tool_name}'.",
        }

    from backend.session_taint_guard import check_egress_tool_call
    taint_res = check_egress_tool_call(
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        approval_id=approval_id,
        db_path=taint_db_path,
    )
    if not taint_res.get("allowed", False):
        return {**taint_res, "gate": "m89_session_taint_guard"}

    return {"allowed": True, "blocked": False, "agent_id": agent_id, "tool": tool_name}


def mark_session_tainted_on_tool_read(
    session_id: str,
    tool_name: str,
    taint_db_path: Optional[str] = None,
) -> bool:
    """Versiegelt eine Session automatisch, sobald sie untrusted Web-/Mail-/MCP-Daten liest."""
    norm = (tool_name or "").strip().lower()
    if norm in UNTRUSTED_INGEST_TOOLS or norm.startswith("mcp__"):
        from backend.session_taint_guard import mark_session_tainted
        mark_session_tainted(session_id, source=f"tool:{norm}", reason="Auto-taint nach externem Daten-Read", db_path=taint_db_path)
        return True
    return False

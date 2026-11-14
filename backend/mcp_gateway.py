"""
backend/mcp_gateway.py
======================
M48 — Native Archon OS MCP-Server (/mcp Gateway) für Claude Desktop, Cursor & VS Code.

Implementiert:
- Model Context Protocol (JSON-RPC 2.0, 2024-11-05 & 2025-03-26 Streamable HTTP + SSE)
- Scoped API-Key-Authentifizierung (read_only, kanban_rw, agent_execute, admin_full)
- HITL-Freigabe-Gate (Human-in-the-Loop) für sensitive/autonome Werkzeuge
- Tools, Resources (Spezialisten, Metriken, Frameworks) und Prompts
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from archon.core.runtime import OBSIDIAN_VAULT_DIR, WORKSPACE_DIR

logger = logging.getLogger("archon.mcp_gateway")

SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"

# Tool-Sicherheitsmatrix: Required Scope + HITL-Pflicht
TOOL_SECURITY_POLICY: Dict[str, Dict[str, Any]] = {
    "archon__list_tasks": {"scope": "read_only", "hitl": False},
    "archon__search_crm_contacts": {"scope": "read_only", "hitl": False},
    "archon__get_inbox_messages": {"scope": "read_only", "hitl": False},
    "archon__get_system_metrics": {"scope": "read_only", "hitl": False},
    "archon__list_specialists": {"scope": "read_only", "hitl": False},
    "archon__search_vault": {"scope": "read_only", "hitl": False},
    "archon__create_task": {"scope": "kanban_rw", "hitl": False},
    "archon__update_task_status": {"scope": "kanban_rw", "hitl": False},
    "archon__trigger_boardroom_debate": {"scope": "agent_execute", "hitl": True, "domain": "boardroom"},
    "archon__ask_specialist": {"scope": "agent_execute", "hitl": True, "domain": "agent_dispatch"},
}


def _scope_allows(granted_scopes: List[str], required_scope: str) -> bool:
    if not required_scope:
        return True
    if "admin_full" in granted_scopes:
        return True
    if required_scope in granted_scopes:
        return True
    # Hierarchie: agent_execute > kanban_rw > read_only
    hierarchy = {"read_only": 1, "kanban_rw": 2, "agent_execute": 3, "admin_full": 4}
    req_level = hierarchy.get(required_scope, 99)
    max_granted = max((hierarchy.get(s, 0) for s in granted_scopes), default=0)
    return max_granted >= req_level


class McpSessionStore:
    """In-Memory Verwaltung aktiver MCP-Sessions (Mcp-Session-Id)."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create(self, client_info: Optional[Dict[str, Any]] = None, protocol_version: str = DEFAULT_PROTOCOL_VERSION) -> str:
        sid = f"mcp_{uuid.uuid4().hex}"
        self._sessions[sid] = {
            "session_id": sid,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "client_info": client_info or {},
            "protocol_version": protocol_version,
            "initialized": True,
        }
        return sid

    def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(sid)

    def delete(self, sid: str) -> bool:
        return self._sessions.pop(sid, None) is not None


class ArchonMcpGateway:
    """Zentrale JSON-RPC 2.0 MCP-Gateway-Engine mit Scoped Auth & HITL."""

    def __init__(self) -> None:
        self.sessions = McpSessionStore()
        self.server_name = "archon-agentic-os"
        self.server_version = "0.5.2.2"

    # ------------------------------------------------------------------
    # Authentifizierung & Scope-Prüfung
    # ------------------------------------------------------------------

    def authenticate_headers(self, headers: Dict[str, str], service_token_valid: bool = False) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Prüft Authorization: Bearer archon_live_..., X-Archon-API-Key oder Service-Token."""
        if service_token_valid:
            return True, {"key_id": "service_token", "name": "internal_service", "scopes": ["admin_full"]}, "OK"

        lower_headers = {k.lower(): v for k, v in headers.items()}
        raw_token = ""
        auth_h = lower_headers.get("authorization", "")
        if auth_h.lower().startswith("bearer "):
            raw_token = auth_h[7:].strip()
        elif "x-archon-api-key" in lower_headers:
            raw_token = lower_headers.get("x-archon-api-key", "").strip()

        if not raw_token:
            return False, None, "Fehlender API-Key (erwartet: Authorization: Bearer archon_live_... oder X-Archon-API-Key)."

        from backend.api_key_manager import api_key_manager
        return api_key_manager.validate_and_consume(raw_token)

    # ------------------------------------------------------------------
    # Tool-Definitionen (7 Basis-Tools + 3 Enterprise/Spezialisten-Tools)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        from scripts.archon_mcp_server import ArchonMcpServer
        base_tools = ArchonMcpServer().get_tool_definitions()

        extra_tools = [
            {
                "name": "archon__list_specialists",
                "description": "Listet verfügbare Archon OS Fachspezialisten (inkl. Domäne & Rolle) auf.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Optionaler Domänen-Filter (z. B. 'finance', 'legal', 'engineering')"},
                        "limit": {"type": "integer", "default": 25},
                    },
                },
            },
            {
                "name": "archon__ask_specialist",
                "description": "Delegiert eine Fachfrage oder Aufgabe an einen der 70 Archon-Spezialisten (HITL-geschützt).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "specialist_id": {"type": "string", "description": "ID des Spezialisten (z. B. 'cfo_financial_strategist')"},
                        "prompt": {"type": "string", "description": "Konkrete Aufgabenstellung oder Frage"},
                        "hitl_approval_id": {"type": "string", "description": "Optionale ID einer bereits genehmigten HITL-Freigabe"},
                    },
                    "required": ["specialist_id", "prompt"],
                },
            },
            {
                "name": "archon__search_vault",
                "description": "Durchsucht den lokalen Obsidian-Vault nach Wissensnotizen und Projektdossiers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Suchbegriff"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        ]

        # Boardroom-Tool um optionales hitl_approval_id ergänzen
        for t in base_tools:
            if t["name"] == "archon__trigger_boardroom_debate":
                props = t.setdefault("inputSchema", {}).setdefault("properties", {})
                props["hitl_approval_id"] = {
                    "type": "string",
                    "description": "Optionale ID einer bereits genehmigten HITL-Freigabe",
                }

        all_tools = base_tools + extra_tools
        for tool in all_tools:
            policy = TOOL_SECURITY_POLICY.get(tool["name"], {"scope": "read_only", "hitl": False})
            tool["annotations"] = {
                "readOnlyHint": policy["scope"] == "read_only",
                "destructiveHint": False,
                "requiredScope": policy["scope"],
                "hitlRequired": bool(policy.get("hitl", False)),
            }
        return all_tools

    # ------------------------------------------------------------------
    # Resources & Prompts
    # ------------------------------------------------------------------

    def list_resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": "archon://specialists",
                "name": "Archon OS Specialist Roster",
                "description": "Verzeichnis aller konfigurierten Fachspezialisten (70 Rollen / 8 Domänen).",
                "mimeType": "application/json",
            },
            {
                "uri": "archon://metrics",
                "name": "Archon OS System Telemetry",
                "description": "Aktuelle Laufzeitmetriken und Systemstatus.",
                "mimeType": "application/json",
            },
            {
                "uri": "archon://boardroom/frameworks",
                "name": "AI Boardroom Frameworks",
                "description": "Verfügbare Entscheidungs-Frameworks für den AI Boardroom.",
                "mimeType": "application/json",
            },
        ]

    def read_resource(self, uri: str) -> Tuple[bool, Any]:
        if uri == "archon://specialists":
            data = self._tool_list_specialists({"limit": 100})
            return True, json.dumps(data, ensure_ascii=False, indent=2)
        if uri == "archon://metrics":
            from scripts.archon_mcp_server import ArchonMcpServer
            data = ArchonMcpServer().execute_tool("archon__get_system_metrics", {})
            return True, json.dumps(data, ensure_ascii=False, indent=2)
        if uri == "archon://boardroom/frameworks":
            fw_path = os.path.join(WORKSPACE_DIR, "config", "boardroom_frameworks.json")
            if os.path.exists(fw_path):
                with open(fw_path, "r", encoding="utf-8") as fh:
                    return True, fh.read()
            return True, json.dumps({"frameworks": []}, ensure_ascii=False)
        return False, f"Unbekannte Resource-URI: {uri}"

    def list_prompts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "boardroom_decision_brief",
                "description": "Strukturierte Entscheidungsvorlage für eine 6-Phasen-Boardroom-Debatte.",
                "arguments": [
                    {"name": "topic", "description": "Strategische Fragestellung", "required": True},
                    {"name": "constraints", "description": "Budget- oder Compliance-Leitplanken", "required": False},
                ],
            },
            {
                "name": "specialist_delegation",
                "description": "Präziser Übergabe-Prompt an einen Archon-Spezialisten.",
                "arguments": [
                    {"name": "specialist_id", "description": "Ziel-Spezialist", "required": True},
                    {"name": "goal", "description": "Erwartetes Ergebnis", "required": True},
                ],
            },
        ]

    def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        args = arguments or {}
        if name == "boardroom_decision_brief":
            topic = args.get("topic", "<Thema>")
            constraints = args.get("constraints", "Keine besonderen Vorgaben")
            return True, {
                "description": "Boardroom Decision Brief",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Analysiere folgende strategische Fragestellung im Archon AI Boardroom:\n"
                                f"Thema: {topic}\nLeitplanken: {constraints}\n"
                                f"Nutze dazu `archon__trigger_boardroom_debate`."
                            ),
                        },
                    }
                ],
            }
        if name == "specialist_delegation":
            sid = args.get("specialist_id", "executive_decision_architect")
            goal = args.get("goal", "<Aufgabe>")
            return True, {
                "description": f"Delegation an {sid}",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": f"Delegiere an Spezialist '{sid}': {goal}",
                        },
                    }
                ],
            }
        return False, f"Unbekannter Prompt: {name}"

    # ------------------------------------------------------------------
    # HITL-Gate & Tool-Ausführung
    # ------------------------------------------------------------------

    def _check_hitl_gate(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        key_info: Dict[str, Any],
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Prüft ob eine HITL-Freigabe erforderlich/vorhanden ist.

        Rückgabe: (allowed_to_execute, pending_response_or_none)
        """
        policy = TOOL_SECURITY_POLICY.get(tool_name, {})
        if not policy.get("hitl"):
            return True, None

        from backend.approval_policy_engine import approval_engine

        approval_id = str(arguments.get("hitl_approval_id") or "").strip()
        if approval_id:
            reqs = approval_engine.get_requests()
            for r in reqs:
                if (r.get("id") or r.get("request_id")) == approval_id:
                    if r.get("status") == "approved":
                        return True, None
                    return False, {
                        "status": "pending_hitl_approval",
                        "request_id": approval_id,
                        "current_status": r.get("status"),
                        "message": f"HITL-Freigabe '{approval_id}' hat Status '{r.get('status')}' (noch nicht freigegeben).",
                    }

        domain = policy.get("domain", "agent_dispatch")
        eval_res = approval_engine.evaluate_and_enqueue(
            domain=domain,
            title=f"MCP Tool-Aufruf: {tool_name}",
            reference_id=f"mcp:{key_info.get('key_id', 'unknown')}",
            payload={"tool": tool_name, "arguments": arguments, "key_name": key_info.get("name")},
        )
        if eval_res.get("status") == "auto_approved":
            return True, None

        return False, {
            "status": "pending_hitl_approval",
            "request_id": eval_res.get("request_id"),
            "domain": domain,
            "message": (
                f"HITL-Freigabe erforderlich für '{tool_name}'. "
                f"Bitte Request '{eval_res.get('request_id')}' in Archon OS (Freigaben / Telegram) bestätigen "
                f"und anschließend mit hitl_approval_id='{eval_res.get('request_id')}' erneut aufrufen."
            ),
        }

    def _tool_list_specialists(self, args: Dict[str, Any]) -> Dict[str, Any]:
        domain_filter = str(args.get("domain") or "").strip().lower()
        limit = min(max(int(args.get("limit", 25)), 1), 200)
        roles_path = os.path.join(WORKSPACE_DIR, "roles.json")
        specialists: List[Dict[str, Any]] = []
        if os.path.exists(roles_path):
            try:
                with open(roles_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                items = raw if isinstance(raw, list) else raw.get("roles", list(raw.values())) if isinstance(raw, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    dom = str(item.get("domain") or item.get("category") or "").lower()
                    if domain_filter and domain_filter not in dom:
                        continue
                    specialists.append({
                        "id": item.get("id") or item.get("role_id"),
                        "name": item.get("name") or item.get("title"),
                        "domain": item.get("domain") or item.get("category"),
                        "summary": str(item.get("description") or item.get("tagline") or "")[:180],
                    })
                    if len(specialists) >= limit:
                        break
            except Exception as exc:
                return {"status": "error", "message": f"Fehler beim Lesen der Spezialisten: {exc}"}
        return {"status": "success", "count": len(specialists), "specialists": specialists}

    def _tool_ask_specialist(self, args: Dict[str, Any]) -> Dict[str, Any]:
        specialist_id = str(args.get("specialist_id") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not specialist_id or not prompt:
            return {"status": "error", "message": "specialist_id und prompt sind erforderlich."}
        from scripts.archon_mcp_server import ArchonMcpServer
        task_res = ArchonMcpServer()._create_task({
            "title": f"MCP Delegation → {specialist_id}",
            "body": prompt,
            "assignee": specialist_id,
            "priority": 3,
        })
        return {
            "status": "success",
            "delegated_to": specialist_id,
            "task": task_res,
            "message": f"Aufgabe an Spezialist '{specialist_id}' übergeben.",
        }

    def _tool_search_vault(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = str(args.get("query") or "").strip().lower()
        limit = min(max(int(args.get("limit", 10)), 1), 50)
        if not query:
            return {"status": "error", "message": "query darf nicht leer sein."}
        vault_root = os.path.realpath(OBSIDIAN_VAULT_DIR)
        matches: List[Dict[str, Any]] = []
        if os.path.exists(vault_root):
            for root, _, files in os.walk(vault_root):
                for fname in sorted(files):
                    if not fname.endswith(".md"):
                        continue
                    fpath = os.path.realpath(os.path.join(root, fname))
                    if not (fpath == vault_root or fpath.startswith(vault_root + os.sep)):
                        continue
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            text = fh.read(8000)
                        if query in fname.lower() or query in text.lower():
                            rel = os.path.relpath(fpath, vault_root)
                            matches.append({
                                "file": rel,
                                "snippet": text[:280].replace("\n", " "),
                            })
                            if len(matches) >= limit:
                                return {"status": "success", "query": query, "count": len(matches), "matches": matches}
                    except Exception:
                        continue
        return {"status": "success", "query": query, "count": len(matches), "matches": matches}

    def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        key_info: Dict[str, Any],
    ) -> Tuple[int, Dict[str, Any]]:
        """Führt Tool mit Scope-Prüfung, Demo-Guard und HITL-Gate aus.

        Rückgabe: (jsonrpc_error_code_or_0, payload)
        """
        policy = TOOL_SECURITY_POLICY.get(name)
        if policy is None:
            return -32602, {"message": f"Unbekanntes MCP-Werkzeug: '{name}'"}

        granted_scopes = list(key_info.get("scopes") or [])
        required_scope = policy["scope"]
        if not _scope_allows(granted_scopes, required_scope):
            return -32003, {
                "message": f"Unzureichender API-Key-Scope für '{name}'. Erforderlich: '{required_scope}', vorhanden: {granted_scopes}."
            }

        # Demo-Mode Guard (M47)
        try:
            from backend.demo_mode import is_demo_mode
            if is_demo_mode() and required_scope != "read_only":
                return -32003, {"message": "Schreibende MCP-Tools sind im Read-Only Demo-Modus gesperrt."}
        except Exception:
            pass

        # HITL-Gate prüfen
        allowed, pending = self._check_hitl_gate(name, arguments, key_info)
        if not allowed and pending is not None:
            return 0, pending

        if name == "archon__list_specialists":
            return 0, self._tool_list_specialists(arguments)
        if name == "archon__ask_specialist":
            return 0, self._tool_ask_specialist(arguments)
        if name == "archon__search_vault":
            return 0, self._tool_search_vault(arguments)

        from scripts.archon_mcp_server import ArchonMcpServer
        res = ArchonMcpServer().execute_tool(name, arguments)
        return 0, res

    # ------------------------------------------------------------------
    # JSON-RPC 2.0 Dispatcher
    # ------------------------------------------------------------------

    def handle_jsonrpc(
        self,
        payload: Dict[str, Any],
        key_info: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Verarbeitet eine einzelne JSON-RPC 2.0 Nachricht.

        Rückgabe: (jsonrpc_response_dict_or_None_for_notification, new_or_existing_session_id)
        """
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request (jsonrpc: '2.0' erforderlich)."},
            }, session_id

        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}

        # Notification (kein id)
        if req_id is None:
            if method in ("notifications/initialized", "notifications/cancelled"):
                return None, session_id
            return None, session_id

        if not isinstance(method, str) or not method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: 'method' fehlt."},
            }, session_id

        if method == "initialize":
            req_proto = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
            chosen_proto = req_proto if req_proto in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
            new_sid = session_id or self.sessions.create(
                client_info=params.get("clientInfo"),
                protocol_version=chosen_proto,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": chosen_proto,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                },
            }, new_sid

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}, session_id

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tool_definitions()},
            }, session_id

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: 'name' ist erforderlich."},
                }, session_id

            err_code, result = self.execute_tool(tool_name, arguments, key_info)
            if err_code != 0:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": err_code, "message": result.get("message", "Tool-Fehler")},
                }, session_id

            is_error = result.get("status") == "error"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": is_error,
                },
            }, session_id

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": self.list_resources()},
            }, session_id

        if method == "resources/read":
            uri = str(params.get("uri") or "")
            ok, content = self.read_resource(uri)
            if not ok:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": str(content)},
                }, session_id
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{"uri": uri, "mimeType": "application/json", "text": content}],
                },
            }, session_id

        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": self.list_prompts()},
            }, session_id

        if method == "prompts/get":
            pname = str(params.get("name") or "")
            ok, prompt_res = self.get_prompt(pname, params.get("arguments"))
            if not ok:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": str(prompt_res)},
                }, session_id
            return {"jsonrpc": "2.0", "id": req_id, "result": prompt_res}, session_id

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: '{method}'"},
        }, session_id


mcp_gateway = ArchonMcpGateway()

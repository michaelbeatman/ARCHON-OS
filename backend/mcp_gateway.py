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

import datetime
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from archon.core.runtime import OBSIDIAN_VAULT_DIR, WORKSPACE_DIR

# D04/MED: am Modulkopf gebunden — ein Importfehler fällt beim Start auf,
# nicht erst bei einer schreibenden MCP-Operation zur Laufzeit.
from backend.demo_mode import is_demo_mode

logger = logging.getLogger("archon.mcp_gateway")


class HITLVerificationUnavailable(RuntimeError):
    """D04/H-04-5: HITL-Verbrauchsstatus nicht verifizierbar -> hart deny."""

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
    "archon__list_workflow_node_plugins": {"scope": "read_only", "hitl": False},
    "archon__create_task": {"scope": "kanban_rw", "hitl": False},
    "archon__update_task_status": {"scope": "kanban_rw", "hitl": False},
    "archon__create_workflow_template": {"scope": "agent_execute", "hitl": True, "domain": "workflow_authoring"},
    "archon__run_workflow_template": {"scope": "agent_execute", "hitl": False},
    "archon__trigger_boardroom_debate": {"scope": "agent_execute", "hitl": True, "domain": "boardroom"},
    "archon__ask_specialist": {"scope": "agent_execute", "hitl": True, "domain": "agent_dispatch"},
    # M73 Teil 4: Kontext-Hygiene durch den Orchestrator (immer via Freigabe)
    "archon__compress_agent_context": {"scope": "agent_execute", "hitl": True, "domain": "context_hygiene"},
}


def bind_incoming_trace_context(headers: Dict[str, str]) -> None:
    """D16/Grenze 9: inbound traceparent/tracestate in den Verarbeitungskontext.

    Die Antwort-Header (``X-Trace-Id``, ``traceparent``) bleiben unverändert
    ueber ``_mcp_trace_headers()`` verdrahtet; hier wird nur die eingehende
    Kante zum MCP-Client wiederhergestellt. Ungueltige Header werden verworfen,
    ohne eine bereits aktive Kette zu überschreiben.
    """
    try:
        from backend.trace_context import (
            current_trace_id,
            current_tracestate,
            extract_headers,
            parse_traceparent,
            start_trace,
        )

        tp = extract_headers(headers)  # setzt tracestate + sampled-Flag
        parsed = parse_traceparent(tp)
        if parsed:
            if current_trace_id() != parsed[0]:
                start_trace(tp, tracestate=current_tracestate())
        elif not current_trace_id():
            # Auch ohne gueltigen traceparent darf ein inbound tracestate
            # nicht verworfen werden (start_trace() wuerde ihn sonst leeren).
            start_trace(tracestate=current_tracestate())
    except Exception as exc:
        logger.warning("[mcp_gateway] Inbound-Trace-Kontext nicht setzbar: %s", exc)


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
    """Thread-sichere In-Memory Verwaltung aktiver MCP-Sessions (Mcp-Session-Id) mit TTL."""

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 1000) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions

    def _prune_locked(self, now: float) -> None:
        expired = [k for k, v in self._sessions.items() if now - v.get("last_used_ts", now) > self.ttl_seconds]
        for k in expired:
            self._sessions.pop(k, None)
        while len(self._sessions) >= self.max_sessions:
            oldest_key = min(self._sessions, key=lambda k: self._sessions[k].get("last_used_ts", 0.0))
            self._sessions.pop(oldest_key, None)

    def create(self, client_info: Optional[Dict[str, Any]] = None, protocol_version: str = DEFAULT_PROTOCOL_VERSION) -> str:
        sid = f"mcp_{uuid.uuid4().hex}"
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            self._sessions[sid] = {
                "session_id": sid,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "last_used_ts": now,
                "client_info": client_info or {},
                "protocol_version": protocol_version,
                "initialized": True,
            }
        return sid

    def get(self, sid: str) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            sess = self._sessions.get(sid)
            if not sess:
                return None
            if now - sess.get("last_used_ts", now) > self.ttl_seconds:
                self._sessions.pop(sid, None)
                return None
            sess["last_used_ts"] = now
            return sess

    def delete(self, sid: str) -> bool:
        with self._lock:
            return self._sessions.pop(sid, None) is not None


class ArchonMcpGateway:
    """Zentrale JSON-RPC 2.0 MCP-Gateway-Engine mit Scoped Auth & HITL."""

    def __init__(self) -> None:
        self.sessions = McpSessionStore()
        self.server_name = "archon-agentic-os"
        self.server_version = "0.5.2.2"
        self._hitl_lock = threading.RLock()
        self._consumed_hitl_ids: set[str] = set()

    @staticmethod
    def _hitl_db_path(approval_engine: Any = None) -> str:
        dbp = getattr(approval_engine, "db_path", None)
        if dbp:
            return dbp
        try:
            from backend.db_paths import resolve_db
            return resolve_db("agentic_memory.db")
        except Exception:
            return os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

    def _is_hitl_consumed(self, approval_id: str, approval_engine: Any = None) -> bool:
        """D04/H-04-5: bei DB-Fehler Exception statt `return False`.

        Ein nicht lesbarer Verbrauchseintrag darf NIE als "nicht verbraucht"
        gewertet werden — sonst ist ein HITL-Token beliebig oft replaybar.
        """
        with self._hitl_lock:
            if approval_id in self._consumed_hitl_ids:
                return True
            dbp = self._hitl_db_path(approval_engine)
            if not os.path.exists(dbp):
                # Noch keine Verbrauchstabelle angelegt: es kann keinen
                # Eintrag geben. `_mark_hitl_consumed` legt sie beim Verbrauch
                # an und verifiziert per Lese-Back.
                return False
            conn = None
            try:
                conn = sqlite3.connect(dbp, timeout=10.0)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS mcp_consumed_hitl_ids (approval_id TEXT PRIMARY KEY, consumed_at TEXT NOT NULL)"
                )
                row = conn.execute(
                    "SELECT 1 FROM mcp_consumed_hitl_ids WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                if row:
                    self._consumed_hitl_ids.add(approval_id)
                    return True
                return False
            except Exception as exc:
                logger.error("HITL-Verbrauchsstatus für '%s' nicht verifizierbar (fail-closed): %s", approval_id, exc)
                raise HITLVerificationUnavailable(
                    f"HITL-Verbrauchsstatus nicht verifizierbar: {exc}"
                ) from exc
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _mark_hitl_consumed(self, approval_id: str, approval_engine: Any = None) -> None:
        """D04/H-04-5: Persistenzfehler eskalieren + Lese-Back-Verifikation.

        Nur im Speicher markierte Tokens überleben keinen Prozessneustart.
        Vor der Tool-Ausführung muss der Eintrag lesbar nachgewiesen werden.
        """
        with self._hitl_lock:
            dbp = self._hitl_db_path(approval_engine)
            conn = None
            try:
                os.makedirs(os.path.dirname(os.path.abspath(dbp)), exist_ok=True)
                conn = sqlite3.connect(dbp, timeout=10.0)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS mcp_consumed_hitl_ids (approval_id TEXT PRIMARY KEY, consumed_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT OR IGNORE INTO mcp_consumed_hitl_ids (approval_id, consumed_at) VALUES (?, ?)",
                    (approval_id, datetime.datetime.now(datetime.timezone.utc).isoformat()),
                )
                conn.commit()
                # Lese-Back: der Verbrauch MUSS aus der DB lesbar sein, bevor
                # die Freigabe als verbraucht gilt.
                row = conn.execute(
                    "SELECT 1 FROM mcp_consumed_hitl_ids WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                if not row:
                    raise HITLVerificationUnavailable(
                        f"HITL-Verbrauchseintrag '{approval_id}' nicht lesbar nach INSERT."
                    )
            except HITLVerificationUnavailable:
                raise
            except Exception as exc:
                logger.error("HITL-Verbrauchseintrag für '%s' nicht persistierbar (fail-closed): %s", approval_id, exc)
                raise HITLVerificationUnavailable(
                    f"HITL-Verbrauchseintrag nicht persistierbar: {exc}"
                ) from exc
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            # Erst nach erfolgreicher Lese-Back-Prüfung in den Speicher-Cache.
            self._consumed_hitl_ids.add(approval_id)

    # ------------------------------------------------------------------
    # Authentifizierung & Scope-Prüfung
    # ------------------------------------------------------------------

    def authenticate_headers(self, headers: Dict[str, str], service_token_valid: bool = False) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Prüft Authorization: Bearer archon_live_..., X-Archon-API-Key oder Service-Token."""
        bind_incoming_trace_context(headers)
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
            {
                "name": "archon__compress_agent_context",
                "description": "Kompaktiert die Chat-Historie einer Agent-Session, um das Kontextfenster freizuraeumen. HITL-geschuetzt: erster Aufruf liefert eine Freigabe-Request-ID, nach Freigabe in Archon OS (Freigaben/Telegram) erneut mit hitl_approval_id aufrufen.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "ID der zu kompaktierenden Session (z. B. 'mc_20261117_103000_ceo')"},
                        "hitl_approval_id": {"type": "string", "description": "ID einer bereits genehmigten HITL-Freigabe"},
                    },
                    "required": ["session_id"],
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

        clean_args = {k: v for k, v in arguments.items() if k != "hitl_approval_id"}
        expected_ref = f"mcp:{key_info.get('key_id', 'unknown')}"
        approval_id = str(arguments.get("hitl_approval_id") or "").strip()
        if approval_id:
            try:
                consumed = self._is_hitl_consumed(approval_id, approval_engine)
            except HITLVerificationUnavailable as exc:
                # D04/H-04-5: Verifikationsfehler NIE als "nicht verbraucht"
                # durchreichen — Tool-Ausführung hart verweigern.
                return False, {
                    "status": "pending_hitl_approval",
                    "request_id": approval_id,
                    "message": f"HITL-Verbrauchsstatus nicht verifizierbar — Ausfuehrung verweigert (fail-closed): {exc}",
                }
            if consumed:
                return False, {
                    "status": "pending_hitl_approval",
                    "request_id": approval_id,
                    "message": f"HITL-Freigabe '{approval_id}' wurde bereits verwendet (Replay blockiert).",
                }
            reqs = approval_engine.get_requests()
            for r in reqs:
                if (r.get("id") or r.get("request_id")) == approval_id:
                    if r.get("status") == "approved":
                        p_raw = r.get("payload") if r.get("payload") is not None else r.get("payload_json")
                        if isinstance(p_raw, str):
                            try:
                                p_raw = json.loads(p_raw)
                            except Exception:
                                p_raw = {}
                        p_dict = p_raw if isinstance(p_raw, dict) else {}
                        stored_args = {k: v for k, v in (p_dict.get("arguments") or {}).items() if k != "hitl_approval_id"}
                        if p_dict.get("tool") != tool_name or stored_args != clean_args or r.get("reference_id") != expected_ref:
                            return False, {
                                "status": "pending_hitl_approval",
                                "request_id": approval_id,
                                "message": f"HITL-Freigabe '{approval_id}' passt nicht zu Tool/Argumenten/API-Key.",
                            }
                        try:
                            self._mark_hitl_consumed(approval_id, approval_engine)
                        except HITLVerificationUnavailable as exc:
                            # D04/H-04-5: ohne nachweisbar persistierten
                            # Verbrauch darf das Tool nicht ausgeführt werden.
                            return False, {
                                "status": "pending_hitl_approval",
                                "request_id": approval_id,
                                "message": f"HITL-Verbrauch nicht persistierbar — Ausfuehrung verweigert (fail-closed): {exc}",
                            }
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
            reference_id=expected_ref,
            payload={"tool": tool_name, "arguments": clean_args, "key_name": key_info.get("name")},
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

    def _tool_compress_agent_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """M73 Teil 4: Orchestrator-Trigger zur Session-Kompaktierung.

        Immer HITL-pflichtig (Security-Policy): 1. Aufruf liefert
        request_id zur Freigabe, 2. Aufruf mit hitl_approval_id fuehrt aus.
        """
        session_id = str(args.get("session_id") or "").strip()
        if not session_id:
            return {"status": "error", "message": "Parameter 'session_id' ist erforderlich."}
        try:
            from archon.services.session_compaction import compact_session_core
            res = compact_session_core(session_id)
            if res.get("compacted"):
                return {
                    "status": "compacted",
                    "session_id": session_id,
                    "original_tokens": res.get("original_tokens"),
                    "compacted_tokens": res.get("compacted_tokens"),
                    "saved_pct": res.get("saved_pct"),
                    "compacted_messages": res.get("compacted_messages"),
                    "kept_recent": res.get("kept_recent"),
                }
            return {"status": "skipped", "reason": res.get("reason", ""), "session_id": session_id}
        except Exception as e:
            return {"status": "error", "message": f"Kompaktierung fehlgeschlagen: {e}"}

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

        # D04/MED: Demo-Mode Guard (M47) — bei Prüfungsfehler HART DENY.
        # `is_demo_mode` ist am Modulkopf importiert; ein Laufzeitfehler darf
        # niemals dazu führen, dass eine schreibende Operation durchgeht.
        try:
            demo_active = is_demo_mode()
        except Exception as exc:
            logger.error("Demo-Mode-Guard nicht pruefbar (fail-closed): %s", exc)
            return -32003, {"message": "demo_guard_unavailable"}
        if demo_active and required_scope != "read_only":
            return -32003, {"message": "Schreibende MCP-Tools sind im Read-Only Demo-Modus gesperrt."}

        # HITL-Gate prüfen
        allowed, pending = self._check_hitl_gate(name, arguments, key_info)
        if not allowed and pending is not None:
            return 0, pending

        # Zentraler ToolRuntime-Chokepoint (M75 + M89 + M90 + PolicyEngine).
        # Fail-closed: wenn die Prüfung selbst scheitert, wird NICHT ausgeführt.
        from backend.tool_runtime import (
            enforce_tool_execution,
            guard_result,
            guard_result_payload,
            record_tool_read_side_effect,
        )
        rt_session = str(key_info.get("session_id") or key_info.get("name") or "mcp_gateway")
        rt_agent = str(key_info.get("agent_id") or "mcp_gateway")
        rt_actor = str(
            key_info.get("actor") or key_info.get("name") or key_info.get("key_id") or rt_agent
        ).strip()
        try:
            from backend.tool_warrants import get_warrant_for_session
            rt_warrant = get_warrant_for_session(rt_session, name)
            gate = enforce_tool_execution(
                agent_id=rt_agent,
                session_id=rt_session,
                tool_name=name,
                args=arguments if isinstance(arguments, dict) else {},
                warrant=rt_warrant,
                requested_by=rt_actor,
            )
        except Exception as exc:
            logger.error("MCPGateway: ToolRuntime-Prüfung fehlgeschlagen — Zugriff verweigert: %s", exc)
            return -32003, {"message": "ToolRuntime-Prüfung fehlgeschlagen — Zugriff verweigert (fail-closed)."}
        if not gate.get("allowed"):
            return -32003, {"message": gate.get("reason", f"Tool '{name}' durch ToolRuntime blockiert."), "gate": gate}

        if name == "archon__list_specialists":
            res = self._tool_list_specialists(arguments)
        elif name == "archon__ask_specialist":
            res = self._tool_ask_specialist(arguments)
        elif name == "archon__search_vault":
            res = self._tool_search_vault(arguments)
        elif name == "archon__compress_agent_context":
            res = self._tool_compress_agent_context(arguments)
        else:
            from scripts.archon_mcp_server import ArchonMcpServer
            res = ArchonMcpServer().execute_tool(name, arguments)

        if rt_session:
            record_tool_read_side_effect(rt_session, name)
        # F10/D12-H1: externer Tool-Output gehoert durch den
        # Firewall-Chokepoint. Das Urteil wird NICHT verworfen: ein
        # `status="error"` (Klassifikatorfehler, leere verschachtelte Felder)
        # wird als strukturierter Fehler mit error_code durchgereicht und
        # von tools/call als `isError=True` gemeldet.
        verdict = guard_result(name, res, with_status=True)
        if not isinstance(verdict, dict):
            # Injizierter Legacy-Guard ohne Urteil: unveraendert durchreichen.
            return 0, verdict
        if str(verdict.get("status") or "").lower() == "error":
            code = str(
                verdict.get("error_code") or verdict.get("error") or "TOOL_OUTPUT_SANITIZATION_ERROR"
            )
            logger.error(
                "[mcp_gateway] Firewall-Urteil '%s' fuer Tool '%s' (leere Felder: %s)",
                code, name, verdict.get("empty_fields") or "-",
            )
            return 0, {
                "status": "error",
                "error": code,
                "error_code": code,
                "result": guard_result_payload(verdict),
            }
        return 0, guard_result_payload(verdict)

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

            # D12/H1: `status="error"` aus dem Firewall-Urteil darf nicht
            # laenger als `isError=false` an den MCP-Client gemeldet werden.
            # String-Results haben kein `.get()` (frueher AttributeError).
            if isinstance(result, dict):
                is_error = str(result.get("status") or "").lower() == "error"
                error_code = str(result.get("error_code") or "") if is_error else ""
            else:
                is_error = False
                error_code = ""
            content: Dict[str, Any] = {
                "type": "text", "text": json.dumps(result, ensure_ascii=False),
            }
            rpc_result: Dict[str, Any] = {"content": [content], "isError": is_error}
            if is_error:
                code = error_code or "TOOL_ERROR"
                content["error_code"] = code
                rpc_result["error_code"] = code
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": rpc_result,
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

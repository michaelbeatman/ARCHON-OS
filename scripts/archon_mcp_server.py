"""
scripts/archon_mcp_server.py
Offizieller Model Context Protocol (MCP) Server für Archon OS 2026.
Ermöglicht Claude Desktop, Cursor, Antigravity, Hermes und externen Agenten
den direkten Zugriff auf Archon Kern-Werkzeuge (Kanban, CRM, Inbox, Boardroom & Metriken).
Protokoll: MCP 2024-11-05 via JSON-RPC 2.0 (stdio & REST-Brücke).
"""

import os
import sys
import json
import time
import uuid
import sqlite3
import datetime
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_kanban_db() -> str:
    candidates = [
        "/opt/data/kanban.db",
        os.path.join(WORKSPACE_DIR, "data", "kanban.db"),
        os.path.expanduser("~/.hermes/kanban.db")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    fallback = os.path.join(WORKSPACE_DIR, "data", "kanban.db")
    try:
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
    except Exception:
        pass
    return fallback


def _resolve_inbox_dir() -> str:
    candidates = [
        "/opt/data/inbox",
        os.path.join(WORKSPACE_DIR, "data", "inbox"),
        os.path.join(WORKSPACE_DIR, "agent_workspace", "inbox")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    fallback = os.path.join(WORKSPACE_DIR, "data", "inbox")
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        pass
    return fallback


class ArchonMcpServer:
    """Implementiert die Kern-Funktionalitäten der Archon OS MCP-Tools."""

    def __init__(self):
        self.server_name = "archon-agentic-os"
        self.server_version = "2026.1.0"
        self.protocol_version = "2024-11-05"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Gibt alle registrierten MCP-Werkzeuge und deren JSON-Schemas zurück."""
        return [
            {
                "name": "archon__create_task",
                "description": "Erstellt eine neue Aufgabe im Operations Kanban Board von Archon OS.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Titel der Aufgabe"},
                        "body": {"type": "string", "description": "Detaillierte Beschreibung oder Akzeptanzkriterien"},
                        "assignee": {"type": "string", "description": "Agenten-ID (z. B. 'executive_decision_architect', 'hermes-researcher')"},
                        "priority": {"type": "integer", "description": "Priorität (1=Niedrig, 2=Mittel, 3=Hoch, 4=Kritisch)", "default": 2}
                    },
                    "required": ["title"]
                }
            },
            {
                "name": "archon__list_tasks",
                "description": "Liest Aufgaben aus dem Archon Operations Kanban Board mit Filterung nach Status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["all", "ready", "in_progress", "review", "done", "blocked"], "default": "all"},
                        "limit": {"type": "integer", "description": "Maximale Anzahl zurückzugebender Aufgaben", "default": 20}
                    }
                }
            },
            {
                "name": "archon__update_task_status",
                "description": "Aktualisiert den Status einer bestehenden Aufgabe im Kanban Board.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Die ID der Aufgabe (z. B. 't-123456')"},
                        "status": {"type": "string", "enum": ["ready", "in_progress", "review", "done", "blocked"]}
                    },
                    "required": ["task_id", "status"]
                }
            },
            {
                "name": "archon__search_crm_contacts",
                "description": "Durchsucht die CRM-Kontaktdatenbank in PocketBase nach Name, Firma oder E-Mail.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Suchbegriff (Name, Unternehmen, E-Mail)"},
                        "limit": {"type": "integer", "description": "Maximalanzahl der Kontakte", "default": 10}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "archon__get_inbox_messages",
                "description": "Liest ungelesene oder aktuelle Nachrichten aus dem Archon Triage-Postfach (E-Mails, Telegram, System).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["all", "emails", "telegram", "internal"], "default": "all"},
                        "limit": {"type": "integer", "default": 10}
                    }
                }
            },
            {
                "name": "archon__trigger_boardroom_debate",
                "description": "Startet eine strukturierte Debatte im AI Boardroom (Executive Council) zu einer strategischen Fragestellung.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Die zu untersuchende Fragestellung oder Entscheidungsvorlage"},
                        "framework": {"type": "string", "enum": ["6_thinking_hats", "first_principles", "devils_advocate", "swot"], "default": "6_thinking_hats"},
                        "budget": {"type": "string", "enum": ["free", "cheap", "balanced", "premium"], "default": "balanced"}
                    },
                    "required": ["topic"]
                }
            },
            {
                "name": "archon__get_system_metrics",
                "description": "Liefert Echtzeit-Metriken über Queue-Tiefe, LLM-Kosten, Fehlerraten und Systemzustand.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Führt ein angefordertes MCP-Werkzeug aus und liefert ein standardisiertes Ergebnis."""
        try:
            if name == "archon__create_task":
                return self._create_task(arguments)
            elif name == "archon__list_tasks":
                return self._list_tasks(arguments)
            elif name == "archon__update_task_status":
                return self._update_task_status(arguments)
            elif name == "archon__search_crm_contacts":
                return self._search_crm(arguments)
            elif name == "archon__get_inbox_messages":
                return self._get_inbox(arguments)
            elif name == "archon__trigger_boardroom_debate":
                return self._trigger_boardroom(arguments)
            elif name == "archon__get_system_metrics":
                return self._get_metrics(arguments)
            else:
                return {"status": "error", "message": f"Unbekanntes Werkzeug: '{name}'"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # --- Tool Implementierungen ---

    def _create_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        title = args.get("title", "").strip()
        if not title:
            return {"status": "error", "message": "Titel darf nicht leer sein."}
        body = args.get("body", "")
        assignee = args.get("assignee", "hermes-researcher")
        priority = int(args.get("priority", 2))
        task_id = f"t-{uuid.uuid4().hex[:6]}"
        now_iso = datetime.datetime.now().isoformat()

        db_path = _resolve_kanban_db()
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                VALUES (?, ?, ?, ?, 'ready', ?, 'mcp_client', ?)
            """, (task_id, title, body, assignee, priority, now_iso))
            conn.commit()

        # Webhook / Notification event
        try:
            from backend.notification_hub import get_notification_hub
            get_notification_hub().dispatch_notification(
                title="Neuer MCP-Task erstellt",
                message=f"Aufgabe '{title}' ({task_id}) wurde über MCP-Server angelegt.",
                severity="INFO",
                category="kanban_create"
            )
        except Exception:
            pass

        return {
            "status": "success",
            "task_id": task_id,
            "title": title,
            "column": "ready",
            "assignee": assignee,
            "created_at": now_iso
        }

    def _list_tasks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        status_filter = args.get("status", "all")
        limit = min(int(args.get("limit", 20)), 100)
        db_path = _resolve_kanban_db()

        with sqlite3.connect(db_path, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if status_filter and status_filter != "all":
                cur.execute("""
                    SELECT id, title, body, assignee, status, priority, created_at, result
                    FROM tasks WHERE status = ?
                    ORDER BY id DESC LIMIT ?
                """, (status_filter, limit))
            else:
                cur.execute("""
                    SELECT id, title, body, assignee, status, priority, created_at, result
                    FROM tasks
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]

        return {"status": "success", "count": len(rows), "tasks": rows}

    def _update_task_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args.get("task_id")
        new_status = args.get("status")
        if not task_id or not new_status:
            return {"status": "error", "message": "task_id und status sind erforderlich."}

        db_path = _resolve_kanban_db()
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": f"Task {task_id} nicht gefunden."}
            old_status = row[0]
            cur.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
            conn.commit()

        return {"status": "success", "task_id": task_id, "old_status": old_status, "new_status": new_status}

    def _search_crm(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query", "").strip()
        limit = min(int(args.get("limit", 10)), 50)
        # PocketBase prüfen
        pb_candidates = [
            os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090"),
            "http://pocketbase:8090"
        ]
        results = []
        for base_url in pb_candidates:
            try:
                filter_q = urllib.parse.quote(f'name ~ "{query}" || firma ~ "{query}" || email ~ "{query}"')
                url = f"{base_url.rstrip('/')}/api/collections/kontakte/records?filter={filter_q}&perPage={limit}"
                req = urllib.request.Request(url, headers={"User-Agent": "ArchonMCP/1.0"})
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        results = data.get("items", [])
                        break
            except Exception:
                continue

        return {"status": "success", "query": query, "count": len(results), "contacts": results}

    def _get_inbox(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cat = args.get("category", "all")
        limit = min(int(args.get("limit", 10)), 50)
        inbox_dir = _resolve_inbox_dir()
        messages = []

        if os.path.exists(inbox_dir):
            for root, dirs, files in os.walk(inbox_dir):
                if cat != "all" and cat not in root.lower():
                    continue
                for f in sorted(files, reverse=True):
                    if f.endswith(".json") or f.endswith(".txt"):
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                content = fh.read(1000)
                            messages.append({
                                "file": f,
                                "path": fpath,
                                "preview": content[:300]
                            })
                            if len(messages) >= limit:
                                break
                        except Exception:
                            pass
                if len(messages) >= limit:
                    break

        return {"status": "success", "category": cat, "count": len(messages), "messages": messages}

    def _trigger_boardroom(self, args: Dict[str, Any]) -> Dict[str, Any]:
        topic = args.get("topic")
        framework = args.get("framework", "6_thinking_hats")
        budget = args.get("budget", "balanced")
        
        # Debatte über core_dispatcher anstoßen oder als Task registrieren
        task_res = self._create_task({
            "title": f"AI Boardroom: {topic[:60]}",
            "body": f"Thema: {topic}\nFramework: {framework}\nBudget: {budget}",
            "assignee": "executive_decision_architect",
            "priority": 3
        })
        return {
            "status": "success",
            "action": "boardroom_scheduled",
            "task_id": task_res.get("task_id"),
            "topic": topic,
            "framework": framework,
            "budget": budget
        }

    def _get_metrics(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from backend.metrics_collector import metrics_collector
            return {"status": "success", "metrics": metrics_collector.get_summary_json()}
        except Exception as e:
            return {"status": "error", "message": f"Metriken konnten nicht abgerufen werden: {e}"}


def run_stdio_server():
    """Führt den stdio JSON-RPC 2.0 MCP-Server aus (für Claude Desktop, Cursor etc.)."""
    server = ArchonMcpServer()
    sys.stderr.write(f"[ArchonMCP] Server gestartet (PID {os.getpid()})\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": server.protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": server.server_name,
                        "version": server.server_version
                    }
                }
            }
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": server.get_tool_definitions()
                }
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            call_res = server.execute_tool(tool_name, arguments)
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(call_res, indent=2, ensure_ascii=False)
                        }
                    ],
                    "isError": call_res.get("status") == "error"
                }
            }
        else:
            if msg_id is not None:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
            else:
                continue

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        run_stdio_server()
    elif "--tools" in sys.argv:
        s = ArchonMcpServer()
        print(json.dumps(s.get_tool_definitions(), indent=2, ensure_ascii=False))
    elif "--call" in sys.argv:
        idx = sys.argv.index("--call")
        t_name = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
        t_args = json.loads(sys.argv[idx + 2]) if len(sys.argv) > idx + 2 else {}
        s = ArchonMcpServer()
        print(json.dumps(s.execute_tool(t_name, t_args), indent=2, ensure_ascii=False))
    else:
        s = ArchonMcpServer()
        print(f"Archon OS MCP Server v{s.server_version}")
        print(f"Verfügbare Tools ({len(s.get_tool_definitions())}):")
        for t in s.get_tool_definitions():
            print(f"  - {t['name']}: {t['description']}")

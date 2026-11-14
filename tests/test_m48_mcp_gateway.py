"""
tests/test_m48_mcp_gateway.py
=============================
Tests für M48: Nativer Archon OS MCP-Server (/mcp Gateway)
mit Streamable HTTP, SSE, Scoped API-Keys und HITL-Freigabe-Gate.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestM48McpGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.api_db = os.path.join(cls.tmpdir.name, "api_keys.db")
        cls.hitl_db = os.path.join(cls.tmpdir.name, "hitl.db")
        cls.kanban_db = os.path.join(cls.tmpdir.name, "kanban.db")

        # Temp Kanban-DB initialisieren
        with sqlite3.connect(cls.kanban_db) as conn:
            conn.execute("""
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    priority INTEGER,
                    created_by TEXT,
                    created_at TEXT,
                    result TEXT
                )
            """)
            conn.commit()

        from backend.api_key_manager import ApiKeyManager
        from backend.approval_policy_engine import ApprovalPolicyEngine

        cls.key_mgr = ApiKeyManager(db_path=cls.api_db)
        cls.approval_mgr = ApprovalPolicyEngine(db_path=cls.hitl_db)

        # Policy für boardroom / agent_dispatch auf HITL erzwingen
        with sqlite3.connect(cls.hitl_db) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO approval_policies (domain, policy_key, policy_value, description, updated_at, updated_by)
                VALUES ('boardroom', 'require_approval', 'true', 'HITL Test Policy', '2026-11-13T00:00:00Z', 'test')
            """)
            conn.commit()

        # Drei Scoped-API-Keys anlegen
        cls.ro_key = cls.key_mgr.create_key(name="mcp-ro-test", scopes=["read_only"])["raw_token"]
        cls.rw_key = cls.key_mgr.create_key(name="mcp-rw-test", scopes=["kanban_rw"])["raw_token"]
        cls.exec_key = cls.key_mgr.create_key(name="mcp-exec-test", scopes=["agent_execute"])["raw_token"]

        from archon.routers.mcp_gateway import router as mcp_router

        cls.app = FastAPI()
        cls.app.include_router(mcp_router)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def _post_mcp(self, payload, token=None, session_id=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        with patch("backend.api_key_manager.api_key_manager", self.key_mgr), \
             patch("backend.approval_policy_engine.approval_engine", self.approval_mgr), \
             patch("scripts.archon_mcp_server._resolve_kanban_db", return_value=self.kanban_db):
            return self.client.post("/mcp", json=payload, headers=headers)

    def test_01_unauthorized_without_key(self):
        resp = self._post_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(resp.status_code, 401)

    def test_02_initialize_and_notification_and_session_delete(self):
        resp = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "clientInfo": {"name": "claude-desktop", "version": "1.0"},
                },
            },
            token=self.ro_key,
        )
        self.assertEqual(resp.status_code, 200)
        sid = resp.headers.get("Mcp-Session-Id")
        self.assertTrue(sid and sid.startswith("mcp_"))
        data = resp.json()
        self.assertEqual(data["result"]["serverInfo"]["name"], "archon-agentic-os")
        self.assertIn("tools", data["result"]["capabilities"])

        # Notification -> 202 Accepted
        notif = self._post_mcp(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            token=self.ro_key,
            session_id=sid,
        )
        self.assertEqual(notif.status_code, 202)

        # DELETE /mcp -> Session schließen
        with patch("backend.api_key_manager.api_key_manager", self.key_mgr):
            del_resp = self.client.delete(
                "/mcp",
                headers={"Authorization": f"Bearer {self.ro_key}", "Mcp-Session-Id": str(sid or "")},
            )
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "closed")

    def test_03_tools_list_and_scope_enforcement(self):
        list_resp = self._post_mcp(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            token=self.ro_key,
        )
        self.assertEqual(list_resp.status_code, 200)
        tools = list_resp.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertIn("archon__list_specialists", names)
        self.assertIn("archon__ask_specialist", names)
        self.assertIn("archon__search_vault", names)
        self.assertIn("archon__trigger_boardroom_debate", names)

        # read_only darf Spezialisten listen
        spec_resp = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "archon__list_specialists", "arguments": {"limit": 5}},
            },
            token=self.ro_key,
        )
        self.assertEqual(spec_resp.status_code, 200)
        self.assertFalse(spec_resp.json()["result"]["isError"])

        # read_only darf KEINEN Task erstellen (-32003)
        denied_resp = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "archon__create_task", "arguments": {"title": "Verboten"}},
            },
            token=self.ro_key,
        )
        self.assertEqual(denied_resp.status_code, 200)
        self.assertEqual(denied_resp.json()["error"]["code"], -32003)

    def test_04_kanban_rw_create_and_list(self):
        create_resp = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "archon__create_task",
                    "arguments": {"title": "MCP Test Task", "priority": 3},
                },
            },
            token=self.rw_key,
        )
        self.assertEqual(create_resp.status_code, 200)
        payload = json.loads(create_resp.json()["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "success")

        list_resp = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "archon__list_tasks", "arguments": {"limit": 10}},
            },
            token=self.rw_key,
        )
        tasks_payload = json.loads(list_resp.json()["result"]["content"][0]["text"])
        self.assertEqual(tasks_payload["count"], 1)
        self.assertEqual(tasks_payload["tasks"][0]["title"], "MCP Test Task")

        # kanban_rw darf KEIN Boardroom triggern (-32003)
        denied = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "archon__trigger_boardroom_debate", "arguments": {"topic": "Test"}},
            },
            token=self.rw_key,
        )
        self.assertEqual(denied.json()["error"]["code"], -32003)

    def test_05_hitl_gate_blocks_until_approved_then_executes(self):
        # 1. Aufruf ohne HITL-Freigabe -> pending_hitl_approval
        first = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "archon__trigger_boardroom_debate",
                    "arguments": {"topic": "Markteintritt DACH 2027"},
                },
            },
            token=self.exec_key,
        )
        self.assertEqual(first.status_code, 200)
        first_body = json.loads(first.json()["result"]["content"][0]["text"])
        self.assertEqual(first_body["status"], "pending_hitl_approval")
        req_id = first_body["request_id"]
        self.assertTrue(req_id)

        # 2. Freigabe erteilen
        self.approval_mgr.approve_request(req_id, approver_id="michael_admin")

        # 3. Erneuter Aufruf mit hitl_approval_id -> wird ausgeführt
        second = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "archon__trigger_boardroom_debate",
                    "arguments": {
                        "topic": "Markteintritt DACH 2027",
                        "hitl_approval_id": req_id,
                    },
                },
            },
            token=self.exec_key,
        )
        second_body = json.loads(second.json()["result"]["content"][0]["text"])
        self.assertEqual(second_body["status"], "success")

    def test_06_resources_prompts_sse_and_info(self):
        res_list = self._post_mcp({"jsonrpc": "2.0", "id": 10, "method": "resources/list"}, token=self.ro_key)
        uris = {r["uri"] for r in res_list.json()["result"]["resources"]}
        self.assertIn("archon://specialists", uris)

        res_read = self._post_mcp(
            {"jsonrpc": "2.0", "id": 11, "method": "resources/read", "params": {"uri": "archon://specialists"}},
            token=self.ro_key,
        )
        self.assertEqual(res_read.status_code, 200)
        self.assertIn("contents", res_read.json()["result"])

        prompts_list = self._post_mcp({"jsonrpc": "2.0", "id": 12, "method": "prompts/list"}, token=self.ro_key)
        self.assertGreaterEqual(len(prompts_list.json()["result"]["prompts"]), 2)

        prompt_get = self._post_mcp(
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "prompts/get",
                "params": {"name": "boardroom_decision_brief", "arguments": {"topic": "Pricing"}},
            },
            token=self.ro_key,
        )
        self.assertIn("messages", prompt_get.json()["result"])

        with patch("backend.api_key_manager.api_key_manager", self.key_mgr):
            sse_resp = self.client.get("/mcp?once=1", headers={"Authorization": f"Bearer {self.ro_key}"})
        self.assertEqual(sse_resp.status_code, 200)
        self.assertIn("event: endpoint", sse_resp.text)

        info_resp = self.client.get("/mcp/info")
        self.assertEqual(info_resp.status_code, 200)
        self.assertIn("claude_desktop", info_resp.json()["clients"])
        self.assertGreaterEqual(info_resp.json()["tool_count"], 10)

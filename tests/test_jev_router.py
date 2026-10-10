"""
test_jev_router.py — Automated verification for JEV router and settings endpoints.
"""

import sys
import os
import json
import unittest
import urllib.request
import urllib.error

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import jev_router

class TestJevRouterUnit(unittest.TestCase):
    def test_fast_path_matching_email_sync(self):
        prompts = [
            "Starte E-Mail-Sync",
            "Starte email sync",
            "Gleiche Mails ab",
            "Synchronisiere Mails",
            "E-Mail Sync",
            "fetch mails"
        ]
        for p in prompts:
            match = jev_router.match_local_fast_path(p)
            self.assertIsNotNone(match, f"Prompt '{p}' should match fast path")
            self.assertEqual(match["intent"], "email_sync")
            self.assertIn("archon_crm_mcp.py", match["command"])

    def test_fast_path_matching_contacts(self):
        prompts = ["hole kontakte", "CRM Kontakte", "kontaktsync"]
        for p in prompts:
            match = jev_router.match_local_fast_path(p)
            self.assertIsNotNone(match, f"Prompt '{p}' should match fast path")
            self.assertEqual(match["intent"], "get_contacts")

    def test_fast_path_negative(self):
        prompts = [
            "Schreibe ein Python-Skript für Datenanalyse",
            "Wie wird das Wetter morgen?",
            "Erstelle ein neues Konzept für die Marketingkampagne"
        ]
        for p in prompts:
            match = jev_router.match_local_fast_path(p)
            self.assertIsNone(match, f"Prompt '{p}' should NOT match fast path")

    def test_tool_pruning(self):
        mock_tools = [
            {"name": "archon_crm__fetch_mails", "description": "Fetches incoming emails from IMAP/Gmail"},
            {"name": "archon_crm__get_contacts", "description": "Returns all saved contacts from CRM"},
            {"name": "github__create_issue", "description": "Creates a new issue in GitHub repository"},
            {"name": "slack__post_message", "description": "Posts a message to a Slack channel"},
            {"name": "obsidian__search_notes", "description": "Search notes across Obsidian vault"},
            {"name": "system__run_shell", "description": "Executes shell command in container"}
        ]
        # Query mentioning slack
        slack_pruned = jev_router.prune_tools("Schicke eine Benachrichtigung in den Slack Channel", mock_tools)
        names = [t["name"] for t in slack_pruned]
        self.assertIn("slack__post_message", names)

        # Query mentioning notes / obsidian
        notes_pruned = jev_router.prune_tools("Suche nach meiner Notiz über Architektur im Obsidian", mock_tools)
        notes_names = [t["name"] for t in notes_pruned]
        self.assertIn("obsidian__search_notes", notes_names)

    def test_connection_probe_fail_open(self):
        # Unreachable port should fail gracefully with an error dictionary, never raise an unhandled crash
        res = jev_router.test_jev_connection(api_key="fake-key", base_url="http://127.0.0.1:59999/v1")
        self.assertIsInstance(res, dict)
        self.assertIn("status", res)
        self.assertEqual(res["status"], "error")


class TestJevAPIIntegration(unittest.TestCase):
    BASE_URL = "http://localhost:8501"

    def test_settings_get_and_post_jev(self):
        # 1. Fetch current settings
        req = urllib.request.Request(f"{self.BASE_URL}/api/settings")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("jev", data)

        # 2. Update JEV settings
        test_payload = {
            "jev": {
                "enabled": True,
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-or-v1-integration-test-key",
                "fast_path_enabled": True,
                "tool_pruning_enabled": True,
                "agent_routing_enabled": True
            }
        }
        post_req = urllib.request.Request(
            f"{self.BASE_URL}/api/settings",
            data=json.dumps(test_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(post_req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

        # 3. Verify settings persisted
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("jev", {}).get("enabled"))
            self.assertEqual(data.get("jev", {}).get("provider"), "openrouter")

        # 4. Clean up: reset to disabled by default
        cleanup_payload = {
            "jev": {
                "enabled": False,
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "",
                "fast_path_enabled": True,
                "tool_pruning_enabled": True,
                "agent_routing_enabled": False
            }
        }
        cleanup_req = urllib.request.Request(
            f"{self.BASE_URL}/api/settings",
            data=json.dumps(cleanup_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(cleanup_req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_jev_diagnostic_endpoint(self):
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/v1/jev/test",
            data=json.dumps({"api_key": "test", "base_url": "https://openrouter.ai/api/v1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", res)
            self.assertIn("latency_ms", res)


if __name__ == "__main__":
    unittest.main()

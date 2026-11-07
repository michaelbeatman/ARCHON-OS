"""
test_jev_router.py — Automated verification for JEV router and settings endpoints.
"""

import sys
import os
import json
import time
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

    @staticmethod
    def _service_token() -> str:
        """Service-Token für authentifizierte /api/*-Aufrufe (Auth ist aktiv)."""
        tok = os.environ.get("ARCHON_SERVICE_TOKEN", "").strip()
        if tok:
            return tok
        for path in (
            "/app/data/.archon_service_token",
            os.path.join(BASE_DIR, "data", ".archon_service_token"),
        ):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read().strip()
            except OSError:
                continue
        return ""

    @classmethod
    def setUpClass(cls):
        cls.token = cls._service_token()
        cls.server_available = False
        if not cls.token:
            # Ohne Token sind alle /api/*-Endpunkte 401 — kein Serverproblem.
            return
        # /health ist der öffentliche Liveness-Endpunkt. /api/health verlangt
        # bereits Auth und liefert 401, taugt also NICHT als Sonde.
        # Mehrere Versuche: unter Last (parallel laufende Tests im selben
        # Container) braucht uvicorn gelegentlich länger als ein Timeout.
        for attempt in range(5):
            try:
                req = urllib.request.Request(f"{cls.BASE_URL}/health")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        cls.server_available = True
                        return
            except Exception:
                time.sleep(1.0)
        cls.server_available = False

    def setUp(self):
        if not getattr(self, "server_available", False):
            reason = (
                "Service-Token nicht gefunden (ARCHON_SERVICE_TOKEN / data/.archon_service_token)"
                if not getattr(self, "token", "")
                else "Archon OS Live-Server (localhost:8501) nicht aktiv"
            )
            self.skipTest(f"{reason} - ueberspringe HTTP-Integrationstest.")

    def _request(self, path, payload=None, timeout=5):
        headers = {"X-Archon-Service-Token": self.token}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.BASE_URL}{path}", data=data, headers=headers)
        return urllib.request.urlopen(req, timeout=timeout)

    def test_settings_get_and_post_jev(self):
        # 1. Ist-Zustand sichern — der Test darf echte JEV-Einstellungen nicht verändern.
        with self._request("/api/settings") as resp:
            self.assertEqual(resp.status, 200)
            original = json.loads(resp.read().decode("utf-8"))
        self.assertIn("jev", original)
        snapshot = dict(original.get("jev") or {})

        test_payload = {
            "jev": {
                "enabled": True,
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "test-key-not-a-secret",
                "fast_path_enabled": True,
                "tool_pruning_enabled": True,
                "agent_routing_enabled": True
            }
        }
        try:
            # 2. Schreiben
            with self._request("/api/settings", test_payload) as resp:
                self.assertEqual(resp.status, 200)

            # 3. Persistenz prüfen
            with self._request("/api/settings") as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("jev", {}).get("enabled"))
            self.assertEqual(data.get("jev", {}).get("provider"), "openrouter")
        finally:
            # 4. Immer zurücksetzen — auch wenn eine Assertion oben fehlschlägt.
            with self._request("/api/settings", {"jev": snapshot}) as resp:
                self.assertEqual(resp.status, 200)

        with self._request("/api/settings") as resp:
            restored = json.loads(resp.read().decode("utf-8")).get("jev", {})
        self.assertFalse(
            restored.get("enabled"),
            f"JEV-Einstellungen nicht zurückgesetzt: {restored}",
        )

    def test_jev_diagnostic_endpoint(self):
        payload = {"api_key": "test", "base_url": "https://openrouter.ai/api/v1"}
        with self._request("/api/v1/jev/test", payload, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertIn("status", res)
            self.assertIn("latency_ms", res)


if __name__ == "__main__":
    unittest.main()

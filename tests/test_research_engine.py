"""
tests/test_research_engine.py — Unittests für das Research Lab in Archon OS
"""

import unittest
import sys
import os
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import research_engine

class TestResearchEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = os.path.join(self.temp_dir, "workspace")
        self.vault_dir = os.path.join(self.temp_dir, "vault")
        os.makedirs(self.workspace_dir, exist_ok=True)
        os.makedirs(self.vault_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_providers_metadata(self):
        providers = research_engine.get_available_providers({})
        self.assertEqual(len(providers), 6)
        provider_ids = [p["id"] for p in providers]
        self.assertIn("duckduckgo", provider_ids)
        self.assertIn("wikipedia", provider_ids)
        self.assertIn("arxiv", provider_ids)
        self.assertIn("searxng", provider_ids)
        self.assertIn("tavily", provider_ids)
        self.assertIn("perplexity", provider_ids)

    def test_wikipedia_search(self):
        res = research_engine.search_wikipedia("Künstliche Intelligenz", lang="de", max_results=2)
        # Fallback auf leere Liste bei Netzwerk-Ausfall, aber kein Crash
        self.assertIsInstance(res, list)
        if res:
            first = res[0]
            self.assertIn("title", first)
            self.assertIn("snippet", first)
            self.assertIn("url", first)
            self.assertEqual(first["source"], "Wikipedia")

    def test_arxiv_search(self):
        res = research_engine.search_arxiv("Machine Learning", max_results=2)
        self.assertIsInstance(res, list)
        if res:
            first = res[0]
            self.assertIn("title", first)
            self.assertIn("snippet", first)
            self.assertIn("arxiv.org", first["url"])

    def test_run_research_mission(self):
        res = research_engine.run_research_mission(
            query="Deep Learning Transformer",
            profile="quick",
            engines=["wikipedia"],
            depth=2,
            adversarial=True,
            export_obsidian=True,
            vault_path=self.vault_dir,
            workspace_dir=self.workspace_dir
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["query"], "Deep Learning Transformer")
        self.assertIn("triangulation_score", res)
        self.assertIn("quality_gate", res)
        self.assertTrue(os.path.exists(res["local_path"]))

        # Prüfen ob Obsidian-Sync erfolgte
        if res.get("obsidian_saved"):
            self.assertTrue(os.path.exists(res["obsidian_path"]))

    def test_history_listing(self):
        # 1. Mission anlegen
        research_engine.run_research_mission(
            query="Test History Item",
            profile="quick",
            engines=[],
            depth=1,
            workspace_dir=self.workspace_dir
        )
        history = research_engine.list_research_history(self.workspace_dir)
        self.assertGreaterEqual(len(history), 1)
        self.assertIn("Test History Item", history[0]["title"])

if __name__ == "__main__":
    unittest.main()

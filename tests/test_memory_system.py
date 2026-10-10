"""
test_memory_system.py — Automated verification for the integrated Memory System:
- evey-memory-adaptive (importance scoring, decay, LRU-K eviction)
- evey-learner (interaction learning, SQLite & JSONL synchronization)
- evey-memory-consolidate (trace/conversation summarization to Obsidian & SQLite)
- LocalMemoryBridge (Pillar 4 SQLite persistent state)
"""

import sys
import os
import json
import time
import unittest
from pathlib import Path

# Ensure root directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from local_memory_bridge import LocalMemoryBridge

# Add Hermes plugins path
HERMES_PLUGINS = Path("/opt/data/plugins") if Path("/opt/data/plugins").exists() else (Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".hermes" / "plugins")
if str(HERMES_PLUGINS) not in sys.path:
    sys.path.insert(0, str(HERMES_PLUGINS))


class TestAdaptiveMemoryBridge(unittest.TestCase):
    def setUp(self):
        self.bridge = LocalMemoryBridge()

    def test_decay_calculation(self):
        # Fresh item (0 days old) with importance 2.0 -> score ~2.0
        score_now = self.bridge.calculate_decay_score(2.0, time.time())
        self.assertAlmostEqual(score_now, 2.0, places=2)

        # 14 days old (one half life) -> score should be halved (~1.0)
        two_weeks_ago = time.time() - (14 * 86400)
        score_half = self.bridge.calculate_decay_score(2.0, two_weeks_ago, half_life_days=14)
        self.assertAlmostEqual(score_half, 1.0, places=1)

        # 28 days old (two half lives) -> score should be ~0.5
        four_weeks_ago = time.time() - (28 * 86400)
        score_quarter = self.bridge.calculate_decay_score(2.0, four_weeks_ago, half_life_days=14)
        self.assertAlmostEqual(score_quarter, 0.5, places=1)

    def test_record_and_get_adaptive_context(self):
        agent_id = "test_agent_adaptive"
        session_id = "test_session_123"

        # Record turns
        self.bridge.record_conversation(agent_id, "user", "Hallo, was kannst du tun?", session_id=session_id)
        self.bridge.record_conversation(agent_id, "assistant", "Ich kann deine Prozesse automatisieren.", session_id=session_id)

        ctx = self.bridge.get_adaptive_context(agent_id, limit=5, session_id=session_id)
        self.assertTrue(len(ctx) >= 2)
        # Check that score exists
        for item in ctx:
            self.assertIn("decayed_score", item)
            self.assertGreater(item["decayed_score"], 0)

        # Cleanup
        self.bridge.clear_conversation_history(agent_id, session_id=session_id)

    def test_boost_and_evict(self):
        res = self.bridge.record_learning(
            agent_id="test_runner",
            category="TestCategory",
            summary="Temporäres Learning für Eviction-Test"
        )
        learning_id = res["learning_id"]
        self.assertIsNotNone(learning_id)

        # Boost
        boost_res = self.bridge.boost_memory(learning_id, table="learnings", boost_amount=1.0)
        self.assertEqual(boost_res["status"], "boosted")
        self.assertGreater(boost_res["new_importance"], 1.0)

        # Dry run eviction
        evict_res = self.bridge.evict_stale_memories(threshold=0.01, table="learnings", dry_run=True)
        self.assertEqual(evict_res["status"], "success")
        self.assertTrue(evict_res["dry_run"])


class TestEveyLearnerIntegration(unittest.TestCase):
    def test_learner_handlers(self):
        import importlib.util
        learner_path = HERMES_PLUGINS / "evey-learner" / "__init__.py"
        self.assertTrue(learner_path.exists(), f"Path {learner_path} must exist")

        spec = importlib.util.spec_from_file_location("evey_learner_mod", str(learner_path))
        learner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(learner)

        # 1. Learn from interaction
        learn_args = {
            "task": "Automatisierter Systemtest für Evey Learner",
            "model_or_tool": "test_model_v1",
            "quality_score": 9,
            "what_worked": "Direkte SQLite-Kopplung",
            "what_failed": "Keine Fehler aufgetreten",
            "do_differently": "Immer Wal-Mode verwenden",
            "tags": ["testing", "sqlite"]
        }
        res_json = learner.learn_handler(learn_args)
        res = json.loads(res_json)
        self.assertEqual(res.get("status"), "learned")
        self.assertTrue(res.get("synced_sqlite"))

        # 2. Apply learnings
        apply_args = {
            "task_description": "Führe einen Systemtest mit SQLite durch",
            "max_results": 3
        }
        apply_json = learner.apply_handler(apply_args)
        apply_res = json.loads(apply_json)
        self.assertIn(apply_res.get("status"), ["found", "no_matches"])
        if apply_res.get("status") == "found":
            self.assertGreater(apply_res.get("matches", 0), 0)


class TestEveyMemoryConsolidate(unittest.TestCase):
    def test_consolidate_module(self):
        import importlib.util
        consolidate_path = HERMES_PLUGINS / "evey-memory-consolidate" / "__init__.py"
        self.assertTrue(consolidate_path.exists(), f"Path {consolidate_path} must exist")

        spec = importlib.util.spec_from_file_location("evey_consolidate_mod", str(consolidate_path))
        consolidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consolidate)

        # Test SQLite conversations query fallback
        traces = consolidate._sqlite_conversations_query(hours_back=24)
        self.assertIsInstance(traces, list)

        # Test Obsidian Markdown creation
        sample_facts = "- [learned] SQLite WAL-Modus verhindert Locking bei gleichzeitigen Schreibvorgängen\n- [decided] Memory Bridge koppelt Hermes und Archon OS"
        obsidian_note = consolidate._save_to_obsidian(sample_facts)
        if obsidian_note:
            self.assertTrue(os.path.exists(obsidian_note))
            with open(obsidian_note, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("Tages-Konsolidierung", content)
                self.assertIn("SQLite WAL-Modus", content)


if __name__ == "__main__":
    unittest.main()

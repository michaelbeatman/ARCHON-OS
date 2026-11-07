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
import shutil
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
    """Angepasst an den aktuellen evey-learner-Stand (11/2026).

    Das Plugin schreibt JSONL statt SQLite und liefert kein `synced_sqlite`-Feld
    mehr — geprüft werden die realen Rückgabefelder. Die Learnings-Datei wird
    auf ein temporäres Verzeichnis umgebogen, damit der Test keine echten
    Learnings in `workspace/orchestrator/learnings.jsonl` hinterlässt.
    """

    def setUp(self):
        import importlib.util
        import tempfile

        learner_path = HERMES_PLUGINS / "evey-learner" / "__init__.py"
        self.assertTrue(learner_path.exists(), f"Path {learner_path} must exist")

        spec = importlib.util.spec_from_file_location("evey_learner_mod", str(learner_path))
        self.learner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.learner)

        self._tmpdir = tempfile.mkdtemp(prefix="evey_learner_test_")
        self.learner.LEARNINGS_DIR = Path(self._tmpdir)
        self.learner.LEARNINGS_FILE = Path(self._tmpdir) / "learnings.jsonl"

    def tearDown(self):
        shutil.rmtree(getattr(self, "_tmpdir", ""), ignore_errors=True)

    def test_learner_handlers(self):
        # 1. Learn from interaction
        learn_args = {
            "task": "Automatisierter Systemtest für Evey Learner",
            "model_or_tool": "test_model_v1",
            "quality_score": 9,
            "what_worked": "JSONL-Persistenz",
            "what_failed": "Keine Fehler aufgetreten",
            "do_differently": "Immer append-only schreiben",
            "tags": ["testing", "jsonl"]
        }
        res = json.loads(self.learner.learn_handler(learn_args))
        self.assertEqual(res.get("status"), "learned", res)
        self.assertEqual(res.get("quality_score"), 9)
        self.assertGreaterEqual(res.get("total_learnings", 0), 1)

        # 2. Apply learnings
        apply_args = {
            "task_description": "Führe einen Systemtest mit JSONL durch",
            "max_results": 3
        }
        apply_res = json.loads(self.learner.apply_handler(apply_args))
        self.assertIn(apply_res.get("status"), ["found", "no_learnings", "no_matches"], apply_res)
        self.assertIsInstance(apply_res.get("applicable_lessons"), list)
        if apply_res.get("status") == "found":
            self.assertGreater(apply_res.get("matches", 0), 0)


class TestEveyMemoryConsolidate(unittest.TestCase):
    """Angepasst an den aktuellen evey-memory-consolidate-Stand (11/2026).

    Das Plugin arbeitet nicht mehr über SQLite (`_sqlite_conversations_query`
    existiert nicht mehr) und exportiert nicht mehr nach Obsidian. Es holt
    Traces über Langfuse und fällt bei Fehlern weich zurück — genau das wird
    hier geprüft, ohne echten Netzwerkzugriff.
    """

    def _load(self):
        import importlib.util

        consolidate_path = HERMES_PLUGINS / "evey-memory-consolidate" / "__init__.py"
        self.assertTrue(consolidate_path.exists(), f"Path {consolidate_path} must exist")
        spec = importlib.util.spec_from_file_location("evey_consolidate_mod", str(consolidate_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_module_surface(self):
        consolidate = self._load()
        self.assertTrue(callable(consolidate.handler))
        self.assertTrue(callable(consolidate._langfuse_query))
        # Die alte SQLite-Kopplung ist bewusst entfernt — Regression-Guard.
        self.assertFalse(hasattr(consolidate, "_sqlite_conversations_query"))

    def test_langfuse_query_fails_open(self):
        consolidate = self._load()
        # Unerreichbarer Host: der Query muss weich zurückfallen, nie crashen.
        consolidate.LANGFUSE_HOST = "http://127.0.0.1:59999"
        traces = consolidate._langfuse_query(hours_back=1)
        self.assertIsInstance(traces, list)
        self.assertGreaterEqual(len(traces), 1)
        self.assertIsInstance(traces[0], str)


if __name__ == "__main__":
    unittest.main()

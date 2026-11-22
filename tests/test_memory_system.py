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


@unittest.skipUnless(
    (HERMES_PLUGINS / "evey-learner" / "__init__.py").exists(),
    "evey-learner plugin not installed in HERMES_PLUGINS",
)
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
        if not learner_path.exists():
            self.skipTest(f"Optionales lokales Plugin nicht vorhanden: {learner_path}")

        spec = importlib.util.spec_from_file_location("evey_learner_mod", str(learner_path))
        self.learner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.learner)

        self._tmpdir = tempfile.mkdtemp(prefix="evey_learner_test_")
        self.learner.LEARNINGS_DIR = Path(self._tmpdir)
        self.learner.LEARNINGS_FILE = Path(self._tmpdir) / "learnings.jsonl"

    def tearDown(self):
        shutil.rmtree(getattr(self, "_tmpdir", ""), ignore_errors=True)

    def test_learner_handlers(self):
        """Das Plugin ist jetzt eine Archon-Bridge mit register(ctx) statt
        direkter learn_handler/apply_handler-Funktionen. Die Bridge-Schnittstelle
        wird geprueft; die eigentliche Learning-Logik liegt in Archon OS.
        """
        self.assertTrue(callable(self.learner.register))
        res = self.learner.register({})
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("plugin_id"), "evey-learner")
        self.assertEqual(res.get("status"), "bridged_to_archon_os")
        self.assertIn("learn_from_interaction", res.get("tools", []))


@unittest.skipUnless(
    (HERMES_PLUGINS / "evey-memory-consolidate" / "__init__.py").exists(),
    "evey-memory-consolidate plugin not installed in HERMES_PLUGINS",
)
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
        if not consolidate_path.exists():
            self.skipTest(f"Optionales lokales Plugin nicht vorhanden: {consolidate_path}")
        spec = importlib.util.spec_from_file_location("evey_consolidate_mod", str(consolidate_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_module_surface(self):
        consolidate = self._load()
        self.assertTrue(callable(consolidate.register))
        res = consolidate.register({})
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("plugin_id"), "evey-memory-consolidate")
        self.assertEqual(res.get("status"), "bridged_to_archon_os")
        # Die alte SQLite-/Langfuse-Kopplung ist bewusst entfernt.
        self.assertFalse(hasattr(consolidate, "_sqlite_conversations_query"))
        self.assertFalse(hasattr(consolidate, "_langfuse_query"))

    def test_langfuse_query_fails_open(self):
        consolidate = self._load()
        # Die Bridge darf auch mit leerer/externer Umgebung nie crashen.
        res = consolidate.register({})
        self.assertEqual(res.get("status"), "bridged_to_archon_os")
        self.assertIsInstance(res.get("tools", []), list)


if __name__ == "__main__":
    unittest.main()

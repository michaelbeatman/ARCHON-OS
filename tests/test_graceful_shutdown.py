"""
tests/test_graceful_shutdown.py
Unit-Tests für das Saubere Herunterfahren & Task-Draining (t-12113b).
"""

import os
import sys
import asyncio
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.graceful_shutdown_coordinator import GracefulShutdownCoordinator


class TestGracefulShutdownCoordinator(unittest.TestCase):

    def setUp(self):
        self.coord = GracefulShutdownCoordinator()

    def test_draining_mode_and_task_admission(self):
        # 1. Normalzustand
        allowed, msg = self.coord.can_start_task("task-1", priority=1)
        self.assertTrue(allowed)

        # 2. Draining aktivieren
        self.coord.start_draining(reason="Deployment Test", grace_seconds=5.0)
        self.assertTrue(self.coord.is_draining)

        # Normale Tasks werden abgewiesen
        allowed_p1, msg_p1 = self.coord.can_start_task("task-2", priority=1)
        self.assertFalse(allowed_p1)
        self.assertIn("Deployment Test", msg_p1)

        # Dringende P3 Notfall-Tasks dürfen passieren
        allowed_p3, msg_p3 = self.coord.can_start_task("task-p3", priority=3)
        self.assertTrue(allowed_p3)

        # 3. Draining abbrechen
        self.coord.cancel_draining()
        self.assertFalse(self.coord.is_draining)
        allowed_again, _ = self.coord.can_start_task("task-3", priority=1)
        self.assertTrue(allowed_again)

    def test_task_registration_and_lifecycle(self):
        self.coord.register_task(
            task_id="t-abc",
            title="Datenimport",
            agent_name="data_sync",
            total_steps=5,
            current_step=1,
            state_payload={"processed": 100}
        )

        status = self.coord.get_status()
        self.assertEqual(status["active_tasks_count"], 1)

        # Progress Update
        self.coord.update_task_progress("t-abc", current_step=3, state_payload={"processed": 300})
        self.assertEqual(self.coord._active_tasks["t-abc"]["current_step"], 3)

        # Unregister
        self.coord.unregister_task("t-abc")
        self.assertEqual(len(self.coord._active_tasks), 0)

    def test_drain_and_checkpoint(self):
        import threading
        import time

        # Zwei Tasks registrieren
        self.coord.register_task("t-fast", "Kurzläufer", total_steps=2, current_step=1)
        self.coord.register_task("t-slow", "Langläufer", total_steps=10, current_step=2)

        # Simuliere schnellen Abschluss von t-fast nach 0.05s
        def finish_fast():
            time.sleep(0.05)
            self.coord.unregister_task("t-fast")

        th = threading.Thread(target=finish_fast)
        th.daemon = True
        th.start()

        # Draining mit 0.3s Timeout
        drain_res = self.coord.drain_active_tasks_sync(timeout_seconds=0.3)
        th.join(timeout=1.0)

        self.assertEqual(drain_res["initial_tasks"], 2)
        self.assertEqual(drain_res["completed_during_grace"], 1)
        self.assertEqual(drain_res["remaining_for_checkpoint"], 1)

        # Verbleibenden Task checkpointen
        checkpoints = self.coord.checkpoint_remaining_tasks()
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0]["task_id"], "t-slow")
        self.assertEqual(checkpoints[0]["status"], "checkpointed")
        self.assertEqual(len(self.coord._active_tasks), 0)

    def test_database_wal_flush(self):
        res = self.coord.flush_all_databases()
        self.assertEqual(res["status"], "success")
        self.assertIsInstance(res["flushed_databases"], list)

    def test_startup_recovery(self):
        res = self.coord.auto_resume_on_startup()
        self.assertIn("recovered_checkpoints", res)
        self.assertIn("recovered_orphans_count", res)


if __name__ == "__main__":
    unittest.main()

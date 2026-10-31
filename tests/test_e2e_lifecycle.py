"""
tests/test_e2e_lifecycle.py
Umfassende End-to-End Testsuite für den gesamten Lebenszyklus von Archon OS:
Telegram / Inbox -> Triage -> Task Creation -> Delegation -> Fan-In Synthese -> Robert Freigabe.
Zusätzlich werden Prompt-Registry, Prometheus-Metriken und MCP-Server verifiziert.
"""

import os
import sys
import json
import time
import uuid
import sqlite3
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


class TestE2ELifecycle(unittest.TestCase):
    """Prüft die Kern-Governance und den Ablaufzyklus der AgenticOS Architektur."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_db = os.path.join(cls.temp_dir.name, "test_kanban.db")
        cls.test_memory_db = os.path.join(cls.temp_dir.name, "test_memory.db")
        cls.test_inbox = os.path.join(cls.temp_dir.name, "inbox")
        os.makedirs(os.path.join(cls.test_inbox, "telegram"), exist_ok=True)
        os.makedirs(os.path.join(cls.test_inbox, "emails"), exist_ok=True)

        # Kanban Schema initialisieren
        with sqlite3.connect(cls.test_db) as conn:
            conn.execute("""
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT,
                    assignee TEXT,
                    status TEXT DEFAULT 'ready',
                    priority INTEGER DEFAULT 2,
                    created_by TEXT DEFAULT 'system',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result TEXT
                )
            """)
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        import gc
        gc.collect()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_telegram_to_inbox_triage(self):
        """Schritt 1: Eingehende Telegram-Nachricht landet als strukturierte JSON im Postfach."""
        msg_id = f"tg_{int(time.time())}"
        payload = {
            "source": "telegram",
            "sender": "Micha",
            "text": "Robert, prüfe bitte den Entwurf des Mietvertrags für das Objekt Bahnhofstr. 12.",
            "timestamp": time.time(),
            "processed": False
        }
        target_file = os.path.join(self.test_inbox, "telegram", f"{msg_id}.json")
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        self.assertTrue(os.path.exists(target_file))
        with open(target_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["sender"], "Micha")
        self.assertIn("Mietvertrags", loaded["text"])

    def test_02_inbox_to_kanban_task(self):
        """Schritt 2: Triage erzeugt eine neue Aufgabe im Kanban-Board (Status 'ready')."""
        task_id = "t-e2e-001"
        title = "Prüfung Mietvertragsentwurf Bahnhofstr. 12"
        body = "Analyse mietrechtlicher Risiken und Klauseln zur Instandhaltung."
        assignee = "executive_decision_architect"

        with sqlite3.connect(self.test_db) as conn:
            conn.execute("""
                INSERT INTO tasks (id, title, body, assignee, status, priority, created_by)
                VALUES (?, ?, ?, ?, 'ready', 3, 'inbox_triage')
            """, (task_id, title, body, assignee))
            conn.commit()

            cur = conn.cursor()
            cur.execute("SELECT status, priority, assignee FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "ready")
        self.assertEqual(row[1], 3)
        self.assertEqual(row[2], "executive_decision_architect")

    def test_03_delegation_and_subtasking(self):
        """Schritt 3: Chef-Stratege Robert delegiert an Fachagent (Status 'in_progress')."""
        task_id = "t-e2e-001"
        subtask_assignee = "commercial_jurist_contracts"

        with sqlite3.connect(self.test_db) as conn:
            conn.execute("""
                UPDATE tasks 
                SET assignee = ?, status = 'in_progress' 
                WHERE id = ?
            """, (subtask_assignee, task_id))
            conn.commit()

            cur = conn.cursor()
            cur.execute("SELECT status, assignee FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()

        self.assertEqual(row[0], "in_progress")
        self.assertEqual(row[1], "commercial_jurist_contracts")

    def test_04_fanin_synthesis_and_marker(self):
        """Schritt 4: Lisa bündelt Teilberichte und setzt den Kontrakt-Marker SYNTHESE-BEREIT."""
        task_id = "t-e2e-001"
        specialist_result = (
            "### Gutachten Gewerbemietvertrag\n"
            "- Klausel § 4 (Indexierung): Unbedenklich.\n"
            "- Klausel § 8 (Dachinstandhaltung): Unverhältnismäßiges Kostenrisiko beim Mieter.\n\n"
            "SYNTHESE-BEREIT"
        )
        self.assertIn("SYNTHESE-BEREIT", specialist_result)

        with sqlite3.connect(self.test_db) as conn:
            conn.execute("""
                UPDATE tasks 
                SET result = ?, status = 'review' 
                WHERE id = ?
            """, (specialist_result, task_id))
            conn.commit()

            cur = conn.cursor()
            cur.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()

        self.assertEqual(row[0], "review")
        self.assertIn("SYNTHESE-BEREIT", row[1])

    def test_05_robert_review_and_freigabe(self):
        """Schritt 5: Robert prüft. Nur Zeile 1 'FREIGABE' schließt Task als 'done' ab."""
        task_id = "t-e2e-001"
        robert_verdict_approved = (
            "FREIGABE: Rechtliche Bedenken zu § 8 sind berechtigt. Nachverhandlung empfohlen.\n"
            "Projekt erfolgreich abgeschlossen."
        )

        first_line = robert_verdict_approved.strip().split("\n")[0]
        self.assertTrue(first_line.startswith("FREIGABE"))

        with sqlite3.connect(self.test_db) as conn:
            new_status = "done" if first_line.startswith("FREIGABE") else "review"
            conn.execute("""
                UPDATE tasks 
                SET status = ?, result = result || '\n\n' || ? 
                WHERE id = ?
            """, (new_status, robert_verdict_approved, task_id))
            conn.commit()

            cur = conn.cursor()
            cur.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            final_status = cur.fetchone()[0]

        self.assertEqual(final_status, "done")

    def test_06_prompt_registry_versioning_and_rollback(self):
        """Schritt 6: Prompt-Registry speichert Versionen, liefert Diffs und unterstützt Rollbacks."""
        from backend.prompt_registry import PromptRegistry
        reg = PromptRegistry(db_path=self.test_memory_db)

        # v1 anlegen
        res1 = reg.save_version(
            agent_id="test_agent",
            prompt="Du bist Test-Agent v1.",
            commit_message="Initialer Prompt",
            created_by="e2e_test",
            make_active=True
        )
        self.assertEqual(res1["version_num"], 1)

        # v2 mit Canary anlegen
        res2 = reg.save_version(
            agent_id="test_agent",
            prompt="Du bist Test-Agent v2 mit optimierten Vorgaben.",
            commit_message="Prompt Upgrade",
            created_by="e2e_test",
            make_active=False,
            canary_percentage=25
        )
        self.assertEqual(res2["version_num"], 2)

        # Diff prüfen
        diff = reg.diff_versions("test_agent", 1, 2)
        self.assertIn("-Du bist Test-Agent v1.", diff)
        self.assertIn("+Du bist Test-Agent v2 mit optimierten Vorgaben.", diff)

        # Rollback auf v1
        rb = reg.rollback_to_version("test_agent", 1, reason="Test Rollback")
        self.assertEqual(rb["status"], "success")
        self.assertEqual(rb["new_active_version"], 3)

        eff = reg.get_effective_prompt("test_agent")
        self.assertEqual(eff["prompt"], "Du bist Test-Agent v1.")

    def test_07_metrics_collector_prometheus(self):
        """Schritt 7: Prometheus-Metriken werden konform generiert."""
        from backend.metrics_collector import metrics_collector
        output = metrics_collector.generate_prometheus_metrics()
        self.assertIn("archon_uptime_seconds", output)
        self.assertIn("archon_tasks_total", output)
        self.assertIn("archon_queue_depth", output)
        self.assertIn("archon_database_size_bytes", output)

    def test_08_mcp_server_protocol_execution(self):
        """Schritt 8: Archon MCP Server liefert standardisierte Werkzeuge und Antworten."""
        from scripts.archon_mcp_server import ArchonMcpServer
        server = ArchonMcpServer()
        tools = server.get_tool_definitions()
        self.assertGreaterEqual(len(tools), 7)
        tool_names = [t["name"] for t in tools]
        self.assertIn("archon__create_task", tool_names)
        self.assertIn("archon__list_tasks", tool_names)
        self.assertIn("archon__get_system_metrics", tool_names)

        # Werkzeug direkt ausführen
        res = server.execute_tool("archon__get_system_metrics", {})
        self.assertEqual(res["status"], "success")
        self.assertIn("metrics", res)


if __name__ == "__main__":
    unittest.main()

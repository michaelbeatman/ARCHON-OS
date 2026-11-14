"""
tests/test_m44_m52_m53_m25.py
================================
Tests für M44 (Business Playbooks + Katalog + Editor),
M52 (Pre-Flight Cost-Estimator + Shadow-Mode),
M53 (Obsidian Epistemic Hygiene) und
M25 (Operations-Kalender).
"""

import datetime
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestM44Playbooks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from backend.playbooks_engine import PlaybooksEngine
        self.mgr = PlaybooksEngine(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_10_active_plus_15_catalog_and_editor_crud_and_run(self):
        active = self.mgr.list_playbooks(active_only=True)
        inactive = self.mgr.list_playbooks(active_only=False)
        self.assertEqual(len(active), 10)
        self.assertEqual(len(inactive), 15)

        # Nachladen aus Katalog
        self.mgr.toggle_playbook("pb_ma_due_diligence", True)
        self.assertEqual(len(self.mgr.list_playbooks(active_only=True)), 11)

        # Editor: neue Vorlage anlegen, bearbeiten, ausführen, löschen
        created = self.mgr.create_playbook({
            "title": "Quartals-Check Custom",
            "category": "Finanzen",
            "variables": ["quartal"],
            "steps": [{"title": "Step 1", "agent_id": "cfo_financial_strategist", "prompt_template": "Prüfe {{quartal}}"}],
        })
        self.assertEqual(created["title"], "Quartals-Check Custom")

        run = self.mgr.run_playbook(created["id"], variables={"quartal": "Q4-2026"})
        self.assertEqual(run["steps"][0]["rendered_prompt"], "Prüfe Q4-2026")

        self.assertTrue(self.mgr.delete_playbook(created["id"]))


class TestM52PreflightShadow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from backend.shadow_mode import ShadowModeManager
        self.shadow = ShadowModeManager(data_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_chain_estimate_and_shadow_graduation_over_90_pct(self):
        from backend.shadow_mode import estimate_chain_cost
        est = estimate_chain_cost(
            steps=[
                {"title": "Research", "prompt": "Analyze DACH market " * 20, "expected_output_tokens": 500},
                {"title": "Synthesis", "prompt": "Write executive memo " * 20, "expected_output_tokens": 800},
            ],
            model_name="deepseek/deepseek-chat",
            budget_usd=0.50,
        )
        self.assertEqual(est["step_count"], 2)
        self.assertTrue(est["fits_budget"])

        for i in range(5):
            r = self.shadow.record_shadow_run("new_agent_x", f"t-{i}", "approve")
            self.shadow.evaluate_shadow_run(r["shadow_id"], "approve", 0.95)

        stats = self.shadow.get_agent_stats("new_agent_x")
        self.assertEqual(stats["evaluated_runs"], 5)
        self.assertGreaterEqual(stats["avg_match_rate"], 0.90)
        self.assertTrue(stats["ready_for_autopilot"])


class TestM53EpistemicHygiene(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmpdir.name, "Angebot_A.md"), "w", encoding="utf-8") as fh:
            fh.write("# Angebot A\nPreis: 1200 EUR\nGültig bis: 2025-01-01\nSiehe [[Projekt_X]]\n")
        with open(os.path.join(self.tmpdir.name, "Angebot_B.md"), "w", encoding="utf-8") as fh:
            fh.write("# Angebot B\nPreis: 1500 EUR\nOhne Links hier.\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_detects_price_conflict_stale_date_and_orphan(self):
        from backend.epistemic_hygiene import scan_vault_epistemic_hygiene
        res = scan_vault_epistemic_hygiene(
            vault_path=self.tmpdir.name,
            reference_date=datetime.date(2026, 11, 14),
        )
        self.assertEqual(res["scanned_files"], 2)
        self.assertEqual(res["conflict_count"], 1)
        self.assertEqual(res["conflicts"][0]["field"], "preis")
        self.assertEqual(res["stale_count"], 1)
        self.assertEqual(res["orphan_count"], 1)


class TestM25OperationsCalendar(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kdb = os.path.join(self.tmpdir.name, "kanban.db")
        with sqlite3.connect(self.kdb) as conn:
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, due_date TEXT)")
            conn.execute("INSERT INTO tasks VALUES ('t-1', 'Steuerabgabe', 'ready', '2026-11-20')")
            conn.commit()
        from backend.operations_calendar import OperationsCalendarManager
        self.cal = OperationsCalendarManager(data_dir=self.tmpdir.name, kanban_db_path=self.kdb)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_aggregates_custom_kanban_and_n8n_via_router(self):
        from archon.routers.operations_calendar import router as cal_router
        from backend.auth_service import auth_service

        app = FastAPI()
        app.include_router(cal_router)
        client = TestClient(app)

        with patch.object(auth_service, "is_auth_enabled", return_value=False), \
             patch("archon.routers.operations_calendar.require_admin_or_503"), \
             patch("archon.routers.operations_calendar.operations_calendar", self.cal):
            cr = client.post("/api/v1/calendar/events", json={"title": "Geburtstag Max", "date": "2026-11-18", "category": "birthday"})
            self.assertEqual(cr.status_code, 200)

            ev = client.get("/api/v1/calendar/events").json()["events"]
            sources = {e["source"] for e in ev}
            self.assertIn("custom", sources)
            self.assertIn("kanban", sources)
            self.assertIn("n8n", sources)

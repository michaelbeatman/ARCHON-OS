"""
tests/test_eu_ai_act_inventory.py
Unit-Tests für das EU AI Act KI-Inventar (t-1aa5e9).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.eu_ai_act_inventory import EUAIActInventoryManager


class TestEUAIActInventory(unittest.TestCase):

    def setUp(self):
        self.mgr = EUAIActInventoryManager()

    def test_load_all_57_profiles(self):
        profiles = self.mgr.load_profiles()
        self.assertGreaterEqual(len(profiles), 57)

    def test_classify_high_risk_hr_agent(self):
        hr_agent = {
            "id": "candidate_screener",
            "name": "Recruiting & Candidate Screener",
            "category": "HR",
            "description": "Sichtet Bewerbungen und erstellt Leistungsbewertungen von Kandidaten",
            "skills": ["bewerber-screening", "interview-evaluation"]
        }
        res = self.mgr.classify_agent(hr_agent)
        self.assertEqual(res["risk_tier"], "HIGH_RISK")
        self.assertIn("Anhang III", res["legal_basis"])
        self.assertIn("MANDATORY_HITL", res["human_oversight_measure"])

    def test_classify_transparency_agent(self):
        email_agent = {
            "id": "cold_outreach_writer",
            "name": "Cold Email Specialist",
            "category": "Sales",
            "description": "Erstellt personalisierte Vertriebs-E-Mails und Marketing-Kampagnen",
            "skills": ["cold-email", "copywriting"]
        }
        res = self.mgr.classify_agent(email_agent)
        self.assertEqual(res["risk_tier"], "SPECIFIC_TRANSPARENCY")
        self.assertIn("Art. 50", res["legal_basis"])
        self.assertIn("HUMAN_IN_THE_LOOP", res["human_oversight_measure"])

    def test_classify_minimal_risk_agent(self):
        devops_agent = {
            "id": "senior_devops",
            "name": "Senior DevOps Engineer",
            "category": "Engineering",
            "description": "Baut CI/CD Pipelines und überwacht Docker Container",
            "skills": ["docker", "ci-cd"]
        }
        res = self.mgr.classify_agent(devops_agent)
        self.assertEqual(res["risk_tier"], "MINIMAL_RISK")

    def test_generate_inventory_and_stats(self):
        inv = self.mgr.generate_inventory(save=False)
        self.assertGreaterEqual(len(inv), 57)

        stats = self.mgr.get_stats()
        self.assertGreaterEqual(stats["total_agents"], 57)
        self.assertGreater(stats["high_risk_count"], 0)
        self.assertGreater(stats["transparency_risk_count"], 0)
        self.assertGreater(stats["minimal_risk_count"], 0)
        self.assertEqual(stats["compliance_readiness_score"], 100.0)

    def test_markdown_report_generation(self):
        report = self.mgr.export_report_markdown()
        self.assertIn("# Offizielles KI-Systemregister", report)
        self.assertIn("Verordnung (EU) 2024/1689", report)
        self.assertIn("HIGH_RISK", report)


if __name__ == "__main__":
    unittest.main()

"""
tests/test_contract_manager.py
Unit-Tests für das Vertrags- & Fristenmanagement (t-0a2171).
"""

import os
import sys
import unittest
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.contract_manager import ContractParser, ContractManager, init_contracts_db, DB_PATH


class TestContractManager(unittest.TestCase):

    def setUp(self):
        # Saubere Test-DB
        init_contracts_db()

    def test_parser_german_contract(self):
        sample_contract = """
        # Dienstleistungsvertrag über Cloud-Infrastruktur
        Zwischen der Archon Systems GmbH und CloudScale Solutions GmbH (Vertragspartner)
        Beginn: 01.01.2026
        Ende: 31.12.2026
        Die Kündigungsfrist beträgt 3 Monate vor Vertragsende.
        Der Vertrag verlängert sich automatisch um weitere 12 Monate, sofern er nicht fristgerecht gekündigt wird.
        Vergütung: 249,00 € monatlich netto.
        Zahlungsziel: 14 Tage nach Rechnungserhalt.
        Kategorie: Hosting
        """
        parsed = ContractParser.parse(sample_contract)

        self.assertIn("CloudScale", parsed["partner_name"])
        self.assertEqual(parsed["start_date"], "2026-01-01")
        self.assertEqual(parsed["end_date"], "2026-12-31")
        self.assertEqual(parsed["notice_period_days"], 90)  # 3 * 30 Tage
        self.assertEqual(parsed["auto_renewal_months"], 12)
        self.assertEqual(parsed["payment_due_days"], 14)
        self.assertEqual(parsed["cost_amount"], 249.00)
        self.assertEqual(parsed["cost_currency"], "EUR")
        self.assertEqual(parsed["billing_cycle"], "monatlich")
        self.assertEqual(parsed["category"], "Hosting")

    def test_parser_english_contract(self):
        sample_english = """
        SaaS Subscription Agreement
        Vendor: AI Analytics Inc.
        Start Date: 2026-03-01
        End Date: 2027-02-28
        There is a notice period of 30 days prior to expiration.
        Payment due within 30 days.
        Total fee: $ 1200.00 yearly.
        Auto-renews for 12 months.
        """
        parsed = ContractParser.parse(sample_english)

        self.assertIn("AI Analytics", parsed["partner_name"])
        self.assertEqual(parsed["start_date"], "2026-03-01")
        self.assertEqual(parsed["end_date"], "2027-02-28")
        self.assertEqual(parsed["notice_period_days"], 30)
        self.assertEqual(parsed["payment_due_days"], 30)
        self.assertEqual(parsed["cost_currency"], "USD")
        self.assertEqual(parsed["billing_cycle"], "jährlich")
        self.assertEqual(parsed["auto_renewal_months"], 12)

    def test_deadline_calculation_and_urgency(self):
        # 31.12.2026 minus 30 Tage -> 2026-12-01
        deadline = ContractManager.calculate_deadline("2026-12-31", 30)
        self.assertEqual(deadline, "2026-12-01")

        # Urgency badges
        badge_crit, col_crit = ContractManager.get_urgency(7)
        self.assertEqual(badge_crit, "Kritisch")
        self.assertEqual(col_crit, "red")

        badge_warn, col_warn = ContractManager.get_urgency(30)
        self.assertEqual(badge_warn, "Warnung")
        self.assertEqual(col_warn, "amber")

        badge_safe, col_safe = ContractManager.get_urgency(120)
        self.assertEqual(badge_safe, "Sicher")
        self.assertEqual(col_safe, "emerald")

        badge_overdue, col_overdue = ContractManager.get_urgency(-5)
        self.assertEqual(badge_overdue, "Abgelaufen")
        self.assertEqual(col_overdue, "rose")

    def test_crud_operations(self):
        c_data = {
            "id": "ct-test-01",
            "contract_name": "Test SaaS Lizenz",
            "partner_name": "DevTools AG",
            "category": "SaaS",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "notice_period_days": 30,
            "cost_amount": 99.0,
            "billing_cycle": "monatlich",
            "status": "active"
        }

        created = ContractManager.create_or_update(c_data)
        self.assertIsNotNone(created)
        self.assertEqual(created["id"], "ct-test-01")
        self.assertEqual(created["next_notice_deadline"], "2026-12-01")

        # Read
        fetched = ContractManager.get("ct-test-01")
        self.assertEqual(fetched["partner_name"], "DevTools AG")

        # List
        all_contracts = ContractManager.list_contracts()
        self.assertTrue(any(c["id"] == "ct-test-01" for c in all_contracts))

        # Stats
        stats = ContractManager.get_stats()
        self.assertGreaterEqual(stats["total_contracts"], 1)
        self.assertGreaterEqual(stats["monthly_fixcosts"], 99.0)

        # Delete
        deleted = ContractManager.delete("ct-test-01")
        self.assertTrue(deleted)
        self.assertIsNone(ContractManager.get("ct-test-01"))

    def test_auto_renewal(self):
        c_data = {
            "id": "ct-renew-01",
            "contract_name": "Jahresabo Hosting",
            "partner_name": "Hetzner Online",
            "category": "Hosting",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "notice_period_days": 30,
            "auto_renewal_months": 12,
            "status": "active"
        }
        ContractManager.create_or_update(c_data)
        renewed = ContractManager.renew_contract("ct-renew-01")
        self.assertIsNotNone(renewed)
        self.assertEqual(renewed["end_date"], "2026-12-31") # Korrekter Monatsletzter (R-31)
        self.assertEqual(renewed["status"], "renewed")
        ContractManager.delete("ct-renew-01")

    def test_scan_and_alert_deadlines(self):
        # Vertrag anlegen mit Deadline in genau 7 Tagen
        target_deadline = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        c_data = {
            "id": "ct-alert-01",
            "contract_name": "Kritischer Cloud-Dienst",
            "partner_name": "CloudCorp",
            "category": "SaaS",
            "next_notice_deadline": target_deadline,
            "cost_amount": 499.0,
            "status": "active"
        }
        ContractManager.create_or_update(c_data)

        alerts = ContractManager.scan_and_alert_deadlines(send_telegram=False, create_kanban_task=False)
        self.assertTrue(any(a["contract_id"] == "ct-alert-01" for a in alerts))

        ContractManager.delete("ct-alert-01")


if __name__ == "__main__":
    unittest.main()

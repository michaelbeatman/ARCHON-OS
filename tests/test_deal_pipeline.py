"""
tests/test_deal_pipeline.py
Unit-Tests für die Deal-Pipeline & Forecast-Engine (t-5b159d).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.deal_pipeline import DealPipelineManager, init_deals_db


class TestDealPipeline(unittest.TestCase):

    def setUp(self):
        init_deals_db()

    def test_create_and_weighted_value(self):
        d_data = {
            "id": "deal-test-01",
            "title": "Enterprise Lizenz Paket",
            "partner_name": "MegaCorp AG",
            "contact_email": "kontakt@megacorp.de",
            "stage": "proposal",
            "deal_value": 20000.0,
            "expected_close_date": "2026-11-30"
        }
        deal = DealPipelineManager.create_or_update(d_data)
        self.assertEqual(deal["stage"], "proposal")
        self.assertEqual(deal["probability"], 0.50)  # Default für Proposal
        self.assertEqual(deal["weighted_value"], 10000.0)

    def test_move_stage(self):
        # Deal anlegen
        DealPipelineManager.create_or_update({
            "id": "deal-test-02",
            "title": "Consulting Vertrag",
            "partner_name": "StartUp GmbH",
            "stage": "discovery",
            "deal_value": 8000.0
        })

        # Verschieben auf negotiation
        moved = DealPipelineManager.move_stage("deal-test-02", "negotiation", notes="Angebot akzeptiert, Vertrag in Prüfung")
        self.assertIsNotNone(moved)
        self.assertEqual(moved["stage"], "negotiation")
        self.assertEqual(moved["probability"], 0.75)
        self.assertEqual(moved["weighted_value"], 6000.0)
        self.assertIn("Vertrag in Prüfung", moved["notes"])

    def test_forecast_calculation(self):
        # 1 Deal in Proposal (10.000 * 0.5 = 5.000)
        DealPipelineManager.create_or_update({
            "id": "deal-fc-1",
            "title": "Deal 1",
            "partner_name": "Kunde 1",
            "stage": "proposal",
            "deal_value": 10000.0,
            "expected_close_date": "2026-12-15"
        })

        # 1 Deal in Negotiation (20.000 * 0.75 = 15.000)
        DealPipelineManager.create_or_update({
            "id": "deal-fc-2",
            "title": "Deal 2",
            "partner_name": "Kunde 2",
            "stage": "negotiation",
            "deal_value": 20000.0,
            "expected_close_date": "2026-12-20"
        })

        # 1 Deal in Closed Won (15.000)
        DealPipelineManager.create_or_update({
            "id": "deal-fc-3",
            "title": "Deal 3",
            "partner_name": "Kunde 3",
            "stage": "closed_won",
            "deal_value": 15000.0
        })

        fc = DealPipelineManager.get_forecast()
        self.assertGreaterEqual(fc["active_pipeline_value"], 30000.0)
        self.assertGreaterEqual(fc["weighted_forecast_value"], 20000.0)
        self.assertGreaterEqual(fc["won_revenue"], 15000.0)
        self.assertGreaterEqual(fc["win_rate_pct"], 50.0)

        # Cleanup
        for did in ["deal-test-01", "deal-test-02", "deal-fc-1", "deal-fc-2", "deal-fc-3"]:
            DealPipelineManager.delete(did)


if __name__ == "__main__":
    unittest.main()

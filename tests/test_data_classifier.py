"""
tests/test_data_classifier.py
Unit-Tests für die Automatische Datenklassifizierung (t-53315b).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data_classifier import DataClassifier, ClassificationLevel


class TestDataClassifier(unittest.TestCase):

    def test_strictly_confidential_secrets(self):
        sample_secret = "Hier ist der Zugang zum Server: passwort = superSecretPass123!"
        res = DataClassifier.classify(sample_secret)
        self.assertEqual(res["level"], ClassificationLevel.STRICTLY_CONFIDENTIAL.value)
        self.assertEqual(res["numeric_level"], 3)
        self.assertFalse(res["cloud_llm_allowed"])
        self.assertEqual(res["routing_policy"], "ZERO_EGRESS_LOCAL_ONLY")

    def test_strictly_confidential_hr_and_nda(self):
        sample_nda = "Non-Disclosure Agreement (NDA) über Firmengeheimnisse und Monatsgehalt: 8500"
        res = DataClassifier.classify(sample_nda)
        self.assertEqual(res["level"], ClassificationLevel.STRICTLY_CONFIDENTIAL.value)
        self.assertIn("Geheimhaltungsabkommen (NDA)", res["triggers"])

    def test_confidential_invoice_and_customer_data(self):
        sample_invoice = """
        Rechnung Nr. RE-2026-1049
        Umsatzsteuer-ID: DE123456789
        Bitte überweisen Sie den Betrag auf DE89370400440532013000
        Kontakt: max.mustermann@firma.de, Tel: +49 89 12345678
        """
        res = DataClassifier.classify(sample_invoice)
        self.assertEqual(res["level"], ClassificationLevel.CONFIDENTIAL.value)
        self.assertEqual(res["numeric_level"], 2)
        self.assertTrue(res["cloud_llm_allowed"])
        self.assertTrue(res["pii_scrubbing_required"])

    def test_public_release_notes(self):
        sample_public = "Release Notes für Archon OS v0.3.6 (Open Source Changelog)"
        res = DataClassifier.classify(sample_public)
        self.assertEqual(res["level"], ClassificationLevel.PUBLIC.value)
        self.assertEqual(res["numeric_level"], 0)
        self.assertTrue(res["cloud_llm_allowed"])
        self.assertFalse(res["pii_scrubbing_required"])

    def test_internal_standard_task(self):
        sample_internal = "Refactoring des Cache-Layers für Performance-Optimierung im Backend."
        res = DataClassifier.classify(sample_internal)
        self.assertEqual(res["level"], ClassificationLevel.INTERNAL.value)
        self.assertEqual(res["numeric_level"], 1)

    def test_tagging_and_persistence(self):
        tagged = DataClassifier.tag_item(
            item_id="task-test-classify-1",
            item_type="task",
            text="Passwort für Datenbank-Migration: passwort = masterRootDb!2026"
        )
        self.assertEqual(tagged["item_id"], "task-test-classify-1")
        self.assertEqual(tagged["classification"]["level"], ClassificationLevel.STRICTLY_CONFIDENTIAL.value)

        # Abruf
        all_items = DataClassifier.get_classifications(item_type="task")
        self.assertTrue(any(it["item_id"] == "task-test-classify-1" for it in all_items))


if __name__ == "__main__":
    unittest.main()

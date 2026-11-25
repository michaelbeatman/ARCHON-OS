"""
tests/test_erp_manager.py
Verifiziert die Multi-Tenant ERP-Engine (`backend/erp_manager.py`):
- Physische Mandantentrennung (`data/tenants/{company_id}/erp.db`)
- DATEV-Nummernkreise (`10001+` Debitoren, `70001+` Kreditoren, `ART-1001+`, `ANG-`, `RE-`)
- 1:n Ansprechpartner & Kommunikations-Timeline
- Artikel-Margenkalkulation (VK vs. EK)
- Belegfluss: Angebot -> 1-Klick-Wandlung in Rechnung + GoBD-Unveränderbarkeit
- Laptop-PocketBase-Sync ohne Überschreiben kaufmännischer Stammdaten
- Vorlagen-Integration mit `corporate_manager.render_template`
"""

import os
import shutil
import sqlite3
import unittest
from backend.erp_manager import ERPManager, TENANTS_BASE_DIR
from backend.corporate_manager import corporate_manager


class TestERPManager(unittest.TestCase):
    TEST_TENANT_A = "test-holding-a"
    TEST_TENANT_B = "test-subsidiary-b"

    def setUp(self):
        for t in (self.TEST_TENANT_A, self.TEST_TENANT_B):
            p = os.path.join(TENANTS_BASE_DIR, t)
            if os.path.exists(p):
                shutil.rmtree(p)
        self.erp = ERPManager()

    def tearDown(self):
        for t in (self.TEST_TENANT_A, self.TEST_TENANT_B):
            p = os.path.join(TENANTS_BASE_DIR, t)
            if os.path.exists(p):
                shutil.rmtree(p)

    def test_physical_tenant_isolation_and_datev_numbers(self):
        # Mandant A legt Kunden und Lieferanten an
        saved_a = self.erp.save_entity({
            "display_name": "Alpha Kundengesellschaft mbH",
            "legal_form": "GmbH",
            "is_customer": 1,
            "is_supplier": 1,
            "vat_id": "DE111222333",
            "street": "Königsallee 10",
            "postal_code": "40212",
            "city": "Düsseldorf",
            "primary_contact": {
                "salutation": "Herr",
                "first_name": "Markus",
                "last_name": "Weber",
                "role_title": "Geschäftsführer",
                "email": "m.weber@alpha-kunde.de",
                "rating": 5
            }
        }, company_id=self.TEST_TENANT_A)

        ent_a = saved_a["entity"]
        self.assertEqual(ent_a["debtor_no"], "10001")
        self.assertEqual(ent_a["creditor_no"], "70001")
        self.assertEqual(len(saved_a["contacts"]), 1)
        self.assertEqual(saved_a["contacts"][0]["full_name"], "Markus Weber")

        # Mandant B muss komplett leer sein (100% DSGVO-Trennung)
        list_b = self.erp.list_entities(company_id=self.TEST_TENANT_B)
        self.assertEqual(list_b["total"], 0)

        # Mandant B bekommt eigenen Nummernkreis ab 10001
        saved_b = self.erp.save_entity({
            "display_name": "Beta Partner AG",
            "is_customer": 1
        }, company_id=self.TEST_TENANT_B)
        self.assertEqual(saved_b["entity"]["debtor_no"], "10001")

    def test_items_margin_and_document_conversion_gobd(self):
        cust = self.erp.save_entity({
            "display_name": "MedTech Bayern GmbH",
            "legal_form": "GmbH",
            "is_customer": 1,
            "street": "Maximilianstr. 5",
            "postal_code": "80539",
            "city": "München"
        }, company_id=self.TEST_TENANT_A)["entity"]

        item = self.erp.save_item({
            "item_type": "service",
            "title": "KI-Compliance Audit (ISO 13485)",
            "unit": "Tag",
            "sales_price_net": 1500.0,
            "purchase_price_net": 300.0,
            "tax_rate_pct": 19.0
        }, company_id=self.TEST_TENANT_A)

        self.assertEqual(item["item_no"], "ART-1001")
        self.assertEqual(item["margin_eur"], 1200.0)
        self.assertEqual(item["margin_pct"], 80.0)

        # Angebot anlegen
        offer = self.erp.save_document({
            "doc_type": "offer",
            "status": "sent",
            "entity_id": cust["id"],
            "lines": [
                {"item_id": item["id"], "quantity": 2.0}
            ]
        }, company_id=self.TEST_TENANT_A)

        self.assertTrue(offer["doc_number"].startswith("ANG-"))
        self.assertEqual(offer["amount_net"], 3000.0)
        self.assertEqual(offer["tax_amount"], 570.0)
        self.assertEqual(offer["amount_gross"], 3570.0)

        # 1-Klick Wandlung in Rechnung
        invoice = self.erp.convert_document(
            source_doc_id=offer["id"],
            target_doc_type="invoice",
            company_id=self.TEST_TENANT_A
        )
        self.assertTrue(invoice["doc_number"].startswith("RE-"))
        self.assertEqual(invoice["status"], "booked")
        self.assertEqual(invoice["amount_gross"], 3570.0)

        # GoBD-Check: Versuch, Betrag einer gebuchten Rechnung zu überschreiben, wird blockiert
        after_tamper = self.erp.save_document({
            "id": invoice["id"],
            "status": "paid",
            "lines": [{"title": "Manipuliert", "quantity": 1, "unit_price_net": 10.0}]
        }, company_id=self.TEST_TENANT_A)
        self.assertEqual(after_tamper["status"], "paid")
        self.assertEqual(after_tamper["amount_gross"], 3570.0)

        # Corporate Template Integration prüfen
        rendered = corporate_manager.render_template(
            template_type="invoice",
            company_id="archon-systems",
            custom={"document_id": invoice["id"]}
        )
        self.assertIn("html", rendered)

    def test_pocketbase_sync_preserves_erp_fields(self):
        # Zuerst Kunde mit USt-IdNr. und Debitorennr. anlegen
        existing = self.erp.save_entity({
            "display_name": "CyberShield GmbH",
            "is_customer": 1,
            "vat_id": "DE999888777"
        }, company_id=self.TEST_TENANT_A)["entity"]

        mock_pb = [
            {
                "id": "pb_rec_101",
                "name": "Julia Neumann",
                "unternehmen": "CyberShield GmbH",
                "rolle": "CISO",
                "email": "j.neumann@cybershield.de",
                "linkedin_url": "https://linkedin.com/in/julia-neumann",
                "status": "Vernetzt",
                "vernetzt_am": "2026-10-01",
                "rating": 5,
                "tags": ["Security", "LinkedIn"],
                "nachrichtenverlauf": [
                    {
                        "messageId": "msg_li_9001",
                        "type": "inbound",
                        "sender_name": "Julia Neumann",
                        "subject": "Pentest Anfrage",
                        "text": "Können wir nächste Woche telefonieren?",
                        "timestamp": "2026-10-15 14:20:00"
                    }
                ]
            }
        ]

        res = self.erp.sync_with_pocketbase(company_id=self.TEST_TENANT_A, mock_records=mock_pb)
        self.assertTrue(res["success"])
        self.assertEqual(res["synced_contacts"], 1)
        self.assertEqual(res["synced_messages"], 1)

        detail = self.erp.get_entity_detail(existing["id"], company_id=self.TEST_TENANT_A)
        # Kaufmännische Felder bleiben unangetastet
        self.assertEqual(detail["entity"]["debtor_no"], "10001")
        self.assertEqual(detail["entity"]["vat_id"], "DE999888777")
        # LinkedIn-Kontakt & Verlauf wurden sauber verknüpft
        self.assertEqual(len(detail["contacts"]), 1)
        self.assertEqual(detail["contacts"][0]["full_name"], "Julia Neumann")
        self.assertEqual(len(detail["interactions"]), 1)

    def test_pocketbase_record_without_unternehmen_keeps_erp_contact_fields(self):
        """H-03-2: PB-Sync darf entity_id/is_primary NIE überschreiben."""
        saved = self.erp.save_entity({
            "display_name": "Firma Mit Agenda GmbH",
            "is_customer": 1,
            "vat_id": "DE123456789",
        }, company_id=self.TEST_TENANT_A)
        entity = saved["entity"]
        contact = self.erp.save_contact({
            "full_name": "Erika Musterfrau",
            "entity_id": entity["id"],
            "is_primary": 1,
            "pocketbase_id": "pb-erika-1",
        }, company_id=self.TEST_TENANT_A)

        # PB-Record ohne 'unternehmen', aber mit bekannter pocketbase_id.
        mock_pb = [{
            "id": "pb-erika-1",
            "name": "Erika Musterfrau",
            "rolle": "Lead",
            "email": "erika@example.org",
            "rating": 4,
        }]
        res = self.erp.sync_with_pocketbase(
            company_id=self.TEST_TENANT_A, mock_records=mock_pb
        )
        self.assertTrue(res["success"])

        detail = self.erp.get_entity_detail(entity["id"], company_id=self.TEST_TENANT_A)
        synced = next(c for c in detail["contacts"] if c["id"] == contact["id"])
        self.assertEqual(synced["entity_id"], entity["id"])
        self.assertEqual(synced["is_primary"], 1)
        # Erlaubte Netzwerk-/Kommunikationsfelder wurden dagegen abgeglichen.
        self.assertEqual(synced["role_title"], "Lead")
        self.assertEqual(synced["email"], "erika@example.org")
        self.assertEqual(detail["entity"]["vat_id"], "DE123456789")

    def test_duplicate_pocketbase_id_is_rejected(self):
        """F015: pocketbase_id UNIQUE verhindert stillen Sync-Lookup auf Zeile 1."""
        self.erp.save_contact({
            "full_name": "Erste Person", "pocketbase_id": "pb-duplicate",
        }, company_id=self.TEST_TENANT_A)

        with self.assertRaises(sqlite3.IntegrityError):
            self.erp.save_contact({
                "full_name": "Zweite Person", "pocketbase_id": "pb-duplicate",
            }, company_id=self.TEST_TENANT_A)

    def test_legacy_pocketbase_duplicates_are_migrated_to_unique_index(self):
        """Bestands-DBs bekommen den Unique-Index ohne Kontaktverlust."""
        from backend.erp_manager import ERPManager, get_tenant_db_path
        db_path = get_tenant_db_path(self.TEST_TENANT_B)

        # Bestands-DB vor dem Fix: Tabelle OHNE UNIQUE, doppelte pocketbase_id.
        # sqlite3.Connection.__exit__ schliesst NICHT — explizit schliessen,
        # sonst haelt Windows die Datei fuer tearDown() fest.
        from contextlib import closing
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "CREATE TABLE crm_contacts ("
                "id TEXT PRIMARY KEY, entity_id TEXT, last_name TEXT NOT NULL, "
                "full_name TEXT NOT NULL, is_primary INTEGER DEFAULT 0, "
                "email TEXT DEFAULT '', pocketbase_id TEXT, "
                "created_at TIMESTAMP, updated_at TIMESTAMP)"
            )
            conn.execute(
                "CREATE INDEX idx_contacts_pb ON crm_contacts(pocketbase_id)"
            )
            conn.executemany(
                "INSERT INTO crm_contacts (id, last_name, full_name, pocketbase_id) "
                "VALUES (?, ?, ?, ?)",
                [
                    ("cnt-old-1", "Alt", "Alt", "pb-old"),
                    ("cnt-old-2", "Zweit", "Zweit", "pb-old"),
                ],
            )
            conn.commit()

        # Schema-Migration beim ersten Öffnen der Bestands-DB.
        fresh = ERPManager()
        try:
            conn, _ = fresh._get_conn(self.TEST_TENANT_B)
            indexes = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='crm_contacts'"
                ).fetchall()
            }
            self.assertIn("idx_contacts_pb_unique", indexes)
            pb_ids = [
                r[0] for r in conn.execute(
                    "SELECT pocketbase_id FROM crm_contacts "
                    "WHERE id IN ('cnt-old-1','cnt-old-2')"
                ).fetchall()
            ]
            self.assertEqual(pb_ids.count("pb-old"), 1)
            self.assertEqual(len(pb_ids), 2)  # keine Kontakte gelöscht
        finally:
            conn.close()

    def test_primary_tenant_seed_and_corporate_template_link(self):
        overview = self.erp.get_tenant_overview("archon-systems")
        self.assertEqual(overview["company_id"], "archon-systems")
        self.assertGreaterEqual(overview["counts"]["entities"], 3)
        self.assertGreaterEqual(overview["counts"]["items"], 4)

        rendered = corporate_manager.render_template(
            template_type="letterhead",
            company_id="archon-systems",
            custom={"entity_id": "ent-nordstern"}
        )
        self.assertIn("Nordstern Digital AG", rendered["html"])
        self.assertIn("Dr. Lukas Bergmann", rendered["html"])


if __name__ == "__main__":
    unittest.main()

"""
tests/test_m43_multi_tenant.py
==============================
Tests für M43: Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV),
durchgängige physische SQLite-DB-Isolation über alle 5 Fachmodule (ERP, Kanban,
CRM, Contracts, Deals) und getrennte Beleg-Nummernkreise.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestM43MultiTenant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.profiles_file = os.path.join(cls.tmpdir.name, "corporate_profiles.json")

        from backend.corporate_manager import CorporateManager
        from backend.tenant_context import TenantContextManager

        cls.corp_mgr = CorporateManager(filepath=cls.profiles_file)
        cls.corp_mgr.save_company({"id": "holding_hq", "name": "Archon Holding GmbH", "entity_type": "holding"})
        cls.corp_mgr.save_company({"id": "spv_alpha", "name": "Projekt SPV Alpha GmbH", "entity_type": "spv"})

        cls.tenant_mgr = TenantContextManager(workspace_dir=cls.tmpdir.name, corporate_mgr=cls.corp_mgr)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_01_physical_sqlite_db_isolation_across_tenants(self):
        self.tenant_mgr.switch_tenant("holding_hq")
        db_hold = self.tenant_mgr.resolve_active_db("kanban.db")
        with sqlite3.connect(db_hold) as conn:
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('t-hold-1', 'Holding Board Meeting', 'todo')")
            conn.commit()

        self.tenant_mgr.switch_tenant("spv_alpha")
        db_spv = self.tenant_mgr.resolve_active_db("kanban.db")
        self.assertNotEqual(db_hold, db_spv)

        with sqlite3.connect(db_spv) as conn:
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('t-spv-1', 'SPV Grundstückskauf', 'todo')")
            conn.commit()
            rows_spv = conn.execute("SELECT id FROM tasks").fetchall()
        self.assertEqual([r[0] for r in rows_spv], ["t-spv-1"])

        # Zurück zu Holding: SPV-Daten dürfen dort nicht sichtbar sein
        self.tenant_mgr.switch_tenant("holding_hq")
        with sqlite3.connect(self.tenant_mgr.resolve_active_db("kanban.db")) as conn:
            rows_hold = conn.execute("SELECT id FROM tasks").fetchall()
        self.assertEqual([r[0] for r in rows_hold], ["t-hold-1"])

    def test_02_end_to_end_domain_managers_isolation_deals_contracts_crm(self):
        """Beweist, dass DealPipelineManager, ContractManager und CRMService real getrennt speichern."""
        from backend.contract_manager import ContractManager
        from backend.crm_service import CRMService
        from backend.deal_pipeline import DealPipelineManager

        crm = CRMService()

        with patch("backend.tenant_context.tenant_context", self.tenant_mgr):
            # 1. Daten in Holding anlegen
            self.tenant_mgr.switch_tenant("holding_hq")
            DealPipelineManager.create_or_update({
                "id": "deal-hold-1",
                "title": "Beteiligungserwerb Nord",
                "partner_name": "Nord Invest AG",
                "stage": "negotiation",
                "deal_value": 250000.0,
            })
            ContractManager.create_or_update({
                "id": "ctr-hold-1",
                "contract_name": "Konzern-Steuerberatungsmandat",
                "partner_name": "WP Kanzlei Dr. Berg",
                "cost_amount": 1800.0,
            })
            created_hold_c = crm.save_contact(contact_id=None, payload={"name": "Dr. Hans Berg", "unternehmen": "WP Berg", "status": "Aktiv"})
            crm.save_contact(contact_id=created_hold_c["id"], payload={"debitor_nr": "10099"})

            # 2. Umschalten auf SPV Alpha: Listen müssen leer bzw. strikt getrennt sein!
            self.tenant_mgr.switch_tenant("spv_alpha")
            self.assertEqual(len(DealPipelineManager.list_deals()), 0)
            self.assertEqual(len(ContractManager.list_contracts()), 0)
            self.assertEqual(crm.list_contacts()["total"], 0)

            # Eigene SPV-Datensätze anlegen
            DealPipelineManager.create_or_update({
                "id": "deal-spv-1",
                "title": "Objektverkauf Wohnpark Süd",
                "partner_name": "Stadtwerke Immobilien",
                "stage": "proposal",
                "deal_value": 1400000.0,
            })
            ContractManager.create_or_update({
                "id": "ctr-spv-1",
                "contract_name": "Generalunternehmervertrag Bauabschnitt 1",
                "partner_name": "BauTech GmbH",
                "cost_amount": 45000.0,
            })
            crm.save_contact(contact_id=None, payload={"name": "Sabine Bauleiter", "unternehmen": "BauTech GmbH", "status": "Kunde"})

            spv_deals = DealPipelineManager.list_deals()
            self.assertEqual([d["id"] for d in spv_deals], ["deal-spv-1"])
            self.assertEqual([c["id"] for c in ContractManager.list_contracts()], ["ctr-spv-1"])
            self.assertEqual(crm.list_contacts()["total"], 1)

            # 3. Zurück zu Holding: Nur Holding-Datensätze sichtbar
            self.tenant_mgr.switch_tenant("holding_hq")
            self.assertEqual([d["id"] for d in DealPipelineManager.list_deals()], ["deal-hold-1"])
            self.assertEqual([c["id"] for c in ContractManager.list_contracts()], ["ctr-hold-1"])
            self.assertEqual(crm.list_contacts()["items"][0]["name"], "Dr. Hans Berg")

    def test_03_atomic_number_ranges_per_tenant(self):
        n1 = self.tenant_mgr.next_document_number("invoice", "holding_hq")
        n2 = self.tenant_mgr.next_document_number("invoice", "holding_hq")
        s1 = self.tenant_mgr.next_document_number("invoice", "spv_alpha")

        self.assertTrue(n1.startswith("RE-HOLDIN-"))
        self.assertTrue(n1.endswith("0001"))
        self.assertTrue(n2.endswith("0002"))
        self.assertTrue(s1.startswith("RE-SPV_AL-") or s1.startswith("RE-SPV"))
        self.assertTrue(s1.endswith("0001"))

    def test_04_router_context_create_company_switch_and_isolation_endpoints(self):
        from archon.routers.tenants import router as tenants_router
        from backend.auth_service import auth_service

        app = FastAPI()
        app.include_router(tenants_router)
        client = TestClient(app)

        with patch.object(auth_service, "is_auth_enabled", return_value=False), \
             patch("archon.routers.tenants.require_admin_or_503"), \
             patch("archon.routers.tenants.tenant_context", self.tenant_mgr):
            ctx = client.get("/api/v1/tenants/context")
            self.assertEqual(ctx.status_code, 200)
            self.assertGreaterEqual(len(ctx.json()["companies"]), 2)

            created = client.post(
                "/api/v1/tenants/companies",
                json={"name": "Operative Logistik GmbH", "entity_type": "operative_gmbh", "activate": True},
            )
            self.assertEqual(created.status_code, 200)
            new_tid = created.json()["tenant_id"]
            self.assertEqual(created.json()["company"]["entity_type"], "operative_gmbh")

            iso_new = client.get(f"/api/v1/tenants/{new_tid}/isolation-status")
            self.assertEqual(iso_new.status_code, 200)
            for db_name in ("erp.db", "kanban.db", "crm.db", "contracts.db", "deals.db"):
                self.assertTrue(iso_new.json()["databases"][db_name]["exists"], f"{db_name} fehlt")

            sw = client.post("/api/v1/tenants/switch", json={"company_id": "spv_alpha"})
            self.assertEqual(sw.status_code, 200)
            self.assertEqual(sw.json()["tenant_id"], "spv_alpha")

            nxt = client.post("/api/v1/tenants/spv_alpha/number-ranges/next", json={"doc_type": "offer"})
            self.assertEqual(nxt.status_code, 200)
            self.assertIn("ANG-", nxt.json()["document_number"])

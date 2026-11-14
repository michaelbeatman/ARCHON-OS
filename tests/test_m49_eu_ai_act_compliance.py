"""
tests/test_m49_eu_ai_act_compliance.py
======================================
Tests für M49: EU AI Act Compliance-Engine, präzise Anhang-III-/Art.-50-Klassifizierung,
SOUL.md-SHA-256-Pinning, Art.-4-KI-Kompetenzregister (inkl. GoBD-Audit-Log) und
prüferfertigen mehrseitigen GoBD- & EU-AI-Act-Verfahrensdokumentations-PDF-Export.
"""

import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader


class TestM49EUAIActCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.inv_file = os.path.join(cls.tmpdir.name, "eu_ai_act_inventory.json")
        cls.lit_file = os.path.join(cls.tmpdir.name, "ai_act_literacy_register.json")
        cls.audit_db = os.path.join(cls.tmpdir.name, "audit_test.db")
        cls.corp_file = os.path.join(cls.tmpdir.name, "corporate_profiles.json")

        from backend.audit_log import ChainedAuditLog
        from backend.compliance_engine import ComplianceEngine
        from backend.corporate_manager import CorporateManager
        from backend.eu_ai_act_inventory import EUAIActInventoryManager
        from backend.tenant_context import TenantContextManager

        cls.audit_log = ChainedAuditLog(db_path=cls.audit_db)
        cls.corp_mgr = CorporateManager(filepath=cls.corp_file)
        cls.corp_mgr.save_company({
            "id": "keller-holding",
            "name": "Keller Strategic Holding GmbH",
            "entity_type": "holding",
            "legal_form": "GmbH",
            "tax": {"tax_number": "27/123/45678", "vat_id": "DE998877665"},
        })
        cls.corp_mgr.set_active_company("keller-holding")

        cls.tenant_mgr = TenantContextManager(workspace_dir=cls.tmpdir.name, corporate_mgr=cls.corp_mgr)
        cls.tenant_mgr.ensure_tenant_databases("keller-holding", init_schemas=True)

        cls.inv_mgr = EUAIActInventoryManager(inventory_file=cls.inv_file)
        cls.engine = ComplianceEngine(
            literacy_file=cls.lit_file,
            inventory_mgr=cls.inv_mgr,
            tenant_mgr=cls.tenant_mgr,
            audit_logger=cls.audit_log,
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_01_precise_specialist_classification_and_soul_hashes(self):
        inv = self.inv_mgr.generate_inventory(save=True)
        self.assertGreaterEqual(len(inv), 57)

        by_id = {item["agent_id"]: item for item in inv}
        # HR-Recruiter muss HIGH_RISK (Anhang III Nr. 4) sein
        self.assertEqual(by_id["hr_recruiter"]["risk_tier"], "HIGH_RISK")
        # B2B Outreach muss SPECIFIC_TRANSPARENCY (Art. 50) sein
        self.assertEqual(by_id["b2b_outreach_specialist"]["risk_tier"], "SPECIFIC_TRANSPARENCY")
        # Interne Rollen (Founder / Research Scout / Wirtschaftsjurist) dürfen NICHT fälschlich als HR-High-Risk landen
        for internal_id in ("founder", "research_scout", "commercial_jurist_contracts"):
            if internal_id in by_id:
                self.assertNotEqual(by_id[internal_id]["risk_tier"], "HIGH_RISK")

        # Jeder Spezialist hat einen echten 64-stelligen SHA-256-Hash seines SOUL-Prompts
        for item in inv:
            self.assertEqual(len(item.get("soul_sha256", "")), 64)

    def test_02_art4_literacy_register_and_gobd_audit_chain(self):
        initial = self.engine.list_literacy_entries()
        self.assertGreaterEqual(len(initial), 1)

        added = self.engine.add_literacy_entry(
            {
                "person_name": "Michael Keller",
                "role": "Geschäftsführer & System-Owner",
                "training_module": "EU AI Act Art. 4 & GoBD-Verfahrenskontrolle",
            },
            actor="michael",
        )
        self.assertEqual(added["person_name"], "Michael Keller")
        self.assertEqual(len(added["certificate_sha256"]), 64)

        # GoBD-Hashkette muss intakt sein und das Ereignis enthalten
        integrity = self.audit_log.verify_integrity()
        self.assertTrue(integrity["valid"])
        self.assertGreaterEqual(integrity["total_records"], 1)

    def test_03_guardrails_gate_blocks_non_compliant_high_risk_agent(self):
        guard = self.engine.evaluate_guardrails()
        self.assertTrue(guard["all_guardrails_passed"])

        ok_check = self.engine.check_activation_allowed("hr_recruiter")
        self.assertTrue(ok_check["allowed"])

        # Setze manuellen Override ohne HITL -> Gate muss Aktivierung blockieren
        self.inv_mgr.set_manual_override(
            "hr_recruiter",
            {"human_oversight_measure": "NONE", "compliance_status": "NON_COMPLIANT"},
            actor="auditor",
        )
        blocked = self.engine.check_activation_allowed("hr_recruiter")
        self.assertFalse(blocked["allowed"])

        # Wiederherstellen
        self.inv_mgr.set_manual_override(
            "hr_recruiter",
            {
                "human_oversight_measure": "MANDATORY_HITL (4-Augen-Freigabe)",
                "compliance_status": "COMPLIANT_WITH_OVERSIGHT",
            },
            actor="auditor",
        )

    def test_04_one_click_gobd_and_eu_ai_act_pdf_generation(self):
        from backend.compliance_pdf import build_verfahrensdokumentation_pdf

        snap = self.engine.collect_verfahrensdokumentation_snapshot("keller-holding")
        pdf_bytes, pdf_sha256 = build_verfahrensdokumentation_pdf(snap)

        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertEqual(len(pdf_sha256), 64)

        reader = PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 2)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("Verfahrensdokumentation nach GoBD & EU AI Act", full_text)
        self.assertIn("Keller Strategic Holding GmbH", full_text)
        self.assertIn("DE998877665", full_text)
        self.assertIn("hr_recruiter", full_text)
        self.assertIn("Michael Keller", full_text)

    def test_05_governance_router_m49_endpoints(self):
        from archon.routers.governance import router as gov_router
        from backend.auth_service import auth_service

        app = FastAPI()
        app.include_router(gov_router)
        client = TestClient(app)

        with patch.object(auth_service, "is_auth_enabled", return_value=False), \
             patch("archon.routers.governance.require_admin_or_503"), \
             patch("backend.compliance_engine.compliance_engine", self.engine):
            r_lit = client.get("/api/v1/governance/ai-act/literacy-register")
            self.assertEqual(r_lit.status_code, 200)
            self.assertGreaterEqual(r_lit.json()["count"], 2)

            r_guard = client.get("/api/v1/governance/ai-act/guardrails")
            self.assertEqual(r_guard.status_code, 200)
            self.assertTrue(r_guard.json()["guardrails"]["all_guardrails_passed"])

            r_pdf = client.get("/api/v1/governance/compliance/verfahrensdokumentation.pdf?company_id=keller-holding")
            self.assertEqual(r_pdf.status_code, 200)
            self.assertEqual(r_pdf.headers["content-type"], "application/pdf")
            self.assertTrue(r_pdf.content.startswith(b"%PDF-1.4"))
            self.assertTrue(len(r_pdf.headers.get("x-document-sha256", "")) == 64)

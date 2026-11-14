"""
tests/test_m51_squad_packs.py
=============================
Tests für M51: Portabler .archonpack Squad-Blueprint-Paketmanager.
"""

import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestM51SquadPacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.TemporaryDirectory()
        cls.dst_dir = tempfile.TemporaryDirectory()

        # Quell-Workspace befüllen
        with open(os.path.join(cls.src_dir.name, "roles.json"), "w", encoding="utf-8") as fh:
            json.dump(
                [
                    {"id": "cfo_lead", "name": "CFO Strategist", "domain": "Finance"},
                    {"id": "legal_counsel", "name": "Legal Counsel", "domain": "Legal"},
                ],
                fh,
            )
        with open(os.path.join(cls.src_dir.name, "agent_profiles.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "cfo_lead": {"model": "deepseek-chat", "api_key": "SUPER_SECRET_SHOULD_BE_SCRUBBED"},
                    "legal_counsel": {"model": "deepseek-chat", "bot_token": "SECRET_BOT_TOKEN"},
                },
                fh,
            )
        os.makedirs(os.path.join(cls.src_dir.name, "skills", "finance"), exist_ok=True)
        with open(os.path.join(cls.src_dir.name, "skills", "finance", "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("# Finance Skill\n")
        os.makedirs(os.path.join(cls.src_dir.name, "n8n_workflows"), exist_ok=True)
        with open(os.path.join(cls.src_dir.name, "n8n_workflows", "finance_sync.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "Finance Sync"}, fh)
        with open(os.path.join(cls.src_dir.name, "prompt_studio_catalog.json"), "w", encoding="utf-8") as fh:
            json.dump([{"id": "tpl_fin_1", "domain": "Finance", "title": "Cashflow Audit"}], fh)

        # Ziel-Workspace leer initialisieren
        with open(os.path.join(cls.dst_dir.name, "roles.json"), "w", encoding="utf-8") as fh:
            json.dump([], fh)
        with open(os.path.join(cls.dst_dir.name, "agent_profiles.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        with open(os.path.join(cls.dst_dir.name, "prompt_studio_catalog.json"), "w", encoding="utf-8") as fh:
            json.dump([], fh)

        from backend.squad_pack_manager import SquadPackManager

        cls.src_mgr = SquadPackManager(workspace_dir=cls.src_dir.name)
        cls.dst_mgr = SquadPackManager(workspace_dir=cls.dst_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.src_dir.cleanup()
        cls.dst_dir.cleanup()

    def test_01_list_domains_and_export_scrubs_secrets(self):
        domains = self.src_mgr.list_available_domains()
        self.assertEqual(len(domains), 2)

        zip_bytes, manifest = self.src_mgr.export_pack(name="finance-squad", domain="finance")
        self.assertEqual(manifest["stats"]["agents"], 1)
        self.assertEqual(manifest["stats"]["prompts"], 1)
        self.assertEqual(manifest["stats"]["n8n_workflows"], 1)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            profiles = json.loads(zf.read("agents/agent_profiles.json").decode("utf-8"))
            self.assertEqual(profiles["cfo_lead"]["api_key"], "")

    def test_02_inspect_rejects_zip_slip_and_tampering(self):
        # Zip-Slip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "pwned")
            zf.writestr("manifest.json", "{}")
        ok, res = self.dst_mgr.inspect_pack(buf.getvalue())
        self.assertFalse(ok)
        self.assertIn("Unsicherer Pfad", res["error"])

        # Tampering (SHA-256 mismatch)
        zip_bytes, _ = self.src_mgr.export_pack(name="finance-squad", domain="finance")
        tampered = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin, zipfile.ZipFile(tampered, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "agents/roles.json":
                    data = b"[]"
                zout.writestr(item.filename, data)
        ok_t, res_t = self.dst_mgr.inspect_pack(tampered.getvalue())
        self.assertFalse(ok_t)
        self.assertIn("Integritätsprüfung", res_t["error"])

    def test_03_import_roundtrip_and_router_endpoints(self):
        zip_bytes, _ = self.src_mgr.export_pack(name="finance-squad", domain="finance")

        from archon.routers.squad_packs import router as sp_router
        from backend.auth_service import auth_service

        app = FastAPI()
        app.include_router(sp_router)
        client = TestClient(app)

        with patch.object(auth_service, "is_auth_enabled", return_value=False), \
             patch("archon.routers.squad_packs.require_admin_or_503"), \
             patch("archon.routers.squad_packs.squad_pack_manager", self.dst_mgr):
            ins = client.post("/api/v1/squad-packs/inspect", files={"file": ("fin.archonpack", zip_bytes, "application/zip")})
            self.assertEqual(ins.status_code, 200)
            self.assertTrue(ins.json()["valid"])

            imp = client.post(
                "/api/v1/squad-packs/import",
                files={"file": ("fin.archonpack", zip_bytes, "application/zip")},
                data={"conflict_mode": "skip"},
            )
            self.assertEqual(imp.status_code, 200)
            self.assertEqual(imp.json()["imported"]["roles"], 1)
            self.assertEqual(imp.json()["imported"]["skills"], 1)
            self.assertEqual(imp.json()["imported"]["prompts"], 1)
            self.assertEqual(imp.json()["imported"]["n8n"], 1)
            self.assertTrue(os.path.exists(os.path.join(self.dst_dir.name, "skills", "finance", "SKILL.md")))

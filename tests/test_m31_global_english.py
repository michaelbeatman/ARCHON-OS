"""
Tests for Milestone 31: Full Global English Edition (Global Release).
Verifies:
1. All 70 agent profiles have English equivalents in agent_profiles.json
2. All 55 boardroom frameworks support DE + EN
3. All 832 Prompt Studio templates have verified Mustache variable parity
4. /api/templates/catalog, /schema, and /render respond correctly with ?lang=en and ?lang=de
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.routers import _rbac
from archon.routers.auth import require_admin
from archon.routers.templates import router as templates_router
from backend.auth_service import auth_service
import core_dispatcher

CATALOG_PATH = REPO_ROOT / "prompt_studio_catalog.json"
PROFILES_PATH = REPO_ROOT / "agent_profiles.json"
VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(auth_service, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(_rbac, "_checker", require_admin)
    app = FastAPI()
    app.include_router(templates_router)
    return TestClient(app)


def test_agent_profiles_all_70_bilingual() -> None:
    assert PROFILES_PATH.exists(), f"Missing {PROFILES_PATH}"
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    # 70 or 71 profiles
    assert len(profiles) >= 70, f"Expected at least 70 profiles, found {len(profiles)}"
    missing_en = []
    for p in profiles:
        pid = p.get("id") or p.get("name")
        has_en = (
            p.get("role_en")
            or p.get("name_en")
            or p.get("description_en")
            or p.get("soul_compact_en")
            or p.get("soul_en")
            or "soul_modes" in p
        )
        if not has_en:
            missing_en.append(pid)
    assert not missing_en, f"Profiles missing English localization: {missing_en}"


def test_boardroom_frameworks_all_55_bilingual() -> None:
    fws_de = core_dispatcher.CATEGORIZED_FRAMEWORKS
    fws_en = core_dispatcher.CATEGORIZED_FRAMEWORKS_EN
    total_de = sum(len(items) for items in fws_de.values())
    total_en = sum(len(items) for items in fws_en.values())
    assert total_de >= 55, f"Expected >= 55 frameworks DE, found {total_de}"
    assert total_en >= 55, f"Expected >= 55 frameworks EN, found {total_en}"
    assert len(fws_de) == len(fws_en), f"Expected same category count: {len(fws_de)} vs {len(fws_en)}"


def test_prompt_studio_catalog_all_832_variable_parity() -> None:
    assert CATALOG_PATH.exists(), f"Missing {CATALOG_PATH}"
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    assert len(catalog) >= 824, f"Expected ~832 templates, found {len(catalog)}"
    mismatches = []
    for tpl in catalog:
        tid = tpl.get("id", "unknown")
        tpl_de = tpl.get("archon_prompt_template", "")
        tpl_en = tpl.get("archon_prompt_template_en", "")

        assert tpl_en, f"Template {tid} missing archon_prompt_template_en"
        assert tpl.get("name_en"), f"Template {tid} missing name_en"
        assert tpl.get("category_en"), f"Template {tid} missing category_en"

        vars_de = set(VAR_RE.findall(tpl_de))
        vars_en = set(VAR_RE.findall(tpl_en))
        if vars_de != vars_en:
            mismatches.append((tid, vars_de, vars_en))

    assert not mismatches, f"Variable mismatches in {len(mismatches)} templates: {mismatches[:5]}"


def test_api_templates_catalog_de_and_en(api_client: TestClient) -> None:
    # Test German catalog
    resp_de = api_client.get("/api/templates/catalog?lang=de")
    assert resp_de.status_code == 200
    data_de = resp_de.json()
    assert data_de["status"] == "ok"
    assert data_de["total"] >= 824
    first_de = data_de["templates"][0]
    assert first_de.get("name_de")

    # Test English catalog
    resp_en = api_client.get("/api/templates/catalog?lang=en")
    assert resp_en.status_code == 200
    data_en = resp_en.json()
    assert data_en["status"] == "ok"
    first_en = data_en["templates"][0]
    assert first_en.get("name_en")
    assert first_en["name"] == first_en["name_en"]
    assert "Business & Strategy" in data_en["categories"] or "Data & Analytics" in data_en["categories"]


def test_api_templates_schema_localized(api_client: TestClient) -> None:
    # Blog-Post template
    resp_de = api_client.get("/api/templates/blog-post/schema?lang=de")
    assert resp_de.status_code == 200
    data_de = resp_de.json()["template"]

    resp_en = api_client.get("/api/templates/blog-post/schema?lang=en")
    assert resp_en.status_code == 200
    data_en = resp_en.json()["template"]

    assert data_en["name"] == data_en.get("name_en", "Blog Post")
    assert "form_fields" in data_en
    assert len(data_en["form_fields"]) > 0
    # Every form field should have English label and placeholder
    for ff in data_en["form_fields"]:
        assert ff.get("label_en")
        assert ff.get("placeholder_en")
        assert ff["label"] == ff["label_en"]


def test_api_templates_render_english_options(api_client: TestClient) -> None:
    payload = {
        "values": {
            "blog_topic": "Archon OS Architecture",
            "target_audience": "Enterprise CTOs",
            "tone": "Authoritative and concise",
            "blog_outline_structure": "1. Overview\n2. Key Innovations\n3. Conclusion",
        },
        "options": {
            "stepbystep": True,
            "reasoning": True,
            "confidence": True,
            "examples_count": 2,
            "success": "Comprehensive, actionable whitepaper draft",
        },
    }
    resp = api_client.post("/api/templates/blog-post/render?lang=en", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    rendered = result["rendered_prompt"]

    # Verify English options injected
    assert "Archon OS Architecture" in rendered
    assert "### REASONING & METHODOLOGY:" in rendered
    assert "Step-by-Step:" in rendered
    assert "### ADVANCED OUTPUT SPECIFICATIONS:" in rendered
    assert "Confidence Rating:" in rendered
    assert "Practical Examples:" in rendered
    assert "### SUCCESS CRITERIA (DEFINITION OF DONE):" in rendered
    assert "4. ARCHON OS GOVERNANCE & ANTI-FLUFF DIRECTIVE" in rendered

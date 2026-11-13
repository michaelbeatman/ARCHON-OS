"""
Unit tests for CorporateManager (Multi-Company & Template Hub)
"""

import os
import tempfile
import pytest
from backend.corporate_manager import CorporateManager


@pytest.fixture
def temp_corp_manager():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name
    
    # Initialize CorporateManager with temp file
    mgr = CorporateManager(filepath=temp_path)
    yield mgr
    
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_initial_company_creation(temp_corp_manager):
    companies = temp_corp_manager.list_companies()
    assert len(companies) == 1
    assert companies[0]["id"] == "archon-systems"
    assert companies[0]["name"] == "Archon Systems GmbH"
    assert companies[0]["is_active"] is True


def test_add_second_company_and_switch_active(temp_corp_manager):
    new_company = {
        "id": "antigravity-media",
        "name": "Antigravity Media UG",
        "legal_form": "UG (haftungsbeschränkt)",
        "slogan": "Next-Gen AI Publishing",
        "address": {
            "street": "Alexanderplatz 1",
            "postal_code": "10178",
            "city": "Berlin"
        },
        "tax": {
            "tax_number": "30/999/8888",
            "vat_id": "DE999888777"
        },
        "design": {
            "primary_color": "#10b981"
        }
    }
    saved = temp_corp_manager.save_company(new_company)
    assert saved["id"] == "antigravity-media"
    
    companies = temp_corp_manager.list_companies()
    assert len(companies) == 2
    
    # Switch active
    assert temp_corp_manager.set_active_company("antigravity-media") is True
    active_company = temp_corp_manager.get_company()
    assert active_company["id"] == "antigravity-media"
    assert active_company["is_active"] is True


def test_render_letterhead_template(temp_corp_manager):
    res = temp_corp_manager.render_template(
        "letterhead",
        custom={
            "recipient_name": "Acme Corp",
            "subject": "Kooperationsvertrag 2026",
            "body_text": "Wir freuen uns auf die Zusammenarbeit."
        }
    )
    assert res["template_type"] == "letterhead"
    assert "Archon Systems GmbH" in res["html"]
    assert "Acme Corp" in res["html"]
    assert "Kooperationsvertrag 2026" in res["html"]
    assert "DE345678901" in res["html"]


def test_render_invoice_template(temp_corp_manager):
    res = temp_corp_manager.render_template(
        "invoice",
        custom={
            "invoice_num": "RE-2026-999",
            "recipient_name": "Testkunde AG"
        }
    )
    assert res["template_type"] == "invoice"
    assert "RE-2026-999" in res["html"]
    assert "Testkunde AG" in res["html"]
    assert "USt-IdNr." in res["html"]
    assert "Gesamtbetrag:" in res["html"]


def test_render_nda_template(temp_corp_manager):
    res = temp_corp_manager.render_template(
        "nda",
        custom={
            "recipient_name": "Partner AG"
        }
    )
    assert res["template_type"] == "nda"
    assert "Vertraulichkeitsvereinbarung (NDA)" in res["html"]
    assert "Partner AG" in res["html"]
    assert "DSGVO / Geschäftsgeheimnisgesetz" in res["html"]


def test_delete_company_prevent_last(temp_corp_manager):
    # Trying to delete the only company should return False
    assert temp_corp_manager.delete_company("archon-systems") is False

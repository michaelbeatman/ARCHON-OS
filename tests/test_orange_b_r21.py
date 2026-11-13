"""Regressionstest R-21: unbekannte company_id darf nicht auf andere Rechtsperson ausweichen.

Vor dem Fix lieferte `get_company(<unbekannt>)` still `companies[0]` — Name,
Steuernummer und IBAN einer ANDEREN Firma landeten auf Rechnung/Angebot.
"""

import os
import tempfile

import pytest

from backend.corporate_manager import CorporateManager, DEFAULT_PRIMARY_COMPANY


@pytest.fixture
def temp_corp_manager():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name
    mgr = CorporateManager(filepath=temp_path)
    # Zweite Firma anlegen, damit companies[0] != default ist und ein stilles
    # Ausweichen auf companies[0] sichtbar wuerde.
    mgr.save_company({
        "id": "firma-a", "name": "Firma A GmbH",
        "tax": {"tax_number": "TA-1", "vat_id": "DE111"},
        "bank": {"iban": "DE00 0000 0000 0000 0000 01"},
    })
    mgr.save_company({
        "id": "firma-b", "name": "Firma B GmbH",
        "tax": {"tax_number": "TB-2", "vat_id": "DE222"},
        "bank": {"iban": "DE00 0000 0000 0000 0000 02"},
    })
    yield mgr
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_get_company_unknown_id_returns_none(temp_corp_manager):
    assert temp_corp_manager.get_company("gibt-es-nicht") is None


def test_get_company_known_id_still_works(temp_corp_manager):
    comp = temp_corp_manager.get_company("firma-a")
    assert comp is not None
    assert comp["name"] == "Firma A GmbH"


def test_get_company_without_id_returns_active(temp_corp_manager):
    comp = temp_corp_manager.get_company()
    assert comp is not None
    assert comp["id"] in ("archon-systems", "firma-a", "firma-b")
    assert comp["is_active"] is True


def test_render_template_unknown_company_raises(temp_corp_manager):
    with pytest.raises(ValueError):
        temp_corp_manager.render_template(template_type="invoice", company_id="gibt-es-nicht")


def test_render_template_known_company_ok(temp_corp_manager):
    res = temp_corp_manager.render_template(template_type="offer", company_id="firma-a")
    assert "Firma A GmbH" in res["html"]

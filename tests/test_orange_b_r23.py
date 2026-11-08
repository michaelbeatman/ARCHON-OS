"""Regressionstest R-23: USt-Satz und Rabatt pro Position im Vorlagen-Druck.

Vor dem Fix: fest `0.0 if is_small else 0.19` und Summen aus qty*price —
ein Beleg mit 7-%-Position druckte 19 % USt und einen falschen Bruttobetrag;
Zeilenrabatte (discount_pct) wurden komplett ignoriert.
"""

import os
import tempfile

from backend.corporate_manager import CorporateManager


def _render_with(filepath, items, small_business=False, template_type="invoice"):
    mgr = CorporateManager(filepath=filepath)
    mgr.save_company({
        "id": "firma-a", "name": "Firma A GmbH",
        "tax": {"tax_number": "TA-1", "vat_id": "DE111", "small_business": small_business},
    })
    res = mgr.render_template(template_type=template_type, company_id="firma-a", custom={"items": items})
    return res["html"]


def test_7_percent_item_uses_7_percent_tax():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        html = _render_with(path, [
            {"pos": 1, "desc": "Buch (7%)", "qty": 2, "unit": "Stk", "price": 10.00, "tax_rate_pct": 7.0},
        ])
        # 2 x 10 EUR netto = 20,00; 7 % = 1,40; brutto = 21,40
        assert "Umsatzsteuer (7%):" in html
        assert "21.40 €" in html
        assert "19%" not in html.replace("Umsatzsteuer (7%)", "")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_discount_pct_reduces_line_total_and_gross():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        html = _render_with(path, [
            {"pos": 1, "desc": "Beratung", "qty": 10, "unit": "Std", "price": 100.00, "discount_pct": 10.0},
        ])
        # 10 x 100 = 1000, minus 10 % = 900; 19 % = 171; brutto = 1071,00
        assert "1,071.00 €" in html  # Tausender-Trenner wie `:,.2f`
        assert "900.00 €" in html  # Zeilen-Gesamt nach Rabatt
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_mixed_tax_rates_render_separate_buckets():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        html = _render_with(path, [
            {"pos": 1, "desc": "Software", "qty": 1, "unit": "Stk", "price": 100.00, "tax_rate_pct": 19.0},
            {"pos": 2, "desc": "Buch", "qty": 1, "unit": "Stk", "price": 100.00, "tax_rate_pct": 7.0},
        ])
        assert "Umsatzsteuer (19%):" in html
        assert "Umsatzsteuer (7%):" in html
        # 119,00 + 107,00 = 226,00 brutto
        assert "226.00 €" in html
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_small_business_still_zero_tax_but_discount_applies():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        html = _render_with(path, [
            {"pos": 1, "desc": "Dienstleistung", "qty": 1, "unit": "Pauschal", "price": 500.00, "discount_pct": 20.0},
        ], small_business=True)
        # 500 minus 20 % = 400 netto, keine USt
        assert "400.00 €" in html
        assert "kleinunternehmer" in html.lower() or "§ 19 UStG" in html
    finally:
        if os.path.exists(path):
            os.remove(path)

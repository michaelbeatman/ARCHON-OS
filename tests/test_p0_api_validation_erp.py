"""P0 API-Validierung Etappe 2d: erp.py (10 Endpunkte).

ERP-Daten (Kontakte, Belege, Bank) sind besonders sensibel: rohe Dict-Bodies
liessen bisher beliebige Typen zu. extra='allow' bleibt dort erhalten, wo
erp_manager den kompletten Payload weiterverarbeitet.
"""

import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import erp  # noqa: E402


def test_erp_models_exist_and_validate_types():
    with pytest.raises(ValidationError):
        erp.ErpBankImportRequest(content=123)
    with pytest.raises(ValidationError):
        erp.ErpMatchBankTransactionRequest(mark_paid="maybe")


def test_erp_payload_models_keep_arbitrary_business_fields():
    model = erp.ErpPayloadRequest(company_id="default", custom_field={"nested": 1})
    dumped = model.model_dump()
    assert dumped["custom_field"] == {"nested": 1}
    assert dumped["company_id"] == "default"


def test_erp_cancel_request_validates_reason_type():
    with pytest.raises(ValidationError):
        erp.ErpCancelDocumentRequest(reason=["not", "a", "string"])

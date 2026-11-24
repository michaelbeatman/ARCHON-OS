"""Re-Audit Etappe 9 — D12: keine Fake-Fakten, echte Kosten, leere SSE als Fehler."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d12_notebook_no_fabricated_analysis():
    src = (ROOT / "utils" / "notebook_engine.py").read_text(encoding="utf-8")
    assert "### 📊 Fundierte Analyse & Antwort:" not in src
    assert "Die hinterlegten Dokumente bestaetigen" not in src
    block = src.split("except ZeroEgressBlockedError:", 1)[1].split("except Exception", 1)[0]
    assert "raise" in block
    assert "LLM_NOT_AVAILABLE" in src
    assert '"status": "blocked"' in src


def test_d12_receipt_no_invented_financial_facts():
    import backend.receipt_ocr_engine as roe

    engine = roe.ReceiptOCREngine.__new__(roe.ReceiptOCREngine)
    engine.extract_metadata_from_vision = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("VISION_EXTRACTION_FAILED")
    )
    result = engine.process_receipt(b"fake-image-bytes", filename="r.jpg")
    assert result["status"] == "needs_manual_review"
    assert result["amount_gross"] is None
    assert result["date"] is None
    assert "erfunden" in result["note"]


def test_d12_stream_cost_is_estimated():
    src = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    assert "cost_usd=0.0" not in src
    assert "estimate_model_cost_usd(m_try, _p_toks, _c_toks" in src
    assert "Stream-Kostenberechnung fehlgeschlagen" in src


def test_d12_empty_sse_is_an_error():
    router = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    kernel = (ROOT / "backend" / "llm_kernel.py").read_text(encoding="utf-8")
    assert "received_payload_chunks" in router
    assert "Leere LLM-Antwort (HTTP 200 ohne Nutzlast)" in router
    assert 'any(str(c).startswith("ERROR:")' in kernel


def test_d12_flightlog_trace_fallback():
    src = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    block = src.split("def _detect_chat_silent_failure", 1)[1].split("\nclass ", 1)[0]
    assert "current_trace_id" in block


def test_d12_dag_cost_not_zero_on_error():
    src = (ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "_cost_usd = None" in src
    assert '"cost_unverified": _cost_unverified' in src
    assert "Kostenberechnung fehlgeschlagen" in src

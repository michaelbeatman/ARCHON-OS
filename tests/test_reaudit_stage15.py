"""Re-Audit Etappe 15 — D02 0-Token-Pfad und D10 externer Watchdog-Prozess."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d02_zero_token_path_wired_in_master_chat():
    src = (ROOT / "backend" / "agent_router.py").read_text(encoding="utf-8")
    block = src.split("async def stream_chat_completion", 1)[1].split(
        "self._reserve_task_budget(", 1
    )[0]
    assert "classify_execution_layer" in block
    assert "deterministic_n8n" in block
    assert "deterministic_script" in block
    assert "0 Tokens" in block
    assert "DETERMINISTIC_HITL_REQUIRED" in block
    assert "EXECUTION_ROUTING_GUARD_UNAVAILABLE" in block


def test_d02_classifier_detects_webhook_directive():
    from backend.execution_routing_guard import classify_execution_layer
    erg = classify_execution_layer("ACTION: WEBHOOK_CRM", "Bitte CRM synchronisieren")
    assert erg["layer"] == "deterministic_n8n"
    assert erg["token_free"] is True
    assert erg["requires_llm"] is False


def test_d10_watchdog_is_separate_process():
    src = (ROOT / "watchdog_daemon.py").read_text(encoding="utf-8")
    block = src.split("def _watchdog_process_main", 1)[1]
    assert "multiprocessing" in block
    assert 'get_context("spawn")' in block
    assert "ArchonWatchdogProcess" in block
    assert "target=_watchdog_process_main" in block
    # Thread bleibt nur dokumentierter Fallback, nicht mehr Default.
    assert "Fallback Thread" in block

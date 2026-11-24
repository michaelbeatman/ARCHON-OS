# -*- coding: utf-8 -*-
"""Re-Audit Stage 1 — Regressionstests fuer die behobenen MED-Funde aus
domain_01.md, domain_02.md und domain_05.md.

Rein implementierend: keine Migration, kein Replay, kein Audit-Report-Zugriff.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# D01/MED — Anti-Slop-Gate fail-closed
# ---------------------------------------------------------------------------

def _text_item(min_score: float = 0.0) -> dict:
    return {
        "id": "med-d01",
        "expected_keywords": [],
        "forbidden_patterns": [],
        "schema_required": [],
        "min_score": min_score,
    }


def test_d01_anti_slop_internal_error_blocks_release(monkeypatch):
    from backend import content_machine, eval_gates

    def _boom(*args, **kwargs):
        raise RuntimeError("content_machine intern fehlgeschlagen")

    monkeypatch.setattr(content_machine, "evaluate_asset_quality", _boom)

    result = eval_gates._evaluate_text_item(
        _text_item(), "Eine hinreichend lange, saubere Antwort ohne Slop.", 1.0, 0.0
    )
    assert result["anti_slop_score"] == 0.0
    assert result["passed"] is False
    assert any("Anti-Slop-Prüfung fehlgeschlagen" in f for f in result["failures"])


def test_d01_anti_slop_low_score_blocks_release(monkeypatch):
    from backend import content_machine, eval_gates

    monkeypatch.setattr(
        content_machine,
        "evaluate_asset_quality",
        lambda asset: {"score": 42.0},
    )
    result = eval_gates._evaluate_text_item(
        _text_item(), "Eine hinreichend lange, saubere Antwort ohne Slop.", 1.0, 0.0
    )
    assert result["anti_slop_score"] == 42.0
    assert result["passed"] is False


def test_d01_anti_slop_good_score_can_pass(monkeypatch):
    from backend import content_machine, eval_gates

    monkeypatch.setattr(
        content_machine,
        "evaluate_asset_quality",
        lambda asset: {"score": 95.0},
    )
    result = eval_gates._evaluate_text_item(
        _text_item(), "Eine hinreichend lange, saubere Antwort ohne Slop.", 1.0, 0.0
    )
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# D01/MED — Tool-Output-Firewall: None/leer ist kein Erfolg
# ---------------------------------------------------------------------------

def test_d01_none_tool_output_is_not_literal_none():
    from backend.tool_output_firewall import guard_tool_output

    guarded = guard_tool_output("web_fetch", None)
    assert guarded["status"] == "error"
    assert guarded["error"] == "EMPTY_TOOL_RESULT"
    assert guarded["output"] == ""
    assert "None" not in guarded["output"]

    blank = guard_tool_output("web_fetch", "   \n  ")
    assert blank["status"] == "error"
    assert blank["error"] == "EMPTY_TOOL_RESULT"


def test_d01_nonempty_tool_output_is_still_wrapped():
    from backend.tool_output_firewall import guard_tool_output

    guarded = guard_tool_output("web_fetch", "echter Inhalt")
    assert guarded["status"] == "ok"
    assert "UNTRUSTED TOOL OUTPUT" in guarded["output"]
    assert "echter Inhalt" in guarded["output"]


def test_d01_batch_empty_result_is_not_reported_as_ok():
    from backend.tool_output_firewall import run_batch_tool_calls

    async def _executor(name, args):
        return None

    results = asyncio.run(
        run_batch_tool_calls([{"tool": "x", "args": {}}], _executor)
    )
    assert results[0]["status"] == "error"
    assert results[0]["error"] == "EMPTY_TOOL_RESULT"
    assert "None" not in results[0]["output"]


# ---------------------------------------------------------------------------
# D01/MED + D02/MED — Capture-Pfad: ehrliche Metadaten, registrierte Agent-ID
# ---------------------------------------------------------------------------

def test_d01_d02_capture_uses_honest_subagents_and_registered_agent(monkeypatch):
    import core_dispatcher
    from archon.routers import mission_control as mc

    monkeypatch.setattr(core_dispatcher, "detect_target_action", lambda title: "none")
    monkeypatch.setattr(mc, "broadcast_event", lambda *a, **k: None)
    monkeypatch.setattr(mc, "get_token", lambda *a, **k: None)
    monkeypatch.setattr(mc, "update_mission_control_data", lambda mutator: mutator({"tasks": []}))

    result = asyncio.run(
        mc.capture_mission_control_task(mc.NewTaskCaptureRequest(title="Normale Aufgabe"))
    )
    task = result["task"]

    assert task["subagents_count"] == 0
    assert task["subagents_count_source"] == "none_yet"
    assert task["subagents_count_estimated"] is False
    assert task["estimated_subagents"] >= 0  # Triageschaetzung bleibt sichtbar
    assert task["agent_id"] == "default"
    assert task["agent_name"] == "Default Agent"

    roles = json.loads((ROOT / "roles.json").read_text(encoding="utf-8"))
    registered = {r.get("id") for r in roles if isinstance(r, dict)}
    assert task["agent_id"] in registered
    assert "micha" not in registered

    audit = asyncio.run(
        mc.capture_mission_control_task(mc.NewTaskCaptureRequest(title="Audit durchführen"))
    )
    assert audit["task"]["agent_id"] == "sandy"


def test_d02_no_hardcoded_removed_profile_id_in_owned_files():
    from archon.services import profiles_service as ps

    assert "micha" not in ps.PROTECTED_PROFILES

    forbidden_snippets = (
        'else "micha"',
        ', "micha", "default")',
        '["default", "micha"]',
        '"founder", "micha")',
    )
    for rel in (
        "archon/routers/mission_control.py",
        "archon/core/orchestration.py",
        "archon/services/profiles_service.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"{rel} contains removed profile pattern: {snippet}"


# ---------------------------------------------------------------------------
# D01/MED — release_approved ist ein Diagnosewert ohne Konsument
# ---------------------------------------------------------------------------

def test_d01_release_approved_is_explicitly_advisory(monkeypatch, tmp_path):
    from backend import eval_regression_runner as err

    monkeypatch.setattr(err, "DB_PATH", str(tmp_path / "eval.db"))
    monkeypatch.setattr(
        err,
        "_get_cfg",
        lambda: {"enabled": True, "min_pass_rate_pct": 90, "block_deploy_on_regression": True},
    )

    result = err.EvalRegressionRunner().run_suite()
    assert result["status"] == "no_executor"
    assert result["release_approved"] is False
    assert result["advisory_only"] is True
    assert result["release_gate_consumer"] is None
    assert "keinem" in result["release_note"]


# ---------------------------------------------------------------------------
# D05/MED — Quittungskette: kein stiller SHA-256-Fallback
# ---------------------------------------------------------------------------

def test_d05_receipt_digest_without_key_fails_closed(monkeypatch):
    from backend import execution_receipt_ledger as erl

    for env in (
        "ARCHON_RECEIPT_HMAC_KEY",
        "ARCHON_RECEIPT_HMAC_EPOCHS",
        "ARCHON_AUDIT_HMAC_KEY",
        "ARCHON_AUDIT_HMAC_EPOCHS",
    ):
        monkeypatch.delenv(env, raising=False)

    with pytest.raises(RuntimeError, match="HMAC-Key fehlt"):
        erl._receipt_digest("a|b|c")

    legacy = erl._receipt_digest("a|b|c", allow_legacy=True)
    assert legacy == hashlib.sha256(b"a|b|c").hexdigest()


def test_d05_chain_without_key_is_never_valid(monkeypatch, tmp_path):
    from backend import execution_receipt_ledger as erl

    for env in (
        "ARCHON_RECEIPT_HMAC_KEY",
        "ARCHON_RECEIPT_HMAC_EPOCHS",
        "ARCHON_AUDIT_HMAC_KEY",
        "ARCHON_AUDIT_HMAC_EPOCHS",
    ):
        monkeypatch.delenv(env, raising=False)

    ledger = erl.ExecutionReceiptLedger(db_path=str(tmp_path / "receipts.db"))
    result = ledger._verify_chain_integrity_raw()
    assert result["hmac_protected"] is False
    assert result["chain_valid"] is False


def test_d05_chain_with_key_remains_valid(monkeypatch, tmp_path):
    from backend import execution_receipt_ledger as erl

    monkeypatch.setenv("ARCHON_RECEIPT_HMAC_KEY", "med-d05-test-key-32-bytes-minimum-ok")

    ledger = erl.ExecutionReceiptLedger(db_path=str(tmp_path / "receipts.db"))
    receipt = ledger.issue_receipt(
        task_id="med-d05",
        agent_role="default",
        model_used="test-model",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.01,
        tools_invoked=[],
    )
    assert receipt["receipt_hash"].startswith(erl.RECEIPT_HMAC_PREFIX)
    result = ledger._verify_chain_integrity_raw()
    assert result["hmac_protected"] is True
    assert result["chain_valid"] is True

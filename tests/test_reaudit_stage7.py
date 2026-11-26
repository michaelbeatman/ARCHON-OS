"""Re-Audit Etappe 7 — D11: schema-validierte Handoffs, HMAC-Konsument, Canary-Ref."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from archon.core.delegation import (
    DelegationPayload,
    HandoffDelegationPayload,
    _parse_delegation_blocks,
    canonicalize_delegation_payload,
    verify_delegation_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def test_d11_payload_requires_target_and_task(monkeypatch):
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w5b-delegation-key")
    # F030/W3-A: EIN kanonisches Schema an der Handoff-Kante (alias-faehig).
    assert DelegationPayload is HandoffDelegationPayload
    with pytest.raises(ValidationError):
        HandoffDelegationPayload.model_validate({"ziel_agent": ""})
    with pytest.raises(ValidationError):
        HandoffDelegationPayload.model_validate({"auftrag": "Fix"})
    # extra="forbid" ist das korrekte Soll-Verhalten: Schattenfelder duerfen
    # nicht mehr still verworfen werden (frueher: extra="ignore").
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HandoffDelegationPayload.model_validate(
            {"ziel_agent": "coder", "auftrag": "Fix", "extra": "ignored"}
        )
    p = HandoffDelegationPayload.model_validate({"ziel_agent": "coder", "auftrag": "Fix"})
    assert p.ziel_agent == "coder"
    assert p.acceptance_criteria == ""

    # Der kanonische Helfer normalisiert Legacy-Aliase, dokumentiert Unknowns
    # in `extensions` und setzt/signiert den Server-Kontext (kein Body-Vertrauen).
    canon = canonicalize_delegation_payload(
        {"agent": "coder", "prompt": "Fix", "extra": "ignored"},
        task_id="task-w5b",
    )
    assert canon["ziel_agent"] == "coder"
    assert canon["auftrag"] == "Fix"
    assert canon["cancel_scope"] == "task:task-w5b"
    assert canon["extensions"]["extra"] == "ignored"
    assert canon["payload_signature"].startswith("dlg-hmac-sha256:")
    assert verify_delegation_payload(canon) is True


def test_d11_parser_schema_validates_before_dispatch():
    good = json.dumps({"ziel_agent": "coder", "auftrag": "Fix", "acceptance_criteria": "Tests grün"})
    bad = json.dumps({"ziel_agent": "coder"})
    valid, invalid = _parse_delegation_blocks(f"```delegation\n{good}\n```\n```delegation\n{bad}\n```")
    assert len(valid) == 1
    assert valid[0]["acceptance_criteria"] == "Tests grün"
    assert any("DelegationPayload" in str(i.get("error", "")) for i in invalid)


def test_d11_no_dead_import_fallback(tmp_path, monkeypatch):
    # G7/D3-6: Ausfuehrungsteil liegt in backend/operations_execution.py;
    # keine toten Import-Fallbacks mehr + echter Verhaltens-Gate-Aufruf.
    api_src = (ROOT / "backend" / "operations_api.py").read_text(encoding="utf-8")
    exec_src = (ROOT / "backend" / "operations_execution.py").read_text(encoding="utf-8")
    combined = api_src + "\n" + exec_src
    assert "DelegationPayload = None" not in combined
    assert "class KanbanDelegationPayload" not in combined

    import backend.operations_api as ops_api
    import backend.operations_execution as ops_exec
    from backend.handoff_desk import HandoffDesk, require_accepted_handoff

    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "f00-stage7-delegation-key")
    monkeypatch.setenv("ARCHON_HANDOFF_HMAC_KEY", "f00-stage7-handoff-key")

    # Echter Aufruf der Kanban-Payload-Konsumentenseite (kein toter Fallback)
    loaded = ops_api._load_kanban_delegation_payload(
        {"ziel_agent": "coder", "auftrag": "Fix F00"}, task_id="task-f00-load"
    )
    assert isinstance(loaded, HandoffDelegationPayload)
    assert loaded.ziel_agent == "coder"
    assert ops_api._load_kanban_delegation_payload({"ziel_agent": ""}, task_id="task-f00-bad") is None
    assert ops_exec.require_accepted_handoff is require_accepted_handoff

    desk = HandoffDesk(db_path=str(tmp_path / "handoffs.db"))

    # Positivprobe: gueltige signierte Uebergabe wird akzeptiert.
    created = desk.create_handoff(
        task_id="task-f00-ok",
        from_agent="orchestrator",
        to_agent="coder",
        deliverables={"result": "ready", "status": "ok"},
        acceptance_criteria="Tests gruen",
    )
    ok_gate = require_accepted_handoff("task-f00-ok", "coder", desk=desk)
    assert ok_gate["allowed"] is True
    assert ok_gate["reason"] == "accepted"

    # Negativprobe 1: falscher Executor wird abgewiesen (keine Self-Attestation).
    wrong_exec = require_accepted_handoff("task-f00-ok", "reviewer", desk=desk)
    assert wrong_exec["allowed"] is False
    assert "executor_mismatch" in wrong_exec["reason"]

    # Negativprobe 2: manipulierter Payload in DB bricht HMAC -> abgewiesen.
    with desk._get_conn() as conn:
        conn.execute(
            "UPDATE agent_handoffs SET deliverables_json = ? WHERE id = ?",
            (json.dumps({"result": "TAMPERED", "status": "ok"}), created["handoff_id"]),
        )
        conn.commit()
    tampered_gate = require_accepted_handoff("task-f00-ok", "coder", desk=desk)
    assert tampered_gate["allowed"] is False
    assert tampered_gate["reason"] == "handoff_hmac_invalid"

    # Negativprobe 3: unsignierter Payload (leerer payload_hash) -> abgewiesen.
    unsigned = desk.create_handoff(
        task_id="task-f00-unsigned",
        from_agent="orchestrator",
        to_agent="coder",
        deliverables={"result": "raw", "status": "ok"},
        acceptance_criteria="Signaturpflicht",
    )
    with desk._get_conn() as conn:
        conn.execute(
            "UPDATE agent_handoffs SET payload_hash = '' WHERE id = ?",
            (unsigned["handoff_id"],),
        )
        conn.commit()
    unsigned_gate = require_accepted_handoff("task-f00-unsigned", "coder", desk=desk)
    assert unsigned_gate["allowed"] is False
    assert unsigned_gate["reason"] == "handoff_hmac_invalid"


def test_d11_structured_handoff_and_hmac_consumer(tmp_path, monkeypatch):
    from archon.core.delegation import sign_delegation_payload
    from backend.handoff_desk import HandoffDesk, mark_truncated

    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "f00-delegation-hmac-key")
    monkeypatch.setenv("ARCHON_HANDOFF_HMAC_KEY", "f00-handoff-hmac-key")

    # 1. Signatur-Roundtrip + Manipulations-Negativprobe
    canon = canonicalize_delegation_payload(
        {"ziel_agent": "coder", "auftrag": "Implement F00"},
        task_id="task-f00-sig",
    )
    assert canon["payload_signature"] == sign_delegation_payload(canon)
    assert verify_delegation_payload(canon) is True

    tampered = dict(canon, auftrag="Manipulierter Auftrag")
    assert verify_delegation_payload(tampered) is False

    unsigned = dict(canon, payload_signature="")
    assert verify_delegation_payload(unsigned) is False

    # 2. Kuerzung markiert explizit statt still abzuschneiden
    long_text = "A" * 5000
    truncated = mark_truncated(long_text, 4000, artifact="test_artifact")
    assert len(truncated) <= 4000
    assert "gekürzt:" in truncated and "test_artifact" in truncated

    # 3. HandoffDesk.verify_payload_hash prueft echten HMAC und erkennt Manipulation
    desk = HandoffDesk(db_path=str(tmp_path / "verify.db"))
    created = desk.create_handoff(
        task_id="task-f00-verify",
        from_agent="orchestrator",
        to_agent="coder",
        deliverables={"result": "clean", "status": "ok"},
        acceptance_criteria="HMAC intakt",
    )
    assert desk.verify_payload_hash(created["handoff_id"]) is True
    with desk._get_conn() as conn:
        conn.execute(
            "UPDATE agent_handoffs SET acceptance_criteria = 'TAMPERED' WHERE id = ?",
            (created["handoff_id"],),
        )
        conn.commit()
    assert desk.verify_payload_hash(created["handoff_id"]) is False


def test_d11_stream_prompt_ref_is_resolved():
    src = (ROOT / "backend" / "llm_kernel.py").read_text(encoding="utf-8")
    assert "prompt_registry.get_effective_prompt" in src
    assert '"source": "prompt_registry"' in src
    assert "hashlib.sha256" in src

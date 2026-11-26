"""Re-Audit Stage 2 / Agent E — verbleibende MED-Funde in eigenen Services.

Deckt die im Working Tree noch offenen Funde aus Domain 03/04/06/07/14 ab:
busy_timeout-SSOT-Konsument, ERP-Fail-Closed/GoBD-Trigger, Dunning-UPSERT,
Voice-Egress-Block, typisierter Reset-Body, Cancel-Eskalation,
TenantDB-Konsolidierungscheck und HITL-/Approval-Schwellen.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _src(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# D03 — busy_timeout SSOT ist kein toter Code mehr
# ---------------------------------------------------------------------------


def test_d03_busy_timeout_detector_has_real_cli_gate(tmp_path):
    from backend.db_paths import audit_busy_timeout_cli, audit_busy_timeout_ssot

    fake = tmp_path / "backend"
    fake.mkdir()
    (fake / "drift.py").write_text('x = "PRAGMA busy_timeout=9000;"\n', encoding="utf-8")
    offenders = audit_busy_timeout_ssot(str(tmp_path))
    assert ("backend/drift.py", 1, "9000") in offenders

    assert audit_busy_timeout_cli([
        "--root", str(tmp_path), "--audit-busy-timeout",
    ]) == 1
    assert audit_busy_timeout_cli([
        "--root", str(tmp_path), "--audit-busy-timeout",
        "--allow-drift", "backend/drift.py",
    ]) == 0


def test_d03_durable_kernel_uses_ssot_and_closes_connections(tmp_path):
    from backend.durable_execution_kernel import DB_BUSY_TIMEOUT_MS, _connect

    db = tmp_path / "kernel.db"
    with _connect(str(db)) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == DB_BUSY_TIMEOUT_MS
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")  # _ArchonClosingConn schliesst beim with-Exit
    assert "PRAGMA busy_timeout=15000" not in _src("backend/durable_execution_kernel.py")


def test_d03_erp_resolver_fail_closed_under_full_isolation(monkeypatch):
    import backend.erp_manager as erp

    monkeypatch.setenv("ARCHON_TENANT_FULL_ISOLATION", "1")

    class _Broken:
        def resolve_active_db(self, *args, **kwargs):
            raise RuntimeError("resolver down")

    monkeypatch.setattr("backend.tenant_context.tenant_context", _Broken())
    with pytest.raises(RuntimeError, match="FULL_TENANT_ISOLATION"):
        erp.get_tenant_db_path("cid-1")


def test_d03_gobd_trigger_blocks_tampering():
    src = _src("backend/erp_manager.py")
    assert "erp_documents_gobd_no_tamper" in src
    # D03/M5: der Trigger wird bewusst per DROP+CREATE erneuert — IF NOT EXISTS
    # würde die alte, unvollständige Version stehen lassen.
    m = re.search(
        r"CREATE TRIGGER(?:\s+IF\s+NOT\s+EXISTS)?\s+erp_documents_gobd_no_tamper\b.*?\bEND\b",
        src, re.DOTALL,
    )
    assert m is not None

    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE erp_documents (
        id TEXT PRIMARY KEY, doc_number TEXT, recipient_snapshot_json TEXT, booked_at TEXT,
        status TEXT, amount_net REAL, tax_amount REAL, amount_gross REAL,
        entity_id TEXT, issue_date TEXT
    )""")
    conn.execute(m.group(0))
    conn.execute(
        "INSERT INTO erp_documents VALUES ('d1', 'RE-1', '{}', '2026-01-01 10:00:00', "
        "'booked', 1.0, 0.0, 1.0, 'e1', '2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="GoBD"):
        conn.execute(
            "UPDATE erp_documents SET recipient_snapshot_json = '{\"changed\":1}' WHERE id = 'd1'"
        )
    # identischer Wert bleibt zulaessig (Status-Updates schreiben booked_at unverändert)
    conn.execute(
        "UPDATE erp_documents SET booked_at = '2026-01-01 10:00:00' WHERE id = 'd1'"
    )
    conn.close()


def test_d03_dunning_task_upsert_preserves_status():
    src = _src("backend/dunning_engine.py")
    assert "INSERT OR REPLACE INTO tasks" not in src
    assert "ON CONFLICT(id) DO UPDATE SET" in src
    assert "status = excluded.status" not in src  # Status bleibt unberührt


# ---------------------------------------------------------------------------
# D04 — Voice-Egress
# ---------------------------------------------------------------------------


def test_d04_voice_egress_block_is_not_swallowed(monkeypatch, tmp_path):
    import backend.voice_pipeline as vp
    from backend.llm_egress_guard import ZeroEgressBlockedError

    monkeypatch.setattr(vp, "GROQ_API_KEY", "g-key")
    monkeypatch.setattr(vp, "OPENAI_API_KEY", "o-key")
    monkeypatch.setattr(vp, "GOOGLE_API_KEY", "")

    def _deny(*args, **kwargs):
        raise ZeroEgressBlockedError("blocked", error_code="TEST_BLOCK")

    monkeypatch.setattr(vp, "_gate_cloud_voice_dispatch", _deny)
    monkeypatch.setattr(
        "backend.privacy_router.get_privacy_config", lambda: {"zero_egress_strict": False},
        raising=False,
    )

    class _NoClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("kein Cloud-Dispatch nach Egress-Block")

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_NoClient))
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"ogg")

    with pytest.raises(ZeroEgressBlockedError):
        asyncio.run(vp.transcribe_audio_bytes(b"ogg", filename="a.ogg"))


def test_d04_voice_tts_routes_through_shared_gate(monkeypatch, tmp_path):
    import backend.voice_pipeline as vp

    seen = {}

    def _gate(url, *, provider, model, metadata, data_category):
        seen.update(url=url, provider=provider, category=data_category, metadata=metadata)
        return {"prompt": "masked text"}

    monkeypatch.setattr(vp, "_gate_cloud_voice_dispatch", _gate)

    captured = {}

    class _Communicate:
        def __init__(self, text, voice):
            captured["text"] = text
            captured["voice"] = voice

        async def save(self, path):
            Path(path).write_bytes(b"mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=_Communicate))
    out = tmp_path / "tts.mp3"
    result = asyncio.run(vp.synthesize_speech("secret text", output_path=str(out)))

    assert result == str(out)
    assert seen["provider"] == "edge-tts"
    assert seen["category"] == "voice_tts"
    assert seen["metadata"]["prompt"] == "secret text"
    assert captured["text"] == "masked text"  # nur sanitierter Text geht raus


# ---------------------------------------------------------------------------
# D06 — typisierter Admin-Body
# ---------------------------------------------------------------------------


def test_d06_reset_zombies_uses_typed_body():
    src = _src("backend/operations_api.py")
    assert "class ResetZombieTasksRequest(BaseModel)" in src
    assert "payload: dict = Body(default={})" not in src
    assert 'Literal["todo", "blocked", "review", "done"]' in src


# ---------------------------------------------------------------------------
# D07 — Cancel-Eskalation, TenantDB-Fail-Closed, Durable-Resume
# ---------------------------------------------------------------------------


def test_d07_cancel_failures_are_persisted_and_can_raise():
    from backend.cancellation import CancelToken, failed_cancellations, get_token

    class _BadTask:
        def done(self):
            return False

        def get_loop(self):
            return None

        def add_done_callback(self, fn):
            pass

        def cancel(self):
            raise RuntimeError("cancel boom")

    token = get_token("scope:test")
    assert isinstance(token, CancelToken)
    token.register_task(_BadTask())  # type: ignore[arg-type]
    token.cancel("timeout")
    assert token.cancellation_failed is True
    assert token.failed_cancels
    assert "scope:test" in failed_cancellations()

    strict = CancelToken("scope:strict")
    strict.register_task(_BadTask())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="konnte nicht"):
        strict.cancel("timeout", strict=True)


def test_d07_cancel_event_runtime_error_is_not_silent():
    from backend.cancellation import CancelToken

    token = CancelToken("scope:event")

    class _Loop:
        def is_running(self):
            return True

        def call_soon_threadsafe(self, fn):
            raise RuntimeError("loop closed")

    token._loop = _Loop()  # type: ignore[assignment]
    token._set_event()
    assert token.cancellation_failed is True
    assert token.failed_cancels


def test_d07_tenant_db_consolidation_check_fail_closed():
    src = _src("backend/tenant_db_registry.py")
    assert '"[TenantDB] Konsolidierungscheck' in src
    block = src.split("resolved_name = db_name", 1)[1].split("db_path = tenant_context", 1)[0]
    assert "except Exception:\n            pass" not in block
    assert "continue" in block


def test_d07_durable_corrupt_checkpoint_is_blocked(tmp_path):
    from backend.durable_execution_kernel import (
        SUSPENDED,
        DurableExecutionKernel,
    )

    db = tmp_path / "durable.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE durable_executions (
        run_id TEXT PRIMARY KEY, state TEXT, fencing_token TEXT, claim_expires REAL,
        checkpoint_step INTEGER, state_json TEXT, payload_json TEXT, updated_at REAL
    )""")
    conn.execute("""CREATE TABLE durable_commands (
        run_id TEXT, seq INTEGER, command_type TEXT, payload_json TEXT,
        fencing_token TEXT, created_at REAL
    )""")
    conn.execute(
        "INSERT INTO durable_executions VALUES (?,?,?,?,?,?,?,?)",
        ("run-1", SUSPENDED, "", 0, 0, "{not json", "{}", 0),
    )
    conn.commit()
    conn.close()
    kernel = DurableExecutionKernel(db_path=str(db))
    res = kernel.resume_suspended("run-1")
    assert res["status"] == "resume_blocked"
    assert res["checkpoint_error"] == "corrupt_state_json"


# ---------------------------------------------------------------------------
# D14 — HITL-Override und Auto-Freigabe-Schwelle
# ---------------------------------------------------------------------------


def test_d14_kanban_unverified_override_bypass_removed(monkeypatch):
    from backend.kanban_verifier import resolve_card_hitl_decision

    monkeypatch.setenv("ARCHON_KANBAN_HITL_ALLOW_UNVERIFIED_OVERRIDE", "1")
    res = resolve_card_hitl_decision(
        "override", 1000, 5000, actor="bob", created_by="alice"
    )
    assert res["next_status"] == "blocked"
    assert res["verified"] is False
    block = _src("backend/kanban_verifier.py").split(
        "def resolve_card_hitl_decision", 1
    )[1].split("\ndef ", 1)[0]
    assert "os.environ.get" not in block  # kein Env-Fail-Open im Entscheider


def test_d14_auto_approval_threshold_requires_four_eyes(tmp_path):
    from backend.approval_policy_engine import ApprovalPolicyEngine

    engine = ApprovalPolicyEngine(db_path=str(tmp_path / "approval.db"))

    def _auto():
        return float(next(
            p["policy_value"] for p in engine.get_policies()
            if p["policy_key"] == "finance_auto_approval_max"
        ))

    assert _auto() == 50.0
    res = engine.update_policy("finance_auto_approval_max", "499.99", user_id="admin")
    assert res["status"] == "pending_four_eyes"
    assert _auto() == 50.0  # einzelner Admin ändert nichts direkt

    with pytest.raises(ValueError, match="Vier-Augen"):
        engine.approve_policy_change_proposal(res["proposal_id"], approver_id="admin")
    engine.approve_policy_change_proposal(res["proposal_id"], approver_id="bob")
    assert _auto() == 499.99

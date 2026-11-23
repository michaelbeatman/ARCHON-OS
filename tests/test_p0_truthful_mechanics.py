"""P0-Regressionstests: „Erfolg ohne Effekt" muss auffallen.

Jeder Test beschreibt eine Mechanik, die heute erfolgreich meldet, obwohl
im Produktivpfad keine Wirkung entsteht. Die Tests sind VOR den Fixes
geschrieben und muessen ohne Patch rot sein.

FdF: Kalender-Einladung, E-Mail-Freigabe, WAL-Flush, Boardroom-Runden-Cap.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _RecordingDraftEngine:
    """Imitiert die ECHTE create_draft-Signatur — `source=` muss TypeError werfen."""

    def __init__(self):
        self.calls = []

    def create_draft(
        self,
        subject,
        recipient,
        body_text,
        agent_id="default",
        agent_name="Hermes Orchestrator",
        sender="system@archon-os.internal",
        source_task_id=None,
        created_by="admin",
    ):
        self.calls.append({"recipient": recipient, "source_task_id": source_task_id})
        return {"draft_id": f"draft_{len(self.calls)}"}


# ---------------------------------------------------------------------------
# F2/F3 — Kalender-Einladungen: TypeError verschluckt + falscher Response-Key
# ---------------------------------------------------------------------------


def test_calendar_invite_reports_only_really_created_drafts(tmp_path, monkeypatch):
    from backend import email_draft_engine as ede
    from backend.operations_calendar import OperationsCalendarManager

    fake = _RecordingDraftEngine()
    monkeypatch.setattr(ede, "email_draft_engine", fake)

    cal = OperationsCalendarManager(data_dir=str(tmp_path))
    event = cal.create_event(
        {"title": "Review", "date": "2026-11-24", "attendees": "a@example.com"}
    )
    result = cal.send_invites(event["id"])

    assert fake.calls, "create_draft wurde nie erfolgreich aufgerufen (TypeError verschluckt?)"
    assert result["draft_ids"], "Entwurf wurde erzeugt, aber nicht an den Aufrufer gemeldet"


# ---------------------------------------------------------------------------
# F1 — E-Mail-Freigabe: Audit „SENT", aber kein SMTP-Aufruf
# ---------------------------------------------------------------------------


def test_approve_and_send_really_calls_smtp(tmp_path):
    from backend.email_draft_engine import EmailDraftEngine

    engine = EmailDraftEngine(db_path=str(tmp_path / "drafts.db"))
    draft = engine.create_draft(
        subject="Freigabe-Test", recipient="empfaenger@example.com", body_text="Hallo"
    )

    with mock.patch(
        "backend.email_service.send_email", return_value={"status": "sent"}
    ) as send:
        result = engine.approve_and_send(draft["draft_id"], approver_id="alice")

    send.assert_called_once(), "approve_and_send muss backend.email_service.send_email aufrufen"
    assert result.get("delivery_status") == "sent"


def test_approve_and_send_does_not_claim_sent_when_smtp_skipped(tmp_path):
    from backend.email_draft_engine import EmailDraftEngine

    engine = EmailDraftEngine(db_path=str(tmp_path / "drafts.db"))
    draft = engine.create_draft(
        subject="Skipped-Test", recipient="empfaenger@example.com", body_text="Hallo"
    )

    with mock.patch(
        "backend.email_service.send_email",
        return_value={"status": "skipped", "reason": "no_smtp_credentials"},
    ):
        result = engine.approve_and_send(draft["draft_id"], approver_id="alice")

    assert result.get("delivery_status") == "skipped"
    assert result.get("message") != "E-Mail freigegeben und versendet."


# ---------------------------------------------------------------------------
# K-1 — WAL-Flush meldet „success", obwohl alle Flushes fehlgeschlagen sind
# ---------------------------------------------------------------------------


def test_wal_flush_reports_error_when_every_flush_fails():
    import backend.graceful_shutdown_coordinator as gsync

    fake_mod = mock.MagicMock()
    fake_mod.async_write_batcher.flush.side_effect = RuntimeError("DB locked")

    coord = gsync.GracefulShutdownCoordinator()
    with mock.patch.dict(sys.modules, {"backend.async_write_batcher": fake_mod}):
        with mock.patch.object(coord, "_known_db_paths", return_value=[]):
            result = coord.flush_all_databases()

    assert result["status"] == "error", "Totalfehlschlag darf nicht 'success' melden"
    assert "async_write_batcher_ram_queue" not in result.get("flushed_databases", [])


# ---------------------------------------------------------------------------
# K-1 — Boardroom-Runden ohne Cap => unbegrenzte kostenpflichtige LLM-Calls
# ---------------------------------------------------------------------------


def test_boardroom_rounds_are_capped():
    from pydantic import ValidationError

    from archon.routers.boardroom import BoardroomRequest

    with pytest.raises(ValidationError):
        BoardroomRequest(task="Testfrage", rounds=999)

"""M112: Event-Ledger, Crash-Recovery, Merkle-Anker und Replay.

Alle Tests arbeiten auf ``tmp_path``-DBs; die HMAC-Keys werden lokal gesetzt.
Es werden keine Produktions-DBs, keine Router-Registrierung in main.py und
keine Auth-/RBAC-Guards veraendert.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.event_ledger import (
    GENESIS_HASH,
    AnchorError,
    AnchorStoreError,
    CallbackAnchorStore,
    EventLedger,
    FileAnchorStore,
    LedgerStateError,
    compute_merkle_root,
    start_anchor_worker,
    stop_anchor_worker,
)


@pytest.fixture
def ledger_db(tmp_path: Path) -> Path:
    return tmp_path / "ledger.db"


@pytest.fixture
def ledger(ledger_db: Path, monkeypatch: pytest.MonkeyPatch) -> EventLedger:
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m112-test-" + "c" * 64)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCHS", raising=False)
    monkeypatch.delenv("ARCHON_AUDIT_HMAC_EPOCH_FROM", raising=False)
    monkeypatch.delenv("ARCHON_EVENT_LEDGER_ANCHOR_PATH", raising=False)
    monkeypatch.delenv("ARCHON_EVENT_LEDGER_ANCHOR_WORM", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    return EventLedger(str(ledger_db), auto_recover=False)


class FailingAnchorStore:
    """Simuliert WORM-/Netzwerkausfall beim Anker-Schreiben."""

    name = "broken"
    mode = "offline"

    def write(
        self, merkle_root: str, first_event_id: int, last_event_id: int, event_count: int
    ) -> str:
        raise AnchorStoreError("WORM-Speicher nicht erreichbar")

    def read(self, merkle_root: str) -> str | None:
        return None


def test_empty_ledger_verifies(ledger: EventLedger) -> None:
    report = ledger.verify_ledger()
    assert report["valid"] is True
    assert report["total_events"] == 0
    assert report["issues"] == []
    assert ledger.status()["latest_hash"] == GENESIS_HASH
    assert ledger.status()["total_events"] == 0


def test_atomic_begin_commit_chain_and_append_only(
    ledger: EventLedger, ledger_db: Path
) -> None:
    begin = ledger.begin_transaction(
        event_type="invoice.create", actor="alice", payload={"amount": 100}
    )
    commit = ledger.commit_transaction(
        begin.transaction_id, actor="alice", payload={"invoice_id": "inv-1"}
    )
    assert begin.status == "pending"
    assert commit.status == "committed"
    assert commit.prev_hash == begin.current_hash
    assert begin.current_hash.startswith("hmac-sha256:")

    report = ledger.verify_ledger()
    assert report["valid"] is True
    assert report["total_events"] == 2
    assert report["total_transactions"] == 1
    assert report["issues"] == []

    # Kein zweiter Abschluss, kein Überschreiben bestehender Einträge.
    with pytest.raises(LedgerStateError):
        ledger.commit_transaction(begin.transaction_id, actor="alice")
    conn = sqlite3.connect(str(ledger_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ledger_events SET payload_json='{}' WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM ledger_events WHERE id=1")
    finally:
        conn.close()


def test_crash_recovery_aborts_pending(ledger: EventLedger, ledger_db: Path) -> None:
    # Crash nach dem Vor-Eintrag: nur BEGIN ist vorhanden.
    ledger.begin_transaction(event_type="order.reserve", actor="alice")
    assert ledger.status()["pending_events"] == 1

    assert ledger.recover_pending() == 1
    assert ledger.recover_pending() == 0  # idempotent
    report = ledger.verify_ledger()
    assert report["valid"] is True
    replay = ledger.replay(include_pending=True)
    assert replay["transactions"][0]["status"] == "aborted"
    assert replay["transactions"][0]["events"][-1]["phase"] == "abort"

    # Automatische Recovery beim Oeffnen einer neuen Instanz (Prozess-Neustart).
    second_db = ledger_db.parent / "crash.db"
    first = EventLedger(str(second_db), auto_recover=False)
    first.begin_transaction(event_type="payment.capture", actor="bob")
    second = EventLedger(str(second_db), auto_recover=True)
    assert second.status()["pending_events"] == 0
    assert second.verify_ledger()["valid"] is True
    assert second.replay(include_pending=True)["transactions"][0]["status"] == "aborted"


def test_manipulation_and_gap_detected(ledger: EventLedger, ledger_db: Path) -> None:
    begin = ledger.begin_transaction(event_type="invoice.create", actor="alice", payload={})
    ledger.commit_transaction(begin.transaction_id, actor="alice")

    conn = sqlite3.connect(str(ledger_db))
    try:
        # Trigger muessen fuer den Test entfernt werden; die Verification
        # erkennt sowohl die Inhaltsaenderung als auch den fehlenden Trigger.
        conn.execute("DROP TRIGGER ledger_events_no_update")
        conn.execute("UPDATE ledger_events SET payload_json='{\"amount\": 999}' WHERE id=2")
        conn.commit()
    finally:
        conn.close()
    report = ledger.verify_ledger()
    assert report["valid"] is False
    assert any(item["code"] == "manipulation" for item in report["issues"])

    gap_db = ledger_db.parent / "gap.db"
    gap = EventLedger(str(gap_db), auto_recover=False)
    ids = [
        gap.begin_transaction(event_type="a", actor="alice").transaction_id,
        gap.begin_transaction(event_type="b", actor="alice").transaction_id,
    ]
    gap.commit_transaction(ids[0], actor="alice")
    conn = sqlite3.connect(str(gap_db))
    try:
        conn.execute("DROP TRIGGER ledger_events_no_delete")
        conn.execute("DELETE FROM ledger_events WHERE id=2")
        conn.commit()
    finally:
        conn.close()
    gap_report = gap.verify_ledger()
    assert gap_report["valid"] is False
    assert any(item["code"] == "gap" for item in gap_report["issues"])


def test_anchor_failure_is_fail_closed_and_can_be_retried(
    ledger_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m112-test-" + "d" * 64)
    monkeypatch.setenv("ENVIRONMENT", "development")
    broken = EventLedger(
        str(ledger_db), auto_recover=False, anchor_store=FailingAnchorStore()
    )
    begin = broken.begin_transaction(event_type="transfer", actor="alice")
    broken.commit_transaction(begin.transaction_id, actor="alice")

    with pytest.raises(AnchorError):
        broken.anchor_batch()
    failed = broken.verify_ledger()
    assert failed["valid"] is False
    assert any(item["code"] == "anchor_failure" for item in failed["issues"])

    # Nachgeholter Anker mit funktionierendem Adapter hebt den Vorfall auf.
    working = FileAnchorStore(tmp_path / "anchors.jsonl", worm=True)
    anchor = broken.anchor_batch(store=working)
    assert anchor is not None
    assert anchor.merkle_root == compute_merkle_root([
        row["current_hash"] for row in _all_events(ledger_db)
    ])
    recovered = broken.verify_ledger(store=working)
    assert recovered["valid"] is True
    assert recovered["anchors_verified"] is True


def test_optional_callback_anchor_and_external_tampering(
    ledger_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "m112-test-" + "e" * 64)
    monkeypatch.setenv("ENVIRONMENT", "development")
    submitted: List[str] = []

    def submit(root: str) -> str:
        submitted.append(root)
        return "ts-" + root[:8]

    external = CallbackAnchorStore(submit)

    ledger = EventLedger(str(ledger_db), auto_recover=False, anchor_store=external)
    begin = ledger.begin_transaction(event_type="report.create", actor="alice")
    ledger.commit_transaction(begin.transaction_id, actor="alice")
    anchor = ledger.anchor_batch()
    assert anchor is not None
    assert anchor.store == "external"
    assert submitted == [anchor.merkle_root]
    assert ledger.verify_ledger()["valid"] is True

    # Datei-Anker: manipulierter Merkle-Root wird beim Verify erkannt.
    file_db = tmp_path / "file.db"
    store = FileAnchorStore(tmp_path / "anchors.jsonl")
    file_ledger = EventLedger(str(file_db), auto_recover=False, anchor_store=store)
    tx = file_ledger.begin_transaction(event_type="report.create", actor="alice")
    file_ledger.commit_transaction(tx.transaction_id, actor="alice")
    file_anchor = file_ledger.anchor_batch()
    assert file_anchor is not None
    assert file_ledger.verify_ledger()["valid"] is True
    anchor_file = tmp_path / "anchors.jsonl"
    anchor_file.write_text(
        anchor_file.read_text(encoding="utf-8").replace(
            file_anchor.merkle_root, "0" * 64
        ),
        encoding="utf-8",
    )
    tampered = file_ledger.verify_ledger()
    assert tampered["valid"] is False
    assert any(item["code"].startswith("anchor") for item in tampered["issues"])


def test_replay_order_and_secret_redaction(ledger: EventLedger) -> None:
    a = ledger.begin_transaction(
        event_type="a.begin", actor="alice", payload={"api_key": "supersecret"}
    )
    b = ledger.begin_transaction(event_type="b.begin", actor="bob")
    ledger.commit_transaction(b.transaction_id, actor="bob")
    ledger.commit_transaction(a.transaction_id, actor="alice")
    c = ledger.begin_transaction(event_type="c.begin", actor="carol")
    ledger.abort_transaction(c.transaction_id, actor="carol")
    d = ledger.begin_transaction(event_type="d.begin", actor="dave")  # offener Crash-Fall

    result = ledger.replay(include_pending=True)
    assert result["status"] == "ok"
    assert result["valid"] is True
    order = [item["transaction_id"] for item in result["transactions"]]
    assert order == [b.transaction_id, a.transaction_id, c.transaction_id, d.transaction_id]
    assert result["transactions"][0]["status"] == "committed"
    assert result["transactions"][2]["status"] == "aborted"
    assert result["transactions"][3]["status"] == "pending"
    assert result["transactions"][0]["event_count"] == 2

    serialized = json.dumps(result)
    assert "supersecret" not in serialized
    assert "[REDACTED]" in serialized

    pending_omitted = ledger.replay()
    assert len(pending_omitted["transactions"]) == 3


def test_router_read_endpoints_rbac_200_and_403(
    ledger: EventLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    import archon.routers._rbac as rbac
    import archon.routers.event_ledger as router_module

    monkeypatch.setattr(router_module, "_configured_ledger", ledger)
    monkeypatch.setattr(rbac, "_checker", lambda request: None)
    monkeypatch.setattr(rbac, "require_session_actor", lambda request: "test-actor")

    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)

    paths = (
        "/api/event-ledger/status",
        "/api/event-ledger/verify",
        "/api/event-ledger/replay",
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json()["status"] == "ok"
    replay = client.get("/api/event-ledger/replay", params={"from_block": 1, "limit": 5})
    assert replay.status_code == 200
    assert replay.json()["replay"]["replayed_transactions"] == 0

    def deny(_request: Any) -> None:
        raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(rbac, "require_admin_or_503", deny)
    for path in paths:
        assert client.get(path).status_code == 403


def _all_events(db_path: Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [
            {"id": int(row["id"]), "current_hash": str(row["current_hash"])}
            for row in conn.execute("SELECT id, current_hash FROM ledger_events ORDER BY id ASC")
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Periodischer Anker (Integration in den Lifespan)
# ---------------------------------------------------------------------------


def test_periodic_anchor_worker_starts_and_stops_cleanly() -> None:
    stop_anchor_worker()
    stopper = start_anchor_worker(interval_sec=60.0)
    try:
        import backend.event_ledger as el

        thread = el._ANCHOR_WORKER.get("thread")
        assert thread is not None and thread.is_alive()
        # Kein zweiter Worker pro Prozess.
        assert start_anchor_worker(interval_sec=60.0) is stopper
    finally:
        stopper()
    import backend.event_ledger as el

    thread = el._ANCHOR_WORKER.get("thread")
    assert thread is None or not thread.is_alive()

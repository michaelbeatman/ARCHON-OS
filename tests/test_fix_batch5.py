import os
import json
import sqlite3
import asyncio
import pytest
from unittest.mock import MagicMock, patch


def test_r06_four_eyes_rejects_same_approver_and_rejected_status(tmp_path):
    """R-06: Vier-Augen-Prinzip muss identischen Erst- und Zweitgenehmiger abweisen und Status pruefen."""
    import backend.approval_policy_engine as ape_mod

    db_path = tmp_path / "approval_test.db"
    engine = ape_mod.ApprovalPolicyEngine(db_path=str(db_path))

    # Erstelle Anfrage mit Vier-Augen-Prinzip (amount 10000 >= four_eyes_min 500)
    res_enq = engine.evaluate_and_enqueue("finance", "Zahlung 10.000 EUR", amount=10000.0)
    req_id = res_enq["request_id"]

    # 1. Erste Genehmigung durch admin
    res1 = engine.approve_request(req_id, approver_id="admin")
    assert res1["status"] == "first_approved"

    # 2. Zweite Genehmigung durch DENSELBEN admin: MUSS ABGEWIESEN WERDEN!
    with pytest.raises(ValueError, match="Vier-Augen-Prinzip"):
        engine.approve_request(req_id, approver_id="admin")

    # 3. Status Guard: Abgelehnte Anfrage darf nicht genehmigt werden
    res_enq2 = engine.evaluate_and_enqueue("finance", "Zahlung 600 EUR", amount=600.0)
    req2_id = res_enq2["request_id"]
    engine.reject_request(req2_id, rejected_by="admin", reason="Zu teuer")
    with pytest.raises(ValueError, match="aktueller Status: rejected"):
        engine.approve_request(req2_id, approver_id="admin")


def test_r07_gdpr_no_receipt_on_store_failure(tmp_path):
    """R-07: DSGVO Art. 17 darf keine Quittung ausstellen, wenn ein Store fehlschlaegt."""
    from backend.gdpr_compliance_engine import GDPRComplianceEngine

    # Defekte Kanban-DB (Tabelle ohne 'body' Spalte)
    kanban_path = tmp_path / "broken_kanban.db"
    conn = sqlite3.connect(str(kanban_path))
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()

    engine = GDPRComplianceEngine()
    engine.kanban_db = str(kanban_path)
    engine.state_db = str(tmp_path / "nonexistent.db")
    engine.memory_db = str(tmp_path / "nonexistent_mem.db")

    # Ausfuehrung muss fehlschlagen und darf keine Quittung ausstellen
    with pytest.raises(RuntimeError):
        res = engine.erase_subject_data("Max Mustermann", dry_run=False)
        assert res.get("receipt") is None


def test_r10_save_json_reraises_on_write_error(monkeypatch):
    """R-10: _save_json darf Schreibfehler nicht verschlucken."""
    import archon.core.runtime as rt

    def mock_broken_write(path, data):
        raise OSError("Disk full or permission denied")

    monkeypatch.setattr(rt, "atomic_write_json", mock_broken_write)

    with pytest.raises(OSError, match="Disk full or permission denied"):
        rt._save_json("/invalid/path.json", {"test": 1})


@pytest.mark.asyncio
async def test_n01_shutdown_drain_does_not_block_event_loop():
    """N-01: Draining darf den Event-Loop nicht blockieren und muss asynchron sein."""
    from backend.graceful_shutdown_coordinator import GracefulShutdownCoordinator
    import main as main_mod

    coordinator = GracefulShutdownCoordinator()
    coordinator.register_task("task-1", "Hintergrund-Job", "Worker")

    # Paralleler Task auf dem Event Loop
    loop_progress = []
    async def parallel_task():
        for i in range(5):
            await asyncio.sleep(0.05)
            loop_progress.append(i)

    async def unregister_after_delay():
        await asyncio.sleep(0.15)
        coordinator.unregister_task("task-1")

    # Starte Draining und parallelen Task
    p_task = asyncio.create_task(parallel_task())
    u_task = asyncio.create_task(unregister_after_delay())

    res = await coordinator.drain_active_tasks(timeout_seconds=0.5)
    await p_task
    await u_task

    assert res["remaining_for_checkpoint"] == 0
    # Wenn die Loop nicht blockiert war, konnte parallel_task voranschreiten
    assert len(loop_progress) > 0, "Event Loop war blockiert waehrend Draining!"
    # on_shutdown_graceful in main.py muss eine Coroutine (async def) sein
    assert asyncio.iscoroutinefunction(main_mod.on_shutdown_graceful), "on_shutdown_graceful muss async def sein!"


def test_n02_write_batcher_restores_buffer_on_error(tmp_path, monkeypatch):
    """N-02: Bei SQLite-Schreibfehlern darf der Batcher die gepufferten Events nicht verlieren."""
    import backend.async_write_batcher as awb_mod

    db_path = tmp_path / "batcher_test.db"
    monkeypatch.setattr(awb_mod, "DB_PATH", str(db_path))

    batcher = awb_mod.AsyncWriteBatcher()
    # Mock settings to disable immediate auto-flush
    monkeypatch.setattr(awb_mod, "_get_cfg", lambda: {"enabled": True, "batch_size": 100, "flush_interval_seconds": 60, "max_queue_size": 1000})

    batcher.enqueue("test_event_1", "module_a", {"foo": "bar"})
    batcher.enqueue("test_event_2", "module_b", {"num": 42})
    assert len(batcher._buffer) == 2

    # Provoziere Schreibfehler (z.B. falsche Tabellenstruktur oder gesperrte DB)
    monkeypatch.setattr(sqlite3, "connect", MagicMock(side_effect=sqlite3.OperationalError("disk I/O error")))

    with pytest.raises(sqlite3.OperationalError):
        batcher.flush()

    # Nach dem Fehler muessen die 2 Events weiterhin im Puffer vorhanden sein!
    assert len(batcher._buffer) == 2, f"Buffer ging verloren! Buffer-Size nach Fehler: {len(batcher._buffer)}"

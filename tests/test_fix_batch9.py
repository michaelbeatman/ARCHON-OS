import os
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_m13_core_dispatcher_uses_concurrency_throttle(monkeypatch):
    """M-13: core_dispatcher muss concurrency_throttle.acquire_slot/release_slot aufrufen."""
    import core_dispatcher
    from backend.concurrency_throttle import concurrency_throttle

    acquire_mock = AsyncMock(return_value=True)
    release_mock = AsyncMock()

    monkeypatch.setattr(concurrency_throttle, "acquire_slot", acquire_mock)
    monkeypatch.setattr(concurrency_throttle, "release_slot", release_mock)
    monkeypatch.setattr(core_dispatcher, "_dispatch_to_omniroute_or_container_exec", AsyncMock(return_value={"status": "success", "content": "Done"}))

    await core_dispatcher.dispatch_to_omniroute_or_container(
        agent_id="test-agent",
        agent_name="Test",
        prompt="Hello world",
        task_id="task-m13"
    )

    assert acquire_mock.await_count >= 1, "M-13 BUG: concurrency_throttle.acquire_slot wurde nicht aufgerufen!"
    assert release_mock.await_count >= 1, "M-13 BUG: concurrency_throttle.release_slot wurde nicht aufgerufen!"


@pytest.mark.asyncio
async def test_m14_execute_kanban_task_registers_with_shutdown_coordinator(tmp_path, monkeypatch):
    """M-14: _execute_kanban_task_async muss den Task bei graceful_shutdown_coordinator registrieren."""
    import backend.operations_api as ops_mod
    from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator

    db_path = tmp_path / "kanban_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            assignee TEXT,
            status TEXT,
            priority INTEGER,
            model_override TEXT,
            provider_override TEXT,
            task_type TEXT,
            block_kind TEXT,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            kind TEXT,
            payload TEXT,
            created_at TEXT
        )
    """)
    conn.execute("INSERT INTO tasks (id, title, assignee, status) VALUES ('task-m14', 'Long Running Job', 'coder', 'in_progress')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ops_mod, "KANBAN_DB_PATH", str(db_path))

    reg_mock = MagicMock()
    unreg_mock = MagicMock()
    monkeypatch.setattr(graceful_shutdown_coordinator, "register_task", reg_mock)
    monkeypatch.setattr(graceful_shutdown_coordinator, "unregister_task", unreg_mock)

    # Mock autonomy & dispatch
    monkeypatch.setattr("backend.model_routing.autonomy_level", lambda domain: "autonomous")
    import core_dispatcher
    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", AsyncMock(return_value={"status": "success"}))

    await ops_mod._execute_kanban_task_async("task-m14")

    assert reg_mock.call_count >= 1, "M-14 BUG: graceful_shutdown_coordinator.register_task wurde nicht aufgerufen!"
    assert unreg_mock.call_count >= 1, "M-14 BUG: graceful_shutdown_coordinator.unregister_task wurde nicht aufgerufen!"


def test_m15_dead_letter_queue_total_count_and_default_simulation(tmp_path, monkeypatch):
    """M-15: list_dlq muss ungedeckelte total-Zahl liefern und replay_job darf Erfolg nicht standardmaessig simulieren."""
    import backend.dead_letter_queue as dlq_mod
    from backend.dead_letter_queue import DeadLetterQueueManager

    db_path = tmp_path / "dlq_test.db"
    monkeypatch.setattr(dlq_mod, "DB_PATH", str(db_path))
    dlq_mod._init_db()

    mgr = DeadLetterQueueManager()

    # Fuege 60 Jobs ein
    for i in range(60):
        mgr.enqueue_failed_job(
            job_type="test",
            source_module="coder",
            payload={"i": i},
            error_message="Test Error"
        )

    listing = mgr.list_dlq()
    assert len(listing["items"]) == 50
    assert listing["total"] == 60, f"M-15 BUG: total wurde als {listing['total']} gemeldet statt 60!"

    # Pruefe replay_job Default
    first_id = listing["items"][0]["dlq_id"]
    res = mgr.replay_job(first_id)
    assert res["status"] != "replayed_success", "M-15 BUG: replay_job(first_id) simuliert standardmaessig Erfolg!"
    assert res["status"] in ("queued", "exhausted")

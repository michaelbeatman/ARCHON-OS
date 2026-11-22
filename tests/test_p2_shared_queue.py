"""Regressionstests: Shared Task Queue mit Idempotenz, CAS-Lease und Work-Stealing."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _manager(tmp_path, monkeypatch):
    import backend.dead_letter_queue as dlq

    monkeypatch.setattr(dlq, "DB_PATH", str(tmp_path / "queue.db"))
    return dlq.DeadLetterQueueManager()


def test_p2_queue_is_idempotent(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    first = mgr.enqueue_task("test", "pytest", {"a": 1}, idempotency_key="idem-1")
    second = mgr.enqueue_task("test", "pytest", {"a": 1}, idempotency_key="idem-1")
    assert first["queued"] is True
    assert second["queued"] is False and second["duplicate"] is True
    assert second["dlq_id"] == first["dlq_id"]


def test_p2_queue_claim_is_atomic_and_priority_ordered(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    mgr.enqueue_task("low", "pytest", {"v": "low"}, priority=1)
    high = mgr.enqueue_task("high", "pytest", {"v": "high"}, priority=9)

    item = mgr.claim_next("worker-a", job_types=["high", "low"])
    assert item is not None and item["dlq_id"] == high["dlq_id"]
    assert item["payload"] == {"v": "high"}
    assert mgr.claim_next("worker-b", job_types=["high"]) is None


def test_p2_queue_work_stealing_after_expired_lease(tmp_path, monkeypatch):
    import backend.dead_letter_queue as dlq

    mgr = _manager(tmp_path, monkeypatch)
    job = mgr.enqueue_task("steal", "pytest", {"v": 1})
    assert mgr.claim_next("worker-a", lease_seconds=10)["dlq_id"] == job["dlq_id"]
    assert mgr.claim_next("worker-b") is None

    # Lease abgelaufen markieren -> anderer Worker darf übernehmen.
    with sqlite3.connect(dlq.DB_PATH, timeout=15.0) as conn:
        conn.execute("UPDATE dead_letter_queue SET claim_expires = ? WHERE dlq_id = ?",
                     (time.time() - 1, job["dlq_id"]))
        conn.commit()
    stolen = mgr.claim_next("worker-b")
    assert stolen is not None and stolen["dlq_id"] == job["dlq_id"]


def test_p2_queue_attempts_end_in_dead_letter(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    job = mgr.enqueue_task("failing", "pytest", {}, max_retries=2)
    mgr.claim_next("worker-a")
    assert mgr.fail(job["dlq_id"], "boom")["status"] == "queued"
    mgr.claim_next("worker-a")
    assert mgr.fail(job["dlq_id"], "boom")["status"] == "dead"
    assert mgr.list_dlq(status_filter="dead")["total"] == 1


def test_p2_delegation_wires_failures_into_shared_queue():
    src = (REPO_ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert "def _enqueue_delegation_failure(" in src
    assert "_enqueue_delegation_failure(task_id, prof_id, status, result)" in src
    exec_src = (REPO_ROOT / "archon" / "routers" / "execution.py").read_text(encoding="utf-8")
    assert '/api/execution/queue/claim' in exec_src
    assert "claim_next(" in exec_src

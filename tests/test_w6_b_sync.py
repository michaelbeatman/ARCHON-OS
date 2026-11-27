# -*- coding: utf-8 -*-
"""W6-B / D08-M1..M5 — sync I/O in async-Pfaden hinter asyncio.to_thread.

Rein implementierende Regressionstests (Produzent → Konsument → Effekt →
Verifikation). Jeder Test misst die Event-Loop-Lebendigkeit parallel zu einem
künstlich verlangsamten SQLite-/Datei-Zugriff und prüft zusätzlich den
fachlichen Effekt (Artefakt, Event, Log, Status). Keine PostgreSQL-Migration,
kein Coroutine-/Event-Replay, keine echten Secrets.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, cast

# Muss VOR dem Import von App-Modulen gesetzt werden (tests/conftest.py).
os.environ.setdefault("ARCHON_TEST_DB_ISOLATION", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Neutraler Placeholder, kein schluesselartiger String.
TEST_KEY = "W6B_TEST_" + "a" * 24


class _Cursor:
    """Minimaler sqlite3-Cursor-Ersatz fuer die verlangsamten Connection-Stubs."""

    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many or []


def _latency_probe():
    """Liefert (Coroutine, Dict) — misst, wann der Event-Loop wieder dran war."""
    result: dict[str, float] = {}

    async def _heartbeat():
        start = time.perf_counter()
        await asyncio.sleep(0.02)
        result["seconds"] = time.perf_counter() - start

    return _heartbeat(), result


# ---------------------------------------------------------------------------
# D08-M1 — Fan-in: DB-Reads + Vault-Write in EINEM to_thread-Block
# ---------------------------------------------------------------------------


def test_m1_fan_in_sync_block_runs_off_the_event_loop(tmp_path, monkeypatch):
    import backend.operations_api as ops
    from archon.core import delegation as d

    class SlowConn:
        def execute(self, sql, params=()):
            if "COUNT(*)" in sql:
                time.sleep(0.25)  # simuliert SQLite-Lock-Contention
                return _Cursor(one=(0,))
            if "SELECT id, title" in sql:
                return _Cursor(many=[(1, "Teilauftrag", "coder", "Ergebnis", "done")])
            return _Cursor()

        def close(self):
            pass

    monkeypatch.setattr(ops, "_get_kanban_connection", lambda: SlowConn())
    monkeypatch.setattr(
        d, "_project_approval_evidence",
        lambda _pid: {"approval_id": "appr-w6b", "approver": "Test Approver"},
    )
    monkeypatch.setattr(d, "_save_message_to_db", lambda *_a, **_kw: None)
    events = []
    monkeypatch.setattr(d, "broadcast_event", lambda typ, data: events.append((typ, data)))
    monkeypatch.setattr(d, "PROJEKTE_DIR", str(tmp_path))

    async def _run():
        heartbeat, latency = _latency_probe()
        await asyncio.gather(
            d._trigger_autonomous_orchestrator_followup(
                "delegator", "sess-w6b", "task-w6b", "done",
                "Ergebnis", "Abschluss", "projekt-w6b",
            ),
            heartbeat,
        )
        assert latency["seconds"] < 0.15, (
            f"Fan-in blockiert den Event-Loop: {latency['seconds']:.3f}s"
        )

    asyncio.run(_run())

    reports = list(tmp_path.rglob("*_Abschlussbericht.html"))
    assert len(reports) == 1, "Synthese-Artefakt muss im Vault geschrieben werden"
    assert "Teilauftrag" in reports[0].read_text(encoding="utf-8")
    assert any(typ == "chat_message_received" for typ, _ in events)
    assert events[-1][1]["project_completed"] == "projekt-w6b"


# ---------------------------------------------------------------------------
# D08-M2 — Watcher-Cancel: idempotentes cancelled-Event, close() in finally
# ---------------------------------------------------------------------------


def test_m2_cancelled_event_is_idempotent_under_parallel_writers(tmp_path, monkeypatch):
    import backend.operations_api as ops
    from archon.core import delegation as d

    db = tmp_path / "kanban.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE task_events (task_id TEXT, kind TEXT, payload TEXT, created_at REAL)"
    )
    conn.commit()
    conn.close()

    opened = []

    def _conn():
        c = sqlite3.connect(db, timeout=5.0)
        opened.append(c)
        return c

    monkeypatch.setattr(ops, "_get_kanban_connection", _conn)

    async def _run():
        heartbeat, latency = _latency_probe()
        await asyncio.gather(
            asyncio.to_thread(
                d._write_cancelled_event_sync, "task-w6b", "abgebrochen", "cancelled"
            ),
            asyncio.to_thread(
                d._write_cancelled_event_sync, "task-w6b", "abgebrochen", "cancelled"
            ),
            heartbeat,
        )
        assert latency["seconds"] < 0.15

    asyncio.run(_run())

    rows = sqlite3.connect(db).execute(
        "SELECT kind, payload FROM task_events WHERE task_id = ?", ("task-w6b",)
    ).fetchall()
    assert len(rows) == 1, "zwei parallele Watcher duerfen nur EIN Event erzeugen"
    payload = json.loads(rows[0][1])
    assert payload["via"] == "delegation_watcher"
    assert payload["mc_status"] == "cancelled"
    # Jede Connection wurde geschlossen (sonst waere das Objekt noch nutzbar).
    for c in opened:
        with __import__("pytest").raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


def test_m2_cancelled_event_closes_connection_on_db_error(monkeypatch):
    import pytest

    import backend.operations_api as ops
    from archon.core import delegation as d

    class BoomConn:
        closed = False

        def execute(self, *_a, **_kw):
            raise RuntimeError("db-locked")

        def close(self):
            self.closed = True

    boom = BoomConn()
    monkeypatch.setattr(ops, "_get_kanban_connection", lambda: boom)

    with pytest.raises(RuntimeError, match="db-locked"):
        d._write_cancelled_event_sync("task-w6b", "", "cancelled")
    assert boom.closed is True


# ---------------------------------------------------------------------------
# D08-M3 — DLQ-Replay: Task-Status aus dem Worker-Thread lesen
# ---------------------------------------------------------------------------


def test_m3_dlq_replay_reads_status_off_loop_and_stays_idempotent(monkeypatch):
    import backend.operations_api as ops
    from archon.core import delegation as dlg
    from backend import workflow_scheduler as ws

    state = {"status": "done"}

    class SlowConn:
        def execute(self, sql, params=()):
            time.sleep(0.25)
            return _Cursor(one=(state["status"],) if state["status"] else None)

        def close(self):
            pass

    monkeypatch.setattr(ops, "_get_kanban_connection", lambda: SlowConn())
    dispatched = []

    async def _fake_execute(task_id):
        dispatched.append(task_id)

    async def _fake_resume():
        return 0

    monkeypatch.setattr(ops, "_execute_kanban_task_async", _fake_execute)
    monkeypatch.setattr(dlg, "resume_pending_delegation_watchers", _fake_resume)

    async def _run(expect_dispatch: bool):
        heartbeat, latency = _latency_probe()
        out = await asyncio.gather(
            ws._handle_delegation_result({"task_id": "task-w6b", "agent_id": "coder"}, {}),
            heartbeat,
        )
        assert latency["seconds"] < 0.15, (
            f"DLQ-Replay blockiert den Event-Loop: {latency['seconds']:.3f}s"
        )
        return out[0]

    # Terminale Status duerfen nicht erneut dispatched werden.
    result = asyncio.run(_run(expect_dispatch=False))
    assert result == {
        "redispatched": False, "reason": "task_status=done", "task_id": "task-w6b"
    }
    assert dispatched == []

    # Nicht-terminaler Status wird wiederholt.
    state["status"] = "failed"
    result = asyncio.run(_run(expect_dispatch=True))
    assert result["redispatched"] is True
    assert dispatched == ["task-w6b"]

    # Fehlender Task bleibt ein harter Fehler (kein stilles Re-Dispatch).
    state["status"] = ""
    import pytest
    with pytest.raises(KeyError, match="nicht gefunden"):
        asyncio.run(
            ws._handle_delegation_result({"task_id": "task-w6b"}, {})
        )
    assert dispatched == ["task-w6b"]


# ---------------------------------------------------------------------------
# D08-M4 — Self-Healing: Datei-Patch + Log-Insert im Worker-Thread
# ---------------------------------------------------------------------------


def test_m4_self_healing_patch_and_log_run_off_the_event_loop(tmp_path, monkeypatch):
    import backend.autonomy_settings as settings
    import backend.task_self_healer as th
    import core_dispatcher

    target = tmp_path / "module.py"
    target.write_text("original = True\n", encoding="utf-8")
    monkeypatch.setattr(th, "WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings, "get_module_config",
        lambda _name: {"enabled": True, "max_attempts": 1, "auto_git_rollback": False},
    )

    async def _fake_dispatch(**_kwargs):
        return {"status": "success", "content": "```python\nfixed = True\n```"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch)

    db = tmp_path / "healing.db"
    healer = th.TaskSelfHealer(db_path=str(db))
    real_get_conn = healer._get_conn

    class SlowConn:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            self._conn.__enter__()
            return self

        def __exit__(self, *_a):
            return self._conn.__exit__(*_a)

        def execute(self, *_a, **_kw):
            time.sleep(0.25)
            return self._conn.execute(*_a, **_kw)

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    monkeypatch.setattr(healer, "_get_conn", lambda: SlowConn(real_get_conn()))

    async def _run():
        heartbeat, latency = _latency_probe()
        out = await asyncio.gather(
            healer.attempt_self_healing(
                task_id="t-w6b", task_title="Fix", failed_code="x = (",
                error_output="SyntaxError", affected_file="module.py",
                apply_patch=True, attempt=1,
            ),
            heartbeat,
        )
        assert latency["seconds"] < 0.15, (
            f"Self-Healing blockiert den Event-Loop: {latency['seconds']:.3f}s"
        )
        return out[0]

    result = asyncio.run(_run())
    assert result["status"] == "repaired"
    assert result["patch_applied"] is True
    assert target.read_text(encoding="utf-8") == "fixed = True\n"
    backup = tmp_path / "module.py.archon_heal_backup"
    assert backup.read_text(encoding="utf-8") == "original = True\n"

    logs = sqlite3.connect(db).execute(
        "SELECT task_id, repaired_successfully FROM task_healing_logs"
    ).fetchall()
    assert logs == [("t-w6b", 1)]


# ---------------------------------------------------------------------------
# D08-M5 — Campaign-Failure: Status in to_thread, Fehler nicht verschluckt
# ---------------------------------------------------------------------------


def test_m5_campaign_failure_marks_status_off_loop_and_logs_error(
    tmp_path, monkeypatch, caplog
):
    import archon.core.task_registry as tr
    import backend.content_machine as bcm
    from archon.routers import content_machine as cm

    db = tmp_path / "content.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE content_campaigns (id TEXT, status TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO content_campaigns VALUES (?, ?, ?)", ("camp-w6b", "running", "")
    )
    conn.commit()
    conn.close()

    def _conn():
        class Conn:
            def __enter__(self):
                self._c = sqlite3.connect(db, timeout=5.0)
                return self

            def __exit__(self, *_a):
                self._c.close()

            def execute(self, sql, params=()):
                time.sleep(0.25)
                return self._c.execute(sql, params)

            def commit(self):
                self._c.commit()

        return Conn()

    async def _failing_pipeline(**_kwargs):
        raise RuntimeError("pipeline-booma")

    spawned: dict[str, Any] = {}

    def _spawn(coro, *, name=None):
        spawned["coro"] = coro
        return None

    monkeypatch.setattr(bcm, "_conn", _conn)
    monkeypatch.setattr(bcm, "run_content_campaign_pipeline", _failing_pipeline)
    monkeypatch.setattr(cm, "require_admin_or_503", lambda _request: None)
    monkeypatch.setattr(tr, "spawn", _spawn)

    with caplog.at_level(logging.ERROR, logger="archon.routers.content_machine"):

        async def _run():
            heartbeat, latency = _latency_probe()
            resp = await cm.api_cm_campaign_generate(
                cast(Any, object()), "camp-w6b",
                cm.CampaignGenerateRequest(background=True, dry_run=False),
            )
            await asyncio.gather(cast(Any, spawned["coro"]), heartbeat)
            assert latency["seconds"] < 0.15, (
                f"Campaign-Failure blockiert den Event-Loop: {latency['seconds']:.3f}s"
            )
            return resp

        resp = asyncio.run(_run())

    assert resp["status"] == "accepted"
    assert any(
        rec.levelno == logging.ERROR and "pipeline-booma" in rec.getMessage()
        for rec in caplog.records
    ), "der Fehler darf nicht mehr mit nacktem except: pass verschluckt werden"
    status = sqlite3.connect(db).execute(
        "SELECT status FROM content_campaigns WHERE id = ?", ("camp-w6b",)
    ).fetchone()[0]
    assert status == "failed"


# ---------------------------------------------------------------------------
# Produktivpfad-Guard: alle fuenf Sites bleiben hinter der Thread-Grenze
# ---------------------------------------------------------------------------


def test_w6b_all_sync_sites_keep_their_thread_boundary():
    from archon.core import delegation as d
    from archon.routers import content_machine as cm
    from backend import task_self_healer as th
    from backend import workflow_scheduler as ws

    checks = [
        (d._trigger_autonomous_orchestrator_followup, r"asyncio\.to_thread\(\s*_fan_in_context_sync"),
        (d._watch_delegated_task, r"asyncio\.to_thread\(\s*_write_cancelled_event_sync"),
        (ws._handle_delegation_result, r"asyncio\.to_thread\(\s*_load_task_status_sync"),
        (th.TaskSelfHealer.attempt_self_healing, r"asyncio\.to_thread\(\s*_apply_patch_sync"),
        (th.TaskSelfHealer.attempt_self_healing, r"asyncio\.to_thread\(\s*_log_healing_sync"),
        (cm.api_cm_campaign_generate, r"asyncio\.to_thread\(\s*_mark_campaign_failed_sync"),
    ]
    for func, pattern in checks:
        source = inspect.getsource(cast(Any, func))
        assert re.search(pattern, source), f"{func.__name__}: {pattern} fehlt"


def test_w6b_no_secret_like_placeholder_in_this_module():
    """Der Pre-Commit-Hook blockt `sk-<Zeichen>` — hier nur neutrale Platzhalter."""
    source = Path(__file__).read_text(encoding="utf-8")
    # Gleiche Regex wie scripts/audit_secrets.py / Pre-Commit-Hook.
    assert re.search(r"\bsk-[a-zA-Z0-9_\-]{20,}\b", source) is None
    assert TEST_KEY.startswith("W6B_TEST_")

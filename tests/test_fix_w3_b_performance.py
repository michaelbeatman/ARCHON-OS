# -*- coding: utf-8 -*-
"""W3-B (F035 / Recovery + Performance) — Regressionstests.

WICHTIG: Diese Datei schreibt nie in die produktiven DBs unter ``./data``.
Vor allen Imports wird ``ARCHON_DATA_DIR`` (falls nicht bereits durch
``tests/conftest.py`` gesetzt) auf ein temporaeres Verzeichnis gezeigt.
"""
import os
import tempfile

if not os.environ.get("ARCHON_DATA_DIR"):
    os.environ["ARCHON_DATA_DIR"] = tempfile.mkdtemp(prefix="archon_w3b_testdata_")

import asyncio
import functools
import inspect
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _src(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _async_test(fn):
    """Coroutine-Test auch ohne pytest-asyncio ausfuehrbar machen.

    ``functools.wraps`` bewahrt die Signatur, damit pytest seine Fixtures
    (monkeypatch/tmp_path) weiterhin korrekt injiziert.
    """
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return _wrapper


# ---------------------------------------------------------------------------
# H-08-1 — Dispatch-Kontext in EINEM Worker-Thread
# ---------------------------------------------------------------------------

def test_dispatch_context_loaders_are_bundled_in_one_thread_helper():
    import core_dispatcher as cd

    impl = inspect.getsource(cd._dispatch_to_omniroute_or_container_impl)
    helper = inspect.getsource(cd._build_dispatch_context_sync)

    assert "await asyncio.to_thread(" in impl
    assert "_build_dispatch_context_sync" in impl
    # Die vier Quellen duerfen nicht mehr direkt im async Impl stehen.
    for forbidden in (
        "prefetch_for_task(", "get_effective_prompt(",
        "compile_system_prompt_injection(", "select_best_model()",
    ):
        assert forbidden not in impl, forbidden
    for expected in (
        "prefetch_for_task(", "get_effective_prompt(",
        "compile_system_prompt_injection(", "select_best_model()",
    ):
        assert expected in helper, expected


@_async_test
async def test_context_loaders_run_off_the_event_loop(monkeypatch):
    import backend.bandit_model_router as bmr
    import backend.core_memory_manager as cmm
    import backend.prompt_registry as pr
    import backend.speculative_prefetcher as sp
    import core_dispatcher as cd

    loop_thread = threading.get_ident()
    seen = []

    class _Prefetcher:
        def prefetch_for_task(self, prompt, agent_id=None):
            seen.append(("prefetch", threading.get_ident()))
            return {"cached_items": {"crm_contact": {"first_name": "A", "last_name": "B"}}}

    class _Registry:
        def get_effective_prompt(self, agent_id, task_id):
            seen.append(("registry", threading.get_ident()))
            return {"prompt": "BASIS", "version_num": 3, "is_canary": False}

    class _Memory:
        def compile_system_prompt_injection(self, agent_id):
            seen.append(("memory", threading.get_ident()))
            return "<core-memory/>"

    class _Bandit:
        def select_best_model(self):
            seen.append(("bandit", threading.get_ident()))
            return {"enabled": True, "selected_model": "chosen/model"}

    monkeypatch.setattr(sp, "get_speculative_prefetcher", lambda: _Prefetcher())
    monkeypatch.setattr(pr, "prompt_registry", _Registry())
    monkeypatch.setattr(cmm, "core_memory_manager", _Memory())
    monkeypatch.setattr(bmr, "bandit_model_router", _Bandit())

    ctx = await asyncio.to_thread(
        cd._build_dispatch_context_sync, "mail me", "agent", "ticket-1", "SYS", "auto/bandit"
    )

    assert ctx["model"] == "chosen/model"
    assert "BASIS" in ctx["system_prompt"]
    assert "<core-memory/>" in ctx["core_mem_addon"]
    assert "CRM-Kontakt" in ctx["prefetch_addon"]
    assert ctx["prompt_version_info"]["resolved"] is True
    assert len(seen) == 4
    assert all(tid != loop_thread for _, tid in seen)


# ---------------------------------------------------------------------------
# H-13-1 — Trajectory-Hop-Invariante im Chokepoint
# ---------------------------------------------------------------------------

def test_trajectory_gate_is_hard_blocked_before_provider_call():
    import core_dispatcher as cd

    impl = inspect.getsource(cd.dispatch_to_omniroute_or_container)
    assert "normalize_trajectory_id" not in impl  # liegt im Sync-Helper
    assert "TRAJECTORY_CAP_BLOCKED" in impl
    assert "reserve_hop" in inspect.getsource(cd._reserve_trajectory_budget_sync)
    assert "reserve_tokens" in inspect.getsource(cd._reserve_trajectory_budget_sync)
    assert "task_id=task_id" in inspect.getsource(cd.execute_with_self_correction)
    assert "retry:" in inspect.getsource(cd.execute_with_self_correction)


@_async_test
async def test_trajectory_reserve_helper_blocks_on_denied_hop(monkeypatch):
    import core_dispatcher as cd

    calls: list[tuple] = []

    def _normalize(_tid, root_ticket_id=None):
        calls.append(("normalize", root_ticket_id))
        return "traj-test"

    def _hop(tid, agent_id, reason, root_ticket_id=None):
        calls.append(("hop", tid, agent_id, reason, root_ticket_id))
        return {"allowed": False, "reason": "CYCLE_DETECTED"}

    def _tokens(*_a, **_k):
        calls.append(("tokens",))
        return {"allowed": True}

    fake = SimpleNamespace(
        normalize_trajectory_id=_normalize,
        reserve_hop=_hop,
        reserve_tokens=_tokens,
    )
    monkeypatch.setitem(__import__("sys").modules, "backend.trajectory_budget", fake)

    result = await asyncio.to_thread(
        cd._reserve_trajectory_budget_sync, "ticket-7", "agent-a", 1000, "llm_call:agent-a"
    )
    assert result["allowed"] is False
    assert result["stage"] == "hop"
    assert result["reason"] == "CYCLE_DETECTED"
    assert ("normalize", "ticket-7") in calls
    assert not any(c[0] == "tokens" for c in calls), "kein Token-Hop nach blockiertem Hop"


# ---------------------------------------------------------------------------
# H-08-2 — /readyz & /health
# ---------------------------------------------------------------------------

def test_readiness_sync_checks_are_offloaded():
    import main

    src = _src("main.py")
    readiness = inspect.getsource(main.readiness_check)
    assert "await asyncio.to_thread(_readiness_sync_checks)" in readiness
    assert "CREATE TABLE" not in readiness
    assert "await readiness_check()" not in inspect.getsource(main.health_check)
    assert "await liveness_check()" in inspect.getsource(main.health_check)
    assert "CREATE TABLE IF NOT EXISTS _readiness_probe" in src
    # G7-Migration (2b, ANALYSIS §6 #5 / Anhang D.2: „Umstellung auf V, nicht
    # Loeschen"): der Source-String wanderte mit dem Lifespan nach
    # archon/services/lifecycle.py. Statt Text wird jetzt das VERHALTEN
    # festgenagelt: der Probe-Aufbau muss beim Lifespan-Start in einem
    # Worker-Thread laufen und darf nicht im Event-Loop blockieren (D08/H-08-2).
    # Rot, sobald asyncio.to_thread durch einen direkten Aufruf ersetzt wird —
    # unabhaengig davon, in welchem Modul der Code steht.
    import asyncio
    import threading
    from contextlib import suppress
    from unittest.mock import AsyncMock, patch

    seen: dict = {}

    def _probe() -> None:
        seen["thread"] = threading.current_thread().name

    async def _drive() -> None:
        gen = main._archon_lifespan(None)
        with patch.object(main, "_STARTUP_HOOKS", []), \
             patch.object(main, "_SHUTDOWN_HOOKS", []), \
             patch.object(main, "_FAIL_FAST_HOOKS", set()), \
             patch.object(main, "_init_readiness_probe_table", _probe), \
             patch("backend.loop_liveness.start_loop_heartbeat", new=AsyncMock()), \
             patch("backend.loop_liveness.stop_loop_heartbeat", new=AsyncMock()):
            await gen.__anext__()
            with suppress(StopAsyncIteration):
                await gen.__anext__()
            await gen.aclose()

    main_thread = threading.current_thread().name
    asyncio.run(_drive())
    assert seen.get("thread"), "Readiness-Probe wurde im Lifespan nicht ausgefuehrt"
    assert seen["thread"] != main_thread, "Readiness-Probe lief im Event-Loop statt im Worker-Thread"


# ---------------------------------------------------------------------------
# H-08-3 / H-08-5 — Kanban & Boardroom Persistenz
# ---------------------------------------------------------------------------

def test_kanban_terminal_status_uses_single_worker_helper():
    import backend.operations_api as ops

    helper = inspect.getsource(ops._persist_kanban_result_sync)
    inner = inspect.getsource(ops._execute_kanban_task_inner)
    assert "_get_kanban_connection" in helper
    assert "conn.commit()" in helper
    assert "await asyncio.to_thread(" in inner
    assert inner.count("_persist_kanban_result_sync") >= 4
    assert "_get_kanban_connection(maintenance=True)" not in inner


def test_kanban_cancel_import_is_fail_closed():
    # G7/D3-6: Ausfuehrungslogik liegt jetzt in backend/operations_execution.py.
    module_src = _src("backend/operations_execution.py")
    assert "except ImportError as cancel_import_exc" in module_src
    assert "raise RuntimeError(\"cancellation unavailable\")" in module_src
    assert "cancellation_unavailable" in module_src


def test_boardroom_persistence_chain_uses_worker_helper():
    import archon.routers.boardroom as br

    helper = inspect.getsource(br._persist_boardroom_result_sync)
    assert "save_boardroom_history_item" in helper
    assert "dispatch_workflow_event" in helper
    assert "_escalate_boardroom_no_consensus" in helper
    for fn in (br.api_run_boardroom,):
        src = inspect.getsource(fn)
        assert "await asyncio.to_thread(" in src
        assert "_persist_boardroom_result_sync" in src
    stream_src = _src("archon/routers/boardroom.py")
    assert "await asyncio.to_thread(" in stream_src


# ---------------------------------------------------------------------------
# D08-MED — Batcher / Prefetcher / Bandit / Client-Close
# ---------------------------------------------------------------------------

def test_enqueue_only_buffers_and_schedules_drain():
    import backend.async_write_batcher as awb

    enqueue_src = inspect.getsource(awb.AsyncWriteBatcher.enqueue)
    assert "self.flush()" not in enqueue_src
    assert "_request_drain()" in enqueue_src
    drain_src = inspect.getsource(awb.AsyncWriteBatcher._drain_worker)
    assert "await asyncio.to_thread(self.flush)" in drain_src


@_async_test
async def test_drain_request_does_not_flush_inline(monkeypatch):
    import backend.async_write_batcher as awb

    batcher = awb.AsyncWriteBatcher()
    requested = []
    flushed = []
    monkeypatch.setattr(batcher, "_request_drain", lambda: requested.append(True))
    monkeypatch.setattr(batcher, "flush", lambda: flushed.append(True))
    monkeypatch.setattr(awb, "_get_cfg", lambda: {
        "enabled": True, "batch_size": 1, "flush_interval_seconds": 60,
        "max_queue_size": 100, "retention_max_rows": 10,
    })

    res = batcher.enqueue("evt", "test", {"a": 1})
    assert res["flush_result"]["drain_scheduled"] is True
    assert requested == [True]
    assert flushed == [], "enqueue darf nicht direkt flush() aufrufen"


@_async_test
async def test_prefetcher_closes_connection_on_error_and_caps_lru(monkeypatch):
    import backend.speculative_prefetcher as sp

    class _Conn:
        row_factory = None

        def execute(self, *_a, **_k):
            raise sqlite3.OperationalError("no such table: learnings")

        def close(self):
            closed.append(True)

    closed: list[bool] = []
    monkeypatch.setattr(sp.os.path, "exists", lambda path: True)
    monkeypatch.setattr(sp.sqlite3, "connect", lambda *_a, **_k: _Conn())
    pf = sp.SpeculativePrefetcher()
    assert pf._lookup_learnings(["irgendwas"], agent_id="agent") == []
    assert closed == [True], "Connection muss auch im Fehlerfall geschlossen werden"

    monkeypatch.setattr(sp, "_MAX_CACHE_ENTRIES", 3)
    pf = sp.SpeculativePrefetcher()
    for i in range(25):
        pf._cache_put(f"key:{i}", {"i": i}, 1e12)
    assert len(pf._cache) == 3
    assert "key:0" not in pf._cache


@_async_test
async def test_bandit_record_outcome_uses_one_connection(monkeypatch, tmp_path):
    import backend.bandit_model_router as bmr

    db = tmp_path / "bandit.db"
    monkeypatch.setattr(bmr, "DB_PATH", str(db))
    monkeypatch.setattr(bmr, "_get_cfg", lambda: {
        "enabled": True, "exploration_epsilon": 0.0,
        "latency_weight": 0.4, "success_weight": 0.6,
    })
    real_connect = sqlite3.connect
    opened = []

    def _counting_connect(*args, **kwargs):
        opened.append(1)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(bmr.sqlite3, "connect", _counting_connect)
    router = bmr.BanditModelRouter()
    opened.clear()  # Schema-Init nicht zaehlen
    result = router.record_outcome("test/model", True, 120.0)
    assert len(opened) == 1, "record_outcome darf nur EINE Connection oeffnen"
    assert result["enabled"] is True
    assert any(entry["model_id"] == "test/model" for entry in result["leaderboard"])


@_async_test
async def test_failed_client_close_is_reported_and_kept(monkeypatch):
    import core_dispatcher as cd

    class _BadClient:
        is_closed = False

        async def aclose(self):
            raise RuntimeError("transport still open")

    client = _BadClient()
    cd._DISPATCHER_HTTP_CLIENTS[asyncio.get_running_loop()] = client
    try:
        result = await cd.close_dispatcher_clients()
        assert result["closed"] == 0
        assert result["failed_closes"] == 1
        assert client in cd._DISPATCHER_HTTP_CLIENTS.values()
    finally:
        cd._DISPATCHER_HTTP_CLIENTS.clear()


# ---------------------------------------------------------------------------
# D07-Rest — Fail-Closed-Pfade
# ---------------------------------------------------------------------------

def test_watchdog_spawn_failure_is_fail_closed(monkeypatch):
    import sys

    import watchdog_daemon as wd

    states = []
    monkeypatch.setattr(wd, "_write_watchdog_liveness",
                        lambda n, *, dead=False: states.append(dead))

    def _no_spawn(*_a, **_k):
        raise RuntimeError("spawn blocked")

    # start_background_watchdog() importiert multiprocessing lokal.
    monkeypatch.setitem(sys.modules, "multiprocessing",
                        SimpleNamespace(get_context=_no_spawn))

    with pytest.raises(RuntimeError, match="Supervisor-Prozess"):
        wd.start_background_watchdog()
    assert states == [True]


def test_usage_log_errors_are_escalated():
    import core_dispatcher as cd

    helper = inspect.getsource(cd._audit_dispatch_failure)
    assert 'category="recovery"' in helper
    assert "logger.error" in helper
    inner = inspect.getsource(cd._log_dispatcher_usage_sync)
    assert "_audit_dispatch_failure" in inner
    assert "cur_upd.rowcount" in inner


def test_mission_control_cockpit_has_no_parallel_15s_poll():
    js = _src("static/js/mission_control_cockpit.js")
    assert "15000" not in js
    assert "60000" in js
    assert "__mc_last_sse_ts" in js


# ---------------------------------------------------------------------------
# Querschnitt W3-A / W3-D: kanonische Helfer konsumieren, nicht duplizieren
# ---------------------------------------------------------------------------

def test_canonical_handoff_schema_is_consumed_not_duplicated():
    import backend.operations_api as ops

    loader = inspect.getsource(ops._load_kanban_delegation_payload)
    assert "canonicalize_delegation_payload(" in loader
    assert "HandoffDelegationPayload" in loader
    # Keine zweite lokale Schema-Definition mehr.
    assert "class KanbanDelegationPayload" not in _src("backend/operations_api.py")
    assert "extra=\"ignore\"" not in loader


def test_accepted_handoff_is_a_hard_gate_before_dispatch():
    # G7/D3-6: Ausfuehrungslogik liegt jetzt in backend/operations_execution.py.
    src = _src("backend/operations_execution.py")
    assert "require_accepted_handoff" in src
    assert src.count("_handoff_gate_ok()") >= 2
    assert "handoff_not_accepted" in src
    assert "handoff_gate_unavailable" in src


def test_task_tenant_uses_canonical_resolver():
    # G7/D3-6: Ausfuehrungslogik liegt jetzt in backend/operations_execution.py.
    src = _src("backend/operations_execution.py")
    assert "resolve_task_tenant_id(t_dict)" in src
    assert '_tenant_id = str(t_dict.get("tenant_id") or "default")' not in src


def test_dispatch_history_uses_dropped_marker():
    import core_dispatcher as cd

    impl = inspect.getsource(cd._dispatch_to_omniroute_or_container_impl)
    assert "history_with_dropped_marker" in impl
    assert "history[-8:]" not in impl
    assert "GEKÜRZT" in impl


def test_budget_allocation_failure_blocks_task():
    import backend.operations_api as ops

    helper = inspect.getsource(ops._block_task_budget_allocation_failed_sync)
    assert "block_kind = 'budget_allocation_failed'" in helper
    assert "budget_allocation_failed" in helper
    src = _src("backend/operations_api.py")
    assert "except Exception as alloc_err:" in src
    assert '# D13/MED: ohne Allokationszeile' in src
    assert '"status": "blocked", "task_id": task_id' in src

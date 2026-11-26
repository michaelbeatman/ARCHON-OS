"""F30 (HIGH H-C): _execute_mission_control_task lagert sync SQLite/Store-I/O in to_thread aus."""
from __future__ import annotations

import asyncio
import time

from archon.core.orchestration import _execute_mission_control_task


def test_f30_mc_task_core_is_non_blocking_and_preserves_cas_idempotency(monkeypatch):
    """Parallele MC-Tasks unter langsamem Store/Lease/Idempotency-Lock blockieren Event-Loop nicht;
    CAS-Semantik (completed -> record_execution_result, failed -> invalidate_key) bleibt erhalten.
    """
    import backend.deadlock_supervisor as ds_mod
    import backend.idempotency_guard as idem_mod

    recorded = []
    invalidated = []
    released = []

    class _SlowSupervisor:
        def acquire_lease(self, tid, ttl_seconds=300):
            time.sleep(0.15)
            return {"acquired": True, "lease_token": f"tok-{tid}"}

        def heartbeat(self, tid, token, ttl_seconds=300):
            return True

        def release_lease(self, tid, token):
            time.sleep(0.05)
            released.append((tid, token))

    class _SlowIdem:
        def check_or_register(self, op, payload, explicit_key=None):
            time.sleep(0.10)
            return {"blocked": False, "idempotency_key": explicit_key}

        def record_execution_result(self, key, result):
            time.sleep(0.05)
            recorded.append((key, result))

        def invalidate_key(self, key):
            time.sleep(0.05)
            invalidated.append(key)

    monkeypatch.setattr(ds_mod, "deadlock_supervisor", _SlowSupervisor())
    monkeypatch.setattr(idem_mod, "idempotency_guard", _SlowIdem())

    store = {
        "tasks": [
            {"id": "t-ok", "title": "Erfolg", "agent_id": "coder", "status": "pending"},
            {"id": "t-fail", "title": "Fehler", "agent_id": "coder", "status": "pending"},
        ]
    }

    def _slow_load():
        time.sleep(0.10)
        return {"tasks": [dict(t) for t in store["tasks"]]}

    def _slow_update(mutator):
        time.sleep(0.05)
        mutator(store)

    class _FakeDispatcher:
        async def dispatch_to_omniroute_or_container(self, **kwargs):
            if kwargs.get("task_id") == "t-fail":
                return {"status": "error", "content": "boom"}
            return {"status": "success", "content": "Fertiges Ergebnis fuer F30."}

    async def _run():
        t0 = time.perf_counter()
        loop_latency = None

        async def _heartbeat():
            nonlocal loop_latency
            await asyncio.sleep(0.02)
            loop_latency = time.perf_counter() - t0

        await asyncio.gather(
            _execute_mission_control_task(
                "t-ok",
                load_mc=_slow_load,
                update_mc=_slow_update,
                dispatcher=_FakeDispatcher(),
                get_profiles=lambda: [{"id": "coder", "name": "Coder", "prompt": "Test"}],
                ticker=lambda *_a, **_kw: None,
                sync_obsidian=lambda *_a, **_kw: "vault/ok.md",
            ),
            _execute_mission_control_task(
                "t-fail",
                load_mc=_slow_load,
                update_mc=_slow_update,
                dispatcher=_FakeDispatcher(),
                get_profiles=lambda: [{"id": "coder", "name": "Coder", "prompt": "Test"}],
                ticker=lambda *_a, **_kw: None,
                sync_obsidian=lambda *_a, **_kw: "vault/fail.md",
            ),
            _heartbeat(),
        )
        # Ohne to_thread wuerden 2*(0.10+0.15+0.10+...) > 0.7s den Event-Loop blockieren
        assert loop_latency is not None and loop_latency < 0.12, f"Event-Loop blockiert: {loop_latency:.3f}s"

    asyncio.run(_run())

    assert any(k == "mct-t-ok" for k, _ in recorded), f"completed-Task muss record_execution_result rufen: {recorded}"
    assert "mct-t-fail" in invalidated, f"failed-Task muss invalidate_key rufen: {invalidated}"
    assert len(released) == 2

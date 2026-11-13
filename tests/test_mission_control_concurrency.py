"""
Nebenläufigkeitstests für den Mission-Control-Store (Audit B1).

Der Store hatte zwei Probleme:

1. **Zwei Locks auf ein Ziel.** `_MC_DATA_LOCK` (threading) schützte
   `_save_mission_control_data`, `_MC_ASYNC_LOCK` (asyncio) schützte den
   Direktschreiber in `orchestration._fan_in_maybe_start_synthesis`. Zwei
   verschiedene Locks serialisieren nicht gegeneinander.
2. **Ungeschützte Lese-Ändere-Schreibe-Kette.** `_load` … `_save` hielt keinen
   Lock über die gesamte Sequenz, parallele Schreiber überschrieben einander
   (Lost Update).

Diese Tests halten den Fix fest: `_write_mc_atomic` nimmt den Lock selbst
(RLock, verschachtelbar), und `update_mission_control_data` hält ihn über
Laden, Ändern und Schreiben.
"""

import json
import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import archon.core.mission_control as mc  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Frischer Store mit nicht-leerer Task-Liste (sonst greift der DB-Fallback)."""
    path = tmp_path / "mission_control_data.json"
    path.write_text(json.dumps({"tasks": [{"id": "seed"}], "counter": 0}), encoding="utf-8")
    monkeypatch.setattr(mc, "MISSION_CONTROL_FILE", str(path))
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------ Lost Update

def test_concurrent_updates_do_not_lose_writes(store):
    """20 Threads × 5 Inkremente = 100. Ein Lost Update würde weniger ergeben."""
    per_thread, threads = 5, 20

    def worker():
        for _ in range(per_thread):
            def mutate(data):
                data["counter"] = data.get("counter", 0) + 1
                return data["counter"]
            mc.update_mission_control_data(mutate)

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=30)
        assert not t.is_alive(), "Thread haengt — moeglicher Deadlock"

    assert _read(store)["counter"] == per_thread * threads


def test_concurrent_updates_keep_task_list_intact(store):
    """Parallel angehaengte Tasks duerfen sich nicht gegenseitig verdraengen."""

    def worker(i):
        def mutate(data):
            data.setdefault("tasks", []).append({"id": f"t{i}"})
        mc.update_mission_control_data(mutate)

    pool = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=30)

    ids = {t["id"] for t in _read(store)["tasks"]}
    assert "seed" in ids
    assert {f"t{i}" for i in range(25)} <= ids


# ------------------------------------------------------------ Lock-Verhalten

def test_write_is_self_locking(store):
    """_write_mc_atomic ohne gehaltenen Lock aufrufen darf nicht korrumpieren."""
    for i in range(10):
        mc._write_mc_atomic({"tasks": [{"id": f"x{i}"}], "counter": i})
    assert _read(store)["counter"] == 9


def test_nested_lock_does_not_deadlock(store):
    """RLock: Schreiben mit bereits gehaltenem Lock (alter Aufrufpfad) muss gehen."""
    done = threading.Event()

    def nested():
        with mc._MC_DATA_LOCK:
            mc._save_mission_control_data({"tasks": [{"id": "nested"}], "counter": 1})
        done.set()

    t = threading.Thread(target=nested)
    t.start()
    assert done.wait(timeout=10), "Deadlock: verschachtelter Lock blockiert"
    assert _read(store)["counter"] == 1


def test_no_temp_files_left_behind(store):
    mc.update_mission_control_data(lambda d: d.__setitem__("counter", 7))
    leftovers = [p for p in os.listdir(os.path.dirname(store)) if p.endswith(".tmp")]
    assert leftovers == []

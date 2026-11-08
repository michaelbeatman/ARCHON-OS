"""Regressionstests F-02, F-07, F-08, F-09, F-11, F-20.

F-02: Watchdog-Seen-IDs chronologisch (kein zufaelliger set-Trim).
F-07: settings.json-Schreiber atomar + gelockt (5 Module + Helfer).
F-08: SSE-broadcast trennt langsame Clients nicht mehr ab (QueueFull).
F-09: Permission-Gate-Anlage meldet Speicherfehler ehrlich (kein Erfolgs-Ping).
F-11: Inbox-Favorite meldet 404 statt Erfolg ohne Schreibbeleg.
F-20: Profil-Mirror schreibt in die Root-SSOT statt ins Paketverzeichnis.
"""

import asyncio
import json
import os
import sys
import tempfile
import types
from unittest import mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- F-02

def test_watchdog_seen_trim_is_chronological(tmp_path):
    from backend import internet_watchdog as iw

    seen_file = tmp_path / "seen.json"
    iw.SEEN_FILE_ORIG = iw.SEEN_FILE
    iw.SEEN_FILE = str(seen_file)

    ids = [f"id-{i:04d}" for i in range(2500)]
    iw._save_seen(ids)

    with open(seen_file, "r", encoding="utf-8") as f:
        saved = json.load(f)["seen_ids"]

    assert len(saved) == 2000
    assert saved[:5] == ["id-0500", "id-0501", "id-0502", "id-0503", "id-0504"], \
        "F-02: die aeltesten IDs muessen zuerst rausfallen (chronologisch)"
    assert saved[-1] == "id-2499"
    # Laden liefert eine Liste (deterministische Reihenfolge), kein set.
    assert isinstance(iw._load_seen(), list)


# ---------------------------------------------------------------- F-07

def test_settings_atomic_update_preserves_other_sections(tmp_path):
    from backend import settings_json as sj

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"fremde_sektion": {"x": 1}}), encoding="utf-8")

    def _apply(current):
        current["memory_consolidation"] = {"enabled": True}

    sj.atomic_update_settings(str(path), _apply)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["fremde_sektion"] == {"x": 1}
    assert data["memory_consolidation"]["enabled"] is True


def test_settings_atomic_update_no_tmp_leftovers(tmp_path):
    from backend import settings_json as sj

    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    sj.atomic_update_settings(str(path), lambda c: c.update({"a": 1}))
    leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert leftovers == []


def test_settings_atomic_update_parallel_writers_no_lost_sections(tmp_path):
    import threading
    from backend import settings_json as sj

    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    def _writer(name):
        def _apply(current):
            current[name] = {"v": name}
        sj.atomic_update_settings(str(path), _apply)

    threads = [threading.Thread(target=_writer, args=(f"modul-{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert all(f"modul-{i}" in data for i in range(6))


def test_memory_consolidator_save_uses_atomic_helper(tmp_path, monkeypatch):
    from backend import memory_consolidator as mc

    path = tmp_path / "settings.json"
    monkeypatch.setattr(mc, "SETTINGS_FILE", str(path))
    path.write_text(json.dumps({"andere": 1}), encoding="utf-8")

    assert mc.save_consolidation_config({"enabled": True}) is True
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["andere"] == 1
    assert data["memory_consolidation"]["enabled"] is True


def test_inbox_watcher_save_uses_atomic_helper(tmp_path, monkeypatch):
    from backend import inbox_watcher as iw

    path = tmp_path / "settings.json"
    monkeypatch.setattr(iw, "SETTINGS_FILE", str(path))
    assert iw.save_inbox_config({"watch_folder": "/x"}) is True
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["inbox_watcher"]["watch_folder"] == "/x"


def test_autonomy_settings_save_preserves_foreign_sections(tmp_path, monkeypatch):
    from backend import autonomy_settings as aua

    path = tmp_path / "settings.json"
    monkeypatch.setattr(aua, "SETTINGS_FILE", str(path))
    path.write_text(json.dumps({"fremd": {"y": 2}}), encoding="utf-8")
    aua.save_autonomy_settings({"pii_scrubber": {"enabled": False}})

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["fremd"] == {"y": 2}
    assert data["pii_scrubber"]["enabled"] is False


def test_concurrency_and_watchdog_save_use_atomic(tmp_path, monkeypatch):
    from backend import concurrency_throttle as ct
    from backend import internet_watchdog as iw

    p1 = tmp_path / "s1.json"
    monkeypatch.setattr(ct, "SETTINGS_FILE", str(p1))
    assert ct.save_concurrency_config({"max_concurrent_agents": 3}) is True

    p2 = tmp_path / "s2.json"
    monkeypatch.setattr(iw, "SETTINGS_FILE", str(p2))
    assert iw.save_watchdog_config({"enabled": False}) is True


# ---------------------------------------------------------------- F-08

def test_broadcast_event_keeps_slow_subscriber_connected():
    from archon.core import runtime as rt

    full_queue = asyncio.Queue(maxsize=1)
    full_queue.put_nowait("voll")

    with mock.patch.object(rt, "_SSE_SUBSCRIBERS", [full_queue]):
        rt.broadcast_event("kanban_updated", {"a": 1})

        # Der volle Puffer wird NICHT entfernt — der Client bleibt verbunden.
        assert full_queue in rt._SSE_SUBSCRIBERS
        assert full_queue.qsize() == 1


def test_broadcast_event_drops_event_for_full_queue_but_delivers_later():
    from archon.core import runtime as rt

    q = asyncio.Queue(maxsize=1)
    q.put_nowait("alt")
    with mock.patch.object(rt, "_SSE_SUBSCRIBERS", [q]):
        rt.broadcast_event("ticker_update", {"x": 1})
        # Puffer voll -> Event fuer diesen Client gedroppt, Verbindung bleibt.
        assert q in rt._SSE_SUBSCRIBERS
        q.get_nowait()  # alt
        rt.broadcast_event("ticker_update", {"x": 2})
        assert q.qsize() == 1
        assert '"x": 2' in q.get_nowait()


def test_broadcast_event_still_removes_cancelled_subscriber():
    from archon.core import runtime as rt

    class _ToteQueue:
        def put_nowait(self, p):
            raise RuntimeError("Queue geschlossen")

    with mock.patch.object(rt, "_SSE_SUBSCRIBERS", [_ToteQueue()]):
        rt.broadcast_event("x", {})
        assert len(rt._SSE_SUBSCRIBERS) == 0


# ---------------------------------------------------------------- F-09

def test_create_permission_gate_aborts_without_disk_beleg(tmp_path):
    from archon.core import permissions as perm

    gates_file = tmp_path / "permission_gates.json"
    saved = {"result": False}

    def _failing_save(data):
        saved["result"] = False
        return False

    with mock.patch.object(perm, "PERMISSION_GATES_FILE", str(gates_file)), \
         mock.patch.object(perm, "save_permission_gates", side_effect=_failing_save), \
         mock.patch.object(perm, "get_decision_factory", return_value=None):
        with pytest.raises(RuntimeError, match="konnte nicht gespeichert"):
            perm.create_permission_gate("tools_erweiterung", "Detail", "agent-1", {})


def test_create_permission_gate_success_persists_gate(tmp_path):
    from archon.core import permissions as perm

    gates_file = tmp_path / "permission_gates.json"
    with mock.patch.object(perm, "PERMISSION_GATES_FILE", str(gates_file)), \
         mock.patch.object(perm, "get_decision_factory", return_value=None), \
         mock.patch("archon.core.runtime.add_ticker"):
        gate = perm.create_permission_gate("tools_erweiterung", "Detail", "agent-1", {})
        assert gate["status"] == "pending"
        assert perm.load_permission_gates()["gates"][0]["id"] == gate["id"]


# ---------------------------------------------------------------- F-11

def test_favorite_unknown_profile_returns_404(tmp_path):
    from archon import routers
    from archon.routers import hermes_profiles as hp

    base = tmp_path / "profiles"
    os.makedirs(base)
    with mock.patch.object(hp, "get_hermes_profiles_base_dirs", return_value=[str(base)]):
        with pytest.raises(HTTPException) as e:
            hp.api_toggle_hermes_profile_favorite("gibt-es-nicht", True)
    assert e.value.status_code == 404


def test_favorite_known_profile_writes_and_returns_state(tmp_path):
    from archon.routers import hermes_profiles as hp

    base = tmp_path / "profiles"
    prof_dir = base / "agent-x"
    os.makedirs(prof_dir)
    yaml_path = prof_dir / "profile.yaml"
    yaml_path.write_text("name: Agent X\nis_favorite: false\n", encoding="utf-8")

    with mock.patch.object(hp, "get_hermes_profiles_base_dirs", return_value=[str(base)]), \
         mock.patch.object(hp, "invalidate_hermes_profiles_cache"), \
         mock.patch.object(hp, "api_get_hermes_profiles", return_value=None):
        res = hp.api_toggle_hermes_profile_favorite("agent-x", True)

    assert res["status"] == "success"
    assert res["is_favorite"] is True
    assert "is_favorite: true" in yaml_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- F-20

def test_profiles_mirror_targets_root_ssot(tmp_path, monkeypatch):
    """Der Spiegel schreibt in APP_ROOT (Repo-Root), nicht in archon/core."""
    import ast
    import inspect
    from archon.core import profiles as prof

    src = inspect.getsource(prof.api_get_hermes_profiles)
    tree = ast.parse(src)
    # _APP_ROOT-Schatten darf nicht mehr existieren:
    assert not any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_APP_ROOT" for t in n.targets)
        for n in ast.walk(tree)
    )
    # SSOT-Pfad nutzt das importierte APP_ROOT:
    assert "os.path.join(APP_ROOT, \"agent_profiles.json\")" in src


def test_profiles_module_has_no_app_root_shadow():
    import ast
    from archon.core import profiles as prof

    with open(prof.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    shadows = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_APP_ROOT" for t in n.targets)
    ]
    assert shadows == [], "F-20: lokale _APP_ROOT-Zuweisung muss weg"

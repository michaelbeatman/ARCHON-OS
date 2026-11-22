"""Regressionstests fuer Batch B/8: Event-Push statt 10s-Polling im Delegations-Watcher.

Quelltext-Assertions sichern die Verdrahtung; ein Offline-Verhaltenstest
(monkeypatcht DB, Config und Finalisierung) zeigt, dass ein ``kanban_updated``-
Terminal-Event den Watcher sofort beendet — ohne 10-Sekunden-Poll und ohne
echtes Netzwerk/DB.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUNTIME_SRC = REPO_ROOT / "archon" / "core" / "runtime.py"
DELEGATION_SRC = REPO_ROOT / "archon" / "core" / "delegation.py"


# ---------------------------------------------------------------------------
# Quelltext-Assertions
# ---------------------------------------------------------------------------
def test_runtime_exposes_bounded_subscription_helpers():
    """runtime.py muss oeffentliche, begrenzte Abonnement-Helfer anbieten."""
    src = RUNTIME_SRC.read_text(encoding="utf-8")
    assert "def subscribe_events()" in src
    assert "def unsubscribe_events(q: asyncio.Queue)" in src
    assert "asyncio.Queue(maxsize=" in src
    assert "_SSE_SUB_LOCK" in src
    assert "_SSE_SUBSCRIBERS" in src
    assert '"subscribe_events", "unsubscribe_events"' in src


def test_watcher_uses_event_driven_wait_and_persisted_config():
    """Der Watcher darf nicht mehr 10s pollen und muss Config-Keys nutzen."""
    src = DELEGATION_SRC.read_text(encoding="utf-8")
    assert "asyncio.sleep(10)" not in src
    assert "subscribe_events()" in src
    assert "unsubscribe_events(events)" in src
    assert "asyncio.wait_for(" in src
    assert "events.get()" in src
    assert "json.loads(payload)" in src
    assert '"kanban_updated"' in src
    assert 'get_module_config("delegation")' in src
    for key in (
        "watcher_deadline_seconds",
        "watcher_fallback_poll_seconds",
        "watcher_retry_count",
    ):
        assert key in src
    # 1200 kommt nur noch als Konfigurations-Default vor, nie als Konstante.
    assert src.count("1200") == 1
    assert '"watcher_deadline_seconds", 1200' in src
    assert "20 Minuten" not in src


# ---------------------------------------------------------------------------
# Offline-Verhalten der Event-Bus-Helfer
# ---------------------------------------------------------------------------
async def test_event_bus_subscribe_unsubscribe_roundtrip():
    """subscribe/unsubscribe registrieren und entfernen die Queue sicher."""
    from archon.core import runtime

    q = runtime.subscribe_events()
    try:
        assert q in runtime._SSE_SUBSCRIBERS
        assert q.maxsize == runtime._SSE_QUEUE_MAXSIZE
        runtime.broadcast_event("p2_probe", {"x": 1})
        payload = await asyncio.wait_for(q.get(), timeout=1)
        parsed = json.loads(payload)
        assert parsed["type"] == "p2_probe"
        assert parsed["data"] == {"x": 1}
    finally:
        runtime.unsubscribe_events(q)

    assert q not in runtime._SSE_SUBSCRIBERS
    # Idempotent: zweites Entfernen darf nicht werfen.
    runtime.unsubscribe_events(q)


# ---------------------------------------------------------------------------
# Offline-Verhalten des Watchers
# ---------------------------------------------------------------------------
async def test_watcher_finalizes_on_terminal_event_without_waiting(tmp_path, monkeypatch):
    """Ein kanban_updated-Event mit 'to=done' beendet den Watcher sofort.

    Alle DB-/Netzwerk-/Datei-Zugriffe sind ersetzt; der Test wartet nur darauf,
    dass der Watcher am Bus registriert ist, und broadcastet dann das Event.
    """
    from archon.core import delegation, runtime

    task_id = "t-p2-event-push-001"
    s_id = "sub-p2-event-push"
    saved: list[tuple[str, str, str]] = []

    # Config: kurzer Deadline, aber sehr langer Fallback-Poll. Wuerde der
    # Watcher pollen statt auf Events zu warten, wuerde er hier nicht enden.
    monkeypatch.setattr(
        "backend.autonomy_settings.get_module_config",
        lambda section: ({
            "watcher_deadline_seconds": 5,
            "watcher_fallback_poll_seconds": 60,
            "watcher_retry_count": 3,
        } if section == "delegation" else {}),
    )

    # Keine echte DB: der Safety-Poll liefert sofort eine terminale Zeile.
    monkeypatch.setattr(
        delegation, "_poll_kanban_row",
        lambda tid: ("done", "fertig", "Testauftrag"),
    )
    # Keine echte Finalisierung: Nachrichten nur sammeln.
    monkeypatch.setattr(
        delegation, "_save_message_to_db",
        lambda sid, role, content, token_count=None: saved.append((sid, role, content)),
    )
    # Datei-/DB-/Netzwerk-Seiteneffekte der Finalisierung neutralisieren.
    monkeypatch.setattr(delegation, "OPT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(delegation, "PROJEKTE_DIR", str(tmp_path / "vault" / "01_PROJEKTE"))
    monkeypatch.setattr(delegation, "WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setattr(
        delegation, "_get_obsidian_vault_dir", lambda: str(tmp_path / "vault")
    )
    monkeypatch.setattr(
        delegation, "mc_get_parent_context_sqlite", lambda tid: (None, None)
    )
    monkeypatch.setattr(delegation, "mc_update_task_sqlite", lambda *a, **k: None)
    monkeypatch.setattr(delegation, "_register_decision", lambda *a, **k: None)

    fake_notify = types.ModuleType("telegram_notify")
    fake_notify.notify_task_status = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "telegram_notify", fake_notify)

    delegation._ACTIVE_WATCHERS.discard(task_id)
    before = len(runtime._SSE_SUBSCRIBERS)
    task = asyncio.create_task(
        delegation._watch_delegated_task(task_id, s_id, "test_agent")
    )
    try:
        # Deterministisch auf die Registrierung warten (kein sleep(10)).
        for _ in range(100):
            if len(runtime._SSE_SUBSCRIBERS) > before:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Watcher hat sich nicht am Event-Bus registriert")

        runtime.broadcast_event(
            "kanban_updated", {"task_id": task_id, "to": "done"}
        )
        await asyncio.wait_for(task, timeout=3)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        delegation._ACTIVE_WATCHERS.discard(task_id)

    assert any(
        role == "assistant" and "DELEGATION ABGESCHLOSSEN" in content
        for _, role, content in saved
    )
    assert not any("DELEGATION-TIMEOUT" in content for _, _, content in saved)


async def test_watcher_ignores_foreign_and_non_terminal_events(tmp_path, monkeypatch):
    """Nur passende task_id + Terminal-Status beenden den Watcher."""
    from archon.core import delegation, runtime

    task_id = "t-p2-event-push-002"
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "backend.autonomy_settings.get_module_config",
        lambda section: ({
            "watcher_deadline_seconds": 5,
            "watcher_fallback_poll_seconds": 60,
            "watcher_retry_count": 3,
        } if section == "delegation" else {}),
    )
    db_state = {"row": ("in_progress", "", "Test")}

    def _fake_poll(tid):
        return db_state["row"]

    monkeypatch.setattr(delegation, "_poll_kanban_row", _fake_poll)
    monkeypatch.setattr(
        delegation, "_save_message_to_db",
        lambda sid, role, content, token_count=None: saved.append((sid, role, content)),
    )
    monkeypatch.setattr(delegation, "OPT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(delegation, "PROJEKTE_DIR", str(tmp_path / "vault" / "01_PROJEKTE"))
    monkeypatch.setattr(delegation, "WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setattr(
        delegation, "_get_obsidian_vault_dir", lambda: str(tmp_path / "vault")
    )
    monkeypatch.setattr(
        delegation, "mc_get_parent_context_sqlite", lambda tid: (None, None)
    )
    monkeypatch.setattr(delegation, "mc_update_task_sqlite", lambda *a, **k: None)
    fake_notify = types.ModuleType("telegram_notify")
    fake_notify.notify_task_status = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "telegram_notify", fake_notify)

    delegation._ACTIVE_WATCHERS.discard(task_id)
    before = len(runtime._SSE_SUBSCRIBERS)
    task = asyncio.create_task(
        delegation._watch_delegated_task(task_id, "sub-002", "test_agent")
    )
    try:
        for _ in range(100):
            if len(runtime._SSE_SUBSCRIBERS) > before:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Watcher hat sich nicht am Event-Bus registriert")

        # Falsche task_id und nicht-terminaler Status duerfen nicht finalisieren.
        runtime.broadcast_event("kanban_updated", {"task_id": "other", "to": "done"})
        runtime.broadcast_event("kanban_updated", {"task_id": task_id, "to": "in_progress"})
        await asyncio.sleep(0.05)
        assert not task.done()
        assert not saved

        # Erst das passende Event beendet den Watcher (Deadline=5s, Poll=60s).
        # Der DB-Read spiegelt den bereits committeten Status wider.
        db_state["row"] = ("done", "fertig", "Test")
        runtime.broadcast_event("kanban_updated", {"task_id": task_id, "to": "done"})
        await asyncio.wait_for(task, timeout=3)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        delegation._ACTIVE_WATCHERS.discard(task_id)

    assert any("DELEGATION ABGESCHLOSSEN" in content for _, _, content in saved)

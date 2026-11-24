"""Cluster Spur A — views_core.py (N-09, P-01, P-02).

Rot gegen 3269f7e1:

* N-09: ``_vault_is_scanning`` wurde gelesen und erst im Worker gesetzt
  (Check-then-Act ueber Threads, ohne Lock); die Cache-Datei wurde mit
  ``open(...,"w")`` geschrieben (abschneidbar).
* P-01: Der kalte Vault-Scan lief inline im ``async def`` (gemessen ~10 s
  Walk) und fror damit den Event-Loop ein.
* P-02: ``subprocess.run`` mit 12-s-Timeout lief direkt im async-Handler.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import views_core  # noqa: E402


# --------------------------------------------------------------------- N-09

def test_cache_write_ist_atomar(tmp_path):
    """Der Cache-Write darf nie ein halbes JSON hinterlassen."""
    target = tmp_path / "cache.json"
    views_core._write_cache_atomic(str(target), {"tree": [1, 2, 3]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"tree": [1, 2, 3]}
    # keine Temp-Dateien liegen herum
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_cache_write_ist_atomar_auch_bei_fehler(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    target.write_text("ALT", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise RuntimeError("Platte voll")

    monkeypatch.setattr(views_core.os, "replace", boom)
    with pytest.raises(RuntimeError):
        views_core._write_cache_atomic(str(target), {"tree": []})

    # Zieldatei unveraendert, keine Temp-Reste
    assert target.read_text(encoding="utf-8") == "ALT"
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_nur_ein_scan_pro_vault_wird_ausgefuehrt(tmp_path, monkeypatch):
    """N gleichzeitige Cold-Requests duerfen nicht N Scans ausloesen."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("a", encoding="utf-8")

    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr(views_core, "VAULT_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(views_core, "_vault_tree_in_memory_cache", None)
    monkeypatch.setattr(views_core, "_vault_tree_cache_time", 0)
    monkeypatch.setattr(views_core, "_vault_is_scanning", False)

    calls = []
    real_build = views_core._build_vault_tree_fast

    def slow_build(*args, **kwargs):
        calls.append(1)
        time.sleep(0.2)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(views_core, "_build_vault_tree_fast", slow_build)

    threads = []
    for _ in range(4):
        t = threading.Thread(target=views_core._refresh_vault_cache_worker, args=(str(vault),))
        t.start()
        threads.append(t)
        time.sleep(0.01)
    for t in threads:
        t.join(timeout=10)

    assert len(calls) == 1, f"{len(calls)} Scans statt 1 (Thread-Sturm)"
    assert json.loads(cache_file.read_text(encoding="utf-8"))["tree"]


def test_scan_flag_wird_nach_dem_scan_zurueckgesetzt(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(views_core, "VAULT_CACHE_FILE", str(tmp_path / "c.json"))

    views_core._refresh_vault_cache_worker(str(vault))
    assert views_core._vault_is_scanning is False


# --------------------------------------------------------------------- P-01

def test_kalter_vault_scan_blockiert_den_event_loop_nicht(tmp_path, monkeypatch):
    """Der Handler darf den Scan nicht inline im Event-Loop ausfuehren."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("a", encoding="utf-8")

    monkeypatch.setattr(views_core, "VAULT_CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(views_core, "_vault_tree_in_memory_cache", None)
    monkeypatch.setattr(views_core, "_vault_tree_cache_time", 0)
    monkeypatch.setattr(views_core, "_vault_is_scanning", False)
    monkeypatch.setattr(views_core, "resolve_obsidian_vault_dir", lambda: str(vault))

    real_build = views_core._build_vault_tree_fast

    def slow_build(*args, **kwargs):
        time.sleep(0.5)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(views_core, "_build_vault_tree_fast", slow_build)

    async def scenario():
        loop = asyncio.get_running_loop()
        ticks = {"n": 0}

        async def ticker():
            while True:
                await asyncio.sleep(0.05)
                ticks["n"] += 1

        task = asyncio.create_task(ticker())
        result = await views_core.get_vault_tree(force_refresh=True)
        task.cancel()
        return result, ticks["n"]

    result, ticks = asyncio.run(scenario())
    assert result["tree"], "der Vault-Baum wurde nicht geliefert"
    # Bei inline-Ausfuehrung waere der Ticker eingefroren (0 Ticks).
    assert ticks >= 3, f"Event-Loop war blockiert (nur {ticks} Ticks)"


# --------------------------------------------------------------------- P-02

def test_run_code_blockiert_den_event_loop_nicht(monkeypatch, tmp_path):
    """Der 12-s-subprocess.run darf nicht inline im async-Handler laufen."""
    monkeypatch.setattr(views_core, "require_admin_or_503", lambda request: None)

    def fake_run(*args, **kwargs):
        time.sleep(0.4)
        raise RuntimeError("kaputt")

    monkeypatch.setattr("subprocess.run", fake_run)
    # Auf Windows schlaegt _resolve_host_path fehl (kein AF_UNIX) — dann
    # wird der gemockte Sleep nie erreicht. Host-Pfad explizit injizieren.
    import backend.ephemeral_sandbox as eps
    monkeypatch.setattr(eps, "_resolve_host_path", lambda _p: "/tmp/any")
    # D04/MED: ohne DOCKER_HOST-Proxy beendet die Sandbox sofort mit
    # not_configured und der 0.4-s-Sleep wird gar nicht erst erreicht.
    # Den Proxy hier setzen, damit der to_thread-Pfad wirklich gemessen wird.
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker-socket-proxy:2375")

    async def scenario():
        ticks = {"n": 0}

        async def ticker():
            while True:
                await asyncio.sleep(0.05)
                ticks["n"] += 1

        task = asyncio.create_task(ticker())
        payload = views_core.CodeRunPayload(code="print('x')", language="python")
        # S6-fail-closed: ohne Docker-Sandbox liefert der Handler 501.
        # dieser Test prüft nur die Event-Loop-Freiheit, nicht die Antwortform.
        outcome = None
        try:
            await views_core.run_showroom_code(None, payload)
        except Exception as exc:
            outcome = exc
        task.cancel()
        return outcome, ticks["n"]

    outcome, ticks = asyncio.run(scenario())
    # Der Handler darf entweder 501 (fail-closed ohne Docker) liefern oder
    # ein Error-Dict zurueckgeben — beides ist korrekt. Entscheidend ist,
    # dass der 0.4-s-Sleep in to_thread lief und die Event-Loop frei blieb.
    if outcome is not None:
        code = getattr(outcome, "status_code", None)
        assert code == 501 or (hasattr(outcome, "detail") and "Sandbox" in str(outcome.detail))
    assert ticks >= 3, f"Event-Loop war blockiert (nur {ticks} Ticks)"

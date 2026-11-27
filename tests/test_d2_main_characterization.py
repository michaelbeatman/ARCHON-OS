# -*- coding: utf-8 -*-
"""C0 — Characterization der 5 offenen D2-Vertraege (vor Schritt 2a).

`ANALYSIS_GOD_OBJECTS.md §4 D2` / `§6 #9` verlangen: die Golden-Tests muessen
GRUEN sein, BEVOR `main.py` zum ersten Mal gesplittet wird. Alle 5 Lueken
waren laut verifizierter Kartierung offen.

Grundsaetze (wie B0/B0b):
* Assertions gegen die ECHTE Logik, nicht gegen Source-Text.
* Jeder Test enthaelt eine Negativprobe, die bei gebrochener Logik rot wird.
* Geteilte Helper statt kopierter Snippets; kein Theater-Gate.
* Reine Testdatei — `main.py` wird NICHT geaendert.

Ownership: G4 (App-Owner), Test-Only-Schritt vor 2a.
"""

from __future__ import annotations

import asyncio
import json
import warnings
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

import main as app_main
from backend import rbac_guards

# ---------------------------------------------------------------------------
# Gemeinsame Helper
# ---------------------------------------------------------------------------


def _readyz() -> Any:
    """Ruft /readyz real auf; mockt NUR die blockierende Sync-DB-Proeung.

    Test-Isolation: andere Tests hinterlassen absichtlich fehlgeschlagene
    Cancels im globalen Registry; /readyz wuerde dafuer korrekt 503 liefern.
    Hier vor dem Aufruf zuruecksetzen, damit der saubere Zustand geprueft wird.
    """
    app_main._FAILED_CANCELS.clear()

    async def _invoke() -> Any:
        with patch.object(app_main, "_readiness_sync_checks", return_value=[]):
            return await app_main.readiness_check()

    return asyncio.run(_invoke())


def _assert_problems(resp: Any, marker: str) -> None:
    """Prueft 503 + Problems-Marker gegen die echte JSONResponse."""
    assert isinstance(resp, app_main.JSONResponse), f"kein 503-Response: {type(resp)}"
    assert resp.status_code == 503
    body = json.loads(bytes(resp.body))
    assert body["status"] == "not_ready"
    assert any(marker in str(p) for p in body["problems"]), body["problems"]


# ---------------------------------------------------------------------------
# ① /livez <-> _FAIL_FAST_HOOKS / _AUDIT_COMPROMISED
# ---------------------------------------------------------------------------


def test_c1_fail_fast_hook_set_and_audit_compromise_degrades_readyz():
    """IST-Stand festgenagelt (Kartierung korrigiert die Dossier-Annahme):

    * ``/livez`` liest NUR ``check_loop_liveness()`` + ``watchdog_liveness()``,
      KEINEN Bezug auf ``_FAIL_FAST_HOOKS``.
    * ``_AUDIT_COMPROMISED`` haengt an ``/readyz`` (``main.py:1362-1363``),
      nicht an ``/livez``.
    * Die 5 Fail-Fast-Hooks sind alle in ``_STARTUP_HOOKS`` registriert und
      ihr Scheitern raiset im Lifespan (``main.py:791-793``).
    """
    expected_hooks = {
        "_assert_router_health",
        "_assert_audit_hmac",
        "_assert_audit_integrity",
        "_assert_auth_on_nonloopback_bind",
        "_assert_api_key_pepper",
    }
    assert app_main._FAIL_FAST_HOOKS == expected_hooks
    for name in expected_hooks:
        assert callable(getattr(app_main, name, None)), f"Hook '{name}' nicht importierbar"
        assert getattr(app_main, name) in app_main._STARTUP_HOOKS, f"Hook '{name}' nicht registriert"
    assert app_main.AUDIT_COMPROMISED is app_main._AUDIT_COMPROMISED  # Alias, keine Kopie

    original = dict(app_main._AUDIT_COMPROMISED)
    try:
        app_main._AUDIT_COMPROMISED.update(compromised=True, reason="NEGATIVPROBE")
        resp = _readyz()
        _assert_problems(resp, "audit_compromised")
        assert any("NEGATIVPROBE" in str(p) for p in json.loads(bytes(resp.body))["problems"])
    finally:
        app_main._AUDIT_COMPROMISED.clear()
        app_main._AUDIT_COMPROMISED.update(original)

    # Negativprobe gegen die echte Logik: ohne Kompromittierung KEIN 503.
    clean = _readyz()
    assert not isinstance(clean, app_main.JSONResponse), (
        "sauberer Zustand darf nicht 503 sein: " + str(bytes(clean.body)[:600])
    )
    assert clean["status"] == "ready"
    with pytest.raises(AssertionError):
        _assert_problems(clean, "audit_compromised")


# ---------------------------------------------------------------------------
# ② Shutdown-Timeout / reversed() / Graceful-Drain
# ---------------------------------------------------------------------------


def test_c2_shutdown_hooks_run_in_reversed_order():
    """``main.py:798`` fuehrt ``reversed(list(_SHUTDOWN_HOOKS))`` aus.

    ``on_shutdown_graceful`` ist das LETZTE Element der Registrierung und muss
    dadurch in ``reversed()` ZUERST laufen (Drain/Checkpoint vor Cancel).
    """
    hooks = list(app_main._SHUTDOWN_HOOKS)
    rev = list(reversed(hooks))
    assert len(hooks) == 8, f"Shutdown-Hooks: {len(hooks)} (Referenz = 8, inkl. M112-Anker-Stopp)"
    assert hooks[-1] is app_main.on_shutdown_graceful
    assert rev[0] is app_main.on_shutdown_graceful
    assert rev.index(app_main._close_all_http_clients) < rev.index(app_main._cancel_tracked_tasks)
    assert rev.index(app_main._close_all_http_clients) < rev.index(app_main._close_dispatcher_clients)

    # Negativprobe: die umgekehrte Behauptung muss rot werden.
    with pytest.raises(AssertionError):
        assert rev[-1] is app_main.on_shutdown_graceful


# ---------------------------------------------------------------------------
# ③ n8n-Startup-Hook -> /readyz-Degradation
# ---------------------------------------------------------------------------


def test_c3_n8n_startup_status_degrades_readyz():
    """KORREKTUR zur Kartierung: die Verdrahtung EXISTIERT (``main.py:1396-1397``),
    sie war nur ungetestet (0 Treffer in ``tests/``). ``status == "error"``
    erzeugt ``n8n_startup_import: …`` in den /readyz-Problems -> 503.
    """
    assert app_main._N8N_STARTUP_STATUS["status"] == "not_configured"
    assert app_main._import_n8n_workflows_on_startup in app_main._STARTUP_HOOKS

    original = dict(app_main._N8N_STARTUP_STATUS)
    try:
        app_main._N8N_STARTUP_STATUS.update(status="error", detail="NEGATIVPROBE")
        _assert_problems(_readyz(), "n8n_startup_import")
        assert any("NEGATIVPROBE" in str(p) for p in json.loads(bytes(_readyz().body))["problems"])
    finally:
        app_main._N8N_STARTUP_STATUS.clear()
        app_main._N8N_STARTUP_STATUS.update(original)

    # Negativprobe: Default-Zustand darf keinen n8n-Fehler melden.
    clean = _readyz()
    assert not isinstance(clean, app_main.JSONResponse), str(bytes(clean.body)[:600])
    with pytest.raises(AssertionError):
        _assert_problems(clean, "n8n_startup_import")


# ---------------------------------------------------------------------------
# ④ Router-Reihenfolge + _rbac.configure() (Verhaltensassertion, kein S-Test)
# ---------------------------------------------------------------------------


def test_c4_router_registration_and_rbac_wiring():
    """Pfade 801 = Referenz 799 + W4-C Liability-Ack + W4-D Task-Endpunkt;
    F2-RBAC vor den Routern konfiguriert; ``_assert_router_health`` fail-closed
    inkl. dokumentiertem Opt-Out.
    """
    assert rbac_guards.is_configured(), "F2-Wiring (rbac_guards.configure) verloren"
    assert not app_main._ROUTER_LOAD_ERRORS
    # Die ~50 Duplicate-Operation-ID-Warnings sind vorbestehend und fuer diesen
    # Contract irrelevant -> nur hier einhegen, nirgends unterdruecken.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        paths = sorted(app_main.app.openapi()["paths"])
    assert len(paths) == 840, f"Pfade: {len(paths)} (Referenz 801 + M67/M68/M69/M70/M74/M112 = 840)"

    # Fail-closed Negativprobe: absichtlich defekter Router MUSS raisen.
    app_main._ROUTER_LOAD_ERRORS.append("NEGATIVPROBE: broken router")
    try:
        with pytest.raises(RuntimeError):
            app_main._assert_router_health()
    finally:
        app_main._ROUTER_LOAD_ERRORS.clear()

    # Opt-Out-Pfad darf NICHT raisen (Negativprobe gegen den Fail-Closed-Pfad).
    with patch.dict("os.environ", {"ARCHON_ALLOW_BROKEN_ROUTERS": "true"}):
        app_main._ROUTER_LOAD_ERRORS.append("NEGATIVPROBE: broken router")
        try:
            app_main._assert_router_health()
        finally:
            app_main._ROUTER_LOAD_ERRORS.clear()


# ---------------------------------------------------------------------------
# ⑤ HealingAttemptPayload / request.state.hitl_apply_patch
# ---------------------------------------------------------------------------


def test_c5_healing_payload_ignores_apply_patch_and_hitl_flag_is_authoritative():
    """``extra="ignore"`` verwirft einen Client-``apply_patch`` still; das Flag
    kommt AUSSCHLIESSLICH aus ``request.state.hitl_apply_patch`` (fail-closed).
    """
    # model_validate statt Kwarg: ``extra="ignore"`` ist ein Laufzeit-Verhalten,
    # das mypy statisch nicht kennt. Der Client-Smuggle wird so trotzdem echt
    # gegen die Pydantic-Logik geprueft.
    p = app_main.HealingAttemptPayload.model_validate({"task_id": "x", "apply_patch": True})
    dumped = p.model_dump()
    assert "apply_patch" not in dumped, "Client darf apply_patch nicht ueber den Body erzwingen"
    assert dumped["task_id"] == "x"

    async def _call(state_value: object) -> bool:
        state = SimpleNamespace() if state_value is None else SimpleNamespace(hitl_apply_patch=state_value)
        req = SimpleNamespace(state=state)
        healer = AsyncMock(return_value={"status": "ok"})
        with patch.object(app_main, "require_admin_or_503"), \
             patch("backend.task_self_healer.task_self_healer.attempt_self_healing", new=healer):
            await app_main.api_attempt_task_healing(
                cast(Any, req), app_main.HealingAttemptPayload(task_id="x")
            )
        assert healer.await_args is not None
        return bool(healer.await_args.kwargs["apply_patch"])

    assert asyncio.run(_call(None)) is False, "ohne HITL-Flag darf nie geschrieben werden"
    assert asyncio.run(_call(True)) is True

    # Negativprobe: wuerde das Flag ignoriert, waere der zweite Aufruf False.
    with pytest.raises(AssertionError):
        assert asyncio.run(_call(True)) is False

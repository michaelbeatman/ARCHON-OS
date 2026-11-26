"""Re-Audit Etappe 13 — verbleibende HIGHs D02/D04/D08/D10/D15."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_d04_rotation_register_exists_and_gate_is_green():
    import subprocess
    import sys
    reg = ROOT / "config" / "secrets_rotation.json"
    assert reg.is_file()
    data = json.loads(reg.read_text(encoding="utf-8"))
    classes = {c["class"] for c in data["credentials"]}
    assert {"github", "telegram", "provider"} <= classes
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_secrets.py"), "--all"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-500:] + proc.stderr[-500:]


def test_d15_roles_match_ssot_prompts():
    import scripts.sync_profile_ssot as sso
    report = sso.detect_drift(allow_missing_hermes=True)
    assert report["prompt_mismatch"] == []
    assert report["drift"] is False


def test_d15_inventory_has_71_entries():
    data = json.loads((ROOT / "data" / "eu_ai_act_inventory.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("items", data.get("inventory", []))
    ids = [e.get("agent_id") for e in entries if isinstance(e, dict)]
    assert len(ids) == 71
    assert "micha" not in ids and "alpha" not in ids


def test_d10_livez_fails_with_dead_watchdog(monkeypatch):
    import asyncio
    import io
    import time
    import urllib.error
    import urllib.request

    from fastapi.responses import JSONResponse

    import archon.services.health_probes as health_probes
    import backend.loop_liveness as loop_liveness
    import scripts.archon_autoheal as autoheal
    import watchdog_daemon

    async def _healthy_loop():
        return {"alive": True, "lag_ms": 1.0}

    monkeypatch.setattr(loop_liveness, "check_loop_liveness", _healthy_loop)

    # 1. Negativfall: Event-Loop gesund, aber Watchdog tot -> HTTP 503 + alive=False
    monkeypatch.setattr(
        watchdog_daemon,
        "watchdog_liveness",
        lambda: {"alive": False, "last_seen": 100.0, "age_s": 999.0},
    )
    dead_res = asyncio.run(health_probes.run_liveness_check())
    assert isinstance(dead_res, JSONResponse)
    assert dead_res.status_code == 503
    dead_body = json.loads(dead_res.body.decode("utf-8"))
    assert dead_body["loops"]["watchdog"]["alive"] is False

    # 2. Fail-Closed-Fall: watchdog_liveness wirft Exception -> HTTP 503 + alive=False
    def _broken_watchdog():
        raise RuntimeError("watchdog_file_unreadable")

    monkeypatch.setattr(watchdog_daemon, "watchdog_liveness", _broken_watchdog)
    err_res = asyncio.run(health_probes.run_liveness_check())
    assert isinstance(err_res, JSONResponse)
    assert err_res.status_code == 503
    err_body = json.loads(err_res.body.decode("utf-8"))
    assert err_body["loops"]["watchdog"]["alive"] is False

    # 3. Positivfall: Event-Loop und Watchdog gesund -> 200-Dict + alive=True
    now = time.time()
    monkeypatch.setattr(
        watchdog_daemon,
        "watchdog_liveness",
        lambda: {"alive": True, "last_seen": now, "age_s": 0.2},
    )
    ok_res = asyncio.run(health_probes.run_liveness_check())
    assert isinstance(ok_res, dict)
    assert ok_res["loops"]["watchdog"]["alive"] is True

    # 4. Autoheal-Konsument: liest den echten 503-Body aus HTTPError und meldet watchdog_stale
    def _urlopen_503(url, timeout=5):
        raise urllib.error.HTTPError(
            url, 503, "Service Unavailable", hdrs={}, fp=io.BytesIO(dead_res.body)
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_503)
    stale_probe = autoheal.probe()
    assert stale_probe["ok"] is False
    assert stale_probe["watchdog_stale"] is True

    # 5. Autoheal-Positivprobe: HTTP 200 mit lebendem Watchdog -> ok=True, watchdog_stale=False
    class _OkResp:
        status = 200

        def read(self, _n=-1):
            return json.dumps(ok_res).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=5: _OkResp())
    healthy_probe = autoheal.probe()
    assert healthy_probe["ok"] is True
    assert healthy_probe["watchdog_stale"] is False


def test_d08_audit_dispatch_is_async():
    guard = (ROOT / "backend" / "llm_egress_guard.py").read_text(encoding="utf-8")
    assert "async def audit_dispatch_async" in guard
    assert "await asyncio.to_thread(_write)" in guard
    # F2: der Bildgenerierungs-Handler (und damit der audit_dispatch_async-
    # Aufruf) liegt jetzt in backend/image_generate.py statt chat.py.
    for rel in ("backend/agent_router.py", "utils/notebook_engine.py", "backend/image_generate.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "await audit_dispatch_async(" in src, rel


def test_d02_cache_respects_policy(monkeypatch):
    """G7-Migration (D5-C3): echtes Verhalten fuer Policy-Scope, Privacy-Config und Cache-Hit-Gate."""
    import pytest

    import backend.compliance_engine as ce_mod
    import backend.llm_egress_guard as egress_mod
    import backend.privacy_router as pr_mod
    import core_dispatcher

    # 1. ARCHON_POLICY_VERSION trennt Cache-Scopes echt
    monkeypatch.setenv("ARCHON_POLICY_VERSION", "pol-v1")
    scope_v1 = core_dispatcher._dispatch_cache_scope("coder")
    monkeypatch.setenv("ARCHON_POLICY_VERSION", "pol-v2")
    scope_v2 = core_dispatcher._dispatch_cache_scope("coder")
    assert scope_v1 != scope_v2
    assert "pol-v1" in scope_v1 and "pol-v2" in scope_v2

    # 2. _cache_policy_context liest get_privacy_config() echt
    monkeypatch.setattr(pr_mod, "get_privacy_config", lambda: {"zero_egress_strict": True})
    _, zero_on = core_dispatcher._cache_policy_context("coder", prompt="Hallo")
    monkeypatch.setattr(pr_mod, "get_privacy_config", lambda: {"zero_egress_strict": False})
    _, zero_off = core_dispatcher._cache_policy_context("coder", prompt="Hallo")
    assert zero_on is True
    assert zero_off is False

    # 3. _validate_cache_hit_gate blockiert fail-closed bei Compliance-Ablehnung
    monkeypatch.setattr(
        ce_mod.compliance_engine,
        "check_activation_allowed",
        lambda *_a, **_kw: {"allowed": False, "error_code": "COMPLIANCE_BLOCKED", "reason": "test block"},
    )
    with pytest.raises(egress_mod.ZeroEgressBlockedError):
        core_dispatcher._validate_cache_hit_gate(
            agent_id="coder",
            provider="openrouter",
            model="deepseek/deepseek-chat",
            prompt="Hallo",
        )

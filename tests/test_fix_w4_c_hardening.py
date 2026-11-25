# -*- coding: utf-8 -*-
"""W4-C (F042 / F043) — Regressionstests fuer verdrahteten Schein + 24/7-Haertung.

WICHTIG: Diese Datei schreibt nie in die produktiven DBs unter ``./data``.
Vor allen Imports werden ``ARCHON_DATA_DIR`` und ``DATA_DIR`` (falls nicht
bereits gesetzt) auf temporaere Verzeichnisse gezeigt.
"""
import os
import sys
import json
import time
import types
import tempfile
import functools
import asyncio
from pathlib import Path

_TEST_DATA = tempfile.mkdtemp(prefix="archon_w4c_testdata_")
if not os.environ.get("ARCHON_DATA_DIR"):
    os.environ["ARCHON_DATA_DIR"] = _TEST_DATA
if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = _TEST_DATA

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _src(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _async_test(fn):
    """Coroutine-Test auch ohne pytest-asyncio ausfuehrbar machen."""
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return _wrapper


# ---------------------------------------------------------------------------
# H-01-1 — Map-Reduce: echter worker_fn, ehrlicher Status
# ---------------------------------------------------------------------------

@_async_test
async def test_map_reduce_real_worker_is_consumed_and_persisted():
    import backend.map_reduce_executor as mre

    mre.DB_PATH = os.path.join(_TEST_DATA, "map_reduce_test.db")
    mre._init_db()
    seen = []

    async def worker(index, item, instruction):
        seen.append((index, item))
        return f"ECHTE-ANALYSE:{item}"

    res = await mre.map_reduce_executor.execute_map_reduce(
        task_title="W4C-Test", items=["a", "b", "c"], instruction="Analysiere",
        worker_fn=worker,
    )
    assert len(seen) == 3
    assert res["simulated"] is False
    assert res["mode"] == "live_worker"
    assert res["status"] == "success"
    assert res["completed_items"] == 3
    assert all("ECHTE-ANALYSE" in c["output"] for c in res["chunks"])

    # Effekt: echter DB-Eintrag mit der echten Synthese
    history = mre.map_reduce_executor.get_history(limit=5)
    assert any(h["job_id"] == res["job_id"] and "ECHTE-ANALYSE" in h["reduced_summary"]
               for h in history)


@_async_test
async def test_map_reduce_failed_worker_is_not_reported_as_success():
    import backend.map_reduce_executor as mre

    mre.DB_PATH = os.path.join(_TEST_DATA, "map_reduce_fail.db")
    mre._init_db()

    async def failing(index, item, instruction):
        raise RuntimeError("dispatcher_blocked")

    res = await mre.map_reduce_executor.execute_map_reduce(
        task_title="Fail-Test", items=["x", "y"], worker_fn=failing,
    )
    assert res["status"] == "failed"
    assert res["failed_items"] == 2
    assert res["simulated"] is False


def test_map_reduce_endpoint_injects_dispatcher_worker():
    src = _src("archon/routers/execution.py")
    segment = src.split('@router.post("/api/execution/map-reduce")', 1)[1].split("@router.get", 1)[0]
    assert "make_dispatcher_worker_fn" in segment
    assert "worker_fn=worker_fn" in segment
    assert 'result["status"] = "simulation"' not in segment
    assert "demo: bool = False" in src


# ---------------------------------------------------------------------------
# H-01-2 — Speculative Hedging: echte Coroutines statt Demo-Platzhalter
# ---------------------------------------------------------------------------

@_async_test
async def test_hedger_uses_real_coroutines_and_verifies_winner():
    import backend.speculative_hedger as sh

    sh.DB_PATH = os.path.join(_TEST_DATA, "hedger_test.db")
    sh._init_db()
    calls = []

    async def primary():
        calls.append("primary")
        await asyncio.sleep(0.01)
        return "ECHTE-PRIMAER-ANTWORT"

    async def fallback():
        calls.append("fallback")
        await asyncio.sleep(0.30)
        return "ECHTE-FALLBACK-ANTWORT"

    res = await sh.speculative_hedger.execute_hedged_call(
        prompt="test", primary_coro_fn=primary, fallback_coro_fn=fallback,
        hedge_delay_override=0.0,
    )
    assert res["demo_only"] is False
    assert res["mode"] == "live_functions"
    assert res["status"] == "success"
    assert res["response"] == "ECHTE-PRIMAER-ANTWORT"
    assert res["winning_source"] == "primary"
    assert "primary" in calls  # Gewinner stammt aus der echten Coroutine


@_async_test
async def test_hedger_demo_remains_honestly_labeled():
    import backend.speculative_hedger as sh

    sh.DB_PATH = os.path.join(_TEST_DATA, "hedger_demo.db")
    sh._init_db()
    res = await sh.speculative_hedger.execute_hedged_call(
        prompt="test", simulate_fallback_latency_sec=0.0,
    )
    assert res["demo_only"] is True
    assert "Primary:" in res["response"]


def test_hedged_completion_endpoint_injects_coroutines():
    src = _src("archon/routers/routergate.py")
    segment = src.split('@router.post("/api/router/hedged-completion")', 1)[1].split("@router.get", 1)[0]
    assert "make_dispatcher_coro" in segment
    assert "primary_coro_fn=primary_coro_fn" in segment
    assert "fallback_coro_fn=fallback_coro_fn" in segment
    assert 'result["demo_only"] = True' not in segment
    assert "demo: bool = False" in src


# ---------------------------------------------------------------------------
# H-01-3 — Plugin-Hooks: SSOT, Manifest-Wahrheit, echter cost_guard-Effekt
# ---------------------------------------------------------------------------

def test_unwired_hooks_are_removed_from_manifests_and_api():
    from backend.plugin_manager import WIRED_HOOKS

    for unwired in ("on_startup", "on_shutdown", "on_message_received"):
        assert unwired not in WIRED_HOOKS
    assert "on_task_completed" in WIRED_HOOKS

    for rel in (
        "plugins/cost_guard/plugin.json",
        "plugins/system_metrics/plugin.json",
        "plugins/security_audit_hook/plugin.json",
    ):
        manifest = json.loads(_src(rel))
        assert set(manifest["hooks"]) <= set(WIRED_HOOKS), rel

    pm_src = _src("backend/plugin_manager.py")
    assert '"hooks": [h for h in self.declared_hooks if h in WIRED_HOOKS]' in pm_src
    assert "def trigger_filter_hook" not in pm_src


@_async_test
async def test_trigger_hook_refuses_unwired_hook():
    from backend.plugin_manager import PluginManager

    pm = PluginManager(
        plugins_dir=os.path.join(_TEST_DATA, "empty_plugins"),
        state_file=os.path.join(_TEST_DATA, "pm_state.json"),
    )
    assert await pm.trigger_hook("on_startup") == []


@_async_test
async def test_cost_guard_counter_writes_on_real_tool_completion():
    from backend.plugin_manager import PluginManager

    pm = PluginManager(
        plugins_dir=os.path.join(_TEST_DATA, "empty_plugins"),
        state_file=os.path.join(_TEST_DATA, "pm_state_cost.json"),
    )
    plugin = pm.load_plugin_from_dir(str(ROOT / "plugins" / "cost_guard"))
    assert plugin is not None

    burn = os.path.join(_TEST_DATA, "daily_burn.json")
    plugin.state_file = burn
    plugin.burn_data = {"date": plugin.burn_data["date"], "spent_usd": 0.0, "total_tokens": 0}

    # Kein Verbrauch -> kein Hook, kein Schreibzugriff.
    await pm.apply_after_tool_execute("read_file", {"status": "ok"}, {"agent_id": "a"})
    assert not os.path.exists(burn)

    # Echter Verbrauch im Tool-Ergebnis -> on_task_completed -> daily_burn.json
    await pm.apply_after_tool_execute(
        "llm_call",
        {"status": "success", "usage": {"total_tokens": 42, "cost_usd": 0.125}},
        {"agent_id": "a"},
    )
    assert os.path.exists(burn)
    data = json.loads(Path(burn).read_text(encoding="utf-8"))
    assert data["total_tokens"] == 42
    assert data["spent_usd"] == 0.125


# ---------------------------------------------------------------------------
# MED — no-op JS-Handler + Scheinerfolg entfernt
# ---------------------------------------------------------------------------

def test_js_noop_handlers_and_fake_pin_are_removed():
    agents = _src("static/js/agent_profiles.js")
    market = _src("static/js/skill_markt.js")
    for forbidden in (
        "function togglePinAgentToCurrentTask",
        "is_pinned_to_task",
        "function closeSoulModal",
        "function closePersonalakteModal",
        "function switchPersonalakteTab",
        "function closeAgentDirectChatModal",
    ):
        assert forbidden not in agents, forbidden
    assert "function closePresetModal" not in market
    assert "function closeCreateAgentModal" not in market
    assert "closeCreateAgentModal();" not in market


# ---------------------------------------------------------------------------
# H-10-1 — /readyz konfigurierbar, Default nur OmniRoute
# ---------------------------------------------------------------------------

def test_readyz_probe_targets_are_configurable(monkeypatch):
    import main as app_main

    monkeypatch.delenv("ARCHON_READINESS_PROBE_URLS", raising=False)
    monkeypatch.delenv("OMNIROUTE_URL", raising=False)
    assert app_main._readiness_probe_targets() == [
        ("omniroute", "http://omniroute:20128/v1/models")
    ]

    monkeypatch.setenv("OMNIROUTE_URL", "http://custom-or:9000/v1")
    assert app_main._readiness_probe_targets() == [
        ("omniroute", "http://custom-or:9000/v1/models")
    ]

    monkeypatch.setenv(
        "ARCHON_READINESS_PROBE_URLS",
        "omniroute=http://or:1/models,n8n=http://n8n:5678/healthz",
    )
    assert app_main._readiness_probe_targets() == [
        ("omniroute", "http://or:1/models"),
        ("n8n", "http://n8n:5678/healthz"),
    ]

    monkeypatch.setenv("ARCHON_READINESS_PROBE_URLS", "")
    assert app_main._readiness_probe_targets() == []


def test_readyz_has_no_hardcoded_n8n_probe():
    src = _src("main.py")
    readyz = src.split('@app.get("/readyz")', 1)[1].split('@app.get("/health")', 1)[0]
    assert "n8n:5678/healthz" not in readyz
    assert "_readiness_probe_targets()" in readyz


def test_starters_and_ansible_force_compose_file():
    for rel in ("setup.ps1", "stop.bat", "install.sh", "start.bat"):
        src = _src(rel)
        assert "docker compose -f docker-compose.yml" in src

    ansible = _src("ansible/roles/archon_node/tasks/main.yml")
    vars_src = _src("ansible/roles/archon_node/vars/main.yml")
    assert "ARCHON_READINESS_PROBE_URLS" in ansible
    assert "archon_readiness_probe_urls" in vars_src
    assert "archon-chaos-resilience-test" in ansible


# ---------------------------------------------------------------------------
# MED D10 — Chaos-Suite: SLA + echte Schreibtransaktionen
# ---------------------------------------------------------------------------

def test_chaos_restart_sla_is_enforced():
    sys.path.insert(0, str(ROOT / "scripts"))
    import chaos_tester as ct

    assert ct.RESTART_SLA_S == 15.0

    class FakeClient:
        def __init__(self):
            self.restarted = 0

        def restart_container(self, name):
            self.restarted += 1
            # Echte, messbare Verzoegerung statt time.time() zu patchen.
            time.sleep(0.02)

        def container_json(self, name):
            return json.dumps({"State": {"Status": "running"}}).encode("utf-8")

    fake = FakeClient()
    monkeypatch = pytest.MonkeyPatch()
    try:
        fake_mod = types.ModuleType("utils.docker_client")
        fake_mod.DockerAdminClient = lambda: fake
        monkeypatch.setitem(sys.modules, "utils.docker_client", fake_mod)
        # SLA auf 1 ms senken: der 20-ms-Restart muss als Verletzung gelten.
        monkeypatch.setattr(ct, "RESTART_SLA_S", 0.001)
        tester = ct.ArchonChaosTester(dry_run=False)
        res = tester.test_simulated_container_restart("test-proxy")
        assert res["status"] == "failed"
        assert res["sla_violation"] is True
        assert res["restart_sla_s"] == 0.001
        assert fake.restarted == 1
    finally:
        monkeypatch.undo()


def test_chaos_db_concurrency_uses_real_immediate_writes():
    sys.path.insert(0, str(ROOT / "scripts"))
    import chaos_tester as ct

    tester = ct.ArchonChaosTester(dry_run=True)
    res = tester.test_database_concurrency(num_threads=2, ops_per_thread=6)
    assert res["status"] == "passed", res
    assert res["journal_mode"] == "wal"
    assert res["successful_commits"] == 12
    assert res["row_count"] == 12
    assert res["integrity_check"] == "ok"


def test_heartbeat_comment_drift_is_fixed():
    src = _src("backend/fleet_self_healing.py")
    assert "ARCHON_HEARTBEAT_ALERTMANAGER_URL" not in src
    assert "archon_heartbeat_timestamp_seconds" in src
    assert "ARCHON_HEARTBEAT_WEBHOOK_URL" in src

"""Regressionstests fuer die P0-Befunde des Archon-Reviews (2026-11-22).

Jeder Test deckt genau einen der kritischen, im Code belegten Fehler ab.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------- P0-1
def test_p01_dispatch_to_external_agent_has_task_id():
    """Der Container-Erfolgspfad darf nicht mehr an einem NameError scheitern."""
    import core_dispatcher

    sig = inspect.signature(core_dispatcher.dispatch_to_external_agent)
    assert "task_id" in sig.parameters


async def test_p01_hermes_success_path_does_not_raise():
    import core_dispatcher

    with patch.object(
        core_dispatcher,
        "dispatch_to_hermes",
        new=AsyncMock(return_value={"status": "success", "content": "ok"}),
    ), patch.object(
        core_dispatcher,
        "_clean_dispatch_output",
        side_effect=lambda text, **_kw: text,
    ):
        res = await core_dispatcher.dispatch_to_external_agent(
            "hermes", "Hermes", "prompt", task_id="t-1"
        )
    assert res["status"] == "success"
    assert res["content"] == "ok"


# ---------------------------------------------------------------- P0-8
def test_p08_cost_estimation_is_model_specific():
    from backend.llm_kernel import estimate_model_cost_usd

    cheap = estimate_model_cost_usd("deepseek/deepseek-chat", 1_000_000, 1_000_000)
    expensive = estimate_model_cost_usd("anthropic/claude-3-opus", 1_000_000, 1_000_000)
    assert expensive > cheap * 10, (cheap, expensive)


def test_p08_no_hardcoded_flat_rate_in_usage_log(tmp_path):
    """G7-Migration (D5-C3): modellabhaengige Kostenberechnung im echten Usage-Log."""
    import sqlite3
    import backend.db_paths as dbp_mod
    import backend.execution_receipt_ledger as erl_mod
    import core_dispatcher as cd

    combined = (
        (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
        + "\n"
        + (REPO_ROOT / "archon" / "core" / "dispatch_budget_cache.py").read_text(encoding="utf-8")
    )
    assert "estimate_model_cost_usd(model, in_tok, out_tok)" in combined
    assert "estimated_cost_eur=est_cost_eur" in combined
    assert "estimated_cost_eur=0.0" not in combined

    db_file = str(tmp_path / "p08_state.db")
    with sqlite3.connect(db_file) as con:
        con.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, display_name TEXT, title TEXT, "
            "model TEXT, profile_name TEXT, started_at REAL, message_count INT, input_tokens INT, "
            "output_tokens INT, estimated_cost_usd REAL, actual_cost_usd REAL)"
        )
        con.execute(
            "CREATE TABLE session_model_usage (session_id TEXT, model TEXT, billing_provider TEXT, "
            "billing_base_url TEXT, billing_mode TEXT, task TEXT, api_call_count INT, input_tokens INT, "
            "output_tokens INT, cache_read_tokens INT, cache_write_tokens INT, reasoning_tokens INT, "
            "estimated_cost_usd REAL, actual_cost_usd REAL, first_seen REAL, last_seen REAL, "
            "PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task))"
        )
        con.commit()
    with patch.object(dbp_mod, "resolve_db", return_value=db_file), patch.object(
        erl_mod.execution_receipt_ledger, "issue_receipt", return_value={}
    ):
        cd._log_dispatcher_usage_sync("coder", "anthropic/claude-3-opus", 1_000_000, 1_000_000, "t-opus")
    with sqlite3.connect(db_file) as con:
        cost = con.execute(
            "SELECT estimated_cost_usd FROM sessions WHERE id = 'task_t-opus'"
        ).fetchone()[0]
    assert cost > 10.0, f"Erwartete Opus-Tarif > 10 USD statt Einheitstarif, erhalten: {cost}"


# ---------------------------------------------------------------- P0-9
def test_p09_budget_is_enforced_when_spend_is_unverified():
    """spend_ok=False darf den Budget-Check nicht mehr ueberspringen."""
    from backend.agent_router import AgentRouter, BudgetExceededError

    router = AgentRouter()
    policy = {
        "daily_budget": 2.0,
        "current_spend": 3.0,
        "spend_ok": False,
        "max_context_tokens": 32000,
    }
    with patch.object(router, "_get_guardian_policy", return_value=policy), patch.object(
        router, "_budget_override", return_value=False
    ), patch.object(
        router, "check_loop_or_circuit_breaker", return_value={"tripped": False}
    ):
        with pytest.raises(BudgetExceededError):
            router._enforce_token_guard(
                [{"role": "user", "content": "hi"}], "local", "llama", "medium"
            )


# ---------------------------------------------------------------- P0-7
def test_p07_outbox_retries_delivery_failed_and_reconciles(tmp_path):
    from backend.event_mesh import EventMesh

    db = tmp_path / "mesh.db"
    mesh = EventMesh(db_path=str(db))

    with patch("utils.safe_http.safe_http_request", side_effect=RuntimeError("offline")):
        first = mesh.emit_outbound_event("http://webhook.invalid/hook", "test.event", {"x": 1})
    assert first["status"] != "delivered"

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM event_mesh_outbox LIMIT 1"
        ).fetchone()
        assert row[0] == "delivery_failed"
        # Backoff kuenstlich ablaufen lassen (sonst erst in 4 s faellig).
        conn.execute("UPDATE event_mesh_outbox SET next_try_at = 0")
        conn.commit()

    with patch("utils.safe_http.safe_http_request", return_value=(200, {}, b'{"ok":true}')):
        mesh.process_outbox()

    with sqlite3.connect(db) as conn:
        outbox_status = conn.execute("SELECT status FROM event_mesh_outbox LIMIT 1").fetchone()[0]
        ledger_state = conn.execute("SELECT state FROM effect_ledger LIMIT 1").fetchone()[0]
    assert outbox_status == "delivered"
    assert ledger_state == "COMMITTED"


# ---------------------------------------------------------------- P0-4
def test_p04_egress_guard_calls_use_valid_keywords():
    for rel in ("archon/routers/chat.py", "archon/routers/container_ops.py", "backend/voice_pipeline.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "enforce_egress_firewall_for_url(eff_url, data_category=" not in src
        assert "enforce_egress_firewall_for_url(url, data_category=" not in src
        assert "enforce_egress_firewall_for_url(groq_url, data_category=" not in src
    voice = (REPO_ROOT / "backend/voice_pipeline.py").read_text(encoding="utf-8")
    # Der Aufruf der nicht existierenden Funktion ist entfernt; die
    # Zero-Egress-Pruefung laeuft jetzt ueber get_privacy_config().
    assert "is_zero_egress_active()" not in voice
    assert "get_privacy_config()" in voice


def test_p04_pii_scrubbing_receives_dict_with_messages():
    from backend.llm_egress_guard import sanitize_outbound_llm_payload

    payload = {"messages": [{"role": "user", "content": "geheim"}]}
    out = sanitize_outbound_llm_payload(payload, agent_id="test")
    assert isinstance(out, dict)
    assert isinstance(out.get("messages"), list)


# ---------------------------------------------------------------- P0-2
def test_p02_no_hardcoded_admin_password():
    src = (REPO_ROOT / "backend/auth_service.py").read_text(encoding="utf-8")
    assert '"archon2026"' not in src


# ---------------------------------------------------------------- P0-3
def test_p03_approver_comes_from_session_not_request_body():
    from archon.routers import operations_approvals as mod

    request = MagicMock()
    # Der Body mit 'approver_id' wurde bewusst entfernt (Body-Actor-Bypass).

    with patch.object(mod, "require_admin_or_503"), patch.object(
        mod, "require_session_actor", return_value="alice"
    ), patch(
        "backend.approval_policy_engine.approval_engine.approve_request",
        return_value={"ok": True},
    ) as engine:
        mod.api_approve_request(request, "req-1")

    engine.assert_called_once()
    assert engine.call_args.kwargs["approver_id"] == "alice"


# ---------------------------------------------------------------- P0-5
async def test_p05_self_healer_does_not_claim_repair_without_patch(tmp_path):
    import core_dispatcher
    from backend.task_self_healer import TaskSelfHealer

    healer = TaskSelfHealer(db_path=str(tmp_path / "heal.db"))
    good_answer = {"status": "success", "content": "```python\nx = 1\n```"}

    with patch.object(
        core_dispatcher,
        "dispatch_to_omniroute_or_container",
        new=AsyncMock(return_value=good_answer),
    ):
        res = await healer.attempt_self_healing(
            "task-1", "Test", "x =", "SyntaxError", attempt=1
        )

    assert res["status"] == "proposed"
    assert res["patch_applied"] is False
    assert "Human Review" in res["next_action"]


async def test_p05_self_healer_writes_patch_only_with_optin(tmp_path):
    import core_dispatcher
    from backend.task_self_healer import TaskSelfHealer, validate_affected_file

    target = tmp_path / "broken.py"
    target.write_text("x = (\n", encoding="utf-8")
    healer = TaskSelfHealer(db_path=str(tmp_path / "heal.db"))
    good_answer = {"status": "success", "content": "```python\nx = 1\n```"}

    with patch.object(
        core_dispatcher,
        "dispatch_to_omniroute_or_container",
        new=AsyncMock(return_value=good_answer),
    ), patch(
        "backend.task_self_healer.WORKSPACE_DIR", str(tmp_path)
    ), patch(
        "backend.task_self_healer.validate_affected_file", return_value="broken.py"
    ):
        res = await healer.attempt_self_healing(
            "task-2", "Test", "x = (", "SyntaxError", attempt=1,
            affected_file="broken.py", apply_patch=True,
        )

    assert res["status"] == "repaired"
    assert res["patch_applied"] is True
    assert target.read_text(encoding="utf-8").strip() == "x = 1"
    assert (tmp_path / "broken.py.archon_heal_backup").exists()


# ---------------------------------------------------------------- P0-10
def test_p010_spawner_is_async_and_status_comes_from_dag():
    src = (REPO_ROOT / "backend/ephemeral_team_spawner.py").read_text(encoding="utf-8")
    assert "async def spawn_task_force" in src
    assert "asyncio.run(run_workflow_dag" not in src
    assert 'dag_run.get("status"' in src


# ---------------------------------------------------------------- P0-6
def test_p06_lease_migrates_missing_columns_and_claims(tmp_path):
    """Lease muss auch auf einer alten tasks-Tabelle ohne Claim-Spalten greifen."""
    from backend.deadlock_supervisor import DeadlockSupervisor

    db = tmp_path / "kanban.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, created_at INTEGER)")
        conn.execute("INSERT INTO tasks VALUES ('t1', 'in_progress', 0)")
        conn.commit()

    supervisor = DeadlockSupervisor(db_path=str(db))
    first = supervisor.acquire_lease("t1", ttl_seconds=300)
    second = supervisor.acquire_lease("t1", ttl_seconds=300)

    assert first["acquired"] is True
    assert second["acquired"] is False  # kein doppelter Claim

    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    assert {"claim_lock", "claim_expires", "worker_pid", "last_heartbeat_at"} <= cols


async def test_p06_orchestration_wires_lease_and_idempotency():
    """Der produktive Mission-Control-Pfad muss Claim + Guard tatsächlich nutzen."""
    from archon.core import orchestration

    task = {
        "id": "t-99", "title": "Test", "capture_input": "do it",
        "agent_id": "a", "status": "in_progress",
    }
    data = {"tasks": [task]}

    supervisor = MagicMock()
    supervisor.acquire_lease.return_value = {"acquired": True, "lease_token": "tok-1"}
    supervisor.heartbeat.return_value = True
    supervisor.release_lease.return_value = True

    guard = MagicMock()
    guard.check_or_register.return_value = {
        "allowed": True, "blocked": False, "idempotency_key": "idem-1",
    }
    guard.record_execution_result.return_value = True
    guard.invalidate_key.return_value = True

    dispatcher = MagicMock()
    dispatcher.dispatch_to_omniroute_or_container = AsyncMock(
        return_value={"status": "success", "content": "done"}
    )

    with patch("backend.deadlock_supervisor.deadlock_supervisor", supervisor), patch(
        "backend.idempotency_guard.idempotency_guard", guard
    ):
        await orchestration._execute_mission_control_task(
            "t-99",
            dispatcher=dispatcher,
            load_mc=lambda: data,
            save_mc=lambda _d: None,
            update_mc=lambda fn: fn(data),
            ticker=lambda *_a: None,
            get_profiles=lambda: [],
            sync_obsidian=lambda _t: "note.md",
            trigger_sandy=AsyncMock(),
            fan_in=AsyncMock(),
        )

    supervisor.acquire_lease.assert_called_once()
    supervisor.release_lease.assert_called_once()
    guard.check_or_register.assert_called_once()
    guard.record_execution_result.assert_called_once()
    guard.invalidate_key.assert_not_called()

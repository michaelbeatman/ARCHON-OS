# -*- coding: utf-8 -*-
"""W4-B — Rollen- & Prompt-SSOT im Dispatch (D15-H1, D15-H7, D08-M8).

Alle Tests sind offline und deterministisch. Sie prüfen den KONSUMENTEN im
Produktivpfad (Kanban-Worker / zentraler Dispatch-Kontext / Dispatcher-Gate /
Budget-Engine), nicht nur die Existenz der SOUL-Artefakte (§0 Soll-Spec).
Es werden keine echten LLM-, SQLite- oder Netzwerkpfade ausgeführt.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Gemeinsame, isolierte Fixtures
# ---------------------------------------------------------------------------


def _soul_pin(agent_id: str) -> str:
    """Pin aus der realen kanonischen SOUL.md (identische Normalisierung)."""
    path = ROOT / "souls" / agent_id / "SOUL.md"
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _install_inventory(monkeypatch: pytest.MonkeyPatch, agent_id: str, pin: str) -> None:
    import backend.eu_ai_act_inventory as inv_mod

    items = [{
        "agent_id": agent_id,
        "risk_tier": "HIGH_RISK",
        "compliance_status": "COMPLIANT",
        "soul_sha256": pin,
    }]
    monkeypatch.setattr(
        inv_mod.eu_ai_act_inventory_manager,
        "get_inventory",
        lambda refresh=False: list(items),
    )


def _install_context_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vier bekannte Kontextquellen des Dispatchers ohne echte I/O."""
    import backend.bandit_model_router as bmr
    import backend.core_memory_manager as cmm
    import backend.prompt_registry as pr
    import backend.speculative_prefetcher as sp

    class _Prefetcher:
        def prefetch_for_task(self, prompt, agent_id=None):
            return {"cached_items": {}}

    class _Registry:
        def get_effective_prompt(self, agent_id, task_id):
            return {"prompt": "BASIS", "version_num": 1, "is_canary": False}

    class _Memory:
        def compile_system_prompt_injection(self, agent_id):
            return ""

    class _Bandit:
        def select_best_model(self):
            return {"enabled": False, "selected_model": ""}

    monkeypatch.setattr(sp, "get_speculative_prefetcher", lambda: _Prefetcher())
    monkeypatch.setattr(pr, "prompt_registry", _Registry())
    monkeypatch.setattr(cmm, "core_memory_manager", _Memory())
    monkeypatch.setattr(bmr, "bandit_model_router", _Bandit())


def _install_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    agent_id: str = "legal_counsel",
    soul_mode: str = "compact",
) -> tuple:
    """Minimaler, aber echter Worker-Durchlauf bis zum Dispatch-Chokepoint."""
    import backend.model_routing as model_routing
    import backend.operations_execution as ops_exec
    import core_dispatcher as dispatcher

    dispatched: list = []
    persisted: list = []

    deps = ops_exec.ExecutionDeps(
        get_active_kanban_db_path=lambda: str(tmp_path / "kanban.db"),
        get_kanban_connection=lambda *a, **k: None,
        load_kanban_delegation_payload=lambda *a, **k: {},
        sync_to_memory_bridge=lambda *a, **k: None,
        load_profiles_map=lambda: {
            agent_id: {
                "id": agent_id,
                "name": "Test Agent",
                "prompt": "BASE_PROMPT",
                "model": "test/model",
                "soul_mode": soul_mode,
            }
        },
        resolve_task_obsidian_rel=lambda _tid: "",
        load_kanban_meta=lambda: {},
    )
    deps_fallback = deps

    def _resolve(deps: Any = None) -> Any:
        return deps if deps is not None else deps_fallback

    monkeypatch.setattr(ops_exec, "_resolve_deps", _resolve)

    task = {
        "id": "t-w4b",
        "title": "Testauftrag",
        "body": "Body",
        "assignee": agent_id,
        "status": "todo",
        "model_override": "",
        "provider_override": "",
        "token_budget": 0,
        "proof_command": "",
        "consecutive_failures": 0,
    }
    monkeypatch.setattr(ops_exec, "_kanban_load_task_sync", lambda _tid: dict(task))
    monkeypatch.setattr(ops_exec, "_kanban_mark_started_sync", lambda *a, **k: None)
    monkeypatch.setattr(
        ops_exec, "require_accepted_handoff", lambda *a, **k: {"allowed": True}
    )
    monkeypatch.setattr(model_routing, "autonomy_level", lambda _domain: "autonomous")
    monkeypatch.setattr(model_routing, "is_enabled", lambda: False)

    class _Token:
        def check(self) -> None:
            return None

        def register_task(self, _task: Any) -> None:
            return None

        def cancel(self, _reason: str = "") -> None:
            return None

    monkeypatch.setattr("backend.cancellation.get_token", lambda _key: _Token())

    async def _fake_dispatch(**kwargs: Any) -> Dict[str, Any]:
        dispatched.append(kwargs)
        return {"status": "success", "content": "OK", "total_tokens": 10}

    async def _cross_ok(**_kwargs: Any) -> Dict[str, Any]:
        return {"passed": True}

    def _persist(*args: Any, **kwargs: Any) -> None:
        persisted.append((args, kwargs))

    monkeypatch.setattr(dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch)
    monkeypatch.setattr(ops_exec, "_persist_kanban_result_sync", _persist)
    monkeypatch.setattr(ops_exec, "_merge_task_meta_facts", lambda *a, **k: None)
    monkeypatch.setattr(ops_exec, "_cross_model_verify_task_result", _cross_ok)
    monkeypatch.setattr(
        "backend.kanban_verifier.verify_card_completion",
        lambda *a, **k: {"status": "done"},
    )
    monkeypatch.setattr(ops_exec, "get_provider", lambda _name: None)
    monkeypatch.setattr("backend.trajectory_budget._audit", lambda *a, **k: None)
    return dispatched, persisted, ops_exec


# ---------------------------------------------------------------------------
# D15-H1 — 3-Tier-SOUL im echten Worker-System-Prompt konsumieren
# ---------------------------------------------------------------------------


def test_d15_h1_high_risk_compact_profile_gets_full_tier_in_worker_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = "legal_counsel"  # HIGH_RISK, Profil deklariert soul_mode=compact
    _install_inventory(monkeypatch, agent, _soul_pin(agent))
    dispatched, persisted, ops_exec = _install_worker(
        monkeypatch, tmp_path, agent_id=agent, soul_mode="compact"
    )

    asyncio.run(ops_exec._execute_kanban_task_inner("t-w4b", lease_token=""))

    assert dispatched, "der Worker hat keinen Dispatch erreicht"
    system_prompt = str(dispatched[0]["system_prompt"])
    assert "BASE_PROMPT" in system_prompt
    # Produzent + Speicherwaren bisher vorhanden; jetzt gibt es einen Konsumenten.
    assert "[AKTIVER_SOUL_TIER: FULL]" in system_prompt
    assert "SOUL-DIREKTIVE (FULL-EXPERT)" in system_prompt
    # Duplex-Schutz: genau ein SOUL-Block im System-Prompt.
    assert system_prompt.count("[AKTIVER_SOUL_TIER:") == 1


def test_d15_h1_soul_pin_drift_blocks_worker_before_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = "legal_counsel"
    _install_inventory(monkeypatch, agent, "0" * 64)  # manipulierter Pin
    dispatched, persisted, ops_exec = _install_worker(
        monkeypatch, tmp_path, agent_id=agent, soul_mode="compact"
    )

    result = asyncio.run(ops_exec._execute_kanban_task_inner("t-w4b", lease_token=""))

    assert dispatched == [], "bei Pin-Drift darf kein Dispatch stattfinden"
    assert result and result.get("blocked") == "SOUL_PIN_DRIFT"
    assert result.get("error_code") == "SOUL_SHA256_MISMATCH"
    assert persisted, "der Block muss im Kanban-Ergebnis sichtbar sein"
    verdict = persisted[-1][1].get("verdict") or {}
    assert verdict.get("block_kind") == "SOUL_PIN_DRIFT"
    assert verdict.get("error_code") == "SOUL_SHA256_MISMATCH"


# ---------------------------------------------------------------------------
# D08-M8 — Tier im zentralen Dispatch-Kontext, Duplex-Schutz, max_chars
# ---------------------------------------------------------------------------


def test_d08_m8_dispatch_context_consumes_resolved_tier_exactly_once(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import core_dispatcher as dispatcher

    agent = "legal_counsel"
    _install_inventory(monkeypatch, agent, _soul_pin(agent))
    _install_context_stubs(monkeypatch)

    ctx = dispatcher._build_dispatch_context_sync("", agent, "t-m8", "SYS", "")
    info = ctx["soul_tier_info"]

    assert info["pin_ok"] is True
    assert info["tier"] == "full"  # HIGH_RISK schlägt soul_mode=compact
    assert info["injected"] is True
    assert ctx["system_prompt"].count("[AKTIVER_SOUL_TIER:") == 1
    assert "SOUL-DIREKTIVE (FULL-EXPERT)" in ctx["system_prompt"]


def test_d08_m8_tier_dependent_chars_and_no_double_injection(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import archon.core.delegation as delegation
    import core_dispatcher as dispatcher

    agent = "legal_counsel"
    _install_inventory(monkeypatch, agent, _soul_pin(agent))
    _install_context_stubs(monkeypatch)

    monkeypatch.setattr(
        delegation, "resolve_effective_soul_mode", lambda _aid, _mode="": "compact"
    )
    compact_ctx = dispatcher._build_dispatch_context_sync("", agent, "t-c", "SYS", "")

    monkeypatch.setattr(
        delegation, "resolve_effective_soul_mode", lambda _aid, _mode="": "full"
    )
    full_ctx = dispatcher._build_dispatch_context_sync("", agent, "t-f", "SYS", "")

    assert compact_ctx["soul_tier_info"]["tier"] == "compact"
    assert full_ctx["soul_tier_info"]["tier"] == "full"
    assert full_ctx["soul_tier_info"]["chars"] > compact_ctx["soul_tier_info"]["chars"]

    already = full_ctx["system_prompt"]
    double_ctx = dispatcher._build_dispatch_context_sync(
        "", agent, "t-d", f"VORBLOCK\n\n{already}", ""
    )
    assert double_ctx["soul_tier_info"]["injected"] is False
    assert double_ctx["system_prompt"].count(
        "AKTIVER_SOUL_TIER"
    ) == already.count("AKTIVER_SOUL_TIER")


# ---------------------------------------------------------------------------
# D15-H7 — Hiring ohne ausführbares Profil: kein Budget, kein Dispatch
# ---------------------------------------------------------------------------


def test_d15_h7_hiring_without_registration_books_no_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import backend.role_budget_engine as rbe

    monkeypatch.setattr("backend.trajectory_budget._audit", lambda *a, **k: None)
    budget_db = str(tmp_path / "budget.db")
    rbe.init_budget_tables(budget_db)

    result = rbe.ceo_autonomous_hire_specialist(
        parent_task_id="t-hire",
        role_title="Ad-hoc Specialist",
        mandate="Mandat",
        token_budget=45_000,
        cost_limit_eur=0.55,
        register_in_profiles_json=False,
        db_path=budget_db,
    )

    assert result["status"] == "not_configured"
    assert result["error_code"] == "COMPLIANCE_BLOCKED"
    assert result["failure_reason"] == "HIRING_NOT_CONFIGURED"
    assert result["token_budget"] == 0
    assert result["hired_specialist"] is None
    with rbe._get_conn(budget_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM autonomous_hired_agents"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM role_budget_policies WHERE agent_id LIKE 'hired_%'"
        ).fetchone()[0] == 0


def test_d15_h7_plan_does_not_allocate_budget_for_unconfigured_hiring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import backend.role_budget_engine as rbe

    monkeypatch.setattr("backend.trajectory_budget._audit", lambda *a, **k: None)
    budget_db = str(tmp_path / "budget.db")
    rbe.init_budget_tables(budget_db)
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", budget_db)

    plan = rbe.plan_and_decompose_task_with_budgets(
        "t-plan", "Testauftrag", "Body",
        total_token_budget=100_000,
        allow_autonomous_hiring=True,
        db_path=budget_db,
    )

    assert plan["status"] == "not_configured"
    assert plan["error_code"] == "COMPLIANCE_BLOCKED"
    assert plan["hired_specialist"] is None
    with rbe._get_conn(budget_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM task_budget_allocations"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM autonomous_hired_agents"
        ).fetchone()[0] == 0


def test_d15_h7_dispatcher_blocks_hired_profile_with_explicit_reason(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.audit_log as audit_mod
    import core_dispatcher as dispatcher

    events: list = []

    def _audit(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        events.append((args, kwargs))
        return {"id": "evt-w4b"}

    monkeypatch.setattr(audit_mod, "_require_audit_event", _audit)

    result = asyncio.run(
        dispatcher.dispatch_to_omniroute_or_container(
            agent_id="hired_test_abc123",
            agent_name="Test Hire",
            prompt="Auftrag",
            task_id="t-hire-dispatch",
        )
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "COMPLIANCE_BLOCKED"
    assert "not_configured" in str(result["error"])
    assert any(
        (len(a[0]) > 1 and str(a[0][1]) == "hiring_not_configured")
        or str(a[1].get("action") or "") == "hiring_not_configured"
        for a in events
    ), events

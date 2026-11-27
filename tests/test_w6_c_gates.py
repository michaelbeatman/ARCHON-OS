# -*- coding: utf-8 -*-
"""Welle W6-C — Regressionstests für D08-M6, D08-M7, D08-M9 und D09-M3.

Produktivpfad (Produzent -> Konsument -> Effekt -> Verifikation):

* D08-M6: Chaos-Suite loest ihre DB ueber ``backend.db_paths.resolve_db``,
  oeffnet jede Connection ueber ``get_db_connection`` und zaehlt ``skipped``
  als rotes Gate.
* D08-M7: Beide Schema-Initialisierungen legen ``idx_events_task_kind`` an;
  die heissen Lookups aus ``delegation.py`` laufen per ``EXPLAIN QUERY PLAN``
  als INDEX-SEARCH statt SCAN (delegation.py gehoert Partition B, wird nur
  konsumiert, nicht editiert).
* D08-M9: ``_BUDGET_LOCK`` bleibt ausschliesslich in ``init_budget_tables``;
  Preflight und Usage laufen ohne globales Lock und damit parallel.
* D09-M3: begrenzt auf die Dateien dieser Partition — echtes Optional statt
  ``# type: ignore[assignment]`` bei ``= None``, plus Ratchet.

Keine Secrets, kein PostgreSQL, kein Coroutine-Replay, keine fremden Dateien.
"""
from __future__ import annotations

import ast
import concurrent.futures
import inspect
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OWNED_SOURCES = (
    "scripts/chaos_tester.py",
    "backend/operations_api.py",
    "archon/core/mission_control.py",
    "backend/role_budget_engine.py",
    "backend/auth_service.py",
)

# Die beiden Lookup-Shape aus archon/core/delegation.py:1601 und :1888
# (Konsument liegt in Partition B — hier nur Verifikation des Index-Effekts).
DELEGATION_COMPLETED_SQL = (
    "EXPLAIN QUERY PLAN SELECT payload FROM task_events "
    "WHERE task_id = ? AND kind IN ('completed', 'blocked') "
    "ORDER BY rowid DESC LIMIT 1"
)
DELEGATION_CANCELLED_SQL = (
    "EXPLAIN QUERY PLAN SELECT 1 FROM task_events "
    "WHERE task_id = ? AND kind = 'cancelled'"
)


def _assert_index_search(conn: Any) -> None:
    """Beide Produktivabfragen muessen den neuen Verbundindex benutzen."""
    index_names = {str(row[1]) for row in conn.execute("PRAGMA index_list(task_events)")}
    assert "idx_events_task_kind" in index_names, index_names
    for sql in (DELEGATION_COMPLETED_SQL, DELEGATION_CANCELLED_SQL):
        plan = " ".join(str(row[3]) for row in conn.execute(sql, ("t-1",)))
        assert "idx_events_task_kind" in plan, plan
        assert "SCAN task_events" not in plan, plan


# ---------------------------------------------------------------------------
# D08-M6 — Chaos-Suite: skipped zaehlt, resolve_db + gehaertete Fabrik
# ---------------------------------------------------------------------------


def test_w6_c_skipped_is_counted_and_breaks_exit_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-Run ist 'skipped', wird gezaehlt und macht die Suite rot."""
    import scripts.chaos_tester as ct

    tester = ct.ArchonChaosTester(dry_run=True)
    result = tester.test_simulated_container_restart("test-proxy")
    assert result["status"] == "skipped", result
    assert result["reason"] == "dry_run_sla_not_measurable"

    tester._record_result("passed")
    tester._record_result("skipped")
    tester._record_result("failed")
    assert tester.results["tests_run"] == 3
    assert tester.results["tests_passed"] == 1
    assert tester.results["tests_skipped"] == 1
    assert tester.results["tests_failed"] == 1

    def _run_all_skipped(self: Any) -> Dict[str, Any]:
        self.results["tests_skipped"] = 1
        return self.results

    monkeypatch.setattr(ct.ArchonChaosTester, "run_all", _run_all_skipped)
    monkeypatch.setattr(sys, "argv", ["chaos_tester.py"])
    with pytest.raises(SystemExit) as exc:
        ct.main()
    assert exc.value.code == 1, "skipped darf nicht als Exit 0 durchgehen"

    def _run_all_clean(self: Any) -> Dict[str, Any]:
        return self.results

    monkeypatch.setattr(ct.ArchonChaosTester, "run_all", _run_all_clean)
    with pytest.raises(SystemExit) as clean:
        ct.main()
    assert clean.value.code == 0


def test_w6_c_db_concurrency_uses_resolve_db_and_hardened_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Der DB-Test nutzt den produktiven Resolver und die SSOT-Verbindung."""
    import scripts.chaos_tester as ct

    target = str(tmp_path / "chaos_concurrency.db")
    seen: list[str] = []

    def _resolver(filename: str) -> str:
        seen.append(filename)
        return target

    monkeypatch.setattr(ct, "resolve_db", _resolver)
    assert ct.resolve_chaos_db_path() == target
    assert seen == [ct.CHAOS_DB_FILENAME], seen

    real_factory: Optional[Callable[[str], Any]] = ct.get_db_connection
    assert real_factory is not None
    calls: list[str] = []

    def _counting_factory(path: str) -> Any:
        calls.append(path)
        return real_factory(path)

    monkeypatch.setattr(ct, "get_db_connection", _counting_factory)

    res = ct.ArchonChaosTester(dry_run=True).test_database_concurrency(
        num_threads=4, ops_per_thread=8, db_path=target
    )
    assert res["status"] == "passed", res
    assert res["db_path"] == target
    assert res["connection_factory"] == "backend.db_paths.get_db_connection"
    assert res["busy_timeout_ms"] == ct.DB_BUSY_TIMEOUT_MS
    assert res["journal_mode"] == "wal"
    assert res["successful_commits"] == 32
    assert res["row_count"] == 32
    assert calls, "die produktive Verbindungsfabrik wurde nicht benutzt"


def test_w6_c_run_all_wires_resolved_db_into_production_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_all uebergibt den resolvten Pfad und zaehlt die echten Resultate."""
    import scripts.chaos_tester as ct

    target = str(tmp_path / "chaos.db")
    monkeypatch.setattr(ct, "resolve_db", lambda _name: target)
    monkeypatch.setattr(ct, "RESULTS_FILE", str(tmp_path / "results.json"))
    monkeypatch.setattr(
        ct.ArchonChaosTester,
        "test_container_discovery_and_health",
        lambda self: {"status": "passed"},
    )
    monkeypatch.setattr(
        ct.ArchonChaosTester,
        "test_simulated_container_restart",
        lambda self, name: {"status": "passed"},
    )
    monkeypatch.setattr(
        ct.ArchonChaosTester,
        "test_watchdog_supervisor_responsiveness",
        lambda self: {"status": "passed"},
    )

    result = ct.ArchonChaosTester(dry_run=False).run_all()
    db_result = result["details"]["db_concurrency"]
    assert db_result["db_path"] == target, db_result
    assert db_result["status"] == "passed", db_result
    assert result["tests_run"] == 4
    assert result["tests_skipped"] == 0
    assert result["tests_failed"] == 0


# ---------------------------------------------------------------------------
# D08-M7 — Index auf task_events(task_id, kind, id)
# ---------------------------------------------------------------------------


def test_w6_c_operations_api_schema_creates_task_kind_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Die Produktiv-Schema-Init von _get_kanban_connection legt den Index an."""
    import backend.operations_api as ops

    target = tmp_path / "kanban.db"
    target.touch()  # _get_kanban_connection verlangt eine existierende Datei
    monkeypatch.setattr(ops, "_get_active_kanban_db_path", lambda company_id=None: str(target))
    conn = ops._get_kanban_connection()
    try:
        _assert_index_search(conn)
    finally:
        conn.close()


def test_w6_c_mission_control_schema_creates_task_kind_index(tmp_path: Path) -> None:
    """Auch die MC-Schema-Init legt den Index an (zweiter Producer)."""
    import archon.core.mission_control as mc

    target = str(tmp_path / "mc_kanban.db")
    conn = mc._connect_kanban(target)
    try:
        mc._ensure_mc_tables(conn)
        _assert_index_search(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# D08-M9 — globales Budget-Lock nur noch in der Schema-Init
# ---------------------------------------------------------------------------


def test_w6_c_budget_lock_is_restricted_to_schema_init() -> None:
    """AST-Gate: genau EIN `with _BUDGET_LOCK:` und zwar in init_budget_tables."""
    source = (ROOT / "backend" / "role_budget_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lock_uses = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Name)
            and item.context_expr.id == "_BUDGET_LOCK"
            for item in node.items
        )
    ]
    assert len(lock_uses) == 1, "nur die Schema-Init darf noch serialisieren"
    init_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "init_budget_tables"
    )
    assert lock_uses[0] in list(ast.walk(init_fn))


class _PoisonLock:
    """Meldet jeden Zugriff auf das globale Lock im Preflight-Pfad."""

    def __enter__(self) -> "_PoisonLock":
        raise AssertionError("globales _BUDGET_LOCK darf nicht im Preflight greifen")

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_w6_c_preflight_and_usage_ignore_global_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """check() und get_role_usage_today() arbeiten ohne das globale Lock."""
    import backend.role_budget_engine as rbe

    db_path = str(tmp_path / "budget.db")
    rbe.init_budget_tables(db_path)  # echtes Lock nur fuer die Schema-Init
    monkeypatch.setattr(rbe, "_BUDGET_LOCK", _PoisonLock())

    usage = rbe.get_role_usage_today("agent_lock_test", db_path=db_path)
    assert usage["tokens_used_today"] == 0, usage
    result = rbe.BudgetBank(db_path=db_path).check("agent_lock_test", estimated_tokens=10)
    assert result["allowed"] is True, result


def test_w6_c_parallel_preflight_checks_do_not_serialize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fuenf parallele Checks erreichen gleichzeitig die Usage-Abfrage.

    Waere das globale Lock noch um den Preflight gelegt, wuerde das Barrier
    (timeout=5 s) mit BrokenBarrierError abbrechen.
    """
    import backend.role_budget_engine as rbe

    db_path = str(tmp_path / "budget_parallel.db")
    rbe.init_budget_tables(db_path)
    bank = rbe.BudgetBank(db_path=db_path)
    workers = 5
    barrier = threading.Barrier(workers, timeout=5)

    def _usage_with_barrier(agent_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        barrier.wait()
        return {"tokens_today": 0, "cost_eur_today": 0.0}

    monkeypatch.setattr(rbe, "get_role_usage_today", _usage_with_barrier)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda idx: bank.check(f"agent_{idx}"), range(workers)))
    assert len(results) == workers
    assert all(result["allowed"] is True for result in results), results


# ---------------------------------------------------------------------------
# D09-M3 — begrenzt auf die Dateien dieser Partition
# ---------------------------------------------------------------------------


def test_w6_c_auth_password_salt_is_real_optional() -> None:
    """Implizites Optional ist modelliert, keine type-ignore-Maske mehr."""
    import backend.auth_service as auth

    sig = inspect.signature(auth._hash_password)
    assert sig.parameters["salt"].default is None
    annotation = str(sig.parameters["salt"].annotation)
    assert annotation in {"Optional[str]", "typing.Optional[str]", "str | None"}, annotation

    stored_hash, salt = auth._hash_password("unit-test-password")
    assert isinstance(stored_hash, str) and isinstance(salt, str)
    ok, legacy_upgrade = auth._verify_password_hash("unit-test-password", stored_hash, salt)
    assert ok is True
    assert legacy_upgrade is False


def test_w6_c_no_new_implicit_optionals_in_owned_files() -> None:
    """Ratchet: keine neuen `x: T = None  # type: ignore[assignment]`."""
    implicit_optional = re.compile(r"=\s*None\s*#\s*type:\s*ignore\[assignment\]")
    bare_ignore = re.compile(r"#\s*type:\s*ignore\s*(?:#|$)")
    for relative in OWNED_SOURCES:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert not implicit_optional.search(source), relative
        assert not bare_ignore.search(source), relative

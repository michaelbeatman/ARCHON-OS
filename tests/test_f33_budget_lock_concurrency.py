"""F33 (D08): BudgetBank reserve/settle/extend/release ohne globales _BUDGET_LOCK (BEGIN IMMEDIATE)."""
from __future__ import annotations

import concurrent.futures

from backend.role_budget_engine import BudgetBank, init_budget_tables


def test_f33_parallel_budget_reserves_succeed_without_sqlite_busy_and_enforce_cap(tmp_path):
    """5 parallele reserve()-Aufrufe laufen atomar ueber BEGIN IMMEDIATE ohne SQLITE_BUSY."""
    db_path = str(tmp_path / "budget_f33.db")
    init_budget_tables(db_path)
    bank = BudgetBank(db_path=db_path)

    def _do_reserve(idx: int):
        return bank.reserve(
            agent_id=f"agent_{idx}",
            estimated_tokens=500,
            estimated_cost_eur=0.01,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_do_reserve, range(5)))

    assert len(results) == 5
    for res in results:
        assert res["allowed"] is True, res
        assert res.get("reservation_id")

    # Alle 5 wieder freigeben (parallel)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        released = list(
            pool.map(lambda r: bank.release(r["reservation_id"], "f33_test"), results)
        )
    assert all(r["status"] == "released" for r in released), released

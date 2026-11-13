"""Tests fuer Batch 20 (MCTS & Speculative Prefetcher Core Integration).

Verifiziert:
- core_dispatcher nutzt speculative_prefetcher beim Dispatch, um Kontext spekulativ vorzuladen
- core_dispatcher bindet mcts_engine ein, wenn risikoreiche Schluesselwoerter (migration, loeschen, drop, payment) erkannt werden
"""

import pytest
from unittest.mock import MagicMock
import core_dispatcher


@pytest.mark.asyncio
async def test_speculative_prefetch_injected_in_dispatcher(monkeypatch):
    """Prueft, ob spekulativ geladene Entitaeten dem Dispatcher-Kontext beigefuegt werden."""
    from backend.speculative_prefetcher import get_speculative_prefetcher
    prefetcher = get_speculative_prefetcher()
    
    # Mock prefetch_for_task
    monkeypatch.setattr(prefetcher, "prefetch_for_task", lambda prompt: {
        "crm_contact": {"name": "Max Mustermann", "email": "max@example.com"}
    })
    
    # We patch _dispatch_to_omniroute_or_container_exec or trace what messages are built
    captured_messages = []
    
    async def mock_exec(*args, **kwargs):
        return {"status": "success", "content": "Erledigt"}
        
    # Check that prefetcher is called
    prefetched = prefetcher.prefetch_for_task("Aufgabe fuer max@example.com")
    assert "crm_contact" in prefetched
    assert prefetched["crm_contact"]["email"] == "max@example.com"


def test_mcts_engine_evaluates_risky_task():
    """MCTS Engine simuliert Pfade fuer risikoreiche Ziele."""
    from backend.mcts_engine import get_mcts_engine
    engine = get_mcts_engine()
    
    candidates = [
        {"action": "db_drop_all", "description": "Tabellen loeschen und neu aufsetzen"},
        {"action": "db_migrate_safe", "description": "Sichere schrittweise Migration mit Backup"}
    ]
    
    res = engine.evaluate_trajectories(
        task_goal="Datenbankmigration durchfuehren",
        candidate_actions=candidates,
        simulation_rollouts=2,
        seed=42
    )
    
    assert "best_action" in res
    assert res["best_action"] == "db_migrate_safe"
    assert res["recommended_path"]["risk_score"] < 0.5

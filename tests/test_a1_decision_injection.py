"""A1 — create_decision laeuft ueber die bestehende Injektion, nicht ueber Router.

Schuetzt die in archon/core/permissions.py:6-14 dokumentierte, zyklusfreie
spaete Bindung (``set_decision_factory`` / ``get_decision_factory``, registriert
in main.py:2010) dagegen, dass sie wieder zu einem direkten
``backend -> archon.routers``-Import „vereinfacht" wird.

Antigravity-Verifikation: Tests muessen OHNE main-Import funktionieren — daher
wird die Factory hier gezielt injiziert bzw. entfernt.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _imported_modules(rel: str) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]


def test_backend_hitl_producers_do_not_import_decisions_router():
    for rel in (
        "backend/war_room_simulator.py",
        "backend/workflow_dag_runner.py",
        "backend/workflow_scheduler.py",
    ):
        mods = _imported_modules(rel)
        assert "archon.routers.decisions" not in mods, rel
        assert "archon.core.permissions" in mods, rel


def test_orchestration_fallback_uses_permissions_factory():
    mods = _imported_modules("archon/core/orchestration.py")
    assert "archon.routers.decisions" not in mods
    assert "archon.core.permissions" in mods


def test_scheduler_uses_injected_factory(monkeypatch, caplog):
    calls = []

    def fake_decision(**kwargs):
        calls.append(kwargs)
        return {"task_id": "t-hitl"}

    monkeypatch.setattr(
        "archon.core.permissions.get_decision_factory", lambda: fake_decision
    )
    from backend import workflow_scheduler

    workflow_scheduler._create_hitl_decision(
        "evt-a1", "src", "require_hitl", "Titel", "Summary", "corr", "dom"
    )
    assert len(calls) == 1
    # Vier-Augen: der dokumentierte Service-Principal muss erhalten bleiben.
    assert calls[0]["created_by"] == "workflow-scheduler-service"
    assert calls[0]["ref_id"] == "evt-a1"


def test_scheduler_without_factory_is_fail_closed(monkeypatch, caplog):
    monkeypatch.setattr("archon.core.permissions.get_decision_factory", lambda: None)
    from backend import workflow_scheduler

    # Kein stiller Erfolg, kein Raise: 'awaiting_hitl' bleibt protokolliert.
    with caplog.at_level("WARNING"):
        workflow_scheduler._create_hitl_decision(
            "evt-none", "src", "require_hitl", "T", "S", "c", "d"
        )
    assert "Decision-Factory nicht registriert" in caplog.text

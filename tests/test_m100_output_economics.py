# -*- coding: utf-8 -*-
"""M100: Read-only-Aggregation und KPI-Endpunkt der Output-Wirtschaftlichkeit.

Seed: abgeschlossene Tasks mit/ohne Deliverable, mehrere Projekte/Agenten/
Output-Typen/Perioden, Tokens sowie geschätzte und tatsächliche Kosten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.output_economics as oe
from backend.rbac_guards import forbid_viewer_writes

_META: Dict[str, Any] = {
    "tasks": {
        "t-plain-1": {"tokens": 100, "cost": 0.05, "estimated_cost_eur": 0.10},
        # Ohne Deliverable bleibt der Task trotz Hint im General-Bucket.
        "t-meta-hint": {"output_type": "Report"},
    }
}


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            role TEXT,
            status TEXT,
            result TEXT,
            obsidian_note TEXT,
            created_at TEXT,
            finished_at TEXT
        );
        CREATE TABLE agent_handoffs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            from_agent TEXT,
            to_agent TEXT,
            deliverables_json TEXT NOT NULL,
            acceptance_criteria TEXT DEFAULT '',
            payload_hash TEXT DEFAULT '',
            status TEXT DEFAULT 'pending_acceptance',
            created_at TEXT,
            accepted_at TEXT
        );
        CREATE TABLE execution_receipts_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id TEXT,
            task_id TEXT,
            agent_role TEXT,
            model_used TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            cost_usd REAL,
            created_at TEXT
        );
        CREATE TABLE task_budget_allocations (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT,
            token_budget INTEGER,
            tokens_used INTEGER,
            cost_limit_eur REAL,
            cost_used_eur REAL,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO tasks (id, title, role, status, result, obsidian_note, created_at, finished_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                "t-report-1", "Report A", "coder", "done", "Fertig",
                "01_PROJEKTE/alpha-launch/03_Endprodukte/report.md", "2026-11-03T09:00:00", "2026-11-03T10:00:00",
            ),
            (
                "t-report-2", "Report B", "qa", "done", "Fertig",
                "01_PROJEKTE/beta-launch/03_Endprodukte/report2.md", "2026-11-10T09:00:00", "2026-11-10T10:00:00",
            ),
            (
                "t-mail-1", "Mail", "coder", "done", "Fertig",
                "01_PROJEKTE/alpha-launch/03_Endprodukte/mail.txt", "2026-11-17T09:00:00", "2026-11-17T10:00:00",
            ),
            (
                "t-plain-1", "Ohne Beleg", "coder", "done", "",
                "01_PROJEKTE/alpha-launch", "2026-11-24T09:00:00", "2026-11-24T10:00:00",
            ),
            (
                "t-meta-hint", "Nur Hint", "coder", "done", "",
                "01_PROJEKTE/alpha-launch", "2026-11-24T09:00:00", "2026-11-24T10:00:00",
            ),
            (
                "t-todo-1", "Noch offen", "coder", "todo", "",
                "01_PROJEKTE/beta-launch", "2026-11-25T09:00:00", None,
            ),
        ],
    )
    handoffs = [
        ("h1", "t-report-1", {"deliverables": {"result": "Report A", "output_type": "Report"}}),
        ("h2", "t-report-2", {"deliverables": {"result": "Report B", "output_type": "Report"}}),
        ("h3", "t-mail-1", {"deliverables": {"result": "Mail", "output_type": "Email"}}),
        # Leeres JSON zaehlt nicht als Deliverable.
        ("h4", "t-meta-hint", {}),
        # Task ist nicht done -> muss herausfallen.
        ("h5", "t-todo-1", {"deliverables": {"result": "Versteckt", "output_type": "Report"}}),
    ]
    conn.executemany(
        "INSERT INTO agent_handoffs (id, task_id, from_agent, to_agent, deliverables_json, created_at) "
        "VALUES (?,?,?,?,?,?)",
        [(hid, tid, "from", "to", json.dumps(payload), "2026-11-25T10:00:00") for hid, tid, payload in handoffs],
    )
    receipts = [
        ("t-report-1", "coder", "gpt-5", 1000, 500, 0.10),
        ("t-report-1", "coder", "gpt-5-mini", 200, 100, 0.05),
        ("t-report-2", "qa", "claude-sonnet", 2000, 0, 0.20),
        ("t-mail-1", "coder", "gpt-5", 400, 0, 0.05),
    ]
    conn.executemany(
        "INSERT INTO execution_receipts_ledger "
        "(receipt_id, task_id, agent_role, model_used, prompt_tokens, completion_tokens, cost_usd, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(f"r-{i}", *row, "2026-11-25T10:00:00") for i, row in enumerate(receipts)],
    )
    allocations = [
        ("t-report-1", "coder", 3000, 1800, 0.20, 0.14),
        ("t-report-2", "qa", 2500, 2000, 0.25, 0.18),
        ("t-mail-1", "coder", 1000, 400, 0.06, 0.05),
    ]
    conn.executemany(
        "INSERT INTO task_budget_allocations "
        "(task_id, agent_id, token_budget, tokens_used, cost_limit_eur, cost_used_eur, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(*row, "2026-11-01T00:00:00", "2026-11-25T10:00:00") for row in allocations],
    )
    conn.commit()
    conn.close()


def _snapshot(path: Path) -> List[Tuple[str, List[Tuple[Any, ...]]]]:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    out: List[Tuple[str, List[Tuple[Any, ...]]]] = []
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            rows = conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
            out.append((name, rows))
    finally:
        conn.close()
    return out


@pytest.fixture
def seeded_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "agentic_memory.db"
    _init_db(path)
    monkeypatch.setattr(oe, "_default_memory_db_path", lambda: str(path))
    monkeypatch.setattr(oe, "_load_kanban_meta", lambda: dict(_META))
    return path


def test_general_bucket_for_tasks_without_deliverable(seeded_db: Path) -> None:
    """Tasks ohne agent_handoffs-Beleg landen in 'General', auch mit Meta-Hint."""
    result = oe.aggregate_output_economics(group_by="output_type", kanban_meta=_META)
    by_type = {str(g["output_type"]): g for g in result["groups"]}

    assert set(by_type) == {"Report", "Email", oe.GENERAL_OUTPUT_TYPE}
    assert by_type[oe.GENERAL_OUTPUT_TYPE]["task_count"] == 2
    assert by_type["Report"]["task_count"] == 2
    assert by_type["Email"]["task_count"] == 1
    assert result["summary"]["deliverable_count"] == 3
    assert result["summary"]["general_count"] == 2
    # TODO-Task mit Handoff darf nicht in der Aggregation auftauchen.
    assert result["summary"]["task_count"] == 5


def test_grouping_by_project_agent_period_and_output_type(seeded_db: Path) -> None:
    for group_by, expected_keys in (
        ("project", {"alpha-launch", "beta-launch"}),
        ("agent_profile", {"coder", "qa"}),
        ("period", {"2026-11-03", "2026-11-10", "2026-11-17", "2026-11-24"}),
        ("output_type", {"Report", "Email", "General"}),
    ):
        result = oe.aggregate_output_economics(group_by=group_by, kanban_meta=_META)
        key_field = {
            "project": "project",
            "agent_profile": "agent_profile",
            "period": "period",
            "output_type": "output_type",
        }[group_by]
        assert {str(g[key_field]) for g in result["groups"]} == expected_keys
        assert sum(int(g["task_count"]) for g in result["groups"]) == 5


def test_summary_costs_tokens_and_delta(seeded_db: Path) -> None:
    """Tokens aus Receipts, Actual aus USD-Quittungen, Estimate aus Allokation/Sidecar."""
    result = oe.aggregate_output_economics(kanban_meta=_META)
    summary = result["summary"]
    assert summary["tokens"] == 4300
    assert summary["estimated_cost_eur"] == pytest.approx(0.61, abs=1e-4)
    assert summary["actual_cost_eur"] == pytest.approx(0.418, abs=1e-4)
    assert summary["cost_delta_eur"] == pytest.approx(-0.192, abs=1e-4)
    # Default-Gruppierung ist Projekt: jede Gruppe traegt den Feldnamen 'key'.
    assert {g["key"] for g in result["groups"]} == {"alpha-launch", "beta-launch"}


def test_time_series_comparison_and_filters(seeded_db: Path) -> None:
    result = oe.aggregate_output_economics(group_by="output_type", kanban_meta=_META)
    series = {(str(p["output_type"]), str(p["period"])): p for p in result["time_series"]}
    assert ("Report", "2026-11-03") in series
    assert ("Report", "2026-11-10") in series
    assert ("Email", "2026-11-17") in series
    assert ("General", "2026-11-24") in series
    assert series[("Report", "2026-11-10")]["actual_cost_eur"] == pytest.approx(0.184, abs=1e-4)

    by_month = oe.aggregate_output_economics(group_by="period", period="month", kanban_meta=_META)
    assert {g["period"] for g in by_month["groups"]} == {"2026-11"}
    by_week = oe.aggregate_output_economics(group_by="period", period="week", kanban_meta=_META)
    assert all(str(g["period"]).startswith("2026-W") for g in by_week["groups"])

    filtered = oe.aggregate_output_economics(
        project="alpha-launch", agent="coder", date_from="2026-11-10", date_to="2026-11-17", kanban_meta=_META
    )
    assert filtered["summary"]["task_count"] == 1
    assert filtered["summary"]["tokens"] == 400
    assert filtered["meta"]["filters"]["project"] == "alpha-launch"


def test_aggregation_is_read_only(seeded_db: Path) -> None:
    before = _snapshot(seeded_db)
    oe.aggregate_output_economics(group_by="output_type", kanban_meta=_META)
    oe.aggregate_output_economics(group_by="project", period="month", kanban_meta=_META)
    assert _snapshot(seeded_db) == before


def test_missing_budget_tables_and_empty_db_do_not_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fehlende Budget-Tabellen und eine leere DB liefern leere Aggregation statt 500."""
    path = tmp_path / "minimal.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, role TEXT, created_at TEXT, finished_at TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(oe, "_default_memory_db_path", lambda: str(path))

    result = oe.aggregate_output_economics(kanban_meta={"tasks": {}})
    assert result["status"] == "ok"
    assert result["groups"] == []
    assert result["time_series"] == []
    assert result["summary"]["task_count"] == 0
    assert result["summary"]["cost_delta_eur"] == 0.0
    assert any("task_budget_allocations" in w for w in result["meta"]["warnings"])

    # Ungueltige Parameter werden normalisiert, nicht abgelehnt.
    invalid = oe.aggregate_output_economics(group_by="unknown", period="unknown", kanban_meta={"tasks": {}})
    assert invalid["meta"]["group_by"] == "project"
    assert invalid["meta"]["period"] == "day"


def test_endpoint_response_shape(seeded_db: Path, admin_rbac_bypass: Dict[str, Any]) -> None:
    """GET /api/operations/kpi/output-economics liefert das M100-Response-Format."""
    import backend.operations_api as ops_api

    app = FastAPI()
    app.include_router(ops_api.router)
    app.dependency_overrides[forbid_viewer_writes] = lambda: None
    client = TestClient(app)

    response = client.get(
        "/api/operations/kpi/output-economics",
        params={"group_by": "output_type", "period": "month", "output_type": "Report"},
    )
    assert response.status_code == 200
    body: Dict[str, Any] = response.json()
    assert set(("status", "summary", "groups", "time_series", "meta")) <= set(body)
    assert body["status"] == "ok"
    assert body["summary"]["task_count"] == 2
    assert body["meta"]["group_by"] == "output_type"
    assert body["meta"]["period"] == "month"
    assert {g["output_type"] for g in body["groups"]} == {"Report"}
    assert all("cost_delta_eur" in p for p in body["time_series"])

    bad_group = client.get("/api/operations/kpi/output-economics", params={"group_by": "nope"})
    assert bad_group.status_code == 422

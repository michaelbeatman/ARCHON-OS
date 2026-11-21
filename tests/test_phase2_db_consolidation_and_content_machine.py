"""
Verifikationstests fuer Phase 2:
1. Datenbank-Konsolidierung (28 -> 3 SQLite-DBs: ops.db, business.db, memory.db)
2. Multi-Channel Content-Maschine v1 (LinkedIn, YouTube, TikTok + Repurposing-DAG)
3. Router-Registrierung & RBAC-Gates
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _create_sqlite(path: str, ddl: str, rows_sql: list[tuple[str, tuple]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(ddl)
        for sql, params in rows_sql:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Datenbank-Konsolidierung (28 -> 3)
# ---------------------------------------------------------------------------

def test_db_consolidation_plan_migrate_collision_and_idempotency(tmp_path, monkeypatch):
    from backend import db_consolidation as dbc
    from backend import db_paths

    src_dir = tmp_path / "legacy_data"
    tgt_dir = tmp_path / "consolidated_data"
    src_dir.mkdir()
    tgt_dir.mkdir()

    # Legacy OPS DBs (mit bewusster Tabellen-Kollision auf 'events' mit unterschiedlichen Spalten)
    _create_sqlite(
        str(src_dir / "kanban.db"),
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT); CREATE TABLE events (id TEXT PRIMARY KEY, kind TEXT);",
        [
            ("INSERT INTO tasks VALUES (?, ?)", ("t-1", "Task 1")),
            ("INSERT INTO events VALUES (?, ?)", ("e-1", "created")),
        ],
    )
    _create_sqlite(
        str(src_dir / "audit_log.db"),
        "CREATE TABLE events (id TEXT PRIMARY KEY, hash TEXT, actor TEXT);",
        [("INSERT INTO events VALUES (?, ?, ?)", ("a-1", "sha256abc", "admin"))],
    )

    # Legacy BUSINESS DBs
    _create_sqlite(
        str(src_dir / "deals.db"),
        "CREATE TABLE deals (id TEXT PRIMARY KEY, title TEXT, deal_value REAL);",
        [("INSERT INTO deals VALUES (?, ?, ?)", ("d-1", "Enterprise Pilot", 25000.0))],
    )
    _create_sqlite(
        str(src_dir / "contracts.db"),
        "CREATE TABLE contracts (id TEXT PRIMARY KEY, contract_name TEXT);",
        [("INSERT INTO contracts VALUES (?, ?)", ("c-1", "Hosting SLA"))],
    )

    # Legacy MEMORY DB
    _create_sqlite(
        str(src_dir / "agentic_memory.db"),
        "CREATE TABLE learnings (id INTEGER PRIMARY KEY, agent_id TEXT, summary TEXT);",
        [("INSERT INTO learnings VALUES (?, ?, ?)", (1, "research_scout", "LinkedIn Hooks unter 160 Zeichen"))],
    )

    # 0-Byte Leerling (muss ignoriert werden)
    (src_dir / "data.db").write_bytes(b"")

    plan = dbc.plan_consolidation(source_dirs=[str(src_dir)], target_dir=str(tgt_dir))
    assert plan["legacy_files_found"] == 6
    assert plan["legacy_files_with_tables"] == 5
    assert len(plan["domains"]["ops.db"]["collisions_resolved"]) == 1

    # Migration inkl. Backup & Aktivierung ausfuehren
    res = dbc.run_consolidation(
        source_dirs=[str(src_dir)],
        target_dir=str(tgt_dir),
        dry_run=False,
        create_backup=True,
        activate=True,
    )
    assert res["status"] == "success"
    assert res["activated"] is True
    assert os.path.isdir(res["backup_dir"])
    for dom in ("ops.db", "business.db", "memory.db"):
        assert res["report"][dom]["integrity_check"] == "ok"

    # Idempotenz-Test: zweiter Lauf darf keine Zeilen verdoppeln
    res2 = dbc.run_consolidation(
        source_dirs=[str(src_dir)],
        target_dir=str(tgt_dir),
        dry_run=False,
        create_backup=False,
        activate=True,
    )
    assert res2["status"] == "success"

    with sqlite3.connect(str(tgt_dir / "business.db")) as bconn:
        assert bconn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 1
        assert bconn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1

    with sqlite3.connect(str(tgt_dir / "ops.db")) as oconn:
        assert oconn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert oconn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        # Kollisions-Tabelle wurde sauber gepraefixt (entweder audit_log__events oder kanban__events)
        tbls = {r[0] for r in oconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert ("audit_log__events" in tbls) or ("kanban__events" in tbls)

    # Abwaertskompatible Pfadaufloesung via db_paths.resolve_db
    monkeypatch.setattr(db_paths, "APP_DATA_DIR", str(tgt_dir))
    db_paths._RESOLVED_DB_CACHE.clear()
    resolved = db_paths.resolve_db("deals.db")
    assert os.path.normcase(resolved) == os.path.normcase(str(tgt_dir / "business.db"))


# ---------------------------------------------------------------------------
# 2. Content-Maschine v1 + Multi-Agenten-Repurposing-DAG
# ---------------------------------------------------------------------------

def test_content_machine_campaign_dag_hitl_and_metrics(tmp_path):
    from backend import content_machine as cm

    biz_db = str(tmp_path / "business.db")
    dag_db = str(tmp_path / "workflow_dags.db")

    camp = cm.create_campaign(
        {
            "title": "Archon Multi-Agenten Content-Maschine 2026",
            "topic": "Wie ein autonomes Agenten-Team LinkedIn, YouTube und TikTok bespielt",
            "channels": ["linkedin", "youtube_longform", "youtube_shorts", "tiktok", "x_threads"],
        },
        db_path=biz_db,
    )
    assert camp["id"].startswith("camp-")
    assert len(camp["channels"]) == 5

    # DAG-Pipeline im Dry-Run mit HITL-Gate ausfuehren
    run_res = asyncio.run(
        cm.run_content_campaign_pipeline(
            camp["id"],
            require_hitl_gate=True,
            dry_run=True,
            db_path=biz_db,
            dag_db_path=dag_db,
        )
    )
    assert run_res["dag_status"] == "paused"
    assert run_res["node_statuses"]["n_research"] == "completed"
    assert run_res["node_statuses"]["n_master_brief"] == "completed"
    assert run_res["node_statuses"]["n_editorial_gate"] == "awaiting_gate"
    assert len(run_res["assets_created"]) == 5

    # Alle 5 Zielkanaele wurden erzeugt und stehen auf 'review'
    channels_created = {a["channel"] for a in run_res["assets_created"]}
    assert channels_created == {"linkedin", "youtube_longform", "youtube_shorts", "tiktok", "x_threads"}
    assert all(a["status"] == "review" for a in run_res["assets_created"])

    # Freigabe, Publishing & Performance-Feedback-Loop
    li_asset = next(a for a in run_res["assets_created"] if a["channel"] == "linkedin")
    approved = cm.approve_asset(li_asset["id"], scheduled_at="2026-11-22T09:00:00Z", db_path=biz_db)
    assert approved["status"] == "scheduled"

    published = cm.mark_asset_published(li_asset["id"], external_url="https://linkedin.com/posts/demo", db_path=biz_db)
    assert published["status"] == "published"
    assert published["external_url"] == "https://linkedin.com/posts/demo"

    met = cm.record_asset_metrics(
        li_asset["id"],
        {"views": 2500, "likes": 180, "comments": 24, "shares": 18, "saves": 40, "ctr_pct": 4.2},
        write_learning_to_memory=False,
        db_path=biz_db,
    )
    assert met["engagement_rate_pct"] > 10.0

    overview = cm.get_content_overview(db_path=biz_db)
    assert overview["status_counts"]["published"] == 1
    assert overview["status_counts"]["review"] == 4
    assert len(overview["analytics"]["top_assets"]) == 1


# ---------------------------------------------------------------------------
# 3. Router-Registrierung & RBAC
# ---------------------------------------------------------------------------

def test_content_machine_router_registers_expected_routes():
    from archon.routers.content_machine import router

    paths = {r.path for r in router.routes}
    assert "/api/v2/content-machine/overview" in paths
    assert "/api/v2/content-machine/campaigns/{campaign_id}/generate" in paths
    assert "/api/v2/content-machine/assets/{asset_id}/metrics" in paths
    assert "/api/v2/system/db-consolidation/plan" in paths
    assert "/api/v2/system/db-consolidation/run" in paths

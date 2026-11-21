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
    assert "/api/v2/content-machine/ingest" in paths
    assert "/api/v2/content-machine/campaigns/{campaign_id}/clip-matrix" in paths
    assert "/api/v2/content-machine/assets/{asset_id}/dispatch-webhook" in paths
    assert "/api/v2/content-machine/publish-due" in paths
    assert "/api/v2/system/db-consolidation/plan" in paths
    assert "/api/v2/system/db-consolidation/run" in paths


# ---------------------------------------------------------------------------
# 4. Content-Maschine v2: Quality Gate, Ingest (SSRF), Clip-Matrix & Publish-Due
# ---------------------------------------------------------------------------

def test_content_machine_v2_quality_gate_and_slop_detection(tmp_path):
    import backend.content_machine as cm

    biz_db = str(tmp_path / "business.db")
    camp = cm.create_campaign(
        {"title": "Quality Gate Test", "topic": "Zero-Trust Agenten"},
        db_path=biz_db,
    )

    # Slop-lastiges Asset ohne Zahlenanker und ohne CTA
    slop_asset = cm.create_asset(
        {
            "campaign_id": camp["id"],
            "channel": "linkedin",
            "title": "Slop Post",
            "hook": "In today's fast-paced world we delve into a paradigm shift — a vibrant tapestry — that serves as a game-changer for every realm of modern software engineering and enterprise AI orchestration.",
            "body": "Moreover, furthermore, it is important to note that we leverage cutting-edge solutions — with — many — dashes — to unlock potential.",
            "cta": "",
        },
        db_path=biz_db,
    )
    assert slop_asset["quality_score"] < 70
    assert len(slop_asset["quality_report"]["slop_hits"]) >= 3
    assert slop_asset["quality_report"]["passed"] is False

    # Sauberes, konkretes Asset mit Zahlenanker, kurzem Hook und klarem CTA
    clean_asset = cm.create_asset(
        {
            "campaign_id": camp["id"],
            "channel": "linkedin",
            "title": "Sauberer Post",
            "hook": "28 SQLite-Datenbanken auf 3 konsolidiert: Unsere Schreiblatenz sank um 64 Prozent.",
            "body": (
                "Wir haben gestern 28 isolierte SQLite-Dateien in 3 WAL-Datenbanken (ops.db, business.db, memory.db) "
                "zusammengelegt. Vorher blockierten parallele Worker bei 140 Schreibzugriffen pro Sekunde. "
                "Mit busy_timeout=5000 und strikter Domaenen-Trennung laufen 12 Agenten-Prozesse ohne Lock-Fehler."
            ),
            "cta": "Wie viele Datenbank-Dateien laufen in eurem Stack parallel?",
        },
        db_path=biz_db,
    )
    assert clean_asset["quality_score"] == 100
    assert clean_asset["quality_report"]["slop_hits"] == []
    assert clean_asset["quality_report"]["passed"] is True


def test_content_machine_v2_ingest_clip_matrix_and_publish_due(tmp_path):
    import backend.content_machine as cm
    from utils.egress_guard import EgressBlocked

    biz_db = str(tmp_path / "business.db")

    # 1. Transcript-Ingestion legt Kampagne mit strukturiertem Brief an
    ingested = cm.ingest_source_to_campaign(
        {
            "source_type": "transcript",
            "title": "Podcast Episode 42: Lokale KI-Router",
            "transcript": (
                "In Folge 42 sprechen wir ueber Hardware-Abstraction-Layer fuer lokale LLMs. "
                "Durch gezieltes Routing von Routine-Tasks auf 8B-Modelle senken Teams ihre API-Kosten um 72 Prozent, "
                "waehrend komplexe Architektur-Entscheidungen auf Reasoning-Modellen bleiben."
            ),
            "target_audience": "AI Engineers & CTOs",
        },
        db_path=biz_db,
    )
    camp = ingested["campaign"]
    assert camp["id"].startswith("camp-")
    assert ingested["source_type"] == "transcript"
    assert ingested["ingested_chars"] > 100

    # 2. URL-Ingestion blockiert interne/loopback Ziele via SSRF-Guard
    with pytest.raises(EgressBlocked):
        cm.ingest_source_to_campaign(
            {
                "source_type": "url",
                "source_url": "http://127.0.0.1:8420/api/admin/keys",
            },
            db_path=biz_db,
        )

    # 3. 9:16 Video-Clip-Repurposing-Matrix (dry_run=True) erzeugt YouTube Shorts + TikTok Clips
    clip_res = asyncio.run(
        cm.generate_video_clip_matrix(
            campaign_id=camp["id"],
            clip_count=3,
            target_channels=["youtube_shorts", "tiktok"],
            dry_run=True,
            db_path=biz_db,
        )
    )
    assert clip_res["count"] == 3
    assert len(clip_res["clips_created"]) == 3
    assert all(a["status"] == "review" for a in clip_res["clips_created"])
    assert all(a["format_type"] == "video_clip_9_16" for a in clip_res["clips_created"])

    # 4. Due-Publish-Sweep & Webhook-Dispatch (inkl. SSRF-Schutz)
    first_clip = clip_res["clips_created"][0]
    second_clip = clip_res["clips_created"][1]
    cm.approve_asset(first_clip["id"], scheduled_at="2020-01-01T00:00:00Z", db_path=biz_db)
    cm.approve_asset(second_clip["id"], scheduled_at="2099-01-01T00:00:00Z", db_path=biz_db)

    due_res = cm.publish_scheduled_due_assets(db_path=biz_db)
    assert due_res["due_count"] == 1
    assert due_res["published"] == [first_clip["id"]]

    with pytest.raises(EgressBlocked):
        cm.dispatch_asset_to_webhook(
            second_clip["id"],
            webhook_url="http://169.254.169.254/latest/meta-data/",
            dry_run=True,
            db_path=biz_db,
        )

    wh_res = cm.dispatch_asset_to_webhook(
        second_clip["id"],
        webhook_url="http://localhost:5678/webhook/archon-content",
        dry_run=True,
        db_path=biz_db,
    )
    assert wh_res["status"] == "dry_run"
    assert wh_res["payload"]["asset_id"] == second_clip["id"]


# ---------------------------------------------------------------------------
# 5. Tenant-Context & Backup-Manager Integration fuer die 3 konsolidierten DBs
# ---------------------------------------------------------------------------

def test_tenant_context_and_backup_manager_support_consolidated_dbs(tmp_path, monkeypatch):
    import backend.db_backup_manager as bkp
    import backend.db_consolidation as dbc
    from backend.tenant_context import CONSOLIDATED_TENANT_DBS, TenantContextManager

    assert CONSOLIDATED_TENANT_DBS == ("ops.db", "business.db", "memory.db")

    src_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    src_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    _create_sqlite(
        str(src_dir / "deals.db"),
        "CREATE TABLE deals (id TEXT PRIMARY KEY, title TEXT);",
        [("INSERT INTO deals VALUES (?, ?)", ("d-1", "Deal 1"))],
    )
    _create_sqlite(
        str(src_dir / "kanban.db"),
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT);",
        [("INSERT INTO tasks VALUES (?, ?)", ("t-1", "Task 1"))],
    )
    _create_sqlite(
        str(src_dir / "memory_Store.db"),
        "CREATE TABLE learnings (id TEXT PRIMARY KEY, note TEXT);",
        [("INSERT INTO learnings VALUES (?, ?)", ("l-1", "Note 1"))],
    )

    dbc.run_consolidation(
        source_dirs=[str(src_dir)],
        target_dir=str(data_dir),
        dry_run=False,
        create_backup=False,
        activate=True,
    )

    tcm = TenantContextManager(workspace_dir=str(tmp_path))
    resolved_deals = os.path.basename(tcm.resolve_active_db("deals.db", company_id="default"))
    resolved_kanban = os.path.basename(tcm.resolve_active_db("kanban.db", company_id="default"))
    resolved_mem = os.path.basename(tcm.resolve_active_db("memory.db", company_id="default"))

    assert resolved_deals == "business.db"
    assert resolved_kanban == "ops.db"
    assert resolved_mem == "memory.db"

    assert any(p.endswith("ops.db") for p in bkp.DB_TARGETS)
    assert any(p.endswith("business.db") for p in bkp.DB_TARGETS)
    assert any(p.endswith("memory.db") for p in bkp.DB_TARGETS)

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(
        bkp,
        "DB_TARGETS",
        [
            str(data_dir / "ops.db"),
            str(data_dir / "business.db"),
            str(data_dir / "memory.db"),
        ],
    )
    monkeypatch.setattr(bkp, "WORKSPACE_DIR", str(tmp_path))
    mgr = bkp.DBBackupManager(backup_dir=str(backup_dir))
    res = mgr.checkpoint_and_backup(keep_days=7)
    assert res["status"] == "success"
    assert res["backed_up_count"] == 3

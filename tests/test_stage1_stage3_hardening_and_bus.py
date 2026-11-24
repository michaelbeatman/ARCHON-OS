# -*- coding: utf-8 -*-
"""
Regressions-Tests fuer Stufe 1 (P0 Security/Data/Workflow),
Stufe 2 (One-System Event-Bus, ToolRuntime, Kanban/CRM/Tenant-Isolation)
und Stufe 3 (Multi-Turn Tool-Calling, Schema-Contracts & Media-Render im DAG).
"""

import asyncio
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =====================================================================
# STUFE 1: P0 Security, Data & Workflow Fixes
# =====================================================================


# =====================================================================
# M110 / PHASE 3: Effect-Ledger, atomare Reservierung, Leases,
# Plan-Validator, Warrant-Gate
# =====================================================================


def test_effect_ledger_unknown_requires_reconciliation(tmp_path):
    from backend.event_mesh import EffectLedger

    ledger = EffectLedger(str(tmp_path / "effects.db"))
    ledger.reserve("key-1", tool="http_post", target="http://example.invalid", payload_hash="h")
    ledger.mark_unknown("key-1", {"error": "timeout"})

    assert ledger.can_retry("key-1") is False
    # Reconciliation ohne Beweis ist nicht erlaubt.
    assert ledger.reconcile("key-1", "COMMITTED", {}) is False
    assert ledger.reconcile("key-1", "COMMITTED", {"http_status": 200}) is True
    assert ledger.can_retry("key-1") is False


def test_budget_reservation_is_atomic(tmp_path):
    from backend.role_budget_engine import BudgetBank, set_role_budget_policy

    db = str(tmp_path / "budget.db")
    set_role_budget_policy(
        "test_agent", daily_token_budget=1000, daily_cost_limit_eur=1.0,
        hard_cap_enabled=True, auto_pause_on_exceed=False, db_path=db,
    )
    bank = BudgetBank(db)
    first = bank.reserve("test_agent", estimated_tokens=800, estimated_cost_eur=0.1)
    second = bank.reserve("test_agent", estimated_tokens=800, estimated_cost_eur=0.1)

    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["error_code"] == "ROLE_TOKEN_BUDGET_EXCEEDED"
    bank.release(first["reservation_id"])
    assert bank.reserve("test_agent", estimated_tokens=800, estimated_cost_eur=0.1)["allowed"] is True


def test_lease_exclusivity_and_liveness(tmp_path):
    from backend.deadlock_supervisor import DeadlockSupervisor

    db = str(tmp_path / "kanban.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT, "
        "created_at REAL, claim_lock TEXT, claim_expires REAL, worker_pid INTEGER, "
        "last_heartbeat_at REAL, worker_started_at REAL, tenant TEXT)"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, created_at) VALUES ('t1', 'Lease', 'in_progress', 1)"
    )
    conn.commit()
    conn.close()

    supervisor = DeadlockSupervisor(db)
    first = supervisor.acquire_lease("t1", 999999)
    second = supervisor.acquire_lease("t1", 999998)

    assert first["acquired"] is True
    assert second["acquired"] is False
    assert supervisor.heartbeat("t1", first["lease_token"]) is True
    assert supervisor._pid_alive(999999) is False
    assert supervisor.release_lease("t1", first["lease_token"]) is True


def test_plan_validator_detects_cycle_before_execution():
    from backend.workflow_dag_runner import validate_dag_def

    # D13-Haertung: der Plan-Validator verlangt einen Run-Cap (fail-closed),
    # sonst ist jedes DAG ungueltig und der Zyklus-Fehler wird verdeckt.
    good = {
        "id": "good",
        "max_budget_eur": 10.0,
        "nodes": [{"id": "a", "type": "agent"}, {"id": "b", "type": "agent", "depends_on": ["a"]}],
        "edges": [{"from": "a", "to": "b", "condition": "on_success"}],
    }
    cyclic = {
        "id": "bad",
        "max_budget_eur": 10.0,
        "nodes": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}],
        "edges": [],
    }
    assert validate_dag_def(good)["valid"] is True
    result = validate_dag_def(cyclic)
    assert result["valid"] is False
    assert any("Zyklus" in e for e in result["errors"])


def test_privileged_tool_requires_warrant(monkeypatch):
    monkeypatch.setenv("ARCHON_WARRANT_SECRET", "test-warrant-secret")
    from backend.delegation_isolation import PolicyEngine

    monkeypatch.setattr(PolicyEngine, "_emit", staticmethod(lambda *args, **kwargs: None))
    engine = PolicyEngine()
    decision = engine.decide(
        agent_id="default", session_id="user:tester", tool_name="pay",
        args={"amount": 10},
    )
    assert decision["allowed"] is False
    assert decision["gate"] == "privileged_tool_requires_warrant"


def test_path_jail_rejects_bare_string_roots(tmp_path):
    from utils.path_jail import is_within, safe_path_within

    f = tmp_path / "secret.txt"
    f.write_text("ok", encoding="utf-8")

    with pytest.raises(TypeError):
        is_within(str(f), str(tmp_path))

    with pytest.raises(TypeError):
        safe_path_within(str(f), str(tmp_path))

    assert is_within(str(f), [str(tmp_path)]) is True
    assert safe_path_within(str(f), [str(tmp_path)], allow_dirs=False) == os.path.realpath(str(f))


def test_agent_router_streaming_empty_choices_guard():
    import backend.agent_router as ar_mod

    # Sicherstellen, dass streaming-Parser bei choices=[] keinen IndexError wirft
    src = Path(ar_mod.__file__).read_text(encoding="utf-8")
    assert "if not choices:" in src
    assert 'if eff_provider == "anthropic":' in src


def test_core_dispatcher_single_write_token_accounting(tmp_path):
    import core_dispatcher as cd

    db_file = str(tmp_path / "usage.db")
    with sqlite3.connect(db_file) as con:
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, total_tokens INTEGER DEFAULT 0, estimated_cost_usd REAL DEFAULT 0.0, updated_at TEXT)")
        con.execute("CREATE TABLE token_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, agent_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cost_usd REAL, created_at TEXT)")
        con.commit()

    with patch.object(cd, "USAGE_DB_PATH", db_file, create=True):
        # Test direkt gegen _log_dispatcher_usage falls DB-Pfad injizierbar, sonst Source-Check
        pass
    src = Path(cd.__file__).read_text(encoding="utf-8")
    assert "if not inserted_session:" in src


def test_role_budget_engine_single_and_subtask_ids(tmp_path):
    from backend.role_budget_engine import allocate_task_budget_to_subagents

    db_path = str(tmp_path / "budget.db")
    single = allocate_task_budget_to_subagents(
        "t-100", total_token_budget=10000, subtasks=[], total_cost_limit_eur=2.5, db_path=db_path
    )
    assert len(single["allocations"]) == 1
    assert single["allocations"][0]["task_id"] == "t-100"
    assert single["allocations"][0]["cost_limit_eur"] == 2.5

    multi = allocate_task_budget_to_subagents(
        "t-200",
        total_token_budget=10000,
        subtasks=[{"role": "researcher"}, {"role": "writer"}],
        total_cost_limit_eur=3.0,
        db_path=db_path,
    )
    assert len(multi["allocations"]) == 2
    assert multi["allocations"][0]["subtask_id"] == "t-200-sub1"
    assert multi["allocations"][1]["subtask_id"] == "t-200-sub2"


def test_workflow_templates_preserves_quality_gate_and_passthru(tmp_path):
    from backend.workflow_templates import _DAG_NODE_PASSTHROUGH_KEYS, _build_dag_def_from_template

    for k in ("channel", "save_to_showroom", "max_revisions", "min_quality_score", "quality_gate", "max_turns", "output_schema", "media_config"):
        assert k in _DAG_NODE_PASSTHROUGH_KEYS

    tpl = {
        "id": "tpl-test",
        "title": "Test",
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "title": "Draft",
                "prompt": "Schreibe {{topic}}",
                "channel": "linkedin",
                "save_to_showroom": True,
                "max_revisions": 2,
                "min_quality_score": 80,
                "max_turns": 2,
                "output_schema": {"required": ["headline", "body"]},
            }
        ],
        "edges": [],
    }
    dag = _build_dag_def_from_template(tpl, {"topic": "KI"}, {"n1": "kt-1"})
    n1 = dag["nodes"][0]
    assert n1["channel"] == "linkedin"
    assert n1["save_to_showroom"] is True
    assert n1["max_revisions"] == 2
    assert n1["min_quality_score"] == 80
    assert n1["max_turns"] == 2
    assert n1["output_schema"] == {"required": ["headline", "body"]}


def test_treasury_approve_reject_atomic_and_balance_check(tmp_path, monkeypatch):
    import backend.treasury_engine as te

    db_file = str(tmp_path / "treasury.db")
    monkeypatch.setattr(te, "_resolve_treasury_db", lambda: db_file)
    te.init_treasury_db()
    acc = te.upsert_account({"name": "Ops Konto", "balance_eur": 100.0})
    tx = te.request_payment({"account_id": acc["id"], "amount": 250.0, "recipient": "Vendor GmbH", "purpose": "Zu teuer"})

    # Guthaben reicht nicht -> ValueError.
    # P0 (Audit 23.11.2026): Zahlungen sind ohne Passkey-Konfiguration jetzt
    # fail-closed. Dieser Test prueft die Guthaben-Atomaritaet, nicht die
    # Passkey-Pflicht — daher hier explizit als verifiziert uebergeben.
    with pytest.raises(ValueError, match="insufficient_balance"):
        te.approve_payment(tx["id"], "admin", passkey_verified=True)

    # Ablehnen funktioniert exakt einmal
    rej = te.reject_payment(tx["id"], "Budget stop", "admin")
    assert rej["status"] == "rejected"
    with pytest.raises(ValueError):
        te.reject_payment(tx["id"], "Doppelt", "admin")


def test_mission_control_does_not_invent_assignee_or_model():
    import archon.core.mission_control as mc

    src = Path(mc.__file__).read_text(encoding="utf-8")
    assert 'agent_id = r["assignee"] or ""' in src
    assert '"model": r["model_override"] or ""' in src


# =====================================================================
# STUFE 2: One-System (Event-Bus, ToolRuntime, Kanban/CRM/PocketBase)
# =====================================================================


def test_event_bus_hitl_approve_and_replay(tmp_path, monkeypatch):
    import backend.workflow_scheduler as ws

    db_file = str(tmp_path / "sched.db")
    monkeypatch.setattr(ws, "SCHEDULES_DB_PATH", db_file)

    ws.init_schedules_db()
    ws.upsert_event_policy("watchdog", "all", policy="require_hitl", max_per_min=10)
    ws.upsert_schedule({
        "template_id": "tpl-research-1",
        "trigger_type": "watchdog",
        "watchdog_keyword": "ki-trend",
        "enabled": True,
    })

    created_decisions = []
    monkeypatch.setattr(ws, "_create_hitl_decision", lambda *a, **kw: created_decisions.append(a[0]))

    triggered = []
    monkeypatch.setattr(ws, "_execute_schedule_row", lambda conn, row, now, extra_inputs=None: (triggered.append(row["id"]) or {"run_id": "run-123"}))

    # 1. Dispatch wird wegen require_hitl geparkt
    res1 = ws.dispatch_workflow_event(source="watchdog", event_type="finding", title="Neuer KI-Trend", summary="Details")
    assert res1["status"] == "awaiting_hitl"
    assert res1["triggered"] == []
    assert len(created_decisions) == 1

    # 2. Nach Owner-Freigabe startet approve_and_replay_hitl_event den Workflow wirklich
    res2 = ws.approve_and_replay_hitl_event(res1["event_id"])
    assert res2["status"] == "triggered"
    assert len(res2["triggered"]) == 1
    assert len(triggered) == 1


def test_tool_runtime_enforces_m75_m89_and_m90(tmp_path):
    from backend.tool_runtime import enforce_tool_execution
    from backend.tool_warrants import issue_warrant, verify_warrant_for_call

    # 1. M90 Warrant: NaN und Path-Traversal ablehnen
    war = issue_warrant(
        session_id="sess-1",
        allowed_tools=["read_file", "pay_invoice"],
        constraints={"max_amount": 50.0, "allowed_path_prefixes": ["01_PROJEKTE/"]},
        secret="test-secret-key-32-chars-minimum!!",
    )
    assert verify_warrant_for_call(war, "sess-1", "pay_invoice", {"amount": float("nan")}, secret="test-secret-key-32-chars-minimum!!")["allowed"] is False
    assert verify_warrant_for_call(war, "sess-1", "read_file", {"path": "../etc/passwd"}, secret="test-secret-key-32-chars-minimum!!")["allowed"] is False
    assert verify_warrant_for_call(war, "sess-1", "read_file", {"path": "01_PROJEKTE/demo.md"}, secret="test-secret-key-32-chars-minimum!!")["allowed"] is True

    # 2. ToolRuntime blockiert leere tool_name
    bad = enforce_tool_execution(agent_id="researcher", session_id="sess-1", tool_name="")
    assert bad["allowed"] is False


def test_crm_service_decoupled_from_pocketbase(tmp_path, monkeypatch):
    import backend.crm_service as crm

    assert "pocketbase" not in crm._DEFAULT_CRM_SQLITE_PATH.lower()
    assert crm._DEFAULT_CRM_SQLITE_PATH.endswith("business.db")

    test_biz = str(tmp_path / "business.db")
    monkeypatch.setattr(crm, "CRM_SQLITE_PATH", test_biz)
    conn = crm._get_sqlite_conn()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "kontakte" in tables
    finally:
        conn.close()


def test_kanban_router_uses_resolve_active_db(monkeypatch):
    import archon.routers.kanban as kb
    from backend.tenant_context import tenant_context

    called = []
    monkeypatch.setattr(tenant_context, "resolve_active_db", lambda fname, cid=None: (called.append(fname) or "/tmp/ops.db"))
    res = kb._resolve_active_kanban_db()
    assert res == "/tmp/ops.db"
    assert called == ["kanban.db"]


# =====================================================================
# STUFE 3: Multi-Turn Tool-Loop, Schema Contracts & Media-Render Node
# =====================================================================


def test_dag_runner_multi_turn_tool_loop_and_output_schema(tmp_path):
    from backend.workflow_dag_runner import default_agent_node_executor

    responses = [
        {"status": "success", "content": '{"tool_call": {"name": "archon__get_system_metrics", "args": {}}}', "input_tokens": 10, "output_tokens": 10, "model": "mock"},
        # Zweite Antwort verletzt erst absichtlich das Schema -> triggert Repair-Retry!
        {"status": "success", "content": "Kein JSON", "input_tokens": 10, "output_tokens": 10, "model": "mock"},
        # Dritte Antwort erfuellt Schema
        {"status": "success", "content": '{"headline": "Archon 2026", "score": 95}', "input_tokens": 10, "output_tokens": 10, "model": "mock"},
    ]

    async def _run():
        with patch("core_dispatcher.dispatch_to_omniroute_or_container", side_effect=responses), \
             patch("backend.tool_runtime.execute_agent_tool", AsyncMock(return_value={"status": "success", "result": {"cpu": 12}})), \
             patch("backend.workflow_dag_runner._update_kanban_task_status"):
            return await default_agent_node_executor(
                {
                    "id": "n-tool",
                    "type": "agent",
                    "title": "System Check",
                    "prompt": "Pruefe System",
                    "allowed_tools": ["archon__get_system_metrics"],
                    "max_turns": 2,
                    "output_schema": {"required": ["headline", "score"]},
                },
                {},
            )

    out = asyncio.run(_run())
    assert out["status"] == "success"
    assert len(out["tool_trace"]) == 1
    assert out["tool_trace"][0]["tool"] == "archon__get_system_metrics"
    assert out["parsed_output"] == {"headline": "Archon 2026", "score": 95}


def test_dag_runner_media_render_node():
    from backend.workflow_dag_runner import default_agent_node_executor

    async def _run():
        with patch("backend.content_machine.generate_video_clip_matrix", return_value={"clips": [{"title": "Clip 1"}]}), \
             patch("backend.workflow_dag_runner._update_kanban_task_status"):
            return await default_agent_node_executor(
                {
                    "id": "n-media",
                    "type": "media_render",
                    "title": "Shorts Render",
                    "channel": "youtube_shorts",
                },
                {"n-script": {"content": "Hook: KI Agenten. Body: 3 Fakten. CTA: Folge mir."}},
            )

    out = asyncio.run(_run())
    assert out["status"] == "success"
    assert out["media_matrix"]["clips"][0]["title"] == "Clip 1"


def test_workflow_node_plugins_vst_discovery_and_execution(tmp_path, monkeypatch):
    import backend.workflow_node_plugins as wnp
    from backend.workflow_dag_runner import default_agent_node_executor

    # 1. Core-Plugins inkl. FFmpeg, KinoCut, TTS, Suno, ImageGen, CalendarPublish vorhanden
    core_ids = {p["plugin_id"] for p in wnp.list_workflow_node_plugins()}
    for expected in ("ffmpeg", "kinocut", "tts", "suno", "image_gen", "calendar_publish"):
        assert expected in core_ids

    # 2. Deklaratives 3rd-Party-Plugin ("VST"-Pattern) aus plugins/workflow_nodes/*.json
    pdir = tmp_path / "workflow_nodes"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "elevenlabs_custom.json").write_text(
        json.dumps({
            "plugin_id": "elevenlabs_custom",
            "label": "ElevenLabs Dubbing",
            "adapter": "http",
            "http_endpoint": "https://api.example.com/dub",
            "params_schema": [{"key": "target_lang", "label": "Sprache", "type": "select", "default": "de", "options": ["de", "en"]}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(wnp, "PLUGINS_NODES_DIR", str(pdir))
    assert wnp.get_workflow_node_plugin("elevenlabs_custom")["third_party"] is True

    # 3. Upstream-Template-Aufloesung + FFmpeg Dry-Run im DAG-Runner
    async def _run_ffmpeg():
        with patch("backend.workflow_dag_runner._update_kanban_task_status"):
            return await default_agent_node_executor(
                {
                    "id": "n-ff",
                    "type": "ffmpeg",
                    "title": "Clip Cut",
                    "plugin_params": {
                        "mode": "aspect_9_16",
                        "input_path": "{{upstream.n_prev.video_path}}",
                        "dry_run": True,
                    },
                },
                {"n_prev": {"video_path": str(tmp_path / "raw.mp4")}},
            )

    res = asyncio.run(_run_ffmpeg())
    # Tool-Output-Firewall markiert Plugin-Ergebnisse als untrusted (Audit-Fix).
    assert "planned" in str(res["status"]) or "success" in str(res["status"])
    assert res["planned_only"] is True
    assert "9:16" in res["command"] or "crop=" in res["command"]


def test_workflow_node_marketplace_install_uninstall_and_template_save(tmp_path, monkeypatch):
    import backend.workflow_node_plugins as wnp
    import backend.workflow_templates as wt

    pdir = tmp_path / "workflow_nodes"
    monkeypatch.setattr(wnp, "PLUGINS_NODES_DIR", str(pdir))

    catalog = wnp.list_marketplace_plugins()
    el = next(x for x in catalog if x["plugin_id"] == "elevenlabs")
    assert el["installed"] is False
    assert el["category"] == "audio"

    wnp.install_marketplace_plugin("elevenlabs")
    assert wnp.get_workflow_node_plugin("elevenlabs") is not None
    assert next(x for x in wnp.list_marketplace_plugins() if x["plugin_id"] == "elevenlabs")["installed"] is True

    wnp.uninstall_marketplace_plugin("elevenlabs")
    assert wnp.get_workflow_node_plugin("elevenlabs") is None

    # Template-Save behaelt Plugin-Typ und header_image bei
    custom_file = tmp_path / "custom_tpls.json"
    monkeypatch.setattr(wt, "CUSTOM_TEMPLATES_PATH", str(custom_file))
    monkeypatch.setattr(wt, "_CUSTOM_TEMPLATES_CORRUPT", False)
    saved = wt.save_workflow_template({
        "title": "Media Pipeline",
        "header_image": "https://example.com/banner.png",
        "nodes": [{"id": "s1", "type": "ffmpeg", "title": "Render", "plugin_params": {"mode": "aspect_9_16"}}],
    })
    assert saved["header_image"] == "https://example.com/banner.png"
    assert saved["nodes"][0]["type"] == "ffmpeg"
    assert saved["nodes"][0]["plugin_params"]["mode"] == "aspect_9_16"


def test_mcp_orchestrator_workflow_builder_tools(tmp_path, monkeypatch):
    import backend.workflow_templates as wt
    from scripts.archon_mcp_server import ArchonMcpServer

    custom_file = tmp_path / "custom_tpls.json"
    monkeypatch.setattr(wt, "CUSTOM_TEMPLATES_PATH", str(custom_file))
    monkeypatch.setattr(wt, "_CUSTOM_TEMPLATES_CORRUPT", False)

    srv = ArchonMcpServer()
    names = {t["name"] for t in srv.get_tool_definitions()}
    assert "archon__list_workflow_node_plugins" in names
    assert "archon__create_workflow_template" in names
    assert "archon__run_workflow_template" in names

    plugs = srv.execute_tool("archon__list_workflow_node_plugins", {})
    assert plugs["status"] == "success"
    assert any(p["plugin_id"] == "ffmpeg" for p in plugs["plugins"])

    created = srv.execute_tool(
        "archon__create_workflow_template",
        {
            "title": "Orchestrator Auto Pipeline",
            "category": "Content & Marketing",
            "nodes": [
                {"id": "s1", "type": "research", "title": "Recherche", "prompt": "Recherchiere {{topic}}"},
                {"id": "s2", "type": "tts", "title": "Voiceover", "depends_on": ["s1"]},
            ],
        },
    )
    assert created["status"] == "success"
    assert created["template"]["nodes"][1]["type"] == "tts"


def test_llm_kernel_unification_and_role_budget_conn_close(tmp_path):
    from backend.llm_kernel import AUTO_MODEL_MAP, estimate_model_cost_usd, finalize_llm_output, resolve_auto_model
    import backend.role_budget_engine as rbe

    assert resolve_auto_model("auto/best-coding") == AUTO_MODEL_MAP["auto/best-coding"]
    assert estimate_model_cost_usd("deepseek/deepseek-chat", 1000, 1000) > 0.0

    # finalize_llm_output darf bei rehydrate_text-Dict nicht crashen und maskiert Secrets
    dummy_key = "sk-" + ("1234567890abcdef" * 2)
    out = finalize_llm_output(
        f"Hallo Welt {dummy_key}",
        session_id="sess_test_kernel",
    )
    assert "sk-123456" not in out

    # role_budget_engine._get_conn() schliesst echte sqlite3.Connection beim Verlassen
    db_file = str(tmp_path / "budget.db")
    with rbe._get_conn(db_file) as conn:
        conn.execute("SELECT 1").fetchone()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_safe_http_blocks_redirects():
    from utils.safe_http import _RejectAllRedirectsHandler
    import urllib.error

    handler = _RejectAllRedirectsHandler()
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com")
    assert exc_info.value.code == 302


def test_unified_kanban_workflow_materialization(tmp_path, monkeypatch):
    import sqlite3
    import backend.workflow_templates as wt
    import backend.operations_api as ops

    ops_db = str(tmp_path / "ops.db")
    with sqlite3.connect(ops_db) as _c:
        _c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT,
                body TEXT,
                assignee TEXT,
                status TEXT,
                priority INTEGER,
                created_by TEXT,
                created_at TEXT,
                project_id TEXT,
                block_kind TEXT
            )
        """)
        _c.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                kind TEXT,
                actor TEXT,
                payload TEXT,
                created_at TEXT
            )
        """)
        _c.commit()
    monkeypatch.setattr(ops, "_resolve_kanban_db_path", lambda: ops_db)
    monkeypatch.setattr(ops, "_get_active_kanban_db_path", lambda _cid=None: ops_db)
    monkeypatch.setattr(ops, "_KANBAN_JOURNAL_INIT", set())

    tpl = {
        "id": "tpl_unit",
        "title": "Content {{topic}}",
        "category": "Content & Marketing",
        "nodes": [
            {
                "id": "n1",
                "type": "agent",
                "title": "Draft {{topic}}",
                "prompt": "Schreibe ueber {{topic}}",
                "expected_output": "Summary zu {{topic}}",
                "plugin_params": {"text": "Intro {{topic}}"},
            },
            {
                "id": "n2",
                "type": "tts",
                "title": "Audio {{topic}}",
                "depends_on": ["n1"],
                "plugin_params": {"text": "{{upstream.n1.content}} fuer {{topic}}"},
            },
        ],
        "edges": [{"from": "n1", "to": "n2", "condition": "on_success"}],
    }
    monkeypatch.setattr(wt, "get_workflow_template", lambda _tid: tpl)

    mat = wt.materialize_workflow_to_kanban("tpl_unit", inputs={"topic": "AI Agents"})
    run_id = mat["run_id"]
    dag = mat.get("dag") or wt._build_dag_def_from_template(tpl, {"topic": "AI Agents"}, {"n1": "t1", "n2": "t2"})
    assert dag["nodes"][0]["plugin_params"]["text"] == "Intro AI Agents"
    assert dag["nodes"][0]["expected_output"] == "Summary zu AI Agents"
    assert dag["nodes"][1]["plugin_params"]["text"] == "{{upstream.n1.content}} fuer AI Agents"

    with sqlite3.connect(ops_db) as conn:
        conn.row_factory = sqlite3.Row
        parent = conn.execute("SELECT * FROM tasks WHERE id = ?", (run_id,)).fetchone()
        assert parent is not None
        assert "[Workflow]" in parent["title"]
        links_sub = conn.execute(
            "SELECT * FROM task_links WHERE parent_id = ? AND kind = 'subtask'",
            (run_id,),
        ).fetchall()
        assert len(links_sub) == 2
        links_blk = conn.execute("SELECT * FROM task_links WHERE kind = 'blocks'").fetchall()
        assert len(links_blk) == 1


def test_tool_runtime_mcp_error_and_audit_record(monkeypatch):
    import backend.tool_runtime as tr

    called = {}
    monkeypatch.setattr(
        "backend.audit_log.chained_audit_log.record_event",
        lambda **kw: called.update(kw) or {"status": "ok"},
    )
    tr._emit_tool_event("tool.blocked", {"agent_id": "a1", "tool_name": "t1"})
    assert called.get("category") == "tool_runtime"
    assert called.get("action") == "tool_blocked"

    class _FakeMcp:
        def execute_tool(self, _name, _args):
            return {"status": "error", "message": "Kaputt"}

    monkeypatch.setattr("backend.tool_runtime.enforce_tool_execution", lambda **_kw: {"allowed": True})
    monkeypatch.setattr(
        "backend.plugin_manager.get_plugin_manager",
        lambda: type("PM", (), {"get_all_exported_tools": lambda self: []})(),
    )
    monkeypatch.setattr("scripts.archon_mcp_server.ArchonMcpServer", _FakeMcp)
    res = asyncio.run(tr.execute_agent_tool(tool_name="archon__broken", args={}))
    assert res["status"] == "error"
    assert "Kaputt" in res["error"]


def test_workflow_plugins_fixes_and_vst2_http(tmp_path, monkeypatch):
    import backend.workflow_node_plugins as wnp

    # 1. FFmpeg extract_audio -> libmp3lame bei default audio_codec="aac" & output_format="mp3"
    ff_res = asyncio.run(
        wnp._run_ffmpeg_plugin(
            {"mode": "extract_audio", "output_format": "mp3", "audio_codec": "aac", "input_path": str(tmp_path / "in.mp4"), "dry_run": True},
            {"id": "n-ff", "workflow_id": "wf_test"},
            {},
        )
    )
    assert ff_res["status"] in ("planned", "success")
    assert "libmp3lame" in ff_res["command"]

    # 2. KinoCut standalone (ohne vorherigen Content-Campaign-Eintrag)
    kc_res = asyncio.run(
        wnp._run_kinocut_plugin(
            {"clip_count": 2, "target_platform": "youtube_shorts", "dry_run": True},
            {"id": "n-kc", "workflow_id": "wf_standalone_test", "prompt": "Test Video Skript fuer zwei Clips."},
            {},
        )
    )
    assert kc_res["status"] == "success"
    assert kc_res["clip_count"] == 2

    # 3. CalendarPublish nutzt start/end/notes
    captured_ev = {}
    monkeypatch.setattr(
        "backend.operations_calendar.operations_calendar.create_event",
        lambda payload: captured_ev.update(payload) or {"id": "cal_unit_1"},
    )
    cal_res = asyncio.run(
        wnp._run_calendar_publish_plugin(
            {"title": "Launch Post", "channel": "linkedin", "notes": "Check CTA"},
            {"id": "n-cal", "workflow_id": "wf_cal"},
            {},
        )
    )
    assert cal_res["calendar_event_id"] == "cal_unit_1"
    assert "start" in captured_ev and "end" in captured_ev and "notes" in captured_ev

    # 4. VST 2.0 HTTP Adapter: fehlender Env-Key -> planned_only; gesetzter Env-Key -> Binary-Download
    pdir = tmp_path / "workflow_nodes"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "custom_audio_vst.json").write_text(
        json.dumps({
            "plugin_id": "custom_audio_vst",
            "label": "Custom Audio VST",
            "category": "audio",
            "adapter": "http",
            "http_endpoint": "https://api.example.com/render",
            "auth": {"type": "bearer", "env_var": "UNIT_VST_KEY"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(wnp, "PLUGINS_NODES_DIR", str(pdir))
    monkeypatch.delenv("UNIT_VST_KEY", raising=False)
    monkeypatch.setattr("backend.tool_runtime.enforce_tool_execution", lambda **_kw: {"allowed": True})

    # Custom Plugin erscheint in Marketplace-Liste
    mkt = wnp.list_marketplace_plugins()
    assert any(p["plugin_id"] == "custom_audio_vst" and p.get("custom") is True for p in mkt)

    dry = asyncio.run(wnp.execute_workflow_node_plugin("custom_audio_vst", {"id": "n1", "workflow_id": "wf_vst"}, {}))
    assert dry["planned_only"] is True
    assert dry["missing_env"] == "UNIT_VST_KEY"

    monkeypatch.setenv("UNIT_VST_KEY", "secret-token-123")
    monkeypatch.setattr(
        "utils.safe_http.safe_http_request",
        lambda *_a, **_kw: (200, {"content-type": "audio/mpeg"}, b"ID3MOCKAUDIO"),
    )
    live = asyncio.run(wnp.execute_workflow_node_plugin("custom_audio_vst", {"id": "n1", "workflow_id": "wf_vst"}, {}))
    assert live["status"] == "success"
    assert live["audio_path"].endswith(".mp3")
    assert os.path.isfile(live["audio_path"])


def test_dag_runner_schema_preserved_and_event_driven_recovery(tmp_path):
    from backend.workflow_dag_runner import default_agent_node_executor, run_workflow_dag

    # 1. output_schema JSON darf durch Anti-Slop nicht zu Prosa ueberschrieben werden
    async def _run_schema():
        with patch(
            "core_dispatcher.dispatch_to_omniroute_or_container",
            AsyncMock(return_value={
                "status": "success",
                "content": '{"hook": "Stopp — 3 Fehler", "body": "Konkreter Text.", "cta": "Folge mir."}',
                "input_tokens": 5,
                "output_tokens": 5,
            }),
        ), patch("backend.workflow_dag_runner._update_kanban_task_status"):
            return await default_agent_node_executor(
                {
                    "id": "n-schema",
                    "type": "agent",
                    "title": "LinkedIn Post",
                    "channel": "linkedin",
                    "quality_gate": True,
                    "output_schema": {"required": ["hook", "body", "cta"]},
                },
                {},
            )

    s_out = asyncio.run(_run_schema())
    assert s_out["status"] == "success"
    assert isinstance(s_out["parsed_output"], dict)
    assert s_out["parsed_output"]["hook"] == "Stopp — 3 Fehler"

    # 2. Event-Driven Ready-Queue + on_failure Recovery
    db_file = str(tmp_path / "dag_event.db")
    order = []

    async def _exec(node, _up):
        nid = node["id"]
        if nid == "slow":
            await asyncio.sleep(0.15)
            order.append("slow")
            return {"status": "success", "content": "slow done"}
        if nid == "fast":
            await asyncio.sleep(0.01)
            order.append("fast")
            return {"status": "error", "error": "boom"}
        if nid == "fast_recover":
            order.append("fast_recover")
            return {"status": "success", "content": "recovered"}
        return {"status": "success", "content": "ok"}

    dag = {
        "id": "wf_event_test",
        # D13-Haertung: Run-Cap ist Pflicht (fail-closed).
        "max_budget_eur": 10.0,
        # D13: eigene Trajectory pro Testlauf (globaler Hop-Cap in ops.db).
        "root_ticket_id": f"wf-event-{uuid.uuid4().hex[:12]}",
        "nodes": [
            {"id": "slow", "type": "agent"},
            {"id": "fast", "type": "agent"},
            {"id": "fast_recover", "type": "agent", "depends_on": ["fast"]},
        ],
        "edges": [
            {"from": "fast", "to": "fast_recover", "condition": "on_failure"},
        ],
    }
    res = asyncio.run(run_workflow_dag(dag, executor_fn=_exec, db_path=db_file))
    assert res["status"] == "completed"
    # fast_recover muss VOR slow laufen (event-driven, kein Wave-Barrier)
    assert order.index("fast_recover") < order.index("slow")

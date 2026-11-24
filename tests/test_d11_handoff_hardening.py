"""D11 (Welle 2) — Regressionstests fuer Handoff-Integritaet.

Deckt ab:
1. HandoffEnvelope (Pydantic v2, extra=forbid) + HMAC-SHA256 + Kuerzungsmarker,
2. Kanban→Agent: Delegations-Payload aus task_events.created ueber den
   Worker-Start im strukturierten Dispatch-Kontext wiederfindbar,
3. prompt_registry.version/Normalisierung + llm_kernel-Dispatch-Return,
4. mark_truncated() in der Fan-in-/Synthese-Kette.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_d11_handoff_envelope_strict_hmac_and_marker(tmp_path):
    from backend.handoff_desk import (
        HandoffDesk, HandoffEnvelope, mark_truncated,
    )

    # Pflichtfelder inkl. trace/session/correlation; extra=forbid.
    with pytest.raises(ValidationError):
        HandoffEnvelope.model_validate({
            "task_id": "t", "from_agent": "a", "to_agent": "b",
            "deliverables": {}, "acceptance_criteria": "K",
            "message_id": "m", "reply_to": "", "shadow": "x",
        })
    with pytest.raises(ValidationError):
        HandoffEnvelope.model_validate({
            "task_id": "t", "from_agent": "a", "to_agent": "b",
            "deliverables": {}, "acceptance_criteria": "K",
            "message_id": "m", "reply_to": "",
            "correlation_id": "c", "trace_id": "trace",  # session_id fehlt
        })

    desk = HandoffDesk(db_path=str(tmp_path / "handoff.db"))
    created = desk.create_handoff(
        "t-1", "delegator", "worker", {"result": "ok", "status": "done"}, "Kriterium",
        trace_id="trace-1", session_id="session-1", correlation_id="task:t-1",
    )
    assert created["payload_hash"].startswith("hmac-sha256:")
    assert created["trace_id"] == "trace-1"
    assert created["session_id"] == "session-1"
    assert desk.verify_payload_hash(created["handoff_id"]) is True
    assert desk.accept_handoff(created["handoff_id"], "worker")["status"] == "accepted"

    # Manipulation der Deliverables muss auffallen.
    with desk._get_conn() as conn:
        conn.execute(
            "UPDATE agent_handoffs SET deliverables_json = ? WHERE id = ?",
            (json.dumps({"result": "manipuliert", "status": "done"}), created["handoff_id"]),
        )
        conn.commit()
    assert desk.verify_payload_hash(created["handoff_id"]) is False

    long = "A" * 5000
    marked = mark_truncated(long, 500, artifact="artifact.md")
    assert "gekürzt" in marked and "4500 Zeichen" in marked
    assert "artifact.md" in marked
    assert mark_truncated("kurz", 500) == "kurz"


def test_d11_kanban_delegation_payload_survives_worker_start(tmp_path, monkeypatch):
    import backend.operations_api as ops

    db_path = tmp_path / "kanban.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE tasks (
        id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT,
        priority TEXT, created_by TEXT, created_at TEXT, started_at TEXT, completed_at TEXT,
        model_override TEXT, project_id TEXT, block_kind TEXT,
        token_budget INTEGER DEFAULT 0, proof_command TEXT DEFAULT '',
        consecutive_failures INTEGER DEFAULT 0, tenant_id TEXT DEFAULT 'default',
        result TEXT DEFAULT ''
    )""")
    conn.execute(
        "INSERT INTO tasks (id, title, body, assignee, status, priority, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("task-d11", "Delegierter Auftrag", "Anzeige-Kopie", "worker", "todo", "1", "2026-11-24"),
    )
    conn.execute("CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER)")
    payload = {
        "title": "Delegierter Auftrag", "assignee": "worker", "via": "delegation_engine_v2",
        "delegator": "delegator", "tgt_session_id": "sess-tgt",
        "origin_session_id": "sess-origin", "delegation_chain": ["delegator", "worker"],
        "reasoning_level": "high", "acceptance_criteria": "Tests gruen",
        "reply_to": "handoff-1", "correlation_id": "trace-abc", "trace_id": "trace-abc",
    }
    conn.execute(
        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
        ("task-d11", "created", json.dumps(payload), 1),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ops, "_get_active_kanban_db_path", lambda company_id=None: str(db_path))
    monkeypatch.setattr(ops, "_DEFAULT_KANBAN_DB_PATH", str(db_path))
    monkeypatch.setattr(ops, "_KANBAN_JOURNAL_INIT_DBS", set())
    monkeypatch.setattr(ops, "_load_profiles_map", lambda: {})
    monkeypatch.setattr(ops, "_resolve_task_obsidian_rel", lambda task_id: "")
    monkeypatch.setattr(ops, "_load_kanban_meta", lambda: {})
    monkeypatch.setattr(ops, "_sync_to_memory_bridge", lambda *a, **k: None)
    monkeypatch.setattr("backend.model_routing.autonomy_level", lambda area: "autonomous")

    class _Cancel:
        def register_task(self, *a, **k): pass
        def check(self): pass
        def cancel(self, *a, **k): pass

    monkeypatch.setattr("backend.cancellation.get_token", lambda key: _Cancel())
    monkeypatch.setattr(
        "backend.kanban_verifier.verify_card_completion",
        lambda **k: {"status": "done", "verified": True},
    )
    monkeypatch.setattr("backend.post_task_pipeline.get_vault_dir", lambda: str(tmp_path / "vault"))

    captured = {}

    async def _fake_dispatch(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "content": "erledigt", "effective_prompt_info": {"version": "7"}}

    import core_dispatcher
    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch)

    loaded = ops._kanban_load_task_sync("task-d11")
    assert loaded["_delegation_payload"]["delegation_chain"] == ["delegator", "worker"]
    assert loaded["_delegation_payload"]["acceptance_criteria"] == "Tests gruen"
    assert loaded["_delegation_payload"]["origin_session_id"] == "sess-origin"

    asyncio.run(ops._execute_kanban_task_inner("task-d11"))
    assert captured, "Worker hat keinen Dispatch ausgefuehrt"
    prompt = captured["system_prompt"]
    assert "[STRUKTURIERTE_DELEGATION_JSON]" in prompt
    block = json.loads(prompt.split("[STRUKTURIERTE_DELEGATION_JSON]\n", 1)[1]
                       .split("\n[/STRUKTURIERTE_DELEGATION_JSON]", 1)[0])
    assert block["delegation_chain"] == ["delegator", "worker"]
    assert block["acceptance_criteria"] == "Tests gruen"
    assert block["origin_session_id"] == "sess-origin"
    assert captured["reasoning_level"] == "high"

    # Persistierte Ereignisse tragen den Kuerzungsmarker, wenn der Text laenger ist.
    with sqlite3.connect(str(db_path)) as c:
        summary = c.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='completed' ORDER BY rowid DESC LIMIT 1",
            ("task-d11",),
        ).fetchone()[0]
    assert "truncated" in summary


def test_d11_prompt_registry_version_and_llm_kernel_result(monkeypatch):
    from backend.prompt_registry import PromptRegistry
    import backend.llm_kernel as kernel
    import core_dispatcher

    reg = PromptRegistry()
    info = reg.get_effective_prompt("d11-test-agent")
    assert "version" in info and info["version"] == str(info["version_num"])
    assert info["prompt_version"] == info["version"]
    assert info["prompt_hash"]

    async def _fake_dispatch(**kwargs):
        # Simuliert einen Dispatch ohne effective_prompt_info.
        return {"status": "blocked", "content": "blockiert"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", _fake_dispatch)
    result = asyncio.run(kernel.dispatch_llm(
        agent_id="d11-test-agent", prompt="p", session_id="sess-1", task_id="task-1",
    ))
    assert result["effective_prompt_info"]["agent_id"] == "d11-test-agent"
    assert result["prompt_version_info"] == result["effective_prompt_info"]
    assert result["session_id"] == "sess-1"
    assert result["correlation_id"] == "task-1"
    assert result["trace_id"]


def test_d11_fan_in_uses_real_agent_ids_and_marked_truncation():
    import archon.core.orchestration as orch

    src = (REPO_ROOT / "archon" / "core" / "orchestration.py").read_text(encoding="utf-8")
    assert "work_package_{idx + 1}" not in src
    assert "validate_debate_statements(fan_statements)" in src
    assert "mark_truncated(" in src
    assert "fan_in_child_ids" in src
    assert orch.mark_truncated("x" * 100, 10, artifact="a").count("gekürzt") == 1

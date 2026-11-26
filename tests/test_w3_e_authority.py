# -*- coding: utf-8 -*-
"""W3-E — Entscheidungs-Hoheit (D14-H1 + D14-M1..M5).

Fail-closed Regressionstests gegen den Produktivpfad. Kein Replay, keine
PostgreSQL-Migration, keine fremden Dateien.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------------------------------------------------------------------------
# D14-M1 — Tier-Veto / tie-break
# ---------------------------------------------------------------------------

def _stmt(agent_id, content, tier=None):
    return {"agent_id": agent_id, "content": content, "tier": tier}


def _split_lead_case():
    # 1 Executive NO, 1 Executive YES, 2 Leads NO, 6 Specialists YES.
    stmts = [
        _stmt("ceo", "KEIN CONSENSUS", "executive"),
        _stmt("default", "KONSENS_ERREICHT", "executive"),
    ]
    stmts += [_stmt("cloud_architect", "WIDERSPRUCH", "lead") for _ in range(2)]
    stmts += [_stmt(f"dev-{i}", "ZUSTIMME", "specialist") for i in range(6)]
    return stmts


def test_m1_lower_tier_veto_is_not_swallowed_by_split_higher_tier():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus(_split_lead_case())
    assert res["yes_votes"] == 7
    assert res["total_votes"] == 10
    assert res["consensus_reached"] is False
    assert res["verdict"] == "NO_CONSENSUS_BY_AUTHORITY"
    assert res["applied_tie_break"] == "highest_tier:lead:no"
    assert res["veto_by"] == "cloud_architect"


def test_m1_policy_veto_also_records_applied_tie_break():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        _stmt("ceo", "ZUSTIMME", "executive"),
        _stmt("dev-1", "POLICY_VIOLATION", "specialist"),
    ])
    assert res["verdict"] == "NO_CONSENSUS_POLICY_VIOLATION"
    assert res["applied_tie_break"] == "policy_veto"


def test_m1_tie_break_parameter_is_enforced_not_decorative():
    from backend.consensus_gate import resolve_debate_consensus

    stmts = [
        _stmt("ceo", "ZUSTIMME", "executive"),
        _stmt("dev-1", "WIDERSPRUCH", "specialist"),
        _stmt("dev-2", "WIDERSPRUCH", "specialist"),
        _stmt("dev-3", "WIDERSPRUCH", "specialist"),
    ]
    authority = resolve_debate_consensus(stmts)
    assert authority["verdict"] == "CONSENSUS_REACHED_BY_AUTHORITY"
    assert authority["applied_tie_break"] == "highest_tier:executive:yes"

    blocked = resolve_debate_consensus(stmts, tie_break="no_consensus")
    assert blocked["consensus_reached"] is False
    assert blocked["verdict"] == "NO_CONSENSUS"
    assert blocked["tie_break_rule"] == "no_consensus"

    with pytest.raises(ValueError, match="tie_break"):
        resolve_debate_consensus(stmts, tie_break="whatever")


def test_m1_unresolved_split_sets_applied_tie_break():
    from backend.consensus_gate import resolve_debate_consensus

    res = resolve_debate_consensus([
        _stmt("ceo", "ZUSTIMME", "executive"),
        _stmt("default", "WIDERSPRUCH", "executive"),
        _stmt("cloud_architect", "ZUSTIMME", "lead"),
        _stmt("hermes_orchestrator", "WIDERSPRUCH", "lead"),
        _stmt("dev-1", "ZUSTIMME", "specialist"),
        _stmt("dev-2", "WIDERSPRUCH", "specialist"),
    ])
    assert res["consensus_reached"] is False
    assert res["verdict"] == "NO_CONSENSUS"
    assert res["applied_tie_break"].startswith("tier_conflict:unresolved")


# ---------------------------------------------------------------------------
# D14-H1 / M5 — HITL-Override, echter Proof + Cross-Modell-Call
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"host": "localhost"}
        self.cookies = {}
        self.state = SimpleNamespace(user={"id": "tester", "username": "tester", "role": "admin"})

        class _URL:
            scheme = "http"

        self.url = _URL()

    async def is_disconnected(self):
        return False

    async def json(self):
        return dict(self._payload)


def _kanban_db(tmp_path, task_id="task-hitl", creator="requester"):
    path = tmp_path / "kanban.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, "
        "assignee TEXT, status TEXT, priority INTEGER, created_by TEXT, "
        "created_at INTEGER, result TEXT, model_override TEXT)"
    )
    conn.execute(
        "INSERT INTO tasks (id,title,status,created_by,created_at,result,model_override) "
        "VALUES (?,?,?,?,?,?,?)",
        (task_id, "T", "blocked", creator, 1, "Geleistete Arbeit", "anthropic/claude-sonnet-4"),
    )
    conn.commit()
    conn.close()
    return str(path)


def _meta_file(tmp_path, task_id="task-hitl", *, proof_command=""):
    path = tmp_path / "kanban_meta.json"
    path.write_text(json.dumps({"tasks": {task_id: {
        "token_budget": 1000,
        "proof_command": proof_command,
        "result_text": "Geleistete Arbeit aus dem Task-Kontext",
        "primary_model": "anthropic/claude-sonnet-4",
        "diff_text": "--- a/x\n+++ b/x\n+ print(1)\n",
    }}}), encoding="utf-8")
    return str(path)


def _patch_router(monkeypatch, tmp_path, *, proof_command, actor="approver", creator="requester"):
    import archon.routers._rbac as rbac
    import archon.routers.decisions as decisions
    import archon.routers.kanban as kanban
    import backend.audit_log as audit_log
    import backend.kanban_sidecar as sidecar
    import backend.operations_api as operations_api
    import backend.passkey_hitl as passkey

    calls = {"audit": [], "status": [], "cross": [], "proof": []}  # type: ignore[var-annotated]
    db_path = _kanban_db(tmp_path, creator=creator)
    monkeypatch.setattr(rbac, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(kanban, "require_session_actor", lambda request: actor)
    monkeypatch.setattr(kanban, "_resolve_active_kanban_db", lambda: db_path)
    monkeypatch.setattr(sidecar, "KANBAN_META_FILE", _meta_file(tmp_path, proof_command=proof_command))
    monkeypatch.setattr(
        decisions, "_decision_self_api", lambda *a, **k: None
    )
    monkeypatch.setattr(
        audit_log.chained_audit_log, "record_event",
        lambda **kw: calls["audit"].append(kw) or {"id": len(calls["audit"])},  # type: ignore[func-returns-value]
    )

    async def _fake_update(request, task_id, payload):
        calls["status"].append((task_id, payload.status))
        return {"status": "success"}

    monkeypatch.setattr(operations_api, "update_task_status", _fake_update)

    def _proof(token, user_id, category="", action="", resource="", consume=True):
        calls["proof"].append((token, user_id, action, resource))
        return token == "valid-proof" and action == "kanban_hitl_override" and resource == "task-hitl"

    monkeypatch.setattr(passkey, "consume_hitl_proof_token", _proof)

    async def _cross(**kw):
        calls["cross"].append(kw)
        return {
            "passed": True, "model_call": True,
            "verifier_model": "deepseek/deepseek-chat", "reason": "echter Verifier-Call",
        }

    import backend.operations_execution as ops_exec
    monkeypatch.setattr(ops_exec, "_cross_model_verify_task_result", _cross)
    return kanban, calls


def test_h1_body_forged_result_text_cannot_release_card(monkeypatch, tmp_path):
    import sys as _sys

    ok = f'"{_sys.executable}" -c "print(123)"'
    kanban, calls = _patch_router(monkeypatch, tmp_path, proof_command="")
    request = _FakeRequest({
        "action": "override_budget",
        "result_text": "FREI ERFUNDEN",
        "proof_command": ok,
        "primary_model": "evil-model",
        "diff_text": "- assert x\n",
        "hitl_proof_token": "valid-proof",
    })
    with pytest.raises(__import__("fastapi").HTTPException) as exc:
        asyncio.run(kanban.api_kanban_task_hitl(request, "task-hitl"))
    assert exc.value.status_code == 403
    assert calls["status"] == []
    # Body-Werte wurden nicht als Proof uebernommen.
    assert calls["cross"] and calls["cross"][0]["primary_model"] == "anthropic/claude-sonnet-4"
    assert calls["cross"][0]["diff_text"].startswith("--- a/x")


def test_h1_empty_proof_command_from_context_stays_blocked(monkeypatch, tmp_path):

    kanban, calls = _patch_router(monkeypatch, tmp_path, proof_command="")
    request = _FakeRequest({
        "action": "override_budget",
        "hitl_proof_token": "valid-proof",
    })
    with pytest.raises(__import__("fastapi").HTTPException) as exc:
        asyncio.run(kanban.api_kanban_task_hitl(request, "task-hitl"))
    assert exc.value.status_code == 403
    assert calls["status"] == []


def test_h1_real_proof_and_cross_model_releases_with_audit_before_status(monkeypatch, tmp_path):
    import sys as _sys

    ok = f'"{_sys.executable}" -c "print(123)"'
    kanban, calls = _patch_router(monkeypatch, tmp_path, proof_command=ok)
    request = _FakeRequest({
        "action": "override_budget",
        "hitl_proof_token": "valid-proof",
        # Body-Freitext darf wirkungslos sein.
        "result_text": "FREI ERFUNDEN",
        "primary_model": "evil-model",
    })
    res = asyncio.run(kanban.api_kanban_task_hitl(request, "task-hitl"))
    assert res["verified"] is True
    assert res["next_status"] == "todo"
    assert res["proof"]["skipped"] is False
    assert res["proof"]["exit_code"] == 0
    assert res["cross_model"]["model_call"] is True
    assert res["proof_context"]["primary_model_source"] == "task_context"
    assert [e["action"] for e in calls["audit"]] == ["kanban_hitl_resolution"]
    assert calls["audit"][0]["payload"]["hitl_proof_verified"] is True
    assert calls["status"] == [("task-hitl", "todo")]


def test_m5_cross_model_failure_is_fail_closed(monkeypatch, tmp_path):
    import sys as _sys

    ok = f'"{_sys.executable}" -c "print(123)"'
    kanban, calls = _patch_router(monkeypatch, tmp_path, proof_command=ok)

    async def _broken(**kw):
        raise RuntimeError("verifier offline")

    import backend.operations_execution as ops_exec
    monkeypatch.setattr(ops_exec, "_cross_model_verify_task_result", _broken)
    request = _FakeRequest({"action": "override_budget", "hitl_proof_token": "valid-proof"})
    with pytest.raises(__import__("fastapi").HTTPException) as exc:
        asyncio.run(kanban.api_kanban_task_hitl(request, "task-hitl"))
    assert exc.value.status_code == 403
    assert calls["status"] == []


def test_m5_precheck_never_claims_a_model_call():
    from backend.kanban_verifier import cross_model_verify_card

    res = cross_model_verify_card("t-99", "anthropic/claude-sonnet-4", diff_text="+ print(1)")
    assert res["passed"] is True
    assert res["model_call"] is False  # Precheck ist kein Verifier-Call
    assert "_cross_model_verify_task_result" in res["reason"]


def test_h1_audit_failure_blocks_status_change(monkeypatch, tmp_path):
    import sys as _sys

    ok = f'"{_sys.executable}" -c "print(123)"'
    kanban, calls = _patch_router(monkeypatch, tmp_path, proof_command=ok)
    import backend.audit_log as audit_log

    def _fail(**kw):
        raise RuntimeError("audit_write_failed")

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _fail)
    request = _FakeRequest({"action": "override_budget", "hitl_proof_token": "valid-proof"})
    with pytest.raises(__import__("fastapi").HTTPException) as exc:
        asyncio.run(kanban.api_kanban_task_hitl(request, "task-hitl"))
    assert exc.value.status_code == 503
    assert calls["status"] == []


# ---------------------------------------------------------------------------
# D14-M4 — MCP-HITL-Ersteller & Engine-Fail-Closed
# ---------------------------------------------------------------------------

def test_m4_mcp_request_persists_verified_requester_and_blocks_self_approval(tmp_path, monkeypatch):
    import backend.approval_policy_engine as ape
    from backend.approval_policy_engine import ApprovalPolicyEngine
    from backend.mcp_gateway import ArchonMcpGateway

    engine = ApprovalPolicyEngine(db_path=str(tmp_path / "approvals.db"))
    monkeypatch.setattr(ape, "approval_engine", engine)
    gw = ArchonMcpGateway()
    allowed, pending = gw._check_hitl_gate(
        "archon__ask_specialist", {"specialist_id": "cfo"}, {"key_id": "k1", "name": "desk-key"}
    )
    assert allowed is False and pending and pending["status"] == "pending_hitl_approval"
    row = next(r for r in engine.get_requests() if r["reference_id"] == "mcp:k1")
    assert row["requester_id"] == "mcp-key:k1 (desk-key)"
    payload = json.loads(row["payload_json"])
    assert payload["_requester_id"] == row["requester_id"]
    assert payload["_requester_required"] is True

    # Identischer Principal darf nicht sich selbst freigeben.
    with pytest.raises(ValueError, match="Vier-Augen"):
        engine.approve_request(row["id"], "mcp-key:k1 (desk-key)")
    # Eine andere Identitaet darf es (zweistufig).
    assert engine.approve_request(row["id"], "admin")["status"] in ("approved", "first_approved")


def test_m4_empty_requester_on_hitl_domain_is_fail_closed(tmp_path):
    from backend.approval_policy_engine import ApprovalPolicyEngine

    engine = ApprovalPolicyEngine(db_path=str(tmp_path / "approvals2.db"))
    ev = engine.evaluate_and_enqueue(domain="agent_dispatch", title="Delegation", payload={})
    assert ev["status"] == "pending"
    with pytest.raises(ValueError, match="nicht verifizierbar"):
        engine.approve_request(ev["request_id"], "admin")


# ---------------------------------------------------------------------------
# D14-M2 + M3 — STORM-Panel-Konsument & Konsens-Begruendung im Archiv/Audit
# ---------------------------------------------------------------------------

def _patch_boardroom(monkeypatch, tmp_path, dispatch_result, events=None):
    import archon.routers._rbac as rbac
    import archon.routers.boardroom as br
    import archon.routers.decisions as decisions
    import backend.audit_log as audit_log
    import backend.workflow_scheduler as scheduler

    roles = [
        {"id": "executive_decision_architect", "name": "Chair", "role": "Executive",
         "prompt": "p", "model": "m", "provider": "openrouter"},
        {"id": "cloud_architect", "name": "Lead", "role": "Lead",
         "prompt": "p", "model": "m", "provider": "openrouter"},
        {"id": "senior_coder", "name": "Coder", "role": "Specialist",
         "prompt": "p", "model": "m", "provider": "openrouter"},
    ]
    monkeypatch.setitem(br._DEPS, "load_roles", lambda: list(roles))
    monkeypatch.setitem(br._DEPS, "api_get_hermes_profiles", lambda: [])
    monkeypatch.setattr(br, "require_admin_or_503", lambda request: None)
    monkeypatch.setattr(rbac, "get_session_actor", lambda request, fallback="": "tester")
    monkeypatch.setattr(br, "add_ticker", lambda *a, **k: None)
    monkeypatch.setattr(br, "OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setattr(br, "BOARDROOM_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setattr(scheduler, "dispatch_workflow_event", lambda **kw: None)

    result = dict(dispatch_result)
    result.setdefault("status", "success")
    result.setdefault("transcript", "Diskussion")
    result.setdefault("synthesis", "Zwei Positionen, kein Konsens.")
    result["events"] = events or []
    result.setdefault("consensus_status", result.get("consensus_verdict", "NO_CONSENSUS"))

    async def _fake_dispatch(**kwargs):
        return dict(result)

    monkeypatch.setattr(br.core_dispatcher, "run_boardroom_debate", _fake_dispatch)

    captured = {"audit": [], "escalation": None}  # type: ignore[var-annotated]

    def _record(category, action, actor_id, payload, **kw):
        captured["audit"].append({"category": category, "action": action, "payload": payload})  # type: ignore[union-attr]
        return {"id": len(captured["audit"])}  # type: ignore[arg-type]

    monkeypatch.setattr(audit_log.chained_audit_log, "record_event", _record)

    def _create_decision(typ, **kw):
        captured["escalation"] = {"typ": typ, **kw}  # type: ignore[assignment]
        return {"id": "esc-1"}

    # Die echte Eskalationsfunktion laeuft (inkl. Audit); nur der Decision-
    # Store wird ersetzt, damit keine produktive DB beruehrt wird.
    monkeypatch.setattr(decisions, "create_decision", _create_decision)
    return br, captured


def test_m2_m3_no_consensus_by_authority_is_archived_and_escalated(monkeypatch, tmp_path):
    import archon.routers.boardroom as br

    events = [
        {"type": "agent_response", "agent_id": "cloud_architect", "content": "Lead lehnt ab."},
        {"type": "agent_response", "agent_id": "senior_coder", "content": "Coder stimmt zu."},
    ]
    br, captured = _patch_boardroom(monkeypatch, tmp_path, {  # noqa: F811
        "consensus_verdict": "NO_CONSENSUS_BY_AUTHORITY",
        "veto_by": "cloud_architect",
        "applied_tie_break": "highest_tier:lead:no",
        "evidence": [("cloud_architect", "WIDERSPRUCH")],
    }, events=events)

    res = asyncio.run(br.api_run_boardroom(
        br.BoardroomRequest(task="Konfliktfall"), _FakeRequest({})  # type: ignore[arg-type]
    ))
    assert res["consensus_verdict"] == "NO_CONSENSUS_BY_AUTHORITY"
    assert res["requires_human_gate"] is True
    assert res["storm_panel"]["human_gate_consumed"] is True
    assert set(res["storm_panel"]["perspectives"]) >= {"cloud_architect", "senior_coder"}

    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    entry = hist[0]
    assert entry["decision_status"] == "no_consensus"
    assert entry["consensus"]["verdict"] == "NO_CONSENSUS_BY_AUTHORITY"
    assert entry["consensus"]["applied_tie_break"] == "highest_tier:lead:no"
    assert any(
        e["agent_id"] == "cloud_architect" and e["tier"] == "lead"
        for e in entry["consensus"]["evidence"]
    )
    assert entry["storm_panel"]["requires_human_gate"] is True

    saved = next(a for a in captured["audit"] if a["action"] == "decision_saved")
    assert saved["payload"]["consensus"]["veto_by"] == "cloud_architect"
    assert saved["payload"]["consensus"]["authority_weights"]["executive"] == 3
    escalated = next(a for a in captured["audit"] if a["action"] == "no_consensus_escalated")
    assert escalated["payload"]["storm_panel"]["human_gate_consumed"] is True
    assert captured["escalation"]["extra"]["consensus"]["applied_tie_break"] == "highest_tier:lead:no"


def test_m2_storm_panel_also_consumed_in_stream_no_consensus_path(monkeypatch, tmp_path):
    import archon.routers.boardroom as br

    br, captured = _patch_boardroom(monkeypatch, tmp_path, {  # noqa: F811
        "consensus_verdict": "NO_CONSENSUS_BY_AUTHORITY",
    })

    async def _fake_stream(**kwargs):
        yield {"type": "agent_response", "agent_id": "cloud_architect", "content": "Seat-Leit bearbeitet."}
        yield {
            "type": "done",
            "transcript": "Diskussion",
            "synthesis": "Kein Konsens.",
            "consensus_verdict": "NO_CONSENSUS_BY_AUTHORITY",
            "veto_by": "cloud_architect",
            "evidence": [("cloud_architect", "WIDERSPRUCH")],
            "is_final_decision": False,
        }

    monkeypatch.setattr(br.core_dispatcher, "stream_boardroom_debate", _fake_stream)
    response = asyncio.run(br.api_stream_boardroom(
        br.BoardroomRequest(task="Stream-Konflikt"), _FakeRequest({})  # type: ignore[arg-type]
    ))
    async def _collect():
        return [chunk async for chunk in response.body_iterator]

    done = None
    for chunk in asyncio.run(_collect()):
        payload = json.loads(chunk[len("data: "):].strip())
        if payload.get("type") == "done":
            done = payload
    assert done is not None
    assert done["requires_human_gate"] is True
    assert done["storm_panel"]["human_gate_consumed"] is True
    assert "cloud_architect" in done["storm_panel"]["perspectives"]
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert hist[0]["consensus"]["verdict"] == "NO_CONSENSUS_BY_AUTHORITY"
    assert hist[0]["storm_panel"]["requires_human_gate"] is True

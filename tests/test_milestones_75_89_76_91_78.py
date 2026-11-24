# -*- coding: utf-8 -*-
import datetime
import sys
import time

import pytest

from backend.delegation_isolation import (
    is_tool_allowed_for_agent,
    resolve_isolated_execution_scope,
)
from backend.kanban_verifier import (
    resolve_card_hitl_decision,
    verify_card_completion,
)
from backend.kanban_views import (
    build_dependency_graph,
    build_gantt_items,
)
from backend.precedent_log import (
    find_matching_precedents,
    format_precedents_for_prompt,
    record_precedent,
    revoke_precedent,
)
from backend.session_taint_guard import (
    check_egress_tool_call,
    mark_session_tainted,
    resolve_taint_approval,
)


def test_m75_delegation_isolation():
    profiles = [
        {"id": "reviewer", "tools": ["web_search"], "skills": ["sdlc-review"], "model": "deepseek/deepseek-chat"},
        {"id": "video_ops", "tools": ["mcp", "filesystem"], "skills": ["kinocut"], "model": ""},
    ]
    scope_rev = resolve_isolated_execution_scope("reviewer", profiles=profiles)
    assert scope_rev["allowed_tools"] == ["web_search"]
    assert is_tool_allowed_for_agent("reviewer", "web_search", scope=scope_rev) is True
    assert is_tool_allowed_for_agent("reviewer", "terminal", scope=scope_rev) is False
    assert is_tool_allowed_for_agent("reviewer", "mcp__pay__pay", scope=scope_rev) is False

    scope_vid = resolve_isolated_execution_scope("video_ops", profiles=profiles)
    assert is_tool_allowed_for_agent("video_ops", "mcp__kinocut__trim", scope=scope_vid) is True
    assert is_tool_allowed_for_agent("video_ops", "terminal", scope=scope_vid) is False


def test_m89_session_taint_guard_hitl_flow(tmp_path):
    import backend.passkey_hitl as pk

    db = str(tmp_path / "taint.db")
    sess = "sess_test_1"

    # Untainted session allows critical egress
    res_clean = check_egress_tool_call(sess, "send_email", {"to": "a@b.de"}, db_path=db)
    assert res_clean["allowed"] is True

    # Taint session via external web content
    mark_session_tainted(sess, source="web_scrape:example.com", reason="untrusted HTML", db_path=db)

    # Read-only tool still allowed
    assert check_egress_tool_call(sess, "web_search", {}, db_path=db)["allowed"] is True

    # Critical egress requires HITL. requested_by wird mitgespeichert, damit
    # Vier-Augen (requested_by != reviewer) geprueft werden kann.
    blocked = check_egress_tool_call(
        sess, "pay", {"amount": 10}, db_path=db, requested_by="agent:probe",
    )
    assert blocked["allowed"] is False
    assert blocked["requires_hitl"] is True
    aid = blocked["approval_id"]

    # Ohne Passkey-Proof bleibt die Freigabe hart blockiert (PermissionError).
    with pytest.raises(PermissionError, match="Passkey-Proof"):
        resolve_taint_approval(aid, approved=True, reviewer="micha", db_path=db)

    # Der Anforderer darf die eigene Freigabe nicht bestaetigen.
    with pytest.raises(PermissionError, match="Vier-Augen"):
        resolve_taint_approval(aid, approved=True, reviewer="agent:probe", db_path=db)

    # Gueltiger, an genau diese Freigabe gebundener Einmal-Proof (system/UV).
    proof = "taint-proof-" + aid
    with pk._LOCK:
        pk._PROOF_TOKENS[proof] = {
            "user_id": "micha",
            "category": "system",
            "uv_verified": True,
            "created_ts": time.time(),
            "action": "Taint-Freigabe %s" % aid,
            "resource": aid,
        }

    # Human approves once
    resolved = resolve_taint_approval(
        aid, approved=True, reviewer="micha", db_path=db, passkey_proof=proof,
    )
    assert resolved["status"] == "approved"
    assert resolved["reviewer"] == "micha"
    assert resolved["requested_by"] == "agent:probe"

    # One-shot execution succeeds
    allowed_once = check_egress_tool_call(sess, "pay", {"amount": 10}, approval_id=aid, db_path=db)
    assert allowed_once["allowed"] is True
    assert allowed_once["hitl_approved"] is True

    # Reusing the same one-shot approval is blocked again
    reused = check_egress_tool_call(sess, "pay", {"amount": 10}, approval_id=aid, db_path=db)
    assert reused["allowed"] is False
    assert reused["requires_hitl"] is True


def test_m76_kanban_verifier_budget_and_proof():
    # Budget exceeded -> HITL block
    b_res = verify_card_completion("t-1", "Done", token_used=12000, token_budget=10000)
    assert b_res["status"] == "blocked"
    assert b_res["requires_hitl"] is True
    assert b_res["block_kind"] == "budget_exceeded_hitl"

    # Proof failure -> first retry, then blocked with HITL
    fail_cmd = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    p1 = verify_card_completion("t-2", "Patch ready", proof_command=fail_cmd, retry_count=0)
    assert p1["status"] == "retry"
    p2 = verify_card_completion("t-2", "Patch ready", proof_command=fail_cmd, retry_count=1)
    assert p2["status"] == "blocked"
    assert p2["requires_hitl"] is True
    assert p2["block_kind"] == "proof_failed_hitl"

    # Passing proof -> done
    ok_cmd = f'"{sys.executable}" -c "print(123)"'
    p_ok = verify_card_completion("t-3", "All good", proof_command=ok_cmd)
    assert p_ok["status"] == "done"
    assert p_ok["verified"] is True

    # HITL decision helper: ohne verifiziertes Ergebnis bleibt der Override
    # blockiert (frueher wurde er unberechtigt freigegeben).
    # D14: Overrides brauchen einen verifizierten Ersteller (fail-closed).
    d_ovr = resolve_card_hitl_decision(
        "override_budget", current_budget=10000, override_budget=25000,
        actor="approver", created_by="requester",
    )
    assert d_ovr["next_status"] == "blocked"
    assert d_ovr["block_kind"] == "override_reverification_failed_hitl"
    assert d_ovr["verified"] is False
    assert d_ovr["token_budget"] == 25000

    # Mit erfolgreicher Reverifikation darf die Sperre aufgehoben werden.
    ok_cmd = f'"{sys.executable}" -c "print(123)"'
    d_ok = resolve_card_hitl_decision(
        "override_budget", current_budget=10000, override_budget=25000,
        result_text="Fertig", proof_command=ok_cmd,
        actor="approver", created_by="requester",
    )
    assert d_ok["verified"] is True
    assert d_ok["block_kind"] == "approval_granted"
    assert d_ok["next_status"] in ("todo", "ready")

    # Vier-Augen: der Ersteller darf die eigene HITL-Sperre nicht loesen.
    with pytest.raises(PermissionError, match="Vier-Augen"):
        resolve_card_hitl_decision("retry", actor="micha", created_by="micha")


def test_m91_precedent_log_strict_tenant_isolation(tmp_path):
    db = str(tmp_path / "precedents.db")
    rec = record_precedent(
        tenant_id="holding_gmbh",
        project_id="proj_alpha",
        question="Welcher Steuersatz gilt fuer SaaS-Lizenzen?",
        ruling_text="Immer 19% USt verwenden.",
        db_path=db,
    )
    # Same tenant + project matches
    hits = find_matching_precedents("holding_gmbh", "proj_alpha", "SaaS Steuersatz pruefen", db_path=db)
    assert len(hits) == 1
    assert "19% USt" in format_precedents_for_prompt(hits)

    # Different tenant or different project NEVER sees it
    assert find_matching_precedents("other_tenant", "proj_alpha", "SaaS Steuersatz", db_path=db) == []
    assert find_matching_precedents("holding_gmbh", "proj_beta", "SaaS Steuersatz", db_path=db) == []

    # Revoke stops matching
    assert revoke_precedent(rec["id"], "holding_gmbh", db_path=db) is True
    assert find_matching_precedents("holding_gmbh", "proj_alpha", "SaaS Steuersatz", db_path=db) == []


def test_m78_kanban_gantt_and_dependency_graph():
    now = datetime.datetime(2026, 11, 19, 12, 0, 0)
    tasks = [
        {"id": "t-a", "title": "Spec", "status": "done", "created_at": "2026-11-19T08:00:00", "started_at": "2026-11-19T08:00:00", "completed_at": "2026-11-19T10:00:00"},
        {"id": "t-b", "title": "Build", "status": "in_progress", "created_at": "2026-11-19T10:00:00"},
    ]
    gantt = build_gantt_items(tasks, default_duration_hours=4, now_dt=now)
    assert len(gantt) == 2
    assert gantt[0]["has_explicit_dates"] is True
    assert gantt[0]["duration_hours"] == 2.0
    assert gantt[1]["has_explicit_dates"] is False
    assert gantt[1]["duration_hours"] == 2.0

    links = [{"parent_id": "t-a", "child_id": "t-b", "link_type": "blocks"}]
    graph = build_dependency_graph(tasks, links)
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["t-a"]["layer"] == 0
    assert by_id["t-b"]["layer"] == 1
    assert len(graph["edges"]) == 1

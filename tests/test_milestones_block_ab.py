# -*- coding: utf-8 -*-
import asyncio
import os
import time

from backend.agent_eval_arena import run_eval_arena
from backend.deep_research_lab import compile_research_dossier, triangulate_sources
from backend.lossless_session_dag import (
    append_turn,
    compact_range_to_summary,
    expand_summary_node,
    run_storm_panel,
    search_lossless_history,
)
from backend.session_receipts import build_delegation_receipt, render_offline_html_receipt
from backend.tool_output_firewall import guard_tool_output, run_batch_tool_calls
from backend.tool_warrants import issue_warrant, verify_warrant_for_call


def test_m90_tool_warrants():
    w = issue_warrant("sess_1", ["pay", "read_file"], constraints={"max_amount": 50.0}, ttl_seconds=60)
    assert verify_warrant_for_call(w, "sess_1", "pay", {"amount": 25.0})["allowed"] is True
    assert verify_warrant_for_call(w, "sess_1", "pay", {"amount": 100.0})["allowed"] is False
    assert verify_warrant_for_call(w, "sess_1", "terminal", {})["allowed"] is False
    assert verify_warrant_for_call(w, "sess_2", "pay", {"amount": 10.0})["allowed"] is False
    assert verify_warrant_for_call(w, "sess_1", "pay", {"amount": 10.0}, now_ts=time.time() + 120)["allowed"] is False


def test_m82_session_receipts():
    rec = build_delegation_receipt("t-1", "coder", "done", ["a.py"], "pytest", 0, "ok")
    assert rec["proof_exit_code"] == 0
    html_doc = render_offline_html_receipt(
        "t-1",
        "Test Task",
        "Fix <script>alert(1)</script>",
        [{"kind": "retry", "status": "failed", "detail": "timeout"}],
    )
    assert "<script>alert(1)</script>" not in html_doc
    assert "timeout" in html_doc


def test_m93_tool_output_firewall_and_batch():
    big = "A" * 12000
    g = guard_tool_output("web_fetch", big, max_chars=8000)
    assert g["truncated"] is True
    assert "TRUNCATED BY TOOL-OUTPUT-FIREWALL" in g["output"]

    async def exec_fn(name, args):
        return f"{name}:{args.get('x')}"

    batch = asyncio.run(run_batch_tool_calls([{"tool": "t1", "args": {"x": 1}}, {"tool": "t2", "args": {"x": 2}}], exec_fn))
    assert len(batch) == 2
    # Produktiv wird jede Tool-Ausgabe durch die Firewall gewrappt (Audit-Fix).
    # Geprüft wird, dass der Inhalt erhalten und als untrusted markiert ist.
    assert "UNTRUSTED TOOL OUTPUT" in batch[0]["output"]
    assert "t1:1" in batch[0]["output"]
    assert "t2:2" in batch[1]["output"]


def test_m94_lossless_session_dag_and_storm(tmp_path):
    db = str(tmp_path / "lcm.db")
    t1 = append_turn("s1", "user", "Unser Budget ist 50000 EUR", db_path=db)
    t2 = append_turn("s1", "assistant", "Verstanden, 50000 EUR notiert.", db_path=db)
    sid = compact_range_to_summary("s1", [t1, t2], "Budget 50k", db_path=db)

    expanded = expand_summary_node(sid, db_path=db)
    assert len(expanded) == 2
    assert "50000 EUR" in expanded[0]["content"]
    assert len(search_lossless_history("s1", "50000", db_path=db)) == 2

    async def seat_fn(seat, q):
        return f"{seat}-view"

    async def judge_fn(q, persp):
        return f"combined:{len(persp)}"

    storm = asyncio.run(run_storm_panel("Markteintritt?", ["cfo", "cto"], seat_fn, judge_fn))
    assert storm["requires_human_gate"] is True
    assert storm["synthesis"] == "combined:2"


def test_m50_eval_arena(tmp_path):
    db = str(tmp_path / "eval.db")

    async def fake_runner(model, prompt):
        if model == "good_model":
            return {"content": "def memo return taint hitl sandbox 100 19 kosten risiko", "cost_usd": 0.01}
        return {"content": "weiss nicht", "cost_usd": 0.02}

    res = asyncio.run(run_eval_arena(["bad_model", "good_model"], fake_runner, db_path=db))
    assert res["winner_model"] == "good_model"


def test_m45_deep_research_lab(tmp_path):
    sources = [
        {"title": "ArXiv Paper", "url": "https://arxiv.org/abs/2601.0001"},
        {"title": "PatSnap Patent", "url": "https://connect.patsnap.com/2b0355/logic-mcp"},
    ]
    tri = triangulate_sources(sources)
    assert tri["corroborated"] is True
    assert tri["tier1_count"] == 2
    dossier = compile_research_dossier("KI Patente", "Zwei Primaerquellen bestaetigen.", sources, vault_dir=str(tmp_path))
    assert dossier["saved_path"] and os.path.exists(dossier["saved_path"])


def test_m65_settings_modal_ergonomics():
    with open("static/views/system_settings_modal.html", "r", encoding="utf-8") as f:
        html = f.read()
    with open("static/views/view_approval_policies.html", "r", encoding="utf-8") as f:
        approvals_html = f.read()
    assert "flex-wrap" in html
    for tab_id in ["btn-tab-kernel", "btn-tab-jev", "btn-tab-memory", "btn-tab-email-guard", "btn-tab-validate", "btn-tab-cost", "btn-tab-corporate", "btn-tab-users", "btn-tab-update"]:
        assert tab_id in html
    assert "approvals-subtab-btn-autonomy" in approvals_html

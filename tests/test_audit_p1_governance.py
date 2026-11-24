"""Audit P1 (D11/D14): Handoff-Nachvollziehbarkeit und Vier-Augen."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_dispatch_audits_prompt_version():
    text = _text("core_dispatcher.py")
    ast.parse(text)
    assert "prompt_version_info" in text
    assert 'extra={"effective_prompt_info": prompt_version_info}' in text


def test_context_compaction_marks_truncation():
    text = _text("backend/agent_router.py")
    assert "[GEKÜRZT:" in text
    assert "weitere Einträge ausgelassen" in text


def test_decision_approver_comes_from_session_and_four_eyes():
    text = _text("archon/routers/decisions.py")
    ast.parse(text)
    assert "require_session_actor(request)" in text
    assert "four_eyes_violation" in text
    assert 'dec_local.get("created_by")' in text
    assert '"decided_by": von' in text
    assert "created_by: str = \"\"" in text

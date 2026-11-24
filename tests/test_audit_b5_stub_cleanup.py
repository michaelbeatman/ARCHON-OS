"""Audit B5: keine erfundenen Risiken und kein RBAC-freier Eval-Endpoint."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_war_room_uses_unknown_on_provider_failure():
    text = (ROOT / "backend" / "war_room_simulator.py").read_text(encoding="utf-8")
    ast.parse(text)
    assert '"risk_rating": "UNKNOWN"' in text
    assert "evaluation_failed" in text
    assert 'evaluation_failed or (risk_order' in text
    assert '"status": "incomplete" if evaluation_failed' in text


def test_eval_suite_endpoint_requires_admin():
    text = (ROOT / "archon" / "routers" / "autonomy_settings.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "api_run_eval_regression_suite"
    )
    assert "request" in [a.arg for a in fn.args.args]
    names = {getattr(getattr(s, "func", None), "id", "") for s in ast.walk(fn) if isinstance(s, ast.Call)}
    assert "require_admin_or_503" in names

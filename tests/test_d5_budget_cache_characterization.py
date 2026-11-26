"""D5-C3 Characterization-Tests fuer archon/core/dispatch_budget_cache.py (INVARIANTS §3)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import core_dispatcher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_explicit_reexport(source: str, module: str, symbol: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name == symbol and alias.asname == symbol:
                    return True
    return False


def test_d5_c3_contextvars_and_audit_lock_remain_singletons_on_core_dispatcher():
    """ContextVars und _AUDIT_WRITE_LOCK bleiben Singletons auf core_dispatcher.py."""
    import archon.core.dispatch_budget_cache as dbc

    assert hasattr(core_dispatcher, "_PROMPT_VERSION_CTX")
    assert hasattr(core_dispatcher, "_STRUCTURED_OUTPUT_SCHEMA_CTX")
    assert hasattr(core_dispatcher, "_AUDIT_WRITE_LOCK")
    assert not hasattr(dbc, "_PROMPT_VERSION_CTX")
    assert not hasattr(dbc, "_STRUCTURED_OUTPUT_SCHEMA_CTX")
    assert not hasattr(dbc, "_AUDIT_WRITE_LOCK")


def test_d5_c3_reserve_trajectory_budget_blocks_on_hop_and_token_caps(monkeypatch):
    import backend.trajectory_budget as tb_mod

    monkeypatch.setattr(tb_mod, "normalize_trajectory_id", lambda *_a, **_kw: "traj-d5-c3")
    monkeypatch.setattr(tb_mod, "reserve_hop", lambda *_a, **_kw: {"allowed": False, "reason": "MAX_HOPS"})
    res_hop = core_dispatcher._reserve_trajectory_budget_sync("t-1", "coder", 500)
    assert res_hop["allowed"] is False
    assert res_hop["stage"] == "hop"

    monkeypatch.setattr(tb_mod, "reserve_hop", lambda *_a, **_kw: {"allowed": True})
    monkeypatch.setattr(tb_mod, "reserve_tokens", lambda *_a, **_kw: {"allowed": False, "reason": "TOKEN_CAP"})
    res_tok = core_dispatcher._reserve_trajectory_budget_sync("t-1", "coder", 50000)
    assert res_tok["allowed"] is False
    assert res_tok["stage"] == "tokens"


def test_d5_c3_ast_explicit_x_as_x_reexports_and_negative_probe():
    src = (REPO_ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    for sym in (
        "_dispatch_cache_scope",
        "_cache_policy_context",
        "_validate_cache_hit_gate",
        "_reserve_trajectory_budget_sync",
        "_DispClosingConn",
    ):
        assert _has_explicit_reexport(src, "archon.core.dispatch_budget_cache", sym), (
            f"core_dispatcher.py muss `{sym} as {sym}` aus archon.core.dispatch_budget_cache re-exportieren."
        )
    # Negativprobe: Import ohne `as X` -> False
    assert _has_explicit_reexport(
        "from archon.core.dispatch_budget_cache import _validate_cache_hit_gate\n",
        "archon.core.dispatch_budget_cache",
        "_validate_cache_hit_gate",
    ) is False

"""Re-Audit Etappe 12 — D07: Fail-Open-Pfade in HITL/Taint/Autonomie/Audit."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_d07_approval_gate_is_fail_closed():
    src = (ROOT / "backend" / "operations_api.py").read_text(encoding="utf-8")
    block = src.split("def _approve_kanban_task_db", 1)[1].split("\n\ndef ", 1)[0]
    assert "NOT_APPROVABLE" in block
    assert "block_kind = 'approval'" in block
    assert "APPROVAL_RACE" in block


def test_d07_taint_tenant_failure_is_fail_closed():
    import backend.session_taint_guard as stg

    original = stg._connect
    # Resolve-Fehler simulieren: tenant_db_registry import fails.
    import builtins
    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "backend.tenant_db_registry":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = broken_import
    try:
        with pytest.raises(RuntimeError, match="TaintStoreUnavailable"):
            with stg._connect():
                pass
    finally:
        builtins.__import__ = real_import
        stg._connect = original


def test_d07_no_undocumented_proof_bypass():
    src = (ROOT / "backend" / "session_taint_guard.py").read_text(encoding="utf-8")
    active = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'os.environ.get("ARCHON_TAINT_HITL_ALLOW_NO_PROOF"' not in active
    assert "Passkey-Proof erforderlich" in src


def test_d07_autonomy_config_failure_is_manual():
    src = (ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    block = src.split("Autonomie-Config nicht lesbar", 1)[1][:1200]
    assert '_del_autonomy = "manual"' in block
    assert "autonomy_config_unavailable" in block


def test_d07_break_glass_audit_failure_blocks():
    src = (ROOT / "scripts" / "break_glass_recovery.py").read_text(encoding="utf-8")
    assert "except Exception as e:\n        pass" not in src
    assert src.count('"error_code": "AUDIT_WRITE_FAILED"') == 2
    assert "nicht auditiert" in src

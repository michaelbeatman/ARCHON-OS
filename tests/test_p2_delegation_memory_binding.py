"""Regressionstest: Memory-Scope-Bindung pro Delegation."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_delegation_binds_memory_scope():
    src = (REPO_ROOT / "archon" / "core" / "delegation.py").read_text(encoding="utf-8")
    assert 'payload.get("memory_scope")' in src
    assert "MEMORY_SCOPE: {memory_scope}" in src
    assert '"memory_scope": memory_scope' in src
    assert '"memory_acl": memory_acl' in src
    assert '"memory_ttl_seconds": memory_ttl_seconds' in src

"""A2 — Kompaktierungs-Logik liegt in der Service-Schicht.

Schuetzt dagegen, dass die Trennung wieder „vereinfacht" (z. B. die Logik
zurueck in den Router oder nach backend/ verschoben) wird. Begruendung:
archon/services/__init__.py — „Ein Service kennt keine HTTP-Schicht".
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _imported_modules(rel: str) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]


def test_service_has_no_http_layer():
    mods = _imported_modules("archon/services/session_compaction.py")
    assert not any(m.startswith("fastapi") or m.startswith("archon.routers") for m in mods)
    assert "archon.core.state_db" in mods
    assert "backend.context_compactor" in mods


def test_router_reexports_service_symbols():
    mods = _imported_modules("archon/routers/context_meter.py")
    assert "archon.services.session_compaction" in mods
    assert "archon.routers.context_meter" not in mods


def test_backend_uses_service_not_router():
    mods = _imported_modules("backend/mcp_gateway.py")
    assert "archon.services.session_compaction" in mods
    assert "archon.routers.context_meter" not in mods


def test_compact_session_core_is_callable_without_http():
    """Der Service muss ohne FastAPI-/Router-Kontext importierbar und nutzbar sein."""
    from archon.services import session_compaction as sc

    assert callable(sc.compact_session_core)
    assert sc.compact_session_core("")["compacted"] is False
    assert "session_id fehlt" in sc.compact_session_core("")["reason"]

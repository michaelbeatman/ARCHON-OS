"""Audit B2-Regressionstests: zentraler RBAC-Zaun + Tenant-IDOR in erp.py.

Statische AST-Pruefungen (kein Modul-Import noetig): die Sicherheitsproperty
muss im Quelltext nachvollziehbar sein und darf nicht durch einen Spaeter-
Commit still wieder aufgeweicht werden.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "archon" / "routers"
ERP = ROUTERS / "erp.py"

RBAC_FUNCS = {"_require_admin", "_require_admin_or_503"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))


def test_rbac_wrappers_delegate_to_central_module():
    """Kein Router darf wieder eine eigene require_admin-Logik enthalten."""
    found = 0
    for path in sorted(ROUTERS.glob("*.py")):
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in RBAC_FUNCS:
                continue
            found += 1
            segment = ast.get_source_segment(
                path.read_text(encoding="utf-8", errors="replace"), node
            ) or ""
            assert "require_admin_or_503" in segment, f"{path}:{node.lineno} delegiert nicht"
            assert "import main" not in segment, f"{path}:{node.lineno} importiert main erneut"
            assert "_DEPS.get" not in segment, f"{path}:{node.lineno} nutzt lokales _DEPS"
    assert found >= 15, f"Erwarte die zentralisierten Router-Wraeper, fand nur {found}"


def test_erp_has_no_raw_body_company_id():
    """company_id darf nicht direkt aus dem Request-Body übernommen werden."""
    source = ERP.read_text(encoding="utf-8", errors="replace")
    assert 'company_id = payload.get("company_id")' not in source
    assert 'company_id=payload.get("company_id")' not in source
    assert "def _authorized_company_id(" in source


def test_erp_endpoints_authorize_company_id_after_rbac():
    """Jeder Endpunkt mit company_id-Parameter muss den aktiven Mandanten erzwingen."""
    tree = _parse(ERP)
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if "company_id" not in [a.arg for a in node.args.args]:
            continue
        checked += 1
        names = {
            getattr(stmt.func, "id", "")
            for stmt in ast.walk(node)
            if isinstance(stmt, ast.Call)
        }
        assert "_authorized_company_id" in names, f"{node.name}: keine Tenant-Pruefung"
        if "require_admin_or_503" in names:
            lines = [getattr(stmt, "lineno", 0) for stmt in ast.walk(node)
                     if isinstance(stmt, ast.Call) and getattr(stmt.func, "id", "") == "require_admin_or_503"]
            auth_lines = [getattr(stmt, "lineno", 0) for stmt in ast.walk(node)
                          if isinstance(stmt, ast.Call) and getattr(stmt.func, "id", "") == "_authorized_company_id"]
            if lines and auth_lines:
                assert min(auth_lines) > min(lines), (
                    f"{node.name}: Tenant-Pruefung läuft vor RBAC (Info-Leak)"
                )
    assert checked >= 10, f"Erwarte >=10 ERP-Endpunkte mit company_id, fand {checked}"

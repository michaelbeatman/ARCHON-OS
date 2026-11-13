"""Regressionstest F-14: keine doppelten Pfad+Methode-Routen im Scope.

AST-Scan ueber main.py, backend/main.py und backend/operations_api.py:
Es darf keine Pfad+Methode-Kombination doppelt registriert sein.
Vor dem Fix: GET /metrics (main.py + operations_api), GET / und GET /api/agents
(main.py + backend/main.py).
"""

import ast
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FILES = [
    os.path.join(BASE_DIR, "main.py"),
    os.path.join(BASE_DIR, "backend", "main.py"),
    os.path.join(BASE_DIR, "backend", "operations_api.py"),
]

_ROUTE_DECORS = {"get", "post", "put", "delete", "patch", "api_route"}


def _collect_routes(tree):
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in _ROUTE_DECORS:
                continue
            if not dec.args:
                continue
            path = dec.args[0]
            if not isinstance(path, ast.Constant) or not isinstance(path.value, str):
                continue
            method = None
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                    method = tuple(sorted(str(m) for m in methods)) or None
                elif kw.arg == "method" and isinstance(kw.value, ast.Constant):
                    method = str(kw.value.value)
            routes.add((path.value, method or dec.func.attr.upper()))
    return routes


def test_no_duplicate_route_registrations():
    seen = {}
    duplicates = []
    for fpath in FILES:
        assert os.path.exists(fpath), f"fehlt: {fpath}"
        with open(fpath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for route in _collect_routes(tree):
            if route in seen:
                duplicates.append((route, seen[route], fpath))
            else:
                seen[route] = fpath
    assert not duplicates, f"Doppelte Pfad+Methode-Registrierungen: {duplicates}"


def test_no_duplicate_metrics_route():
    """GET /metrics darf nur noch einmal registriert sein (main.py)."""
    all_routes = set()
    for fpath in FILES:
        with open(fpath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        all_routes |= _collect_routes(tree)
    metrics = [r for r in all_routes if r[0] == "/metrics"]
    assert len(metrics) == 1, f"/metrics-Registrierungen: {metrics}"


def test_backend_main_has_no_root_or_agents_collision():
    """backend/main.py darf GET / und GET /api/agents nicht mehr fuehren."""
    with open(os.path.join(BASE_DIR, "backend", "main.py"), "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    routes = _collect_routes(tree)
    collisions = {"/", "/api/agents"}
    assert not (collisions & {r[0] for r in routes})

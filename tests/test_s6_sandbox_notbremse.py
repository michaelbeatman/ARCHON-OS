"""Tests für S6-Notbremse: /api/sandbox liefert 501, subprocess.run entfernt."""

import ast
import re
from pathlib import Path


def test_sandbox_endpoint_returns_501():
    """POST /api/sandbox gibt HTTP 501 zurück (Integration via TestClient)."""
    from fastapi.testclient import TestClient
    from main import app

    T = Path("/mnt/raid/AgenticOS-2026/data/.archon_service_token").read_text().strip()
    client = TestClient(app)
    r = client.post(
        "/api/sandbox",
        json={"code_content": "print(1)"},
        headers={"X-Archon-Service-Token": T},
    )
    assert r.status_code == 501, f"Expected 501, got {r.status_code}: {r.text}"
    data = r.json()
    assert "detail" in data
    assert "Sandbox deaktiviert" in data["detail"]


def test_sandbox_handler_source_has_no_subprocess():
    """AST-basierter Test: Handler-Rumpf enthält kein subprocess.run / sys.executable mehr."""
    source = Path("/mnt/raid/AgenticOS-2026/main.py").read_text(encoding="utf-8")

    # Finde die Handler-Funktion
    tree = ast.parse(source)
    handler_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "api_run_python_sandbox":
            handler_node = node
            break

    assert handler_node is not None, "api_run_python_sandbox function not found"

    # Prüfe auf verbotene Konstrukte im Body
    forbidden_calls = []
    for n in ast.walk(handler_node):
        if isinstance(n, ast.Call):
            # subprocess.run(...)
            if isinstance(n.func, ast.Attribute) and n.func.attr == "run":
                if isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess":
                    forbidden_calls.append(ast.get_source_segment(source, n) or "subprocess.run()")
            # sys.executable
            if isinstance(n.func, ast.Attribute) and n.func.attr == "executable":
                if isinstance(n.func.value, ast.Name) and n.func.value.id == "sys":
                    forbidden_calls.append(ast.get_source_segment(source, n) or "sys.executable")

    assert not forbidden_calls, f"Verbote Konstrukte im Handler gefunden: {forbidden_calls}"

    # Prüfe, dass HTTPException raise vorhanden ist
    has_raise = False
    for n in ast.walk(handler_node):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
            if isinstance(n.exc.func, ast.Name) and n.exc.func.id == "HTTPException":
                has_raise = True
                break
    assert has_raise, "Handler enthält kein 'raise HTTPException(...)'"


def test_sandbox_execute_endpoint_exists():
    """/api/sandbox/execute Route existiert (Parität-Check)."""
    from fastapi.testclient import TestClient
    from main import app

    T = Path("/mnt/raid/AgenticOS-2026/data/.archon_service_token").read_text().strip()
    client = TestClient(app)
    # 422 weil fehlende Pflichtfelder, aber NICHT 404 (Route existiert)
    r = client.post(
        "/api/sandbox/execute",
        json={},
        headers={"X-Archon-Service-Token": T},
    )
    assert r.status_code != 404, "/api/sandbox/execute Route nicht gefunden (404)"
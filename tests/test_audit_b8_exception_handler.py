"""Audit B8: globaler 500-Catch-All ohne Stacktrace-Leak."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_generic_exception_handler_registered():
    text = (ROOT / "archon" / "core" / "exceptions.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "generic_exception_handler")
    assert fn is not None
    assert "add_exception_handler(Exception, generic_exception_handler)" in text
    assert "logger.exception" in text
    assert "trace_id" in text

# -*- coding: utf-8 -*-
"""Re-Audit D16 (R-B6 / H2, H3, H5): Trace-Kontext im Dispatcher-/Provider-Pfad.

Statische Pruefung: jeder ausgehende httpx-/urllib-Call in den vier
Produktivdateien hat eine inject_headers()-Quelle innerhalb eines
child_span()-Blocks. Dynamische Pruefung: der Fehlerpfad von record_span()
meldet ueber note_local_trace_error(). W5-E ergaenzt container_ops.py:
der OmniRoute-/Lokal-LLM-Fallback-Dispatch war der einzige Hop ohne
Child-Span (Self-Parenting).
"""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OWNED_FILES = (
    "core_dispatcher.py",
    "backend/agent_router.py",
    "api_provider.py",
    "archon/routers/container_ops.py",
)

OUTBOUND_METHODS = {"post", "put", "patch", "request", "urlopen"}


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _parse(relative_path: str):
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return source, tree, parents


def _innermost_function(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _is_descendant(node: ast.AST, ancestor: ast.AST) -> bool:
    return any(child is node for child in ast.walk(ancestor))


@pytest.mark.parametrize("relative_path", OWNED_FILES)
def test_every_outbound_call_has_inject_headers_inside_child_span(relative_path):
    """Jeder httpx-/urllib-Call muss im selben Scope injizieren, und zwar im Block."""
    _source, tree, parents = _parse(relative_path)
    # FastAPI-Router-Dekoratoren (@router.post(...)) sind keine outbound Calls.
    # container_ops.py enthaelt zwei davon; ohne diesen Filter wuerden die
    # Endpoint-Funktionen faelschlich als HTTP-Hops geprueft.
    decorators = {
        dec
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for dec in node.decorator_list
        if isinstance(dec, ast.Call)
    }
    outbound = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node not in decorators
        and _call_name(node) in OUTBOUND_METHODS
    ]
    assert outbound, f"Kein outbound Call in {relative_path} gefunden (Test veraltet?)"

    seen_functions: set[int] = set()
    for call in outbound:
        fn = _innermost_function(call, parents)
        assert fn is not None, f"Outbound-Call ohne Funktion in {relative_path}"
        if id(fn) in seen_functions:
            continue
        seen_functions.add(id(fn))

        inject_calls = [n for n in ast.walk(fn) if _call_name(n) == "inject_headers"]
        assert inject_calls, (
            f"{relative_path}:{fn.name}: httpx-/urllib-Call ohne inject_headers-Quelle"
        )

        child_spans = [
            with_node
            for with_node in ast.walk(fn)
            if isinstance(with_node, ast.With)
            and any(_call_name(item.context_expr) == "child_span" for item in with_node.items)
        ]
        assert child_spans, (
            f"{relative_path}:{fn.name}: inject_headers ohne child_span()-Block"
        )
        assert any(
            _is_descendant(inject, with_node)
            for inject in inject_calls
            for with_node in child_spans
        ), (
            f"{relative_path}:{fn.name}: inject_headers() liegt nicht im "
            "child_span()-Block —traceparent wuerde die Parent-ID tragen"
        )


@pytest.mark.parametrize("relative_path", OWNED_FILES)
def test_no_second_root_in_outbound_paths(relative_path):
    """child_span() forkt; start_trace()/ensure_trace() duerfen nicht zusätzlich
    im selben Block stehen (sonst zweiter Root)."""
    _source, tree, _parents = _parse(relative_path)
    for with_node in ast.walk(tree):
        if not isinstance(with_node, ast.With):
            continue
        if not any(_call_name(item.context_expr) == "child_span" for item in with_node.items):
            continue
        body_names = {_call_name(n) for n in ast.walk(with_node)}
        assert "start_trace" not in body_names, (
            f"{relative_path}: start_trace() im child_span()-Block — zweiter Root"
        )
        assert "ensure_trace" not in body_names, (
            f"{relative_path}: ensure_trace() im child_span()-Block — zweiter Root"
        )


def test_trace_close_error_is_warning_and_counted():
    """H5: Abschlussfehler nicht mehr auf DEBUG, zentral gezaehlt."""
    source = (ROOT / "core_dispatcher.py").read_text(encoding="utf-8")
    assert 'note_local_trace_error("dispatch-trace-close", tr_exc)' in source
    assert 'logger.warning("[Dispatcher] Trace-Abschluss fehlgeschlagen: %s", tr_exc)' in source
    assert "logger.debug(f\"[Dispatcher] Trace-Abschluss fehlgeschlagen" not in source


def test_child_span_injects_new_span_id_not_parent():
    """Vertrag: traceparent traegt die Child-ID, nicht die Parent-ID."""
    from backend import trace_context as tc

    root_tid, root_sid = tc.start_trace()
    with tc.child_span() as (tid, sid, parent_sid):
        assert tid == root_tid
        assert sid != root_sid
        assert parent_sid == root_sid
        injected = tc.inject_headers({"Authorization": "Bearer x"})
        child_from_tp = tc.parse_traceparent(injected["traceparent"])
        assert child_from_tp == (root_tid, sid)
        assert injected["Authorization"] == "Bearer x"
    # Kontext nicht ueberschrieben
    assert tc.current_trace_id() == root_tid
    assert tc.current_span_id() == root_sid


def test_dispatch_trace_close_error_calls_note_local_trace_error(monkeypatch):
    """H5 dynamisch: record_span() wirft -> note_local_trace_error() wird gerufen."""
    import core_dispatcher as cd
    from backend import (
        concurrency_throttle,
        otel_tracer,
        role_budget_engine,
        semantic_cache,
        trace_context,
    )

    recorded: list[tuple[str, BaseException]] = []

    def _note(stage: str, exc: BaseException) -> None:
        recorded.append((stage, exc))

    monkeypatch.setattr(trace_context, "note_local_trace_error", _note)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("export-down")

    monkeypatch.setattr(otel_tracer.tracer, "record_span", _boom)
    monkeypatch.setattr(otel_tracer.tracer, "start_trace", lambda *_a, **_k: "trace-123")

    class _Throttle:
        async def acquire_slot(self, *_a, **_k):
            return True

        async def release_slot(self, *_a, **_k):
            return None

    class _Cache:
        def lookup(self, *_a, **_k):
            return None

        def store(self, *_a, **_k):
            return None

    class _Budget:
        def reserve(self, *_a, **_k):
            return {"allowed": True, "reservation_id": None}

    monkeypatch.setattr(concurrency_throttle, "concurrency_throttle", _Throttle())
    monkeypatch.setattr(semantic_cache, "semantic_cache_manager", _Cache())
    monkeypatch.setattr(role_budget_engine, "budget_bank", _Budget())

    async def _exec(*_a, **_k):
        return {"status": "success", "content": "", "cost_usd": 0.0}

    async def _identity(res, *_a, **_k):
        return res

    monkeypatch.setattr(cd, "_dispatch_to_omniroute_or_container_exec", _exec)
    monkeypatch.setattr(cd, "_guard_silent_failures", _identity)

    result = asyncio.run(
        cd.dispatch_to_omniroute_or_container(
            agent_id="test-agent",
            agent_name="test-agent",
            prompt="hi",
        )
    )
    assert result["status"] == "success"
    assert recorded, "note_local_trace_error wurde bei record_span-Fehler nicht gerufen"
    # W5-E: der Dispatcher oeffnet inzwischen weitere Child-Spans; ein
    # vorausgegangener ``child-span-hop``-Fehler darf die Pruefung des
    # Abschlussfehlers nicht verdecken. relevant ist, dass der Stage
    # ``dispatch-trace-close`` mit derselben Ausnahme gezaehlt wurde.
    stages = [stage for stage, _ in recorded]
    assert "dispatch-trace-close" in stages, (
        f"dispatch-trace-close nicht gezaehlt (Stages: {stages})"
    )
    exc = next(exc for stage, exc in recorded if stage == "dispatch-trace-close")
    assert isinstance(exc, RuntimeError) and str(exc) == "export-down"

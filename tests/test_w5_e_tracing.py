# -*- coding: utf-8 -*-
"""W5-E — Tracing-Regressionstests (D16-H1, D16-M1).

D16-H1: der produktive OmniRoute-/Lokal-LLM-Hop in ``container_ops.py`` muss
einen echten Child-Span forken. Der traceparent darf nicht die Span-ID des
Senders tragen. Geprueft dynamisch im Produktivpfad
``send_prompt_to_agent()`` mit gefaktem HTTP-Client.

D16-M1: die FastAPI-CORS muss ``traceparent``/``tracestate``/``X-Trace-Id``
sowohl in ``allow_headers`` als auch in ``expose_headers`` fuehren. Geprueft
mit echtem OPTIONS-Preflight und Antwort-Headers; das Frontend konsumiert
alle drei exponierten Header.

Keine Secrets, kein Netzwerk-/DB-Zugriff, kein Commit durch Subagenten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _reset_trace() -> None:
    from backend import trace_context as tc

    tc._current_trace.set("")
    tc._current_span.set("")
    tc._current_tracestate.set("")
    tc._current_sampled.set(None)


def _header_set(response: Any, name: str) -> set[str]:
    return {
        part.strip().lower()
        for part in response.headers.get(name, "").split(",")
        if part.strip()
    }


def _cors_client() -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from archon.services import runtime_endpoints as runtime

    app = FastAPI()

    @app.get("/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "true"}

    runtime.install_cors_middleware(app)
    return TestClient(app)


# ---------------------------------------------------------------------------
# D16-H1 — Self-Parenting am OmniRoute-/Lokal-LLM-Hop
# ---------------------------------------------------------------------------


def test_container_ops_outbound_uses_forked_child_span(monkeypatch):
    """Produktivpfad: gesendeter traceparent traegt die geforkte Child-ID."""
    from archon.routers import container_ops as co
    from backend import trace_context as tc

    captured: dict[str, Any] = {}
    hops: list[dict[str, Any]] = []

    class _FakeAppMain:
        DEFAULT_ROLES = [
            {"name": "Orchestrator & System-Architekt", "prompt": "system-prompt"}
        ]
        memory_bridge = None

        def load_roles(self) -> list[dict[str, str]]:
            return self.DEFAULT_ROLES

    monkeypatch.setattr(
        "archon.core.provider_registry.get_provider", lambda _name: _FakeAppMain()
    )
    monkeypatch.setattr(
        "backend.llm_egress_guard.evaluate_and_gate_llm_dispatch",
        lambda **_kwargs: {
            "model": "auto/best-free",
            "provider": "omniroute",
            "routed_to_local": True,
            "target_url": "http://127.0.0.1:11434/v1/chat/completions",
            "data_category": "general",
            "zero_egress_active": False,
        },
    )
    monkeypatch.setattr(
        "backend.llm_egress_guard.enforce_egress_firewall_for_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "backend.llm_egress_guard.sanitize_outbound_llm_payload",
        lambda payload, **_kwargs: payload,
    )
    monkeypatch.setattr(
        "backend.llm_egress_guard.log_completed_llm_dispatch",
        lambda **kwargs: captured.update(audit=kwargs) or {},
    )

    # Hop-Persistenz im Test nicht in die SQLite schreiben, aber die Kante
    # mitprotokollieren — der Child-Span bleibt damit verifybar.
    monkeypatch.setattr(
        tc,
        "_record_child_hop",
        lambda trace_id, span_id, parent_span_id, **_kwargs: hops.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            }
        ),
    )

    class _FakeResponse:
        status_code = 200
        text = "ok"

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "fertig"}}]}

    class _FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *_exc: Any) -> None:
            return None

        def post(self, url: str, *, json: Any = None, headers: Any = None) -> Any:
            captured["headers"] = dict(headers or {})
            captured["span_at_post"] = tc.current_span_id()
            captured["trace_at_post"] = tc.current_trace_id()
            return _FakeResponse()

    monkeypatch.setattr("httpx.Client", _FakeClient)

    _reset_trace()
    root_tid = "a" * 32
    root_sid = "b" * 16
    tc.start_trace(tc.format_traceparent(root_tid, root_sid, sampled=True))

    result = co.send_prompt_to_agent(
        agent_name="test-agent", agent_config={}, user_input="hi"
    )

    assert result == "fertig"
    parsed = tc.parse_traceparent(captured["headers"]["traceparent"])
    assert parsed is not None
    trace_id, span_id = parsed
    assert trace_id == root_tid
    assert span_id != root_sid, "Self-Parenting: traceparent traegt die Parent-ID"
    assert span_id == captured["span_at_post"]
    assert captured["trace_at_post"] == root_tid
    # child_span() stellt den Kontext deterministisch wieder her.
    assert tc.current_trace_id() == root_tid
    assert tc.current_span_id() == root_sid
    # Effekt: echter Hop mit Parent-Kante + Audit mit geforkter Span-ID.
    assert hops and hops[0]["span_id"] == span_id
    assert hops[0]["parent_span_id"] == root_sid
    assert captured["audit"]["trace_id"] == root_tid
    assert captured["audit"]["extra"]["span_id"] == span_id
    _reset_trace()


def test_container_ops_injection_is_inside_child_span():
    """Statischer Rueckgriff: inject vor dem Post, beides im Child-Block."""
    src = (ROOT / "archon" / "routers" / "container_ops.py").read_text(
        encoding="utf-8"
    )
    child_at = src.index("with child_span() as (hop_tid, hop_sid, parent_sid):")
    inject_at = src.index("req_headers = inject_headers(req_headers)")
    post_at = src.index("res = client.post(url, json=payload, headers=req_headers)")
    assert child_at < inject_at < post_at
    assert "from backend.trace_context import child_span, inject_headers" in src


# ---------------------------------------------------------------------------
# D16-M1 — CORS ueber die Browser-Grenze
# ---------------------------------------------------------------------------


def test_cors_preflight_allows_trace_headers():
    origin = "http://localhost:3005"
    with _cors_client() as client:
        res = client.options(
            "/ping",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "traceparent,tracestate,X-Trace-Id"
                ),
            },
        )
    assert res.status_code == 200
    assert {"traceparent", "tracestate", "x-trace-id"}.issubset(
        _header_set(res, "access-control-allow-headers")
    )
    assert res.headers.get("access-control-allow-origin") == origin


def test_cors_simple_response_exposes_trace_headers():
    origin = "http://localhost:8787"
    with _cors_client() as client:
        res = client.get("/ping", headers={"Origin": origin})
    assert res.status_code == 200
    assert {"traceparent", "tracestate", "x-trace-id"}.issubset(
        _header_set(res, "access-control-expose-headers")
    )


def test_frontend_consumes_all_exposed_trace_headers():
    src = (ROOT / "frontend" / "src" / "lib" / "archon-api.ts").read_text(
        encoding="utf-8"
    )
    traced = src.split("export async function tracedFetch", 1)[1].split(
        "\nexport async function archonFetch", 1
    )[0]
    for header in ("traceparent", "tracestate", "X-Trace-Id"):
        assert f"res.headers.get('{header}')" in traced
    assert "export function getArchonTraceId" in src


# ---------------------------------------------------------------------------
# W3-Reste-Schutz: der bestehende Audit-/Shutdown-Fix bleibt unangetastet.
# ---------------------------------------------------------------------------


def test_w3_shutdown_audit_fix_is_preserved():
    src = (ROOT / "archon" / "services" / "runtime_endpoints.py").read_text(
        encoding="utf-8"
    )
    assert (
        'logger.error("[Shutdown] Audit-Anker-Stopp fehlgeschlagen: %s", _anchor_exc)'
        in src
    )
    assert (
        'logger.error("[Shutdown] Graceful Shutdown fehlgeschlagen: %s", e)' in src
    )
    assert '_audit_shutdown_failure("anchor_stop_failed", str(_anchor_exc))' in src
    assert '_audit_shutdown_failure("graceful_shutdown_failed", str(e))' in src
    assert "if _is_audit_strict():" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

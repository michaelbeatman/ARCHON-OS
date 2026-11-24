"""Re-Audit D16 / R-B6 - Trace-Kontext im Frontend (statische Absicherung).

Kein Node-Build noetig: die Tests pruefen den quelltextseitigen Vertrag der
W3C-Kontext-Erzeugung, Injektion und Weitergabe ueber Browser, Next.js-Proxy,
SSE und PocketBase.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

ARCHON_API = "lib/archon-api.ts"
EVENTS = "lib/useArchonEvents.ts"
ARCHON_ROUTE = "app/api/archon/[...path]/route.ts"
POCKETBASE = "lib/pocketbase.ts"
MEDIA_ROUTE = "app/api/media/[...path]/route.ts"

TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")


def _src(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


def _function_body(source: str, signature: str, next_marker: str) -> str:
    start = source.index(signature)
    end = source.index(next_marker, start)
    return source[start:end]


def test_browser_root_uses_w3c_format_and_crypto():
    src = _src(ARCHON_API)
    assert "export function createTraceparent" in src
    body = _function_body(src, "export function createTraceparent", "\nlet activeTracestate")
    # 128 Bit trace_id, 64 Bit span_id, kryptografisch erzeugt, lowercase Hex.
    assert "randomHex(16)" in body
    assert "randomHex(8)" in body
    assert "crypto.getRandomValues" in src
    assert "toString(16).padStart(2, '0')" in src
    assert "`00-${traceId}-${spanId}-01`" in body
    # Keine Null-ID: beide Guards muessen vorhanden sein.
    assert body.count("while (") == 2
    assert "ZERO_TRACE_ID" in body and "ZERO_SPAN_ID" in body


def test_create_traceparent_template_logic():
    """Kleine JS-Logikpruefung ohne Node: gerendertes Template muss W3C-gueltig sein."""
    src = _src(ARCHON_API)
    body = _function_body(src, "export function createTraceparent", "\nlet activeTracestate")
    template = body.split("return `", 1)[1].split("`;", 1)[0]
    trace_id = "a" * 32
    span_id = "b" * 16
    rendered = template.replace("${traceId}", trace_id).replace("${spanId}", span_id)
    assert TRACEPARENT_RE.fullmatch(rendered)
    assert rendered == f"00-{trace_id}-{span_id}-01"


def test_archon_fetch_injects_without_overwriting_existing_headers():
    src = _src(ARCHON_API)
    assert "export function withTraceHeaders" in src
    assert "if (!headers.has('traceparent'))" in src
    assert "headers.set('traceparent', createTraceparent())" in src
    assert "headers.has('tracestate')" in src
    fetch = _function_body(src, "export async function archonFetch", "\nexport const archonApi")
    assert "withTraceHeaders(init)" in fetch
    assert "fetch(`/api/archon/${cleanPath}`" in fetch
    assert "setArchonTracestate(res.headers.get('tracestate'))" in fetch


def test_proxy_generates_valid_root_when_header_missing():
    src = _src(ARCHON_ROUTE)
    assert "function rootTraceparent" in src
    assert "crypto.getRandomValues" in src
    assert "outgoingTp = rootTraceparent()" in src
    assert "const forkedTp = childTraceparent(rawTp)" in src
    assert "forwardHeaders['traceparent'] = outgoingTp" in src
    assert "respHeaders['traceparent'] = outgoingTp" in src
    # Der alte null-Pfad darf nicht mehr existieren.
    assert "if (childTp) forwardHeaders" not in src
    assert "if (childTp) respHeaders" not in src


def test_proxy_consumes_sse_query_param_and_tracestate():
    src = _src(ARCHON_ROUTE)
    assert "incomingTraceparent(request)" in src
    assert "request.nextUrl.searchParams.get('traceparent')" in src
    assert "request.nextUrl.searchParams.get('tracestate')" in src
    assert "forwardHeaders['tracestate'] = inboundTracestate" in src
    assert "searchParams.delete('traceparent')" in src


def test_sse_event_source_carries_traceparent_in_query():
    src = _src(EVENTS)
    assert "createTraceparent" in src
    assert "tracedEventsUrl()" in src
    assert "searchParams.set('traceparent'" in src
    assert "new EventSource(" in src


def test_pocketbase_sdk_hooks_inject_trace_headers():
    src = _src(POCKETBASE)
    assert "client.beforeSend = " in src
    assert "createTraceparent()" in src
    assert "traceparent" in src and "tracestate" in src
    assert "installTraceHook(pb)" in src
    assert "installTraceHook(pbMedia)" in src


def test_media_proxy_propagates_trace_context():
    src = _src(MEDIA_ROUTE)
    assert "function traceHeaders" in src
    assert "rootTraceparent()" in src
    assert "crypto.getRandomValues" in src
    assert "traceparent: forked || rootTraceparent()" in src
    assert "...trace" in src
    assert "Object.assign(headers, traceHeaders(req))" in src
    assert "{ ...traceHeaders(request) }" in src

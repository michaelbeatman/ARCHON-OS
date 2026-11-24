"""Audit D16: leichter W3C-Trace-Context (ohne OTel-SDK-Abhängigkeit).

LIEFERT: traceparent-Format/Parse, contextvars-basierte aktive Trace-/Span-ID,
Header-Injektion für ausgehende Requests und Extraktion aus eingehenden
Requests. Dies ist bewusst ein minimaler, abhängigkeitsfreier Kern: der
frühere Claim „OpenTelemetry & Langfuse" war code-seitig nicht haltbar
(kein SDK, kein traceparent). Der Anschluss an einen echten Collector ist
ein eigener Folgeschritt.
"""

from __future__ import annotations

import contextvars
import re
import secrets
from typing import Any, Mapping, Optional

_TRACEPARENT_RE = re.compile(
    r"^(00)-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$", re.IGNORECASE
)
_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16

_current_trace: contextvars.ContextVar[str] = contextvars.ContextVar("archon_trace_id", default="")
_current_span: contextvars.ContextVar[str] = contextvars.ContextVar("archon_span_id", default="")


def new_ids() -> tuple[str, str]:
    """Erzeugt konforme 128-Bit-Trace- und 64-Bit-Span-IDs (nie 0)."""
    return secrets.token_hex(16), secrets.token_hex(8)


def parse_traceparent(value: Optional[str]) -> Optional[tuple[str, str]]:
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip())
    if not match:
        return None
    version, trace_id, span_id, _flags = match.groups()
    if version != "00" or trace_id == _ZERO_TRACE or span_id == _ZERO_SPAN:
        return None
    return trace_id.lower(), span_id.lower()


def format_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    return f"00-{trace_id.lower()}-{span_id.lower()}-{'01' if sampled else '00'}"


def start_trace(incoming: Optional[str] = None) -> tuple[str, str]:
    """Setzt den aktiven Kontext (aus eingehendem Header oder neu) und liefert ihn."""
    parsed = parse_traceparent(incoming)
    trace_id, span_id = parsed if parsed else new_ids()
    _current_trace.set(trace_id)
    _current_span.set(span_id)
    return trace_id, span_id


def current_trace_id() -> str:
    return _current_trace.get()


def current_span_id() -> str:
    return _current_span.get()


def inject_headers(headers: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """traceparent in einen Header-Dict einfügen (für urllib/httpx/requests)."""
    out = dict(headers or {})
    trace_id = current_trace_id()
    span_id = current_span_id()
    if trace_id and span_id:
        out["traceparent"] = format_traceparent(trace_id, span_id)
    return out


def extract_headers(headers: Mapping[str, str]) -> Optional[str]:
    """Liest traceparent case-insensitiv aus einem Header-Mapping."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    value = lowered.get("traceparent")
    return str(value) if value else None

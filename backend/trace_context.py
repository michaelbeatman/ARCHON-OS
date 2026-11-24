"""Audit D16: leichter W3C-Trace-Context (ohne OTel-SDK-Abhängigkeit).

LIEFERT: traceparent/tracestate-Format/Parse inkl. W3C-Validierung,
contextvars-basierte aktive Trace-/Span-ID, Sampling-Entscheidung,
Header-Injektion für ausgehende Requests und Extraktion aus eingehenden
Requests. Child-Spans erzeugen pro Systemgrenze eine neue 64-Bit-Span-ID
und übernehmen tracestate sowie das Sampled-Flag unverändert.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import random
import re
import secrets
from typing import Any, Iterator, Mapping, Optional

_TRACEPARENT_RE = re.compile(
    r"^(00)-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$", re.IGNORECASE
)
# W3C tracestate: key = lcalpha 0*255(lcalpha / DIGIT / '_' / '-' / '*' / '/')
# value = printable US-ASCII ohne ',' und '='; max. 32 Einträge / 512 Zeichen.
_TRACESTATE_KEY_RE = re.compile(r"^[a-z0-9_*/\-]{1,256}$")
_TRACESTATE_VALUE_RE = re.compile(r"^[\x20-\x2b\x2d-\x3c\x3e-\x7e]{0,256}$")
_TRACESTATE_MAX_LEN = 512
_TRACESTATE_MAX_ENTRIES = 32

_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16

_current_trace: contextvars.ContextVar[str] = contextvars.ContextVar("archon_trace_id", default="")
_current_span: contextvars.ContextVar[str] = contextvars.ContextVar("archon_span_id", default="")
_current_tracestate: contextvars.ContextVar[str] = contextvars.ContextVar("archon_tracestate", default="")
_current_sampled: contextvars.ContextVar[Optional[bool]] = contextvars.ContextVar(
    "archon_sampled", default=None
)


def new_ids() -> tuple[str, str]:
    """Erzeugt konforme 128-Bit-Trace- und 64-Bit-Span-IDs (nie 0)."""
    return secrets.token_hex(16), secrets.token_hex(8)


def _parse_full(value: Optional[str]) -> Optional[tuple[str, str, bool]]:
    if not value:
        return None
    match = _TRACEPARENT_RE.match(str(value).strip())
    if not match:
        return None
    version, trace_id, span_id, flags = match.groups()
    if version != "00" or trace_id == _ZERO_TRACE or span_id == _ZERO_SPAN:
        return None
    return trace_id.lower(), span_id.lower(), bool(int(flags, 16) & 0x01)


def parse_traceparent(value: Optional[str]) -> Optional[tuple[str, str]]:
    parsed = _parse_full(value)
    if parsed is None:
        return None
    return parsed[0], parsed[1]


def traceparent_sampled(value: Optional[str]) -> Optional[bool]:
    """Liest das Sampled-Flag eines gültigen traceparent (W3C)."""
    parsed = _parse_full(value)
    return parsed[2] if parsed else None


def format_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    return f"00-{trace_id.lower()}-{span_id.lower()}-{'01' if sampled else '00'}"


def sanitize_tracestate(value: Optional[str]) -> str:
    """Validiert W3C-Vendor-Einträge; verwirft ungültige/duplizierte und begrenzt auf 512 Zeichen."""
    if not value:
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for raw in str(value).split(","):
        part = raw.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        if not _TRACESTATE_KEY_RE.fullmatch(key) or not _TRACESTATE_VALUE_RE.fullmatch(val):
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append(f"{key}={val}")
        if len(kept) > _TRACESTATE_MAX_ENTRIES:
            kept.pop()
            break
    out = ",".join(kept)
    while len(out) > _TRACESTATE_MAX_LEN and kept:
        kept.pop()
        out = ",".join(kept)
    return out[:_TRACESTATE_MAX_LEN]


def should_sample(force: Optional[bool] = None, *, ignore_parent: bool = False) -> bool:
    """Zentrale Sampling-Entscheidung (OTEL_TRACES_SAMPLER / _ARG).

    Audit-/HITL-Pfade rufen ``force_sample_audit()`` bzw. ``should_sample(True)``
    auf und werden damit immer gesampelt (1.0).
    """
    if force is not None:
        return bool(force)
    name = (os.getenv("OTEL_TRACES_SAMPLER") or "parentbased_always_on").strip().lower()
    arg = (os.getenv("OTEL_TRACES_SAMPLER_ARG") or "").strip()
    active = None if ignore_parent else _current_sampled.get()
    if name.startswith("parentbased") and active is not None:
        return bool(active)
    if name in ("always_off", "parentbased_always_off"):
        return False
    if name in ("traceidratio", "parentbased_traceidratio"):
        try:
            ratio = float(arg or "1.0")
        except (TypeError, ValueError):
            ratio = 1.0
        return bool(random.random() < max(0.0, min(1.0, ratio)))
    return True


def force_sample_audit() -> bool:
    """Audit/HITL: Sampling hart auf 1.0 setzen (auch bei ratio-/off-Konfiguration)."""
    _current_sampled.set(True)
    return True


logger = logging.getLogger(__name__)


def note_local_trace_error(stage: str, exc: BaseException) -> None:
    """M4 (Re-Audit D16): zentrale Fehlerzaehlung fuer Trace-/Exportfehler.

    Vorher importierten `llm_kernel` und `workflow_dag_runner` diese Funktion
    aus diesem Modul, existierte aber nicht — beide fielen auf divergierende
    lokale Fallbacks zurueck.
    """
    try:
        from backend.otel_tracer import tracer
        tracer.note_local_trace_error(str(stage), exc)
    except Exception as count_exc:  # pragma: no cover - nur bei Import-/Tracer-Fehler
        logger.warning("[Trace] Fehlerzaehlung fuer %s nicht verfuegbar: %s", stage, count_exc)


def current_tracestate() -> str:
    return _current_tracestate.get()


def current_sampled() -> bool:
    return should_sample()


def start_trace(
    incoming: Optional[Any] = None,
    tracestate: Optional[str] = None,
    sampled: Optional[bool] = None,
) -> tuple[str, str]:
    """Setzt den aktiven Kontext (aus ingress traceparent/tracestate oder neu)."""
    tp = incoming
    if isinstance(incoming, Mapping):
        tp = extract_headers(incoming)
        tracestate = tracestate if tracestate is not None else extract_tracestate(incoming)
        sampled = sampled if sampled is not None else traceparent_sampled(tp)
    parsed = _parse_full(tp)
    if parsed:
        trace_id, span_id, flag = parsed
        sampled = sampled if sampled is not None else flag
        sampled_decision = should_sample(sampled)
    else:
        trace_id, span_id = new_ids()
        # Root-Trace: keine Sampled-Flag des vorherigen Kontexts erben.
        sampled_decision = should_sample(sampled, ignore_parent=True)
    # main.py ruft start_trace(extract_headers(...)): extract_headers hat
    # tracestate bereits in die ContextVar geschrieben — nicht verwerfen.
    ts = current_tracestate() if (tracestate is None and parsed) else tracestate
    _current_trace.set(trace_id)
    _current_span.set(span_id)
    _current_tracestate.set(sanitize_tracestate(ts))
    _current_sampled.set(sampled_decision)
    return trace_id, span_id


def current_trace_id() -> str:
    return _current_trace.get()


def current_span_id() -> str:
    return _current_span.get()


def inject_headers(
    headers: Optional[Mapping[str, str]] = None,
    *,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    tracestate: Optional[str] = None,
    sampled: Optional[bool] = None,
    traceparent: Optional[str] = None,
) -> dict[str, str]:
    """W3C-Header in ein Dict injizieren; explizite Werte erlauben Re-Injektion
    aus persistiertem Outbox-/DLQ-Kontext (drainer läuft ohne Request-Kontext)."""
    out = dict(headers or {})
    tid = str(trace_id or current_trace_id() or "").strip()
    sid = str(span_id or current_span_id() or "").strip()
    stored = str(traceparent or "").strip()
    if tracestate is None:
        # Nur tracestate des eigenen Traces übernehmen, nicht einen fremden Kontext.
        parsed_stored = parse_traceparent(stored) if stored else None
        own = (not stored) or (parsed_stored is not None and parsed_stored[0] == current_trace_id())
        ts = current_tracestate() if own else ""
    else:
        ts = str(tracestate)
    ts = sanitize_tracestate(ts)
    if stored and parse_traceparent(stored):
        out["traceparent"] = stored
    elif tid and sid:
        out["traceparent"] = format_traceparent(
            tid, sid, sampled if sampled is not None else should_sample()
        )
    if ts:
        out["tracestate"] = ts
    return out


def response_trace_headers(headers: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Antwort-Header: X-Trace-Id + forkbares traceparent/tracestate."""
    out = inject_headers(headers)
    tid = current_trace_id()
    if tid:
        out["X-Trace-Id"] = tid
    return out


def extract_headers(headers: Mapping[str, str]) -> Optional[str]:
    """Liest traceparent case-insensitiv und übernimmt tracestate/Sampled-Flag."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    value = lowered.get("traceparent")
    tp = str(value) if value else None
    if tp:
        flag = traceparent_sampled(tp)
        if flag is not None:
            _current_sampled.set(flag)
    if "tracestate" in lowered:
        _current_tracestate.set(sanitize_tracestate(lowered.get("tracestate")))
    return tp


def extract_tracestate(headers: Mapping[str, str]) -> str:
    lowered = {str(k).lower(): v for k, v in headers.items()}
    ts = sanitize_tracestate(lowered.get("tracestate"))
    _current_tracestate.set(ts)
    return ts


def ensure_trace() -> tuple[str, str]:
    """Liefert den aktiven Trace-Kontext oder startet automatisch einen neuen W3C-Trace."""
    tid = current_trace_id()
    sid = current_span_id()
    if tid and sid:
        return tid, sid
    return start_trace()


@contextlib.contextmanager
def child_span(
    incoming: Optional[str] = None,
    tracestate: Optional[str] = None,
    sampled: Optional[bool] = None,
) -> Iterator[tuple[str, str, Optional[str]]]:
    """Kind-Span im aktiven Trace (neue 64-Bit-ID, Eltern-Kante erhalten).

    Liefert ``(trace_id, span_id, parent_span_id)`` und stellt alle vier
    ContextVars beim Verlassen deterministisch wieder her. tracestate und
    Sampled-Flag werden an den Child weitergegeben.
    """
    parent_tid = current_trace_id()
    parent_sid = current_span_id() or None
    if incoming:
        parsed = parse_traceparent(incoming)
        if parsed:
            parent_tid, parent_sid = parsed
    next_ts = current_tracestate() if tracestate is None else tracestate
    next_sampled = current_sampled() if sampled is None else sampled
    if not parent_tid:
        parent_tid, new_sid = new_ids()
        parent_sid = None
        sampled_decision = should_sample(sampled, ignore_parent=True)
    else:
        new_sid = secrets.token_hex(8)
        sampled_decision = should_sample(next_sampled)
    tok_t = _current_trace.set(parent_tid)
    tok_s = _current_span.set(new_sid)
    tok_ts = _current_tracestate.set(sanitize_tracestate(next_ts))
    tok_sampled = _current_sampled.set(sampled_decision)
    try:
        yield parent_tid, new_sid, parent_sid
    finally:
        _current_sampled.reset(tok_sampled)
        _current_tracestate.reset(tok_ts)
        _current_span.reset(tok_s)
        _current_trace.reset(tok_t)


@contextlib.contextmanager
def use_trace_context(
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    traceparent: Optional[str] = None,
    tracestate: Optional[str] = None,
    sampled: Optional[bool] = None,
) -> Iterator[tuple[str, str]]:
    """Stellt einen persistierten Trace-Kontext im Drainer/DLQ-Reply wieder her."""
    parsed = parse_traceparent(traceparent) if traceparent else None
    tid = str(trace_id or (parsed[0] if parsed else "") or current_trace_id()).strip()
    sid = str(span_id or (parsed[1] if parsed else "") or current_span_id()).strip()
    if parsed and traceparent_sampled(traceparent) is not None:
        sampled = traceparent_sampled(traceparent) if sampled is None else sampled
    tok_t = _current_trace.set(tid)
    tok_s = _current_span.set(sid)
    tok_ts = _current_tracestate.set(
        sanitize_tracestate(current_tracestate() if tracestate is None else tracestate)
    )
    tok_sampled = _current_sampled.set(
        should_sample(sampled, ignore_parent=(sampled is None and parsed is None))
    )
    try:
        yield tid, sid
    finally:
        _current_sampled.reset(tok_sampled)
        _current_tracestate.reset(tok_ts)
        _current_span.reset(tok_s)
        _current_trace.reset(tok_t)


def inject_payload(payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Fuegt trace_id (und falls vorhanden span_id/tracestate) non-destruktiv in ein Webhook-Payload ein."""
    out = dict(payload or {})
    tid = current_trace_id()
    sid = current_span_id()
    if tid and "trace_id" not in out:
        out["trace_id"] = tid
    if sid and "span_id" not in out:
        out["span_id"] = sid
    ts = current_tracestate()
    if ts and "tracestate" not in out:
        out["tracestate"] = ts
    return out

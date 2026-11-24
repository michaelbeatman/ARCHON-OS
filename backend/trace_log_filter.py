"""Re-Audit D16/H7: Bruecke vom W3C-Trace-Kontext in Python-Logs (Loki/Promtail).

``TraceIdFilter`` injiziert die aktive ``current_trace_id()`` als Attribut
``trace_id`` in jeden Log-Record und markiert die Nachricht zusaetzlich mit
einem stabilen Prefix ``[trace_id=<32-hex>]``. Promtail liest dieses Feld ueber
die ``(?P<trace_id>[0-9a-f]{32})``-Gruppe und setzt daraus das Loki-Label.

Ohne aktiven Trace-Kontext bleibt die Nachricht unveraendert; ``record.trace_id``
ist dann leer (aber immer vorhanden, damit Formatter nicht scheitern).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^\[trace_id=[0-9a-f]{32}\]\s*", re.IGNORECASE)


class TraceIdFilter(logging.Filter):
    """Logging-Filter: trace_id aus dem ContextVar in Log-Records injizieren."""

    def __init__(self, name: str = "", *, inject_message: bool = True) -> None:
        super().__init__(name)
        self.inject_message = inject_message

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from backend.trace_context import current_trace_id

            trace_id = str(current_trace_id() or "").strip().lower()
        except Exception:
            trace_id = ""
        if not _TRACE_ID_RE.fullmatch(trace_id):
            trace_id = ""
        record.trace_id = trace_id

        if trace_id and self.inject_message:
            text = record.getMessage()
            if not _PREFIX_RE.match(text):
                # Args auflösen, sonst formatiert der Handler erneut und haengt
                # das Prefix doppelt an.
                record.msg = f"[trace_id={trace_id}] {text}"
                record.args = ()
        return True


def install_trace_log_filter(
    logger: Optional[logging.Logger] = None,
) -> TraceIdFilter:
    """Filter idempotent auf Root-/Ziel-Loggern und ihren Handlern installieren.

    Aufgerufen beim Import von ``backend.otel_tracer``. Eigene Logger koennen
    das explizit fuer ihre Handler nachholen (z. B. in Custom-Bootstrap-Pfaden).
    """
    target = logger if logger is not None else logging.getLogger()
    existing = next((f for f in target.filters if isinstance(f, TraceIdFilter)), None)
    trace_filter = existing or TraceIdFilter()
    if existing is None:
        target.addFilter(trace_filter)

    handlers = list(target.handlers)
    if logger is None:
        handlers.extend(logging.getLogger().handlers)
    for handler in handlers:
        if not any(isinstance(f, TraceIdFilter) for f in handler.filters):
            handler.addFilter(trace_filter)
    return trace_filter

# mypy: ignore-errors
"""
backend/otel_tracer.py
OpenTelemetry- & Langfuse-kompatibler Tracer für Archon OS (Pillar 1 & 6).
Erfasst hierarchische Traces und Spans für Tasks, Agenten-Delegationen,
Tool-Ausführungen und LLM-Aufrufe mit Latenz, Token-Verbrauch und Kosten.
"""
import logging

_archon_exc_logger = logging.getLogger("otel_tracer")

# D16/MED: Status der Log-Bruecke (Loki/Promtail) fuer get_tracing_status().
_TRACE_LOG_FILTER_STATUS = {"installed": False, "error": ""}

import contextvars
import datetime
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

_LOCAL_LOCK = threading.Lock()

class OpenTelemetryTracer:
    """
    Zentraler OpenTelemetry- & Langfuse-Tracer für Archon OS.
    Speichert Spans transaktional in agentic_memory.db und streamt bei Bedarf an Langfuse.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._export_stats = {"success": 0, "failures": 0, "last_error": ""}
        self._record_stats = {"success": 0, "failures": 0, "sampled_out": 0, "last_error": ""}
        self._stage_failures: Dict[str, int] = {}
        self._init_db()

    def note_local_trace_error(self, stage: str, exc: BaseException) -> None:
        """Sichtbar machen statt still verschlucken (D16/MED).

        Aufrufer (z. B. llm_kernel/workflow_dag_runner) können damit Start-,
        Span- und End-Fehler auf WARNING heben und im Status zählen.
        """
        self._record_stats["failures"] += 1
        self._record_stats["last_error"] = f"{stage}: {exc}"
        key = str(stage)
        self._stage_failures[key] = self._stage_failures.get(key, 0) + 1
        _archon_exc_logger.warning("[otel_tracer] %s fehlgeschlagen: %s", stage, exc)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS otel_traces (
                    trace_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    name TEXT NOT NULL,
                    agent_id TEXT,
                    status TEXT DEFAULT 'OK',
                    total_tokens INTEGER DEFAULT 0,
                    total_cost_usd REAL DEFAULT 0.0,
                    duration_ms REAL DEFAULT 0.0,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    metadata_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS otel_spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    span_type TEXT NOT NULL, -- 'task', 'agent', 'llm', 'tool'
                    name TEXT NOT NULL,
                    agent_id TEXT,
                    model TEXT,
                    input_data TEXT,
                    output_data TEXT,
                    status TEXT DEFAULT 'OK',
                    status_message TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    duration_ms REAL DEFAULT 0.0,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    attributes_json TEXT,
                    FOREIGN KEY (trace_id) REFERENCES otel_traces(trace_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_otel_trace_task ON otel_traces(task_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_otel_spans_trace ON otel_spans(trace_id, parent_span_id);")
            conn.commit()

    def start_trace(
        self,
        name: str,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        """Startet oder verknuepft einen Root-Trace (W3C 128-Bit-Hex-Format, D16 F02/F03)."""
        active_tid = ""
        try:
            from backend.trace_context import current_trace_id, ensure_trace
            active_tid = current_trace_id()
            if not active_tid and not trace_id:
                active_tid, _ = ensure_trace()
        except Exception as exc:
            # Re-Audit D16/H4: frueher `except Exception: active_tid = ''` —
            # der Fehler war unsichtbar und der Trace bekam einen zweiten Root.
            self.note_local_trace_error("start_trace-context", exc)
            active_tid = ""
        resolved_tid = (trace_id or active_tid or secrets.token_hex(16)).strip()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _LOCAL_LOCK:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO otel_traces (trace_id, task_id, name, agent_id, status, start_time, metadata_json)
                    VALUES (?, ?, ?, ?, 'RUNNING', ?, ?)
                """, (resolved_tid, task_id or resolved_tid, name, agent_id, now_iso, json.dumps(metadata or {})))
                conn.commit()
        return resolved_tid

    def end_trace(self, trace_id: str, status: str = "OK", metadata_update: Optional[Dict[str, Any]] = None):
        """Schließt einen Root-Trace ab und aggregiert Spans (Wall-Clock-Dauer, F28)."""
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now_dt.isoformat()
        with _LOCAL_LOCK:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        COALESCE(SUM(total_tokens), 0),
                        COALESCE(SUM(cost_usd), 0.0),
                        COALESCE(SUM(duration_ms), 0.0)
                    FROM otel_spans WHERE trace_id = ?
                """, (trace_id,))
                row = cur.fetchone()
                tot_tok = row[0] if row else 0
                tot_cost = row[1] if row else 0.0
                span_sum_ms = float(row[2] if row else 0.0)

                tr_row = cur.execute(
                    "SELECT start_time FROM otel_traces WHERE trace_id = ?",
                    (trace_id,),
                ).fetchone()
                tot_dur = span_sum_ms
                if tr_row and tr_row[0]:
                    try:
                        st = datetime.datetime.fromisoformat(str(tr_row[0]).replace("Z", "+00:00"))
                        if st.tzinfo is None:
                            st = st.replace(tzinfo=datetime.timezone.utc)
                        tot_dur = max(0.0, (now_dt - st).total_seconds() * 1000.0)
                    except Exception as exc:
                        # Re-Audit D16/H4: fehlerhafte Startzeit darf nicht
                        # still durch die Span-Summe ersetzt werden.
                        self.note_local_trace_error("end_trace-duration", exc)
                        tot_dur = span_sum_ms

                cur.execute("""
                    UPDATE otel_traces
                    SET status = ?, end_time = ?, total_tokens = ?, total_cost_usd = ?, duration_ms = ?
                    WHERE trace_id = ?
                """, (status, now_iso, tot_tok, tot_cost, tot_dur, trace_id))
                conn.commit()

        # Asynchroner Export an OTLP / Langfuse (falls konfiguriert)
        self._export_async(trace_id)

    def record_span(
        self,
        trace_id: str,
        name: str,
        span_type: str,
        parent_span_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
        input_data: Any = None,
        output_data: Any = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        status: str = "OK",
        status_message: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        *,
        _span_id: Optional[str] = None,
    ) -> str:
        """Speichert einen Span mit der EINEN ID-Quelle aus ``trace_context``.

        D16/HIGH: bei uebergebenem Parent darf niemals ``current_span_id()``
        als eigene ``span_id`` benutzt werden — das erzeugte einen
        selbst-parentenden Span (``parentSpanId == spanId``) im OTLP-Export.
        Stattdessen wird immer ein echtes ``child_span()`` geoeffnet.
        ``_span_id`` ist intern fuer bereits geforkte outbound Hops reserviert:
        deren ID stammt exakt aus dem ``traceparent`` des HTTP-Requests.
        """
        attrs = dict(attributes or {})
        try:
            from backend.trace_context import (
                child_span,
                current_sampled,
                current_tracestate,
                format_traceparent,
            )
            if _span_id:
                # Hop-Span: ID kommt vom traceparent, KEIN zweiter Fork.
                span_id = str(_span_id)
                sampled = self._span_sampled(attrs, default=bool(current_sampled()))
                ts = current_tracestate()
            else:
                sampled_default = self._span_sampled(attrs, default=bool(current_sampled()))
                if parent_span_id:
                    # Echter Child des uebergebenen Parents — auch wenn der
                    # aktuelle Kontext genau diese Parent-ID trägt.
                    incoming = format_traceparent(
                        trace_id, parent_span_id, sampled=sampled_default
                    )
                    with child_span(incoming=incoming, _record_hop=False) as (
                        _tid, sid, resolved_parent
                    ):
                        span_id, parent_span_id = sid, resolved_parent or None
                else:
                    with child_span(_record_hop=False) as (_tid, sid, parent_sid):
                        span_id, parent_span_id = sid, parent_sid or None
                sampled = self._span_sampled(attrs, default=bool(current_sampled()))
                ts = current_tracestate()
            # Re-Audit H6/M2: die Sampling-Entscheidung wird als persistiertes
            # Flag gespeichert und ist damit im Export-Thread lesbar — nicht
            # nur ein Kosmetik-Attribut. Ein explizit uebergebenes Flag hat
            # Vorrang vor dem Kontext (z. B. bei Re-Injektion aus dem Drainer).
            attrs["archon.sampled"] = sampled
            if ts:
                attrs.setdefault("tracestate", ts)
        except Exception as exc:
            self.note_local_trace_error("span-context", exc)
            span_id = str(_span_id or secrets.token_hex(8))  # letzte Notation, wenn trace_context fehlt
            sampled = self._span_sampled(attrs, default=True)

        # Harte Invariante: kein Selbstloop im Span-Graph (S-16.5).
        if parent_span_id and span_id == parent_span_id:
            raise ValueError(
                f"span_id == parent_span_id ({span_id}); selbst-parentender Span verweigert"
            )

        # Hartes Sampling: "00-...-00" erzeugt gar keinen lokalen Span und
        # damit auch nichts, was spaeter exportiert werden koennte.
        if not sampled:
            self._record_stats["sampled_out"] += 1
            return ""

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        total_tokens = input_tokens + output_tokens

        inp_str = json.dumps(input_data, ensure_ascii=False) if isinstance(input_data, (dict, list)) else str(input_data or "")
        out_str = json.dumps(output_data, ensure_ascii=False) if isinstance(output_data, (dict, list)) else str(output_data or "")

        try:
            with _LOCAL_LOCK:
                with self._get_conn() as conn:
                    conn.execute("""
                        INSERT INTO otel_spans (
                            span_id, trace_id, parent_span_id, span_type, name, agent_id, model,
                            input_data, output_data, status, status_message, input_tokens, output_tokens,
                            total_tokens, cost_usd, duration_ms, start_time, end_time, attributes_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        span_id, trace_id, parent_span_id, span_type, name, agent_id, model,
                        inp_str, out_str, status, status_message, input_tokens, output_tokens,
                        total_tokens, cost_usd, duration_ms, now_iso, now_iso, json.dumps(attrs)
                    ))
                    conn.commit()
            self._record_stats["success"] += 1
        except Exception as exc:
            self.note_local_trace_error("record_span", exc)
            raise

        return span_id

    def get_trace_tree(self, trace_or_task_id: str) -> Optional[Dict[str, Any]]:
        """Gibt den vollständigen Trace-Baum mit allen verschachtelten Spans zurück."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM otel_traces 
                WHERE trace_id = ? OR task_id = ?
                ORDER BY start_time DESC LIMIT 1
            """, (trace_or_task_id, trace_or_task_id))
            trace_row = cur.fetchone()
            if not trace_row:
                return None

            trace_dict = dict(trace_row)
            actual_trace_id = trace_dict["trace_id"]

            cur.execute("""
                SELECT * FROM otel_spans 
                WHERE trace_id = ?
                ORDER BY start_time ASC
            """, (actual_trace_id,))
            span_rows = cur.fetchall()

            spans = [dict(s) for s in span_rows]
            trace_dict["spans"] = spans
            trace_dict["span_count"] = len(spans)
            return trace_dict

    def list_recent_traces(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Listet die jüngsten Traces mit Zusammenfassungsmetriken auf."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM otel_traces 
                ORDER BY start_time DESC 
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _span_sampled(attrs: Dict[str, Any], *, default: bool = True) -> bool:
        """Liest das persistierte Sampling-Flag (kein ContextVar-Zugriff im Export-Thread)."""
        raw = attrs.get("archon.sampled")
        if raw is None:
            return bool(default)
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)

    @staticmethod
    def _span_attributes(sp: Dict[str, Any]) -> Dict[str, Any]:
        """Attribute eines gespeicherten Spans als Dict (robust gegen Altbestände)."""
        try:
            return json.loads(str(sp.get("attributes_json") or "{}")) or {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _to_otlp_hex(raw: str, length: int) -> str:
        clean = "".join(ch for ch in (raw or "").lower() if ch in "0123456789abcdef")
        if len(clean) >= length:
            return clean[:length]
        return (clean + "0" * length)[:length]

    @staticmethod
    def _iso_to_unix_ns(iso_str: Optional[str]) -> str:
        if not iso_str:
            return str(int(time.time() * 1_000_000_000))
        try:
            dt = datetime.datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return str(int(dt.timestamp() * 1_000_000_000))
        except Exception:
            return str(int(time.time() * 1_000_000_000))

    def _build_otlp_payload(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        service_name = os.getenv("OTEL_SERVICE_NAME", "archon-os").strip() or "archon-os"
        tid_hex = self._to_otlp_hex(tree.get("trace_id", ""), 32)
        spans_out: List[Dict[str, Any]] = []
        for sp in tree.get("spans") or []:
            span_attrs = self._span_attributes(sp)
            # Sampling hart auch im Payload: nur das persistierte Flag zaehlt.
            # Ein fehlendes Flag in Altbeständen gilt als gesampelt.
            if not self._span_sampled(span_attrs, default=True):
                continue
            end_ns = int(self._iso_to_unix_ns(sp.get("end_time") or sp.get("start_time")))
            dur_ns = int(max(0.0, float(sp.get("duration_ms") or 0.0)) * 1_000_000)
            start_ns = max(0, end_ns - dur_ns)
            item: Dict[str, Any] = {
                "traceId": tid_hex,
                "spanId": self._to_otlp_hex(sp.get("span_id", ""), 16),
                "name": str(sp.get("name") or "span"),
                "kind": 1,
                "startTimeUnixNano": str(start_ns),
                "endTimeUnixNano": str(end_ns),
                "attributes": [
                    {"key": "archon.span_type", "value": {"stringValue": str(sp.get("span_type") or "")}},
                    {"key": "archon.agent_id", "value": {"stringValue": str(sp.get("agent_id") or "")}},
                    {"key": "gen_ai.request.model", "value": {"stringValue": str(sp.get("model") or "")}},
                    {"key": "gen_ai.usage.total_tokens", "value": {"intValue": str(int(sp.get("total_tokens") or 0))}},
                    {"key": "archon.sampled", "value": {"boolValue": self._span_sampled(span_attrs)}},
                ],
                "status": {"code": 1 if str(sp.get("status", "OK")).upper() == "OK" else 2},
            }
            if span_attrs.get("tracestate"):
                item["attributes"].append({
                    "key": "tracestate", "value": {"stringValue": str(span_attrs["tracestate"])[:512]},
                })
            if sp.get("parent_span_id"):
                item["parentSpanId"] = self._to_otlp_hex(str(sp["parent_span_id"]), 16)
            spans_out.append(item)
        if not spans_out:
            # Re-Audit M3: kein zufaelliger zweiter Root. Nur eine vom Aufrufer
            # persistierte Root-Span-ID darf hier verwendet werden; sonst bleibt
            # der Trace bewusst leer (gueltiges OTLP ohne Spans).
            root_sid = str(tree.get("span_id") or "").strip()
            if root_sid:
                spans_out.append({
                    "traceId": tid_hex,
                    "spanId": self._to_otlp_hex(root_sid, 16),
                    "name": str(tree.get("name") or "trace"),
                    "kind": 1,
                    "startTimeUnixNano": self._iso_to_unix_ns(tree.get("start_time")),
                    "endTimeUnixNano": self._iso_to_unix_ns(tree.get("end_time") or tree.get("start_time")),
                    "status": {"code": 1 if str(tree.get("status", "OK")).upper() == "OK" else 2},
                })
        return {
            "resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service_name}}]},
                "scopeSpans": [{"scope": {"name": "archon.otel_tracer", "version": "1.0.0"}, "spans": spans_out}],
            }]
        }

    def _export_async(self, trace_id: str) -> None:
        """Exportiert asynchron getrennt an OTLP/HTTP (Collector) und/oder Langfuse (F14/F15)."""
        otlp_ep = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
        lf_host = (os.getenv("LANGFUSE_HOST") or "").strip()
        lf_pub = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
        lf_sec = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
        lf_enabled = bool(lf_host and lf_pub and lf_sec)
        if not otlp_ep and not lf_enabled:
            return

        def _do_export():
            import base64
            import urllib.request

            from backend import trace_context as tc
            tree = self.get_trace_tree(trace_id)
            if not tree:
                return

            def _export_headers(base: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
                """D16/MED: W3C-Header am Export-Hop injizieren.

                Der Export thread hat eine kopierte ContextVar; mit
                ``child_span()`` entsteht pro Export eine eigene Span-ID bei
                gleicher trace_id. Der resultierende traceparent wird als
                Attribut am Export-Span persistiert.
                """
                parent_sid = tc.current_span_id() or secrets.token_hex(8)
                with tc.child_span(
                    incoming=tc.format_traceparent(str(tree.get("trace_id") or ""), parent_sid),
                ) as (hop_tid, hop_sid, hop_parent):
                    headers = tc.inject_headers(base)
                    tp = str(headers.get("traceparent") or "")
                    self._record_stats.setdefault("export_hops", 0)
                    self._record_stats["export_hops"] += 1
                    return headers, {
                        "traceparent": tp,
                        "span_id": hop_sid,
                        "parent_span_id": hop_parent or "",
                        "trace_id": hop_tid,
                    }

            if otlp_ep:
                try:
                    payload_obj = self._build_otlp_payload(tree)
                    # Nichts gesampelt -> kein Export (H6: kein OTLP-Payload).
                    if not payload_obj["resourceSpans"][0]["scopeSpans"][0]["spans"]:
                        return
                    headers, hop = _export_headers({"Content-Type": "application/json"})
                    for sp in payload_obj["resourceSpans"][0]["scopeSpans"][0]["spans"]:
                        sp.setdefault("attributes", []).append({
                            "key": "archon.export_traceparent",
                            "value": {"stringValue": hop["traceparent"]},
                        })
                    otlp_url = otlp_ep if otlp_ep.rstrip("/").endswith("/v1/traces") else f"{otlp_ep.rstrip('/')}/v1/traces"
                    payload = json.dumps(payload_obj).encode("utf-8")
                    req = urllib.request.Request(
                        otlp_url,
                        data=payload,
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5):
                        pass
                    self._export_stats["success"] += 1
                except Exception as exc:
                    self._export_stats["failures"] += 1
                    self._export_stats["last_error"] = f"otlp: {exc}"
                    _archon_exc_logger.warning("[otel_tracer] OTLP-Export fehlgeschlagen (%s): %s", otlp_ep, exc)
            if lf_enabled:
                try:
                    auth_val = base64.b64encode(f"{lf_pub}:{lf_sec}".encode()).decode()
                    now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    batch: List[Dict[str, Any]] = [{
                        "id": str(uuid.uuid4()),
                        "timestamp": tree.get("start_time") or now_ts,
                        "type": "trace-create",
                        "body": {
                            "id": tree["trace_id"],
                            "name": tree.get("name", "archon-trace"),
                            "metadata": {"task_id": tree.get("task_id"), "agent_id": tree.get("agent_id")},
                        },
                    }]
                    for sp in tree.get("spans") or []:
                        if not self._span_sampled(self._span_attributes(sp)):
                            continue
                        batch.append({
                            "id": str(uuid.uuid4()),
                            "timestamp": sp.get("start_time") or now_ts,
                            "type": "span-create",
                            "body": {
                                "id": sp["span_id"],
                                "traceId": tree["trace_id"],
                                "parentObservationId": sp.get("parent_span_id"),
                                "name": sp.get("name", "span"),
                                "startTime": sp.get("start_time") or now_ts,
                                "endTime": sp.get("end_time") or now_ts,
                                "metadata": {"model": sp.get("model"), "tokens": sp.get("total_tokens")},
                            },
                        })
                    if len(batch) <= 1:
                        return  # nur unsampled Spans -> kein Langfuse-Export
                    headers, hop = _export_headers({
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {auth_val}",
                    })
                    batch[0]["body"]["metadata"] = dict(batch[0]["body"].get("metadata") or {})
                    batch[0]["body"]["metadata"]["traceparent"] = hop["traceparent"]
                    payload = json.dumps({"batch": batch}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{lf_host.rstrip('/')}/api/public/ingestion",
                        data=payload,
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5):
                        pass
                    self._export_stats["success"] += 1
                except Exception as exc:
                    self._export_stats["failures"] += 1
                    self._export_stats["last_error"] = f"langfuse: {exc}"
                    _archon_exc_logger.warning("[otel_tracer] Langfuse-Export fehlgeschlagen (%s): %s", lf_host, exc)

        if not hasattr(self, "_export_pool"):
            from concurrent.futures import ThreadPoolExecutor
            self._export_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="otel_export")
        # Re-Audit M2: ContextVars (trace_id/span_id/sampled/tracestate) gehen
        # nicht mit submit() in den Worker-Thread ueber. Explizit kopieren.
        ctx = contextvars.copy_context()
        self._export_pool.submit(ctx.run, _do_export)

    def _export_to_langfuse_async(self, trace_id: str) -> None:
        self._export_async(trace_id)

    def shutdown(self, wait: bool = True) -> None:
        """F27: Beendet den Export-ThreadPool sauber beim Shutdown."""
        pool = getattr(self, "_export_pool", None)
        if pool is not None:
            pool.shutdown(wait=wait, cancel_futures=False)


def get_tracing_status() -> dict:
    """F-075 / F18: ehrlicher Zustand des externen Exports (OTLP & Langfuse)."""
    otlp_ep = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    lf_host = (os.getenv("LANGFUSE_HOST") or "").strip()
    lf_pub = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    lf_sec = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    lf_configured = bool(lf_host and lf_pub and lf_sec)
    otlp_configured = bool(otlp_ep)
    configured = otlp_configured or lf_configured
    targets = []
    if otlp_configured:
        targets.append("otlp")
    if lf_configured:
        targets.append("langfuse")
    # D16/HIGH: der Collector exportiert aktuell NUR nach debug/file. Ohne
    # explizit verdrahteten Tempo/Jaeger-Downstream ehrlich ausweisen, statt
    # einen nicht gestarteten Consumer zu behaupten (S-1.5).
    downstream = (os.getenv("ARCHON_OTEL_COLLECTOR_DOWNSTREAM") or "").strip()
    stages = dict(getattr(tracer, "_stage_failures", {}))
    log_bridge_failures = sum(
        n for key, n in stages.items() if key.startswith("log_bridge") or key.startswith("trace-log-filter")
    )
    # A9-Nachlauf: runtime.py meldet den Stage als "sse-trace" (Bindestrich),
    # beide Schreibweisen muessen im Status sichtbar sein.
    sse_trace_failures = sum(
        n for key, n in stages.items()
        if key.startswith("sse_trace") or key.startswith("sse-trace")
    )
    return {
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "target": "+".join(targets) if targets else None,
        "otlp_configured": otlp_configured,
        "langfuse_configured": lf_configured,
        # S-1.5 / A1-Nachlauf: der Langfuse-Container und das Profil
        # `langfuse-not-configured` wurden entfernt. Es gibt nur noch externes
        # Langfuse ueber LANGFUSE_*-Werte — ohne Keys ehrlich not_configured,
        # kein Hinweis auf einen nicht mehr existierenden Compose-Befehl.
        "langfuse_status": "configured" if lf_configured else "not_configured",
        "langfuse_note": (
            "" if lf_configured else
            "Externes Langfuse nicht konfiguriert: LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY setzen. "
            "Das alte Profil 'langfuse-not-configured' und der lokale Container wurden entfernt."
        ),
        "service_name": os.getenv("OTEL_SERVICE_NAME", "archon-os").strip() or "archon-os",
        "collector_downstream": downstream or "not_configured/local_only",
        "collector_local_only": not bool(downstream),
        "log_bridge": {
            "status": "degraded" if log_bridge_failures else "ok",
            "installed": bool(_TRACE_LOG_FILTER_STATUS["installed"]),
            "failures": log_bridge_failures,
        },
        "sse_trace": {
            "status": "degraded" if sse_trace_failures else "ok",
            "failures": sse_trace_failures,
        },
        "local_trace_db": True,
        "export_stats": dict(getattr(tracer, "_export_stats", {})),
        "record_stats": dict(getattr(tracer, "_record_stats", {})),
        "sampler": (os.getenv("OTEL_TRACES_SAMPLER") or "parentbased_always_on").strip(),
        "sampler_arg": (os.getenv("OTEL_TRACES_SAMPLER_ARG") or "").strip(),
    }


# Globales Singleton
tracer = OpenTelemetryTracer()

# Re-Audit H7: Log-Bruecke zu Loki. Der Filter wird auf die Root-Handler
# installiert (main.py registriert dort den Datei-Handler fuer Promtail).
try:
    from backend.trace_log_filter import install_trace_log_filter
    install_trace_log_filter()
    _TRACE_LOG_FILTER_STATUS["installed"] = True
except Exception as _log_filter_exc:  # pragma: no cover - defensive
    # D16/MED: vorher DEBUG — ein fehlgeschlagener Filter liess jeden Log-Eintrag
    # ohne trace_id in Loki landen, während get_tracing_status() Erfolg meldete.
    _TRACE_LOG_FILTER_STATUS["error"] = str(_log_filter_exc)
    _archon_exc_logger.warning(
        "[otel_tracer] Trace-Log-Filter nicht installiert: %s", _log_filter_exc
    )
    tracer.note_local_trace_error("log_bridge/trace_log_filter", _log_filter_exc)

"""
backend/otel_tracer.py
OpenTelemetry- & Langfuse-kompatibler Tracer für Archon OS (Pillar 1 & 6).
Erfasst hierarchische Traces und Spans für Tasks, Agenten-Delegationen,
Tool-Ausführungen und LLM-Aufrufe mit Latenz, Token-Verbrauch und Kosten.
"""
import logging
_archon_exc_logger = logging.getLogger("otel_tracer")

import os
import sys
import time
import json
import uuid
import secrets
import sqlite3
import datetime
import threading
from typing import Dict, Any, List, Optional

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
        self._init_db()

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
        except Exception:
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
                    except Exception:
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
        attributes: Optional[Dict[str, Any]] = None
    ) -> str:
        """Erstellt und speichert einen abgeschlossenen Span (W3C 64-Bit-Span-ID, F02)."""
        span_id = secrets.token_hex(8)
        if not parent_span_id:
            try:
                from backend.trace_context import current_span_id
                cur_sid = current_span_id()
                if cur_sid and cur_sid != span_id:
                    parent_span_id = cur_sid
            except Exception:
                pass
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        total_tokens = input_tokens + output_tokens

        inp_str = json.dumps(input_data, ensure_ascii=False) if isinstance(input_data, (dict, list)) else str(input_data or "")
        out_str = json.dumps(output_data, ensure_ascii=False) if isinstance(output_data, (dict, list)) else str(output_data or "")

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
                    total_tokens, cost_usd, duration_ms, now_iso, now_iso, json.dumps(attributes or {})
                ))
                conn.commit()

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
                ],
                "status": {"code": 1 if str(sp.get("status", "OK")).upper() == "OK" else 2},
            }
            if sp.get("parent_span_id"):
                item["parentSpanId"] = self._to_otlp_hex(str(sp["parent_span_id"]), 16)
            spans_out.append(item)
        if not spans_out:
            spans_out.append({
                "traceId": tid_hex,
                "spanId": secrets.token_hex(8),
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
            import urllib.request
            import base64
            tree = self.get_trace_tree(trace_id)
            if not tree:
                return
            if otlp_ep:
                try:
                    otlp_url = otlp_ep if otlp_ep.rstrip("/").endswith("/v1/traces") else f"{otlp_ep.rstrip('/')}/v1/traces"
                    payload = json.dumps(self._build_otlp_payload(tree)).encode("utf-8")
                    req = urllib.request.Request(
                        otlp_url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
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
                    payload = json.dumps({"batch": batch}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{lf_host.rstrip('/')}/api/public/ingestion",
                        data=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Basic {auth_val}",
                        },
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
        self._export_pool.submit(_do_export)

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
    return {
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "target": "+".join(targets) if targets else None,
        "otlp_configured": otlp_configured,
        "langfuse_configured": lf_configured,
        "service_name": os.getenv("OTEL_SERVICE_NAME", "archon-os").strip() or "archon-os",
        "local_trace_db": True,
        "export_stats": dict(getattr(tracer, "_export_stats", {})),
    }


# Globales Singleton
tracer = OpenTelemetryTracer()

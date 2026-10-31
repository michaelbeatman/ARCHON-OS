"""
backend/otel_tracer.py
OpenTelemetry- & Langfuse-kompatibler Tracer für Archon OS (Pillar 1 & 6).
Erfasst hierarchische Traces und Spans für Tasks, Agenten-Delegationen,
Tool-Ausführungen und LLM-Aufrufe mit Latenz, Token-Verbrauch und Kosten.
"""

import os
import sys
import time
import json
import uuid
import sqlite3
import datetime
import threading
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

_LOCAL_LOCK = threading.Lock()

class OpenTelemetryTracer:
    """
    Zentraler OpenTelemetry- & Langfuse-Tracer für Archon OS.
    Speichert Spans transaktional in agentic_memory.db und streamt bei Bedarf an Langfuse.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
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

    def start_trace(self, name: str, task_id: Optional[str] = None, agent_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Startet einen neuen Root-Trace."""
        trace_id = f"tr-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.datetime.now().isoformat()
        with _LOCAL_LOCK:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO otel_traces (trace_id, task_id, name, agent_id, status, start_time, metadata_json)
                    VALUES (?, ?, ?, ?, 'RUNNING', ?, ?)
                """, (trace_id, task_id or trace_id, name, agent_id, now_iso, json.dumps(metadata or {})))
                conn.commit()
        return trace_id

    def end_trace(self, trace_id: str, status: str = "OK", metadata_update: Optional[Dict[str, Any]] = None):
        """Schließt einen Root-Trace ab und aggregiert Spans."""
        now_iso = datetime.datetime.now().isoformat()
        with _LOCAL_LOCK:
            with self._get_conn() as conn:
                cur = conn.cursor()
                # Aggregiere Tokens, Latenz und Kosten aus Spans
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
                tot_dur = row[2] if row else 0.0

                cur.execute("""
                    UPDATE otel_traces 
                    SET status = ?, end_time = ?, total_tokens = ?, total_cost_usd = ?, duration_ms = ?
                    WHERE trace_id = ?
                """, (status, now_iso, tot_tok, tot_cost, tot_dur, trace_id))
                conn.commit()

        # Asynchroner Export an Langfuse (falls konfiguriert)
        self._export_to_langfuse_async(trace_id)

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
        """Erstellt und speichert einen abgeschlossenen Span (LLM, Tool, Sub-Task)."""
        span_id = f"sp-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.datetime.now().isoformat()
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

    def _export_to_langfuse_async(self, trace_id: str):
        """Exportiert den Trace asynchron zu einer externen Langfuse- oder OTLP-Instanz (wenn konfiguriert)."""
        host = os.getenv("LANGFUSE_HOST") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        pub_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        sec_key = os.getenv("LANGFUSE_SECRET_KEY")
        if not (host and pub_key and sec_key):
            return  # Langfuse nicht konfiguriert -> lokaler Betrieb

        def _do_export():
            try:
                import urllib.request
                import base64
                tree = self.get_trace_tree(trace_id)
                if not tree:
                    return
                auth_val = base64.b64encode(f"{pub_key}:{sec_key}".encode()).decode()
                payload = json.dumps({"batch": [{"type": "trace-create", "body": tree}]}).encode()
                req = urllib.request.Request(
                    f"{host.rstrip('/')}/api/public/ingestion",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {auth_val}"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
            except Exception:
                pass  # Nie den laufenden Betrieb stören

        t = threading.Thread(target=_do_export, daemon=True)
        t.start()

# Globales Singleton
tracer = OpenTelemetryTracer()

"""
Archon OS Model Context Protocol (MCP) Driver for n8n Automation Mesh.

Provides a modular, capability-rich interface for agents to execute external tasks
through n8n without granting destructive administrative access to n8n internals.

Supports:
1. Article & Web Extraction (Clean text/markdown from URLs)
2. Multi-Channel Messaging (Email, Telegram, Slack, etc.)
3. Document & PDF Rendering (HTML/MD to PDF/DOCX)
4. Feeds & Opportunity Search (RSS, Job portals, news)
5. CRM & Data Record Sync (Leads, contacts, interactions)
6. Generic Webhook Fallback
7. Direct Python API, CLI execution, and stdio JSON-RPC 2.0 MCP server.
"""

import os
import sys
import json
import time
import re
import hashlib
import socket
import logging
import contextlib
from typing import Dict, Any, List, Optional

_archon_logger = logging.getLogger("archon.n8n_mcp_driver")
import urllib.request
import urllib.error

# D16/H-16-3: der Treiber laeuft als eigenstaendiger Stdio-/CLI-Prozess.
# Damit der W3C-Kontext nicht an der Prozessgrenze verloren geht, wird er
# explizit aus `_meta.traceContext` bzw. TRACEPARENT/TRACESTATE uebernommen.
_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)


def _trace_context_from(meta: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """W3C-Kontext aus MCP-`_meta.traceContext` oder der Umgebung lesen."""
    raw: Any = None
    if isinstance(meta, dict):
        raw = meta.get("traceContext", meta.get("traceparent"))
    src = raw if isinstance(raw, dict) else ({"traceparent": raw} if isinstance(raw, str) else {})
    out = {
        "traceparent": str(src.get("traceparent") or os.getenv("TRACEPARENT") or "").strip(),
        "tracestate": str(src.get("tracestate") or os.getenv("TRACESTATE") or "").strip(),
        "trace_id": str(src.get("trace_id") or "").strip(),
        "span_id": str(src.get("span_id") or "").strip(),
    }
    if not out["traceparent"] and out["trace_id"] and out["span_id"]:
        out["traceparent"] = f"00-{out['trace_id']}-{out['span_id']}-01"
    parsed = re.fullmatch(
        r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})",
        out["traceparent"], re.IGNORECASE,
    )
    if parsed:
        out["trace_id"] = out["trace_id"] or parsed.group(1).lower()
        out["span_id"] = out["span_id"] or parsed.group(2).lower()
    return out


@contextlib.contextmanager
def _replay_trace_context(ctx: Dict[str, str]):
    """MCP-Stdio: uebernommener Kontext wird im Treiber-Prozess replayed."""
    try:
        from backend import trace_context as tc
    except Exception:  # pragma: no cover - nur bei fehlendem Backend
        yield
        return
    with tc.use_trace_context(
        trace_id=ctx.get("trace_id") or None,
        span_id=ctx.get("span_id") or None,
        traceparent=ctx.get("traceparent") or None,
        tracestate=ctx.get("tracestate") or None,
    ):
        yield


# Environment configuration
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678").rstrip("/")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")

# Fallback detection: if running inside docker network, host 'n8n' is often available
def resolve_n8n_base_url() -> str:
    url = N8N_BASE_URL
    # Check if configured url works or if we should auto-adjust
    try:
        req = urllib.request.Request(f"{url}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                return url
    except Exception:
        pass

    # Try alternative docker hostname if on localhost
    if "localhost" in url or "127.0.0.1" in url:
        docker_url = "http://n8n:5678"
        try:
            req = urllib.request.Request(f"{docker_url}/healthz", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    return docker_url
        except Exception:
            pass

    return url


class N8nMcpDriver:
    """
    Modular MCP Driver connecting Archon Agentic OS to n8n workflows.
    """

    CAPABILITIES = [
        {
            "name": "mcp__n8n__extract_article",
            "description": "Extract clean, ad-free article text or markdown from a web page, job listing, or documentation URL via n8n.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The target website or article URL to extract."
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "text", "html"],
                        "default": "markdown",
                        "description": "Requested output format."
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether to extract author, publication date, and title."
                    }
                },
                "required": ["url"]
            },
            "webhook_path": "archon-extract-article"
        },
        {
            "name": "mcp__n8n__dispatch_message",
            "description": "Send a communication or notification across channels (email, telegram, slack, teams) via n8n.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "enum": ["email", "telegram", "slack", "teams", "webhook"],
                        "description": "Target communication channel."
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Recipient address, chat ID, or handle."
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject line (especially for email or ticket systems)."
                    },
                    "body": {
                        "type": "string",
                        "description": "Message content in plain text or markdown."
                    },
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of local file paths or URLs to attach."
                    }
                },
                "required": ["channel", "recipient", "body"]
            },
            "webhook_path": "archon-dispatch-message"
        },
        {
            "name": "mcp__n8n__render_document",
            "description": "Compile formatted HTML or Markdown into a finalized PDF or document (e.g. application letters, CVs, reports) via n8n.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "HTML or Markdown document body."
                    },
                    "document_type": {
                        "type": "string",
                        "enum": ["pdf", "docx", "html"],
                        "default": "pdf",
                        "description": "Output format."
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title / header."
                    },
                    "filename": {
                        "type": "string",
                        "description": "Target filename for storage."
                    }
                },
                "required": ["content"]
            },
            "webhook_path": "archon-render-document"
        },
        {
            "name": "mcp__n8n__search_or_feed",
            "description": "Query live news feeds, RSS sources, or search endpoints for new vacancies and market data via n8n.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["jobs", "news", "rss", "custom"],
                        "description": "Category or topic."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search keyword or filtering phrase."
                    },
                    "feed_url": {
                        "type": "string",
                        "description": "Direct RSS or Atom feed URL (if applicable)."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of items to return."
                    }
                }
            },
            "webhook_path": "archon-search-feed"
        },
        {
            "name": "mcp__n8n__sync_crm_record",
            "description": "Upsert contacts, leads, or job opportunities into CRM/PocketBase/Notion via n8n.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["lead", "contact", "vacancy", "interaction"],
                        "description": "Record type."
                    },
                    "identifier": {
                        "type": "string",
                        "description": "Unique key (e.g. email or URL) to prevent duplicates."
                    },
                    "data": {
                        "type": "object",
                        "description": "Field key-value pairs to store."
                    }
                },
                "required": ["entity_type", "data"]
            },
            "webhook_path": "archon-sync-crm"
        },
        {
            "name": "mcp__n8n__trigger_workflow",
            "description": "Trigger an automated n8n workflow via custom webhook path with retry-backoff.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "webhook_path": {
                        "type": "string",
                        "description": "Webhook endpoint path (e.g. 'archon-lead-intake')."
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON payload to pass to the workflow."
                    }
                },
                "required": ["webhook_path", "payload"]
            },
            "webhook_path": None
        },
        {
            "name": "mcp__n8n__list_capabilities",
            "description": "List all active n8n automation capabilities, tools, and endpoints.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "webhook_path": None
        },
        {
            "name": "mcp__n8n__health_check",
            "description": "Check if the n8n automation instance is responsive and return latency.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "webhook_path": None
        }
    ]

    def __init__(self, base_url: Optional[str] = None, api_key: str = N8N_API_KEY,
                 incoming_traceparent: Optional[str] = None):
        self.base_url = (base_url or resolve_n8n_base_url()).rstrip("/")
        self.api_key = api_key
        # Optionaler Kontext des Aufrufers (MCP-_meta / CLI / ENV). Ohne Wert
        # forkt child_span() den aktiven Kontext oder startet einen Root.
        self.incoming_traceparent = str(
            incoming_traceparent or os.getenv("TRACEPARENT") or ""
        ).strip()

    @staticmethod
    def _has_valid_payload(data: Any) -> bool:
        """D12/H-12-4: nur eine nichtleere, geparste Nutzlast ist ein Erfolg."""
        if data is None:
            return False
        if isinstance(data, (dict, list, tuple, str)):
            return bool(data)
        return True  # JSON-Zahl/-Boolean sind gueltige Quittungen

    def _http_post_json(self, url: str, payload: Dict[str, Any], timeout: float = 20.0,
                        idempotency_key: str = "") -> Dict[str, Any]:
        """Perform HTTP POST with standard library urllib."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Archon-Mesh-Kernel/2.0",
            "X-Archon-Timestamp": str(time.time())
        }
        # W4: Retry nach verlorener Response darf keine zweite Seitenwirkung
        # auslösen (doppelter Nachrichtenversand / CRM-Schreibvorgang).
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key

        # D06 (Re-Audit): exakt derselbe kompakte Body wie der n8n-Empfaenger
        # signiert (JSON.stringify(body)) — sonst lehnt die Signaturpruefung ab.
        body_bytes = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")

        # Fail-closed: ohne Secret wird gar nicht erst gesendet (der Empfaenger
        # wuerde ohnehin ablehnen). Kein Default-Secret, kein Repo-Secret.
        if not (os.environ.get("ARCHON_WEBHOOK_HMAC_SECRET") or "").strip():
            raise RuntimeError(
                "ARCHON_WEBHOOK_HMAC_SECRET fehlt — n8n-Webhook nicht gesendet (fail-closed)."
            )
        from utils.safe_http import webhook_signature_headers, _RejectAllRedirectsHandler
        headers.update(webhook_signature_headers(body_bytes))

        # D16/H-16-3: Header-Injektion NUR innerhalb des child_span()-Blocks
        # in execute_webhook() — sonst traego die neue Span-ID nicht in den
        # traceparent und die Kausalkante zeigt auf sich selbst.
        try:
            from backend import trace_context as tc
            headers = tc.inject_headers(headers)
        except Exception as exc:  # pragma: no cover - nur bei fehlendem Backend
            # Kein stiller Swallower: der Export-Hop wird sichtbar gemacht,
            # der Webhook selbst bleibt aber sendefaehig (Header sind additiv).
            _archon_logger.warning("[Trace] n8n-Hop: inject_headers nicht verfuegbar: %s", exc)

        # D06/MED-Rest: der Redirect-Block allein verhindert nicht, dass der
        # X-N8N-API-KEY an einen fremden Host geht. Ziel muss zusaetzlich gegen
        # die Egress-Regeln geprueft und auf die konfigurierte n8n-Base-URL
        # begrenzt sein (kein IMDS-/SSRF-Ziel mit API-Key).
        from urllib.parse import urlparse
        from utils.egress_guard import EgressBlocked, check_target_url
        _base = urlparse(self.base_url)
        _allowed_n8n = f"{_base.hostname}:{_base.port or (443 if _base.scheme == 'https' else 80)}"
        try:
            if not url.rstrip("/").startswith(self.base_url.rstrip("/") + "/"):
                raise EgressBlocked("Ziel liegt ausserhalb der konfigurierten n8n-Base-URL", url)
            check_target_url(url, allowed=[_allowed_n8n])
        except EgressBlocked as exc:
            return {"status": "error", "error": f"Egress-Block: {exc}"}

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
        opener = urllib.request.build_opener(_RejectAllRedirectsHandler())

        try:
            with opener.open(req, timeout=timeout) as resp:
                status_code = resp.status
                raw = resp.read().decode("utf-8", errors="replace")
                # D12/H-12-4: 2xx ohne Nutzlast ist KEINE nachgewiesene
                # Zustellung. Frueher wurde b"" als {"raw_response": ""} als
                # Erfolg an den Agenten zurueckgegeben.
                if not raw.strip():
                    return {
                        "status": "error",
                        "error_code": "EMPTY_WEBHOOK_BODY",
                        "status_code": status_code,
                        "error": f"HTTP {status_code} ohne Nutzlast — Wirkung nicht nachgewiesen",
                    }
                try:
                    data = json.loads(raw)
                except Exception as exc:
                    return {
                        "status": "error",
                        "error_code": "INVALID_WEBHOOK_JSON",
                        "status_code": status_code,
                        "data": {"raw_response": raw[:200]},
                        "error": f"Ungueltige JSON-Antwort des Webhooks: {exc}",
                    }
                if not (200 <= status_code < 300):
                    return {
                        "status": "error",
                        "error_code": "WEBHOOK_HTTP_ERROR",
                        "status_code": status_code,
                        "error": f"HTTP {status_code} vom Webhook",
                    }
                if not self._has_valid_payload(data):
                    return {
                        "status": "error",
                        "error_code": "EMPTY_WEBHOOK_BODY",
                        "status_code": status_code,
                        "error": "Webhook-Antwort enthielt keine verwertbare Nutzlast",
                    }
                return {"status": "success", "status_code": status_code, "data": data}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            return {
                "status": "error",
                "status_code": e.code,
                "error": f"HTTP {e.code}: {e.reason}",
                "detail": err_body
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def execute_webhook(self, webhook_path: str, payload: Dict[str, Any], max_retries: int = 3) -> Dict[str, Any]:
        """Execute webhook with exponential backoff."""
        # W4: Pfad-Traversal blockieren. lstrip('/') liess '../../rest/...'
        # durch — damit wurde der X-N8N-API-KEY an Admin-Endpunkte gesendet.
        clean_path = str(webhook_path or "").strip().lstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,127}", clean_path) or ".." in clean_path:
            return {"status": "error", "error": "Ungueltiger Webhook-Pfad."}
        url = f"{self.base_url}/webhook/{clean_path}"

        # Deterministischer Schlüssel: gleiche Anfrage = gleiche Aktion,
        # auch über mehrere retries hinweg.
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        idem_key = hashlib.sha256(f"{clean_path}|{canonical}".encode("utf-8")).hexdigest()

        try:
            from backend import trace_context as tc
        except Exception as exc:  # pragma: no cover - nur bei fehlendem Backend
            tc = None
            _archon_logger.warning("[Trace] n8n-Hop: trace_context nicht verfuegbar: %s", exc)

        # D16/H-16-3: genau EIN Child-Span je Webhook-Aufruf. inject_payload()
        # und inject_headers() MUESSEN innerhalb des Blocks laufen, damit die
        # NEUE Span-ID im traceparent und Payload steht (kein Self-Parenting).
        # Die Signatur wird anschliessend im _http_post_json ueber den
        # injizierten Final-Body neu berechnet.
        span_ctx = (
            tc.child_span(incoming=self.incoming_traceparent)
            if tc is not None
            else contextlib.nullcontext(("", "", None))
        )
        with span_ctx as (hop_tid, hop_sid, _hop_parent):
            traced_payload = tc.inject_payload(payload) if tc is not None else dict(payload)
            res = self._run_webhook_attempts(url, traced_payload, idem_key, max_retries)
        if isinstance(res, dict) and hop_tid and hop_sid:
            res.setdefault("trace_id", hop_tid)
            res.setdefault("span_id", hop_sid)
        return res

    def _run_webhook_attempts(
        self, url: str, payload: Dict[str, Any], idem_key: str, max_retries: int
    ) -> Dict[str, Any]:
        """Retry-Schleife; wird ausschliesslich innerhalb des Hop-Spans gerufen."""
        last_error = None
        for attempt in range(1, max_retries + 1):
            res = self._http_post_json(url, payload, idempotency_key=idem_key)
            # D12/H-12-4: success NUR bei validierter Nutzlast — nie eine
            # leere 200/204 als Erfolgsquittung an den Agenten durchreichen.
            if res.get("status") == "success" and self._has_valid_payload(res.get("data")):
                res["attempt"] = attempt
                return res
            # Ein leerer/ungueltiger Body bei 2xx ist deterministisch: ein
            # Retry mit identischem Idempotency-Key ergaebe dasselbe Ergebnis.
            # Keinscheiterfolg, sondern harter, sichtbarer Fehler.
            if res.get("error_code") in ("EMPTY_WEBHOOK_BODY", "INVALID_WEBHOOK_JSON"):
                return {"status": "error", **res}
            if res.get("status") == "success":
                return {
                    "status": "error",
                    "error_code": "EMPTY_WEBHOOK_BODY",
                    "error": "Webhook-Quittung ohne validierte Nutzlast",
                    "attempt": attempt,
                }

            # If server error or connection error, retry
            status_code = res.get("status_code", 0)
            if status_code in (404, 400, 401, 403):
                # Client error: do not retry endlessly
                return res

            last_error = res.get("error") or res.get("detail")
            time.sleep((2 ** (attempt - 1)) * 0.4)

        return {
            "status": "failed",
            "attempts": max_retries,
            "error": last_error or "Service unreachable",
            "url": url
        }

    def health_check(self) -> Dict[str, Any]:
        """Ping n8n healthz endpoint."""
        t0 = time.perf_counter()
        url = f"{self.base_url}/healthz"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Archon-Mesh-Kernel/2.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                return {
                    "status": "ok" if resp.status == 200 else "degraded",
                    "status_code": resp.status,
                    "base_url": self.base_url,
                    "latency_ms": latency_ms
                }
        except Exception as exc:
            return {
                "status": "offline",
                "error": str(exc),
                "base_url": self.base_url
            }

    def list_capabilities(self) -> Dict[str, Any]:
        """Return all catalogued capabilities and driver state."""
        health = self.health_check()
        tools_summary = []
        for c in self.CAPABILITIES:
            tools_summary.append({
                "name": c["name"],
                "description": c["description"],
                "webhook_path": c.get("webhook_path"),
                "status": "ready" if health.get("status") == "ok" else "pending_service"
            })
        return {
            "service": "n8n Automation Mesh",
            "base_url": self.base_url,
            "health": health,
            "available_tools": tools_summary
        }

    @staticmethod
    def _validate_arguments(schema: Dict[str, Any], arguments: Dict[str, Any]) -> str:
        """W4: deklarierte inputSchema zur Laufzeit prüfen (required + enum)."""
        for field in (schema or {}).get("required", []) or []:
            value = arguments.get(field)
            if value is None or value == "":
                return f"Pflichtfeld fehlt: {field}"
        for key, spec in ((schema or {}).get("properties") or {}).items():
            if key in arguments and "enum" in spec and arguments[key] not in spec["enum"]:
                return f"Ungueltiger Wert fuer {key}: {arguments[key]}"
        return ""

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call to the appropriate webhook or internal handler."""
        if name == "mcp__n8n__health_check":
            return self.health_check()
        if name == "mcp__n8n__list_capabilities":
            return self.list_capabilities()
        if name == "mcp__n8n__trigger_workflow":
            webhook_path = str(arguments.get("webhook_path", "")).strip()
            # Nur registrierte Webhooks — kein freier Pfad (API-Key-Exposition).
            known = {c.get("webhook_path") for c in self.CAPABILITIES if c.get("webhook_path")}
            if webhook_path not in known:
                return {"status": "error", "message": "Unbekannter/registrierter Webhook-Pfad erforderlich."}
            payload = arguments.get("payload", {})
            if not isinstance(payload, dict):
                return {"status": "error", "message": "payload muss ein Objekt sein."}
            return self.execute_webhook(webhook_path, payload)

        # Lookup capability definition
        for cap in self.CAPABILITIES:
            if cap["name"] == name:
                validation_error = self._validate_arguments(cap.get("inputSchema", {}), arguments)
                if validation_error:
                    return {"status": "error", "message": validation_error}
                webhook_path = cap.get("webhook_path")
                if webhook_path:
                    return self.execute_webhook(webhook_path, arguments)

        return {"status": "error", "message": f"Unknown tool: {name}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return MCP-compliant tool specifications."""
        return [
            {
                "name": c["name"],
                "description": c["description"],
                "inputSchema": c["inputSchema"]
            }
            for c in self.CAPABILITIES
        ]


# --- Stdio JSON-RPC 2.0 Server Loop for MCP Clients ---
def run_stdio_server():
    """Run interactive MCP stdio loop handling JSON-RPC requests."""
    driver = N8nMcpDriver()
    
    # Process line-by-line JSON-RPC
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Handle MCP Methods
        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "archon-n8n-mesh",
                        "version": "2.0.0"
                    }
                }
            }
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": driver.list_tools()
                }
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            # D16/H-16-3: der aufrufende Kontext kommt aus `_meta.traceContext`
            # (MCP) oder TRACEPARENT/TRACESTATE (ENV) und muss im Treiber-
            # prozess replayed werden — ContextVars des FastAPI-Prozesses
            # gibt es hier nicht.
            trace_ctx = _trace_context_from(params.get("_meta"))
            if trace_ctx["traceparent"]:
                driver.incoming_traceparent = trace_ctx["traceparent"]
            with _replay_trace_context(trace_ctx):
                call_res = driver.call_tool(tool_name, arguments)
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(call_res, indent=2, ensure_ascii=False)
                        }
                    ],
                    "isError": call_res.get("status") in ("error", "failed")
                }
            }
        else:
            if msg_id is not None:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
            else:
                continue

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        run_stdio_server()
    elif "--health" in sys.argv:
        driver = N8nMcpDriver()
        print(json.dumps(driver.health_check(), indent=2))
    elif "--capabilities" in sys.argv or "--tools" in sys.argv:
        driver = N8nMcpDriver()
        print(json.dumps(driver.list_capabilities(), indent=2))
    elif "--call" in sys.argv:
        idx = sys.argv.index("--call")
        if len(sys.argv) > idx + 1:
            tool = sys.argv[idx + 1]
            args = json.loads(sys.argv[idx + 2]) if len(sys.argv) > idx + 2 else {}
            cli_tp = ""
            if "--traceparent" in sys.argv:
                tpi = sys.argv.index("--traceparent")
                cli_tp = sys.argv[tpi + 1] if len(sys.argv) > tpi + 1 else ""
            driver = N8nMcpDriver(incoming_traceparent=cli_tp or None)
            with _replay_trace_context({"traceparent": driver.incoming_traceparent}):
                call_res = driver.call_tool(tool, args)
            print(json.dumps(call_res, indent=2))
    else:
        # Default info output
        driver = N8nMcpDriver()
        print("Archon n8n MCP Driver (v2.0)")
        print(f"Base URL: {driver.base_url}")
        print(f"Health:   {json.dumps(driver.health_check())}")
        print(f"Tools ({len(driver.CAPABILITIES)}):")
        for tool in driver.list_tools():
            print(f"  - {tool['name']}: {tool['description'][:75]}...")

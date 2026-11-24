# P1 Tracing -> P0 Compose Handoff Notes

Stand: 2026-11-24 | Commit-Serie: P1 Tracing (`main`)

## Was in P1 umgesetzt wurde (disjunkte Dateien)
- `backend/trace_context.py`: um `ensure_trace()`, `child_span()` (mit automatischem ContextVar-Reset und `parent_span_id`) und `inject_payload()` erweitert.
- `backend/otel_tracer.py`:
  - W3C-konforme 128-Bit-`trace_id` (32 Hex) & 64-Bit-`span_id` (16 Hex), Wiederverwendung des aktiven `trace_context` (kein doppelter Root-Trace mehr zwischen `llm_kernel` und `core_dispatcher`).
  - Saubere Trennung zwischen OTLP/HTTP (`OTEL_EXPORTER_OTLP_ENDPOINT` -> `POST .../v1/traces` mit `resourceSpans`) und Langfuse (`LANGFUSE_HOST` -> `/api/public/ingestion` im v2-Event-Format), plus Export-Zaehler & `logger.warning` bei Fehlern, `shutdown()`-Hook und Wall-Clock-Trace-Dauer.
- `core_dispatcher.py`, `backend/agent_router.py`, `backend/llm_egress_guard.py`, `archon/routers/hermes_proxy.py`, `archon/routers/container_ops.py`:
  - `traceparent`-Header-Propagation ueber alle Outbound-LLM-Hops (OmniRoute, OpenRouter, Groq, OpenAI, Anthropic, Ollama), `hermes_proxy` (inkl. Response-Header) und `trigger_n8n_execution` (im HMAC-signierten Payload + Header).
  - `trace_id` wird in `log_completed_llm_dispatch` -> `audit_log` mitgeschrieben.
- `archon/routers/operations_dag.py`: neuer Endpoint `GET /api/operations/traces/otel/status`.
- `config/otel-collector-config.yml`: neue Collector-Konfiguration (gRPC `:4317`, HTTP `:4318`).

## Compose-Einbindung fuer P0 (Hy4, `docker-compose.yml`)
Da `docker-compose*.yml` in P0 bei Hy4 liegt, bitte dort bei Bedarf folgenden Service + Env einhaengen:

```yaml
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.114.0
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    volumes:
      - ./config/otel-collector-config.yml:/etc/otelcol-contrib/config.yaml:ro
    ports:
      - "127.0.0.1:4317:4317"
      - "127.0.0.1:4318:4318"
    profiles: ["tracing", "observability", "all"]
    restart: unless-stopped
```

Und am `archon-os`-Service (wenn das Profil aktiv ist):
```yaml
    environment:
      - OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-}
      - OTEL_SERVICE_NAME=archon-os
```

# Archon OS – LLM-Tracing mit OpenTelemetry & Langfuse

*Stand: Oktober 2026 | Observability & Säule 1 & 6*
*Korrigiert: 24.11.2026 nach Audit D16 (siehe `audit_reports/2026-11-24_d16_tracing.md`)*

---

## 0. Ist-Zustand nach dem Audit 24.11.2026 (bitte zuerst lesen)

Die Aussage „vollwertiges, OpenTelemetry-konformes Tracing" in Abschnitt 1 war **nicht code-gedeckt**:

- Es ist **kein OpenTelemetry-SDK** installiert; `opentelemetry-api` war nur eine transitive FastAPI-Abhängigkeit.
- Es gab **kein `traceparent`** und keinen W3C-Propagator. An allen 18 untersuchten Systemgrenzen (Hermes, OmniRoute, n8n, PocketBase, MCP, SSE, Outbox, Async-Tasks) brach der Trace ab.
- `backend/otel_tracer.py` ist ein **lokaler SQLite-Span-Recorder** mit eigener ID-Generierung — kein OTel-Exporter. Der Langfuse-Export schluckt Fehler auf DEBUG-Ebene.
- `audit_log` und Receipt-Ledger hatten zunächst keine `trace_id`-Spalte — Audit und Tracing waren zwei getrennte Welten.

**Nach den Fix-Wellen (A1 + B6) gilt jetzt:**

| Fähigkeit | Status |
| :--- | :--- |
| W3C `traceparent` parsen/formatieren (`backend/trace_context.py`) | ✅ implementiert |
| Trace-/Span-IDs via `contextvars`, 128/64 Bit, konform | ✅ implementiert |
| Eingehender Request → Trace-Kontext (`TraceContextMiddleware`, Response-Header `X-Trace-Id`) | ✅ implementiert |
| Ausgehende OmniRoute-Anfrage → `traceparent`-Header | ✅ implementiert |
| Audit-Log übernimmt aktive `trace_id` automatisch aus dem Kontext | ✅ implementiert |
| Spalten `trace_id`/`session_id`/`correlation_id` in `audit_log` (aus A1) | ✅ implementiert |
| Propagation über **alle** 18 Grenzen (n8n, Hermes, PocketBase, MCP, SSE, Outbox, `to_thread`) | ⚠️ **Folgeschritt** |
| Echter OTel-Collector + Langfuse-Export mit Sampling/Alerting | ⚠️ **Folgeschritt** |

Die folgenden Abschnitte beschreiben das **Zielbild**; Abschnitt 0 beschreibt den **Ist-Zustand**.

---

## 1. Übersicht & Zielsetzung

Mit 56 autonomen Spezialisten-Rollen und mehrstufigen Fan-in-Delegationen (Robert -> Fachagenten -> Lisa -> Freigabe) reicht ein simples Text-Log nicht mehr aus, um Kosten, Latenzen und Fehlerquellen zu lokalisieren.

Archon OS integriert ein vollwertiges, OpenTelemetry-konformes Tracing-System:
- **Hierarchische Spans:** Jeder Kanban-Task und LLM-Aufruf wird als standardisierter Span mit Start-/Endzeit, Latenz in Millisekunden, Input- und Output-Tokens sowie Status erfasst.
- **Transaktionale Persistenz:** Alle Traces werden primär in `memory.db` in den Tabellen `otel_traces` und `otel_spans` (WAL-Modus) gespeichert – vollständig unabhängig von externer Cloud-Software.
- **Langfuse & OTLP Export:** Über Umgebungsvariablen (`LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) streamt der Tracer Spans automatisch asynchron an eine selbst-gehostete Langfuse-Instanz.

---

## 2. API-Schnittstellen

| Endpunkt | Methode | Beschreibung |
| :--- | :--- | :--- |
| `/api/operations/traces/otel` | `GET` | Listet die jüngsten Traces mit aggregierten Metriken (Laufzeit, Token-Summe, Kosten) auf. |
| `/api/operations/traces/otel/{trace_or_task_id}` | `GET` | Liefert den vollständigen hierarchischen Span-Baum einer Aufgabe inklusive Prompts und Antworten. |

Beispiel-Abfrage:
```bash
curl http://localhost:8501/api/operations/traces/otel?limit=10
```

---

## 3. Selbst-gehostetes Langfuse Dashboard (Docker)

In `docker-compose.yml` ist der Langfuse-Dienst unter dem Profil `tracing` verankert:
```bash
# Starten des Langfuse Dashboards auf Port 3000
docker compose --profile tracing up -d langfuse
```

Nach dem Start ist das Web-UI unter `http://localhost:3000` erreichbar. Die API-Keys aus Langfuse können anschließend in der `.env` hinterlegt werden:
```env
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```
Der Tracer erkennt diese Variablen automatisch und leitet künftige Spans ohne Neustart an Langfuse weiter.

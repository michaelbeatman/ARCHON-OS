# Archon OS – LLM-Tracing mit OpenTelemetry & Langfuse

*Stand: Oktober 2026 | Observability & Säule 1 & 6*

---

## 1. Übersicht & Zielsetzung

Mit 56 autonomen Spezialisten-Rollen und mehrstufigen Fan-in-Delegationen (Robert -> Fachagenten -> Lisa -> Freigabe) reicht ein simples Text-Log nicht mehr aus, um Kosten, Latenzen und Fehlerquellen zu lokalisieren.

Archon OS integriert ein vollwertiges, OpenTelemetry-konformes Tracing-System:
- **Hierarchische Spans:** Jeder Kanban-Task und LLM-Aufruf wird als standardisierter Span mit Start-/Endzeit, Latenz in Millisekunden, Input- und Output-Tokens sowie Status erfasst.
- **Transaktionale Persistenz:** Alle Traces werden primär in `agentic_memory.db` in den Tabellen `otel_traces` und `otel_spans` (WAL-Modus) gespeichert – vollständig unabhängig von externer Cloud-Software.
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

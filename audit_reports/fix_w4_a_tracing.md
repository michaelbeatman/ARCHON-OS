# Fix-Report — Remediation Welle 4 / W4-A (Distributed Tracing, F041, Domäne 16)

**Datum:** 25.11.2026 · **Welle:** W4-A · **Fix-ID:** F041
**Basis:** `00_SOLL_SPEC.md` §3/§2.5, `domain_16.md` (alle Befunde + Positivliste),
`MASTER_PLAN.md` §4/§5 (F041), `INCIDENT_2026-11-25_LOGIN_OUTAGE.md`.

**Ownership strikt eingehalten:** nur `backend/otel_tracer.py`,
`backend/trace_context.py`, `backend/trace_log_filter.py` (unverändert),
`backend/eval_gates.py`, `config/otel-collector-config.yml`,
`config/grafana/datasources/datasources.yml`, `docker-compose.yml`, `.env.example`,
`requirements.txt`, `requirements.lock.txt`, `scripts/mcp_n8n_driver.py`,
`scripts/sync_inbox_to_pocketbase.py`, Root-`archon_crm_mcp.py`,
`frontend/src/lib/pocketbase.ts` und neu `tests/test_fix_w4_a_tracing.py`.

**Nicht angefasst:** `core_dispatcher.py`, `backend/workflow_scheduler.py`,
`backend/event_mesh.py`, `archon/routers/mesh.py`, `utils/safe_http.py` (W4-B),
`main.py` (W4-C), `backend/metrics_collector.py`, `archon/routers/v2_capabilities.py`.

---

## 1. HIGH-Befunde

### H-16-1 — Kein OTel-SDK: ehrlicher Status statt halber Integration

**Entscheidung:** Variante 2 (ehrlicher Status), **vollständig** umgesetzt.

**Begründung („keine halbe Lösung"):**
- `requirements.lock.txt` ist eine Python-3.13-Hash-Lock-Resolution; CI installiert
  mit `--require-hashes --no-deps`. Ein SDK-Pin ohne Neuberechnung *aller* Hash-
  Zeilen (Plus Transitive `opentelemetry-semantic-conventions`,
  `opentelemetry-exporter-otlp-proto-common`, `opentelemetry-proto`, `protobuf`,
  `deprecated`) bricht den Installations-Gate. Die vorhandene Umgebung hat kein
  `pip` im CI-venv (Python 3.11.15) — eine saubere Resolution ist hier nicht
  reproduzierbar.
- Die komplette Produktivkette (18 Systemgrenzen, Sampling, Hop-Spans, Audit-
  Korrelation) ist auf die ContextVar-SSOT in `trace_context.py` gebaut. Ein
  `-SDK` „nebenbei" zu importieren hätte einen zweiten, konkurrierenden
  ID-/Span-Graph erzeugt — genau die halbe Lösung, die der Auftrag ausschließt.
- Stattdessen ist der Ist-Zustand jetzt **maschinenlesbar und in allen
  Ownership-Dokumenten konsistent** ausgewiesen.

**Nachher:**
- `get_tracing_status()` liefert `otel_sdk=false`, `otel_sdk_installed=false`,
  `implementation="w3c_trace_context_sqlite_recorder"` und einen expliziten
  `implementation_note` („W3C Trace Context + lokaler SQLite-Span-Recorder, kein
  OTel-SDK … kein TracerProvider, kein BatchSpanProcessor, kein SDK-Propagator").
- Modul-/Klassen-Docstrings in `otel_tracer.py` und `trace_context.py` sagen
  dasselbe; `requirements.txt`/`.lock` enthalten einen begründeten Vermerk
  (kein SDK-Pin, `opentelemetry-api` bleibt transitiv via FastAPI).
- `config/otel-collector-config.yml` trägt denselben Hinweis im Header.

**Verifikation:** `test_h16_1_status_declares_no_otel_sdk`,
`test_h16_1_no_sdk_pin_in_requirements`; live
`get_tracing_status()["otel_sdk"] is False`.

**Außerhalb Ownership (an D09/Doku-Owner eskaliert):**
`docs/system/LLM_TRACING_LANGFUSE_GUIDE.md:38` behauptet weiterhin
„vollwertiges, OpenTelemetry-konformes Tracing-System" (Abschnitt 0 korrigiert das
bereits, Abschnitt 1 nicht). Diese Datei liegt nicht in W4-A und wurde nicht
geändert.

### H-16-2 — Collector-Downstream, Tempo, Grafana, echter Default

**Vorher:** `exporters: [debug, file/traces-local]`; Datei in flüchtigem
Container-`/tmp`; kein Tempo; keine Trace-Datasource;
`OTEL_EXPORTER_OTLP_ENDPOINT=${...:-}` leer; toter
`OTEL_DOWNSTREAM_OTLP_ENDPOINT`-Knopf nur in `.env.example`.

**Nachher:**
- `config/otel-collector-config.yml`: neuer `otlphttp/downstream` mit
  `endpoint: http://tempo:4318` und eine zweite echte Traces-Pipeline
  `traces/downstream`. Der OTLP-Receiver bleibt in beiden Pipelines; laut
  OTel-Docs ist das explizit supported (Fan-out, pipeline-lokale
  Processor-Instanzen). Die bestehende `traces`-Pipeline bleibt unverändert —
  damit bleibt der ältere Test `test_med_d16_d01.py:113` gültig, statt ihn für
  eine Config-Änderung zu brechen.
- `file/traces-local` schreibt jetzt nach `/var/lib/otel/traces-local.json`
  auf dem neuen Volume `otel_local_traces` (kein Datenverlust bei Restart).
- `docker-compose.yml`: neuer Service `tempo` mit gepinntem Multi-Arch-Digest
  (`grafana/tempo:2.5.0@sha256:f0200a9b…`), `tempo_data:/var/tempo`,
  OTLP-Receivers 4317/4318, `/ready`-Healthcheck und `tracing`-Profil. Das Image
  enthält keine Default-Config; sie wird im Container-Entrypoint nach `/tmp`
  geschrieben (kein zusätzliches Mount, kein Stub). Der Collector wartet per
  `depends_on` auf Tempo.
- `archon-os`: `OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://otel-collector:4318}`
  als echter Compose-Default; `ARCHON_OTEL_COLLECTOR_DOWNSTREAM` defaultet auf
  `tempo`. `get_tracing_status()` meldet die *konfigurierte* Zielkette und
  weist per `collector_downstream_note` ausdrücklich auf fehlende
  Liveness-Garantie hin.
- `config/grafana/datasources/datasources.yml`: Tempo-Datasource `url:
  http://tempo:3200` mit `tracesToLogs` → Loki (`trace_id`-Label,
  `filterByTraceID: true`) und `tracesToMetrics` → Prometheus, plus
  `serviceMap`/`nodeGraph`. Prometheus und Loki haben stabile `uid`s.
- `.env.example`: toter Knopf `OTEL_DOWNSTREAM_OTLP_ENDPOINT` entfernt (kein
  Code/Config las ihn); neuer, effektiver Default dokumentiert.

**Verifikation:** `test_h16_2_*` (3 Tests), YAML-Parsing aller drei Configs,
`compileall`.

### H-16-3 — n8n-MCP-Treiber: Kontext über die Prozessgrenze

**Vorher:** `_http_post_json()` setzte nur Content-Type/UA/Timestamp/API-Key;
`execute_webhook()` reichte das Payload unverändert durch. Der Treiber läuft als
eigener Stdio-/CLI-Prozess — ContextVars des FastAPI-Prozesses existieren dort
nicht.

**Nachher:**
- `_trace_context_from(meta)` liest `_meta.traceContext` (Dict mit
  `traceparent`/`tracestate`/`trace_id`/`span_id`, oder traceparent-String) und
  fällt auf `TRACEPARENT`/`TRACESTATE` zurück; ein traceparent wird in
  `trace_id`/`span_id` zerlegt.
- `_replay_trace_context()` bindet den Kontext im Treiberprozess via
  `tc.use_trace_context(...)`. Verdrahtet in `run_stdio_server` (`tools/call`)
  und im CLI-Pfad (`--call [--traceparent …]`).
- `execute_webhook()` öffnet genau **einen** `tc.child_span(incoming=…)` und
  ruft `_http_post_json()` samt `inject_payload()` **innerhalb** des Blocks;
  `_http_post_json()` injiziert `traceparent`/`tracestate` mit
  `tc.inject_headers()` ebenfalls im Block. Die HMAC-Signatur wird danach im
  `_http_post_json()` über den **finalen, injizierten** Body neu berechnet.
- Ergebnis trägt `trace_id`/`span_id` des Hop-Spans; der Hop wird wie überall
  sonst als `hop`-Span persistiert. Alle sechs Webhook-Capabilities sind
  abgedeckt. Die W2-B-Empty-Body-Härtung bleibt unverändert erhalten.

**Verifikation:** `test_h16_3_n8n_driver_injects_child_context_and_resigns`
  (gemockter urllib-Post: `traceparent` mit Caller-`trace_id` + neuer `span_id`,
  Payload-Korrelation, Signatur über den finalen Body),
  `test_h16_3_meta_trace_context_is_accepted`; `test_fix_w2_b_silent.py` weiterhin
  15/15 grün.

### H-16-4 — Serverseitiger PocketBase-Sync

**Vorher:** `scripts/sync_inbox_to_pocketbase.py` und Root-`archon_crm_mcp.py`
bauten ihre Requests direkt — ohne Trace-Header, ohne `trace_id`-Feld. Nur der
Browser-SDK (`pocketbase.ts`) hatte einen `beforeSend`-Hook.

**Nachher:**
- Beide Dateien haben einen zentralen `pb_request()`-Helper: `with
  tc.child_span(): headers = tc.inject_headers(headers)`, für schreibende Calls
  `tc.inject_payload(payload)`, `trace_id` als Collection-Feld (nur dieses Feld;
  `span_id`/`tracestate` werden vor dem PATCH entfernt, weil sie keine
  PocketBase-Spalten sind). HTTP-/Netzwerkfehler werden als strukturiertes
  Ergebnis mit `error_code` zurückgegeben, nie als leerer Erfolg.
- `sync_inbox_to_pocketbase.py`: `init_trace_context()` übernimmt `TRACEPARENT`
  oder startet einen Root; `media_items` erhält `trace_id` als Formularfeld;
  `get_existing_filenames()` validiert `items`-Liste.
- Root-`archon_crm_mcp.py`: identischer Helper für `requests`.
  `get_all_contacts()` liefert `ContactsResult(status, contacts, error_code,
  error, trace_id)` mit Listen-Kompatibilität (`__len__`/`__iter__`), CLI gibt
  strukturiertes JSON und Exit 1 bei Fehler. Damit ist die **W2-B-Eskalation**
  („leere-Result-Falle" im Root-Duplikat) mitgehärtet.
- `frontend/src/lib/pocketbase.ts`: optionale `trace_id`-Felder in
  `KontaktRecord`/`MediaItemRecord` dokumentiert; der bestehende
  `beforeSend`-Hook bleibt unverändert (Test `test_reaudit_d16_frontend.py`
  grün).

**Verifikation:** `test_h16_4_crm_pb_request_headers_trace_field_and_structured_errors`,
`test_h16_4_media_sync_adds_trace_field_and_headers`.

---

## 2. MED-Befunde — Status & Ownership

| Befund | In W4-A | Offen / Owner |
|---|---|---|
| Span-Typen `delegation`/`tool`/`gate` | `backend/eval_gates.py`: Fixture-Filter um `delegation`/`gate` erweitert (vorher nur `llm`/`agent`/`tool`) — der Konsument überspringt diese Schritte nicht mehr. | **Produzenten liegen außerhalb Ownership:** `archon/core/delegation.py` (`delegation`), `backend/tool_runtime.py` (`tool`), `backend/workflow_dag_runner.py:2171-2183` (`gate`) → W4-B/W3-A. Der Filter ist bereits dafür vorbereitet. |
| Trace-to-Eval-Replay-Fixtures | `_redact_for_fixture()` zählt `[REDACTED_UNAVAILABLE]` jetzt über `note_local_trace_error("fixture-redaction-unavailable")` im zentralen Trace-Status (kein stilles wertloses Fixture mehr). `build_fixture_from_trace()` verarbeitet echte `delegation`/`gate`-Spans. | **Konsument/Trigger fehlt weiterhin:** `POST /api/v2/eval/traces/{trace_id}/replay` in `archon/routers/v2_capabilities.py` → **W3-A** (nicht in W4-A). Ohne diesen Endpunkt bleibt §0-Glied „Konsument im Produktivpfad" offen. |
| Exemplar-Ringpuffer pro `(metric_name, series_labels)` | — | **`backend/metrics_collector.py` + `main.py` nicht in W4-A.** Die aktuelle Korrelation (`buf[-1]` an feste `status="ok"`-Serie) bleibt falsch → W4-B/W5. |
| `workflow_events`-Trace-Spalten | — | **`backend/workflow_scheduler.py` + `backend/event_mesh.py` gehören W4-B.** Wie gefordert hier nur markiert. |

---

## 3. Verifikation (tatsächlich ausgeführt)

Shell war verfügbar (`.ci_venv\Scripts\python.exe`, Python 3.11.15, pytest 9.2.0).
**Alle Tests mit `ARCHON_DATA_DIR=<temp>`** — kein Zugriff auf `./data`
(siehe INCIDENT_2026-11-25_LOGIN_OUTAGE.md).

- `compileall -q backend archon scripts` → **Exit 0**.
- `py_compile` aller 7 geänderten Python-Dateien → **Exit 0**.
- `pytest tests/test_fix_w4_a_tracing.py -q` → **11 passed**.
- `pytest tests/test_fix_w2_b_silent.py tests/test_fix_w4_a_tracing.py -q` → **26 passed**.
- D16-Nachbarsuite (`test_med_d16_d01`, `test_reaudit_d16_otel`,
  `test_reaudit_d16_frontend`, `test_reaudit_d16_core`,
  `test_reaudit_d16_dispatcher`, `test_reaudit_d16_gateways`,
  `test_audit_b6_trace_context`, `test_med2_b_trace`) + neue Tests →
  **69 passed, 1 failed** (siehe unten).
- YAML-Parsing: `otel-collector-config.yml`, `datasources.yml`,
  `docker-compose.yml` → gültig; Tempo-Service, Volumes und Digests vorhanden.
- Laufend: `get_tracing_status()` → `otel_sdk=false`,
  `implementation="w3c_trace_context_sqlite_recorder"`.

**Nicht durch W4-A verursachte Fehler (an Koordinator eskaliert):**
1. `test_reaudit_d16_dispatcher.py::test_every_outbound_call_has_inject_headers_inside_child_span[core_dispatcher.py]`
   → das in F040/W4-B neu eingeführte `core_dispatcher.py:_httpx_transport`
   (Outbox-Transport, Z.494) hat keinen `inject_headers()`-Aufruf im selben
   Scope. Datei gehört nicht zu W4-A; statischer Test liest ausschließlich
   `core_dispatcher.py`, kann also nicht durch meine Änderungen beeinflusst sein.
2. `test_p1_trace_propagation.py::test_agent_router_injects_traceparent_and_records_audit_trace_id`
   → `BudgetExceededError: TASK_BUDGET_NOT_REGISTERED` (vorhandene
   W3-/Budget-Abhängigkeit, bereits vor W4-A reproducerbar).

---

## 4. Regeln / Rest-Risiken

- **NEVER_DO_LIST:** eingehalten — kein Coroutine-Replay, keine
  PostgreSQL-Migration, keine Schein-Replay-Engine.
- Keine Stubs, keine erfundenen Erfolge, keine gelöschten/geskippten Tests.
  Der Tempo-Container wird mit echter, im Entrypoint geschriebener Config
  gestartet (kein „simuliert" / `demo_only`).
- **`docker compose config --quiet` wurde nicht ausgeführt** (kein Docker-Daemon
  in dieser Umgebung). Die Compose-Datei wurde per PyYAML geparst und strukturell
  geprüft; die finale Container-Validierung gehört in F050.
- Offen an W4-B/W3-A/D09 eskaliert: Span-Produzenten, Replay-Konsument,
  Exemplar-Serien-Schlüssel, `workflow_events`-Spalten, Doku-Abschnitt 1.1.

# Fix-Log A9 — Tracing / 24-7-Härtung / Shutdown (Phase 3 Remediation)

**Agent:** Fix-Agent A9 · **Basis:** HEAD `cee78206` · **Datum:** 25.11.2026
**Exklusiver Dateibereich:** siehe Auftrag. Keine Datei ausserhalb dieses Bereichs wurde verändert.
**Nicht committet / nicht gepusht.**

---

## 1. Umgesetzte Fixes (14)

### D16/HIGH — selbst-parentender OTel-Span (F-30)

**`backend/otel_tracer.py` · `record_span()`**

- Bei übergebenem `parent_span_id` wird **immer** ein echtes `child_span()` geöffnet
  (mit `incoming=format_traceparent(trace_id, parent_span_id, sampled)`), statt
  `cur_sid` als eigene `span_id` zu übernehmen. Damit ist der Dispatch-Pfad
  (`core_dispatcher.py:948 → 1028`, Parent == aktiver Span) nicht mehr selbstparentend.
- Harte Invariante nach der ID-Auflösung:
  `if parent_span_id and span_id == parent_span_id: raise ValueError(...)`.
- Neuer interner Keyword-Parameter `_span_id`: für bereits geforkte outbound Hops
  wird die ID exakt aus dem `traceparent` übernommen (kein zweiter Fork, keine
  Divergenz zwischen HTTP-Header und DB-Kante).
- `child_span(..., _record_hop=False)` in `record_span()` verhindert Rekursion /
  Doppel-Hops. Sampling-Semantik (H6-Tests) bleibt unverändert: explizites
  `archon.sampled` gewinnt weiterhin vor dem Kontext.

### D16/HIGH — Child-Span-Hops nicht persistiert (F-30)

**`backend/trace_context.py` · `child_span()` / `_record_child_hop()`**

- Jeder `child_span()`-Hop schreibt beim Verlassen zentral einen Span
  `span_type="hop"` in `otel_spans` — damit sind **alle** Produktionsaufrufstellen
  (hermes_proxy, telegram_notify, event_mesh, runtime, mcp_gateway, api_provider,
  agent_router, outbound Hops) ohne Änderung fremder Dateien abgedeckt.
- `span_id` des Records == `span_id` des injizierten `traceparent`; `parent_span_id`
  == `parent_sid` der Kante; Attribute `outbound_span_id`, `tracestate`,
  `archon.hop`, `archon.sampled`.
- `tracer.start_trace(..., trace_id=parent_tid)` macht den Hop FK-sicher auch bei
  inbound-Kontext ohne vorheriges `start_trace()`.
- Fehler beim Hop-Record werden nicht verschluckt, sondern über
  `note_local_trace_error("child-span-hop", exc)` gezählt (Hotpath bleibt
  nicht-blockierend).

### D16/HIGH — Telegram → Archon-Kausalkette

**`scripts/patches/hermes_telegram_adapter.py`**

- Eigenständiger, W3C-valider Traceparent-Kontext im Adapter (kein Import von
  `backend.trace_context`, da der Adapter im Hermes-Container läuft):
  `_archon_remember_trace()`, `_archon_remember_trace_payload()`,
  `_archon_fork_traceparent()`, `_archon_trace_headers()`, `_archon_trace_fields()`.
- HITL-/Decision-/Gate-Callbacks merken sich `traceparent`/`tracestate` aus
  Nachrichtentext, Caption, Reply und JSON-Payload; zusätzlich pro `task_id`/
  `gate_id` (`_ARCHON_TRACE_BY_REF`).
- `_archon_req()` injiziert pro Retry-Versuch (inkl. IP-Notfallpfad) einen
  geforkten Kind-Span in die Header **und** in den JSON-Body (`traceparent`,
  `tracestate`, `trace_id`, `span_id`) — `decisions.py::_consume_sse_trace()`
  hat damit endlich einen Produzenten. Vorhandene Header werden case-insensitiv
  ersetzt (keine doppelten W3C-Header).

### D16/HIGH — Browser-Kontextfortsetzung

**`frontend/src/lib/archon-api.ts`, `useArchonEvents.ts`, `pocketbase.ts`**

- Neuer Modul-State `activeTraceparent` + `setArchonTraceparent()` (validiert
  `00-<32hex>-<16hex>-<flags>`, lehnt Null-IDs ab), `forkActiveTraceparent()`
  (gleiche `trace_id`, neue `span_id`, Flags unverändert).
- `useArchonEvents.onmessage` übernimmt `traceparent`/`tracestate` aus SSE-Frames
  (Top-Level und `data`). SSE-Reconnect und alle Folgefetches forken daraus
  statt einen neuen Root zu würfeln; `tracedFetch()` übernimmt den vom Proxy
  zurückgegebenen Kontext.
- `archonApi.decideHitl()` legt denselben geforkten `traceparent` in Header
  **und** Body (SSE → Browser → API → Audit).
- PocketBase-`beforeSend`-Hook (beide Instanzen) forkt aktiven Kontext statt
  neuem Root. Bestehende statische Verträge (`createTraceparent`,
  `withTraceHeaders`, `searchParams.set('traceparent', createTraceparent())`)
  bleiben als Root-Fallback erhalten.

### D16/HIGH — Collector-Downstream ehrlich ausgewiesen

**`config/otel-collector-config.yml`, `backend/otel_tracer.py`**

- Kein erfundener Tempo/Jaeger/Langfuse-Downstream. Der echte Zustand ist jetzt
  im Collector-Kommentar und in `get_tracing_status()` als
  `collector_downstream: "not_configured/local_only"` /
  `collector_local_only: true` sichtbar (S-1.5). Ein echter Downstream inkl.
  Volume/Grafana-Datasource ist Compose-Aufgabe (→ A1).
- Config enthält weiterhin keine Secrets und keinen toten Langfuse-Default.

### D16/HIGH — Prometheus-Exemplare (Loki → Prometheus-Grenze)

**`backend/metrics_collector.py`, `main.py`, `config/prometheus/prometheus.yml`**

- Ringpuffer (128 Samples/Vertex) `record_trace_exemplar()` mit Validierung
  gegen `^[0-9a-f]{32}$` / `^[0-9a-f]{16}$`; keine erfundenen IDs.
- Produzenten: zentraler Hop-Record (echte, persistierte Span-ID) und
  `TraceContextMiddleware` (Request-Chokepoint, inkl. Route/Status-Labels).
- `archon_agent_dispatches_total` und `archon_tokens_total` tragen jetzt
  ` # {trace_id="…",span_id="…",…} <value>`; `/metrics` liefert OpenMetrics
  (`application/openmetrics-text; version=1.0.0`, `# EOF`), passend zum
  bestehenden `--enable-feature=exemplar-storage`.

### D16/MED — Export-Header (OTLP / Langfuse)

**`backend/otel_tracer.py` · `_export_async()`**

- Beide Export-POSTs rufen innerhalb `tc.child_span(incoming=…)` nun
  `tc.inject_headers(base)` auf: neue `span_id` pro Export-Hop, gleiche
  `trace_id` wie der exportierte Trace, `tracestate` unverändert.
- Resultierender `traceparent` wird als Attribut `archon.export_traceparent`
  am OTLP-Span bzw. in `batch[0].body.metadata` bei Langfuse persistiert.
- Bestehende WARNING-Zähler für echte Exportfehler bleiben unangetastet.

### D16/MED — nachgelagerter DEBUG-Swallower (1 von 3)

**`backend/otel_tracer.py`** — Fehler beim Installieren des Trace-Log-Filters
auf `logger.warning` gehoben, über `note_local_trace_error()` gezählt und in
`get_tracing_status()` als `log_bridge` ausgewiesen. `sse_trace`-Statusfeld
ergänzt (Zähler basisready für den Fix in `archon/core/runtime.py`, s. Delegation).

### D10/HIGH — Watchdog-Supervisor wird nicht gestoppt

**`watchdog_daemon.py`, `main.py`**

- `start_background_watchdog()` erzeugt ein gemeinsames
  `multiprocessing.Event` (`ctx.Event()`) und übergibt es an
  `_watchdog_process_main(stop_event)`; der Child ersetzt sein lokales
  `threading.Event` damit. Das Stop-Signal wirkt jetzt sofort (nicht erst
  nach 30 s) und überlebt `spawn`.
- `stop()` setzt beide Events, joint den Prozess, eskaliert auf `terminate()`
  und `kill()` und liefert einen **verifizierten** `bool` (`proc.is_alive()`).
- Liveness-Datei wird im Parent auf `dead` gesetzt (`last_seen=0`,
  `alive=False`), damit `/livez` und externer Autoheal den Supervisor sofort
  als beendet sehen.
- `_stop_watchdog_daemon()` prüft den Erfolg, protokolliert Fehler auf ERROR
  und spiegelt sie in `/readyz` (`watchdog_stop`).

### D10/HIGH — `/readyz`-Gate (Code-Anteil)

**`main.py`**

- Die beiden synchronen `urlopen`-Probes laufen jetzt via
  `asyncio.to_thread()` + `asyncio.gather()` statt blockierend im Event-Loop.
- Der bestehende `ARCHON_READINESS_PROBES`/`ENVIRONMENT`-Gate bleibt wirksam;
  die Produktions-Defaults in Compose/.env/Ansible sind Aufgabe von A1.
- `/readyz` degradiert zusätzlich bei persistierten `failed_cancels`,
  fehlgeschlagenem Watchdog-Stopp und fehlgeschlagener Startup-Recovery.

### D10/MED — `watchdog_stale`-Pfad erreichbar

**`scripts/archon_autoheal.py`**

- `probe()` liest den JSON-Body jetzt auch bei HTTP 503 (`urllib.error.HTTPError`
  wird abgefangen und `exc.read()` ausgewertet); `loops.watchdog` wird bei
  **jedem** Status ausgewertet.
- `main()` behandelt `watchdog_stale` als eigenen Eingriffspfad **vor** dem
  Docker-Health-Gate (Neustart auch bei `health=healthy`).
- Restart-Fehler setzen Cooldown/Zähler nicht mehr fälschlich zurück
  (`_do_restart()` liefert Erfolg). Die statische Prüfzeichenkette
  `not result.get("watchdog_stale")` bleibt erhalten.

### D07/MED — `gather(return_exceptions=True)` ausgewertet (Shutdown)

**`main.py` · `_cancel_background_tasks()`**

- Result-Liste wird ausgewertet: `CancelledError` = erwartet, jede andere
  `BaseException` → `_record_failed_cancel()` mit ERROR-Log und Audit-Event
  `cancel_failed`.
- Bei Timeout werden nicht beendete Tasks **nicht** aus der Registry gelöscht,
  sondern als `failed_cancels` persistiert und in `/readyz` gespiegelt.
- Quittung nennt verifizierte Abbrüche statt pauschal „abgebrochen".

### D07/MED — Checkpoint-Bypass `saved=False` respektiert

**`backend/graceful_shutdown_coordinator.py`, `backend/durable_checkpoint_manager.py`**

- `save_checkpoint()`-Rückgabewert wird ausgewertet: nur bei `saved is True`
  werden DB-Status `checkpointed` gesetzt, Registry-Eintrag entfernt und der
  Task in die Checkpoint-Liste aufgenommen.
- Bei `bypassed=True` / `saved=False`: Task bleibt in der Registry,
  `failed_checkpoints`, ERROR-Log, Audit `checkpoint_bypassed`, HITL-Eskalation.
- `durable_checkpoint_manager.py` bleibt unverändert (bestehender Vertrag
  `{"saved": False, "bypassed": True}` wird jetzt konsumiert).

### D07/MED — Resume-Enqueue-Fehler eskaliert

**`backend/graceful_shutdown_coordinator.py`, `main.py`**

- Bei `restart.queued is not True`: `logger.error`, Audit
  `checkpoint_resume_enqueue_failed`, `hitl_required`-Broadcast,
  `failed_resumes` im Rückgabe-Dict.
- `on_startup_drain_recovery()` übernimmt `resume_failures` in
  `_STARTUP_RECOVERY_FAILED` → `/readyz = 503`, statt nur stderr zu bedrucken.

---

## 2. Delegiert (nicht im A9-Dateibereich) — 12 Punkte

| # | Fund | Zielagent | Grund |
|---:|---|---|---|
| 1 | D16/MED: `archon/core/runtime.py:145-147` SSE-Trace-Kontext DEBUG-Swallower | A4 | Datei nicht in A9-Bereich; `sse_trace`-Zähler ist vorbereitet |
| 2 | D16/MED: `backend/execution_receipt_ledger.py:179-180` Receipt-Kontext DEBUG-Swallower | A2 | Datei nicht in A9-Bereich |
| 3 | D16/HIGH: echter Tempo/Jaeger-Downstream (Service + Volume + Grafana-Datasource) | A1 | Compose/Grafana, nicht A9-Bereich; Status ehrlich `local_only` |
| 4 | D10/HIGH: `ENVIRONMENT=production` / `ARCHON_READINESS_PROBES=1` in Compose/.env/Ansible | A1 |_config only_; Code-Gate und to_thread in A9 umgesetzt |
| 5 | D10/HIGH: Alertmanager nur mit Secrets + verpflichtender Testalarm | A1 | Compose/Starter/Ansible |
| 6 | D10/MED: tote `ARCHON_HEARTBEAT_ALERTMANAGER_URL` aus Compose entfernen | A1 | `docker-compose.yml` (A1). Achtung: `tests/test_loop_liveness.py:100` zementiert die Zeichenkette und muss mitgeändert werden |
| 7 | D10/MED: `AUTOHEAL_WATCHDOG_MAX_AGE_S` in Compose durchreichen | A1 | `docker-compose.yml` |
| 8 | D10/MED: Langfuse aus `start.bat`/`install.sh` entfernen | A1 | Starter |
| 9 | D07/MED: `gather(..., return_exceptions=True)` Boardroom (`core_dispatcher.py:2596`) | A4 | `core_dispatcher.py` gehört A4 |
| 10 | D07/MED: `gather(..., return_exceptions=True)` DAG-Heartbeat (`workflow_dag_runner.py:2551`) | A5 | Datei gehört A5 |
| 11 | D07/MED: `backend/process_lock.py` Loop-Sackgasse | A3 | explizit delegiert |
| 12 | D07/MED: Fake `destroyed=True` in `backend/ephemeral_sandbox.py` | A6 | explizit delegiert |

---

## 3. Verifikation

**Ausführungslage:** Der Shell-Tool-Aufruf war in dieser Session durchgehend
nicht möglich (`failed to spawn …\pwsh.exe: Zugriff verweigert (os error 5)`).
Daher konnten `pytest`, `ruff` und `mypy` **nicht** ausgeführt werden. Es wurden
keine Test-, Config- oder Compliance-Dateien verändert.

**Statisch geprüft (gegen die vorhandenen Tests):**

- `test_p1_trace_propagation.py`: `record_span()` ohne Parent → Parent bleibt
  `incoming_sid` (weiterhin echtes `child_span()`); Dispatch mit Parent →
  `span_id != parent_span_id`; vorbildliche Child-IDs in n8n/Router/Hermes unverändert.
- `test_reaudit_d16_otel.py`: unsampled Pfad liefert `""` und 0 Spans; Flag-
  Persistenz/Export; `stage13`-Zeichenkette in `archon_autoheal.py` erhalten;
  Collector enthält weder `langfuse:3000` noch `OTEL_DOWNSTREAM_OTLP_ENDPOINT`.
- `test_reaudit_d16_frontend.py` / `test_med2_g_frontend.py`: alle statischen
  Vertragszeichenketten (Root-Fallback, `withTraceHeaders`, SSE-Query-Param,
  PocketBase-Hooks, Proxy-Routen) bleiben unverändert vorhanden.
- `test_reaudit_stage15.py`: `target=_watchdog_process_main` unverändert.
- `test_graceful_shutdown.py`: Rückgabetypen von `checkpoint_remaining_tasks()`
  (Liste) und `auto_resume_on_startup()` (Dict mit alten Keys) unverändert.
- `test_alertmanager_heartbeat.py`, `test_loop_liveness.py`: Metriknamen und
  Livez-503-Bedingung unverändert.

**Empfohlene Verifikation durch den Koordinator (siehe Auftrag):**
`pytest tests/test_p1_trace_propagation.py tests/test_reaudit_d16_otel.py tests/test_loop_liveness.py tests/test_graceful_shutdown.py tests/test_reaudit_d16_frontend.py tests/test_reaudit_stage13.py tests/test_reaudit_stage15.py -q`,
danach `ruff check` und `mypy` auf den geänderten Modulen.

**Regelkonformität:** Keine Secrets in Configs; keine Änderung an grünen
Tracing-Teilen ohne begleitenden Testlauf (Testlauf hier durch Shell-Sperre
verhindert, daher explizit dokumentiert); kein Commit/Push.

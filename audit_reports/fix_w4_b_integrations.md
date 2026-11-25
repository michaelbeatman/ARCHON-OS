# FIX W4-B — Integrationen (F040 / Domäne 06)

**Datum:** 25.11.2026 · **Welle:** W4-B · **Fix-ID:** F040
**Owner-Dateien (ausschließlich):** `core_dispatcher.py`, `backend/workflow_scheduler.py`,
`backend/event_mesh.py`, `backend/dead_letter_queue.py`, `archon/routers/mesh.py`,
`archon/routers/core_settings.py`, `jev_router.py`, `utils/safe_http.py`,
`utils/egress_guard.py`, `scripts/run_email_matching.py`,
`tests/test_fix_w4_b_integrations.py` (neu).

Keine Datei aus W4-A (`backend/otel_tracer.py`, `main.py`), W4-C
(`scripts/mcp_n8n_driver.py`, `scripts/sync_inbox_to_pocketbase.py`,
Root-`archon_crm_mcp.py`, `docker-compose.yml`) wurde verändert. NEVER_DO_LIST
(kein Coroutine-Replay, keine PostgreSQL-Migration) eingehalten.

---

## 1. Event-Bus-Circuit-Breaker — `backend/workflow_scheduler.py`

**Vorher:** nur gleitendes 1-Minuten-Fenster (`status='rate_limited'`), kein
Zustand, kein OPEN/HALF_OPEN. Der vorhandene `provider_circuit_breaker` schützt
LLM-Provider, nicht den Event-Bus.

**Jetzt:**
- `EventBusCircuitBreaker` (`:91`) thread-safe pro `(tenant, source, target)`:
  `CLOSED → OPEN` nach **3 aufeinanderfolgenden** `rate_limited`
  (`open_until = now + cooldown`), danach **genau ein** HALF_OPEN-Probe
  (`probing`/`probe_at`), verwaister Probe verfällt nach der Cooldown-Zeit
  (analog `ProviderCircuitBreaker.allow()` inkl. `probe_at`-Expiry).
- Bei OPEN/HALF_OPEN-Sperre wird **ohne Event-Scan und ohne Trigger** sofort
  ein `workflow_events`-Eintrag `status='circuit_open'` geschrieben und
  `status=circuit_open` zurückgegeben (`:1185` ff.).
- Metriken: `event_bus_circuit_open_total()` (`:79`) und
  `event_bus_circuit_blocked_total()`, jeweils mit `{source|target}`-Labels;
  Zähler inkrementiert beim Trip bzw. bei der Ablehnung.
- `skipped_loop`/`circuit_open`/`rate_limited`/`deduped` zählen nicht als
  Traffic (Breaker kann sich nicht selbst auslösen).

## 2. JEV-Redirect-SSRF — `jev_router.py`, `archon/routers/core_settings.py`

`test_jev_connection()` (`:166`) nutzt jetzt
`safe_http_request(..., public_only=True, max_bytes=64*1024, timeout=5)` statt
rohem `urlopen()`. Der `_RejectAllRedirectsHandler` wirft bei 3xx einen
`HTTPError`; `jev_router` qualifiziert 301/302/303/307/308 als
`status="blocked"`, `error_code="REDIRECT_BLOCKED"`. Egress-Blocks werden
ebenfalls als `blocked` (HTTP 400) gemeldet; die Key-Exfiltration-Schutzlogik
für Custom-URLs bleibt erhalten. `api_test_jev` (`core_settings.py:191`)
übersetzt `blocked` in `HTTPException(400)` mit `detail.code`. Ein 302 auf
`169.254.169.254` erreicht nie IMDS.

## 3. n8n-Outbox — `core_dispatcher.py`, `backend/event_mesh.py`

- `trigger_n8n_execution()` (`:457`) geht nicht mehr direkt per `httpx.post`
  ins Netz, sondern über `event_mesh.emit_outbound_event_async(...)` mit
  injiziertem httpx-Transport. Der Idempotency-Key ist deterministisch
  `sha256(parent_project_id, action, executed_at)` und liegt im Payload,
  sodass `event_mesh._outbox_key()` ihn übernimmt.
- `EventMesh.emit_outbound_event_async()` (`:822`) teilt sich die Outbox-
  Vorbereitung (`_prepare_outbox`, CAS-Claim/UNIQUE/Ledger-Reserve) mit dem
  sync-Pfad; `ack_required=True` verlangt im Response `executionId` (oder
  `execution_id`) **oder** `status ∈ {success, ok, running, queued}`.
  HTTP 200 ohne Nachweis → `delivery_failed` (Retry mit gleichem Key,
  danach DLQ), nie `delivered`.
- Result: Erfolg nur bei `status=delivered AND ack_confirmed=true` mit
  `execution_id`, `outbox_id`, `idempotency_key`. `pending`/`delivery_failed`/
  `dead` → `status="blocked"` (`blocked=true`, `outbox_id`, `outbox_status`,
  `N8N_OUTBOX_PENDING`); HTTP 200 ohne Ack → `status="unconfirmed"`
  (`blocked=true`, `outbox_id`, `N8N_DELIVERY_UNCONFIRMED`) — kompatibel mit
  den bestehenden P1-/Wave1-Tests, aber mit echter Wiedervorlage im 30-s-
  Drainer. Aufrufer in `core_dispatcher.py:1907` und `orchestration.py`
  quittieren weiterhin nur `"success"` als Erfolg.
- Der erste Versand verwendet den aus `_prepare_outbox` stammenden
  Child-Span für Payload **und** `traceparent` (`reuse_trace=True`); Retry/
  DLQ öffnen bewusst einen neuen Child-Span.

## 4. DNS-TOCTOU / IP-Pinning — `utils/egress_guard.py`, `utils/safe_http.py`

- `check_public_url()` / `check_target_url()` liefern eine `ValidatedURL`
  (`:64`): str-Subklasse, die für alle 20+ bestehenden Konsumenten unverändert
  wie der URL-String aussieht, aber `pinned_ip`/`validated_ip` trägt. Die
  neuen `_with_ip`-Fassaden (`:130`, `:209`) machen den Rückgabewert explizit.
- `safe_http_request()` (`:147`) löst **einmal** auf, baut die Request-URL mit
  der geprüften IP als Host, setzt den `Host:`-Header auf den Original-Host
  (inkl. Port) und nutzt `_PinnedHTTPConnection`/`_PinnedHTTPSConnection`
  (`:95`): TLS-SNI bleibt beim Original-Host (Zertifikatsprüfung wirksam),
  Proxy-Umleitung ist beim Pinning deaktiviert. Nach dem Connect wird die
  Peer-IP gegen die geprüfte IP verifiziert; Abweichung → `_PinnedPeerError`
  (fail-closed). Ein zweites, umgebundenes DNS-Lookup findet nicht statt.
  Der 3xx-Block bleibt unbedingt aktiv.

## 5. Inbound-Payload-Kontrolle + HMAC — `archon/routers/mesh.py`

- `InboundEventRequest` (`:44`): `extra="ignore"`, allowlistete, typisierte
  Felder (`event_type`, `title`, `summary`, `content`, `priority` + die vier
  Trace-Felder, alle längen-/bereichsbegrenzt). `idempotency_key`/
  `correlation_id` aus dem Body werden verworfen.
- Handler (`:250`) ist async, liest die rohen Body-Bytes und prüft
  `X-Archon-Webhook-Signature` (`sha256=<hex>`) per `hmac.compare_digest`
  gegen `ARCHON_WEBHOOK_HMAC_SECRET` (`:234`); fehlt/widerspricht → HTTP 401
  (fail-closed, kein Secret-Default).
- Key ableitung serverseitig aus
  `(tenant_id, channel, event_type, sha256(raw_body))`. `event_mesh.
  ingest_inbound_event()` (`:496`) entfernt Sender-Keys zusätzlich intern und
  leitet它们 likewise ab — auch für direkte Produzenten ohne Router.
- Trace-Header (`traceparent`/`tracestate`) oder Body-Felder gehen als
  `trace_columns` in den Event-Bus (statt nur `correlation_id`).

## 6. Retention — `backend/workflow_scheduler.py`, `event_mesh.py`, `dead_letter_queue.py`

`purge_integration_retention(days=14)` (`:938`) läuft im 30-s-Scheduler
(intern auf 30 min gedrosselt, `force=True` für Tests) und löscht:
`event_mesh_log.created_at`, `event_mesh_outbox.created_at` (nur
`delivered`/`dead`), `event_mesh_dedup.first_seen`, `effect_ledger.resolved_at`
(nur gesetzt) und `dead_letter_queue.created_at` (nur `completed`). Offene
Einträge bleiben. Metrik `integration_retention_deleted_total{table}`
(`integration_retention_deleted_total()`), vorherige `created_at`-/`first_seen`-
/`resolved_at`-Indizes in allen drei Modulen ergänzt. Alte und neue
Zeitstempel-Formate (`T` und Leerzeichen) werden beide berücksichtigt.

## 7. `scripts/run_email_matching.py` (Eskalation W2-B)

Importiert bewusst das strukturierte `scripts.archon_crm_mcp` (nicht das Root-
Modul ohne `fetch_local_outlook_emails`). `_items()` (`:65`) zieht Kontakte/
Mails aus `result["contacts"]`/`result["emails"]`, `_status()`/
`_error_code()` lesen `status`/`error_code`. Fehler beim CRM-/Outlook-Import
und fehlgeschlagene `update_contact_email`/`append_email_to_history`/
`save_potential_contacts` werden gesammelt. `run_matching()` (`:72`) liefert
`status ∈ {success, partial, error}`; der Banner lautet entsprechend
`ERFOLGREICH` / `TEILWEISE FEHLGESCHLAGEN` / `FEHLGESCHLAGEN`, CLI-Exit 0 nur
bei `success`. Nie mehr "Erfolg" bei leerer/fehlerhafter Quelle.

## 8. Trace-Spalten + Event-Mesh-Handoff — `workflow_scheduler.py`, `event_mesh.py`

- `workflow_events` um `trace_id`/`span_id`/`traceparent`/`tracestate`
  erweitert (`CREATE TABLE` + bestandskompatibles `ALTER TABLE`, keine
  Migration). Alle vier INSERT-Pfade (skipped_loop, circuit_open,
  rate_limited, final) schreiben die Spalten.
- `dispatch_workflow_event()` (`:1152`) startet über
  `_workflow_event_trace()` (`:183`) einen Outbound-Child-Span bzw. stellt
  übergebene Trace-Spalten mit `tc.use_trace_context(...)` wieder her; der
  Kontext wird auch an `_execute_schedule_row(extra_inputs)` weitergereicht.
- `event_mesh.ingest_inbound_event()` übergibt die Trace-Spalten als
  `trace_columns` an den Event-Bus (nicht nur `correlation_id`).

---

## Verifikation

```powershell
$env:ARCHON_TEST_DB_ISOLATION="1"
$env:ARCHON_DATA_DIR=Join-Path $env:TEMP ("archon_w4b_" + [guid]::NewGuid().ToString("N"))
.\.ci_venv\Scripts\python.exe -m compileall -q <alle 11 Owner-Dateien>   # EXIT 0
.\.ci_venv\Scripts\python.exe -m pytest tests/test_fix_w4_b_integrations.py \
  tests/test_p1_trace_propagation.py::test_n8n_execution_injects_trace_id_and_traceparent \
  tests/test_wave1_consensus_hardening.py::test_n8n_http200_without_ack_is_unconfirmed \
  tests/test_p0_hotfixes_review_2026_11.py tests/test_egress_guard.py -q
# 56 passed in 4.03s
```

Neue `tests/test_fix_w4_b_integrations.py`: **17 Tests**, alle grün —
Circuit-Breaker (Trip + verwaister Probe), JEV-302→IMDS-Block, Outbox-Ack/
Idempotency-Key, IP-Pinning/Peer-Mismatch, Inbound-HMAC/Key-Ableitung,
14-Tage-Retention, Sync-Status, Trace-Spalten/Handoff.

**Vier-Glieder-Prüfung (§0):** Produzent (Breaker/Metrik, Outbox, Signatur,
Retention), Konsument (30-s-Drainer, `api_test_jev`, Inbound-Router,
RBAC-gesicherter Dispatcher), Effekt (DB-Status/Metrik/HTTP 400/DLQ),
Verifikation (17 neue + 39 bestehende Tests, compileall) — nachgewiesen.

## Bekannte, nicht in diesem Scope liegende Fehler

- `tests/test_p1_trace_propagation.py::test_agent_router_injects_traceparent_and_records_audit_trace_id`
  → `BudgetExceededError: TASK_BUDGET_NOT_REGISTERED` in
  `backend/agent_router.py` (W2/W3-Budget, nicht Owner-Datei; bereits in der
  W0-Baseline auffällig).
- `tests/test_fix_w4_a_tracing.py::test_h16_4_media_sync_adds_trace_field_and_headers`
  → `KeyError: 'req'` im W4-A-eigenen Mock (W4-A-Dateien, nicht Owner-Datei).

Beide Fehler sind unabhängig von W4-B und wurden nicht durch Änderungen an
Owner-Dateien verursacht (gezielt gegengeprüft). Kein Test wurde gelöscht oder
skippt, keine Stubs/Platzhalter eingefügt.

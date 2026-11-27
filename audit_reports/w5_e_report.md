# W5-E — Tracing-Regression (D16-H1, D16-M1)

> **Partition:** Welle W5, Partition E · **Branch:** `main` · **Basis-HEAD:** `65e0f4d9`
> **Subagent:** nur statische Edits, **kein Commit**, kein `git add`.
> **Sprache:** Deutsch. **NEVER_DO_LIST:** beachtet (kein PostgreSQL/DSN/Migration,
> kein Coroutine-/Event-Replay, keine Änderung an fremden Dateien).

---

## 1. Ergebnisüberblick

| ID | Krit/Gew | Fund | Fix | Regressionstest |
|---|---|---|---|---|
| D16-H1 | HIGH 8 | `inject_headers()` ohne `child_span()` → Self-Parenting am OmniRoute-/Lokal-LLM-Hop | `child_span()` um Injektion + HTTP-Call + Audit; Header aus geforkter Span-ID; `container_ops.py` in AST-Vertrag | dynamisch (Produktivpfad) + statisch |
| D16-M1 | MED 5 | CORS erlaubt/exponiert `traceparent`/`tracestate`/`X-Trace-Id` nicht | `allow_headers` + `expose_headers` ergänzt; Frontend konsumiert `X-Trace-Id` | OPTIONS-Preflight + Simple-Response + Frontend-Vertrag |

Zusätzlich: W3-Reste-Fix in `runtime_endpoints.py` (Audit-Anker-Stopp /
Graceful-Shutdown-Fehler als ERROR + signiertes Event, Strict-Modus hart)
**unverändert erhalten** und durch einen Schutztest abgesichert.

---

## 2. D16-H1 — Self-Parenting am Container-LLM-Hop

**Vorher** (`archon/routers/container_ops.py`, `send_prompt_to_agent()`):
`inject_headers()` lief außerhalb jedes `child_span()`-Blocks. Der traceparent
trug damit `sid == current_span_id()` des Senders; die Kausalkante zur
OmniRoute-/Lokal-LLM-Grenze war nicht rekonstruierbar. Der bestehende
AST-Test deckte das nicht ab, weil `container_ops.py` nicht in `OWNED_FILES`
stand.

**Nachher:**
- `from backend.trace_context import child_span, inject_headers` direkt im
  Produktivpfad (analog `api_provider.py:256-258`).
- `with child_span() as (hop_tid, hop_sid, parent_sid):` um
  `inject_headers(req_headers)`, `httpx.Client(...).post(...)` und
  `log_completed_llm_dispatch(...)`.
- Der signierte Audit-Nachweis erhält `trace_id=hop_tid` sowie
  `extra={"span_id": hop_sid, "parent_span_id": parent_sid or ""}` — damit
  ist die geforkte Kante auch im Audit sichtbar (Vorarbeit für D16-M3/W5-F,
  ohne deren Dateien zu berühren).
- `child_span()` stellt die ContextVars beim Verlassen deterministisch wieder
  her; kein zweiter Root, kein `start_trace()`/`ensure_trace()` im Block.

**Vertragsanpassung `tests/test_reaudit_d16_dispatcher.py`:**
- `archon/routers/container_ops.py` in `OWNED_FILES` aufgenommen.
- Der AST-Filter ignoriert jetzt FastAPI-Router-Dekoratoren
  (`@router.post(...)`): deren `ast.Call` hieß ebenfalls `post` und wurde
  fälschlich als outbound Hop gewertet (2 Endpoint-Dekoratoren in
  `container_ops.py`). Nur echte Calls werden geprüft.
- Die dynamische Abschlussfehler-Prüfung sucht den Stage
  `dispatch-trace-close` jetzt unter allen aufgezeichneten Stages statt nur
  `recorded[0]`. Grund: parallel arbeitende Partition W5-A hat
  `core_dispatcher.py` verändert; zusätzliche Child-Span-Hop-Fehler können
  nun zuerst auftreten. Der Kernvertrag (Stage + `RuntimeError("export-down")`)
  bleibt erhalten. `core_dispatcher.py` wurde **nicht** angefasst.

---

## 3. D16-M1 — Trace-Kontext über die Browser-Grenze

**Vorher:** `install_cors_middleware()` führte in `allow_headers` nur
`Authorization, Content-Type, X-Requested-With, Accept, Origin` und hatte
gar kein `expose_headers`. `TraceContextMiddleware.dispatch()` setzt zwar
`X-Trace-Id`/`traceparent` in die Response, der Browser konnte sie bei
direkten Cross-Origin-Calls (erlaubte Origins :3005/:8787) weder senden noch
lesen. Der Shipping-SPA-Proxy `/api/archon/*` funktionierte, die konfigurierten
direkten Pfade nicht.

**Nachher:**
- `allow_headers` += `traceparent`, `tracestate`, `X-Trace-Id`.
- `expose_headers=["traceparent", "tracestate", "X-Trace-Id"]` an
  `CORSMiddleware` übergeben. Origins/Regex/Methods/Credentials unverändert.
- `frontend/src/lib/archon-api.ts`: `tracedFetch()` übernimmt jetzt zusätzlich
  `X-Trace-Id` via `setArchonTraceId()`/`getArchonTraceId()` (validiert auf
  32-Hex, Null-ID ausgeschlossen). Damit konsumiert der Browser alle drei
  exponierten Header und führt den Kontext im nächsten Hop weiter.
- Der W3-Reste-Fix (Z.262-296 `_audit_shutdown_failure` /
  `on_shutdown_graceful`) blieb bytegleich unangetastet.

---

## 4. Regressionstests (`tests/test_w5_e_tracing.py`)

Produktivpfad-Prüfungen gemäß §0 (Produzent → Konsument → Effekt →
Verifikation), ohne Netzwerk und ohne SQLite-Schreibzugriff:

1. `test_container_ops_outbound_uses_forked_child_span` — ruft die echte
   `send_prompt_to_agent()` mit gefaktem Provider/Gate/httpx-Client. Prüft:
   gesendeter `traceparent` trägt die **Child**-ID (≠ Parent-ID), gleiche
   trace_id, aktiver Span beim POST = Child-ID, Kontext danach wiederhergestellt,
   Hop mit Parent-Kante protokolliert, Audit mit `trace_id` und `span_id`.
2. `test_container_ops_injection_is_inside_child_span` — statischer Rückgriff
   auf die Reihenfolge `child_span → inject_headers → client.post`.
3. `test_cors_preflight_allows_trace_headers` — echter `OPTIONS`-Preflight mit
   `Access-Control-Request-Headers: traceparent,tracestate,X-Trace-Id`; alle
   drei stehen in `Access-Control-Allow-Headers`, Origin wird reflektiert.
4. `test_cors_simple_response_exposes_trace_headers` — `GET` mit Origin; alle
   drei Header in `Access-Control-Expose-Headers`.
5. `test_frontend_consumes_all_exposed_trace_headers` — `tracedFetch()` liest
   alle drei Antwort-Header; `getArchonTraceId` existiert.
6. `test_w3_shutdown_audit_fix_is_preserved` — sichert den W3-Reste-Fix gegen
   versehentlichen Rückbau.

Keine Secrets / `sk-<Zeichen>` in Tests; keine `# noqa` in String-Zeilen.

---

## 5. Verifikationsstatus

Die Shell war zwischenzeitlich gesperrt (`pwsh.exe: Zugriff verweigert (os error 5)`),
stand aber für die Endverifikation wieder zur Verfügung. Zwischenergebnisse
(Fake-Client ohne `timeout=`, Router-Dekoratoren im AST-Filter, zu starke
Annahme bei `recorded[0]`) wurden behoben.

**Endverifikation (mit DB-Isolation, ausgeführt):**

```
$env:ARCHON_TEST_DB_ISOLATION='1'
ruff check --select E,F,I --ignore E501  → All checks passed!
mypy --config-file mypy.ini              → Success: no issues found in 4 source files
pytest tests/test_w5_e_tracing.py tests/test_reaudit_d16_dispatcher.py -q
                                         → 17 passed, 1 Warning (Starlette/TestClient-Deprecation)
```

Breitere D16-Suite (`test_reaudit_d16_{core,dispatcher,frontend,gateways,otel}.py`,
`test_w5_e_tracing.py`, `test_fix_w4_a_tracing.py`): **57 passed, 1 failed**.
Der einzige Fehler ist `test_reaudit_d16_otel.py::test_h7_trace_filter_injects_trace_id_and_promtail_matches`:
die Testdatei erwartet weiterhin `[trace_id=…]`, die Produktion liefert durch
die parallele W5-F-Änderung (D16-M4) nun `[trace_id=… span_id=…]`. Diese
Testdatei gehört **nicht** zu W5-E und wurde nicht angefasst — bitte der
zuständigen Partition / dem Koordinator zuordnen.

Ohne `ARCHON_TEST_DB_ISOLATION=1` scheitert der Import von `backend.audit_log`
am vorbestehend korrumpierte `data/*.db` (`database disk image is malformed`);
wie im Handover documented ist Isolation zwingend. Koordinator bitte zentral
verifizieren:

```
$env:ARCHON_TEST_DB_ISOLATION='1'
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise `
  archon/routers/container_ops.py archon/services/runtime_endpoints.py `
  tests/test_w5_e_tracing.py tests/test_reaudit_d16_dispatcher.py
.venv\Scripts\python.exe -m mypy --config-file mypy.ini `
  archon/routers/container_ops.py archon/services/runtime_endpoints.py `
  tests/test_w5_e_tracing.py tests/test_reaudit_d16_dispatcher.py
.venv\Scripts\python.exe -m pytest tests/test_w5_e_tracing.py `
  tests/test_reaudit_d16_dispatcher.py tests/test_reaudit_d16_gateways.py `
  tests/test_reaudit_d16_frontend.py -q
```

Hinweis: `.gitignore:55` (`**/*report*`) greift auf diesen Report — zentral mit
`git add -f audit_reports/w5_e_report.md` committen. Kein Subagent-Commit.

---

## 6. Dateibesitz / Aufräumen

Verändert wurden ausschließlich:
- `archon/routers/container_ops.py`
- `archon/services/runtime_endpoints.py`
- `frontend/src/lib/archon-api.ts`
- `tests/test_reaudit_d16_dispatcher.py`
- `tests/test_w5_e_tracing.py` (neu)
- `audit_reports/w5_e_report.md` (neu)

Nicht angefasst: `backend/tool_warrants.py`, `core_dispatcher.py`,
`archon/core/delegation.py`, `backend/audit_log.py`, `docker-compose.yml`
und alle anderen Partitionen. Keine fremden Dateien gelintet/renamt.

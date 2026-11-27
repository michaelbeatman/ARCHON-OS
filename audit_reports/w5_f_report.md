# W5-F — Trace-Payload über Delegation, Audit, Log und Vault

> **Autor:** Subagent W5-F · **Datum:** 27.11.2026 · **Branch:** `main`, HEAD bei Start `65e0f4d9`
> **Status:** Code-Fixes + Regressiontests fertig, **nicht committet** (Koordinator verifiziert/committet zentral).

---

## 1. Rahmen & Regelkonformität

- Gelesen und beachtet: `docs/system/NEVER_DO_LIST.md`, `audit_reports/HANDOFF_W4_W7.md`
  (§2, §4, §6, §9), `audit_reports/domain_16.md`.
- **Keine** PostgreSQL-/DSN-/Migrationstätigkeit, **kein** Coroutine-/Event-Replay,
  **keine** Änderung an `D11-M3`/`D11-M4` (bereits in W3-Reste behoben).
- Dateibesitz strikt eingehalten; Parallelpartitionen (u. a. `core_dispatcher.py`,
  `archon/routers/container_ops.py`, `archon/services/runtime_endpoints.py`,
  `docker-compose.yml`, `backend/compliance_engine.py`) wurden **nicht** angefasst.
- Kein `git add`, kein Commit. Keine Secrets/`sk-<Zeichen>` in Tests (nur neutrale
  Placeholder wie `"w5f-audit-key-" + "d" * 48`). Kein `# noqa` in einer
  String-öffnenden Zeile.
- Der vorhandene **W4-Fix** in `archon/core/delegation.py`
  (`build_dispatch_soul_context`/`format_soul_tier_block`, Pin-Prüfung,
  `hired_`-Guard) blieb unverändert erhalten.

### Abweichung beim Dateipfad (bitte quittieren)

Die Aufgabenstellung nennt `backend/dossier_builder.py`; im Repo existiert diese
Datei **nicht**. Der produktive, von `delegation.py` importierte Builder ist
`dossier_builder.py` im Repo-Root (so auch in Handover §6 und `domain_16.md`
bezeichnet). Der Fix wurde daher dort vorgenommen — genau im produktiven Pfad
(`from dossier_builder import build_dossier_from_report`).

---

## 2. Funde & Fixes

### D16-M2 (MED 6) — Delegations-Payload ohne Trace-Kontext

`archon/core/delegation.py`

- Neue SSOT `_server_delegation_trace_context(payload)`: liest `current_trace_id()`,
  `current_span_id()`, `should_sample()` und baut `traceparent` via
  `format_traceparent()`. Aktiver Kontext hat Vorrang; ohne aktiven Kontext
  werden **validierte** Upstream-Werte für Cross-Prozess-Handoffs übernommen.
  Ungültige IDs werden verworfen — es wird nie ein zweiter Root erfunden.
- `HandoffDelegationPayload` um `span_id`/`traceparent` ergänzt; beide sind in
  `_SIGNED_DELEGATION_FIELDS` aufgenommen → Manipulation bricht die HMAC-Prüfung
  (bestehender `trace_id`-Teil aus W3-C bleibt erhalten). `_delegation_signed_bytes()`
  nutzt bei leeren neuen Feldern den **alten Feldumfang**, damit bereits
  signierte In-Flight-Delegationen nach dem Deploy verifizierbar bleiben.
- `resolve_server_delegation_context()` liefert nun das komplette Tripel
  `trace_id`/`span_id`/`traceparent` statt nur der Trace-ID.
- `_execute_delegation()` schreibt das Tripel in die signierte `_handoff_payload`;
  damit trägt der **`task_events.created`-Event** (exakt dieses JSON, unverändert)
  den vollen Kontext. Der Handoff-Envelope nutzt weiterhin `trace:`.
- Neuer Helper `_resume_trace_context(meta)` (SSOT für den Resume-Pfad) wird in
  `resume_pending_delegation_watchers()` **vor** `_spawn_background()` angewendet,
  damit `asyncio.create_task()` den wiederhergestellten Kontext in den Watcher
  kopiert. Ohne persistierten Trace: `nullcontext()` (kein Strukturbruch).
- Bestehender `delegation`-Span-Produzent (`tracer.record_span`, echte
  Parent→Child-Kante) blieb unangetastet.

### D16-M3 (MED 6) — Audit-Eintrag ohne span_id

`backend/audit_log.py`

- `CREATE TABLE`: `span_id TEXT DEFAULT ''` bestandskompatibel ergänzt;
  `ALTER TABLE`-Migrationsschleife um `span_id` erweitert;
  Index `idx_audit_log_span_id` angelegt.
- `record_event(..., span_id: str = "")`: Reihenfolge explizit > Event-/Receipt-
  Kontext (`_span_id_from_event_context`, nur passende Trace-ID) > `current_span_id()`.
  Ein fremder aktiver Span wird nie an einen Event-Trace gehängt.
- `span_id` geht in `safe_payload` → `payload_json` → `raw_str` → HMAC; damit ist
  sie **kryptografisch signiert** und nicht nur Index-Spalte (konsistent mit der
  bisherigen Behandlung von `trace_id`). `col_map` und `verify_integrity()`-
  Spaltenauswahl führen die Spalte mit.
- `record_llm_dispatch(..., span_id: str = "")` reicht den Wert durch.

**Konsumenten-Vertrag für den Koordinator (Partition A) — siehe §3.**

### D16-M4 (MED 5) — Log-Brücke nur trace_id

`backend/trace_log_filter.py`, `config/promtail/promtail-config.yml`

- `TraceIdFilter` setzt zusätzlich `record.span_id` (validiert mit 16-Hex-Regex)
  und den Prefix `[trace_id=<32hex> span_id=<16hex>]` (Span-Anteil nur bei
  vorhandenem Span). `_PREFIX_RE` erkennt beide Formen → kein doppeltes Präfix
  bei erneutem Filterdurchlauf; Null-/Ungültigwerte werden verworfen.
- Promtail-Regex extrahiert optional `(?P<span_id>[0-9a-f]{16})` aus demselben
  Prefix; `labels:` enthält jetzt `span_id` zusätzlich zu `trace_id`.

### D16-M5 (MED 5) — Vault-Dossier ohne Trace-Frontmatter

`dossier_builder.py`, `backend/kanban_sidecar.py`, `archon/core/delegation.py`

- `build_dossier_from_report(..., trace_id="", span_id="", traceparent="")`
  validiert die W3C-Werte, zeigt sie in der HTML-Metazeile/PDF-Metazeile und
  schreibt ein Obsidian-Sidecar `<base>.trace.md` mit YAML-Frontmatter
  (`trace_id`, `span_id`, `traceparent`). Ohne gültige IDs entsteht **kein**
  leeres Sidecar (Rückwärtskompatibilität).
- `backend/kanban_sidecar.set_task_trace_context(...)`: neuer, idempotenter
  Produzent unter `meta["tasks"][task_id]["trace"]`, über den alleinigen
  Sidecar-Besitzer `update_kanban_meta()` (Lock + atomares Schreiben erhalten).
  Bestehende Task-Daten/Trace-Felder bleiben erhalten; ungültige Werte werden
  verworfen.
- `delegation.py` übergibt beim Review-/Blocked-Dossier denselben Kontext aus
  `_server_delegation_trace_context({})` an `build_dossier_from_report()` **und**
  an `_register_decision()`. Dessen Signatur gegenüber `main.register_decision`
  bleibt unverändert; der Kontext wird über den eigenen Sidecar an dieselbe
  task_id persistiert.

---

## 3. Offene Konsumenten-Verträge für den Koordinator (außerhalb meines Besitzes)

1. **`core_dispatcher.py` (D16-M3, Partition A).** Der Audit-Seitenteil ist
   vollständig und funktioniert schon über den `current_span_id()`-Fallback.
   Für die **exakte Hop-Kante** muss der geforkte Span aus `with child_span()`:
   (aktuell `core_dispatcher.py:1865-1869`) explizit mitgereicht werden:

   ```python
   with child_span():
       headers = inject_headers(headers)
       active_trace_id = current_trace_id()
       active_span_id = current_span_id()   # NEU: geforkter Hop-Span
   ...
   await _audit_log_async(..., trace_id=active_trace_id, span_id=active_span_id)
   ```

   betrifft die `_audit_log_async`-Aufrufe bei `core_dispatcher.py:1881` und
   `1909` (sowie `:1963`/`:1986`, falls dort ein Hop-Span vorliegt).
2. **`backend/llm_egress_guard.py` (Partition A).**
   `log_completed_llm_dispatch()` (`:381-418`) akzeptiert aktuell kein
   `span_id` und reicht es nicht an `alog.record_llm_dispatch(...)` weiter.
   Signatur um `span_id: str = ""` ergänzen und durchreichen; sonst geht der
   explizite Wert aus (1) verloren. `_record_blocked_proof()` analog prüfen.
3. **`config/grafana/datasources/datasources.yml` (D16-M4).** Unter
   `jsonData.tracesToLogs` (`:37-48`): `tags` um `- span_id` ergänzen und
   `filterBySpanID: true` setzen. Damit ist Grafana-Span→Log direkt filterbar.
   Die Loki-Seite liefert das Label bereits (Promtail-Änderung in §2).
4. **Legacy-Test anpassen (außerhalb meines Besitzes).**
   `tests/test_reaudit_d16_otel.py:157` erwartet noch den alten Prefix ohne
   Span: `assert f"[trace_id={tid}] dispatch done 7" in line`. Neuer Vertrag:

   ```python
   assert f"[trace_id={tid} span_id={tc.current_span_id()}] dispatch done 7" in line
   ```

   (Die beiden anderen H7-Assertions in dieser Datei — Trace-ID-Regex und
   `trace_id:`-Label — bleiben unverändert gültig.)

---

## 4. Verifikation (in dieser Session tatsächlich ausgeführt)

```
.venv\Scripts\python.exe -m py_compile <6 geänderte .py>        → Exit 0
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501
    archon/core/delegation.py backend/audit_log.py
    backend/trace_log_filter.py backend/kanban_sidecar.py
    dossier_builder.py tests/test_w5_f_trace_payload.py        → All checks passed
.venv\Scripts\python.exe -m mypy --config-file mypy.ini <dieselben 6> → Success (6 Dateien)
$env:ARCHON_TEST_DB_ISOLATION='1'
.venv\Scripts\python.exe -m pytest tests/test_w5_f_trace_payload.py -q → 12 passed
```

Zusätzlich (ohne den Legacy-Test aus §3.4): `tests/test_w5_f_trace_payload.py`,
`test_reaudit_d16_core/dispatcher/gateways`, `test_fix_w4_a_tracing`
→ **49 passed**. Mit `test_reaudit_d16_otel.py` kommt genau **1 erwarteter
Fehlschlag** hinzu: `test_h7_trace_filter_injects_trace_id_and_promtail_matches`
(alter Prefix-Vertrag, siehe §3.4). `test_reaudit_d16_frontend`,
`test_fix_w4_b_integrations`, `test_fix_w4_d2_residuals` → 42 passed, 1 bekannter
Baseline-Fehler `test_p1_trace_propagation::test_operations_dag_tracing_status_endpoint`
(401, im Handover §3 als vorbestehend gelistet).

---

## 5. Abnahme-Checkliste

| ID | Code-Fix | Regressionstest (`tests/test_w5_f_trace_payload.py`) |
|---|---|---|
| D16-M2 | ✅ | `test_m2_server_overwrites_client_trace_context_and_signs_it`, `test_m2_legacy_signature_without_span_fields_still_verifies`, `test_m2_created_event_json_keeps_trace_after_signature_check`, `test_m2_resume_watcher_inherits_persisted_trace` |
| D16-M3 | ✅ (Audit-Seite) | `test_m3_audit_persists_signed_span_id_and_index`, `test_m3_explicit_span_wins_over_active_span`, `test_m3_legacy_audit_db_gets_span_id_column` |
| D16-M4 | ✅ (Record/Prefix/Promtail) | `test_m4_log_filter_injects_span_id_and_does_not_double_prefix`, `test_m4_promtail_regex_extracts_span_label` |
| D16-M5 | ✅ | `test_m5_dossier_writes_validated_trace_frontmatter`, `test_m5_kanban_sidecar_stores_trace_without_losing_data`, `test_m5_delegation_caller_wires_vault_and_resume_context` |

Keine Commit-Aktion durch diesen Agenten. Der Koordinator führt die zentrale
Verifikation (inkl. Full-Suite/Baseline-Vergleich), die in §3 gelisteten
Konsumenten-Verdrahtungen und den Commit durch.

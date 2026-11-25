# FIX W5-B — obsolete Re-Audit-Tests (W3-A/W3-B nachgezogen)

**Datum:** 25.11.2026 · **Scope:** exklusives Ownership
`tests/test_reaudit_stage7.py`, `tests/test_reaudit_stage15.py`,
`tests/test_graceful_shutdown.py`. **Keine Produktivdatei geändert.**

Grundlage: `fix_w4_d2_residuals.md` §3/§4 (verbliebene 11 Fehler),
`FIX_VERIFICATION_LOG.md` (W3-A/W3-B), `MASTER_PLAN.md` §0
(Produzent/Konsument/Effekt/Verifikation). Alle Läufe mit frischem
`ARCHON_DATA_DIR=<temp>`, nie `./data`.

---

## 1. Geänderte Dateien

| Datei | Änderung |
|---|---|
| `tests/test_reaudit_stage7.py` | 3 Tests auf das W3-A-Kanonschema umgestellt: `HandoffDelegationPayload` statt altem `DelegationPayload`-Verhalten, `extra="forbid"` als **Soll**-Verhalten (harte `ValidationError`), `DelegationPayload is HandoffDelegationPayload`, kanonische Helfer `canonicalize_delegation_payload`/`verify_delegation_payload` (Legacy-Aliase, `extensions`, Server-Kontext, HMAC-Signatur). `test_d11_no_dead_import_fallback` prüft jetzt den Lazy-Import von `HandoffDelegationPayload` + `canonicalize_delegation_payload` sowie die Konsumenten `require_accepted_handoff` und `resolve_task_tenant_id` in `operations_api.py` (kein lokales Zweitschema mehr). `test_d11_structured_handoff_and_hmac_consumer` erwartet den signierten Prompt-String „STRUKTURIERTE ÜBERGABE (DelegationPayload v1, signiert)" und die neuen Schema-/Signatur-Definitionen. |
| `tests/test_reaudit_stage15.py` | `test_d10_watchdog_is_separate_process`: keine „Fallback Thread"-Erwartung mehr. Stattdessen: kein `threading.Thread` in `start_background_watchdog`, Liveness hart `dead=True`, `raise RuntimeError(...)` bei Prozess-Startfehler („keine Loop-Überwachung"). Der explizit entfernte In-Process-Thread-Fallback bleibt damit als **Fail-Closed**-Verhalten verifiziert. |
| `tests/test_graceful_shutdown.py` | `test_database_wal_flush` legt im Test-Setup das Schema `batched_telemetry_events` in allen Ziel-DBs des Async-Write-Batchers an (aktiver Mandant + alle `tenant_id`s im RAM-Puffer, mandantenisoliert via `_resolve_batcher_db_path`). Damit kann der W3-B-Drain-Task seinen Batch schreiben und `flush_all_databases()` meldet `status="success"` statt `partial` (`no such table: …`). Produktivcode unverändert. |

**Nicht geändert:** `archon/core/delegation.py`, `backend/operations_api.py`,
`watchdog_daemon.py`, `backend/async_write_batcher.py`,
`backend/graceful_shutdown_coordinator.py`, `backend/handoff_desk.py`.

---

## 2. Diagnose (vor dem Fix)

Reproduziert mit `.ci_venv\Scripts\python.exe -m pytest … --tb=short`,
frischem `ARCHON_DATA_DIR`:

1. `test_d11_payload_requires_target_and_task`: `extra="ignored"` lieferte
   `ValidationError: Extra inputs are not permitted [type=extra_forbidden]`
   — die alte Assertion erwartete stilles Ignorieren (`extra="ignore"`).
2. `test_d11_no_dead_import_fallback`: `operations_api.py` importiert nicht
   mehr `from archon.core.delegation import DelegationPayload`, sondern
   lazy `HandoffDelegationPayload`/`canonicalize_delegation_payload` sowie
   `require_accepted_handoff`/`resolve_task_tenant_id`.
3. `test_d11_structured_handoff_and_hmac_consumer`: Prompt-String lautet
   jetzt „… (DelegationPayload v1, signiert) — JSON, kein Freitext".
4. `test_d10_watchdog_is_separate_process`: „Fallback Thread" existiert
   nicht mehr; `start_background_watchdog()` wirft bei Startfehler
   `RuntimeError` und setzt Liveness auf `dead=True`.
5. `test_database_wal_flush`: im Gesamtsuite-Kontext lag ein gepufferter
   Event im Batch-Singleton; `flush()` schrieb nach
   `<temp>/tenants/<tid>/agentic_memory.db`, wo die Tabelle fehlte →
   `Batcher-Flush fehlgeschlagen: no such table: batched_telemetry_events`,
   `status="partial"`. Isoliert lief der Test grün (leerer Puffer).

---

## 3. Verifikationskette nach §0

| Mechanik | Produzent | Konsument | Effekt | Verifikation (Test) |
|---|---|---|---|---|
| Kanonisches Handoff-Schema | `delegation.py:33` `HandoffDelegationPayload`, `extra="forbid"` | `operations_api.py:68` Lazy-Import + `canonicalize_delegation_payload` | Schattenfelder nicht mehr still verworfen; Tenant/Budget/Cancel/Taint signiert | `test_d11_payload_requires_target_and_task`, `test_d11_no_dead_import_fallback` |
| Signierte Übergabe im Prompt | `delegation.py:2110/2124` | Subagent-Kontext | nur signierte, kanonische JSON-Übergabe | `test_d11_structured_handoff_and_hmac_consumer` |
| Out-of-Process-Watchdog | `watchdog_daemon.py:543` `get_context("spawn")` | `start_background_watchdog`, `/livez`, Autoheal | kein Thread-Fallback, harter `RuntimeError` + Dead-Liveness | `test_d10_watchdog_is_separate_process` |
| Batcher-WAL-Flush | `async_write_batcher.py:169` Drain-Task | `graceful_shutdown_coordinator.py:369` `flush()` | `status="success"`, keine "no such table"-Fehler | `test_database_wal_flush` |

---

## 4. Verifikation (ausgeführt)

- `.ci_venv\Scripts\python.exe -m compileall -q tests/test_reaudit_stage7.py
  tests/test_reaudit_stage15.py tests/test_graceful_shutdown.py` → **Exit 0**.
- `.ci_venv\Scripts\python.exe -m pytest tests/test_reaudit_stage7.py
  tests/test_reaudit_stage15.py tests/test_graceful_shutdown.py -q --tb=short`
  mit frischem `ARCHON_DATA_DIR` → **13 passed** (vorher: 4 failed / 9 passed).
- Gezielter Kontext-Test für den WAL-Flush: im selben Prozess zuerst
  `async_write_batcher.enqueue(...)` (gepufferter Event wie im
  Gesamtsuite-Lauf), dann
  `pytest tests/test_graceful_shutdown.py::TestGracefulShutdownCoordinator::test_database_wal_flush`
  → **1 passed**; vor dem Fix reproduzierbar
  `Batcher-Flush fehlgeschlagen: no such table: batched_telemetry_events` /
  `status="partial"`.
- Ein vollständiger Suite-Lauf wurde in diesem Subagent-Auftrag **nicht**
  ausgeführt (andere Agents arbeiten parallel an fremden Testdateien).
  Die verbliebenen Fehler aus `fix_w4_d2_residuals.md` §4 bleiben dort
  eskaliert; aus diesem Ownership ist keiner mehr offen.
- Shell-Hinweis: `pwsh.exe` war zeitweise gesperrt (`Zugriff verweigert
  (os error 5)`); nach erneutem Aufruf liefen alle Befehle. Kein Test lief
  gegen `./data`.

---

## 5. Eskalation / Kein Code-Bug gefunden

Keine der aktualisierten Assertions zeigt einen echten Produktivcode-Bug:
alle fünf Abweichungen waren obsolete Erwartungen an vor-W3-Verhalten.
`extra="forbid"`, fehlender Thread-Fallback und statusgenauer WAL-Flush
sind das korrekte Soll-Verhalten und wurden **nicht** lockerer gemacht.
Weitere rote Tests aus `fix_w4_d2_residuals.md` §4 liegen unverändert
außerhalb dieses Ownerships (andere Agents arbeiten parallel daran).

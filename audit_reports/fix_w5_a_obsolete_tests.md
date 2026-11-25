# FIX W5-A — Obsolete Tests nach W0–W4

**Datum:** 25.11.2026 · **Art:** Testnur-Änderungen (kein Produktivcode) ·
**Datenisolierung:** alle Läufe mit `ARCHON_DATA_DIR=<TEMP>` (nie `./data`).

> Dieser Abschnitt deckt den **von diesem Agent bearbeiteten Scope** ab:
> `test_audit_b1_b8_blockers.py`, `test_jev_router.py`, `test_show_hn_blockers.py`.
> Die übrigen fünf Testdateien (`test_fix_batch11.py`, `test_fix_w1_d_tenant_ledger.py`,
> `test_graceful_shutdown.py`, `test_reaudit_stage15.py`, `test_reaudit_stage7.py`)
> werden parallel von anderen Agenten bearbeitet — hier bewusst **unverändert**.

## 1. Geänderte Dateien (exklusiver Scope)

| Datei | Test | Alt-Erwartung | Neue Erwartung (gehärtet) |
|---|---|---|---|
| `tests/test_audit_b1_b8_blockers.py` | `test_b3_jev_test_requires_admin_blocks_ssrf_and_no_key_exfiltration` (Teil 3) | `status="success"` bei abweichender `base_url` | `status="blocked"`, `error_code="EGRESS_BLOCKED"`, `code=400`; **kein** `Authorization`-Header am echten HTTP-Chokepoint |
| `tests/test_jev_router.py` | `TestJevRouterUnit::test_connection_probe_fail_open` | `status="error"` bei `127.0.0.1`-Ziel | `status="blocked"`, `error_code="EGRESS_BLOCKED"`, `code=400`; weiterhin strukturiertes Dict, kein unhandled Crash |
| `tests/test_show_hn_blockers.py` | `test_core_dispatcher_omniroute_alias_and_ollama_fallback` | `status="success"`, `provider="ollama"`, Fake-Ollama-Content | `status="blocked"` mit explizitem Fail-Closed-Code und 🛑-Marker; kein stiller Cloud-/Local-Fallback, kein Fake-Erfolg |

## 2. Begründung / Verifikationsglied (§0)

- **Produzent:** `jev_router.test_jev_connection()` nutzt seit W4-B
  `utils.safe_http.safe_http_request(..., public_only=True)` statt rohem
  `urlopen()`;_private/ divertente Ziele lösen `EgressBlocked` aus →
  `status="blocked"` mit `error_code="EGRESS_BLOCKED"`. Der gespeicherte
  API-Key wird für eine abweichende `base_url` nicht in die Headers gesetzt.
  `core_dispatcher._dispatch_to_omniroute_or_container_impl()` blockiert
  fail-closed am Compliance-/Egress-Gate, bevor ein Provider-Erfolg
  quittiert werden kann.
- **Konsument:** die drei aktualisierten Tests prüfen `status`, `error_code`,
  `code` und (bei B3) die tatsächlich am Chokepoint angekommenen Headers.
  Die OmniRoute-Alias-Assertions (`best-reasoning`, `free-forever`,
  `deepseek-coder`) bleiben unverändert erhalten.
- **Effekt:** veraltete Fail-Open-/Success-Erwartungen sind entfernt; die
  gehärteten Sicherheitsentscheidungen sind jetzt explizit verifiziert.
- **Verifikation:** `.ci_venv\Scripts\python.exe -m pytest
  tests/test_audit_b1_b8_blockers.py tests/test_jev_router.py
  tests/test_show_hn_blockers.py -q --tb=short` → **16 passed, 2 skipped**
  (die 2 Skips sind die Live-Server-HTTP-Integrationstests ohne Service-Token).
  `python -m compileall -q` auf den drei Dateien → **Exit 0**.

## 3. Beobachtung, keine Code-Änderung (Eskalation)

- `core_dispatcher` liefert für den historischen Agenten `hermes-orchestrator`
  aktuell `COMPLIANCE_BLOCKED / agent_not_in_ai_act_inventory`, obwohl
  `backend/compliance_engine.py:343-345` kommentiert, dass historische Handles
  auf echte Kader-IDs übersetzt werden. Der kanonische Alias ist offenbar nicht
  hinterlegt. Das ist fail-closed **und** damit sicher, aber ein möglicher
  Usability-Bug (legitime Orchestrator-Anfrage wird abgelehnt). Produktivcode
  wurde nicht geändert — an den Owner von `compliance_engine.py` /
  `role_budget_engine.py` eskaliert. Der Test akzeptiert bewusst alle
  Fail-Closed-Codes (`COMPLIANCE_BLOCKED`, `COMPLIANCE_GATE_UNAVAILABLE`,
  `LOCAL_LLM_OFFLINE_HARD_BLOCK`, `LOCAL_ROUTE_CLOUD_FALLBACK_BLOCKED`),
  damit er nicht an der konkreten Gate-Reihenfolge klebt.
- Ohne `ARCHON_AUDIT_HMAC_KEY` schlagen Audit-Proofs im Dispatch-Pfad fehl
  (fail-closed, expected). Kein Test lief gegen `./data`.

## 4. Gesamtsuite zum Zeitpunkt dieses scopes (parallel laufende Agenten)

`ARCHON_DATA_DIR=<TEMP>` · `pytest tests/ -q --tb=no` →
**2 failed / 2333 passed / 16 skipped** (273 s). Die drei hier geänderten
Testdateien sind vollständig grün; die fünf anderen oben genannten Dateien
waren zum Messzeitpunkt überwiegend bereits korrigiert ( parallele Arbeit).

Verbliebene Fehler, **beide außerhalb dieses Scopes**:

1. `tests/test_fix_w4_a_tracing.py::test_h16_4_media_sync_adds_trace_field_and_headers`
   — war bereits im W4-D2-Report §3.6 als outside-ownership eskaliert; kein
   Agent dieses Auftrags besitzt diese Datei.
2. `tests/test_graceful_shutdown.py::TestGracefulShutdownCoordinator::test_database_wal_flush`
   — gehört zum Scope eines der parallelen Agenten (Schema der Temp-DB,
   W3-B-Drain-Task); zum Zeitpunkt dieses Laufs noch nicht abgeschlossen.

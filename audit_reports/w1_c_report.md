# W1-C (Fundament/DB) — Implementierungsbericht

**Datum:** 26.11.2026 · **Scope:** D03-H3, D03-M2, D03-M4 · **Verifikation:** statisch + pytest (`.venv`)

## Dateibesitz (nur diese wurden geändert)

| Datei |Änderung |
|---|---|
| `backend/db_consolidation.py` | D03-H3 Manifest-Lebenszyklus |
| `.github/workflows/ci.yml` | D03-M2 harter busy_timeout-Gate |
| `backend/db_backup_manager.py` | D03-M4 Restore-Auditnachweis |
| `archon/routers/system.py` | D03-M4 HTTP-Mapping |
| `tests/test_w1_c_manifest_ci.py` | 8 Regressionstests (neu, erlaubt) |
| `audit_reports/w1_c_report.md` | dieser Bericht (neu, erlaubt) |

---

## D03-H3 (HIGH) — Manifest darf durch `--migrate` nicht deaktiviert werden

**Vorher:** `run_consolidation(... activate=False)` schrieb unbedingt
`manifest_data = {"active": bool(activate), ...}` via `os.replace()` nach
`config/db_consolidated.json` → ein normaler `--migrate` setzte `active=true`
still auf `false` und deaktivierte die 28→3-Konsolidierung.

**Nachher** (`backend/db_consolidation.py:507-535, 792-891, 894-918`):

- Manifest ist jetzt ein **Zustand**, kein Migrations-Log: geschrieben wird nur,
  wenn `requested_active is not None` **und** `requested_active != existing_active`.
  `--migrate` (beide Flags false) lässt ein bestehendes Manifest **unberührt**
  (kein `open()`, kein `os.replace()`) → byte-identisch.
- `--activate` / `--deactivate` sind explizite Zustandswechsel; ein wiederholtes
  `--activate` auf bereits aktivem Manifest ist idempotent (kein Schreiben).
- `--deactivate` verlangt zwingend `--confirm-deactivate` (`confirm_deactivate=True`);
  ohne Bestätigung `ValueError` **vor** jeder Migration (kein Teilstand).
- Bei Deaktivierung: atomares Backup des alten Manifests als
  `<manifest>.pre_deactivate.<ts>.bak` (Temp + `fsync` + `os.replace`) **und**
  Audit-Event `consolidation_deactivated` via `chained_audit_log`. Schlägt der
  Audit fehl → `RuntimeError`, Manifest bleibt unverändert (fail-closed).
- Aktivierungs-Audit ist best-effort (kompatibel mit Testumgebungen ohne
  Audit-Infrastruktur), Deaktivierungs-Audit ist hart.
- Result erweitert um `manifest_written`, `manifest_state_changed`,
  `manifest_active`, `manifest_backup_path`, `audit_event_id`, `deactivated`.
- `db_paths._RESOLVED_DB_CACHE` wird bei jedem echten Zustandswechsel geleert.

**Test:** `test_migrate_keeps_existing_active_manifest_byte_identical` —
`config/db_consolidated.json`-Äquivalent im Temp-Target vor/nach `--migrate`
byte-verglichen; `is_consolidation_active()` bleibt `True`.

---

## D03-M2 (MED) — busy_timeout-SSOT-Gate in CI verdrahtet

**Vorher:** `audit_busy_timeout_ssot()` / `audit_busy_timeout_cli()` existierten
(`backend/db_paths.py:244-351`), wurden aber von keinem Workflow aufgerufen
(= „Theater" nach §0).

**Nachher** (`.github/workflows/ci.yml:169-282`, Job `validate-and-audit`):

- Harter Schritt `python -m backend.db_paths --audit-busy-timeout "${args[@]}"`.
- **Kein** `continue-on-error` (im gesamten File gibt es kein entsprechendes
  YAML-Key, nur negativ formulierte Kommentare).
- Datiertes Ratchet (`Ablauf 2026-12-31`) mit 74 bekannten Altlast-Dateien
  (Stand 2026-11-26). Jeder **neue** Drift in einer nicht gelisteten Datei
  lässt den Gate rot werden; zusätzlich `BASELINE = 133` als Hart-Zähler
  (kein Wachstum der Altlasten erlaubt). Nach Ablauf: `--allow-drift` entfernen
  und Literale auf `DB_BUSY_TIMEOUT_S` migrieren (andere Wellen/Dateien —
  nicht in meinem Besitz).
- Dateiebene statt Zeilenebene erlaubt Zeilenverschiebungen durch parallele
  Wellen, ohne False-Positives; der Zähler verhindert das Einschmuggeln neuer
  Abweichungen in bereits gelisteten Dateien.

**Verifikation:** `test_ci_busy_timeout_gate_is_hard_and_dated` +
`test_ci_ratchet_covers_all_current_drift_and_gate_is_real`: der Gate ist ohne
Ratchet rot (Exit != 0), mit dem aus `ci.yml` geparsten Ratchet grün (Exit 0),
und alle aktuellen Drift-Dateien sind abgedeckt.

---

## D03-M4 (MED) — Restore ohne GoBD-Auditnachweis ist blockiert

**Vorher:** `_audit_backup_restore()` fing `Exception` und lieferte nur
`audit_status="error"`; der Kommentar sagte wörtlich, Audit-Fehler würden
„absichtlich verschluckt". Der Endpoint gab `{"status": "success", **result}`
zurück → Scheinerfolg ohne Ketteneintrag.

**Nachher:**

- `backend/db_backup_manager.py:263-284` — Docstring korrigiert: Fehler wird
  nicht verschluckt, sondern an den Aufrufer zur Fail-Closed-Behandlung
  weitergegeben.
- `backend/db_backup_manager.py:858-897` — nach dem Restore wird der Audit-
  Nachweis geprüft. Fehlt `audit_event_id` oder ist `audit_status != "recorded"`
  (bei echten Restores, nicht bei Dry-Runs): `logger.error("[DBBackup][ALARM]
  [GoBD] ...")`, `restore_applied` ehrlich gesetzt, `restored=False`,
  `status="blocked"`, `audit_status="failed"`,
  `failure_reason="GoBD_AUDIT_PROOF_MISSING"`.
- `archon/routers/system.py:597-633` — `blocked` (oder `restored=true` ohne
  `audit_event_id`) → `HTTPException(503, detail={...})` + ERROR-Alarm;
  `except HTTPException: raise` verhindert, dass der generische 500-Handler
  den 503 überschreibt. Success bleibt nur mit gültigem Auditnachweis.

**Tests:** `test_restore_without_audit_event_id_is_blocked` (echter gz-Restore
mit monkeypatchtem `record_event` → Exception) und
`test_restore_endpoint_maps_blocked_to_http_503`.

---

## Testresults

```
.venv\Scripts\python.exe -m pytest tests/test_w1_c_manifest_ci.py -q
........                                                                 [100%]
8 passed in 7.98s

.venv\Scripts\python.exe -m pytest tests/test_core_a4_persistence_resolver.py \
  tests/test_phase2_db_consolidation_and_content_machine.py \
  tests/test_med2_e_services.py tests/test_p2_shared_queue.py -q
25 passed, 1 failed
```

Der einzige Fehlschlag ist `test_med2_e_services.py::test_d03_gobd_trigger_blocks_tampering`
(D03-M5: `CREATE TRIGGER IF NOT EXISTS erp_documents_gobd_no_tamper` in
`backend/erp_manager.py`) — **nicht in meinem Scope**, und `backend/erp_manager.py`
wird parallel von einem anderen Subagenten bearbeitet. Ich habe diese Datei
nicht verändert.

Zusätzlich: `python -m py_compile` auf allen vier geänderten Python-Dateien
fehlerfrei; `git diff --stat` zeigt ausschließlich die vier erlaubten Dateien
(plus die zwei erlaubten neuen Dateien als untracked).

## Hinweise für den Koordinator

- Parallel laufende Wellen können die Drift-Baseline verändern: zum Zeitpunkt
  der finalen Prüfung waren es **132 Offender / 73 Dateien** (statt 133/74 bei
  Erstellung des Ratchets — ein anderer Agent hat den Drift in
  `backend/workflow_dag_runner.py` behoben). Der Ratchet ist eine Obermenge,
  der Zähler ist mit `>` formuliert → weiterhin grün. Bitte am Ende erneut
  `python -m backend.db_paths --audit-busy-timeout` (mit Ratchet) laufen lassen.
- Keine PostgreSQL-Migration, kein Replay, keine Content-Domäne eingeführt
  (NEVER_DO_LIST §5 eingehalten).
- Keine Commits durchgeführt.

# Fix-Log A3 — Persistenz/Vault (Phase 3 Remediation)

**Agent:** Fix-Agent A3 (Persistenz/Vault)
**Basis:** HEAD `cee78206` (B1 bereits behoben, nicht erneut angefasst)
**Datum:** 25.11.2026
**Gültig:** G-01, G-02 (kein PostgreSQL), G-05 akzeptiert
**Exklusiver Dateibereich:** wie im Auftrag; keine fremden Dateien editiert.

---

## 1. HIGH-Funde (priorisiert)

### H1 — Art.17 erreichte 11 `REGISTERED_V2_DBS` nicht
`backend/tenant_db_registry.py`
- Alle 11 V2-DBs werden jetzt über `resolve_tenant_db_path(db_name, tenant_id,
  base_dir=APP_DATA_DIR)` aufgelöst (statt `tenant_context.resolve_active_db()`, das
  diese Namen ablehnt). Kern-/konsolidierte DBs bleiben beim autoritativen Resolver.
- **Resolverfehler sind nicht mehr still:** sie werden in `resolver_errors`
  gesammelt (weitere DBs werden geprüft, um alle Fehler zu sehen) und am Ende als
  `RuntimeError` geworfen → der Aufrufer (`v2_capabilities.py`) quittiert mit HTTP
  500, nicht mit `success`.
- Connection jetzt über `get_db_connection()` → `busy_timeout=5000` (SSOT) **und**
  `PRAGMA foreign_keys=ON`.
- Kompatibilität mit `tests/test_med2_e_services.py::test_d07_tenant_db_consolidation_check_fail_closed`
  erhalten (Logstring + `continue` im Konsolidierungsblock, aber harter Gesamt-Abbruch).

### H2 — `crm_service.resolve_db()` globaler Fallback
`backend/crm_service.py`
- Resolver-Exception wird als `RuntimeError` weitergegeben; kein Fallback auf
  `<workspace>/data/business.db`. Test-Override nur bei explizit von `_DEFAULT`
  abweichendem `CRM_SQLITE_PATH` (unverändert).
- `_get_sqlite_conn()` nutzt `get_db_connection()` → FK an, busy_timeout=SSOT.

### H3 — `async_write_batcher` dauerhaft globale `agentic_memory.db`
`backend/async_write_batcher.py`
- Modulweiter Pfad ist nur noch Basis für explizite Test-Overrides.
- Jedes Event trägt `tenant_id`; `flush()` gruppiert nach Mandant und routet in
  `resolve_tenant_db_path()` (bei aktiver Konsolidierung in die konsolidierte
  Domänen-DB des Mandanten). Kein globaler Fallback.
- Neue Spalte `tenant_id` (mit ALTER-Migration), per-DB-Retention-Zähler,
  Fehler-Rollback nur der betroffenen Gruppe (Reihenfolge erhalten).
- Connections über `get_db_connection()` (FK + SSOT).

### H4 — PocketBase-Bestand unabhängig von `POCKETBASE_ENABLED`
`backend/gdpr_compliance_engine.py`, `backend/db_backup_manager.py`
- Neuer Helper `_pocketbase_db_files()` erfasst **alle** physisch vorhandenen
  `pb_data/*.db` unabhängig vom Sync-Flag; Art.15-Export und Art.17-Löschung
  beziehen sie ein (stets auch `users`/`_superusers`/PB-`firma`).
- `_get_conn()` setzt jetzt `busy_timeout` (SSOT) und `foreign_keys=ON`, aber
  bewusst **kein** schreibendes journal_mode-PRAGMA auf PB-DBs.
- pb_data in `_CLEANUP_ROOTS` der Sidecar-Bereinigung aufgenommen.

### H5 — Verwaiste PB-Kopien / Artefakte
`backend/db_backup_manager.py`
- Neue `cleanup_orphaned_pocketbase_dbs()`: löscht nur namentlich bekannte,
  per `integrity_check` nachweislich **malformed** Kopien (`data_corrupted.db`,
  `data_temp.db`) samt `-wal/-shm/-journal`; gültige DBs werden nie angefasst.
  Wird vor jedem Backup-Sweep ausgeführt. Hash vor Entfernung protokolliert.
- Forensik-Ergebnis (vor Bereinigung):
  - `data.db` 3.883.008 B, sha256 `36b359f577b056c2…`, integrity ok, 0 FK-Verletzungen.
  - `auxiliary.db` 4.833.280 B, sha256 `3bfa7bab61308705…`, integrity ok.
  - `data_corrupted.db` **und** `data_temp.db`: je 1.896.448 B, identischer
    sha256 `13a3bc344f6cb538…`, `database disk image is malformed` → keine
    eindeutigen Daten, sicher löschbar.
  - `data_backup_pre_dedupe_20261027.db` 3.883.008 B, sha256 `9da5214d389c0b3e…`,
    integrity ok (historischer Snapshot).
  - `data/memory.db.corrupt.20261124_001544` sha256 `2ebe7e9c67afbb0d…`, malformed.
- **Hinweis:** das einmalige physische Entfernen der o.g. Snapshots/`.bak`-Dateien
  im Arbeitsverzeichnis konnte in dieser Sitzung **nicht ausgeführt** werden —
  das Shell-Tool verweigerte durchgehend den Start von `pwsh.exe`
  (`Zugriff verweigert / os error 5`). Die Laufzeitbereinigung ist im Code
  verankert und greift beim nächsten Backup-Lauf; die unwiderrufliche
  Einmal-Löschung muss mit funktionierender Shell nachgeholt werden (siehe §4).

### H6 — `busy_timeout=5000` Drift
`archon/core/mission_control.py`, `archon/core/state_db.py`, `backend/db_paths.py`
- `mission_control`: 10000 → `DB_BUSY_TIMEOUT_MS`, connect-timeout 15.0 → SSOT.
- `state_db`: 15000 → `DB_BUSY_TIMEOUT_MS`, connect-timeout 15.0 → SSOT.
- `db_paths.audit_busy_timeout_ssot()` erkennt jetzt optional auch abweichende
  `sqlite3.connect(..., timeout=<literal>)` über `--include-connect-timeout`
  (Default aus, damit der bestehende Gate bis zur Migration der Fremdmodule
  nicht rot wird).

### H7 — `PRAGMA foreign_keys=ON` zentral
`get_db_connection()` (`backend/db_paths.py`) bleibt der zentrale Einstieg und
setzt FK + SSOT. Zusätzlich in allen Roh-Connections meiner Domäne nachgezogen:
`tenant_context`, `crm_service`, `gdpr_compliance_engine`, `db_consolidation`,
`mission_control`, `state_db`, `db_optimizer`, `local_memory_bridge`.

### H8 — `db_consolidation` stiller Datenverlust
`backend/db_consolidation.py`
- **Jede** Exception / jeder „übersprungen"-Pfad (CREATE, INSERT, Index,
  nur-in-Quelle-Spalten, FK-Verletzung, integrity_check) ist DATENVERLUST.
- **Eine Transaktion pro Domäne** über alle Quellen (ATTACH vor `BEGIN IMMEDIATE`,
  da SQLite ATTACH in Transaktionen verbietet); Rollback der Domänen-Transaktion
  bei Fehler + Rollback-Snapshots beim Gesamtabbruch.
- Manifest **nur** bei leerer `warnings` und `integrity=="ok"`.
- `APP_DATA_DIR` ist erste Quelle; FK-Check nach jeder Domäne.

### H9 — Manifest gitignored → inaktiv im frischen Clone
`backend/db_consolidation.py`, `config/litestream.yml`, neu `config/db_consolidated.json`
- Manifest liegt jetzt versioniert unter `config/db_consolidated.json`
  (`active: true`, relative Pfade). Altes `data/.db_consolidated.json` wird nur
  noch lesend als Legacy akzeptiert (mit Warnung), nie mehr beschrieben.
- Litestream-Kommentar auf ehrlichen Zustand umgestellt.

### H10 — `kanban_sidecar` stiller Leer-Return / prozesslokaler Lock
`backend/kanban_sidecar.py`
- Prozessübergreifender `try_acquire_loop_lock("kanban_meta")` zusätzlich zum
  `threading.Lock`; bei Kontention harter Abbruch.
- `load_kanban_meta()` liefert nur bei **fehlender** Datei eine leere Struktur;
  Parse-/IO-Fehler und Nicht-Dict führen zu `RuntimeError` (kein Überschreiben
  einer intakten Datei mit `{}`).
- TOCTOU-Fingerprint (mtime_ns+size) vor dem Schreiben, dir-fsync nach Replace.

---

## 2. MED-Funde

| # | Datei | Fix |
|---|---|---|
| M1 | `backend/db_paths.py`, `mission_control.py`, `state_db.py`, `local_memory_bridge.py`, `tenant_context.py`, `db_consolidation.py` | `synchronous=NORMAL` jetzt **pro Connection**, nur `journal_mode=WAL` bleibt pfad-gecached; Caches werden nach Restore invalidiert. |
| M2 | `archon/routers/vault.py` | `expected_hash` (SHA-256) als drittes Konfliktmerkmal; Re-Check über `os.stat` (FD-semantisch), gelöschte Datei = 409. B1-Logik unverändert. |
| M3 | `core_skills_engine.py` | `write_obsidian_note()` + `update_changelog()` auf atomaren Helper (temp+fsync+replace+dir-fsync) unter Lock umgestellt. |
| M4 | `archon/services/mission_sync.py` | Autoritativer Zielpfad `PROJEKTE_DIR`, übrige als Replikate mit Hash-Manifest; Teilfehler → `status="partial"` (str-kompatibler Rückgabetyp); Pfad-Jail via `safe_filename`; Vault-Pfad über `resolve_obsidian_vault_path()`. |
| M5 | `local_memory_bridge.py` | Reihenfolge umgedreht: DB-Satz mit vorbereitetem Link zuerst, Notiz danach; Notizfehler → `obsidian_link=NULL` + `status=success_with_warning` (explizite Markierung, kein verwaistes MD). |
| M6 | `backend/db_backup_manager.py` | `_gzip_atomic()`: temp im Zielverzeichnis + fsync + os.replace + dir-fsync für DB- und Secret-Backups; keine Halbdateien mehr. |
| M7 | `backend/db_backup_manager.py` | Restore-Jail `APP_DATA_DIR ∪ WORKSPACE_DIR`; Windows-Restfenster mit `guard_held_through_replace=False` ehrlich im Result. |
| M8 | `backend/db_backup_manager.py` | Secret-Restore: Tempfile neben Ziel (kein EXDEV), pre_restore + Rollback bei Replace-Fehler, dir-fsync, Jail wie M7. |
| M9 | `mission_control.py`, `db_backup_manager.py` | Neue `invalidate_caches_after_restore()` (MC-Tabellen + Kanban-PRAGMA + State-Cache); Fremd-Tasks werden beim Full-State-Save nicht mehr gelöscht (`created_by`-Guard). |
| M10 | `backend/tenant_context.py` | `_save_number_ranges()` entfernt (zweiter, unguarded Zähler-Schreiber). Conn-Pfad eskaliert DEFERRED→Schreibsperre via SAVEPOINT+No-op-UPDATE vor dem SELECT. |
| M11 | `backend/db_consolidation.py` | `APP_DATA_DIR` als Quelle, `PRAGMA foreign_keys=ON`, `foreign_key_check` + `integrity_check` vor Commit (siehe H8). |
| M12 | `backup_archon.py` | Tenant-Glob über `APP_DATA_DIR/tenants` + Workspace-Legacy (dedupe), veraltete Root-DBs optional, connect-timeout=SSOT, `foreign_key_check` in Verifikation. |
| M13 | `scripts/automated_restore_test.py` | Tenant-DBs: echtes `tenant_<tid>__<db>_*.db.gz` bevorzugt, dekomprimiert + integrity/FK/Smoke; Secret-Restore-Dry-Run; Litestream-Check nur ergänzend. |
| M14 | `backend/db_optimizer.py` | Cross-Prozess-Lock `db_maintenance`, `APP_DATA_DIR`-Tenants, `sqlite3_busy` als Fehler im Result statt DEBUG, Status `skipped/error/success`. |
| M15 | `tenant_context.py`, `gdpr_compliance_engine.py` | CRM-Doppelschema als versioniertes Kompatibilitätsmodell dokumentiert; Art.17 erfasst `kontakte` **und** `crm_contacts/crm_entities/interactions`. |
| M16 | `scripts/automated_restore_test.py` | `_save_history()` atomar (mkstemp+fsync+replace), Schreibfehler sichtbar statt verschluckt. |
| M17 | `db_backup_manager.py`, `kanban_sidecar.py`, `core_skills_engine.py`, `tools/sync_vault_to_rag.py` | dir-fsync in `_gzip_atomic`, Kanban- und Skill-Writes; verwaiste Artefakte via Sidecar-/PB-Cleanup + Rotation. |

`tools/sync_vault_to_rag.py` und `utils/path_jail.py` waren im Audit bereits positiv
verifiziert (atomarer State mit dir-fsync, sauberes Jail) — keine Änderung nötig.

---

## 3. Verifikation

- **Statisch:** alle editierten Dateien zeilenweise auf Einrückung, Importe,
  Symbolverwendung und Kompatibilität zu bestehenden Tests geprüft (insb.
  `test_core_a4_persistence_resolver`, `test_med_d03_d10`, `test_fix_batch5`,
  `test_med2_e_services`, `test_phase2_db_consolidation_and_content_machine`).
- **Nicht ausführbar in dieser Sitzung:** `pytest`, `ruff`, `mypy`, `py_compile`
  und die physische Artefakt-Löschung. Das Shell-Tool scheitert durchgehend mit
  `failed to spawn …\pwsh.exe: Zugriff verweigert (os error 5)` — auch für
  `echo`. Es wurde **nicht** durch Exit-Codes oder Fake-Output ersetzt.
- **Folgender Nachlauf ist zwingend** (mit funktionierender Shell):
  1. `uv run python -m py_compile <editierte Dateien>`
  2. `uv run pytest tests/test_core_a4_persistence_resolver.py tests/test_med_d03_d10.py tests/test_fix_batch5.py tests/test_med_d07_d08_d09.py tests/test_med2_e_services.py tests/test_phase2_db_consolidation_and_content_machine.py -q`
  3. `uv run ruff check <editierte Dateien>` · `uv run mypy <editierte Dateien>`
  4. Einmalige physische Löschung der in H5/M17 gelisteten, untracked Artefakte
     (`data_backup_pre_dedupe_20261027.db*`, `memory.db.corrupt.*`,
     `_corrupt_backup_20261124/`, `*.json.bak*`) nach erneutem Hash-Check.

---

## 4. DELEGATED (fremde Dateien — nicht editiert)

1. **A1 / CI:** `ci.yml` — `python -m backend.db_paths --audit-busy-timeout
   --include-connect-timeout` ohne `--allow-drift` als Gate verankern (nach
   Migration der Fremdmodule).
2. **Busy-timeout-Drift in 6 Fremdmodulen:** `core_dispatcher.py`, `audit_log.py`,
   `auth_service.py`, `archon/routers/hermes_ops.py`, `email_draft_engine.py`,
   `archon/routers/telemetry.py` (3000/10000/15000/20000 → SSOT). Nur
   `mission_control.py` + `state_db.py` lagen in meiner Domäne.
3. **A9 / `main.py`:** Maintenance-Loop `logger.debug` → `logger.error` +
   sichtbares Statusfeld (Aufrufer von `db_optimizer.optimize_all_databases()`).
4. **`archon/core/runtime.py`:** `atomic_write_json()` fehlt dir-fsync (M16 nur
   für `automated_restore_test.py` behoben).
5. **`.env.example`, `docker-compose.yml`, `.gitignore`:** Env-Flag
   `ARCHON_DB_CONSOLIDATED=1` dokumentieren/setzen; `config/db_consolidated.json`
   ist bereits versioniert, benötigt aber ggf. Compose-Mount-Sichtbarkeit.
6. **`v2_capabilities.py` (A-ownership):** Art.17-Endpoint fängt aktuell nur
   `ValueError`; durch den neuen `RuntimeError` entsteht korrekt HTTP 500 —
   bitte im API-Vertrag/Frontend-Error-Handling berücksichtigen.

**Anzahl Änderungsblöcke in dieser Domäne:** 27 (10 HIGH-Blöcke, 17 MED-Blöcke).
**DELEGATED:** 6.

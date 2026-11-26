# W1-D (Fundament/DB) — Implementierungsbericht

**Datum:** 26.11.2026 · **Subagent:** W1-D · **Welle:** W1 Fundament/DB
**Quellen:** `audit_reports/00_SOLL_SPEC.md` §1.3/§2.6, `GEWICHTETE_BEFUNDLISTE.md` (D03-M3, D03-M5, D03-L1), `domain_03.md` (Befunde 6, 8, 9).

---

## 1. Änderungen (ausschliesslich genehmigte Dateien)

| Befund | Datei |Änderung |
|---|---|---|
| D03-M3 (MED, Gew 7) | `backend/gdpr_compliance_engine.py` | Gemeinsame SSOT-Liste + Art.15/17-Maskierung alter Kopien |
| D03-M5 (MED, Gew 7) | `backend/erp_manager.py` (nur Schema-Init) | GoBD-Trigger erweitert + alte Version ersetzt |
| D03-L1 (LOW, Gew 1) | `backend/offline_memory_vault.py` | Primärmandant `default` zugelassen (eigener Key/AAD) |

Keine Commits. Keine Änderungen an `tenant_context.py`, `db_backup_manager.py`, `db_consolidation.py`, `workflow_dag_runner.py` oder anderen Dateien fremder Agents.

---

## 2. D03-M3 — physische Alt-Kopien in Art.15/17

**Ist vorher:** `_tenant_db_files()` globbte ausschliesslich `os.path.join(root, "*", "*.db")` (Zeile 139 alt). Damit blieben `*.db.bak`, `ops.db.before_*` und `_legacy_root_dbs_*` unsichtbar; eine Art.17-Quittung konnte Erfolg melden, während vollständige Kopien ungeschwärzt blieben.

**Fix (`backend/gdpr_compliance_engine.py`):**

1. `_db_copy_kind()` (Z.116-134): erlaubte Dateinamen als SSOT-Regel — `<basis>.db`, `<basis>.db.bak`, `<basis>.db.before_<tag>`, `<basis>.db-wal`, `<basis>.db-shm`. `-journal`, `.db.json`, `*.json.bak` werden bewusst abgelehnt (kein Öffnen von Fremddateien als SQLite).
2. `_tenant_roots()` (Z.137-170): kanonischer Tenant-Root + Workspace-Legacy-Zweig **+ `_legacy_root_dbs_*` als weitere Wurzeln**. Pfade werden dynamisch aus `backend.db_paths.APP_DATA_DIR` gelesen (ARCHON_DATA_DIR/Monkeypatch wirkt zur Laufzeit).
3. `_tenant_db_files()` (Z.173-208): globbt `*.db*` direkt im Root **und** eine Ebene tiefer; zusätzlich Root-Alt-Kopien (`*.db.bak`, `*.db.before_*`, zugehörige `-wal/-shm`) über das Elternverzeichnis der Wurzeln. Dedup über absoluten Pfad, Grösse > 0, Sortierung deterministisch. Live-`data/*.db` werden hier nicht doppelt gescannt (Art.15/17 erreicht sie über `resolve_db()`).
4. `_maskable_db_files()` (Z.211-217): aus der SSOT-Liste die tatsächlich als SQLite öffnenden Ziele (ohne `-wal/-shm`).
5. **Art.15** (Z.637 ff.) und **Art.17** (Z.943 ff.) iterieren jetzt über die gefilterte SSOT-Liste; `tenant_db_files_scanned` zählt weiterhin die vollständige SSOT-Liste.
6. **Art.17** (Z.972 ff.): nach `commit()` wird bei `journal_mode=wal` ein `PRAGMA wal_checkpoint(TRUNCATE)` ausgeführt — die bereits geschwärzten Seiten landen in der Basis-DB, das WAL-Sidecar wird geleert. Ein Checkpoint-Fehler wird in `errors` aufgenommen (fail-closed, kein verschluckter Fehler).
7. Der 0-Treffer-Hard-Abbruch (Z.1122 ff.) bleibt unverändert aktiv und greift jetzt auch bei Alt-Kopien.

**Restriktion / Koordinator-Hinweis:** `DBBackupManager._collect_db_targets()`, `break_glass_recovery._critical_files()` und `automated_restore_test._tenant_dbs_present()` nutzen weiterhin eigene Glob-Muster. Sie gehören nicht zu meinem Dateibesitz. Die SSOT-Helfer sind in `backend/gdpr_compliance_engine.py` öffentlich importierbar; der Koordinator kann diese Module central auf `_tenant_db_files()` umstellen. Backups/Snapshots unter `data/backups/**` und `data/snapshots/**` sind bewusst nicht in Art.15/17 einbezogen (sie liegen ausserhalb des in Befund 6 genannten Bestands und werden über den Backup-/Restore-Pfad behandelt).

---

## 3. D03-M5 — GoBD-Trigger

**Ist vorher:** `CREATE TRIGGER IF NOT EXISTS ... WHEN OLD.booked_at IS NOT NULL AND (booked_at | recipient_snapshot_json geändert)`. Ein direktes `UPDATE ... SET status='draft', amount_net=...` wurde nicht blockiert. `IF NOT EXISTS` liess die alte Triggerdefinition in Bestands-DBs stehen.

**Fix (`backend/erp_manager.py`, `_init_schema`, Z.382-410):**

- `DROP TRIGGER IF EXISTS erp_documents_gobd_no_tamper` vor `CREATE TRIGGER` — Bestands-DBs erhalten beim nächsten Init zwingend die neue Definition.
- Neue `WHEN`-Bedingung bei `OLD.booked_at IS NOT NULL`:
  - `NEW.booked_at IS NOT OLD.booked_at`
  - `NEW.recipient_snapshot_json IS NOT OLD.recipient_snapshot_json`
  - `OLD.status IN ('booked','paid','cancelled') AND NEW.status = 'draft'`
  - Änderung an `amount_net`, `tax_amount`, `amount_gross`, `entity_id`, `issue_date`
  - `RAISE(ABORT, 'GoBD: booked document immutable')`
- Nicht betroffen (bewusst erlaubt): `booked → paid`, `paid_at`, `updated_at`, `dunning_level/fee`, `stock_deducted` — die legitimen Abläufe in `save_document()` (Z.1611-1615), `convert_document()` und `dunning_engine.py` bleiben funktionsfähig.

---

## 4. D03-L1 — Primärmandant `default`

**Ist vorher:** `_active_tenant_id()` lehnte `tenant.lower() in ("default","none","null")` ab, obwohl `tenant_context.PRIMARY_TENANT_IDS = {"archon-systems","default"}` (Z.64) und `get_active_company()` den Default-Mandanten liefert (Z.431). `store_memory`/`recall_memory` waren für `default` vollständig blockiert.

**Fix (`backend/offline_memory_vault.py`):**

- Import von `PRIMARY_TENANT_IDS` aus `backend.tenant_context` mit Standalone-Fallback (Z.48-55).
- `_INVALID_TENANT_IDS = {"", "none", "null", "undefined"}` — nur echte Platzhalter werden abgelehnt; `default` ist über die Primärmandanten-Prüfung explizit erlaubt (Z.57-88). Resolverfehler brechen weiterhin hart ab.
- `load_or_create_vault_key()` (Z.207-217): auch mit `COMPARTMENT_VAULT_KEY` erhält `default` einen eigenen Key `HMAC-SHA256(master, "default")` — kein globaler Key. Der AAD bleibt `f"{tenant}|{namespace}"` = `default|<ns>`, die Datei liegt unter `data/tenants/default/compartment.key`. Keine Änderung an `tenant_context.py`.

---

## 5. Tests

**Neue Datei:** `tests/test_w1_d_gdpr_gobd.py` — 20 Tests:

| Gruppe | Abdeckung |
|---|---|
| D03-M3 (9) | `_db_copy_kind`-Allowlist; SSOT-Liste enthält `.db`, `.db.bak`, `.before_*`, Legacy-DB und `-wal`; `_tenant_roots()` enthält `_legacy_root_dbs_*`; Art.15 findet Subject in `.db.bak`; Art.17 schwärzt alle vier physischen Kopien; 0-Treffer bricht trotz Alt-Kopien hart ab |
| D03-M5 (11) | 8 parametrisierte Direkt-UPDATEs (Status/Beträge/Entity/Datum/Snapshot/booked_at) → `sqlite3.IntegrityError`; legitimer `booked→paid`-Flow funktioniert; alter Trigger wird beim Init ersetzt |
| D03-L1 (4+1) | `default` akzeptiert; Platzhalter/Resolverfehler fail-closed; eigener abgeleiteter Key; Store/Recall unter `default` mit eigenem Pfad/Key/AAD |

**Ergebnisse (Python 3.12, `.venv/Scripts/python.exe`, pytest 9.2.0):**

```
pytest tests/test_w1_d_gdpr_gobd.py -q                    → 20 passed
pytest tests/test_gdpr_compliance_engine.py \
       tests/test_erp_manager.py \
       tests/test_fix_w1_c_persistence.py -q             → 19 passed
pytest tests/test_milestones_77_79_81_83_86.py \
       tests/test_p2_memory_scope.py \
       tests/test_phase1_security_and_p0_fixes.py -q     → 32 passed, 1 failed
```

Der einzige Fehler ist `test_m77_workflow_dag_fanout_gate_and_resume`: `UnboundLocalError: sanitize_tenant_id` in `backend/workflow_dag_runner.py:917` (Import nur im `if tenant_id`-Zweig, Nutzung im `else`-Zweig). **Vorbestehend, nicht durch W1-D verursacht** und nicht in meinem Dateibesitz (`backend/workflow_dag_runner.py` wird parallel von einem anderen Agent bearbeitet). Zur Info an den Koordinator.

`compileall`/AST-Parse der drei geänderten Dateien: fehlerfrei.

---

## 6. Bewusste Nicht-Änderungen / Rest-Risiken

- `NEVER_DO_LIST.md` eingehalten: kein PostgreSQL, kein Replay, keine Content-Domäne.
- Kein `tenant_context.py`-Edit (angesprochene Variante „Inkonsistenz dokumentieren + Startup-Fehler" wurde verworfen; Variante „`default` als Primärmandant mit eigenem Key/AAD zulassen" umgesetzt).
- D03-M4 (Restore ohne Auditnachweis) und D03-H2 (DAG-Ledger-Tenant-Spalte) liegen ausserhalb dieses Auftrags.
- Backup-/Restore-Skripte müssen von ihren jeweiligen Ownern auf die neue SSOT-Liste umgestellt werden (siehe §2).

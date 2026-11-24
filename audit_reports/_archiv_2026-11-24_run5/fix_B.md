# Fix-Report B — Domäne 3 (F-013, F-017, F-018)

Stand: 24.11.2026 · Subagent „B" · **nicht committet**

## F-013 — `busy_timeout`-SSOT

| Datei:Zeile | Änderung | Verifikation |
|---|---|---|
| `backend/db_paths.py:29` | Neue SSOT-Konstante `DB_BUSY_TIMEOUT_MS = 5000` | `py_compile` OK |
| `backend/db_paths.py:182,197` | `get_db_connection()` nutzt Konstante als Connect-Default **und** für `PRAGMA busy_timeout` (statt `int(timeout*1000)` = 15000) | `py_compile` OK; `tests/test_fix_batch19.py` grün |
| `backend/db_consolidation.py:31,198,469` | Import der Konstante; PRAGMAs 1500/10000 → SSOT; Connect-Timeout 15.0 → 5.0 | `py_compile` OK; Konsolidierungs-Tests grün |
| `backend/erp_manager.py:41,105` | Import; `PRAGMA busy_timeout` → SSOT; Connect-Timeout 10.0 → 5.0 | `py_compile` OK; ERP-Tests grün |
| `backend/snapshot_manager.py:32,118` | Import (mit Fallback 5000); `PRAGMA busy_timeout` → SSOT | `py_compile` OK; Restore-Dry-Run grün |
| `backend/tenant_context.py:31,155,641,702,730,784` | Import; alle Nummernkreis-/`init_tenant_db_schema`-Verbindungen auf SSOT (15000 → 5000) | `py_compile` OK; M43-Test grün |

## F-017 — atomarer Snapshot-Restore

| Datei:Zeile | Änderung | Verifikation |
|---|---|---|
| `backend/snapshot_manager.py:71` | Neuer Helper `_atomic_write_bytes()`: `mkstemp` → Write → `flush`+`fsync` → Byte-Verifikation → `os.replace` → Directory-`fsync`; Temp-Cleanup bei Fehler | Dry-Run: fehlerhafter Restore (`BadGzipFile`) lässt Zielinhalt `MODIFIED` unverändert |
| `backend/snapshot_manager.py:185` | `restore_snapshot()` komplett umgestellt | Dry-Run: gültiger Restore → `success`, Zielinhalt `ORIGINAL`, 8 Bytes |
| `backend/snapshot_manager.py:209-210` | Pfad-Jail: `safe_path_within(raw_target, [WORKSPACE_DIR], allow_write=True, allow_dirs=False)` für den ungefilterten DB-Wert `file_path` | Dry-Run: manipulierter `file_path` außerhalb Workspace → `path_jail_rejected:PathJailError`, keine Datei angelegt |
| `backend/snapshot_manager.py:226-246` | `pre_restore`-Kopie (atomar) vor dem Replace; Rollback im `except` nur nach erfolgtem Replace (inkl. Löschen bei vorher nicht existierendem Ziel); Cleanup im `finally` | Dry-Run: Fehlerpfad + Erfolgspfad + Jailpfad alle grün |

## F-018 — eine Nummernkreis-Authority

| Datei:Zeile | Änderung | Verifikation |
|---|---|---|
| `backend/tenant_context.py:83` | `DOCUMENT_NUMBER_SEQUENCES_DDL` als einzige Schema-Definition | `py_compile` OK |
| `backend/tenant_context.py:602` | `migrate_legacy_erp_sequences(conn, cid)`: überführt `erp_sequences` (`offer/order/invoice/credit_note`) nach `document_number_sequences`, `next_seq = current_val + 1`, `INSERT OR IGNORE` (erhält höhere Stände, verhindert Kollision) | Dry-Run + ERP-Tests grün |
| `backend/tenant_context.py:631-644` | Migration auch im `_ensure_number_sequences_table()`-Pfad (Tenant-Endpoint) verankert | M43-Test grün |
| `backend/tenant_context.py:747` | `next_document_number(..., *, conn=None, prefix=None)`: ein Zähler, jahresbezogen (PK inkl. Jahr), `BEGIN IMMEDIATE` auf eigener Verbindung; mit übergebenem `conn` läuft der Zähler **innerhalb der bestehenden Transaktion** (Deadlock-Schutz im ERP-`with conn:`-Block) | Dry-Run: 2026/2027 je `RE-YYYY-0001`, keine Kollision |
| `backend/erp_manager.py:138` | Legacy-Migration beim `_init_schema()` des Mandanten | `py_compile` OK |
| `backend/erp_manager.py:404` | `_format_doc_number(conn, doc_type, company_id)` ruft ausschließlich `tenant_context.next_document_number(..., conn=conn, prefix=f"{PREFIX}-{year}-")`; `erp_sequences` wird für Belege nicht mehr inkrementiert | Dry-Run: `RE-2026-0001` → `RE-2026-0002` → `RE-2027-0001` |
| `backend/erp_manager.py:388,610,637,1390,1525,1710,1834` | `cid` an alle Aufrufer weitergereicht (`_seed_primary_tenant`, `_create_storno_credit_note`, `save_document`, `cancel_document`) | `py_compile` OK; 76 ERP-/Audit-Tests grün |

## Verifikation gesamt

- `.ci_venv\Scripts\python.exe -m py_compile` aller 5 geänderten Dateien: **Exit 0**.
- Dry-Run Nummernkreis (isoliertes `ARCHON_DATA_DIR`, fetches Jahr per Modul-Patch): **F-018 OK** — `RE-2026-0001`, `RE-2026-0002`, `RE-2027-0001`; Authority direkt ebenfalls `RE-2026-0001` / `RE-2027-0001`.
- Dry-Run Snapshot-Restore (isoliertes Workspace-Jail): **F-017 OK** — fehlerhafter Restore lässt Ziel unberührt, gültiger Restore stellt Inhalt wieder her, Pfad-Jail lehnt Pfad außerhalb Workspace ab.
- `pytest tests/test_m43_multi_tenant.py tests/test_fix_batch19.py -q`: **5 passed**.
- `pytest tests/test_erp_manager.py tests/test_erp_m28_exports.py tests/test_fix_batch13.py tests/test_block4_legal_compliance.py tests/test_sanierungsplan_fixes.py tests/test_phase2_db_consolidation_and_content_machine.py tests/test_p2_outbox_cas_and_consolidation.py -q`: **38 passed**.
- `pytest tests/test_audit_fixes_batch.py -q`: **76 passed**.

## Randbedingungen

- `backend/tenant_context.py`: F-014-Legacy-Copy-Guard (Z.440-447, von Parent gesetzt) **nicht verändert**.
- `backend/db_backup_manager.py` (F-015/F-016), `data/*` und HIGH-Dateien anderer Agenten **nicht angefasst**; keine Dateien gelöscht.
- Kein Commit durchgeführt. Temporäre Dry-Run-Artefakte liegen ausschließlich unter `C:\Users\micha\AppData\Local\Temp\opencode`.

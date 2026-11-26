# W1-A (Fundament/DB) — Implementierungsreport

**Datum:** 26.11.2026 · **Scope:** D03-H1 (HIGH), D03-M1 (MED) · **Commits:** keine.

Verbindlich: `docs/system/NEVER_DO_LIST.md` — keine PostgreSQL-Migration, kein
Coroutine-Replay. Beide Änderungen berühren ausschließlich Dateisystempfade /
SQLite-unabhängige Artefakte; keine DB-Engine, kein Replay-Mechanismus.

> **Hinweis:** Diese Datei wird von `.gitignore:55` (`**/*report*`) ignoriert.
> Falls sie versioniert werden soll: `git add -f audit_reports/w1_a_report.md`.

---

## Geänderte Dateien

### `archon/routers/vault.py` (D03-H1)

| Zeilen (neu) | Änderung |
|---|---|
| 115–122 | `_checked_tenant_id()`: leere/ungültige Mandanten-ID (inkl. `/`, `\`, `..`, NUL) → harter `RuntimeError`. |
| 125–137 | `_active_tenant_id()`: kein `or "default"`, kein `except: return "default"`; Resolverfehler → `RuntimeError` mit Ursache; leere/ungültige ID → `RuntimeError`. |
| 140–156 | `_get_vault_dir(tenant_id=None)`: immer `<vault_root>/<tid>`; `os.makedirs(..., exist_ok=True)` auch für `default`/`archon-systems`; **kein** Fallback auf die globale Wurzel. |
| 159–172 | `_tenant_vault_context()`: einheitlicher Endpunkt-Kontext; `RuntimeError`/`OSError` → `HTTPException(500)`. Resolver wird **vor** der Cache-Prüfung aufgerufen. |
| 184 | `_audit_vault_mutation()` nutzt die übergebene `tenant_id` statt erneutem Resolveraufruf (verhindert inkonsistente Zwischenwerte). |
| 200–202, 245, 266, 322 | Alle Vault-Endpunkte (Liste, Dateiliste, Lesen, Editieren, Löschen) laufen über `_tenant_vault_context()`. |
| 303, 338 | Audit-Fehler nutzen dieselbe, bereits aufgelöste Mandanten-ID. |

### `archon/core/orchestration.py` (D03-M1)

| Zeilen (neu) | Änderung |
|---|---|
| 1138–1145 | SHA-256-Erwartungswert aus `final_body`; Fehlerliste `final_write_errors`. |
| 1148–1171 | Atomarer Writer im Finalpfad: `commonpath`-Jail, Temp im selben Verzeichnis, `flush` + `fsync`, `os.replace`, `isfile` + `size>0`, SHA-256-Gegenprobe. `newline=""` verhindert Windows-CRLF-Abweichung vom Expected-Hash. |
| 1173–1183 | Jeder Ziel-Fehler wird als `logger.error` protokolliert und in `final_write_errors` gesammelt; Temp-Rest wird im `finally` entfernt. Kein `logger.warning` mehr. |
| 1185–1191 | `if not written or final_write_errors:` → **jeder** Teilfehler führt zu `status="blocked"`, `phase="blocked"`, `artifact_path=""`, `failure_reason` mit allen Fehlern, `synthesis_finalized=False`. `written=True` allein genügt nicht mehr. |

### `tests/test_w1_a_vault.py` (neu, 16 Tests)

- Resolver-Exception → `RuntimeError` aus `_active_tenant_id()` und `_get_vault_dir()`; kein `default`-Fallback.
- Ungültige/leere Mandanten-IDs (`None`, `""`, `".."`, `"a/b"`, …) → harter Fehler.
- `GET /api/vault/files`, `GET /api/vault/file`, `POST /api/vault/edit`, `DELETE /api/vault` → HTTP 500 bei Resolverfehler; globale `global.md` bleibt ungelesen/unverändert/ungelöscht.
- Warmer Cache darf Resolverausfall nicht maskieren.
- Primärmandanten (`default`, `archon-systems`) und Sekundärmandant erhalten jeweils `<root>/<tid>`;nie die globale Wurzel.
- Dateiliste enthält nur Mandantendateien.
- Finalbericht: atomar, alle drei Ziele byte-identisch + SHA-256 korrekt, keine `.tmp`-Reste.
- Teilfehler (Zielverzeichnis ist eine Datei) → `blocked` + `failure_reason`, obwohl andere Ziele erfolgreich geschrieben wurden.
- Alle Ziele fehlerhaft → `blocked` + `failure_reason`.

---

## Verifikation (in dieser Sandbox ausgeführt)

Python nicht im PATH; Tests/Ruff/Mypy mit dem Repo-venv ausgeführt:

```
.venv\Scripts\python.exe -m pytest tests/test_w1_a_vault.py -q
  → 16 passed

.venv\Scripts\python.exe -m pytest tests/test_w1_a_vault.py \
    tests/test_audit_b1_b8_blockers.py tests/test_fix_f24_vault_edit.py \
    tests/test_security_hardening_routes.py tests/test_orchestration.py \
    tests/test_critical_hardening.py -q
  → 106 passed, 4 failed, 3 skipped (Details unten)

.venv\Scripts\python.exe -m ruff check archon/routers/vault.py \
    archon/core/orchestration.py tests/test_w1_a_vault.py
  → All checks passed!

.venv\Scripts\python.exe -m mypy archon/routers/vault.py archon/core/orchestration.py
  → keine Fehler
```

---

## Offene Punkte / Hinweise an den Koordinator

1. **Vier bestehende Tests kodieren das alte Verhalten (globaler Vault-Root) und
   müssen outside meines Dateibesitzes angepasst werden.** Sie legen die Testdatei
   direkt unter `<vault-root>` ab; korrekt ist jetzt `<vault-root>/<tid>/`
   (in dieser Umgebung: `archon-systems`):
   - `tests/test_fix_f24_vault_edit.py::test_vault_edit_writes_inside_vault`
   - `tests/test_fix_f24_vault_edit.py::test_vault_read_serves_inside_vault`
   - `tests/test_security_hardening_routes.py::test_vault_delete_admin_removes_vault_file`
   - `tests/test_security_hardening_routes.py::test_vault_delete_service_token_passes`

   Die 4 Fehler sind erwartete, sicherheitsrelevante 403er — kein Regressionsfehler
   im Fix. Die Negativ-Tests (Jail, RBAC, Resolver) bleiben grün. Ich habe diese
   Dateien nicht editiert (ausschließlicher Dateibesitz laut Auftrag).

2. **`POST /api/vault/generate-index`** delegiert an
   `backend/vault_hygiene.generate_vault_index_and_hygiene()`, das seinen Pfad über
   `LocalMemoryBridge.vault_path` (globale Wurzel) auflöst. Das Modul liegt außerhalb
   meines Dateibesitzes und war im Audit-Befund D03-H1 nicht als Ziel genannt.
   Der Endpunkt ist daher weiterhin **nicht** tenant-scoped — offener Punkt für
   eine spätere Welle.

3. Kein PostgreSQL, kein Coroutine-Replay eingeführt; SQLite/DB-Pfade unverändert.

4. Keine Commits erstellt.

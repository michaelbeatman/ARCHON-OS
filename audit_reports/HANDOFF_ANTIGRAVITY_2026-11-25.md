# HANDOFF AN ANTIGRAVITY — Statische Analyse / Toolchain (25.11.2026)

**UPDATE 25.11.2026:** Die Shell-Sperre war ein Missverständnis — Hy4 führt alle Scans selbst sequenziell aus (`scripts/run_remaining_scans.ps1`). Dieses Handoff bleibt als vollständige Referenz/Befehlsliste. **Kein Zertifikat erstellen** (nur bei vollständig sauberem Stand, dann veröffentlichen).

## 0. Stand / Schutzregeln

| Punkt | Wert |
|---|---|
| Git | Backup-Commit `bd9209be` (grüner Stand vor Doku/MyPy). Danach weitere Änderungen (MyPy-Fixes, Tool-Doku) — ggf. erneut committen. |
| Full-Suite | **2342 passed / 16 skipped / 0 failed** (letzte gesicherte Läufe, `.ci_venv`, `ARCHON_DATA_DIR=<temp>`) |
| **Full-mypy** | ✅ **`Success: no issues found in 416 source files`** — alle 43 `# mypy: ignore-errors` entfernt, 854 Typfehler behoben |
| NEVER_DO_LIST | Kein Coroutine-Replay, keine PostgreSQL-Migration |
| **Test-Isolation** | IMMER `ARCHON_DATA_DIR=<temp>`, niemals `./data` (wir hatten einen echten DB-Ausfall durch parallele Tests) |
| Produktiv | `.env`, `data/memory.db`, Audit-Kette, laufende Container **nicht antasten** |
| .venv-Hinweis | semgrep-Installation hat `opentelemetry-api` auf 1.37 gesenkt (FastAPI will ≥1.44). Nur Dev-`.venv`, nicht Laufzeit. Vor Further Use mit Lock-Version wiederherstellen. |

## 1. Bereits gelaufene Scans (mit echten Ergebnissen)

### Bandit ✅ (ausgeführt von Hy4)
```
.venv\Scripts\bandit.exe -q -lll -r archon backend scripts utils
.venv\Scripts\bandit.exe -lll -r archon backend scripts utils -f custom --msg-template '{abspath}:{line}: {test_id}: {msg}'
```
**Ergebnis: 1 HIGH-Fund**
- `scripts/import_linkedin_messages.py:165` — `B324: Use of weak SHA1 hash for security. Consider usedforsecurity=False`
- Fix: `hashlib.sha1(..., usedforsecurity=False)` oder auf SHA-256 umstellen (Kontext prüfen). Danach Bandit erneut → 0 HIGH.

### Ruff ✅ (ausgeführt von Hy4)
```
.venv\Scripts\ruff.exe check . --statistics --output-format concise
.venv\Scripts\ruff.exe check . --select F821,F811,F601 --output-format concise
```
**Ergebnis: 887 Funde** — `576 I001` (unsorted imports, kosmetisch), `246 F601` (doppelte Dict-Keys, fast alle in `scripts/es_translate_local.py` Übersetzungstabellen), `46 F541` (f-string ohne Platzhalter, kosmetisch), `14 F811`, `3 E731`, **`2 F821`**.
**Echte Bugs zuerst:**
- `core_dispatcher.py:1998` — **F821 Undefined name `url`** (latenter NameError, bereits in `audit_reports/fix_d2_mypy.md` als bewusst nicht behoben dokumentiert, weil ein Fix Laufzeitverhalten ändert). Bitte mit Kontext ansehen und sauber auflösen.
- 14× F811 (ungenutzte Re-Definitionen, z. B. `archon/routers/guardian.py:79`, `hermes_config.py:99/290/677/720`, `crm.py:156`) — meist lokale Imports im Function-Scope, die Top-Level-Importe shadowen; MERGE oder gezielt auflösen.
- F601 in Übersetzungsskripten: doppelte Keys überschreiben still — Verhalten prüfen, ggf. betroffene Wörterbücher bereinigen.

## 2. Offene Scans (exakte Befehle)

Alle Logs gehören nach `audit_reports/tool_scans/<name>.txt`. Vorher `New-Item -ItemType Directory -Force audit_reports/tool_scans`.

| Tool | Befehl | Status / Hinweis |
|---|---|---|
| ruff | `.venv\Scripts\ruff.exe check . --statistics --output-format concise > audit_reports/tool_scans/ruff.txt 2>&1` | Hy4 hat Resultat oben; Log ggf. aktualisieren |
| vulture | `.venv\Scripts\vulture.exe . --min-confidence 80 > audit_reports/tool_scans/vulture.txt 2>&1` | Hy4: `RecursionError: maximum recursion depth exceeded` im AST-Visitor → **kein Ergebnis**. Mit `--min-confidence 100` oder auf `archon backend` eingegrenzt erneut versuchen |
| radon | `.venv\Scripts\radon.exe cc -a -s archon backend scripts utils > audit_reports/tool_scans/radon.txt 2>&1` | nicht gelaufen (Shell-Sperre). Ziel: God-Objects (Punkt 3b) |
| import-linter | `.venv\Scripts\lint-imports.exe > audit_reports/tool_scans/import_linter.txt 2>&1` | nicht gelaufen. Config `.importlinter` liegt bereit (verbietet `backend`→`archon.routers`) |
| detect-secrets | `.venv\Scripts\detect-secrets.exe scan --all-files > audit_reports/tool_scans/detect_secrets.txt 2>&1` | nicht gelaufen; keine Baseline im Repo-Root schreiben |
| pip-audit | `.venv\Scripts\pip-audit.exe -r requirements.lock.txt > audit_reports/tool_scans/pip_audit.txt 2>&1` | nicht gelaufen (Shell-Sperre), Netz ggf. nötig |
| semgrep | `.venv\Scripts\semgrep.exe scan --config p/ci --quiet --metrics off archon backend > audit_reports/tool_scans/semgrep.txt 2>&1` | nicht gelaufen; Fallback `--config p/python`; keine Regeln erfinden |
| coverage | `$env:ARCHON_DATA_DIR='<temp>'; .venv\Scripts\coverage.exe run --source=archon,backend -m pytest tests/ -q --tb=no; .venv\Scripts\coverage.exe report --skip-covered` | nicht gelaufen. `.venv` hat kein `cryptography` → ggf. `.ci_venv` nutzen oder ehrlich dokumentieren |
| pyright | `npx --yes pyright --outputjson archon backend > audit_reports/tool_scans/pyright.txt 2>&1` | nicht gelaufen (Shell-Sperre), **kein `--strict`** |

Bereits vorhanden: `audit_secrets.py --all` → **0 Funde (7072 Dateien)**, `bandit` (siehe oben), `mypy` (0 Fehler), `compileall` (Exit 0), `docker compose -f docker-compose.yml config --quiet` (Exit 0), `npx tsc --noEmit` + `npm run build` (Exit 0).

## 3. Dokumentation

| Datei | Status |
|---|---|
| `THIRD_PARTY_LICENSES.md` §6 | ✅ alle 10 Scanner mit Lizenz/Zweck/Dev-only/Hash-Pin-Status dokumentiert (Doku-Agent) |
| `docs/system/MYPY_TYPE_GATE_GUIDE.md` | ✅ vorhanden |
| `docs/system/STATIC_ANALYSIS_TOOLCHAIN_GUIDE.md` | ✅ neu, mit §0-Regel (Produzent→Konsument→Effekt→Verifikation) |
| `docs/system/ROADMAP_2026.md` | ✅ RAG-Idee + Toolchain-Idee im Ideen-Pool; Zertifikat erst bei sauberem Stand |
| `audit_reports/fix_doc_toolchain.md` | ✅ Fix-Report |
| `audit_reports/PROPOSAL_3b_MODULARITY.md` | ✅ gestaffelter Plan für Importzyklen/God-Objects (nicht ausgeführt) |
| `audit_reports/HANDOFF_FINAL_2026-11-25.md` | Standing Handoff (älter) |

**Ehrlicher CI-Status (im Guide dokumentiert):** ruff/mypy/bandit/pip-audit sind harte Gates; coverage nur „pytest muss laufen" (kein `--fail-under`); **vulture/radon/import-linter/detect-secrets/semgrep/pyright haben noch kein CI-Gate → nach §0 Theater**. Bitte nach den Scans echte Gates daraus machen oder bewusst als lokale Diagnose-Tools belassen und so dokumentieren.

## 4. Empfohlene Reihenfolge

1. Schnelle Scans: ruff (Log aktualisieren), detect-secrets, import-linter, radon, semgrep, pyright.
2. Echte Funde fixen (B324 SHA1, F821 `url`, F811-Redefinitionen) — **keine Laufzeitlogik ohne Test ändern**.
3. coverage + vulture (mit engerem Scope).
4. Final-Gate: `ARCHON_DATA_DIR=<temp> .ci_venv\Scripts\python.exe -m pytest tests/ -q` (0 failed), `compileall`, `tsc --noEmit`, `npm run build`, `docker compose config --quiet`, `audit_secrets.py --all`.
5. **Erst wenn alles grün:** Zertifikat erstellen und veröffentlichen.

## 5. Nicht tun

- Kein `mypy --strict` / `pyright --strict` direkt (Tausende Funde ohne Priorität).
- Kein globales `disable_error_code` oder `ruff --fix` ohne Review (würde Gate erneut zum Theater machen).
- Keine Produktiv-DB/.env/Audit-Kette verändern. Kein stummes Re-Signieren des Audit-Ketten-Bruchs (siehe `INCIDENT_2026-11-25_LOGIN_OUTAGE.md`).

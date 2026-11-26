# v0.6 Re-Zertifizierung & Go/No-Go (26.11.2026)

**Worktree:** `C:\Users\micha\.local\share\opencode\worktree\b1d671\fullscan-d5` (Branch `fullscan-d5`)
**Verifizierter Code-HEAD:** `5f5c0bb85639f494d1f9ae2c9775193cb2a7546c`
**Vorher:** `8a69868c` (F40 + 3 v0.6-Härtungs-Commits)
**Maschinen-Gate-Protokoll:** `audit_reports/V06_MACHINE_GATE.log`
**Red-Team-PoCs:** `Temp\opencode\v06-rt1\`, `v06-rt2\`, `v06-rt3\` (isolierte Temp-Verzeichnisse)
**Push-Status:** **KEIN PUSH** (wartet auf explizite Owner-Freigabe).

---

## 1. Empirisches Full-Gate (13/13 EXIT=0, final nach allen RT-Fixes)

| # | Gate | Ergebnis |
|---:|---|---|
| 1 | ruff kritisch `E9,F63,F7,F82` | EXIT=0 |
| 2 | Ruff A/B gegen `bc31e2dd` | `NEUE_FUNDE=0`, `VERBESSERUNGEN=3` |
| 3 | mypy(new D5 `--disallow-untyped-defs`) | EXIT=0 (3 Dateien) |
| 4 | mypy(full) | EXIT=0 (439 Dateien) |
| 5 | lint-imports | 2 kept / 0 broken (315/1148) |
| 6 | compileall | EXIT=0 |
| 7 | audit_secrets | 7177 Dateien, 0 Secrets |
| 8 | bandit | EXIT=0 |
| 9 | pip-audit | 0 bekannte Schwachstellen |
| 10 | `tsc --noEmit` (read-only gegen Hauptbaum-node_modules; `frontend/`-Diff = 0) | EXIT=0 |
| 11 | `curl http://127.0.0.1:8501/livez` (read-only) | HTTP 200 |
| 12 | A/B-Router exakt | `paths=799 routes=91 load_errors=0 rbac=True ABWEICHUNGEN=0` |
| 13 | `pytest tests/` (seriell) | **2538 passed, 20 skipped, 0 failed** |

---

## 2. Adversarielles Red-Team (nach „No Exploit, No Report")

| Run | Ergebnis | Beleg |
|---|---|---|
| RT1 PoC 1A (strict-audit, 2 Failed-Cancels) | **CLEAN** | `_FAILED_CANCELS=['bg_task_1','bg_task_2']`, `_BACKGROUND_TASKS=[]`, Eskalation `RuntimeError('audit_write_failed')`, EXIT=0 |
| RT1 PoC 1B (wait_for-Timeout verwirft gather-Results) | **EXPLOIT bei `8a69868c` → NOT_REPRODUCED bei `5f5c0bb8`** | Vorher `FAILED_CANCELS=[]`, keine Eskalation; nach Fix beide Tasks erfasst + Eskalation, EXIT=1 |
| RT1 PoC 2A/2B (parallele Resume-Cleanups / silent persist) | **INCONCLUSIVE** | Harness-Fehler: `sqlite3.OperationalError: table workflow_runs has 8 columns but 5 values were supplied` (EXIT=99); kein Produktbefund, nicht als PASS gewertet |
| RT2 Absoluter Pfad außerhalb Workspace | **GEFIXT** | Original-PoC `poc_audit_abs_path.py`: `PermissionError`, EXIT=1 |
| RT2 Case-Bypass `.ENV`/`AUDIT_ANCHOR`/`C:/WINDOWS/SYSTEM32` | **GEFIXT** | `poc_audit_case_bypass.py`: 3/3 blockiert, `exploited 0/3`, EXIT=1 |
| RT2 PocketBase `%`-Wildcard → Fremd-PATCH | **GEFIXT** | Kein PATCH auf `victim-42`; `null` statt `items[0]` |
| RT2 Cost-Guard Persistenzfehler | **GEFIXT** | Original-PoC: Disk unverändert, RAM akkumuliert, WARNING, nächster Event persistiert 1401/7.135, EXIT=0 nach Testangleichung |
| RT2 Positive Controls | **PASS** | `poc_audit_baseline.py`: `notes/ok.md` erlaubt, `../…`/`.env` blockiert |
| RT3 Mutations-Check (12 Tests) | **12/12 rot** | `MUTATED_EXIT=1` für alle 12 Fälle nach Schärfung der 2 Theater-Gates |

Zwei anfängliche Theater-Gates wurden geschlossen: `test_v06_cost_guard_plugin_persists_atomically`
und `test_f34_force_done_audit_is_non_blocking_and_returns_503_on_audit_failure`
waren vorher bei Fix-Ausbau grün (`MUTATED_EXIT=0`), jetzt rot.

---

## 3. Reifegrad (6 Kriterien, Stand `5f5c0bb8`)

| Kriterium | `ee18373a` | F40 `7a580e95` | **jetzt** |
|---|---:|---:|---:|
| Security, Krypto & Zero-Trust | 5,5 | 8,5 | **8,6** |
| Verifikation & Test-Integrität | 5,5 | 8,5 | **8,7** (12/12 Mutationen rot) |
| Event-Loop & Performance | 5,5 | 8,2 | **8,2** |
| Modularität & Architektur | 5,5 | 7,4 | **7,4** (C4/C5 offen) |
| Governance & Produktiv-Betrieb | 5,5 | 8,2 | **8,3** (Timeout-Record-Verlust geschlossen) |
| Ehrlichkeit von Doku & Runtime | 5,5 | 8,0 | **8,0** |
| **Gesamt** | **5,5** | **8,1** | **8,2 / 10** |

---

## 4. Ehrliche Restfläche / `v0.6.0`-Backlog

- **D5 bleibt bewusst partiell:** C4 (Boardroom-Orchestrierung) und C5 (Dispatch-Core) offen; kein Fertig-Claim.
- **D4** (Telegram-Adapter, Drittsoftware): Owner-Entscheidung, außerhalb Ownership.
- **`.mcp.json`**: `pay`/`pay-cli`/`canonry` weiterhin ungepinnt (Pre-Flight-MED, nicht in den 3 Härtungs-Commits enthalten).
- **`tools/migrate_projects_structure.py`**: Dry-Run/Rollback-Manifest offen (Pre-Flight-MED).
- **RT1 2A/2B** inconclusive (Harness-SQL-Fehler) – nachgebauter PoC mit korrektem Schema steht aus.
- **Audit-Kette:** Startup-Blocker behoben; historischer Kettenbruch bewusst archiviert (`data/backups/pre_hmac_archive_2026-11-26/`), nicht re-signiert, Betreiberentscheidung dokumentiert.
- `otel_sdk=false`, `~/.hermes`-Fallback, flaky Test `test_stage1_stage3_hardening_and_bus.py:808`, `main.py`-Ratchet: unverändert dokumentiert.

---

## 5. Votum

**GO für v0.6** (Merge/Push nach expliziter Owner-Freigabe). Alle harten Gates grün, 0 reproduzierbare
Exploits in den ausgeführten PoCs, 12/12 Mutations-Checks rot. **Kein Push ausgeführt.**
Die beiden inconclusiven RT1-PoCs sind als offene Verifikationsschuld ausgewiesen, nicht als PASS.

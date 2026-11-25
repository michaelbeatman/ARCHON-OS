# HANDOFF — Hy4 (nicht Flash) / Debugging-Fortsetzung 25.11.2026

## 1. Stand (gesichert)

| Prüfung | Ergebnis |
|---|---|
| Full-mypy | ✅ `Success: no issues found in 416 source files` (mit `--config-file mypy.ini`, ohne `--txt-report` — der Report-Flag crasht mypy 2.4.1 intern) |
| Pauschale `# mypy: ignore-errors` | ✅ 43 → 0 |
| Zwei letzte Bugfixes (Orchestrator) | ✅ mypy `--no-incremental core_dispatcher.py scripts/import_linkedin_messages.py` → 0 Fehler |
| Full-Suite (letzte gesicherte Läufe der Typ-Agenten) | ✅ 2342 passed / 16 skipped / 0 failed, `.ci_venv`, `ARCHON_DATA_DIR=<temp>` |
| compileall / compose / tsc / npm build / audit_secrets | ✅ alle Exit 0 (zuletzt vor den 2 Bugfixes) |
| Produktiv | Login funktioniert, Container healthy, `/livez`/`/readyz`/`/health` 200 |
| Git | Backup-Commit `bd9209be`; danach viele Änderungen noch **nicht** committet |

## 2. Zwingende Schutzregeln

1. **Nie** Tests gegen `./data` laufen lassen — immer `$env:ARCHON_DATA_DIR='C:\Users\micha\AppData\Local\Temp\opencode\archon-<zweck>'`. (Einmalige Produktiv-DB-Korrumpierung ist dokumentiert in `INCIDENT_2026-11-25_LOGIN_OUTAGE.md`.)
2. Nicht ändern: `.env`, `data/memory.db`, Audit-Kette, laufende Container. Kein stummes Re-Signieren (siehe Incident).
3. NEVER_DO_LIST: kein Coroutine-Replay, keine PostgreSQL-Migration.
4. `pwsh.exe`-Spawn ist zeitweise blockiert (`Zugriff verweigert`, os error 5) — tritt gehäuft bei parallelen Shell-Agenten auf. Sequenziell läuft es. Shell-Befehle bei Bedarf 2–3× retry.
5. **Kein Push und kein Commit** ohne explizite Freigabe. User-Entscheidung 25.11.2026: erst die Antwort von Hy4 (nicht Flash) abwarten, dann Final-Gate grün, dann ggf. committen/pushen. Grund: jeder bisherige Deploy/Push hat Follow-up-Fehler erzeugt, die aufwendig entfernt werden mussten.
6. **Kein Zertifikat** erstellen — nur wenn alles vollständig sauber ist, dann veröffentlichen.

## 3. Was gerade noch lief / offen ist

| Punkt | Status |
|---|---|
| Bandit nach SHA1-Fix | ✅ **0 HIGH** — `bandit -q -lll -r archon backend scripts utils` lief ohne Output (Exit 0). Vor dem Fix: 1 HIGH (`import_linkedin_messages.py:165`, B324), behoben mit `usedforsecurity=False`. |
| Final-Gate | Nach den 2 Bugfixes **noch nicht** komplett wiederholt: `pytest tests/ -q`, `compileall`, `tsc --noEmit`, `npm run build`, `docker compose -f docker-compose.yml config --quiet`, `audit_secrets.py --all` |
| ruff | 887 Funde: 576 I001 (Imports, kosmetisch), 246 F601 (doppelte Dict-Keys, v.a. `scripts/es_translate_local.py`), 46 F541, 14 F811, 3 E731, **2 F821**. F821 in `core_dispatcher.py:1998` ist behoben (expliziter Platzhalter `egress-firewall://proof.local` statt undefiniertem `url`). Zweiter F821 bitte mit `ruff check . --select F821` verifizieren. |
| pip-audit | **10 CVEs in 4 Paketen**: `mcp 1.29.0` (5×, Fix 1.30.0/2.2.0), `opentelemetry-api 1.37.0` (2×, Fix 1.45.1/1.45.2), `stanza 1.10.1` (2×, Fix 1.12.2), `wcmatch 8.5.2` (1×, Fix 11.2). Achtung: semgrep-Installation hat `opentelemetry-api` in `.venv` auf 1.37 gesenkt (FastAPI will ≥1.44) — Dev-Toolchain, nicht Laufzeit.升级 mit Lockfile-Hashes und Test-Gate. |
| radon | ✅ gelaufen: 4650 Blöcke, Durchschnitt **B (7.14)** = gesund. Ausreißer: `workflow_dag_runner.py:1211` CC 246 (F), `hermes_config.py:287` CC 138, `delegation.py:1383` CC 135, `orchestration.py:1385` CC 116, Telegram-Patch CC 158. Siehe `PROPOSAL_3b_MODULARITY.md` — bewusst nicht zerlegt. |
| import-linter | ⚠️ **Korrektur 2 (Hy4):** Die Ursache ist nicht nur Singular/Plural, sondern `root_packages` (**Plural**, v2.17: `forbidden.py:257-259`, `use_cases.py:436-441`) — `archon` **und** `backend` müssen beide intern sein, `include_external_packages = False` bleibt richtig. Real: 715 Importzeilen zwischen `backend`↔`archon`, Zyklus `delegation.py`↔`operations_api.py` weiterhin aktiv. Die korrigierte Config entsteht in Hy4s Worktree, nicht im Hauptbaum. |
| vulture / semgrep / pyright / detect-secrets / coverage | Logs in `audit_reports/tool_scans/` liegen teils noch von fehlgeschlagenen Agentenläufen („NOT EXECUTED") — **nicht als echte Ergebnisse zählen**. detect-secrets hängt (0-Byte-Log). Äquivalent: `audit_secrets.py --all` → 0 Funde (7072 Dateien). |
| Clean-Code-Zertifikat | bewusst zurückgestellt |

## 4. Dokumentation (bereits erledigt)

- `THIRD_PARTY_LICENSES.md` §6: alle Scanner mit Lizenz/Zweck/Dev-only
- `docs/system/MYPY_TYPE_GATE_GUIDE.md`, `docs/system/STATIC_ANALYSIS_TOOLCHAIN_GUIDE.md`
- `docs/system/ROADMAP_2026.md`: RAG-Idee + Toolchain-Idee im Ideen-Pool
- `audit_reports/FIX_VERIFICATION_LOG.md`, `MASTER_PLAN.md` §9, `HANDOFF_FINAL_2026-11-25.md`, `HANDOFF_ANTIGRAVITY_2026-11-25.md`
- **Ehrlich dokumentiert:** nur ruff/mypy/bandit/pip-audit sind harte CI-Gates; vulture/radon/import-linter/detect-secrets/semgrep/pyright haben **kein** Gate → nach §0 Theater.

## 4b. S1-Status / DELEGATED (Hy4, 25.11.2026)

| Punkt | Status |
|---|---|
| S1 im Worktree `…\worktree\b1d671\god-objects` (HEAD `2ee92706`) | 2/3 Full-Gate-Läufe grün (2342/20/0 und 2343/20/0), 1 Lauf rot durch **flaky Test**, A/B-Eingrenzung 6/6 isoliert grün. Lauf 3 mit final korrigiertem Stand läuft. |
| Flaky Test + Kostenbug `:1763-1764` | **DELEGATED an G7/Antigravity** — nicht S1-verursacht, vorbestehend. Muss im S1-Report §7 und in der Commit-Message ehrlich stehen bleiben. |
| Lokaler S1-Commit (nach grünem Lauf 3) | Nur 3 Dateien (`.importlinter`, `tests/test_import_layer_contracts.py`, `S1_IMPORT_CONTRACT_REPORT.md`), **kein Push**, kein `--no-verify`. |
| Unabhängige Verifikation (unsere Rolle) | Läuft **nach** dem Commit gegen den definierten HEAD — bei echtem Befund lokal amend/revert möglich, da kein Push. |

## 5. Empfohlene Reihenfolge für den neuen Lauf

1. ✅ Bandit: 0 HIGH bestätigt — erledigt.
2. `ruff check . --select F821` → 0 Funde bestätigen; F811 einzeln bewerten (meist lokale Imports, die Top-Level-Importe shadowen).
3. ~~pip-audit-CVEs: betroffene Pakete im Lockfile anheben~~ **KORREKTUR (Hy4, verifiziert):** `mcp`/`stanza`/`wcmatch` stehen in **keinem** Manifest, `opentelemetry-api` ist im Runtime-Lock **bereits 1.45.2** (Fix-Version). Die 10 CVEs betreffen die Dev-`.venv`, nicht das Produkt. → **kein Bump**, kein Lockfile-Eingriff.
4. import-linter-Config bereinigen, echten Verstoß-Check erneut laufen lassen.
5. **Final-Gate komplett** (siehe §3) mit `ARCHON_DATA_DIR=<temp>`.
6. Danach ggf. `git commit` des grünen Stands.
7. God-Objects/Importzyklen **nicht** in diesen Lauf ziehen — eigenes Projekt mit Worktree.

## 6. Werkzeuge/Versionen

`.venv` (Python 3.12): mypy 2.4.1, ruff, bandit, pip-audit, vulture, radon, import-linter, detect-secrets, semgrep, coverage, pyright via npx.
`.ci_venv` (Python 3.11): pytest, uvicorn, FastAPI — hier laufen die Tests.
`node v24.17.0`, `npm`, `npx` vorhanden.

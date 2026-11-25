# Full-Scan & Bewertung — Archon OS, 25.11.2026

**Anlass:** Frage nach dem Gesamtstand („wieder 4/5 oder solide 8?") nach Abschluss der
Import-Schuld-Tilgung (`s1-god-objects`, HEAD `ee18373a`) und der
Artefakt-Bereinigung.

**Methodik:** Messung im Worktree `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects`
mit den absoluten Executable-Pfaden aus dem Hauptbaum (`.venv` = Py 3.12 für
ruff/mypy/lint-imports/bandit/pip-audit/radon/vulture, `.ci_venv` = Py 3.11 für
pytest/python). `ARCHON_DATA_DIR=<temp>`, `ARCHON_TEST_DB_ISOLATION=1`.
**Keine Änderung am Worktree, kein Commit, kein Push.**

> **Wichtigste Aussage vorweg:** Der Scan hat die Bewertung **präzisiert, nicht
> verbessert**. Er hat vorbestehende strukturelle Befunde sichtbar gemacht.
> Der Sprung von „4/5" auf „8" ist real — aber **nur in den Dimensionen, die
> diese Session bearbeitet hat**.

---

## 1. Harte Gates — alle grün (Push-relevant)

| Prüfung | Exakter Aufruf / Quelle | Ergebnis |
|---|---|---|
| Ruff Changed-Files-Ratchet | `ruff --select E,F,I --ignore E501` auf `git diff 2ee92706..HEAD` (29 `.py`) | **All checks passed!** EXIT 0 (572 → 0 Funde) |
| Ruff kritisch | `--select E9,F63,F7,F82` | **All checks passed!** EXIT 0 |
| `lint-imports` | `--no-logo`, `.importlinter` | **2 kept / 0 broken**, **0 ignored imports** (287 Dateien, 992 Dependencies) |
| mypy Full-Run | `mypy --config-file mypy.ini archon backend main.py core_dispatcher.py scripts utils` | **Success: no issues found in 410 source files** |
| mypy geänderte / neue | 29 Dateien + 2 neue mit `--disallow-untyped-defs` | 0 / 0 |
| compileall | `-q archon backend scripts tools utils core_dispatcher.py main.py` | EXIT 0 |
| bandit (**CI-Aufruf**) | `ci.yml:452`: `-q -lll -r main.py core_dispatcher.py backend archon -x tests,scripts` | **EXIT 0** (0 HIGH) |
| pip-audit (**CI-Aufruf**) | `ci.yml:446`: `pip-audit -r requirements.lock.txt` | **No known vulnerabilities found**, EXIT 0 |
| `pytest tests/ -q` | Full-Gate `ee18373a` | **2355 passed / 20 skipped / 0 failed** (3:00) |
| `audit_secrets.py --all` | 7108 Dateien | **0 Funde** |
| Fail-Closed-Negativprobe | `_assert_router_health()` + `ARCHON_ALLOW_BROKEN_ROUTERS` | RuntimeError / Opt-Out kein Abbruch |
| Import-Smoke | `rbac_guards.is_configured()`, Re-Export-Identität, **799 OpenAPI-Pfade** | alle grün |

**`pip-audit` ohne `-r` (Dev-`.venv`) liefert EXIT 1 mit 10 CVEs in 4 Paketen**
(`mcp 1.29.0`, `opentelemetry-api 1.37.0`, `stanza 1.10.1`, `wcmatch 8.5.2`).
Laut `HANDOFF_HY4_DEBUG §5` (verifizierte Korrektur): `mcp`/`stanza`/`wcmatch`
stehen in **keinem** Manifest, `opentelemetry-api` ist im Runtime-Lock **bereits
1.45.2**. → betrifft nur die Dev-Toolchain, **kein Bump, kein Lockfile-Eingriff,
kein Push-Blocker**.

---

## 2. Weiche Scanner — Befunde, aber keine harten Gates

`HANDOFF_HY4_DEBUG §4` / `INVARIANTS §1`: *„nur ruff/mypy/bandit/pip-audit sind
harte CI-Gates; vulture/radon/import-linter/detect-secrets/semgrep/pyright haben
keins → Theater. Ein Gate, das immer grün ist, ist schlimmer als keins."*
Diese Funde sind **Bestandsaufnahme, nicht Regression**.

| Scanner | Ergebnis | Einordnung |
|---|---|---|
| **radon** (`cc -s -n F`) | 152 Ausgabezeilen, ~50 Blöcke Rang **F (CC ≥ 41)**. Spitzen: `api_save_hermes_form_config` 138, `_watch_delegated_task` 135, `_run_synthesis_cascade` 116, `_execute_delegation` 114, `api_get_hermes_profiles` 118, `api_brain_galaxy_data` 58, `api_chat_stream` 56 … | `ANALYSIS_GOD_OBJECTS.md §1.2` dokumentiert CC **246** (`default_agent_node_executor`, `workflow_dag_runner.py:1211`) als größten Ausreißer. **Bewusst nicht zerlegt** (D1). |
| **vulture** (`--min-confidence 100`) | **17 Treffer**: 10× ungenutzte Variable (`save_mc`, `alert_msg`, `force_check`, …), 6× redundante if-Bedingung (`core_dispatcher.py:2230/2255/2280/2345`, `agent_router.py`), 1× unreachable code, 1× unsatisfiable ternary | Kein Gate. `INVARIANTS §3` warnt: merkwürdiger/toter Code hat oft einen Grund → **nicht blind löschen**. |
| **import-linter** | 2 Contracts kept / 0 broken | Lokal hart, in CI **kein** eigener Schritt; das Äquivalent ist `tests/test_import_layer_contracts.py` (5 Tests, nicht tautologisch). |
| **semgrep** | `semgrep.txt` 18 B, `"NOT EXECUTED"` | Bewusst nicht erneut ausgeführt. |
| **detect-secrets** | `detect_secrets.txt` ~8 MB; laut Handoff hängt der Lauf (0-Byte-Log) | Bewusst nicht erneut ausgeführt. Äquivalent: `audit_secrets.py --all`. |
| **pyright** | `pyright.txt` 583 KB, via `npx` | Nicht erneut ausgeführt. |
| **coverage** | `ci.yml:555` `coverage run -m pytest tests/ -q` + `coverage report`, **ohne `--fail-under`** | Kein Fail-Gate, **keine gemessene Abdeckungszahl** vorhanden. |

---

## 3. God-Objects — Zeilenzahlen (nach dieser Session)

| Datei | Jetzt | Früher (Analyse-Snapshot) | Δ |
|---|---:|---:|---:|
| `main.py` | **2919** | 3638 | −719 |
| `backend/operations_api.py` | **3829** | 4511 | −682 |
| `core_dispatcher.py` | 3583 | 3803 | −220 |
| `backend/workflow_dag_runner.py` | 2833 | 3035 | −202 |
| `archon/core/delegation.py` | 2127 | 2346 | −219 |
| `archon/core/orchestration.py` | 1783 | 1941 | −158 |
| `scripts/patches/hermes_telegram_adapter.py` | 10290 | 11232 | −942 |

Die Reduktionen stammen aus der Import-Schuld-Tilgung (F4: 14 Router-Blöcke +
125 Re-Exports entfernt) und Antigravity's Ruff-Cleanup. **S2–S4
(God-Object-Zerlegung) sind nicht ausgeführt** — `ANALYSIS_GOD_OBJECTS.md` D2
stuft `main.py` als 🔴 höchstes Risiko ein. Der Rückwärts-Zyklus
(Invariante **#3**: ≥27 Module importieren `main` zurück, ~50 `app_main.*`-
Symbole) besteht weiter — die Re-Exports wurden per `X as X` **erhalten**, nicht
aufgelöst.

---

## 4. Bewertung nach Dimension

| # | Dimension | Evidenz | Note |
|---:|---|---|---:|
| 1 | Import-Layering / Architekturgrenzen | 23 → 0 Paare, 0 Ignores, 2 Contracts, streng transitiv, hartes pytest-Ratchet mit Negativprobe, F5-Schloss | **9** |
| 2 | CI-Gate-Fähigkeit (Ruff) | 572 → 0 Funde in gesamter PR-Range, kritische Klassen 0 | **9** |
| 3 | Typen / Statik / SAST | mypy 410/0, compileall 0, bandit CI-Aufruf 0 HIGH | **8** |
| 4 | Supply Chain | `pip-audit -r requirements.lock.txt` = 0 CVEs | **8** |
| 5 | Regression | 2355/20/0 — aber keine Coverage-Zahl, CC-246-Block nur 4 direkte V-Tests, `test_workflow_dag_e2e.py` umgeht den Executor komplett | **7** |
| 6 | Secrets | Pre-Commit-Hook 0 Funde, kein `--no-verify` — aber `audit_secrets.py:146` nutzt `git ls-files`, **untracked Dateien wurden nie geprüft**, `fix_d2_mypy.md`-Zitat offen | **6** |
| 7 | Prozess / Nachvollziehbarkeit | Ownership, unabhängiger Zweitblick, 1 Commit = 1 Full-Gate, A/B-Dokumentation, kein Push ohne Freigabe | **9** |
| 8 | Komplexität / Monolithen | ~50 Rang-F-Blöcke, CC 246, Monolithen 1.8k–10k Zeilen, S2–S4 offen | **4** |
| 9 | Invarianten-Absicherung | #3 / #7 / #8 / #9 offen (⛔), `tests/test_invariants.py` bewusst nicht gebaut | **4** |
| 10 | Dead Code | 17 vulture-Treffer @ 100 %, kein Gate | **5** |

### Antwort auf „4/5 oder 8?"

**Beides — je nach Gewichtung.**

- Bewertet der Score **CI-Grünheit, Import-Hygiene, Typensicherheit, Regression
  und Prozess** (also genau das, was diese Session adressiert hat), ist es eine
  **solide 8, eher 8–9**. Der Sprung von 4/5 ist real und messbar.
- Bewertet er die **Code-Qualität im Ganzen** — Komplexität, Monolithen,
  Testabdeckung kritischer Pfade, offene Invarianten — bleibt es bei **5–6**.
  Daran hat diese Session **fast nichts geändert**, weil es nicht der Auftrag
  war („17 Paare tilgen, keine neuen Analysen starten").

**Der Full-Scan hat daran nichts geändert.** Er hat die offenen Punkte lediglich
**beziffert**: ~50 Rang-F-Blöcke, 17 vulture-Treffer, sieben Monolithen, vier
offene Invarianten, fehlende Coverage-Zahl.

---

## 5. Was eine echte Gesamt-8 bräuchte (kein weiterer Scan)

1. **S2–S4**: Zerlegung von `main.py` / `core_dispatcher.py` /
   `operations_api.py` / Telegram-Adapter — jeweils 1 Commit + Full-Gate,
   mit dem `app_main.*`-Rückwärts-Zyklus (Invariante #3) als erstem Schritt.
2. **Characterization-Tests für CC 246** (`default_agent_node_executor`):
   `ANALYSIS_GOD_OBJECTS.md` D1 nennt nur 4 direkte Verhaltenstests und eine
   große ungetestete Verzweigungsmatrix.
3. **`tests/test_invariants.py`** für #3, #7, #8, #9 — mit Negativprobe je
   Invariante (`INVARIANTS.md §5`).
4. **Coverage-Gate**: `coverage report --fail-under=…` statt nur `coverage report`
   (`ci.yml:556`), plus `pytest-cov` für die Full-Suite.
5. **17 vulture-Treffer einzeln bewerten** — nicht blind löschen (`INVARIANTS §3`).
6. **Secret-Scan auf untracked Dateien** ausweiten oder das
   `fix_d2_mypy.md`-Zitat bewusst zur Doku-Ausnahme erklären
   (Owner-Entscheidung, Handoff §7).

---

## 6. Blinde Flecken dieses Scans (ehrlich)

- Nicht ausgeführt: semgrep (`NOT EXECUTED`), detect-secrets (hängt), pyright
  (583 KB Log, via npx), coverage (kein Fail-Gate).
- `audit_secrets --all` prüft nur **getrackte** Dateien; die 7 `??` im Hauptbaum
  (5 Handoff-Docs, `fix_d2_mypy.md`, `audit_reports/_archiv_2026-11-25_artefakte/`)
  wurden **nie** gescannt.
- Die archivierten `run_*scans.ps1` wurden **nicht** reaktiviert; sie nutzen
  relative `.venv`-Pfade und funktionieren im Worktree nicht (dort gibt es keine
  Venvs). Alle Scanner liefen direkt mit absoluten Pfaden.
- `mypy .` crasht an `hermes-webui` (ungültiger Paketname) → Full-Run über die
  CI-Pfade, wie in `ci.yml:535`.

---

## 7. Push-Status

**Alle harten CI-Gates sind grün. Kein Blocker.** `s1-god-objects @ ee18373a`,
Working Tree sauber, **kein Push** (der Nutzer pusht selbst).

Verbleibend DELEGATED: Flaky-Test
(`test_stage1_stage3_hardening_and_bus.py:775-785`), Kostenpfad-Bug
(`workflow_dag_runner.py:1763-1764`), Owner-Entscheidung zum Secret-Zitat,
Push-Freigabe.

Siehe auch: `HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md` (§12 finaler Stand,
§13 Artefakt-Bereinigung), `HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md`,
`ANALYSIS_GOD_OBJECTS.md`, `INVARIANTS.md`.

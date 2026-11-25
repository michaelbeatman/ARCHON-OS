# HANDOFF — Pre-Push-Remediation für Gemini neon, 25.11.2026

**Zweck:** Dieses Dokument ist für einen Agenten mit **frischem Kontext** geschrieben. Es beschreibt, was nach Abschluss der Import-Schuld-Tilgung noch offen ist, **warum** es offen ist, und wie es vor dem ersten Push behoben werden kann.

**WICHTIG:** Der Nutzer pusht **selbst**. Du pushst **nicht**. Du bereitest nur den Stand so vor, dass der erste Push CI-grün wird.

---

## 0. In 60 Sekunden

- **Erreicht:** Import-Schuld `23 → 0` Paare, `.importlinter` `ignore_imports` leer, Debt-Test `== 0`. Zwei Commits auf `s1-god-objects`, beide mit grünem Full-Gate.
- **Lokal alles grün:** `pytest tests/ -q` = 2355 passed / 20 skipped / 0 failed; `lint-imports` = 2 kept / 0 broken / **0 ignored imports**; mypy 0; compileall 0; `audit_secrets --all` 0.
- **Aber:** Der erste **Push/PR würde CI rot machen** — nicht wegen der Logik, sondern weil der Changed-Files-Ratchet `ruff --select E,F,I --ignore E501` auf `main.py` (513 Alt-Funde) und `backend/operations_api.py` (37 Alt-Funde) losläuft. Gemessen: **550 Funde**.
- **Dein Auftrag:** Baustelle A (Ratchet) bewerten und beheben, ohne die Import-Schuld-Arbeit anzutasten. Baustellen B–D sind Hygiene/DELEGATED, keine CI-Blocker.

---

## 1. Verifizierter Stand

| | |
|---|---|
| Hauptbaum | `C:\.Antigravity-projekte\AgenticOS-2026` · Branch `main` · HEAD `2ee92706` · **kein Push** |
| Worktree | `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects` |
| Branch | `s1-god-objects` |
| HEAD | **`cbdeccb4`** — `fix(F2/F5): letzte 3 Import-Paare getilgt, ignore_imports leer (3 -> 0)` |
| Davor | `04e3cc7d` — `fix(F4/F3): 14 operations_*-Router ... (17 -> 3)` |
| Basis | `b9be7d37` (A2, 17 Paare) |
| Working Tree | **sauber** |
| Push | **keiner** |

Kette: `2ee92706 → 07979512 → 69f5626e → 85ffaf35 → 81c79e0e → ceaf7088 → b9be7d37 → 04e3cc7d → cbdeccb4`.

Venvs liegen **NUR im Hauptbaum**: `.venv\Scripts` (Python 3.12: `ruff.exe`, `mypy.exe`, `lint-imports.exe`), `.ci_venv\Scripts` (Python 3.11: `pytest.exe`, `python.exe`). Der Worktree hat **keine** eigenen Venvs → alle Gates mit **absoluten Executable-Pfaden** bei `cwd = Worktree` ausführen.

---

## 2. Warum das offen blieb (nicht „vergessen")

Der Auftrag war explizit: *„17 Paare, in 2 Schritten, je 1 Commit + 1 Full-Gate … Heute abschließen, keine neuen Analysen starten."* Die offenen Punkte sind bewusst abgegrenzt:

1. **A/B-Praxis** (Vorgabe aus `b9be7d37`): *„alle 4 vorbestehend, 0 neue"*. Angefasste Dateien dürfen Alt-Funde haben, solange keine neuen dazukommen. Frühere `chore(ruff)`-Commits betrafen 24 bzw. 11 Funde in kleinen Dateien.
2. **Ownership** (`INVARIANTS §4.1`): exklusive Positiv-/Negativliste; „Außerhalb Ownership = dokumentieren, nicht ändern". Die Artefakte liegen im Hauptbaum, nicht im Worktree.
3. **Risiko** (`ANALYSIS_GOD_OBJECTS.md` D2): `main.py` ist 🔴 **höchstes Risiko** — W0–W5-gehärtete Pfade (Lifespan-Fail-Fast, `/livez`/`/readyz`, RBAC, Audit-HMAC, Auth-Bind). Die F401 sind überwiegend geschützte Re-Exports, die E402 bewusst platzierte Router-Imports.
4. **Tempo**: Nutzer-Entscheidung „2 Gates statt der ursprünglich 5".
5. **DELEGATED** (Handoff §7): Flaky-Test und Kostenpfad-Bug sind vorbestehend, nicht S1-verursacht, und gehören nicht in F1–F5.

**Ehrliche Lücke:** Die **Konsequenz** (CI prüft absolut, kennt keine Baseline → 550 Funde → rot) wurde erst auf Nachfrage des Nutzers nachgemessen, nicht proaktiv kommuniziert. Genau das ist der Punkt, der die Gesamtbewertung drückt.

---

## 3. Baustelle A — DER einzige CI-Blocker: Changed-Files-Ratchet

### 3.1 Was CI tut

`.github/workflows/ci.yml:501-525`:

```bash
# Range
if [ "${{ github.event_name }}" = "pull_request" ]; then
  RANGE="origin/${{ github.base_ref }}...HEAD"     # GANZER Branch (32 Dateien)
else
  RANGE="HEAD^ HEAD"                               # nur letzter Commit (9 Dateien)
fi
FILES=$(git diff --name-only --diff-filter=ACMR $RANGE -- '*.py' '*.pyi')
ruff check --select E,F,I --ignore E501 $FILES --output-format=concise
```

Entscheidend: **CLI `--ignore E501` ersetzt die `ignore`-Liste aus `ruff.toml`** (dort stehen u.a. `E402`, `F401`, `F841`, `E741`, `E701` auf Legacy-Deferral). Im Ratchet werden diese Regeln also **wieder aktiv**. Es gibt **keine Baseline** und **kein `continue-on-error`**.

Separates hartes Gate: `ci.yml:499` — `ruff check --select E9,F63,F7,F82 …` (global, hier unkritisch).
Mypy-Ratchets: `ci.yml:527-551` (geänderte Dateien + `--disallow-untyped-defs` für neue).

### 3.2 Gemessener Ist-Stand

`cbdeccb4` ändert 9 Dateien; davon `.py`: `archon/routers/chat.py`, `backend/image_generate.py`, `backend/operations_api.py`, `backend/rbac_guards.py`, `backend/workflow_node_plugins.py`, `main.py`, `tests/test_import_layer_contracts.py`, `tests/test_reaudit_stage13.py`.

```
RUFF_FUNDE_IM_RATCHET = 550
  main.py                     513   (≈398 F401 + 114 E402 + 1 I001)
  backend/operations_api.py    37   (E402 am Dateianfang, ~6 F401, 12 E701, 1 I001)
  alle übrigen                 0
```

Nachmessen:
```powershell
$wt='C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects'
$V='C:\.Antigravity-projekte\AgenticOS-2026\.venv\Scripts'
$F=(git -C $wt diff --name-only --diff-filter=ACMR HEAD^ HEAD) -split "`n" | Where-Object {$_ -match '\.(py|pyi)$'}
& "$V\ruff.exe" check --select E,F,I --ignore E501 --statistics ($F | ForEach-Object { Join-Path $wt ($_ -replace '/','\') })
```

Bei einem **Pull Request** kommen alle 32 Branch-Dateien dazu (u.a. `backend/llm_kernel.py`, `archon/core/orchestration.py`, `tests/test_fix_batch7.py`), also mehr Funde.

### 3.3 Warum `ruff --fix` hier GEFÄHRLICH ist

`main.py` lädt ~75 Router per `include_router`; ≥27 Produktionsmodule importieren `main` **zurück** (lazy, ≥90 Stellen, ~50 Symbole). Aus `ANALYSIS_GOD_OBJECTS.md §2.3`, die geschützten `app_main.*`-Gruppen:

- Persistenz/Helpers: `load_agents`, `save_agents`, `load_roles`, `save_roles`, `load_services`, `save_services`, `load_memory`, `save_memory`, `load_profiles_list`, `_load_json`, `_save_json`, `_get_state_db`, `_save_message_to_db`, `add_ticker`, `ticker_entries`, `create_rolling_backup`
- Pfade/Konstanten: `WORKSPACE_DIR`, `MEMORY_DIR`, `OBSIDIAN_VAULT`, `OBSIDIAN_VAULT_DIR`, `PERSONALAKTEN_DIR`, `PROJEKTE_DIR`, `SETTINGS_FILE`, `STATE_DB_PATH`, `GATEWAY_CONFIG_FILE`, `QUICKCHAT_SESSIONS_DIR`, `DEFAULT_ROLES`, `soul_path`, `profile_dir`, `agent_log_path`, `__file__`
- Gateway/Hermes: `forward_to_hermes`, `_get_shared_proxy_client`, `_run_docker_exec`, `_get_all_installed_profiles`, `_load_gateway_config`, `_save_gateway_config`, `_update_profile_status`
- Auth/Decisions: `get_current_user_from_request`, `_get_service_token`, `_decision_self_api`, `_request_has_service_token`, `auth_service`, `app`
- Export/Dispatch: `core_dispatcher`, `api_get_hermes_profiles`, `api_telegram_relay`, `get_hud_telemetry`, `detect_container_port`
- Quickchat: `_quickchat_state_session_id`, `_ensure_state_session`

Ein F401-`--fix` löscht genau diese Importe → `import main as app_main` bricht zur Laufzeit. Die **114 E402** sind die absichtlich nach Code stehenden Router-Imports inkl. `try/except` + `_ROUTER_LOAD_ERRORS.append(...)`; ihre Reihenfolge ist **Pfad-Präzedenz** (`main.py:3149-3150`), Fail-Closed hängt an `_assert_router_health()` (`:3457-3486`). Dokumentiertes Schadensbild: „Router-404 bei healthy `/health`".

**Verboten:** blindes `ruff --fix`, `# noqa`, `ci.yml`-Aufweichung (per-file-ignores / `continue-on-error`). `INVARIANTS §4`: *„Ein Gate, das immer grün ist, ist schlimmer als keins."*

### 3.4 Lösungswege (bewerten, dann entscheiden — der Nutzer entscheidet)

| Option | Aufwand | Risiko | Bewertung |
|---|---|---|---|
| **A1 — `chore(ruff)`-Commit** für `main.py` + `operations_api.py`: jede F401 einzeln prüfen (Re-Export vs. wirklich tot), Re-Exports via `X as X` absichern (Ruff akzeptiert explizite Re-Exports, siehe `archon/routers/chat.py:56-61`), E402 durch `# noqa`-freie Umstrukturierung oder bewusste Dokumentation, E701/I001 händisch | **Hoch** (~550 Funde) | 🔴 | Sauber, aber eigenes Projekt mit Characterization-Tests; entspricht ANALYSIS D2/S2 |
| **A2 — Commit-Grenzen umbauen**, sodass `main.py`/`operations_api.py` nicht im letzten Commit erscheinen (bei Push reicht `HEAD^ HEAD`) | Gering | 🟡 | Hilft **nur bei Push**, nicht bei PR (`...HEAD` = ganzer Branch). Wirkt wie Gate-Umgehung → nur mit dokumentierter Begründung |
| **A3 — Bewusst mit rotem Ratchet pushen** und CI-Ergebnis dokumentieren | 0 | 🟡 | Nur mit **ausdrücklicher Freigabe** des Nutzers |
| **A4 — Alt-Funde als bewusste, dokumentierte Ausnahmen** im Ratchet führen (nicht `noqa`, sondern z.B. eigene Baseline-Datei, die der Ratchet lädt und die **nur sinken** darf) | Mittel | 🟢 | Empfehlenswert: erhält die Härte des Gates (Ratchet statt Aufweichung), passt zur etablierten A/B-Praxis. Muss `ruff.toml`/`ci.yml` ändern → eigenes Full-Gate |

**Empfehlung für die Bewertung:** A4 ist am konsistentesten mit `INVARIANTS §4.3` („Vorbestehende Funde → separater `chore(ruff)`-Commit, kein `noqa`, kein Mix") und der Ratchet-Idee (#10 Debt-Counter). A1 ist „richtig", aber ein eigenes Großprojekt. **Frag den Nutzer, bevor du A2/A3 wählst.**

### 3.5 Akzeptanzkriterium

```powershell
# cwd = Worktree, absoluter ruff-Pfad
$F=(git diff --name-only --diff-filter=ACMR HEAD^ HEAD) -split "`n" | Where-Object {$_ -match '\.(py|pyi)$'}
& "C:\.Antigravity-projekte\AgenticOS-2026\.venv\Scripts\ruff.exe" check --select E,F,I --ignore E501 --output-format=concise ($F | ForEach-Object { Join-Path $PWD ($_ -replace '/','\') })
# EXIT 0
```
Zusätzlich: PR-Range (`git diff 2ee92706..HEAD`) muss ebenfalls 0 ergeben, sonst ist die erste PR rot.

---

## 4. Baustelle B — Artefakte im Hauptbaum (Hygiene, KEIN CI-Blocker)

`git -C C:\.Antigravity-projekte\AgenticOS-2026 status --short` liefert **11** `??` (Handoff §7 nannte 6 — veraltet):

```
?? .importlinter                                  <- ALT-Config (root_package SINGULAR), verwirrend; Worktree hat die korrekte committet
?? audit_reports/HANDOFF_GOD_OBJECTS_F4F3_2026-11-25.md   <- Abschluss-Notiz dieser Session
?? audit_reports/HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md
?? audit_reports/INVARIANTS.md
?? audit_reports/S1_IMPORT_DEBT_DETAIL.md
?? audit_reports/fix_d2_mypy.md                  <- enthält laut Handoff ein SECRET-ZITAT (Owner-Entscheidung: Doku vs. Scanner-Regex)
?? audit_reports/mypy_full_stdout.txt
?? audit_reports/tool_scans/                     <- teils "NOT EXECUTED", nicht als echte Scanner-Ergebnisse zählen
?? scripts/run_fast_scans.ps1
?? scripts/run_remaining_scans.ps1
?? scripts/run_static_toolchain.ps1
```

**Wichtig:** Diese liegen auf `main` im Hauptbaum und sind **nicht** Teil von `s1-god-objects` → sie wandern bei `git push s1-god-objects` **nicht** mit. Risiko entsteht erst, wenn jemand `git add -A` macht oder ein Scanner über den Hauptbaum läuft (Secret-Zitat!).

Die `??`-Handoff-/Invarianten-Docs sind **bewusst untracked** (Handoff §1: „gehört nicht in die Worktree-Commits"). Nicht löschen, nicht in den Branch committen.

Zu klären: Alt-`.importlinter` löschen oder als historisch markieren; `fix_d2_mypy.md` gegen `audit_secrets`/detect-secrets bewerten; `tool_scans/` + `mypy_full_stdout.txt` + 3 Skripte entweder bereinigen oder bewusst als Dev-Artefakte dokumentieren.

---

## 5. Baustelle C — Flaky-Test (DELEGATED)

`tests/test_stage1_stage3_hardening_and_bus.py:775-785` — `test_dag_runner_schema_preserved_and_event_driven_recovery`. Enges `asyncio.sleep(0.15)` gegen `0.01` + SQLite-Recovery; erwartet `fast_recover` vor `slow`. Laut Handoff: **1 von 3** Full-Gate-Läufen rot, isoliert **6/6 grün**, nicht S1-verursacht, State-Leak-Verdacht. In **allen** Läufen dieser Session (3 Full-Gates) grün.

**Regel:** rote/obsolete Tests werden **eskaliert, nicht gelöscht, geskippt oder umgeschrieben**, um ein Gate grün zu bekommen (`fix_w3_d_trajectory_dag.md:121-127`). Ein Fix braucht einen Characterization-Test und ein eigenes Gate.

---

## 6. Baustelle D — Kostenpfad-Bug (DELEGATED)

`backend/workflow_dag_runner.py:1763-1764`: Log `Kostenberechnung fehlgeschlagen: unsupported operand type(s) for +=: 'NoneType' and 'float'`. `:1764` setzt `_cost_usd = None` — **Absicht** (D12: nie `0.0`, sonst geht ein Fehler als realer Wert in die Abrechnung). Ein Aggregator weiter unten addiert darauf.

**Nicht** „auf `0.0` fixen". Separater Fix unter Wahrung der D12-Semantik, mit eigenem Test. Nicht testrelevant, nicht CI-blocking.

---

## 7. Zwingende Regeln (aus `HANDOFF_HY4_DEBUG §2`, `INVARIANTS §4`, AGENTS.md)

1. **`ARCHON_DATA_DIR=<temp>`**, nie `./data`. Für pytest zusätzlich **`ARCHON_TEST_DB_ISOLATION=1`** setzen (`tests/conftest.py:60-64` erzeugt dann ein frisches `mkdtemp` und überschreibt `ARCHON_DATA_DIR`). Empfehlung: `C:\Users\micha\AppData\Local\Temp\opencode\archon-<zweck>`.
2. **Nicht ändern:** `.env`, `data/memory.db`, Audit-Kette, laufende Container. Kein stummes Re-Signieren.
3. **NEVER_DO:** kein Coroutine-Replay, keine PostgreSQL-Migration.
4. **Kein `--no-verify`**, **kein Push ohne Freigabe**.
5. **Vor JEDEM Commit:** `git restore -- config/kanban_meta.json` (Testlauf-Rauschen, `tpl_unit`).
6. **1 Schritt = 1 Commit = 1 Full-Gate**, mindestens: `ruff --select E,F,I --ignore E501` auf geänderte `.py`, `lint-imports`, `mypy --config-file mypy.ini` (geänderte + `--disallow-untyped-defs` für neue + Full-Run), `pytest tests/ -q`, `compileall`, `audit_secrets.py --all`.
7. **A/B gegen Baseline** bei vorbestehenden Funden: „0 neue" dokumentieren, nicht still bereinigen.
8. **Nicht vereinfachen ohne Test** (`INVARIANTS §3`): merkwürdiger Code hat einen Grund. Die 8 dokumentierten Fallen: `set_decision_factory`, `_cost_usd = None`, Vier-Augen `created_by`, `_FALLBACK_MODEL_PRICES_PER_1M`, 125 Re-Exports, `allow_indirect_imports`, `test_unbound_calls.py`, `core_dispatcher`-Doppelimport.
9. **Zweiter Blick ist Pflicht:** eine frische, unabhängige Instanz prüft den Fix, nicht derselbe Agent.
10. Historische `audit_reports/*.md` sind **Zeitdokumente** — nicht editieren. Neue Erkenntnisse in ein **neues** Report-Dokument.

---

## 8. Referenz-Docs (alle im Hauptbaum `audit_reports/`, Worktree hat teils eigene Kopien)

| Dokument | Wofür |
|---|---|
| `HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md` | Vollständige Ausgangslage, Rest-Plan, §7 Offen/DELEGATED |
| `HANDOFF_GOD_OBJECTS_F4F3_2026-11-25.md` | Abschluss-Notiz dieser Session (beide Commits, Gate-Ergebnisse, Fallen) |
| `ANALYSIS_GOD_OBJECTS.md` | **§2.3** `app_main.*`-Rückwärtsimporte, **D2** `main.py` 🔴, Ownership-Matrix §4 |
| `INVARIANTS.md` | §2 Katalog, §3 Vereinfachungs-Fallen, §4 Prozessregeln |
| `S1_IMPORT_DEBT_DETAIL.md` | 23 Paare, §9 Antigravity-Verifikation, §10 F1a |
| `HANDOFF_HY4_DEBUG_2026-11-25.md` | §2 Schutzregeln, §6 Werkzeuge/Versionen |
| `INCIDENT_2026-11-25_LOGIN_OUTAGE.md` | Warum nie `./data` |
| `.github/workflows/ci.yml` | `:496-525` Ruff-Ratchets, `:527-551` mypy, `:305/:555` pytest |
| `ruff.toml` | Legacy-`ignore`-Liste, die der Ratchet **nicht** anwendet |
| `mypy.ini` | SSOT, `python_version 3.11`, `warn_unused_ignores=True`, `explicit_package_bases` |

---

## 9. Bekannte Fallen aus dieser Session (bitte nicht wiederholen)

1. **UTF-8-BOM**: `[System.IO.File]::WriteAllText` mit `[Text.Encoding]::UTF8` kann ein BOM erzeugen → 8 pytest-Fehler durch `ast.parse`-`SyntaxError: invalid non-printable character U+FEFF`. **Byte-Level prüfen**, BOM-frei schreiben (`[System.Text.UTF8Encoding]::new($false, $true)`). Alle angefassten Dateien sind jetzt BOM-frei.
2. **Parallele `pwsh.exe`-Spawns** schlagen mit `Zugriff verweigert (os error 5)` fehl → Shell-Calls **sequenziell in EINEM Prozess**, lesende Subagenten parallel.
3. **PowerShell-Quoting**: `mypy … (Join-Path …),(Join-Path …)` ohne Array-Klammer → `Duplicate module named "__main__"`. Immer `$mods = @(…)` bilden.
4. **Ratchet ist dateigranular**, nicht zeilengranular: ein einziges neues `from … import …` in `main.py` erzeugt einen neuen **E402**. Neue Module müssen unter `--disallow-untyped-defs` vollständig annotiert sein.
5. **`as`-Selbstalias** (`X as X`) ist der F401-freie Weg für Re-Exports — aber isort will `as`-Importe in **getrennten Statements** (`combine-as-imports=false`) **und eine Leerzeile vor einem davor stehenden Kommentar**, sonst I001.
6. **Source-Text-Tests** brechen bei Modul-Verschiebungen: `tests/test_reaudit_stage13.py:58`, `tests/test_audit_p2_performance.py:15-19`, `tests/test_fix_w3_b_performance.py`. Vor jedem Move Referenzsuche.
7. **FastAPI** kapselt `include_router` in `_IncludedRouter`-Objekte (`.path` leer) — Routen über `app.openapi()["paths"]` prüfen, nicht über `app.routes`.
8. **PowerShell-Scanner** lehnt sehr komplexe Shell-Skripte mit `invalid-structure` ab → dann `edit`-Tool nutzen oder Skript aufteilen.

---

## 10. Erwartetes Endergebnis

- `s1-god-objects` weiterhin mit `cbdeccb4` als Import-Schuld-Abschluss (oder einem sauberen `chore(ruff)`-Nachfolger).
- `git diff --name-only --diff-filter=ACMR HEAD^ HEAD` → Ruff-Ratchet **EXIT 0**; PR-Range `2ee92706..HEAD` ebenfalls **EXIT 0**.
- `pytest tests/ -q` weiter **2355 passed / 20 skipped / 0 failed**, `lint-imports` **2 kept / 0 broken / 0 ignored imports**, mypy 0, `audit_secrets --all` 0.
- Working Tree sauber, **kein Push** (der Nutzer pusht selbst).
- Kurzer Report, welche Option aus §3.4 gewählt wurde und warum; historische Docs unangetastet.

**Erste Frage an den Nutzer, bevor du Code anfasst:** Welche Option aus §3.4 soll es sein? (Empfehlung: A4, falls er das Ratchet-Prinzip erhalten will; A1, falls er echte Bereinigung will.)

---

## 11. NACHTRAG — paralleler Antigravity-Cleanup (25.11., noch NICHT committet)

**WICHTIG: §3 ist damit faktisch erledigt, falls der Cleanup committet wird.** Die Zahlen in §3.1/§3.2 beschreiben den Stand von `cbdeccb4` und sind als historisch zu lesen.

### Was parallel passiert ist

Ein zweiter Agent (Antigravity) hat **im selben Worktree** — also parallel zu diesem Handoff — ein `A1 Komplett-Cleanup` durchgeführt. `INVARIANTS §4.4` untersagt paralleles Schreiben auf demselben Worktree; das war nicht abgestimmt. Der lesenden Verifikation zufolge ist aber **nichts beschädigt** worden.

Gemeldete Ergebnisse (vom Nutzer übermittelt, nicht von mir nachgemessen):

| Check | Ergebnis |
|---|---|
| Ruff PR-Range-Ratchet (`2ee92706..HEAD`, 29 `.py`) | **0 Funde** (vorher 572) |
| Ruff kritisch (`E9,F63,F7,F82`) | 0 Funde |
| `lint-imports` | 2 kept / 0 broken |
| mypy (29 geänderte Dateien) | 0 Fehler |
| compileall | bestanden |
| `audit_secrets --all` | 0 (7108 Dateien) |
| `pytest tests/ -q` | **läuft noch** (`task-235`, ~3 Min) |
| Commit | **noch nicht gestartet** |

Bereinigte Dateien: `main.py` 513 → 0, `backend/operations_api.py` 37 → 0, `archon/routers/operations_org.py` 16 → 0, `tests/test_fix_batch7.py` 5 → 0, `tests/test_rbac_admin_routes_paket2.py` 1 → 0. Methode laut Bericht: geschützte `app_main.*`-Re-Exports per `X as X` erhalten, 25 komplett tote Re-Exports entfernt, Modul-Top-Level-Imports an den Dateianfang gezogen, **ohne `# noqa`**, ohne Änderung der `include_router`-Reihenfolge.

### Korrektur meiner Einschätzung

Meine Warnung in **§3.3** („`ruff --fix`/Cleanup = eigenes 🔴-Großprojekt") war **zu konservativ**. Der `X as X`-Weg — den ich in dieser Session selbst in `archon/routers/chat.py:56-61` für die F2-Re-Exports benutzt habe — skaliert auch auf `main.py`. Option **A1** war in unter 5 Minuten beherrschbar. Streiche die Empfehlung „A4" in §3.4 zugunsten von A1, sofern der Cleanup committet und grün ist.

### Von mir lesend verifiziert (ohne Shell, um `task-235` nicht zu stören)

Die Branch-Ref `C:\.Antigravity-projekte\AgenticOS-2026\.git\refs\heads\s1-god-objects` steht noch auf **`cbdeccb4`** → der Cleanup ist **uncommittet** und liegt als Working-Tree-Änderung über meinem Commit 2.

Erhalten (Zeilennummern nach dem Umbau):

- `main.py:2916-2928` — kompletter F2-Wiring-Block (`_rbac_mod`, `_auth_mod`, `_rbac_configure`, `_guards_configure` mit allen 4 Original-Guards)
- `main.py:2920` `_rbac_configure(require_admin=require_admin)` · `:2930` `except Exception as _e_rbac`
- `main.py:2579`–`:3226` — **alle** `_ROUTER_LOAD_ERRORS.append(...)` in ihren `except`-Blöcken, inkl. `operations_api:` bei `:2587`
- `main.py:3229` `_assert_router_health()` · `:3258` `_STARTUP_HOOKS.insert(0, ...)` · `:614` `_FAIL_FAST_HOOKS`
- `.importlinter` `ignore_imports =` leer, F5-Header `0/0/0`
- `tests/test_import_layer_contracts.py:222` `assert len(pairs) == 0`, Negativprobe mit synthetischem `allowed`
- `archon/routers/chat.py:57-61` Re-Exports + `:1400` `router.post("/api/v1/tools/image_generate")(...)`
- `backend/operations_api.py:25/27/863` → `backend.operations_constants` / `backend.rbac_guards`

### Drei Pflichtprüfungen, BEVOR der 3. Commit entsteht

1. **Import-Smoke nach dem pytest wiederholen.** Die Full-Suite prüft das F2-Wiring **nicht direkt**: die meisten RBAC-Tests patchen `archon.routers._rbac._checker` und rufen `operations_*`-Handler auf, nicht `backend.rbac_guards`. Nur dieser Smoke deckt einen stillen RBAC-Ausfall ab:
   ```python
   import sys, os
   sys.path.insert(0, r"C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects")
   os.environ["ARCHON_DATA_DIR"] = r"C:\Users\micha\AppData\Local\Temp\opencode\archon-postcleanup"
   os.environ.setdefault("ARCHON_AUDIT_HMAC_KEY", "probe-only-" + "a" * 64)
   import main
   from backend import rbac_guards, image_generate as ig
   from archon.routers import chat
   assert rbac_guards.is_configured(), "F2-Wiring verloren!"
   assert chat.api_tool_image_generate is ig.api_tool_image_generate
   paths = sorted(main.app.openapi()["paths"])
   assert len(paths) == 799, f"Pfade: {len(paths)} (Referenz cbdeccb4 = 799)"
   for p in ["/api/v1/tools/image_generate", "/api/operations/esign/submissions", "/api/operations/org-chart"]:
       assert p in paths, p
   assert not main._ROUTER_LOAD_ERRORS, main._ROUTER_LOAD_ERRORS
   ```
2. **Router-Reihenfolge / Pfad-Präzedenz gegen `cbdeccb4` vergleichen.** `_ROUTER_LOAD_ERRORS` wanderte von `:130` auf `:592`, `include_router` von `:2753` auf `:1429` ff. — die Imports wurden um ~1300 Zeilen verschoben. Bericht sagt „Reihenfolge unverändert", aber `test_orange_b_f14.py::test_no_duplicate_route_registrations` und die 799 Pfade sollten es belegen.
3. **Commit-Hygiene**: `git restore -- config/kanban_meta.json` (Test-Rauschen), `ARCHON_TEST_DB_ISOLATION=1`, kein `--no-verify`, **kein Push** (der Nutzer pusht selbst). Commit-Reihenfolge dann: `04e3cc7d` → `cbdeccb4` → `<chore(ruff)>`.

### Für den frischen Agenten

- **Nicht** im Worktree schreiben, solange `task-235` läuft oder Antigravity dort noch arbeitet.
- Wenn der pytest grün ist und die drei Prüfungen bestehen, ist §3 **erledigt**; übrig bleiben nur noch §4 (Artefakte), §5 (Flaky), §6 (Kostenbug) und der Push selbst.
- Die „erste Frage an den Nutzer" am Ende von §10 ist damit **hinfällig** — A1 ist faktisch gewählt. Frag stattdessen, ob der 3. Commit jetzt gemacht werden soll.

---

## 12. FINALER STAND (nach Commit `ee18373a`) — alle Prüfungen grün

§11 beschreibt den Zwischenstand („noch nicht committet"); **dieser Abschnitt ist der aktuelle**.

| | |
|---|---|
| HEAD | **`ee18373a`** — `chore(ruff): A1-Cleanup aller 572 Alt-Funde im PR-Range (0 noqa, Re-Exports erhalten)` |
| Kette | `04e3cc7d` → `cbdeccb4` → `ee18373a` |
| Working Tree | **sauber** (kein `M`, kein `??`) |
| Push | **keiner** — der Nutzer pusht selbst |

**Gate von Antigravity** (vom Nutzer übermittelt): Ruff PR-Range 29/29 = 0, Ruff kritisch = 0, `lint-imports` 2 kept / 0 broken, mypy 29/29 = 0, compileall 0, `audit_secrets --all` 7108 Dateien / 0 Funde, **`pytest tests/ -q` = 2355 passed / 20 skipped / 0 failed (3:00)**.

**Unabhängige Nachprüfung (Hy4, nach dem Commit, ein sequenzieller Shell-Lauf):**
- `git log -4` → `ee18373a`, `cbdeccb4`, `04e3cc7d`, `b9be7d37`; `git status --short` leer
- Ruff PR-Range `2ee92706..HEAD` (29 `.py`): **All checks passed!** EXIT 0
- Ruff `E9,F63,F7,F82`: **All checks passed!** EXIT 0
- `lint-imports --no-logo`: **2 kept / 0 broken**, 0 ignored imports (287 Dateien, 992 Dependencies), EXIT 0
- **Import-Smoke (die in §11 markierte Lücke ist geschlossen)**: `rbac_guards.is_configured() = True`, `ops_pkg.router is oa.router = True`, `chat.api_tool_image_generate is ig.api_tool_image_generate = True`, `chat.ImageGenerateToolRequest is ig.ImageGenerateToolRequest = True`, `main.ImageGenerateToolRequest` / `main.api_tool_image_generate` vorhanden, **799 OpenAPI-Pfade = exakt Referenz `cbdeccb4`** inkl. `/api/v1/tools/image_generate` und allen Esign-/Org-/Keys-/PBD-Pfaden, `_ROUTER_LOAD_ERRORS = []`, Negativprobe → `RuntimeError`, `ARCHON_ALLOW_BROKEN_ROUTERS=true` → kein Abbruch. **SMOKE_OK, EXIT 0.**
- Branch-Diff `2ee92706..HEAD`: 32 Dateien, +2153 / −1608.

**Damit ist §3 (CI-Ratchet) erledigt.** Alle drei Pflichtprüfungen aus §11 sind bestanden — insbesondere der direkte Wiring-Smoke, den die 2355 Tests nicht abdecken. §4 (Artefakte im Hauptbaum), §5 (Flaky-Test), §6 (Kostenpfad-Bug) bleiben bewusst **DELEGATED**.

**Offen bleibt NUR:** die Push-Freigabe durch den Nutzer sowie die drei DELEGATED-Punkte (§4 Artefakte, §5 Flaky-Test, §6 Kostenbug). Der Branch ist aus Sicht aller lokalen Gates **bereit**. **Kein Agent pusht.**

---

## 13. Artefakt-Bereinigung im Hauptbaum — ERLEDIGT (§4 damit abgeschlossen)

Ausgeführt am 25.11. im **Hauptbaum** (`C:\.Antigravity-projekte\AgenticOS-2026`, Branch `main`, HEAD `2ee92706`). **Reversibel: nichts gelöscht**, kein `git add`, kein Commit, kein Push.

**Neues Archiv:** `audit_reports/_archiv_2026-11-25_artefakte/` mit `README.md` (Gründe + `Copy-Item`-Rückgängig-Befehle).

Verschobene 6 Artefakte:

| Von | Nach | Grund |
|---|---|---|
| `.importlinter` | `importlinter.ALT-root_package-SINGULAR` | Alt-Config mit dem Singular-Fehler; gültige Config liegt committet im Worktree (`ee18373a`) |
| `audit_reports/mypy_full_stdout.txt` | gleichnamig | ~23 KB veraltetes Scan-Log, kein Gate-Ergebnis |
| `audit_reports/tool_scans/` | `tool_scans/` | 10 Logs / ~9 MB, teils `"NOT EXECUTED"`, nicht als Ergebnisse zählen |
| `scripts/run_fast_scans.ps1` | gleichnamig | lokale Dev-Toolchain, relative `.venv`-Pfade |
| `scripts/run_remaining_scans.ps1` | gleichnamig | dto. |
| `scripts/run_static_toolchain.ps1` | gleichnamig | dto. |

**Referenz-Check:** Die 3 Skripte werden nur in **historischen Docs** zitiert (`ANALYSIS_GOD_OBJECTS.md:152/268/612`, `fix_doc_toolchain.md:26`, `HANDOFF_ANTIGRAVITY_2026-11-25.md:3`, diesem Dokument `:145`) — **keine aktiven Code-Referenzen**. Zeitdokumente blieben unangetastet (`INVARIANTS §4`).

**Bewusst NICHT angetastet:**
- Die 5 Dokumentations-`??` (`HANDOFF_GOD_OBJECTS_F4F3`, `HANDOFF_GOD_OBJECTS_FINAL`, dieses Dokument, `INVARIANTS.md`, `S1_IMPORT_DEBT_DETAIL.md`) — Zeitdokumente, gehören nicht in Worktree-Commits (Handoff §1).
- `audit_reports/fix_d2_mypy.md:90-91` — zitiert `ARCHON_OS_API_KEY_SALT_<REDACTED>`. **Orchestrator-Entscheidung** (Handoff §7: „Doku vs. Scanner-Regex"), nicht angefasst.

**Wichtiger Scanner-Befund:** `scripts/audit_secrets.py:146` nutzt `git ls-files` → `audit_secrets --all` prüft **ausschließlich getrackte** Dateien. Alle `??`-Artefakte/Docs wurden **nie** gescannt; die „0 Funde"-Meldungen bezogen sich nur auf getrackte Dateien. **Vor jedem `git add` dieser Dokumente muss das Zitat bewusst bewertet werden.**

**`git status` Hauptbaum nach der Bereinigung:** 7 `??` (5 Docs + `fix_d2_mypy.md` + das Archiv-Verzeichnis selbst) und 2 vorbestehende `M`:
- `audit_reports/HANDOFF_HY4_DEBUG_2026-11-25.md`
- `audit_reports/PROPOSAL_3b_MODULARITY.md`

Die zwei `M` sind **kein neuer Befund**: es sind Hy4's Doku-Korrekturen aus der Analyse-Phase (`root_packages`-Korrektur, §4b S1-Status, pip-audit-„kein Bump"), bereits beim ersten Read dieser Session vorhanden, vorbestehend laut `HANDOFF §0.1` („Working Tree dirty: ~180 `M` + ~40 `??`"). Sie gehören zu `main @ 2ee92706`, **nicht** zu `s1-god-objects`, und wurden bewusst **weder restauriert noch committet**.

**Worktree unverändert:** `s1-god-objects @ ee18373a`, Working Tree **sauber**.

**Damit verbleiben nur noch:** Push-Freigabe (Nutzer), §5 Flaky-Test, §6 Kostenpfad-Bug, und die Owner-Entscheidung zum Secret-Zitat. **Kein Agent pusht.**

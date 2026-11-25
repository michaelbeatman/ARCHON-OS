# HANDOFF — S2–S4: Monolithen-Zerlegung (für eine frische Session)

**Erstellt:** 25.11.2026 · **Für:** Agent mit frischem Kontext (z. B. Gemini neon)
**Ausgangsstand:** Branch `s1-god-objects`, HEAD **`ee18373a`**, Working Tree sauber, **KEIN Push**.
**Neues Projekt.** Der heutige Auftrag (S1 = Import-Schuld `23 → 0`) ist **abgeschlossen**; dieses Dokument beschreibt das **nächste, eigene** Projekt.

---

## 0. Für den frischen Kontext — in 90 Sekunden

| | |
|---|---|
| Hauptbaum | `C:\.Antigravity-projekte\AgenticOS-2026` · `main` · HEAD `2ee92706` · kein Push |
| Bisheriger Worktree | `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects` · `s1-god-objects` · `ee18373a` |
| **Empfehlung** | **EIGENER neuer Worktree** für S2–S4 (`INVARIANTS §4.4`: kein paralleles Schreiben auf demselben Worktree) |
| Venvs | **NUR im Hauptbaum**: `.venv\Scripts` (Py 3.12: ruff, mypy, lint-imports, bandit, pip-audit, radon, vulture, coverage) · `.ci_venv\Scripts` (Py 3.11: pytest, python). Im Worktree gibt es **keine** Venvs → immer **absolute Pfade**, `cwd = Worktree`. |
| Erreichter Stand | Import-Paare `backend → archon.routers` **0**, `ignore_imports` leer, Ruff PR-Range **0 Funde**, mypy 410/0, pytest **2355/20/0**, lint-imports 2 kept/0 broken, bandit/pip-audit CI-Aufrufe EXIT 0 |

**Auftrag dieser Session: S2–S4 = Monolithen zerlegen.** Nicht Import-Schuld (fertig), nicht Artefakte (bereinigt).

**WICHTIG — Begriffs-Falle:** Branch, Dossier und Handoffs heißen alle „God-Objects", aber die heutige Arbeitsliste war **nur S1 (F1–F5)**. `HANDOFF_HY4_DEBUG §5.7` sagt explizit: *„God-Objects/Importzyklen nicht in diesen Lauf ziehen — eigenes Projekt mit Worktree."* S2–S4 waren **nie** im heutigen Auftrag. Den heutigen Stand nicht als „unfertig" behandeln.

---

## 1. Korrektur einer häufigen Fehlannahme: Ladezeit

**„Viele kleine Dateien → kürzere Ladezeit, weil nur geladen wird, was aufgerufen wird" — so stimmt das bei Python/FastAPI nicht.**

- Python importiert Module **beim Prozessstart**, nicht pro Request. `main.py` lädt ~75 Router per `include_router` **einmal** beim Import. Ein Split in 14 Router (heute, F4) hat die Startzeit **nicht** verkleinert, nur die Registrierung umsortiert.
- Mehr Module = mehr `import`-Statements, mehr Datei-/Stat-Calls → Kaltstart wird tendenziell **etwas langsamer**, nicht schneller.
- Was tatsächlich **Ladezeit verteilt**, sind **Lazy Imports** — und die hat das Repo bereits: ~607 lazy `backend`-Imports in `archon/**` (`ANALYSIS_GOD_OBJECTS.md §1.3`), z. B. `_get_ops_deps()` in `operations_org.py:73-82`, der `backend.operations_api` erst zur Laufzeit lädt. Das ist unabhängig von der Dateigröße.
- **Was durch kleine Dateien wirklich flüssiger wird:** die **Edit-/Test-/Review-Schleife** — inkrementelles `ruff`/`mypy` auf geänderte Dateien (das Changed-Files-Ratchet `ci.yml:501-525`), kleinere Diffs, weniger Merge-Konflikte, gezieltere Test-Selektion, menschliche Navigation. Und der **Blast-Radius** sinkt (`INVARIANTS §6`). Nicht die Request-Latenz.

Diese Korrektur gehört ins Handoff, damit die neue Session nicht mit einer falschen Erfolgsmetrik startet.

---

## 2. Warum S1 vor S2 — die Reihenfolge ist technisch erzwungen

`ANALYSIS_GOD_OBJECTS.md §2.3` / `PROPOSAL_3b`: `main.py` lädt 75 Router, **wird aber selbst von ≥27 Produktionsmodulen zurück importiert** (≥90 Stellen, ~50 `app_main.*`-Symbole): Persistenz-Helfer, Pfadkonstanten, Gateway/Hermes, Auth/Decisions, Export/Dispatch, Quickchat.

> *„Ohne diesen Schritt erzeugt S2 genau die Import-Order-Probleme, die S1 verhindern soll. Das ist der Grund, warum S1 vor S2 stehen muss."*

**Wir haben heute also genau in der richtigen Reihenfolge gearbeitet**: erst die Layergrenzen klären (23 → 0 Paare), dann darf `main.py` angefasst werden. Ein „gleich so machen" hätte den Zyklus in den Split hineingetragen.

Zusätzliche Gründe, warum es nicht „von Anfang an" passiert ist:
1. **Gewachsenes Produktivsystem** bei ~60 % V1.0 (`INVARIANTS §0`), laufender Betrieb, täglich neue Features (ERP). Es gab bereits eine Teil-Modularisierung (`main.py` „AUSGELAGERTE ROUTER", 75 `include_router`) — F4 heute war der nächste Schritt davon, nicht der erste.
2. **Risiko**: `ANALYSIS_GOD_OBJECTS.md` D2 stuft `main.py` als 🔴 **höchstes Risiko** ein (W0–W5-gehärtete Pfade: Lifespan-Fail-Fast, `/livez`/`/readyz`, RBAC, Audit-HMAC, Auth-Bind). Dokumentiertes Schadensbild: „Router-404 bei healthy `/health`" oder fail-open. Ohne Characterization-Tests ①–⑤ ist ein Split „Blindflug".
3. **Tempo-Vorgabe** des Nutzers heute: „2 Gates statt der ursprünglich 5", „heute abschließen, keine neuen Analysen starten".
4. **Produktivschutz**: jeder Split berührt laufende Container / Login (siehe `INCIDENT_2026-11-25_LOGIN_OUTAGE.md`).

---

## 3. „Schreibfest" — deine wichtigste Intuition, und sie ist richtig

**Ja: das ist nicht nur Best Practice, sondern ein echtes Sicherheitsfeature.** Aber es entsteht **nicht durch Dateigröße**, sondern durch **Tests + Ownership + Negativproben**. `INVARIANTS.md §0` formuliert es exakt:

> *„Die Gefahr ist: Vibe-Code **vereinfacht bewährten Code**, weil er die Begründung nicht kennt. Ein Kommentar schützt dagegen nicht — er wird mit ‚bereinigt'. Was schützt, ist **ein Test, der den Grund festnagelt**, plus ein **zweiter Blick**."*

Der Mechanismus, der bewährten Code „schreibfest" macht:

| Baustein | Wo | Wirkung |
|---|---|---|
| **Characterization-Test VOR jedem Split** | `ANALYSIS §4`, F1a/A1/A2/F4 Praxis | Nagelt das Verhalten fest, bevor sich die Datei ändert. Gold-Output bleibt byte-identisch. |
| **Ownership (Positiv-/Negativliste)** | `INVARIANTS §4.1`, `fix_*`-Modell | „Außerhalb Ownership = dokumentieren, nicht ändern". Verhindert parallele Zerstörung. |
| **Negativprobe gegen die echte Logik** | `INVARIANTS §4.5` | Ein Test, der **nicht** rot werden kann, ist ein Theater-Gate. |
| **Zweiter Blick durch frische Instanz** | `INVARIANTS §4.6` | Dieses Repo hat jeden kritischen Fund durch eine unabhängige Instanz gefunden, nie durch den Autor des Fixes. |
| **Ratchet / Changed-Files-Gate** | `ci.yml:501-525`, `INVARIANTS #1/#10` | Jede neue Datei landet sofort im Gate; Altschuld darf nur sinken. |
| **`tests/test_unbound_calls.py`** | `INVARIANTS §1` | Schützt gegen eine ganze **Fehlerklasse** (`NameError`), nicht gegen einen Einzelfall. |
| **Invarianten-Katalog #1–#12** | `INVARIANTS §2` | 6 erzwungen, 4 gelebt, 4 offen. |

**Kleine Dateien ergänzen das um einen kleineren Blast-Radius** (`INVARIANTS §6`: *„100 % Schutz gibt es nicht. Aber der Blast-Radius sinkt, weil jede neue Datei sofort im Ratchet, im Changed-Files-Gate und in der Full-Suite landet."*). Beides zusammen — kleine Einheiten **plus** festgenagelte Verträge — ist der eigentliche Gewinn.

**Die 8 Vereinfachungs-Fallen, die ein Split treffen würde** (`INVARIANTS §3`, **vor jeder Änderung lesen**): `set_decision_factory`, `_cost_usd = None` (D12), leerer `created_by` → 403, `_FALLBACK_MODEL_PRICES_PER_1M`, 125 Re-Exports (heute entfernt, aber als Lehre), `allow_indirect_imports`, `test_unbound_calls.py`, `core_dispatcher`-Doppelimport.

---

## 4. Zielobjekte und Reihenfolge (aus `ANALYSIS_GOD_OBJECTS.md`)

### D2 — `main.py` 🔴 (2919 Zeilen) — **S2, zuerst**

**Stabile Contracts, die erhalten bleiben MÜSSEN** (D2 §295):
① Registrierungsreihenfolge der 75 Router · ② je Router `try/except` + `_ROUTER_LOAD_ERRORS.append(...)` · ③ `_rbac_configure(require_admin=...)` **vor** den Routern · ④ `_assert_router_health()` fail-closed inkl. `ARCHON_ALLOW_BROKEN_ROUTERS`-Opt-Out · ⑤ `_FAIL_FAST_HOOKS`-Menge + `raise` statt Log im Lifespan · ⑥ `insert(0, …)`-Reihenfolge der 5 Hooks · ⑦ `_SHUTDOWN_HOOKS` in `reversed()` · ⑧ `app`, `auth_service`, `core_dispatcher`, `get_hud_telemetry`, `detect_container_port`, `_request_has_service_token` · ⑨ die ~50 `app_main.*`-Symbole.

**Fehlende Characterization-Tests (VOR Schritt 2a bauen):** ① `/livez` ↔ `_FAIL_FAST_HOOKS`/`_AUDIT_COMPROMISED` verdrahtet · ② Shutdown-Timeout / `reversed()`-Reihenfolge / Graceful-Drain · ③ n8n-Startup-Hook → `/readyz`-Degradation · ④ Router-Reihenfolge + `_rbac.configure()` als Verhaltensassertion (bisher nur Source-Text, `test_rbac_admin_routes_paket2.py:364-371`) · ⑤ `HealingAttemptPayload` / `request.state.hitl_apply_patch`.

**Reihenfolge:** **2a** zuerst die ~50 `app_main.*`-Symbole nach `archon/core/runtime.py` / `archon/services/app_state.py` heben **und alle ≥90 Rückwärts-Imports umstellen** (1 Commit, Full-Gate) → **2b** Lifespan → `archon/services/lifecycle.py` → **2c** Middleware/Auth → `archon/middleware/` → **2d** Router-Registrierung → `archon/routers/__init__.py`. **Ziel `< 300` Zeilen erst am Ende**, nicht als erstes Kriterium.

**Achtung:** Antigravity's Ruff-Cleanup (`ee18373a`) hat die Imports an den Dateianfang gezogen und die Re-Exports per `X as X` erhalten. `_ROUTER_LOAD_ERRORS` liegt jetzt `:592` (früher `:130`), `_assert_router_health()` `:3229`, `_guards_configure`-Block `:2916-2928`. **Zeilennummern vor jedem Split neu verifizieren.**

### D3 — `backend/operations_api.py` 🟠 (3829 Zeilen) — **S3**

42 eigene Endpunkte (Kanban, Esign …), `router = APIRouter(prefix="/api/operations")` bei `:81`. Die 14 Unter-Router sind **bereits** ausgelagert (`archon/routers/operations/__init__.py`, F4). Verbleibend:
- `_get_kanban_connection` (~45 Referenzstellen über 4 Schichten), `_load_kanban_meta`, `_execute_kanban_task_async`, `_get_active_kanban_db_path`, `_resolve_task_obsidian_rel`, `_build_kanban_obsidian_map`, `_PROFILES_MAP_CACHE`, `PROFILES_FILE`, `WORKSPACE_DIR`, `_load_profiles_map`, `_get_fallback_avatar`, `KANBAN_DB_PATH`, `VALID_KANBAN_STATUSES`, `TaskStatusUpdateRequest`, `QualityReviewRequest/Verdict`, `update_task_status`.
- **`_get_ops_deps()` (`operations_org.py:73-82`) ist ein positional 6-Tupel** — der fragilste Contract im Cluster; 10 Aufrufstellen. Vor S3 einfrieren oder durch benanntes Objekt ersetzen.
- **S-Tests brechen bei JEDEM Split**, auch bei identischem Verhalten (`test_fix_w3_b_performance.py`, `test_orange_b_f14.py`, `test_workflow_dag_e2e.py:247-258`, `test_reaudit_stage7.py:63`). Vorher durch G7 auf Verhaltensassertions umstellen.
- Fehlende Golden-Tests: `_execute_kanban_task_inner` (CC 118), `get_projects_overview` (CC 118), `_resolve_task_obsidian_rel` (CC 65), Undo-Store-TTL, `_get_ops_deps()`-Reihenfolge.

### D1 — `backend/workflow_dag_runner.py` CC 246 🟠 — **vor S3, eigener Schritt**

`default_agent_node_executor` (`:1211`) mit 10 Verantwortungs-Clustern. **Nur 4 direkte Verhaltenstests** (`test_stage1_stage3_hardening_and_bus.py`), `test_workflow_dag_e2e.py` umgeht den Executor komplett via `executor_fn=mock_exec`. Vor jedem Cluster: Verzweigungsmatrix mit Golden-Output. Dann **reine Extraktion, keine Logikänderung**, ein Cluster pro Commit. Facade `default_agent_node_executor` muss importierbar bleiben.

### D4 — `scripts/patches/hermes_telegram_adapter.py` ⚫ (10290 Zeilen) — **S4, zuletzt**

**Nicht lokal importierbar** (`gateway.*`, `hermes_cli.*` nur im Image). `register(ctx)` existiert bereits (`:11212-11232`, 17 Keywords). Mount `docker-compose.yml:405` auf `/opt/hermes/plugins/platforms/telegram/adapter.py:ro`. **Zwei widersprüchliche Digests**: `docker-compose.yml:374/437` = `sha256:276d4468…` (mit Adapter-Mount), `docker-compose.hermes.yml:32/75` = `sha256:e6d81ae5…` (ohne). 8 Methoden Rang F, `_handle_callback_query` CC 158 / 765 Zeilen. Nur `ci.yml:166-167` `compileall` prüft Syntax; `test_telegram_gate_meldung.py` parst per `ast`. → `adapter.py` als **dünner Re-Export** erhalten, Logik nach `scripts/patches/telegram/*.py` **mit `gateway.*`-Mock-Gerüst**, Digest-Kopplungs-Gate.

### D5 — `core_dispatcher.py` (3583 Zeilen) — **BACKLOG, NICHT nach Größe splitten**

Mutable Modul-Globals werden von Routern zur Laufzeit überschrieben (`CATEGORIZED_FRAMEWORKS`, `MAX_CONCURRENT_AGENT_TASKS`, `_DISPATCHER_HTTP_CLIENTS`). Erst in einen expliziten State-Store überführen, Source-Text-Tests auf Verhalten umstellen (`test_fix_w3_b_performance.py:51,52,125,128-131`, `test_fix_w2_a_security.py:55`). `test_show_hn_blockers.py:55` ist `blocked` und **nicht im Ownership** → eskalieren, nicht löschen/skippen.

---

## 5. Zwingende Regeln (aus `HANDOFF_HY4_DEBUG §2`, `INVARIANTS §4`, `AGENTS.md`)

1. **1 Schritt = 1 Commit = 1 Full-Gate.** Kein Schritt ohne grünes Gate.
2. **`ARCHON_DATA_DIR=<temp>`**, nie `./data`; für pytest zusätzlich **`ARCHON_TEST_DB_ISOLATION=1`** (`tests/conftest.py:60-64` erzeugt ein frisches `mkdtemp`). Empfehlung `C:\Users\micha\AppData\Local\Temp\opencode\archon-s2-<zweck>`.
3. **`git restore -- config/kanban_meta.json` vor JEDEM Commit** (Test-Rauschen `tpl_unit`).
4. **Kein `--no-verify`**, **kein Push ohne Freigabe**, **NEVER_DO** (kein Coroutine-Replay, keine PostgreSQL-Migration), `./data`/`.env`/Audit-Kette/laufende Container nicht antasten.
5. **Nicht vereinfachen ohne Test** (`INVARIANTS §3`). Rote/obsolete Tests werden **eskaliert, nicht gelöscht, geskippt oder umgeschrieben** (`fix_w3_d_trajectory_dag.md:121-127`).
6. **Jeder neue Test braucht eine Negativprobe gegen die echte Logik** — gemeinsame Hilfsfunktionen nutzen, kein hartcodiertes Snippet.
7. **Zweiter Blick ist Pflicht**: frische, unabhängige Instanz prüft den Fix.
8. **CI-Ratchet-Simulation vor dem Commit**: `ruff --select E,F,I --ignore E501 <geänderte .py>` (dateigranular!). Vorbestehende Funde → separater `chore(ruff)`-Commit, kein `noqa`, kein Mix. A/B „0 neue Funde" dokumentieren.
9. **Historische `audit_reports/*.md` sind Zeitdokumente** — nicht editieren. Neue Erkenntnisse in einen **neuen** Report.
10. **Ownership**: pro Datei genau ein Owner; Kollisionen (z. B. `delegation.py` zwischen G2 und G5) sequenziell lösen, nie parallel.

---

## 6. Full-Gate (exakte Befehle, `cwd = Worktree`)

```powershell
$V = 'C:\.Antigravity-projekte\AgenticOS-2026\.venv\Scripts'
$C = 'C:\.Antigravity-projekte\AgenticOS-2026\.ci_venv\Scripts'
$env:ARCHON_TEST_DB_ISOLATION = '1'
$env:ARCHON_DATA_DIR = 'C:\Users\micha\AppData\Local\Temp\opencode\archon-s2'

$F = (git diff --name-only --diff-filter=ACMR HEAD^ HEAD -- '*.py' '*.pyi')
& "$V\ruff.exe" check --select E,F,I --ignore E501 $F --output-format=concise
& "$V\lint-imports.exe" --no-logo                      # 2 kept / 0 broken / 0 ignored
& "$V\mypy.exe" --config-file mypy.ini $F              # geaenderte
& "$V\mypy.exe" --config-file mypy.ini --disallow-untyped-defs <NEUE_MODULE>
& "$V\mypy.exe" --config-file mypy.ini archon backend main.py core_dispatcher.py scripts utils
& "$C\python.exe" -m pytest tests/ -q                  # 2355 passed / 20 skipped / 0 failed
& "$C\python.exe" -m compileall -q archon backend scripts tools utils core_dispatcher.py main.py
& "$C\python.exe" scripts/audit_secrets.py --all       # nur GETRACKTE Dateien (git ls-files!)
& "$V\bandit.exe" -q -lll -r main.py core_dispatcher.py backend archon -x tests,scripts
& "$V\pip-audit.exe" -r requirements.lock.txt
```

**Zusätzlich nach JEDEM `main.py`-Split (Pflicht-Smoke)** — die Full-Suite prüft das F2-Wiring nicht direkt, weil RBAC-Tests `_rbac._checker` patchen:

```python
import sys, os
sys.path.insert(0, r"<WORKTREE>")
os.environ["ARCHON_DATA_DIR"] = r"C:\Users\micha\AppData\Local\Temp\opencode\archon-s2-smoke"
os.environ.setdefault("ARCHON_AUDIT_HMAC_KEY", "probe-only-" + "a" * 64)
import main
from backend import rbac_guards, operations_api as oa
from archon.routers import operations as ops_pkg, chat
from backend import image_generate as ig
assert rbac_guards.is_configured(), "F2-Wiring verloren"
assert ops_pkg.router is oa.router
assert chat.api_tool_image_generate is ig.api_tool_image_generate
paths = sorted(main.app.openapi()["paths"])
assert len(paths) == 799, f"Pfade: {len(paths)} (Referenz ee18373a = 799)"
assert not main._ROUTER_LOAD_ERRORS
main._ROUTER_LOAD_ERRORS.append("NEGATIVPROBE: broken router")
try:
    main._assert_router_health()
except RuntimeError:
    pass
else:
    raise AssertionError("Fail-closed fehlt")
finally:
    main._ROUTER_LOAD_ERRORS.clear()
os.environ["ARCHON_ALLOW_BROKEN_ROUTERS"] = "true"
main._ROUTER_LOAD_ERRORS.append("NEGATIVPROBE: broken router")
try:
    main._assert_router_health()
finally:
    main._ROUTER_LOAD_ERRORS.clear()
```

---

## 7. Fallen aus der heutigen Session (nicht wiederholen)

1. **UTF-8-BOM**: `[System.IO.File]::WriteAllText` mit `[Text.Encoding]::UTF8` kann ein BOM erzeugen → 8 pytest-Fehler durch `ast.parse`-`SyntaxError U+FEFF`. Byte-Level prüfen; BOM-frei schreiben (`[System.Text.UTF8Encoding]::new($false, $true)`).
2. **Parallele `pwsh.exe`-Spawns** → `Zugriff verweigert (os error 5)`. Shell-Calls **sequenziell in EINEM Prozess**; lesende Subagenten parallel.
3. **PowerShell-Quoting**: `mypy … (Join-Path …),(Join-Path …)` ohne Array-Klammer → `Duplicate module named "__main__"`. Immer `$mods = @(…)`.
4. **Ratchet dateigranular**: ein einziges neues `from … import …` in `main.py` erzeugt einen neuen E402. `X as X` für Re-Exports; isort will `as`-Importe in **getrennten Statements** und **eine Leerzeile vor einem Kommentar**.
5. **Source-Text-Tests brechen bei Modul-Verschiebungen**: `test_reaudit_stage13.py:58`, `test_audit_p2_performance.py:15-19`, `test_fix_w3_b_performance.py`, `test_reaudit_stage7.py:68`, `test_audit_p1_governance.py:16`. **Vor jedem Move Referenzsuche** (diesmal: 125 Re-Exports, 28 aktive Test-Referenzen).
6. **FastAPI** kapselt `include_router` in `_IncludedRouter` (`.path` leer) → Routen über `app.openapi()["paths"]` prüfen, nicht `app.routes`.
7. **`mypy .` crasht** an `hermes-webui` (ungültiger Paketname) → Full-Run über CI-Pfade.
8. **`audit_secrets --all` prüft nur `git ls-files`** → untracked Dateien werden nie gescannt.
9. **Shell-Scanner** lehnt sehr komplexe Skripte mit `invalid-structure` ab → `edit`/`write`-Tool nutzen oder aufteilen.
10. **`_get_org_hierarchy_file` / `TEAMS_DEFINITION`** mussten vor F4 nach `backend/operations_constants.py` gehoben werden — sonst brechen `:944` / `:4130`. Muster: **interne Nutzungen vor dem Löschen von Re-Exports finden**.

---

## 8. Akzeptanzkriterien je Schritt

- Alle 2355 Tests grün (0 failed), Full-Gate komplett.
- Gold-/Characterization-Outputs **byte-identisch** zum Vor-Split-Stand.
- Router-Reihenfolge, `/livez`/`/readyz`/`/health` unverändert; Fail-Fast-Hooks raisen; Negativprobe mit absichtlich defektem Router → **Start bricht ab**.
- `monkeypatch.setattr(ops, "_get_kanban_connection", …)` greift weiter (Adapter/Re-Export statt Patch-Punkt-Wechsel).
- `default_agent_node_executor` weiter importierbar; CC der Facade < 20.
- Kein neuer Importzyklus; `lint-imports` 2 kept / 0 broken / 0 ignored.
- `register(ctx)` gegen Mock-`ctx` grün (S4), Mount-Pfad `:405` unverändert, Produktiv-Telegram unverändert.
- Jeder Commit: 1 Schritt, 1 Full-Gate, `config/kanban_meta.json` restauriert, kein `--no-verify`, **kein Push**.

---

## 9. Referenz-Docs (Hauptbaum `audit_reports/`)

| Dokument | Wofür |
|---|---|
| `ANALYSIS_GOD_OBJECTS.md` | **Hauptquelle**: §1 Klassen A/B/C, §2 Symbol-Graphen, §3 Dossiers D0–D6, §4 Ownership-Matrix |
| `PROPOSAL_3b_MODULARITY.md` | S1–S4, §2/§3 Gate-Regeln, §4 Freigabe |
| `INVARIANTS.md` | §2 Katalog #1–#12, §3 8 Vereinfachungs-Fallen, §4 Prozessregeln, §5 offene Arbeit |
| `HANDOFF_HY4_DEBUG_2026-11-25.md` | §2 Schutzregeln, §5.7 „God-Objects nicht in diesen Lauf", §6 Werkzeuge |
| `HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md` | Ausgangslage, Commit-Kette, §7 Offen/DELEGATED |
| `HANDOFF_GOD_OBJECTS_F4F3_2026-11-25.md` | Abschluss der Import-Schuld-Session inkl. NACHTRAG `ee18373a` |
| `FULLSCAN_BEWERTUNG_2026-11-25.md` | Aktuelle Messwerte: radon Rang-F-Blöcke, vulture 17 Treffer, Zeilenzahlen, Noten nach Dimension |
| `HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md` | §12 finaler Stand, §13 Artefakt-Bereinigung |
| `INCIDENT_2026-11-25_LOGIN_OUTAGE.md` | Warum nie `./data` |
| `domain_09.md` | H-09-2 Layergrenze, M8 mutable States |
| `.github/workflows/ci.yml` | `:496-525` Ruff-Ratchets, `:527-551` mypy, `:305/:555` pytest/coverage, `:444-452` pip-audit/bandit |
| `INVARIANTS §5` | `tests/test_invariants.py` (maschinenprüfbare #2/#3/#5/#7/#8/#9) — ** bewusst nicht gebaut, eigenes Backlog-Item** |

---

## 10. Erste Frage an den Nutzer, bevor Code angefasst wird

**Welcher Schritt zuerst:** D2/2a (`main.py` `app_main.*`-Symbole + ≥90 Rückwärts-Imports, 🔴) oder D1 (Characterization-Tests für CC 246, 🟠, geringeres Risiko)? `ANALYSIS §4` empfiehlt D2 zuerst, aber D1 liefert die Test-Infrastruktur, von der D2 profitiert.

**Unabhängig davon: eigener Worktree, und der aktuelle `s1-god-objects @ ee18373a` bleibt unverändert und wird nicht angefasst.**

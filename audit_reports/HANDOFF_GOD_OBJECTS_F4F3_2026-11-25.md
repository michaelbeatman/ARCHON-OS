# HANDOFF — God-Objects / Import-Schuld: ABSCHLUSS 25.11.2026

**Branch:** `s1-god-objects` · **Worktree:** `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects`
**HEAD:** **`cbdeccb4`** · **Working Tree sauber** · **KEIN Push.**
**Import-Schuld: 23 → 0 Paare. `ignore_imports` leer. Debt-Test `== 0`.**

---

## Commit-Kette (diese Session)

| Commit | Inhalt | Paare |
|---|---|---:|
| `04e3cc7d` | **F4+F3**: 14 `operations_*`-Router-Registrierungen nach `archon/routers/operations/__init__.py`, `main.py:2752` umgestellt, `TEAMS_DEFINITION` + `_get_org_hierarchy_file` nach `backend/operations_constants.py`, 125 Re-Exports entfernt, 2 Testdateien umgestellt | 17 → 3 |
| `cbdeccb4` | **F2+F5**: letzte 3 Paare (`_rbac` / `auth` / `chat`) getilgt, `ignore_imports` geleert, Debt-Test auf 0 | 3 → **0** |

Basis war `b9be7d37` (A2, 17 Paare). Hauptbaum `main` = `2ee92706`, unverändert, kein Push.

---

## Was genau geändert wurde

**F4/F3 (`04e3cc7d`)**
- `archon/routers/operations/__init__.py` (NEU): registriert die 14 Unter-Router 1:1 in der Reihenfolge `org → dag → prompts → receipts → sysops → dunning → finetuning → approvals → keys → emails → security → bot_screen → autonomy → pbd`. Re-exportiert **denselben** `backend.operations_api.router` — kein zweiter Router, kein doppeltes Prefix. `try/except` + `_ROUTER_LOAD_ERRORS` + `_assert_router_health()` blieben unverändert.
- `backend/operations_constants.py` (NEU): SSOT für `TEAMS_DEFINITION` und `_get_org_hierarchy_file()`; `operations_org.py` re-exportiert. `ORG_HIERARCHY_FILE` in `operations_api.py` bewusst behalten (tote Zuweisung, aber stabiler Contract).
- Eigene Esign-/Kanban-Endpunkte bleiben in `operations_api.py`. Kein Shadowing (verifiziert: kein `/esign`-Pfad und kein bare-path-parameter in den 14 Routern).
- 25 dynamische `getattr`-Referenzen (`test_rbac_admin_routes_paket2.py:87-111`) + 3 direkte (`test_fix_batch7.py`) auf `archon.routers.operations_*` umgestellt.

**F2/F5 (`cbdeccb4`)**
- `backend/rbac_guards.py` (NEU): **A1-style Registry** mit den **ORIGINAL**-Guards, verdrahtet in `main.py:3155`. `archon/routers/_rbac.py` und `auth.py` blieben **byte-identisch** → `_checker`, `configure`, `is_configured` und alle 13 Test-Patch-Ziele greifen 1:1. Fail-closed (503) bei leerer Registry = bisheriger `_checker is None`.
- `backend/image_generate.py` (NEU): `ImageGenerateToolRequest` + `api_tool_image_generate` als SSOT, eigene `_save_message_to_db`-Kopie, `api_provider` als Modulobjekt, lazy `llm_egress_guard`-Import, DB-Write bei `session_id` unverändert. `chat.py` re-exportiert explizit und re-registriert `/api/v1/tools/image_generate` auf demselben `chat.router`.
- `operations_api.py:29` → `backend.rbac_guards`; lazy `_task_creator_actor`-Import bleibt lazy, `try/except Exception: return ""` 1:1 (D14). `workflow_node_plugins.py:642` → `backend.image_generate` (weiterhin lazy). `main.py:2054/2069` blieben bewusst unverändert (F1a-Re-Export-Muster).
- `.importlinter`: `ignore_imports` leer, `allow_indirect_imports=false` (streng transitiv) beibehalten, zweiter Contract unberührt.
- `tests/test_import_layer_contracts.py`: `== 0`, F5-Schloesser in `test_linter_config_is_well_formed` + `test_every_ignored_import_actually_exists`, Negativprobe mit **synthetischem `allowed`** (beide Zweige der echten `_violations()`, nicht tautologisch). Name `test_documented_debt_is_bounded` beibehalten (historische Docs verweisen darauf).
- `tests/test_reaudit_stage13.py:58`: Source-Text-Assertion auf `backend/image_generate.py` umgestellt (F2-Folge).

---

## Finales Full-Gate (Commit 2, alle grün)

| Check | Ergebnis |
|---|---|
| `pytest tests/ -q` | **2355 passed / 20 skipped / 0 failed** (2:59) |
| `lint-imports` | **2 kept / 0 broken / 0 ignored imports** |
| `mypy --config-file mypy.ini` (geänderte) | 0 (8 Dateien) |
| `mypy --disallow-untyped-defs` (neue Module) | 0 (2 Dateien) |
| `mypy` Full-Run CI-Pfade | 0 (410 Dateien) |
| `ruff --select E,F,I --ignore E501` | A/B **0 neue Funde** |
| `compileall` | 0 |
| `audit_secrets --all` | 0 (7106 Dateien) |
| Import-Smoke | Guards verdrahtet, Re-Export-Identität, **799 OpenAPI-Pfade** inkl. `/api/v1/tools/image_generate` + `/api/operations/*` |
| Negativprobe | `_assert_router_health()` → RuntimeError; `ARCHON_ALLOW_BROKEN_ROUTERS=true` → kein Abbruch |

`ARCHON_TEST_DB_ISOLATION=1` / `ARCHON_DATA_DIR=<temp>`, `git restore -- config/kanban_meta.json` vor jedem Commit, **kein `--no-verify`**, **kein Push**.

**Unabhängiger Zweitblick** (lesend, parallel zum Gate): **keine Blocker** — 0 echte `archon.routers`-Imports in `backend/**`, kein Importzyklus, RBAC-Patch-Ziele unverändert, Route/Re-Exports/F5-Logik 1:1, `allow_indirect_imports=false` transitiv sicher.

---

## Offen / DELEGATED (unverändert aus `HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md`)

- Flaky-Test `test_dag_runner_schema_preserved_and_event_driven_recovery` (`test_stage1_stage3_hardening_and_bus.py:775-785`). In dieser Session **nicht** aufgetreten.
- `workflow_dag_runner.py:1763-1764` `NoneType += float` im Kostenpfad (`_cost_usd = None` ist Absicht, D12).
- `tests/test_invariants.py` — bewusst nicht gebaut.
- Artefakt-Bereinigung **vor Push**: 6 `??`-Artefakte im Hauptbaum (`.importlinter` Alt-Config, `tool_scans/`, `mypy_full_stdout.txt`, 3× `run_*scans.ps1`), `fix_d2_mypy.md`-Secret-Zitat.
- **Kein Push.** Beim ersten Push greift `ci.yml:501-525` (Changed-Files-Ratchet). Alle in dieser Session geänderten `.py` sind unter `--select E,F,I --ignore E501` **0 neue Funde**; vorbestehende Funde in `main.py` (513) / `operations_api.py` (37) sind Legacy und wurden per A/B dokumentiert, nicht bereinigt.

---

## Bekannte Fallen (für künftige Vibe-Sessions)

1. **BOM**: `[System.IO.File]::WriteAllText` mit `[Text.Encoding]::UTF8` kann ein UTF-8-BOM erzeugen → 8 pytest-Fehler durch `ast.parse`-`SyntaxError U+FEFF`. Alle angefassten Dateien sind BOM-frei. Byte-Level prüfen.
2. **Venvs** liegen NUR im Hauptbaum (`.venv` = Py 3.12 für ruff/mypy/lint-imports, `.ci_venv` = Py 3.11 für pytest). Gates mit absoluten Pfaden bei `cwd=Worktree`.
3. **Parallele `pwsh.exe`-Spawns** schlagen mit os error 5 fehl → Shell-Calls sequenziell in EINEM Prozess, Zweitblick rein lesend.
4. **CI-Ratchet ist dateigranular**: ein zusätzliches `from ... import ...` in `main.py` erzeugt einen neuen E402 → Re-Export in `chat.py` nutzen. `as`-Selbstalias gegen F401, und eine **Leerzeile vor dem Kommentar** gegen I001.
5. **`mypy --disallow-untyped-defs`** gilt für neue Module → alle Defs annotieren. PowerShell-Quoting: immer `$newMods = @(...)` bilden, sonst `Duplicate module named "__main__"`.
6. **Source-Text-Tests** (`test_reaudit_stage13.py`, `test_audit_p2_performance.py`) brechen bei Modul-Verschiebungen → Referenzsuche VOR dem Move.
7. **Kosmetisch, bewusst nicht geändert**: `backend/operations_constants.py:13` nennt `operations_api.py:87`; korrekt wäre `:88`. Reiner Kommentar.

Ausgangslage und vollständige Analyse: `audit_reports/HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md`, `ANALYSIS_GOD_OBJECTS.md`, `INVARIANTS.md`, `S1_IMPORT_DEBT_DETAIL.md`.

---

## NACHTRAG 25.11. — dritter Commit (Ruff-Cleanup), HEAD `ee18373a`

Der Abschnitt „vorbestehende Ruff-Funde" oben ist **überholt**: Antigravity hat parallel im selben Worktree alle **572** Alt-Funde der PR-Range (`2ee92706..HEAD`, 29 `.py`-Dateien) auf **0** bereinigt — geschützte `app_main.*`-Re-Exports per `X as X` erhalten, 25 tote Re-Exports entfernt, Imports an den Dateianfang gezogen, **0 `# noqa`**, `include_router`-Reihenfolge unverändert. Meine Einschätzung, das sei ein eigenes 🔴-Großprojekt, war zu konservativ.

**Neuer HEAD: `ee18373a`** — `chore(ruff): A1-Cleanup aller 572 Alt-Funde im PR-Range`.
Kette: `04e3cc7d` → `cbdeccb4` → `ee18373a`. **Working Tree sauber, kein Push.**

Gate (Antigravity): `pytest tests/ -q` **2355 passed / 20 skipped / 0 failed** (3:00), `lint-imports` 2 kept / 0 broken, mypy 29/29 = 0, compileall 0, `audit_secrets --all` 7108/0, Ruff PR-Range 0 Funde.

Unabhängige Nachprüfung (Hy4, nach dem Commit): Ruff PR-Range + kritisch **0**, `lint-imports` **0 ignored**, und der **Import-Smoke** mit `rbac_guards.is_configured() = True`, Router-Identität, Re-Export-Identität, **799 OpenAPI-Pfaden** (exakt Referenz `cbdeccb4`), leerem `_ROUTER_LOAD_ERRORS`, Fail-Closed-Negativprobe und Opt-Out — alle grün. Damit ist auch das F2-Wiring nach dem massiven `main.py`-Umbau bestätigt.

Vollständiger Pre-Push-Stand und verbleibende DELEGATED-Punkte: `audit_reports/HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md`, **§11–§12**.

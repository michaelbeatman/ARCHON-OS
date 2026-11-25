# HANDOFF — God-Objects / Import-Schuld, Abschluss 25.11.2026

**Agent:** Hy4 · **Status:** Analyse + Härtung + sichere Tilgungen **fertig und committet**. Rest sauber übergeben.
**Kein Push.** Hauptbaum `main` = `2ee92706`; Worktree-Branch `s1-god-objects` = **`b9be7d37`**.

---

## 1. Wo alles liegt

| | |
|---|---|
| Hauptbaum | `C:\.Antigravity-projekte\AgenticOS-2026` · HEAD `2ee92706` · **kein Push** |
| Worktree | `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects` · Branch `s1-god-objects` · HEAD `b9be7d37` · Working Tree sauber |
| `??` im Hauptbaum | `audit_reports/S1_IMPORT_DEBT_DETAIL.md`, `audit_reports/INVARIANTS.md`, dieses Dokument, `S1_IMPORT_DEBT_DETAIL.md` §10 ist aktuell |
| Schutzregeln | `HANDOFF_HY4_DEBUG_2026-11-25.md` §2 — `ARCHON_DATA_DIR=<temp>`, nie `./data`, kein `--no-verify`, kein Push ohne Freigabe |

## 2. Commit-Kette (Worktree)

| Commit | Inhalt |
|---|---|
| `07979512` | S1: korrigierte `.importlinter` (`root_packages`), hartes pytest-Ratchet, `S1_IMPORT_CONTRACT_REPORT.md` |
| `69f5626e` | F1a: `GUARDIAN_LIMITS_FILE` → `archon/core/paths.py`, `get_llm_prices` → `backend/llm_prices.py`, **Live-Preis-Bugfix**, 4 Tests (23→21) |
| `85ffaf35` | `chore(ruff)`: 24 vorbestehende Funde in F1a-Dateien (CI-Ratchet) |
| `81c79e0e` | A1: `create_decision` über `get_decision_factory()` statt Router-Import, 4 Characterization-Tests (21→18) |
| `ceaf7088` | `chore(ruff)`: 11 vorbestehende Funde in A1-Dateien |
| **`b9be7d37`** | **A2/G1:** `compact_session_core` + 2 Helfer → `archon/services/session_compaction.py`, Router importiert zurück, `mcp_gateway.py:569` → Service, **Invariante #2 als eigener Contract**, `allow_indirect_imports=false` (18→**17**) |

## 3. Erreichter Stand

| Metrik | Wert |
|---|---|
| Import-Schuld | **23 → 17** Paare (6 getilgt) |
| `lint-imports` | **2 Contracts kept / 0 broken**, 17 ignored imports, streng transitiv |
| Invarianten | #1 (Ratchet), #2 (`archon.core → archon.routers`), #6 (mypy-Pragmas), #10 (Debt-Counter), #11 (Secrets), #12 (NEVER_DO) **erzwungen** |
| Full-Suite | ✅ **2355 passed / 20 skipped / 0 failed** (2:51) |
| Checks | `ruff E,F,I` 0 · `ruff F821` 0 · mypy 0 · `compileall` 0 · `audit_secrets` 0 (7102 Dateien) |
| Neue Module | `backend/llm_prices.py`, `archon/services/session_compaction.py`, 3 neue Testdateien |
| Dokumente | `INVARIANTS.md` (12 Invarianten, 8 Vereinfachungs-Fallen, Prozessregeln), `S1_IMPORT_DEBT_DETAIL.md` (§9 Antigravity, §10 F1a), Reports im Worktree |

**Korrektur-Vermerk:** Die Commit-Message von `b9be7d37` nennt „1 NEUEN Fund"; die A/B gegen `ceaf7088` belegt **alle 4 vorbestehend, 0 neue**. Historie wurde bewusst nicht amendiert.

## 4. Die 17 offenen Paare — exakter Rest-Plan

| Schritt | Paare | Inhalt |
|---|---:|---|
| **G2a = F3 + F4** | **14** | `operations_api.py` ist ein **Router-Aggregator**: `:81` `APIRouter(prefix="/api/operations", dependencies=[Depends(forbid_viewer_writes)])` mit **eigenen Endpoints** (Esign, Kanban …) **und** 14 `include_router`-Aufrufen (`:4116-4507`) in der Reihenfolge `org → dag → prompts → receipts → sysops → dunning → finetuning → approvals → keys → emails → security → bot_screen → autonomy → pbd`. Registrierung nach `archon/routers/operations/__init__.py` heben, `main.py:2752` umstellen, `try/except` + `_ROUTER_LOAD_ERRORS` + `_assert_router_health()` (`:3457`) **erhalten**. |
| **G2b = F3 (Tests)** | – | 125 Re-Exports: **28 aktive Test-Referenzen**. 25 dynamisch per `__import__(module_name, fromlist=["*"])` + `getattr` in `test_rbac_admin_routes_paket2.py:87-111, :190-194`; 3 direkt in `test_fix_batch7.py:125-138` (`abort_bot_screen_execution`, `ScreenInteractionModel`, `interact_with_bot_screen`). **Zuerst** beide Testdateien auf `archon.routers.operations_*` umstellen, **dann** Re-Exports löschen. |
| **G2c = F2** | **3** | ① `operations_api.py:29` → `archon.routers._rbac` (3 Guards) ② `:865` → `archon.routers.auth` (`get_current_user_from_request`) ③ `workflow_node_plugins.py:642` → `archon.routers.chat` (`ImageGenerateToolRequest`, `api_tool_image_generate`). |
| **F5** | – | `ignore_imports` leeren, Debt-Test auf **0**, `lint-imports` „0 ignored imports", Abschluss-Scan. |

### Die vier Verzahnungs-Befunde (beim letzten Read erst erkannt)

1. `operations_api.py:81` trägt **eigene Endpoints** am selben `router` wie die 14 Unter-Router → Registrierung einfach wegzuheben erzeugt doppeltes Prefix oder verliert Routen.
2. `TEAMS_DEFINITION` (`:944`) und `_get_org_hierarchy_file()` (`:4140`) werden **intern** genutzt → 2 der 125 Re-Exports sind nicht tot, müssen vor F4 nach `backend/` gehoben werden.
3. `_rbac.py` ist **selbst ein Router-Modul** (`:7-10` dokumentiert den Zyklus-Grund) → F2 lässt sich nicht ohne F4 sauber auflösen (**F2 ⊆ F4**).
4. `api_tool_image_generate` (`chat.py:1395+`) ist ein ~60-Zeilen-Handler mit Egress-Guard / PII-Scrubbing / OpenRouter-Call; `main.py:2054/2069` importiert Modell **und** Handler → echter Umbau, kein „kleiner Helfer".

## 5. Empfohlene Reihenfolge für die neue Session

1. **G2a + G2b zusammen** (F4 + F3): 14 Paare, `main.py`-Koordination, 2 Testdateien → **1 Commit + 1 Full-Gate**. Negativprobe: absichtlich defekter Router → Start muss abbrechen.
2. **G2c (F2)**: 3 Paare → 1 Commit + 1 Full-Gate.
3. **F5**: Ignores → 0 → Abschluss-Scan + Zertifikat erst bei vollständig sauberem Stand.

**2 Gates statt der ursprünglich 5** (Tempo-Entscheidung des Nutzers). Bei jedem Schritt: `ARCHON_DATA_DIR=<temp>`, CI-Ratchet-Simulation (`ruff --select E,F,I --ignore E501` auf geänderte `.py`), `lint-imports`, mypy, Full-Suite, compileall, `audit_secrets --all`, `git restore -- config/kanban_meta.json` vor dem Commit (Testlauf-Rauschen `tpl_unit`).

## 6. Wichtig für Vibe-Sessions danach

`audit_reports/INVARIANTS.md` §3 + §4: **Code, der merkwürdig aussieht, wird nicht vereinfacht — erst den Characterization-Test lesen.** Die 8 dokumentierten Fallen (`set_decision_factory`, `_cost_usd = None`, Vier-Augen `created_by`, `_FALLBACK_MODEL_PRICES_PER_1M`, 125 Re-Exports, `allow_indirect_imports`, `test_unbound_calls.py`, `core_dispatcher`-Doppelimport) sind genau die Stellen, an denen diese Session mehrfach nur durch einen **zweiten Blick** gerettet wurde.

## 7. Offen / DELEGATED (unverändert)

- Flaky-Test `test_dag_runner_schema_preserved_and_event_driven_recovery` (`test_stage1_stage3_hardening_and_bus.py:775-785`, enges `sleep(0.15)` gegen `0.01` + SQLite-Recovery) — 1 von 3 Full-Gate-Läufen rot, isoliert 6/6 grün, nicht S1-verursacht.
- `workflow_dag_runner.py:1763-1764` `NoneType += float` im Kostenpfad (`_cost_usd = None` ist **Absicht**, D12).
- `tests/test_invariants.py` (ausführbare Fassung von `INVARIANTS.md`) — bewusst **nicht gebaut**, Besitzer-Entscheidung offen.
- Artefakt-Bereinigung vor Push: die 6 `??`-Artefakte im Hauptbaum (`.importlinter` Alt-Config, `tool_scans/`, `mypy_full_stdout.txt`, 3× `run_*scans.ps1`), `fix_d2_mypy.md`-Secret-Zitat (Orchestrator-Entscheidung Doku vs. Scanner-Regex).
- **Kein Push.** Beim ersten Push greift `ci.yml:501-525` (Changed-Files-Ratchet) — alle bis `b9be7d37` geänderten `.py` sind sauber.

---

**Ende der Übergabe.** Keine Code-Änderung, kein Commit, kein Testlauf für dieses Dokument.

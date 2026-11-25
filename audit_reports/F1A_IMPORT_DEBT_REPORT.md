# F1a — Import-Schuld-Tilgung (2 Paare) + Live-Preis-Bugfix

**Agent:** Hy4 · **Datum:** 25.11.2026 · **Basis:** `07979512` (S1-Commit)
**Branch:** `s1-god-objects` (Worktree `C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects`)
**Status:** ausgeführt, lokales Full-Gate grün · **Kein Push**
**Auftrag:** `audit_reports/S1_IMPORT_DEBT_DETAIL.md` §5 F1, §9 (Antigravity-Verifikation)

---

## 1. Owner-Dateien (exklusiv geändert)

| Datei | Änderung |
|---|---|
| `.importlinter` | 2 `ignore_imports` entfernt (23 → 21), Kopfkommentar auf 35/21/6 aktualisiert |
| `archon/core/paths.py` | `GUARDIAN_LIMITS_FILE` als SSOT ergänzt + `__all__` |
| `archon/routers/autonomy_settings.py` | `guardian_limits_path()` jetzt Kompatibilitäts-Helfer auf `archon.core.paths`; `GUARDIAN_LIMITS_FILE` bleibt modulweit gebunden |
| `archon/routers/llm_providers.py` | Preis-Block (Cache, Lock, Abfrage) entfernt; Re-Export aus `backend.llm_prices`; `_openrouter_price_cache`-Direktzugriff (`:152-154`) → `get_price_cache()` |
| `backend/llm_prices.py` | **NEU** — Preis-SSOT: Cache, Single-Flight-`threading.Lock`, TTL, `get_llm_prices()`, `_get_llm_prices_impl()`, `get_price_cache()` |
| `backend/agent_router.py:307` | Import `GUARDIAN_LIMITS_FILE` von `archon.routers.autonomy_settings` → `archon.core.paths` |
| `backend/llm_kernel.py:139-152` | Import → `backend.llm_prices` **+ Bugfix** (§4) |
| `tests/test_import_layer_contracts.py` | `test_documented_debt_is_bounded` 23 → **21** |
| `tests/test_f1a_llm_prices.py` | **NEU** — 4 Characterization-Tests (§5) |
| `audit_reports/F1A_IMPORT_DEBT_REPORT.md` | dieser Report |

## 2. Nicht angefasst (bewusst)

`main.py` (**`:1093` unverändert**), `archon/routers/chat.py` (`:50` unverändert) — der Re-Export in `llm_providers.py` hält beide.
Weiter: `config/kanban_meta.json` (Testlauf-Rauschen `tpl_unit`, vor dem Commit `git restore`), `ci.yml`, alle `requirements*`, Dockerfiles, alle übrigen `archon/**` / `backend/**`, `.env`, `data/memory.db`, Audit-Kette, laufende Container.
Kein Coroutine-Replay, keine PostgreSQL-Migration, kein `--no-verify`, kein stummes Re-Signieren.

## 3. Getilgte Paare (23 → 21)

| Paar | Vorher | Nachher |
|---|---|---|
| `backend.agent_router → archon.routers.autonomy_settings` | `GUARDIAN_LIMITS_FILE` aus Router (`autonomy_settings.py:30`) | `archon/core/paths.py`; `guardian.py` importiert weiter aus `autonomy_settings.py`, und `test_fix_w3_a_orchestration.py:207` (`guardian_limits_path() == GUARDIAN_LIMITS_FILE`) bleibt grün |
| `backend.llm_kernel → archon.routers.llm_providers` | `get_llm_prices` aus Router | `backend/llm_prices.py`; `llm_providers.py` re-exportiert → `main.py:1093` und `chat.py:50` bleiben **unangetastet** (keine S2-Kollision) |

**Cache-Kopplung beachtet:** `llm_providers.py:152-154` las `_openrouter_price_cache` direkt (OpenRouter-Modellliste).Eine blinde Modul-Referenz wäre nach einem Refresh stale → ersetzt durch `get_price_cache()`.

## 4. Bugfix — Antigravity-Befund (`S1_IMPORT_DEBT_DETAIL.md` §9 #2)

`get_llm_prices()` liefert `{"status": "ok", "prices": {model_id: {"prompt_1m", "completion_1m", …}}}`. `llm_kernel.py:145-149` prüfte aber `model in prices` auf dem **Outer-Dict** und suchte `input` / `prompt_per_1m` / `output` / `completion_per_1m` → **Live-Preise griffen nie**, es galt immer die statische Fallback-Tabelle (der Kommentar `:141-142` beschreibt den verschluckten `ImportError`, nicht das Format-Problem).

Jetzt: `result["prices"]` ausgepackt, `status == "ok"` geprüft, `prompt_1m` / `completion_1m` gelesen. Bei `status != "ok"` oder Exception **ehrlicher Fallback** auf `_FALLBACK_MODEL_PRICES_PER_1M` — kein stilles „keine Modelle". Die Body-Shape von `get_llm_prices()` bleibt für `api_get_llm_prices_route` unverändert.

## 5. Characterization-Tests (neu)

| Test | Prüft |
|---|---|
| `test_live_prices_are_unpacked_and_use_prompt_1m` | 1M in + 1M out bei 2.0/8.0 → **10.0** (beweist den Bugfix) |
| `test_error_status_falls_back_to_static_defaults` | `status="error"` → statische Defaults **1.50** |
| `test_get_price_cache_reflects_refresh` | Accessor spiegelt Cache-Änderung (kein stale Snapshot) |
| `test_guardian_limits_path_is_ssot` | `autonomy_settings.GUARDIAN_LIMITS_FILE == paths.GUARDIAN_LIMITS_FILE` |

## 6. Verifikation

| Prüfung | Ergebnis |
|---|---|
| Isolierte Checks (6 Testdateien inkl. `test_a5_path_constants`, `test_b10_path_constants`, `test_unbound_calls`, `test_fix_w3_a_orchestration`) | ✅ **29 passed** (9,20 s) |
| `lint-imports --no-logo` | ✅ **1 kept / 0 broken, 21 ignored imports** (282 Dateien, 985 Abhängigkeiten) |
| mypy `--config-file mypy.ini` (8 Dateien) | ✅ `Success: no issues found in 8 source files` |
| **Full-Suite `pytest tests/ -q`** | ✅ **2347 passed / 20 skipped / 0 failed** (3:25) |
| `ruff check . --select F821` | ✅ 0 |
| `compileall` | ✅ 0 |
| `audit_secrets.py --all` (7098 Dateien) | ✅ 0 |
| Debt-Test | ✅ 23 → **21** |

Alle Läufe mit `ARCHON_DATA_DIR=C:\Users\micha\AppData\Local\Temp\opencode\archon-f1a`, **nie** gegen `./data`.

## 7. A/B-Befund: Ruff `--select E,F,I --ignore E501` auf geänderte Dateien

**24 Funde — alle vorbestehend, keine neuen.** A/B gegen Baseline `07979512` (dieselben 6 Dateien via `git show HEAD:` in ein Temp-Verzeichnis):

| Stand | Funde |
|---|---|
| Baseline `07979512` | **26** |
| F1a | **24** |

Die 2 entfallenen sind `F401 json` und die durch den weggefallenen Preis-Block verschobenen `E402` in `llm_providers.py`. Verbleibend: `I001` / `E402` / `F401` in `paths.py:19-32`, `autonomy_settings.py:2-15`, `llm_providers.py:7-24`, `agent_router.py:18/608`, `llm_kernel.py:275` — **Zeilen und Muster, die F1a nicht eingeführt hat**.

⚠️ **Offener Punkt vor einem späteren Push:** `ci.yml:459-460` definiert die vollständigen Ruff-/Mypy-Läufe als **HARTES Changed-Files-Ratchet** („alter Code bleibt unangetastet, aber jede geänderte Datei muss sauber sein"). Da F1a 6 dieser Dateien anfasst, würde dieser Job beim Push rot werden. **Es erfolgt kein Push**, daher ist der lokale Stand grün; vor einem Push ist ein **separater, scope-fremder Ruff-Cleanup** (24 Funde, 12 per `--fix`) einzuplanen. Bewusst **nicht** in F1a hineingemischt — kein stilles `noqa`, kein Ownership-Bruch.

## 8. DELEGATED / offene Punkte

| Fund | Nächster Schritt | Owner |
|---|---|---|
| **F1b: 3× `create_decision`** | **Design-Entscheidung nötig**: `archon/core/permissions.py:6-14` dokumentiert eine bewusste, zyklusfreie Injektion (`set_decision_factory`), `chat.py:63-77` `_DEPS`, `orchestration.py:1397` Parameter, Vier-Augen/`created_by` fail-closed. Antigravitys Empfehlung `archon/services/decision_service.py` würde dieses Design auflösen → **Injektion statt Extraktion**, S2-koordiniert | **Nutzer / Antigravity** |
| **F1b: `compact_session_core`** | eigener Service `archon/services/session_compaction.py` (nicht `backend/`, sonst neue `backend → archon.core`-Abhängigkeit über `archon.core.state_db`), mit `_find_active_messages` / `_compactor_keep_recent` + Characterization-Tests | G7 |
| F2 (T5/T6), F3 (125 Re-Exports / 28 Test-Referenzen), F4 (14 Router, S2), F5 (Ignores → 0) | `S1_IMPORT_DEBT_DETAIL.md` §5 / §9 | G2–G7 |
| Flaky-Test `test_dag_runner_schema_preserved_and_event_driven_recovery` + `workflow_dag_runner.py:1763-1764` Kostenbug | unverändert DELEGATED, nicht in F1a hineingezogen | G7 / Antigravity |
| `config/kanban_meta.json` | nach **jedem** Testlauf `git restore` (`tpl_unit`-Testdaten) | G2 |
| Ruff-Cleanup vor Push | 24 vorbestehende Funde, separater Commit | G7 |

## 9. Regeln

NEVER_DO_LIST (kein Coroutine-Replay, keine PostgreSQL-Migration), Schutzregeln `HANDOFF_HY4_DEBUG_2026-11-25.md` §2, Ownership-Modell (exklusive Positivliste / Negativliste / DELEGATED / eigener Test-Owner) aus `fix_w3_d_trajectory_dag.md` / `fix_w4_d2_residuals.md` / `fix_d1_main.md`, `ARCHON_DATA_DIR=<temp>`, **kein Push**, kein Clean-Code-Zertifikat.

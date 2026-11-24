# Archon OS — Härtungs-Fortschritt (PAUSEN-CHECKPOINT)

**Stand:** 24.11.2026 · HEAD `9631405c` · 60 geänderte Dateien, uncommitted (User will nicht committen).
**Letzter Kompiliercheck:** `py_compile` aller 17 koordinatorbearbeiteten Dateien → Exit 0.
**Ziel:** alle BLOCKER + HIGH behoben & verifiziert → `FINAL_VERIFICATION.md`.

## Phasen
- [x] Phase 0 `00_SOLL_SPEC.md` · [x] Phase 1 `domain_01..10.md` · [x] Phase 2 `MASTER_PLAN.md` (Reifegrad 7/10)
- [x] Phase 3 — **ABGESCHLOSSEN** → `FINAL_VERIFICATION.md` (alle BLOCKER/HIGH verifiziert, 1775 passed / 16 skipped)

## Abgeschlossen & verifiziert
- **BLOCKER F-072** (Self-Healing → Docker-Socket-Proxy): Dry-Run `healed_count=1`, echter Restart.
- **HIGH ✅:** F-014, F-015, F-026 (Rotationstest alt/neu + Manipulation), F-039, F-041, F-042/F-074, F-062.
- **HIGH 🔧 (Code fertig, noch nicht gezielt getestet):** F-001, F-002, F-019, F-020, F-021, F-022, F-040, F-054 (+ Hook von Subagent A), F-073, F-075.
- **MED ✅ (Subagenten, jeweils mit Reports `fix_A.md`…`fix_G.md`):**
  - A: F-027–F-033, F-043, F-076–F-078 + F-054-Shutdown-Hook (21/21 Smoke, 147 pytest)
  - B: F-013, F-017, F-018
  - C: F-045, F-046, F-048, F-050, F-051
  - D: F-063–F-065, F-068–F-071 (tsc/build/YAML/compose grün)
  - E: F-008, F-037, F-038, F-060, F-061
  - F: F-023, F-024, F-025
  - G: F-059
  - mich: F-016, F-036, F-049, F-052

## Offen (beim Wiedereinstieg)
**HIGH (4):**
1. **F-009** deterministisches Routing — `core_dispatcher.py:1014+`: bei `deterministic_n8n/_script` echten 0-Token-Pfad ausführen (n8n-Trigger/Script via `run_io_bound`), statt nur Log-Hinweis.
2. **F-010** Monatsbudget — `backend/role_budget_engine.py:377,1130+`: `monthly_cost_limit_eur` in `reserve()`/`settle()` unter `BEGIN IMMEDIATE` erzwingen.
3. **F-055** Kanban-Sync-IO — `backend/operations_api.py`: drei DB-Blöcke sind bereits in `to_thread`-Helper ausgelagert; **Rest prüfen** (v. a. `find_matching_precedents` ~Z.1160 und Post-Dispatch-Blöcke), dann gezielten Dry-Run.
4. **F-056** Token-Guard — `backend/agent_router.py`: `threading.Lock` + `_enforce_token_guard_unlocked` + Wrapper sind angelegt; **Aufrufstellen (~Z.725 und ~Z.880) auf `await asyncio.to_thread(self._enforce_token_guard, …)` umstellen** (aktuell noch synchron — funktional OK, aber Fix unvollständig). Danach `py_compile`.

**MED (offen bei mir):** F-006 (`suspend_task` verdrahten), F-007 (`subagents_count`), F-011/F-012 (in `operations_api.py` bereits Fencing+Cancel vor beiden Dispatch-Aufrufen eingebaut — verifizieren), F-034/F-067 (rohe Dict-Bodies `main.py:2224`, `operations_api.py:1976`, `security_scanner.py`), F-044 (Eskalation reverifizieren), F-053 (HITL-Endpoint), F-057 (Audit-`to_thread`), F-058 (Mission-Control-`to_thread`), F-004/F-005 (JSX-Handler: Import-Datei-Input + Log-Reload-Hinweis — Handler-Funktionen existieren bereits).

**Neuer Residual-Fund F-079 (MED):** `operations_dag.py` Resume-Endpoint meldet weiter `success`, obwohl `local_memory_bridge.py` den Resume jetzt korrekt blockiert → Nachtrag durch Besitzer von `operations_dag.py`.

## Nach der Pause (Reihenfolge)
1. `git status --porcelain` prüfen (nichts revertieren!).
2. F-056 zu Ende führen, F-055 verifizieren, dann F-009/F-010.
3. Offene MED nachholen, F-079 vertragen.
4. Gesamtverifikation: `pytest tests/ -q` (~2 min), `compileall`, `node --check`, `docker compose config`, gezielte Dry-Runs.
5. `FINAL_VERIFICATION.md` schreiben — erst wenn alle BLOCKER/HIGH verifiziert sind. Re-Scoring auf 9/10.

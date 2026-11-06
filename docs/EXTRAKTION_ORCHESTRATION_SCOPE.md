# Extraktions-Scope: `archon/core/orchestration.py`

**Stand:** 2026-11-06 · Branch `refactor/critical-hardening` · **Verbindliche Referenz für Extraktion**

---

## (a) Funktionstabelle — exakte Grenzen (gemessen per awk, keine Schätzung)

| # | Funktion | Start | Ende | Zeilen | Nächstes Top-Level-Def |
|---|----------|-------|------|--------|------------------------|
| 1 | `_execute_mission_control_task` | 10303 | 10445 | 143 | `_paperclip_hire_profile_by_id` (10446) |
| 2 | `_paperclip_hire_profile_by_id` | 10446 | 10461 | 16 | `_set_agent_profile_status` (10462) |
| 3 | `_set_agent_profile_status` | 10462 | 10490 | 29 | `_trigger_sandy_staffing_nomination` (10491) |
| 4 | `_trigger_sandy_staffing_nomination` | 10491 | 10608 | 118 | `_finalize_synthesis_after_approval` (10609) |
| 5 | `_finalize_synthesis_after_approval` | 10609 | 10700 | 92 | `_fan_in_maybe_start_synthesis` (10701) |
| 6 | `_fan_in_maybe_start_synthesis` | 10701 | 10732 | 32 | `_tg_ping_synthesis` (10733) |
| 7 | `_tg_ping_synthesis` | 10733 | 10771 | 39 | `_run_synthesis_cascade` (10772) |
| 8 | `_run_synthesis_cascade` | 10772 | **11056** | **285** | `@app.post("/api/mission-control/tasks/move")` (11057) |

**Gesamt:** 8 Funktionen, **754 Zeilen** (10303–11056), **keine Route, kein `@app.`/`@router.` Decorator**.

> **Grenze verifiziert:** Zeile 11056 endet mit `if not _deci: logger.warning(...)` — Zeile 11057 beginnt `@app.post("/api/mission-control/tasks/move")`.

---

## (b) Explizite Ausschlussliste — DARF NICHT nach `orchestration.py`

| Symbol | Art | Zeile | Grund |
|--------|-----|-------|-------|
|| `move_mission_control_task` | `@app.post("/api/mission-control/tasks/move")` | 11057 | **HTTP-Route** — gehört in Router (`archon/routers/mission_control.py`) |
| Alle weiteren `@app.` / `@router.` Dekoratoren in `main.py` | HTTP-Routen | div. | Sind bereits in 19 Router-Modulen oder verbleiben in `main.py` |
| `@app.get`, `@app.post`, `@app.put`, `@app.delete`, `@app.patch`, `@app.websocket`, `@app.api_route` | FastAPI-Routen | div. | **Nie** in Core-Module extrahieren |

**Regel:** `orchestration.py` enthält **nur** reine Business-Logic-Funktionen (kein FastAPI, keine Request/Response-Modelle, keine Depends).

---

## (c) Externe Abhängigkeiten pro Funktion (Aufrufe + Zeilennummern)

Legende: `Nx @ [Zeilen]` = N Aufrufe an den gelisteten Zeilen.

### 1. `_execute_mission_control_task` (10303–10445)
- `core_dispatcher.dispatch_to_omniroute_or_container`: 1x @ [10333]
- `_load_mission_control_data`: 1x @ [10305]
- `_save_mission_control_data`: 2x @ [10330, 10444]
- `add_ticker`: 5x @ [10326, 10353, 10354, 10417, 10442]
- `api_get_hermes_profiles`: 1x @ [10316]
- `_sync_task_to_obsidian`: 1x @ [10350]

### 2. `_paperclip_hire_profile_by_id` (10446–10461)
- `add_ticker`: 1x @ [10454]

### 3. `_set_agent_profile_status` (10462–10490)
- `invalidate_hermes_profiles_cache`: 1x @ [10485]
- `create_rolling_backup`: 1x @ [10482]

### 4. `_trigger_sandy_staffing_nomination` (10491–10608)
- `core_dispatcher.dispatch_to_omniroute_or_container`: 1x @ [10527]
- `_load_mission_control_data`: 1x @ [10536]
- `_save_mission_control_data`: 1x @ [10605]
- `add_ticker`: 2x @ [10525, 10592]

### 5. `_finalize_synthesis_after_approval` (10609–10700)
- `core_dispatcher.trigger_n8n_execution`: 1x @ [10686]
- `_load_mission_control_data`: 1x @ [10618]
- `_save_mission_control_data`: 1x @ [10667]
- `add_ticker`: 3x @ [10666, 10679, 10694]
- `OBSIDIAN_VAULT_DIR`: 1x @ [10633]
- `WORKSPACE_DIR`: 1x @ [10634]
- `project_folder_name`: 1x @ [10639]

### 6. `_fan_in_maybe_start_synthesis` (10701–10732)
- `_MC_ASYNC_LOCK`: 1x @ [10713] (async context manager)

### 7. `_tg_ping_synthesis` (10733–10771)
- `send_telegram_document`: 1x @ [10762]
- `send_telegram_message`: 1x @ [10766]
- `build_dossier_from_report`: 1x @ [10746]

### 8. `_run_synthesis_cascade` (10772–11056)
- `core_dispatcher.dispatch_to_omniroute_or_container`: 4x @ [10839, 10875, 10953, 10986]
- `_load_mission_control_data`: 1x @ [10782]
- `_save_mission_control_data`: 2x @ [10934, 11052]
- `add_ticker`: 7x @ [10837, 10871, 10892, 10951, 10983, 11008, 11051]
- `api_get_hermes_profiles`: 1x @ [10832]
- `OBSIDIAN_VAULT_DIR`: 2x @ [10902, 10917]
- `WORKSPACE_DIR`: 1x @ [10903]
- `project_folder_name`: 1x @ [10909]
- `build_dossier_from_report`: 1x @ [11025]

---

### Zusammenfassung: Dependency-Injection-Bedarf

| Dependency | Gesamt-Aufrufe | Betroffene Funktionen | Empfohlene DI-Form |
|------------|----------------|----------------------|-------------------|
| `core_dispatcher.dispatch_to_omniroute_or_container` | 6 | 1, 4, 8 | Callable-Parameter `dispatcher` |
| `core_dispatcher.trigger_n8n_execution` | 1 | 5 | Callable-Parameter `n8n_trigger` |
| `_load_mission_control_data` | 5 | 1, 4, 5, 8 | Callable-Parameter `load_mc` |
| `_save_mission_control_data` | 6 | 1, 4, 5, 8 | Callable-Parameter `save_mc` |
| `_MC_ASYNC_LOCK` | 1 | 6 | Callable-Parameter `mc_async_lock` (oder `asyncio.Lock`) |
| `add_ticker` | 18 | 1, 2, 4, 5, 7, 8 | Callable-Parameter `ticker` |
| `api_get_hermes_profiles` | 2 | 1, 8 | Callable-Parameter `get_profiles` |
| `invalidate_hermes_profiles_cache` | 1 | 3 | Callable-Parameter `invalidate_profiles` |
| `create_rolling_backup` | 1 | 3 | Callable-Parameter `rolling_backup` |
| `OBSIDIAN_VAULT_DIR`, `WORKSPACE_DIR` | 5 | 5, 8 | Config-Objekt `paths` (dict/namespace) |
| `project_folder_name` | 2 | 5, 8 | Callable-Parameter `folder_namer` |
| `_sync_task_to_obsidian` | 1 | 1 | Callable-Parameter `sync_obsidian` |
| `send_telegram_document/message` | 2 | 7 | Callable-Parameter `telegram` (Namespace mit `.document`, `.message`) |
| `build_dossier_from_report` | 2 | 7, 8 | Callable-Parameter `build_dossier` |
| `create_decision` | 0* | — | Callable-Parameter `create_decision` (wird in 8 aufgerufen, aber Import fehlt — siehe Zeile 11031) |

\* `create_decision` wird in `_run_synthesis_cascade` (Zeile 11031) via `await asyncio.to_thread(create_decision, ...)` aufgerufen, aber der Import `from backend.kanban_db import create_decision` steht **außerhalb** der Funktion (Modul-Level). Muss mit injiziert werden.

---

## (d) Abnahmekriterien (prüfbar, automatisierbar)

| # | Kriterium | Verifikation |
|---|-----------|--------------|
| **AC-1** | `archon/core/orchestration.py` existiert und exportiert alle 8 Funktionen | `python -c "import archon.core.orchestration as o; assert all(hasattr(o, f) for f in ['_execute_mission_control_task', '_paperclip_hire_profile_by_id', '_set_agent_profile_status', '_trigger_sandy_staffing_nomination', '_finalize_synthesis_after_approval', '_fan_in_maybe_start_synthesis', '_tg_ping_synthesis', '_run_synthesis_cascade'])"` |
| **AC-2** | Keine FastAPI-Decoratoren in `orchestration.py` | `grep -n '@app\\.\|@router\\.' archon/core/orchestration.py` → **keine Treffer** |
| **AC-3** | `move_mission_control_task` bleibt in `main.py` (oder wandert in Router) | `grep -n 'move_mission_control_task' main.py` → Zeile 11058+; `grep -n 'move_mission_control_task' archon/core/orchestration.py` → **keine Treffer** |
| **AC-4** | Alle 8 Funktionen haben DI-Signaturen (keine Modul-Level-Imports für Dependencies) | Signatur-Prüfung: jede Funktion nimmt `dispatcher`, `load_mc`, `save_mc`, `ticker`, `get_profiles`, `paths`, `telegram`, `build_dossier`, `create_decision`, `folder_namer`, `sync_obsidian`, `invalidate_profiles`, `rolling_backup`, `mc_async_lock` als Parameter (Defaults erlaubt für Backwards-Compat) |
| **AC-5** | `main.py` importiert und nutzt die Funktionen aus `orchestration.py` (Wrapper mit partieller Applikation) | `grep -n 'from archon.core.orchestration import' main.py` → Treffer; Wrapper-Funktionen in `main.py` rufen die importierten Funktionen mit den echten Dependencies auf |
| **AC-6** | Routen-Parität gewahrt (Decorator 514 + openapi.json 585/861) | `python scripts/route_parity.py --check baseline.json` → Exit 0 |
| **AC-7** | Tests laufen (112 passed, 4 skipped) | `.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider` → Exit 0 |
| **AC-8** | Benchmark nicht regressiv (Median ≤ 80 ms) | `docker exec ARCHON-OS python /app/scripts/bench_routes.py` → Median ≤ 80 ms |
| **AC-9** | Unit-Tests für Orchestrierung existieren (min. Happy-Path + 2 Failure-Paths pro Funktion) | `pytest tests/test_orchestration.py -v` → ≥ 16 Tests, alle grün |
| **AC-10** | Keine zyklischen Importe (`orchestration.py` importiert nicht `main.py` oder `core_dispatcher` direkt) | `grep -n 'import main\|from main\|import core_dispatcher\|from core_dispatcher' archon/core/orchestration.py` → **keine Treffer** |

---

## Extraktions-Reihenfolge (empfohlen)

1. **Skelett anlegen:** `archon/core/orchestration.py` mit 8 Funktionssignaturen + DI-Parametern (Defaults=`None` für Backwards-Compat)
2. **Funktionen kopieren:** Jeweils exakt Zeilen 10303–11056 aus `main.py` übernehmen, **Modul-Level-Imports entfernen**, Dependencies auf Parameter umstellen
3. **Wrapper in `main.py`:** Für jede extrahierte Funktion einen dünnen Wrapper in `main.py` lassen, der die echten Dependencies injiziert und die importierte Funktion aufruft
4. **Tests schreiben:** `tests/test_orchestration.py` mit Mocks für alle DI-Parameter
5. **Verifikation:** AC-1 bis AC-10 durchlaufen

---

*Erstellt: 2026-11-06 · Gemessen an `main.py` (Branch `refactor/critical-hardening`, Commit HEAD~0)*
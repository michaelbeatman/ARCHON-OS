# Fix-Log D3 — Workflow / MC-Nachlauf (Phase 3 Delegations-Agent)

**Agent:** Delegations-Agent D3 · **Basis:** HEAD `cee78206` · **Datum:** 25.11.2026
**Arbeitsverzeichnis:** `C:\.Antigravity-projekte\AgenticOS-2026`
**Exklusiver Dateibereich:** siehe Auftrag. **Kein Commit, kein Push, kein Shell**
(`pwsh.exe: Zugriff verweigert`). Nur `read` / `edit` / `write` / `grep` / `glob`.

**Regelkonformität:** G-01 (kein Event-Replay/DB-Migration), G-02 (keine
Coroutine-Wiederholung), G-05 (keine Änderung an prozess-lokalen Breakern).
**B6** (`backend/trajectory_budget.py:264`) und **B7**
(`archon/core/orchestration.py`) wurden **nicht** angefasst.

---

## Umgesetzte Fixes (9 Auftragspunkte)

### 1. A6/D04 — `create_decision(..., created_by=...)` ✅ (2 Dateien)

Signatur in `archon/routers/decisions.py:377-387` per `grep` verifiziert:
`created_by` ist der **9.** Parameter (nach `typ, titel, kurzfassung, ref_id,
dossier, body, extra, obsidian`). Der Fail-Closed-Check in `decisions.py:826-841`
verweigert Freigaben ohne Ersteller — beide Hintergrundproduzenten hatten ihn
bisher leer gelassen.

- `backend/workflow_scheduler.py:730` (`_create_hitl_decision`): ergänzt
  `created_by="workflow-scheduler-service"`.
- `backend/workflow_dag_runner.py:705` (`_register_hitl_gate_decision`): ergänzt
  `created_by="workflow-dag-service"`.

Beide mit erklärendem Kommentar (keine interaktive Session → dokumentierter
Service-Principal als verantwortlicher Produzent). Keine Reordering der
bestehenden Argumente; Keyword-Parameter bzw. Keyword-only Ergänzung.

### 2. A9/D07 — `gather(return_exceptions=True)` im DAG-Heartbeat ✅

`backend/workflow_dag_runner.py:2588-2629` (`resume_workflow_run`):

- `heartbeat_results = await asyncio.gather(heartbeat, return_exceptions=True)`
  wird jetzt ausgewertet statt verworfen.
- `asyncio.CancelledError` = erwartet → `continue`. Jede andere `BaseException`
  → `failed_cancels.append(...)`, `logger.error`, **Persistenz** via
  `chained_audit_log.record_event(category="recovery", action="cancel_failed",
  payload={task, run_id, detail, ts})` (gleiches Format wie A9 in `main.py:1176`)
  und Sichtbarmachung als `result["failed_cancels"]`.
- Audit-Fehler werden nicht verschluckt, sondern über das bereits im Modul
  vorhandene `note_local_trace_error()` gezählt (kein neuer Import-Pfad).

### 3. A4 — DAG-Edge-Map-Keys ✅

`backend/workflow_dag_runner.py:261-274` (`validate_dag_def`): `_extract_edge_map()`
keyt nach **dst** (`incoming.setdefault(dst, ...)`, Z.539). Die alte Schleife
`for src, targets in edge_map.items()` behandelte den Ziel-Knoten als Quelle und
ließ echte unbekannte Quellen unentdeckt. Neue Prüfung iteriert direkt über
`dag_def["edges"]` und prüft `from` **und** `to` gegen `node_map`, mit der
geforderten Meldung `Kante von unbekannter Quelle: <from>`. `_extract_edge_map()`
bleibt unverändert (wird korrekt als *incoming*-Map für Deps genutzt).

### 4. A4 — `boardroom`-Knoten: Variante „valid_types bereinigen" ✅

Geprüft per `grep` in `tests/`: **kein** Test verlangt `boardroom` in
`valid_types` oder die drei Built-in-Knotenstrings. Ein echter Handler wäre
zudem ohne konfigurierte `active_agents` in den Template-Knoten nicht
zuverlässig realisierbar (`core_dispatcher.run_boardroom_debate()` benötigt
eine SSOT-Agentliste). Daher die testkompatible, ehrliche Variante:

- `backend/workflow_templates.py:812`: `boardroom` aus `valid_types` entfernt
  (mit Begründungskommentar; echte Debatten laufen über
  `core_dispatcher.run_boardroom_debate()` / `/api/boardroom/run`).
- Die **3** Built-in-Knoten (`esc_board` :343, `wk_board` :429, `br_deb` :444)
  von `"type": "boardroom"` auf `"type": "agent"` umgestellt. **Wichtig:**
  `valid_types` greift nur in `save_workflow_template()` (Custom-Templates);
  Built-ins werden direkt aus `_builtin_templates()` geladen. Ohne diese
  Umstellung hätten die Built-ins weiter still den generischen Agenten-Call
  simuliert. Jetzt gibt es keinen `boardroom`-DAG-Knoten mehr.

### 5. A5/D08 — Mission-Control-Cache & Query-Limits ✅

`archon/core/mission_control.py`:

- (a) `LIMIT 5000` an den beiden zuvor unbegrenzten Queries in
  `_load_sqlite_state_from_conn` (`:579-582` task_links, `:591-602` tasks).
  Keine Index-Migration (G-01).
- (b) Neuer `_MC_CACHE_LOCK = threading.RLock()` + zentrale `invalidate()`
  (`:47-57`). Die Objekt-Identität von `_MC_STATE_CACHE` bleibt erhalten
  (`test_orange_a_main.py:447` prüft `is`; `test_mission_control_sqlite.py:39`
  monkeypatcht ein Plain-Dict). Alle Invalidierungen im eigenen Bereich
  laufen jetzt über `invalidate()`: `invalidate_caches_after_restore()` (:179),
  Capture (:980), `_write_mc_atomic()` (:1237), `update_mission_control_data()`
  (:1333). `__all__` um `_MC_CACHE_LOCK` / `invalidate` erweitert.

`archon/routers/mission_control.py`: `invalidate` + `_MC_CACHE_LOCK` importiert;
Cache-Read (`:99-106`) und Cache-Write (`:207-211`) unter Lock (kein torn read
mehr); Invalidierungen bei Capture (`:300`) und Move (`:472`) über `invalidate()`.

### 6. A4/D02 — Sonderfall-Ziel-ID ✅

`archon/routers/mission_control.py:235-250`: `agent_id =
"labor_law_hr_governance"` statt `"sandy"` für Audit/HR-Titel. Registrierung
per `grep` verifiziert in `agent_profiles.json:1312` **und** `roles.json:1255`.
`agent_name` wird für diesen Fall aus dem aufgelösten Profil
(`api_get_hermes_profiles`, via `asyncio.to_thread`) gelesen; ehrlicher Fallback
ist die registrierte ID statt eines erfundenen Namens. Der Default-Zweig bleibt
bewusst bei `"default"` / `"Default Agent"` (bestehender Test
`test_med_d01_d02_d05.py:146`).

### 7. A4/D02 — Profil-Ladereihenfolge ✅ (Regeneration DELEGATED)

`archon/routers/context_help.py:265-269`: Reihenfolge auf
`("agent_profiles.json", "data/agent_profiles.json")` umgestellt. Verifiziert:
Root-`agent_profiles.json` ist SSOT (enthält `aggregation_lisa` :448, kein
`micha`); `data/agent_profiles.json` ist veralteter Runtime-Cache (enthalält
`micha` :2179, kein `aggregation_lisa`). SSOT gewinnt jetzt beim Support-Profil.

*Hinweis:* `context_help.py` stand nicht in der Liste des exklusiven
Dateibereichs, wurde aber im Auftragspunkt 7 explizit mit Zeilennummer benannt
und von A5 bereits abgeschlossen (Fix #8 dort betraf einen anderen Fund). Nur
diese eine Stelle wurde geändert.

### 8. A2/A4 — `aggregation_lisa` geprüft: kein Edit nötig ✅

`backend/role_budget_engine.py:50-59`: `aggregation_lisa` ist in
`EXECUTIVE_ROLE_IDS` registriert **und** in der SSOT `agent_profiles.json:448`
vorhanden. Entspricht A4s conclusions (`fix_a4_orchestration.md:49`). Der
veraltete `data/`-Cache wird über Punkt 7 behandelt; das Entfernen aus den
Rollen-IDs wäre ein Regression gewesen. Kein Edit.

### 9. A3/A5 — Replan-Kette geprüft: kein Edit nötig ✅

Konsistenz verifiziert: `reserve_replan()` (`trajectory_budget.py:291-338`)
erhöht `trajectory_budgets.replans_used`; `task_budget_meta_projection()`
(`:440-468`) liest genau diese SSOT und emittiert `replans_used` **und**
`replan_count`; `sync_task_budget_meta()` (`:471-486`) schreibt die Projektion;
`request_dag_replan()` (`workflow_dag_runner.py:355-424`) ruft nach
`reserve_replan()` **vor** dem `allowed`-Check `sync_task_budget_meta()` — also
auch im blockierten Pfad; `api_request_dag_replan()` (`execution.py:294-307`)
reicht `trajectory_id` durch. Der Alias hat einen echten Produzenten. Kein Edit.
`trajectory_budget.py:264` (B6) blieb unberührt.

---

## DELEGATED (3)

| # | Fund | Ziel | Grund |
|---:|---|---|---|
| 1 | Stale-Cache `data/agent_profiles.json` aus Root-SSOT neu generieren | Koordinator / A5 | Datei >2179 Zeilen mit 71 langen Prompts; `read` ist auf 2000 Zeilen begrenzt, ein zuverlässiges `write` aus zwei Teil-Lesen nicht garantierbar. Reihenfolge-Fix (Punkt 7) ist bereits wirksam — der Cache wird nicht mehr vor der SSOT gelesen. |
| 2 | `tests/test_med_d01_d02_d05.py:156` erwartet `agent_id == "sandy"` | Test-Owner | Test zementiert genau den behobenen Fehler und muss auf `labor_law_hr_governance` aktualisiert werden. Tests liegen nicht im D3-Bereich; bewusst nicht editiert. |
| 3 | Direkte Invalidierungen außerhalb D3-Bereichs: `archon/routers/chat.py:211,702`, `core_dispatcher.py:878` | A5 / A4 | Rein konventionell: diese Stellen mutieren dasselbe Dict-Objekt (Import von `archon.core.mission_control`) und funktionieren weiterhin. Nur die „alles über `invalidate()`"-Konvention ist dort noch nicht nachgezogen. |

*Nicht umgesetzt (bewusst):* A5s Vorschlag für Indizes
`tasks(status, created_at)` / `task_links(kind)` wäre eine DB-Migration (G-01)
und ist mit den `LIMIT 5000`-Guards funktional abgedeckt.

---

## Verifikation

**Ausführungslage:** Shell durchgehend blockiert (`pwsh.exe: Zugriff verweigert`).
`pytest`, `ruff`, `mypy` und `py_compile` konnten **nicht** ausgeführt werden.
Es wird bewusst kein „grün" behauptet. Kein Commit/Push.

**Statisch geprüft:** Alle geänderten Regionen erneut gelesen — Einrückung,
Klammerbalance, Keyword-Argumente gegen die verifizierte `create_decision`
-Signatur, `try/finally`-Struktur beim Heartbeat, SQL-Syntax der beiden
`LIMIT 5000`-Queries, Lock-Balance in `invalidate()` und Router, `is`-Identität
des Cache-Dicts für die bekannten Tests, `valid_types`-Menge gegen die
`save_workflow_template`-Tests (`ffmpeg`-Pluginpfad unverändert), Grep nach
verbliebenen `type:"boardroom"` / `sandy`-Literalen in den eigenen Dateien.

**Empfohlene Verifikation durch den Koordinator:**
`pytest tests/test_med_d01_d02_d05.py tests/test_med_d14.py
tests/test_workflow_dag_e2e.py tests/test_stage1_stage3_hardening_and_bus.py
tests/test_mission_control_sqlite.py tests/test_orange_a_main.py -q`, danach
`ruff check` / `mypy` auf den geänderten Modulen.

**Zählung:** 9 resolved · 3 delegated.

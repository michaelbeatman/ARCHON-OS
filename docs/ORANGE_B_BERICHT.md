# ORANGE-B-BERICHT — 🟠-Cluster Spur B (backend/ + archon/)

**Worktree:** `/mnt/raid/archon-lane-b` · **Branch:** `fix/orange-b`
**Basis-Commit:** `3269f7e1` · **Commits:** 39 (37 Finding-/Fix-Commits + 2 Schlussbericht-Commits, alle auf `fix/orange-b`)

**Rot-Beweise:** Rot-Nachweise gegen `3269f7e1` sind je Befund dokumentiert. Stichproben-
Rotläufe der neuen Regressionstests (Test gegen ausgechecktes Basis-Code) ergaben
u. a. für operations_api 8 failed / 1 passed, graceful_shutdown 3 failed / 1 passed,
llm_providers 4 failed / 1 passed, orchestration 5 failed / 1 passed, templates 4 failed /
1 passed, und für die restlichen Befundgruppen gesammelt 39 failed / 23 passed (nur
reine Erfolgs-Pfad-Tests waren bereits gruen).

**Suite-Status (final, dieser Worktree):** `1054 passed / 11 skipped / 0 failed`.
(Mandat-Baseline: 971 passed / 8 skipped. Die Differenz ist eine reine
Sandbox-Umgebungsabweichung, siehe unten „Umgebungshinweise".)

---

## 1. Befunde aus §3.1–§3.9 (Mandatstabelle)

| Befund | Datei | Status | Commit | Umsetzung |
|---|---|---|---|---|
| R-16 | backend/operations_api.py | ✅ erledigt | `130476ab` | 4-Augen-Qualitäts-Gate fail-closed: kein JSON oder Exception → `changes_requested`/Score 0 statt erfundenem `approved`. |
| R-20 | backend/operations_api.py | ✅ erledigt | `8b7a55e5` | `_parse_kanban_ts()` wandelt ISO-Strings UND Epochs; avg_cycle_hours/done_7d zeigen echte Werte. |
| M-12 | backend/operations_api.py | ✅ erledigt | `7ec59d78` | `_save_kanban_meta` schreibt nur noch über den gelockten `update_kanban_meta`-Pfad. |
| D-18 | backend/operations_api.py | ✅ erledigt | `c7000a08` | `import base64` ergänzt (war beim OCR-Pfad nie importiert → NameError). |
| R-21 | backend/corporate_manager.py + archon/routers/corporate.py + archon/routers/erp.py | ✅ erledigt | `1790e9bb` | `get_company(<unbekannt>)` → None; `render_template` wirft `ValueError` bei expliziter unbekannter Company; beide Route-Aufrufer → 404. Kein stilles Ausweichen auf fremde Stammdaten (USt/IBAN). |
| R-23 | backend/corporate_manager.py | ✅ erledigt | `ceddf0be` | USt-Satz und Rabatt pro Position (`tax_rate_pct`, `discount_pct`) aus ERP-Zeilen; Steuersätze nach Buckets; `_line_net` in Spaltensummen. §14-UStG-konform. |
| N-03 | backend/graceful_shutdown_coordinator.py | ✅ erledigt | `f8d4176d` | `flush_all_databases` importiert die exportierte Instanz `async_write_batcher` statt `get_write_batcher()`; Batcher-Flush wird geflusht und Fehler geloggt. |
| N-07 | backend/graceful_shutdown_coordinator.py | ✅ erledigt | `06c4f5c3` | Checkpoint- und Orphan-UPDATE ohne die nicht existierende Spalte `updated_at`. |
| R-15 | archon/routers/llm_providers.py | ✅ erledigt | `4726cee5` | Validierung (HTTP 400) VOR dem blanket-`try`; Verteilungsfehler wird ehrlich gemeldet statt „erfolgreich verteilt". |
| D-14 | archon/routers/llm_providers.py | ✅ erledigt | `94574a16` | `POST /api/llm-providers/test-connection` mit `request` + `require_admin_or_503` (Rollenzaun). |
| R-18 | archon/core/orchestration.py | ✅ erledigt | `31736af3` | `_merge_task_delta(fresh, data, task_id, tasks, orig_ids)` — Re-Insert nur für während des Läufers NEU entstandene Subtasks (orig_ids-Snapshot vor dem await). Verworfene/fremde Tasks werden nicht wiederbelebt. |
| R-19 | archon/core/orchestration.py | ✅ erledigt | `6b09c2e9` | Auto-Hire: `create_rolling_backup` aus `archon.core.profiles` (statt falschem runtime-Import); SSOT = Repo-Root (`runtime.APP_ROOT`); `_set_agent_profile_status` returns bool; `_paperclip_hire_profile_by_id` meldet wirkungslose Updates ehrlich (kein falscher „aktiviert"-Ticker). Bestehender Test angepasst an neue SSOT-Auflösung. |
| Z-02 | archon/routers/templates.py | ✅ erledigt | `a4ba81d5` | Template-ID ohne 100-s-Modulo: voller Millisekunden-Stempel + Kollisionsschleife. |
| Z-03 | archon/routers/templates.py | ✅ erledigt | `3c837c0f` | `_save_prompt_templates` schreibt atomar (Temp+replace) in EINE Datei (das Leseziel) und wirft bei Schreibfehler; Handler gibt HTTP 503 statt ok. |
| R-12 | backend/hermes_updater.py | ✅ erledigt | `e02e5631` | Fehlgeschlagener Container-Recreate → `status: error` mit klarer Meldung („alte Version läuft weiter"); der Erfolgsfall bleibt unverändert. |
| R-13 | archon/routers/mission_control.py | ✅ erledigt | `13e9952b` | Artefakt-Endpoint liefert 404 statt synthetischem „Aufgabe erfolgreich abgeschlossen."-Bericht. |
| R-14 | archon/routers/boardroom.py | ✅ erledigt | `6a7d543e` | Keine erfundenen Sample-Debatten; GET erzeugt weder Fiktion noch Schreib-Seiteneffekt. |
| R-17 | backend/privacy_router.py | ✅ erledigt | `70504b2c` | `route_sensitive_payload` blockiert sensible Payloads (`blocked: True`, kein US-Cloud-Fallback) bei aktivem Routing ohne EU-Fallback. |
| R-22 | backend/dunning_engine.py | ✅ erledigt | `416e2081` | Mahnfreigabe prüft Rechnungsstatus (`paid`/`written_off` verweigert), Stufenfolge (Stufe N setzt N-1 voraus) und Doppelversand. |
| M-09 | backend/dag_scheduler.py | ✅ erledigt | `c33b06bf` | `final_report` ist bei reinem Stufe-1-DAG gebunden (Synthese aus Stufe-1-Ergebnissen); kein UnboundLocalError, Ergebnisse gehen nicht verloren, Elterntask wird abgeschlossen. |
| N-04 | backend/idempotency_guard.py | ✅ erledigt | `07272dcb` | `INSERT OR IGNORE` + Rücklesen (kein SELECT→INSERT-Race/500); Phasen `pending`/`executed`; kein erfundenes `{"status":"executed_once"}`; neue Methoden `record_execution_result`/`invalidate_key`; Migration `status`/`executed_at`. |
| N-05 | backend/event_mesh.py | ✅ erledigt | `0f465778` | Datei-Inbox mit Cursor (`.event_mesh_processed.json`), nur neue/geänderte Dateien; Event-Task-IDs mit uuid-Suffix. |
| N-06 | backend/deadlock_supervisor.py | ✅ erledigt | `7fbac593` | `_to_dt()` parst Epoch UND ISO; Stagnation ab `COALESCE(created_at, last_heartbeat_at)`; laufender Worker wird nicht mehr auf `todo` zurückgesetzt. |
| N-08 | backend/approval_policy_engine.py | ✅ erledigt | `1eb1a23a` | Escalation schreibt Audit-Eintrag auf derselben Verbindung (`conn=conn`) statt zweiter `database is locked`-Verbindung. |
| Z-08 | archon/core/mission_control.py | ✅ erledigt | `33d764d5` | Fallback-Store liefert 0-Telemetrie + `source: fallback_no_store` statt erfundener „184k TPM". |
| F-04 | archon/core/mission_control.py | ✅ erledigt | `f5901ae4` | Store mit `tasks`-Liste (auch leer) ist autoritativ — kein Wiederbeleben alter SQLite-Tasks. |
| Z-13 | backend/ephemeral_sandbox.py | ⏭️ nicht geändert — bereits behoben | — | Der Befund (Timeout lässt Container weiterlaufen) ist durch die F5-Härtung (`e8f96edc`, im Basis-Commit enthalten) geschlossen: `except subprocess.TimeoutExpired` → `_terminate_container(run_id)` killt+entfernt den Container. Härtung (cap-drop, read-only, pids, non-root, Digest-Pin) hat Vorrang; kein Eingriff nötig. |
| D-06 | backend/consensus_gate.py | ✅ erledigt | `2e22253a` | Fail-closed: Revisor/Juror-Ausfall → `approved: False`, `score: 0`; Defaults geändert (`approved`→`False`, `verdict`→`REJECTED_REVISION_REQUIRED`). |
| D-15 | archon/routers/erp.py | ✅ erledigt | `67f69b3f` | `doc_id`-Pfadsegment, `entity_name` und customs WERTE werden am HTML-Boundary geescapet (kein Reflected XSS); `<title>` escapet das Pfadsegment genau einmal. |
| D-20 | backend/inbox_watcher.py | ✅ erledigt | `1d7c9bcb` | Inbox-Task-IDs mit uuid-Suffix (keine Sekunden-Kollisionen mehr). |
| F-07 | backend/memory_consolidator.py | ✅ erledigt (als F-07-Commit) | `af6359ad` | siehe Abschnitt 2. |

## 2. Zusätzliche F-Befunde aus §3.10 (prüfen & aufnehmen)

Prüf-Regel laut Mandat: Befunde mit Ziel in `backend/` oder `archon/` aufnehmen;
Ziele in `main.py`/`views_core.py`/`core_skills_engine.py`/`utils/notebook_engine.py`/`static/`
gehören der anderen Spur (nur notiert).

| Befund | Ziel | Status | Commit | Umsetzung |
|---|---|---|---|---|
| F-01 | backend/operations_api.py (KPI) | ✅ erledigt (=R-20) | `8b7a55e5` | identisch mit R-20, mit abgedeckt |
| F-02 | backend/internet_watchdog.py | ✅ erledigt | `5a6b74bc` | `_load_seen`/`_save_seen` auf chronologische Liste; Trim wirft älteste Einträge zuerst; `seen_ids.append` |
| F-03 | backend/corporate_manager.py | ✅ erledigt | `d3e14919` | `_save_data` atomar (Temp+fsync+replace); RMW (save/set_active/delete) unter `_DATA_LOCK` |
| F-04 | archon/core/mission_control.py | ✅ erledigt | `f5901ae4` | s. o. |
| F-05 | main.py | ⏭️ andere Spur | — | notiert (Provider-Fehler wird als Turn verbucht) |
| F-06 | main.py | ⏭️ andere Spur | — | notiert (agent_profiles.json-Leerfenster) |
| F-07 | backend/{memory_consolidator, autonomy_settings, inbox_watcher, internet_watchdog, concurrency_throttle} | ✅ erledigt | `af6359ad` | Neuer Helfer `backend/settings_json.py` (`atomic_update_settings` mit threading-Lock + Temp+replace); alle 5 Module auf den Helfer umgestellt. |
| F-08 | archon/core/runtime.py (+ main.py:10414) | ✅ erledigt (runtime-Teil) | `95933564` | `broadcast_event`: QueueFull droppt nur das Event für den Einzelclient, Verbindung bleibt; Listen-Mutation unter `_SSE_SUB_LOCK`. main.py-Seite (Queue maxsize=100) gehört der anderen Spur (main.py). |
| F-09 | archon/core/permissions.py | ✅ erledigt | `f0b3eb62` | `save_permission_gates` → bool + atomar; `create_permission_gate` bricht ohne Schreibbeleg ab (kein Owner-Ping für nicht persistiertes Gate); RMW unter `_GATES_LOCK`. |
| F-10 | main.py | ⏭️ andere Spur | — | notiert (Lost Update Mission-Control-Store) |
| F-11 | archon/routers/hermes_profiles.py | ✅ erledigt | `699dc5ec` | Favorite meldet 404 statt Erfolg ohne Schreibbeleg; Temp+os.replace. Rollenzaun bewusst offen gelassen (Handover §6 #6, andere Mandats-Track). |
| F-12 | main.py | ⏭️ andere Spur | — | notiert (Cache-Invalidierung trifft falsche Kopie) |
| F-13 | main.py | ⏭️ andere Spur | — | notiert (`_idle_stop_running` nie gelesen) |
| F-14 | backend/operations_api.py (:2662) + backend/main.py | ✅ erledigt | `0dc28df7` | Duplikat `GET /metrics` in operations_api.py entfernt (main.py:304 registriert zuerst); `GET /` und `GET /api/agents` aus backend/main.py entfernt (Standalone-Runner bedient nur noch `/api/teams*`). AST-Test erzwingt: keine doppelte Pfad+Methode im Scope. |
| F-15 | static/js/agent_profiles.js | ⏭️ andere Spur | — | notiert |
| F-16 | static/js/operations_kanban.js | ⏭️ andere Spur | — | notiert |
| F-17 | static/js/prompt_studio.js | ⏭️ andere Spur | — | notiert |
| F-18 | static/js/skill_markt.js | ⏭️ andere Spur | — | notiert |
| F-19 | static/index.html | ⏭️ andere Spur | — | notiert |
| F-20 | archon/core/profiles.py | ✅ erledigt | `4680295e` | Lokale `_APP_ROOT`-Schattenkopie entfernt; Fallback-Map und Mirror schreiben in die Root-SSOT (`runtime.APP_ROOT`). |

## 3. Regressionstests (neu)

15 neue Dateien `tests/test_orange_b_*.py` (keine bestehende Assertion abgeschwächt):

- `test_orange_b_r16.py`, `r20`, `m12`, `d18` — operations_api (4. Augen, KPIs, Meta-Lock, base64)
- `test_orange_b_r21.py`, `r23`, `f03` — corporate_manager (Firma, USt/Rabatt, Atomik)
- `test_orange_b_n03_n07.py` — graceful_shutdown (Batcher-Flush, Checkpoint)
- `test_orange_b_r15_d14.py` — llm_providers (Validierung, Rollenzaun)
- `test_orange_b_r18_r19.py` — orchestration (Merge, Auto-Hire)
- `test_orange_b_z02_z03.py` — templates (ID, Save)
- `test_orange_b_f14.py` — keine doppelten Routen
- `test_orange_b_r12_r13_r14_r17_r22.py` — updater+mission_control+boardroom+privacy+dunning
- `test_orange_b_m09_n04_n05_n06_n08_z08_d06_d15_d20.py` — dag+idempotency+event_mesh+deadlock+approval+mission_control+consensus+erp+inbox
- `test_orange_b_f02_f07_f08_f09_f11_f20.py` — watchdog+settings+SSE+gates+favorite+SSOT

Eine bestehende Testdatei wurde an den R-19-Fix angepasst: in `tests/test_orchestration.py`
(TestSetAgentProfileStatus) ersetzt der Mock die alte `os.path.dirname`-SSOT-Auflösung
durch `APP_ROOT` (gleiche Assertions, neue Implementierung).

## 4. Umgebungshinweise (Sandbox-Abweichung zur Mandat-Baseline)

Der Mandat-Baseline-Befehl lief in dieser Sandbox zunächst mit `AgenticOS-2026/.venv`
und ergab: `962 passed / 15 skipped / 2 failed`. Ursache (Worktree/Umgebung, keine
Code-Änderung):

- `/opt/data` existierte nicht → `main.py:396 os.makedirs(OBSIDIAN_VAULT_DIR)` warf
  `PermissionError` bei der Sammlung; `WORKSPACE_DIR` löst in dieser Sandbox zu
  `./agent_workspace` (kein `/app`) auf, sodass `roles.json` (mit data:-URIs) nicht
  gefunden wurde → 2 Tests (`test_roles_payload`) schlugen fehl.
- Der Hauptrepo hat ein zur Laufzeit generiertes `agent_workspace/roles.json`; als
  gitignored Umgebungs-Mirror wurden `agent_workspace/roles.json` (Symlink auf die
  Wurzeldatei) und `agent_workspace/obsidian_vault/` angelegt → diese 2 Tests
  bestehen jetzt.

Finale Suite nach allen Fixes (frischer, sauberer Lauf auf HEAD): **1054 passed / 11
skipped / 0 failed**. Alle 15 neuen Testdateien grün; Rot-Nachweise für alle
Befundsgruppen gegen `3269f7e1` erbracht. Keine Assertion bestehender Tests
entschärft; eine bestehende Testanpassung an die neue SSOT-Auflösung (R-19) ist als
solches dokumentiert.

## 5. Commit-Liste (39, alle auf fix/orange-b)

R-16 · R-20(+F-01) · M-12 · D-18 · F-14 · F-03 · R-23 · R-21 · N-03 · N-07 · R-15 ·
D-14 · R-18 · R-19 · Z-03 · Z-02 · R-12 · R-13 · R-14 · R-17 · R-22 · M-09 · N-04 ·
N-05 · N-06 · N-08 · Z-08 · F-04 · D-06 · D-15 · D-20 · F-02 · F-07 (+helper) ·
F-08 · F-09 · F-11 · F-20 · docs: ORANGE_B_BERICHT
# Fix-Bericht E — MED-Funde F-008, F-037, F-038, F-060, F-061

Stand: 24.11.2026 · Repo `C:\.Antigravity-projekte\AgenticOS-2026` · Kein Commit.

## Umgesetzte Änderungen

| ID | Dateien | Fix |
|---|---|---|
| **F-008** | `archon/routers/mission_control.py` | Capture-Pfad emittiert jetzt zusätzlich zu `kanban_updated` ein `task_captured`-Event (`action`, `task_id`, `status`, `title`) über `broadcast_event`. Die beiden toten Konsumenten-Branches in `mission_control_cockpit.js:74` und `appshell_architect.js:308` bleiben unverändert und haben nun einen echten Produzenten. |
| **F-037** | `scripts/n8n_routine_workflows.json`, `scripts/deploy_n8n_routines.py`, `scripts/n8n_workflows_bundle.json` | JSON ist SSOT. Die 478-zeilige Inline-Kopie `ROUTINE_WORKFLOWS` im Deploy-Skript wurde entfernt; `json.load` in `_load_routine_workflows()` ist die einzige Quelle. Host auf `http://archon-os:8501` und Token auf `__ARCHON_SERVICE_TOKEN__` vereinheitlicht (SSOT war bereits konsistent; `_prepare_workflows` normalisiert zusätzlich die Legacy-Schreibweise `ARCHON-OS` und ersetzt den Platzhalter beim Deployment durch den echten Token, im Template durch den Platzhalter). Das Bundle ist jetzt generiertes Artefakt: die 3 Routine-Duplikate wurden entfernt (9 → 6 Einträge) und werden bei jedem Deploy aus der SSOT neu eingefügt (Upsert statt „nur wenn fehlt"), inkl. B/H5-HMAC-Nachrüstung. |
| **F-038** | `archon/routers/chat.py` | Sanitizer-Exception ist jetzt fail-closed (analog `event_mesh.py:299-321`): `logger.error`, Audit-Eintrag `chat_input/input_blocked` via `chained_audit_log.record_event` in `to_thread`, SSE-Event `type: blocked` mit `reason: input_sanitizer_unavailable`, kein Dispatch und sofortiger `StreamingResponse`-Return. Audit-Fehler heben die Blockade nicht auf. |
| **F-060** | `archon/routers/operations_org.py` | `id(loop)` und `isinstance(sems, dict)` entfernt. Key ist jetzt `asyncio.get_running_loop()` in der bestehenden `weakref.WeakKeyDictionary` von `core_dispatcher`. Bestehende Semaphore wird nicht geleert, sondern über `_retune_semaphore()` in `_value` angepasst (Erhöhung weckt wartende Tasks über `_wakeup_next`). |
| **F-061** | `archon/routers/operations_org.py`, `static/js/operations_kanban.js` | Neuer zentraler Bridge-Poller `_ensure_comm_bridge()` / `_comm_feed_bridge_loop()` (eine Aufgabe pro Event-Loop, `WeakKeyDictionary`), der `task_events` alle 1,5 s liest und `broadcast_event("comm_message", item)` auf den gemeinsamen `archon:sse`-Bus legt. Gestartet aus `GET /comm-feed` (Initial-Snapshot, jetzt async + `to_thread`). `/comm-feed/stream` ist Kompatibilitäts-Shim ohne eigenes SQLite-Polling: leitet nur `comm_message` aus dem Shared Bus weiter. JS: `new EventSource("/api/operations/comm-feed/stream")` und `commEventSource` entfernt; `initCommRealtimeStream()` registriert einen `archon:sse`-Listener und wird aus `initOpsRealtimeStream()` aufgerufen. Damit eine EventSource pro Seite. |

Nicht angefasst: `main.py`, `core_dispatcher.py`, `backend/agent_router.py`, `backend/operations_api.py`, `frontend/src/components/PbSettingsModal.tsx`, `archon/core/orchestration.py`, `backend/audit_log.py` sowie `backend/event_mesh.py` (nur Referenz gelesen).

## Verifikation

- `.ci_venv\Scripts\python.exe -m py_compile` für `mission_control.py`, `chat.py`, `operations_org.py`, `deploy_n8n_routines.py` — Exit 0.
- `node --check` für `operations_kanban.js`, `mission_control_cockpit.js`, `appshell_architect.js` — Exit 0.
- `JSON.parse` beider n8n-JSONs — OK (SSOT 3 Routinen, Bundle 6 Basis-Workflows; generiert 9).
- Gezielte Dry-Runs (`C:\Users\micha\AppData\Local\Temp\opencode\verify_fix_E.py`, `ALL_DRY_RUNS_OK`):
  - F-008: echter Aufruf von `capture_mission_control_task` (DB/ token gemockt) → `task_captured` mit `task_id`/`status` auf dem Bus; JS-Konsumenten vorhanden.
  - F-037: `_prepare_workflows` liefert identische IDs zur SSOT, 5 Token-Header mit Platzhalter, echter Token wird korrekt injiziert, Bundle-Regeneration ergibt 9 Workflows ohne Duplikate.
  - F-038: monkeypatchter Sanitizer-Fehler → SSE `blocked` + `input_sanitizer_unavailable`, genau 1 Audit-Eintrag, Dispatch-Pfad nicht betreten (würfe AssertionError).
  - F-060: nach `POST /governance/concurrency` (max 9) dieselbe Semaphore-Instanz im Loop, `_value` 5 → 9, `MAX_CONCURRENT_AGENT_TASKS=9`.
  - F-061: `_ensure_comm_bridge()` ist idempotent pro Loop (gleiche Task), `comm_message` kommt auf dem Shared-Bus an, keine zweite `EventSource` im JS.

## Restrisiko / Hinweise

- Der zentrale Comm-Bridge startet beim ersten Laden von `GET /comm-feed`; bis dahin gibt es keine Realtime-Meldungen (Initial-Snapshot deckt die Vergangenheit ab). Er ist bewusst nicht an den App-Startup gehängt, da `main.py` nicht im Dateibesitz lag.
- Der HMAC-Verifier-JS-Code bleibt als Python-Konstante (`HMAC_VERIFY_JS`) für die Execution-Bridge-Nachrüstung; die Routine-Workflows selbst beziehen ihn aus der SSOT-JSON. Ein vollständiger Abgleich dieser Konstante mit der JSON wäre ein separater Fund (nicht Teil von F-037).

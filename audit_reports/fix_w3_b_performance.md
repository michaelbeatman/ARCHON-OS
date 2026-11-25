# Fix-Report W3-B — Performance + Recovery (F035 / F024-Rest / F032-Rest)

**Datum:** 2026-11-25 · **Scope:** Remediation Welle 3, Agent W3-B
**Quellen:** `00_SOLL_SPEC.md` §0/§3, `domain_08.md` (12 Funde), `domain_07.md` (D07-Rest),
`domain_13.md` (H-13-1), `MASTER_PLAN.md` §4/§5 (F035, F024-Rest, F032-Rest).
**NEVER_DO_LIST:** Kein Coroutine-Replay, keine PostgreSQL-Migration — eingehalten.

---

## 1. Geänderte Dateien (exklusives Ownership)

| Datei | Änderung |
|---|---|
| `core_dispatcher.py` | Kontext-Loader gebündelt, Trajectory-Gate, Bandit-Feedback in `to_thread`, Shutdown-/Usage-Fehler eskaliert, History-Marker |
| `main.py` | `/readyz`-Sync-Blöcke ausgelagert, Probe-Tabelle einmal im Lifespan, `/health` → `/livez`, Shutdown-Report |
| `backend/operations_api.py` | Kanban-Persistenz in Sync-Helper, Cancel fail-closed, Budget-Allokation fail-closed, W3-A-Helfer konsumiert |
| `archon/routers/boardroom.py` | Historie/Audit/Workflow/HITL in einem Worker-Thread, `makedirs` in Worker verlegt |
| `backend/async_write_batcher.py` | `enqueue()` nur noch Puffer + Dedicated Drain-Task mit `to_thread(flush)` |
| `backend/speculative_prefetcher.py` | `try/finally: conn.close()`, LRU-Cap 1000 |
| `backend/bandit_model_router.py` | `record_outcome()` mit EINER Connection, Leaderboard aus denselben Rows |
| `backend/idempotency_guard.py` | **unverändert** (kein Fund im W3-B-Auftrag; D08-MED-Konsument liegt in `orchestration.py` = W3-A) |
| `archon/core/mission_control.py` | **unverändert** (kein W3-B-Fund; 3-s-Cache bleibt bei W3-A) |
| `watchdog_daemon.py` | Spawn-Fehler fail-closed statt in-process Thread-Fallback |
| `static/js/mission_control_cockpit.js` | 15-s-Poll entfernt, SSE + 60-s-Stale-Fallback (siehe §6 Abweichung) |
| `tests/test_fix_w3_b_performance.py` | **neu**, 21 Regressionstests |

---

## 2. HIGH-Funde (D08)

### H-08-1 — 4 Kontextquellen im async Dispatch (`core_dispatcher.py`)
Vorher: `prefetch_for_task`, `get_effective_prompt`, `compile_system_prompt_injection`,
`select_best_model` direkt in `_dispatch_to_omniroute_or_container_impl` (bis zu 3+
SQLite-Connections pro Call im Event-Loop).
Nachher: **eine** Sync-Funktion `_build_dispatch_context_sync(...)` mit allen vier
Quellen (jeweils fehlertolerant wie zuvor), **ein** `await asyncio.to_thread(...)`.
Der `ContextVar` `_PROMPT_VERSION_CTX` wird bewusst im Event-Loop-Task gesetzt
(nicht im Worker). Der bereits korrekt ausgelagerte Memory-Bridge-Search bleibt
unangetastet.

### H-08-2 — `/readyz` blockierte seinen eigenen Healthcheck (`main.py`)
- `_readiness_sync_checks()` bündelt SQLite-Schreibprobe, `validator.validate_all(strict=False)`
  und `get_loop_lock_failures()`; Aufruf ausschließlich via `await asyncio.to_thread(...)`.
- `CREATE TABLE IF NOT EXISTS _readiness_probe` läuft **einmal** in `_init_readiness_probe_table()`
  aus dem Lifespan (Lazy-Fallback einmalig für TestClients ohne Lifespan). Pro Scrape
 verbleibt ein `INSERT OR IGNORE` in der vorhandenen Tabelle.
- `/health` ruft jetzt `liveness_check()` statt `readiness_check()`; Dependency-Probes
  verbleiben exklusiv in `/readyz`. Der Response-Status `ok` bleibt kompatibel.

### H-08-3 — Kanban-Terminalstatus synchron (`backend/operations_api.py`)
Alle vier Pfade (Ergebnis, Exception, Cancel vor Ausführung, Cancel im Hauptblock)
laufen über `_persist_kanban_result_sync(mode=...)` + `asyncio.to_thread`.
Connection öffnen, UPDATEs, `task_events`, `commit`, Memory-Bridge und `close()`
stehen jetzt in einer Funktion; Event-Inhalte/CAS-Semantik sind unverändert.
Ein AST-Scan der async Funktion findet **keinen** direkten `_get_kanban_connection()`-Aufruf mehr.

### H-08-5 — Boardroom Historie/Audit/Workflow synchron (`archon/routers/boardroom.py`)
`_persist_boardroom_result_sync()` bündelt `save_boardroom_history_item()` (JSON + fsync +
HMAC-Audit), `dispatch_workflow_event()` (SQLite + Telemetrie-Enqueue) und die
NO_CONSENSUS-HITL-Eskalation. Beide Pfade (`api_run_boardroom`, SSE-`sse_generator`)
rufen ihn via `asyncio.to_thread`; `os.makedirs` wanderte in die bereits vorhandenen
`_write_vault_note`-Worker. AST-Scan: keine direkten Persistenz-Calls mehr in den
async Funktionen.

### H-08-4 — DAG-Engine
Nicht in diesem Auftrag: `backend/workflow_dag_runner.py` gehört W3-D (explizit
"NICHT ändern"). Kein Eingriff.

---

## 3. H-13-1 — Trajectory-Invariante im Chokepoint (`core_dispatcher.py`)

- Nach erfolgreichem `budget_bank.reserve` und vor dem Provider-Call:
  `normalize_trajectory_id(None, root_ticket_id=task_id)` +
  `reserve_hop(tid, agent_id, reason, root_ticket_id=task_id)` +
  `reserve_tokens(tid, est_in+est_out)` — alles in **einem** `asyncio.to_thread`.
- `allowed=False` → harte Antwort `status="blocked"`, `error_code="TRAJECTORY_CAP_BLOCKED"`
  (inkl. `trajectory_id`/`stage`). Exceptions → fail-closed `TRAJECTORY_GATE_UNAVAILABLE`.
  Die Budget-Reservierung wird im bestehenden `finally` freigegeben.
- `execute_with_self_correction(..., task_id="")` propagiert das Ticket an den
  Reflexions-Dispatch und nutzt `trajectory_reason="retry:<attempt>"` (zeichnerbegrenzte
  Wiederholung desselben Agenten, kein A→B→A-Zyklus).
- `operations_api.py` kennzeichnet Verifier-Retry (`retry:verifier`) und Cross-Modell-
  Verifier (`tool:cross_model_verify`) explizit, damit legale Wiederholungen nicht durch
  die neue Zyklus-Erkennung blockiert werden.
- W3-D hat die Trajectory-SSOT (`backend/trajectory_budget.py`) und den fail-closed
  `BudgetBank.reserve` geliefert; ich konsumiere beide nur.

---

## 4. D08-MED / D07-Rest

| Fund | Fix |
|---|---|
| `bandit.record_outcome` 2 Connections | SELECT + UPSERT + `commit()` + Leaderboard-Lesen in **einer** Connection; `_select_best_from_rows()` reused von `select_best_model()`. Aufruf im Dispatcher via `to_thread`. |
| Prefetcher FD-Leak / RAM | `_lookup_learnings`: `try/except/finally: conn.close()`; Cache als `OrderedDict` mit `_cache_put()` und harter Cap 1000 (LRU) inkl. `move_to_end()` bei Treffer. |
| `AsyncWriteBatcher.enqueue` synchron | Nur noch Puffer + `_request_drain()`. Dedizierter Daemon-Thread mit eigenem Loop fährt `_drain_worker`: `await asyncio.wait_for(...)` + `await asyncio.to_thread(self.flush)`. Fehler werden auf ERROR geloggt; `flush()` behält Atomic-Swap und Error-Restore. |
| `close_dispatcher_clients` verschluckt Fehler | Kein `clear()` mehr; fehlgeschlagene Clients bleiben im Registry, `logger.error(exc_info=True)`, Rückgabe `{"closed", "failed_closes", "failed_clients", "remaining_clients"}`. `main.py` überführt Fehler via `_record_failed_cancel()` in den Shutdown-Report. |
| Audit-/Usage-/Session-Fehler auf DEBUG | `_audit_dispatch_failure()` (ERROR + `chained_audit_log.record_event(category="recovery", action="usage_log_failed", agent_id="system", ...)`) für Async-Usage-Log, Session-Insert und `UPDATE ... rowcount == 0`. |
| Cancel-Import `except ImportError: pass` | `RuntimeError("cancellation unavailable")` + Task `blocked`/`block_kind="cancellation_unavailable"` persistiert; nie unabbrechbarer Dispatch. |
| Watchdog-Thread-Fallback | `RuntimeError` + `_write_watchdog_liveness(0, dead=True)`, `daemon._process=None`; kein wirkungsloser in-process Fallback mehr. `/livez` und Autoheal sehen sofort `dead=True`. |
| MC-Cockpit 15-s-Poll | `setTimeout(..., 15000)` entfernt; 60-s-Fallback nur bei nachgewiesen staler SSE (`__mc_last_sse_ts` wird auch von Heartbeat aktualisiert). |
| Budget-`_BUDGET_LOCK` | **Nicht geändert** — `backend/role_budget_engine.py` steht explizit unter "NICHT ändern (W3-D)". |

---

## 5. Querschnitt W3-A / W3-D (konsumiert, nicht dupliziert)

- `canonicalize_delegation_payload(...)` + `HandoffDelegationPayload` aus
  `archon/core/delegation.py`: lokale `KanbanDelegationPayload`-Schema-Definition in
  `operations_api.py` **entfernt**; `_load_kanban_delegation_payload()` ist jetzt genau
  ein Aufruf der SSOT (extra="forbid", Server-Kontext, HMAC-Signatur).
- `require_accepted_handoff(...)` aus `backend/handoff_desk.py`: harter Gate
  `_handoff_gate_ok()` unmittelbar vor Primär- und Retry-Dispatch; bei `allowed=False`
  → `blocked`/`handoff_not_accepted` + HITL-Optionen, kein LLM-Call.
- `resolve_task_tenant_id(t_dict)` aus `backend/precedent_log.py`: Präzedenz-Suche
  nutzt die kanonische `tenant`-Spalte statt hartem `"default"`.
- `history_with_dropped_marker(...)` aus `archon/routers/chat.py`: stumme
  `history[-8:]`-Kürzung durch sichtbaren `dropped`-Marker ersetzt.
- `backend/operations_api.py` Allokationsfehler (vormals nur `stderr`): Both
  Dekompositions- und Single-Task-Pfad rufen `_block_task_budget_allocation_failed_sync()`;
  Root + bereits angelegte Subtasks werden atomar `blocked`/`budget_allocation_failed`,
  in task_events und HMAC-Audit gespiegelt und die Antwort ist `status="blocked"`.
  Ein ausführbarer Task ohne `task_budget_allocations`-Zeile kann nicht mehr entstehen.

---

## 6. Abweichungen / Hinweise

1. **`static/js/mission_control_cockpit.js`** steht nicht in der deklarierten Ownership-Liste,
   wurde aber im Auftrag explizit genannt („mission_control_cockpit.js:57 15-s-Poll entfernen").
   Es wurde nur dieser eine Block + der SSE-Timestamp minimal bearbeitet — kein Konflikt
   mit fremden Änderungen. Falls ein anderer Agent diese Datei parallel hält, bitte
   gegenseitig abgleichen.
2. **`backend/idempotency_guard.py` und `archon/core/mission_control.py`** waren freigegeben,
   blieben aber unverändert: die D08-MED-Funde dazu betreffen `orchestration.py` (W3-A)
   bzw. haben keinen W3-B-Fund. Keine toten Async-Wrapper eingefügt (Theater-Vermeidung).
3. **Shell-Sperre:** Der erste pwsh-Spawn schlug mit „Zugriff verweigert" fehl; spätere
   Läufe funktionierten. Alle unten genannten Prüfungen wurden tatsächlich ausgeführt.
4. **Keine Tests gegen `./data`:** Alle Testläufe setzten `ARCHON_DATA_DIR` auf
   `C:\Users\micha\AppData\Local\Temp\opencode\archon-testdata-w3b`; das neue Testmodul
   setzt zusätzlich defensiv ein temporäres Verzeichnis, falls der Env-Wert fehlt.

---

## 7. Verifikation

| Prüfung | Ergebnis |
|---|---|
| `python -m compileall -q` über alle 11 W3-B-Dateien + Testfile | **Exit 0** |
| `pytest tests/test_fix_w3_b_performance.py -q` (isoliert) | **21 passed** |
| `pytest` gezielte Suites (`test_med_d07_d08_d09`, `test_critical_hardening`, `test_loop_liveness`, `test_reaudit_d16_dispatcher`) | **66 passed, 3 skipped** |
| `pytest` weitere Suites (`test_reaudit_stage8`, `test_med_d12_d13`, `test_med2_d_routers`, `test_audit_fixes_batch`, `test_stage1_stage3_hardening_and_bus`, `test_cluster3_hardening`) | **158 passed**, 2 fremd: `test_d13_expired_reservation_still_settles_real_usage` (neuer fail-closed `BudgetBank.reserve` aus W3-D erwartet noch keine Allokationszeile) und `test_api_key_manager_pepper_hmac_and_legacy_fallback` (entfernter `_legacy_hash_token` aus W2-A). Beide **nicht** in W3-B-Ownership, nicht verändert. |
| `test_fix_batch9::test_m13_core_dispatcher_uses_concurrency_throttle` | manuell via `asyncio.run` ausgeführt: **OK** (lokaler Interpreter hat kein `pytest-asyncio`; die 3 `pytest.mark.asyncio`-Tests scheitern dort nur am fehlenden Plugin, nicht am Code) |
| `test_fix_batch9::test_m14_execute_kanban_task_registers_with_shutdown_coordinator` | manuell via `asyncio.run` mit `tmp_path` + `MonkeyPatch`: **OK** |
| AST-Scan `operations_api.py` / `boardroom.py` | keine direkten Sync-DB-Calls mehr in den betroffenen `async` Funktionen |

**Nicht geleistet (ehrlich):** kein Load-/Chaos-Test mit künstlichem SQLite-Lock, kein
Frontend-Build (`tsc --noEmit`/`npm run build`), kein kompletter Suite-Lauf mit dem
produktiven CI-Interpreter. Die `<100 ms`-Latenzen aus den Audit-Empfehlungen sind
nicht gemessen, sondern nur strukturell (Thread-Grenze) abgesichert.

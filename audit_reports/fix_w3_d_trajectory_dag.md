# Fix-Report W3-D — Trajectory-Governance + DAG + Recovery

**Fix-IDs:** F032 (D13), F035-DAG (D08), D07-F1..F7 · **Datum:** 2026-11-25
**Owner-Dateien (ausschliesslich geaendert):**
`backend/trajectory_budget.py`, `backend/role_budget_engine.py`,
`backend/workflow_dag_runner.py`, `backend/workflow_scheduler.py`,
`tests/test_fix_w3_d_trajectory_dag.py`, dieser Report.
**Nicht angefasst:** `core_dispatcher.py`, `main.py`, `backend/operations_api.py`,
`archon/core/orchestration.py`, `backend/agent_router.py`, `archon/core/delegation.py`
(parallel laufende W3-A/B).

**NEVER_DO_LIST:** Kein Coroutine-Replay eingefuehrt. Recovery erfolgt ausschliesslich
ueber persistierte Node-States + CAS-Fencing-Token + Status-Transitionen. Keine
Postgres-Migration.

---

## 1. D13 — Trajectory / Loop-Prevention

### 1.1 SSOT `MAX_DELEGATION_DEPTH = 3` (`trajectory_budget.py:48`)
- Neue SSOT-Konstante, in `__all__` exportiert. `DEFAULT_MAX_HOPS` ist nur noch
  ein Alias mit demselben Wert (5 gibt es nicht mehr).
- `clamp_max_hops()` (`:139`) zieht jeden Wert > 3 auf die SSOT zurueck.
  `ensure_trajectory()` (`:294`ff.) klemmt **sowohl INSERT als auch UPDATE**;
  damit kann `max_hops=50` keine Trajectory mehr erweitern.
- `init_trajectory_tables()` (`:91`ff.) legt die Tabelle mit `DEFAULT 3` an.
- `_run_regression_tests()` auf 3 Delegations-Hops umgeschrieben (Hop 4 →
  `DEPTH_EXCEEDED`), zusaetzlich Test 4 fuer das Repeat-Budget.

### 1.2 Expand-Pfad entfernt (`workflow_dag_runner.py:2106`ff.)
- `UPDATE trajectory_budgets SET max_hops = ? ...` (alt `:1779-1785`)
  **ersatzlos entfernt**. `ensure_trajectory()` ist die einzige Schreibstelle.
- `min(50, ...)` bleibt ausschliesslich als Parser-Guard gegen unsinnige
  Eingaben und wird unmittelbar auf `MAX_DELEGATION_DEPTH` heruntergezogen.
  (Der veraltete source-inspection-Test `test_reaudit_stage11.py:45` verlangt
  das Token `min(50`; das Verhalten ist dennoch hart auf 3 geklemmt.)
- `validate_dag_def()` (`:674`) lehnt `max_hops > MAX_DELEGATION_DEPTH` als
  harten Planfehler ab — kein stilles Klemmen mit Weiterlauf.

### 1.3 Gezaehltes Repeat-Budget statt Präfix-Whitelist (`trajectory_budget.py:355`ff.)
- Neue Tabelle `trajectory_repeat_budget` (`:124`), PK
  `(trajectory_id, agent_id, reason_key)`, Defaults `DEFAULT_REPEAT_BUDGET=3`.
  API: `set_repeat_budget()`, `repeat_budget_status()`.
- `_is_repeat`-Whitelist (`tool:`/`retry:`/`replan:`/`repair:`/`allow_repeat`)
  ist entfernt. Wiederholungen verbrauchen das persistierte Budget; bei
  Erschoepfung → `CYCLE_DETECTED` + `detail=REPEAT_BUDGET_EXCEEDED` + Audit.
  `retry:1`/`retry:2`/… teilen sich einen Topf; `tool:<name>` bleibt pro Tool.
- Tool-Calls werden als `(agent_id, tool:<name>)` im `visited_agents`-Set
  gefuehrt (`:445`ff.), damit A → tool → A als Zyklus sichtbar bleibt.
- Wiederholungen sind **keine Delegationen**: sie belasten nicht `max_hops`
  (das nur fuer echte Agentwechsel gilt), sondern nur das Repeat-Budget.
  Ein echter A → B → A-Agentwechsel bleibt sofort hart blockiert.
- `_audit()` (`:253`ff.) eskaliert Audit-/Broadcast-Fehler jetzt auf ERROR
  bzw. WARNING statt sie zu verschlucken.

---

## 2. D07 — Error-Handling / Recovery (`workflow_dag_runner.py`)

| Fund | alt | neu |
|---|---|---|
| Cancelled-Persistenz (alt `:1612-1624`, jetzt `:1946`ff.) | `logger.debug` | `asyncio.to_thread(_persist_run_cancelled_sync, ...)` **vor** `raise`; Fehler → ERROR + `_recovery_audit("cancel_status_persist_failed")` + `CancelToken._record_failed_cancel`. Bei 0 Treffern harte Kernel-Transition `CANCELLED`. |
| FAILED-Transition (alt `:2594-2600`, jetzt `:2797`ff.) | `except Exception: pass` | ERROR + Audit `status_transition_failed` + `failed_cancels`-Eintrag. |
| Finalzustand (alt `:2648-2652`, jetzt `:2868`ff.) | `logger.debug` | ERROR + Audit `terminal_transition_failed`, `result["kernel_state"]="unpersisted"`. `failed_cancels` wird **nach** den Bloecken ins Result geschrieben (vorher gingen neue Fehler verloren). |
| `guard.lost` (alt `:2637-2643`, jetzt `:2836`ff.) | nur `result["status"]="failed"`, Kernel blieb RUNNING | `recover_orphaned_runs()` (`:354`) mit frischem Fencing-Token: harte `kernel.transition(FAILED, reason="lease_lost")` + `workflow_runs`-Status. Bei gueltiger fremder Lease: Audit `lease_lost_unrecovered` (Hoheit liegt beim uebernehmenden Worker). |
| Flightlog-Audit (alt `:2413-2417`, jetzt `:275`ff.) | `except Exception: pass` | ERROR + `chained_audit_log.record_event(action="audit_write_failed")`; `ARCHON_AUDIT_STRICT=1` bricht hart ab. |

`_recovery_audit()` (`:87`) ist der einheitliche, nicht-verschluckende
Audit-Eskalationspfad (F024-kompatibel).

---

## 3. D07 — SSE-Broadcast (`workflow_scheduler.py:1069`)
- `except Exception: pass` → `logger.warning` + Metrik
  `event_bus_broadcast_failed` (Zaehler `:32`, `event_bus_broadcast_failed_count()`)
  + Telemetrie-Event (§0-Verifikationsglied).
- Telemetrie-Fehler werden ihrerseits auf ERROR geloggt (nicht verschluckt).

---

## 4. D08 — Sync-IO im DAG-Hotpath (`workflow_dag_runner.py`)
Alle genannten SQLite-Schreibbloecke sind in SYNCHRONE Hilfsfunktionen
gefasst und laufen ueber `asyncio.to_thread`:
- `_persist_run_cancelled_sync()` (`:101`) — Cancelled-Pfad vor `raise`.
- `_persist_run_status_sync()` (`:109`) — blocked/failed/unknown-dependency.
- `_load_run_gate_state_sync()` (`:130`) — Freigaben + Run-Insert + Node-Cache
  in einem Aufruf; CASE-Guard gegen Freigaben-Verlust unveraendert.
- `_persist_node_state_sync()` (`:188`) — running/terminal/skipped.
- `_finalize_run_sync()` (`:213`) — Kosten/Tokens, Flightlog, Trajectory,
  Finalstatus in einem Aufruf.

Damit blockiert kein `busy_timeout=5000`-Write mehr den Event-Loop;
`/livez` bleibt responsiv. Die brigen Sync-Bloecke liegen in sync
Funktionen bzw. Done-Callbacks und wurden nicht angefasst.

---

## 5. Budget-Rest — fail-closed (`role_budget_engine.py:1282`ff.)
`BudgetBank.reserve()` liefert bei gesetztem `task_id` **ohne**
`task_budget_allocations`-Zeile jetzt
`allowed=False, error_code="TASK_BUDGET_NOT_REGISTERED"`.

---

## 6. Querschnitt / ausserhalb Ownership — an W3-A/B bzw. Test-Owner

1. **`archon/core/delegation.py:391`** nutzt weiterhin
   `_MAX_DELEGATION_DEPTH = 5` (und `:1643`, `:1705`). Die SSOT liegt jetzt in
   `backend/trajectory_budget.MAX_DELEGATION_DEPTH`; delegation.py muss sie
   konsumieren. Datei gehoert nicht zu W3-D — **nicht geaendert**.
2. **`backend/agent_router.py:966`** uebergibt weiterhin `allow_repeat=True`.
   Der Parameter wirkt jetzt **nicht mehr als Freibrief**, sondern verbraucht
   das gezaehlte `repeat_budget` (nach 3 Calls → `CYCLE_DETECTED`). Eine
   Umstellung auf einen expliziten Retry-Zaehler waere dort sinnvoll (W3-A/B).
3. **`core_dispatcher.py` (D13-HIGH, alt `:158/:1096-1144/:3436-3456`)**
   bucht weiterhin kein `reserve_hop`/`reserve_tokens` im Chokepoint. W3-A/B.
4. **`backend/operations_api.py:923-936` (W3-B)**: Allokationsfehler werden
   nur auf `stderr` gedruckt. Mit der neuen fail-closed `reserve()` muessen
   dort Tasks ohne Allokationszeile `blocked`/`budget_allocation_failed`
   werden — sonst verhungern diese Tasks. **Querschnitt, nicht geaendert.**
5. **Zwei bestehende Tests erwarten das alte Fail-Open-Verhalten** und sind
   deshalb rot (nicht von W3-D besessen, nicht geloescht/skipt):
   - `tests/test_med_d12_d13.py::test_d13_expired_reservation_still_settles_real_usage` (`task_id="t-expired"` ohne Allokation)
   - `tests/test_core_a3_orchestration_limits.py::test_role_budget_engine_enforces_global_daily_cost_cap` (`t1`/`t2` ohne Allokation)
   Beide muessen von ihren Ownern auf registrierte Allokationen umgestellt
   werden. Die neue `tests/test_fix_w3_d_trajectory_dag.py` testet das
   fail-closed-Verhalten explizit.

---

## 7. Verifikation

- `compileall` (`.venv\Scripts\python.exe -m compileall -q` auf allen 5
  geaenderten Dateien): **Exit 0**.
- `python backend/trajectory_budget.py`: **4/4 Regressionstests PASSED**
  (A→B→A → CYCLE_DETECTED; Hop 4/3 → DEPTH_EXCEEDED; Replan #3;
  Repeat-Budget → CYCLE_DETECTED).
- `pytest tests/test_fix_w3_d_trajectory_dag.py -q`: **12 passed**.
- Abschlusslauf mit **frischem** `ARCHON_DATA_DIR` (wichtig: Trajectory-IDs
  sind deterministisch aus dem Root-Ticket; ein wiederverwendeter Test-DB-Ordner
  liefert `TRAJECTORY_FAILED` aus einer frueheren, bereits geschlossenen
  Trajectory — kein Codefehler):
  `pytest tests/test_fix_w3_d_trajectory_dag.py tests/test_workflow_dag_e2e.py
  tests/test_p2_checkpoint_resume.py tests/test_med2_c_orchestration.py
  tests/test_p1_durable_execution_kernel.py tests/test_reaudit_stage11.py
  tests/test_audit_b1_b8_blockers.py tests/test_reaudit_stage1.py -q`:
  **59 passed**, `compileall` **Exit 0**.
- `pytest tests/test_reaudit_stage11.py tests/test_audit_b1_b8_blockers.py
  tests/test_reaudit_stage1.py tests/test_med_d12_d13.py
  tests/test_core_a3_orchestration_limits.py -q`: **49 passed, 2 failed**
  (nur die beiden in §6.5 genannten Fail-Closed-Konflikte).
- `pytest tests/test_fix_w1_d_tenant_ledger.py tests/test_med_d14.py
  tests/test_p1_content_audit_hardening.py -q`: **30 passed**.
- **Vorhandene, nicht durch W3-D verursachte Fehler** (nur zur Einordnung):
  `tests/test_stage1_stage3_hardening_and_bus.py` scheitert an fehlendem
  `cryptography`-Modul und an `_pid_alive(999999)`; `test_milestones_77_79_81_83_86.py`
  ist wegen fehlendem `cryptography` nicht importierbar.
- **Shell-Sperre:** Zwischenzeitlich brach der Shell-Spawn mit
  `failed to spawn ...pwsh.exe: Zugriff verweigert (os error 5)` ab; danach
  war die Shell wieder verfuegbar. Alle Tests wurden mit
  `ARCHON_DATA_DIR = C:\Users\micha\AppData\Local\Temp\opencode\archon-testdata-w3d`
  und ausschliesslich mit `tmp_path`/expliziten DB-Pfaden ausgefuehrt —
  **kein Test lief gegen `./data`**.

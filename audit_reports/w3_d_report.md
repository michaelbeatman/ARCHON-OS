# W3-D — Trajectory-Governance (Umsetzungs-Report, 26.11.2026)

Scope: `D13-H1` (HIGH), `D13-M1`, `D13-M2`, `D13-M3` (MED).
Soll: `00_SOLL_SPEC.md` §1.1/§1.4/§2.4, `GEWICHTETE_BEFUNDLISTE.md`,
`audit_reports/domain_13.md`. SQLite ONLY — kein Replay, keine Postgres-Migration.

## Ergebnis

| Befund | Status | Geänderte Dateien |
| --- | --- | --- |
| D13-H1 | behoben | `backend/trajectory_budget.py`, `archon/core/dispatch_budget_cache.py`, `archon/routers/{quickchat,telegram,agent_chat,prompts,operations_org}.py` |
| D13-M1 | behoben | `archon/routers/operations_org.py`, `backend/role_budget_engine.py` |
| D13-M2 | behoben | `backend/flightlog_backtester.py` |
| D13-M3 | behoben | `backend/trajectory_budget.py`, `backend/role_budget_engine.py`, `archon/core/dispatch_budget_cache.py` |

Tests: `tests/test_w3_d_trajectory.py` (14 Tests, alle grün).
Zusätzlich grün: `test_fix_w3_b_performance`, `test_d5_budget_cache_characterization`,
`test_stage1_stage3_hardening_and_bus`, `test_fix_w3_d_trajectory_dag`,
`test_med2_c_orchestration`, `test_d3_ops_deps`, `test_d2_include_sequence`,
`test_audit_fixes_batch` (mit `ARCHON_TEST_DB_ISOLATION=1`) — 89 + 76 Tests.
Modul-Selbsttest `python backend/trajectory_budget.py`: PASS 1–4.

---

## D13-H1 — stabile Trajectory-Root-Korrelation

**Ursache:** Der zentrale Chokepoint leitete `trajectory_id` ausschließlich aus
`task_id` ab. Ohne `task_id` erzeugte `stable_trajectory_id("")` pro Aufruf
`traj-<sha256(anonymous:<time_ns>:<thread>)>` — Hop-/Zyklus-/Token-Caps waren
für QuickChat, Telegram-Relay, Agent-Chat, Prompt-Optimizer und die
Sandy-/Reviewer-/Robert-Kette wirkungslos.

**Fix:**

1. `backend/trajectory_budget.py`
   - `stable_trajectory_id()` / `normalize_trajectory_id()` enthalten **kein**
     `time.time_ns()` mehr. Korrelationsreihenfolge:
     explizite `traj-…`-ID → `root_ticket_id` → `session_id` → gebundener
     Root (`_TRAJECTORY_ROOT_CTX`) → W3C-`current_trace_id()` → stabiler
     Fail-closed-Sentinel `unrooted`.
   - Neue Helfer: `current_trajectory_root()`, `trajectory_root(scope,*parts)`
     (PII-freier Hash), `bind_trajectory_root()`, `trajectory_root_scope()`,
     `trajectory_root_source()`.
   - Ein Scope bleibt über `asyncio.to_thread()` wirksam (ContextVar-Kopie),
     also auch im ausgelagerten Trajectory-Gate.

2. Router-Call-Sites (jeweils stabiler Root statt anonymer ID):
   - QuickChat: `trajectory_root("quickchat", state_sid)`
   - Telegram-Relay (inkl. Voice-Relay): `trajectory_root("telegram-relay", ziel, trace_id|text)`
   - Agent-Chat: `trajectory_root("agent-chat", agent_id, trace_id|message+history)`
   - Prompt-Optimizer: `trajectory_root("prompt-optimizer", trace_id|raw_input)`
   - `/tasks/{id}/allocate-budget`: `normalize_trajectory_id(None, root_ticket_id=task_id)`

3. Metrik/Zähler: `archon/core/dispatch_budget_cache.py` zählt jeden Dispatch
   ohne `task_id` in `get_dispatch_without_root_metrics()` (Labels `trace`,
   `unrooted`), schreibt WARNING-Log und broadcastet
   `dispatch_without_trajectory_root`. Damit bleibt die Fallback-Korrelation
   sichtbar statt still zu umgehen.

**Hinweis zur Ownership:** `archon/core/orchestration.py` und
`core_dispatcher.py` gehören anderen Agenten und wurden nicht angefasst. Die
ortlose Kette wird dort über die Trace-ID-Korrelation stabil; ein expliziter
Root kann jederzeit über `bind_trajectory_root()` gesetzt werden. Die
BudgetBank übernimmt zusätzlich dieselbe Korrelation (siehe M3).

## D13-M1 — Budget-Minting / verwaistes Hire-Profil

- `TaskBudgetAllocateRequest`: `total_token_budget: Optional[int] = Field(None, ge=1, le=2_000_000)`,
  `total_cost_limit_eur: Field(None, ge=0.01, le=1000)`. Ceilings kommen als
  Konstanten aus `backend/role_budget_engine.py` (eine Wahrheit, auch
  serverseitig in `allocate_task_budget_to_subagents()` geprüft).
- Default 120000 entfernt. Ohne Wert konsultiert `_resolve_parent_budget()`
  die SSOT; ohne Elternbudget → `blocked/NO_PARENT_BUDGET`.
- Endpoint liefert bei `blocked` **HTTP 409** statt `status="success"`.
- CEO-Hiring: Platzhalter-Allokation zuerst, Hiring erst nach erfolgreicher
  Parent-Allokation mit exakt dem allokierten Anteil; `task_budget_allocations`
  wird auf die echte `hired_*`-ID umgeschrieben. Bei jedem Fehler
  `revoke_autonomous_hire()` (Status `revoked`, Policy 0/0) — kein verwaistes
  Profil mit aktivem Tagesbudget.

## D13-M2 — Loop-Erkennung im Flightlog

- Additive Spalten `trajectory_id`, `hop_index` in `flight_events`;
  `record_flight_event()` / `mirror_flight_event_to_trace()` schreiben sie
  (auto-ausgefüllt aus Trajectory-Kontext, falls der Produzent sie nicht reicht).
- Neue Regel `_detect_tool_loops()` mit drei Signalen (Flag-Prefix `tool_loop`
  bleibt für den Dispatcher-Guard kompatibel):
  1. `args_hash`-Streak ≥ 3 (altes Signal behalten),
  2. `tool_name` ≥ 3 im gleitenden Fenster von 8 Events — auch bei **unterschiedlichen** Argumenten,
  3. zyklische Wiederholung eines `(agent_id, tool_name)`-Musters der Länge 2–4,
     also A→tool_x→B→tool_y→A über Agentgrenzen hinweg.
- Flags tragen `@trajectory_id:hop-N` als Befund; `detect_silent_failures()`
  liefert zusätzlich `loop_details`.

## D13-M3 — Actual-Tokens statt Schätzung

- Neue Tabelle `trajectory_token_reservations` (ID, Trajectory, Agent,
  `source_key`, `tokens_estimated`, `tokens_actual`, Status, TTL-Zeitstempel).
  `trajectory_budgets` erhält `reserved_tokens`/`actual_tokens`.
- `reserve_tokens()` bucht die Schätzung atomar **und** legt eine einzelne
  Reservierung an; `finalize_tokens(..., outcome="settled"|"released")` ersetzt
  den Schätzwert durch den echten Wert (keine Doppelbuchung), `release_tokens()`
  bucht bei `blocked`/`error` gegen. `expire_stale_reservations()` wendet
  `RESERVATION_TTL_SECONDS` an (opportunistisch beim nächsten Reserve).
- `record_tokens(set_total=True)` rechnet eine offene Reservierung automatisch
  mit dem Actual ab (kompatibel mit dem bestehenden Agent-Router-Pfad).
- Audit: `_audit_reconciliation()` schreibt `category="trajectory_budget"`,
  `action="token_reconciliation"` inklusive `estimated` **und** `actual` in die
  HMAC-Kette und broadcastet `trajectory_token_reconciled`.
- **Verdrahtung ohne fremde Datei:** `core_dispatcher.py` ruft im Erfolgspfad
  `budget_bank.settle()` und im `finally` `budget_bank.release()` auf. Diese
  Methoden (in `backend/role_budget_engine.py`) schließen über die am
  Reservierungszeugnis gespeicherte `trajectory_id` + `source_key` die
  Trajectory-Reservierung ab. Damit greift die Reconciliation exakt dort,
  wo der Dispatcher schon Actual-Tokens kennt — ohne Änderung an
  `core_dispatcher.py`.
- Verifiziert: 10k Estimate → 2k Actual ⇒ `tokens_used == 2000`,
  `reserved_tokens == 0`; 3 blockierte/`released` Dispatches ⇒ 0 Restlast.

## Bekannte Grenzen / nicht empfohlen

- Kein Coroutine-/Event-Replay, keine PostgreSQL-Migration (NEVER_DO_LIST).
- `core_dispatcher.py` / `orchestration.py` bleiben bei externer Ownership;
  die Korrelation läuft dort über Trace-Kontext, nicht über neue Parameter.
- Ohne jeden Root (z. B. nackter Hintergrundjob ohne Trace) teilen sich
  Dispatchs denselben stabilen `unrooted`-Trajectory und werden nach den
  SSOT-Caps blockiert (fail-closed) — Absicht, nicht Defekt; der Zähler macht
  diesen Fall sichtbar.

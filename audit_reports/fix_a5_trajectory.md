# Fix-Log A5 — Trajectory / Performance (Phase 3 Remediation)

**Agent:** Fix-Agent A5 (Trajectory/Performance) · **Basis:** HEAD `cee78206`, Worktree vor Edits clean
**Exklusiver Dateibereich:** siehe Auftrag. Keine fremde Datei editiert. **B6** (`backend/trajectory_budget.py:264`
Retry→Tool-Cycle-False-Positive) wurde **nicht** angefasst. G-01/G-02/G-05 beachtet: kein Event-Replay,
keine DB-Migration, keine Coroutine-Wiederholung.

---

## 1. Umgesetzte Fixes (15)

### D13/HIGH — Flightlog-`run_id`-Namensraum (Fix 1)
**Dateien:** `backend/flightlog_backtester.py`, `backend/agent_router.py`, `backend/workflow_dag_runner.py`

- Neuer, zentraler Helfer `mirrored_run_ids()` + `mirror_flight_event_to_trace()` in
  `backend/flightlog_backtester.py`: liefert Primär-ID → Session-ID → `current_trace_id()` und schreibt
  ein bereits vom Chokepoint unter `flightlog_run_id` persistiertes Event **zusätzlich** unter der
  Trace-ID. Kein Löschen/Überschreiben, kein Replay.
- `agent_router.py`: in beiden Provider-Pfaden (`_chat_completion_unreserved`,
  `_stream_chat_completion_unreserved`) wird bei HTTP-2xx ein `llm_dispatch`-Korrelationsmarker unter
  der aktiven Trace-ID gespiegelt. Damit findet der **aktuelle** Konsument in `core_dispatcher.py`
  (`_guard_silent_failures()` liest `current_trace_id()`) ohne Änderung Events vor.
- `workflow_dag_runner.py`: nach `execute_agent_tool(...)` und am Run-Abschluss
  (`dag_run_complete`) wird jedes Flight-Event unter der Trace-ID gespiegelt. Token-Schätzung
  über `tool_runtime._result_token_estimate()`.
- `flightlog_backtester.py`: `effort_collapse` ignoriert jetzt `llm_dispatch`-Marker, damit ein
  kurzer LLM-Text nicht falsch als „versteckter Fehler" quittiert wird (G-03: Effekt ↔ Produzent).

> Der „saubere" Konsumenten-Fix bleibt **DELEGATED** an A4 — exakter Code-Vorschlag in §3.
> `delegation.py:1256` (`run_id=str(task_id)`) ist ein dritter Namensraum (fremde Datei, nicht editiert);
> die Spiegelung macht ihn für den Dispatcher unschädlich.

### D13/HIGH — Legacy-Fan-out-Cap (Fix 2)
**Datei:** `archon/routers/chat.py`

- `_parse_delegation_blocks()` bekommt bewusst einen weiten Cap; danach werden die
  Regex-`hermes -p …`-Payloads mit **derselben Dedup-Regel** (`ziel:auftrag[:40]`) in dieselbe
  `payloads`-Menge aufgenommen und der Cap **einmalig** auf die Gesamtmenge angewendet.
- Überschuss: `DelegationReceipt(status="blocked", reason="FANOUT_CAP", block_kind="fanout_cap",
  trajectory_id=…)` + `_audit()` + `mc_task_meta`-Persistenz (`status=blocked`, `failure_reason=FANOUT_CAP`)
  über `mc_update_task_sqlite`. `invalid_blocks` trägt `fanout_cap/fanout_blocked/omitted_count`.
- Die alte Generic-Fehler-Quittung überschreibt `FANOUT_CAP`-Einträge nicht mehr (doppeltes Quittieren
  vermieden). Erwartetes Verhalten: 7 Legacy-Befehle → 5 Delegationen + 2 `FANOUT_CAP`-Quittungen.

### D13/HIGH — Ticketweites Token-Cap (Fix 3)
**Dateien:** `archon/routers/chat.py`, `backend/agent_router.py`

- `ChatStreamRequest` um `token_budget: Optional[int] = Field(ge=1, le=2_000_000)` und
  `cost_limit_eur: Optional[float] = Field(ge=0.01, le=10_000)` erweitert (Pydantic-Validierung).
- `_capture_mission_task_with_budget()` legt Task + `task_budget_allocations`-Zeile in **einem**
  `BEGIN IMMEDIATE` an (SQLite-`ATTACH` der Budget-DB an die Kanban-Connection; im JSON-Testmodus
  Fallback ohne Transaktion). Ohne Allocation greift `budget_bank.reserve()` bekanntlich nicht.
- `ensure_trajectory(..., max_tokens=token_budget)` beim Task-Anlegen; der Missions-Task erhält
  außerdem `trajectory_id/max_tokens/tokens_used/max_replans/replans_used/replan_count` im Meta.
- **Kritische Verdrahtung:** `chat.py` übergibt jetzt `task_id=mission_task_id or session_id` an
  `router_instance.stream_chat_completion()` — vorher lief der Router gegen die Session-ID und damit
  gegen eine andere Trajectory als das Ticket.
- `agent_router._reserve_task_budget()`: nach Hop-Gate neues atomares `reserve_tokens(_hop_tid,
  est_in+est_out, reason=f"llm_call:{agent_id}")` **vor** dem Provider-Call; bei Cap/Fehler fail-closed
  `BudgetExceededError` + `budget_bank.release()`. Liefert `_hop_tid` an beide Caller.
- `agent_router._settle_task_budget()`: nach dem Call `record_tokens(..., set_total=True)`; verhindert
  Doppelbuchung, blockiert bei Cap-Verletzung. Im Stream-Pfad wird der Fehler als `ERROR:`-Chunk
  quittiert, nicht verschluckt.

### D13/MED — `replan_count`-Alias mit echtem Produzenten (Fix 4)
**Dateien:** `backend/trajectory_budget.py`, `backend/workflow_dag_runner.py`, `archon/routers/chat.py`

- `task_budget_meta_projection()` liest die SSOT `trajectory_budgets` und liefert
  `max_hops/hops_used/max_tokens/tokens_used/max_replans/replans_used` **und** `replan_count`.
- `sync_task_budget_meta()` schreibt die Projektion via `mc_update_task_sqlite()` in `mc_task_meta`.
- Produzenten: `request_dag_replan()` (nach `reserve_replan()`, auch im blockierten Pfad) und
  Missions-Task-Anlegen in `chat.py`. Damit greift `enforce_task_budget_caps()` sichtbar; der Alias
  ist keine tote Allowlist-Zeile mehr.

### D08/HIGH — Beleg-Upload blockiert Event-Loop (Fix 5)
**Datei:** `archon/routers/operations_receipts.py`

- `api_receipts_upload()` ruft `process_receipt()` und `update_receipt()` über `asyncio.to_thread`.
- Modul-lokales `threading.RLock` (`_OCR_CHAIN_LOCK`) in den Sync-Wrappern hält die Reihenfolge der
  Beleg-IDs/Hashkette bei parallelen Uploads deterministisch. `receipt_ocr_engine.py` (A8) blieb unberührt.

### D08/MED — Weitere Event-Loop-Blockaden (Fixes 6–14)

| # | Fund | Umsetzung |
|---:|---|---|
| 6 | HUD-Config-Loader (`telemetry.py`) | `_load_hud_configs(app_main)` lädt `load_agents()`/`load_services()` in `to_thread`; Endpoint nutzt `agents, services = await …`. |
| 7 | Key-Scan `chat.py` | `api_tool_image_generate()`: `all_keys = await asyncio.to_thread(api_provider.collect_keys)`. |
| 8 | Key-Scan `context_help.py` | `api_ask_help_assistant()`: identische Thread-Übergabe (`asyncio` import ergänzt). |
| 9 | HTTP-Client-Pools | `AgentRouter.close_http_clients()` implementiert: Snapshot der `WeakKeyDictionary`, `await client.aclose()` je Client, `.clear()`, Fehler → `logger.debug`. wiring in `main.py` → **DELEGATED an A9**. |
| 10 | HITL SQLite + Audit (`kanban.py`) | `_load_hitl_creator()` via `run_io_bound()`; beide `record_event()`-Aufrufe (`kanban_hitl_resolution`, `taint_approval_queue_read`) via `run_io_bound()`. HMAC-Kettenreihenfolge bleibt durch `audit_log.py:604 self._lock` gewahrt. |
| 11 | Eval-Gates (`eval_gates.py`) | `init_eval_db()` und `_persist_eval_run()` (INSERT `eval_runs`) via `asyncio.to_thread`. |
| 12 | Team-Spawner (`ephemeral_team_spawner.py`) | `_persist_task_force()` via `asyncio.to_thread`; Ergebnis unverändert. |
| 13 | Template-Raster (`prompt_studio.js`) | `tplVisibleCount=60`, `filtered.slice()`, „Mehr laden"-Button, `tplLoadMore()`, 180-ms-Debounce im Suchfeld, Render-Key-Reset bei Filterwechsel. |
| 14 | Showroom-FS-Scans (`views_core.py`) | `_scan_showroom_reports()`, `_load_showroom_report_content()`, `_scan_showroom_apps()` in `to_thread`; Listen auf `_SHOWROOM_MAX_ENTRIES=1000` begrenzt, unnötiges `read_text()` im Listenpfad entfernt. |

### D07/HIGH (A5-Anteil) — 90-s-Kettendeadline im Stream-Pfad (Fix 15)
**Datei:** `backend/agent_router.py` (`_stream_chat_completion_unreserved`)

- `chain_deadline = time.monotonic() + 90.0` vor der Kandidatenschleife (analog zum bereits
  gefixten Non-Stream-Pfad).
- Prüfung vor jedem Hop, Restzeit als `timeout=` in `client.stream(...)`, hartes `TimeoutError`
  bei abgelaufener Restzeit, `aiter_lines()`-Deadline-Check und gedeckeltes Backoff
  (`asyncio.wait_for(..., timeout=min(rest, 10.0))`).
- Eigener `except TimeoutError`-Zweig: Ketten-Deadline wird als `ERROR: FALLBACK_CHAIN_DEADLINE`
  quittiert, **ohne** nächsten Fallback-Hop und ohne den Provider-Breaker falsch zu beeindrucken.

---

## 2. Nicht im Ownership-Bereich — DELEGATED

| ID | Ziel | Grund / Erwartung |
|---|---|---|
| **D1** | A4 · `core_dispatcher.py` | Flightlog-Konsument `_guard_silent_failures()` (Z.103-131) liest nur `current_trace_id()`. Exakter Code-Vorschlag in §3. Die Spiegelung aus Fix 1 macht den aktuellen Konsumenten bereits funktionsfähig; der Vorschlag ist der saubere, namespace-feste Endzustand. |
| **D2** | A9 · `main.py` | `_SHUTDOWN_HOOKS` um `_close_all_http_clients()` ergänzen; `agent_router.router_instance.close_http_clients()` aufrufen (sowie `hermes_proxy`, `system`, `reverse_proxy`). A5 liefert nur die hier implementierte `close_http_clients()`. |
| **D3** | Owner `archon/core/mission_control.py` / `archon/routers/mission_control.py` | D08/MED: `LIMIT 5000` für die zwei unbegrenzten Queries in `_load_sqlite_state_from_conn` (Z.547, Z.556-566), Indizes `tasks(status, created_at)` / `task_links(kind)`. Dateien nicht in A5s Bereich. |
| **D4** | Owner `archon/core/mission_control.py` | D08/MED (9. Fund): `_MC_STATE_CACHE` (einfaches Dict ohne Lock/Single-Flight) auf gelockte atomare Zuweisung / `ttl_cache` umstellen und alle Invalidierungen über eine `invalidate()` leiten. Datei nicht in A5s Bereich. |

**Zusätzlicher Hinweis an A4:** `archon/core/delegation.py:1256` schreibt Abschluss-Events unter
`run_id=str(task_id)` (dritter Namensraum). Mit Fix 1 ist der Dispatcher auch ohne Änderung dort
abgedeckt; langfristig sollte dieser Schreibpfad denselben `flightlog_run_id` wie der Detektor nutzen.

---

## 3. Exakter Code-Vorschlag für A4 (`core_dispatcher.py`)

Replace in `_guard_silent_failures()` (Z.113-128) — fallback reads both keys, no migration/replay:

```python
    # D13/HIGH: Produzent schreibt unter flightlog_run_id (Trajectory/Task-ID),
    # nicht unter current_trace_id(). Beide Namensraeume abfragen.
    run_ids: list[str] = []
    try:
        from backend.trajectory_budget import normalize_trajectory_id
        if str(task_id or "").strip():
            run_ids.append(normalize_trajectory_id(
                task_id if str(task_id).startswith("traj-") else None,
                root_ticket_id=str(task_id),
            ))
    except Exception as exc:
        logger.debug("[Dispatcher] Trajectory-ID nicht verfuegbar: %s", exc)
    try:
        from backend.trace_context import current_trace_id
        trace = str(current_trace_id() or "").strip()
        if trace and trace not in run_ids:
            run_ids.append(trace)          # Fallback: gespiegelter Namensraum (A5)
    except Exception as exc:
        logger.debug("[Dispatcher] Trace-ID nicht verfuegbar: %s", exc)
    if not run_ids:
        return res

    finding: dict = {}
    for rid in run_ids:
        candidate = await asyncio.to_thread(
            detect_silent_failures, rid,
            res.get("status", "success"), str(res.get("content") or ""),
        )
        if not finding or candidate.get("flags"):
            finding = candidate
        if candidate.get("flags"):
            break
```

Docstring Z.106-109 simultan korrigieren („Produzent schreibt unter `flightlog_run_id`; der
Dispatcher prüft Trajectory-ID **und** Trace-ID"). Optional: `flightlog_run_id` als Parameter durch
`dispatch_to_omniroute_or_container()` reichen und als ersten Eintrag in `run_ids` setzen.

Regressionstest für A4: drei identische Tool-Calls unter exakt der abgefragten `run_id` →
`tool_loop`-Flag und Dispatch-Status `blocked`.

---

## 4. Verifikation

- **Statisch:** Alle 12 editierten Python-Dateien wurden zeilenweise auf Syntax/Einrückung und
  Importverfügbarkeit geprüft; `prompt_studio.js` auf Template-/Klammerbalance. Grün: B6-Logik
  (`trajectory_budget.py:264`), `await audit_dispatch_async(` in `agent_router.py` (Test
  `test_d08_audit_dispatch_is_async`), `_create_dec(...)`-Signatur (Test
  `test_chat_mission_decision_sets_created_by`), `ORDER BY id DESC LIMIT 5000` in `kanban.py`
  (Performance-Test) blieben unverändert.
- **Nicht ausgeführt:** `pytest tests/test_med_d12_d13.py tests/test_reaudit_stage13.py
  tests/test_audit_p2_performance.py`, `ruff`, `mypy`. Grund: das Shell-Werkzeug dieser Session
  konnte `pwsh.exe` nicht starten (`failed to spawn … Zugriff verweigert (os error 5)`) — auch
  `python --version` und `git status` scheitern damit. Bitte in einer Session mit funktionierendem
  Terminal nachholen. Es wurde **nicht** committet oder gepusht.

**Zählung:** 15 umgesetzte Fixes · 4 DELEGATED.

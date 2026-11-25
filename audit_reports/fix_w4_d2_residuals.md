# FIX W4-D2 — Restpunkte aus Welle 4 (Domain 16 MED + Altfehler)

**Datum:** 25.11.2026 · **Scope:** `F041`/D16-MED-Reste aus `FIX_VERIFICATION_LOG.md`
(W4-D/W5-ToDo) plus zwei vorbestehende Testfehler. **Basis:** `00_SOLL_SPEC.md` §3/§4,
`domain_16.md` (3 MED-Funde), `MASTER_PLAN.md` §4/§5, `FIX_VERIFICATION_LOG.md`,
`INCIDENT_2026-11-25_LOGIN_OUTAGE.md`.

**Datenisolierung:** Alle Testläufe mit `ARCHON_DATA_DIR=<TEMP>`; kein Test lief gegen
`./data`. `NEVER_DO_LIST` (kein Coroutine-Replay, keine PostgreSQL-Migration) eingehalten.

---

## 1. Geänderte Dateien (exklusives Ownership)

| Datei | Änderung |
|---|---|
| `archon/core/delegation.py` | `record_span(span_type="delegation")` am Parent→Child-Launch (~Z.2243–2280) mit `parent_span_id` aus `current_span_id()`, Kind-Task-ID, Session, Trajectory, Depth; Fehler via `note_local_trace_error`. |
| `backend/tool_runtime.py` | Neuer `_record_tool_span()` (~Z.26); Span bei blockiertem Gate (`status=ERROR`) und im Finalize `guard_result()` (`status` aus Firewall-Urteil, `tool.name` als Attribut). Kein Roh-Output im Span (PII/Secrets). |
| `backend/workflow_dag_runner.py` | Node-Span (~Z.2457) jetzt `span_type="gate" if _is_gate else "agent"`; `_is_gate = requires_gate or ntype == "quality_gate"`. Neue Attribute `gate.required`, `gate.decision`. |
| `archon/routers/v2_capabilities.py` | Neues Pydantic-v2-Modell `EvalReplayRequest` und `POST /api/v2/eval/traces/{trace_id}/replay` (~Z.1163): Admin + verifizierter Session-Actor + zwingendes, an `action`/`resource=trace_id` gebundenes Passkey-Einmalproof; `executor_fn` ruft den **produktiven** `core_dispatcher.dispatch_to_omniroute_or_container`; Persistenz in `replay_fixtures`/`eval_runs` erfolgt in `backend.eval_gates.replay_and_evaluate`. |
| `backend/metrics_collector.py` | Ringpuffer pro `(metric_name, series_labels)` statt pro Name; `_series_labels_for()` normalisiert HTTP-Status auf `ok`/`error`; `_exemplar_line(metric, value, series_labels)` liefert **nur** das passende Sample (kein Fallback auf fremde Serie). OP-Serie `{status="error"}` erhält jetzt ebenfalls ein Exemplar. |
| `core_dispatcher.py` | `_httpx_transport()` injiziert einen Child-Span nur dann, wenn die Outbox keinen `traceparent` mitgeliefert hat; vorhandene Outbox-Kante wird nicht geforkt (Header ↔ Payload-span_id bleiben konsistent). |
| `tests/test_fix_w4_d2_residuals.py` | **neu:** 12 Tests für Produzenten, Persistenz, Replay-Wiring, Exemplar-Serie und Transport-Injektion. |
| `tests/test_core_a4_persistence_resolver.py` | A4-Test erwartet jetzt die **aktive Konsolidierung** `memory.db` statt Legacy `agentic_memory.db`; Tenant-Resolver wird für die System-DB nicht bemüht. |
| `tests/test_audit_fixes_batch.py` | Pepper-Test auf keyed HMAC-SHA256 + Key-Rotation ohne Legacy-Fallback + harten Fail-Closed in Produktion umgestellt (`_legacy_hash_token` existiert nicht mehr). |
| `tests/test_orange_b_r16.py` | Obsoleter `force_verdict`-Test: Body-Feld darf nichts bewirken; legitime Freigabe nur über 4-Augen-Override mit Session-Actor + passkey-gebundenem Proof. |
| `tests/test_reaudit_stage5.py` | Neuer D05-Test für getrennte/epochenbewusste Audit- und Anker-Keys bei Rotation (alter Test blieb erhalten). |
| `tests/test_fix_w3_d_trajectory_dag.py` *(unverändert)* | Referenz für fail-closed `TASK_BUDGET_NOT_REGISTERED`. |
| `tests/test_med_d12_d13.py`, `tests/test_core_a3_orchestration_limits.py` | Die zwei W3-D-Fail-Open-Erwartungen: echte `task_budget_allocations` in Temp-DB angelegt; Verhalten bleibt fail-closed. |
| `tests/test_p1_trace_propagation.py`, `tests/test_zero_egress_and_dispatch_audit.py`, `tests/test_core_a2_fail_closed_sandbox.py` | Drei weitere Tests, die ohne registriertes Task-Cap `TASK_BUDGET_NOT_REGISTERED` als „altes Verhalten" erwarteten: jeweils echte Allokation in Temp-DB; **Produktivcode `backend/agent_router.py` blieb unverändert** (Fail-Closed ist korrekt). |
| `tests/test_fix_batch8.py` | R-30-Tampering-Test entfernt in der **Temp-DB** die append-only-Trigger, um einen Offline-Angriff zu simulieren ( Produktivtrigger bleiben aktiv). |

**Nicht geändert (bewusst):** `requirements*.txt`, `.github/workflows/*`,
`backend/otel_tracer.py`/`trace_context.py`, `backend/trajectory_budget.py`, `main.py`,
`backend/agent_router.py`, `backend/eval_gates.py`, `backend/workflow_scheduler.py`.

---

## 2. Verifikationskette nach §0

| Mechanik | Produzent | Konsument | Effekt | Verifikation |
|---|---|---|---|---|
| Delegations-Span | `delegation.py:2265` | OTel-Baum / `get_trace_tree`, `eval_gates.build_fixture_from_trace` | `otel_spans`-Zeile mit `span_type='delegation'`, korrektem Parent | `test_three_new_span_types_are_really_persisted`, `test_delegation_launch_records_delegation_span_with_parent` |
| Tool-Span | `tool_runtime.py:26` + Finalize `guard_result` | Fixture-Filter `eval_gates.py:506` | `otel_spans` mit `tool.name`, Status aus Firewall | `test_tool_runtime_finalize_records_tool_span`, `test_tool_runtime_blocked_call_records_error_span` |
| Gate-Span | `workflow_dag_runner.py:2466` | Fixture-Filter / Grafana | `span_type='gate'` statt `agent` | `test_dag_gate_nodes_get_gate_span_type`, Persistenz-Test |
| Replay | Span-Baum | `POST /api/v2/eval/traces/{id}/replay` → `replay_and_evaluate` → Dispatcher | `replay_fixtures` + `eval_runs(target_type='replay')` | `test_replay_endpoint_is_wired_to_dispatcher_and_hitl` |
| Exemplar-Korrelation | Middleware/`trace_context` → `record_trace_exemplar` | `metrics_collector.py:113` beim Rendern | 500er-Trace nur an `{status="error"}`, 200er nur an `{status="ok"}` | `test_exemplar_ring_buffer_is_keyed_by_metric_and_series`, `test_render_attaches_exemplar_to_matching_status_series` |
| n8n-Trace-Hop | Outbox-Header oder Transport-Fallback | `_httpx_transport` → n8n | `traceparent` mit Kind-Span-ID; vorhandene Outbox-Kante unverändert | `test_httpx_transport_injects_trace_when_outbox_has_none`, `...keeps_outbox_span_when_present`, `test_reaudit_d16_dispatcher.py` |

---

## 3. Außerhalb Ownership / Eskalation

1. **`main.py:389-394` (`TraceContextMiddleware`)** ist explizit von der Änderung
   ausgeschlossen. Der dortige Aufrufer übergibt weiterhin
   `labels={"route": ..., "status": response.status_code}`. Der neue Kollektor ist
   **rückwärtskompatibel**: `_series_labels_for()` leitet daraus intern die Serie
   `status=ok|error` ab (HTTP-Code < 400 → ok). `core_dispatcher.py` enthält keine
   `record_trace_exemplar`-Aufrufer. Falls die Labels künftig explizit gebunden werden
   sollen: `record_trace_exemplar(..., series_labels={"status": "error"})` übergeben —
   nur in `main.py`, nicht in dieser Welle.
2. **`backend/eval_gates.py:506-508`** filtert bereits `("llm","agent","tool",
   "delegation","gate")` — kein Eingriff nötig (Datei nicht im Ownership).
3. **`backend/agent_router.py`** bleibt unverändert: `TASK_BUDGET_NOT_REGISTERED` ist
   das korrekte Fail-Closed-Verhalten. Nur die betroffenen alten Tests wurden aktualisiert.
4. **`backend/workflow_scheduler.py`** (`workflow_events`-Trace-Spalten) wurde in
   W4-B umgesetzt — nicht erneut angefasst.
5. **D16-HIGH-Reste** (kein OTel-SDK, Collector-Downstream, n8n-MCP-Treiber,
   Server-PocketBase) sind W4-A/F041 bzw. ausdrücklich nicht in diesem Auftrag
   enthalten.
6. **`test_show_hn_blockers.py::test_core_dispatcher_omniroute_alias_and_ollama_fallback`**
   ist weiterhin rot (`status="blocked"`): die Erwartung stammt aus der Zeit vor der
   Zero-Egress-/Local-Offline-Härtung (W2-A/W4-B). Datei nicht im Ownership → nicht
   geändert; an Test-Owner eskalieren.
7. **`tests/test_jev_router.py::TestJevRouterUnit::test_connection_probe_fail_open`**
   erwartet weiterhin `status="error"` statt des jetzt korrekten fail-closed
   `status="blocked"` bei nicht erreichbarem Port. Nicht in Ownership → eskaliert.
8. **`scripts/run_email_matching.py` / Root-`archon_crm_mcp.py`** (W4-ToDo aus
   W2-B) sind nicht in diesem Ownership und bleiben offen.

---

## 4. Verifikation (ausgeführt)

- `.ci_venv\Scripts\python.exe -m compileall -q` auf allen geänderten
  Produktiv-/Testdateien → **Exit 0**.
- `pytest tests/test_fix_w4_d2_residuals.py -q` (frisches `ARCHON_DATA_DIR`) →
  **12 passed**.
- Gezielte Suite (13 Testdateien, frisches `ARCHON_DATA_DIR`) → **186 passed**.
- Gesamtsuite `pytest tests/ -q --tb=no` mit frischem `ARCHON_DATA_DIR` →
  **11 failed / 2323 passed / 16 skipped** (W0-Baseline: 20 failed / 2120 passed;
  Baseline dieser Welle: 19 failed / 2303 passed). Damit sind **8 der 19**
  vorbestehenden Fehler behoben; 20 neue Tests grün.

**Verbliebene 11 Fehler (alle außerhalb dieses Ownerships, keine Regression durch
W4-D2):** `test_audit_b1_b8_blockers.py::test_b3_jev_test_requires_admin_blocks_ssrf_and_no_key_exfiltration`,
`test_fix_batch11.py::test_n11_boardroom_debate_ids_collision_free`,
`test_fix_w1_d_tenant_ledger.py::test_event_mesh_dedup_is_tenant_scoped`,
`test_fix_w4_a_tracing.py::test_h16_4_media_sync_adds_trace_field_and_headers`,
`test_graceful_shutdown.py::TestGracefulShutdownCoordinator::test_database_wal_flush`,
`test_jev_router.py::TestJevRouterUnit::test_connection_probe_fail_open`,
`test_reaudit_stage15.py::test_d10_watchdog_is_separate_process`,
`test_reaudit_stage7.py::{test_d11_payload_requires_target_and_task,test_d11_no_dead_import_fallback,test_d11_structured_handoff_and_hmac_consumer}`,
`test_show_hn_blockers.py::test_core_dispatcher_omniroute_alias_and_ollama_fallback`.

**Shell-Hinweis:** `pwsh.exe` war zeitweise gesperrt (`Zugriff verweigert (os error 5)`);
nach Wiederholung bzw. nach Ende des Hintergrundlaufs waren alle Befehle ausführbar.
`python` im PATH ist der Microsoft-Store-Stub; verwendet wurde
`.ci_venv\Scripts\python.exe` (Python 3.11.15). Kein Test lief gegen `./data`.

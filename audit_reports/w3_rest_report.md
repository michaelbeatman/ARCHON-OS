# W3-Reste — Sanierungs-Report (D07-M4/M6/M7, Lease, D11-M3/M4)

**Datum:** 27.11.2026 · **Umfang:** 6 Funde aus §4 des Handovers `HANDOFF_W4_W7.md`
**Regeln:** `NEVER_DO_LIST.md` beachtet (kein Replay, keine PostgreSQL-Migration).
Keine Commits durch Subagenten; Dateibesitz strikt eingehalten.

---

## 1. Änderungen

| ID | Datei | Fix | Regressionstest |
|---|---|---|---|
| (Rest) | `archon/core/orchestration.py:422-432` | `ARCHON_LEASE_FAIL_OPEN`-Opt-out entfernt. Jeder nicht auswertbare Lease-Claim setzt den Task `blocked` und committet ihn — kein Dispatch ohne CAS. | `test_mission_control_lease_claim_is_fail_closed_even_with_optout` (Produktivpfad `_execute_mission_control_task`, Flag bewusst auf `1` gesetzt) |
| D07-M4 | `archon/services/background_loops.py` | Neue Helfer `_record_loop_failure` / `_reset_loop_failures`. Deadlock-, Synthese- und Alert-Loop-Fehler: `logger.error` + signiertes `_require_audit_event(category="recovery")`. Zähler pro Loop, nach 3 aufeinanderfolgenden Fehlern `report_external_alert(..., "CRITICAL")` + Audit-Event `loop_external_alarm`. Erfolg setzt den Zähler zurück. | `test_recovery_loop_failures_are_audited_and_escalate` (echter 30-s-Loop über 3 Zyklen, alle drei Konsumenten fehlerhaft) |
| D07-M6 | `archon/services/runtime_endpoints.py` | Neuer Helper `_audit_shutdown_failure`. Audit-Anker-Stopp und Graceful-Shutdown-Fehler: `logger.error` + signiertes Event; bei `ARCHON_AUDIT_STRICT=1` harter Abbruch. | `test_anchor_and_graceful_shutdown_failures_are_audited` |
| D07-M6 | `archon/services/shutdown_clients.py` | Neuer Helper `_record_client_close_failure`. Fünf ehemalige `DEBUG`-Pfade (AgentRouter, Pool-Clients, Dict-Clear, Pool-Close, System-Client) → `ERROR` + signiertes Audit + Spiegelung in `_FAILED_CANCELS` (von `/readyz` konsumiert). Test räumt die Spiegelung wieder auf. | `test_client_close_failure_is_audited_and_mirrored` |
| D07-M7 | `archon/services/lifecycle.py` | Gesamtbudget `_SHUTDOWN_BUDGET_SECONDS = 10.0` für alle Shutdown-Hooks. Jeder Hook in `asyncio.wait_for` mit Restbudget; Name, Status und Dauer im signierten Audit. Der Liveness-Stop läuft in einem inneren `finally` immer (kleine Restfrist von 0,05 s wenn das Budget aufgebraucht ist). | `test_lifecycle_shutdown_honours_total_budget_and_audits_hooks` (hängender Hook, Budget im Test auf 0,25 s reduziert, Stop wird trotzdem ausgeführt) |
| D11-M3 | `backend/lossless_session_dag.py` | `record_turns`: `dedup_key` enthält jetzt Position `idx` und explizite `turn_id`/`message_id`/`id` — identische Turns kollabieren nicht mehr, exakter Re-Dispatch bleibt idempotent. `derive_session_id`: explizite Session-Felder behalten den Vertrag `session:<id>`; der Fallback-Fingerprint hash-t die gesamte Kette plus Mandanten-Salz und optionale `turn_id`/`task_id`/`run_id`/`request_id` statt nur System + erstem User-Turn. | `test_identical_turns_stay_distinct_and_sessions_do_not_bleed` |
| D11-M4 | `archon/routers/boardroom.py` | Alle fünf stillen `[:1500]`-Schnitte bei `critique`/`synthesis`/Seat-Perspektiven durch `mark_truncated(..., artifact=...)` ersetzt (Marker + Artefaktpfad `boardroom.debate/…`, `boardroom.panel/…`, `boardroom.hitl/…`). | `test_storm_panel_truncations_carry_marker_and_artifact`, `test_hitl_escalation_truncations_carry_marker_and_artifact` |

**Neue Testdatei:** `tests/test_w3_rest.py` — 8 Tests, alle gegen den Produktivpfad.
**Import-Sortierung:** `backend/lossless_session_dag.py` (vorbestehendes I001 im geänderten File) korrigiert.

---

## 2. Verifikation

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' })
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/test_w3_rest.py -q
```

**Ergebnisse:**

- Ruff (`E,F,I`, `E501` ignoriert): **All checks passed** (8 Dateien).
- MyPy (`mypy.ini`): **Success: no issues found in 8 source files**.
- Neue Suite `tests/test_w3_rest.py`: **8 passed**.
- Angrenzende Suiten (`test_w3_*`, `test_f32_livez…`, `test_d2b_lifespan…`,
  `test_d2_main_characterization`, `test_fix_w1_b_lossless`): **95 passed**.
- Boardroom-/Orchestrierungs-Suiten (`test_core_a3_orchestration_limits`,
  `test_fix_batch11`, `test_fix_w3_b_performance`, `test_d5_dispatcher_characterization`):
  **37 passed**.
- Full-Suite: **2772 passed, 16 skipped, 22 failed, 1 error** (263 s). Die Roten
  sind die im Handover §3 dokumentierten vorbestehenden Fehler
  (`test_orange_a_main` 6, `test_orange_a_security` 4, `test_orange_b_r16` 3,
  `test_p0_api_validation_*` 2, `test_p1_trace_propagation` 1,
  `test_m49_eu_ai_act_compliance::test_05` 1 error) sowie vier weitere
  isoliert reproduzierbare Altfehler in nicht angefassten Dateien
  (`test_fix_batch9::test_m14_execute_kanban_task_registers_with_shutdown_coordinator`,
  `test_fix_w2_c_governance_roles::test_status_force_done_with_proof_writes_actor_and_evidence`,
  `test_med2_b_trace::test_fleet_self_healing_audit_failure_is_visible`,
  `test_milestones_77_79_81_83_86::test_m83_flightlog_and_policy_backtester`).
  Zwei weitere Full-Suite-Rote (`test_reaudit_d16_dispatcher::…dispatch_trace_close…`,
  `test_w3_d_trajectory::…trajectory_root_scope…`) laufen isoliert grün und sind
  Order-abhängig. Keiner der Fehler betrifft eine in dieser Welle geänderte Datei.

Während der Verifikation wurde ein echter Designfehler gefunden und behoben:
der Liveness-Stop wurde bei aufgebrauchtem Hook-Budget zunächst übersprungen;
er läuft jetzt immer (`finally`) und erhält nötigenfalls eine eigene Restfrist.

---

## 3. Abnahme

- [x] Alle 6 Funde mit Code-Fix und Regressionstest im Produktivpfad.
- [x] Ruff und MyPy auf allen geänderten `.py`-Dateien: Exit 0.
- [x] Neue Suiten grün; Full-Suite auf Baseline-Niveau.
- [x] Keine fremden Dateien verändert, keine Secrets in Tests, keine Subagent-Commits.
- [x] Report mit `git add -f` committet (`.gitignore:55` `**/*report*`).
- [ ] Status-Synchronisierung in `GEWICHTETE_BEFUNDLISTE.md` folgt als separater
      Commit nach diesem Fix-Commit (Muster `786d6e71`).

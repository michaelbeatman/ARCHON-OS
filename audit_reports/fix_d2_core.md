# Fix-Log D2 — Core-Nachlauf (Phase 3 Delegations)

**Agent:** Delegations-Agent D2 · **Datum:** 25.11.2026 · **Basis:** Arbeitsbaum nach A1–A9
**Exklusiver Dateibereich:** `core_dispatcher.py`, `backend/llm_egress_guard.py`,
`local_security_guard.py`, `backend/handoff_desk.py`, `backend/operations_api.py`,
`archon/core/delegation.py` (`backend/approval_policy_engine.py` und
`utils/notebook_engine.py` nur geprüft).
**G-01/G-02/G-05:** kein Event-Replay, keine Coroutine-Wiederholung, keine
DB-Migration (nur idempotentes `CREATE TABLE IF NOT EXISTS` in der
Spiegelungsfunktion), prozess-lokale Breaker unverändert. **Kein Commit, kein Push.**
**Shell:** wie bei allen Fix-Agenten blockiert (`pwsh.exe: Zugriff verweigert`) —
nur `read`/`edit`/`write`/`grep`/`glob` verwendet, keine Tests ausgeführt.

---

## 1. A6 → `backend/llm_egress_guard.py` — `bypassed` im Wrapper (D04/MED)

`enforce_egress_firewall_for_url()` (Z.670–722):

- Neuer, **expliziter Fail-Closed-Block** vor dem generischen Firewall-Block:
  `fw_res.get("bypassed") is True` → signierter Proof mit
  `action="llm_dispatch_blocked_egress_bypassed"`,
  `error_code="EGRESS_FIREWALL_BYPASSED"` + `ZeroEgressBlockedError`.
  Damit greift A6s Härtung auch im Wrapper, nicht nur direkt an
  `egress_firewall.check_url()`.
- `bypassed` wird aus `fw_res` in die Rückgabe übernommen
  (`"bypassed": bool(fw_res.get("bypassed", False))`, Z.719) und zusätzlich in
  den `extra`-Payload des generischen Blocks (Z.708) aufgenommen.
- **Verifikation A2:** `grep` findet weiterhin alle 11 von A2 konvertierten
  `_record_blocked_proof()`-Pfade (Z.231, 253, 290, 309, 531, 579, 629, 653,
  699, 742, 768) plus den neuen Bypass-Pfad (Z.679). Kein Pfad entfernt,
  kein direkter `record_llm_dispatch()`-Blockpfad eingeführt.

## 2. A8 → `local_security_guard.py` — Halluzinations-Judge (D15/HIGH)

`validate_ai_output()` (Z.282–371):

- Neuer `evaluation_failed = False` vor dem `use_llm`-Block.
- Leere Judge-Antwort (`reply == ""`) → `raise RuntimeError("EMPTY_JUDGE_RESPONSE")`
  (Z.333–336), wird vom bestehenden `except` gefangen.
- `except`: `evaluation_failed = True`, `base_score = min(base_score, 3)` unverändert
  erhalten; zusätzlich wird die Empfehlung hart überschrieben:
  `evaluation_failed → recommendation="NEEDS_HUMAN_REVIEW"` (Z.351–354),
  **nie `TRUST`**, auch bei niedrigem `min_score`.
- Return um `evaluation_failed` und `evaluation_marker`
  (`"JUDGE_EVALUATION_FAILED"` / `"ok"`) ergänzt; `passed` ist bei Fehler
  ebenfalls `False` (Z.365–369).
- **Regression geprüft:** A2s/B5s Klassifikator-Fix (Z.233–244, explizites
  `SAFE`, Fail-Closed `blocked` bei Fehler) wurde nicht angefasst.
  `use_llm=False` (Default, u. a. `tests/test_security_and_validation.py`)
  liefert unveränderte `score`/`recommendation`/`passed`.

## 3. A8 → `core_dispatcher.py` — Structured-Output-Chokepoint (D15/HIGH)

- Neuer task-lokaler ContextVar `_STRUCTURED_OUTPUT_SCHEMA_CTX` + öffentlicher
  Setter `set_structured_output_schema()` (Z.26–36) als Produzenten-Kante.
- Modul-Import `from backend.structured_output_enforcer import
  structured_output_enforcer` (Z.46) — per `grep` verifiziert, keine
  Namenskollision, kein weiterer Import im Chokepoint.
- Verdrahtung nach `_dispatch_to_omniroute_or_container_exec()`
  (also nach `parse_omniroute_response`/`_clean_dispatch_output`) und nach
  `_guard_silent_failures()`, **vor** Cache-Store und Budget-Settle
  (Z.1162–1206). Schemaquelle: ContextVar oder `res["output_schema"]` /
  `response_schema` / `schema`. Das DAG-Format `{"required": [...]}` wird auf
  das Enforcer-Format `{feld: typ}` abgebildet.
- Bei `valid is False` → `status="error"`,
  `error_code="STRUCTURED_OUTPUT_INVALID"`, `structured_output_validation`
  im Result; Enforcer-Exception ist fail-closed (gleicher Error-Code).
  `is_ok` liest den geänderten Status → kein Cache-Store, kein
  `budget_bank.settle` (Stattdessen `release` im `finally`).
- Ohne Schema bleibt der Pfad bewusst inaktiv (sonst würde der Enforcer jeden
  Freitext-Dispatch mit `schema_required` ablehnen).

## 4. A5 → `core_dispatcher.py` — `_guard_silent_failures()` (D13/HIGH)

Exakter Code-Vorschlag aus `fix_a5_trajectory.md` §3 übernommen (Z.118–174):

- `run_ids` enthält jetzt die **Trajectory-ID** via
  `normalize_trajectory_id(..., root_ticket_id=str(task_id))` **und** als
  Fallback die `current_trace_id()` (A5-Spiegelung). Beide Namesräume werden
  nacheinander abgefragt; bei Flags wird abgebrochen.
- Docstring korrigiert: Produzent schreibt unter `flightlog_run_id`, der
  Dispatcher prüft Trajectory-ID **und** Trace-ID.
- `run_id` im Audit-Payload ist die ID, die den Treffer geliefert hat.
- A5s Spiegelung in `agent_router.py` / `workflow_dag_runner.py` blieb
  unangetastet; kein Replay, keine Migration.

## 5. A9 → `core_dispatcher.py` — Boardroom-Cancel-`gather` (D07/MED)

- Neuer lokaler Helper `_record_failed_cancel()` + `_FAILED_CANCELS`
  (Z.50–66): ERROR-Log, prozess-lokale Liste, signiertes Audit-Event
  `category="recovery", action="cancel_failed"` (best effort).
- `finally` der Boardroom-Fan-out-Schleife (Z.2923–2955) wertet jetzt die
  `gather(..., return_exceptions=True)`-Liste aus: `asyncio.CancelledError`
  erwartet/ignoriert, jede andere `BaseException` → `_record_failed_cancel()`.
- Das Warten ist auf 10 s gedeckelt; bei Timeout werden die nicht beendeten
  Tasks **nicht aus der Registry gelöscht**, sondern ebenfalls als
  `failed_cancels` quittiert.

## 6. A7 → `core_dispatcher.py` — Fallback-Schleifen (D07/MED, Minimalvariante)

- `chain_deadline` im `_impl` (Z.1429–1430), identisch zum bereits vorhandenen
  90-s-Wrapper `_dispatch_to_omniroute_or_container_exec()`.
- Groq-, OmniRoute- und Container-Hops prüfen die Restzeit vor dem Start und
  nach jeder Exception (Z.2052, 2106, 2200, 2086, 2135, 2234).
- Die nackten `continue` in den Exception-Pfaden (Groq/OmniRoute/Container)
  sind durch `logger.warning` + `_provider_backoff(...)` + Deadline-Check
  ersetzt (Z.2084–2088, 2133–2137, 2232–2237). `ZeroEgressBlockedError`
  bleibt ein sofortiger harter Block (unverändert).
- **DELEGATED:** das vollständige `HopResult`-Modell (strukturierte
  Hop-Quittung pro Provider) wurde zugunsten der vom Auftrag erlaubten
  Minimalvariante nicht eingeführt.

## 7. A3 → `core_dispatcher.py` — busy_timeout-SSOT (H6)

`_log_dispatcher_usage_sync()` (Z.872–875): `busy_timeout=15000` und
`timeout=15.0` ersetzt durch `DB_BUSY_TIMEOUT_MS` aus `backend.db_paths`
(`timeout=DB_BUSY_TIMEOUT_MS / 1000.0`,
`PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};`). Keine Literale mehr — der
SSOT-Detektor (`audit_busy_timeout_ssot(..., --include-connect-timeout)`)
findet hier keine Abweichung mehr.

## 8. A8 → `backend/operations_api.py` + `backend/handoff_desk.py` — Handoff-Konsument

- `_accept_loaded_handoff()` (Z.973–1025) im Worker-Thread: liest die
  `handoff_id` über `latest_handoff_id_for_task()`, den autorisierten
  Empfänger aus dem **signierten** Envelope (`get_handoff()["to_agent"]`),
  ruft `accept_handoff()` und schreibt das Ergebnis als `task_events`-Event
  (`handoff_accepted` / `handoff_accept_failed`) **und** signiertes Audit
  (`handoff_accepted_by_worker`). Idempotent: bereits akzeptierte Envelopes
  erzeugen kein zweites Event (G-01/G-02).
- Verdrahtet in `_kanban_load_task_sync()` direkt nach dem Laden des
  Delegations-Envelopes (Z.1085–1090).
- `accept_handoff()` (`handoff_desk.py`, Z.417–425) gibt jetzt zusätzlich
  `receiving_agent`, `trace_id`, `session_id`, `correlation_id` aus dem
  verifizierten Envelope zurück — der Konsument übernimmt diese verifizierten
  Werte statt sie zu erfinden.
- `_merge_task_meta_facts()` (Z.1028–1068): merged `effective_prompt_info`
  sowie `trace_id`/`session_id`/`correlation_id` in `mc_task_meta`, ohne
  vorhandene Budget-/Trajectory-Werte zu überschreiben und ohne die
  Whitelist in `mission_control.py` (fremde Datei) zu erweitern.
- Die Fakten werden aus dem Dispatcher-Result (oder dem validierten
  Delegations-Payload) gebildet (Z.1516–1528) und in **alle** Worker-Events
  (`awaiting_approval`, `blocked`, `failed`, `completed`) übernommen
  (Z.1546, 1550, 1559 ff., 1572 ff.).

## 9. A5 → `archon/core/delegation.py` — Flightlog-Namensraum (Hinweis A5 §2)

`record_flight_event()` des Run-Abschlusses (Z.1283–1296) schreibt nicht mehr
`run_id=str(task_id)`, sondern `_flight_run_id =
normalize_trajectory_id(task_id if startswith("traj-") else None,
root_ticket_id=str(task_id))` — exakt derselbe Wert, den
`core_dispatcher._guard_silent_failures()` abfragt. Der dritte Namensraum ist
damit geschlossen; `_w_tid`/`_finalize_trajectory()` (A4-Fix) blieben
unverändert.

## 10. A2 → `archon/routers/operations_keys.py` — verifiziert, kein Edit

Datei liegt **außerhalb meines Dateibereichs**. Sie ist bereits korrigiert:
`api_create_key()` hat `except AuditWriteFailedError as exc: raise
HTTPException(status_code=exc.status_code, ...)` (Z.63–68) **und**
`except HTTPException: raise` (Z.69–70) vor der Blanket-500. Die neue 503
kommt damit an. Kein Edit, keine Delegation nötig.

## Geprüft, kein offener Nachlauf in meiner Domäne

- `backend/approval_policy_engine.py`: A6s `FINANCE_THRESHOLD_MIN_GAP = 0.01`,
  `_assert_finance_threshold_invariant()` und beide Aufrufstellen (Z.366,
  460) sind vorhanden. Kein Edit.
- `utils/notebook_engine.py`: im Phase-3-Bericht kein offener DELEGATED-Punkt
  (nur archivierter F-Fix); kein Edit.

---

## DELEGATED (außerhalb meines Dateibereichs / bewusst nicht umgesetzt)

1. **`HopResult`-Modell** für die Provider-Fallback-Schleifen
   (`core_dispatcher.py`): volle strukturierte Hop-Quittung pro Provider
   statt der hier umgesetzten Minimalvariante (warning + backoff + deadline).
2. **`archon/core/task_registry.py:cancel_all()`** (Z.67–68) entfernt
   registrierte Tasks auch bei `asyncio.TimeoutError` aus `_TASKS`. Der
   Dispatcher löscht bei Timeout nichts mehr (siehe #5), aber die zentrale
   Registry tut es weiterhin. Datei nicht in meinem Scope → ownerseitig
   korrigieren (nur bei Timeout, `failed_cancels` spiegeln).

## Verifikation / Limitierung

- Statisch: alle editierten Abschnitte erneut gelesen; Importe/Helfer per
  `grep` verifiziert (`structured_output_enforcer`,
  `normalize_trajectory_id`, `current_trace_id`, `detect_silent_failures`,
  `_provider_backoff`, `DB_BUSY_TIMEOUT_MS`, `accept_handoff`,
  `_record_blocked_proof`). Einrückung und Symbolverwendung geprüft.
- `pytest` / `ruff` / `mypy` / `py_compile`: **nicht ausführbar** — Shell
  blockiert (`pwsh.exe: Zugriff verweigert`). Kein „grün" behauptet; im
  Integrationslauf nachzuholen (insb. `test_d11_handoff_hardening.py`,
  `test_security_and_validation.py`, `test_reaudit_d16_dispatcher.py`,
  `test_med_d12_d13.py`).
- Bestehende Produzenten/Konsumenten und SSOT-Ketten wurden nicht verändert:
  A2-Beweis-Pfade, A5-Spiegelung, A6-Firewall-Result, A4-Trajectory-Finalize,
  A6-Schwellen-Invariante, B5-Klassifikator, G-05-Breaker.

**Zählung:** 9 umgesetzte Fixes · 2 DELEGATED · 1 verifiziert ohne Edit (A2-Router).

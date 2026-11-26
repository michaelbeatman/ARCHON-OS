# W3-C (Orchestrierung) — Implementierungs-Report

**Datum:** 26.11.2026 · **Scope:** D07-H1/H2, D11-H1/H2/H3, D11-M1/M2/M5 (+ Warrant-/Trace-Kontext)
**Grundlage:** `00_SOLL_SPEC.md` §1.1/§3/§4/§0, `GEWICHTETE_BEFUNDLISTE.md`, `domain_07.md`, `domain_11.md`
**Dateibesitz (nur diese wurden von mir geändert):**
`backend/operations_api.py`, `backend/operations_execution.py`, `archon/core/delegation.py`,
`backend/handoff_desk.py`, `backend/tool_warrants.py`, plus `tests/test_w3_c_handoff.py` und dieser Report.
**Keine Commits. Keine fremden Dateien. Kein Replay/Postgres.**

---

## 1. Umgesetzte Befunde

### D07-H1 — Zombie-Reset fail-closed (`backend/operations_api.py:347`)
- Importfehler von `backend.trajectory_budget.zombie_eligible` führt nicht mehr zu
  `zombie_eligible=None` → „alle eligible“. Stattdessen `logger.error` +
  Pflicht-Audit `recovery/zombie_guard_unavailable` + **`return 0`**.
- Zusätzlicher CAS in der UPDATE-Where: `AND (claim_expires IS NULL OR
  CAST(claim_expires AS REAL) <= now)`, sofern die Spalte existiert. Damit kann auch
  zwischen Lesen und Schreiben keine aktive Lease mehr überschrieben werden.
- Verifikation: `tests/test_w3_c_handoff.py::test_zombie_guard_import_error_never_resets_and_audits`
  (Task bleibt `in_progress`, Audit-Event vorhanden) und
  `::test_zombie_reset_still_respects_active_lease`.

### D07-H2 — Kein Dispatch ohne CAS-Lease (`backend/operations_execution.py:412`)
- `ARCHON_LEASE_FAIL_OPEN`-Branch vollständig entfernt; jeder `acquire_lease`-Fehler
  ⇒ `{"skipped": "lease_unavailable"}` + `logger.error` + Audit `recovery/lease_unavailable`.
- `acquired=False and task_exists=False` ⇒ ebenfalls `skipped` (kein Fallthrough).
- `acquired=True` mit leerem `lease_token` ⇒ `skipped`; zusätzliche Barriere vor dem
  Aufruf von `_execute_kanban_task_inner`. `_execute_kanban_task_inner` bleibt für
  direkte Legacy-Aufrufer (Tests) aufrufbar, wird aber vom Produktiv-Einstieg nie mehr
  ohne Token erreicht.
- Verifikation: `::test_lease_fail_open_env_is_ignored`,
  `::test_no_dispatch_without_valid_lease_token` (0 Dispatch-Aufrufe).

### D11-H1 — Delegations-HMAC vor Kanonisierung (`archon/core/delegation.py:223`)
- Neue SSOT-Helfer `is_signed_delegation_payload()` und
  `load_verified_delegation_payload()`: HMAC-Prüfung **vor** jeder Normalisierung;
  signierte Payloads werden nach `extra="forbid"`-Validierung **unverändert**
  zurückgegeben (kein Re-Sign, keine Server-Neuberechnung).
- `canonicalize_delegation_payload(require_signature=True)` prüft jetzt die
  **eingehende** Signatur vor der Kanonisierung (statt wie vorher die gerade
  überschriebene Signatur nachträglich zu „verifizieren“).
- Konsument (`backend/operations_api.py:273`, `backend/operations_execution.py:187`):
  signierte `created`-Events mit `require_signature=True` laden; bei Manipulation
  wird `_delegation_signature_invalid` gesetzt und der Task vor dem Dispatch
  hart geblockt (`delegation_signature_invalid`, kein LLM-Call).
- Verifikation: `::test_tampered_created_payload_is_rejected_before_canonicalization`,
  `::test_canonicalize_requires_valid_incoming_signature`,
  `::test_tampered_signature_means_zero_llm_calls`.

### D11-H2 — EIN signiertes Payload als SSOT (`archon/core/delegation.py:2113`)
- Produzent baut **ein** kanonisches Objekt mit vollem `auftrag`, `ziel_agent`,
  `extensions`, `trace_id`, `warrant_id`, Budget-Gewichtung und allen
  Watcher-/Lifecycle-Feldern und schreibt exakt dieses signierte JSON in
  `task_events.kind='created'` (statt der bisherigen verarmten Rekonstruktion
  mit `title = auftrag[:80]`). Die `state.db`-Nachricht enthält dieselbe
  kanonische Fassung (Mirror, nicht SSOT).
- Kind-Worker konsumiert das gespeicherte Objekt unverändert;
  `[STRUKTURIERTE_DELEGATION_JSON]` ist keine neue Projektion mehr.
- Verifikation: `::test_producer_writes_single_signed_payload_and_envelope_before_dispatch`,
  `::test_worker_reads_full_signed_payload_unchanged` (volle 400 Zeichen + Extensions
  + Original-Signatur erhalten).

### D11-H3 — Envelope vor Dispatch, harter Gate (`backend/handoff_desk.py:504`)
- `require_accepted_handoff(..., require_envelope=True)`: fehlender oder
  HMAC-ungültiger Envelope ⇒ `allowed=False` (`missing_handoff_envelope` /
  `handoff_hmac_invalid`), kein `no_handoff_for_task`-Freischein für Delegationen.
- Produzent legt den signierten Annahme-Envelope **vor** dem Worker-Spawn an
  (`from_agent=delegator`, `to_agent=ziel`, `trace_id`/`session_id` aus der
  signierten Übergabe) und verifiziert ihn sofort; bei Fehler ⇒ Task `blocked`,
  `_block_receipt`, kein Dispatch.
- Gate bevorzugt den Envelope der Empfängerkante (`to_agent=executor`), fällt aber
  für die `executor_mismatch`-Erkennung auf den neuesten Envelope zurück.
- Verifikation: `::test_handoff_gate_requires_envelope`,
  `::test_missing_envelope_means_zero_llm_calls` (0 LLM-Calls).

### D11-M1 — Explizite Positiv-Feldliste (`backend/operations_execution.py:36`)
- `model_dump(exclude_defaults=True)` ersetzt durch `_DELEGATION_CHILD_FIELDS`.
  Damit erscheinen im Child-Prompt auch Default-Werte (`taint_status="unknown"`,
  `soul_mode="compact"`, `budget_remaining_tokens=None`, leere ACLs) sowie
  `trace_id`, `warrant_id`, `complexity_weight`, `budget_share_pct`, `token_budget`.
- `trace_id` wird zusätzlich serverseitig aus `current_trace_id()` ergänzt
  (Produzent: `resolve_server_delegation_context`, Konsument: Fallback im Worker).

### D11-M2 — SOUL-Tier konsumiert (`backend/operations_execution.py`)
- Der signierte `soul_mode` wird im Worker über `active_soul_tier_text(assignee, mode)`
  in den `system_prompt` injiziert (`[AKTIVER_SOUL_TIER: …]`). Fehlt ein explizit
  angeforderter `pro`/`full`-Tier, wird das auf `ERROR` sichtbar gemacht.

### D11-M5 — Budget-Gewichtung signiert mitgeführt (`archon/core/delegation.py`)
- Neue signierte Schemafelder `complexity_weight`, `budget_share_pct`,
  `token_budget`; Auflösung **serverseitig** aus `task_budget_allocations`
  (`agentic_memory.db`) in `resolve_server_delegation_context`, nie aus dem
  LLM-Payload. Die Werte landen im Child-Prompt als verbindliche Constraints;
  die `BudgetBank`-Durchsetzung bleibt unverändert.

### W2-B-Hinweis — `!UNKNOWN_AGENT!` hart blockiert (`backend/operations_execution.py`)
- `resolve_agent_id(raw_assignee, known_ids=<Profile-SSOT>)`; der Sentinel
  `UNKNOWN_AGENT_ID` führt zu `blocked`/`UNKNOWN_AGENT_ID` und 0 Dispatch.
  Für signierte Delegationen ist eine leere Profil-SSOT ebenfalls ein harter Block.
- Verifikation: `::test_unknown_agent_sentinel_is_blocked`.

### Zusatz — Warrant-Vererbung (`backend/tool_warrants.py:164`)
- `latest_warrant_payload_for_session()` + `inherit_warrant_for_session()`:
  gültiges Parent-Warrant wird (Signatur + Ablauf geprüft) als eigenes, an die
  Kind-Session gebundenes Warrant neu ausgestellt und registriert; die
  `warrant_id` ist signiertes Delegationsfeld. Ohne Parent-Warrant bleibt sie leer
  (keine stillen Zusatzrechte).
- Verifikation: `::test_warrant_is_inherited_to_child_session`.

---

## 2. Nicht in diesem Patch (Dateibesitz / andere Welle)

| Befund | Ort | Grund / Empfehlung |
|---|---|---|
| **D11-M3** | `backend/lossless_session_dag.py:342-363,179-198` | Nicht in meinem Dateibesitz. Fix: `dedup_key` um `seq`/ explizite `turn_id` ergänzen; `derive_session_id()` auf explizite Korrelationsfelder verpflichten. |
| **D11-M4** | `archon/routers/boardroom.py:498-505` | Nicht in meinem Dateibesitz. Fix: `mark_truncated(str(...), 1500, artifact=f"boardroom.history/{history_id}")` mit Volltext als `deliverables`. `mark_truncated()` selbst (in meiner Datei) unterstützt `artifact` bereits. |
| **D07-H2 (Rest)** | `archon/core/orchestration.py:426` | Der identische Fail-Open-Schalter existiert auch im Mission-Control-Pfad (D02-H2). Nicht in meinem Dateibesitz; dort ebenfalls entfernen. In `.env.example` kommt der Schalter nicht vor. |

---

## 3. Verifikation

- `python -m py_compile` auf allen fünf geänderten Produktivdateien: Exit 0.
- `python -m pytest -q tests/test_w3_c_handoff.py` → **15 passed**.
- Regressionslauf `test_reaudit_stage7`, `test_fix_w3_a_orchestration`,
  `test_d11_handoff_hardening`, `test_med_d11`, `test_fix_w3_b_performance`,
  `test_d3_execution_characterization`, `test_med2_c_orchestration`,
  `test_p2_delegation_*`, `test_f22_dag_and_delegation_gates` → **99 passed, 1 failed**.
  Der Fehler ist **vorbestehend und nicht durch diesen Patch verursacht**:
  - `test_med2_c_orchestration.py::test_reserve_tokens_enforces_cap_during_run`
    scheitert auch isoliert (`close_trajectory` → `completed` statt `blocked`,
    `trajectory_budget.py`, fremder Dateibesitz).
  - `test_fix_w3_b_performance.py::test_prefetcher_closes_connection_on_error_and_caps_lru`
    ist ordnungsabhängig (im Kombi-Lauf grün, in einem kleineren Setup durch
    gemeinsamen DB-Zustand rot); `speculative_prefetcher` ist fremder Dateibesitz.

**NEVER_DO_LIST:** kein Coroutine-Replay, keine PostgreSQL-Migration, keine eigene
Content-Domäne — alle drei Negativconstraints eingehalten.

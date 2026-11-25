# Fix-Report W3-A — Orchestrierung + Handoff (F030 / F031 / F033, D11 / D13 / D07)

**Datum:** 25.11.2026 · **Welle:** W3-A · **Basis:** `00_SOLL_SPEC.md` §0/§1.1/§4, `domain_02.md` (8), `domain_11.md` (10), `domain_13.md` (MED), `domain_14.md` (H-14-1), `domain_07.md` (chat.py), `MASTER_PLAN.md` §4/§5.
**Ownership:** ausschließlich die im Auftrag genannten Dateien. `core_dispatcher.py`, `main.py`, `backend/operations_api.py`, `backend/workflow_dag_runner.py`, `backend/workflow_scheduler.py`, `backend/trajectory_budget.py`, `backend/role_budget_engine.py` wurden **nicht** verändert (W3-B/D).

---

## 1. Umgesetzte Findings

### H-02-1 — Unknown-Agent fail-closed (`archon/core/delegation.py:888`, `:1968`)
- Substring-Schritt 5 (`role`/`name`) in `_resolve_target_agent_id()` ersatzlos entfernt. Ein halluziniertes `ziel_agent="orchestrator"` trifft nicht mehr auf `@default` (APEX + `terminal`/`filesystem`).
- Nach der Auflösung wird die Ziel-ID gegen die tier-geprüfte Profil-SSOT geprüft; ein Alias auf eine unbekannte ID wird ebenfalls verworfen.
- Unbekannte Ziele laufen über `_block_receipt(..., "UNKNOWN_AGENT", ...)` → `status=blocked`, `block_kind=unknown_agent`, Audit + HITL-Hinweis. Kein Freitext-Erfolg mehr.

### H-02-2 + MED — `cancelled` im Fan-in (`orchestration.py:1220`, `delegation.py`, `orchestration.py:1822`)
- `terminal_states` enthält jetzt `cancelled`; `failed_siblings` behandelt es als Fehlschlag: Parent `status=blocked`, `failure_reason="Teilaufgabe abgebrochen: <ids>"`, `fan_in_escalation="hitl_required"`, keine Synthese. Die reine Entscheidung wurde als `fan_in_start_decision()` herausgezogen (testbar ohne SQLite/Locks).
- Delegations-Watcher: `cancelled` im Terminal-Tupel, `mc_status="cancelled"`, `task_events`-Eintrag `kind='cancelled'` (nur wenn noch keiner existiert), anschließend `_invoke_fan_in(fan_parent)`.
- `recover_stale_synthesis()` erkennt jetzt auch Projekte, die **nie** `synthesis_started` bekamen, weil ein Kind `cancelled` war (Nach Deploy): Parent wird blockiert + eskaliert. Kein Coroutine-Replay.

### H-11-1/2 — EIN kanonisches Handoff-Schema (`delegation.py:33/154/233`)
- `HandoffDelegationPayload` mit `extra="forbid"` vereint `DelegationPayload` **und** `KanbanDelegationPayload` (Aliase `DelegationPayload`/`KanbanDelegationPayload` zeigen auf dasselbe Objekt). Neue Felder: `tenant_id`, `project_id`, `cancel_scope`, `taint_status`, `budget_remaining_tokens`, `soul_mode`, `extensions`, `payload_signature`, verdict-Felder.
- `canonicalize_delegation_payload()` validiert **einmal**, führt unbekannte Keys dokumentiert in `extensions` (statt stiller Projektion), löst Tenant/Budget/Taint/Cancel **serverseitig** aus `tenant_context` / `trajectory_budget` / `session_taint_guard` auf und signiert mit HMAC-SHA256 (`ARCHON_DELEGATION_HMAC_KEY`, Fallback Audit-Key; ohne Key → fail-closed `RuntimeError`).
- Child-Cancel-Token: `get_task_child_token("task:<parent>", "task:<child>")` (`backend/cancellation.py:294`) erzeugt den echten Kind-Scope; das Kind wird am Worker registriert und `cancel_scope`/Signatur in `task_events.created` persistiert.
- **Querschnitt an W3-B:** `backend/operations_api.py` gehört nicht zu W3-A. Die Kompatibilitätsfunktion `canonicalize_delegation_payload()` steht hier bereit; `_load_kanban_delegation_payload()` muss dort durch genau **einen** Aufruf ersetzt werden (kein zweites `model_dump()` mehr). Ebenso muss der Worker `t_dict.get("tenant") or t_dict.get("tenant_id")` über `precedent_log.resolve_task_tenant_id()` auflösen und vor dem Dispatch `handoff_desk.require_accepted_handoff()` als harten Gate nutzen (siehe §3).

### H-14-1 — Fan-in-Marker-Produzent (`orchestration.py:114/154`)
- `extract_dispatch_verdict()` liest `consensus_verdict`/`verdict`/`decision_status` und `guardrail_result`/`policy_violation` aus dem **echten** `dispatch_to_omniroute_or_container()`-Result und schreibt sie auf den Kind-Task — nicht nur `result_summary=reply`.
- Beide Subtask-Erzeugungspfade (Haupt- und Sandy-Pfad) legen die Felder von Anfang an deklariert an. `_marker_line` ist nie dauerhaft `""`: ohne strukturiertes Urteil erscheint `KEINE_STIMME_STRUKTURIERT:<…>` (explizite Enthaltung, kein erfundenes Ja/Nein). `resolve_debate_consensus()` zählt damit echte Stimmen; Policy-Veto bleibt hart.
- `DebateStatement` kennt `verdict_source`/`guardrail_violation` (weiterhin `extra="forbid"`). `extract_guardrail_result()` in `backend/consensus_gate.py` ist der kanonische Veto-Produzent für W3-B/D.

### D13-MED — Guardian-Wirkung, gezählter Retry, Depth-SSOT
- `save_circuit_breaker_limits()` (`autonomy_settings.py:33`) schreibt `loop_detection_enabled`/`max_steps_per_task` in `settings.json:circuit_breaker` — genau den Pfad, den `agent_router._get_guardian_policy()` liest. `api_save_guardian_config()` ruft es auf (Fehler → 503); der GET zeigt die effektiven Werte. `GUARDIAN_LIMITS_FILE` ist der gemeinsame Dateipfad für Guardian und AgentRouter (kein Host-/Container-Drift mehr).
- **Nachzug zu W3-D (abgeschlossen):** `allow_repeat=True` im AgentRouter ist kein RAM-Zähler mehr, sondern konsumiert das **persistierte `repeat_budget` aus `backend/trajectory_budget.py`**. Der eigene `counted_retry_allowed()`-Zähler wurde entfernt; `reserve_hop(..., allow_repeat=True)` liefert bei Erschöpfung `CYCLE_DETECTED` + `detail=REPEAT_BUDGET_EXCEEDED` mit `repeat_used`/`repeat_limit`, der Router gibt die Budget-Reservierung frei und bricht hart ab (BudgetExceededError). Damit existiert nur **eine** Zähler-SSOT (auch über Neustarts hinweg).
- `delegation.py` importiert `MAX_DELEGATION_DEPTH` direkt aus `backend/trajectory_budget.py` (SSOT W3-D, `:631`), fail-closed Fallback 3. `_hard_depth = min(_MAX_DELEGATION_DEPTH, …)`, `ensure_trajectory(max_hops=_MAX_DELEGATION_DEPTH)` und die `_put_chain()`-Truncation (`:1922`) nutzen **dieselbe** Konstante — keine lokale 5 mehr. Stumme Fanout-Slices in `orchestration.py` werden als `FANOUT_CAP` mit Ticker + Audit quittiert.

### D11-MED + D07-chat — Kontextverlust, Tenant, HANDOFF-Gate
- `preview=lines[0]` und der stille 3-Nachrichten-`break` in `backend/agent_router.py` waren bereits in W1-B behoben (Verifizierung: `mark_truncated()` über den Voltext, System-Streifen mit `dropped`). Unverändert übernommen.
- `history_with_dropped_marker()` (`chat.py:104`) setzt bei jeder History-Kürzung einen `[CHAT-HISTORY GEKÜRZT: N …]`-Streifen; `_load_state_history()` zählt die tatsächlich verworfenen Turns. Für `core_dispatcher.py`/`agent_chat.py` (W3-B/D) als Helfer bereitgestellt.
- `precedent_log.canonical_tenant_id()` / `resolve_task_tenant_id()` (`precedent_log.py:66/84`) lösen `tenant` (Kanban-Spalte) und `tenant_id` kanonisch auf — die physische Spalte ist SSOT, nie hart `"default"`. Kanban-Precedent-Endpunkte konsumieren den Kanoniker.
- `require_accepted_handoff()` (`handoff_desk.py:491`) ist der harte Gate: Empfängeridentität vom echten Executor (nicht aus dem signierten Envelope), HMAC/Schema erneut geprüft, `allowed=False` ⇒ Task `blocked` + HITL. Die `hermes-orchestrator`-Self-Attestation wurde entfernt; `/api/handoff/{id}/accept` (mesh.py) leitet den Empfänger aus der Kanban-SSOT ab.
- `soul_mode` ist im kanonischen Payload deklariert, wird serverseitig gesetzt, in `task_events.created` persistiert und über `active_soul_tier_text()` (`delegation.py`, bereits W2-C) als System-Tier in die Sub-Session geladen.
- `backend/agent_aliases.py` konsumiert jetzt `config/org_hierarchy.json.aliases` als SSOT (Legacy-Map nur noch Fallback).

---

## 2. Verifikation

- **Shell:** zeitweise `pwsh.exe: Zugriff verweigert` (wie in W0–W2); alle unten genannten Kommandos liefen erfolgreich. Der Zustand `archon/core/cancellation.py` existiert nicht — kanonisch ist `backend/cancellation.py` (so auch `domain_07.md`); es wurde **kein** toter Shim angelegt.
- **Kein Test gegen Produktiv-DBs:** alle Testläufe mit `ARCHON_DATA_DIR=C:\Users\micha\AppData\Local\Temp\opencode\archon-testdata-w3a*`.
- `compileall -q` über alle 14 geänderten `.py`-Dateien + neue Testdatei → **Exit 0**. Import-Smoke aller Module → **ok**.
- Neue Tests `tests/test_fix_w3_a_orchestration.py` → **15 passed** (Unknown-Agent, cancelled-Fan-in, Marker-Produzent, kanonisches Schema/Signatur, Child-Cancel, Guardian-SSOT, W3-D-`repeat_budget`-Konsumtion via `reserve_hop`, History-/Tenant-/Handoff-Marker).
- Gezielte Regression (11 Dateien: `test_d11_handoff_hardening`, `test_p1_multiagent_hardening`, `test_p2_delegation_batch_d`, `test_med_d14`, `test_wave1_consensus_hardening`, `test_p2_deterministic_fan_in`, `test_orchestration`, `test_core_a3_orchestration_limits`, `test_med2_c_orchestration`, `test_med_d12_d13`, `test_fix_w2_c_governance_roles`) → **120 passed, 2 failed**.
- Die 2 Fehler (`test_role_budget_engine_enforces_global_daily_cost_cap`, `test_d13_expired_reservation_still_settles_real_usage`) liegen in `role_budget_engine`/`trajectory_budget` (W3-D) und sind **nicht** durch W3-A verursacht: `db_paths` lädt trotz `ARCHON_DATA_DIR` eine externe `C:\Users\micha\.hermes\agentic_memory.db` („Split-Brain"-Warnung), wodurch Budget-Reservierungen aus fremdem Zustand abgelehnt werden. Isoliert reproducerbar ohne W3-A-Module.

---

## 3. Querschnitt / Ownership-Hinweise

1. **`backend/operations_api.py` (W3-B):** doppelte `model_dump()`-Projektion in `_load_kanban_delegation_payload()` durch `canonicalize_delegation_payload(raw, trajectory_id=…, task_id=…, session_id=…)` ersetzen; Worker-Tenant über `resolve_task_tenant_id(t_dict)`; vor `dispatch_to_omniroute_or_container()` `require_accepted_handoff(task_id, executor)` prüfen und bei `allowed=False` Task `blocked` + HITL/DLQ (0 LLM-Calls). Beide Helfer liegen in W3-A-Dateien und sind importbereit.
2. **`core_dispatcher.py` / `archon/routers/agent_chat.py` (W3-B/D):** `history[-8:]` über `history_with_dropped_marker()` aus `archon/routers/chat.py` laufen lassen; dort ist der `dropped`-Marker noch still.
3. **`backend/trajectory_budget.py` (W3-D):** `MAX_DELEGATION_DEPTH=3`, `clamp_max_hops()` und das persistierte `repeat_budget` (inkl. `set_repeat_budget`/`repeat_budget_status`) werden von W3-A konsumiert; keine Änderung nötig. W3-Ds `extract_guardrail_result()` bleibt kanonisch für den Boardroom-Produzenten; W3-A stellt denselben Helfer für den Orchestrierungs-Fan-in bereit (`backend/consensus_gate.py`).
4. **`archon/routers/v2_capabilities.py`:** B-11 war bereits in W1-B gefixt — unverändert übernommen.
5. **`archon/core/cancellation.py`:** existiert nicht und wurde bewusst nicht als Stub angelegt; `backend/cancellation.py` ist die SSOT.

---

## 4. NEVER_DO_LIST

Kein Coroutine-Replay, keine PostgreSQL-Migration, keine eigene Content-Domäne. Alle Änderungen sind deterministische Validierungs-/Audit-/Gate-Logik; keine simulierten Erfolge, keine gelöschten oder geskippten Tests.

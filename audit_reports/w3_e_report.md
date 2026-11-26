# Fix-Report W3-E — Entscheidungs-Hoheit & Konfliktlösung (Domäne 14)

**Datum:** 26.11.2026 · **Scope:** `D14-H1`, `D14-M1`…`D14-M5`
**Maßstab:** `audit_reports/00_SOLL_SPEC.md` §1.1/§2.4/§2.5, `audit_reports/domain_14.md`, `audit_reports/GEWICHTETE_BEFUNDLISTE.md`
**Besitz:** `backend/consensus_gate.py`, `backend/lossless_session_dag.py`, `archon/routers/boardroom.py`, `backend/kanban_verifier.py`, `archon/routers/kanban.py`, `backend/mcp_gateway.py`, `backend/approval_policy_engine.py`
**Nicht gemacht:** keine Commits, keine fremden Dateien, kein Coroutine-Replay, keine PostgreSQL-Migration.

---

## Status

| ID | Krit | Befund | Status | Nachweis |
|---|---|---|---|---|
| D14-H1 | HIGH | HITL-Override mit Body-Freitext / leerem Proof fälschbar | **Behoben** | `backend/kanban_verifier.py:35,202,442,514`; `archon/routers/kanban.py:191,211,235,278` |
| D14-M1 | MED | Tier-Veto `break` nach erstem Tier, `tie_break` dekorativ | **Behoben** | `backend/consensus_gate.py:232,301,329–386` |
| D14-M2 | MED | `run_storm_panel()` ohne Produktivkonsument | **Behoben (verdrahtet)** | `archon/routers/boardroom.py:427,771,937,994` |
| D14-M3 | MED | Konsens-Begründung nicht im Archiv/HMAC-Audit | **Behoben** | `archon/routers/boardroom.py:120,355,636,668,835,994` |
| D14-M4 | MED | MCP-HITL ohne `requester_id` → Ersteller-Sperre wirkungslos | **Behoben** | `backend/mcp_gateway.py:38,565`; `backend/approval_policy_engine.py:32,544,657` |
| D14-M5 | MED | Cross-Modell-Helfer nur Precheck ohne Modellaufruf | **Behoben** | `backend/kanban_verifier.py:404,442,514`; SSOT `backend/operations_execution.py:931` (unverändert) |

---

## D14-H1 — Hoheitsakt HITL-Override (HIGH)

**Vorher:** Router las `result_text`, `proof_command`, `primary_model`, `diff_text` aus dem Body; `run_proof_command("")` lieferte `passed=True, skipped=True`; Cross-Call war ein Precheck ohne LLM; kein Passkey-Proof; Audit-Fehler nur `logger.warning`.

**Jetzt (Kette, fail-closed):**

1. `archon/routers/kanban.py:211–246` übernimmt aus dem Body **nur** `action`, `token_budget`, `current_budget` und das Einmal-Token `hitl_proof_token` (alias `proof_token`). `result_text`/`proof_command`/`primary_model`/`diff_text` werden nicht mehr gelesen.
2. `backend/kanban_verifier.py:514` `resolve_card_hitl_decision_verified()` erzwingt Reihenfolge: Vier-Augen-Erstellerabgleich → Passkey-Proof → Task-Kontext → echter Proof → echter Cross-Modell-Call → Entscheidung.
3. `load_hitl_proof_context()` (`:442`) liest ausschließlich `backend.kanban_sidecar.load_kanban_meta()["tasks"][task_id]` und die `tasks`-Tabelle der aktiven Kanban-DB. `primary_model` kommt aus Meta/`model_override` (Rollen-SSOT des Dispatches), nie aus dem Body. Der Router-Erstellerleser `:191` erhielt zusätzlich `row_factory = sqlite3.Row` — ohne diesen Fix scheiterte der Abgleich an `tuple['created_by']` (latenter Fehler im Altcode).
4. `run_proof_command(..., require_proof=True)` (`:35`) lehnt ein leeres Kommando mit `passed=False, exit_code=-1, error_code='EMPTY_PROOF_COMMAND'` ab. `resolve_card_hitl_decision(..., require_full_proof=True)` (`:202`) verlangt zusätzlich `verified=True`, `proof.skipped is False`, `proof.exit_code == 0`, `passkey_verified=True` und einen echten Cross-Call (`model_call is True`). Ohne diese Nachweise → `next_status='blocked'`, `block_kind='override_proof_missing_hitl'`.
5. Passkey: `consume_hitl_proof_token(token, actor, category='system', action='kanban_hitl_override', resource=task_id, consume=True)` — an Aktion **und** Karte gebunden, genau einmal verbraucht. Fehler → `hitl_proof_unavailable` (fail-closed).
6. `archon/routers/kanban.py:278` ruft `_require_audit_event()` **vor** `update_task_status()`. Ein Audit-Schreibfehler → HTTP 503 und kein Statuswechsel. Das signierte Payload enthält Actor, Ersteller, alter/neuer Budgetwert, Proof, Cross-Modell-Ergebnis und `hitl_proof_verified`.
7. Rückwärtskompatibilität: die alte sync-Funktion `resolve_card_hitl_decision()` und `run_proof_command()` ohne `require_proof` bleiben für Bibliotheksaufrufe/Alt-Tests unverändert; der **Produktivpfad** benutzt ausschließlich den neuen verifizierten Pfad.

**Regression:** `{"action":"override_budget","result_text":"beliebig"}` → 403/`blocked`, Karte bleibt `blocked`; geprüft in `tests/test_w3_e_authority.py`.

---

## D14-M1 — Tier-Veto, Tie-Break, Beweispflicht

`backend/consensus_gate.py:232`: `tie_break` wird gegen `{_DEFAULT_TIE_BREAK_RULE, "no_consensus"}` validiert; unbekannte Werte → `ValueError`. `authority_enabled` schaltet die gewichtete Autoritätsmehrheit ab, wenn `"no_consensus"` gewählt wurde — der Parameter wirkt jetzt tatsächlich.

`backend/consensus_gate.py:329–386`: Die Höchst-Tier-Schleife bricht **nur** bei einer echten Entscheidung ab (Veto `no>yes` oder einstimmiges Ja als Tie-Break). Ein gespaltenes Tier (`yes>0` und `no>0`) wird in `unresolved_splits` vermerkt und die Schleife läuft mit `continue` zum nächsten Tier. Damit wird das klare `no` eines nachgelagerten Lead-Tiers nicht mehr vom gespaltenen Executive-Tier verdeckt. Bleibt kein Tier entscheidend, wird hart `NO_CONSENSUS` + `applied_tie_break='tier_conflict:unresolved:<tier>'` gesetzt (HITL). `applied_tie_break` wird bei jedem aufgelösten oder ungelösten Konflikt gesetzt.

**Regression:** 10-Statements-Fall (1 Exec NO / 1 Exec YES / 2 Leads NO / 6 Specialists YES) → `NO_CONSENSUS_BY_AUTHORITY`, `veto_by='cloud_architect'`, `applied_tie_break='highest_tier:lead:no'`. Bestehende Erwartung `CONSENSUS_REACHED_BY_AUTHORITY` bei einstimmigem Executive-Ja bleibt erhalten.

---

## D14-M2 — STORM-Panel M94 im Produktivpfad

`archon/routers/boardroom.py:427` ` _run_no_consensus_storm_panel()` ruft `backend.lossless_session_dag.run_storm_panel()` in **beiden** NO_CONSENSUS-Pfaden auf: `api_run_boardroom()` (`:771`) und `api_stream_boardroom()` (`:937`).

- Seats sind die registrierten Debatten-Teilnehmer; ihre Perspektiven kommen aus den echten `agent_response`-Events der gerade beendeten Debatte (im Stream über `running_perspectives` gesammelt). Der Judge ist der echte Chairman-Synthese-Dispatch. Es werden keine erfundenen Stimmen und keine zusätzlichen LLM-Calls erzeugt.
- Das Ergebnis wird in `res['storm_panel']`, in `hist_entry['storm_panel']`, in die HITL-Eskalation (`extra`) und in die HMAC-Audit-Kette (`decision_saved`, `no_consensus_escalated`) geschrieben.
- `requires_human_gate=True` wird über `human_gate_consumed` tatsächlich konsumiert: `decision_status='no_consensus'`, kein `decision`-Workflow-Event, echte HITL-Eskalation. Ein Panel-Fehler ist fail-closed (ebenfalls HITL, nie finale Entscheidung). Im Stream wird nach dem `await` `cancel_token.check()` ausgeführt.

Damit sind Produzent, Konsument, Effekt und Verifikation im Produktivpfad nachweisbar (`§0`). `backend/lossless_session_dag.py` musste nicht geändert werden — das bestehende Modul wurde unverändert konsumiert.

---

## D14-M3 — Konsens-Begründung revisionssicher

`archon/routers/boardroom.py:355` `_consensus_audit_object()` baut aus dem `done`-Event das vollständige Objekt: `verdict`, `yes_votes`, `total_votes`, `required_votes`, `evidence` (je `agent_id`/`marker`/`tier`, Tier aus Rollen-SSOT), `applied_tie_break`, `tie_break_rule`, `authority_weights`, `severity`, `veto_by`, `critique_error`. Felder, die der Dispatcher noch nicht mitsendet, bleiben explizit `None` statt erfunden zu werden; `applied_tie_break` wird bei `NO_CONSENSUS_BY_AUTHORITY` aus dem Veto-Tier rekonstruiert.

Das Objekt landet in `hist_entry['consensus']` (`:835`/`:994`, zusätzlicher Fallback in `_persist_boardroom_result_sync` `:680`) und in den Audit-Payloads `decision_saved` (`:155`) und `no_consensus_escalated` (`:636`, `:668`).

**Archiv-Test:** Bei `NO_CONSENSUS_BY_AUTHORITY` enthalten History und Audit-Kette das auslösende Tier (`lead`) und die Stimme (`cloud_architect`) inklusive `applied_tie_break='highest_tier:lead:no'`.

---

## D14-M4 — MCP-HITL-Ersteller / Vier-Augen

`backend/mcp_gateway.py:38` `_mcp_requester_identity()` leitet den Principal aus der verifizierten Key-Identität ab (`actor`/`service_principal`, sonst `mcp-key:<key_id> (<name>)`). `_check_hitl_gate()` (`:565`) übergibt ihn als `requester_id` und setzt `_requester_id` sowie `_requester_required` im signierten Payload. Ohne Key-Identität wird der HITL-Antrag nicht angelegt (fail-closed).

`backend/approval_policy_engine.py:32` deklariert `HITL_REQUIRED_DOMAINS` (`agent_dispatch`, `boardroom`, `workflow_authoring`, `context_hygiene`, `system`, `governance`). `evaluate_and_enqueue()` (`:544`) markiert diese Anträge (sowie `force_four_eyes` und explizites `requester_required`) mit `_requester_required`. `approve_request()` (`:657`) lehnt bei gesetztem Marker und leerem Ersteller mit `ValueError` ab (`:691`) — statt wie vorher still freizugeben. Die bestehende Identitätsprüfung gegen einen bekannten Ersteller bleibt aktiv.

**Regression:** MCP-Request → `approval_requests.requester_id='mcp-key:k1 (desk-key)'`; Freigabe durch denselben Principal → `ValueError`/403; identischer Ersteller bei HITL-Domain ohne Antragsteller → `ValueError`. Legacy-Finance-/ERP-Aufrufer ohne Ersteller bleiben zur Kompatibilität unverändert (siehe "Grenzen").

---

## D14-M5 — Cross-Modell ist ein echter Dispatch

`backend/kanban_verifier.py:404` `cross_model_verify_card()` bleibt bewusst die **Precheck-Hälfte** der SSOT und deklariert jetzt explizit `model_call=False` im Ergebnis; der reason-Text verweist auf die SSOT. Der einzige echte Modellaufruf bleibt `backend/operations_execution.py:931` `_cross_model_verify_task_result()` (fremde Datei, unverändert), der den Precheck aufruft und bei Dispatch-Fehler/fehlender Begründung fail-closed blockiert.

Der Override-Pfad `resolve_card_hitl_decision_verified()` (`:514`) ruft genau diese SSOT mit dem aus dem Task-Kontext geladenen `primary_model`/`diff_text`/`result_text` auf und verlangt `passed=True` **und** `model_call=True`. Fehler oder reiner Precheck → `blocked`. Damit ist die im Audit genannte Alternative „Override-Pfad direkt auf `_cross_model_verify_task_result()` umstellen" umgesetzt; es gibt keine zweite Dispatch-Implementierung.

**Regression:** Override mit nicht erreichbarem Verifier → 403/`blocked`, kein Statuswechsel.

---

## Verifikation

- `python -m pytest -q tests/test_w3_e_authority.py` → **14 passed** (inkl. Stream-Pfad).
- Gezielte Regressionsrunde (16 testdateien, u. a. `test_med_d14.py`, `test_med2_d_routers.py`, `test_hardening_wave1_d04_d14.py`, `test_milestones_*`, `test_wave1_consensus_hardening.py`, `test_p2_consensus_wiring.py`, `test_fix_batch5.py`, `test_w2_e_firewall_contract.py`) → **146 passed**, 3 `FAILED`.
- Die 3 Fehlschläge sind **vorbestehende Umgebungsprobleme / parallele W3-Arbeiten**, keine Regression aus W3-E: `sqlite3.DatabaseError: database disk image is malformed` im gemeinsamen `data/audit_log.db` (Taint-Guard) sowie geänderte Erwartungen in `flightlog_backtester.py` (`tool_loop:terminal@traj-…`) und `tool_output_firewall` durch andere W3-Agents. In einer größeren Runde mit zusätzlichen Domänen traten außerdem `TRAJECTORY_CAP_BLOCKED` und weitere `audit_log.db`-Fehler auf. Keiner der Fehlschläge berührt die in diesem Report geänderten Pfade.
- `py_compile` aller sieben besitzenden Dateien: Exit 0.

## Grenzen / bewusst nicht geändert

- `backend/lossless_session_dag.py` und `backend/operations_execution.py` bleiben unverändert (fremder Besitz bzw. korrekt vorhandene SSOT).
- `run_proof_command("")` ohne `require_proof` behält sein Legacy-Verhalten (`skipped=True`) für den regulären Abschlusspfad; der Hoheits-Override ist davon ausdrücklich ausgenommen und hart fail-closed.
- Die Engine-Fail-Closed-Regel greift für HITL-pflichtige Domains und explizit markierte Anträge. Reine Legacy-Finance-/ERP-Aufrufer ohne `requester_id` verhalten sich kompatibel (kein Self-Approval-Schutz in diesem Altpfad — separater Befund, nicht Teil von D14-M4).
- Kein Replay, keine PostgreSQL-Migration, keine eigene Content-Domäne (`NEVER_DO_LIST` eingehalten).

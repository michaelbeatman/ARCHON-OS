# Fix-Log A4 — Orchestrierung / Entscheidungshoheit (Phase 3 Remediation)

**Agent:** Fix-Agent A4 · **Basis:** HEAD `cee78206`, Arbeitsbaum zu Beginn clean · **Datum:** 25.11.2026
**Exklusiver Dateibereich:** `core_dispatcher.py`, `archon/core/orchestration.py`, `archon/core/delegation.py`, `backend/consensus_gate.py`, `backend/role_budget_engine.py`, `archon/routers/boardroom.py`, `archon/routers/execution.py`, `backend/handoff_desk.py`, `backend/trajectory_budget.py`.
**Nicht angefasst:** `archon/routers/chat.py` (A5), `main.py` (A9), `backend/llm_egress_guard.py` (A2), `backend/workflow_dag_runner.py` (A5), `backend/approval_policy_engine.py` / `archon/routers/decisions.py` (A6). Keine PG-Migration, kein Coroutine-/Event-Replay (G-01/G-02). G-05: prozess-lokale Breaker unverändert.

---

## Umgesetzte Fixes (13)

**Fix-Index:** 1 Cache-Scope-Erweiterung · 2 Cache-Hit-Gate-Revalidierung + `blocked`-Return · 3 `cancelled` terminal im Result · 4 `cancel_reason`/`cancel_scope` in History/Audit · 5 strukturierter Guardrail-Veto-Produzent · 6 `tier` in Boardroom-Events/Authority · 7 Critique vor Konsens · 8 `critique_error` fail-closed · 9 Autorität gewichtet alle Stimmen + hartes Veto · 10 B7-Vollständigkeit (alle `NO_CONSENSUS*`, Policy-Veto, HITL-Belege) · 11 Fan-in-Markerproduzent + `tier` · 12 leere Synthese im Stream-Pfad · 13 Trajectory-Finalize-Key.

### D02/HIGH-1 (Fix 1+2) — Governance-Gate vor Cache-Lookup / Scope-Erweiterung
`core_dispatcher.py:196` `_dispatch_cache_scope()` um `data_category`, `canary`, `zero_egress_active` erweitert (zusätzlich zu Tenant/Agent/`policy_version`/Env-Zero-Egress). Neue Helper `_cache_policy_context()` (`:233`, berechnet wirksame Kategorie + Zero-Egress ohne Audit-Write; Fehler → `confidential`/`zero_active`, also Cache-Miss) und `_validate_cache_hit_gate()` (`:259`).
Im Dispatcher (`:946-992`) wird der Scope mit diesen Werten gebaut; **bei jedem Cache-Hit** werden `compliance_engine.check_activation_allowed()`, `DataClassifier` und `evaluate_and_gate_llm_dispatch()` erneut ausgewertet. Bei `blocked`/Gate-Fehler → sofort `status="blocked"` mit `error_code`/`audit_event`, **kein Cache-Return, kein Cloud-Fallback**. Der alte Stage-13-Check nur auf `zero_egress_strict` ist entfernt.
*Hinweis:* Der Gate-Check bewusst NUR am Hit (nicht schon vor dem Lookup), damit der bereits vorhandene Non-Cache-Exec-Pfad und seine Tests (z. B. `test_reaudit_d16_dispatcher.py`) nicht durch eine zweite Compliance-Prüfung für unbekannte Agenten verändert werden. Die alternativ geforderte Kombination (Scope-Erweiterung + Revalidierung pro Hit) ist damit vollständig erfüllt.

### D02/HIGH-2 — `cancelled` nicht durch `incomplete` überschreiben
`core_dispatcher.py` `run_boardroom_debate()`: Cancel-Event setzt zusätzlich `cancel_scope` (`:~3140`); nach der Event-Schleife wird vor dem `done_seen`/Synthese-Check auf `status=="cancelled"` geprüft und das Result unverändert zurückgegeben.

### D02/HIGH-3 — `cancel_reason` / `cancel_scope` in History und Audit
`archon/routers/boardroom.py`: Non-Stream-`hist_entry` trägt jetzt `cancel_reason` und `cancel_scope`; `decision_status="cancelled"` bleibt als eigener Terminalstatus erhalten (nicht `no_consensus`/`incomplete`). `save_boardroom_history_item()` spiegelt `decision_status`, `consensus_verdict`, `cancel_reason`, `cancel_scope` zusätzlich in den signierten `decision_saved`-Audit-Eintrag.

### D14/HIGH-1 — Policy-Veto-Produzent in den Dispatch-Wrappern
`core_dispatcher.py`: Neuer Helper `_boardroom_guardrail_result()` (`:2415`) liest ein strukturiertes Guardrail-Result aus `guardrail_result` bzw. den Feldern `policy_violation` / `guardrail_violation` / `severity` / `source_trace_id` des Dispatch-Ergebnisses; ein `status="blocked"` wird hart als Veto gewertet. Die Felder gehen in **beide** `agent_response`-Events (`:2735`, `:2824`) und das `critique`-Event (`:2901`) ein. `DebateStatement.source_trace_id` in `backend/consensus_gate.py:85` deklariert. Die Debatten-Prompts fordern zusätzlich eine eigene `POLICY_VIOLATION`-Zeile (strukturierter Kanal bleibt primär, Marker nur Fallback). Keine neuen Freitext-Marker als Veto-Quelle eingeführt.

### D14/HIGH-2 — Critique vor finale Konsensauswertung
`core_dispatcher.py:2863-2936`: Der Critique-Dispatch läuft jetzt nach der letzten Debattenrunde und **vor** der finalen Konsensauswertung. Das strukturierte Critique-Event wird in `debate_statements` aufgenommen, danach wird `resolve_debate_consensus()` erneut mit Tier-Authority aufgerufen; `final_verdict` / `has_final_decision` stammen ausschließlich aus diesem zweiten Verdict. Bei `critique_error`: fail-closed auf `NO_CONSENSUS`, `veto_by="boardroom-critic"`, explizites `no_consensus`-Event, `critique_error` im `done`-Event und im `run_boardroom_debate()`-Result → HITL-Eskalation downstream.

### D14/HIGH-3 — Autoritätsgewichtung für alle Stimmen + hartes Veto
`backend/consensus_gate.py:254-328`: Gewichtete 2/3-Mehrheit ist jetzt primäres Kriterium (nicht nur Nachrangregel bei gescheiterter Rohe-Mehrheit); `applied_tie_break="authority_weight_majority"`. Zusätzlich hartes Veto des höchsten anwesenden Tiers bei Gegenmehrheit → `consensus_reached=False`, `verdict="NO_CONSENSUS_BY_AUTHORITY"`, `veto_by=<Agent der Gegenmehrheit>`. Exakter gewichteter Gleichstand wird weiterhin vom höchsten Tier entschieden (nur bei interner Einstimmigkeit); geteiltes höchstes Tier bleibt ohne Flip (HITL). `unanimous` bleibt hart. Bestehender Test `test_authority_tie_break_executive_wins` (exec-JA vs. spec-NEIN → `CONSENSUS_REACHED_BY_AUTHORITY`) bleibt logisch unverändert; neu abgedeckt ist `[spec,spec JA | exec NEIN]` → `NO_CONSENSUS_BY_AUTHORITY`.

### D14/BLOCKER B7 — Vollständigkeit des NO_CONSENSUS-Gates
`archon/core/orchestration.py`: Der Fan-in-Verdict wird einmal zentral abgeleitet (`:1396`). `startswith("CONSENSUS_REACHED")` sperrt die Finalisierung für **alle** `NO_CONSENSUS*`-Verdikte, inkl. `NO_CONSENSUS_BY_AUTHORITY` und `NO_CONSENSUS_POLICY_VIOLATION`. Bei Policy-Veto wird der Robert-Freigabe-Prompt vollständig übersprungen (harte Ablehnung, keine Finalisierung). Die HITL-Entscheidung erhält `original_verdict`, `veto_by`, `policy_violation` und `evidence` im `extra`-Dict. B7-Logik selbst wurde nicht rückgängig gemacht; der bestehende String-Gate-Test (`startswith("CONSENSUS_REACHED")`) bleibt erfüllt.

### D02/D14/MED — Fan-in-Markerproduzent + `tier` in Fan-in-Statements
`archon/core/orchestration.py:1340-1374`: Kind-Ergebnisse mit strukturiertem `consensus_verdict`/`verdict` oder `policy_violation`/`guardrail_violation` werden in echte `KONSENS_ERREICHT` / `KEIN KONSENS` / `POLICY_VIOLATION`-Marker übersetzt und mit `tier` (aus `_infer_tier` der verifizierten Rollen-SSOT) sowie `severity` in die `DebateStatement` übernommen. Damit hat der gezählte Marker einen Produzenten im Produktivpfad.

### D02/D14/MED — `tier` in Boardroom-Events und Authority-Map
`core_dispatcher.py`: `_boardroom_tier()` (`:2408`) nutzt das Slot-Feld `tier` aus `_prepare_boardroom_agents()` (SSOT) mit `_infer_tier()`-Fallback. Beide Event-Dicts tragen jetzt `tier`; der `authority`-Dict wird daraus gebaut, statt leer zu bleiben.

### D14/MED — Leere Synthese auch im Stream-Pfad
`archon/routers/boardroom.py:708-720`: `_stream_final` verlangt jetzt zusätzlich `is_final_decision`, nicht-leeren `synthesis_text`, nicht abgebrochenes Cancel-Token und kein `cancelled`-Flag. Vault-Überschrift und `decision_status="approved"` werden nur bei diesem konsistenten Bündel gesetzt; bei Verdict `CONSENSUS_REACHED`, aber leerem Text → `decision_status="incomplete"`, Konfliktanalyse statt „Finale Synthese", HITL-Eskalation. Cancel-Grund/-Scope auch im Stream-`hist_entry`.

### D02/MED — Trajectory-Finalize-Key
`archon/core/delegation.py:347` neuer Helper `_trajectory_for_task()` als Inverse von `_CHAIN_TASK_BY_TRAJECTORY`; der Run-Abschluss (`:~1280`) liest statt des falschen `_SESSION_TRAJECTORY.get(str(task_id))` jetzt den echten, verknüpften Trajectory-Key. Damit wird die ursprüngliche Trajectory geschlossen (Zyklusschutz/Hop-Zähler), keine frische `trajectory_id` mehr abgeleitet.

### Verifiziert, keine Änderung nötig
- `backend/role_budget_engine.py`: `aggregation_lisa` ist am aktuellen HEAD sehr wohl in `agent_profiles.json` (Zeile 442) und in `EXECUTIVE_ROLE_IDS` registriert — der D02-MED-Befund zur fehlenden SSOT ist auf diesem HEAD nicht mehr reproduzierbar. Kein Edit.
- `archon/routers/execution.py`, `backend/handoff_desk.py`, `backend/trajectory_budget.py`: die in D02 als „verdrahtet" bestätigten Pfade (`request_dag_replan`, `inherit_replan_count`, Effect-Ledger) sind unverändert vorhanden; kein offener D02/D14-Fund in diesem Zuständigkeitsbereich.
- B7-Basisgate, G-01/G-02 und prozess-lokale Breaker (G-05) wurden nicht verändert.

---

## Delegiert (7) — außerhalb meines Dateibereichs

| Fund | Datei / Owner | Grund |
|---|---|---|
| Schwellen-Invariante `finance_auto_approval_max < finance_four_eyes_min` symmetrisch in `update_policy()` + `approve_policy_change_proposal()`, Auto-Freigabe an `not requires_four_eyes` koppeln | `backend/approval_policy_engine.py` → **A6** | Explizit als DELEGATED markiert |
| `decisions.py`-Eskalationsbelege (`extra`-Key / Top-Level-Keys im Followup) | `archon/routers/decisions.py` → **A6** | Explizit als DELEGATED markiert |
| 0-Token-Pfad auch in `chat_completion()` | `backend/agent_router.py` / `archon/routers/chat.py` → **A5** | Explizit als DELEGATED markiert |
| DAG-Edge-Map Keys (Ziel- vs. Quell-Key in `validate_dag_def()`) | `backend/workflow_dag_runner.py` → **A5** | A5 besitzt die Datei |
| `boardroom`-Knoten-Handler oder `valid_types`-Bereinigung | `backend/workflow_dag_runner.py`, `backend/workflow_templates.py` → **A5** | A5 besitzt die Dateien |
| Stale Profil-Cache `data/agent_profiles.json` (Reihenfolge/Regeneration) | `data/agent_profiles.json`, `archon/routers/context_help.py` → nicht in A4-Bereich | Keine andere Datei editiert |
| `sandy` → `labor_law_hr_governance` in der Sonderfall-Ziel-ID | `archon/routers/mission_control.py` → nicht in A4-Bereich | Keine andere Datei editiert |

---

## Verifikationsstatus

- **Statische Prüfung:** Alle Edited-Regionen erneut gelesen; Syntax/Indentation, Pydantic-Felddeklarationen (`extra="forbid"`) und die kompatiblen Gate-/Verdict-Strings geprüft. Bestehende Source-String-Tests (`test_audit_b1_b8_blockers.py::test_b7_synthesis_cascade_guards_against_no_consensus`, `test_p2_deterministic_fan_in.py`) bleiben erfüllt; `startswith("CONSENSUS_REACHED")` ist unverändert im Source vorhanden.
- **Laufende Verifikation (pytest / ruff / mypy) NICHT ausführbar:** Die Shell war während der gesamten Editing-Phase nicht startbar (`failed to spawn …pwsh.exe: Zugriff verweigert`, auch für `echo`/`git status`). Die geforderten gezielten Consensus-/Boardroom-Tests, `ruff` und `mypy` konnten daher **nicht** ausgeführt werden — bitte im Integrationslauf nachholen. Es wurde bewusst kein „grün" behauptet.
- **Nicht committet / nicht gepusht.**

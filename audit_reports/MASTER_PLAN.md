# Archon OS — MASTER PLAN (Phase 2: Konsolidierung & Architektur-Bewertung)

> **Eingang:** `00_SOLL_SPEC.md` + `domain_01.md` … `domain_16.md` (16 parallele Tiefenaudits, frischer Lauf gegen HEAD `83691375` / v0.5.7.7).
> **Skala (verbindlich):** 1 = schlecht/kaputt/disfunktional · 10 = top/funktional im Sinne des Erfinders.
> **Ziel (Phase 3):** Alle 12 BLOCKER, 79 HIGH und 93 MED finden, fixen und verifizieren;.every Fix mit Test/Nachweis; Abschluss in `FINAL_VERIFICATION.md`.

---

## 1. Konsolidierte Befundmatrix

| Domäne | B | H | M | Gesamt | Score | Schwerpunkt |
|---|---:|---:|---:|---:|---:|---|
| 01 Verdrahteter Schein | 0 | 1 | 7 | 8 | 6 | Simulierte Eval-Outputs erzeugen persistierte `release_approved`; Marketplace/Map-Reduce Fake-Daten |
| 02 Orchestrierung & Routing | 1 | 4 | 5 | 10 | 5 | NO_CONSENSUS → Final Decision; Konsens-Check nur vor letzter Runde; kein Critique-Dispatch |
| 03 Persistenz & Vault | 0 | 3 | 3 | 6 | 6 | **Reale FK-Korruption in aktiven Mandanten-DBs (bis 142 Verletzungen)**; Nummernkreis-Bypasses; `busy_timeout`-Drift |
| 04 Governance & Security | 0 | 5 | 10 | 15 | 6 | Dual-LLM-Quarantine läuft nie; Passkey für `system`/`destructive_actions` fail-open; AST-Sperre durch Harness umgangen; Taint-Liste ungeschützt |
| 05 Audit & Krypto | 0 | 3 | 3 | 6 | 6 | HMAC-Abschalter im Schreibpfad; 6 Nebenketten ohne Head-Anker/Trigger-Prüfung; geblockte Dispatches ohne Proof |
| 06 Integrationen | 0 | 0 | 5 | 5 | 7 | Rohe Dict-Bodies; n8n-Treiber ohne HMAC; Gateway-Key fließt nach außen |
| 07 Error & Recovery | 0 | 3 | 10 | 13 | 6 | Erfolgssignale in Fehlerpfaden; stille Exception-Swallower; HITL-Sackgassen |
| 08 Performance | 0 | 1 | 6 | 7 | 7 | Sync SQLite im Event-Loop auf heißem Pfad; FD-Leaks durch fehlende Client-Shutdown-Kette |
| 09 Standards | 0 | 4 | 9 | 13 | 6 | Drei Images ohne Digest; `continue-on-error` für Ruff/Mypy/ESLint; ungehashster Coverage-Install |
| 10 24/7-Härtung | 0 | 3 | 4 | 7 | 6 | Ansible startet Observability nicht; externer Autoheal nicht in Startpfaden; Watchdog-Thread unsupervisiert; Dead-Man-Alarm invertiert |
| 11 Context Drift | 0 | 7 | 10 | 17 | 4 | Kein einziges schema-validiertes Handoff im Produktivpfad; berechnete Werte nie im Result; `work_package_N` statt Agent-IDs; unmarkierte Kürzungskette |
| 12 Silent Failures | 4 | 17 | 6 | 27 | 3 | Chat-SSE erfindet Antwort; Flightlog-Detektor ohne Produzent; simulierte Evals → Release; War-Room meldet `blocked` ohne Wirkung |
| 13 Trajectory | 2 | 8 | 9 | 19 | 3 | Zyklus-Schutz liest/schreibt unterschiedliche Dict-Keys (tot); `replan_count`-Setzer Totcode; kein ticketweites `max_hops`; Budget-Minting pro Hop |
| 14 Entscheidungshoheit | 1 | 5 | 1 | 7 | 3 | NO_CONSENSUS → Final Decision; Chairman-Tier prüfbar umgangen; 500-€-Schwelle durch Admin änderbar; Policy-Verstoß per Mehrheit überstimmt |
| 15 Rollen & Prompts | 2 | 9 | 2 | 13 | 3 | **Zwei CI-Drift-Gates rot (Exit 1)**; 72/73 Negativ-Abgrenzungen Boilerplate; 21 statt 26 HIGH_RISK; erfundene SOUL-Hashes live |
| 16 Distributed Tracing | 2 | 6 | 3 | 11 | 3 | `tracestate` fehlt komplett; 12/16 Grenzen ohne Propagation; Collector exportiert nur `debug`; Outbox/DLQ verlieren Trace |
| **Summe** | **12** | **79** | **93** | **184** | **5,0** | |

**Deduplikation (sachlich identische Root Causes):**
- `NO_CONSENSUS`-Kette: D02/BLOCKER ≡ D14/BLOCKER (`core_dispatcher.py:2273`, `boardroom.py:426`) — **ein** Fix-Block.
- Flightlog-Produzent: D12/BLOCKER ≡ D13/BLOCKER (`flightlog_backtester.py:57`) — **ein** Fix-Block.
- Erfinderischer SOUL-Hash: D15/HIGH ≡ D04/MED (`eu_ai_act_inventory.py:111-113`) — **ein** Fix-Block.
- Ersteller-Abgleich: D14/HIGH ≡ D04/HIGH (`decisions.py:708`) — **ein** Fix-Block.
- Simulierte Eval-Outputs: D01/HIGH ≡ D12/BLOCKER (`eval_regression_runner.py:116`) — **ein** Fix-Block.
- Tool-Output-Firewall Fail-Open: D12/HIGH ≡ D04/MED (`tool_runtime.py:143`, `tool_output_firewall.py:34`) — **ein** Fix-Block.
- CI-Qualitätstor / Drift-Gates: D09/HIGH ≡ D15/BLOCKER (`.github/workflows/ci.yml`) — **ein** Fix-Block.

**Effektiv unique Root-Causes: ~166.**

---

## 2. Reifegrad-Bewertung (Skala 1–10)

| Kriterium | Score | Begründung (mit Domänenbezug) |
|---|---:|---|
| **1. Funktionale Vollständigkeit (Echtbetrieb vs. Schein)** | **5** | Der Großteil der Kernmechaniken ist real verdrahtet (HMAC-Kern, Proxy-Self-Healing, Passkey-Prüfung, BudgetBank, Outbox-Drainer, Digest-Pinning) – daher nicht unter 5. Aber: simulierte Eval-Outputs erzeugen echte `release_approved` (D01/D12), HTTP-200-ohne-Nutzlast wird zur erfundenen Antwort (D12, 4 BLOCKER), `NO_CONSENSUS` erzeugt Final Decision (D02/D14), War-Room meldetBlockade ohne HITL-Wirkung. Das 100%-Kriterium G-03 ist an zentralen Stellen verletzt. |
| **2. Multi-Agenten-Stabilität (Context/Loops/Roles)** | **3** | D11 4, D12 3, D13 3, D14 3, D15 3, D02 5. Kein schema-validierter Handoff im Produktivpfad, Berechnungswerte verschwinden zwischen den Stationen, `work_package_N` anonymisiert Agenten, Zyklusschutz tot (falscher Dict-Key), `replan_count` ohne Setzer, kein `max_hops` pro Ticket, 72/73 Rollen-Abgrenzungen Boilerplate,两条 CI-Gates rot. Die autonome Kette ist an ihren Übergängen nicht belastbar. |
| **3. Sicherheits-Härtung (Zero-Trust/Governance)** | **5** | Starke Basis (Auth fail-closed, zentraler RBAC, HMAC-Warrants, Taint-Default-Deny, Egress in allen Dispatch-Pfaden, keine Secrets im Git → D04 positives Urteil). Aber fünf strukturelle HIGH-Lücken: Dual-LLM-Quarantine nie aktiviert, Passkey für Hochrisiko ohne Credentials fail-open, AST-Sperre durch eigenen Harness (`import os`) umgangen, Taint-Approval-Liste ohne RBAC, Docker-CLI umgeht Proxy-Allowlist. D05: HMAC-Abschalter im Schreibpfad. |
| **4. Fehlertoleranz & Silent-Failure-Schutz** | **4** | D12 mit 4 BLOCKER/17 HIGH ist das schlechteste Glied: Silent-Failure-Detector hat keinen Produzenten, Chat-Stream erfindet Text, Container-Ops schluckt `ZeroEgressBlockedError`, Default-Kosten `0.0`. D07 (6/10) hat 3 HIGH und 10 MED mit Erfolgssignalen in Fehlerpfaden. Positive Teilmechaniken (Non-Stream-Prüfung, `structured_output_enforcer`) verhindern die 3. |
| **5. Daten- & Trace-Integrität** | **5** | D03: echte FK-Korruption in aktiven Mandanten-DBs (bis 142 Verletzungen), zwei GoBD-/Nummernkreis-Bypasses. D05: Zentralkette vorbildlich, aber 6 Nebenketten ohne Head-Anker. D16: `tracestate` fehlt, 12/16 Grenzen ohne Propagation, Collector verwirft alle Spans in `debug`, Outbox/DLQ ohne Trace-Spalten. Daten und Trace sind nicht durchgängig nachvollziehbar. |
| **6. Code- & Architekturqualität** | **6** | D06 7, D08 7, D09 6, D10 6. Digest-Pinning, Hash-Lockfile, Action-SHA, `WeakKeyDictionary`, Token-Guard-Fix sind real. Aber: zwei CI-Gates rot (D15), Qualitätstor für 3 von 4 Lintern `continue-on-error` (D09), drei Images ungepinnt, Langfuse v2 EOL, 130 `any` in `frontend/src`, keine Modal-A11y. |
| **Gesamt** | **5 / 10** | Ein architektonisch durchdachtes System mit starker Sicherheits- und Krypto-Basis, dessen **Kernversprechen – autonome, auditierbare, gehärtete 24/7-Orchestrierung – an den Übergängen nicht eingehalten wird**. Die 12 BLOCKER und 79 HIGH sitzen genau dort: Hoheitsketten, Trajectory-Limits, Silent-Failure-Eskalation, Handoff-Schemas, Trace-Propagation und Rollen-SSOT. Nach Abarbeitung aller Funde mit Verifikation ist 9/10 realistisch; 10/10 bleibt wegen bewusst akzeptierter Risiken (G-05) unerreichbar. |

> **Hinweis zum Erwartungsgap (9,5):** Der frühere Wert 9/10 stammte aus einem 10-Domänen-Audit auf altem HEAD und einem Verifikationsstandard, den das eigene Register als „nur keine Regression, nicht fertig" beschreibt. Die sechs jetzt zusätzlich geprüften Domänen (D11–D16) sind genau die mit 3–4/10. Die neue Bewertung ist evidenzbasiert gegen aktuellen HEAD und nicht geschönt.

---

## 3. Abhängigkeits-Matrix (konfliktfreie Ausführungsreihenfolge)

**Sortierprinzip:** Fundament/Daten/Krypto → Hoheit/Silent-Failures → Orchestrierung/Handoff → Tracing/Resilienz → Integrationen/Standards → Verifikation.
**Regel:** Dateien, die von mehreren Funden betroffen sind, werden in **einem einzigen Edit-Block** bearbeitet (kein paralleles Schreiben auf dieselbe Datei).

### Welle 0 — Fundament: Daten, Krypto, Rollen-SSOT, CI-Gates
| IDs | Edit-Blöcke (Dateien) | Maßnahme | Gate |
|---|---|---|---|
| D03 (alle) | `backend/db_paths.py`, `tenant_context.py`, `erp_manager.py`, `db_backup_manager.py`, aktive `data/tenants/*.db` | FK-Korruption bereinigen + FK-Check vor Schreiben; Nummernkreis-Einzelauthorität; `busy_timeout=5000` als SSOT | `PRAGMA foreign_key_check` = 0 in allen Mandanten-DBs; Restore-Test |
| D05 (alle) | `backend/audit_log.py`, `backend/autonomy_settings.py`, 6 Nebenketten, `llm_egress_guard.py` | HMAC-Abschalter entfernen; Head-Anker + Trigger-Prüfung in allen Ketten; Proofs für geblockte Dispatches; Audit-Fehler `error` | Ketten-Verify `valid=True`, Manipulation `valid=False`, Rotationstest |
| D15/BLOCKER + D09/CI | `.github/workflows/ci.yml`, `scripts/build_souls_ssot.py`, `check_soul_ssot_drift.py`, `souls/`, `roles.json`, `agent_profiles.json`, `eu_ai_act_inventory.py` | SOUL-SSOT neu bauen (490 vs. 511 klären); beide CI-Gates grün; `continue-on-error` entfernen; erfundene SOUL-Hashes → `None`; HIGH_RISK 21→26 mit Wortgrenzen | `build_souls_ssot.py --check` Exit 0; `check_soul_ssot_drift.py` Exit 0; `high_risk_count == 26` |
| D03/MED + D09/Images | `docker-compose*.yml`, `Dockerfile*`, `requirements*.txt`, `.github/workflows/*` | Drei Images digest-pinnen; Langfuse v4; Coverage-Job auf Hash-Lock; `ARCHON_TEST_DB_ISOLATION=1` in allen Jobs | `docker compose config --quiet`, YAML-Parse, `--require-hashes` |

### Welle 1 — BLOCKER: Hoheit, Silent Failures, Trajectory
| IDs | Edit-Blöcke | Maßnahme | Gate |
|---|---|---|---|
| D02/BLOCKER + D14/BLOCKER | `core_dispatcher.py`, `archon/routers/boardroom.py`, `backend/consensus_gate.py` | Konsens auch in letzter Runde; `consensus_status` im Result; NO_CONSENSUS → `no_consensus` + HITL, keine Final Decision/kein `decision`-Event | Test: NO_CONSENSUS-Marker → kein Final-Decision-Event, Status ≠ success |
| D12/BLOCKER + D13/BLOCKER | `archon/routers/chat.py`, `backend/flightlog_backtester.py`, `backend/eval_regression_runner.py`, `backend/war_room_simulator.py`, `archon/routers/autonomy_settings.py`, `backend/tool_runtime.py` | Leere SSE → `error`, kein Fake-Text/Usage; Flightlog-Produzent im Tool-Chokepoint + `resolve_db()`; Eval-Simulation → `release_approved=False` + Marker; War-Room → `blocked_effective=False` bei fehlgeschlagener HITL | Jeder BLOCKER mit Contract-Test gegen Produktivpfad |
| D04/HIGH + D14/HIGH | `archon/routers/decisions.py`, `backend/approval_policy_engine.py`, `backend/session_taint_guard.py`, `archon/routers/kanban.py`, `archon/routers/operations_approvals.py` | Ersteller aus Session + fail-closed bei leerem `created_by`; `requester_id` in `approval_requests`; 500-€-Schwelle nur über 4-Augen; Taint-Liste RBAC | Test: identischer Ersteller/Genehmiger → Ablehnung; Admin allein kann Schwelle nicht ändern |
| D04/HIGH (Sandbox, Quarantine, Passkey) | `backend/self_evolving_tooling.py`, `local_security_guard.py`, `backend/dual_llm_sanitizer.py`, `backend/passkey_hitl.py`, `utils/docker_client.py` | Harness ohne `import os/sys`, AST gegen gesamten Script; `quarantine_external_text()` mit echtem 2. LLM; Passkey fail-closed für Hochrisiko; Docker-CLI über Proxy oder `not_configured` | Sandbox-Bypass-Testblockiert; PoC `os.system` → deny; Passkey-Test ohne Credentials → 403 |

### Welle 2 — Orchestrierung, Handoff, Trajectory, Recovery
| IDs | Edit-Blöcke | Maßnahme |
|---|---|---|
| D13 (Rest) | `archon/core/delegation.py`, `workflow_dag_runner.py`, `role_budget_engine.py`, `agent_router.py`, `mission_control.py`, `operations_api.py`, neue Tabelle `trajectory_budgets` | Ein `trajectory_id`/Key für Lesen+Schreiben der Kette; `max_hops`/`hops_used` pro Ticket; `request_dag_replan()` verdrahten; Budget-Minting → `blocked`; Fan-out-Cap; Reservierungs-TTL |
| D11 (alle) | `archon/core/delegation.py`, `operations_api.py`, `backend/handoff_desk.py`, `backend/consensus_gate.py`, `core_dispatcher.py`, `backend/prompt_registry.py` | `DelegationPayload`/`HandoffEnvelope`/`DebateStatement` (Pydantic v2, `extra="forbid"`); `effective_prompt_info` in **jedem** Dispatch-Return; Key-Mismatch `version_num` → `version`; `mark_truncated()` an 5 Stellen; echte Agent-IDs im Fan-in + Trace-Korrelation |
| D02 (Rest) + D07 | `core_dispatcher.py`, `backend/agent_router.py`, `backend/operations_api.py`, `archon/core/orchestration.py`, `watchdog_daemon.py`, `main.py` | Deterministisches Routing ausführen; Circuit-Breaker Half-Open; Cancel-Kette; Fehlerpfade → `blocked`/DLQ statt `success`; `except: pass` → Logging/Eskalation |

### Welle 3 — Tracing & 24/7-Resilienz
| IDs | Edit-Blöcke | Maßnahme |
|---|---|---|
| D16 (alle) | `backend/trace_context.py`, `backend/otel_tracer.py`, `backend/event_mesh.py`, `backend/dead_letter_queue.py`, `main.py`, `frontend/src/app/api/archon/[...path]/route.ts`, `archon/core/runtime.py`, `archon/routers/mcp_gateway.py`, `telegram_notify.py`, `config/otel-collector-config.yml`, `docker-compose.yml` | `tracestate` ContextVar + Inject/Extract; `child_span()` in allen Outbound-Hooks; eine ID-Quelle; Outbox/DLQ-Spalten + Re-Injektion; Collector `exporters: [debug, otlphttp/downstream]`; Sampling; Middleware-Reihenfolge; 4xx-Handler mit `X-Trace-Id` |
| D10 (alle) + D08/HIGH | `ansible/roles/archon_node/**`, `start.bat`, `install.sh`, `docker-compose.yml`, `watchdog_daemon.py`, `scripts/archon_autoheal.py`, `backend/resource_backpressure.py`, `backend/fleet_self_healing.py`, `archon/routers/proxies.py` | Ansible-Profile + Autoheal in Startpfade; Watchdog-`last_seen` in `/livez` + Supervisor; Dead-Man-Metrik statt expiring Alert; Disk-Fail-Closed; RTO-Dokumentation; HTTP-Client-`aclose()`-Kette |

### Welle 4 — Integrationen, Frontend, Rest-MED
D01 (Rest), D03 (Rest), D04 (Rest), D05 (Rest), D06 (alle), D07 (Rest), D08 (Rest), D09 (Rest), D10 (Rest), D11 (Rest), D12 (Rest), D13 (Rest), D14 (Rest), D15 (Rest), D16 (Rest).
Alle verbleibenden MED-Funde, nach Datei gruppiert, in einem Edit-Block pro Datei. Kein Fix darf ein neues, ungetestetes Risiko erzeugen – sonst `DEFERRED` mit dokumentiertem Grund (Register-Regel 4).

### Welle 5 — Finale Verifikation
`pytest tests/ -q` (mit `ARCHON_TEST_DB_ISOLATION=1`), `compileall`, `npx tsc --noEmit`, `node --check`, `docker compose config`, alle Dry-Runs, Re-Scoring der 6 Kriterien, `FINAL_VERIFICATION.md`.

---

## 4. Versionierung

Branch `audit/hardening-2026-11-24`. Ein Commit pro Welle mit Testnachweis im Commit-Body. Kein Commit auf `main`. Alte Berichte bleiben unter `audit_reports/_archiv_2026-11-24_run5/` erhalten.

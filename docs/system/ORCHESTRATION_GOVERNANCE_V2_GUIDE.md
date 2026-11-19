# Archon OS — Orchestrierung, Governance & Memory v2 (M75–M91)

Technische Referenz der zehn neu umgesetzten Architektur-Meilensteine in Archon OS.

---

## 1. Delegation & Multi-Agent-Orchestrierung

### M75 — Strikte Rollen- & Tool-Isolation (`backend/delegation_isolation.py`)
- **Zweck:** Verhindert, dass delegierte Subagenten implizit privilegierte Werkzeuge (`terminal`, `filesystem`, `mcp`) des aufrufenden Parent-Agenten erben.
- **Kernfunktionen:**
  - `resolve_isolated_execution_scope(target_agent_id, requested_model, profiles)` liest ausschließlich `tools`, `skills` und `model` aus `agent_profiles.json` (fail-closed Fallback: `["web_search"]`).
  - `is_tool_allowed_for_agent(agent_id, tool_name, scope)` prüft Tool-Freigaben inkl. `mcp__*`-Präfixen.
  - `build_isolated_system_prompt_header(scope)` injiziert den Scope-Header in die Sub-Session.
- **Integration:** `archon/core/delegation.py` (`_execute_delegation`).

### M77 — Agenten-Workflow-DAGs (`backend/workflow_dag_runner.py`)
- **Zweck:** Asynchroner Runner für JSON-Workflow-DAGs mit parallelem Fan-Out, Quorum, Human-/Machine-Gates und Fingerprint-Resume.
- **Knotentypen:** `agent`, `fanout` (`branches`, `quorum_min`), `gate` (`gate_approvals`).
- **Persistenz:** `data/workflow_dags.db` (SQLite WAL, Tabellen `workflow_runs`, `workflow_node_states`). Abgeschlossene Knoten mit identischem SHA-256-Fingerprint werden beim Resume als `skipped_cached` übersprungen.

### M86 — Quota- & Verification-Escalation (`backend/agent_router.py`)
- **Kernfunktionen:**
  - `select_quota_and_escalation_route(...)`: Wechselt bei unterschrittener Rest-Quota (`remaining_quota_pct < quota_threshold_pct`) auf `cheap_model`; eskaliert bei fehlgeschlagener Verifikation auf `frontier_model`.
  - `chat_with_verification_escalation(...)`: Führt zuerst das ausgewählte Modell aus, prüft via `verifier_fn` und eskaliert nur bei Fehlschlag.

---

## 2. Kanban-Qualität, Präzedenzfälle & Visualisierung

### M76 & M81 — Verifizierte Kanban-Cards & Cross-Model-Verifier (`backend/kanban_verifier.py`)
- **Zweck:** Jede Kanban-Ausführung prüft Token-Budget, Ergebnis-Integrität und optionales `proof_command` (Exit Code `0`).
- **HITL-Verhalten:** Bei `retry_count < 1` erfolgt ein automatischer Retry; bei Budget-Überschreitung oder erneutem Proof-Fehler wird die Card auf `blocked` gesetzt (`budget_exceeded_hitl` / `proof_failed_hitl`) und über `POST /api/operations/kanban/tasks/{task_id}/hitl` (`override_budget` | `retry` | `abort`) durch den Menschen aufgelöst.
- **M81 (`cross_model_verify_card`):** Wählt über `pick_independent_verifier_model()` bewusst eine andere Modell-Familie und blockiert über `detect_deleted_test_assertions()`, falls Test-Assertions aus dem Diff entfernt wurden.
- **Integration:** `backend/operations_api.py` (`_execute_kanban_task_async`), `archon/routers/kanban.py`.

### M91 — Präzedenzfall-Gedächtnis (`backend/precedent_log.py`)
- **Zweck:** Speichert menschliche Antworten auf blockierte Kanban-Fragen als dauerhafte Rulings – strikt isoliert pro `(tenant_id, project_id)` ohne Übertrag zwischen Mandanten.
- **Persistenz:** `data/precedents.db` (SQLite WAL).
- **API:** `GET /api/operations/precedents`, `POST /api/operations/precedents`, `DELETE /api/operations/precedents/{precedent_id}`.
- **Prompt-Injection:** `operations_api.py` lädt vor dem Dispatch passende Rulings und hängt sie als `[PRECEDENT RULINGS]` an den Task-Prompt an.

### M78 — Gantt-Timeline & Dependency-Graph (`backend/kanban_views.py`, `static/js/kanban_gantt_graph.js`)
- **Hybrid-Gantt:** Nutzt explizite `started_at`/`completed_at`/`due_date`-Felder und füllt fehlende Endzeiten automatisch aus `created_at` + Default-Dauer bzw. Live-Laufzeit.
- **Dependency-Graph:** Berechnet aus `tasks` + `task_links` Longest-Path-Layer (`layer`) und Abhängigkeitskanten.
- **API:** `GET /api/operations/kanban/gantt`, `GET /api/operations/kanban/graph`.

---

## 3. Security, Observability & Offline-Memory

### M89 — Information-Flow-Taint-Tracking (`backend/session_taint_guard.py`)
- **Zweck:** Sobald eine Session untrusted Content liest (`mark_session_tainted`), werden kritische Ausgänge (`send_email`, `pay`, `pay-cli`, `git_push`, `deploy`, `memory_write`, `execute_shell`, `webhook_post`, `telegram_send`) über das HITL-Gate geparkt.
- **Persistenz:** `data/taint_guard.db` (SQLite WAL). Einmalige Freigabe-Tokens (`ta-...`) werden nach Nutzung verbraucht (`consumed = 1`).
- **API:** `GET /api/v1/guardian/taint/approvals`, `POST /api/v1/guardian/taint/approvals/{approval_id}`.

### M83 — Flugschreiber & Guardrail-Backtester (`backend/flightlog_backtester.py`)
- **Zweck:** `detect_silent_failures` erkennt „grün fehlgeschlagene“ Runs (versteckte Tool-Errors, Loops >= 3, Token-Spikes, Effort-Collapse). `backtest_policy` spielt neue Regeln gegen historische Events in `data/flightlog.db` ab.

### M79 — Lokaler verschlüsselter Offline-Memory-Vault (`backend/offline_memory_vault.py`)
- **Zweck:** 100 % offline arbeitender AEAD-verschlüsselter Speicher (`data/compartment_vault.db`, Schlüssel in `data/compartment.key` oder `COMPARTMENT_VAULT_KEY`) mit lokalem 64-dim-Hybrid-Embedding ohne Netzwerkzugriff oder API-Keys.

---

## 4. Erweiterte Security-, Workflow- & Research-Module (Block A & B: M84, M90, M80, M82, M93, M92, M94, M50, M45, M65)

- **M84 — Prompt-Injection-Feuerübung (`backend/injection_range.py`):** 8 standardisierte Angriffsszenarien (inkl. Base64, HTML-Kommentare, Memory-Poisoning, Reply-Hijack, Tool-Smuggling) über `run_injection_drill()`.
- **M90 — Signierte Tool-Warrants (`backend/tool_warrants.py`):** `issue_warrant()` + `verify_warrant_for_call()` mit HMAC-SHA256-Signatur, Ablaufzeit und Parameter-Constraints (`max_amount`, `allowed_path_prefixes`).
- **M80 — Hybrid-SOP-Runner (`backend/hybrid_sop_runner.py`):** `run_hybrid_sop()` trennt deterministische `script`-Schritte strikt von `agent`-Entscheidungsschritten.
- **M82 — Subagenten- & Session-Receipts (`backend/session_receipts.py`):** `build_delegation_receipt()` + `render_offline_html_receipt()` für autarke, XSS-sichere Offline-HTML-Belegdokumente inkl. Retries.
- **M93 — Tool-Output-Firewall & Batching (`backend/tool_output_firewall.py`):** `guard_tool_output()` kappt übergroße MCP-/Web-Outputs; `run_batch_tool_calls()` bündelt parallele Tool-Calls in einem Turn.
- **M92 — Workflow-Freeze & Replay (`backend/workflow_freeze.py`):** `freeze_tool_sequence()` + `replay_frozen_workflow()` in `data/frozen_workflows.db` (Replay mit `0` LLM-Tokens).
- **M94 — Lossless Session-DAG & STORM-Panel (`backend/lossless_session_dag.py`):** Verlustfreie SQLite-Historie (`data/lcm_sessions.db`, `expand_summary_node`, `search_lossless_history`) sowie `run_storm_panel()` mit Judge & Human-Gate.
- **M50 — Agent-Eval- & Modell-Benchmark-Arena (`backend/agent_eval_arena.py`):** `run_eval_arena()` vergleicht Modelle anhand des Referenz-Decks in `data/eval_arena.db` nach Score, Latenz und Kosten.
- **M45 — Deep-Research-Labor (`backend/deep_research_lab.py`):** `triangulate_sources()` (Trust-Tiers inkl. ArXiv/PatSnap/amtliche Quellen) und `compile_research_dossier()` mit Vault-Ablage unter `02_Research/`.
- **M65 — Settings-Modal-Ergonomie (`static/views/system_settings_modal.html`):** Gruppierte, umbrechende Tab-Navigation mit visuellen Trennern und einheitlichem Content-Spacing.

---

## 5. Automatisierte Verifikation
- Testsuiten: `tests/test_milestones_75_89_76_91_78.py`, `tests/test_milestones_77_79_81_83_86.py` und `tests/test_milestones_block_ab.py`.

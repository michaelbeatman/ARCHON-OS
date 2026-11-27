# Multi-Agent- & Content-Machine-Roadmap 2026 — Abschlussbericht

**Status (korrigiert 23.11.2026):** 28/28 Punkte *implementiert*, aber zum Zeitpunkt des ursprünglichen Berichts **nicht verifiziert**. Ein nachfolgendes Voll-Audit fand erhebliche Verdrahtungsfehler (Gates ohne Wirkung, Publish ohne Versand, fehlende UI). Diese wurden in einer umfangreichen Sanierungswelle behoben — Details siehe [`SYSTEM_AUDIT_2026_KONSOLIDIERT.md`](SYSTEM_AUDIT_2026_KONSOLIDIERT.md) und [`AUDIT_2026_11_SANIERUNG.md`](AUDIT_2026_11_SANIERUNG.md).

**Zweck:** Nachweis, welche Audit-/Feature-Forderungen aus den Roadmap-Abschnitten 6 (Multi-Agenten-Orchestrierung) und 7 (Content-Machine) im Code landed sind, inklusive Datei- und Testreferenzen.

> **Verifikationsstatus:** Die Regressionstests wurden geschrieben, aber in der Entwicklungssession **nicht vollständig ausgeführt** (lokale venvs ohne pytest, kein `frontend/node_modules`). Die Infrastruktur-Batch-Suite meldet 40 bestandene Tests, der Gesamtlauf (`pytest tests/ -q`, `npm ci && npx tsc --noEmit && npm run build`) muss in CI/Docker erfolgen. Solange dieser nicht grün ist, ist „umgesetzt" nicht gleich „verifiziert".

---

## 1. Multi-Agenten-Orchestrierung (12/12)

| # | Punkt | Kernimplementierung |
|---|-------|---------------------|
| 1 | Durable-Execution-Kernel | `backend/durable_execution_kernel.py` — State-Machine, Append-Only-Command-Log, Fencing-Token, CAS-Claim, Checkpoints; verdrahtet in `workflow_dag_runner.py` (Claim/Transition, Node-Fingerprint-Idempotenz). |
| 2 | Cross-Worker Lease & Claim | `backend/deadlock_supervisor.py` (CAS-Lease, Heartbeat, PID-Liveness) + `backend/event_mesh.py` (Outbox `claimed_by`/`claim_expires`); Hot-Path in `archon/core/orchestration.py`. |
| 3 | Typisiertes A2A-Protokoll | `backend/handoff_desk.py` — `message_id`, `reply_to`, `correlation_id`, `confidence`, `attachments_json`, Payload-Hash; Erzeugung in `archon/core/delegation.py`, Empfang mit `role="assistant"` statt `role="user"`. |
| 4 | Shared Task Queue | `backend/dead_letter_queue.py` — `attempt`, `idempotency_key`, `priority`, CAS-Leases, `enqueue_task`/`claim_next`/`complete`/`fail`; Delegations-Fehler werden eingestellt, REST in `archon/routers/execution.py`. |
| 5 | Supervisor-Worker-Topologie | `backend/supervisor_rollover.py` — Parent-Kette aus `config/org_hierarchy.json`, Ausfall-Registry, Rollover; explizite `supervisor_id` auf Leitrollen, `apex_ids` in `delegation.py`, echte `links` als SSOT. |
| 6 | Agent-Memory-Scope | `backend/core_memory_manager.py` und `backend/offline_memory_vault.py` — `private/shared/project/global`, ACL, TTL, Migration, zentrale Sichtbarkeitsregel; `archon/routers/memory.py` validiert den Scope; Delegationsbindung in `delegation.py`. |
| 7 | Deterministischer Conflict-Resolver | `backend/consensus_gate.py::resolve_debate_consensus()` (Votes/Evidence, Negation gewinnt, Fail-Closed); Boardroom in `core_dispatcher.py`, Fan-in in `archon/core/orchestration.py` (statt `aggregation_lisa`-Prompt). |
| 8 | Event-Push statt 10-s-Polling | `archon/core/runtime.py::subscribe_events()/unsubscribe_events()`; `delegation.py` wartet auf `kanban_updated`, konfigurierbare Deadline/Fallback-Poll/`retry_count` in `autonomy_settings`. |
| 9 | Eval & Promotion Gates | `backend/eval_gates.py`, `backend/agent_scorecard_engine.py` (kein erfundener 98 %-Wert mehr); Delegations-Check in `delegation.py`, strikte Profil-Aktivierung in `archon/services/profiles_service.py`. |
| 10 | Structured Handoff | `backend/handoff_desk.py` — Acceptance Criteria aus dem Task-Payload, Validierung vor `accept_handoff()`, `summarize_for_handoff()` für Context-Compression; Worker-Verifikation via `kanban_verifier.py`. |
| 11 | Config-SSOT + CI-Drift-Check | `scripts/sync_profile_ssot.py` (`--check`, `--allow-missing-hermes`), `scripts/validate_config.py --strict`, `.github/workflows/ci.yml` (73/73/73 konsistent). |
| 12 | Zentrale Cancellation-Propagation | `backend/cancellation.py` (CancelToken, Kind-Tokens, `cancel_scope`); Kette Mission Control → Dispatch (`orchestration.py`) → DAG (`workflow_dag_runner.py`) → Boardroom (`archon/routers/boardroom.py`). |

## 2. Content-Machine (16/16)

| # | Punkt | Kernimplementierung |
|---|-------|---------------------|
| 1 | Publish-Sweep im Scheduler | `workflow_scheduler.py` (5-Min-Sweep), `content_machine.py::publish_scheduled_due_assets()` mit vereinheitlichter Suche `('scheduled','approved')`. |
| 2 | HITL-Finalisierung zentral | `finalize_assets_for_workflow_run()` in `workflow_dag_runner.py::resume_workflow_run()` verankert (idempotent). |
| 3 | Research-Engine anbinden | `n_research` als echter Tool-Knoten (`workflow_dag_runner.py`), `research_engine_v2.py` mit Triangulation + `save_dossier_for_result()`, `dossier_path` im Asset-Schema, Verdict-Key-Fix. |
| 4 | Quality-Gate wirksam | `content_machine.py::_enforce_asset_quality()` blockt Freigabe/Publish; echter `quality_gate`-Knoten im DAG-Runner und in Vorlagen. |
| 5 | Fact-Check-Gate | `evaluate_fact_check()` gegen Belegquellen, gespeichert in `fact_check_report_json` und als Freigabeblocker verdrahtet. |
| 6 | Plagiat-/Copyright-Check | `evaluate_plagiarism_risk()` (Shingle-Ähnlichkeit, injizierbarer Korpus), `evaluate_source_rights()`, `license`/`rights` pro Quelle in `research_engine_v2.py`/`research_sources.py`, Rechte-Metadaten bei Ingestion. |
| 7 | SEO-Direkt-Publish abschalten | `seo_execution_agent.py` erzeugt `status: "review"` + `approval_required`, nur `draft_cms`, echte SERP-Daten via `serp_analysis`; `/api/seo/generate` mit `require_admin_or_503`. |
| 8 | Ideen-Status vereinheitlichen | `VALID_CAMPAIGN_STATUSES`/`CAMPAIGN_STATUS_IDEA` in `content_machine.py`, `competitor_idea_bridge.py` nutzt die Konstante; `idea`-Badge + Filter im Frontend. |
| 9 | Feedback-Loop lesbar | `content_machine.py` liest `config/voice.md`, `voice_winner_hooks.md` + Learnings und injiziert sie in `n_master_brief`; Regressionstest vorhanden. |
| 10 | A/B-Testing | `content_variants`/`content_experiments`, `variant_id` in `content_metrics`, Helfer `create_variant`/`record_variant_metrics`/`decide_experiment`, REST-Endpunkte. |
| 11 | Harte Kanalvalidierung | `validate_channel_constraints()` gegen `CHANNEL_SPECS` (Hook 180), Markierung von Parse-Fehlern, `channel_validation_json`, Freigabeblocker. |
| 12 | Editorial Calendar & Rollen | `author`/`reviewer`/`publisher`, Tabelle `content_asset_approvals`, `approval_history()`, `decision_id` auch bei manueller Freigabe, Router-Endpunkt. |
| 13 | Skills injizieren | `li-human`-Regeln aus `.agents/skills/li-human/SKILL.md` (path-jail) in Kanal-Prompts + verpflichtender Review-Knoten `n_li_human_review` vor dem HITL-Gate. |
| 14 | GEO als Fähigkeit | `build_geo_jsonld()` (Article/FAQ), `append_llms_txt()`, `geo_jsonld_json`, `check_geo_citations(hours=48)` mit persistiertem `citation_check_json`. |
| 15 | Frontend vereinigen | Content-Arbeit läuft im Workflow-Studio `/workflows` (`ContentMachineCockpit`-Bausteine); Media-Handoff `?media=…` aus `ContentStudioView` (`/crm`) inkl. `frontend/src/lib/content-flow.ts`. Produktmodell-Korrektur 23.11.2026 (D09-M7): keine eigene Content-Domäne, alte Deeplinks nur als Legacy-Alias weitergeleitet. |
| 16 | SSRF-Schutz & dynamische Daten | `oracle_news_radar.py` nutzt `utils.safe_http.safe_http_json(..., public_only=True)` und einen dynamischen 30-Tage-GitHub-Cutoff. |

---

## 3. Umsetzungsreihenfolge

| Batch | Schwerpunkte |
|-------|--------------|
| A | CI `--strict`/Drift-Check, Oracle-SSRF, Research-Verdict, decision_id, `idea`-Status, Kanal-/Fact-Check-Blocker, A/B-API |
| B | Event-Push, Cancel-Kette, deterministischer Konsens inkl. Ersatz von `aggregation_lisa` |
| C | Shared Queue, Memory-Scope + Delegationsbindung, Plagiat/Rechte, SEO-HITL, GEO-Artefakte |
| D | A2A-Envelope, Handoff-Kriterien/Kompression, Eval-Gates, Supervisor-Rollover, Dossier, Editorial-Rollen, Skills, GEO-Citation, Frontend |

## 4. Neue/regressionsrelevante Module

`backend/cancellation.py`, `backend/supervisor_rollover.py`, `frontend/src/lib/content-flow.ts` (neu) sowie `backend/supervisor_rollover.py`-Tests. Erweitert wurden u. a. `backend/content_machine.py`, `backend/dead_letter_queue.py`, `backend/handoff_desk.py`, `backend/core_memory_manager.py`, `backend/offline_memory_vault.py`, `archon/core/delegation.py`, `archon/core/orchestration.py`, `core_dispatcher.py`, `backend/workflow_dag_runner.py`.

## 5. Regressionstests

Neue Testfiles (`tests/test_p2_*.py`): `oracle_ssrf`, `research_verdict`, `content_quickwins`, `config_strict_ci`, `cancellation`, `cancellation_wiring`, `delegation_event_push`, `consensus_wiring`, `seo_hitl`, `plagiarism_gate`, `memory_scope`, `shared_queue`, `deterministic_fan_in`, `delegation_memory_binding`, `supervisor_rollover`, `content_batch_d`, `delegation_batch_d`.

## 6. Bewusste Vereinfachungen / offene Folgearbeiten

- **Kein echtes Coroutine-Replay** im Durable Kernel: Resume nutzt persistierte Node-States und Checkpoints (pragmatisch, aber strukturell abgesichert).
- **Frontend** ist ein Media-Handoff zwischen `/crm` und dem Workflow-Studio (`/workflows`), kein vollständiger Komponenten-Merge und keine eigene Content-Domäne (Produktmodell-Korrektur 23.11.2026, D09-M7).
- **`supervisor_id`** wurde auf sechs Leitrollen explizit gesetzt; alle anderen Supervisoren kommen aus den 69 echten `links` der Hierarchie.
- **Kontext-Kompression** beim Handoff ist eine deterministische Kopf-/Schwanz-Kürzung, keine semantische Zusammenfassung.
- **M111 (Bulkheads/Circuit-Breaker), M112 (OTel-Tracing) und M113 (Kill-Switch/Asset-Retirement)** bleiben eigenständige Meilensteine und sind nicht Teil von M114.
- **Tests nicht ausgeführt** — siehe Hinweis oben.

## 7. Verifikation

```bash
python -m pytest tests/test_p2_*.py -q
python scripts/validate_config.py --strict
python scripts/sync_profile_ssot.py --check --allow-missing-hermes --json
```

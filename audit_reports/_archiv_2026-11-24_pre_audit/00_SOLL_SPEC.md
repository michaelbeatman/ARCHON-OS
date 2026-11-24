# Archon OS — SOLL-SPEZIFIKATION (Phase 0, frischer Lauf 24.11.2026)

> Verbindlicher Maßstab für alle 16 Domänen-Audits. **Ausschließlich aus Systemdokumentation
> extrahiert; kein Implementierungscode als Quelle verwendet.**
> Basis: HEAD `83691375` (main, v0.5.7.7).

## Quellen / SSOT-Rangfolge

1. `docs/system/NEVER_DO_LIST.md` — Veto, Benutzerentscheidung 22.11.2026
2. `docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` — Architektur-SSOT
3. `docs/AUDIT_FINDINGS_REGISTER.md` — Findings-SSOT („kein Fix ohne Registereintrag")
4. `docs/system/WIRING_AUDIT_2026.md` — 100%-Verdrahtungskriterium
5. `docs/system/ORCHESTRATION_GOVERNANCE_V2_GUIDE.md`, `docs/ARCHITECTURE_N8N_VS_AGENT_ROUTING.md`
6. `docs/system/LLM_TRACING_LANGFUSE_GUIDE.md` (Ist-Zustand Abschnitt 0 ist maßgeblich), `docs/security/*`, `README.md`, `SECURITY.md`

## 0. Globale Randbedingungen

| ID | Anforderung | Quelle |
|---|---|---|
| G-01 | **Kein Coroutine-/Event-Replay** im Durable Kernel. Persistierte Node-States + Checkpoints sind die akzeptierte Lösung. Nicht implementieren, nicht vorschlagen. | NEVER_DO §1 |
| G-02 | **Keine PostgreSQL-Migration.** SQLite bleibt DB. Konsolidierung `28 → 3` Domänen-DBs + physisch isolierte Mandanten-DBs ist Endarchitektur. | NEVER_DO §2 |
| G-03 | **100 %-Verdrahtung:** Jede Mechanik braucht (1) Produzent, (2) Konsument im Produktivpfad, (3) sichtbarer Effekt (DB/Datei/Webhook/Audit), (4) Test/Metrik. Fehlt ein Glied → „Theater". | WIRING_AUDIT |
| G-04 | Status „implementiert" nur mit Verifikation (Test/py_compile/Container). „Keine Regression" ≠ „fertig". Grüne Tests heißen nur: keine Regression. | REGISTER §5 |
| G-05 | Bewusst akzeptierte Risiken nicht neu verhandeln: `main.py` God-Object, 11k-Zeilen-Telegram-Adapter, prozess-lokale Provider-Breaker, Dev-Default ohne Auth nur bei `127.0.0.1`, n8n-Stubs deaktiviert statt implementiert. | REGISTER §6 |
| G-06 | Doku-Behauptungen sind **Behauptungen**, keine Beweise. Jede Aussage ist gegen Code zu verifizieren. | REGISTER §5 / TRACING §0 |
| G-07 | Zweisprachigkeit DE/EN: 70 Spezialisten + 3 Meta-Profile (73 Einträge), 3-Tier `SOUL.md` (Compact/Pro/Full), 832 Prompts, 55 Frameworks, 11 UI-Lokale. | README / Architektur |

## 1. Verdrahteter Schein & Stub-Detection

- S-1.1 Keine Mocks, Dummy-Daten, hartcodierten Returns oder `TODO`/`FIXME` im Produktivkern, die als echte Funktion ausgegeben werden.
- S-1.2 Alle vier Glieder aus G-03 nachweisbar. UI-Controls brauchen Handler + existierenden Ziel-Endpunkt; SSE hört auf echte Events; Status-Maps kennen alle Backend-Statuswerte.
- S-1.3 Quality-/Fact-Check-/Plagiat-/Kanal-Gates **blockieren** Freigaben, nicht nur Score.
- S-1.4 Outbox/DLQ braucht produktiven Drainer mit CAS + Retry + Dead-Letter.
- S-1.5 Deaktivierte Stubs dürfen keinen Erfolg signalisieren; ehrlicher Zustand (`planned`/`not_configured`/`simulation`/`ARCHON_DEMO_MODE`).
- S-1.6 Historisch offen: `subagents_count`, `suspend_task()`, Schema-Dropzone, n8n-echte Nodes, PbSettings-Endpunkte, Tool-Output-Firewall im echten Chokepoint.
- S-1.7 Leere/fehlerhafte Antworten nie als Erfolg; „success" nur bei nachgewiesener Wirkung.

## 2. Agenten-Orchestrierung & Routing

- S-2.1 70 Spezialisten + 3 Meta-Profile, 3-Tier SOUL, 8 Domänen, profilbasierte Tool-Scopes.
- S-2.2 Delegation über zentrale PolicyEngine + isolierte Scopes; Subagenten erben **keine** privilegierten Parent-Tools; fail-closed `["web_search"]`.
- S-2.3 Zyklus-/Tiefenschutz: `visited`-Set pro Sub-Session, `_MAX_DELEGATION_DEPTH=5`, Ablehnung **bevor** Kanban-Task/LLM-Call entstehen.
- S-2.4 Cancel-Kette: Kill-Switch fail-closed, `worker.cancel()` bei Deadline, Cancel-Token nach **jedem** `await`, Status `cancelled` persistiert, Registry-Cleanup im `finally`.
- S-2.5 Fan-in-Synchronisation: Synthese erst wenn alle Kinder `completed`; Latch mit Timestamp + Watchdog-Reset; `_MC_ASYNC_LOCK` + `_MC_DATA_LOCK`.
- S-2.6 Lease/Fencing: CAS-Lease, 30-s-Heartbeat, Fencing-Token bei Verlust → harter Abbruch; kein Reaktivieren laufender Tasks; Lease-Claim-Fehler fail-closed.
- S-2.7 DAG: paralleler Fan-Out, Quorum, Human-/Machine-Gates, SHA-256-Fingerprint-Resume, `replan_count`-Cap, Pre-Execution-Validator, `CancelledError` → `cancelled`.
- S-2.8 Effect Ledger mit `UNKNOWN` + zwingender Reconciliation (CAS gegen doppelte Zustellung).
- S-2.9 Budget: atomare BudgetBank (`reserve → settle/release`), harte Tages-/Monatslimits, 15 % Triage/Synthese + 85 % komplexitätsgewichtet, `paused_budget` bei Überschreitung.
- S-2.10 Routing: deterministisch vor probabilistisch (n8n/Skripte, 0 Tokens); OmniRoute :20128; Zero-Egress-Gate + Privacy-Router hart fail-closed; `evaluate_and_gate_llm_dispatch()` in **allen** Dispatch-Pfaden; `blocked` darf nicht auf Cloud-Fallback fallen.
- S-2.11 Circuit-Breaker mit Half-Open (genau **ein** Probe), Retry-After + Jitter 0,75–1,25, 90-s-Gesamt-Deadline der Fallback-Kette.
- S-2.12 Boardroom: 55 Frameworks, 4 Phasen + optionales MoA, isolierte Debate/Critique/Synthesis, `resolve_debate_consensus()`, Chairman-Hoheit, `NO_CONSENSUS` ohne Final Decision, Framework-Instruktion nur 1× pro Call.

## 3. Persistenz, Datenbank & Vault-Integrität

- S-3.1 SQLite WAL als SSOT: `ops.db`, `business.db`, `memory.db`; `busy_timeout=5000`; `resolve_db()` + `TenantContextManager`.
- S-3.2 Physische Mandantentrennung `data/tenants/<id>/{erp,kanban,crm,contracts,deals}.db`; Echtzeit-Umschalter; keine Vermischung.
- S-3.3 DATEV-Nummernkreise pro Mandant atomar; **eine** Authority.
- S-3.4 GoBD-Unveränderlichkeit: `recipient_snapshot_json`, `booked_at`; `booked`/`paid → draft` gesperrt.
- S-3.5 Backups/Restore: Cross-Prozess-Restore-Lock, `PRAGMA quick_check` + FK-Check **vor** `os.replace()`, Rollback, tenant-korrekt + Secrets + WAL; Litestream inkl. Tenant-DBs; RPO/RTO dokumentiert.
- S-3.6 Obsidian-Vault: atomare Writes + Eindeutigkeitssuffix, `expected_mtime`-Konflikt (409), SSOT-Pfad `resolve_obsidian_vault_path()`, RAG-State path→`{mtime,size}`.
- S-3.7 OS-verwaltete Locks, kein TOCTOU; `safe_path_within()` für alle Dateioperationen.
- S-3.8 Schema-Per-Spec: `crm_entities`, `crm_contacts` (GDPR-Opt-In), `crm_interactions` (`external_msg_id UNIQUE`), `erp_*`.
- S-3.9 `PRAGMA foreign_key_check = 0`; keine verwaisten WAL/SHM-Sidecars; keine stillen Datenverluste; `INSERT OR IGNORE` bei abweichender PK-Kollision → Abbruch (DATENVERLUST).
- S-3.10 28→3-Konsolidierung braucht Manifest/Env-Aktivierung; divergierende Inhalte brechen ab.

## 4. Governance, Security & Permissions

- S-4.1 Default-Deny: `ARCHON_REQUIRE_AUTH=true` / Auth fail-closed für Mesh/Prod; Non-Loopback-Bind erzwingt Auth; lokaler Single-User nur bei `127.0.0.1`.
- S-4.2 RBAC auf **allen** schreibenden Admin-Routen; kein fail-open `_require_admin`; Actor aus Body nie autoritativ; 19 RBAC-Duplikate zentralisiert.
- S-4.3 HITL: Passkey/WebAuthn (ES256/RS256, `rpIdHash`, `signCount`, UV, Attestation), Proof an `action` + `resource` gebunden, fail-closed 503/403; Vier-Augen ab 500 € mit Ersteller-Abgleich; Auto-Freigabe bis 50 €; 24 h Eskalation.
- S-4.4 Taint-Gate Default-Deny: `is_critical_egress_tool()` parkt `terminal`, `execute_code`, `computer_use`, `mcp__*`, unbekannte Tools; Einmal-Token verbraucht.
- S-4.5 Tool-Warrants: HMAC-SHA256, Ablaufzeit, `max_amount`, `allowed_path_prefixes`; **alle** Pfad-Aliase geprüft; RBAC-Jail zentral in `decide()`.
- S-4.6 Secrets: keine Secrets im Git; env-basiert; `audit_secrets.py` als hartes Gate; keine statischen Fallback-Keys; Rotation (GitHub 90 d, Telegram 180 d, Provider 90 d); HMAC-Epochen.
- S-4.7 Input-Sanitization: Dual-LLM-Quarantine, **25** Injection-Muster, Prompt-Shield, Tool-Output-Firewall, HTML-Escaping, `_validate_base_url()`, YAML-Sperre, SSRF-Schutz.
- S-4.8 Sandbox: `python -I`, `TemporaryDirectory`, ohne Host-Env-Secrets, POSIX-`rlimit`, AST-Sperre (`os`, `subprocess`, `socket`, `ctypes`, `urllib`) — auch gegen `__import__`/`eval`/`exec`/Dunder.
- S-4.9 Egress/DLP: `enforce_egress_firewall_for_url()` + `sanitize_outbound_llm_payload()` vor **jedem** externen Dispatch; `internal: true` Worker-Netz; Socket-Proxy-Allowlist; `cap_drop: [ALL]`.
- S-4.10 DSGVO Art. 15/17, EU AI Act Art. 4/12/19/50, GoBD, ISO-27001; 26 HIGH_RISK-Rollen; Disclaimer-Dialoge; KI-Kompetenzregister.

## 5. Audit-Trail & Kryptografie

- S-5.1 HMAC-SHA256-Hashkette mit Env-Key: `HMAC(prev_hash + timestamp + payload)`; **kein** Abschalter; nacktes SHA-256 nur Legacy.
- S-5.2 Lückenlose LLM-Dispatch-Proofs: provider, model, target_host, target_endpoint, egress_zone, **Prompt-/Canary-Version**, Spalten- **und** Payload-Konsistenz; URL-Query-Tokens vor Signatur geschwärzt.
- S-5.3 Alle Ketten (Audit, Approval, Receipt, Treasury, ApiKey, Email-Draft, GDPR) mit `verify_integrity()`, Append-only-Trigger, Block-ID/Epochen, Anker gegen **Chain-Head** (Tail-Löschung erkannt), non-blocking.
- S-5.4 Audit-Schreibfehler nie verschluckt; RBAC-Denials + Restore + Webhooks signiert in Zentralkette; keine Payloads/Secrets im Event.
- S-5.5 Unveränderbarkeit: Verify-Endpoint, JSON/CSV-Export, GoBD-PDF mit verifizierten Blöcken.
- S-5.6 5 Nebenketten im 30-s-Loop verifiziert; kein fail-open Mirror als Wahrheitsquelle; `trace_id`/`session_id`/`correlation_id` in audit_log.

## 6. Integrationen, Webhooks & API-Routing

- S-6.1 OmniRoute :20128, Multi-Provider, Key aus `OMNIROUTE_API_KEY` auch für `/v1/models`; Allowlist + Diff vor `--fix`.
- S-6.2 n8n :5678: **eine** Workflow-Quelle, echte Nodes, Service-Token in allen HTTP-Nodes, Host `archon-os`, Browser-ID-Bindung, kein Auto-Owner-Fallback, Webhooks authentifiziert/aktiv.
- S-6.3 Outbound-Webhooks HMAC-SHA256 über exakten (kompakten) Body, Secret nur aus `ARCHON_WEBHOOK_HMAC_SECRET`, Empfänger `compare_digest`/`timingSafeEqual`.
- S-6.4 Pydantic v2 statt roher `dict = Body(...)`; `extra="ignore"`; keine `.dict()`-Reste; Steuerungsfelder vor externen Keys geschützt; Container-Antworten nur bekannte Inhaltsfelder.
- S-6.5 Timeouts auf allen `requests`/`urlopen`, Retry-After + Jitter, strukturierte Hop-Resultate; keine stillen Fallbacks.
- S-6.6 Externe LLM-Provider: Dual-LLM-Guard, Injection-Quarantine, SSRF, Base-URL-Validierung.
- S-6.7 Telegram/Hermes :8642/:8787, MCP `/mcp` mit scoped Keys + HITL; keine internen Auth-Header nach außen; `follow_redirects=False`, `html.escape`.

## 7. Error-Handling, Sackgassen & Recovery

- S-7.1 Keine unbehandelten Exceptions; keine stillen `except: pass`; kein `AttributeError`-500 durch Dict/Modell-Mix; globaler 500-Handler mit `trace_id` ohne Stacktrace-Leak.
- S-7.2 Keine Endlosschleifen: Loop-Guards, Retry-Caps, Deadlock-Watchdog, Replan-Cap, `sufficient=False`.
- S-7.3 Keine Zombie-Prozesse; `_terminate_container()` verifiziert Entfernung; keine Checkpoint-Verluste; `cancel()`-Fehler nie verschluckt.
- S-7.4 Fallback-Strategien mit definierter Kette + 90-s-Deadline; keine Sackgassen bei `blocked`/`failed`; fehlgeschlagene Verifikation → Eskalation; HITL-Auflösung override/retry/abort.
- S-7.5 Fail-Closed bei allen Governance-/Auth-/Egress-/Lease-/Taint-Pfaden; Opt-in-Fail-Open nur explizit dokumentiert.
- S-7.6 Fehler in Insertions/Artefaktwrites → `blocked`/DLQ + ehrliche Quittung, niemals `completed`/`success`.

## 8. Performance, Concurrency & Engpässe

- S-8.1 Kein blockierendes SQLite/I/O im Event-Loop; `asyncio.to_thread` für Hot-Paths; `run_io_bound`.
- S-8.2 Keine `id(loop)`-Clients/Semaphoren ohne Shutdown → `WeakKeyDictionary` + zentraler `close()`.
- S-8.3 TTL-Caches mit Lock, Single-Flight; HTTP-Client-Pools mit `aclose()` im Shutdown.
- S-8.4 Keine Memory-Leaks, keine unbegrenzten Queries, Token-Overhead begrenzt (Framework nur 1×).
- S-8.5 Frontend: ein zentraler SSE-Bus, Debounce/AbortController, Virtualisierung großer Listen (832 Templates).

## 9. Architektur- & Code-Standards (2026)

- S-9.1 Python 3.13 / Node 22 konsistent; alle Compose-Images mit `@sha256:` gepinnt.
- S-9.2 Reproduzierbare Builds: Lockfile + `--require-hashes`; `npm ci` ohne `|| npm install`; Actions per SHA gepinnt.
- S-9.3 CI-Qualitätstor wirkungsvoll: keine `continue-on-error`/`|| true` für Ruff/Mypy/Coverage/ESLint; `ARCHON_TEST_DB_ISOLATION=1` in **allen** Test-Jobs.
- S-9.4 Pydantic-v2-Modelle, Typsicherheit, Modularität statt God-Objects (bewusst akzeptierte Ausnahmen nach G-05).
- S-9.5 Keine XSS-Sinks (`dangerouslySetInnerHTML` nur sanitisiert), WCAG/Focus-Trap.

## 10. System-Härtung & 24/7-Resilienz

- S-10.1 Healthchecks `/health`, `/readyz`, `/livez` (503 bei Event-Loop-Hang); Prometheus/Grafana, Loki/Promtail.
- S-10.2 Watchdog 30 s, Deadlock-Watchdog, Self-Healing **mit echtem Effekt** über Docker-Socket-Proxy (`DOCKER_HOST`, Allowlist, `DockerAdminClient`) — kein direkter Socket.
- S-10.3 Alertmanager wirklich gestartet, Alarm reproduzierbar zustellbar; externer Heartbeat/Dead-Man-Switch konfigurierbar.
- S-10.4 Graceful Shutdown, Crash-Recovery (6 h), Backpressure (Disk/Memory/CPU) mit korrekten Schwellen; kein Default „25 GiB frei".
- S-10.5 Produktiv-Compose statt Dev-`--reload`; `/readyz`-Gate; externes DR-Ziel mit RPO ~5–10 s / RTO dokumentiert; **Watchdog-Supervisor außerhalb des überwachten Loops**.
- S-10.6 Observability-Profile opt-in (`ARCHON_OBSERVABILITY=full`), tracing profile mit Langfuse-Keys; `not_configured` ehrlich gemeldet.

## 11. Context Drift & Handoff-Integrität

- S-11.1 Übergaben Orchestrator → Subagent strukturiert und schema-validiert (Pydantic/JSON-Schema), kein Freitext-Verlust.
- S-11.2 Canary-/Prompt-Version im signierten Dispatch-Proof; berechnete Werte (z. B. `effective_prompt_info`) müssen im Result zurückkommen.
- S-11.3 Kürzungen explizit markiert; keine stillen Trunkierungen von Kontext/Outputs.
- S-11.4 Kind-Ergebnisse mit `trace_id`/`session_id`/`correlation_id` am Parent wieder zusammenführbar (Fan-in).
- S-11.5 State-Übergabe über SQLite-Reloads hinweg persistiert (`cancelled`, `paused`, `delegation_depth`, `replan_count`, `failure_reason`).

## 12. Silent Tool Failures & Hallucination-Prevention

- S-12.1 HTTP 200 ohne `choices`/Text/modellierte Nutzlast → `RuntimeError`, niemals Erfolg.
- S-12.2 `null`, leerer Body, leere Antwort, ungültiges JSON → harter Fehler + Eskalation; keine Erfindung von Fakten.
- S-12.3 `cost_usd` real berechnet (nicht `0.0`); `structured_output_enforcer` füllt Pflichtfelder **nicht** mit `0`/`""`/`[]` und `valid: True`.
- S-12.4 Tool-Wrapper/Webhooks/API-Clients eskalieren Fehler; `ZeroEgressBlockedError` nie geschluckt; kein Fake-Text (`[agent]: Anweisung empfangen...`).
- S-12.5 Simulierte LLM-Antworten (RouterGate, Speculative Hedger, War-Room, Eval-Suite, Map-Reduce) nur explizit gekennzeichnet; keine simulierten Risiken in Governance/HITL.

## 13. Trajectory-Governance & Loop-Prevention

- S-13.1 Harte `max_hops`-, Rekursions-, Token-Budget-Limits **pro Ticket**, persistiert und zur Laufzeit geprüft.
- S-13.2 `replan_count` hat Setzer und Cap; Zirkel-Delegation via `visited`-Set erkannt; Ping-Pong zwischen Agenten blockiert.
- S-13.3 Breaker/Guard greift **vor** teuren Aktionen (Kanban-Task, LLM-Call, Zahlung).
- S-13.4 Loop-Detektion mit anomalen Pfaden (Loops ≥ 3, Token-Spikes, Effort-Collapse) im Flightlog.

## 14. Entscheidungs-Hoheit & Konfliktlösung

- S-14.1 Deterministische Tie-Breaking-Regeln und Autoritäts-Hierarchie bei widersprüchlichen Subagenten-Ergebnissen.
- S-14.2 Chairman nur aus erlaubter, tier-geprüfter Menge (400 bei unbekanntem ID); kein freier Body-Wert.
- S-14.3 `NO_CONSENSUS` erzeugt **keine** Final Decision; Konflikte → HITL/Eskalation.
- S-14.4 Approver-Identität aus Session statt Body; Vier-Augen mit Ersteller-Abgleich; Schwelle nicht durch Einzel-Admin änderbar.
- S-14.5 Policy-Verstoß eines Subagenten → harte Ablehnung, kein „meistens gewinnt".

## 15. Semantische Rollen- & Prompt-Trennschärfe

- S-15.1 Rollen mit klarer Positiv- und **Negativ-Abgrenzung** („was darf diese Rolle explizit NICHT?") — alle 70 Profile.
- S-15.2 Keine überlappenden Zuständigkeiten / widersprüchlichen System-Prompts zwischen Profilen.
- S-15.3 Medizin/Recht/Steuer/Finanzen mit HITL-Pflicht und 26 EU-AI-Act-HIGH_RISK korrekt klassifiziert.
- S-15.4 SOUL-SSOT: `souls/` versioniert (490 Artefakte DE+EN), SHA-256-Manifest über normalisierte Zeilenenden, CI-Drift-Gates, keine erfundenen SOUL-Hashes.
- S-15.5 `.hermes/profiles/` und `data/hermes_profiles/` aus SSOT regeneriert, keine Divergenz.

## 16. Distributed Tracing & Observability

- S-16.1 W3C `traceparent`/`tracestate` (128/64 Bit) über **alle 18 Systemgrenzen**: Browser→Next.js→FastAPI→LLM-Kernel→Dispatcher→Provider/n8n→Outbox→Hermes→PocketBase→MCP→SSE→Telegram→Audit→OTel→Langfuse→Loki→Prometheus.
- S-16.2 `TraceContextMiddleware` inbound (Response-Header `X-Trace-Id`), `inject()` in allen outbound `httpx`-Calls, `contextvars` über `to_thread`/Tasks.
- S-16.3 `trace_id` persistent in `event_mesh_outbox`, Audit-Log, Receipts; bei Retry/DLQ erneut injiziert.
- S-16.4 Echter OTel-Collector + Langfuse-Export mit Sampling, Exportfehler nicht auf DEBUG verschluckt.
- S-16.5 Kausale Fehlerketten lückenlos rekonstruierbar (ein Root pro Systemeintritt, keine zweiten Roots im selben Call).

---

## Bewertungsskala (verbindlich für Audits und Masterplan)

**1 = schlecht / kaputt / disfunktional · 10 = top / funktional im Sinne des Erfinders.**

Jeder Domänenbericht schließt mit `DOMÄNEN-SCORE: X/10` + einzeiliger Begründung.

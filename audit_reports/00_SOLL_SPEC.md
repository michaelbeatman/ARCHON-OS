# Archon OS — SOLL-SPEZIFIKATION (verbindlich, Phase 0)

> **Zweck:** Kompakte, maschinennahe Referenz aller verbindlichen funktionalen und
> sicherheitstechnischen Anforderungen. Ausschließlich aus System-Dokumentation
> extrahiert (kein Implementierungscode gelesen). Jeder Domänen-Subagent in Phase 1
> nutzt dieses Dokument als alleinigen Soll-Maßstab.
>
> **Quellen (SSOT-Reihenfolge bei Konflikten):**
> 1. `docs/system/NEVER_DO_LIST.md` (Veto, Benutzerentscheidung 22.11.2026)
> 2. `docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` (Architektur-SSOT)
> 3. `docs/AUDIT_FINDINGS_REGISTER.md` (Findings-SSOT, "kein Fix ohne Registereintrag")
> 4. `docs/system/SYSTEM_AUDIT_2026_KONSOLIDIERT.md`, `docs/system/WIRING_AUDIT_2026.md`
> 5. `docs/system/ARCHON_ERP_ARCHITECTURE_SPEC.md`, `docs/system/ORCHESTRATION_GOVERNANCE_V2_GUIDE.md`
> 6. `docs/ARCHITECTURE_N8N_VS_AGENT_ROUTING.md`, `docs/security/*`, `README.md`

---

## 0. Global verbindliche Randbedingungen

| ID | Anforderung | Quelle |
|---|---|---|
| G-01 | **Kein Coroutine-/Event-Replay** im Durable Kernel. Persistierte Node-States + Checkpoints sind die akzeptierte Lösung. Nicht implementieren, nicht vorschlagen. | NEVER_DO_LIST §1 |
| G-02 | **Keine PostgreSQL-Migration.** SQLite bleibt DB. Konsolidierung `28 → 3` Domänen-DBs + physisch isolierte Mandanten-DBs ist Endarchitektur. | NEVER_DO_LIST §2 |
| G-03 | **100 %-Verdrahtungskriterium:** Jede Kernmechanik braucht nachweisbar (1) Produzent, (2) Konsument im Produktivpfad, (3) sichtbarer Effekt (DB/Datei/Webhook/Audit), (4) Test/Metrik. Fehlt ein Glied → "Theater"/BLOCKER. | WIRING_AUDIT_2026 |
| G-04 | Status "implementiert" ist nur mit Verifikation (Test/py_compile/Container) zulässig. "Keine Regression" ≠ "fertig". | AUDIT_FINDINGS_REGISTER §5 |
| G-05 | Release-SSOT ist v0.5.7.4 (24.11.2026); Boardroom = 4 Phasen + optionales MoA (nicht 6). | README / Register §8.6 |
| G-06 | Deutsch + Englisch parity (70 Profile, 832 Prompts, 55 Frameworks, 11 UI-Lokale). | README / Architektur |

---

## 1. Verdrahteter Schein & Stub-Detection (Domäne 1)

- **S-1.1** Keine Mocks, Dummy-Daten, hartcodierten Returns oder `TODO`/`FIXME`-Blöcke im Produktivkern, die als echte Funktion ausgegeben werden.
- **S-1.2** Jede mechanic muss alle 4 Glieder aus G-03 erfüllen. UI-Controls brauchen Handler + existierenden Ziel-Endpunkt; SSE-Cockpits hören auf echte Events statt manuellem Refresh; Status-Maps müssen alle Backend-Statuswerte kennen.
- **S-1.3** Gates (Quality/Fact-Check/Plagiat/Kanal) müssen Freigaben **blockieren**, nicht nur einen Score liefern.
- **S-1.4** Outbox/DLQ braucht produktiven Drainer mit CAS + Retry + Dead-Letter.
- **S-1.5** Deaktivierte Stubs dürfen keinen Erfolg signalisieren; "ehrlicher Zustand" statt Fake-Erfolg. Demo-/Schattenpfade müssen explizit gekennzeichnet sein (`ARCHON_DEMO_MODE`, `status: planned/not_configured/simulation`).
- **S-1.6** `subagents_count`, `suspend_task()`, Schema-Dropzone, n8n-echte Nodes, PbSettings-Backend-Endpunkte waren historisch offen → Prüfung auf Re-Regresssion. (Register Cluster A PARTIAL)
- **S-1.7** Tool-Output-Firewall `guard_result()` muss im echten Tool-Chokepoint (MCP/Plugins/DAG) liegen, nicht nur als Endpoint.

---

## 2. Agenten-Orchestrierung & Routing (Domäne 2)

- **S-2.1** 70 Spezialisten + 3 Meta-Profile (73 Einträge), 3-Tier `SOUL.md` (Compact/Pro/Full), 8 Domänen; profilbasierte Tool-Scopes.
- **S-2.2** Delegation: zentrale `PolicyEngine` + isolierte Scopes (`resolve_isolated_execution_scope`), Subagenten erben **keine** privilegeierten Parent-Tools; fail-closed Fallback `["web_search"]`.
- **S-2.3** Zyklus-/Tiefenschutz: `visited`-Set pro Sub-Session, `_MAX_DELEGATION_DEPTH=5`, Ablehnung bevor Kanban-Task/LLM-Call entstehen.
- **S-2.4** Cancel-Kette: Kill-Switch-Registrierung fail-closed, `worker.cancel()` bei Deadline, Cancel-Token nach **jedem** `await` geprüft, Status `cancelled` persistiert, Registry-Cleanup im `finally`.
- **S-2.5** Fan-in-Synchronisation: Synthese startet erst wenn alle Kind-Tasks `completed`; Latch mit Timestamp + Watchdog-Rücksetzbar; `_MC_ASYNC_LOCK` + `_MC_DATA_LOCK`.
- **S-2.6** Lease/Fencing: CAS-Lease mit 30-s-Heartbeat, Fencing-Token bei Verlust harter Abbruch; kein Reaktivieren laufender Tasks durch Deadlock-Watchdog; Lease-Claim-Fehler fail-closed.
- **S-2.7** DAG-Engine: paraleller Fan-Out, Quorum, Human-/Machine-Gates, SHA-256-Fingerprint-Resume; `replan_count`-Cap, Pre-Execution-DAG-Validator; `CancelledError` → Node `cancelled`, Run `cancelled`.
- **S-2.8** Effect Ledger mit `UNKNOWN` + zwingender Reconciliation (CAS gegen doppelte Zustellung).
- **S-2.9** Budget: atomare `BudgetBank` (`reserve → settle/release`), harte Rollen-Tages-/Monatslimits, Reservierung 15 % Triage/Synthese + 85 % komplexitätsgewichtet (0.7–2.0), `paused_budget` bei Überschreitung; `reserve()` muss Task-Budgets prüfen.
- **S-2.10** Routing: deterministisch vor probabilistisch (n8n/Skripte für feste Regeln, 0 Tokens); OmniRoute-Port 20128; Zero-Egress-Gate + Privacy-Router mit hartem Fail-Closed-Block; `evaluate_and_gate_llm_dispatch()` in **allen** Dispatch-Pfaden (Core, Agent-Router, Boardroom, Chat, Container-Ops); `blocked`-Status darf nicht auf Cloud-Fallback fallen.
- **S-2.11** Circuit-Breaker mit Half-Open (genau ein Probe), Retry-After + Backoff/Jitter (0.75–1.25), 90-s-Gesamt-Deadline der Fallback-Kette.
- **S-2.12** Boardroom: 55 Frameworks, 4 Phasen + optionales MoA, isolierte Debate + Critique + Synthesis, `resolve_debate_consensus()`; Framework-Instruktion nur 1× pro Call (Token-Overhead).

---

## 3. Persistenz, Datenbank & Vault-Integrität (Domäne 3)

- **S-3.1** SQLite WAL als Single Source of Truth: `ops.db`, `business.db`, `memory.db` (Konsolidierung 28→3), `busy_timeout=5000`, `resolve_db()`-Adapter + `TenantContextManager`.
- **S-3.2** Physische Mandanten-Trennung: `data/tenants/<company_id>/{erp,kanban,crm,contracts,deals}.db`, Echtzeit-Umschalter; keine Vermischung personenbezogener Daten zwischen Einheiten.
- **S-3.3** DATEV-Nummernkreise pro Mandant atomar: Debitoren ab 10001, Kreditoren ab 70001, Artikel `ART-1001+`, `ANG-/AB-/RE-{YYYY}-{0001}`.
- **S-3.4** GoBD-Unveränderlichkeit: `recipient_snapshot_json`, `booked_at`; Status-Rückstufung `booked`/`paid → draft` gesperrt.
- **S-3.5** Backups/Restore: Cross-Prozess-Restore-Lock (`acquire_restore_lock()`), Verifikation (`PRAGMA quick_check`, FK-Check) **vor** `os.replace()`, Rollback bei Fehler; tenant-korrekt + Secrets + WAL; LiteStream-Replikation inkl. Tenant-DBs (≥0.5, `dir:`-Pattern).
- **S-3.6** Obsidian-Vault: atomare Writes + Eindeutigkeits-Suffix, `expected_mtime`-Konflikterkennung (409), SSOT-Pfad `resolve_obsidian_vault_path()`, RAG-State path→`{mtime,size}` (Geänderte erneut synchronisieren).
- **S-3.7** Dateisystem-Locks: OS-verwaltete Locks, kein TOCTOU; `safe_path_within()` für alle Datei-Operationen (Trash/Restore/Purge/Run).
- **S-3.8** Schema-Per-Spec: `crm_entities`, `crm_contacts` (inkl. `gdpr_opt_in_status`), `crm_interactions` (`external_msg_id UNIQUE`), `erp_items`, `erp_documents`, `erp_document_lines` (siehe ERP-Spec §2).
- **S-3.9** FK-Integrität: `PRAGMA foreign_key_check` = 0; keine verwaisten WAL/SHM-Sidecars; keine stillen Datenverluste.

---

## 4. Governance, Security & Permissions (Domäne 4)

- **S-4.1** Default-Deny: `ARCHON_REQUIRE_AUTH=true` / Auth fail-closed für Mesh/Prod; Non-Loopback-Bind erzwingt Auth (`_must_force_auth()`); lokaler Single-User-Modus nur bei `127.0.0.1`. Kein Fallback-Admin ohne expliziten lokalen Modus.
- **S-4.2** RBAC auf **allen** schreibenden Admin-Routen; kein fail-open `_require_admin`; Actor aus Body ist nie autoritativ; Auth-Flag im Session-Pfad.
- **S-4.3** HITL-Gates: Passkey/WebAuthn-Proof (ES256/RS256, `rpIdHash`, `signCount`-Replay-Schutz), Proof an `action` + `resource` gebunden, fail-closed 503/403; Vier-Augen ab 500 €, Auto-Freigabe bis 50 €, 24 h Eskalation; Urlaubsmodus/Delegation;竞争性 Kategorien.
- **S-4.4** Taint-Gate Default-Deny: `is_critical_egress_tool()` parkt `terminal`, `execute_code`, `computer_use`, `mcp__*`, `node_plugin:*` und unbekannte Tools; nur explizit harmlose Tools ausgenommen; Einmal-Token verbraucht (`consumed=1`).
- **S-4.5** Tool-Warrants: HMAC-SHA256-signiert, Ablaufzeit, `max_amount`, `allowed_path_prefixes`; **alle** Pfad-Aliase (`file_path`, `uri`, `target`) geprüft; fehlendes Pfad-Argument bei Pfad-Constraint → deny; RBAC-Jail zentral in `decide()`.
- **S-4.6** Secrets: keine Secrets/Keys/Tokens im Git; env-basiert (`.env` 0600); `scripts/audit_secrets.py --staged/--all` als harte Gates; keine statischen Fallback-Keys (`sk-archon-local-dev` etc.); Rotation (GitHub 90 d, Telegram 180 d, Provider 90 d); HMAC-Key-Rotation über Epochen.
- **S-4.7** Input-Sanitization: Dual-LLM-Quarantine (`backend/dual_llm_sanitizer.py`), 25 Injection-Muster, Prompt-Shield, Tool-Output-Firewall, HTML-Escaping in UI/Proxy, `_validate_base_url()` (nur http(s), keine Steuerzeichen/Credentials), YAML-Injektionssperre, SSRF-Schutz (`check_public_url`).
- **S-4.8** Sandbox: `python -I`, `TemporaryDirectory`, ohne Host-Env-Secrets, POSIX-`rlimit`, AST-Sperre (`os`, `subprocess`, `socket`, `ctypes`, `urllib`); `proof_command` nie beliebige Binarys ohne Policy/Jail; kein Host-Fallback ohne Opt-in.
- **S-4.9** Egress/DLP: `enforce_egress_firewall_for_url()` + `sanitize_outbound_llm_payload()` (secret_masker + pii_scrubber) vor **jedem** externen Dispatch; `docker-worker-zero-egress_net` (`internal: true`); Docker-Socket-Proxy mit Allowlist + `DockerAdminClient`; least privilege, `cap_drop: [ALL]`, `no-new-privileges`.
- **S-4.10** DSGVO Art. 15/17 (paginiert exportieren, case-insensitiv schwärzen), EU AI Act Art. 4/12/19/50, GoBD + ISO-27001 Controls; keine professionelle Beratung ohne Disclaimer-Dialoge (Legal/Tax, BauGB/HOAI, EU-MDR/REACH).

---

## 5. Audit-Trail & Kryptografie (Domäne 5)

- **S-5.1** HMAC-SHA256-Hashkette mit Env-Key: `hash = HMAC_SHA256(env_key, prev_hash + timestamp + payload)`; **kein** Abschalter (`sha256_dispatch_audit_enforced = true`); nacktes SHA-256 nur Legacy-Format.
- **S-5.2** Lückenlose LLM-Dispatch-Proofs: pro Call (auch geblockte) provider, model, target_host, target_endpoint, egress_zone; Spalten- **und** Payload-Konsistenz in `verify_integrity()`; URL-Query-Tokens vor Signatur geschwärzt.
- **S-5.3** Alle Ketten (Audit, Approval, Receipt, Treasury, ApiKey, Email-Draft, GDPR) mit `verify_integrity()`, Append-only-Trigger gegen UPDATE/DELETE, `block_id`/Epochen-Migration bei Formatwechsel; Anker-Verifikation gegen Ketten-Head (Tail-Löschung erkannt); Hintergrund-Anker non-blocking.
- **S-5.4** Audit-Schreibfehler nie verschluckt (`audit_status: "error"`), RBAC-Denials + DB-/Snapshot-Restore + Webhook-In/-Out signiert in Zentralkette (keine Payloads/URL-Query/Secrets im Event).
- **S-5.5** Unveränderbarkeit: `/api/operations/governance/audit-log/verify`, Export JSON/CSV, Live-Posture-Report; GoBD-PDF zeigt verifizierte Blöcke, signed Dispatches, Hard-Block, `Internal=true`.
- **S-5.6** 5 Nebenketten im 30-s-Loop verifiziert; kein fail-open Mirror als Wahrheitsquelle; Signatur-Epochen brachen alte Blöcke nicht.

---

## 6. Integrationen, Webhooks & API-Routing (Domäne 6)

- **S-6.1** OmniRoute :20128, Multi-Provider (OpenAI/Anthropic/Gemini/Groq/DeepSeek), Key aus `OMNIROUTE_API_KEY` (auch `/v1/models`); Allowlist für Healthcheck-`--fix`, Diff vor Update.
- **S-6.2** n8n :5678: **eine** Workflow-Quelle, echte Nodes, Service-Token in allen HTTP-Nodes, Host `archon-os` (kein Drift), Browser-ID-Bindung aktiv, kein Auto-Owner-Fallback; Webhooks authentifiziert.
- **S-6.3** Outbound-Webhooks HMAC-SHA256 über exakten Body (`utils/safe_http.py::webhook_signature_headers()`), Secret nur aus `ARCHON_WEBHOOK_HMAC_SECRET` (kein Default), kompakte Serialisierung, Empfängerseite `timingSafeEqual`/`compare_digest` (Exchange Bridge aktiv).
- **S-6.4** Payload-Validierung: Pydantic v2-Modelle statt roher `dict = Body(...)` (historisch ~136 rohe Dicts), `extra="ignore"`, keine `.dict()`-Reste; Steuerungsfelder (`status/content/error/media_path/data`) vor externen Keys geschützt; Container-Antworten nur bekannte Inhaltsfelder + `_clean_dispatch_output()`.
- **S-6.5** Timeouts auf allen `requests`/`urlopen`, Retry-After + Jitter, strukturierte Hop-Resultate für Monitoring; keine stillen Fallbacks.
- **S-6.6** Externe LLM-Provider: Dual-LLM-Guard, Prompt-Injection-Quarantine für E-Mail/Web, SSRF-Schutz, Base-URL-Validierung vor Config-Schreiben.
- **S-6.7** Telegram/Hermes :8642/:8787, MCP-Gateway `/mcp` mit scoped Keys + HITL; keine internen Auth-Header nach außen (`authorization`, `x-archon-session`, Cookies); `follow_redirects=False`, `html.escape`.

---

## 7. Error-Handling, Sackgassen & Recovery (Domäne 7)

- **S-7.1** Keine unbehandelten Exceptions; keine stillen `except: pass` (historisch 407 im Produktivkern durch risikogestuftes Logging ersetzt); kein `AttributeError`-500 durch Dict/Modell-Mix.
- **S-7.2** Keine Endlosschleifen: Loop-Guards resetten beim Re-Lifespan, Retry-Caps, Deadlock-Watchdog, Replan-Cap, `replan_count`, inconclusive → `sufficient=False` (Research).
- **S-7.3** Keine Zombie-Prozesse: Sandbox-`_terminate_container()` verifiziert Entfernung, räumt generischen Fehlerpfad auf; keine Checkpoint-Verluste (nur erfolgreich gesicherte Tasks aus Registry entfernt).
- **S-7.4** Fallback-Strategien: definierte Provider-Kette mit Deadline, keine Sackgassen bei `blocked`/`failed`; fehlgeschlagene Verifikation → Eskalation statt Erfolg; HITL-Auflösung von `blocked` (override/retry/abort).
- **S-7.5** Fail-Closed-Default bei allen Governance-/Auth-/Egress-/Lease-/Taint-Pfaden; Opt-in-Fail-Open nur explizit dokumentiert.

---

## 8. Performance, Concurrency & Engpässe (Domäne 8)

- **S-8.1** Kein blockierendes I/O im Event-Loop: `asyncio.to_thread`, `run_io_bound(ThreadPoolExecutor(max_workers=4))`, bounded backpressure; kein 50-ms-Block, keine 300-s-Slot-Blockade.
- **S-8.2** Keine Race Conditions: `_MC_DATA_LOCK` + `BEGIN IMMEDIATE`, `WeakKeyDictionary` statt `id(loop)`, Single-Flight-Locks für Caches/Preise/Skill-Index, atomare Disk-Caches (Temp+fsync+`os.replace`), CAS für Outbox/Reconciliation.
- **S-8.3** HTTP-Client-Pools statt Loop-Keyed Clients; `close_dispatcher_clients()` als Shutdown-Hook → keine FD-/Memory-Leaks bei Reloads.
- **S-8.4** Budget-Schema-Init einmal pro DB-Pfad (nicht 5–8×/Dispatch), Indizes/WAL/Cache-Tuning, gezielte Punkt-Abfragen statt ganzem State, Trimming von Caches/Registries.
- **S-8.5** Token-Overhead: 3-Tier-SOUL, Framework-Instruktion 1×, keine doppelten SSE-EventSources (ein `archon:sse`-Bus), kein 30-s-Polling.

---

## 9. Architektur- & Code-Standards (2026) (Domäne 9)

- **S-9.1** Python 3.13 durchgängig (Dockerfile/backend), Node 22 (Frontend/CI), Images mit `@sha256:`-Digest gepinnt; `requirements.lock.txt`, `package-lock.json`; keine EOL-Versionen.
- **S-9.2** Pydantic v2, Type-Safety (mypy/ruff als `quality-warn-only` mit gepinnter Version), keine `.dict()`-Reste, keine rohen Body-Dicts.
- **S-9.3** Modularität: `archon/routers/*`, `backend/*`, Dienste statt God-Object; bewusst akzeptiert: `main.py` ~2,5k Zeilen, 11k-Telegram-Adapter (ACCEPTED, nicht neu verhandeln).
- **S-9.4** Keine veralteten Anti-Patterns, keine Duplikat-Runner (archiviert), keine unverdrahteten Standalone-Stubs; SSOT-Dokumentation konsistent (kein Drift bei DB-Pfaden/Version/Phasen).
- **S-9.5** CI-Gates: `compileall` hart, `node --check` auf `scripts/*.js`, `pytest tests/ -q` (Ziel 1775 passed/16 skipped), `docker compose config` (main/all/dev), `yaml.safe_load`(), Restore-Test 5/5; SAST/SBOM/SLot Check wo möglich.
- **S-9.6** Frontend-Build `npm ci && npx tsc --noEmit && npm run build` (lokal node_modules fehlt → CI-Gate); `escapeErpHtml`/`safeMd`, XSS-Escaping, WCAG-Fokus-Ringe, Modal-Focus-Trap.

---

## 10. Funktionale Erhebung & 24/7-Resilienz (Domäne 10)

- **S-10.1** Healthchecks: `/health`, `/livez`, `/readyz` mit 503 bei Unready; Startup `_assert_router_health` wirft wirklich (Lifespan re-raist); `/metrics` echte Werte (Disk via `shutil.disk_usage().used/total*100`).
- **S-10.2** Watchdog 30 s in eigenem Thread, Kernel调度 Tickless Sleep, OTel/Langfuse Tracing, zentrale Logs (Loki/Promtail), Prometheus/Grafana + Alertmanager (Telegram-Receiver, 8 Regeln, Disk-Alarm <2 GiB / >90 %).
- **S-10.3** Self-Healing verdrahtet: `_fleet_self_healing_loop()` (120 s, `_exclusive_loop`, shutdown-tracked) → `check_fleet_and_heal()` (nur existierende Container, `unhealthy` trotz Up erkannt); externer Dead-Man-Switch bewusst ACCEPTED.
- **S-10.4** Graceful Shutdown: Lifespan-Hooks via `asyncio.to_thread()`, `gather` mit 10-s-Timeout, Loop-Guards-Reset, Hintergrund-Tasks shutdown-tracked (`_spawn_background`).
- **S-10.5** Crash-Recovery: Auto-Recovery 6 h, Restore-Tests, Backup-Artefakte, Break-Glass (`data/security/`, 0600), Read-Only-Mount + rw-Settings (`_write_atomic()` mount-fähig).
- **S-10.6** Observability-Profile opt-in (`ARCHON_OBSERVABILITY=full` → monitoring/logging/replication); Standard-Dev schlank; kein Offsite/S3 (nicht gewünscht).
- **S-10.7** Demo-/Produktionsmodus klar getrennt: `ARCHON_DEMO_MODE` read-only ASGI guard, zero token egress; Production `read_only: true`, `cap_drop: [ALL]`.

---

## Annex: Bewusst akzeptierte Risiken (NICHT als Befund melden, unless regression)

- Kein externer Dead-Man-Switch-Empfänger im Default-Stack (ACCEPTED).
- Provider-Breaker prozess-lokal (Single-Instance akzeptiert).
- Alertmanager `null`-Receiver/Telegram-429 (externe Drosselung, keine Konfigurationsursache).
- `main.py` ~2,5k Zeilen / 11k-Telegram-Adapter (ACCEPTED).
- Kein node_exporter (Disk-Metrik aus `shutil.disk_usage`).
- H5-Empfänger-Workflow war `active:false` — bei Re-Audit Status prüfen.
- 39 legitime Drift-Treffer in Doku (Mandanten-DB-Namen/Historie) sind keine aktiven Funde.

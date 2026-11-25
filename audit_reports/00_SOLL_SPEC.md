# 00 — SOLL-SPEZIFIKATION (Archon OS V5.0 SYSTEM-AUDIT)

> **Phase 0 — Sollzustand-Extraktion.** Diese Datei wurde **ausschließlich** aus der
> Systemdokumentation erstellt (READMEs, `SECURITY.md`, Architektur-Specs, ADR-/Guide-Dateien,
> Audit-Abschlussberichte). Es wurde **kein Implementierungscode** gelesen.
>
> Quellen (verbindlich): `README.md`, `README.de.md`, `SECURITY.md`, `INSTALL_AGENT.md`,
> `docs/SYSTEM_HANDBUCH.md`, `docs/ARCHITECTURE_N8N_VS_AGENT_ROUTING.md`,
> `docs/AUDIT_FINDINGS_REGISTER.md`, `docs/system/ARCHON_ERP_ARCHITECTURE_SPEC.md`,
> `docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md`,
> `docs/system/SYSTEM_AUDIT_2026_KONSOLIDIERT.md`, `docs/system/AUDIT_ABSCHLUSS_2026_11_23.md`,
> `docs/system/WIRING_AUDIT_2026.md`, `docs/system/NEVER_DO_LIST.md`,
> `docs/system/ORCHESTRATION_GOVERNANCE_V2_GUIDE.md`, `docs/system/APPROVAL_POLICIES_GUIDE.md`,
> `docs/system/CHAOS_RESILIENCE_GUIDE.md`, `docs/system/EVENT_BUS_GOVERNANCE_GUIDE.md`,
> `docs/system/ENTERPRISE_FEATURES_2026_GUIDE.md`, `docs/security/*.md`,
> `docs/system/ROADMAP_2026.md`.
>
> **Vorrang-Regel:** `NEVER_DO_LIST.md` hat Vorrang vor allen anderen Dokumenten.
> Bei Widersprüchen gilt die neueste datierte Quelle; die Versionsbasis ist
> `v0.5.7.8` / `config/version.json` (PDF-Manuale hinken bei `v0.5.2.1` hinterher).

---

## 0. Leitkriterium: „100 % korrekt verdrahtet" (aus `WIRING_AUDIT_2026.md`)

Eine Mechanik gilt **nur dann als wirksam**, wenn alle vier Glieder im **Produktivpfad** nachweisbar sind:

1. **Produzent** – erzeugt Zustand / Event / Artefakt.
2. **Konsument** – liest es im echten Ablauf (nicht nur in Tests, nicht nur manuell per Endpoint).
3. **Effekt** – sichtbare/nachweisbare Wirkung (DB-Status, Datei, Webhook, Audit-Event).
4. **Verifikation** – Test oder Metrik, die Scheitern sichtbar macht.

Fehlt ein Glied → „Theater" / verdrahteter Schein → Befund. Analoge Prüffelder:
Gates blockieren Freigabe (nicht nur Score); Outbox/DLQ mit echtem Drainer (CAS + Retry + Dead-Letter);
Cancel-Token nach jedem `await` geprüft + Status `cancelled` persistiert; `synthesis_started`
mit Timestamp + Watchdog rücksetzbar; Tool-Output-Firewall im echten Chokepoint; Secret-Masking
vor **jedem** externen LLM-Dispatch; Egress-Firewall auch für als „lokal" klassifizierte Zonen;
Tenant-Scope in Cache/Idempotency/Ledger/GDPR-Löschung; Audit-Schreibfehler nie verschluckt;
UI-Controls mit echtem Handler + existierendem Ziel-Endpunkt; SSE hört auf echte Events;
Status-Maps vollständig (inkl. `queued`/`awaiting_gate`/`cancelled`/`paused`).

---

## 1. Funktionale Soll-Anforderungen

### 1.1 Kernkette (Task → Workflow → Agent → Gate → Artefakt)
- Zentrale Steuerung: FastAPI auf `:8501` (`main.py` + `archon/routers/*`), SPA/Next.js-Cockpit.
- 71 Agentenprofile in `agent_profiles.json` / `roles.json` / `.hermes/profiles/`, 8 Domänen,
  dreistufige `SOUL.md` (Compact / Pro / Full), 832 Prompt-Templates, 55 Boardroom-Frameworks.
- Delegation über `archon/core/delegation.py`; Parent/Child via `task_links` + `project_id` in `ops.db`.
- Fan-in-Synchronisation: Synthese startet automatisch, wenn alle Kinder `completed`/`done`
  (Sperrschutz `_MC_ASYNC_LOCK` + `_MC_DATA_LOCK`).
- Konsens-Auflösung via `resolve_debate_consensus()`; Finalisierung über HITL-Gate-Kaskade.
- **Hartes Budget**: `role_budget_policies` + `role_daily_budget_ledger`, Tages-/Monatslimit in
  Tokens und EUR; Überschreitung → Rolle `paused_budget`. 15 % Reserve für Triage/Synthese,
  85 % komplexitätsgewichtet (`complexity_weight` 0.7–2.0) auf Subagenten.
- Autonomes CEO-Hiring nur explizit freigeschaltet (`allow_autonomous_hiring`), temporäre
  `hired_<slug>_<hash>`-Profile mit eigenem Teilbudget, Auflösung nach Projektabschluss.

### 1.2 Deterministisch vs. probabilistisch (`ARCHITECTURE_N8N_VS_AGENT_ROUTING.md`)
- Grundregel: **„Deterministisch vor Probabilistisch"**. Kein LLM für Aufgabe mit fester
  Ein-/Ausgabe-Logik. Klassifikation via `backend/execution_routing_guard.py`
  (`classify_execution_layer`).
- Routing-Matrix: E-Mail-Polling/CRM-Abgleich, RSS/News-Scans, Telegram→CRM, Finanzmathematik/
  USt-Split/Backups = `deterministic_n8n` / `deterministic_script` = **0 Tokens**;
  Publishing (nach Freigabe) = n8n + HITL; Content/Boardroom/Strategie = budgetierte Agenten.
- Endpunkte: `GET /api/operations/routing/matrix`, `POST /api/operations/routing/classify`,
  `GET|POST /api/operations/org/budgets`, `POST /api/operations/tasks/{id}/allocate-budget`.

### 1.3 Persistenz & Datenbanken
- SQLite WAL als Single Source of Truth; Konsolidierung **28 → 3** domänenisolierte DBs:
  `data/ops.db` (Steuerung/Workflows/Security), `data/business.db` (ERP/CRM/Verträge/Treasury/
  Content), `data/memory.db` (Agentengedächtnis/Sessions). `busy_timeout=5000`,
  Kollisions-Präfixe `<legacy_stem>__<table>`, Pre-Consolidation-Backups, transparenter
  Pfad-Adapter `resolve_db()` + `TenantContextManager.resolve_active_db()` + `DBBackupManager`.
- **Mandanten-Isolation (M43)**: pro `company_id` fünf physisch getrennte WAL-DBs unter
  `data/tenants/{company_id}/`: `erp.db`, `kanban.db`, `crm.db`, `contracts.db`, `deals.db`.
  Keine Vermischung personenbezogener Daten/Belege zwischen Rechtseinheiten. Atomare
  Nummernkreise: Debitoren ab 10001, Kreditoren ab 70001, Artikel `ART-1001`,
  `ANG|AB|RE-{YYYY}-{0001}`.
- Obsidian-Vault als Second Brain (`01_PROJEKTE`, `02_Research`, HR-Personalakten), atomare
  Sidecars (`kanban_sidecar.py`), Litestream-WAL-Replikation (5–10 s), Restore-Tests.
- PocketBase auf `:8090` optionaler Laptop-CRM-Sync (in Archon standardmäßig deaktiviert,
  `POCKETBASE_ENABLED=false`); Sync gleicht nur Netzwerk-/Kommunikationsdaten ab,
  überschreibt **nie** kaufmännische ERP-Felder.
- ERP-Schema: `crm_entities`, `crm_contacts`, `crm_interactions`, `erp_items`,
  `erp_documents`, `erp_document_lines` mit GoBD-unveränderlichem `recipient_snapshot_json`,
  Statusmodell `draft→approved→booked/sent→paid|cancelled`, `external_msg_id UNIQUE`
  (Duplikatsschutz), `pocketbase_id UNIQUE`.
- GoBD: `booked`/`paid` → `draft` ist gesperrt; Art. 15 paginierter Export, Art. 17
  case-insensitive Schwärzung inkl. `memory.db` (kein stiller Fallback).

### 1.4 Integrationen
- OmniRoute `:20128` (OpenAI/Anthropic/Gemini/Groq/DeepSeek + lokale Ollama/LM Studio),
  Cost-Estimator vor Dispatch, Budget-Attribution.
- n8n `:5678` als Event-Trigger-/Automatisierungsschicht; Webhook `/webhook/archon-execution`.
- Event-Bus (M105, `backend/workflow_scheduler.py`) mit Trigger-Matrix
  (Quelle × Ziel-Domäne: `allow` | `require_hitl` | `deny`), `max_per_min`-Rate-Limit +
  Circuit-Breaker, `correlation_id`-Dedup + 14-Tage-Retention, Dead-Letter + Replay.
  Standard: `watchdog→treasury/system` = deny; `inbox/calendar→treasury` = require_hitl.
- Idempotency-Keys + Outbox mit Retry/DLQ für Events, Webhooks, Scheduler; Dead-Outbox → DLQ;
  Replay echt (kein Fake-Success), `next_try_at`-Backoff.
- MCP-Server `/mcp` (M48): Streamable HTTP/SSE, scoped Keys
  (`read_only`|`kanban_rw`|`agent_execute`|`admin_full`), HITL-Gate für
  `archon__trigger_boardroom_debate` / `archon__ask_specialist`.

---

## 2. Sicherheits-Soll-Anforderungen (Zero-Trust / Governance)

### 2.1 Netzwerk & Container
- Localhost-First: Bind `127.0.0.1:8501` default; `ARCHON_BIND_IP=0.0.0.0` nur mit
  `auth.enabled=true`. Aktuell: `settings.json` hat **keinen `auth`-Block** → bewusster
  Single-User-Localhost-Modus, **nicht** für LAN/Produktion. `_must_force_auth()` erzwingt
  Auth bei Non-Loopback-Bind.
- Zero-Trust Docker Socket Proxy über isoliertes `archon-admin_net` (Allowlist), nie roher
  `/var/run/docker.sock`-Mount in Produktion.
- Worker/Sandbox-Netze `archon-worker-zero-egress_net` / `archon-sandbox_net` mit
  `internal: true` / `--network none`, kein Default-Gateway, kein NAT; Fail-Closed-Prüfung
  vor jedem Container-Launch.
- Non-Root UID 1000, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`.
- Read-Only-Demo (`ARCHON_DEMO_MODE=true`): ASGI-Middleware blockt alle Mutationen,
  Shell/Sandbox, Container-Aktionen und externen LLM-Egress.

### 2.2 Auth, RBAC, Secrets
- 3-Tier-RBAC (`admin` | `operator` | `viewer`), PBKDF2-HMAC-SHA256-Sessions,
  Token-Bucket-Rate-Limited scoped API-Keys.
- Alle schreibenden Admin-Routen RBAC-geschützt; Fail-Closed `require_admin_or_503`
  (keine Fail-Open-`_require_admin`-Fallbacks). Kein Body-Actor in Freigabe-/Versandpfaden
  (`require_session_actor`), Vier-Augen-Prinzip nicht fälschbar.
- Echte FIDO2/WebAuthn-Signaturprüfung (ES256/RS256, `rpIdHash`, `signCount`-Replay-Schutz);
  Passkey-Proof zwingend an `action` + `resource` gebunden.
- API-Keys in Runtime-Env / Credential-Vault `.env` (0600), nie im Code; Missing-Key →
  harter Fehler (fail-closed), kein Platzhalter-Fallback. Windows: echtes `icacls`-Härten
  + DACL-Verifikation (`secret_files.py`).
- Secrets-Gate `audit_secrets.py --all`: 0 Funde als hartes CI-Gate.

### 2.3 Egress, Prompt-Injection, Taint
- Zero-Egress-Gate + Privacy-Router: sensible Kategorien (`finance`, `contracts`, `crm`, `hr`,
  `gdpr`) **nur** zu verifizierten `LOCAL_ON_PREM`-Endpunkten; harter Fail-Closed-Block
  (`LOCAL_LLM_OFFLINE_HARD_BLOCK`) bei offline lokalem Modell. `zero_egress_strict`
  weitet Lock systemweit aus. `explicit_category` darf Klassifikation **nicht** abschwächen;
  Klassifikationsfehler → fail-closed `confidential`.
- Egress-Firewall `enforce_egress_firewall_for_url()` + `sanitize_outbound_llm_payload()`
  (secret_masker + pii_scrubber) vor **jedem** externen Dispatch, auch für „lokale" Zonen.
- Dual-LLM-Quarantine-Sanitizer (`backend/dual_llm_sanitizer.py`), 25 Prompt-Injection-Muster
  (`local_security_guard.py`), 8 standardisierte Angriffs-Szenarien (`injection_range.py`).
- Information-Flow-Taint-Tracking (M89): nach untrusted Content werden kritische Ausgänge
  (`send_email`, `pay`, `pay-cli`, `git_push`, `deploy`, `memory_write`, `execute_shell`,
  `webhook_post`, `telegram_send`, `terminal`, `execute_code`, `computer_use`, `mcp__*`,
  `node_plugin:*`, unbekannte Tools) über HITL geparkt. Default-Deny; nur explizit harmlose
  Tools (`read_file`, `web_search`, …) ausgenommen. Einmal-Tokens (`ta-...`) werden verbraucht
  (`consumed=1`), CAS-UPDATE `AND consumed=0`.
- Sandbox: `python -I`, `TemporaryDirectory`, ohne Host-Env-Secrets, POSIX-`rlimit`,
  AST-Sperre gefährlicher Module (`os`, `subprocess`, `socket`, `ctypes`, `urllib`), SSRF-Schutz
  (`check_public_url`) für `visual_web_agent.py`.

### 2.4 HITL, Approvals, Warrants
- Vier-Augen-Prinzip ab 500 €, Auto-Freigabe bis 50 €, 24 h Eskalationsfrist;
  Kommunikation: Freigabepflicht für KI-Antwortentwürfe, 12 h, Domain-Whitelist.
- Jede Regel-/Statusänderung append-only in `approval_policy_audit_chain` SHA-256-Hashkette.
- Signierte Tool-Warrants (M90): HMAC-SHA256, Ablaufzeit, Parameter-Constraints
  (`max_amount`, `allowed_path_prefixes`); **alle** Pfad-Aliase (`file_path`, `uri`, `target`,
  …) gegen Prefixes prüfen; fehlendes Pfad-Argument bei Pfad-Constraint → deny.
  Pflicht für `pay` / `mcp__*`.
- Kanban-Verifier (M76/M81): Token-Budget, Ergebnis-Integrität, `proof_command` (Exit 0);
  Retry einmal, dann `blocked` (`budget_exceeded_hitl`/`proof_failed_hitl`) → Mensch
  (`override_budget`|`retry`|`abort`). Cross-Modell-Verifier anderer Modellfamilie,
  `detect_deleted_test_assertions()` blockt entfernte Test-Assertions.
- Präzedenzfälle (M91) strikt isoliert pro `(tenant_id, project_id)`, kein Mandanten-Transfer.

### 2.5 Audit-Trail & Kryptografie
- Lückenlose HMAC-SHA256-Hashkette (Env-Key `ARCHON_AUDIT_HMAC_KEY`) in `backend/audit_log.py`:
  `hash = HMAC_SHA256(env_key, prev_hash + timestamp + payload)`, Spalten-zu-Payload-
  Tamper-Verifikation. Jeder LLM-Dispatch (ausgeführt **und** blockiert) atomar mit
  `category="llm_dispatch"`, `provider`, `model`, `target_endpoint`, `target_host`,
  `egress_zone`.
- Bei Manipulation/Key-Fehler → **fail-fast im Lifespan**, Produktion startet nicht.
  Audit-Schreibfehler blockieren Tool-Calls (nie verschlucken). Verankerung mit externem
  Anker + Startup-Key-Check; Anker default-aktiv in Produktion; `verify_integrity()`
  vergleicht letzten Anker-Hash mit Ketten-Head (Tail-Löschung erkannt).
- Execution-Receipt-Kette: HMAC-SHA256 mit **eigenem** Env-Key + Domain-Prefix (nicht Audit-Key),
  Append-only-Trigger gegen UPDATE/DELETE, `hmac_protected` im Verify-Result,
  `verify_chain_integrity()` prüft alle SHA-256-Zeilenhashes.
- Break-Glass-Notfallkey unter `data/security/`, Modus 600, getrennt vom verschlüsselten
  Vault und HMAC-Key; Zip-Slip-Pfad-Jail + WAL-Sidecar-Entfernung beim Restore.

### 2.6 Mandanten- & Rollen-Grenzen
- Tenant-Scope in **allen** Caches, Idempotency, Ledger, Taint-Guard, Egress-Log, PII-Vault,
  Offline-Vault (DB+Key+AAD), GDPR-Löschung; kein globaler Vault/Key.
- EU AI Act: Default-Deny + zentrale Alias-Auflösung für unbekannte Agenten; Klassifizierung
  HIGH_RISK (Anh. III 4/5), SPECIFIC_TRANSPARENCY (Art. 50), MINIMAL_RISK (Art. 95) mit
  `SOUL.md`-SHA-256-Hash; Art.-4-Kompetenzregister revisionssicher.

---

## 3. Resilienz-, Observability- & 24/7-Soll-Anforderungen

- **Liveness/Readiness**: echter async Event-Loop-Heartbeat in `/livez` (503 bei Stall),
  `/readyz` mit 503, Docker-Healthcheck verdrahtet; `ARCHON_HEARTBEAT_WEBHOOK_URL`
  (Dead-Man-Switch). Startup `_assert_router_health` wirft wirklich (Lifespan re-raist),
  Loop-Guards resetten beim Re-Lifespan, Shutdown-`gather` mit 10 s Timeout.
- **Watchdog**: eigener Thread, 30-s-Intervall, Alarmprotokoll `archon_alarms.json` beschreibbar.
- **Recovery**: Auto-Crash-Recovery (6 h), Worker-Leases/Heartbeats mit Liveness-Check,
  CAS-Claim fail-closed + Lease-Guard bricht DAG bei Token-Verlust hart ab; `CancelledError`
  explizit gefangen → Nodes `cancelled`, Run-Status `cancelled` persistiert; relevante
  Payload-Operatoren via `asyncio.to_thread`, HTTP-Client-Pools, `WeakKeyDictionary`
  statt `id(loop)` + `close_dispatcher_clients()` als Shutdown-Hook (kein FD/Memory-Leak).
- **Chaos-Suite** (`scripts/chaos_tester.py`): SQLite-Concurrency (8 Threads × 50 Tx,
  WAL ohne Lock-Fehler), Container-Health, Restart-Recovery SLA < 15 s, Watchdog-Responsiveness.
- **OTel/Langfuse-Tracing** in LLM-Kernel und DAG; Trace-to-Eval-Replay-Fixtures.
  Gefordert: durchgängige `trace_id`/`span_id`-Propagation über Hermes, OmniRoute, n8n,
  PocketBase (kausale Fehlerketten lückenlos rekonstruierbar).
- Zentrale Logs (Loki/Promtail), Prometheus/Grafana, SSE/WebSocket-Live-Streaming
  (ein gemeinsamer `archon:sse`-Bus, keine doppelten EventSources).

---

## 4. Code-, Architektur- & Reproduzierbarkeits-Standards (2026)

- Python 3.13; Pydantic **v2** Request-Modelle (kein rohes `dict = Body(...)` in Produktions-
  routern, `extra="ignore"`, kein `.dict()`-Rest, Union-Typen statt `Optional` ohne Default);
  strikte Schema-Validierung an **allen** Übergabepunkten (keine unstrukturierten Freitext-
  Handoffs zwischen Orchestrator und Subagenten).
- `requirements.lock.txt` mit Hashes (`--require-hashes`), SBOM, `pip-audit` 0 CVEs,
  `bandit -lll` 0 HIGH, `compileall` Exit 0, CI `security-scan` als hartes Gate (kein
  `continue-on-error`), Image-Digests (`sha256`) + Action-Pins auf Commit-SHA.
- Frontend: `npm ci`, `tsc --noEmit`, `npm run build` (Next.js 16 / React 19) grün;
  Lazy-Iframes, `AbortController`-Debounce, `escapeErpHtml`/`safeMd`/XSS-Escaping,
  `role="dialog"` + Focus-Trap + Escape/Fokus-Rückführung auf Modals, vorkompiliertes
  Tailwind (kein Runtime-JIT-CDN), i18n-Parität über alle 11 Sprachkataloge.
- **Keine** toten Stubs/Theater-Module: Produzent + Konsument + Effekt + Verifikation.
  `TODO`/`FIXME`, Hardcoded Returns, Dummy-Daten, `simulated`-vs-`success` ehrlich markiert.

---

## 5. Verbindliche Negativ-Constraints (NEVER_DO_LIST — Vorrang)

1. **Kein echtes Coroutine-Replay** im Durable Kernel. Akzeptiert: persistierte Node-States
   + Checkpoints. Kein Event-Sourcing/Snapshotting/Replay-Framework, auch nicht als „Folgearbeit".
2. **Keine PostgreSQL-Migration**. SQLite bleibt; Konsolidierung 28 → 3 + physisch isolierte
   Mandanten-DBs ist Endarchitektur. Keine DSN, kein Migrationstool, keine Empfehlung.

Zusätzlich (Produktmodell-Korrektur 23.11.2026): **keine eigene Content-Domäne / kein
`/content-studio`**; Content ist Task → Workflow → Agent → Gate → Artefakt. Backend-Module
bleiben interne Bausteine, keine Produktfläche.

---

## 6. Dokumentierte Risikolandschaft (Soll ↔ behaupteter Ist; zu verifizieren)

Die Audit-Dokumente behaupten若干 Punkte als „behoben", andere als „teilweise offen".
Diese Liste ist **kein Freibrief**, sondern Priorisierungshinweis für die Domänen-Audits:

|_cluster | Dokumentierte Rest-Risiken (Quelle: `SYSTEM_AUDIT_2026_KONSOLIDIERT.md`, `AUDIT_ABSCHLUSS_2026_11_23.md`) |
|---|---|
| Auth/RBAC | Passkey-Bindung teils offen (laut Abschluss behoben — verifizieren); ~136 rohe `dict = Body` in `archon/routers/**`; `extra="allow"`-Reste |
| Tenant | Vault/Taint teils offen (laut Abschluss tenant-scoped — verifizieren); Cache/Idempotency-Scope |
| Orchestrierung | Cancel nach `await`, Lease/Fencing, DLQ-Scheinconsumer, Boardroom-Killswitch (teils offen laut konsolidiertem Audit) |
| Audit/Krypto | HMAC im Break-Glass, Receipt-Kette nacktes SHA-256, verschluckte Audit-Errors, Anker nie verifiziert (teils offen) |
| Persistenz | Restore tenant-Pfad, Backups ohne Keys, konsolidierte DBs nicht gesichert (teils offen) |
| Performance | 50-ms-Event-Loop-Block, 300-s-Slot-Block, DDL pro Budget-Call, Loop-Keyed Clients (teils offen) |
| Doku | PDF-Manuale bei v0.5.2.1, Versionsdrift, „100 % verdrahtet" nur Einschätzung (Frontend-Build lokal nicht verifiziert) |
| Betrieb | `settings.json` ohne `auth`-Block; `zero_egress=false`, `zero_egress_strict=false`; kein LAN/Produktions-Default |

> **Wichtiger Hinweis an alle Subagenten:** Die Doku behauptet einen weitgehend sanierten
> Zustand. Euer Auftrag ist eine **unabhängige, skeptische Verifikation gegen den Code**,
> nicht die Übernahme der Doku-Behauptungen. Jeder Befund braucht Dateipfad:Zeile + technischen
> Nachweis. Vertraut der Doku nur als Soll-Definition, nie als Ist-Nachweis.

---

## 7. Domänen-Referenz (welche Soll-Abschnitte für welche Domäne)

| Domäne | Relevante Soll-Abschnitte |
|---|---|
| 01 Stub-Detection/Wiring | §0 (Vier-Glieder-Kriterium), §1.1, §1.4, §4 (keine toten Stubs) |
| 02 Orchestrierung/Routing | §1.1–1.2, §3 (Cancel/Lease), §6 |
| 03 Persistenz/Vault | §1.3, §2.6, §6 |
| 04 Governance/Security | §2.1–2.2, §2.3, §2.4, §2.6, §5 |
| 05 Audit-Trail/Krypto | §2.5, §3 (OTel), §6 |
| 06 Integrationen/Webhooks | §1.4, §2.3 (SSRF/Egress), §6 |
| 07 Error/Recovery | §3, §0 (Audit-Fehler nicht schlucken), §6 |
| 08 Performance/Concurrency | §3, §1.3 (WAL/Locks), §6 |
| 09 Architektur/Standards | §4, §5 |
| 10 System-Härtung/24-7 | §3, §2.1 |
| 11 Context Drift/Handoff | §1.1, §4 (Pydantic-Schema an Übergaben) |
| 12 Silent Failures/Hallucination | §0, §2.3, §2.5, §4 (kein Platzhalter-Fallback) |
| 13 Trajectory/Loop-Prevention | §1.1 (MAX_DELEGATION_DEPTH=3, MAX_FANOUT=5), §2.4 (Budget), §1.4 (Loop-Dedup) |
| 14 Entscheidungs-Hoheit | §1.1 (Konsens/HITL), §2.4 (Vier-Augen, Warrants), §2.6 |
| 15 Rollen-/Prompt-Trennschärfe | §1.1 (71 Profile/3-Tier SOUL), §2.6 (EU AI Act Guardrails), §5 |
| 16 Distributed Tracing | §3 (OTel `trace_id`/`span_id` über alle Grenzen), §2.5 (Audit-Kette) |

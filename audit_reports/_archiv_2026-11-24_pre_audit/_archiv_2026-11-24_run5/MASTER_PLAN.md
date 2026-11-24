# Archon OS — MASTER PLAN (Phase 2: Konsolidierung & Architektur-Bewertung)

> **Eingang:** `audit_reports/00_SOLL_SPEC.md` + `domain_01.md` … `domain_10.md` (10 parallele Tiefenaudits).
> **Stand:** 24.11.2026 · **Basis:** HEAD `9631405c`, sauberer Working Tree.
> **Ziel (Phase 3):** Alle `BLOCKER`- und `HIGH`-Funde behoben, verifiziert und in `FINAL_VERIFICATION.md` dokumentiert. Jeder „verdrahtete Schein" durch echte Implementierung ersetzt.

---

## 1. Konsolidierte Befundmatrix

| Domäne | BLOCKER | HIGH | MED | Gesamt | Schwerpunkt |
|---|---:|---:|---:|---:|---|
| 01 Stub-Detection | 0 | 2 | 6 | 8 | PbSettingsModal Fake-Save/Test/Export, `suspend_task` tot, `subagents_count` Dummy, SSE-Geist-Event |
| 02 Orchestrierung | 0 | 2 | 2 | 4 | Deterministisches Routing nur klassifiziert, Monatsbudget ohne Cap, Fencing/Cancel im Kanban-Worker tot |
| 03 Persistenz | 0 | 2 | 4 | 6 | Tenant-Legacy-Kopie ohne Primär-Guard, FK-Check fehlt vor Restore-`os.replace()`, Snapshot-Restore nicht atomar |
| 04 Governance | 0 | 4 | 3 | 7 | Statischer OCR-Token, AST-Sandbox-Sperre fehlt, OCR/Voice ohne Egress+DLP, Chat-Sanitizer fail-open |
| 05 Audit/Krypto | 0 | 1 | 7 | 8 | Treasury-Kette bricht bei HMAC-Rotation, Plain-SHA-256 für Neublöcke, `egress_zone` nicht verifiziert |
| 06 Integrationen | 0 | 0 | 5 | 5 | Rohe Dict-Bodies, `.dict()`, n8n-Dreiquellen, nicht-kompakter HMAC-Body, Chat-Sanitizer fail-open |
| 07 Error/Recovery | 0 | 4 | 11 | 15 | Erfolgssignale in Fehlerpfaden, Compliance fail-open, Watchdog-NameError, Zombie/DB-Leaks, stille `except pass` |
| 08 Performance | 0 | 3 | 5 | 8 | `id(loop)`-Clients ohne Shutdown, sync SQLite im Event-Loop (Kanban + Token-Guard), ungesperrte Caches, 2. EventSource |
| 09 Standards | 0 | 1 | 9 | 10 | Backend-Image ohne Hash-Lock, Basisimages unpinned, `npm ci || npm install`, XSS-Sinks, CI-Restore-Gate fehlt |
| 10 24/7-Resilienz | **1** | 3 | 3 | 7 | **Self-Healing spricht direkten Docker-Socket statt Proxy**, Alertmanager nie gestartet, Langfuse nicht verdrahtet |
| **Summe** | **1** | **22** | **55** | **78** | |

**Deduplikation (3 Doppelmeldungen, sachlich identisch):**
- `F-042` (D7) ≡ `F-074` (D10): Watchdog-`threading`-NameError.
- `F-035` (D6) ≡ `F-066` (D9): `.dict()` in `email_settings.py:57,70`.
- `F-034` (D6) ≡ `F-067` (D9): roher Dict-Body `operations_api.py:1976` (D6 additionally `main.py:2224`, `security_scanner.py`).
- `F-036` (D6) und `F-072` (D10) betreffen dieselbe Datei `fleet_self_healing.py`, aber verschiedene Defekte → gemeinsam in einem Edit-Block.

**Effektiv unique Funde: 75.**

### Vollständiger Fund-Index (ID → Domäne / Kritikalität / Ort / Kurzform)

| ID | D | Krit. | Datei:Zeile | Kurzform |
|---|---|---|---|---|
| F-001 | 1 | HIGH | `frontend/src/components/PbSettingsModal.tsx:95-110,185-190,509-562` | Save-Signalisierung ohne Persistenz |
| F-002 | 1 | HIGH | `PbSettingsModal.tsx:112-129` / `email_settings.py:64-65` | Test-Email ohne Body → 422 |
| F-003 | 1 | MED | `PbSettingsModal.tsx:147-159,674,751-764` | Schema-Export hartcodiert |
| F-004 | 1 | MED | `PbSettingsModal.tsx:685-695` | Schema-Import-Dropzone Dekoration |
| F-005 | 1 | MED | `PbSettingsModal.tsx:55,648` | Log-Reload No-Op |
| F-006 | 1 | MED | `backend/agent_router.py:1062-1066` | `suspend_task()` ohne Aufrufer |
| F-007 | 1 | MED | `archon/routers/chat.py:704`; `orchestration.py:401,781` | `subagents_count` Konstante |
| F-008 | 1 | MED | `static/js/mission_control_cockpit.js:74`; `appshell_architect.js:308` | `task_captured` ohne Producer |
| F-009 | 2 | HIGH | `core_dispatcher.py:1014-1020` | Deterministisches Routing nur Log-Hinweis |
| F-010 | 2 | HIGH | `backend/role_budget_engine.py:377,1130-1140` | Monatslimit nicht erzwungen |
| F-011 | 2 | MED | `backend/operations_api.py:916,929` | Lease-Token tote Variable |
| F-012 | 2 | MED | `backend/operations_api.py:941` | Cancel-Token nur 1× geprüft |
| F-013 | 3 | MED | `backend/db_paths.py:177-186` | `busy_timeout` 15000 statt 5000 |
| F-014 | 3 | HIGH | `backend/tenant_context.py:428-447` | Legacy-Kopie für alle Mandanten → Cross-Tenant |
| F-015 | 3 | HIGH | `backend/db_backup_manager.py:446-455,519` | FK-Check fehlt vor `os.replace()` |
| F-016 | 3 | MED | `data/.memory.db.restore.*.tmp-shm/-wal` | Verwaiste Restore-Sidecars |
| F-017 | 3 | MED | `backend/snapshot_manager.py:170-175` | Snapshot-Restore nicht atomar, kein Pfad-Jail |
| F-018 | 3 | MED | `backend/erp_manager.py:122-135,383-404` ↔ `tenant_context.py:588-596` | Zwei Nummernkreis-Authoritäten |
| F-019 | 4 | HIGH | `backend/receipt_ocr_engine.py:167` | Statischer Token `Bearer internal-archon` |
| F-020 | 4 | HIGH | `backend/self_evolving_tooling.py:91`; `ephemeral_sandbox.py:342-397` | Keine AST-Import-Sperre |
| F-021 | 4 | HIGH | `backend/receipt_ocr_engine.py:154-169` | OCR-Dispatch ohne Egress-Firewall/DLP |
| F-022 | 4 | HIGH | `backend/voice_pipeline.py:81-119` | OpenAI/Gemini/TTS ohne Egress/DLP |
| F-023 | 4 | MED | `utils/notebook_engine.py:472-494` | NotebookLM ohne Egress/DLP |
| F-024 | 4 | MED | `backend/dual_llm_sanitizer.py:28-38` | 9 statt 25 Injection-Muster |
| F-025 | 4 | MED | `backend/delegation_isolation.py:340-378` | Pfad-Aliase `uri`/`target`/`src` fehlen |
| F-026 | 5 | HIGH | `backend/treasury_engine.py:174,229-233` | HMAC-Rotation bricht Treasury-Kette |
| F-027 | 5 | MED | `backend/audit_log.py:120-127,640-649` | Plain-SHA-256 für Neublöcke, Flag kosmetisch |
| F-028 | 5 | MED | `backend/audit_log.py:710-726` | `egress_zone` nicht Pflichtfeld |
| F-029 | 5 | MED | `backend/audit_log.py:140-142,207-218` | Token-Sanitization exakte Matchliste |
| F-030 | 5 | MED | `backend/llm_egress_guard.py:523-527` | DNS-Block ohne Audit-Proof |
| F-031 | 5 | MED | `backend/api_key_manager.py:178-188,257-268` | Audit-Fehler nur DEBUG |
| F-032 | 5 | MED | `backend/execution_receipt_ledger.py:190-196` | Bypass-Lücke unsichtbar |
| F-033 | 5 | MED | `email_draft_engine.py:500-502`; `gdpr_compliance_engine.py:1093-1095` | Verify-Funktionen ohne Produktivkonsument |
| F-034 | 6 | MED | `main.py:2224`; `operations_api.py:1976`; `security_scanner.py:17,39` | Rohe Dict-Bodies |
| F-035 | 6 | MED | `archon/routers/email_settings.py:57,70` | `.dict()`-Reste (= F-066) |
| F-036 | 6 | MED | `backend/fleet_self_healing.py:91` | HMAC-Body nicht kompakt |
| F-037 | 6 | MED | `n8n_routine_workflows.json`; `deploy_n8n_routines.py:153`; `n8n_workflows_bundle.json` | Drei n8n-Quellen |
| F-038 | 6 | MED | `archon/routers/chat.py:646-647` | Sanitizer-Fehler fail-open |
| F-039 | 7 | HIGH | `archon/core/delegation.py:1322,1386-1389,1422-1433` | Fehlgeschlagener INSERT → Erfolgs-Quittung |
| F-040 | 7 | HIGH | `archon/core/orchestration.py:904-921` | Artefakt-Schreibfehler → `completed` |
| F-041 | 7 | HIGH | `backend/agent_router.py:623-634`; `core_dispatcher.py:160-179,1001-1012` | Compliance-Gate fail-open |
| F-042 | 7 | HIGH | `watchdog_daemon.py:314` | `threading`-NameError (= F-074) |
| F-043 | 7 | MED | `main.py:1311-1315` | RAG-Subprocess-Zombie |
| F-044 | 7 | MED | `backend/agent_router.py:1183-1195` | Eskalation nicht reverifiziert |
| F-045 | 7 | MED | `backend/workflow_dag_runner.py:1272` | Non-Dict-Output → `success` |
| F-046 | 7 | MED | `local_memory_bridge.py:923-926,938-941` | Korruptes Checkpoint → `{}` |
| F-047 | 7 | MED | `backend/self_evolving_tooling.py:40-44,51,299,329` | SQLite-Verbindungen nie geschlossen |
| F-048 | 7 | MED | `scripts/archon_crm_mcp.py:99-105` | Stiller `except pass` im Injection-Scan |
| F-049 | 7 | MED | `core_dispatcher.py:1019-1020` | Stiller `except pass` im Dispatch |
| F-050 | 7 | MED | `scripts/garbage_collector.py:23,32` | Nacktes `except: pass` im Löschpfad |
| F-051 | 7 | MED | `scripts/installer_build/build_export.py:78` | Nacktes `except: pass` im Export |
| F-052 | 7 | MED | `backend/ephemeral_sandbox.py:396` | `destroyed: True` ohne Container |
| F-053 | 7 | MED | `backend/operations_api.py:1734-1763` | HITL setzt jeden Task auf `todo` |
| F-054 | 8 | HIGH | `archon/routers/proxies.py:21` | `id(loop)`-HTTP-Client ohne Shutdown |
| F-055 | 8 | HIGH | `backend/operations_api.py:929` | Sync SQLite im Kanban-Event-Loop |
| F-056 | 8 | HIGH | `backend/agent_router.py:66` | Token-Guard blockiert 2 s pro Request |
| F-057 | 8 | MED | `core_dispatcher.py:1132`; `agent_router.py:793,949` | Sync Audit-Schreibtransaktion im Loop |
| F-058 | 8 | MED | `archon/core/orchestration.py:170,216,438,559-591` | Mission-Control-Sync-I/O im Loop |
| F-059 | 8 | MED | `backend/async_write_batcher.py:35`; `concurrency_throttle.py:26,65` | TTL-Caches ohne Lock |
| F-060 | 8 | MED | `archon/routers/operations_org.py:736` | `id(loop)`-Semaphore toter Pfad |
| F-061 | 8 | MED | `static/js/operations_kanban.js:4106` | Zweite EventSource |
| F-062 | 9 | HIGH | `backend/Dockerfile:5-6` | Backend-Image ohne Hash-Lockfile |
| F-063 | 9 | MED | `Dockerfile:1`; `backend/Dockerfile:1`; `frontend/Dockerfile:1` | Basisimages ohne `@sha256:` |
| F-064 | 9 | MED | `frontend/Dockerfile:9` | `npm ci || npm install` |
| F-065 | 9 | MED | `requirements.lock.txt:2` | Lockfile mit Python 3.12 erzeugt |
| F-066 | 9 | MED | `archon/routers/email_settings.py:57,70` | `.dict()` (= F-035) |
| F-067 | 9 | MED | `backend/operations_api.py:1976` | roher Body (= F-034) |
| F-068 | 9 | MED | `frontend/src/app/crm/page.tsx:270` | `dangerouslySetInnerHTML` SVG |
| F-069 | 9 | MED | `frontend/src/components/DesignEditorTab.tsx:827` | `dangerouslySetInnerHTML` SVG |
| F-070 | 9 | MED | `.github/workflows/ci.yml` | Restore-/yaml-Gate fehlt |
| F-071 | 9 | MED | `.github/workflows/pages.yml:28,30,32,36` | Actions unpinned |
| F-072 | 10 | **BLOCKER** | `backend/fleet_self_healing.py:181,242`; `utils/docker_client.py:144-156` | Self-Healing gegen direkten Socket statt Proxy |
| F-073 | 10 | HIGH | `start.bat:25`; `install.sh:271-275` | Alertmanager nie gestartet |
| F-074 | 10 | HIGH | `watchdog_daemon.py:314` | NameError (= F-042) |
| F-075 | 10 | HIGH | `backend/otel_tracer.py:214-248`; `docker-compose.yml:55-98` | Langfuse-Export ohne Keys/Profil |
| F-076 | 10 | MED | `main.py:2640-2667` | Router-Health fail-open in Dev |
| F-077 | 10 | MED | `backend/resource_backpressure.py:108-134`; `main.py:1150-1161` | Disk-Alarm nicht periodisch, Schwellen >85 %/2.0 GB |
| F-078 | 10 | MED | `config/prometheus/alerts.yml:96-97,110-126` | Überholte Kommentare leugnen Disk-Metrik/Receiver |

---

## 2. Reifegrad-Bewertung (Skala 1–10)

| Kriterium | Score | Begründung (mit Befundbezug) |
|---|---:|---|
| **1. Funktionale Vollständigkeit (Echtbetrieb vs. Schein)** | **7** | Der Produktivkern ist überwiegend echt verdrahtet: 73 Profile/3-Tier-SOUL, DAG-Engine mit Fan-Out/Quorum/Fingerprint-Resume, Fan-in-Latch, Effect-Ledger mit CAS, BudgetBank, Zero-Egress in Core/Router/Boardroom/Chat/Container-Ops, Boardroom 4 Phasen, Passkey-HITL, 4-Augen — alle mit Produktivkonsument nachgewiesen (D2/D4/D5 Positivlisten). **Abzüge:** F-072 (Self-Healing läuft, hat aber keinen Effekt — klassisches „Theater" nach G-03), F-001/F-002 (UI-Speichern/Test-Mail reine Scheinerfolge), F-009 (Determinismus nur klassifiziert), F-006 (`suspend_task` defined-but-never-called), F-007 (Dummy-Zahl), F-008 (Geist-Event), F-073 (Alarm ohne Adressat), F-075 (Tracing ohne Export). Ein BLOCKER und 7 HIGH mit direktem Echtbetriebsbezug. |
| **2. Sicherheits-Härtung (Zero-Trust/Governance)** | **7** | Sehr starke Basis: Auth fail-closed inkl. `sys.argv`-Bind-Erkennung, RBAC mit 503-Fallback, Passkey/WebAuthn (ES256/RS256, rpIdHash, signCount, UV, action/resource), Taint-Default-Deny, HMAC-Warrants mit TTL+Pfad-Constraints, zentraler RBAC-Jail in `decide()`, HMAC-Webhooks, Sandbox `python -I`/rlimit, Socket-Proxy-Allowlist, DSGVO/AI-Act/GoBD. **Abzüge:** F-019 statischer Token im OCR-Pfad (K3-Klasse), F-020 keine AST-Sperre in genau der Sandbox, die synthetisierten Code ausführt, F-021/F-022 drei Dispatch-Pfade ohne Egress/DLP, F-038 Chat-Sanitizer fail-open, F-024 nur 9 statt 25 Muster, F-025 unvollständige Pfad-Aliase. Die Härtung ist breit, aber an den Rändern durchlässig. |
| **3. Fehlertoleranz & Recovery** | **6** | Loop-Guards, Replan-Cap, `sufficient=False`, Lease/Fencing im DAG-Pfad, Container-Cleanup-Verifikation, Restore-Lock mit Rollback, Self-Healing-Loop, Graceful Shutdown, 6-h-Crash-Recovery vorhanden. **Abzüge (schwer):** F-039/F-040 melden fehlgeschlagene Insertions/Artefaktwrites als Erfolg, F-041 Compliance-Gate fail-open an 3 Stellen, F-042 Watchdog-Stop defekt (Thread nicht joinbar, Fehler verschluckt), F-043 Zombie-Prozess, F-044 Eskalation ohne Reverifikation, F-045 Non-Dict → `success`, F-046 Checkpoint-Korruption still `{}`, F-047 FD-Leak, F-048–F-051 vier stille Exception-Swallower, F-053 HITL-Sackgasse. Hier liegt die größte Dichte an Echtfehlern (15 Funde, 4 HIGH). |
| **4. Daten- & Audit-Integrität** | **7** | Zentralkette mit HMAC-Env-Key, Epochen, Append-only-Trigger, präfix-toleranter Anker, Spalten-/Payload-Konsistenz, Export/Verify; alle 7 Ketten haben Verifikatoren; 28→3-Konsolidierung, physische Mandantentrennung, GoBD-Sperren, tenant-scoped Vault/Taint/Cache. **Abzüge:** F-014 Cross-Tenant-Legacy-Kopie (echte Datenvermischung im Bestand belegt), F-015 kein FK-Check vor Restore-`os.replace()`, F-026 Treasury-Kette bricht bei Key-Rotation, F-027 Plain-SHA-256 für Neublöcke + kosmetisches Enforcement-Flag, F-028 `egress_zone` nicht verifiziert, F-029 Token-Leak im signierten Endpoint, F-032 Bypass-Lücke unsichtbar, F-033 zwei Verifikatoren ohne Konsument, F-017 nicht-atomarer Snapshot-Restore, F-018 doppelte Nummernkreise. |
| **5. Code- & Architekturqualität** | **7** | Python 3.13/Node 22 konsistent, alle 22 Compose-Images digest-gepinnt, CI-Actions in `ci.yml` per SHA, `compileall`/`node --check`/pytest/compose-config harte Gates, Pydantic-v2-Basismodelle, Modularisierung (`provider_registry`, `import main`-Shims reduziert), 1775 passing Tests, XSS-Escaping/WCAG/Focus-Trap weitgehend. **Abzüge:** F-062 Backend-Image ohne Hash-Lock (Reproduzierbarkeitslücke), F-063–F-065 Drift bei Basisimages/`npm ci`/Lockfile-Metadaten, F-035/F-066 `.dict()`, F-034 rohe Bodies, F-068/F-069 zwei XSS-Sinks, F-070 Restore-/yaml-Gate nur manuell, F-071 `pages.yml` unpinned, F-054 `id(loop)`-Regression, F-055/F-056 blockierendes I/O, F-059/F-060 Cache-/Semaphore-Races. |
| **Gesamt** | **7 / 10** | **Begründung:** Ein produktionsfähiges, architektonisch durchdachtes und weitgehend echt verdrahtetes System mit starker Governance- und Audit-Basis — aber noch nicht im behaupteten 24/7-Zustand. Ein BLOCKER (Self-Healing ohne Effekt) und 22 HIGH-Funde, davon mehrere mit stillen Erfolgssignalen in Fehlerpfaden und Sicherheitslücken an Integrationsrändern, sind mit „100 % determiniert, gehärtet" unvereinbar. Nach Abarbeitung der Wellen 0–3 (alle BLOCKER/HIGH) ist eine Bewertung von **9/10** realistisch; die verbleibenden MED/Restrisiken (u. a. bewusst akzeptierte Punkte) verhindern eine 10. |

---

## 3. Abhängigkeits-Matrix (konfliktfreie Ausführungsreihenfolge)

**Sortierprinzip:** Fundament/Datenbank → Security/Krypto → Orchestrierung/Concurrency → Integrationen/UI → Standards/CI → Verifikation. Innerhalb einer Welle werden Dateien, die von mehreren Funden betroffen sind, **in einem einzigen Edit-Block** bearbeitet (keine parallelen Schreibzugriffe auf dieselbe Datei).

### Welle 0 — Fundament & Daten-Integrität (BLOCKER + Daten-HIGH)
| IDs | Dateien (Edit-Blöcke) | Maßnahme | Grund der Vorziehung |
|---|---|---|---|
| **F-072 + F-036** | `backend/fleet_self_healing.py`, `utils/docker_client.py` | Self-Healing auf `DOCKER_HOST`-Proxy umstellen (`docker_client.restart_container`), `returncode` prüfen, kompakte HMAC-Serialisierung | **Einziger BLOCKER**; kein anderes Modul darf vor dem Fundament gehärtet werden |
| F-014 + F-018 | `backend/tenant_context.py`, `backend/erp_manager.py` | Primär-Mandanten-Guard im Legacy-Copy-Pfad; eine Nummernkreis-Authority | Datenvermischung ist irreversibel — vor allen Code-Änderungen |
| F-015 + F-016 | `backend/db_backup_manager.py`, `data/`-Sidecars | `PRAGMA foreign_key_check` vor `os.replace()`, Rollback, Sidecar-Cleanup im `finally` | Restore ist letzte Verteidigungslinie |
| F-026 | `backend/treasury_engine.py` | `block_id` in Signatur + Verify, Legacy-Fallback, Rotationstest | Krypto-Fundament für alle Epochen |
| F-062 | `backend/Dockerfile` | Lockfile-basierter hash-geprüfter Install | Reproduzierbarkeit vor jeder Laufzeitverifikation |

**Gate W0:** `py_compile` aller geänderten `.py`; gezielter Self-Healing-Sim (Container `unhealthy` → `healed_count > 0`); `restore_backup()` mit manipuliertem FK-Backup lehnt ab; Treasury-Rotationstest grün.

### Welle 1 — Security, Governance & Audit (HIGH)
| IDs | Dateien (Edit-Blöcke) | Maßnahme |
|---|---|---|
| F-019 + F-021 | `backend/receipt_ocr_engine.py` | Env-Key statt statischem Token; `enforce_egress_firewall_for_url()` + `sanitize_outbound_llm_payload()` vor Dispatch |
| F-020 + F-047 | `backend/self_evolving_tooling.py`, `backend/ephemeral_sandbox.py` | AST-Import-Sperre (`os/subprocess/socket/ctypes/urllib`), Auto-Fix darf keine gesperrten Imports injizieren; `_ClosingConn` gegen FD-Leak |
| F-022 | `backend/voice_pipeline.py` | Alle Cloud-/TTS-Zweige durch gemeinsames Egress+DLP-Gate; Key in Header statt Query |
| F-039 | `archon/core/delegation.py` | `task_id` erst nach `commit()`; Fehler → `blocked` + DLQ + ehrliche Quittung |
| F-040 | `archon/core/orchestration.py` | Write-Erfolg tracken; bei Fehler `blocked` statt `completed` |
| F-041 | `backend/agent_router.py`, `core_dispatcher.py` | Compliance-Check-Exception → `COMPLIANCE_GATE_UNAVAILABLE` (fail-closed) an allen 3 Stellen |
| F-073 | `start.bat`, `install.sh`, `docker-compose.yml` | `alertmanager` in SERVICES-Liste / `depends_on` |
| F-074/F-042 | `watchdog_daemon.py`, `main.py` | Modulweites `import threading`, `join()`, Log-Level INFO |
| F-075 | `backend/otel_tracer.py`, `.env.example`, `docker-compose.yml`, `start.bat` | Langfuse-Keys/Host durchreichen, `--profile tracing`, oder ehrlich `not_configured` |
| F-001 + F-002 + F-035/F-066 | `PbSettingsModal.tsx`, `archon/routers/email_settings.py` | Echte SMTP-/Storage-Saves + Test-Mail mit Body; `.dict()` → `model_dump()` |

**Gate W1:** `py_compile`; `node --check PbSettingsModal.tsx` (via `tsc`); gezielte Tests: Sanitizer/Compliance fail-closed, OCR-Key env-only, Delegations-Fehlerpfad → `blocked`, Watchdog `stop()` ohne Exception.

### Welle 2 — Orchestrierung & Concurrency (HIGH + zugehörige MED)
| IDs | Dateien (Edit-Blöcke) | Maßnahme |
|---|---|---|
| F-009 + F-057 + F-049 | `core_dispatcher.py` | Deterministische Route ausführen (0 Tokens) + HITL-Block; Audit-Schreibpfad via `to_thread`+Lock; stille `except pass` → Logging |
| F-010 | `backend/role_budget_engine.py` | Monatslimit in `reserve()`/`settle()` unter `BEGIN IMMEDIATE` erzwingen |
| F-054 | `archon/routers/proxies.py` | `WeakKeyDictionary`, zentraler `aclose()`-Shutdown-Hook |
| F-055 + F-011 + F-012 + F-053 | `backend/operations_api.py`, `archon/routers/…` | Kanban-Hot-Path in `asyncio.to_thread`; Fencing-Guard nach jedem `await`; `token.check()` nach jedem `await`; HITL nur `awaiting_approval`/`blocked` mit `resolution` |
| F-056 + F-044 + F-041-Rest | `backend/agent_router.py` | Token-Guard in `to_thread`; Eskalation reverifizieren |
| F-058 + F-060 | `archon/core/orchestration.py`, `archon/routers/operations_org.py` | Sync-Store/Profil-I/O via `to_thread`; Semaphore-Key `WeakKeyDictionary` statt `id(loop)` |

**Gate W2:** `py_compile`; `pytest tests/ -q` (Erwartung ≥ 1775 passed, 0 failed); Concurrency-Smoke: parallele Dispatches mit Audit-Kette `valid=True`, keine `bound to a different loop`-Fehler.

### Welle 3 — Integrationen, Audit-Rand & Resilienz-MED
| IDs | Dateien | Maßnahme |
|---|---|---|
| F-023 + F-024 + F-025 + F-031 | `utils/notebook_engine.py`, `backend/dual_llm_sanitizer.py`, `backend/delegation_isolation.py`, `backend/api_key_manager.py` | Egress/DLP im Notebook-Pfad; 25 Muster als SSOT; Pfad-Aliase + fail-closed; Audit-Fehler `logger.error` + `audit_status` |
| F-027 + F-028 + F-029 + F-030 + F-032 + F-033 | `backend/audit_log.py`, `backend/llm_egress_guard.py`, `backend/execution_receipt_ledger.py`, `main.py`, Nebenketten | Fail-Closed HMAC ohne Key; `egress_zone` Pflichtfeld; substring-basierte Token-Redaktion; DNS-Block-Audit; Bypass sichtbar; alle 7 Verifikatoren im 30-s-Loop |
| F-034 + F-037 + F-038 | `main.py`, `archon/routers/security_scanner.py`, `archon/routers/chat.py`, n8n-Skripte | Pydantic-v2 statt Dict; eine n8n-Quelle; Sanitizer-Fehler fail-closed |
| F-003–F-008 | `PbSettingsModal.tsx`, `backend/agent_router.py`, `archon/routers/chat.py`, `archon/core/orchestration.py`, `static/js/*` | Alle verbleibenden Stubs echt verdrahten oder ehrlich kennzeichnen |
| F-043 + F-044–F-053 | `main.py`, `workflow_dag_runner.py`, `local_memory_bridge.py`, `ephemeral_sandbox.py`, `operations_api.py`, Skripte | Zombie-`wait()`, Reverifikation, Non-Dict-Fehler, Checkpoint-Fehler, `destroyed:None`, HITL-Optionen, stille Swallower |

**Gate W3:** `py_compile`; `pytest tests/ -q`; Kette-Smoke 5+ Events `valid=True`; `node --check static/js/*.js`; HBMC-Byte-Vergleich Sender↔n8n.

### Welle 4 — Persistenz-Rest, Standards & CI
| IDs | Dateien | Maßnahme |
|---|---|---|
| F-013 + F-017 | `backend/db_paths.py`, `backend/snapshot_manager.py` | `DB_BUSY_TIMEOUT_MS=5000` als SSOT; atomarer Snapshot-Restore + `safe_path_within` |
| F-063–F-065 + F-068–F-071 | Dockerfiles, `requirements.lock.txt`, `frontend/src/*`, `.github/workflows/*` | Digest-Pinning, `npm ci`, 3.13-Lock, SVG-Sanitizer, Restore-/yaml-CI-Gate, SHA-pinned Actions |

**Gate W4:** `docker compose config --quiet` (main/all/dev); `promtool check rules`; `amtool check-config`; Restore-Test 5/5; `compileall` Exit 0; `node --check scripts/*.js`.

### Welle 5 — Finale Verifikation & Dokumentation
- Gesamtsuite `pytest tests/ -q`, `compileall`, `node --check`, `docker compose config`, gezielte Dry-Runs pro Modul.
- Abgleich gegen `00_SOLL_SPEC.md` (alle S-Punkte) und `WIRING_AUDIT_2026.md` (4 Glieder je Mechanik).
- Register-Pflicht: jede behobene ID mit Status `FIXED` + Verifikationsmethode in `FINAL_VERIFICATION.md` (und Empfehlung zur Nachtragung in `docs/AUDIT_FINDINGS_REGISTER.md`).
- Re-Scoring der 5 Kriterien; Freigabe erst wenn alle BLOCKER/HIGH `verifiziert` sind.

---

## 4. Konfliktregeln & Randbedingungen für Phase 3

1. **Nie zwei Editoren auf dieselbe Datei parallel.** Die Tabelle oben bündelt Mehrfachbetroffenheit pro Welle.
2. **NEVER_DO_LIST ist Veto:** kein Coroutine-Replay, keine PostgreSQL-Migration — auch nicht als „Fix".
3. **Akzeptierte Risiken nicht neu verhandeln:** Dead-Man-Switch, prozesslokale Breaker, `main.py`-Größe, 11k-Adapter, `null`-Receiver-Historie, 39 legitime Doku-Drifts (siehe Annex SOLL_SPEC).
4. **Fail-Closed ist Default:** Jeder neue Opt-in-Fail-Open braucht explizites Env-Flag + Audit-Event + Doku-Eintrag.
5. **Kein Fix ohne Verifikation:** Pro Modul mindestens `py_compile`/`node --check` + gezielter Test/Dry-Run. Grüne Tests allein belegen keine Funktionalität (G-04).
6. **Ehrlicher Zustand:** Wo eine Integration bewusst nicht aktiviert wird, ist `not_configured`/`disabled` zu melden — niemals Erfolg zu simulieren (S-1.5).

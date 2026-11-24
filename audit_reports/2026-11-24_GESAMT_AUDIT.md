# Archon OS v0.5.7.5 – Konsolidiertes Gesamtaudit (24.11.2026)

**Scope:** Working Tree von `C:\.Antigravity-projekte\AgenticOS-2026` (HEAD `9631405c`, 62 uncommitted Dateien).
**Methodik:** 16 spezialisierte Subagenten, domänenbeschränkt über die gesamte Codebasis; anschließend eigenständige Verifikation aller Top-Befunde durch den Orchestrator (Dateiinhalte direkt gelesen).
**Umfang:** ~2.866 produktive Python-Dateien / ~678.000 LOC (ohne venv/site-packages/Archive), 454 Befunde insgesamt.

---

## 1. Gesamturteil

| Bewertung | Wert |
|---|---|
| **Domänen-Durchschnitt** (16 Domänen, deutsche Skala 1=best) | **2,7** |
| **Gewichtetes Gesamturteil** | **3,0 – „befriedigend mit kritischen Abstrichen"** |
| Kritischste Einzeldomänen | D12 Silent Failures (2, Tendenz 1), D13 Trajectory (4), D15 Rollen/Prompts (4), D16 Tracing (2), D10 Härtung (2) |
| Befunde gesamt | 454 (~47 kritisch/blocker, ~152 hoch, ~208 mittel, ~41 niedrig; Kategorien teils überlappend) |
| Kernaussage | Die Architektur ist umfangreich und vielerorts echt implementiert – aber die **Kernfunktion (autonome, auditierbare Agenten-Orchestrierung im 24/7-Betrieb) ist in mehreren Hot Paths nicht geschlossen**: simulierte Ergebnisse fließen in Governance ein, Trajectory-Limits werden nicht persistiert, Trace-Kontext existiert nicht, und zentrale „erledigt"-Behauptungen der Doku sind Stubs. |

**Grundsätzliches Fazit:** Archon OS ist ein beeindruckendes Konstrukt aus echten, figuraufwendigen Mechanismen (HMAC-Kette, BudgetBank, Leases/Fencing, PolicyEngine, Outbox/DLQ, CAS, Replay-Fixtures). Die Probleme liegen weniger im Fehlen von Code als in **Verdrahtung, Persistenz und Fail-Open-Entscheidungen an den Übergängen**. Genau dort, wo Agenten autonom handeln sollen, werden Ergebnisse nicht validiert, Limits nicht durchgesetzt und Fehler in Erfolg übersetzt.

---

## 2. Notenmatrix der 16 Domänen

| Domäne | Note | Befunde | Bericht |
|---|---|---|---|
| 01 Verdrahteter Schein & Stubs | 2 | 24 (3 krit.) | `d01_stub_detection.md` |
| 02 Agenten-Orchestrierung & Routing | 2 | 28 (4 krit.) | `d02_orchestration.md` |
| 03 Persistenz, DB & Vault | 3 | 32 (2 krit.) | `d03_persistence.md` |
| 04 Governance, Security & Permissions | 3 | 24 (1 krit.) | `d04_security.md` |
| 05 Audit-Trail & Kryptografie | 3 | 23 (2 krit.) | `d05_audit_crypto.md` |
| 06 Integrationen, Webhooks & API | 3 | 26 | `d06_integrations.md` |
| 07 Error-Handling & Recovery | 3 | 37 | `d07_error_recovery.md` |
| 08 Performance & Concurrency | 3 | 26 | `d08_performance.md` |
| 09 Architektur- & Code-Standards | 3 | 28 | `d09_standards.md` |
| 10 System-Härtung & 24/7-Betrieb | **2** | 27 (1 Blocker) | `d10_hardening.md` |
| 11 Context Drift & Handoff | **2** | 32 (6 krit.) | `d11_context_drift.md` |
| 12 Silent Tool Failures / Hallucination | **2 (→1)** | 40 (14 krit.) | `d12_silent_failures.md` |
| 13 Trajectory-Governance & Loop-Prevention | **4** | 28 (8 hoch) | `d13_trajectory_limits.md` |
| 14 Entscheidungs-Hoheit & Konfliktlösung | 2 | 26 (5 krit.) | `d14_decision_authority.md` |
| 15 Semantische Rollen- & Prompt-Trennschärfe | **4** | 25 (4 krit.) | `d15_roles_prompts.md` |
| 16 Distributed Tracing & Observability | **2** | 28 (5 krit.) | `d16_tracing.md` |

---

## 3. Top-Befunde (vom Orchestrator verifiziert)

| # | Datei:Zelle | Kritikalität | Befund (verifiziert) |
|---|---|---|---|
| 1 | `backend/agent_router.py:825-849` | KRITISCH | HTTP 200 ohne `choices`/Text wird als Erfolg zurückgegeben; `cost_usd=0.0` hart codiert → leere Antworten werden zu Halluzinationen. |
| 2 | `backend/self_evolving_tooling.py:42-59` | KRITISCH | AST-Blocker prüft nur `ast.Import`/`ImportFrom`; `__import__`, `eval`, `exec`, Dunder umgehen die Sandbox → RCE. |
| 3 | `backend/audit_log.py:120-127` + 5 Nebenketten | KRITISCH | `_chain_hash()` fällt ohne Key auf nacktes SHA-256 zurück; Guard nur in `record_event()` → DSGVO/API-Key/Approval/Email/Treasury-Ketten unsigniert. |
| 4 | `backend/audit_log.py:824-831` | KRITISCH | Anker-Check `last_anchor in chain_hashes` akzeptiert jeden historischen Hash → Tail-Löschung unentdeckt; Klartextdatei im DB-Verzeichnis. |
| 5 | `archon/routers/erp.py:36,44,82-91` u. v. m. | KRITISCH | `company_id` aus Query/Body ohne Tenant-Kontext-Abgleich → Cross-Tenant-IDOR. |
| 6 | `archon/core/mission_control.py:219-233` | KRITISCH | `cancelled` fällt durch auf `return "todo"` → abgebrochene Tasks werden reaktiviert, Eltern verwaist. |
| 7 | `docker-compose.yml:524` | HOCH/BLOCKER | `archon-worker` ist `time.sleep(86400)` – kein Queue-Consumer, kein Healthcheck. |
| 8 | `archon/routers/container_ops.py:196-199` | HOCH | Blanket `except Exception` schluckt `ZeroEgressBlockedError`; Fake-Text `[agent_name]: Anweisung empfangen...` als Ergebnis. |
| 9 | `api_provider.py:709-743`, `746-750` | HOCH | Jeder Provider-Key-Lookup scannt synchron ~70 Profil-`.env`-Dateien ohne Cache → Event-Loop-Blocker. |
| 10 | `.hermes/profiles/` vs. `data/hermes_profiles/` | HOCH | 280/280 gemeinsame Tier-Dateien bitverschieden (289 vs. 293 Dateien) → „73 synced Profile" falsch, Safety-Regeln verloren. |
| 11 | `agent_profiles.json` (73 Rollen) | HOCH | 0/73 Rollen mit domänenspezifischer Negativ-Abgrenzung; Medizin/Recht/Steuer/Finanzen ohne HITL-Pflicht. |
| 12 | Gesamtes Repo (Python + YAML) | KRITISCH | Kein `traceparent`, kein OTel-SDK, kein Propagator → 18/18 Systemgrenzen brechen Trace; Audit-Log ohne trace_id. |
| 13 | `core_dispatcher.py:916-927` | HOCH | `effective_prompt_info` berechnet, aber nie im Result zurückgegeben → Canary-Version im Handoff nicht nachvollziehbar. |
| 14 | `archon/routers/boardroom.py:308-331` | KRITISCH | Chairman frei aus Request-Body wählbar, keine Tier-Prüfung; `NO_CONSENSUS` erzeugt trotzdem Final Decision. |
| 15 | `.github/workflows/ci.yml:271,301-319` | HOCH | Ruff/Mypy/Coverage/ESLint nur mit `continue-on-error`/`|| true`; „Qualitätstor" wirkungslos. |
| 16 | `tests/conftest.py:60` (CI setzt Flag nicht) | HOCH | `ARCHON_TEST_DB_ISOLATION` nicht in CI → Tests schreiben in Produktiv-`data/*.db`. |
| 17 | `backend/cancellation.py:98-102` | HOCH | Blinder `except: pass` beim `task.cancel()`; danach Erfolgs-Event → Zombie/Doppel-Execution. |
| 18 | `backend/resource_backpressure.py:56-66` | HOCH | Disk-Schutz defaultet bei Fehler auf „25 GiB frei" → Disk-Full-Alarm stumm. |
| 19 | `backup_archon.py:31-50`, `config/litestream.yml:30-49` | HOCH | Tenant-DBs werden nicht gesichert/repliziert; DR lokal auf derselben Disk, kein RPO/RTO. |
| 20 | `backend/db_consolidation.py:303-328` | HOCH | `INSERT OR IGNORE` bei PK-Kollision mit abweichendem Inhalt → stiller Datenverlust; kein Aktivierungs-Manifest. |

**Weitere besonders relevante Befunde (Auszug):**
- Simulierte LLM-Antworten in `routergate.py:100-116` / `speculative_hedger.py:86-108`; erfundene Risiken in `war_room_simulator.py:153-190` steuern HITL-Blockaden; `/api/evolution/eval-suite/run` genehmigt Releases ohne echten Lauf (`eval_regression_runner.py:92-166`); `/api/execution/map-reduce` liefertFake-Ergebnisse mit `status: completed` (`execution.py:112-122`).
- `agent_router.py` Fallback-Kette ohne Gesamt-Deadline (bis 270 s, Slot+Budget blockiert); IMAP ohne Timeout und ohne `\Seen` (`operations_calendar.py:1777`) → Hängen + doppelte RSVP.
- n8n: 5/7 `mcp__n8n__*`-Webhooks `active:false`; HMAC-Signatur-Serialisierung zwischen Sender/Verifier inkonsistent (`mcp_n8n_driver.py`).
- `structured_output_enforcer.py:112-139` füllt fehlende Pflichtfelder mit `0`/`""`/`[]` und meldet `valid: True`.
- `passkey_hitl.py:311-324`: Registrierung verzichtet optional auf `rpIdHash`/UP-Flag/Attestation.
- `approval_policy_engine.py:238-290`: Einzelner Admin kann Vier-Augen-Schwelle auf 1 Mio. € anheben.
- 19 kopierte `_require_admin`-Definitionen; kein globaler Exception-Handler; fire-and-forget `create_task` im HITL-Resume.
- Klartext-Secrets im Arbeitsverzeichnis (`.env`) – Werte hier ausdrücklich nicht wiedergegeben.

---

## 4. Dokumentation vs. Code (Kernbehauptungen)

| Behauptung | Status | Nachweis |
|---|---|---|
| „HMAC-SHA256-Auditkette lückenlos & manipulationssicher" | ⚠️ | Zentralkette solide, 5 Nebenketten fail-open, Anker wirkungslos (s. o.) |
| „Jeder LLM-Dispatch lückenlos protokolliert" | ❌ | Firewall-Fehlerpfad auditfrei (`llm_egress_guard.py:550-558`), Audit-Fehler nur WARNING (`core_dispatcher.py:1166`) |
| „OpenTelemetry & Langfuse Tracing" | ❌ | Kein SDK, kein `traceparent`, Env-Var leer, Exportfehler auf DEBUG |
| „Zero-Egress hart fail-closed" | ⚠️ | Grundsatz echt, aber `container_ops.py:196-199` schluckt Blockade |
| „PolicyEngine/BudgetBank mit signed warrants" | ⚠️ | Echt implementiert, aber `replan_count` ohne Setzer, Budget zur Laufzeit nicht geprüft, `cost_usd=0.0` |
| „407 stille except-Blöcke ersetzt" | ⚠️ | Einzeilige `except: pass` = 0, aber 82 Multiline-Blöcke in 41 Dateien + 313 DEBUG-only-Handler |
| „28→3 SQLite-Konsolidierung aktiv" | ⚠️ | Code vorhanden, kein Manifest/Env-Aktivierung; `INSERT OR IGNORE` mit Datenverlust |
| „73 synced Profile" | ❌ | 280/280 SOUL-Tier-Dateien divergiert |
| „EU AI Act Art.4/50 vollständig" | ❌ | Nur 2/73 HIGH_RISK, fehlendes Art.-4-Register blockiert genau diese; SOUL-Hash hasht JSON statt SOUL.md |
| „CI/CD-Qualitätstor" | ❌ | Ruff/Mypy/Coverage/ESLint `continue-on-error` |
| „n8n-Workflows aktiv" | ❌ | 5/7 Webhooks `active:false`, Signatur inkompatibel |
| „Vier-Augen-Prinzip" | ⚠️ | Kein Ersteller-Abgleich, Schwelle per Admin änderbar |
| „24/7-Produktionsbetrieb" | ❌ | Ansible deployt Dev-Compose mit `--reload`, kein Supervisor, kein externes DR, kein Alerting |
| „Autonome Agenten-Orchestrierung" | ❌ | Board-Move von Hand nötig, kein Proof-/Verifier-Gate, Zero-Egress-Worker = `sleep` |
| „Vorkompiliertes Tailwind / zentraler SSE-Bus / HTTP-Pools" | ✅ | Im Code bestätigt (Domäne 8/9) |
| „Passkey/WebAuthn echte Signaturprüfung" | ⚠️ | Signaturprüfung echt, aber Registrierung optional ohne `rpIdHash`/Attestation |

---

## 5. Bewertung nach gängigen Kriterien (ISO/IEC-25010-nahe)

| Kriterium | Note | Begründung |
|---|---|---|
| Funktionale Eignung | 3 | Viele Mechanismen echt, aber Stubs in Governance-/Eval-Pfaden |
| Zuverlässigkeit / Recovery | 3 | Cancel-Fehler, keine Supervision, HITL-Livelock, unvollständiges Error-Handling |
| Performance-Effizienz | 3 | Hot-Path-Blocker, unbegrenzte Queries, kein Token-Budget im Prompt-Aufbau |
| Sicherheit | 3 | Breite Kontrollen, aber Sandbox-Bypass, IDOR, Secrets, Demo-Guard fail-open |
| Wartbarkeit / Modularität | 3 | God-Objects (212 KB Dispatcher), 19 RBAC-Duplikate, wirkungsloses Qualitätstor |
| Observability / Betrieb | 4 | Kein verteilter Trace, kein Alerting, leere Endpunkte, keine SLOs |
| Compliance (GoBD/DSGVO/AI Act) | 3,5 | Zentrale Kette gut, Nebenketten/Anker/Rollenklassifizierung mangelhaft |
| **Autonomie (Kernfunktion)** | **4** | Manueller Start, kein Verifikations-Gate, Placeholder-Worker, wirkungslose Trajectory-Limits |

---

## 6. Priorisierter Verbesserungsplan

### P0 – vor dem nächsten Release (Sicherheit & Wahrheit der Kernfunktion)
1. **Fail-closed-Signierung zentralisieren:** `sign_block()`-API mit Pflicht-Key für alle Ketten; Anker signieren, extern/WORM ablegen, Verifikation auf Head oder signierten Fortschritt verschärfen.
2. **Silent-Failure-Klasse abschaffen:** Einheitlicher `Result[T, Error]`-Vertrag für alle Tool-/Provider-Wrapper; HTTP 200 ohne Nutzlast = Fehler; keine Fallback-Texte; leere Antworten nie an LLM zurückgeben.
3. **Trajectory-Limits persistieren & hart durchsetzen:** `delegation_depth`, `failure_reason`, `replan_count`, `max_fanout`, `max_budget_eur` in `mc_task_meta`/Task-Schema; Validierung vor jedem Hop; Token-Budget für System-Prompt.
4. **Simulationen aus Governance entfernen:** Hedge-/War-Room-/Eval-/Map-Reduce-Stubs entweder echt verdrahten oder hart von Produktions-Endpunkten trennen (`demo_only` + RBAC + kein Schreibzugriff auf Decisions).
5. **Company-ID autorisieren:** Tenant-Kontext aus Session/Claim statt Query/Body; CAS/Prüfung in allen ERP-/CRM-/Tenant-Endpunkten.
6. **Sandbox & Demo-Guard schließen:** AST-Blocker auf Calls/Dunder/`eval`/`exec` erweitern; `python -I` ohne `open`/`os` (oder echte process-/namespace-Isolation); Demo-Guard fail-closed.
7. **Boardroom-Hoheit:** Chairman nicht aus Request-Body; Tier-Prüfung; `NO_CONSENSUS` → kein Final Decision; Ersteller-Abgleich bei Freigaben; Vier-Augen-Schwelle nicht per Einzel-Admin änderbar.

### P1 – Betriebsfähigkeit herstellen
8. Ansible auf produktive `docker-compose.yml` umstellen, Probes/Resource-Limits/Restart-Policies verdrahten; echten Worker-EntryPoint oder Platzhalter entfernen.
9. Externen Heartbeat/Dead-Man-Switch + Supervisor für den Watchdog, Alarmierung bei Integritätsverletzungen.
10. W3C Trace Context durchgängig: SDK, `traceparent`-Inject/Extract an allen 18 Grenzen, `trace_id`/`span_id` in Audit und Logs, OTel-Collector + echtes Backend, Sampling definieren.
11. DR: Tenant-DBs in Backup/Litestream aufnehmen, externes Ziel, RPO/RTO definieren, Restore-Test darf nie auf Live-DB fallen.
12. CI-Qualitätstor wirklich schließen (`continue-on-error` entfernen), `ARCHON_TEST_DB_ISOLATION=1` in CI setzen, lokales Suite-Skript mit GitHub Actions angleichen.

### P2 – Substanz & Standards
13. 73 Rollen: Negativ-Abgrenzungen (bes. Medizin/Recht/Steuer/Finanzen), SOUL-Bäume vereinheitlichen (280 Divergenzen), AI-Act-Klassifizierung korrigieren, Art.-4-Register füllen, SOUL-Hash auf echte Dateien.
14. Context-Handoff auf Pydantic-Schemata umstellen; `effective_prompt_info`, Failure-Reason, Trace-ID mitführen; keine stillen Truncations ohne Marker.
15. Hot Paths: Profile-Key-Cache, SQLite-Writes via `to_thread`, MC-Cache synchronisieren, `LIMIT` in Listen-Endpunkten, Virtualisierung der 832 Templates.
16. Monolithe aufteilen (`core_dispatcher.py`, `main.py`), 19 `_require_admin`-Duplikate auf zentrales Modul, globaler Exception-Handler, Mypy/Ruff als echte Gates.

---

## 7. Transparenzhinweise
- Der Audit lief gegen den **Working Tree** mit 62 uncommitted Dateien; einzelne Befunde können in COMMIT `9631405c` abweichen.
- „Jede Zeile Code" wurde nicht wörtlich sequenziell gelesen (678 k LOC); die 16 Subagenten haben domänenweise gezielte Vollsuche + Tiefenlesen derHot Paths durchgeführt. Alle hier aufgeführten Top-Befunde wurden vom Orchestrator im Originalcode nachgelesen.
- Die 16 vollständigen Befundberichte mit je 23–37 KB, Tabellen, Zeilennummern und Empfehlungen liegen in `audit_reports/2026-11-24_d01…d16_*.md`.

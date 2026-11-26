# MASTER PLAN — Archon OS System-Audit 2026-11-26

> **Phase 2 — Konsolidierung & Architektur-Bewertung.** Grundlage: `00_SOLL_SPEC.md`
> (Phase 0) sowie alle 16 Domain-Berichte `domain_01.md` … `domain_16.md` (Phase 1).
> Alle 16 Subagenten haben unabhängig und skeptisch gegen den **aktuellen Code** geprüft;
> ältere „behoben"-Behauptungen wurden nicht übernommen. Die Zählungen unten sind die
> Summe der 16 Domain-Berichte. Verbindlich: `docs/system/NEVER_DO_LIST.md`
> (kein Coroutine-Replay, keine PostgreSQL-Migration, keine eigene Content-Domäne).
>
> **Gesamt: 121 Befunde — 2 BLOCKER · 36 HIGH · 82 MED · 1 LOW.**

---

## 1. Reifegrad-Bewertung (Skala 1–10)

| # | Hartes Kriterium | Score | Begründung (ehrlich, gegen Code) |
|---|---|---|---|
| 1 | **Funktionale Vollständigkeit (Echtbetrieb vs. Schein)** | **5/10** | Der harte Kern (BudgetBank, Taint-Guard, Warrants, Passkey, HMAC-Kette, DLQ-Replay, Konsensalgorithmus, SSE, OTel-Recorder) ist real verdrahtet. Aber zahlreiche **publikums wirksame** Mechaniken sind Theater: PbD-Synthese nur `print()` (D01-H1), „Anweisung an Agenten" nur Feed-Eintrag (D01-H2), 3-Tier-SOUL ohne Konsument (D11-M5/D15-H1), STORM-Panel ohne Produktivaufrufer (D14-M2), `hired_*-Profile` trotz Hiring blockiert (D15-H7), Restart-SLA und Watchdog-Test nur Schein (D10-H1/M1), Restore-Test ohne Replikat (D10-M2). Fix und Schein liegen dicht beieinander. |
| 2 | **Multi-Agenten-Stabilität (Context/Loops/Roles)** | **4/10** | Strukturell stark: `MAX_DELEGATION_DEPTH=3` aus SSOT, A→B→A-Zyklus-Erkennung, Fanout-Cap 5, `replan_count=2`, Lease/Fencing, atomare BudgetBank. Semantisch aber drei harte Löcher: Delegationssignatur produktiv **nie geprüft** (D11-H1), zwei various Payloads (D11-H2), Handoff-Gate lässt genau Delegations ungefiltert passieren (D11-H3). Dazu `task_id`-lose Dispatches mit frischer `traj-anonymous:<time>`-ID → Hop-/Loop-/Token-Caps wirkungslos (D13-H1), Tier-Veto `break` zu früh und `tie_break` dekorativ (D14-M1), Founder/CEO-Doppelmandat und APEX-Doppelung (D15-H6/M). |
| 3 | **Sicherheits-Härtung (Zero-Trust/Governance)** | **4/10** | **Paradox:** Die Krypto-/Policy-Implementierung ist über weite Strecken exzellent (echte ES256/RS256-Passkey-Prüfung, HMAC-Warrants mit 24 Pfad-/Betragsaliasen, Taint-Default-Deny, korrigierbare RBAC-Fail-Closed-Gates, gehärtete Windows-DACLs, harte CI-Gates). Die **ausgelieferte Konfiguration** negiert davon das Wichtigste: `sensitive_local_routing=false` + `fallback_to_eu=true` schalten Zero-Egress faktisch ab (**BLOCKER** D04-B1), `secret_masking_enabled` ist zur Laufzeit abschaltbar (D04-H2), die Merge-Reihenfolge überschreibt harte Werte mit `false` (D04-H3), Demo-WS lässt `/rest/push` durch (D04-H1), Egress-Firewall fail-open mit hartcodierter Allowlist (D04-M6), `get_session_actor` fällt auf `"admin"` zurück (D04-M5). Zero-Trust im Code, Fail-Open in der Auslieferung. |
| 4 | **Fehlertoleranz & Silent-Failure-Schutz** | **4/10** | **Zweiter BLOCKER:** der einzige Produktivaufruf von `recover_stale_synthesis()` ist ein `TypeError`, auf `DEBUG` verschluckt → Synthesis-Watchdog komplett tot (D07-B1). Zombie-Reset bei Importfehler fail-open (D07-H1), `ARCHON_LEASE_FAIL_OPEN` umgeht CAS (D07-H2). Firewall-Urteil wird an vier Konsumenten verworfen (D12-H1), CRM-/Inbox-/IMAP-/Updater-Pfade melden Ausfälle als Erfolg (D12-H2/H3/H4 + M). Positiv: `CancelledError`-Persistenz, 90-s-Deadline, `EMPTY_RESPONSE`-Erkennung, Flightlog-Produzent im Chokepoint — der Detektor ist da, die Konsumenten oft nicht. |
| 5 | **Daten- & Trace-Integrität** | **5/10** | HMAC-Hashkette mit Env-Key, Append-only-Trigger, Anker mit Tail-Löschungserkennung, domain-separierte Receipt-Kette, echter Lifespan-Fail-Fast — solide (D05 positiv). Aber: echte LLM-Calls ohne Dispatch-Proof in Voice/Research/Injection-Klassifikator (D05-H1), „externer" Anker liegt im selben Mount wie die DB (D05-H2), Audit/Log/Vault ohne `span_id` (D16-M3/M4/M5), Tenant-Vault-Fail-Open (D03-H1), DAG-Ledger ohne Tenant-Spalte (D03-H2), `*.db.bak`-Alt Kopien außerhalb Art. 17 (D03-M3), GoBD-Trigger schützt nur 2 Spalten (D03-M5), Restore ohne Auditnachweis als Erfolg (D03-M4). |
| 6 | **Code- & Architekturqualität** | **6/10** | Supply-Chain vorbildlich: Hash-Locks mit Python-3.13-SSOT, CycloneDX-SBOM mit Hashes-Gate, `pip-audit`/`bandit` hart, SHA-gepinnte Actions, `@sha256:`-Image-Digests inkl. Basisimages, `npm ci && tsc --noEmit && build`, keine Pydantic-v1-Reste (D09 positiv). Abstriche: vier God-Objects bis 161 KB und ein 11.232-Zeilen-Fremdcode-Patch im Read-Only-Produktivmount (D09-H1), MyPy läuft gegen 3.11 statt 3.13 (D09-M1), Import-Layer-Gate nur zur Hälfte (D09-M2), ~100 `# type: ignore[assignment]`, `compileall`/`bandit` erfassen die Root-Monolithen nicht (D09-M4), ungesicherter Undo-Store (D09-M5), Doku-Widerspruch `/content-studio` (D09-M7). |
| **Gesamt (arithmetisches Mittel)** | **≈ 4,7/10** | **Ehrliches Urteil:** Archon OS ist ein außergewöhnlich umfangreiches, architektonisch durchdachtes System mit einer **sehr guten Sicherheits- und Krypto-Basis**, aber im Auslieferungszustand **kein 24/7-produktionsreifes Zero-Trust-System**. Es scheitert nicht an fehlenden Funktionen, sondern an drei systematischen Mustern: (a) **konfigurationsgesteuerte Fail-Open-Pfade**, (b) **Produzenten ohne Konsument** (Theater), (c) **Fehler, die auf `DEBUG` verschluckt oder als Erfolg quittiert werden**. Mit den 2 Blockern und den 36 HIGH-Fixes ist 7–8/10 erreichbar; ohne sie bleibt die Doku-Behauptung „100 % korrekt verdrahtet" eine Einschätzung, kein Faktum. |

---

## 2. Domänen-Übersicht (tabellarisch)

| Domäne | Funde | B / H / M / L | Top-Befund | Score | Charakter |
|---|---|---|---|---|---|
| 01 Stub/Wiring | 8 | 0 / 2 / 6 / 0 | PbD print-only Fake-Success | — | Theater in UI/Nebenpfaden, Kern ehrlich |
| 02 Orchestrierung | 5 | 0 / 3 / 2 / 0 | n8n-Schein-Erfolg im Router | — | Historik behoben, neue Chokepoint-Divergenz |
| 03 Persistenz | 9 | 0 / 3 / 5 / 1 | Vault-Tenant-Fallback `default` | — | Kerndaten solide, Randpfade fail-open |
| 04 Security | 11 | **1** / 3 / 7 / 0 | Zero-Egress konfigurationsseitig aus | — | **Beste Krypto, schlechteste Config** |
| 05 Audit/Krypto | 4 | 0 / 2 / 2 / 0 | LLM-Dispatch-Proof-Lücke | — | Kette saniert, Vollständigkeit/Anker offen |
| 06 Integrationen | 3 | 0 / 1 / 2 / 0 | Outbox-Drainer nur aktiver Mandant | — | Meisten W2/W4-Funde echt behoben |
| 07 Error/Recovery | 7 | **1** / 2 / 4 / 0 | `recover_stale_synthesis` TypeError | — | **Watchdog komplett tot** |
| 08 Performance | 10 | 0 / 1 / 9 / 0 | Sync-Idempotency im async DAG-Retry | — | Großregressionen behoben, Rest-I/O |
| 09 Architektur | 9 | 0 / 1 / 8 / 0 | God-Objects + 11k-Patch-Mount | 7/10 | Supply-Chain vorbildlich, Struktur nicht |
| 10 Härtung/24-7 | 9 | 0 / 1 / 8 / 0 | Restart-SLA Mess-Theater | 6,5/10 | Health/Watchdog echt, Verifikation fake |
| 11 Context Drift | 8 | 0 / 3 / 5 / 0 | Delegations-HMAC nie geprüft | — | Schema stark, Konsument schwach |
| 12 Silent Failures | 10 | 0 / 4 / 6 / 0 | Firewall-Urteil verworfen | — | Kern-Firewall intakt, Konsumenten nicht |
| 13 Trajectory/Loops | 4 | 0 / 1 / 3 / 0 | `task_id`-lose Dispatches | — | Caps real, aber umgehbar |
| 14 Entscheidungs-Hoheit | 6 | 0 / 1 / 5 / 0 | HITL-Override mit Body-Freitext fälschbar | — | Algorithmus solide, Ränder fälschbar |
| 15 Rollen/Prompts | 12 | 0 / 7 / 5 / 0 | 3-Tier-SOUL ohne Konsument | — | Struktur 71/71, Semantik löchrig |
| 16 Distributed Tracing | 6 | 0 / 1 / 5 / 0 | `traceparent`-Self-Parenting | — | Erstaudit-HIGHs behoben, Restgrenzen offen |
| **Summe** | **121** | **2 / 36 / 82 / 1** | — | **≈ 4,7/10** | — |

---

## 3. BLOCKER & HIGH — vollständiger Befundkatalog (38 Funde)

| ID | Krit. | Datei:Zeile | Soll-Ist-Abweichung (kompakt) | Fix (kompakt) |
|---|---|---|---|---|
| **D04-B1** | **BLOCKER** | `data/privacy_routing.json:2-8` | `sensitive_local_routing=false`, `fallback_to_eu=true` → finance/contracts/CRM/hr/gdpr ungefiltert in Cloud; harter LOCAL_ON_PREM-Block greift nicht | Flags auf `true`/`false`; Security-Only-Merge (ODER für Härte, UND für Fallback); Startup-Fail-Fast bei Prod + `false` |
| **D07-B1** | **BLOCKER** | `archon/services/background_loops.py:170-187`; `orchestration.py:1888-1894` | 4 Positionalargumente an Signatur mit 2 pos.+2 keyword-only → `TypeError`, auf DEBUG verschluckt; Synthesis-Watchdog nie wirksam | Keyword-Args, `type: ignore` entfernen, `ERROR`+Audit, Loop-Regressionstest |
| D01-H1 | HIGH | `backend/computer_use_pbd.py:437-502` | PbD-Skripte nur `print()`/`sleep()`, melden `completed` | Echte CUA-Runtime oder ehrlich `simulated`/`demo_only` + `RuntimeError` |
| D01-H2 | HIGH | `static/js/agent_profiles.js:4376-4411`; `operations_org.py:201-221` | „Anweisung an Agenten" schreibt nur `task_events`-Feed | Task-Endpunkt mit `agent_id`; Erfolg nur bei sichtbarer `task_id` |
| D02-H1 | HIGH | `backend/agent_router.py:1098-1112` | n8n `unconfirmed`/`blocked` → `blocked=False` + „ausgeführt" | Statusprüfung wie `core_dispatcher.py:1640-1654` |
| D02-H2 | HIGH | `archon/core/orchestration.py:323,346,397-470,648-656` | Cancel-Token nicht nach jedem `await`; Lease-Phase außerhalb `CancelledError`-Handler | Äußerer `try/except CancelledError`, `cancelled` via shield persistieren, `check()` nach jedem await |
| D02-H3 | HIGH | `backend/workflow_dag_runner.py:1357-1369`; `workflow_nodes/prompt.py:56-63` | `and profiles`-Klausel → Fail-Open bei leerer Profil-SSOT, Generik-Prompt | Klausel entfernen, bei expliziter ID + fehlendem Profil immer `blocked` |
| D03-H1 | HIGH | `archon/routers/vault.py:115-120,137-144` | Resolverfehler → still `default`/gemeinsame Vault-Wurzel | `RuntimeError`,immer `<root>/<tid>`, kein gemeinsamer Root |
| D03-H2 | HIGH | `backend/workflow_dag_runner.py:788-839` | DAG-Ledger in globaler `ops.db`, keine `tenant_id`-Spalte | `resolve_active_db("ops.db")`, `tenant_id NOT NULL`, PK `(tenant_id,run_id)` |
| D03-H3 | HIGH | `backend/db_consolidation.py:772-784` | `--migrate` ohne `--activate` überschreibt Manifest → Konsolidierung deaktiviert | Manifest nur bei expliziter Zustandsänderung schreiben |
| D04-H1 | HIGH | `backend/demo_mode.py:36-46,1309-1315`; `proxies.py:347-349` | Demo-WS lässt n8n-Alias `/rest/push` durch → Egress-Bypass | Default-Deny für WS, `/rest/push` blocken, Gate im Proxy |
| D04-H2 | HIGH | `backend/secret_masker.py:84-90` | `secret_masking_enabled=false` → Klartext + `count=0` = „Erfolg" | Schalter entfernen/hart blockieren, `secure_mask()`-SSOT |
| D04-H3 | HIGH | `backend/privacy_router.py:97-112` | `merged.update(data)` überschreibt härteren settings.json-Wert | Strengthening-only-Merge, `verify_zero_egress_config()` am Start |
| D05-H1 | HIGH | `voice_pipeline.py:100-172`; `local_security_guard.py:219-340`; `research_engine*.py` | Echte LLM-Calls ohne `llm_dispatch`-Proof (nur blockierte Pfade signiert) | Zentraler `audit_dispatch_sync()` in jedem Erfolgspfad + AST-CI-Gate |
| D05-H2 | HIGH | `.env:18`; `docker-compose.yml:124,171-172` | „Externer" Anker = `./data/audit_anchor.log` im DB-Mount | Pfad auf getrenntes Volume, `ro`-Mount, RFC3161/WORM perspektivisch |
| D06-H1 | HIGH | `backend/workflow_scheduler.py:1586-1625` | Einziger 30-s-Drainer ohne `tenant_id` → Sekundärmandanten nie zugestellt | Per-Tenant-Loop über alle Mandanten-DBs |
| D07-H1 | HIGH | `backend/operations_api.py:361-372` | Importfehler des Liveness-Guards → `None` = „eligible", alle Tasks reset | Fail-Closed `return 0` + Audit, CAS-Reset-Bedingung |
| D07-H2 | HIGH | `backend/operations_execution.py:427-439` | `ARCHON_LEASE_FAIL_OPEN` + `task_exists=False` → Dispatch ohne CAS | Umgebungsschalter entfernen, immer `skipped` bei Claim-Fehler |
| D08-H1 | HIGH | `backend/workflow_dag_runner.py:1645,1675,1705` | Sync-Idempotency (`timeout=15.0`) im `async`-Retry blockiert Event-Loop | `asyncio.to_thread` + `shield` im `finally` |
| D09-H1 | HIGH | `core_dispatcher.py`; `main.py`; `views_core.py`; `api_provider.py`; `docker-compose.yml:409` | 4 Monolithen + 11.232-Zeilen-Telegram-Patch im Produktivmount | Patch zerlegen + Adapter-Smoke-Test als CI-Gate; Dispatcher/Main entflechten |
| D10-H1 | HIGH | `scripts/chaos_tester.py:182-218,329-338`; `archon_autoheal.py:31-36,149-185` | Restart-SLA != 15 s: Messung erst beim Docker-Call, real ≥ 150 s, Dry-Run = `passed` | End-to-End-Messung bis `/livez` 200, Autoheal < 15 s, `skipped` ≠ Exit 0 |
| D11-H1 | HIGH | `archon/core/delegation.py:298-299`; `operations_api.py:288-292` | Delegations-HMAC produktiv nie geprüft, Signatur vor Prüfung überschrieben | Verify **vor** Kanonisierung, `require_signature=True`, Block bei Fälschung |
| D11-H2 | HIGH | `delegation.py:2145-2191` vs `operations_execution.py:179-191` | Zwei Payloads: volle signierte Fassung tote Daten in `state.db`, Kind erhält verarmte Rekonstruktion (`auftrag[:80]`) | Ein signiertes Payload als SSOT in `task_events.created`, Kind liest es unverändert |
| D11-H3 | HIGH | `backend/handoff_desk.py:518-523`; `delegation.py:1751-1800` | `no_handoff_for_task` → `allowed=True`; Envelope erst nach Kind-Abschluss | Envelope vor Dispatch, `require_envelope=True`, 0 LLM-Calls bei Fehler |
| D12-H1 | HIGH | `backend/tool_runtime.py:331`; `mcp_gateway.py:745/837`; `plugins.py:168`; `operations_sysops.py:286/294` | Firewall-Urteil verworfen; leere verschachtelte Felder/Klassifikatorfehler = `success` | `with_status=True` als Pflichtvertrag, `verdict["status"]` überall prüfen |
| D12-H2 | HIGH | `scripts/archon_mcp_server.py:347-361` | Jeder PocketBase-Fehler → `success, count=0` | Result-Vertrag mit `error_code`/`attempts`, Fehler ≠ leeres CRM |
| D12-H3 | HIGH | `backend/email_service.py:192-210` | IMAP-Sanitizer-Exception → Rohtext mit `security_status="safe"` persistiert | Fail-Closed in Quarantäne, Gesamtstatus aus `errors` |
| D12-H4 | HIGH | `backend/system_updater.py:587-627` | GitHub-API-Teilfehler → „System ist auf dem neuesten Stand" | `status="partial"`, `update_available=None`, `verification{}` |
| D13-H1 | HIGH | `quickchat.py:147-155`; `telegram.py:147-154`; `agent_chat.py:271-280`; `prompts.py:184-191`; `orchestration.py:940-1704` | `task_id`-lose Dispatches → neue `traj-anonymous:<time>` pro Call, Caps wirkungslos | Erzwungene Trajectory-Root-Korrelation, Metrik `dispatch_without_trajectory_root` |
| D14-H1 | HIGH | `backend/kanban_verifier.py:217-247`; `kanban.py:226-255` | HITL-Override: leeres `proof_command` → `passed=True, skipped=True`, `verified=True`, kein Modellaufruf | Proof aus Task-Kontext, echter Cross-Modell-Call, Passkey+Audit vor Statuswechsel |
| D15-H1 | HIGH | `delegation.py:2181-2191`; `operations_execution.py:608-612` | 3-Tier-SOUL erzeugt+gespeichert, Worker nutzt nur `prof["prompt"]` | Tier-Text in Dispatch-System-Prompt, Hash-Druck fail-closed |
| D15-H2 | HIGH | `eu_ai_act_inventory.py:151-176`; `compliance_engine.py:309-417`; `hr.py:291-320` | SOUL-SHA pinnt `souls/<id>/SOUL.md`, Dispatch nutzt abweichenden `agent_profiles.json`-Prompt; UI-Edit ohne Pin-Refresh | Eine Prompt-SSOT, `refresh_soul_pin_for_agents()` zwingend, Drift → deny |
| D15-H3 | HIGH | `static/js/agent_profiles.js:990-1163`; `profiles.py:827-846` | Pflicht-Warn-Dialoge nur Legacy-UI mit `sessionStorage`, wegklickbar; Domain 4 nur 2/7 Rollen; kein Prompt/Dialog im Chat | Serverseitige, nicht wegklickbare Bestätigung in allen Pfaden + Prompt-Injektion |
| D15-H4 | HIGH | `data/ai_act_literacy_register.json:2-18`; `compliance_engine.py:232-238,428-440` | Einziger HIGH_RISK-Bediener mit `certificate_sha256: null`, `recorded_by: fix_a8_roles_bootstrap` | Validator auf Zeichenkette+Herkunft härten, Bootstrap ersetzen, bis dahin deny |
| D15-H5 | HIGH | `agent_profiles.json:4545-4588,1568-1592`; `delegation_isolation.py:97-108` | Prompt deklariert `terminal/filesystem/execute_code`, `tools`-Array verbietet sie → widersprüchlich | Tool-Deklaration aus SSOT generieren, CI-Gate Prompt≡tools |
| D15-H6 | HIGH | `eu_ai_act_inventory.py:64-66`; `agent_profiles.json:66-229`; `org_hierarchy.json:78-93,837-852` | `founder` und CEO identisches Mandat+Budget+HIGH_RISK; Eigentümer Tier 3 unter CEO Tier 1 | Mandate disambiguiieren, ein Profil deaktivieren, Tier korrigieren |
| D15-H7 | HIGH | `role_budget_engine.py:835-1043`; `compliance_engine.py:363-373`; `core_dispatcher.py:1591-1600` | `hired_*-Profile` nicht im Inventar → Default-Deny `COMPLIANCE_BLOCKED`, Budget wird aber gebucht | Temporären Inventareintrag vor Dispatch oder Hiring als `not_configured` ausweisen |
| D16-H1 | HIGH | `archon/routers/container_ops.py:184-185` | `inject_headers()` ohne `child_span()` → Self-Parenting; nicht in `OWNED_FILES` des AST-Tests | `child_span()` um Inject+POST, Datei in Test-Scope |

### MED-Clustermatrix (82 Funde, nach Wirkungsbereich gruppiert)

| Cluster | Anzahl | Repräsentative Funde (Datei:Zeile) | Gemeinsamer Fix |
|---|---|---|---|
| Audit-/Receipt-Fehler verschluckt, Konfigurations-Audit | 9 | `session_taint_guard.py:380-396`; `dual_llm_sanitizer.py:102-114`; `privacy_router.py:238-255`; `agent_router.py:1395`; `fleet_self_healing.py:258-285`; `consensus_gate.py:598`; `db_backup_manager.py:281` | Ein `secure_audit_event(...)` mit `ARCHON_AUDIT_STRICT`; Zustandsänderung bei Auditfehler zurückrollen |
| Tenant-/DB-/GoBD-Randpfade | 11 | `orchestration.py:1139-1152`; `db_paths.py:244-351` (Gate nicht in CI); `gdpr_compliance_engine.py:139` (Alt-Kopien); `erp_manager.py:382-395` (Trigger); `offline_memory_vault.py:66` | CI-Ratchet für `busy_timeout`, `*.db*`-SSOT für Art.17, Trigger auf Status/Beträge erweitern |
| Async-I/O-/Lock-Contention | 9 | `delegation.py:1142/1886`; `workflow_scheduler.py:1641`; `task_self_healer.py:209`; `content_machine.py:271`; `role_budget_engine.py:49,1182`; `task_events`-Index | Gemeinsamer `run_blocking_io()`-Wrapper + AST-CI-Gate, Index `(task_id,kind,id)` |
| Chaos-/Restore-/Watchdog-Verifikation | 8 | `chaos_tester.py:259-260` (Watchdog-Test immer skipped), `:331-338`; `automated_restore_test.py:88-130,357-383`; `ansible/vars/main.yml:75`; `docker-compose.yml:147,338`; `haproxy.cfg:175` | Evidenz-basierte Tests, `skipped` als Fehler, DR aus Observability-Opt-in lösen |
| Handoff-/Context-Feldverlust | 8 | `operations_execution.py:614-627` (`exclude_defaults`); `delegation.py:2247-2278` (kein `trace_id`/Warrant); `lossless_session_dag.py:342-363` (Dedup ohne Seq); `boardroom.py:498-505` (`[:1500]` ohne Marker); `role_budget_engine.py:733-776` (Gewichtung nicht im Kind) | Explizite Positiv-Feldliste, `mark_truncated`, Budget-Gewichtung signiert mitführen |
| Silent-Failure-/Schema-Reste | 8 | `structured_output_enforcer.py:71-77` (Bypass=`valid=True`); `consensus_gate.py:469,564` (Default-Score 7); `archon_mcp_server.py:363-391` (Inbox); `dual_llm_sanitizer.py:60-62` (hartcodierte Trust-Liste); `core_dispatcher.py:1191-1214` (Budget-Settle) | `None`/`needs_human` statt Default, Bypass sichtbar, Fail-Closed bei Registry-Fehler |
| Rollen-/Prompt-Hygiene | 9 | `compliance_engine.py:391-417` (Hash nur HIGH_RISK); `org_hierarchy.json:11-18` (APEX-Doppelung); `agent_profiles.json:469` (Lisa deprecated vs aktiv); `build_souls_ssot.py:147-186` (CrewAI-Falschzuordnung); `eu_ai_act_inventory.py:26-86` (26 vs 28, Phantomer IDs) | Hash-Prüfung verallgemeinern, Status-SSOT, fachliche Passung der Negativgrenzen |
| Security-Fail-Open-Reste | 9 | `session_taint_guard.py` Audit; `egress_firewall.py:96-110` (Default-Allowlist); `_rbac.py:43-54` (Fallback `admin`); `agent_aliases.py:73-75` (leere ID → `research_scout`); `llm_kernel.py:186-190` (Masking-Fehler); `core_dispatcher.py:619-654` (Container-Hop unmaskiert); `erp_manager.py:3238-3241` / `sync_inbox_to_pocketbase.py:54-105` (SSRF-Redirect) | Keine Default-Identitäten/Allowlists, `safe_http_request()` als SSOT, Maskierung überall |
| Tracing-/Observability-Grenzen | 5 | `runtime_endpoints.py:107-113` (CORS); `delegation.py:211-230` (kein `trace_id`); `audit_log.py:538-741` (kein `span_id`); `trace_log_filter.py:29-47` (nur Trace); `dossier_builder.py` (Vault ohne Trace) | `span_id` durchgehend ergänzen, CORS-Header, Vault-Frontmatter |
| Code-/Betriebs-Hygiene | 14 | `mypy.ini:7` (3.11); `.importlinter:51-58` (2. Contract); ~100 `# type: ignore`; `main.py:1563` (Roh-Dict); `ci.yml:167,452` (Root-Module nicht geprüft); `operations_bulk.py:25` (Undo-Store); `backend/requirements.txt` (3/38 Deps); Docs `/content-studio`; 3 `.bat` ohne `-f` | MyPy 3.13, beide Import-Contracts, Root-Module in Gates, SSOT-Manifeste, `-f docker-compose.yml` |
| Sonstige (Konsens-/Budget-/Recovery-Details) | 1 | `role_budget_engine.py:987-1025` (CEO-Hiring vor Parent-Check) | Transaktional nach Parent-Allokation |

---

## 4. Abhängigkeits-Matrix — konfliktfreie Ausführungsreihenfolge

**Prinzip:** Fundament/Datenbank → Security → Orchestrierung/Rollen → Integrationen → Performance/Observability → UI-Verifikation. Innerhalb einer Welle gibt es keine Abhängigkeiten; Wellen bauen aufeinander auf. **Die 2 BLOCKER gehen der gesamten Matrix voraus**, weil sie Security- bzw. Recovery-Mechaniken vollständig deaktivieren.

| Welle | Fokus | Befunde (IDs) | Warum genau hier | Exit-Kriterium / Konfliktvermeidung |
|---|---|---|---|---|
| **W0 — BLOCKER** | Sicherheit & Recovery wiederherstellen | **D04-B1**, **D07-B1** | Ohne Zero-Egress fließen sensible Daten extern; ohne Synthesis-Watchdog hängen Projekte dauerhaft. Alle weiteren Wellen setzen wirksame Security/Recovery voraus. | `verify_zero_egress_config()` grün + finance→cloud Test blocked; `recover_stale_synthesis` über 30-s-Loop feuert nachweislich; keine Änderung an DB-Schema nötig → kollidiert mit nichts |
| **W1 — Fundament & Datenbank** | Tenant-/Manifest-Integrität | D03-H1, D03-H2, D03-H3, D03-M1…M5, D05-H2 | DB-Pfade und Manifest sind die SSOT für alle späteren Gate-/Audit-/Outbox-Änderungen. Wer zuerst Orchestrierung ändert, läuft in `resolve_db()`-Falle. | 2-Tenant-Test mit identischem `run_id`; Manifest byte-identisch bei `--migrate`; Anker außerhalb `data/`; **kein** Schema-Lock-Konflikt mit W0 |
| **W2 — Security & Governance** | Fail-Open-Pfade, Maskierung, Audit | D04-H1…H3 + D04-M, D05-H1, D12-H1…H4 + M, D06-M(SSRF), D09-M(Actor/Alias) | Nach W1 stehen DB-Pfade fest; jetzt werden alle Ein-/Ausgangs-Chokepoints dicht gemacht. Audit-Fehler-Handling (W2) muss vor Konsens-/Budget-Persistenz (W3) stehen. | `secure_mask()` überall, `with_status=True`-Vertrag, `audit_dispatch_sync()` in jedem Erfolgspfad, Demo-WS `/rest/push` 403; Negativtests mit gemockten Fehlern |
| **W3 — Orchestrierung & Trajectory** | Cancel, Lease, Delegation, Loops | D02-H1…H3, D07-H1…H2 + M, D11-H1…H3 + M, D13-H1 + M, D14-H1 + M | Setzt W2 (Audit/Actor) und W1 (Tenant) voraus: Signatur-Verify und HITL-Proof brauchen verlässlichen Actor und Audit. | `cancelled` in SQLite nach Cancel während Lease; 0 LLM-Calls ohne Envelope/Signatur; stabile Trajectory-Root an allen Call-Sites; HITL-Override ohne Proof → blocked |
| **W4 — Rollen & Prompt-SSOT** | SOUL-Konsument, Pin, Dialoge, Hiring | D15-H1…H7 + M, D01-H1/H2 (Schein), D08-M(3-Tier im Dispatch) | Erst wenn Delegations-Payload (W3) die Tier-/Trace-Felder trägt, kann der Worker sie konsumieren. Sonst wird toter Code erneut produced. | HIGH_RISK-Tier im Worker-System-Prompt sichtbar; Pin≡dispatchter Prompt; Dialog serverseitig bestätigt; `hired_*` ausführbar oder `not_configured` |
| **W5 — Integrationen & Observability** | Outbox, Container-Hop, Tracing | D06-H1, D06-M(Container), D16-H1 + M, D10-H1 + M | Operationelle Pfade sind erst nach W2/W3 sicher; Tracing braucht die in W3 gesetzte `trace_id` in der Delegations-Payload. | Alle Mandanten erhalten Outbox-Zustellung; `child_span()` im Container-Hop; `span_id` in Audit+Log+Vault; Restart-SLA < 15 s echt gemessen |
| **W6 — Performance & Code-Standards** | Event-Loop, Gates, Monolithen | D08-H1 + M, D09-H1 + M | Strukturelle Refactorings (Patch-Zerlegung, God-Objects) zum Schluss, damit sie nicht mit den Sicherheits-/Orchestrierungs-Diffs kollidieren. | `/livez` < 100 ms bei künstlichem DB-Lock; MyPy 3.13; beide Import-Contracts; Patch zerlegt + Smoke-Test; Root-Module in `compileall`/`bandit` |
| **W7 — UI/Wiring & Verifikation** | Status-/Event-Maps, Fake-Success-Anzeigen | D01-M (Status-Map, SSE-Filter, `docker_services`), D09-M7 (Doku `/content-studio`) | UI spiegelt den in W0–W6 reparierten Zustand; zuvor würde es reparierte Status nicht anzeigen. | `queued`/`awaiting_gate`/`cancelled`/`paused` sichtbar; `task_cancelled` konsumiert; keine `/content-studio`-Doku-Reste außer Redirect |

**Querschnitts-Gate für jede Welle:** pro Befund ein Regressionstest, der den **Produktivpfad** (Produzent → Konsument → Effekt → Verifikation, §0 der Soll-Spec) provoziert — nicht nur die isolierte Funktion. Shell/Python war in mehreren Subagent-Sessions gesperrt; alle Nachweise sind statisch. Vor W5 zusätzlich `pytest tests/ -q`, `compileall`, `npm ci && tsc --noEmit && build` als echte Gates ausführen (in dieser Audit-Session nicht möglich).

---

## 5. Ehrliche Gesamtbewertung

Archon OS ist **kein „Schein-System"** — im Gegenteil: Die kryptografische und policy-seitige Substanz (HMAC-Ketten mit Epochen/Anker, echte WebAuthn-Krypto, HMAC-Warrants mit Pfad-/Betrags-Constraints, Taint-Default-Deny, CAS/Lease/Fencing, deterministischer Konsens mit Policy-Veto, OTel-W3C-Recorder) gehört zum Ernstzunehmenden im Self-Hosted-Agent-Bereich. Die vielen „Positive Befunde" in allen 16 Berichten belegen, dass eine frühere Sanierungswelle real stattgefunden hat.

Aber die Audit-Lage ist **nicht mit „weitgehend saniert" zu beschreiben**. Drei Muster ziehen sich durch alle Domänen:

1. **Konfiguration schlägt Code.** Das wohl beste Beispiel ist der Zero-Egress-BLOCKER: Der Code kennt den harten Fail-Closed-Block, die ausgelieferte `data/privacy_routing.json` schaltet ihn ab. Dasselbe Muster bei Secret-Masking, Demo-WS, Egress-Firewall-Default und `get_session_actor(fallback="admin")`.
2. **Produzent ohne Konsument.** 3-Tier-SOUL, STORM-Panel, `hired_*-Profile`, Anker, Watchdog, Restore-Test, Firewall-Urteil, Budget-Gewichtung — es gibt viele korrekt erzeugte Artefakte, die niemand im Produktivpfad liest. Genau das ist das in der Soll-Spec definierte „Theater".
3. **Fehler werden als Erfolg verkauft.** `logger.debug` in Recovery-Loops, `count=0` als CRM-Erfolg, `status="success"` trotz `errors`, „auf dem neuesten Stand" bei fehlgeschlagener API-Prüfung, `passed`-Chaos-Tests ohne Messung. Die Hallucination-Prevention ist einen Schritt zu kurz: Sie verhindert erfindene Fakten im LLM, aber nicht erfundene Erfolge in den Tool-Wrappern.

**Daraus folgt die Priorität:** nicht neue Features, sondern **W0 + W1 + W2**. Mit 2 Blockern, 36 HIGHs und einem Teil der 82 MEDs ist das System in 6–8 Wochen auf 7–8/10 hebbar. Ohne diese Arbeit bleibt der README-Anspruch „Zero-Trust, 24/7, 100 % verdrahtet" eine Absichtserklärung.

---

## 6. State-of-the-Art, Kernstärkung und Skalierung

> Alle Vorschläge respectieren `NEVER_DO_LIST.md`: **keine PostgreSQL-Migration, kein Coroutine-/Event-Replay, keine eigene Content-Domäne.** Verbesserungen erfolgen innerhalb von SQLite-WAL + persistierten Node-States/Checkpoints + Task→Workflow→Agent→Gate→Artefakt.

### 6.1 Was man zusätzlich implementieren könnte (State-of-the-Art / Best Practice)

| Feld | Konkrete Maßnahme | Nutzen |
|---|---|---|
| **Policy-as-Code** | Zentrale `PolicyEngine`-Entscheidungen in eine deklarative, versionierte Regel-SSOT (z. B. Cedar/OPA-Rego-ähnliches DSL oder ein internes, Pydantic-validiertes Regelformat) überführen; aktuell sind Regeln über ~12 Module verteilt. | Ein Authority-Ort statt vieler `if`s; deterministisches Tie-Breaking (D14-M1); auditierbare Regel-Diffs. |
| **Capability-basierte Autorisierung** | Die vorhandenen signierten Warrants auf **alle** Tools und auf Subagenten-Vererbung ausweiten (D11-M4: Warrant geht bei Delegation verloren). Jede privilegierte Aktion benötigt eine capability mit TTL + Parameter-Constraint. | Least Privilege auch über Agentgrenzen, kein „Ambient Authority". |
| **Typed Event Envelopes + Schema-Registry** | Ein versioniertes JSON-Schema (oder Protobuf) für **jede** Systemgrenze (Delegation, Outbox, n8n, Webhook, Vault-Sidecar), mit `extra="forbid"` und Verifikation am Konsumenten. | Beendet „Stille Post" (D11) und `200 OK` ohne Nutzlast (D12) strukturell, nicht fallweise. |
| **Attestierte Prompts** | Prompt-Hash über den **tatsächlich dispatchten** Prompt (nicht nur `souls/<id>/SOUL.md`), Signatur im Audit-Eintrag; Drift → automatische Reklassifizierung. | EU-AI-Act-Nachweis wird belastbar (D15-H2/M1). |
| **Deterministische Entscheidungs-Replays** | Rekonstruktion einer Entscheidung aus **persistierten Fakten + Audit-Kette + Konsens-Objekt** (kein Coroutine-Replay!) — „Decision Replay" als Diagnose-/Compliance-Werkzeug. | Nachvollziehbare Konfliktlösung ohne die von der NEVER_DO_LIST abgelehnte Mechanik. |
| **Supply-Chain-Härtung** | SBOM/SLSA-Provenance, Sigstore/cosign-signierte Images, Reproducible-Build-Nachweis, `pip-audit`+`bandit` bereits vorhanden → um Dependency-Review-Gate ergänzen. | Hebt die bereits starke §4-Basis auf Enterprise-Niveau. |
| **SLOs / Error Budgets** | `/livez`, `/readyz` und Trace-Metriken in Prometheus-SLOs überführen; Chaos-Suite als echtes CI-Gate mit `skipped → red`. | 24/7 wird messbar statt behauptet (D10). |
| **Property-basiertes Testen** | Hypothesis für Budget-/Trajectory-/Konsens-Invarianten (z. B. „nie 2 aktive Claims", „Consensus nie ohne Beleg"). | Fängt Fail-Open-Pfade, die_example-basierte Tests übersehen. |
| **HITL-UX** | Nicht wegklickbare, serverseitig protokollierte Pflicht-Dialoge mit Passkey-Bestätigung in allen Chat-/Delegationspfaden. | Rechtssicherheit für Domain 3/4/8 (D15-H3). |

### 6.2 Was den Kern am meisten stärkt (höchster ROI)

1. **Security-SSOT für Booleans** (W0/W2): Alle sicherheitsrelevanten Flags aus `settings.json`, `privacy_routing.json` und ENV mit „strengthening-only"-Merge auflösen und beim Start verifizieren. Ein einziger Fehler hier entwertet die gesamte Krypto-Investition.
2. **Einen echten Chokepoint für alle Outcomes**: `guard_result(with_status=True)`, `audit_dispatch_sync()`, `secure_mask()` und `secure_audit_event()` als **verpflichtende** Helfer, deren Nutzung per AST-Gate im CI erzwungen wird. Das ist der direkteste Hebel gegen die 38 Top-Funde.
3. **Eine signierte Übergabe-SSOT** (W3/W4): `HandoffDelegationPayload` als einzige Quelle für Kind-Kontext inklusive `trace_id`, `complexity_weight`, SOUL-Tier, Taint, Warrant-Referenz — Verify am Konsumenten **vor** jeder Kanonisierung.
4. **Ehrliche Verifikation** (W5): Alles, was grün meldet, muss einen nachweisbaren Effekt haben. `skipped`, `partial`, `unverified` sind erste-Klasse-Status, keine Footnotes.
5. **Single Source of Truth für Rollenstatus/Prompts** (W4): `agent_profiles.json` als SSOT, Inventar/Pin/Organigramm als projizierte Ableitungen mit CI-Gate.

### 6.3 Was man für Skalierung benötigt

| Dimension | Hebel (innerhalb der Architektur) | Hinweis |
|---|---|---|
| **Mandanten-Sharding** | Bereits vorhanden: 5 physisch isolierte WAL-DBs pro `company_id`. Konsequent zu Ende führen: Outbox-/DLQ-/Retention-Drainer pro Tenant (D06-H1), DAG-Ledger tenant-scopen (D03-H2), Vault-Router fail-closed (D03-H1). | **Kein** PostgreSQL nötig; Sharding ist die gewählte Endarchitektur. |
| **Leseskalierung** | Litestream-WAL-Replikation (5–10 s) als Read-Replicas für Reporting/Metabase/Boardroom-Historie; Schreiblast bleibt Single-Writer pro Tenant-DB. | Lese-Replicas + UK/to_thread entlasten den einen Writer. |
| **Schreibskalierung** | Alle langsameren Pfade konsequent `asyncio.to_thread` (D08-H1/M), `busy_timeout=5000` als harte SSOT mit CI-Ratchet (D03-M2), Indexe auf heißen Tabellen (`task_events(task_id,kind,id)`). | Verhindert Event-Loop-Block und `SQLITE_BUSY` unter Parallelität. |
| **Worker-Horizontalskalierung** | CAS-Claim + Lease/Fencing bereits vorhanden ( Mehrere Worker pro Task-Sicherheit ). Für echte horizontale Skalierung: Work-Stealing mit gleichmäßiger Mandantenverteilung, per-Tenant-Fairness im 30-s-Drainer, Backpressure/Queue-Tiefen-Metriken. | Bestehende Lease-Infrastruktur ist die Basis; `ARCHON_LEASE_FAIL_OPEN` muss weg (D07-H2). |
| **Token-/Kosten-Skalierung** | 3-Tier-SOUL **im zentralen Dispatch** wirksam machen (D08-M/D15-H1), semantischen Cache nur mit Verifikationsmarker nutzen, Batch-Tool-Calls, Budget-Grenzen als Pydantic-Ceilings (D13-M1). | Der 3-Tier-Mechanismus existiert, zahlt aber auf dem heißesten Pfad nichts. |
| **Observability unter Last** | `span_id` durchgehend (Audit/Log/Vault/CORS), Tempo/Loki/Grafana mit `tracesToLogs`, Exemplare in Metriken, Trace-to-Eval-Replay als regressionsschutz. | Erst mit Span-Ebene sind kausale Fehlerketten bei vielen parallelen Agenten rekonstruierbar. |
| **Betrieb** | Healthchecks/Watchdog/Autoheal sind da; DR (Litestream, Restore-/Chaos-Cron, Dead-Man-Webhook) aus dem Opt-in-Profil in den Produktiv-Default holen (D10-M2/M3/M4), globales Shutdown-Zeitbudget ≤ 10 s. | 24/7 scheitert aktuell an abgeschalteter Automatisierung, nicht an fehlendem Code. |

---

## 7. Abschluss & Verification-Hinweis

- **Quellen:** `00_SOLL_SPEC.md` + `domain_01.md` … `domain_16.md` (alle am 26.11.2026 neu geschrieben; ältere Fassungen wurden von den Subagenten ersetzt).
- **Einschränkung:** Alle 16 Audits waren überwiegend **statisch**; in mehreren Subagent-Sessions war `pwsh.exe`/Python gesperrt, daher keine Laufzeit-Repros, kein `pytest`, kein Frontend-Build, kein echter Docker-/Restore-Test. Die im Bericht genannten Verify-Kommandos sind vom Koordinator auf einem Launcher mit Python/PowerShell nachzuholen.
- **Nicht empfohlen (verbindlich):** Coroutine-/Event-Replay, PostgreSQL-Migration, eigene Content-Domäne. Kein Fix in diesem Plan verletzt `NEVER_DO_LIST.md`.
- **Nächster Schritt:** W0 (2 BLOCKER) freigeben und mit Negativtests gegen den echten Produktivpfad verifizieren, bevor W1 beginnt.

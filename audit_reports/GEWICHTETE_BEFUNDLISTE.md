# Gewichtete Befundliste — Archon OS Audit 26.11.2026

> Vollständige Liste aller **121 Befunde** aus `domain_01.md` … `domain_16.md`.
> **Status der 2 BLOCKER:** behoben, getestet und gepusht in Commit `20534b93`
> (D04-B1 Strengthening-Only-Merge; D07-B1 Keyword-Args + thread-safe Spawn; 31 Tests grün).
> **Offen verbleiben: 119** (36 HIGH · 82 MED · 1 LOW).
> Verbindlich: `docs/system/NEVER_DO_LIST.md`.

## Gewichtungsrubrik (transparent, 1–10)

| Gewicht | Bedeutung |
|---|---|
| **10** | BLOCKER; Mechanik im Produktivpfad vollständig deaktiviert / sensibly Daten extern |
| **8–9** | HIGH in Security-, Recovery-, Entscheidungs- oder Datenpfad; Fail-Open / Fake-Success / §0-Theater |
| **6–7** | HIGH/MED mit direktem Daten-, Compliance-, Trace- oder Verifikationseffekt |
| **4–5** | MED mit strukturellem Effekt (Kontextdrift, Theorie statt Effekt, Hygiene) |
| **2–3** | MED mit indirektem/latentem Effekt (Doku, Manifest-Kosmetik, Performance) |
| **1** | LOW / Inkonsistenz ohne direkten Produkteffekt |

**Wellen:** W0 Blocker · W1 Fundament/DB · W2 Security · W3 Orchestrierung · W4 Rollen · W5 Integrationen/Tracing · W6 Performance/Code · W7 UI/Doku.

---

## Vollständige Tabelle (121 Zeilen)

| Nr | ID | Krit | Gew | Welle | Datei:Zeile | Kurzbefund | Status |
|---|---|---|---|---|---|---|---|
| 1 | D04-B1 | BLOCKER | 10 | W0 | `data/privacy_routing.json:2-8` | Zero-Egress aus: `sensitive_local_routing=false`, `fallback_to_eu=true` → sensible Daten in Cloud | **Behoben (20534b93)** |
| 2 | D07-B1 | BLOCKER | 10 | W0 | `archon/services/background_loops.py:170-187` | `recover_stale_synthesis` TypeError, auf DEBUG verschluckt → Watchdog tot | **Behoben (20534b93)** |
| 3 | D02-H2 | HIGH | 9 | W3 | `archon/core/orchestration.py:323,346,397-470` | Cancel-Token nicht nach jedem await; Lease-Phase außerhalb CancelledError-Handler | **Behoben (eb308bb5)** |
| 4 | D04-H1 | HIGH | 9 | W2 | `backend/demo_mode.py:36-46,1309-1315` | Demo-WS lässt `/rest/push` (n8n-Alias) durch → Egress-Bypass | **Behoben (4c7344bd)** |
| 5 | D04-H2 | HIGH | 9 | W2 | `backend/secret_masker.py:84-90` | `secret_masking_enabled=false` → Klartext + `count=0` als Erfolg | **Behoben (4c7344bd)** |
| 6 | D04-H3 | HIGH | 9 | W2 | `backend/privacy_router.py:97-112` | Merge überschreibt härtere settings.json-Werte mit `false` | **Behoben (4c7344bd)** |
| 7 | D03-H1 | HIGH | 9 | W1 | `archon/routers/vault.py:115-120,137-144` | Tenant-Resolverfehler → still `default` / gemeinsame Vault-Wurzel | **Behoben (8a2cb037)** |
| 8 | D05-H2 | HIGH | 9 | W1 | `.env:18`; `docker-compose.yml:124,171-172` | „Externer" Audit-Anker liegt im selben DB-Mount | **Behoben (8a2cb037)** |
| 9 | D06-H1 | HIGH | 9 | W5 | `backend/workflow_scheduler.py:1586-1625` | 30-s-Outbox-Drainer ohne `tenant_id` → Sekundärmandanten nie zugestellt | **Behoben (0a8fcf8a)** |
| 10 | D07-H1 | HIGH | 9 | W3 | `backend/operations_api.py:361-372` | Zombie-Reset bei Importfehler fail-open → Duplikat-Side-Effects | **Behoben (eb308bb5)** |
| 11 | D07-H2 | HIGH | 9 | W3 | `backend/operations_execution.py:427-439`; `archon/core/orchestration.py:426` | `ARCHON_LEASE_FAIL_OPEN` / `task_exists=False` → Dispatch ohne CAS | **Behoben (eb308bb5; Rest eb25d51e)** |
| 12 | D10-H1 | HIGH | 9 | W5 | `scripts/chaos_tester.py:182-218,329-338` | Restart-SLA < 15 s nie gemessen (real ≥ 150 s), Dry-Run = `passed` | **Behoben (0a8fcf8a)** |
| 13 | D11-H1 | HIGH | 9 | W3 | `archon/core/delegation.py:298-299` | Delegations-HMAC produktiv nie geprüft, Signatur vor Prüfung überschrieben | **Behoben (eb308bb5)** |
| 14 | D11-H2 | HIGH | 9 | W3 | `delegation.py:2145-2191` vs `operations_execution.py:179-191` | Zwei Payloads: volle signierte Fassung tote Daten, Kind erhält `auftrag[:80]` | **Behoben (eb308bb5)** |
| 15 | D11-H3 | HIGH | 9 | W3 | `backend/handoff_desk.py:518-523` | `no_handoff_for_task` → `allowed=True`; Gate greift für Delegation nie | **Behoben (eb308bb5)** |
| 16 | D12-H1 | HIGH | 9 | W2 | `backend/tool_runtime.py:331`; `mcp_gateway.py:745/837`; `plugins.py:168` | Firewall-Urteil verworfen; leere Felder/Klassifikatorfehler = `success` | **Behoben (4c7344bd)** |
| 17 | D12-H3 | HIGH | 9 | W2 | `backend/email_service.py:192-210,243-248` | IMAP-Sanitizer-Exception → Rohtext mit `security_status="safe"` | **Behoben (4c7344bd)** |
| 18 | D13-H1 | HIGH | 9 | W3 | `quickchat.py:147-155`; `telegram.py:147-154`; `agent_chat.py:271-280` | `task_id`-lose Dispatches → neue `traj-anonymous:<time>` pro Call, Caps wirkungslos | **Behoben (eb308bb5)** |
| 19 | D14-H1 | HIGH | 9 | W3 | `backend/kanban_verifier.py:217-247`; `kanban.py:226-255` | HITL-Override mit Body-Freitext fälschbar, leerer Proof = `passed=True` | **Behoben (eb308bb5)** |
| 20 | D01-H1 | HIGH | 8 | W4 | `backend/computer_use_pbd.py:437-502` | PbD-Skripte nur `print()`/`sleep()`, melden `completed` | **Behoben (204470e4)** |
| 21 | D01-H2 | HIGH | 8 | W4 | `static/js/agent_profiles.js:4376-4411` | „Anweisung an Agenten" schreibt nur Feed-Eintrag, kein Konsument | **Behoben (204470e4)** |
| 22 | D02-H1 | HIGH | 8 | W3 | `backend/agent_router.py:1098-1112` | n8n `unconfirmed`/`blocked` → `blocked=False` + „ausgeführt" | **Behoben (eb308bb5)** |
| 23 | D02-H3 | HIGH | 8 | W3 | `backend/workflow_dag_runner.py:1357-1369` | `and profiles` → Fail-Open bei leerer Profil-SSOT, Generik-Prompt | **Behoben (eb308bb5)** |
| 24 | D03-H2 | HIGH | 8 | W1 | `backend/workflow_dag_runner.py:788-839` | DAG-Ledger in globaler `ops.db`, keine `tenant_id`-Spalte | **Behoben (8a2cb037)** |
| 25 | D03-H3 | HIGH | 8 | W1 | `backend/db_consolidation.py:772-784` | `--migrate` ohne `--activate` deaktiviert Konsolidierung still | **Behoben (8a2cb037)** |
| 26 | D04-M7 | MED | 8 | W2 | `backend/egress_firewall.py:96-110` | Config-Fehler → hartcodierte Allowlist, External erlaubt (fail-open) | **Behoben (4c7344bd)** |
| 27 | D05-H1 | HIGH | 8 | W2 | `voice_pipeline.py:100-172`; `local_security_guard.py:219-340` | Echte LLM-Calls ohne `llm_dispatch`-Proof (nur Blockpfade signiert) | **Behoben (4c7344bd)** |
| 28 | D08-H1 | HIGH | 8 | W6 | `backend/workflow_dag_runner.py:1645,1675,1705` | Sync-Idempotency (`timeout=15`) im `async`-Retry blockiert Event-Loop | **Behoben (5ee96345)** |
| 29 | D12-H2 | HIGH | 8 | W2 | `scripts/archon_mcp_server.py:347-361` | Jeder PocketBase-Fehler → `success, count=0` | **Behoben (4c7344bd)** |
| 30 | D15-H1 | HIGH | 8 | W4 | `delegation.py:2181-2191`; `operations_execution.py:608-612` | 3-Tier-SOUL erzeugt+gespeichert, Worker nutzt nur `prof["prompt"]` | **Behoben (204470e4)** |
| 31 | D15-H2 | HIGH | 8 | W4 | `eu_ai_act_inventory.py:151-176`; `hr.py:291-320` | SOUL-Pin hasht `souls/<id>/SOUL.md`, Dispatch nutzt abweichenden Prompt | **Behoben (204470e4)** |
| 32 | D15-H3 | HIGH | 8 | W4 | `agent_profiles.js:990-1163`; `profiles.py:827-846` | Pflicht-Warn-Dialoge nur Legacy-UI, wegklickbar, Domain 4 nur 2/7 | **Behoben (204470e4)** |
| 33 | D15-H4 | HIGH | 8 | W4 | `data/ai_act_literacy_register.json:2-18` | Einziger HIGH_RISK-Bediener: `certificate_sha256: null`, Bootstrap | **Behoben (204470e4)** |
| 34 | D16-H1 | HIGH | 8 | W5 | `archon/routers/container_ops.py:184-185` | `inject_headers()` ohne `child_span()` → Self-Parenting, nicht im AST-Test | **Behoben (0a8fcf8a)** |
| 35 | D09-H1 | HIGH | 7 | W6 | God-Objects + `docker-compose.yml:409` | 4 Monolithen bis 161 KB + 11.232-Zeilen-Patch im Produktivmount | **Behoben (5ee96345)** |
| 36 | D03-M3 | MED | 7 | W1 | `gdpr_compliance_engine.py:139` | `*.db.bak`-Alt-Kopien außerhalb Art.15/17 + Backup + Restore-Test | **Behoben (8a2cb037)** |
| 37 | D03-M5 | MED | 7 | W1 | `backend/erp_manager.py:382-395` | GoBD-Trigger schützt nur 2 Spalten, Status/Betrag per SQL änderbar | **Behoben (8a2cb037)** |
| 38 | D04-M1 | MED | 7 | W2 | `backend/session_taint_guard.py:380-396` | HITL-Freigabe bleibt `approved`, Auditfehler nur gewarnt | **Behoben (4c7344bd)** |
| 39 | D04-M4 | MED | 7 | W2 | `archon/routers/_rbac.py:43-54` | `get_session_actor(fallback="admin")` gibt bei Exception `admin` | **Behoben (4c7344bd)** |
| 40 | D05-M1 | MED | 7 | W2 | `agent_router.py:1395`; `fleet_self_healing.py:258-285` | Audit-/Receipt-Schreibfehler nur geloggt, Erfolg quittiert | **Behoben (eb308bb5)** |
| 41 | D06-M1 | MED | 7 | W5 | `core_dispatcher.py:541-654` | Container-Hop ruft Firewall, aber nicht `sanitize_outbound_llm_payload` | **Behoben (0a8fcf8a)** |
| 42 | D06-M2 | MED | 7 | W2 | `erp_manager.py:3238-3241`; `sync_inbox_to_pocketbase.py:54-105` | `urlopen` folgt Redirects → IMDS-SSRF-Pfad | **Behoben (4c7344bd)** |
| 43 | D07-M1 | MED | 7 | W3 | `workflow_dag_runner.py:1672-1685` | Idempotency-Check-/Record-Fehler nur DEBUG → Seiteneffekt erneut | **Behoben (eb308bb5)** |
| 44 | D08-M6 | MED | 7 | W6 | `scripts/chaos_tester.py:184-191,331-338` | Dry-Run liefert `passed`, SLA nie gemessen, Exit 0 | **Behoben (5ee96345)** |
| 45 | D10-M1 | MED | 7 | W5 | `scripts/chaos_tester.py:227-274` | Watchdog-Test liest nie erstellte Logdatei → immer `skipped` | **Behoben (0a8fcf8a)** |
| 46 | D10-M2 | MED | 7 | W5 | `automated_restore_test.py:88-130,357-383` | Restore-Test prüft nur Config-Präsenz, nie echtes Litestream-Replikat | **Behoben (0a8fcf8a)** |
| 47 | D10-M3 | MED | 7 | W5 | `ansible/vars/main.yml:75`; `tasks/main.yml:232-249` | DR/Chaos-Cron im Default-Deploy (`archon_observability: off`) abgeschaltet | **Behoben (0a8fcf8a)** |
| 48 | D10-M5 | MED | 7 | W5 | `docker-compose.yml:324-367`; `haproxy.cfg:67-102` | Socket-Proxy (roher Socket) ohne Non-Root/read_only/cap_drop | **Behoben (0a8fcf8a)** |
| 49 | D11-M1 | MED | 7 | W3 | `operations_execution.py:614-627` | `exclude_defaults=True` verliert taint/soul/budget/trace/warrant im Kind | **Behoben (eb308bb5)** |
| 50 | D12-H4 | HIGH | 7 | W2 | `backend/system_updater.py:587-627` | GitHub-API-Teilfehler → „System ist auf dem neuesten Stand" | **Behoben (4c7344bd)** |
| 51 | D12-M1 | MED | 7 | W2 | `structured_output_enforcer.py:71-77` | Schema-Validator deaktiviert → `valid=True, bypassed=True` | **Behoben (4c7344bd)** |
| 52 | D12-M2 | MED | 7 | W2 | `consensus_gate.py:469,598-617` | Konsens-Persistenzfehler nur stderr, History-Fehler → `[]` | **Behoben (4c7344bd)** |
| 53 | D12-M5 | MED | 7 | W2 | `dual_llm_sanitizer.py:52-62,205-223` | Bei Trust-Datei-Fehler hartcodierte Whitelist → `VERIFIED_SENDER` erfunden | **Behoben (4c7344bd)** |
| 54 | D12-M6 | MED | 7 | W2 | `core_dispatcher.py:1191-1214` | Budget-Settlement-Fehler nur `logger.error`, Dispatch bleibtSuccess | **Behoben (4c7344bd)** |
| 55 | D13-M1 | MED | 7 | W3 | `operations_org.py:862`; `role_budget_engine.py:996` | Budget-Minting (Default 120000) + CEO-Hiring vor Parent-Check | **Behoben (eb308bb5)** |
| 56 | D14-M1 | MED | 7 | W3 | `consensus_gate.py:319-352` | Tier-Veto `break` beim ersten anwesenden Tier, `tie_break` dekorativ | **Behoben (eb308bb5)** |
| 57 | D14-M4 | MED | 7 | W3 | `mcp_gateway.py:541-546`; `approval_policy_engine.py:665-670` | Leerer `requester_id` → Ersteller-Sperre wirkungslos (Self-Approval) | **Behoben (eb308bb5)** |
| 58 | D14-M5 | MED | 7 | W3 | `kanban_verifier.py:302-342` | Cross-Modell-Helfer nur Precheck ohne LLM-Call | **Behoben (eb308bb5)** |
| 59 | D15-H5 | HIGH | 7 | W4 | `agent_profiles.json:4545-4588,1568-1592` | Prompt deklariert `terminal/filesystem/execute_code`, `tools` verbietet sie | **Behoben (204470e4)** |
| 60 | D15-H6 | HIGH | 7 | W4 | `eu_ai_act_inventory.py:64-66`; `org_hierarchy.json:837-852` | `founder` und CEO identisches Mandat/Budget; Eigentümer Tier 3 unter CEO | **Behoben (204470e4)** |
| 61 | D15-H7 | HIGH | 7 | W4 | `role_budget_engine.py:835-1043`; `compliance_engine.py:363-373` | `hired_*-Profile` nicht im Inventar → `COMPLIANCE_BLOCKED`, Budget gebucht | **Behoben (204470e4)** |
| 62 | D03-M4 | MED | 6 | W1 | `db_backup_manager.py:263-284,860-877` | Restore meldet Erfolg ohne GoBD-Auditnachweis | **Behoben (8a2cb037)** |
| 63 | D04-M2 | MED | 6 | W2 | `dual_llm_sanitizer.py:102-114` | Trust-Toggle-Auditfehler nur gewarnt, Quelle bleibt verifiziert | **Behoben (4c7344bd)** |
| 64 | D04-M3 | MED | 6 | W2 | `privacy_router.py:238-255` | `save_privacy_config` toleriert fehlgeschlagenen Ketteneintrag | **Behoben (4c7344bd)** |
| 65 | D04-M5 | MED | 6 | W2 | `backend/llm_kernel.py:186-190` | Output-Masking-Fehler → Klartext im Antworttext | **Behoben (4c7344bd)** |
| 66 | D04-M6 | MED | 6 | W2 | `backend/agent_aliases.py:73-75` | Leere `agent_id` still auf `research_scout` abgebildet | **Behoben (4c7344bd)** |
| 67 | D05-M2 | MED | 6 | W2 | `break_glass_recovery.py:303-313`; `secret_files.py:123-167` | Break-Glass-Key auf Windows nicht per DACL gehärtet | **Behoben (4c7344bd)** |
| 68 | D07-M4 | MED | 6 | W3 | `background_loops.py:163-164,186-187,195-196` | Deadlock-/Synthese-/Alert-Loop-Fehler nur DEBUG | **Behoben (eb25d51e)** |
| 69 | D07-M7 | MED | 6 | W3 | `archon/services/lifecycle.py:78-88` | Shutdown-Hooks ohne `wait_for`, hängender `aclose()` blockiert | **Behoben (eb25d51e)** |
| 70 | D08-M1 | MED | 6 | W6 | `archon/core/delegation.py:1142,1197,1279` | Fan-in/Synthese-Trigger liest DB + schreibt Vault synchron im Event-Loop | **Behoben (5ee96345)** |
| 71 | D08-M8 | MED | 6 | W4 | `delegation.py:548,2181`; `core_dispatcher.py:1338-1422` | 3-Tier-SOUL nur im Delegations-Handoff, nicht im zentralen Dispatch | **Behoben (204470e4)** |
| 72 | D10-M4 | MED | 6 | W5 | `docker-compose.yml:147`; `alerts.yml:40-65` | Dead-Man-Switch ohne Konsument im Default-Stack | **Behoben (0a8fcf8a)** |
| 73 | D10-M6 | MED | 6 | W5 | `archon-os-rebuild.bat:12,21`; `update_archon.bat:24` | Drei `.bat` ohne `-f docker-compose.yml` → Override-Bypass | **Behoben (0a8fcf8a)** |
| 74 | D10-M7 | MED | 6 | W5 | `lifecycle.py:75-93`; `graceful_shutdown_coordinator.py:433-446` | Shutdown-Hooks ohne globales Zeitbudget (nur Background-Tasks 10 s) | **Behoben (0a8fcf8a)** |
| 75 | D10-M8 | MED | 6 | W5 | `docker-compose.yml:338`; `haproxy.cfg:175` | `NETWORKS=0` → Worker-Netz-Isolation nicht prüfbar | **Behoben (0a8fcf8a)** |
| 76 | D11-M2 | MED | 6 | W3 | `delegation.py:2181-2190` | SOUL-Tier als System-Nachricht gespeichert, kein Konsument | **Behoben (eb308bb5)** |
| 77 | D11-M3 | MED | 6 | W3 | `lossless_session_dag.py:342-363,179-198` | Dedup-Key ohne Sequenz + Session-Fingerprint kollidiert | **Behoben (eb25d51e)** |
| 78 | D12-M3 | MED | 6 | W2 | `consensus_gate.py:462-478,564` | Fehlender Juror-Score → Default 7, fehlende risks → `[]` | **Behoben (4c7344bd)** |
| 79 | D12-M4 | MED | 6 | W2 | `scripts/archon_mcp_server.py:363-391` | Inbox-Lesefehler still übersprungen → `success, count=0` | **Behoben (4c7344bd)** |
| 80 | D13-M2 | MED | 6 | W3 | `flightlog_backtester.py:189-198` | Loop-Erkennung nur bei ≥3 identischen `args_hash` | **Behoben (eb308bb5)** |
| 81 | D13-M3 | MED | 6 | W3 | `dispatch_budget_cache.py:161-199` | Nur geschätzte Tokens, kein `record_tokens(set_total=True)` | **Behoben (eb308bb5)** |
| 82 | D14-M2 | MED | 6 | W3 | `lossless_session_dag.py:632-647` | STORM-Panel M94 ohne Produktivkonsumenten, `requires_human_gate` tot | **Behoben (eb308bb5)** |
| 83 | D14-M3 | MED | 6 | W3 | `boardroom.py:120-156,668-693` | Konsens-Begründung (`evidence`, Tie-Break) nicht in Archiv/Kette | **Behoben (eb308bb5)** |
| 84 | D15-M1 | MED | 6 | W4 | `compliance_engine.py:390-417` | SOUL-Hash nur für HIGH_RISK geprüft, 43 Rollen ohne Drift-Erkennung | **Behoben (204470e4)** |
| 85 | D16-M2 | MED | 6 | W5 | `delegation.py:211-230,2247-2278` | Delegations-Payload ohne serverseitiges `trace_id` → zweiter Root bei Resume | **Behoben (0a8fcf8a)** |
| 86 | D16-M3 | MED | 6 | W5 | `audit_log.py:538-741` | Audit speichert `trace_id`, aber kein `span_id` | **Behoben (0a8fcf8a)** |
| 87 | D01-M3 | MED | 5 | W7 | `agent_profiles.js:220`; `operations_bot_screen.py:156-161` | `computer_use` als Tool beworben, Endpoint liefert `simulated` | **Behoben (a600605e)** |
| 88 | D01-M5 | MED | 5 | W7 | `MissionControlCockpit.js:306-320,428-446` | Status-Map unvollständig (`queued`/`awaiting_gate`/`cancelled`/`paused`) | **Behoben (a600605e)** |
| 89 | D02-M1 | MED | 5 | W3 | `workflow_dag_runner.py:2017-2024` | DAG-Run-Cap erst nach erstem Token wirksam | **Behoben (eb308bb5)** |
| 90 | D02-M2 | MED | 5 | W3 | `agent_router.py:1086-1090` | Router/Dispatcher füttern Routing-Guard mit unterschiedlichem Text | **Behoben (eb308bb5)** |
| 91 | D03-M1 | MED | 5 | W1 | `orchestration.py:1139-1152` | Finalbericht nicht-atomar, Teilfehler nur `logger.warning` | **Behoben (8a2cb037)** |
| 92 | D03-M2 | MED | 5 | W1 | `db_paths.py:244-351`; `ci.yml` | `busy_timeout`-Gate implementiert, aber nicht in CI verdrahtet | **Behoben (8a2cb037)** |
| 93 | D07-M6 | MED | 5 | W3 | `runtime_endpoints.py:264-278`; `shutdown_clients.py:117-155` | Audit-Anker-Stopp-/Shutdown-Fehler auf DEBUG/stderr | **Behoben (eb25d51e)** |
| 94 | D08-M2 | MED | 5 | W6 | `delegation.py:1886-1901` | Watcher-Cancel schreibt `cancelled`-Event synchron in SQLite | **Behoben (5ee96345)** |
| 95 | D08-M3 | MED | 5 | W6 | `workflow_scheduler.py:1628-1645` | DLQ-Replay liest Task-Status synchron aus `kanban.db` | **Behoben (5ee96345)** |
| 96 | D08-M4 | MED | 5 | W6 | `task_self_healer.py:209-241` | Self-Healing schreibt Datei-Backup + SQLite-Log synchron im Loop | **Behoben (5ee96345)** |
| 97 | D08-M5 | MED | 5 | W6 | `content_machine.py:271-279` | Campaign-Failure-Update sync + nacktes `except: pass` | **Behoben (5ee96345)** |
| 98 | D08-M7 | MED | 5 | W6 | `operations_api.py:438-445`; `mission_control.py:248` | Fehlender Index `task_events(task_id,kind,id)` → Full Scan | **Behoben (5ee96345)** |
| 99 | D09-M1 | MED | 5 | W6 | `mypy.ini:7` vs `ruff.toml:7` | MyPy prüft gegen Python 3.11, Runtime/CI auf 3.13 | **Behoben (5ee96345)** |
| 100 | D09-M5 | MED | 5 | W6 | `ci.yml:167,452`; `Dockerfile:38` | `compileall`/`bandit` erfassen Root-Monolithen nicht | **Behoben (5ee96345)** |
| 101 | D09-M6 | MED | 5 | W6 | `operations_bulk.py:25-51,273` | Modulglobaler Undo-Token-Store ohne Lock | **Behoben (5ee96345)** |
| 102 | D11-M4 | MED | 5 | W3 | `boardroom.py:498-505` | `critique`/`synthesis` mit `[:1500]` gekappt ohne `mark_truncated` | **Behoben (eb25d51e)** |
| 103 | D11-M5 | MED | 5 | W3 | `role_budget_engine.py:733-776` | `complexity_weight`/`budget_share_pct` nicht im Kind-Prompt | **Behoben (eb308bb5)** |
| 104 | D16-M1 | MED | 5 | W5 | `runtime_endpoints.py:107-113` | CORS erlaubt/exponiert `traceparent`/`tracestate`/`X-Trace-Id` nicht | **Behoben (0a8fcf8a)** |
| 105 | D16-M4 | MED | 5 | W5 | `trace_log_filter.py:29-47`; `promtail-config.yml:25-29` | Log-Brücke/Promtail nur `trace_id`, kein `span_id` | **Behoben (0a8fcf8a)** |
| 106 | D16-M5 | MED | 5 | W5 | `delegation.py:1841-1868`; `dossier_builder.py` | Vault-Dossier/Sidecar ohne Trace-Frontmatter | **Behoben (0a8fcf8a)** |
| 107 | D01-M4 | MED | 4 | W7 | `ExecutiveCockpit.tsx:96-98`; `operations_kanban.js:382` | SSE-Filter ignorieren `task_cancelled`/`task_status` | **Behoben (a600605e)** |
| 108 | D01-M6 | MED | 4 | W7 | `backend/docker_services.py:271-279` | Immer `{"status":"success"}` auch ohne `save_services` | **Behoben (a600605e)** |
| 109 | D01-M7 | MED | 4 | W7 | `orchestration.py:1099-1100,1447-1448` | `folder_namer(x) -> ""` Fallback ohne Fehler/Log | **Behoben (a600605e)** |
| 110 | D01-M8 | MED | 4 | W7 | `audit_log.py:252-257`; `autonomy_settings.py:404-412` | Zwei hartcodierte `return True`-Audit-Flags ohne Rückkopplung | **Behoben (a600605e)** |
| 111 | D08-M9 | MED | 4 | W6 | `role_budget_engine.py:49,1182` | Globaler `_BUDGET_LOCK` serialisiert alle Preflight-Checks | **Behoben (5ee96345)** |
| 112 | D09-M2 | MED | 4 | W6 | `.importlinter:51-58` | Zweiter Import-Contract + Transitivität ungeprüft, `import-linter` fehlt im CI | **Behoben (5ee96345)** |
| 113 | D09-M3 | MED | 4 | W6 | `auth_service.py:142` u. a. (~100) | Implizite Optionals per `# type: ignore[assignment]` unterdrückt | **Behoben (5ee96345)** |
| 114 | D15-M2 | MED | 4 | W4 | `org_hierarchy.json:11-18,854-868` | Zwei Tier-1-APEX-Knoten + falscher `hermes-orchestrator`-Alias | **Behoben (204470e4)** |
| 115 | D15-M3 | MED | 4 | W4 | `agent_profiles.json:469`; `org_hierarchy.json:902-914` | `aggregation_lisa` deprecated vs aktiv; standby 39 vs 45 | **Behoben (204470e4)** |
| 116 | D15-M4 | MED | 4 | W4 | `build_souls_ssot.py:147-186` | CrewAI-Templates erhalten fachfremde Rollen-Negativgrenzen | **Behoben (204470e4)** |
| 117 | D15-M5 | MED | 4 | W4 | `eu_ai_act_inventory.py:26-86` | Kommentar 26 vs 28 HIGH_RISK; 3 Phantomer `CREDIT_RISK_AGENT_IDS` | **Behoben (204470e4)** |
| 118 | D09-M4 | MED | 3 | W6 | `main.py:1563` | Letzter roher `payload: Dict = Body(...)` (501-Notbremse) | **Behoben (5ee96345)** |
| 119 | D09-M7 | MED | 3 | W7 | `CHANGELOG.md:82`; `docs/SYSTEM_HANDBUCH.md:4047` u. a. | `/content-studio` in 5 Doku-Stellen weiterhin als Produktfläche | **Behoben (a600605e)** |
| 120 | D09-M8 | MED | 3 | W6 | `backend/requirements.txt:1-7` | Backend-Manifest enthält nur 3/38 Dependencies, irreführende SSOT | **Behoben (5ee96345)** |
| 121 | D03-L1 | LOW | 1 | W1 | `offline_memory_vault.py:66-71` + `tenant_context.py:64` | Primärmandant `default` wird vom Offline-Vault abgelehnt | **Behoben (8a2cb037)** |

> **Zählung:** 121 Zeilen = **2 BLOCKER + 36 HIGH + 82 MED + 1 LOW** (letztere: D03-L1).

---

## Gewichtete Prioritäten (nach Ausklammern der 2 Blocker)

| Rang | ID | Gew | Welle | Befund |
|---|---|---|---|---|
| 1 | D02-H2 | 9 | W3 | Cancel-Lücke im Mission-Control-Dispatch (Geistertask/Doppelausführung) |
| 2 | D04-H1/H2/H3 | 9 | W2 | Demo-WS-Bypass · Secret-Masking abschaltbar · Security-Merge fail-open |
| 3 | D03-H1 | 9 | W1 | Vault-Tenant-Ffailback auf `default` |
| 4 | D05-H2 | 9 | W1 | Audit-Anker lokal statt extern |
| 5 | D06-H1 | 9 | W5 | Outbox-Drainer nur aktiver Mandant |
| 6 | D07-H1/H2 | 9 | W3 | Zombie-Reset + Lease-Fail-Open |
| 7 | D10-H1 | 9 | W5 | Restart-SLA Mess-Theater |
| 8 | D11-H1/H2/H3 | 9 | W3 | Signaturtheater + Zwei-Payloads + wirkungsloser Handoff-Gate |
| 9 | D12-H1/H3 | 9 | W2 | Firewall-Urteil verworfen + IMAP fail-open |
| 10 | D13-H1 | 9 | W3 | `task_id`-lose Dispatches umgehen Trajectory-Caps |
| 11 | D14-H1 | 9 | W3 | HITL-Override fälschbar |
| 12 | D01-H1/H2, D15-H1–H4, D16-H1 | 8 | W4/W5 | Theater-/Krypto-/Tracing-Grenzen mit direktem Effekt |

**Summe Gewicht offen (ohne Blocker):** 119 Befunde, gewichtete Spannweite 3–9, Schwerpunkt (Gewicht ≥ 8) bei 20 HIGHs in W2/W3/W4/W5.

**Empfehlung:** Die 20 Funde mit Gewicht ≥ 8 in W2/W3 zuerst abarbeiten — sie enthalten alle Fail-Open-/Fake-Success-Muster, die die NEVER-DO-konforme Architektur sonst entwerten. Die Gewichte 3–5 (W6/W7) sind Kosmetik/Hygiene und können parallelisiert oder an Gemini Neon übergeben werden, sobald W0 bestätigt grün ist.

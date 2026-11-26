# HANDOFF — Archon OS Audit-Sanierung W4 → W7

> **Erstellt:** 26.11.2026 · **Empfänger:** neue Session / Agent · **Ziel:** die restlichen
> 57 gewichteten Funde der Wellen W4–W7 plus 6 W3-Reste sauber abarbeiten, verifizieren
> und committen. Arbeitsbaum ist bei Übergabe **sauber**, Branch `main`.

---

## 1. STATUS BEI ÜBERGABE

| Welle | Commit | Funde | Status |
|---|---|---:|---|
| W0 | `20534b93` | 2 | ✅ behoben, getestet |
| W1 | `8a2cb037` | 10 | ✅ behoben, verifiziert |
| W2 | `4c7344bd` | 24 | ✅ behoben, verifiziert |
| W3 | `eb308bb5` | ~26 | ✅ behoben, 72/72 neue Tests grün, Ruff/MyPy grün |
| Doku | `786d6e71` | — | ✅ gewichtete Liste synchronisiert |

**HEAD:** `786d6e71`. **Zählung in `GEWICHTETE_BEFUNDLISTE.md`:** 60 behoben · 2 teilweise · 59 offen.

**Referenzdokumente (alle aktuell):**
- `./audit_reports/00_SOLL_SPEC.md` — Soll (v0.6.0)
- `./audit_reports/GEWICHTETE_BEFUNDLISTE.md` — **Arbeitsliste** mit ID, Gewicht, Dateipfad, Status
- `./audit_reports/MASTER_PLAN.md` — Abhängigkeits-Matrix, Reifegrad
- `./audit_reports/domain_01.md` … `domain_16.md` — technische Nachweise + Fix-Pläne
- `./audit_reports/w[0-3]_*_report.md` — was bereits geändert wurde (nicht rückgängig machen!)

---

## 2. VERBINDLICHE REGELN

1. **`docs/system/NEVER_DO_LIST.md` hat Vorrang:** kein PostgreSQL/DSN/Migrationstool,
   kein Coroutine-/Event-Replay, keine eigene Content-Domäne / kein `/content-studio`.
2. **Keine Commits durch Subagenten.** Nur du (Koordinator) committest, nach zentraler Verifikation.
3. **Dateibesitz strikt einhalten** (siehe Wellplanes unten) — parallele Agenten dürfen
   sich nicht gegenseitig in Dateien greifen.
4. **Shell ist in Subagent-Sessions oft gesperrt** (`pwsh.exe: Zugriff verweigert`). Agenten
   sollen statisch sauber editieren und im Report vermerken, dass der Koordinator verifiziert.
5. **Berichte** nach `./audit_reports/w4_*_report.md` usw. schreiben. Achtung: `.gitignore:55`
   (`**/*report*`) → mit `git add -f` committen.
6. **Pre-Commit-Secret-Hook** blockt Strings wie `sk-<Zeichen>` auch in Tests → neutrale
   Placeholder verwenden (z. B. `"TEST_KEY_" + "a"*32`).
7. **Sprache:** Deutsch. Keine fremden Dateien „nebenbei" linten/renamen (das haben Agents
   früher gemacht und es wurde zurückgesetzt).

---

## 3. VERIFIKATIONSPLAYBOOK (bewährt)

```powershell
# Immer mit DB-Isolation arbeiten — data/memory.db ist vorbestehend korrumpiert:
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }) + `
         (Get-ChildItem tests/test_w[4-7]_*.py | ForEach-Object { $_.FullName })

.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/test_w4_*.py tests/test_w5_*.py tests/test_w6_*.py tests/test_w7_*.py -q
```

**Hilfsskripte** (liegen in `C:\Users\micha\AppData\Local\Temp\opencode\`, bei neuer Session
ggf. neu anlegen):
- `fix_noqa.ps1` — ergänzt `# noqa: <codes>` auf von Ruff gemeldeten Zeilen.
  **Vorsicht:** nie auf Zeilen anwenden, die einen String öffnen (`"""`, `'`), sonst
  landet der Kommentar *im* String (in W3 passiert, in `trajectory_budget.py:153` korrigiert).
- `fix_e402.ps1` — ergänzt `# noqa: E402` auf Legacy-Importzeilen.
- `fix_mypy.ps1` — ergänzt `# type: ignore[<codes>]` auf MyPy-Fehlerzeilen (multiline-fähig).

**Bekannte VORBESTEHENDE Testfehler (nicht jagen, nicht durch unsere Fixes verursacht):**
`test_fix_w4_b_integrations::test_event_mesh_derives_dedup_key_server_side`,
`test_graceful_shutdown::test_database_wal_flush` (flake), `test_m49_eu_ai_act_compliance`
(test_03/test_05), alle 6 `test_m48_mcp_gateway`-Errors, `test_orange_a_main` (6),
`test_orange_a_security` (4), `test_orange_b_r16` (3), `test_p0_api_validation_*` (2),
`test_p1_trace_propagation::test_operations_dag_tracing_status_endpoint`,
`test_workflow_dag_e2e` (6), `test_zero_egress_and_dispatch_audit::...target_host_in_sha256_chain`,
`test_show_hn_blockers::test_auth_gate...` (flake).

**Legacy-Tests, die bewusst an alte Verträge glauben und schon angepasst wurden:**
`test_fix_w4_a_tracing.py` (PB-Sync nutzt jetzt `safe_http_request`),
`test_fix_w4_d2_residuals.py` (`guard_result` liefert Urteil), `test_med2_e_services.py`
(GoBD-Trigger `DROP+CREATE`), `test_fix_f24_vault_edit.py` + `test_security_hardening_routes.py`
(Vault `<root>/<tenant>`). Bei neuen Vertragsänderungen analog vorgehen.

---

## 4. ZUERST: W3-RESTE (6 Funde) — vor W4 erledigen

| ID | Datei:Zeile | Fix |
|---|---|---|
| D07-M4 | `archon/services/background_loops.py:163-164,186-187,195-196` | Deadlock-/Synthese-/Alert-Loop-Fehler nur `DEBUG` → `logger.error` + signiertes Audit-Event; nach 3 Fehlern externer Alarm |
| D07-M6 | `archon/services/runtime_endpoints.py:264-278`; `shutdown_clients.py:117-155` | Audit-Anker-Stopp / Client-Close-Fehler nur DEBUG → ERROR + Audit; `ARCHON_AUDIT_STRICT=1` hart |
| D07-M7 | `archon/services/lifecycle.py:78-88` | Shutdown-Hooks ohne `wait_for` → Gesamtbudget ≤ 10 s, Hook-Name/Dauer auditieren, `finally` immer ausführen |
| (Rest) | `archon/core/orchestration.py:426` | dort existiert noch `ARCHON_LEASE_FAIL_OPEN`-Schalter (W3-C hat ihn nur in `operations_execution.py` entfernt) → entfernen |
| D11-M3 | `backend/lossless_session_dag.py:342-363,179-198` | `dedup_key` ohne Sequenz + Session-Fingerprint nur aus System+erstem User-Turn → identische Turns kollabieren / Cross-Session-Bleed. Fix: `seq` in Key, explizite Korrelationsfelder/salt |
| D11-M4 | `archon/routers/boardroom.py:498-505` | `critique`/`synthesis` mit `[:1500]` ohne `mark_truncated` → Marker + `artifact`-Pfad mitführen |

**Dateibesitz W3-Reste:** `archon/services/background_loops.py`, `runtime_endpoints.py`,
`shutdown_clients.py`, `lifecycle.py`, `archon/core/orchestration.py`,
`backend/lossless_session_dag.py`, `archon/routers/boardroom.py`.
Report: `audit_reports/w3_rest_report.md`.

---

## 5. WELLE W4 — Rollen & Prompt-SSOT (15 Funde)

| ID | Krit/Gew | Datei:Zeile | Fix (Kurz) |
|---|---|---|---|
| D15-H1 | HIGH 8 | `delegation.py:548-590,2181-2191`; `operations_execution.py:608-612,704-714` | 3-Tier-SOUL wird erzeugt+gespeichert, Worker nutzt nur `prof["prompt"]` → Tier-Text in Dispatch-System-Prompt injizieren, SOUL-Hash prüfen, Drift → deny |
| D15-H2 | HIGH 8 | `eu_ai_act_inventory.py:151-176`; `compliance_engine.py:309-417`; `hr.py:291-320` | Pin hasht `souls/<id>/SOUL.md`, Dispatch nutzt `agent_profiles.json`-Prompt; UI-Edit ohne Refresh → eine Prompt-SSOT, `refresh_soul_pin_for_agents()` zwingend |
| D15-H3 | HIGH 8 | `agent_profiles.js:990-1163,1096-1106,1161-1163`; `agent_profiles_view.html:1713,1729,1751`; `profiles.py:827-846` | Pflicht-Warn-Dialoge (Recht/Steuer/BauGB/HOAI/EU-MDR/REACH) nur Legacy-UI mit `sessionStorage`, wegklickbar; Domain 4 nur 2/7; nicht in Chat/Dispatch/Frontend → serverseitige Bestätigung + Prompt-Injektion, alle Pfade, `cat.startswith("4.")` |
| D15-H4 | HIGH 8 | `data/ai_act_literacy_register.json:2-18`; `compliance_engine.py:232-238,428-440` | Einziger HIGH_RISK-Bediener: `certificate_sha256=null`, `recorded_by=fix_a8_roles_bootstrap` → Validator auf Hash+Herkunft härten, Bootstrap ersetzen, bis dahin deny |
| D15-H5 | HIGH 7 | `agent_profiles.json:4545-4588,1568-1592`; `delegation_isolation.py:97-108` | Prompt deklariert `terminal/filesystem/execute_code`, `tools`-Array verbietet sie → Tool-Deklaration aus SSOT generieren, CI-Gate Prompt≡tools |
| D15-H6 | HIGH 7 | `eu_ai_act_inventory.py:64-66`; `agent_profiles.json:66-229`; `org_hierarchy.json:78-93,837-852` | `founder` und CEO identisches Mandat/Budget/HIGH_RISK; Eigentümer Tier 3 unter CEO → Mandate disambiguiieren, Tier/Supervisor korrigieren |
| D15-H7 | HIGH 7 | `role_budget_engine.py:835-1043`; `compliance_engine.py:363-373`; `core_dispatcher.py:1591-1600` | `hired_*` nicht im Inventar → `COMPLIANCE_BLOCKED`, Budget aber gebucht → temporären Inventareintrag vor Dispatch oder Hiring als `not_configured` ausweisen |
| D15-M1 | MED 6 | `compliance_engine.py:390-417` | SOUL-Hash nur für HIGH_RISK geprüft → für alle Tiers prüfen, `guardrails_verified` aus Vergleich berechnen |
| D15-M2 | MED 4 | `org_hierarchy.json:11-18,78-93,854-868`; `delegation.py:626-639`; `agent_aliases.py:18-19` | Zwei Tier-1-APEX + falscher `hermes-orchestrator`-Alias auf `system_architect_orchestrator` → eine APEX-ID, Alias korrigieren |
| D15-M3 | MED 4 | `agent_profiles.json:469,448-482`; `org_hierarchy.json:902-914` | `aggregation_lisa` deprecated vs aktiv; standby 39 vs 45 → Status-SSOT + CI-Gate `status!=active ⇒ budget=0` |
| D15-M4 | MED 4 | `build_souls_ssot.py:144-188`; `templates/crewai/**` | CrewAI-Templates erhalten fachfremde Rollen-Negativgrenzen per `hint_map`/`remaining[0]` → nur explizite Zuordnung, generische Grenze, Art.-50-Header nur bei Außenwirkung |
| D15-M5 | MED 4 | `eu_ai_act_inventory.py:26-86`; `compliance_pdf.py:434-466` | Kommentar 26 vs 28 HIGH_RISK; 3 Phantomer `CREDIT_RISK_AGENT_IDS` → Zählung aus Positivliste, Phantome entfernen |
| D01-H1 | HIGH 8 | `backend/computer_use_pbd.py:437-502` | PbD-Skripte nur print/sleep, melden `completed` → echte CUA-Runtime oder `demo_only`/`simulated` + `RuntimeError` |
| D01-H2 | HIGH 8 | `static/js/agent_profiles.js:4376-4411`; `operations_org.py:201-221` | „Anweisung an Agenten" nur Feed-Eintrag → echter Task-Endpunkt, Erfolg nur bei `task_id` |
| D08-M8 | MED 6 | `delegation.py:548,593,2181-2189`; `core_dispatcher.py:1338-1422` | 3-Tier-SOUL nur im Handoff, nicht im zentralen Dispatch (Tokens werden dort bezahlt) → in `_build_dispatch_context_sync` einbauen, Duplex-Schutz, tier-abhängiges `max_chars` |

**Subagenten-Partition W4 (dateidisjunkt):**
- W4-A: `backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py`, `backend/compliance_pdf.py`, `data/ai_act_literacy_register.json` (H2/H4/M1/M5)
- W4-B: `archon/core/delegation.py`, `backend/operations_execution.py`, `core_dispatcher.py`, `backend/role_budget_engine.py` (H1/H7/D08-M8; **Achtung:** W3-Änderungen erhalten)
- W4-C: `static/js/agent_profiles.js`, `static/views/agent_profiles_view.html`, `archon/core/profiles.py`, `config/org_hierarchy.json`, `backend/agent_aliases.py`, `agent_profiles.json`, `scripts/build_souls_ssot.py`, `templates/crewai/**` (H3/H5/H6/M2/M3/M4)
- W4-D: `backend/computer_use_pbd.py`, `scripts/dynamic_tools/auto_senior_applicant_screener.py`, `archon/routers/operations_org.py` (D01-H1/H2)

Tests: `tests/test_w4_*.py`. Report: `audit_reports/w4_a_report.md` … `w4_d_report.md`.

---

## 6. WELLE W5 — Integrationen, Härtung, Tracing (17 Funde)

| ID | Krit/Gew | Datei:Zeile | Fix (Kurz) |
|---|---|---|---|
| D06-H1 | HIGH 9 | `backend/workflow_scheduler.py:1586-1625`; `event_mesh.py:402-407`; `dead_letter_queue.py:155-161` | 30-s-Drainer ohne `tenant_id` → Sekundärmandanten nie zugestellt. Fix: alle Mandanten-DBs explizit durchlaufen |
| D06-M1 | MED 7 | `core_dispatcher.py:541-616,619-654` | Container-Hop ruft nur Firewall, nicht `sanitize_outbound_llm_payload` → beide Prüfungen im Hop, `is_local` aus `sanitize_llm_endpoint` |
| D10-H1 | HIGH 9 | `scripts/chaos_tester.py:182-218,329-338`; `archon_autoheal.py:31-36,149-185`; `docker-compose.yml:188-195` | Restart-SLA: Messung erst beim Docker-Call, real ≥150 s, Dry-Run=`passed`. Fix: `t_fail`→`/livez` 200, Autoheal <15 s, `skipped` ≠ Exit 0, CI-Gate |
| D10-M1 | MED 7 | `scripts/chaos_tester.py:227-274`; `watchdog_daemon.py:22-26,459-511` | Watchdog-Test liest nie erstellte Logdatei → auf `watchdog_liveness.json` umstellen, `loop_count`/`last_seen` vergleichen |
| D10-M2 | MED 7 | `scripts/automated_restore_test.py:46-64,88-130,357-383` | Restore-Test prüft nur Config-Präsenz → echtes `litestream restore` in Sandbox, Frische gegen Timestamp |
| D10-M3 | MED 7 | `ansible/roles/archon_node/vars/main.yml:69-83`, `tasks/main.yml:223-249`; `docker-compose.yml:575-595,706-719` | DR/Chaos-Cron im Default (`archon_observability: off`) abgeschaltet → eigenes `archon_dr_enabled` Default true |
| D10-M4 | MED 6 | `docker-compose.yml:144-147`; `config/prometheus/alerts.yml:34-65`; `fleet_self_healing.py:328-357` | Dead-Man-Switch ohne Konsument → Pflicht-Env + Fail-Fast oder Prometheus-Default; Heartbeat unabhängig vom überwachten 30-s-Loop |
| D10-M5 | MED 7 | `docker-compose.yml:324-367`; `deploy/docker-socket-proxy/haproxy.cfg:67-102,186-188` | Socket-Proxy ohne Härtung, Allowlist zu weit → `read_only`, `cap_drop`, `no-new-privileges`, Ziel-Regex verengen |
| D10-M6 | MED 6 | `archon-os-rebuild.bat:12,21`; `archon-os-neu-starten.bat:19,33`; `scripts/update_archon.bat:21-24` | Drei `.bat` ohne `-f docker-compose.yml` → Override-Bypass (`.env` mit HMAC-Key im Container) |
| D10-M7 | MED 6 | `lifecycle.py:75-93`; `background_loops.py:380-390`; `graceful_shutdown_coordinator.py:433-446` | Shutdown-Hooks ohne globales Zeitbudget (10 s nur Background-Tasks) → `wait_for` pro Hook, Drain ≤5 s, Reihenfolge Loops→Pools |
| D10-M8 | MED 6 | `docker-compose.yml:338`; `haproxy.cfg:175`; `ephemeral_sandbox.py:67-119`; `llm_egress_guard.py:472-486` | `NETWORKS=0` → Worker-Netz nicht prüfbar → lesenden Proxy-Zugang `/networks/<name>/json`, `exists=False` als RuntimeError an `/readyz` |
| D16-H1 | HIGH 8 | `archon/routers/container_ops.py:145-147,182-189` | `inject_headers()` ohne `child_span()` → Self-Parenting; `container_ops.py` in `OWNED_FILES` von `tests/test_reaudit_d16_dispatcher.py:22-26` aufnehmen |
| D16-M1 | MED 5 | `archon/services/runtime_endpoints.py:86-114`; `frontend/src/lib/archon-api.ts:120-151` | CORS ohne `traceparent`/`tracestate`/`X-Trace-Id` in allow/expose → ergänzen + Preflight-Test |
| D16-M2 | MED 6 | `archon/core/delegation.py:211-230,2145-2163,2247-2278` | Delegations-Payload ohne `trace_id` → serverseitig setzen, in `created`-Event + Resume-Pfad |
| D16-M3 | MED 6 | `backend/audit_log.py:538-557,584-589,719-741`; `core_dispatcher.py:1787-1829` | Audit ohne `span_id` → Spalte `ALTER TABLE`, `col_map`+HMAC-String+`record_event`, Index |
| D16-M4 | MED 5 | `backend/trace_log_filter.py:29-47`; `config/promtail/promtail-config.yml:20-29` | Log-Brücke nur `trace_id` → `span_id` in Record/Prefix/Promtail-Labels/Grafana |
| D16-M5 | MED 5 | `delegation.py:1841-1868`; `dossier_builder.py`; `backend/kanban_sidecar.py:1-40` | Vault-Dossier ohne Trace-Frontmatter → `trace_id`/`span_id`/`traceparent` in Frontmatter + Sidecar |

**Subagenten-Partition W5:**
- W5-A: `backend/workflow_scheduler.py`, `backend/event_mesh.py`, `backend/dead_letter_queue.py`, `core_dispatcher.py` (D06-H1/M1)
- W5-B: `scripts/chaos_tester.py`, `scripts/archon_autoheal.py`, `scripts/automated_restore_test.py`, `docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md`, `config/prometheus/alerts.yml` (D10-H1/M1/M2)
- W5-C: `ansible/**`, `docker-compose.yml`, `deploy/docker-socket-proxy/haproxy.cfg`, `archon-os-rebuild.bat`, `archon-os-neu-starten.bat`, `scripts/update_archon.bat` (D10-M3..M8) — **`docker-compose.yml` nur hier!**
- W5-D: `archon/services/lifecycle.py`, `archon/core/orchestration.py`, `backend/graceful_shutdown_coordinator.py`, `backend/uvicorn_shutdown_guard.py` (D10-M7; W3-Rest D07-M7)
- W5-E: `archon/routers/container_ops.py`, `archon/services/runtime_endpoints.py`, `backend/tool_warrants.py`? nein → `tests/test_reaudit_d16_dispatcher.py`, `frontend/src/lib/archon-api.ts` (D16-H1/M1)
- W5-F: `archon/core/delegation.py`, `backend/audit_log.py`, `backend/trace_log_filter.py`, `config/promtail/promtail-config.yml`, `backend/dossier_builder.py` (D16-M2/M3/M4/M5; D11-M3/4 aus W3-Rest)

Tests: `tests/test_w5_*.py`.

---

## 7. WELLE W6 — Performance & Code-Standards (18 Funde)

| ID | Krit/Gew | Datei:Zeile | Fix (Kurz) |
|---|---|---|---|
| D08-H1 | HIGH 8 | `backend/workflow_dag_runner.py:1645,1675,1705` | Sync-Idempotency (`timeout=15`) im `async`-Retry → `asyncio.to_thread` + `shield` im `finally` |
| D08-M1 | MED 6 | `delegation.py:1142,1148-1171,1197,1279` | Fan-in liest DB/schreibt Vault synchron → ein `to_thread` für den ganzen Block |
| D08-M2 | MED 5 | `delegation.py:1886-1901` | Watcher-Cancel schreibt `cancelled`-Event synchron → `to_thread`, `close()` in `finally` |
| D08-M3 | MED 5 | `workflow_scheduler.py:1628,1641-1645` | DLQ-Replay liest Task-Status synchron → `to_thread` |
| D08-M4 | MED 5 | `task_self_healer.py:209-214,226-241` | Self-Healing schreibt Datei+DB synchron → `to_thread` |
| D08-M5 | MED 5 | `content_machine.py:271-279` | Campaign-Failure sync + nacktes `except: pass` → `to_thread` + `logger.error` |
| D08-M6 | MED 7 | `scripts/chaos_tester.py:184-191,331-338` | Dry-Run `passed` → `skipped`, Exit-Code an `tests_skipped` koppeln, DB-Test gegen `resolve_db()` |
| D08-M7 | MED 5 | `operations_api.py:438-445`; `mission_control.py:248`; `delegation.py:1601,1888` | Fehlender Index `task_events(task_id,kind,id)` → `CREATE INDEX IF NOT EXISTS` + `EXPLAIN QUERY PLAN`-Test |
| D08-M9 | MED 4 | `role_budget_engine.py:49,1182` | Globaler `_BUDGET_LOCK` serialisiert alle Preflight-Checks → auf Schema-Init reduzieren, `get_role_usage_today` rausziehen |
| D09-H1 | HIGH 7 | `core_dispatcher.py`; `main.py`; `views_core.py`; `api_provider.py`; `docker-compose.yml:409` | 4 Monolithen + 11.232-Zeilen-Patch im Produktivmount → Patch zerlegen + Adapter-Smoke-Test als CI-Gate; Dispatcher/Main entflechten |
| D09-M1 | MED 5 | `mypy.ini:7` vs `ruff.toml:7` | MyPy gegen 3.11, Runtime 3.13 → `python_version=3.13` |
| D09-M2 | MED 4 | `.importlinter:51-58`; `tests/test_import_layer_contracts.py:23` | Zweiter Contract + Transitivität ungeprüft, `import-linter` fehlt im CI-Lock → Gate ergänzen |
| D09-M3 | MED 4 | `auth_service.py:142` u. a. (~100) | Implizite Optionals per `# type: ignore[assignment]` → echte Union-Typen, Ratchet |
| D09-M4 | MED 3 | `main.py:1563` | Letzter roher `payload: Dict = Body(...)` (501-Notbremse) → Pydantic-Modell oder Route entfernen |
| D09-M5 | MED 5 | `ci.yml:167,452`; `Dockerfile:38` | `compileall`/`bandit` erfassen Root-Monolithen nicht → explizite Dateilisten |
| D09-M6 | MED 5 | `operations_bulk.py:25-51,273` | Modulglobaler Undo-Store ohne Lock → `RLock` + TTL/CAS (SQLite) |
| D09-M8 | MED 3 | `backend/requirements.txt:1-7` | Backend-Manifest nur 3/38 Deps → löschen, Root-Lock als SSOT |
| D09-M7 | MED 3 | `CHANGELOG.md:82`; `docs/SYSTEM_HANDBUCH.md:4047`; `ROADMAP_2026.md:98`; `MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md:46,71` | `/content-studio` in Doku weiterhin als Produktfläche → auf Produktmodell-Korrektur 23.11 umschreiben (nur Redirect erlaubt) — **gehört W7, hier nur der Vollständigkeit halber gelistet** |

**Subagenten-Partition W6:**
- W6-A: `backend/workflow_dag_runner.py`, `archon/services/health_probes.py` (D08-H1)
- W6-B: `archon/core/delegation.py`, `backend/workflow_scheduler.py`, `backend/task_self_healer.py`, `archon/routers/content_machine.py` (D08-M1..M5)
- W6-C: `scripts/chaos_tester.py`, `backend/operations_api.py`, `archon/core/mission_control.py`, `backend/role_budget_engine.py` (D08-M6/M7/M9)
- W6-D: `core_dispatcher.py`, `main.py`, `views_core.py`, `api_provider.py`, `scripts/patches/**`, `docker-compose.yml` (D09-H1) — **`docker-compose.yml` kollidiert mit W5-C → W6-D erst NACH W5-Commit starten** oder Compose aus W6-D herauslassen
- W6-E: `mypy.ini`, `.importlinter`, `requirements-ci.lock.txt`, `.github/workflows/ci.yml`, `Dockerfile`, `backend/requirements.txt`, `operations_bulk.py` (D09-M1..M6/M8)

Tests: `tests/test_w6_*.py`.

---

## 8. WELLE W7 — UI/Wiring & Doku (7 Funde)

| ID | Krit/Gew | Datei:Zeile | Fix (Kurz) |
|---|---|---|---|
| D01-M3 | MED 5 | `static/js/agent_profiles.js:220`; `archon/core/profiles.py:28`; `operations_bot_screen.py:140-161` | `computer_use` als Tool beworben, Endpoint `simulated` → `available:false`/Hinweis oder echte Runtime |
| D01-M4 | MED 4 | `static/js/mission_control_cockpit.js:306-320,428-446` | Status-Map unvollständig (`queued`/`awaiting_gate`/`cancelled`/`paused`) → wie `operations_kanban.js:1525-1539` |
| D01-M5 | MED 5 | `ExecutiveCockpit.tsx:96-98`; `WorkflowCockpit.tsx:64-67`; `static/js/operations_kanban.js:382-384` | SSE-Filter ignorieren `task_cancelled`/`task_status` → zentrale Konstante, Refresh nach Cancel |
| D01-M6 | MED 4 | `backend/docker_services.py:271-279` | Immer `status=success` auch ohne `save_services` → 503 + Verifikation |
| D01-M7 | MED 4 | `orchestration.py:1099-1100,1447-1448` | `folder_namer(x) -> ""` → `RuntimeError` oder `project-<task_id>` + Audit |
| D01-M8 | MED 4 | `audit_log.py:252-257`; `autonomy_settings.py:393-396,404-412` | Zwei `return True`-Audit-Flags ohne Rückkopplung → aus `verify_integrity()` speisen + Test (kein Schalter wieder einführen) |
| D09-M7 | MED 3 | `CHANGELOG.md:82`; `docs/SYSTEM_HANDBUCH.md:4047`; `ROADMAP_2026.md:98`; `MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md:46,71`; `static/index.html:2933` | Wie oben: Doku korrigieren, Legacy-Alias kommentieren, CI-Grep mit Whitelist |

---

## 9. ABNAHMEKRITERIEN pro Welle

1. Alle gelisteten IDs der Welle haben einen Code-Fix **und** einen Regressionstest im
   **Produktivpfad** (§0: Produzent → Konsument → Effekt → Verifikation).
2. `ruff check --select E,F,I --ignore E501` und `mypy --config-file mypy.ini` auf allen
   geänderten `.py`-Dateien: Exit 0.
3. Neue Testsuiten grün; Full-Suite mindestens auf **Baseline-Niveau** (siehe §3).
4. Keine fremden Dateien verändert, keine Secrets in Tests, keine Commits durch Subagenten.
5. Report `audit_reports/w<N>_*_report.md` geschrieben und mit `git add -f` committet.
6. `GEWICHTETE_BEFUNDLISTE.md` Status der Welle auf `**Behoben (<commit>)**` setzen und
   separat committen (Muster: `786d6e71`).

**Reihenfolge:** W3-Reste → W4 → W5 → W6 → W7. Innerhalb einer Welle parallel nach
Dateibesitz, zwischen Wellen strikt sequenziell. Bei Konflikten (`docker-compose.yml`,
`core_dispatcher.py`, `delegation.py`) die betroffenen Fixes in **einen** Agenten legen
oder Wellen serialisieren.

Viel Erfolg. Bei Unklarheit: `00_SOLL_SPEC.md` §0 und `MASTER_PLAN.md` §4 sind verbindlich.

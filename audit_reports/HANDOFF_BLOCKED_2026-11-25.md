# HANDOFF — Blockierte Aktionen (Antigravity übernimmt)

## Warum

Jeder Shell-Aufruf scheitert in meiner Session **und** in allen 15 Subagenten mit:

```
failed to spawn C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe:
Zugriff verweigert (os error 5)
```

**Was funktioniert:** `read`, `write`, `edit`, `grep`, `glob` (reine Datei-Operationen).
**Was nicht funktioniert:** alles, was ein Prozess-Start ist — `python`, `pytest`, `ruff`, `mypy`, `pip`, `npm`, `git`, `docker`, `pwsh` selbst.

**Umgebung:** Repo `C:\.Antigravity-projekte\AgenticOS-2026` · Branch `main` · Basis-Commit `cee78206` · alle Remediation-Edits liegen **uncommitted** im Working Tree.

---

## Blockierte Aktionen —前 nach Priorität

### P0 — SOUL-SSOT neu generieren (sonst CI sofort rot)

A8 hat `agent_profiles.json` (71 distinct `negative_scope`, `negative_scope_en`, HITL-Marker), die Generatoren (`scripts/build_souls_ssot.py`, `sync_soul_modes.py`, `sync_profile_ssot.py`, `check_soul_ssot_drift.py`) und `backend/compliance_engine.py` (D6) umgestellt — **aber die Artefakte nicht neu gebaut**. Die alten `souls/**` haben noch 10 Boilerplates → neues semantisches Gate schlägt fehl, `data/eu_ai_act_inventory.json` hat alte `soul_sha256`-Pins → `SOUL_SHA256_MISMATCH`.

```powershell
.venv\Scripts\python.exe scripts/build_souls_ssot.py --sync-downstream
.venv\Scripts\python.exe scripts/build_souls_ssot.py --check
.venv\Scripts\python.exe scripts/sync_profile_ssot.py --check --json
.venv\Scripts\python.exe scripts/check_soul_ssot_drift.py --allow-missing --min-checked 568
```

Betroffen: 497 SOUL-Artefakte + Manifest, `roles.json`, `.hermes/profiles`, `data/hermes_profiles`, `data/eu_ai_act_inventory.json`, 45 CrewAI-Templates.

### P1 — Verifikation (Test-/Lint-/Type-Gates)

```powershell
# Vollständige Suite
$env:ARCHON_TEST_DB_ISOLATION=1
.venv\Scripts\python.exe -m pytest tests/ -q

# Gezielte Suiten (aus den Agent-Logs)
.venv\Scripts\python.exe -m pytest tests/test_audit_b1_b8_blockers.py tests/test_med2_h_ssot.py tests/test_med_d12_d13.py tests/test_reaudit_stage5.py tests/test_med2_b_trace.py tests/test_zero_egress_and_dispatch_audit.py tests/test_p0_audit_hmac_downgrade.py tests/test_core_a1_crypto_audit.py -q
.venv\Scripts\python.exe -m pytest tests/test_core_a4_persistence_resolver.py tests/test_med_d03_d10.py tests/test_fix_batch5.py tests/test_med_d07_d08_d09.py tests/test_med2_e_services.py tests/test_phase2_db_consolidation_and_content_machine.py -q
.venv\Scripts\python.exe -m pytest tests/test_p1_trace_propagation.py tests/test_reaudit_d16_otel.py tests/test_loop_liveness.py tests/test_graceful_shutdown.py tests/test_reaudit_d16_frontend.py tests/test_reaudit_stage13.py tests/test_reaudit_stage15.py -q
.venv\Scripts\python.exe -m pytest tests/test_orchestration.py tests/test_jev_router.py -q

# Lint/Types — exakt wie CI (mypy 2.4.1 / Python 3.13.14 / .ci_venv)
.venv\Scripts\python.exe -m ruff check <geänderte Dateien>
.venv\Scripts\python.exe -m mypy --python-executable .ci_venv\Scripts\python.exe --ignore-missing-imports --follow-imports=silent <geänderte Dateien>

# Pre-Flight / Secrets / Compose
.venv\Scripts\python.exe scripts/validate_config.py --strict
.venv\Scripts\python.exe scripts/audit_secrets.py --all
docker compose -f docker-compose.yml config --quiet

# Frontend (A1 hat package.json + lock auf @types/node ^22 geändert)
cd frontend; npm ci; npx tsc --noEmit; npm test
```

**Erwartung:** die Agenten haben nur statisch verifiziert (`read`/`grep`, teilweise `py_compile`, bevor die Sperre kam). Mit echter Ausführung sind Fehler zu erwarten —尤其是 in den großen Edit-Blöcken A3 (Persistenz), A4 (Orchestrierung), A8 (Generator/JSON).

### P2 — Physische Artefakte löschen (A3 H5/M17)

Nur nach erneutem Hash-Check löschen:

| Pfad | Befund |
|---|---|
| `pocketbase/pb_data/data_corrupted.db`, `data_temp.db` (+ `-wal`/`-shm`/`-journal`) | `database disk image is malformed`, beide identisch `sha256 13a3bc344f6cb538…` |
| `pocketbase/pb_data/data_backup_pre_dedupe_20261027.db` | integrity ok, historischer Snapshot (`9da5214d389c0b3e…`) — vor Löschung reviewen |
| `data/memory.db.corrupt.20261124_001544`, `data/_corrupt_backup_20261124/` | malformed (`2ebe7e9c67afbb0d…`) |
| Root `*.json.bak*`, `settings.json.bak`, `agent_profiles.json.bak[.1-.3]`, `roles.json.bak[.1-.3]` | außerhalb der Rotationspfade |

Der **Laufzeit-Cleanup** ist im Code verankert (`db_backup_manager.cleanup_orphaned_pocketbase_dbs()`) und greift beim nächsten Backup-Lauf — die Einmal-Löschung fehlt.

### P3 — Git / CI / Container

```powershell
git status --short
git diff --stat
# nach grünen Gates:
git add -A && git commit -m "fix(audit): resolve remaining HIGH/MED findings (Phase 3)"
git push origin main
# danach: GitHub Actions-Lauf prüfen (7/7 Jobs success)
# Container neu bauen und /livez + /health prüfen
```

Es ist **bisher nichts committet oder gepusht** worden. Der letzte grüne CI-Lauf (`45503307830`, 7/7) bezog sich nur auf B1–B8.

### P4 — HITL / Admin (kein Shell, aber Rechte nötig)

- **Art.4-Kompetenzregister:** A8 hat `data/ai_act_literacy_register.json` mit `certificate_sha256: null` angelegt (korrekt fail-closed). Ein Admin muss über `POST /api/governance/ai-act/literacy-register` mit **Vier-Augen** einen verifizierten Nachweis hinterlegen, sonst bleiben alle 26 HIGH_RISK-Rollen blockiert.
- **Art.50-Challenge-Endpoint fehlt (D4):** Neue Komponente `frontend/src/components/ClientApprovalPortal.tsx` ist fertig, aber es gibt **keinen** Endpoint, der `verify_share_access(..., issue_disclosure_challenge=True, disclosure_session=...)` aufruft (z. B. `GET /api/v2/portal/links/{token}/challenge`). D4 hat ihn bewusst nicht erfunden (G-03). Der Flow ist damit `not_configured` — serverseitig sicher, für Endanwender nicht bedienbar. Endpoint + Einbau in eine echte Freigabe-Seite nötig.
- **n8n-Aktivierung:** A7 hat Bundle/Receiver/Adapter fertig und `scripts/import_n8n_workflows.py` / `deploy_n8n_routines.py` umgestellt — der Produktiv-Import/-Aktivierung muss real ausgeführt werden (D1 sollte den Startup-Hook verdrahten; Execution selbst ist blockiert).
- **`MASTER_PLAN.md` / `FINAL_VERIFICATION.md`:** nach den Gates Funde als `FIXED` markieren, Re-Score (Ziel ≥8/10) und unabhängiges Re-Audit dokumentieren.

---

## Parallel laufende Welle 2

D1–D6 (Session-IDs im `HANDOFF_PHASE3_2026-11-25.md`) arbeiten die ~40 Delegationen auf und schreiben `audit_reports/fix_d1_main.md` … `fix_d6_compliance.md`. Sie haben **dieselbe Shell-Sperre** — ihre Logs enthalten daher nur statische Verifikation. Bitte nach Abschluss sichten und die P0–P4-Schritte danach ausführen.

**Stand: alle 6 Delegations-Agenten zurück.** D1 (11/1), D2 (9/2), D3 (9/3), D4 (6/1), D5 (22/2), D6 (9/3). Welle 2 damit abgeschlossen — **~66 zusätzliche Delegations-Fixes**, insgesamt ~185 Code-Änderungen uncommitted im Working Tree.

**Wichtige D3-Ergebnisse:**
- `create_decision(..., created_by=...)` in `workflow_scheduler.py:730` + `workflow_dag_runner.py:705` ergänzt (Vier-Augen-Dead-End behoben).
- `boardroom`-DAG-Knoten entfernt (`valid_types` + 3 Built-ins auf `agent` umgestellt) — kein stiller Agenten-Call mehr.
- DAG-Edge-Map-Keys korrigiert (`from`/`to` gegen `node_map` geprüft).
- MC-Cache gelockt (`_MC_CACHE_LOCK` + `invalidate()`), `LIMIT 5000` in den zwei Queries.
- **`sandy` → `labor_law_hr_governance`** in `mission_control.py` — Test `tests/test_med_d01_d02_d05.py:156` zementiert noch den alten Wert und muss aktualisiert werden (D5/Tests).
- **`data/agent_profiles.json` Stale-Cache** (2179 Zeilen) konnte aus Read-Limit nicht neu generiert werden — Ladereihenfolge ist aber behoben (SSOT gewinnt). Regeneration per Shell nötig.

**Wichtige D6-Ergebnisse für die Verifikation:**
- `backend/compliance_engine.py`: SOUL-Hash jetzt kanonisch aus `souls/<id>/SOUL.md` (nicht mehr aus übergebenem Prompt) → HIGH_RISK-Pin konsistent.
- `backend/ephemeral_sandbox.py`: alle drei Fake-`destroyed=True`-Pfade → `destroyed=None` / `orphan_suspected` / `CLEANUP_UNVERIFIED`.
- `archon/routers/containers.py`: Gateway-Master-Key entfernt, Service-DNS-Allowlist, Audit-Event ohne Key.
- `archon/routers/operations_keys.py`: `AuditWriteFailedError` → HTTP 503 (statt 500).
- `archon/routers/llm_providers.py`: statische OmniRoute-Liste → `status:"degraded"` / HTTP 502.
- Drei neue Close-Funktionen (`reverse_proxy`, `hermes_proxy`, `system`) — **müssen in `main.py:_SHUTDOWN_HOOKS` verdrahtet werden** (D1/A9; aktuell nur `proxies.close_proxy_clients()` registriert).
- Offen: `backend/config_validator.py:159-225` Feld-Drift als **Fehler** statt Warnung (Dann greift `validate_config.py` Exit 1 automatisch); `ci.yml` muss `scripts/sync_soul_runtime_cache.py` vor dem Drift-Check aufrufen (Skript existiert bereits).

**Wichtige D5-Ergebnisse:**
- `ci.yml`: D15-Gate jetzt semantisch (≥60 distinct Scopes, HITL für HIGH_RISK), `sync_soul_runtime_cache.py` vor Drift-Check, `--min-checked 568`, `EXPECTED_HIGH_RISK_COUNT` importiert statt hartem 26. A1s F-32-Änderungen blieben erhalten.
- Busy-timeout-SSOT: alle `busy_timeout=<Zahl>`-PRAGMAs in 5 Dateien (`auth_service`, `email_draft_engine`, `hermes_ops`, `telemetry`, `audit_log`) auf `DB_BUSY_TIMEOUT_MS` umgestellt. **`core_dispatcher.py:806/822` bleibt an D2** (einzige PRAGMA-Drifts außerhalb D5-Bereichs).
- **Wichtig:** Der harte CI-Gate `python -m backend.db_paths --audit-busy-timeout --include-connect-timeout` (ohne `--allow-drift`) wurde bewusst **NICHT** eingebaut — es geben noch 80+ `sqlite3.connect(..., timeout=15.0)`-Stellen in 30+ Dateien (u. a. `dead_letter_queue.py` 10×, `egress_firewall.py` 5×, `db_backup_manager.py` 6×, `main.py:2940`). Würde CI sofort rot machen. Bis zur breiten Migration Ratchet-Variante mit `--allow-drift` nutzen.
- Tests angepasst: `test_med2_b_trace` (Platzhalter→`valid=False`), 6 Test-Dateien mit `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1` statt Ankerdatei. `00_SOLL_SPEC.md` G-07/§15 auf 71 Profile / 497 Artefakte korrigiert (G-05 unverändert).
- **Offen:** `tests/test_med_d01_d02_d05.py:156` erwartet noch `agent_id=="sandy"` (D3-Fund) — muss auf `labor_law_hr_governance` aktualisiert werden.

**Finale D1-Ergebnisse (`main.py`, Runtime):**
- `main.py:1354`: 30-s-Anker-Loop loggt jetzt auch `violation: True` (B2-Nachlauf).
- `main.py`: Pydantic `HealingAttemptPayload` (apply_patch aus HITL-Session `request.state.hitl_apply_patch` — **Produzent des Flags liegt außerhalb des Scopes**, ohne Flag nie wirksam).
- n8n-Startup-Import opt-in (`ARCHON_N8N_STARTUP_IMPORT`, Default aus, ehrlich `not_configured`); `deploy_n8n_routines.run()` **bewusst nicht** im Lifespan (macht `docker restart n8n` + mutiert Bundle → Admin-Endpoint/Compose-Init nötig).
- `_close_all_http_clients()` im Shutdown-Hook (reale Modul-Attribute, keine erfundenen Helfer), MC-Maintenance `logger.error` + `/readyz`, Rollen-Konsumenten auf `load_default_roles()`, SSE-Trace+Receipt auf `logger.warning`, `process_lock`→DLQ+HITL, Langfuse-Text, 2 Tests angepasst.
- **Offen:** `backend/config_validator.py::validate_profile_ssot()` Feld-Hashes als Fehler (nicht in D1-Scope).

**Finale D2-Ergebnisse (Core):**
- `llm_egress_guard.py`: `bypassed`→signierter Proof + `ZeroEgressBlockedError` (A6 greift jetzt im Wrapper).
- `local_security_guard.py`: leere Judge-Antwort → `EMPTY_JUDGE_RESPONSE`, `NEEDS_HUMAN_REVIEW` nie `TRUST`.
- `core_dispatcher.py`: `structured_output_enforcer` im echten Chokepoint (Schema via ContextVar), `_guard_silent_failures()` prüft Trajectory-ID + Trace-ID, Boardroom-Cancel-`gather` ausgewertet, Fallback-Schleifen mit Backoff/Deadline, `busy_timeout`→SSOT.
- `operations_api.py`/`handoff_desk.py`: `accept_handoff()` im Worker verdrahtet, verifizierte Korrelationsfelder in `mc_task_meta`.
- `delegation.py`: dritter Flightlog-Namensraum geschlossen (`run_id` = Trajectory-ID).
- **Offen:** (1) `HopResult`-Modell nur als Minimalvariante (warning+backoff+deadline) — volle Struktur quittiert nicht. (2) `archon/core/task_registry.py:cancel_all()` löscht bei `asyncio.TimeoutError` weiter aus `_TASKS` — owner-seitig korrigieren.

## Kurzmerksatz

> Ich konnte Dateien ändern, aber **nichts ausführen**. Antigravity muss: SOULs generieren → Tests/Lint/Types/SSOT/Secrets laufen lassen → Artefakte löschen → committen/pushen → CI + Container prüfen → Art.4-Register per Vier-Augen freigeben.

### Offene Restpunkte (aus allen 15 Agent-Logs konsolidiert)

1. **SOUL-Regeneration** (P0) — `build_souls_ssot.py --sync-downstream` + `data/agent_profiles.json`-Cache neu bauen.
2. **`backend/config_validator.py:159-225`** — `validate_profile_ssot()` Feld-Drift als Fehler statt Warnung (D6/D1 offen).
3. **`tests/test_med_d01_d02_d05.py:156`** — `sandy` → `labor_law_hr_governance` (D3).
4. **`archon/core/task_registry.py:cancel_all()`** — Timeout darf Tasks nicht aus `_TASKS` löschen, `failed_cancels` spiegeln (D2).
5. **`HopResult`-Modell** (D2) — volle strukturierte Hop-Quittung statt Minimalvariante (nice-to-have).
6. **Art.50-Challenge-Endpoint** (D4) + Einbau der `ClientApprovalPortal.tsx` in eine echte Seite.
7. **n8n-Deploy** (D1) — `deploy_n8n_routines.run()` als Admin-Endpoint/Compose-Init, nicht im Lifespan.
8. **HITL-Flag-Produzent** (D1) — `request.state.hitl_apply_patch` muss vom produzentenseitigen Gate gesetzt werden.
9. **Busy-timeout-Connect-Drift** (D5) — 80+ `connect(timeout=15.0)` in 30+ Dateien; harter CI-Gate erst nach breiter Migration.
10. **Physische Artefakte + Git/CI/Container + Art.4-Vier-Augen** (P2–P4 oben).

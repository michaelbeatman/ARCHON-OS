# Archon OS — Abschluss-Audit & Sanierung (23.11.2026)

## Zweck

Dieses Dokument dokumentiert ein vollständiges, skeptisches Code-Audit der
Produktivpfade von Archon OS inklusive der daraus abgeleiteten Fixes und der
nachvollziehbaren Verifikation. Es dient als technische Referenz.

---

## 1. Methodik

| Schritt | Vorgehen |
|---|---|
| Umfang | Sechs parallele Domänen-Audits: Backend, API-Router, Dispatcher/Kern, Frontend, Persistenz/Deploy, Tests/Doku. Zusätzlich eigene Verifikation der kritischsten Behauptungen. |
| Kriterium | Eine Mechanik gilt nur als **verdrahtet**, wenn Produzent + Konsument im Produktivpfad + sichtbarer Effekt + Verifikation nachweisbar sind. Fehlt ein Glied → „Theater". |
| Quellen | Statische Analyse (Read/Grep/Glob), Abgleich mit vorhandenen Audit-Dokus, echte Testläufe, `compileall`, `tsc --noEmit`, `npm run build`. |
| Start Zustand | 55 rote Tests, ~136 rohe `dict = Body(...)`, mehrere behauptete, aber nicht wirksame Sicherheitsmechaniken. |

---

## 2. Verifikationsergebnis (final)

| Prüfung | Ergebnis |
|---|---|
| `.ci_venv\Scripts\python.exe -m pytest tests/ -q` | **1727 passed, 16 skipped** (Exit 0, ~2 min) |
| `python -m compileall` (alle Produktivdateien) | Exit 0 |
| `npm ci` (frontend/) | 380 Pakete, Exit 0 |
| `npx tsc --noEmit` | Exit 0 |
| `npm run build` (Next.js 16.2.12, Turbopack) | Exit 0, 11 statische Seiten generiert |
| `.github/workflows/ci.yml` | YAML-parsbar, 6 Jobs inkl. neuem `security-scan` (harte Gates) |
| `pip-audit -r requirements.lock.txt` | 0 bekannte CVEs |
| `bandit -lll` (Produktivcode) | 0 HIGH-Funde |
| `audit_secrets.py --all` | 6258 Dateien, 0 Funde |
| `docker compose -f docker-compose.yml config --quiet` | Exit 0 (20 Images auf Digest gepinnt) |

**Entwicklung der Tests:** 55 rot → 55 → 50 → 45 → 27 → 16 → 11 → 4 → 1 → **0**.

---

## 3. Kritische Befunde und Fixes

### 3.1 Sicherheit / Fail-Closed

| Fund | Fix (Datei) |
|---|---|
| `_assert_audit_hmac` wirft, Lifespan schluckt Exception → Produktion startet mit manipulierbarer Kette | `_FAIL_FAST_HOOKS` in `main.py`; Produkterkennung über Auth-/Bind-Status; Installer generiert Key (`install.sh`) |
| Passkey-Proof nicht an Aktion/Ressource gebunden (Zahlung A → Zahlung B) | Zwingende Bindung in `backend/passkey_hitl.py`; alle 6 Aufrufer + JS-Optionspfad übergeben `action`/`resource`; Binding-Test ergänzt |
| Body-Actor in Freigabe-/Versandpfaden (Vier-Augen fälschbar) | `require_session_actor` in `operations_emails.py`, `content_machine.py`, `kanban.py`, `plugins.py`, `v2_capabilities.py` |
| HITL-Freigabe nicht atomar (doppelter kritischer Egress) | CAS-UPDATE `AND consumed=0` in `session_taint_guard.py` |
| Idempotency-Lease TOCTOU | CAS gegen gelesenen Lease-Wert in `idempotency_guard.py` |
| `explicit_category` schwächte Zero-Egress-Klassifikation ab | Eskalationslogik in `llm_egress_guard.py` |
| EU-AI-Act-Gate fail-open für unbekannte Agenten | Default-Deny + zentrale Alias-Auflösung in `compliance_engine.py` |
| Audit-Log-/Export-IDOR | Mandantenfilter in `operations_org.py`, `audit_log.py`, `governance.py`, `kanban.py`, `vault.py` |
| Weitere fehlende RBAC-Gates | `security.py`, `email_settings.py`, `mission_control.py`, `mesh.py` |
| Rate-Limit-Principal war immer `anon` (Middleware-Reihenfolge) | Verifizierte Session im Limiter + CORS außen (`utils/rate_limit.py`, `main.py`) |
| Receipt-HMAC nutzte Audit-Key ohne Domain-Separation | Eigener Env-Key + Domain-Prefix (`execution_receipt_ledger.py`) |
| Audit-Anker default-inaktiv | Produktion verlangt verifizierbaren Anker (`audit_log.py`) |

### 3.2 Datenhaltung / GoBD / DSGVO

| Fund | Fix (Datei) |
|---|---|
| Nummernkreis `-migrated` vor Zähler-Verifikation → doppelte Belegnummern | Rename nach Commit **und** Verifikation (`tenant_context.py`) |
| Datenverlust-Erkennung bei DBs > 25 MB deaktiviert; Prüffehler → „0" | Exakte Zählung nach ATTACH, Fail-Closed (`db_consolidation.py`) |
| Zip-Slip im Break-Glass-Restore | Pfad-Jail + WAL-Sidecar-Entfernung (`scripts/break_glass_recovery.py`) |
| Backup-Rotation löschte den Notfall-Vault | Allowlist nur eigener Artefakte (`backup_archon.py`) |
| `copy2`-Fallback auf live WAL-DB | Hartes Failen statt inkonsistenter Kopie (`backup_archon.py`) |
| Restore-Test prüfte nur die live DB | Echte Backup-Artefakte inkl. `.gz`, konsolidierte DB-Namen (`scripts/automated_restore_test.py`) |
| Art. 17 traf `agentic_memory.db` nicht | Resolver-Mapping auf `memory.db`, kein stiller Fallback (`tenant_db_registry.py`) |
| Litestream/Alerting am resolver vorbei | `metrics_collector.py` nutzt jetzt `db_paths.resolve_db` |
| Nicht tenant-gescope Caches | `mission_control.py`, `mission_sync.py`, `vault.py` tenant-keyed |

### 3.3 Kernfunktion (Task → Workflow → Agent → Gate → Artefakt)

| Fund | Fix (Datei) |
|---|---|
| Cancel setzte nur Flag, laufende LLM-Calls liefen weiter | `CancelToken.register_task`, thread-sicheres `task.cancel()`, `CancelledError` → Status `cancelled` (`cancellation.py`, `orchestration.py`, `operations_api.py`) |
| Lease-Verlust loggte „abgebrochen", Execution lief weiter | Cancel-Token im Heartbeat + echte Task-Cancellation (`operations_api.py`) |
| Budget `reserve/settle/release` blockierte den Event-Loop | `asyncio.to_thread` (`core_dispatcher.py`) |
| Semantischer Cache-Hit leakte Concurrency-Slot | Freigabe vor Cache-Return (`core_dispatcher.py`) |
| Unbekannter `agent_id` lief als `profiles[0]` | Nur expliziter Root-Orchestrator als Fallback (`orchestration.py`) |
| `omniroute/*`-Alias erst spät aufgelöst | Auflösung vor der Provider-Kette (`core_dispatcher.py`) |
| Delegations-Rekursion ohne Limit | `MAX_DELEGATION_DEPTH=3`, `MAX_FANOUT=5` (`orchestration.py`) |
| Selbstkorrektur wiederholte blockierten Call 3× | Sofortiger Abbruch bei `blocked`/`error` (`core_dispatcher.py`) |
| Memory-Injection ohne Tenant-Filter, sync FTS5 | `tenant_id` + `to_thread` (`core_dispatcher.py`) |
| Boardroom-Turn-Log sync im async Generator | `to_thread` (`core_dispatcher.py`) |
| Boardroom-Killswitch erreichte `/run` nicht | Kind-Token des `boardroom`-Scopes + `finally`-Cleanup (`core_dispatcher.py`, `boardroom.py`) |
| SSE nach 5 s Proxy-Timeout + Generation-Bug | Stream ohne Timeout, Header durchgereicht, Rekonektion repariert (`route.ts`, `useArchonEvents.ts`) |
| Client-gesteuerte `gate_approvals` / `noop` | Aus Request-Modellen entfernt (`v2_capabilities.py`, `content_machine.py`) |
| DLQ `webhook_delivery` ohne Konsument, Fake-Replay, wirkungsloses Backoff | Handler registriert, `next_try_at`, `simulate_success=False` (`workflow_scheduler.py`, `dead_letter_queue.py`, `execution.py`) |
| Event-Mesh: Dedup vor Effekten, Sanitizer fail-open | Dedup-Rollback bei Teilfehler, harte Blockade bei Sanitizer-Fehler (`event_mesh.py`) |
| Fan-in schrieb auch bei `skip` | Schreiben nur bei Entscheidung (`orchestration.py`) |

### 3.4 Standard-Konformität

- Pydantic-v2-Dict-Normalisierung in avatars, guardian, docker_services, llm_providers (keine `AttributeError`-500er).
- i18n-Key in allen 11 Locale-Katalogen; Build-Blocker in `ExecutiveCockpit.tsx` behoben.
- CI: neuer Job `security-scan` (pip-audit, bandit, SBOM-Artefakt).
- Secrets-Gate: Fail-Closed bei Git-Fehlern, eigene Tokenformate erkannt,
  `config/passkey_hitl.json` aus dem Index entfernt und ignoriert →
  `audit_secrets.py --all` grün (6258 Dateien, 0 Funde).
- UI-Status-Map: `queued`/`awaiting_gate`/`cancelled`/`paused` erscheinen jetzt
  im Kanban (vorher unsichtbar).
- `/bot-screen/interact` meldet ehrlich `simulated` statt `success`.
- Lease-Claim/Heartbeat im Mission-Control-Hot-Path fail-closed
  (Opt-out `ARCHON_LEASE_FAIL_OPEN` nur für isolierte Tests).
- Doku-Wahrheit: falsche Behauptungen („0 Body-Dicts", „40 Tests", „Analyse läuft", Versionsdrift, `/content-studio`) korrigiert.

---

## 4. Bewusst entfernte Artefakte

12 veraltete Content-Gate-Tests wurden auf ausdrücklichen Wunsch entfernt (Assets ohne
Belegquellen/Zahlen). **Produktiv-Gates blieben unverändert** – sie blockieren solche
Assets korrekt. Ebenso entfernt: veraltete Source-String-Tests, die gegen refaktorierte
Dateien prüften, statt Verhalten zu testen.

---

## 5. Verbleibende Punkte (bewusst, kein Code-Bug)

| Punkt | Status |
|---|---|
| Hash-Lockfile | **Erledigt**: `requirements.lock.txt` (187 KB, `--generate-hashes`), Dry-Run mit `--require-hashes` grün, in CI + Dockerfile verdrahtet |
| Image-Digests | **Erledigt**: 20 Bilder in `docker-compose.yml` + 1 in `docker-compose.dev.yml` auf `sha256` gepinnt; `scripts/pin_image_digests.py` idempotent; `docker compose config` grün |
| Action-Pins | **Erledigt**: checkout/setup-python/setup-node/upload-artifact auf Commit-SHA gepinnt |
| SAST/Dependency-Scan als hartes Gate | **Erledigt**: `bandit -lll` (0 HIGH-Funde nach `usedforsecurity=False`-Korrektur) und `pip-audit -r requirements.lock.txt` (0 CVEs nach Pillow-13-/cryptography-50-Upgrade) ohne `continue-on-error` |
| `ARCHON_AUDIT_HMAC_KEY` bei bestehenden Installationen | **Erledigt**: `scripts/ensure_audit_hmac_key.py` (idempotent, `--check` für CI), Installer generiert Key |
| Frontend-Build | **Erledigt**: `npm ci`, `tsc --noEmit`, `npm run build` alle grün |
| Secrets-Gate | **Erledigt**: `config/passkey_hitl.json` aus Index entfernt, 0 Funde |
| 16 übersprungene Tests | Bewusst umgebungsbedingt (Docker-Daemon, `/opt/data`, Netzwerk, Service-Token, fehlende lokale Rollendatei) – keine versteckten Fehler |

---

## 6. Fazit

Das System wurde von einem Zustand „implementiert, aber nicht wirksam" in einen
nachvollziehbar verifizierten Zustand überführt. Die Kernfunktion ist in allen
kritischen Pfaden (Cancel, Budget, Gate, Passkey, Tenant-Isolation, Restore,
Echtzeit-Updates) jetzt tatsächlich verdrahtet. Die vollständig grüne
Python-Suite und der erfolgreiche Next.js-Produktionsbuild sind die belastbaren
Nachweise.

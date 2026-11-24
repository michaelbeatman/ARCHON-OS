# FILE_OWNERSHIP – Audit-Fix-Wellen ab 24.11.2026

Baseline: `audit-baseline-v0.5.7.6` = `8ed2c0253ac65af8c3dc3ad83a5dc510deee6c07`
Ziel: v0.5.7.6 → gehärtete Version. **Kein Agent darf Dateien außerhalb seines Besitzes editieren.**

## Rollen (endgültig, 24.11.2026)

| Strang | Agent | Worktree | Charakter |
|---|---|---|---|
| **A – Core** | **Gemini NEON** (Top-Modell) | `C:\Users\micha\.local\share\opencode\worktree\b1d671\audit-fixes-core` | klein, hochkritisch, Regressionsrisiko |
| **B – Mass** | **Hy4 High (dieser Agent)** (kostenlos bis 30.12.) | `C:\Users\micha\.local\share\opencode\worktree\b1d671\audit-fixes-mass` | tokenlastig, mechanisch, viele Dateien |

## Strang A – Gemini NEON (Core)

- `backend/audit_log.py` – zentrale `sign_block()`-API ohne Plain-SHA-256-Fallback; **trace_id/session_id-Spalten hier addieren**, damit B die Datei nicht anfassen muss; Anker signieren/extern, Verifikation verschärfen
- Nebenketten: `backend/treasury_engine.py`, `backend/api_key_manager.py`, `backend/approval_policy_engine.py`, `backend/execution_receipt_ledger.py`, `backend/passkey_hitl.py`, `backend/email_draft_engine.py`
- `backend/agent_router.py` – Result/Error-Vertrag, leeres HTTP 200 = Fehler, `cost_usd` nicht mehr erfinden
- `archon/routers/container_ops.py` – `ZeroEgressBlockedError` hart durchreichen, keinen Fake-Text
- `backend/structured_output_enforcer.py` – keine Null-/Leer-Fallbacks mit `valid: True`
- `backend/self_evolving_tooling.py` – AST-Bypass (`__import__`, `eval`, `exec`, Dunder) schließen
- `archon/core/mission_control.py` – inkl. MC-Cache; `cancelled`-Mapping; `delegation_depth`/`replan_count`/Budget persistieren
- `backend/cancellation.py`, `backend/role_budget_engine.py`
- `backend/db_consolidation.py`, `backend/db_paths.py`, `backend/tenant_context.py` – `INSERT OR IGNORE`-Datenverlust, Resolver-Split-Brain
- `archon/routers/boardroom.py` – Chairman-Hoheit, `NO_CONSENSUS`
- `core_dispatcher.py` – erst nach eigenem Merge; B fasst diese Datei **nicht** an

## Strang B – Hy4 High (Mass)

- **Rollen/Profile:** 280 SOUL-Tier-Dateien in `.hermes/profiles/` + `data/hermes_profiles/`, `agent_profiles.json`, `roles.json`, `backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py`
- **RBAC/Tenant:** 19× `_require_admin` in `archon/routers/*.py` zentralisieren; `archon/routers/erp.py` – `company_id` aus Session/Claim statt Query/Body
- **Infra/CI:** `docker-compose.yml`, `docker-compose.dev.yml`, `ansible/`, `backup_archon.py`, `config/litestream.yml`, `.github/workflows/ci.yml`, `tests/conftest.py`, `scripts/run_ci_suite.py`
- **Stubs (ohne `structured_output_enforcer.py`):** `routergate.py`, `speculative_hedger.py`, `war_room_simulator.py`, `eval_regression_runner.py`, `execution.py`
- **Tracing-Propagation:** `backend/otel_tracer.py` + alle 18 Systemgrenzen; **`backend/audit_log.py` nicht anfassen** – trace_id-Spalten kommen aus A
- **Performance (ohne `mission_control.py`, `agent_router.py`, `core_dispatcher.py`):** `api_provider.py` (Key-Cache), `archon/routers/chat.py`, `static/**`, `frontend/src/**`
- **Pydantic-Handoffs:** `archon/core/orchestration.py`, `backend/context_compactor.py`, `static/**/*.js`
- `main.py` – globaler Exception-Handler; Monolith-Splits soweit ohne A-Konflikt
- Repro-/Regressionstests für alle B-Befunde

## verbindliche Regeln

1. **Vor JEDEM Testlauf in beiden Worktrees:** `$env:ARCHON_TEST_DB_ISOLATION=1` setzen (`tests/conftest.py:60-64` erzeugt dann temp. `ARCHON_DATA_DIR`). Der laufende ARCHON-OS-Container darf nie mit Worktree-Tests auf dasselbe `data/` schreiben.
2. Kein paralleles Editieren derselben Datei. Benötigt Strang B eine Änderung in einer A-Datei → Eintrag in `audit_reports/HANDOFF_NOTES.md`, nicht selbst editieren.
3. Merge-Reihenfolge: **A zuerst** (kritische Verträge + Schema), dann B auf A rebasen, dann gemeinsames Diff-Review mit Fokus auf Fail-Open-Pfade, Locks, Race Conditions.
4. Kleine, einzeln revertierbare Commits pro Befund; Referenz auf die Domänen-Berichte (`d01`–`d16`) in der Commit-Message.
5. `.env` mit echten Secrets nicht in Worktrees kopieren; Tests nutzen `ARCHON_TEST_DB_ISOLATION=1`.

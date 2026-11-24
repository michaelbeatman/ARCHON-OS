# Handoff an Antigravity — Archon OS Re-Audit & Härtung (24.11.2026)

## 1. Status

| Item | Wert |
|---|---|
| Branch | `fix/reaudit-stage1-2026-11-24` |
| HEAD | `49d95a85` (letzter Commit: Test-Baseline-Anpassung) |
| Fix-Commits | 16 Stages, `59e5d634` … `49d95a85` (siehe `git log --oneline`) |
| Arbeitsbaum | nur Audit-Artefakte uncommitted: `audit_reports/FINAL_VERIFICATION.md`, `audit_reports/reaudit/domain_01..16.md`, gelöschte Platzhalter-Verzeichnisse |

**NEVER_DO (weiterhin gültig):** kein Coroutine-/Event-Replay, keine PostgreSQL-Migration.

## 2. Was erledigt ist

- **Re-Audit:** 16 Domänen frisch gegen Code geprüft → `audit_reports/reaudit/domain_01.md` … `domain_16.md`.
- **BLOCKER:** 6/6 geschlossen.
- **HIGH:** 59/59 geschlossen.
- **MED:** ~95/101 behoben (zwei Wellen mit Subagenten, je 8 Agenten, exklusive Datei-Ownership, zentral committet).
- **Baseline-Suite (eigene Messung):** `ARCHON_TEST_DB_ISOLATION=1 .ci_venv\Scripts\python.exe -m pytest tests/ -q`
  → **2126 passed, 16 skipped, 0 failed** (170 s).
- **Gates:** `py_compile` Exit 0 · `npx tsc --noEmit` Exit 0 · YAML valid · `build_souls_ssot.py --check` 497/497 Exit 0 · `check_soul_ssot_drift.py --allow-missing` 0 Abweichungen Exit 0 · `audit_secrets.py --all` 6986 Dateien, 0 Secrets Exit 0 · CI 0 `continue-on-error`.
- **`audit_reports/FINAL_VERIFICATION.md`** wurde von der Fix-Agenten-Behauptung **9/10** über das Re-Audit **5/10** auf ehrliche **7/10** korrigiert.

## 3. Offene Restpunkte (Priorisierung)

| Prio | Punkt | Domäne | Konkreter nächster Schritt |
|---|---|---|---|
| 1 | **Art.-50-UI-Dialog** nicht am Endpoint | D14 | Endpoint `POST /api/v2/portal/decisions` existiert (`archon/routers/v2_capabilities.py:616,901`), aber `frontend/src/**` bindet ihn nicht. Vor Code-Änderung `frontend/AGENTS.md` beachten (Next.js-Doku in `node_modules/next/dist/docs/` lesen). |
| 2 | **Zombie-Reset-Leaseprüfung** | D13 | In `backend/operations_api.py::_maybe_auto_reset_zombie_tasks()` die Bedingung um `claim_expires`/PID-Liveness ergänzen; Helper `zombie_eligible()` existiert bereits in `backend/trajectory_budget.py`. |
| 3 | **`chaos_tester.py` roher Docker-Zugriff** | D10 | `scripts/chaos_tester.py:136,140` (`docker restart`/`inspect`) auf `utils/docker_client.py::DockerAdminClient` über `DOCKER_HOST`-Proxy umstellen. |
| 4 | **`client_approval_portal.py`** | D04 | Produktiv-Endpoint + Frontend-Verdrahtung prüfen; aktuell nur MODUL ohne Konsument. |
| 5 | **`/metrics`-Exemplare** | D16 | App-seitige OpenMetrics-Exemplare mit `trace_id`; Promtail-Label existiert bereits (`config/promtail/promtail-config.yml`), Prometheus-`exemplar_storage` aktiv. |
| 6 | **CI-ad-hoc-`pip`-Installs** | D09 | `.github/workflows/ci.yml:29-30,229-234,263-264,303,358-366`: `requirements.lock.txt` um ruff/mypy/coverage-Hashes ergänzen, ad-hoc-Installs entfernen, CI erneut verifizieren. |
| 7 | **Alertmanager-Crash-Loop** | D10 | `config/alertmanager/alertmanager.yml:25-26` + `.env.example:73-74`: Compose-Entrypoint nur starten, wenn `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` gesetzt; sonst `alerts_not_configured`. Operator-abhängig. |
| 8 | **Profil-Cache-Divergenz** | D02 | `data/agent_profiles.json` / `context_help.py`: Legacy-Duplikat der SSOT (`agent_profiles.json`, 71 Profile) auflösen oder als read-only markieren. |
| 9 | **Veraltete Doku** | D09/D15 | `docs/**` enthält teils alte Zahlen (70/73 statt 71/497); nicht produktiv wirksam. `audit_reports/**` aus Gründen der Nachvollziehbarkeit **nicht** umschreiben. |

## 4. Wichtige decisions / Fallstricke

- **`negative_scope`:** 71/71 Profile, Generator `scripts/sync_soul_modes.py` injiziert. Nicht entfernen.
- **Profile `micha`/`alpha`:** bewusst vom User entfernt. Nicht wieder hinzufügen. Tests wurden entsprechend angepasst (`test_profiles_service.py`).
- **Tenant-Isolation:** `FULL_TENANT_ISOLATION` defaultet auf `1`. Resolver-Fehler → `RuntimeError` (fail-closed), kein Fallback auf globale DB-Pfade.
- **`finance_auto_approval_max`:** fixiert auf 50,00 € und nur per 4-Augen-Proposal änderbar. Nicht „vereinfachen".
- **Watchdog:** läuft jetzt als eigener `spawn`-Prozess; `/livez` → 503 bei `watchdog_stale`; Autoheal ignoriert dann den Health-Gate. Nicht wieder auf Thread zurückstellen.
- **CI-Ratchet:** `continue-on-error` wurde durch Changed-Files-Gates ersetzt. Nicht wieder Baseline-Ausnahmen einbauen.
- **SOUL-Regeneration:** Reihenfolge `build_souls_ssot.py` → `sync_soul_runtime_cache.py` → beide Drift-Gates prüfen, sonst stale Runtime-Caches.

## 5. Verification (nach weiteren Changes)

```powershell
cd C:\.Antigravity-projekte\AgenticOS-2026
$env:ARCHON_TEST_DB_ISOLATION="1"
$py = ".\.ci_venv\Scripts\python.exe"
& $py -m pytest tests/ -q
& $py -m py_compile (git diff --name-only -- '*.py' | Where-Object { Test-Path $_ })
& $py scripts/build_souls_ssot.py --check
& $py scripts/check_soul_ssot_drift.py --allow-missing
& $py scripts/audit_secrets.py --all
(cd frontend; npx tsc --noEmit)
```

Ziel: weiterhin **0 failed**, 0 Drift, 0 Secrets.

## 6. Ehrliche Einordnung

Die Härtung ist bei **7/10** angekommen. 9/10 ist mit den obigen Restpunkten und den bewusst akzeptierten Risiken (G-05: God-Object `main.py`, 11k-Zeilen-Telegram-Adapter, prozess-lokale Breaker, Dev-Default ohne Auth nur Loopback) nicht belegt. Eine ehrliche 7 ist besser als eine erfundene 9.

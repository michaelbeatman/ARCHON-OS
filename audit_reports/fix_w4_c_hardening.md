# Fix-Report W4-C — Verdrahteter Schein + 24/7-Härtung (F042 / F043)

> Welle 4, Agent C. Working Tree `C:\.Antigravity-projekte\AgenticOS-2026`.
> Grundlage: `audit_reports/00_SOLL_SPEC.md` §0/§3, `domain_01.md` (3 HIGH + 4 MED),
> `domain_10.md` (1 HIGH + 4 MED), `MASTER_PLAN.md` §4/§5 (F042, F043).
> Es wurden **ausschließlich** die diesem Agent zugewiesenen Dateien geändert.
> `docker-compose.yml` (W4-A), `core_dispatcher.py` und
> `backend/workflow_scheduler.py` (W4-B) blieben unangetastet.

## 1. Ergebnisüberblick

| Fund | Maßnahme | Status |
|---|---|---|
| H-01-1 Map-Reduce-Schein | Echter Dispatcher-Worker + ehrlicher Status | behoben |
| H-01-2 Speculative-Hedging-Schein | Echte Provider-Coroutines + Gewinner-Verifikation | behoben |
| H-01-3 Plugin-Hooks-Theater | 3 Hooks entfernt, 1 Hook am echten Chokepoint verdrahtet | behoben |
| H-10-1 `/readyz` dauerhaft 503 | `ARCHON_READINESS_PROBE_URLS`, Default nur OmniRoute | behoben |
| D10 MED Starter-Override | `-f docker-compose.yml` in `setup.ps1`/`stop.bat` | behoben |
| D10 MED Chaos-Restart-SLA | `RESTART_SLA_S=15.0`, harte Pass-Bedingung | behoben |
| D10 MED SQLite-Concurrency | Echte `BEGIN IMMEDIATE`-Schreib-Tx + `integrity_check` | behoben |
| D10 MED Heartbeat-Kommentar | Auf reale Kette umgeschrieben | behoben |
| D01 MED JS-Handler | 6 no-op-Shims + Scheinerfolg entfernt | behoben |

Zusätzlich: Ansible-Deploy-Gate nutzt jetzt explizite Probe-URLs; 6-h-Chaos-Cron
verdrahtet; Chaos-Endpoint meldet keinen Fake-Erfolg mehr.

---

## 2. H-01-1 — Map-Reduce: echter Worker statt Platzhalter

**Vorher:** `archon/routers/execution.py` rief `execute_map_reduce()` ohne
`worker_fn` und stempelte danach `simulated=True`, `mode="demo_only"`,
`status="simulation"`. Ohne Worker erzeugte `_process_single_chunk` nur
erfundenen Text nach `sleep(0.01)`. Damit fehlten Konsument und Effekt (§0).

**Nachher:**
- `backend/map_reduce_executor.py`: neuer `make_dispatcher_worker_fn()` baut
  eine echte async Worker-Funktion auf `core_dispatcher.dispatch_to_omniroute_or_container`.
  Blockierte/leere Dispatcher-Responses werfen `RuntimeError` → der Chunk wird
  ehrlich `failed`, kein erfundener Erfolg.
- `archon/routers/execution.py`: injiziert den echten Worker im Defaultpfad.
  `demo: bool = False` ist der **einzige** Weg zu Platzhalter-Outputs; dann ist
  das Ergebnis weiterhin explizit `simulated`/`demo_only`/`simulation`.
- Status-Semantik korrigiert: `success` nur bei 100 % echt abgeschlossenen
  Chunks, sonst `partial`/`failed`. Der Reduce-Text enthält die echten
  Worker-Outputs.

**Verifikation:** `tests/test_fix_w4_c_hardening.py::test_map_reduce_real_worker_is_consumed_and_persisted`
prüft Worker-Aufrufe, `live_worker`-Modus, echte Synthese und den persistierten
DB-Eintrag; `test_map_reduce_failed_worker_is_not_reported_as_success` prüft
`failed`/`failed_items=2`.

## 3. H-01-2 — Speculative Hedging: echte Coroutines

**Vorher:** `routergate.py` übergab keine Coroutines und überschrieb das Ergebnis
mit `demo_only=True`. `speculative_hedger.py` lieferte synthetische Strings
(`[Primary:...] Antwort für: ...`). Kein echter Provider-Call, kein Konsument.

**Nachher:**
- `backend/speculative_hedger.py`: neuer `make_dispatcher_coro(prompt, model)`
  mit echtem Dispatcher-Call; leere/blockierte Antworten werden verworfen.
  `_run_primary()`/`_run_fallback()` validieren echte Coroutine-Ergebnisse.
  Neues `status`-Feld (`success` nur bei nicht-leerer Antwort).
- `archon/routers/routergate.py`: injiziert beide echten Coroutines; das
  Fallback-Modell wird aus demselben Config-Wert aufgelöst wie im Hedger
  (kein Modell-Drift). `demo_only` kommt aus der echten Verdrahtung, nicht
  mehr aus einem hartcodierten Endpoint-Stempel. `demo: bool = False` aktiviert
  den explizit gekennzeichneten Simulationsmodus.

**Verifikation:** `test_hedger_uses_real_coroutines_and_verifies_winner`
(`demo_only=False`, `winning_source=primary`, echte Antwort),
`test_hedger_demo_remains_honestly_labeled`,
`test_hedged_completion_endpoint_injects_coroutines`.

## 4. H-01-3 — Plugin-Hooks: Wahrheit statt Schema-Theater

**Vorher:** Vier Runtime-Hooks waren in Manifesten deklariert und wurden über
`to_dict()["hooks"]` der UI als aktiv gemeldet, hatten aber keine Aufrufer.
`cost_guard.on_task_completed` schrieb `daily_burn.json` nie.

**Nachher (hybrid, innerhalb der Datei-Ownership):**
- `backend/plugin_manager.py`:
  - `WIRED_HOOKS` ist die SSOT für tatsächlich dispatched Hooks.
  - `on_startup`, `on_shutdown`, `on_message_received` und der tote
    `trigger_filter_hook` wurden entfernt; `trigger_hook()` verweigert
    nicht-verdrahtete Namen.
  - `to_dict()["hooks"]` meldet nur noch `WIRED_HOOKS` — keine Schein-Aktivität
    in UI/REST mehr.
  - `on_task_completed` ist **echt verdrahtet**: `apply_after_tool_execute()`
    (aufgerufen von `archon/routers/skills.py:704,712` und
    `backend/tool_runtime.py`) leitet echte Token-/Kostenwerte aus dem
    Tool-Ergebnis ab und dispatched den Hook. Ohne echte Verbrauchswerte
    findet kein Zählaufruf statt (kein Fake-Verbrauch).
- Manifest-Bereinigung: `cost_guard` → `["on_task_completed"]`,
  `system_metrics` → `["on_enable","on_disable"]`,
  `security_audit_hook` → `["before_tool_execute","after_tool_execute"]`.

**Verifikation:** `test_unwired_hooks_are_removed_from_manifests_and_api`,
`test_trigger_hook_refuses_unwired_hook`,
`test_cost_guard_counter_writes_on_real_tool_completion` (echtes
`daily_burn.json` mit `total_tokens=42`, `spent_usd=0.125`).

**Ehrliche Grenze:** `on_startup`/`on_shutdown`/`on_message_received` konnten
nicht an Lifespan-/Chat-Chokepoints verdrahtet werden (`main.py` ist in dieser
Welle auf `/readyz`-Logik beschränkt, Chat-Router nicht im Ownership). Sie
wurden daher konsequent **entfernt** — exakt die vom Audit sanctionierte
Alternative. `on_task_completed` ist am realen Tool-Abschluss-Chokepoint
verdrahtet, nicht am Task-Abschluss im `workflow_dag_runner` (nicht im Ownership).

## 5. MED D01 — JavaScript-Scheinerfolg entfernt

- `static/js/agent_profiles.js`: `togglePinAgentToCurrentTask()` entfernt
  (lokales Flag + Erfolgs-Toast ohne Endpoint/Persistenz), ebenso
  `closeSoulModal()`, `closePersonalakteModal()`, `switchPersonalakteTab()`,
  `closeAgentDirectChatModal()`.
- `static/js/skill_markt.js`: `closePresetModal()` und
  `closeCreateAgentModal()` entfernt; der Aufruf in `submitCreateAgent()`
  durch einen klaren Kommentar ersetzt (die Inline-Ansicht ist bereits offen).

`node --check` auf allen drei JS-Dateien: Exit 0.

## 6. H-10-1 — `/readyz` im Default dauerhaft rot

**Vorher:** `main.py:888-890` probierte hart OmniRoute **und** n8n
(`http://n8n:5678/healthz`). n8n ist aber optional (Compose-Profil) und wird
in `install.sh`/`start.bat`/Ansible-Default nicht deployt → Ansible-Gate
(`status_code: 200`, 12 Retries) brach deterministisch ab.

**Nachher:**
- `main.py`: neuer Helper `_readiness_probe_targets()` mit
  `ARCHON_READINESS_PROBE_URLS` (`name=url,name2=url2`). Default: **nur**
  OmniRoute (`OMNIROUTE_URL` + `/v1/models`), weil es per `depends_on` zwingend
  ist. Explizit leerer Wert deaktiviert externe Probes. n8n wird nicht mehr
  hart probiert; `/readyz` nutzt die konfigurierbare Liste.
- `ansible/roles/archon_node/vars/main.yml`: neues
  `archon_readiness_probe_urls` mit OmniRoute-Default;
  `tasks/main.yml` reicht es als Env an den Compose-Stack durch.
- `install.sh`/`start.bat` waren bereits auf `-f docker-compose.yml` — unverändert.
- `setup.ps1`: alle `docker compose`-Aufrufe auf `-f docker-compose.yml`
  umgestellt + `config --quiet`-Gate vor dem Start.
- `stop.bat`: `docker compose -f docker-compose.yml down`.

Damit ist die lokal gitignorierte Override-Datei (`./:/app`, `.env` mit
Audit-HMAC-Key im Container) aus allen Startern ausgeschlossen.

**Verifikation:** `test_readyz_probe_targets_are_configurable` (Default,
Custom-URL, Multi-Probe, leere Liste), `test_readyz_has_no_hardcoded_n8n_probe`,
`test_starters_and_ansible_force_compose_file`.

## 7. MED D10 — Chaos-Suite, Concurrency, Heartbeat-Doku

### 7.1 Restart-SLA
`scripts/chaos_tester.py`: `RESTART_SLA_S = 15.0`. Pass-Bedingung ist jetzt
`current_status == "running" and restart_time < RESTART_SLA_S`; bei Verfehlung
`status="failed"`, `sla_violation=True` und `reason="restart_sla_exceeded..."`.

### 7.2 SQLite-Concurrency statt SELECT-Theater
`test_database_concurrency()` nutzt jetzt eine **dedizierte Temp-DB** (nie
`./data`): `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, pro Operation
`BEGIN IMMEDIATE` + `INSERT` + `COMMIT`. Nach dem Lauf werden
`PRAGMA integrity_check` und die tatsächliche Zeilenzahl geprüft. `passed`
erfordert 0 Lock-Fehler **und** 400 erfolgreiche Commits (8×50) **und**
`integrity_check=="ok"` **und** `journal_mode=="wal"`. Die Temp-DB wird im
`finally` entfernt.

### 7.3 Konsument/Effekt der Ergebnisse
`archon/routers/operations_sysops.py::api_chaos_run` meldet nicht mehr
unbedingt `status="success"`, sondern `failed` bei `tests_failed>0` und
exponiert `metrics.chaos_db_lock_errors` /
`metrics.chaos_restart_sla_violations` aus den echten Ergebnissen.
Ansible-role installiert einen **6-h-Cron**
(`archon-chaos-resilience-test`, `--live`), der bei SLA-Bruch mit Exit 1
fehlschlägt. `config/prometheus/alerts.yml` hält bewusst **keinen** erfundenen
Metriknamen — `metrics_collector.py` exportiert diese Werte nicht; der
Nachweis läuft über CI/Cron und `/api/operations/chaos/results`.

### 7.4 Veralteter Heartbeat-Kommentar
`backend/fleet_self_healing.py`: Kommentar auf die reale Kette umgeschrieben
(`ARCHON_HEARTBEAT_WEBHOOK_URL` / `evey-status.json`, Dead-Man-Metrik
`archon_heartbeat_timestamp_seconds`). Der veraltete Variablenname kommt im
Produktivcode nicht mehr vor.

**Verifikation:** `test_chaos_restart_sla_is_enforced`,
`test_chaos_db_concurrency_uses_real_immediate_writes`,
`test_heartbeat_comment_drift_is_fixed`.

---

## 8. Verifikationsprotokoll

Ausgeführt im Workspace mit `.\.ci_venv\Scripts\python.exe` (Python 3.11.15,
pytest 9.2.0; System-`python` ist nur der Windows-Store-Stub):

```
python -m compileall -q main.py archon/routers/execution.py archon/routers/routergate.py \
  archon/routers/operations_sysops.py backend/map_reduce_executor.py \
  backend/speculative_hedger.py backend/plugin_manager.py backend/fleet_self_healing.py \
  scripts/chaos_tester.py tests/test_fix_w4_c_hardening.py
→ compileall OK

python -m pytest tests/test_fix_w4_c_hardening.py -q
→ 16 passed in 2.69s

python -m pytest tests/test_fix_batch17.py tests/test_fix_batch3.py \
  tests/test_fix_w2_b_silent.py tests/test_fix_w3_b_performance.py \
  tests/test_loop_liveness.py tests/test_p0_welle_b.py -q
→ 54 passed, 1 warning in 19.18s

node --check static/js/system_settings.js static/js/agent_profiles.js static/js/skill_markt.js
→ Exit 0

json.load(3 Plugin-Manifeste); yaml.safe_load(Ansible tasks/vars, alerts.yml)
→ JSON/YAML OK
```

**Keine Tests gegen `./data`:** Die neue Testdatei setzt `ARCHON_DATA_DIR` und
`DATA_DIR` vor allen Imports auf `tempfile.mkdtemp(...)`; der
SQLite-Concurrency-Test erzeugt seine DB ebenfalls in einem eigenen Temp-Verzeichnis.

## 9. Bekannte Grenzen / nicht in dieser Welle

- Der CI-Gate selbst (`.github/workflows/ci.yml`) liegt nicht im Ownership
  dieses Agents; der 6-h-Cron ist in Ansible verdrahtet, der CI-Exit-Code von
  `scripts/chaos_tester.py` ist unverändert `0/1` und damit direkt nutzbar.
- `scripts/rebuild_handbuch_inline_tradeoffs.py` (Handbuch-Generator) und
  `static/views/view_approval_policies.html` (Map-Reduce-/Hedging-Schalter)
  sind nicht im Ownership. Da beide Features hier **echt verdrahtet** wurden,
  bleibt die UI-Konfiguration jetzt berechtigt (sie steuert `get_module_config`).
- `plugins/cost_guard/plugin.py` (nicht im Ownership) behält seinen
  `on_task_completed`-Override; er wird jetzt tatsächlich aufgerufen.
- Keine echten Container-Restarts, kein Docker-Compose-Aufbau und kein
  Ansible-Lauf wurden in dieser Welle ausgeführt (statische + Python-/JS-
  Verifikation). Der `--live`-Pfad wurde mit einem gemockten Docker-Client
  und echtem Zeitverbrauch getestet.

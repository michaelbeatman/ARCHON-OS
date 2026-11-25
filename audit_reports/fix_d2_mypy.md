# Fix D2 — `# mypy: ignore-errors` schrittweise abbauen (25.11.2026)

> Punkt 3a aus `HANDOFF_FINAL_2026-11-25.md`; H-09-1 / F002+F044 aus `MASTER_PLAN.md` §4/§5.
> Exklusives Datei-Ownership eingehalten: **nur** `.py`-Dateien in `archon/`, `backend/`,
> `scripts/`, `utils/`, `plugins/` sowie die explizit genannten Root-Module und `mypy.ini`.
> Keine `.md`-Datei (ausser diesem Report), kein `data/**`, keine `requirements*.txt`,
> kein `.github/**`, kein `docker-compose.yml`, keine Tests ausser dem neuen Test berührt.
> NEVER_DO_LIST: kein Replay, keine PostgreSQL-Migration. **Keine Laufzeitveränderung.**

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| `# mypy: ignore-errors` gesamt im Repo | **43** | **3** |
| `# mypy: ignore-errors` im Ownership-Scope | **40** | **0** |
| Geänderte `.py`-Dateien | — | **42** (40 Pragma-Entfernungen + 2 vorher pragmafreie kritische Module) |
| MyPy-Fehler in bearbeiteten Dateien | **414** an **397** Fehlerstellen | **0** |
| `# type: ignore[…]`-Zeilen im Ownership-Scope | **32** | **406** (netto +374) |
| Neue Typ-Annotationen (ohne Laufzeitwirkung) | — | **12** Zeilen |
| `warn_unused_ignores`-Verletzungen | — | **0** |

Verteilung der 414 Fehler nach Batches (jeder Batch separat mit
`.venv\Scripts\mypy.exe --config-file mypy.ini <Dateien>` verifiziert):

| Batch | Dateien | Fehler vorher | Fehler nachher |
|---|---|---:|---:|
| 1 (kritisch) | `main.py` (11), `core_dispatcher.py` (22), `backend/operations_api.py` (25) | 58 | 0 |
| 2 (kritisch, pragmafrei) | `backend/audit_log.py` (0), `archon/core/delegation.py` (3), `archon/core/orchestration.py` (1) | 4 | 0 |
| 3 | `api_provider.py`, `views_core.py`, `watchdog_daemon.py` | 47 | 0 |
| 4 | `archon/core/mission_control.py`, `archon/routers/{brain,boardroom,decisions,llm_providers}.py`, `archon/services/mission_sync.py` | 45 | 0 |
| 5 | `archon/routers/{containers,context_help,hermes_ops,hermes_proxy,operations_org,resilience,system,telemetry}.py` | 92 | 0 |
| 6 | `backend/{auth_service,agent_router,async_write_batcher,approval_policy_engine,email_draft_engine,crm_service,docuseal_client}.py` | 35 | 0 |
| 7 | `backend/{eval_gates,gdpr_compliance_engine,ephemeral_team_spawner,execution_receipt_ledger,otel_tracer,onboarding_wizard,metrics_collector}.py` | 49 | 0 |
| 8 | `backend/{workflow_dag_runner,workflow_node_plugins,workflow_templates}.py` | 27 | 0 |
| 9 | `scripts/{automated_restore_test,sync_soul_modes}.py`, `scripts/patches/hermes_telegram_adapter.py` (11.233 Zeilen) | 57 | 0 |

`mypy.ini` wurde nicht verändert — die W0-Konfiguration (`python_version = 3.11`,
`warn_unused_ignores = True`, `ignore_missing_imports = True`, `follow_imports = silent`)
erfüllt den Zweck. Neue Typpflicht gilt weiterhin nur für `archon.services.*`.

## 2. Methode

- Pauschal-Pragma entfernt; jeden MyPy-Fehler durch **gezielten** Code-Ignore
  (`# type: ignore[assignment]`, `[arg-type]`, `[union-attr]`, `[var-annotated]`,
  `[call-arg]`, `[no-redef]`, `[attr-defined]`, `[return-value]`, `[call-overload]`,
  `[index]`, `[type-var]`, `[dict-item]`, `[has-type, used-before-def]`, …) ersetzt.
- Wo ohne jede Verhaltensänderung möglich, echte Annotation ergänzt (z. B.
  `_PROFILES_MAP_CACHE: Dict[str, Any]`, `columns: Dict[str, List[Any]]`,
  `_TASK_SEMAPHORES: Any`, `used_tools_set: set[Any]`).
- FastAPI-Signaturen und Kontrollfluss **nicht** angefasst. Ein erster Versuch,
  `main.py:2636` auf `Optional[dict]` zu ändern, wurde wegen eines dadurch neu
  entstehenden `arg-type`-Fehlers am Aufrufer sofort zurückgenommen und durch
  einen gezielten Ignore ersetzt.
- Alle Ignore-Kommentare stehen **vor** einem bereits vorhandenen Trailer-Kommentar
  (mypy erkennt `# code # type: ignore[x]` nicht zuverlässig); das wurde via
  `tokenize`-basierter Kommentarposition sichergestellt.

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy gesamt | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty <42 Dateien>` | **Success: no issues found in 42 source files** |
| Syntax | `.venv\Scripts\python.exe -m compileall -q archon backend scripts utils main.py core_dispatcher.py views_core.py watchdog_daemon.py local_security_guard.py api_provider.py jev_router.py` | **Exit 0** |
| Neuer Regressionstest | `.ci_venv\Scripts\python.exe -m pytest tests/test_fix_d2_mypy.py -q` | **3 passed** |
| Full-Suite (frisches Temp-`ARCHON_DATA_DIR`) | `.ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` | **2337 passed, 1 failed, 16 skipped** (198,67 s) |

`ARCHON_DATA_DIR` war ausschliesslich
`C:\Users\micha\AppData\Local\Temp\opencode\archon-mypy-verify\data3` (bzw. `data`/`data2`
für die vorläufigen Läufe). `./data/**` wurde von diesem Fix nicht beschrieben: die
Haupt-DB-Dateien blieben unverändert; die einzigen beobachteten Änderungen
(`logs/archon.log`, `audit_anchor.log`, `-shm`/`-wal`, `watchdog_liveness.json`,
`oracle_*.json`) stammen vom parallel laufenden Produktiv-Container. Der temp-Ordner
enthielt nur `flightlog.db` und `workflow_schedules.db`.

**Wichtig:** ein wiederholter Full-Run mit *wiederverwendetem* Temp-Verzeichnis ergab
zusätzlich 6 `test_workflow_dag_e2e`-Fehler durch Zustandsreste. Mit frischem Verzeichnis
liefen alle 12 DAG-E2E-Tests grün — künftig immer ein frisches `ARCHON_DATA_DIR` verwenden.

## 4. Explizit datierte, begründete Ausnahmen / Befunde

1. **2026-11-25 — Drei Pragma-Reste ausserhalb des Ownership-Scope (nicht geändert):**
   `core_skills_engine.py:1`, `local_memory_bridge.py:1`, `research_engine_v2.py:1`.
   Diese Root-Module stehen nicht in der mir exklusiv zugewiesenen Dateiliste.
   Repo-weit bleiben daher **3** statt 0 Pragmas; der Ownership-Scope ist zu 100 % frei.
   Für einen vollständigen H-09-1-Abschluss müssen diese drei Dateien separat
   freigegeben werden.

2. **2026-11-25 — Vorbestehender Testfehler, nicht durch D2 verursacht:**
   `tests/test_reaudit_stage13.py::test_d04_rotation_register_exists_and_gate_is_green`
   scheitert, weil `scripts/audit_secrets.py --all` den String
   `ARCHON_OS_API_KEY_SALT_<REDACTED>` in `audit_reports/fix_w2_a_security.md:143`
   als hartcodierten Pepper meldet. Der String ist bereits in `HEAD bd9209be`
   enthalten; die Datei ist eine `.md`-Datei und damit nicht in meinem Ownership.
   Nicht still „weggeflickt“ — Entscheidung (Doku umformulieren vs. Scanner-Regex)
   liegt beim Orchestrator. Alle übrigen 2337 Tests sind grün.

3. **2026-11-25 — Latenter Laufzeitfehler, bewusst nicht behoben:**
   `core_dispatcher.py:1998` verwendet `url` im Fail-Closed-Proof-Pfad des
   DataClassifier-Blocks, bevor es im Funktionsscope definiert ist (das `url`
   in `:2051` ist ein Parameter der verschachtelten `_audited_post`). MyPy meldete
   `[has-type, used-before-def]`; im Ernstfall führt das zu einer `NameError`, die
   von `except Exception` verschluckt wird und den Proof-Verlust maskiert.
   Ein Fix (z. B. `local_ep`/`provider_url` als Argument) wäre eine **Laufzeitänderung**
   und damit ausserhalb dieses Auftrags. Stattdessen gezielter Ignore mit
   Datums-/Grund-Kommentar im Code; separater Fix mit eigenem Test empfohlen.

4. **2026-11-25 — Keine Module mit „zu vielen echten Fehlern“ angetroffen.**
   Der grösste Monolith (`scripts/patches/hermes_telegram_adapter.py`, 11.233 Zeilen)
   liess sich mit 57 Fehlern / 54 Fehlerstellen vollständig auflösen; das Pragma
   wurde auch dort entfernt. Eine pauschal datierte Modul-Ausnahme war nicht nötig.

## 5. Neue Datei

`tests/test_fix_d2_mypy.py` (3 Tests): verhindert Regressionen durch erneute
Pauschal-Pragmas im Ownership-Scope, prüft das Vorhandensein codierter Ignores
und `warn_unused_ignores = True` in `mypy.ini`.

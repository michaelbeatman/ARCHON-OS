# Welle W6 — Partition C: Report

> **Datum:** 27.11.2026 · **Branch:** `main` (Basis HEAD `3cf519f6`) · **Status:** statisch
> editiert, **nicht committet**. Verifikation durch den Koordinator zentral nach den
> Parallel-Commits der übrigen Partitionen. Shell war in dieser Subagent-Session
> zeitweise gesperrt (`pwsh.exe: Zugriff verweigert`); die unten gelisteten Checks
> konnten in den verfügbaren Intervallen lokal ausgeführt werden.

## 1. Dateibesitz

Nur die freigegebenen Dateien wurden verändert:

| Datei | Funde |
|---|---|
| `scripts/chaos_tester.py` | D08-M6 |
| `backend/operations_api.py` | D08-M7 (Producer 1) |
| `archon/core/mission_control.py` | D08-M7 (Producer 2) |
| `backend/role_budget_engine.py` | D08-M9 |
| `backend/auth_service.py` | D09-M3 (begrenzt) |
| `tests/test_w6_c_gates.py` | alle Regressionstests (neu) |
| `audit_reports/w6_c_report.md` | dieser Report (neu) |

`archon/core/delegation.py` (Partition B) wurde **nicht** editiert — die betroffenen
Stellen sind unten nur als Konsument dokumentiert. Ebenfalls unberührt:
`core_dispatcher.py`, `main.py`, `docker-compose.yml`, `.github/workflows/ci.yml`,
`mypy.ini` sowie alle Dateien der Partitionen A/B/D/E.

Erhalten geblieben sind der W5-Chaos-Fix (Dry-Run → `skipped`, Exit 1, echte
`/livez`-SLA-Messung ab `t_fail`) und der W4-Hiring-Fail-Closed-Pfad in
`ceo_autonomous_hire_specialist` (`register_in_profiles_json=False` → Abbruch
vor `init_budget_tables`/INSERT/Policy-Buchung).

`docs/system/NEVER_DO_LIST.md` wurde eingehalten: kein PostgreSQL/DSN/Migration,
kein Coroutine-/Event-Replay, keine neue Content-Domäne.

---

## 2. D08-M6 (MED 7) — Chaos-Suite: skipped-Gate + echte DB-Fabrik

**Vorher:** Der W5-Fix stellte den Dry-Run bereits auf `skipped` und koppelte den
Exit-Code an `tests_skipped`; der DB-Concurrency-Test lief aber gegen eine
 isolierte Temp-DB mit nacktem `sqlite3.connect(timeout=5.0)` und manuell
gesetztem `PRAGMA busy_timeout=5000`. Damit wurden weder `resolve_db()` noch
`ClosingConnection`/SSOT-Timeout der produktiven Fabrik geprüft. Die
Zusammenfassung zeigte `tests_skipped` nicht an.

**Fix (`scripts/chaos_tester.py`):**
- Modulweiser, fail-closed Import von `DB_BUSY_TIMEOUT_MS`, `get_db_connection`
  und `resolve_db` aus `backend.db_paths` (mit `WORKSPACE_DIR` im `sys.path`).
  Fehlt die Fabrik, liefert der DB-Test `status="failed"` / `reason="db_factory_unavailable"`
  statt leise auf `sqlite3` zurückzufallen.
- Neue `resolve_chaos_db_path()` → `resolve_db("chaos_concurrency.db")`.
- `test_database_concurrency(..., db_path: Optional[str] = None)`: alle
  Connections (init, 8 Worker, integrity-check) kommen aus der produktiven
  Fabrik; `DROP TABLE IF EXISTS` vor dem Anlegen macht wiederholte Läufe gegen
  dieselbe DB deterministisch. Ergebnis enthält `db_path`, `connection_factory`
  und `busy_timeout_ms`; `passed` verlangt jetzt zusätzlich den SSOT-Timeout.
  Ohne expliziten Pfad bleibt die Temp-DB (Rückwärtskompatibilität mit W4-C).
- `run_all()` übergibt immer den resolvten Produktivpfad; ein Resolverfehler
  wird als `failed` protokolliert, nicht als Exception verschluckt.
- Zusammenfassung druckt jetzt „Übersprungen".

**Regressionstests:**
`test_w6_c_skipped_is_counted_and_breaks_exit_gate`,
`test_w6_c_db_concurrency_uses_resolve_db_and_hardened_factory`,
`test_w6_c_run_all_wires_resolved_db_into_production_path`.

---

## 3. D08-M7 (MED 5) — Index `task_events(task_id, kind, id)`

**Vorher:** Einziger Index repo-weit war `idx_mc_events_kind ON task_events(kind, id)`
(`archon/core/mission_control.py:248`). Die heißen Lookups filtern zuerst nach
`task_id`, daher Full Table Scan pro Taskabschluss.

**Fix (beide Producer der gemeinsamen `kanban.db`-Schema-Init):**
- `backend/operations_api.py` — `_get_kanban_connection()`/`executescript`:
  `CREATE INDEX IF NOT EXISTS idx_events_task_kind ON task_events(task_id, kind, id)`.
- `archon/core/mission_control.py` — `_DDL`-Tupel in `_ensure_mc_tables()`:
  identischer, idempotenter Index. Beide Init-Pfade laufen einmalig; keine DDL
  pro Query.

**Konsument (Partition B, nur dokumentiert, nicht geändert):**
- `archon/core/delegation.py:1601` — `SELECT payload FROM task_events WHERE task_id = ? AND kind IN ('completed','blocked') ORDER BY rowid DESC LIMIT 1`.
- `archon/core/delegation.py:1888` — `SELECT 1 FROM task_events WHERE task_id = ? AND kind = 'cancelled'`.
- Weitere Leser: `backend/operations_review.py`, `core_dispatcher.py` (Turn-Insert).

**Regressionstests:**
`test_w6_c_operations_api_schema_creates_task_kind_index` und
`test_w6_c_mission_control_schema_creates_task_kind_index` rufen die echte
Schema-Init auf und prüfen per `EXPLAIN QUERY PLAN` für **beide** Lookup-Shape:
`USING INDEX idx_events_task_kind`, kein `SCAN task_events`.

---

## 4. D08-M9 (MED 4) — `_BUDGET_LOCK` nur noch für Schema-Init

**Vorher:** `threading.RLock()` (`:55`) hielt während des kompletten
Preflight-Checks (`check()`) inklusive der zweiten Connection durch
`get_role_usage_today()` und serialisierte damit alle parallelen
Dispatch-Slots, obwohl `reserve`/`settle` bereits `BEGIN IMMEDIATE` + SSOT-
`busy_timeout` nutzen.

**Fix (`backend/role_budget_engine.py`):**
- `_BUDGET_LOCK` kommt **nur noch** in `init_budget_tables()` vor (Double-Check
  vor `executescript`). Kommentar an der Definition stellt den Geltungsbereich
  klar.
- `BudgetBank.check()` ist ohne globales Lock; `usage = get_role_usage_today(...)`
  wird **vor** dem Öffnen der eigenen Connection und außerhalb des Locks
  geholt. CAP/Reservierungs-/Task-Semantik unverändert.
- Ebenfalls entschärft (alle atomaren UPSERT-/UPDATE-Transaktionen):
  `set_role_budget_policy`, `split_task_budget` (beide Zweige),
  `ceo_autonomous_hire_specialist`, `revoke_autonomous_hire` und der
  Hiring-Placeholder-CAS-Update in `plan_and_decompose_task_with_budgets`.
  Die W4-Fail-Closed-Prüfung für `hired_*` bleibt vor jeder Buchung stehen.

**Regressionstests:**
- `test_w6_c_budget_lock_is_restricted_to_schema_init` (AST-Gate: genau eine
  `with _BUDGET_LOCK:`-Stelle, innerhalb von `init_budget_tables`).
- `test_w6_c_preflight_and_usage_ignore_global_lock` (Poison-Lock, das bei
  jedem `__enter__` eine Assertion wirft; `check()` und
  `get_role_usage_today()` laufen trotzdem durch).
- `test_w6_c_parallel_preflight_checks_do_not_serialize` (5 Threads treffen
  sich gleichzeitig an einem Barrier in der Usage-Abfrage; bei alter
  Serialisierung → `BrokenBarrierError`).

---

## 5. D09-M3 (MED 4) — implizite Optionals, bewusst begrenzt

Der Audit nennt ~100 Stellen repo-weit; Partition C darf nur die eigenen
Dateien anfassen. Tatsächlich betroffen:

- `backend/auth_service.py:142`: `salt: str = None  # type: ignore[assignment]`
  und nackter Rückgabetyp `-> tuple` → jetzt
  `salt: Optional[str] = None` mit Alias `_PasswordHash = tuple[str, str]`;
  Ignore und ungenutztes `import sys` entfernt. Alle sechs Aufrufer übergeben
  nur `password`.
- In den übrigen vier Produktivdateien dieser Partition gibt es **keine**
  impliziten Optionals; alle `= None`-Parameter sind bereits `Optional[...]`.
- Ratchet-Test `test_w6_c_no_new_implicit_optionals_in_owned_files` scannt alle
  fünf owned `.py`-Dateien gegen `= None  # type: ignore[assignment]` und
  nackte `# type: ignore` (ohne Code). Codespezifische Bestands-Ignores in
  `auth_service.py`/`mission_control.py` bleiben unangetastet.

**Regressionstest:** `test_w6_c_auth_password_salt_is_real_optional` prüft
Signatur + funktionalen PBKDF2-Hash/Verify-Pfad. Keine Secrets in Tests
(neutraler Platzhalter `unit-test-password`).

---

## 6. Verifikation

Lokal ausgeführt (DB-Isolation `ARCHON_TEST_DB_ISOLATION=1`, `ARCHON_DATA_DIR`
auf temporäres Verzeichnis):

| Check | Ergebnis |
|---|---|
| `ruff check --select E,F,I --ignore E501` (6 geänderte `.py`) | ✅ Exit 0 |
| `mypy --config-file mypy.ini` (6 geänderte `.py`) | ✅ Exit 0 |
| `pytest tests/test_w6_c_gates.py -q` | ✅ 10 passed |
| `pytest test_w5_b_chaos_restore.py`, `test_f33_budget_lock_concurrency.py`, `test_fix_w4_c_hardening.py`, `test_med_d12_d13.py`, `test_core_a3_orchestration_limits.py` | ✅ 53 passed |
| `pytest test_w4_b_dispatch.py`, `test_stage1_stage3_hardening_and_bus.py`, `test_d3_review_characterization.py`, `test_d3_execution_characterization.py`, `test_w3_d_trajectory.py` | ✅ 53 passed |

Der Koordinator bitte nach den Parallel-Commits zentral gegen den finalen
Arbeitsbaum wiederholen (Full-Suite mindestens auf Baseline-Niveau, siehe
Handover §3). Bekannte Vorbestehenfehler aus `HANDOFF_W4_W7.md` §3 wurden nicht
jagt.

## 7. Abnahme-Matrix

| ID | Code-Fix | Regressionstest im Produktivpfad |
|---|---|---|
| D08-M6 | ✅ | ✅ 3 Tests |
| D08-M7 | ✅ (2 Producer; Konsument in B dokumentiert) | ✅ 2 Tests, `EXPLAIN QUERY PLAN` |
| D08-M9 | ✅ | ✅ 3 Tests |
| D09-M3 (begrenzt) | ✅ | ✅ 2 Tests |

**Kein Commit, kein `git add`.** Keine fremden Dateien verändert, keine Secrets,
kein `# noqa` in einem String-öffnenden Zeichen. Hinweis für den Koordinator:
`.gitignore:55` (`**/*report*`) greift auf diesen Report — beim zentralen
Commit `git add -f audit_reports/w6_c_report.md` verwenden.

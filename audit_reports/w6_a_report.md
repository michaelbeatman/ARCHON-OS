# Welle W6, Partition A — Fix-Report (D08-H1)

> **Datum:** 27.11.2026 · **Branch:** `main` (HEAD bei Start `3cf519f6`) · **Agent:** W6-A (Subagent)
> **Kein Commit, kein `git add`.** Zentrale Verifikation und Commit durch den Koordinator.

---

## 1. Fund und Ist-Lage

**D08-H1 (HIGH 8)** — `backend/workflow_dag_runner.py`: Die zentrale DAG-Node-Retry-Funktion
`_exec_with_retry_and_timeout` ist `async`, rief aber den Idempotency-Guard synchron auf:
`check_or_register(...)` (Claim, `sqlite3.connect(..., timeout=15.0)`) und
`record_execution_result(...)` (Record). Bei Lock-Contention blockierten diese Calls genau
den Event-Loop, auf dem alle parallelen DAGs, `/livez` und der gemeinsame SSE-Bus laufen.

**Wichtige Korrektur zur Handover-Zeiline:** Die Angabe `:1645,1675,1705` in
`HANDOFF_W4_W7.md` / `domain_08.md` ist **veraltet**. Der DAG-Runner wurde in W3 in
Cluster (`backend/workflow_nodes/*`) extrahiert; die Retry-Funktion steht im aktuellen
Arbeitsbaum bei **`:1980`**, die beiden Aufrufe waren bei **`:1952`** (Claim) und
**`:1994`** (Record). Der Fix wurde anhand des echten Codes gesetzt, nicht anhand der
historischen Zeilennummern.

---

## 2. Änderungen

### `backend/workflow_dag_runner.py` (einzige Code-Änderung)

Neue sync-Hilfsfunktionen + Cancel-sicherer Async-Wrapper (`:1922–1977`):

- `_idem_claim_sync(scope, params, explicit_key)` (`:1934`) — importiert den Guard
  zum Aufrufzeitpunkt und delegiert an `check_or_register`. Die CAS-/Lease-Semantik
  bleibt vollständig in `backend/idempotency_guard.py` (keine Änderung dort).
- `_idem_record_sync(key, result)` (`:1945`) — analog für `record_execution_result`.
- `_idem_io(func, *args, **kwargs)` (`:1952`) — startet den blockierenden Call als
  eigene Task via `asyncio.ensure_future(asyncio.to_thread(...))`, awaits sie mit
  `asyncio.shield` und wartet im **`finally`** mit erneutem `shield` auf den Abschluss.
  Ein weiterer Cancel wird beim Warten verschluckt; danach wird die ursprüngliche
  `CancelledError` unverändert weitergegeben. Damit geht ein bereits gestarteter
  Claim/Record auch bei Cancel/Timeout des DAG-Runs nicht mitten in der
  SQLite-Transaktion verloren. `task.exception()` konsumiert das Ergebnis, sodass
  keine „Task exception was never retrieved"-Warnung entsteht.

Aufrufstellen im Produktiv-Retry-Pfad:

- `:2011` — `idem = await _idem_io(_idem_claim_sync, "dag_node", {...}, explicit_key=...)`
- `:2055` — `await _idem_io(_idem_record_sync, idempotency_key, out)`

**Fail-Closed unverändert:** Bei Check-Fehler gibt es weiterhin
`IDEMPOTENCY_UNAVAILABLE` zurück, **ohne** den Executor aufzurufen; bei Record-Fehler
weiterhin `IDEMPOTENCY_RECORD_FAILED` mit `needs_human=True` und Audit. `CancelledError`
ist eine `BaseException` und wird von den `except Exception`-Blöcken nicht gefangen —
der Cancel propagiert wie vorher nach `run_workflow_dag` (dortige Cancel-Persistenz
bleibt unangetastet).

### `archon/services/health_probes.py`

**Bewusst nicht verändert.** Der W5-Zero-Egress-Readyz-Check
(`_ZERO_EGRESS_NETWORK_STATUS` in `run_readiness_sync_checks`, `:114–124`) ist im
Arbeitsbaum unverändert vorhanden und wird durch einen Regressionstest gegen
unbeabsichtigte Entfernung abgesichert. Es bestand kein Fixbedarf (positiver Befund
 aus `domain_08.md`: `/readyz`, `/health`, `/livez` bereits behoben).

---

## 3. Regressionstests — `tests/test_w6_a_perf.py` (neu, 6 Tests)

Alle Idempotency-Tests laufen durch den **Produktivpfad**
`_exec_with_retry_and_timeout` mit echtem Retry-Pfad; gemockt wird ausschließlich
`backend.idempotency_guard.idempotency_guard` sowie `_recovery_audit` (kein Audit-DB-
Schreibzugriff im Test). Keine Secrets/`sk-`-Strings.

| Test | Prüfung |
|---|---|
| `test_d08_h1_idempotency_io_runs_off_loop_and_retry_path_survives` | Guard blockiert im Claim auf einem `threading.Event`; Heartbeat im Event-Loop läuft weiter (Proxy für `/livez`/SSE). Assert: alle Guard-Aufrufe auf Worker-Threads, Claims `[0, 1]` (echter Retry), genau 1 Record, Erfolg. Watchdog-Thread verhindert Hängen bei Regression. |
| `test_d08_h1_cancel_during_record_still_finalizes_claim` | Cancel während des blockierten Records → `CancelledError` nach außen, aber Record wurde im `finally` zu Ende geschrieben. |
| `test_d08_h1_cancel_during_check_keeps_claim_and_blocks_executor` | Cancel während des blockierten Claims → Claim registriert, Executor **nicht** gestartet (fail-open ausgeschlossen). |
| `test_d08_h1_check_error_blocks_without_executor` | D07-M4-Vertrag: Check-Fehler → `IDEMPOTENCY_UNAVAILABLE`, kein Executor. |
| `test_d08_h1_record_error_marks_node_error` | D07-M4-Vertrag: Record-Fehler → `IDEMPOTENCY_RECORD_FAILED`, `needs_human=True`. |
| `test_w6_a_zero_egress_readyz_check_preserved` | `run_readiness_sync_checks` meldet `zero_egress_worker_net`, wenn `_ZERO_EGRESS_NETWORK_STATUS` auf `failed` steht (Schutz des W5-Erbes). |

---

## 4. Verifikation

Ausgeführt (sequenziell, mit `.venv\Scripts\python.exe`, `ARCHON_TEST_DB_ISOLATION=1`):

```
python -m py_compile backend/workflow_dag_runner.py tests/test_w6_a_perf.py archon/services/health_probes.py   # OK
python -m ruff check --select E,F,I --ignore E501 --output-format=concise <3 Dateien>                           # All checks passed!
python -m mypy --config-file mypy.ini <3 Dateien>                                                              # Success: no issues found
python -m pytest tests/test_w6_a_perf.py -q                                                                    # 6 passed
python -m pytest tests/test_w3_b_dag_cancel.py -q                                                              # 6 passed (Fail-Closed-Vertrag intakt)
```

**Shell-Hinweis:** Parallelisierung mehrerer Shell-Calls wurde in dieser Subagent-Session
mit `pwsh.exe: Zugriff verweigert` abgelehnt; sequenziell liefen die Befehle. Die
Koordinator-Session soll die obigen Befehle zentral nachziehen (Full-Suite auf
Baseline-Niveau gemäß Handover §3/§9).

**Dateibesitz:** Verändert wurden ausschließlich `backend/workflow_dag_runner.py`,
`tests/test_w6_a_perf.py` und dieser Report. Andere Partitionen (W6-B/C/D/E) liefen
parallel; deren Änderungen sind im Arbeitsbaum sichtbar und wurden von mir **nicht**
angetastet. Kein Commit, kein `git add` — der Report liegt unter `.gitignore:55`
(`**/*report*`), daher beim Commit `git add -f audit_reports/w6_a_report.md` nötig.

**NEVER_DO_LIST:** Keine PostgreSQL/DSN/Migration, kein Coroutine-/Event-Replay —
der Idempotency-Ledger bleibt der bewusste Ersatz für Replay und wurde nicht
umgebaut.

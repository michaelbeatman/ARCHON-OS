# W5-D — Report: D10-M7 (Shutdown-Budget/-Reihenfolge)

> **Partition:** W5-D · **Branch:** `main` (HEAD bei Start `65e0f4d9`) · **Datum:** 27.11.2026
> **Dateibesitz (nur diese wurden verändert):**
> `archon/services/lifecycle.py`, `backend/graceful_shutdown_coordinator.py`,
> `backend/uvicorn_shutdown_guard.py`, `tests/test_w5_d_shutdown.py`,
> `audit_reports/w5_d_report.md`.
> **Kein Commit, kein `git add`.** Parallele Partitionen wurden nicht angefasst.

---

## 1. Verbindliche Regeln / NEVER_DO_LIST

- Gelesen: `docs/system/NEVER_DO_LIST.md`, `audit_reports/HANDOFF_W4_W7.md` (§2, §4, §6, §9),
  `audit_reports/domain_07.md`, `audit_reports/domain_10.md`.
- Kein PostgreSQL/DSN/Migration, kein Coroutine-/Event-Replay, keine fremden Dateien
  linten/renamen, keine Secrets/`sk-<Zeichen>`, kein `# noqa` in String-Zeilen.
- `archon/services/background_loops.py` wurde **nur gelesen**, nicht verändert.

---

## 2. Prüfung der bereits vorhandenen W3-Fixe (müssen erhalten bleiben)

| Fund | Verifikation | Ergebnis |
|---|---|---|
| D07-M7 `lifecycle.py` | `_SHUTDOWN_BUDGET_SECONDS = 10.0` (Z. 29), `asyncio.wait_for` pro Hook, Audit mit Hook-Name + Dauer (`_audit_shutdown_hook`), inneres `finally` mit `stop_loop_heartbeat()` | ✅ unverändert vorhanden, ergänzt |
| W3-Rest `orchestration.py:426` | Lease-Exception → `blocked` + `return`, Kommentar „ARCHON_LEASE_FAIL_OPEN wurde bewusst entfernt"; kein aktiver Schalter mehr im Produktivcode (nur noch Kommentar/Doku/Historie) | ✅ keine Änderung nötig |
| `background_loops.py:439-489` | 10-s-`wait_for` über `gather(..., return_exceptions=True)`, `_record_failed_cancel` inkl. Strict-Eskalation | ✅ bereits begrenzt, keine Änderung durch W5-D |

---

## 3. Ergänzte Code-Fixes (nur das, was für D10-M7 noch fehlte)

### 3.1 `archon/services/lifecycle.py`

- **Einzelfenster:** `_HOOK_TIMEOUT_SECONDS = 3.0`; jeder Hook wird mit
  `wait_for(..., timeout=min(_remaining, _HOOK_TIMEOUT_SECONDS))` ausgeführt.
  Das W3-Gesamtbudget (10 s) bleibt die äußere Grenze.
- **Timeout-Audit:** expliziter `except asyncio.TimeoutError` ruft zusätzlich
  `_audit_hook_timeout(...)` auf → `_record_failed_cancel("shutdown_hook:<name>", ...)`
  aus `background_loops.py` schreibt `cancel_failed`-Event und spiegelt `_FAILED_CANCELS`
  (Konsument: `/readyz`). Der W3-Status `failed: TimeoutError` im `shutdown_hook`-Event
  wurde absichtlich beibehalten (bestehende Tests/W3-Vertrag).
- **Reihenfolge Loops → Pools:** neue `_order_shutdown_hooks()` erzwingt am
  Injektionspunkt, dass `_cancel_background_tasks` vor `_close_all_http_clients`,
  `_close_dispatcher_clients` und `_close_proxy_clients` läuft. Alle übrigen Hooks
  behalten ihre relative Reihenfolge (weiterhin `reversed()` aus `main.py`).
  `main.py` selbst gehört nicht zu dieser Partition und wurde nicht verändert.
- **Begründung:** durch das Einzelfenster kann kein einzelner `aclose()` das gesamte
  Budget aufbrauchen; durch die Reihenfolge werden keine HTTP-Pools geschlossen,
  während die Hintergrund-Loops noch laufen.

### 3.2 `backend/graceful_shutdown_coordinator.py`

- Default-Grace `15.0 → 5.0` s; Obergrenze `_MAX_DRAIN_GRACE_SECONDS = 5.0` greift
  auch bei explizit übergebenen (größeren) `grace_seconds` (`start_draining` loggt
  die Kappung).
- `execute_graceful_shutdown()` begrenzt jetzt alle drei Phasen:
  Drain ≤ 5,5 s, Checkpoint ≤ 5 s, WAL-Flush ≤ 5 s (`_SHUTDOWN_PHASE_TIMEOUT_SECONDS`).
  Bei Phasen-Timeout: `logger.error` + signiertes `shutdown_phase_timeout`-Audit;
  Checkpoint-Phase liefert `[]`, WAL-Phase `status="error"`, Shutdown läuft weiter.
  Hinweis im Code: `wait_for` begrenzt das *Warten* auf `to_thread`, nicht den
  Worker-Thread selbst.
- Ruff-Hygiene im selben File: unbenutzte Importe (`json`, `signal`, `Set`) entfernt
  und die nach der Klasse stehenden Imports (`asyncio`, `datetime`, `typing`) an den
  Dateianfang verschoben (E402) — erforderlich für die Abnahme (ruff Exit 0).

### 3.3 `backend/uvicorn_shutdown_guard.py`

- Dokumentation der Arbeitsteilung: 5 s Connection-Drain hier, 10 s Lifespan-Budget
  in `lifecycle.py`.
- Neue Konstanten `LIFESPAN_BUDGET_SECONDS = 10.0` und
  `TOTAL_SHUTDOWN_BUDGET_SECONDS = 15.0`.
- Zusätzlicher, idempotenter Patch auf `Server.shutdown` als letzter Rückhalt:
  bei Überschreitung des Gesamtbudgets `force_exit = True` + `logger.error`.
  Der bestehende Patch auf `_wait_tasks_to_complete` bleibt unverändert.

---

## 4. Regressionstests — `tests/test_w5_d_shutdown.py`

Alle Tests fahren den Produktivpfad (Produzent → Konsument → Effekt → Verifikation):

| Test | Abgedeckter Effekt |
|---|---|
| `test_lifecycle_shutdown_timeout_is_bounded_and_audited` | Zwei hängende Hooks → Gesamt- und Einzelfenster greifen, `shutdown_hook`-Audit mit `failed: TimeoutError`, `cancel_failed`-Audit + `_FAILED_CANCELS`-Spiegel, Liveness-Stop im inneren `finally` |
| `test_lifecycle_stops_loops_before_closing_http_pools` | Mit den Produktiv-Hook-Namen aus `main.py` → `on_shutdown_graceful` zuerst, `_cancel_background_tasks` vor allen Pool-Close-Hooks |
| `test_graceful_shutdown_clamps_drain_and_bounds_phases` | `grace_seconds=60` wird auf ≤ 5 s gekappt; hängende Checkpoint-Phase (< 1 s Gesamt) → `shutdown_phase_timeout`-Audit, WAL-Phase läuft weiter |
| `test_uvicorn_guard_bounds_connection_drain_and_total_shutdown` | Fake-`uvicorn.server.Server`: Connection-Drain und Gesamt-Shutdown enden begrenzt mit `force_exit`; `install()` idempotent |

Keine Secrets, keine fremden Dateien, keine `sk-`-Strings.

---

## 5. Verifikation

Shell war in dieser Subagent-Session verfügbar; folgende Checks wurden hier ausgeführt,
sollen aber vom Koordinator zentral nachgezogen werden:

```
$env:ARCHON_TEST_DB_ISOLATION='1'
.venv\Scripts\python.exe -m py_compile <4 geänderte .py-Dateien>      # Exit 0
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 \
  --output-format=concise <4 geänderte .py-Dateien>                   # All checks passed
.venv\Scripts\python.exe -m mypy --config-file mypy.ini \
  <4 geänderte .py-Dateien>                                           # Success, 4 files
.venv\Scripts\python.exe -m pytest tests/test_w5_d_shutdown.py \
  tests/test_w3_rest.py -q                                            # 12 passed
.venv\Scripts\python.exe -m pytest tests/test_graceful_shutdown.py \
  tests/test_f32_livez_and_shutdown_nonblocking.py \
  tests/test_p0_welle_b.py -q                                         # 9 passed, 2 failed
.venv\Scripts\python.exe -m pytest tests/test_audit_fixes_batch.py \
  tests/test_fix_batch5.py -q -k "graceful or shutdown or drain or checkpoint"  # 2 passed
```

Nach dem letzten Lauf wurde nur noch eine Leerzeile in `graceful_shutdown_coordinator.py`
nachgezogen; ein erneuter Shell-Lauf wurde danach durch `pwsh.exe: Zugriff verweigert`
blockiert (bekanntes Subagent-Problem). Der Koordinator bitte zentral nachverifizieren.

**Zwei fehlgeschlagene Tests** in `tests/test_p0_welle_b.py`
(`test_chaos_watchdog_without_evidence_is_not_passed`,
`test_chaos_watchdog_with_stale_log_fails`) betreffen D10-M1
(`scripts/chaos_tester.py` liest `watchdog_daemon.log` statt `watchdog_liveness.json`).
Diese Dateien gehören zur **W5-B-Partition** und wurden von W5-D nicht berührt; die
Funde sind fachlich unabhängig von diesem Shutdown-Fix und bleiben dort zu klären.

---

## 6. Hinweis an den Koordinator

- `background_loops.py` wurde nicht geändert: sein 10-s-Cancel-`gather` ist bereits
  begrenzt; die von domain_10 geforderte Reihenfolge „Loops vor Pools" wurde stattdessen
  am Lifespan-Injektionspunkt (`lifecycle.py`) erzwungen, da `main.py` nicht zu dieser
  Partition gehört. Falls der Koordinator die Reihenfolge dauerhaft in `main.py`
  verankern will, ist das ein separater, nicht hier durchgeführter Schritt.
- Kein Commit, kein `git add`. `git status` zeigt ausschließlich zusätzlich die
  parallelen Änderungen anderer W5-Partitionen; diese stammen nicht aus W5-D.
- NEVER_DO_LIST eingehalten: kein Coroutine-Replay, keine PostgreSQL-Migration.

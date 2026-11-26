# W3-B — Orchestrierung: Fix-Report (26.11.2026)

**Welle:** W3 (Orchestrierung) · **Status:** implementiert, getestet, nicht committet
**Dateibesitz:** `archon/core/orchestration.py`, `backend/workflow_dag_runner.py`,
`backend/cancellation.py`, `backend/workflow_nodes/tool_loop.py`
**Soll-Referenz:** `audit_reports/00_SOLL_SPEC.md` §1.1/§3 · `docs/system/NEVER_DO_LIST.md`

> Hinweis zur ID-Zuordnung: Der Auftrag nennt den Idempotency-Befund „D07-M4".
> In `GEWICHTETE_BEFUNDLISTE.md` trägt derselbe Befund (`workflow_dag_runner.py`,
> Idempotency-Check/Record nur `DEBUG`) die ID **D07-M1**; D07-M4 ist dort der
> Loop-Log-Level-Befund in `background_loops.py`. Implementiert wurde — wie im
> Auftrag explizit beschrieben — der Idempotency-Pfad im DAG-Runner.
> `background_loops.py` liegt außerhalb des Dateibesitzes und wurde nicht berührt.

---

## 1. D02-H2 (HIGH) — Cancel-Lücke im Mission-Control-Dispatch

**Vorher:** `cancel_token.check()` nur an zwei Stellen. Die awaits bei Laden,
Lease-Acquire, Idempotency-Check und den Commit-Pfaden waren ungeprüft. Die
Lease-/Idempotency-Phase lag außerhalb des `try`, dessen
`except asyncio.CancelledError` das `status='cancelled'` schrieb. Ein Cancel
während `acquire_lease`/`check_or_register` entging der Persistenz vollständig
→ der Deadlock-Supervisor reaktivierte den Task als `approval`/`in_progress`
(Geisterlauf / Doppelausführung).

**Nachher** (`archon/core/orchestration.py`):

- Cancel-Token wird **vor** dem ersten await registriert (`:322-330`).
- Die **ganze Rest-Funktion** (Laden, Profilauflösung, Lease, Idempotency,
  Heartbeat, LLM-Dispatch, Obsidian, Auto-Staffing, `finally`) liegt im äußeren
  `try` (`:365`) mit einem äußeren `except asyncio.CancelledError` (`:730-750`).
  Der Handler setzt `task["status"]="cancelled"`, stoppt den Heartbeat und
  persistiert über `await asyncio.shield(_commit_async())`, danach `re-raise`.
  Ein zweiter Cancel während dieses Commits wird abgefangen und geloggt; die
  bestehenden shield-geschützten Cleanups im `finally` bleiben unverändert.
- `cancel_token.check()` steht jetzt nach **jedem** await: Laden (`:375`),
  Lease-Acquire (`:413`), Lease-Fehler-Commit (`:431`), Idempotency-Check
  (`:452`), Idempotency-Cache-Commit (`:461`), Vor-Dispatch-Commit (`:491`),
  bestehender Pre-Dispatch-Check (`:494`), LLM-Dispatch (`:505`) und
  Obsidian-Ablage (`:526`).
- Der Task wird für die Persistenz **nach** dem Laden aufgelöst, damit auch ein
  bereits vorab abgebrochener Scope noch `cancelled` in den Store schreibt.

**Verifikation:** `test_d02_h2_cancel_during_lease_persists_cancelled`,
`test_d02_h2_pre_cancelled_scope_persists_cancelled_without_dispatch`.

## 2. D02-H3 (HIGH) — Fail-Open bei gestörter Profil-SSOT

**Vorher:** `except Exception: prof = {}` (still), und der Block-Guard enthielt
die Klausel `and profiles`. Bei leerer/fehlerhafter SSOT war die Bedingung
`False`, der Knoten lief mit Generik-Prompt und Default-Modell unter ungeprüfter
`agent_id` weiter (Rollenbudget / Tool-Scope / EU-AI-Act-Klasse undefiniert).

**Nachher** (`backend/workflow_dag_runner.py`):

- SSOT-Fehler wird auf `logger.error` angehoben und über
  `_recovery_audit("profile_ssot_unavailable", …)` auditiert (`:1622-1635`).
- Die `and profiles`-Klausel ist entfernt (`:1646`): explizite nicht-`default`
  `agent_id` + fehlendes Profil ⇒ **immer** `blocked` / `UNKNOWN_AGENT_ID`,
  unabhängig davon, ob die SSOT leer ist oder die Auflösung scheiterte.

**Verifikation:** `test_d02_h3_profile_ssot_error_blocks_unknown_agent`
(kein LLM-Call, Audit-Event vorhanden).

## 3. D02-M1 (MED) — Run-Cap erst nach erstem Token wirksam

**Vorher:** `_node_est = float(node.get("max_budget_eur") or 0.0)` → 0 bei
unbeziffertem Node; `_node_budget_ok()` sah beim Initial-Dispatch 0 Tokens.
Ein einziger Node konnte den Run-Cap überschreiten, bevor die Grenze griff.

**Nachher** (`backend/workflow_dag_runner.py`):

- Neuer Helper `_estimate_dag_node_cost_eur()` (`:1374`): prognostiziert über
  `estimate_model_cost_usd(model, in, out) * USD_TO_EUR_RATE`, mit deklarierten
  Token-Schätzungen des Nodes oder einem konservativen Default (4096/1024).
- Im Budget-Gate vor jedem Dispatch (`:2344-2357`) ersetzt die Prognose die 0,
  sobald der Node keinen eigenen Cap hat. Bei Überschreitung bleibt der
  bestehende fail-closed Block `blocked` / `budget_exhausted` / `needs_human`.
- Der **verbleibende Run-Rest** wird als `_dag_run_cap_remaining_eur` in den
  Node-Kontext injiziert (`:2409`) und von `_node_budget_ok()` als effektiver
  Node-Cap bevorzugt (`:1407-1413`). Damit greift der Run-Cap auch bei
  Tool-Loop-Folgedispatchen, nicht erst beim nächsten DAG-Knoten.

**Verifikation:** `test_d02_m1_prognosis_blocks_first_unpriced_node`
(Executor wird nie aufgerufen, Node `blocked/budget_exhausted/needs_human`).

## 4. D07-M4 (Auftrags-ID) — Idempotency-Fehler nur DEBUG

**Vorher:** `check_or_register`-Fehler wurde auf `DEBUG` geloggt und der
Executor trotzdem aufgerufen; `record_execution_result`-Fehler ebenfalls nur
`DEBUG` → kein gecachter Erfolg, Seiteneffekt beim Retry erneut.

**Nachher** (`backend/workflow_dag_runner.py`, `_exec_with_retry_and_timeout`):

- Check-Fehler (`:1960-1974`): `logger.error` + `_recovery_audit("idempotency_check_failed", …)`
  + sofortige Rückgabe von `_blocked_node_result(node, "IDEMPOTENCY_UNAVAILABLE")`.
  **Kein Executor-Aufruf**, wenn ein `idempotency_key` gesetzt ist.
- Record-Fehler (`:1994-2015`): `logger.error` + `_recovery_audit("idempotency_record_failed", …)`
  + Node als `error` mit `IDEMPOTENCY_RECORD_FAILED`, `needs_human=True`.

**Verifikation:** `test_d07_m4_check_failure_blocks_without_executor`,
`test_d07_m4_record_failure_marks_node_error`.

---

## 5. Tests & Ergebnisse

Neue Datei: `tests/test_w3_b_dag_cancel.py` — 6 Tests (eine pro Fix plus
Pre-Cancel-Variante). Alle 6 grün.

Regressionslauf (mit `ARCHON_TEST_DB_ISOLATION=1`, siehe unten):

```
118 passed in 9.10s
```

Enthalten: `test_w3_b_dag_cancel.py`, `test_orchestration.py`,
`test_orchestration_atomic.py`, `test_f30_mc_core_nonblocking.py`,
`test_f40_high_regressions.py`, `test_f22_dag_and_delegation_gates.py`,
`test_workflow_dag_e2e.py`, `test_d1_executor_characterization.py`,
`test_fix_w3_d_trajectory_dag.py`, `test_p0_hotfixes_review_2026_11.py`.

**Umgebungshinweis:** Ohne DB-Isolation scheitern 6 `test_workflow_dag_e2e.py`-
Tests an der bereits dokumentierten korrumpierten `data/memory.db` des
laufenden Containers (`[otel_tracer] … database disk image is malformed`,
siehe `tests/conftest.py:1-18`). Mit `ARCHON_TEST_DB_ISOLATION=1` laufen alle
DAG-E2E-Tests grün; die Ursache liegt nicht in diesem Fix.

## 6. Abgrenzung / NEVER_DO_LIST

- Kein Coroutine-Replay, kein Event-Sourcing, keine PostgreSQL-Migration —
  alle Fixes nutzen persistierte States/Checkpoints und SQLite.
- `backend/cancellation.py` und `backend/workflow_nodes/tool_loop.py` wurden
  **nicht verändert** (W1-Tenant-Korrektur in `tool_loop.py` bleibt erhalten).
- Keine Commits, keine fremden Dateien, kein Replay/Postgres.

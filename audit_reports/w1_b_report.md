# W1-B (Fundament/DB) — D03-H2: Mandantenisoliertes DAG-Ledger

**Status:** implementiert (statisch verifiziert). Shell/Python in dieser Sandbox
gesperrt (`pwsh.exe … Zugriff verweigert, os error 5`) → **keine Tests ausgeführt**.
Zentrale Verifikation durch den Koordinator erforderlich.

## Befund (Ist vor dem Fix)

`backend/workflow_dag_runner.py:788-839`: `_resolve_dag_db_path()` rief
`resolve_db("workflow_dags.db")`. Da `workflow_dags.db` weder in
`ISOLATED_TENANT_DBS` noch `CONSOLIDATED_TENANT_DBS` (`tenant_context.py:62-63`)
steht, mappede `db_paths.resolve_db()` über `CONSOLIDATION_DOMAIN_MAP` auf die
globale `data/ops.db`. `workflow_runs` (PK `run_id`) und
`workflow_node_states` (PK `(run_id, node_id)`) hatten keine `tenant_id`:
gleiche `run_id` zweier Mandanten überschrieb sich, fremde
`gate_approvals_json` / `output_json` wurden beim Resume gelesen.

## Umsetzung

### 1. DB-Pfad (hart fail-closed)
`workflow_dag_runner.py:991-1011` — `_resolve_dag_db_path()` nutzt jetzt
`tenant_context.resolve_active_db("ops.db")` → `data/tenants/<tid>/ops.db`.
Bei Auflösungsfehler `RuntimeError`, **kein** Fallback auf `DEFAULT_DB_PATH`.
Der verbleibende `DEFAULT_DB_PATH`-Zweig ist ein bewusster Test-/Operator-
Override (kein Fehlerpfad). Explizit übergebene `db_path` (Tests) bleiben gültig.

### 2. Schema + Migration
`workflow_dag_runner.py:820-988`:
- `workflow_runs`: `tenant_id TEXT NOT NULL`, PK `(tenant_id, run_id)`.
- `workflow_node_states`: `tenant_id TEXT NOT NULL`, PK
  `(tenant_id, run_id, node_id)`.
- Der Spalten-Default ist der **aktive Primärmandant** (i. d. R.
  `archon-systems`), nicht der hartcodierte Wert `default`. Damit bleiben
  Bestandszeilen und Legacy-Inserts ohne `tenant_id` für genau den Mandanten
  sichtbar, in dessen DB sie liegen (Kompatibilität mit bestehenden Tests).
- Additive, bestandskompatible Migration: fehlende Spalten werden mit DEFAULT
  ergänzt (Bestandszeilen → aktiver Primärmandant), danach Table-Rebuild für
  den PK-Wechsel (`ALTER TABLE` kann SQLite-PKs nicht ändern). Migration läuft
  unter `BEGIN IMMEDIATE` + Prozess-Lock; Fastpath ohne Schreiblock.
- Ein stehengebliebener `*_tenant_legacy`-Rest bricht hart ab (kein
  Datenverlust durch Überschreiben).
- `sqlite3.connect(timeout=10.0)` → SSOT `DB_BUSY_TIMEOUT_S` (5000 ms);
  `PRAGMA busy_timeout` aus `DB_BUSY_TIMEOUT_MS` (mit `db_paths` synchron).

### 3. Alle Queries tenant-skaliert
Identität pro Verbindung über `ContextVar` (`_DAG_TENANT_VAR`, gesetzt in
`_connect`, `workflow_dag_runner.py:1014-1033`) — funktioniert auch über
`asyncio.to_thread` (Context-Copy). Betroffene Zugriffe, alle mit
`WHERE tenant_id = ?` / `ON CONFLICT(tenant_id, …)`:

| Stelle | Pfad |
|---|---|
| Cancel-Persistenz | `_persist_run_cancelled_sync` (:103-123) |
| Status-Insert/Upsert | `_persist_run_status_sync` (:126-140) |
| `gate_approvals_json` lesen + Cache | `_load_run_gate_state_sync` (:143-197) |
| `output_json` Node-States | `_persist_node_state_sync` (:200-232) |
| Verify/Kosten/Tokens | `_finalize_run_sync` (:235-347) |
| Replan (blocked/dag_json) | `request_dag_replan` (:749-783) |
| HITL-Decision-Dedupe | `_register_hitl_gate_decision` (:1195-1220) |
| Resume-Abfrage | `get_workflow_run` (:2680-2727) |
| Liste | `list_workflow_runs` (:2730-2742) |
| SUSPENDED-Resume | `resume_suspended_workflow_run` (:2985-2991) |
| Failed-Persistenz | `schedule_workflow_resume` (:3074-3078) |

Öffentliche APIs (`run_workflow_dag`, `resume_workflow_run`,
`resume_suspended_workflow_run`, `schedule_workflow_resume`,
`request_dag_replan`, `get_workflow_run`, `list_workflow_runs`) erhielten ein
optionales `tenant_id`-Keyword; ohne expliziten Wert gilt der ContextVar /
aktive Mandant. Per-Run-Lock ist jetzt `(tenant_id, run_id)`-skaliert.
Resolverfehler in den try/except-Pfaden von Cancel und HITL-Dedupe werden
als `RuntimeError` **weitergeworfen** (nicht als "kein Duplikat"/Error-Dict
interpretiert).

### 4. Regressionstest
`tests/test_w1_b_dag_tenant.py` (6 Tests):
- Resolver verwendet `ops.db`, bricht bei Fehler hart ab (kein Fallback).
- Fehlender Tenant-Kontext bricht Ledger-Zugriff ab.
- Schema: `tenant_id NOT NULL`, PK wie oben.
- Legacy-Migration: Bestandszeilen → aktiver Primärmandant, identische `run_id` des
  zweiten Mandanten kollidiert nicht.
- **Zwei-Tenant-Test**: identische `run_id`/`node_id` → zwei Zeilen; getrennte
  Gate-Freigaben, getrennte Outputs/Caches, `get_workflow_run` + `list_…`
  liefern nur den eigenen Mandanten, Cancel und Verify wirken nur lokal.
- ContextVar-Pfad ohne expliziten Parameter.

## Bewusst nicht geändert

- `backend/db_paths.py`, `backend/tenant_context.py`: beide boten die
  benötigten APIs bereits (`resolve_active_db`, `sanitize_tenant_id`,
  `CONSOLIDATED_TENANT_DBS` enthält `ops.db`). Keine Änderung nötig —
  `resolve_tenant_db()` behält seinen (für andere Module vorgesehenen)
  Fallback; der DAG-Pfad nutzt ihn nicht.
- Kein PostgreSQL, kein Replay, keine Content-Domäne (NEVER_DO_LIST beachtet).

## Restrisiko / Follow-up (Koordinator)

`backend/workflow_nodes/tool_loop.py:123-127` (außerhalb meines Dateibesitzes)
schreibt Tool-Checkpoints mit `ON CONFLICT(run_id, node_id)`. Durch den neuen
PK `(tenant_id, run_id, node_id)` passt dieser Conflict-Target nicht mehr; der
Schreibfehler wird dort bereits in `except Exception` nur auf DEBUG geloggt
(best-effort Checkpoint, kein Datenverlust im DAG-Hauptledger). Empfehlung:
ein Follow-up mit `ON CONFLICT(tenant_id, run_id, node_id)` und expliziter
`tenant_id` aus `node["_dag_tenant_id"]` (vom DAG-Runner in `node_ctx`
ergänzt). Ich habe diese Datei nicht angefasst.

## Verifikation (offen)

```
pytest tests/test_w1_b_dag_tenant.py -q
pytest tests/test_workflow_dag_e2e.py tests/test_f34_resume_and_force_done_nonblocking.py \
       tests/test_fix_w3_d_trajectory_dag.py -q
python -m backend.db_paths --audit-busy-timeout
```

# Fix T3 — MyPy-Typfehler in `archon/routers/memory.py` und `archon/routers/execution.py` (25.11.2026)

> Grundlage: Full-Run-Output `sh_2124093e1001f5XXGxcQnlxcxm.out`, `mypy.ini`.
> **Exklusives Ownership eingehalten:** nur die zwei zugewiesenen Dateien.
> Keine Änderung an anderen Routern, an `mypy.ini`, an Tests oder an Daten.

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler `archon/routers/memory.py` | **49** | **0** |
| MyPy-Fehler `archon/routers/execution.py` | **49** | **0** |
| Summe Ownership-Dateien | **98** | **0** |
| Geänderte Dateien | — | **2** |
| Neue Ignores / Pauschal-Pragmas | — | **0** |

Die 98 Fehler waren alle derselben Klasse: `payload` ist ein Pydantic-Request-Modell,
wurde aber mit `model_dump()` / `_as_payload()` zum `dict[str, Any]` umgebunden.
Danach meckert MyPy sowohl über die Zuweisung (`assignment`) als auch über
`payload.get(...)` am Modell (`attr-defined`).

## 2. Auflösung

| Datei | Fix | Umfang |
|---|---|---|
| `archon/routers/memory.py` | `payload = payload.model_dump()` → `data = payload.model_dump()`; alle Folgezugriffe `payload.get(...)` → `data.get(...)` | 10 Zuweisungen, 39 Zugriffe |
| `archon/routers/execution.py` | `payload = _as_payload(payload)` → `data = _as_payload(payload)`; alle Folgezugriffe `payload.get(...)` → `data.get(...)` | 11 Zuweisungen, 38 Zugriffe |

Rein namensbasierte Umbenennung einer lokalen Variable. **Keine Laufzeit- oder
Gate-Logik verändert:**

- `require_admin_or_503(request)` / RBAC-Rollenzaun bleibt an derselben Stelle.
- Map-Reduce: `demo`-Flag, `make_dispatcher_worker_fn()`-Entscheidung und
  `result["demo_only"]` unverändert.
- Durable Checkpoint: `state_payload`, `completed_steps`, `status` und die
  `int(...)`-Konvertierungen unverändert.
- Idempotency, Dry-Run, DLQ: `simulate_success`-Default `False` (echter Replay)
  und alle Felder unverändert.
- Queue: `priority`, `idempotency_key`, `max_retries`, Lease und CAS-Ablauf
  unverändert. Keyword-Argumente (`payload=...`) blieben bewusst unangetastet;
  nur der rechte Seite `data.get("payload", {})` wurde umbenannt.

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (Ownership-Dateien) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty archon/routers/memory.py archon/routers/execution.py` | **Success: no issues found in 2 source files** |
| Syntax | `.venv\Scripts\python.exe -m compileall -q archon/routers/memory.py archon/routers/execution.py` | **Exit 0**, keine Ausgabe |
| Gezielte Tests | `pytest tests/test_p0_api_validation_execution.py tests/test_p0_api_validation_memory_mesh.py tests/test_p1_durable_execution_kernel.py tests/test_memory_system.py tests/test_med2_d_routers.py -q --tb=short` | **33 passed in 5.85s** |
| Full-Suite | `.ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` | **2342 passed, 16 skipped, 2 warnings in 267.51 s** |

`ARCHON_DATA_DIR` war ausschliesslich ein frisches
`C:\Users\micha\AppData\Local\Temp\opencode\archon-t3-*` (`-mem-exec-<PID>` bzw.
`-full-<PID>`). `./data/**` wurde nicht beschrieben.

## 4. Bemerkungen

1. Keine `# type: ignore` hinzugefügt, keine entfernt, keine `mypy.ini`-Regel
   gelockert. `warn_unused_ignores` / `warn_redundant_casts` bleiben aktiv.
2. Die Umbenennung ist semantisch neutral: `data` enthält exakt denselben
   `dict`, den vorher der überschriebene Name `payload` hielt.
3. Die zwei Warnungen der Full-Suite stammen aus `test_loop_liveness.py`
   (Starlette `timeout`-Deprecation) und `test_m48_mcp_gateway.py`
   (Boardroom-Fallback-Coroutine); beide sind vorbestehend und betreffen nicht
   die Ownership-Dateien.

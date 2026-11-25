# Fix T8 — MyPy-Restmenge + ≤2-Fehler-Dateien (25.11.2026)

> Subagent-Auftrag aus dem Full-Run-Output
> `sh_2124093e1001f5XXGxcQnlxcxm.out`. Exklusives Ownership eingehalten:
> die 21 zugewiesenen Dateien sowie die übrigen Dateien mit ≤2 Fehlern, die
> keinem anderen Agenten gehören. **Keine Datei eines anderen Agenten berührt**,
> kein globales Disable, kein `# mypy: ignore-errors`, keine Pauschal-Ignores.

## 1. Zahlen

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in Ownership-Dateien | ~137 | **0** |
| Geänderte Dateien | — | **59** (21 Kern + 38 Rest Dateien) |
| MyPy (Ownership, explode Runs) | ~137 | **Success: no issues found** |
| MyPy (Sanity `archon backend utils scripts plugins`, 406 Dateien) | — | 1 Restfehler, **außerhalb Ownership** (T7) |
| `compileall` | — | **0 Fehler** |
| `pytest -q tests/` (Temp-`ARCHON_DATA_DIR`) | — | **2342 passed, 16 skipped** |
| `audit_secrets.py --all` | — | **0 Funde** (7072 Dateien) |

## 2. Muster der Fehler

### `payload = model_dump()` / `as_payload()` → neue lokale Variable
Wie vorgegeben wurde das Ergebnis nicht mehr in die model-typisierte
Parameter-Variable geschrieben; alle Folgeverwendungen wurden umbenannt:

- `swarm.py`: `data = _as_payload(payload)`
- `deals.py`: `data = as_payload(payload)` (2 Endpunkte)
- `updater.py`: `data = as_payload(payload)`

### Weitere Typ-Fixes (Auswahl)
- **Lokale Typannotationen** fehlender leerer Container: `dead_letter_queue.py`
  (`_RUNNING_TASKS`), `context_compactor.py`, `secret_files.py`,
  `content_machine.py` (`base: Dict[str, Any]`), `event_mesh.py`,
  `dual_llm_sanitizer.py`, `es_translate_local.py`, `translate_locales.py`,
  `build_system_handbuch*.py`, `backup_to_nas.py`, `speculative_prefetcher.py`,
  `bench_routes.py`.
- **Variablen-Kollisionen** aufgelöst: `process_and_sort_avatars.py` (`f` → `fh`),
  `vault_hygiene.py` (`f` → `fh`), `contract_manager.py` (`mo` → `month_num`,
  `pat` → `date_pattern`), `prompts.py` (`reader` → `csv_reader`),
  `hybrid_search_engine.py` (`doc` → `doc_entry`),
  `eval_regression_runner.py` (`simulated` → `outputs`),
  `plugin_manager.py`, `cancellation.py`.
- **Implizites Optional** durch explizites `Optional[...]` ersetzt:
  `docker_services.py`, `internet_watchdog.py`, `calendar_aggregator.py`,
  `notification_hub.py`, `tool_permission_manager.py`, `skill_synthesizer.py`,
  `pii_scrubber.py`, `hermes_profiles.py`. In `hermes_profiles.py` muss die
  `Request`-Annotation erhalten bleiben (FastAPI erkennt `Optional[Request]`
  nicht als Request-Parameter) → **gezielter** `# type: ignore[assignment]`.
- **Plattform-APIs** (Windows-Stubs): `self_evolving_tooling.py` (`resource`),
  `system_updater.py` (`os.killpg`/`signal.SIGKILL`) über `Any`-Alias
  typisiert — Laufzeitverhalten unverändert, keine Ignores.
- **Security-kritisch**: `utils/secret_files.py` — nur Typannotationen und
  eine `if not path`-Guard; **keine Härtungslogik verändert**.
- **JIT-Persona-Router**: `operations_autonomy.py` nutzte nicht existierende
  kwargs der Engine; auf reale Signatur abgebildet (`task_prompt`,
  `domain_hint`, `prompt`), Kontext in den Prompt übernommen und
  `auto_purge_on_complete` über `purge_persona()` umgesetzt (der Endpunkt
  war vorher zur Laufzeit ein `TypeError`).
- **Ungenutzte `type: ignore`s** entfernt: `chat.py` (3), `uvicorn_shutdown_guard.py`,
  `passkey_hitl.py`, `deadlock_supervisor.py`.
- **Monkey-Patch** in `uvicorn_shutdown_guard.py` auf `setattr(...)` umgestellt
  (`method-assign`): semantisch identisch.
- **Return-Typen**: `docker_services.py` (`dict | JSONResponse`),
  `contract_manager.py`/`deal_pipeline.py` (`... or {}` bei `Optional`-Get),
  `container_ops.py` (Klassen-Annotationen für dynamische `BlockedDispatch`-Felder).
- **Tenant-API**: `speculative_prefetcher.py` und `dunning_engine.py` nutzten
  das nicht existierende `get_active_company_id` → `tenant_context.get_active_tenant_id()`.

## 3. Verifikation

```powershell
# MyPy, Ownership in Batches — alle 0 Fehler
.venv\Scripts\python.exe -m mypy --config-file mypy.ini --no-pretty <Ownership-Dateien>

# Sanity-Lauf (406 Dateien): nur 1 Restfehler, nicht in Ownership
archon\routers\operations_calendar.py:55: error: Invalid type comment or annotation
```

`pytest` lief ausschließlich gegen Temp-Verzeichnisse
(`ARCHON_DATA_DIR=<temp>\archon_t8_verify_data`, `ARCHON_TEST_DB_ISOLATION=1`);
`./data` wurde nicht beschrieben. `.ci_venv` wurde wegen fehlendem
`cryptography` im `.venv` verwendet.

## 4. Nicht verändert

- `mypy.ini`, `pytest.ini`, `conftest.py`, `requirements*.txt`
- `./data`
- Härtungs-/RBAC-/Actor-Logik (insbesondere `utils/secret_files.py`)
- `archon/routers/operations_calendar.py` (T7-Ownership): der dort verbleibende
  `valid-type`-Fehler in Zeile 55 (`conint(...)` in einer Typannotation) wurde
  **nicht** angefasst, da die Datei einem anderen Agenten gehört.

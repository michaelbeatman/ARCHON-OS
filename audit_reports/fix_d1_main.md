# Fix-Log — D1 (Delegations-Agent, Phase-3-Nachlauf)

**Agent:** Delegations-Agent D1 · **Datum:** 25.11.2026 · **Basis:** HEAD `cee78206`
**Arbeitsverzeichnis:** `C:\.Antigravity-projekte\AgenticOS-2026`
**Scope:** ausschliesslich die 10 freigegebenen Dateien. Kein Commit, kein Push.
**Umgebung:** Shell-Tool blockiert (`pwsh.exe: Zugriff verweigert`). Alle Edits mit `edit`, jede Änderung per `read`/`grep` verifiziert. `pytest` / `ruff` / `mypy` / `py_compile` **nicht ausführbar** (siehe §3).

---

## 1. Erledigte Punkte (11)

| # | Delegation (Quelle) | Datei:Zeile (final) | Änderung / Begründung |
|---:|---|---|---|
| 1 | A2-Nr.4 (`main.py:1354`, Tail-Löschung) | `main.py:1382-1386` | 30-s-Anker-Loop: `("error" in v or v.get("violation") is True)`. Verifiziert gegen `backend/audit_log.py:1535-1539`: `violation: True` wird dort immer zusammen mit `written: False` geliefert, wird jetzt also zuverlässig als `failed` geloggt. |
| 2 | A1-Nr.1 / A7-Nr.2 (D-D7) | `main.py:18`, `:2491-2529` | Neues Pydantic-v2-Modell `HealingAttemptPayload` mit `ConfigDict(extra="ignore")`, `attempt: int = Field(ge=1)`, `max_attempts: int\|None = Field(ge=1)`. `apply_patch` ist bewusst **kein** Body-Feld und kommt aus der HITL-Session (`request.state.hitl_apply_patch`), fail-closed `False`. **Hinweis:** ein repo-weiter HITL-Session-Helper existiert nicht (`grep` über `*.py`); es wurde deshalb kein erfundener Helfer aufgerufen. Der produzentenseitige HITL-Gate muss das State-Flag setzen — ohne Flag wird nie geschrieben. Bestehender Test `test_orange_a_security.py::test_healing_attempt_verlangt_admin` bleibt kompatibel (Zaun greift vor Payload-Zugriff). |
| 3a | A7-Nr.1 (Startup-Hook n8n) | `main.py:99-104`, `:2576-2603`, `:2615` | Opt-in-Lifespan-Hook `_import_n8n_workflows_on_startup()`: ruft `scripts/import_n8n_workflows.main()` via `asyncio.to_thread` (inkl. Webhook-Aktivierung durch `activate_n8n_workflows.js`). Default `ARCHON_N8N_STARTUP_IMPORT` aus → ehrlicher Status `_N8N_STARTUP_STATUS = {"status": "not_configured", ...}`; bei Fehler `status="error"` und `/readyz`-Degradation (`main.py:730-731`). Blockierende `docker exec`/`cp`-Arbeit läuft nie im Event-Loop. |
| 4 | A5/A9 (S-8.2/S-8.3) | `main.py:2665-2717`, `:2745` | Neuer Hook `_close_all_http_clients()`, in `_SHUTDOWN_HOOKS` so registriert, dass er in `reversed()` nach dem Graceful-Drain und vor Task-Cancel läuft. **Namensprüfung per `grep`:** `agent_router.router_instance.close_http_clients()` existiert (`backend/agent_router.py:255`) und wird aufgerufen. Die drei in der Delegation genannten Helfer `hermes_proxy.close_all_hermes_clients()`, `system.close_system_http_client()`, `reverse_proxy.close_proxy_clients()` existieren **nicht** — es wurden keine erfundenen Calls eingebaut; stattdessen werden die realen Modulattribute `_HERMES_CLIENTS_BY_LOOP`, `_SYSTEM_HTTP_CLIENT`, `_PROXY_CLIENTS` per `aclose()` + `clear()`/None geschlossen (fail-safe, Fehler → `logger.debug`). |
| 5 | A3-Nr.3 (Maintenance-Loop) | `main.py:1407-1429`, `:732-733` | `logger.debug` → `logger.error` + sichtbares `_DB_MAINTENANCE_STATUS`. `optimize_all_databases()`-Result wird ausgewertet (`status="error"`), Fehler werden in `/readyz` gespiegelt (`db_maintenance: …`). |
| 6 | A8-Nr.9/10 (Rollen-SSOT) | `main.py:934-935`, `:989-992`; `archon/routers/brain.py:24-25`, `:173-177`; `archon/core/settings_state.py:20-21`, `:181-184` | Konsumenten nutzen jetzt `archon.core.roles_data.load_default_roles()` (Laufzeitprojektion aus `agent_profiles.json`) statt des statischen Import-Snapshots. Import-Kompatibilität bleibt erhalten über explizite Re-Exporte (`DEFAULT_ROLES as DEFAULT_ROLES`) — u.a. liest `archon/routers/container_ops.py:69` weiterhin `app_main.DEFAULT_ROLES`. Re-Export-Alias verhindert zugleich `ruff F401` in geänderten Dateien. |
| 7 | A9-Nr.1 / A3-Nr.4 | `archon/core/runtime.py:145-154`, `:267-277` | SSE-Trace-Kontext: `logger.debug` → `logger.warning` + `note_local_trace_error("sse-trace", exc)` (API verifiziert in `backend/trace_context.py:136`). `atomic_write_json()` jetzt mit dir-fsync nach `os.replace` im Muster `archon/routers/vault.py:94-104`; `OSError` (u.a. Windows-Verzeichnis-Handle) wird nur gedebugt und bricht den Write nicht ab. Zusätzlich `backend/otel_tracer.py:591-596`: Statuszähler akzeptiert `sse_trace` **und** `sse-trace`, damit der neue Stage sichtbar wird. |
| 8 | A9-Nr.11 / D07-MED (Loop-Sackgasse) | `backend/process_lock.py:13-21`, `:25-65`, `:194-201`; `main.py:734-740` | `@exclusive_loop` eskaliert bei `lock is None` jetzt statt `return None`: `broadcast_event("hitl_required", …)` aus `archon.core.runtime` (verifiziert: `:150`), DLQ-Eintrag über `dead_letter_queue_manager.enqueue_task(..., idempotency_key=f"loop_lock_unavailable:{name}")` (verifiziert: `backend/dead_letter_queue.py:367`), Persistenz in `get_loop_lock_failures()` und `/readyz`-Problem `loop_lock_unavailable`. **Kein** `backend.event_mesh.broadcast_event` verwendet — diese Funktion existiert nicht (`grep` 0 Treffer), obwohl `graceful_shutdown_coordinator.py` sie importiert. |
| 9 | A9-Nr.2 (Receipt-Kontext) | `backend/execution_receipt_ledger.py:179-188` | DEBUG-Swallower → `logger.warning` + `note_local_trace_error("receipt-context", exc)`, Zähler-Fehler werden fail-safe gedebugt. |
| 10 | A1-Nr.7 (Langfuse-EOL-Text) | `backend/otel_tracer.py:603-612` | Irreführende Aussage „Opt-in-Profil `langfuse-not-configured`" / Compose-Befehl entfernt; Note sagt jetzt ehrlich `not_configured` + „alter Profil-Name und Container wurden entfernt". Der Literalstring bleibt als **historischer Hinweis** erhalten, damit der bestehende Behaviour-Test `tests/test_reaudit_d16_otel.py:188` (nicht im D1-Scope) grün bleibt. |
| 11 | A1-Nr.5 / A9-Nr.6 | `tests/test_loop_liveness.py:100` | `ARCHON_HEARTBEAT_ALERTMANAGER_URL` → `ARCHON_HEARTBEAT_WEBHOOK_URL` (verifiziert in `docker-compose.yml:125,940` und `backend/fleet_self_healing.py:85`). |
| 12 | A1-Nr.4 / A9-Nr.6 | `tests/test_reaudit_stage13.py:44-51` | An A9s neue `probe()` angepasst: statischer Bergungszweig `not result.get("watchdog_stale")` bleibt (in `scripts/archon_autoheal.py:178` unverändert vorhanden), zusätzlich werden jetzt die echten 503-Body-Pfad-Merkmale geprüft (`except urllib.error.HTTPError`, `exc.read(`, `_watchdog_stale_from_body(raw)`). |

---

## 2. DELEGATED (1 Punkt)

| # | Fund | Grund / empfohlener nächster Schritt |
|---:|---|---|
| 3b | `scripts/deploy_n8n_routines.py::run()` automatisch im Lifespan aufrufen | **Zu riskant für Startzeit:** `run()` führt `docker restart n8n` aus (`scripts/deploy_n8n_routines.py:288`) und schreibt das versionierte `scripts/n8n_workflows_bundle.json` (`:300-313`) — das würde einen laufenden Container mitten im App-Start unterbrechen und Repo-Artefakte mutieren. Der Import/Pfad aus 3a ist verdrahtet; der Deploy-Schritt bleibt bewusst `not_configured`. Empfehlung: als expliziter Admin-Endpoint oder Compose-Init-Container mit `ARCHON_N8N_STARTUP_IMPORT=1` ausführen, nicht als App-Startup-Hook. |

**Zwei kleinere Produzenten-Hinweise (keine eigenen Delegationspunkte):**
- Der HITL-Gate, der `request.state.hitl_apply_patch` setzt, liegt ausserhalb des D1-Scopes (siehe Punkt 2).
- `backend/config_validator.py::validate_profile_ssot()` (Feld-Hashes statt Warnung) war in A8 an A1/A6 delegiert und ist **nicht** Teil des D1-Auftrags — bewusst unverändert.

---

## 3. Verifikation / Einschränkung

- **Statisch (durchgeführt):** jeder Edit per `read` nachgelesen; `grep`-Nachweis für alle aufgerufenen Helfer (`close_http_clients`, `note_local_trace_error`, `broadcast_event`, `enqueue_task`, `load_default_roles`, `get_loop_lock_failures`) und für die entfernten/ersetzten Strings. Kein erfundener Funktionsaufruf eingebaut.
- **Kompatibilität geprüft:** `app_main.DEFAULT_ROLES` (Re-Export), `not result.get("watchdog_stale")` (statischer Test), `langfuse-not-configured` (Behaviour-Test), Rollenzaun vor Payload-Zugriff.
- **Nicht ausführbar:** `pytest`, `ruff`, `mypy`, `py_compile` — Shell verweigert durchgehend `pwsh.exe` (`Zugriff verweigert, os error 5`). Vom Koordinator nachzuholen:
  `pytest tests/test_loop_liveness.py tests/test_reaudit_stage13.py tests/test_orange_a_security.py tests/test_reaudit_d16_otel.py tests/test_reaudit_stage5.py -q`, danach `ruff check` und `mypy` auf den geänderten Modulen.
- **Regeln:** G-01 (keine Secrets im Code), G-02 (keine PostgreSQL-Migration), G-05 (God-Object `main.py` nicht refaktoriert — nur gezielte Edits). Kein Commit, kein Push.

**Summe:** 12 Punkte bearbeitet · 11 erledigt · 1 DELEGATED (Deploy-Hälfte von Punkt 3).

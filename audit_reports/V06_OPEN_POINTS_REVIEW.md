# v0.6 FINALE OFFENE PUNKTE — Unabhängiges Review vor Push (26.11.2026)

**Prüfer:** Antigravity / Gemini Neon (modellfremder Zweitblick auf Hy4-Commit `5f5c0bb8`)  
**Worktree / HEAD:** `C:\Users\micha\.local\share\opencode\worktree\b1d671\fullscan-d5` @ `b51b6359`  
**Modus:** Strikt read-only auf Repo-Code & Produktiv-State; RT1-PoCs in isoliertem Temp (`Temp\opencode\v06-rt1-fixed\`).  
**Kein Push, kein Commit, kein Code-Change.**

---

## 1. Ergebnistabelle aller Prüfpunkte

| Punkt | Kritikalität | Pfad:Zeile / PoC-Exit | Urteil | Empfehlung |
|---|---|---|---|---|
| **1a. `background_loops.py` Timeout-Pfad (`5f5c0bb8`)** | **PASS (0 Findings)** | `archon/services/background_loops.py:390-420`; `tests/test_v06_p0_p2_shutdown_and_dag_cleanup.py:92-137` | Bei `asyncio.TimeoutError` bleibt `results=None` → kein Double-Record mit `:419`. `task.cancelled()` + `try/except asyncio.CancelledError` schützt `task.exception()`; `task_exc is None` filtert saubere Tasks; `audit_errors` bewahrt Strict-Eskalation + `_BACKGROUND_TASKS`-Cleanup im `finally`. | Übernehmen, kein Nachbesserungsbedarf. |
| **1b. `security_audit_hook/plugin.py` Workspace-Jail (`5f5c0bb8`)** | **LOW (Minor Note)** | `plugins/security_audit_hook/plugin.py:46-59` | `Path.resolve()` löst Symlinks, `..` und `//` auf; `is_relative_to(workspace_root)` greift jetzt auf **jeden** Pfad; `sensitive_targets` ist case-insensitive. Einzige Restkante: ohne `context["workspace_root"]` / `config["workspace_root"]` fällt `:53` auf Prozess-CWD `"."` zurück (im Core durch `tool_runtime.py`/`operations_projects.py` kompensiert). | Kein Push-Blocker; in v0.6.x Default-Workspace-Root explizit aus Konfiguration ziehen. |
| **1c. `extension/background.js` Filter-Escaping & Exact-Match (`5f5c0bb8`)** | **PASS (0 Findings)** | `extension/background.js:8-15, 57, 76` | `\`, `"`, `%`, `_` sind für PocketBase `~` (`LIKE`) vollständig maskiert; Entfernung von `data.items[0]` verhindert Fuzzy-Overwrite fremder Datensätze. | Übernehmen, kein Nachbesserungsbedarf. |
| **1d. Geschärfte Tests (`5f5c0bb8`)** | **PASS (0 Findings)** | `tests/test_f34_resume_and_force_done_nonblocking.py:47-63`; `tests/test_v06_satellites_hardening.py:56-71` | Keine Theater-Gates mehr: `test_f34` misst kontinuierlich `max_lag[0] < 0.12` über die gesamte Laufzeit von `update_task_status_impl`; `test_v06_satellites_hardening` erzwingt `os.replace`-Fehler und prüft Platten-Unveränderlichkeit + RAM-Persistenz. | Übernehmen, kein Nachbesserungsbedarf. |
| **2a. RT1 PoC 2A (`poc2a_parallel_and_drain.py`)** | **PASS (0 Findings)** | `Temp\opencode\v06-rt1-fixed\poc2a_parallel_and_drain.py` → **`POC2A_EXIT=0` (`VERDICT: CLEAN`)** | Korrigiertes Temp-SQL-Schema (`(run_id, workflow_id, status, created_at, updated_at)`): `tracked_before=3`, `drained=3`, `statuses=['failed', 'failed', 'failed']`, `tracked_after=0`. | Bestätigt sauber. |
| **2b. RT1 PoC 2B (`poc2b_silent_persist_failure.py`)** | **PASS (0 Findings)** | `Temp\opencode\v06-rt1-fixed\poc2b_silent_persist_failure.py` → **`POC2B_EXIT=1` (`VERDICT: NOT_REPRODUCED`)** | `_mark_failed_sync` loggt `ERROR` inkl. Traceback (`Failed-Status fuer Run 'run-rt1-silent' konnte nicht persistiert werden: database is locked`); `drained=0`, `tracked set=0` — kein falscher Erfolgszähler, kein stilles Schlucken. | Bestätigt sauber. |
| **3a. D5 C4 (Boardroom-Orchestrierung)** | **GO (optional)** | `core_dispatcher.py:2600-3291` | Extrahierbar mit G7-Migration der 3 Source-Text-S-Tests + Characterization zuerst; kein v0.6-Blocker. | Als optionales v0.6.x-Item belassen. |
| **3b. D5 C5 (Dispatch-Core) & D4 (Telegram)** | **GO (bewusst offen)** | `backend/workflow_dag_runner.py:1214`; `tests/test_fix_w3_b_performance.py:445`; `scripts/patches/hermes_telegram_adapter.py` | Per Owner-Entscheidung bewusst offen / außerhalb Ownership. | Unverändert akzeptiert. |
| **3c. `.mcp.json` & `tools/migrate_projects_structure.py`** | **GO (v0.6.x Backlog)** | `.mcp.json:10-23,31-35`; `tools/migrate_projects_structure.py:58` | Keine hartcodierten Secrets in `.mcp.json`; `migrate_projects_structure.py` ist ein manuelles CLI-Skript außerhalb des Runtime-Hot-Paths. | In v0.6.x-Backlog belassen (MCP-Pinning / Dry-Run-Flag). |
| **3d. Audit-Kette, `otel_sdk=false`, flaky `:808`, `main.py`-Ratchet** | **GO (akzeptiert)** | `data/backups/pre_hmac_archive_2026-11-26/ARCHIVE_MANIFEST.txt` (Read-Only); `main.py` (1856 Z.) | Startup-Blocker behoben (Produktiv-`ARCHON-OS` läuft `healthy`, HTTP 200, frische HMAC-Ketten); historischer Kettenbruch bewusst archiviert, nicht re-signiert, Betreiberentscheidung dokumentiert; übrige Punkte dokumentiert akzeptiert. | Kein Handlungsbedarf vor Push. |
| **4a. `StarletteDeprecationWarning` (`test_loop_liveness.py`)** | **PASS (harmlos)** | `tests/test_loop_liveness.py:138` (`client.get("/livez", timeout=15)`) | Reines Test-Artefakt durch `timeout`-Argument am Starlette-`TestClient`; kein Produktivcode betroffen. | Kein Push-Blocker; bei Gelegenheit im Test entfernen. |
| **4b. `RuntimeWarning: coroutine 'run_boardroom_debate' was never awaited`** | **LOW (echter Fallback-Pfad)** | `scripts/trigger_boardroom_debate.py:138-147` | Bei Aufruf von `run_debate()` aus einem bereits laufenden Event-Loop (z. B. `test_m48_mcp_gateway.py`) und fehlgeschlagenem HTTP-Call erzeugt `:138` das Coroutine-Objekt, `asyncio.run(...)` wirft `RuntimeError`, `:146` fängt ihn ab, das Coroutine-Objekt wird nie geschlossen → `RuntimeWarning`. Kein Security-/Stabilitäts-Blocker. | Kein Push-Blocker; v0.6.x-Fix: Coroutine vor `asyncio.run` erst prüfen oder im `except` schließen (`coro.close()`). |
| **5. `db_paths`-Split-Brain-Warnungen** | **MED (DELEGATED, bekannt)** | `backend/db_paths.py:89-104, 157-170` | `db_candidates()` hängt `os.path.expanduser("~/.hermes/{filename}")` (`:96`) auch bei `ARCHON_TEST_DB_ISOLATION=1` an. Bei leerer Temp-DB (0 Tabellen) beim App-Import (`ab_check_wt.py` / Startup) greift `:160-169` auf `~/.hermes/agentic_memory.db` / `state.db` zurück (read-only Tabellenprüfung + ggf. Laden). Tests mit explizitem `db_path=tmp_path/...` sind nicht betroffen. | Per `ANWEISUNG §4` / `HANDOVER §4 #8` als `DELEGATED` dokumentiert — kein neuer Blocker. Minimaler v0.6.x-Fix: in `db_candidates()` unter `ARCHON_TEST_DB_ISOLATION=1` den `~/.hermes`-Fallback weglassen. |

---

## 2. Zusammenfassung & Push-Empfehlung

- **Kein BLOCKER, kein HIGH, keine neue Regression** in Commit `5f5c0bb8` oder den abgeschlossenen RT1-PoCs (`poc2a` `CLEAN`, `poc2b` `NOT_REPRODUCED`).
- Alle 4 Verbesserungen aus `5f5c0bb8` halten der unabhängigen Prüfung stand; die beiden geschärften Tests sind echte Verhaltensprüfungen ohne Theater-Gate-Schwäche.
- Die beiden Gate-Warnungen und die `db_paths`-Split-Brain-Meldung sind vollständig aufgeklärt (`StarletteDeprecationWarning` harmlos, `trigger_boardroom_debate.py:138` LOW-CLI-Fallback, `db_paths.py:96` bekannter `DELEGATED`-Fallback).

**Push-Empfehlung: GO.**

Der Stand `fullscan-d5 @ b51b6359` (69 Commits seit `ee18373a`, 13/13 Gates EXIT=0, `pytest 2538/20/0`, `mypy 439/0`, `A/B=0`, `ARCHON-OS` `healthy`) ist bereit für Merge/Push nach deiner ausdrücklichen Freigabe. **Kein Push und kein Commit wurden in diesem Lauf ausgeführt.**

# Abschlussbericht — Behebung der 21 vorbestehenden Baseline-Testfehler

> **Datum:** 27.11.2026 · **Basis:** `main` (`bcbfbf78`) · **Produktivcode geändert:** Nein (0 Zeilen)  
> **Hinweis für Koordinator:** Diese Datei fällt unter `.gitignore` (`**/*report*`) und muss zentral mit `git add -f audit_reports/baseline_21_report.md` committet werden.

---

## 1. Zusammenfassung

Alle **21 dokumentierten vorbestehenden Testfehler** wurden bereinigt, ohne Produktiv-Guards abzuschwächen und ohne Änderungen am Produktivcode vorzunehmen:

- **16/21 Fehler** hatten eine gemeinsame Ursache: veraltete Test-Patches auf `main.require_admin` / `main.require_admin_or_503` bzw. fehlende Session-Kontexte, während die Router fail-closed gegen `archon.routers._rbac`, `archon.routers.auth`, `backend.rbac_guards` und die `auth_gate`-Middleware prüfen. Gelöst über die neue **explizite** (nicht-`autouse`) Fixture `admin_rbac_bypass` in `tests/conftest.py`.
- **5/21 Fehler** waren Einzelvertrags-Abweichungen in 5 Testdateien (Lease-Claim-Fail-Closed, entferntes `ops.get_provider`, Strict-Audit-Vertrag, Trajectory-Suffix am Loop-Flag, W3-Trace-Fallback).

---

## 2. Übersicht aller 21 behobenen Testfälle

| # | Test | Ursache | Fix | Status |
|---|---|---|---|---|
| 1 | `tests/test_orange_a_main.py::test_save_full_html_schreibt_atomar_und_meldet_fehler` | Patch auf `app_main.require_admin` wirkungslos; `archon/routers/ui.py` ruft `_rbac.require_admin_or_503` (401). | Explizite Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 2 | `tests/test_orange_a_main.py::test_save_full_html_meldet_schreibfehler` | Identisch (401 statt 500). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 3 | `tests/test_orange_a_main.py::test_save_full_html_lehnt_zu_kurzes_html_ab` | Identisch (401 statt 400). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 4 | `tests/test_orange_a_main.py::test_gateway_start_setzt_zustand_nur_bei_erfolg` | Patch auf `app_main.require_admin` wirkungslos; `archon/routers/gateway.py` ruft `_rbac.require_admin_or_503` (403 statt 502). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 5 | `tests/test_orange_a_main.py::test_gateway_start_setzt_zustand_bei_erfolg` | Identisch (403 statt 200/Erfolg). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 6 | `tests/test_orange_a_main.py::test_gateway_stop_meldet_fehler_und_aendert_den_zustand_nicht` | Identisch (403 statt 502). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 7 | `tests/test_orange_a_security.py::test_diff_preview_lehnt_pfade_ausserhalb_des_repos_ab` | Patch auf `app_main.require_admin_or_503` wirkungslos; `archon/routers/mesh.py` importiert `_rbac.require_admin_or_503` direkt (401 statt 403). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 8 | `tests/test_orange_a_security.py::test_diff_preview_lehnt_systempfade_ab` | Identisch (401 statt 403). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 9 | `tests/test_orange_a_security.py::test_diff_preview_erlaubt_repo_dateien` | Identisch (401 statt Diff-Ergebnis). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 10 | `tests/test_orange_a_security.py::test_diff_preview_verlangt_einen_pfad` | Identisch (401 statt 400). | Fixture `admin_rbac_bypass` genutzt, toten Patch entfernt. | PASSED |
| 11 | `tests/test_orange_b_r16.py::test_reviewer_exception_verdict_changes_requested` | `ops.trigger_quality_review` ruft `backend.rbac_guards.require_session_actor(None)` -> 401/503. | Fixture `admin_rbac_bypass` genutzt, redundanten `ops.require_admin_or_503`-Mock entfernt. | PASSED |
| 12 | `tests/test_orange_b_r16.py::test_reviewer_prose_answer_no_json_fail_closed` | Identisch (503 statt `changes_requested`). | Fixture `admin_rbac_bypass` genutzt, redundanten Mock entfernt. | PASSED |
| 13 | `tests/test_orange_b_r16.py::test_body_force_verdict_cannot_approve_and_four_eyes_override_still_works` | Identisch in Schritt 1 (`trigger_quality_review` -> 503). | Fixture `admin_rbac_bypass` genutzt; expliziter `supervisor-b`-Mock in Schritt 2 für Vier-Augen-Prüfung erhalten. | PASSED |
| 14 | `tests/test_p0_api_validation_batch2.py::test_system_language_endpoint_rejects_wrong_type_with_422` | Router-Dependency `Depends(forbid_viewer_writes)` blockte unauthentifizierten POST mit 403 vor 422. | Fixture `admin_rbac_bypass` hinzugefügt. | PASSED |
| 15 | `tests/test_p0_api_validation_security.py::test_mask_secrets_endpoint_returns_422_for_non_string_text` | Router-Dependency `Depends(forbid_viewer_writes)` auf `security.router` blockte POST mit 403 statt 422. | Fixture `admin_rbac_bypass` hinzugefügt. | PASSED |
| 16 | `tests/test_p1_trace_propagation.py::test_operations_dag_tracing_status_endpoint` | `auth_gate`-Middleware auf `app_main.app` blockte `GET /api/operations/traces/otel/status` ohne Session mit 401 statt 200. | Fixture `admin_rbac_bypass` hinzugefügt. | PASSED |
| 17 | `tests/test_fix_batch9.py::test_m14_execute_kanban_task_registers_with_shutdown_coordinator` | Fail-Closed-Lease-Claim (`deadlock_supervisor.acquire_lease`/`heartbeat`) und SOUL-Pin-Prüfung (`build_dispatch_soul_context`) stoppten den Worker vor der Shutdown-Registrierung. | `deadlock_supervisor.acquire_lease`, `heartbeat`, `release_lease` und `build_dispatch_soul_context` im Test gemockt. | PASSED |
| 18 | `tests/test_fix_w2_c_governance_roles.py::test_status_force_done_with_proof_writes_actor_and_evidence` | Veraltetes Patch-Target `ops.get_provider` (nicht mehr in `backend.operations_api` exportiert). | Veraltetes `monkeypatch.setattr(ops, "get_provider", ...)` entfernt. | PASSED |
| 19 | `tests/test_med2_b_trace.py::test_fleet_self_healing_audit_failure_is_visible` | `backend/fleet_self_healing.py:271-274` wirft unter Default `ARCHON_AUDIT_STRICT=1` bei Audit-Fehler hart `RuntimeError("audit_write_failed")`. | Test an den harten Fail-Closed-Vertrag angepasst (`pytest.raises(RuntimeError)` + Zähler/Log-Prüfung) sowie expliziten Opt-out-Pfad (`ARCHON_AUDIT_STRICT=0`) zusätzlich abgedeckt. | PASSED |
| 20 | `tests/test_milestones_77_79_81_83_86.py::test_m83_flightlog_and_policy_backtester` | Loop-Flag trägt seit Trajectory-Korrelation das Suffix `@traj-...` (`tool_loop:terminal@traj-...`); Test prüfte exakte Gleichheit. | Assertion auf Prefix-Prüfung `any(f.startswith("tool_loop:terminal") for f in diag["flags"])` umgestellt. | PASSED |
| 21 | `tests/test_w3_d_trajectory.py::test_trajectory_root_scope_is_stable_per_session` | `current_trajectory_root()` fällt seit W3 auf `trace:<id>` zurück, wenn im Prozess bereits ein W3C-Trace aktiv ist; Test erwartete hart `""`. | Erwarteten Rückgabewert nach Scope-Ende deterministisch gegen `current_trace_id()` geprüft (`f"trace:{tid}" if tid else ""`), ohne globalen Kontext zu mutieren. | PASSED |

---

## 3. Begründung der semantischen Entscheidung: Strict-Audit (`test_med2_b_trace.py`)

**Entscheidung:** Der Produktivcode (`backend/fleet_self_healing.py:271-274`) bleibt unverändert **fail-closed**; der Test `test_fleet_self_healing_audit_failure_is_visible` wurde an den harten Vertrag angepasst.

**Begründung:**
1. **Soll-Spezifikation (`audit_reports/00_SOLL_SPEC.md` §0 & §2.5):** Verlangt verbindlich „Audit-Schreibfehler nie verschluckt" und „Audit-Schreibfehler blockieren Tool-Calls (nie verschluckt)".
2. **Audit-Historie (Befund D05-M1, behoben in `eb308bb5`):** Vor D05-M1 loggte `fleet_self_healing.py` einen Audit-Fehler nur und gab dennoch `status: "success"` zurück. Das harte `raise RuntimeError("audit_write_failed")` bei aktivem `_audit_strict()` (Default `ARCHON_AUDIT_STRICT=1`) ist exakt der gewollte GoBD-/Fail-Closed-Fix.
3. **Caller-Integration (`backend/fleet_self_healing.py:337, 382-383`):** `check_fleet_and_heal()` fängt die `RuntimeError` sauber ab und liefert `{"status": "error", "error": "audit_write_failed", "healed_count": 0}`, statt eine ungeprüfte Selbstheilung ohne revisionssicheren Audit-Nachweis als Erfolg zu quittieren.
4. **Systemweite Konsistenz:** Entspricht `backend/audit_log.py::_require_audit_event()`, `core_dispatcher._audit_log_async()` und dem Schwestertest `test_verify_rejects_placeholder_version_via_audit_strict` in derselben Datei.
5. **Testabdeckung nach Fix:** Der Test prüft jetzt beide Verträge explizit:
   - Default (`ARCHON_AUDIT_STRICT` ungesetzt -> `1`): `pytest.raises(RuntimeError, match="audit_write_failed")` + Inkrement von `get_audit_error_counts()` + `ERROR`-Log.
   - Explizites Opt-out (`ARCHON_AUDIT_STRICT=0`): sichtbares Fehlerresultat (`audit_write_failed=True`, `audit_status="error"`).

---

## 4. Architektur der Auth-Harness (`tests/conftest.py`)

Die neue Fixture `admin_rbac_bypass(monkeypatch)` ist **explizit** (kein `autouse=True`), sodass alle echten Auth-/RBAC-Tests (z. B. `test_healing_attempt_verlangt_admin`) ihre fail-closed Semantik unverändert behalten. Sie patched über `monkeypatch` (mit automatischem Teardown):
- `archon.routers._rbac` (`_checker`, `require_admin_or_503`, `forbid_viewer_writes`, `require_session_actor`)
- `archon.routers.auth` (`get_current_user_from_request` -> Admin-Dict, `require_admin`)
- `backend.rbac_guards` (`_GUARDS`-Registry und alle 4 Wrapper-Funktionen)
- `backend.auth_service.auth_service.is_auth_enabled` (`-> False`) für `TestClient(app_main.app)`
- `main`-Referenzen und `main.app.dependency_overrides` (falls `main` geladen ist)

---

## 5. Verifikation

- **Ruff** (`-m ruff check --select E,F,I --ignore E501 --output-format=concise <12 geänderte .py>`): **Exit 0** (`All checks passed!`)
- **MyPy** (`-m mypy --config-file mypy.ini <12 geänderte .py>`): **Exit 0** (`Success: no issues found in 12 source files`; 43 vorbestehende Legacy-Test-Typbefunde in den berührten Testdateien mit gezielten `# type: ignore[...]` annotiert)
- **Pytest Full-Suite** (`$env:ARCHON_TEST_DB_ISOLATION='1'; .venv\Scripts\python.exe -m pytest tests/ -q`):
  - **2961 passed, 16 skipped, 0 failed** (Baseline: 21 failed / 2940 passed / 16 skipped -> alle 21 vorbestehenden Fehler behoben).
  - **1 vorbestehender Windows-Teardown-Error** in der nicht berührten Datei `tests/test_m49_eu_ai_act_compliance.py::TestM49EUAIActCompliance::test_05_governance_router_m49_endpoints` (`PermissionError: [WinError 32]` beim `TemporaryDirectory.cleanup()` von `erp.db`; dokumentierter vorbestehender Flake laut `HANDOFF_W4_W7.md §3`).

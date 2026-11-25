# Fix-Report W1-A — Audit-Trail & Kryptografie (F010 / F013 / D05-MED)

**Datum:** 25.11.2026 · **Scope:** exklusives Datei-Ownership laut Auftrag · **Basis:** `audit_reports/domain_05.md`, `MASTER_PLAN.md` §4/§5

---

## 1. Was geändert wurde

### BLOCKER B-05 — Fail-Fast + `AUDIT_COMPROMISED` (`main.py`)
- Neuer thread-sicherer Global-State `_AUDIT_COMPROMISED` + `_mark_audit_compromised(label, result)`.
- Neuer Hook `_assert_audit_integrity()` ruft `_verify_all_audit_chains()` (Zentralkette + sechs Nebenketten inkl. Receipt-Kette); bei `valid=False` → `RuntimeError` (Lifespan re-raist). In `_FAIL_FAST_HOOKS` registriert und in `_STARTUP_HOOKS` eingehängt.
- `/readyz` liefert 503 mit `audit_compromised: <reason>` (auch `/health`, da es `/readyz` consume).
- 30-s-Loop nutzt jetzt denselben Verifizierer; `valid=False` → ERROR-Log + Flag. Ebenso werden `violation: True` (Head-Anker-Tail-Löschung) markiert.
- **Produktions-Gate:** `_audit_integrity_enforced()` (ENVIRONMENT production/prod/live **oder** erzwungene Auth **oder** explizites `ARCHON_AUDIT_INTEGRITY_FAIL_FAST=1`). §2.5 verlangt „Produktion startet nicht"; isolierte Dev/Test-Installationen mit historischen Legacy-Blöcken bleiben startbar. Das ERROR-Log erscheint **immer**, das 503-Flag nur im Produktivpfad — sonst würde jede langlebige Test-Session nach 15 s permanent 503 liefern (verifiziert).

### H-05-1 — Anker-Signatur epoch-fähig (`backend/audit_log.py`, `.env.example`, Compose, Key-Skript)
- Neu: `_anchor_key_epochs()`, `_anchor_key_for_epoch()`, `_anchor_known_keys()`, `_anchor_signing_key()`.
- `_write_anchor()` schreibt Format **v3** mit 5. Spalte `epoch_from` und signiert mit dem Key der passenden Epoche (analog `_key_for_block`). Verify akzeptiert v3 (exakter Epochen-Key, Fallback auf bekannte Keys falls Marker nach Config-Änderung nicht mehr existiert), v2 (alle bekannten Anker-/Audit-Keys) und v1 (Legacy, nur mit Opt-out).
- Dedizierter `ARCHON_AUDIT_ANCHOR_KEY` (+ `ARCHON_AUDIT_ANCHOR_EPOCHS` / `_EPOCH_FROM`) ist now dokumentiert und wird erzeugt; Rotationstests grün.

### H-05-2 — Externe Verankerung als Produktions-Default
- Compose: `ARCHON_AUDIT_ANCHOR_PATH` defaultet auf `/app/audit_anchor/audit_anchor.log` auf **getrenntem Volume** (`${ARCHON_AUDIT_ANCHOR_DIR:-./audit_anchor}:/app/audit_anchor`), nicht mehr unter `./data`. Neue Keys/Epochen/Strict werden durchgereicht.
- `.env.example`: separates Volume, 0600 (Windows: DACL via Installer), WORM-Empfehlung, Fail-Closed-Dokumentation.
- `_write_anchor()` legt die Datei via `os.open(..., 0o600)` an und `chmod(0600)` (best effort).
- `verify_integrity()` + `_start_anchor_worker()` schlagen in Produktion fehl/ERROR, wenn kein externes Ziel konfiguriert ist (Opt-out nur `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1`, in Produktion wirkungslos).

### H-05-3 — Auth-Events in der HMAC-Kette (`archon/routers/auth.py`, `backend/auth_service.py`)
- Neuer zentraler Helper `_audit_auth_event()` (Router) bzw. `_audit_auth_event()` (Service): `category="auth"`, `action` ∈ `login_success | login_failed | logout | user_created | role_changed | user_updated | password_changed | user_deleted`, `agent_id=<username>`.
- Payload: `client_ip_hash`, `user_agent_hash` (HMAC-SHA256 des Audit-Keys, 32 Hex-Zeichen), `user_id`, `role`, `reason`. **Keine** Klartext-Passwörter/Tokens/IPs; zusätzliche Sensitivitäts-Filter im Router-Helper.
- `auth_service._record_failed_login()` schreibt jetzt dauerhaft signierte `login_failed`-Events (zuvor nur prozesslokal, bei Neustart verloren); zusätzlich `account_locked` / `account_inactive`.
- Bei `ARCHON_AUDIT_STRICT=1` (Default) wird ein Audit-Schreibfehler hart abgebrochen (Router: HTTP 503 `audit_write_failed`; Service: `RuntimeError`).

### H-05-4 — `_record_failed_cancel` (`core_dispatcher.py`, nur Zeilen 50–64)
- `agent_id="system"` ergänzt (vorher garantiert `TypeError`, toter Pfad), Fehler auf `logger.error`, Result-Feld `audit_status` (`ok`/`error`) + `audit_event_id`. `_FAILED_CANCELS` wird weiterhin von `/readyz` gespiegelt.

### MED aus D05
- **Receipt-Key:** `ARCHON_RECEIPT_HMAC_KEY` in `.env.example`, Compose und `scripts/ensure_audit_hmac_key.py` (drei getrennte Secrets, idempotent, 0600). Legacy-Fallback meldet `hmac_protected=False`, `domain_separated=False`, `key_source="legacy_audit_key"`; in Produktion + Strict zusätzlich `chain_valid=False`. Migrationspfad `ARCHON_RECEIPT_HMAC_EPOCHS` dokumentiert.
- **Approval-Trigger:** `BEFORE UPDATE ON approval_policy_audit_chain` ohne `OF`-Klausel (alle Spalten), inkl. `DROP TRIGGER` für Bestands-DBs; `signature_valid` ist damit ebenfalls unveränderbar, ohne dass historische Hashes brechen.
- **OTel-Korrelation:** `verify_integrity()` prüft `trace_id` / `session_id` / `correlation_id` gegen den signierten Payload → `valid=False` bei Manipulation.
- **Audit-Fehler nicht verschluckt:** `backend/agent_rbac_jail.py`, `local_security_guard.py`, `backend/passkey_hitl.py`, `backend/compliance_engine.py` → ERROR + bei Strict Fail-Closed. Zentraler Helper `_require_audit_event()` in `backend/audit_log.py` (wirft `RuntimeError("audit_write_failed")`).
- **PDF/Prüfer:** `compliance_pdf.py` zeigt `reason` + `corrupted_id` statt „Prüfung erforderlich"; Label korrigiert auf „GoBD HMAC-SHA256 Hashkette (M21)". `compliance_engine._safe_verify_audit_chain()` übernimmt `reason`/`error`/`corrupted_id`.
- **`governance.py`:** unverändert — der Audit-Fehler-Pfad des PDF-Exports (HTTP 503 + Header) war bereits korrekt (Positivbefund D05).

### Zusätzlich behoben (Root Cause mehrerer roter Baseline-Tests)
- `finalize_secondary_chain_verification()` las Head-Anker aus der **globalen** Zentral-DB, auch wenn die Nebenkette in einer isolierten Test-DB lag → falscher „Tail-Loeschung"-Alarm (z. B. 999 Anker vs. 1 Block). Anker sind jetzt über `db_path` scoped (`get_chain_anchors`/`record_chain_anchor`/`anchor_secondary_chains`), inkl. Rückwärtskompatibilität zu Legacy-Ankern und 2-Argument-Monkeypatches.

---

## 2. Verifikation

**Shell:** `.ci_venv\Scripts\python.exe` war über weite Strecken verfügbar; zeitweise `pwsh.exe: Zugriff verweigert` (nach重试 erfolgreich). Alle unten genannten Commands wurden tatsächlich ausgeführt.

- `python -m compileall -q <alle obigen Dateien>` → **Exit 0**, keine Ausgabe.
- **Neue Tests** `tests/test_fix_w1_a_audit.py` (11 Tests): Anker-Rotation (Audit-Key + dedizierter Anker-Key), Korrelationsspalten-Tampering, Approval-All-Column-Trigger + Detection, `_require_audit_event`, DB-scoped Anker, Receipt-Legacy-Reporting, `agent_id` in `_record_failed_cancel`, Auth-Kontext-Hashing/Event-Payload, Fail-Fast-Hook → **11 passed**.
- **Baseline-Teilmenge (vom Parent gemeldet, vorher rot):** alle 14 relevanten Tests jetzt grün, u. a. `test_email_draft_audit.py` (4/4), `test_audit_fixes_batch.py::{receipt_ledger, approval_policy_*, llm_egress_guard_*, secret_masker_*}`, `test_phase1_security_and_p0_fixes.py::test_approval_policy_hmac_mixed_chain_and_fail_closed`, `test_sanierungsplan_fixes.py::test_execution_receipt_ledger_detects_payload_tampering`, `test_core_a3_orchestration_limits.py::test_email_draft_engine_defines_workspace_dir_and_detects_hmac_downgrade`, `test_show_hn_blockers.py::test_core_dispatcher_omniroute_alias_and_ollama_fallback`.
- **Weitere gezielte Läufe:** `test_core_a1_crypto_audit.py`, `test_p0_audit_hmac_downgrade.py`, `test_p1_content_audit_hardening.py` (16), `test_reaudit_stage5.py`, `test_audit_b1_b8_blockers.py`, `test_critical_hardening.py` → alle grün.
- **Gesamtsuite (Finallauf):** `8 failed, 2171 passed, 16 skipped` (Baseline des Parents: `20 failed, 2120 passed, 16 skipped`). 12 weniger Failures, +11 eigene Tests, keine neuen Errors.

**NEVER_DO_LIST:** kein Replay, keine PostgreSQL-Migration — eingehalten. `backend/tool_runtime.py` wurde nicht angefasst (anderer Agent).

---

## 3. Offene Punkte / nicht verifiziert

1. `tests/test_fix_batch8.py::test_r30_audit_integrity_detects_payload_tampering` (**außerhalb meines Ownerships**) ist jetzt rot: der Test manipuliert `new_value` per direktem SQL-UPDATE, den der neue all-column-Trigger absichtlich blockt. Der äquivalente Nachweis (manipulierte Zeile nach bewusstem `DROP TRIGGER` wird erkannt) ist in `tests/test_fix_w1_a_audit.py` grün. Der Test muss vom Owner angepasst werden (Trigger vor der Manipulation droppen) — ich habe ihn nicht gelöscht oder geskippt.
2. `tests/test_workflow_dag_e2e.py` (6 Tests, Nodes `failed` statt `completed`) und `test_graceful_shutdown.py::test_database_wal_flush` (nur im Gesamtlauf, isoliert grün) liegen außerhalb meines Ownerships / sind Ordering-Flakes. Nicht durch meine Änderungen verursacht.
3. `ARCHON_RECEIPT_HMAC_KEY` und `ARCHON_AUDIT_ANCHOR_KEY` fehlen aktuell in `.env` (nicht in meinem Ownership). `python scripts/ensure_audit_hmac_key.py --check` meldet das korrekt als Fehler; der Betreiber muss das Skript einmalig ausführen, sonst bleibt Produktion fail-closed. Ebenso ist das externe Anker-Ziel im laufenden Workspace nicht umgestellt (nur Compose/`.env.example`).
4. Laufende Produktiv-DB `data/agentic_memory.db` enthält historische Plain-SHA-Blöcke (~2429) und manipulierte Receipt-Hashes (~140); der Fail-Fast greift dort korrekt, wurde aber nicht „geheilt" (kein Replay/Neusignieren — NEVER_DO_LIST).
5. Docker-Compose-Config, echte WORM-/NAS-Eigenschaften des Anker-Volumes, Windows-DACL und PDF-Rendering wurden nicht zur Laufzeit geprüft (kein Docker/kein Windows-ACL-Tool in dieser Session).
6. Shell war zeitweise verweigert (`pwsh.exe: Zugriff verweigert`); alle oben gelisteten Commands wurden jedoch erfolgreich ausgeführt.

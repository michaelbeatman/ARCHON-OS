# Fix-Log A6 — Security/Governance (Phase 3 Remediation)

> Agent: Fix-Agent A6 (Security/Governance) · Basis: HEAD `cee78206` ·
> Exklusiver Dateibereich gem. Auftrag · **kein Commit, kein Push** ·
> G-05 (lokaler Auth-Default) und B5 (leere HTTP-200 im Klassifikator) wurden
> **nicht** angefasst.

## 1. D04/HIGH — Schwellen-Invariante (A4-Handoff) ✅

Datei: `backend/approval_policy_engine.py`

- Neue Konstanten `FINANCE_THRESHOLD_MIN_GAP = 0.01` (eine Cent-Stufe als
  harter Mindestabstand) und `_GAP_EPSILON = 1e-9` (Float-Rundung,
  `500.0 - 499.99 == 0.009999999999990905`).
- Neue zentrale Prüfung `_parse_finance_threshold()` +
  `_assert_finance_threshold_invariant(cur, policy_key, candidate_value)`:
  liest bei Änderung einer Schwelle **immer die Gegen Schwelle** aus der DB
  und prüft `four_eyes_min - auto_max >= 0.01`. Bei fehlender oder nicht
  numerischer Schwelle → `ValueError` (fail-closed, kein stillen Fallback
  auf 500/50 mehr).
- `update_policy()`: Aufruf der Invariante **für beide Keys**
  (`finance_auto_approval_max` UND `finance_four_eyes_min`) — vorher wurde nur
  `auto_max` gegen `four_eyes_min` geprüft.
- `approve_policy_change_proposal()`: identische symmetrische Prüfung vor dem
  Schreiben des freigegebenen Vorschlags (vorher ebenfalls einseitig).
- `evaluate_and_enqueue()`: Auto-Freigabe jetzt nur noch bei
  `amount <= auto_max and not requires_four_eyes and domain == "finance"`.
  Ein Betrag, der die Vier-Augen-Schwelle erreicht, wird nie automatisch
  freigegeben — auch nicht bei veralteter/manipulierter Policy-Konfiguration.

Verifikation: `tests/test_med_d14.py`, `tests/test_med2_e_services.py`
(`test_d14_auto_approval_threshold_requires_four_eyes`),
`tests/test_fix_batch5.py`, `tests/test_med_d04_d06_d15.py`.

## 2. D04/MED — Egress-Fail-Open ✅

Datei: `backend/egress_firewall.py`

- `_egress_disable_opt_in()`: Deaktivierung nur noch bei explizitem
  `ARCHON_ALLOW_EGRESS_FIREWALL_DISABLE=true|1|yes|on`.
- `_audit_egress_disabled()`: signiertes Audit-Event (HMAC-Hashkette über
  `chained_audit_log.record_event`) mit `action="egress_firewall_disabled"`,
  `explicit_opt_in` und `bypassed=True`; Audit-Fehler werden über
  `_record_audit_error()` sichtbar gemacht und weichen den Deny nicht auf.
- `check_url()` bei `enabled=false`: **`allowed=False`, `blocked=True`,
  `bypassed=True`** (nie mehr `allowed=True`), zusätzlich
  `explicit_opt_in` im Result und ein `allowed=0`-Eintrag in
  `egress_firewall_logs`. Damit greift bereits der bestehende Block in
  `enforce_egress_firewall_for_url()` (`fw_res["allowed"] is False`) — auch
  bevor A2 das `bypassed`-Flag im Wrapper durchreicht.
- `local_security_guard.py` wurde **nicht** editiert (B5-Nachlauf nicht nötig;
  der dortige `bypassed`-Block ist jetzt über die Firewall-Antwort wirksam).

DELEGATED an A2: `backend/llm_egress_guard.py` — in
`enforce_egress_firewall_for_url()` das `bypassed`-Flag aus `fw_res` in die
Rückgabe übernehmen (Z.687) und `bypassed=True` als
`llm_dispatch_blocked_egress_bypassed` mit `ZeroEgressBlockedError` behandeln.

## 3. D04/MED — Vier-Augen-Dead-End (Teilfix) ✅ / DELEGATED

Datei: `archon/routers/decisions.py`

- Fail-Closed bei leerem/identischem Ersteller (Z.819-833) unverändert
  beibehalten — kein Sicherheitsabbau.
- `register_decision()` speichert zusätzlich `dec["extra"] = dict(extra)`.
  Der HITL-Followup `boardroom_no_consensus` liest damit nicht mehr `{}`,
  sondern die echten Konfliktbelege `consensus_verdict`, `veto_by`,
  `critique`, `synthesis`.
- Audit-Payload des Auflösungs-Events um `consensus_verdict`, `veto_by`,
  `critique`, `synthesis` und `evidence` ergänzt; der archivierte Decision-
  Eintrag trägt `critique` und `synthesis` ebenfalls mit.

DELEGATED an A5 (2 Dateien): `backend/workflow_scheduler.py:730` und
`backend/workflow_dag_runner.py:696` — `create_decision(..., created_by=...)`
aus verifizierter Session / dokumentiertem Service-Principal
(`workflow-scheduler-service`, `workflow-dag-service`).

## 4. D14/MED — Eskalationsbelege in `decisions.py` (A4-Delegation) ✅

Identisch mit Punkt 3: `dec["extra"] = dict(extra)` stellt die Kette
Produzent (`_escalate_boardroom_no_consensus`, `extra` mit Konfliktbelegen) →
Konsument (HITL-Followup) → Effekt (archivierte Decision + signiertes Audit)
wieder her. Vorher gingen die Belege durch `dec.update(extra)` verloren und
der Audit-Eintrag enthielt nur den Default-Verdict `NO_CONSENSUS`.

## 5. D04/MED — Art.50-Dialog: Token-Bindung ✅ / DELEGATED

Dateien: `backend/client_approval_portal.py`, `archon/routers/v2_capabilities.py`

- `_disclosure_signature(token, key, nonce="", session="")` rechnet jetzt
  `HMAC(key, token|nonce|session|ai_disclosure_v1)`. Bestehende Links ohne
  Nonce behalten das Legacy-Format (keine DB-Migration nötig).
- Neue Spalten `ai_disclosure_nonce`, `ai_disclosure_session`,
  `ai_disclosure_consumed` (idempotente `ALTER TABLE`-Migration).
- `create_share_link()` erzeugt eine Einmal-Nonce, bindet daraus das Token
  und gibt Nonce/Session zusätzlich zurück; optional `disclosure_session`
  aus verifiziertem Client-Kontext.
- `verify_share_access(..., issue_disclosure_challenge=True,
  disclosure_session=...)` dreht die Nonce und gibt eine frische,
  an Nonce+Session gebundene Challenge aus — genau der Wert, den der UI-
  Dialog nach expliziter Bestätigung zurücksenden muss.
- `submit_client_decision()` akzeptiert `ai_disclosure_nonce` /
  `ai_disclosure_session`, verlangt im neuen Flow zwingend
  `ai_disclosure_shown=True`, exakten Nonce-/Session-Abgleich und
  unverbrauchtes Token. Der Verbrauch ist atomar per CAS
  (`UPDATE ... WHERE ai_disclosure_consumed = 0`, `rowcount == 1`).
- Die Legacy-Break-Glass-Env `ARCHON_CLIENT_PORTAL_LEGACY_DISCLOSURE` wurde
  entfernt; ein bloßes `ai_disclosure_shown=True` genügt nie.
- Kompatibilitätspfad ohne Nonce-Parameter bleibt für bereits ausgestellte
  Links / bestehende Direktaufrufer erhalten; der **Produktiv-Endpoint**
  `POST /api/v2/portal/decisions` verlangt weiterhin (unabhängig davon)
  `ai_disclosure_shown=True` + Token → HTTP 403 bei Fehlen (Z.908-918).
- `ClientDecisionSubmitRequest` um `ai_disclosure_nonce` /
  `ai_disclosure_session` erweitert und an die Engine durchgereicht.

DELEGATED an A8: `frontend/` — nicht wegklickbarer Art.-50-Dialog, der die
Challenge aus `verify_share_access()` holt, den Hinweis anzeigt und Token +
Nonce + Session + `ai_disclosure_shown=true` an
`POST /api/v2/portal/decisions` sendet. Ohne UI bleibt der Flow serverseitig
hoch gesichert, aber für Endanwender nicht bedienbar (G-03-Konsument fehlt).

## Delegationen (Summe: 4)

| Ziel | Agent | Datei(en) | Thema |
|---|---|---|---|
| A2 | A2 | `backend/llm_egress_guard.py` | `bypassed`-Flag im Wrapper durchreichen |
| A5 | A5 | `backend/workflow_scheduler.py`, `backend/workflow_dag_runner.py` | `created_by` an `create_decision()` (2 Dateien = 2 Delegationen) |
| A8 | A8 | `frontend/` | Art.-50-UI-Dialog |

## Verifikation / Tests

- `python -m py_compile` auf allen 5 geänderten Dateien: **OK**.
- Gezielte Suite (`tests/test_med_d14.py`, `test_med_d04_d06_d15.py`,
  `test_med2_e_services.py`, `test_med2_d_routers.py`,
  `test_milestones_41_40_42_85_87.py`, `test_decision_followup_beleg.py`):
  69 Tests grün; 3 Fehlschläge, davon **1 eigener** (zu großer Mindestabstand
  1.00 EUR gegen den etablierten 499.99/500.00-Test) — behoben durch
  `FINANCE_THRESHOLD_MIN_GAP = 0.01` + Floating-Point-Toleranz.
  Die zwei verbleibenden Fehlschläge sind **vorbestehend / umgebungsbedingt**:
  `test_d07_tenant_db_consolidation_check_fail_closed` (Source-String-Check
  in `backend/tenant_db_registry.py`, nicht in diesem Auftragsbereich) und
  `test_gate_ohne_passkey_proof_bleibt_pending` (`No module named
  'cryptography'` in beiden Venvs — fehlende Dependency, kein Codefehler).
- Ruff/Mypy: `ruff.toml` ignoriert E501/F401/F841; geänderte Stellen
  verwenden keine neuen Import- oder Namenskonflikte. Mypy/Ruff-Lauf im
  Terminal war zeitweise durch `pwsh`-Spawn-Fehler (`Zugriff verweigert`)
  blockiert; Py_compile und die gezielte Pytest-Suite wurden erfolgreich
  ausgeführt.

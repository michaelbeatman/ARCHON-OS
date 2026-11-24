# Fix-Log — A2 (Audit/Krypto), Phase 3 Remediation

**Agent:** Fix-Agent A2 (Audit/Krypto)
**Basis:** HEAD `cee78206`, Branch `main`
**Datum:** 25.11.2026
**Scope:** nur die 9 freigegebenen Dateien. B1/B2/B4-Grundfix (anderer Agent) nicht angefasst, nur verifiziert. Nicht committet.

---

## 1. D05/HIGH — Platzhalter-Prüfung an `ARCHON_AUDIT_STRICT` (Default 1), nicht an `_is_production()`

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/HIGH (Platzhalter Fail-Open) | `backend/audit_log.py:1420-1429` (neu), `:767` | Neuer Helper `_is_audit_strict()`: `ARCHON_AUDIT_STRICT` defaultet auf `"1"`; nur explizites `0/false/no/off/none` schaltet ab. `record_llm_dispatch()` nutzt ihn statt `_is_production()` — `ENVIRONMENT=development` darf keinen `"unknown"`-Proof mehr signieren. | Statisch: kein `is_prod`-Zugriff mehr im Platzhalterpfad; `grep` bestätigt `_is_audit_strict()` an der RuntimeError-Kante. |
| D05/HIGH (Dispatch-Proof bricht ab) | `backend/audit_log.py:730-757` | Registry-Fallback liefert jetzt bei `canary_percentage=0` den echten Wert `"stable"` statt `""`; fehlt der Registry-Eintrag ganz, werden deterministische Nicht-Platzhalter `("v1-static", "stable")` gesetzt. Damit bleibt ein regulärer Dispatch unter `ARCHON_AUDIT_STRICT=1` lauffähig, während ein **vom Aufrufer explizit übergebener** Platzhalter weiterhin fail-closed `RuntimeError` erzeugt. | Statisch: alle Wege vor `_is_placeholder_version()` mit Default belegt; Existenz des expliziten Platzhalter-Checks erhalten. |

## 2. D05/HIGH — `verify_integrity()`: Platzhalter immer `valid=False`

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/HIGH (GoBD-Nachweis wirkungslos) | `backend/audit_log.py:998-1018`, `:855-860` | Bedingung `if not req_value or is_prod:` → `if not req_value or placeholder:`. Ein Platzhalter in `prompt_version`/`canary_version` liefert jetzt unabhängig von `ENVIRONMENT` `valid=False` + `corrupted_id` + `reason`. Das lokale `is_prod` aus `verify_integrity()` wurde entfernt (sonst ungenutzte Variable). `unverified_version_blocks` kann nicht mehr mit `valid=True` auftreten, da der Return vor dem Erfolgspfad erfolgt. `legacy_max`-Ausnahme für Alt-Blöcke bleibt erhalten (Hashketten-Reihenfolge unverändert). | Statisch: kein `is_prod` mehr in `verify_integrity()`; Platzhalter-Return vor `return {"valid": True, ...}`. |

## 3. D05/HIGH — Trigger- und Anker-Strukturprüfungen unbedingt

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/HIGH (Strukturprüfungen fail-open in Dev) | `backend/audit_log.py:1099,1115,1137-1155`, `:1431-1449` | `if is_prod and not triggers_intact` → `if not triggers_intact and not _allow_insecure_audit_dev()`; `if is_prod and anchor_ok is not True` → `if anchor_ok is not True and not ...`. Zusätzlich: 4-Spalten-Anker ohne Anker-Key und unsignierte 2-Spalten-Legacy-Anker bei aktivem HMAC-Key werden jetzt ebenfalls `anchor_ok=False` (statt nur in Produktion). Einziger Ausweg: explizites, laut geloggtes `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1` — in Produktion wirkungslos. | Statisch: keine `is_prod`-Kopplung der Strukturprüfungen mehr; Opt-out ist env-explizit und loggt WARNING/ERROR. |

## 4. D05/MED — Spalten-/Payload-Konsistenz für jeden Block mit Dispatch-Spalten

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/MED (Spaltenmanipulation in Fremdkategorien unentdeckt) | `backend/audit_log.py:974-1061` | `parsed_payload` wird jetzt pro Block vorbereitet. Die 5-Spalten-Prüfung (`provider`, `model`, `target_host`, `target_endpoint`, `egress_zone`) wurde aus dem `category == "llm_dispatch"`-Zweig herausgelöst und läuft für **jeden** Block mit mindestens einer befüllten Dispatch-Spalte — inklusive `rbac`, `webhook`, `api_keys`, `chain_anchor`. Bei Abweichung: `valid=False`, `corrupted_id`, `reason` mit Spaltenname. LLM-Dispatch-Pflichtfeld- und Zonenprüfungen bleiben unverändert im Originalzweig. | Statisch: Prüfung liegt außerhalb der Kategorie-Bedingung, aber vor `chain_hashes.append()`; Hashketten-Reihenfolge und -Inhalt unverändert. |

## 5. D05/MED — Verify-Endpoints: nicht-2xx + reason/corrupted_id an der Wurzel

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/MED (`POST /governance/audit-log/verify` meldet success bei `valid=false`) | `archon/routers/operations_org.py:907-933` | `status` aus `result["valid"]` abgeleitet; `reason`/`corrupted_id` auf Antwortwurzel kopiert; bei `valid != True` `JSONResponse(409, headers={"X-Archon-Audit-Status": "error"})` statt HTTP 200. `JSONResponse` importiert. | Statisch: `valid = result.get("valid") is True`, Returnpfad 409 vor Success-Return. |
| D05/MED (`GET /api/audit/verify` ohne Statuscode) | `archon/routers/resilience.py:90-108` | Analoge Statuskopplung: `valid`/`status` an der Wurzel, `reason`/`corrupted_id` bleiben im Roh-Result erhalten, 409 + Header bei `valid=false`. `JSONResponse` importiert. | Statisch: Cookie/RBAC-Zaun (`_require_admin`) unverändert; nur Response-Aufbau geändert. |

## 6. D05/MED — GoBD-PDF-Export verschluckt Audit-Fehler

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/MED (Compliance-PDF ohne Revisionsnachweis) | `archon/routers/governance.py:206-253` | `logger.warning` → `logger.error`; `audit_status`/`audit_error` im Response-Header `X-Archon-Audit-Status` / `X-Archon-Audit-Error`. Bei `ARCHON_AUDIT_STRICT=1` (Default) wird der Export mit HTTP 503 und `reason: audit_write_failed` verweigert. Bei explizitem Opt-out bleibt der PDF-Download mit sichtbarem Error-Header erhalten. | Statisch: `os`/`HTTPException`/`logger` bereits importiert; kein „success"-Payload mehr ohne Audit-Eintrag. |

## 7. D05/MED — `api_key_manager.py` verwirft `_emit_global_audit()`-Ergebnis

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| D05/MED (API-Key-Erfolg ohne Zentralkette) | `backend/api_key_manager.py:22-44`, `:368`, `:436`, `:451` | Neue `AuditWriteFailedError(RuntimeError)` mit `status_code = 503` und Meldung `audit_write_failed: <operation>`. Helper `_raise_if_audit_failed()` wertet das Ergebnis von `_emit_global_audit()` aus. `create_key()`, `revoke_key()`, `delete_key()` eskalieren bei `audit_status == "error"` statt `raw_token` bzw. `True` zu melden. Erfolgspfad unverändert (`audit_status: "ok"` bleibt im `create_key`-Result). | Statisch: alle drei Aufrufstellen ausgewertet; `Dict`/`Any` sind vor dem Helper importiert. |

## 8. B4-Nachlauf — alle 8 geblockten Proof-Pfade nutzen echte Werte

| Befund-ID | Datei:Zeile | Änderung | Verifikation |
|---|---|---|---|
| B4-Nachlauf (8 direkte `record_llm_dispatch()`-Aufrufe ohne Versionsparameter) | `backend/llm_egress_guard.py:111-159` (Helper), `:231`, `:253`, `:290`, `:309`, `:531`, `:579`, `:629`, `:653` | Alle acht Pfade (`blocked_local_offline`, `blocked_egress_zone`, 2× `blocked_egress_policy`, `blocked_empty_url`, `blocked_metadata_ip`, `blocked_dns_not_local`, `blocked_egress_firewall`) auf `_record_blocked_proof()` umgestellt → `prompt_version`/`canary_version` aus dem bereits behobenen `_proof_prompt_versions()` (`v1-static`/`stable`). Helper bekam optionalen `data_category`-Parameter (Pfad 1–4 behalten ihre Kategorie), Normalisierung von Marker-Endpunkten auf eine gültige Egress-Zone (sonst `UNKNOWN` → `verify_integrity()` rot) und ersetzte `provider/model="unknown"`-Fallbacks durch `egress-firewall`/`egress-proof`. Zusätzlich `log_completed_llm_dispatch()` (`:365-366`) ohne `"unknown"`-Fallback. | Statisch: `grep` findet nur noch die 3 vorbestehenden Helper-Aufrufe + 8 konvertierte = 11 Aufrufe; kein `record_llm_dispatch()` direkt in den Blockpfaden mehr; kein `"unknown"`-Literal außerhalb eines Kommentars. |

## 9. Keine Änderung nötig (Scope geprüft)

- `backend/execution_receipt_ledger.py`: kein offener D05-HIGH/MED-Fund im zugewiesenen Auftrag; Nachweis-Hash fail-closed (bereits positiv verifiziert).
- `backend/session_receipts.py`: keine einschlägigen Platzhalter-/Verify-/Audit-Pfade.
- `backend/prompt_registry.py`: B4-Grundfix (`_effective_ref`, `version`/`version_num`) bereits vorhanden, nicht verändert.

---

## Verifikation — Durchführung / Limitierung

- **Statische Prüfung:** vollständige Lektüre aller geänderten Abschnitte; `grep`-Kontrollen für `is_prod`, `ARCHON_AUDIT_STRICT`, `record_llm_dispatch`, `_record_blocked_proof`, `unknown`, Statuscodes und Header. Alle neuen Namen (`Dict`, `Any`, `HTTPException`, `JSONResponse`, `logger`, `os`) sind in den jeweiligen Dateien bereits importiert.
- **Hashketten-Reihenfolge:** unverändert — `chain_hashes.append()` / `expected_prev = ...` blieben an derselben Stelle; nur Prüfungen wurden ergänzt/verschoben.
- **`pytest` / `ruff` / `mypy`: NICHT AUSFÜHRBAR.** Der Shell-Wrapper des Agenten konnte `pwsh.exe` trotz mehrfacher Versuche nicht starten (`failed to spawn C:\Users\micha\AppData\Local\Microsoft\WindowsApps\pwsh.exe: Zugriff verweigert (os error 5)`). Ein vorhandenes `.venv\Scripts\python.exe` wurde gefunden, konnte aber wegen desselben Spawn-Fehlers nicht aufgerufen werden. Bitte im Haupt-Session-Kontext nachholen:
  `ARCHON_TEST_DB_ISOLATION=1 .venv\Scripts\python.exe -m pytest tests/test_reaudit_stage5.py tests/test_med2_b_trace.py tests/test_zero_egress_and_dispatch_audit.py tests/test_p0_audit_hmac_downgrade.py tests/test_core_a1_crypto_audit.py -q`
  sowie `ruff check` / `mypy` auf den neun Dateien.

---

## DELEGATED (nicht in meinem Datei-Bereich — von anderen Agenten zu übernehmen)

1. **`tests/test_med2_b_trace.py:188-196`** — `test_verify_reports_unverified_versions_outside_production` erwartet altwidersprüchlich `valid=True` bei Platzhaltern. Muss auf `valid=False` + `reason` mit „Platzhalter/unknown" umgestellt werden (oder entfallen). Auch `:167-185` sollte `ARCHON_AUDIT_STRICT`-Unabhängigkeit statt `ENVIRONMENT` prüfen.
2. **Tests ohne Anker-Setup** — durch die jetzt unbedingte Anker-Strukturprüfung schlagen `verify_integrity()`-Assertions ohne `ARCHON_AUDIT_ANCHOR_PATH`/`_write_anchor()` fehl, u. a. `tests/test_p0_audit_hmac_downgrade.py:31-32`, `tests/test_fix_batch2.py:71-73`, `tests/test_zero_egress_and_dispatch_audit.py:78-80,113,126-129,261,307`, `tests/test_p1_content_audit_hardening.py:24,130,139,142,148,225`, `tests/test_m49_eu_ai_act_compliance.py:109`, `tests/test_audit_fixes_batch.py:1478`. Entweder Ankerdatei im Test anlegen oder bewusst `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1` setzen. Kein Produktivcode-Betroff.
3. **`archon/routers/operations_keys.py:53-64`** — `api_create_key()` fängt jede Exception und mappt sie auf HTTP 500; damit die neue `AuditWriteFailedError(status_code=503)` auch beim Create-Pfad als 503 ankommt, muss `except AuditWriteFailedError: raise` (oder `except HTTPException: raise`) ergänzt werden. Revoke/Delete (`:78-81`, `:95-98`) reichen `HTTPException` bereits durch.
4. **`main.py:1354`** — der 30-s-Anker-Loop prüft weiterhin nur `"error" in v`; ein `record_chain_anchor()`-Result mit `violation: True` (Tail-Löschungs-Versuch) wird nicht geloggt. Bedingung um `or v.get("violation") is True` erweitern. (Teil des ursprünglichen D05-BLOCKERS, gehört nicht zu meinem Scope.)
5. **`docs/SYSTEM_HANDBUCH.md:828`** — Doku-Aussage „selbst direkte Datenbank-Manipulationen an Einzelspalten werden sofort erkannt" jetzt zwar für alle Dispatch-Spalten aller Kategorien zutreffend; trotzdem Geltungsbereich („Dispatch-Spalten") präzisieren.
6. **`.env.example` / `docker-compose*.yml`** — Ankerziel liegt laut D05/HIGH weiterhin als lokale Datei `./data/audit_anchor.log` neben der DB (Doku behauptet „extern"). Für die volle S-5.3-Erfüllung auf getrenntes, nur-append-fähiges Volume/Remote-Timestamp umstellen. `ARCHON_AUDIT_STRICT` ist nun Default 1 und muss nicht explizit gesetzt werden.

**Anzahl Fixes:** 9 · **DELEGATED:** 6

# W2-C — Security/Audit Remediation Report (26.11.2026)

**Scope:** D04-M1, D04-M2, D12-M5 (Gewichtung 7/6/7, Welle W2).
**Dateibesitz (ausschließlich geändert):**
- `backend/session_taint_guard.py`
- `backend/dual_llm_sanitizer.py`
- `tests/test_w2_c_audit_strict.py` (neu)
- `audit_reports/w2_c_report.md` (dieses Dokument)

**Soll-Basis:** `audit_reports/00_SOLL_SPEC.md` §0 (Vier-Glieder-Kriterium: Produzent → Konsument → Effekt → Verifikation), §2.3/§2.5 (Audit-Schreibfehler nie verschlucken), `audit_reports/GEWICHTETE_BEFUNDLISTE.md` (Nr. 38/53/63), `audit_reports/domain_04.md` (F-05/F-06), `audit_reports/domain_12.md` (Befund 8). `NEVER_DO_LIST.md` §5 beachtet: kein Coroutine-Replay, keine PostgreSQL-Migration, keine Empfehlung dazu.

---

## 1. D04-M1 — HITL-Taint-Freigabe ohne signierten Nachweis (behoben)

**Ist (vorher):** `resolve_taint_approval()` setzte Status/Reviewer per `UPDATE` + `conn.commit()` und schrieb danach den signierten Audit-Event in `try/except` mit `logger.warning`. Bei Audit-Ausfall blieb die Freigabe `approved` und wurde über `check_egress_tool_call()` (CAS `AND consumed=0`) ganz normal eingelöst. Angreifer mit DB-Schreibzugriff oder vollem Audit-Log konnte einen kritischen Egress ohne Ketteneintrag freigeben.

**Fix (`backend/session_taint_guard.py`):**
- Neue Helfer `_audit_strict()` (`:29`, Default `ARCHON_AUDIT_STRICT=1`), `_record_audit_error()` (`:39`, ERROR + Zähler `_AUDIT_ERROR_COUNTS`) und `_record_taint_audit()` (`:47`).
- `resolve_taint_approval()` (`:351`): der signierte Pflicht-Event `security/taint_hitl_resolved` mit `requested_by` **und** `reviewer` wird jetzt **vor** `conn.commit()` geschrieben (`:418–432`).
- Bei Auditfehler: ERROR-Log + Zähler, und bei Strict (Default) `RuntimeError("audit_write_failed")`. Die Exception verlässt den `with _connect()`-Block vor dem Commit → sqlite3 rollt das `UPDATE` beim `close()` zurück. Status bleibt `pending`; die Freigabe ist nicht einlösbar.
- `ARCHON_AUDIT_STRICT=0` bleibt der einzige explizite Opt-out; der Fehler wird dort nicht mehr verschluckt, sondern gezählt.

**Verifikation (§0):** Produzent = `_record_taint_audit`, Konsument = `resolve_taint_approval` vor Commit, Effekt = kein Statuswechsel bei Auditfehler, Verifikation = 4 Regressionstests (siehe §3), inkl. Test mit paralleler SQLite-Connection, der den Status `pending` **zum Zeitpunkt des Audit-Schreibvorgangs** beweist.

---

## 2. D04-M2 / D12-M5 — Fail-Open Trust-Registry & gewarntes Trust-Toggle-Audit (behoben)

**Ist (vorher):** `load_trusted_sources()` gab bei fehlender/fehlerhafter `data/trusted_sources.json` die hartcodierte Whitelist `intern@archon.local`, `system@archon.os`, `micha@archon.os` zurück. `sanitize_external_input()` markierte diese Quellen ohne echte Verifikation als `extracted_facts={"trust_status": "VERIFIED_SENDER"}` und gewährte den vereinfachten Trust-Pfad. `toggle_trusted_source()` schrieb die Whitelist atomar und protokollierte den Auditfehler nur mit `logger.warning` — die Quelle blieb `[T]`.

**Fix (`backend/dual_llm_sanitizer.py`):**
- Neue `TrustedSources(list)` (`:41`) mit `verified` und `trust_verification_error`; list-kompatibel, damit der bestehende Endpunkt `GET /api/operations/security/trusted-sources` (`archon/routers/operations_security.py:88`) unverändert bleibt (keine fremde Datei geändert).
- `load_trusted_sources()` (`:84`): bei fehlender Datei → `trust_registry_missing`, bei Lese-/Parsefehler → `trust_registry_unreadable: ...`; in beiden Fällen **leere Liste** + `verified=False` + Fehlercode (Fail-Closed). Die hartcodierten Absender sind entfernt.
- `is_trusted_source()` (`:115`): lehnt bei explizitem Registry-Fehler jede Quelle ab. Einfache Listen-Mocks bleiben kompatibel (`verified` defaultet auf `True`, der echte Loader setzt es bei Fehler auf `False`).
- `sanitize_external_input()` (`:225–233`): `VERIFIED_SENDER` wird nur noch erzeugt, wenn die Registry erfolgreich gelesen wurde (`registry_verified`) **und** die Quelle in der verifizierten Liste steht (`:254`).
- `toggle_trusted_source()` (`:132`):
  - Audit-Event `security/sender_trust_toggled` wird **vor** dem Atomar-Schreiben der Registry erzeugt (`:160–179`); bei Fehler ERROR + Zähler und bei Strict (Default) `RuntimeError("audit_write_failed")` — die Änderung wird gar nicht erst angewandt (strengste Form von „Toggle zurücknehmen").
  - Eine existierende, aber nicht verifizierbare Registry wird mit `RuntimeError("trust_registry_unverified: ...")` abgelehnt (`:148–149`), damit ein Toggle keine beschädigte Datei überschreibt. Fehlt die Datei, darf ein Admin sie erstmals anlegen.
  - Der Auditfehler beim Injection-Block-Pfad (vormals `logger.warning`) wird nun über `_record_audit_error("prompt_injection_blocked", ...)` als ERROR mit Zähler sichtbar gemacht (Kontrollfluss unverändert).

**Verifikation (§0):** Produzent = Registry-Loader/Toggle-Audit, Konsument = `is_trusted_source`/`sanitize_external_input`, Effekt = keine `VERIFIED_SENDER`-Aussage bei Registry-Fehler, kein Toggle ohne Proof, Verifikation = 8 Regressionstests (inkl. gemocktem `open`-Fehler, ungültigem JSON, fehlender Datei und Auditfehler).

---

## 3. Tests

**Neue Datei:** `tests/test_w2_c_audit_strict.py` — 12 Tests:

| Gruppe | Tests | Kern asserting |
|---|---|---|
| D04-M1 | 4 | Auditfehler → `RuntimeError("audit_write_failed")`, Status `pending`, Freigabe nicht einlösbar; Audit-Vor-Commit (zweite SQLite-Connection sieht `pending`); Happy Path mit CAS-Verbrauch; `ARCHON_AUDIT_STRICT=0` zählt Fehler |
| D12-M5/D04-M2 | 8 | Parsefehler/fehlender `open`/fehlende Datei → leere Liste + `trust_verification_error`; kein `VERIFIED_SENDER` bei Registry-Fehler; `VERIFIED_SENDER` nur bei gültiger Registry; Toggle-Auditfehler → RuntimeError + Datei unverändert; Audit vor Datei-Schreiben;Toggle verweigert unlesbare Registry |

**Resultate (Python 3.12.13, `.venv`, `ARCHON_TEST_DB_ISOLATION=1`):**
- `tests/test_w2_c_audit_strict.py`: **12 passed**
- Regressionsmenge `test_audit_fixes_batch.py`, `test_fix_w4_b_integrations.py`, `test_f14_audit_signing.py`, `test_rbac_admin_routes_paket2.py`, `test_w2_c_audit_strict.py`: **454 passed**
- Weitere Taint-/Sanitizer-nahe Tests (`test_f11_requested_by_hitl_chain.py`, `test_fix_w2_a_security.py`, `test_hardening_wave1_d04_d14.py`, `test_milestones_75_89_76_91_78.py`, `test_reaudit_stage12.py`, `test_w2_f_ingest_ssrf.py`): **55 passed**

**Hinweis zur Umgebung:** Ohne `ARCHON_TEST_DB_ISOLATION=1` schlugen 7 Tests in der obigen Regressionsmenge mit `sqlite3.DatabaseError: database disk image is malformed` im **gemeinsamen** `chained_audit_log`-DB fehl (betroffen: `auth_service`, `api_key_manager`, `event_mesh`, `background_loops`, `llm_egress_guard`). Das ist ein vorbestehendes Umgebungsproblem (parallele Subagenten / laufender Container auf derselben Audit-DB), kein Befund dieser Änderung; mit der in `pytest.ini` empfohlenen Isolierung sind alle Tests grün. Die eigenen 12 Tests laufen auch ohne Isolierung grün, da sie alle Audit-Schreibvorgänge mocken.

---

## 4. Konformität & Randbedingungen

- **Keine Commits** durchgeführt.
- **Keine fremden Dateien** geändert (insb. `archon/routers/operations_security.py` blieb unangetastet; API-Kompatibilität wurde über die listenkompatible `TrustedSources`-Klasse erhalten).
- **Kein Replay, keine PostgreSQL-Migration**, keine diesbezügliche Empfehlung (NEVER_DO_LIST §5).
- Alle Änderungen sind additiv/kompatibel im bestehenden SQLite-/HMAC-Kettenpfad. Bestehende Freigaben mit `requested_by` und Passkey-Proof bleiben unverändert nutzbar.
- Die Hilfsfunktionen `_audit_strict()` / `_record_audit_error()` folgen dem im Repo etablierten Muster aus `local_security_guard.py:14`, `passkey_hitl.py:11` und `egress_firewall.py:42`.

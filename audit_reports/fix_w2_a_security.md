# Fix-Report W2-A — F020 / Domäne 04 (Governance, Security & Permissions)

**Datum:** 25.11.2026 · **Fix-ID:** F020 · **Scope:** 5 HIGH + 5 MED aus `domain_04.md`

---

## 1. Umgesetzte Änderungen

### H-04-1 — DataClassifier-Fail-Open im Dispatch-Pfad (`core_dispatcher.py`)
- Beide Klassifikationsfehler-Blöcke (Container-Gate `_gate_container_dispatch`,
  Haupt-Dispatch `_dispatch_to_omniroute_or_container_impl`) setzen jetzt
  `explicit_cat/classified_cat = "confidential"`.
- `.get("cloud_llm_allowed", True)` → `.get("cloud_llm_allowed", False)`; ein
  fehlender Dict-Key bedeutet damit „nicht Cloud-erlaubt".
- Jeder Klassifikationsfehler schreibt über `_record_blocked_proof()` einen
  signierten Audit-Proof (`action=llm_dispatch_blocked_classifier_unavailable`,
  `error_code=DATA_CLASSIFIER_UNAVAILABLE`) und eskaliert als
  `ZeroEgressBlockedError`. Scheitert auch der Proof-Write, wird der Block
  trotzdem geworfen (nie Fail-Open).
- Analog zu den bereits korrekten Stellen `core_dispatcher.py:308-310` /
  `backend/agent_router.py:834-836`.

### H-04-2 — API-Key-Pepper (`backend/api_key_manager.py`, `main.py`, `.env.example`, `scripts/audit_secrets.py`)
- `KEY_SALT`, `LEGACY_KEY_SALT`, `_warn_missing_pepper_once()` und
  `_hash_token()`-SHA256-Fallback entfernt. Es gibt nur noch
  `hmac.new(env_pepper, token, sha256)` via `_get_api_key_pepper()`.
- `_legacy_hash_token()` und die Legacy-Abfrage in `validate_and_consume()`
  entfernt: Keys unter dem öffentlich bekannten Salt werden **nicht mehr**
  akzeptiert (kompromittiert → Rotation erforderlich).
- Fehlt `ARCHON_API_KEY_PEPPER` in Produktion: `ApiKeyPepperMissingError`
  (503) im Manager **und** Fail-Fast-Hook `_assert_api_key_pepper()` im
  Lifespan (`_FAIL_FAST_HOOKS` + `_STARTUP_HOOKS`). Platzhalter-/Kurz-Pepper
  werden ebenfalls abgelehnt.
- Isolierte Entwicklung nutzt einen **prozesslokalen Zufalls-Pepper**
  (`secrets.token_urlsafe`) — keine hartcodierte Konstante, keine
  Cross-Prozess-Gültigkeit. `.env.example` dokumentiert ENV-Pflicht + Rotation.
- Neues Secrets-Pattern für hartcodierte `ARCHON_OS_API_KEY_SALT_*` /
  `KEY_SALT = "..."`; Auditberichte, die den Wert als Beleg zitieren, sind
  als Doku-Ausnahme markiert. `audit_secrets.py --all`: **0 Funde**.

### H-04-3 — `requested_by` durch den Tool-Chokepoint
- `session_taint_guard.check_egress_tool_call(requested_by=...)`:
  - verlangt einen nicht-leeren Actor, **bevor** eine neue HITL-Freigabe
    angelegt wird (kein `pending`-Eintrag bei `requested_by=""`);
  - lehnt Legacy-Freigaben mit leerem `requested_by` auch beim Einlösen ab;
  - `resolve_taint_approval()` denyt jetzt explizit bei leerem
    `requested_by` (vorher wurde die Vier-Augen-Prüfung still übersprungen).
- `delegation_isolation.enforce_runtime_tool_gate(requested_by=...)` und
  `PolicyEngine.decide(requested_by=...)`: Parameter aufgenommen und bis
  `check_egress_tool_call()` durchgereicht. Bewusst **kein** pauschaler Deny
  an dieser Stelle: harmlose Tools ohne Freigabe müssen weiter laufen; die
  harte Ablehnung liegt genau dort, wo die Freigabe entsteht.
- `archon/routers/inbox_tools.py`: Body-Actor
  `payload.get("requested_by", "Robert …")` durch
  `require_session_actor(request)` ersetzt.

### H-04-4 — Treasury-Vier-Augen (`backend/treasury_engine.py`)
- Neue SSOT-Helper `_finance_threshold(policy_key)` liest
  `finance_four_eyes_min` / `finance_auto_approval_max` aus
  `approval_policy_engine`; fehlende/nicht numerische Policy → harter Fehler.
- `approve_payment()`: bei `amount >= four_eyes_min` deny bei Schnitt der
  Identitäts-Tokens (`approval_policy_engine._actor_identity_tokens`,
  SSOT mit Ersteller-Sperre). Leere Identität → `PermissionError`.
- `request_payment()`: `requested_by` **nur** aus dem serverseitigen
  `actor_id`, nie aus dem Payload; `anonymous`/`system`/leer → Ablehnung.
- `execute_immediately` nur noch bei `amount < auto_max` (Default 50 €),
  ohne Passkey-HITL und mit verifiziertem Actor; sonst `pending_approval`.

### H-04-5 — MCP-HITL fail-closed (`backend/mcp_gateway.py`)
- Neue `HITLVerificationUnavailable`. `_is_hitl_consumed()` wirft bei
  SQLite-/Lesefehlern statt `return False`; `_check_hitl_gate()` denyet mit
  `fail-closed`-Meldung. Nicht vorhandene DB = noch kein Verbrauchseintrag
  (zulässig; der Verbrauch wird beim Markieren angelegt).
- `_mark_hitl_consumed()` eskaliert Persistenzfehler, schreibt mit
  `INSERT OR IGNORE`, verifiziert per **Lese-Back** und erst dann Cache-
  Markierung. Kein „nur im Speicher"-Fallback mehr.
- Demo-Mode-Guard: `is_demo_mode` am Modulkopf importiert; Prüfungsfehler →
  `-32003 {"message": "demo_guard_unavailable"}` (hart deny).

### MED
- `main._assert_auth_on_nonloopback_bind()`: liest jetzt
  `AuthService._read_auth_enabled()` (echte Config ohne Force-Pfad) statt
  `is_auth_enabled()` — der tote Hook ist wirksam.
- `backend/tool_warrants.py`: `PATH_ARG_KEYS` + `AMOUNT_ARG_KEYS` als SSOT
  (von `delegation_isolation` importiert, keine zweite Liste); alle
  Betragsaliase `amount/value/total/price/betrag` geprüft; fehlender Betrag
  bei betragspflichtigen Tools → deny; vollständige Pfad-Aliasliste inkl.
  `destination_path`, `workdir`, `url`, …
- `backend/privacy_router.py`: `zero_egress_governance` aus `settings.json`
  als echte **verstärkende** zweite Quelle, nach dem Merge von
  `privacy_routing.json` angewendet (ein `true` kann nicht durch ein
  `false` in einer anderen Datei überschrieben werden).
  `save_privacy_config()` schreibt `privacy.zero_egress` und
  `zero_egress_governance` in einem einzigen read-modify-write; Fehler →
  `RuntimeError`.
- `local_security_guard.py`: **keine Änderung nötig** — die 25
  Injektionsmuster sind bereits die geprüfte SSOT; kein D04-Befund betrifft
  Funktionscode in dieser Datei.

---

## 2. Verifikation (selbst ausgeführt)

| Prüfung | Ergebnis |
|---|---|
| `.\.ci_venv\Scripts\python.exe -m compileall -q core_dispatcher.py main.py local_security_guard.py backend archon\routers\inbox_tools.py scripts\audit_secrets.py tests\test_fix_w2_a_security.py` | Exit **0** |
| `pytest tests/test_fix_w2_a_security.py -q` | **18 passed** |
| `pytest` der 6 relevanten Bestandsdateien (M48, Stage1/3, M75/89/76/91/78, Hardening-D04/D14, Audit-Fixes, neue Datei) | **136 passed, 1 failed** (siehe §3) |
| `python scripts/audit_secrets.py --all` | **OK — 0 Funde**, 7035 Dateien |

**Shell-Hinweis (explizit):** `pwsh.exe` war zu Beginn und mehrfach
zwischenzeitlich mit `Zugriff verweigert (os error 5)` blockiert. Nach
erneutem Versuch war die Shell verfügbar; `python` im PATH ist nur der
Microsoft-Store-Stub. Verwendet wurde der vorhandene Workspace-Interpreter
`.ci_venv\Scripts\python.exe` (Python 3.11.15, pytest 9.2.0). Ein
Python-3.13-Lauf war in dieser Umgebung nicht möglich.

---

## 3. Bekannte Restpunkte / Übergaben

1. **Obsolet Test (nicht in meinem Ownership):**
   `tests/test_audit_fixes_batch.py::test_api_key_manager_pepper_hmac_and_legacy_fallback`
   (Z.111-137) testet genau das entfernte Legacy-Fallback-Verhalten
   (`_legacy_hash_token`, Cross-Pepper-Gültigkeit). Er schlägt mit
   `AttributeError: ... hat kein Attribut '_legacy_hash_token'` fehl. Der
   Test muss auf den neuen Security-Contract umgeschrieben werden ( ENV-
   Pepper Pflicht, Legacy-Keys kompromittiert ). Ich habe die Datei nicht
   verändert, da sie nicht in W2-A-Ownership liegt.
2. **`backend/tool_runtime.py` ( fremdes Ownership):** unverändert. Der
   andere Agent muss `enforce_tool_execution()` /
   `execute_agent_tool()` um einen `requested_by`-Parameter erweitern und
   ihn an `policy_engine.decide(requested_by=...)` weitergeben. Meine
   Kette akzeptiert und verarbeitet den Parameter bereits; mit leerem Wert
   wird keine kritische Egress-Freigabe mehr angelegt. Bis zur Verdrahtung
   bleibt der Deny im `session_taint_guard` die wirksame Kontrolle.
3. **`data/privacy_routing.json` (nicht in Ownership):** existiert in
  zwischenzeitlichem Stand mit `sensitive_local_routing=false` und
   `fallback_to_eu=true`. `get_privacy_config()` wendet die verstärkenden
   `zero_egress_governance`-Werte danach an; die Datei selbst sollte vom
   Konfigurations-Owner mit `settings.json` konsolidiert werden.
4. **Key-Rotation (operativ):** alle unter dem alten Salt
   `ARCHON_OS_API_KEY_SALT_2026_SECURE` erzeugten API-Keys sind als
   kompromittiert zu betrachten und müssen widerrufen und neu ausgestellt
   werden. `ARCHON_API_KEY_PEPPER` ist in Produktion Pflicht (Fail-Fast).
5. NEVER_DO_LIST (§5: kein Replay-Framework, keine PostgreSQL-Migration)
   und alle Gates bleiben intakt; keine Stubs, keine deaktivierten Prüfungen.

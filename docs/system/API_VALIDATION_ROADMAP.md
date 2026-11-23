# API-Validierung & HTTP-Status – 8 Etappen

Ziel: alle **121 Endpunkte mit rohem `Dict = Body(...)`** auf Pydantic-Modelle
umstellen und alle **25 `{"status":"error"}`-Antworten mit HTTP 200** auf echte
HTTP-Fehlercodes heben. Inventur: `scripts`-interner Scan (2026-11-22).

**Kompatibilitätsregel (wichtig):**
- `model_config = ConfigDict(extra="ignore")` als Default: bestehende Clients
  senden Zusatzfelder (z. B. `created_by`, `user_id`, `rejected_by`), die
  serverseitig aus der Session kommen. Diese werden ignoriert, nicht
  abgelehnt. `extra="forbid"` nur nachweislich sicheren Endpunkten.
- Bei HTTP-200-Fehlern wird `JSONResponse(status_code=4xx/5xx, content=...)`
  mit **altem Body-Shape** verwendet. Damit sehen Monitoring und Clients den
  echten Status, ohne dass bestehende `res.json()`-Parser brechen.

---

| Etappe | Scope | Funde | Status |
|---|---|---:|---|
| 1 | `operations_keys`, `operations_approvals`, `operations_dunning`, `operations_receipts`, `llm_providers` | 23 | ✅ erledigt |
| 2a | `auth` (10 Endpunkte: Toggle, Login, User-CRUD, Passwort, Passkey) | 10 | ✅ erledigt (23.11.2026) |
| 2b | `system` (7), `plugins` (3): Update/Drain/Language, Plugin-Tools/-Config | 10 | ✅ erledigt (23.11.2026) |
| 2c | `security` (7), `routergate` (4): Maskierung, PII, Egress, RBAC-Check, Kosten/Bandit | 11 | ✅ erledigt (23.11.2026) |
| 2d | `erp` (10): Entitäten, Kontakte, Belege, Bankimport, PocketBase-Sync | 10 | ✅ erledigt (23.11.2026) |
| 2 | `llm_providers` (Rest), `governance`, `guardian`, `docker_services`, `watchdog`, `hermes_profiles`, `email_settings`, `kanban`, `memory_ops`, `telegram` | ~19 | offen |
| 3 | `v2_capabilities` (Teil 1) | ~20 | offen |
| 4 | `v2_capabilities` (Teil 2) + `content_machine` (Teil 1) | ~20 | offen |
| 5 | `content_machine` (Rest) | ~19 | offen |
| 6 | `operations_calendar` (14) + `operations_sysops` (7) | 21 | offen |
| 7 | `operations_emails`, `operations_prompts`, `playbooks`, `operations_security`, `preflight_shadow`, `tenants` | ~20 | offen |
| 8 | `documents`, `oracle_seo`, `voice`, `system`, `squad_packs`, `operations_finetuning`, `backend/operations_api` | ~19 | offen |

**Rest nach Etappe 1:** 105 Body-Dicts + 18 HTTP-200-Fehler = 123.  
**Nach Etappe 2a:** 95 Body-Dicts + 18 HTTP-200-Fehler = 113.  
**Nach Etappe 2b:** 85 Body-Dicts + 18 HTTP-200-Fehler = 103.  
**Nach Etappe 2d:** 44 Body-Dicts + 18 HTTP-200-Fehler = 62.  
**Hinweis:** alle Testlaeufe seit dem 23.11.2026 nur noch mit
`ARCHON_TEST_DB_ISOLATION=1`, damit die produktiven `data/*.db` nicht mehr
durch Host/Container-WAL-Konflikte beschaedigt werden.

---

## Etappe 2a – Auth (23.11.2026, P0-Sprint)

Alle 10 `dict = Body(...)`-Endpunkte in `archon/routers/auth.py` nutzen jetzt
Pydantic-v2-Modelle (`AuthToggleRequest`, `AuthLoginRequest`,
`AuthCreateUserRequest`, `AuthUpdateUserRequest`, `AuthChangePasswordRequest`,
`PasskeyConfigRequest`, `PasskeyRegisterOptionsRequest`,
`PasskeyRegisterVerifyRequest`, `PasskeyHitlOptionsRequest`,
`PasskeyHitlVerifyRequest`).

- Kompatibilitaetsregel eingehalten: gemeinsame Basis mit
  `ConfigDict(extra="ignore")`; Client-Zusatzfelder (`created_by`, `user_id`,
  `rejected_by`, …) werden verworfen statt abgelehnt.
- Migrationsmuster: Handler starten mit `payload = payload.model_dump()` — die
  bestehende Dict-Zugriffslogik bleibt unverändert, Response-Shapes unverändert.
- Konkreter Fix: `POST /api/auth/login` mit `username: 123` lieferte vorher
  `AttributeError: 'int' object has no attribute 'strip'` (HTTP 500) → jetzt 422.
- Verifikation: `tests/test_p0_api_validation.py` (4 neue Tests) + volle Suite
  **1745 passed, 16 skipped**.

### Etappe 2b – system.py / plugins.py (10 Endpunkte)

- Wichtigste Erkenntnis: **Rollenzaun vor Payload-Parsing**. Die erste
  Fassung hatte `payload.model_dump()` vor `_require_admin()` / 
  `require_admin_or_503()` — direkte RBAC-Tests (die Handler mit `Body`-Stubs
  aufrufen) brachen mit 31 Fehlern. Korrekte Reihenfolge: erst autorisieren,
  dann parsen. Das ist auch fachlich fail-closed.
- `PluginSettingsRequest` nutzt bewusst `extra="allow"` (beliebige
  Plugin-Manifest-Settings muessen durchgereicht werden), alle anderen
  `extra="ignore"`.
- Verifikation: `tests/test_p0_api_validation_batch2.py` (4 neue Tests) +
  volle Suite **1749 passed, 16 skipped**.

---

## Etappe 1 – Details

### Neue Pydantic-Modelle
- `operations_keys.py`: `ApiKeyCreateRequest` (Scopes-Liste, RPM/RPD mit Grenzen)
- `operations_approvals.py`: `ApprovalPolicyUpdateRequest`, `ApprovalRequestCreate`
  (Betrag `ge=0`), `ApprovalRejectRequest`, `DelegationSetRequest`
- `operations_dunning.py`: `InvoiceCreateRequest` (`amount_net > 0`, `due_days` 0–365,
  `level` 1–3), `DunningDraftRequest`, `DunningApproveRequest`, `DunningMarkPaidRequest`
- `operations_receipts.py`: `ReceiptProcessRequest` (Model-Validator: Bild oder Pfad
  erforderlich), `ReceiptPatchRequest` (nur erlaubte Felder, `exclude_none=True`)
- `llm_providers.py`: `PrivacyRoutingRequest` (`extra="allow"`),
  `ProviderConnectionTestRequest`

### Zusätzlich behoben
- `operations_dunning`: `except Exception` verschluckte HTTP 404 → jetzt
  `except HTTPException: raise` vor dem Blanket-Handler.
- `operations_receipts`: `PATCH` gab das Pydantic-Objekt statt eines Dicts zurück.
- `llm_providers`: 7 Fehlerpfade liefern jetzt 500/502 statt 200
  (alter Body-Shape bleibt, Kompatibilität zu `chat_engine.js`/`agent_profiles.js`).

### Bewusst nicht in Etappe 1
`get_llm_prices()` und `get_llm_provider_models()` in `llm_providers.py` sind
auch **interne Helfer** (`chat.py:947`, `backend/llm_kernel.py:77`) und müssen
zuerst von ihren Route-Decorators getrennt werden – sonst bekämen interne
Aufrufer ein `JSONResponse` statt eines Dicts. Das ist Etappe 2.

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
| 2 | `llm_providers` (Rest), `governance`, `guardian`, `docker_services`, `watchdog`, `hermes_profiles`, `email_settings`, `kanban`, `memory_ops`, `telegram` | ~19 | offen |
| 3 | `v2_capabilities` (Teil 1) | ~20 | offen |
| 4 | `v2_capabilities` (Teil 2) + `content_machine` (Teil 1) | ~20 | offen |
| 5 | `content_machine` (Rest) | ~19 | offen |
| 6 | `operations_calendar` (14) + `operations_sysops` (7) | 21 | offen |
| 7 | `operations_emails`, `operations_prompts`, `playbooks`, `operations_security`, `preflight_shadow`, `tenants` | ~20 | offen |
| 8 | `documents`, `oracle_seo`, `voice`, `system`, `squad_packs`, `operations_finetuning`, `backend/operations_api` | ~19 | offen |

**Rest nach Etappe 1:** 105 Body-Dicts + 18 HTTP-200-Fehler = 123.

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

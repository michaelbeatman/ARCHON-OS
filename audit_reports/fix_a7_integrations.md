# Fix-Log A7 — Integrationen/Webhooks (Phase 3 Remediation, D06)

**Agent:** Fix-Agent A7 (Integrationen/Webhooks)
**Basis:** HEAD `cee78206`, Branch `main`
**Datum:** 25.11.2026
**Scope:** nur die in der Aufgabenstellung gelisteten Dateien; `main.py` (A9),
`backend/llm_egress_guard.py` (A2), `core_dispatcher.py` (A4), `onboarding.py` (A8),
`containers.py` (A5/A9), `docs/**` und `tests/**` wurden NICHT veraendert.

---

## Vorbedingungen / abgegrenzt

- **B3** (`/api/v1/jev/test`: Admin-Zaun, `check_public_url`, kein Key bei fremder
  `base_url`) ist laut Auftrag bereits behoben — `core_settings.py` und
  `jev_router.py` wurden **nicht** angefasst.
- **G-01/G-02** eingehalten: keine Secrets im Code, keine echten Keys in diesem
  Report, HMAC ausschliesslich ueber den exakten (kompakt serialisierten) Body.
  Alle Token-Stellen enthalten nur den Laufzeit-Platzhalter
  `__ARCHON_SERVICE_TOKEN__`; der echte Wert kommt aus
  `data/.archon_service_token` bzw. `ARCHON_SERVICE_TOKEN`.

---

## Fix 1 — D06/HIGH: fuenf n8n-Stubs durch echte Nodes ersetzen

**Datei:** `scripts/n8n_workflows_bundle.json`

Alle fuenf previously inaktiven Webhook+Set-Stubs sind jetzt **aktive**, echte
Workflows mit realem Archon-API-Effekt (G-03: Produzent → Konsument → Wirkung):

| ID | Workflow | Webhook | Echter Effekt (HTTP-Node) |
|---|---|---|---|
| `b1c3f1e9b2d84f01` | Article Extractor | `archon-extract-article` | POST `/api/v2/research/triangulate` |
| `b1c3f1e9b2d84f02` | Multi-Channel Dispatcher | `archon-dispatch-message` | POST `/api/telegram/send` |
| `b1c3f1e9b2d84f03` | Document Renderer | `archon-render-document` | POST `/api/corporate/render-template` |
| `b1c3f1e9b2d84f04` | Feed & Search Engine | `archon-search-feed` | GET `/api/inbox-watcher/scan-now` |
| `b1c3f1e9b2d84f05` | CRM Sync Pipeline | `archon-sync-crm` | GET `/api/crm/contacts` |

- `active: true` bei **allen** sechs Bundle-Workflows.
- **Jeder** HTTP-Node: Host `http://archon-os:8501` und Header
  `X-Archon-Service-Token: __ARCHON_SERVICE_TOKEN__` (Laufzeit-Injektion).
- **Jeder** Webhook ist authentifiziert: ein `n8n-nodes-base.code`-Node
  `Archon HMAC Verify` sitzt zwischen Webhook und API-Node und bricht bei
  fehlendem Secret oder ungueltiger Signatur ab (fail-closed).
- `responseMode: "lastNode"` — Antwort erst nach Ausfuehrung, Status spiegelt
  die echte API-Antwort (`{{ $json.status || 'success' }}`), keine
  `not_implemented`-Strings mehr.
- Jeder Format-Node traegt `verified: "hmac_sha256"` als nachweisliches
  Verifikationsmerkmal.

## Fix 2 — D06/HIGH: HMAC-Empfaenger verifizierbar + stabile ID

**Datei:** `scripts/n8n_workflows_bundle.json` (Workflow 6),
`scripts/deploy_n8n_routines.py`, `scripts/activate_n8n_workflows.js`

- Empfaenger mit **stabiler ID `a7c3f1e9b2d84f6a`** versioniert — das ist die
  ID, die `docs/AUDIT_FINDINGS_REGISTER.md:287` bereits fuehrt. Der
  ID-Drift (`…f00` im Bundle vs. `…f6a` in der Doku) ist damit **aus Code-Sicht
  behoben**; eine Doku-Aenderung war nicht noetig (Datei nicht im Scope).
- `active: true`, `responseMode: "response"` (statt `onReceived`) — HTTP 200
  wird nicht mehr vor der Signaturpruefung gesendet.
- Pruefung mit **`crypto.createHmac` + `crypto.timingSafeEqual`**
  (`require('crypto')`, mit constant-time XOR-Fallback, falls der n8n-Task-Runner
  Built-ins blockt). Laengencheck vor dem Vergleich; Secret nur aus
  `$env.ARCHON_WEBHOOK_HMAC_SECRET`, kein Default.
- HMAC ueber den **exakten kompakten Body**: `JSON.stringify(body)` bzw.
  `rawBody`-Buffer, passend zum Sender
  (`json.dumps(..., ensure_ascii=False, separators=(',', ':'))`).
- Code-Node `onError: "continueErrorOutput"`: HMAC-Fehler → Error-Branch →
  `Respond HMAC Error (401)` (`{"status":"error","error":"invalid_signature"}`);
  Erfolg → `Format Ack` mit `executionId` → `Respond OK (200)`.
  Damit kann der Dispatcher eine Ablehnung als `status:"error"` erkennen.
- `deploy_n8n_routines.py`: gemeinsames `HMAC_VERIFY_JS` auf timingSafeEqual
  gehoben; `_ensure_bridge_hmac_receiver()` normalisiert vorhandene Receiver
  (active, responseMode, JS, stabile ID) statt sie still inaktiv zu lassen.

## Fix 3 — D06/HIGH: Signierender Webhook-Adapter

**Datei:** `backend/workflow_node_plugins.py` (generischer HTTP-Adapter)

- `webhook_url` aus `resolved_params` aufgeloest (Fallback `http_endpoint`),
  `action` und `payload_text`/`content` und `executed_at` werden als
  Top-Level-Felder an das Empfaenger-Schema gesetzt — der
  G-03-Verdrahtungsbruch zwischen UI-Control und Ziel-Endpunkt ist geschlossen.
- Die aus `resolved_params` stammende Webhook-URL (bzw. jeder
  Execution-Webhook) wird vor dem Request durch `check_target_url()` geprueft
  (SSRF/Exfil-Schutz); bei Block → `status:"blocked"`. Reine 3rd-Party-Plugins
  mit festem, lokal deklariertem `http_endpoint` bleiben unberuehrt, damit
  bestehende External-API-Plugins nicht durch eine leere Env-Allowlist
  regressieren.
- Body mit `json.dumps(..., ensure_ascii=False, separators=(",",":"))` und
  `headers.update(webhook_signature_headers(body_bytes))` — identisch mit
  `core_dispatcher.py` und `mcp_n8n_driver.py`.
- Antwortvalidierung: HTTP ≥ 400 oder `status` in
  `blocked/error/rejected/denied/invalid_signature/unauthorized/forbidden/failed`
  → `status:"blocked"`, `execution:"rejected"` (DLQ-Pfad), **kein** Erfolg.
  Bei ausfuehrenden Webhooks zusaetzlich Pflicht zur bestaetigten
  `executionId`/`status` aus der Antwort; sonst `blocked`/`execution_unconfirmed`.

## Fix 4 — D06/MED: statische Modellliste gekennzeichnet

**Datei:** `api_provider.py`

- Neue `ProviderModelList(list)` mit `source`, `verified_at`, `status` plus
  Helfer `model_list_provenance()`. Die `List[str]`-API bleibt kompatibel.
- Live-Listen: `source="live"`, `verified_at=<UTC>`, `status="ok"`.
- OmniRoute-Fallback (alle drei URLs tot): `source="static_fallback"`,
  `verified_at=None`, `status="degraded"` — kein stilles `status:"ok"` mehr.
  Metadaten ueberstehen den 120-s-TTL-Cache (vorher `list(...)` kopiert und
  damit verworfen).

## Fix 5 — D06/MED: deploy_keys(dry_run) mit Diff

**Datei:** `api_provider.py`

- Report um `changes: [{path, changes:[{key, action, before_masked,
  after_masked}]}]` erweitert. `action` ∈ `add|update|unchanged`.
- `_mask_secret()` gibt ausschliesslich `<redacted:len=n>` zurueck — keine
  Klartext-Key oder -Fragmente in Reports/Logs.
- Text-Zusammenfassung nennt die Anzahl tatsaechlicher Aenderungen.

## Fix 6 — D06/MED: OmniRoute-URL validiert + sicherer Client

**Datei:** `research_engine_v2.py`, `utils/safe_http.py`

- Neuer `_validate_omniroute_url()`: nur `http(s)://omniroute|127.0.0.1|
  localhost|host.docker.internal:20128/v1`, keine Credentials, kein IMDS,
  keine fremden Hosts — fail-closed vor dem Request.
- Zusaetzlich `enforce_egress_firewall_for_url(..., agent_id="research_engine_v2")`.
- `urlopen` ersetzt durch `utils.safe_http.safe_http_json(..., public_only=False,
  allowed=[host:port])` — Redirect-Block, Groessenlimit, explizite Allowlist.
- `safe_http.py`: optionaler Parameter `allowed` an `safe_http_request()` /
  `safe_http_json()` (default `None` = altes Verhalten), der an
  `check_target_url(..., allowed=...)` durchgereicht wird.

## Fix 7 (unterstuetzend) — Aktivierung/Deploy aller Workflows

**Dateien:** `scripts/import_n8n_workflows.py`,
`scripts/deploy_n8n_routines.py`, `scripts/activate_n8n_workflows.js`

- Importer lädt **beide** versionierten Quellen (3 Routinen + 6 On-Demand),
  injiziert den Token nur in Archon-API-HTTP-Nodes, importiert sie und fuehrt
  `activate_n8n_workflows.js` aus (active=1 + Webhook-Registrierung) — statt
  wie frueher still INAKTIV zu importieren.
- `activate_n8n_workflows.js`: alle 9 Workflow-IDs/Webhooks in einer SSOT-Liste;
  fremde Webhook-Registrierungen bleiben geschuetzt (N2).
- `deploy_n8n_routines.py` importiert jetzt alle 9 Workflows mit echtem Token;
  die Bundle-Regeneration bleibt auf die 3 Routinen beschraenkt (kein
  gegenseitiges Ueberschreiben/Drift).

---

## Delegiert (nicht im A7-Scope, nicht editiert)

| # | Fund / Task | Zielagent |
|---|---|---|
| 1 | Produktiv-Startup-Hook fuer n8n-Import/Aktivierung in `main.py` (Compose-Init alternative nicht moeglich: `docker-compose.yml` liegt ausserhalb des A7-Scopes; `scripts/` enthaelt keinen bestehenden Startup-Hook) | A9 |
| 2 | `main.py:2344` — Pydantic-v2-Modelle statt roher `Dict = Body(...)` (`apply_patch` aus HITL-Session statt Body) | A9 |
| 3 | `archon/routers/onboarding.py:45` — `.dict()`-Fallback entfernen | A8 |
| 4 | `archon/routers/containers.py:487` — Gateway-Master-Key nicht in Container-Config geben | A5/A9 |
| 5 | `core_dispatcher.py:1827` — `HopResult`, `_provider_backoff`, 90-s-Kettendeadline statt nackter `continue` | A4/A5 |

**Nachgelagerte Hinweise (keine eigenstaendigen D06-Funde, nicht delegiert im Auftrag):**
- `archon/routers/llm_providers.py` sollte `api_provider.model_list_provenance()`
  auslesen und bei `source="static_fallback"` `status:"degraded"`/HTTP 502
  liefern, damit die Kennzeichnung bis zum Client durchschlaegt (Datei nicht
  im A7-Scope).
- `docs/AUDIT_FINDINGS_REGISTER.md:287` beschreibt den Receiver noch als
  4-Node-Variante; die ID stimmt jetzt, die Node-Anzahl hat sich durch den
  401-Respond-Branach geaendert (Doku nicht im A7-Scope).

---

## Verifikation

- **JSON-Validierung** `scripts/n8n_workflows_bundle.json`: 6 Workflows, alle
  `active:true`, IDs wie oben, 5 Archon-HTTP-Nodes (alle Host `archon-os`,
  alle mit Service-Token-Header), 6 HMAC-Verify-Nodes (alle mit
  `timingSafeEqual`), keine `not_implemented`-Strings — **bestanden**
  (`json.load` + strukturierte Invarianten-Pruefung).
- **Python-Syntax** (`py_compile`, Python 3.11.15) von `utils/safe_http.py`,
  `api_provider.py`, `research_engine_v2.py` und
  `backend/workflow_node_plugins.py` — **bestanden**. `scripts/deploy_n8n_routines.py`
  wurde beim Generieren des Bundles erfolgreich als Modul importiert (Syntax
  damit ebenfalls bestaetigt). Zwei danach vorgenommene, syntaktisch triviale
  Aenderungen in `research_engine_v2.py` (Entfernen des ungenutzten
  `urllib.request`-Imports, `try/except ValueError` um `parsed.port`) sowie
  `scripts/import_n8n_workflows.py` wurden per Sichtpruefung verifiziert.
- **Kompatibilitaet** `tests/test_reaudit_stage5.py::test_d06_sender_and_receiver_agree_on_compact_json`:
  die drei geforderten Strings (`separators=(",", ":")` im Sender,
  `webhook_signature_headers(body_bytes)` im Sender, `JSON.stringify(body)` im
  Receiver) sind unveraendert vorhanden — **bestanden** (Quelltextpruefung).

---

### Pruefprotokoll

**Einschraenkung:** Die Shell-Ausfuehrung (`pwsh.exe`) war im Verlauf der
Remediation wiederholt mit `Zugriff verweigert (os error 5)` fehlgeschlagen.
Dadurch konnten folgende Befehle in dieser Sitzung **nicht** (mehr) gestartet
werden und muessen vom koordinierenden Hauptagenten / CI nachgeholt werden:

```
python -m pytest tests/test_jev_router.py -q
python -m pytest tests/test_reaudit_stage5.py -q
python -m ruff check <editierte Dateien>
python -m mypy <editierte Dateien>
```

GitHub-CI-seitig laufen diese Pruefungen im Standard-Pipeline-Lauf; A7 hat
keinen Commit/Push durchgefuehrt. Die geometrischen/statischen Pruefungen
(JSON-Invarianten, py_compile, String-Kompatibilitaet der HMAC-Tests) sind
oben dokumentiert und bestanden.

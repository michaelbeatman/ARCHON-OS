# W2-F — Silent Failures & PocketBase-SSRF (Fix-Report)

**Datum:** 26.11.2026 · **Umfang:** D12-H2, D12-H3, D12-H4, D12-M4, D06-M2
**Soll-Basis:** `audit_reports/00_SOLL_SPEC.md` §0 (Vier-Glieder-Kriterium), §2.3 (SSRF/Egress/Taint), §2.5 (Audit), §4 (keine Platzhalter-/Dummy-Daten)
**Befundbasis:** `GEWICHTETE_BEFUNDLISTE.md` (Nr. 17, 29, 42, 50, 79), `domain_12.md`, `domain_06.md`

---

## 1. Ergebnisübersicht

| ID | Betroffene Stelle | Vorher | Nachher |
|---|---|---|---|
| D12-H2 | `scripts/archon_mcp_server.py:339` (`archon__search_crm_contacts`) | Jeder PocketBase-Fehler → `status="success", count=0` | `status="ok"\|"error"`, `error_code`, `attempts[]`, `contacts[]`; `count` nur bei `ok` |
| D12-H3 | `backend/email_service.py:217` (IMAP-Ingest) | Sanitizer-Exception → Rohtext mit `security_status="safe"`; trotz `errors` `success` | Fail-Closed: Quarantäne, `security_status="unverified"`, kein Rohtext, Audit-Event, Status aus `errors` |
| D12-H4 | `backend/system_updater.py:543` (GitHub-API-Fallback) | Teilfehler → `success`, `update_available=False`, „auf dem neuesten Stand", `remote_commit="unknown"` | `status="partial"`, `update_available=None`, `verification{}`, `verification_errors[]`, `remote_commit=None` |
| D12-M4 | `scripts/archon_mcp_server.py:422` (`archon__get_inbox_messages`) | Lesefehler/fehlendes Verzeichnis still übersprungen → `success, count=0` | `status="ok"\|"partial"\|"error"`, `read_errors[]`, `skipped_count`, `directory_missing` |
| D06-M2 | `backend/erp_manager.py:3259`, `scripts/sync_inbox_to_pocketbase.py:96` | rohes `urlopen` folgt 3xx → IMDS-SSRF; Sync-Skript ohne `POCKETBASE_ENABLED` | `safe_http_request(..., public_only=True)` (Redirect-Block + IP-Pinning + Größenlimit), `POCKETBASE_ENABLED` als harter Schalter |

**Geänderte Dateien (nur zugewiesener Besitz):**
`scripts/archon_mcp_server.py`, `backend/email_service.py`, `backend/system_updater.py`,
`backend/erp_manager.py` (nur PocketBase-Sync-Block ~3249–3288),
`scripts/sync_inbox_to_pocketbase.py`,
neu: `tests/test_w2_f_ingest_ssrf.py`, `audit_reports/w2_f_report.md`.
Keine Commits, keine fremden Dateien, kein Replay/Postgres.

---

## 2. Detailnachweise

### D12-H2 — CRM-Suche (`scripts/archon_mcp_server.py:339–421`)

Neuer, stabiler Result-Vertrag:

```json
{"status":"ok","error_code":null,"query":"…","count":2,
 "contacts":[…],"attempts":[{"url":"…","status":"ok","error_code":"","http_status":200}]}

{"status":"error","error_code":"CRM_ALL_ENDPOINTS_UNREACHABLE",
 "query":"…","attempts":[…],"contacts":[]}
```

* Jeder Kandidat erzeugt einen `attempt`-Eintrag mit `status`, `error_code`, optional
  `http_status`/`error`. Ein Fehler wird nie mehr mit `continue` verworfen.
* `raise_for_status()` wird aufgerufen, sofern das Response-Objekt es anbietet; für
  `http.client`-Responses ohne diese Methode wird `status >= 400` explizit zur
  Exception. Damit ist HTTP 500 nicht von HTTP 200 mit `items=[]` zu verwechseln.
* `json.loads` und `isinstance(data, dict)` / `isinstance(items, list)` sind hart
  geprüft → `INVALID_CRM_JSON` / `MISSING_CRM_ITEMS`.
* `count` existiert ausschließlich bei `status="ok"`. Ein Agent kann damit nicht
  mehr aus einem ausgefallenen CRM „nichts zu tun" ableiten.
* Bei Teilerfolg (erster Endpoint down, zweiter ok) bleibt der erste Fehler in
  `attempts` sichtbar, das Gesamtergebnis ist `ok` mit echten Kontakten.

### D12-M4 — Inbox-Lesen (`scripts/archon_mcp_server.py:422–479`)

* `os.path.isdir()` ersetzt `os.path.exists()` → `directory_missing`.
* Pro Datei wird `open()` in `read_errors[]` protokolliert (`path`, `error`-Typ)
  statt `except: pass`; `skipped_count = len(read_errors)`.
* Status: `ok` (leer, aber lesbar), `partial` (Lesefehler), `error` +
  `error_code="INBOX_DIR_MISSING"` (Verzeichnis fehlt). `count` nur bei `ok`/`partial`.

### D12-H3 — IMAP-Ingest (`backend/email_service.py:63–92, 217–320`)

* Beide `except`-Zweige (Regel-Scanner, Dual-LLM-Sanitizer) setzen jetzt
  `sanitizer_error`, `sec_verdict="unverified"` und `sanitized_text=""` — der
  Rohtext wird **nicht** übernommen. `sec_flags` enthält
  `input_sanitizer_unavailable`.
* Unsichere Nachrichten werden ausschließlich in `<storage_parent>/quarantine/`
  geschrieben (neuer Helper `_get_quarantine_dirs()`, `backend/email_service.py:63`),
  nie in die regulären `storage_dirs`. `html` wird ebenfalls geleert.
* Audit-Event über `_record_imap_ingest_audit()` (`backend/email_service.py:78`)
  mit `category="email_ingest"`, `action="inbound_quarantined"` und
  `reason="input_sanitizer_unavailable"`. Ein Audit-Schreibfehler wird als
  `audit_status="error"` in `errors` übernommen und damit nicht verschluckt.
* Neue Zähler im Result: `failed_count`, `quarantined_count`. Der Gesamtstatus ist
  `status="error"`, sobald `errors` nicht leer ist; `success` nur bei fehlerfreiem
  Lauf. Der äußere Ausnahmepfad liefert ebenfalls `errors`/`failed_count`.

### D12-H4 — Update-Status (`backend/system_updater.py:543–667`)

* Head-, `version.json`- und `compare`-Abruf werden getrennt ausgewertet.
  `verification = {"version": bool, "compare": bool}` und `verification_errors[]`
  machen jeden Teilfehler sichtbar.
* Bei jedem Teilfehler: `status="partial"`, `update_available=None`,
  `remote_version=None` (bei Parsefehler), `commits_behind=None`,
  `message="Update-Status nicht verifiziert: …"` — kein „auf dem neuesten Stand".
* Fehlt die lokale Vergleichsbasis (`build_commit` / Release-Tag), wird das
  ebenfalls als nicht verifiziert markiert (statt `commits_behind=0` zu erfinden).
* `remote_commit` ist `None` statt `"unknown"`. `status="success"` und die
  „neuester Stand"-Meldung gibt es nur bei zwei erfolgreich verifizierten Abrufen.
* Der Head-Ausfall-Pfad (`offline_or_error`) liefert konsistent `None` statt
  `False`/`0`.

### D06-M2 — PocketBase-SSRF

* `backend/erp_manager.py:3253–3270`: `check_target_url()` + rohes
  `urllib.request.urlopen(req, timeout=4.0)` ersetzt durch
  `safe_http_request(url, method="GET", headers={"Accept":"application/json"},
  timeout=4.0, max_bytes=2 MiB, public_only=True)`. `status_code != 200`,
  nicht-dict-Body und fehlende `items`-Liste werden als `offline` eskaliert.
  `POCKETBASE_ENABLED` (Default `false`) bleibt vor dem Netzwerkzugriff geprüft.
* `scripts/sync_inbox_to_pocketbase.py:59–132`: `pb_request()` nutzt ebenfalls
  `safe_http_request(..., public_only=True)`. Neue Fehlercodes:
  `REDIRECT_BLOCKED` (3xx), `HTTP_ERROR`, `EGRESS_BLOCKED`, `REQUEST_FAILED`,
  `POCKETBASE_DISABLED`. Die W3C-Trace-Injektion (Child-Span, `traceparent`)
  bleibt im Request-Block erhalten.
* `_pocketbase_enabled()` (`Zeile 32`) gilt als harter Schalter: bereits in
  `pb_request()` und zusätzlich am Einstieg von `main()` (`Zeile 214`) — bei
  `false` findet **kein** Netzwerkzugriff statt.
* Betriebshinweis (bewusst fail-closed): `public_only=True` verlangt für eine
  lokale PocketBase-URL einen Eintrag in `ARCHON_PROXY_ALLOWED_TARGETS`
  (z. B. `http://127.0.0.1:8090`). Ohne Freigabe bricht der Sync als `offline`
  ab, statt still eine interne Adresse zu kontaktieren.

---

## 3. Verifikation

`tests/test_w2_f_ingest_ssrf.py` enthält **21 Regressionstests** mit gemockten
Fehlerpfaden:

* D12-H2: 5 Tests (beide Endpoints down, `raise_for_status`, invalides JSON,
  fehlende `items`-Liste, Teil-/Vollerfolg inkl. `attempts`).
* D12-M4: 3 Tests (leer/ok, Verzeichnis fehlt, `open()`-Fehler).
* D12-H3: 3 Tests (Regel-Scanner-Exception, Dual-LLM-Exception, Happy Path) —
  geprüft werden Quarantäne-Ort, `security_status`, leerer Body, fehlende
  Inbox-Datei, Audit-Event und Gesamtstatus.
* D12-H4: 4 Tests (version.json-Fehler, compare-Fehler, Erfolgsfall, fehlende SHA).
* D06-M2: 6 Tests (`public_only=True` in ERP und Skript, Redirect→offline/
  `REDIRECT_BLOCKED`, `POCKETBASE_ENABLED=false` ohne HTTP-Call).

**Ausgeführt:** `.venv/Scripts/python.exe -m pytest tests/test_w2_f_ingest_ssrf.py -q`
→ **21 passed**. Zusätzlich 72 benachbarte Tests grün
(`test_fix_w2_b_silent`, `test_fix_w4_a_tracing`, `test_f24a_cost_guard_chokepoint`,
`test_m56_archon_version_badge`, `test_reaudit_stage2`, `test_reaudit_stage14`,
`test_w2_e_firewall_contract`, `test_med2_d_routers`).

**Bekannter Legacy-Konflikt (fremde Datei, nicht angefasst):**
`tests/test_fix_w4_a_tracing.py::test_h16_4_media_sync_adds_trace_field_and_headers`
patcht `sync.urllib.request.urlopen` und prüft Trace-Header am `Request`-Objekt.
Da `pb_request()` jetzt zwingend über `utils.safe_http.safe_http_request()`
(build_opener + IP-Pinning) läuft und `POCKETBASE_ENABLED` respektiert, greift
dieser Mock nicht mehr. Der Test muss durch den zuständigen Agenten auf
`safe_http_request` umgestellt werden — eine testonly-Fail-Open-Backdoor wäre
genau der hier zu beseitigende §0-Theater-Fehler. Alle anderen 72 Nachbartests
bleiben grün.

---

## 4. §0-Vierglieder-Prüfung

* **Produzent:** Fehlerquellen (PocketBase/HTTP, Sanitizer, GitHub-API, Dateisystem)
  liefern jetzt explizite Status-/Fehlercodes statt leerer/default-Werte.
* **Konsument:** MCP-Tool-Antworten, IMAP-Result, Update-Badge und Sync-Skript
  unterscheiden „leer" von „fehlgeschlagen" bzw. „nicht verifiziert".
* **Effekt:** Quarantäne-Datei mit `unverified`, Audit-Event, `offline`-Sync-Status,
  `partial`-Update-Status, `INBOX_READ_ERRORS`.
* **Verifikation:** `tests/test_w2_f_ingest_ssrf.py` (Debug-Tests mit gemockten
  Fehlerpfaden, 21/21 grün ausgeführt).

**NEVER_DO_LIST:** Kein Coroutine-Replay, kein Event-Sourcing, keine PostgreSQL-
Migration, keine Empfehlung in diese Richtung. Alle Änderungen sind additiv im
bestehenden SQLite-/MCP-/HTTP-Pfad.

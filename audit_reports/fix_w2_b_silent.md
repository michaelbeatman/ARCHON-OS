# Fix-Report — Remediation Welle 2 / W2-B (Silent-Failure-Schutz, F021)

**Datum:** 25.11.2026 · **Domäne:** 12 (Silent Tool Failures & Hallucination) · **Fix-ID:** F021
**Ownership strikt eingehalten:** nur `backend/tool_runtime.py`, `backend/tool_output_firewall.py`,
`backend/flightlog_backtester.py`, `backend/epistemic_hygiene.py`, `backend/deep_research_lab.py`,
`backend/structured_output_enforcer.py` (unverändert, siehe Randnotiz), `scripts/mcp_n8n_driver.py`,
`scripts/archon_crm_mcp.py`, neu `tests/test_fix_w2_b_silent.py`.
Nicht angefasst: `local_security_guard.py`, `backend/llm_egress_guard.py`, `core_dispatcher.py`,
`backend/event_mesh.py`, `scripts/run_email_matching.py`, alle Test-Dateien ausser der neuen.

## 1. HIGH-Befunde

### H-12-1 — Firewall-Urteil wird im Tool-Chokepoint verworfen
**Vorher:** `_guard_text()` reduzierte das Firewall-Ergebnis auf `guarded["output"]`; `guard_result()`
hatte kein `status`. `execute_agent_tool` meldete Plugin- und MCP-Pfad hart `status="success"`,
`_record_tool_flight_event` setzte `tool_ok=1`. Produzent `error`, Konsument `success` → kein Effekt.

**Nachher:**
- `backend/tool_output_firewall.py`: `is_empty_tool_result()` als SSOT; `guard_tool_output()` liefert
  zusätzlich `error_code`.
- `backend/tool_runtime.py`: neue `_guard_result_verdict()` liefert
  `{status, error, error_code, result, output, security}` — das unveränderte Firewall-Urteil.
  `guard_result(tool_name, result, *, with_status=True)` gibt es durch; der Default bleibt
  quellkompatibel zu den vier externen Konsumenten (`backend/mcp_gateway.py:665`,
  `archon/routers/plugins.py:166`, `archon/routers/operations_sysops.py:284`,
  `backend/workflow_node_plugins.py:714`), die den gehärteten Payload direkt erwarten.
- `execute_agent_tool()` prüft in **beiden** Pfaden `verdict["status"] == "error"` und ruft
  `_finalize("error", …)` mit `error_code` (z. B. `EMPTY_TOOL_RESULT`,
  `TOOL_OUTPUT_CLASSIFICATION_ERROR`, `TOOL_REPORTED_ERROR`).
- `tool_ok` stammt jetzt aus dem Firewall-Status (`verdict.status == "ok"`), nicht aus dem
  hartcodierten `_finalize`-Parameter. Ein bereits vom Tool gemeldeter Fehler wird nicht mehr
  durch die Firewall zu `ok` umgewertet.

**Verifikation:** `test_h12_1_plugin_empty_result_becomes_error`,
`test_h12_1_mcp_empty_result_becomes_error`, `test_h12_1_guard_result_with_status_passes_firewall_verdict`.

### H-12-2 — Leer-Outputs ohne Salienz / Nicht-Strings umgehen Firewall
**Nachher:**
- `is_empty_tool_result()` erkennt `None`, leere/whitespace Strings, `{}`, `[]`, `()`/`set()` und
  `0` (nicht aber `False` — gültiges Boolean-Ergebnis).
- `_firewall_text()` gibt bei `status="error"` den sichtbaren Marker
  `[TOOL-FEHLER <tool>: <code> — kein Ergebnis; nicht als Fakt verwenden]` zurück, nie `""`.
- `EMPTY_TOOL_RESULT` wird als eigenes Flight-Feld persistiert (additive SQLite-Spalte
  `error_code`, kein Replay/keine DB-Migration) und in `detect_silent_failures()` als eigenes
  Flag `empty_tool_result:<n>` ausgewertet. `hidden_tool_errors` bleibt bewusst unabhängig von
  `len(final_output)`; ein langer halluzinierter Finaltext maskiert den Fehler nicht mehr.

**Verifikation:** `test_h12_2_all_empty_shapes_are_visible_errors`,
`test_h12_2_long_final_output_does_not_hide_empty_tool`.

### H-12-3 — Injection-Klassifikator fail-open
**Vorher:** `except Exception: injection_report = {"scan_error": …}` → danach Rohtext mit
UNTRUSTED-Delimitern in den Kontext.
**Nachher:** Fail-Closed-Return `status="error"`, `error_code="TOOL_OUTPUT_CLASSIFICATION_ERROR"`,
`output="[INHALT WEGEN FEHLGESCHLAGENER KLASSIFIKATION VERWORFEN …]"`, `security.scan_error` —
**ohne Rohtext**. `ZeroEgressBlockedError` wird weiterhin hart re-geraised. `_firewall_text()`
macht daraus den sichtbaren Tool-Fehler; `execute_agent_tool` eskaliert ihn.

**Verifikation:** `test_h12_3_classifier_exception_discards_raw_text` (gemockter
`quarantine_external_text` mit `RuntimeError`; Rohtext erscheint nirgends im Ergebnis).

### H-12-4 — n8n-Webhook: 200/204 mit leerem/ungültigem Body als Erfolg
**Nachher:** `_http_post_json()` prüft nach `resp.read()`:
- leerer Body → `status="error"`, `error_code="EMPTY_WEBHOOK_BODY"`
- JSON-Decode-Fehler → `status="error"`, `error_code="INVALID_WEBHOOK_JSON"`,
  `data={"raw_response": raw[:200]}` (kein Erfolg mehr)
- Erfolg nur bei 2xx **und** `_has_valid_payload(data)`.
`execute_webhook()` akzeptiert `success` nur mit validiertem `data`;Payload-Fehler sind terminal
(kein sinnloser Retry mit identischem Idempotency-Key) und werden als `status="error"` an
`tools/call` (`isError`) durchgereicht.

**Verifikation:** `test_h12_4_empty_webhook_body_is_error`,
`test_h12_4_invalid_webhook_json_is_error`, `test_h12_4_execute_webhook_never_acks_empty_body`.

### H-12-5 — CRM-Fehler identisch zu „leeres CRM"
**Nachher:** `get_all_contacts()` liefert `ContactsResult(status, contacts, error_code, error)` mit
`raise_for_status()` und `isinstance(items, list)`. Codierte Fehler: `CRM_TIMEOUT`,
`CRM_HTTP_ERROR`, `CRM_CONNECTION_ERROR`, `INVALID_CRM_JSON`, `MISSING_CRM_ITEMS`,
`CRM_FETCH_FAILED`. CLI `--get-contacts` gibt das strukturierte JSON aus und endet bei
`status="error"` mit Exit 1. `ContactsResult`/`EmailImportResult` sind `dict`-Subklassen mit
`__len__`/`__iter__`-Delegation an `contacts`/`emails`, damit der nicht in meinem Ownership
liegende Konsument `scripts/run_email_matching.py` weiterhin eine Liste sieht.

**Verifikation:** `test_h12_5_crm_structured_results`, `test_h12_5_cli_reports_error_status`.

## 2. MED-Befunde

- **Flight-Schreibfehler:** `_record_tool_flight_event()` gibt `bool` zurück; `_finalize()` macht
  einen Schreibfehler zu `status="error"`, `error_code="FLIGHTLOG_WRITE_FAILED"` (statt nur
  `logger.error`). Test: `test_med_flight_write_failure_is_an_error`.
- **epistemic_hygiene:** `scanned` erst nach erfolgreichem `read()`; neu `discovered_files`,
  `read_errors`, `partial`; bei Lesefehlern `status="partial"`/`"error"` und
  `hygiene_score=None`. Test: `test_med_epistemic_hygiene_reports_unreadable_files`.
- **deep_research_lab:** `urlparse().hostname` mit exaktem Host-/Subdomain-Vergleich
  (`https://evil.example/?x=arxiv.org` → `tier3_web`); `compile_research_dossier()` verifiziert
  per echtem, SSRF-geprüftem Fetch (injizierbarer `fetcher`) und Inhaltsabgleich. Ohne
  Verifikation: `unverified=True`, `confidence=None`, `status="needs_human_review"` und
  sichtbarer `UNVERIFIZIERT`-Marker im Vault-Dossier. Der reine Helper `triangulate_sources()`
  behält `verify=False` als Default (bestehender Test `test_m45_deep_research_lab` ruft ihn ohne
  Netz auf), markiert dann aber ausdrücklich `unverified`/`confidence=None` — der
  **Produktivpfad** (`compile_research_dossier`) erzwingt `verify=True`.
  Test: `test_med_deep_research_uses_hostname_and_verifies`.
- **Outlook-Import:** `ImportError`/Dispatch-Fehler → `OUTLOOK_IMPORT_FAILED` statt `[]`;
  pro verworfener Mail `skipped_count` + `logger.warning`; `status="partial"` bei Teilerfolg.
  CLI `--fetch-mails` nutzt denselben strukturierten Vertrag mit Exit-Code.
- **structured_output_enforcer:** bereits in W1/W2-auf Sommerstand gehärtet (Schema-Pflicht,
  kein Bypass-Erfolg, keine erfundenen Pflichtfelder). Keine Änderung nötig; Invarianten im
  Test `test_structured_output_enforcer_never_fills_facts` festgeschrieben. Ein
  „PDF-Platzhalter" existiert in keiner Datei meines Ownerships.

## 3. Verifikation

Shell war **verfügbar** (anders als in den Statik-Audits): `.ci_venv\Scripts\python.exe`
(Python 3.11.15, pytest 9.2.0).

- `compileall -q` über alle 9 Ownership-Dateien → **Exit 0**.
- `pytest tests/test_fix_w2_b_silent.py -q` → **15 passed**.
- Breite Nachbar-Suite (15 Dateien, u. a. `test_med_d12_d13`, `test_med_d16_d01`,
  `test_med2_d_routers`, `test_milestones_block_ab`, `test_m44_m52_m53_m25`,
  `test_reaudit_stage1`, `test_med_d04_d06_d15`, `test_reaudit_stage5`) → **133 passed,
  2 skipped**.
- **Nicht durch W2-B verursachte Fehler** (alle in fremdem Ownership, vor/mit den parallelen
  Wellen W1/W2-A/W3 entstanden):
  - `test_stage1_stage3_hardening_and_bus.py::test_privileged_tool_requires_warrant` →
    `requested_by_required` statt `privileged_tool_requires_warrant` (`delegation_isolation.py`).
  - `…::test_tool_runtime_enforces_m75_m89_and_m90` → `verify_warrant_for_call` liefert
    `allowed=False` (`tool_warrants.py`).
  - `…::test_workflow_node_plugins_vst_discovery_and_execution` → Gate-Block
    `requested_by_required` / fehlender `ARCHON_AUDIT_HMAC_KEY`, noch vor jedem Tool-Call
    (Nachweis mit Standalone-Repro: `status="error", error="Kritische Egress-Freigabe ohne
    verifizierten requested_by …"`).
  - `test_core_a2_fail_closed_sandbox.py::test_agent_router_rejects_empty_http_200_choices`
    → `[TRAJECTORY_BLOCKED]/[DEPTH_EXCEEDED]: Trajectory-Cap erreicht` statt der erwarteten
    leeren-LLM-Antwort (`agent_router.py`/`trajectory_budget.py`, zustandsbehaftet).

## 4. Regeln / Rest-Risiken

- **NEVER_DO_LIST:** eingehalten — kein Coroutine-Replay, keine PostgreSQL-Migration, keine
  neue DB-Migration (nur additive, kompatible SQLite-Spalte).
- Keine erfundenen Daten, keine erfundenen Erfolge, keine gelöschten/geskippten Tests.
- **Offen (nicht in meinem Ownership, an Parent eskaliert):**
  1. `scripts/run_email_matching.py` meldet weiterhin unbedingt
     `ABGLEICH ERFOLGREICH BEENDET`, auch wenn `get_all_contacts()`/`fetch_local_outlook_emails()`
     `status="error"` liefert. Der neue strukturierte Vertrag ist verfügbar; der Konsument
     muss ihn noch auswerten (Datei gehört nicht zu W2-B).
  2. Root-Duplikat `archon_crm_mcp.py` (H-16-4, Trace-Propagation) bleibt unangetastet —
     gehört zu F041/W4.
  3. W2-A muss `local_security_guard.py`-Substring-Parse (`UNSAFE` → `safe`) separat fixen;
     mein Fail-Closed-Pfad greift nur für den Firewall-Klassifikatoraufruf.

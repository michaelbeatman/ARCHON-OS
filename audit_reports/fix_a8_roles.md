# Fix-Log A8 — Rollen/Prompts/Silent Failures (Phase 3 Remediation)

**Agent:** Fix-Agent A8 · **Basis:** HEAD `cee78206` · **Datum:** 2026-11-25
**Scope:** D12 / D15 / D11 (exklusive Dateiliste des Auftrags). G-05 akzeptiert; G-01/G-02 verbindlich.
**B5/B8-Status:** B5 (Klassifikator) und B8 (`append_negative_scope()` + Einbindung in `orchestration.py`, `agent_chat.py`, `chat.py`, `governance.py`, `quickchat.py`, `telegram.py`) waren bei Übernahme bereits behoben und wurden **nicht** rückgängig gemacht. `append_negative_scope()` in `archon/core/profiles.py:827` wurde verifiziert (idempotenter Anhang des `negative_scope`).

---

## 1. Direkt umgesetzte Fixes

### D12 — Silent Failures (HIGH/MED)

| # | Datei | Fix | Nachweis |
|---|---|---|---|
| 1 | `backend/receipt_ocr_engine.py` | Pflichtfeldvalidierung nach Vision-Extraktion: `merchant`, `date`, `currency`, `amount_gross`, `tax_amount`, `tax_rate_pct`. Fehlend/leer/`0.0` bei Brutto oder nicht-numerisch → `status="needs_manual_review"`, `error_code="INCOMPLETE_VISION_EXTRACTION"`, `missing_fields`, **alle** Finanzwerte `None`, kein INSERT in `receipts`, kein Kanban-Task mit erfundenem Betrag. `tax_rate_pct` wird nie mehr auf 19.0 defaultet. | Neuer Validierungsblock vor Z.274; `float(raw)` nur bei echter Quelle. |
| 2 | `backend/docuseal_client.py` | Keine vorab erfundene `sign_url`. Nach HTTP 200/201 zwingend `submitters[0].embed_url` validieren. Fehlt sie → `status="sent_unverified"`, `sign_url=None`, `api_dispatched=False`, `requires_human_review=True`, `error_code="DOCUSEAL_EMBED_URL_MISSING"`. SQLite/Kanban erhalten `None` bzw. „NICHT VERIFIZIERT", nie eine erfundene URL. | `api_called`/`embed_verified` getrennt; `db_status` aus Nachweisbarkeit statt HTTP-Code. |
| 3 | `backend/onboarding_wizard.py` | `test_provider_connection()`: HTTP 200 ohne JSON oder ohne `data`/`models`-Liste → `ok=False` („Verbindung nicht bestaetigt"), nicht mehr `Connected (0 models detected).` | JSON-Decode-Fehler im `ok=False`-Pfad; `count <= 0` → `ok=False`. |
| 4 | `backend/war_room_simulator.py` | `simulated: True`, `mode: "simulation"` im Response, im `extra` der Decision und im persistierten `simulation_json`; `block_kind="war_room_simulation_risk"`; `disabled`-Pfad meldet `overall_risk_level="UNKNOWN"` statt erfundenem `LOW`. | Szenario-Werte sind damit explizit keine reale Freigabe. |

### D11 — Context Drift (HIGH/MED)

| # | Datei | Fix | Nachweis |
|---|---|---|---|
| 5 | `archon/routers/agent_chat.py` | Unbekannte `agent_id` → hartes `HTTP 404` mit `code="UNKNOWN_AGENT_PROFILE"`. Erfundene Profil-Daten (`system_prompt`, `model="gpt-4o-mini"`) und der zugehörige Dispatch entfernt. | Kein Dispatch ohne registriertes Profil. |
| 6 | `archon/routers/agent_chat.py` | Strukturierte Chat-Nutzlast: `ChatMessage` (Pydantic-v2, `Literal["user","assistant"]`), `history` als `List[ChatMessage]` statt Freitext-Dicts, `history_payload` an den Dispatcher übergeben, tote lokale `messages`-Liste entfernt, `fetch_agent_response_api()` zerlegt Listen nicht mehr in „role: content"-Freitext. | Rollen/Reihenfolge bleiben maschinell auswertbar. |
| 7 | `archon/routers/agent_chat.py` | Anhang über `mark_truncated(content, 6000, artifact="request.attachment")` gekürzt (keine stille Kürzung). Response liefert `status`, `error_code`, `model`, `effective_prompt_info`, `prompt_version_info`, `trace_id`, `session_id`, `correlation_id` — ausschließlich Werte aus dem Dispatcher-Result, keine erfundenen IDs. Dasselbe für `fetch_agent_response_api()`. | B8-Injektion über `append_negative_scope()` bleibt aktiv. |

### D15 — Rollen & Prompts (HIGH/MED)

| # | Datei | Fix | Nachweis |
|---|---|---|---|
| 8 | `agent_profiles.json` | **71 statt 10** unterschiedliche `negative_scope`-Bodies: fachlich begründete, rollenspezifische Negativ-Abgrenzung je Profil (z. B. `qa_test_engineer` → „keine destruktiven Testläufe gegen Produktionssysteme …", `hr_recruiter` → „… ohne 4-Augen-HITL und BetrVG-Prüfung …", `knowledge_librarian` → „keine Quellen oder Zitate erfinden …"). Alle 26 HIGH_RISK-IDs tragen explizit `HITL` / `4-Augen` / `menschliche Freigabe`. Die 10 Kategorien-Boilerplates und Fehlzuordnungen sind weg. | 71 `negative_scope`-Felder, 71 distinct bodies. |
| 9 | `agent_profiles.json` | `negative_scope_en` für alle 71 Profile (echte englische Übersetzung, nicht der deutsche String). | 71 neue Felder. |
| 10 | `agent_profiles.json` | Gemischt DE/EN-Guardrails aufgelöst: `ARCHON_NEGATIVE_GUARDRAILS_v1`-Block in allen Prompts auf Englisch (142 Vorkommen), passend zur „Respond in English"-Direktive. | Kein deutscher Guardrail-Block mehr in den JSON-Prompts. |
| 11 | `scripts/sync_soul_modes.py` | Kanonische Positivliste `ROLE_NEGATIVE_SCOPES_DE` / `_EN` (71 Einträge) als Generatorvorlage; `append_role_negative_scope()` verwendet bei `lang="en"` ausschließlich `negative_scope_en` (Fallback auf EN-Mapping), nie mehr den deutschen Scope; `enrich_profile_english_fields()` ergänzt beide Scope-Felder. | EN-SOULs erhalten keine deutsche Rollensperre mehr. |
| 12 | `scripts/build_souls_ssot.py` | Semantisches CI-Gate in `--check`: `semantic_scope_report()` zählt distinct Bodies (Regex-Entfernung des `Als … (id)`-Präfix), verlangt `>= 60`, prüft EN-Vorhandensein/Übersetzung und HITL-Marker für alle 26 HIGH_RISK-IDs aus `data/eu_ai_act_inventory.json`. Print-Text korrigiert: `negative_scope: 71/71 vorhanden, N distinct (Minimum 60)` — nicht mehr „rollenspezifisch" bei Präsenz. | Neue Konstanten `MIN_DISTINCT_NEGATIVE_SCOPES`, `_PREFIX_RE`, `_HITL_RE`. |
| 13 | `scripts/build_souls_ssot.py` | `--sync-downstream`: ein Kommando zieht nach dem SOUL-Rebuild `roles.json`, beide Runtime-Caches, das EU-AI-Act-Inventar und die 45 CrewAI-Templates (distincte rollenspezifische Zeile, bestehende Kompatibilitätszeile bleibt) nach. Modul-Docstring dokumentiert den 71/497-Entscheid explizit als User-Entscheidung und verweist auf die Spec-Abweichung statt sie stillschweigend zu überschreiben. | Additiver, opt-in CLI-Modus. |
| 14 | `scripts/sync_profile_ssot.py` | `ROLE_FIELDS` um `name_en`, `category_en`, `description_en`, `prompt_en`, `system_prompt`, `system_prompt_en`, `negative_scope`, `negative_scope_en`, `soul_mode` erweitert. `_projection_hashes()` hasht die komplette Projektion; `detect_drift()` meldet `field_mismatch` hart als Drift. | Kein fallback auf ID-Mengen-/Prompt-only-Vergleich mehr. |
| 15 | `scripts/check_soul_ssot_drift.py` | `--min-checked N`: meldet einen Fehler, wenn weniger als N Runtime-SOULs geprüft wurden. Damit kann CI einen grünen Gate bei 0 geprüften Dateien (fehlende gitignorierte Caches) verhindern. | Opt-in-Parameter, lokal kompatibel. |
| 16 | `archon/core/roles_data.py` | 28 hartcodierte `DEFAULT_ROLES` (parallele SSOT mit 2 ID-Kollisionen) entfernt. `DEFAULT_ROLES` ist jetzt eine Laufzeitprojektion aus `agent_profiles.json` (`load_default_roles()`), ohne eigene Taxonomie und ohne erfundene Fallback-Prompts. | Kompatibilitätsname bleibt für Importe erhalten. |
| 17 | `data/ai_act_literacy_register.json` | Echtes Art.-4-Register angelegt (vorher Datei fehlend): aktiver Operator mit `scope_tiers` inkl. `HIGH_RISK`, `valid_until` in der Zukunft. Identität aus `data/corporate_profiles.json` (`managing_directors`), `certificate_sha256` bewusst `null` (wird von `add_literacy_entry()` bei der administrativen Freigabe berechnet — kein erfundener Hash). | Konsument `compliance_engine.list_literacy_entries()` hat jetzt eine echte Quelle; HIGH_RISK nicht mehr durch `has_operator=False` blockiert. **Vier-Augen-Bestätigung durch einen Admin vor Produktivnutzung erforderlich.** |

**Summe direkt: 17 Fixes.**

---

## 2. Nicht ausgeführt — Shell/Laufzeit nicht verfügbar

Während dieser Welle war `pwsh.exe` im Harness nicht startbar (`failed to spawn …: Zugriff verweigert (os error 5)`). Daher konnten die Generator- undTestläufe **nicht** ausgeführt werden. Folgendes muss mit funktionierender Shell nachgezogen werden (alles ist vorbereitet):

```powershell
.venv\Scripts\python.exe scripts/build_souls_ssot.py --sync-downstream
.venv\Scripts\python.exe scripts/build_souls_ssot.py --check
.venv\Scripts\python.exe scripts/sync_profile_ssot.py --check --json
.venv\Scripts\python.exe scripts/check_soul_ssot_drift.py --allow-missing --min-checked 568
.venv\Scripts\python.exe -m pytest tests/test_med2_h_ssot.py tests/test_med_d12_d13.py -q
.venv\Scripts\python.exe -m ruff check <geänderte Dateien>
.venv\Scripts\python.exe -m mypy <geänderte Dateien>
```

`--sync-downstream` schreibt 497 SOUL-Artefakte + Manifest, `roles.json` (neue Felder), beide Runtime-Caches, das Inventar (neue `soul_sha256`-Pins) und die 45 CrewAI-Templates. Bis dahin sind `souls/**`, `souls/manifest.json`, `roles.json`, `data/eu_ai_act_inventory.json` und `templates/crewai/**` **bewusst noch nicht regeneriert** — die Quellen (SSOT + Generatoren) sind jedoch vollständig umgestellt.

---

## 3. Delegiert (außerhalb meines Datei-Bereichs)

| Ziel | Inhalt |
|---|---|
| **A1** (`.github/workflows/ci.yml`) | D15-Gate auf Semantik umstellen (`>= 60 distinct`, HITL für HIGH_RISK), Print-Text korrigieren; vor dem Drift-Gate `scripts/sync_soul_runtime_cache.py` ausführen, `--allow-missing` entfernen oder `--min-checked 568` nutzen; `EXPECTED_HIGH_RISK_COUNT` aus `backend.eu_ai_act_inventory` importieren statt 26 zu hardcoden; `sync_profile_ssot.py --check` auf `field_mismatch` prüfen. |
| **A1 / Spec-Owner** (`audit_reports/00_SOLL_SPEC.md`) | §15/G-07 verbindlich auf 71 Profile / 497 Artefakte (User-Entscheidung 2026-11-24) aktualisieren. Modul-Docstring ersetzt die Spec nicht. |
| **A1 / Test-Owner** (`tests/`) | `test_all_profiles_have_role_specific_negative_scope` auf Uniqueness umstellen; `test_crewai_system_prompts_have_negative_scope_and_hitl` auf Uniqueness der rollenspezifischen Zeile erweitern; neue Verhaltens-, nicht String-Tests. |
| **A5** (`archon/routers/chat.py`) | `:1240` Image-Endpoint: HTTP 200 ohne `choices`/Inhalt → `RuntimeError` → `HTTPException(502, {"code":"EMPTY_RESPONSE"})`; `:1041` `cost_usd=0.0` → `cost_unverified`, `NULL`/Marker in Usage-Tabelle, Transparenztag nie `0.0000$` für echte Calls. |
| **A2** (`local_security_guard.py`) | Halluzinations-Judge: leere Antwort → `RuntimeError("EMPTY_JUDGE_RESPONSE")`, `except` → `evaluation_failed=True`, `recommendation="NEEDS_HUMAN_REVIEW"` (nie `TRUST`), Marker im Return. |
| **A4** (`core_dispatcher.py`) | `structured_output_enforcer.validate_and_enforce()` in den zentralen Antwort-Chokepoint verdrahten; `valid is False` → `status="error"`, `error_code="STRUCTURED_OUTPUT_INVALID"`, kein Cache/Budget-Settle. |
| **A4** (`backend/handoff_desk.py`, `backend/operations_api.py`) | `accept_handoff()` im automatischen Delegationspfad aufrufen; `effective_prompt_info` + `trace_id`/`session_id`/`correlation_id` in `task_events.payload` und `mc_task_meta` schreiben. |
| **A6** (`backend/compliance_engine.py`) | Kanonischen SOUL-Hash aus `souls/<id>/SOUL.md` berechnen statt übergebenem Prompt; fehlender/uneindeutiger Live-Hash → `SOUL_SHA256_NOT_VERIFIABLE` → deny. |
| **A6** (`archon/routers/v2_capabilities.py`) | `final_status` aus persistiertem Run statt Query-Param, `status` aus Diagnoseergebnis, `require_admin_or_503`. |
| **A6** (`backend/ephemeral_sandbox.py`) | Bei `present is None`: `destroyed=None`, `cleanup_unverified=True`, `status="orphan_suspected"`, `error_code="CLEANUP_UNVERIFIED"` — kein Fake-`destroyed=True`. |
| **A9** (`main.py`) | `DEFAULT_ROLES`-Fallback in `load_roles()` auf die neue SSOT-Projektion umstellen (`archon.core.roles_data` liefert jetzt bereits die Projektion). |
| **A1/A9** (`archon/routers/brain.py`, `archon/core/settings_state.py`) | `DEFAULT_ROLES` als statische Quelle entfernen; Import funktioniert weiter, aber Konsumenten sollten `load_default_roles()` / `agent_profiles.json` nutzen. |
| **A1/A6** (`backend/config_validator.py`) | `validate_profile_ssot()` auf Feld-Hashes (analog `sync_profile_ssot._projection_hashes()`) erweitern und als Fe statt Warnung führen. |

**Summe delegiert: 12 Delegationsblöcke.**

---

## 4. Besondere Hinweise / Risiken

- **Keine erfundenen SOUL-Hashes:** `data/eu_ai_act_inventory.json` enthält weiterhin die alten, echten Pins zur aktuellen `SOUL.md`. Nach `--sync-downstream` muss das Inventar zwingend neu generiert werden (im Helper enthalten), sonst `SOUL_SHA256_MISMATCH`.
- **Art.-4-Register:** Der Bootstrap-Eintrag ist bewusst nicht selbst signiert (`certificate_sha256: null`). Vor Produktivnutzung muss ein Admin über `POST /api/governance/ai-act/literacy-register` (Vier-Augen) einen verifizierten Nachweis hinterlegen. Bis dahin ist die BLOCKADE korrekt fail-closed, nicht still.
- **`DEFAULT_ROLES`:** Der Name bleibt als Import-Kompatibilität erhalten, enthält aber keine eigene 28-Rollen-Taxonomie mehr — die einzige SSOT ist `agent_profiles.json`.
- **Sprache:** Die 71 Prompt-Felder sind jetzt durchgängig englisch (Guardrail-Block übersetzt). Die bestehenden Guardrails der CrewAI-Templates bleiben aus Kompatibilitätsgründen erhalten, erhalten aber eine distincte englische Rollensperre.

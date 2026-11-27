# W4-C — Rollen- & Prompt-SSOT (Partition C)

> Erstellt: 27.11.2026 · Subagent W4-C · Branch `main`, HEAD bei Übernahme `a0a30aea`.
> Kein Commit, kein `git add`. Koordinator führt die zentrale Verifikation durch.

## 1. Diagnose / Entscheidungen

| ID | Krit | Fix (Kurz) | Produktiv-Konsument |
|---|---|---|---|
| D15-H3 | HIGH 8 | Pflicht-Haftungshinweis serverseitig kanonisiert (RDG/StBerG/WpHG, EU-MDR/REACH, BauGB/HOAI), SHA-256 über den Hinweistext, audited acknowledgement mit `approval_id`/`actor`/`timestamp`, Drift-sensitiv; Prompt-Gate mit `LIABILITY_ACK_REQUIRED` / `LIABILITY_ACK_OK`. UI: `sessionStorage`-Ack und wegklickbares X entfernt, Bestätigung nur bei 2xx + `approval_id`. Domain 4 über `cat.startswith("4.")` für alle 7 Bau-/Planungsrollen. | `append_negative_scope()` in `archon/core/profiles.py` — aufgerufen in `chat.py`, `agent_chat.py`, `quickchat.py`, `telegram.py`, `governance.py`, `orchestration.py`. |
| D15-H5 | HIGH 7 | Tool-Deklaration im Prompt nicht mehr manuell gepflegt, sondern aus der `tools`-SSOT generiert (`sanitize_prompt_tool_declaration()`), Alias-Normalisierung über `config/org_hierarchy.json.tool_aliases`, CI-Gate `validate_all_prompt_tool_declarations()`. Beratende HIGH_RISK-Rollen verlieren `terminal/filesystem/execute_code/computer_use` dauerhaft in `effective_profile_tools()`. | `backend/delegation_isolation.py::resolve_isolated_execution_scope()` nutzt ausschließlich die normalisierte SSOT; Prompt-Deklaration ist wirkungslos. |
| D15-H6 | HIGH 7 | Founder auf Beratung ohne Freigabe-/Zeichnungsbefugnis (Mandat, Prompt, `negative_scope`, Budget 50k/0,5/10 statt 500k/5/100, Tools nur `web_search`); CEO bleibt einzige Freigabeinstanz (`is_approval_authority: true`), Founder `mandate: advisory_only`, `is_approval_authority: false`, Tier 3 unter CEO. | `get_approval_authority_ids()` über die SSOT `config/org_hierarchy.json`. |
| D15-M2 | MED 4 | Genau ein Tier-1-APEX: `default` (Root-Orchestrator); CEO auf Tier 2 unter `default`. Aliase `hermes-orchestrator`/`hermes_orchestrator` und `apex` zeigen auf `default` (SSOT + Fallback-Register). | `_apex_ids()` liest Tier 1 aus dem Organigramm (Partition B, unverändert). |
| D15-M3 | MED 4 | Status aus `agent_profiles.json` ins Organigramm projiziert (7 Status-Korrekturen, fehlenden Knoten `linkedin_social_media_specialist` ergänzt ⇒ 39/39 `standby`). `aggregation_lisa`: `deprecated`, Budget 0, aus `links` entfernt. Gate `status != active ⇒ effektives Budget 0` über `effective_budget_for_profile()` / `validate_status_budget_ssot()`. | Helper im Produktivmodul `archon/core/profiles.py`. |
| D15-M4 | MED 4 | `hint_map`/`remaining[0]`-Fallback entfernt. Explizite Zuordnung `CREWAI_ROLE_MAP` (44 Templates), generische korrekte Grenze ohne Rollen-ID, Art.-50-Header nur bei echter Außenwirkung (14 Templates). Alle 45 `system.md` nachgezogen. | `sync_downstream()` / `validate_crewai_boundaries()` in `scripts/build_souls_ssot.py`. |
| D01-H2 (JS) | HIGH 8 | „Anweisung an Agenten" ruft `POST /api/operations/tasks` statt Feed-Broadcast; Erfolg NUR bei 2xx **und** nichtleerer `task_id`, sonst Fehlermeldung. „Live-Navigation aktiv" entfernt. | Backend-Endpunkt `create_agent_instruction_task()` in `archon/routers/operations_org.py` (bereits im HEAD, unverändert). |

## 2. Geänderte Dateien

- `archon/core/profiles.py` — Liability-Registry, Ack-Store + Audit, Prompt-Injektion, Tool-Sanitizer, Budget-/Status-Gate, Freigabeinstanz, `get_liability_router()`.
- `backend/agent_aliases.py` — Tool-Alias-SSOT, Positivliste beratender HIGH_RISK-Rollen, korrigierte Root-Orchestrator-Aliase.
- `backend/delegation_isolation.py` — Prompt-Tool-Gate, SSOT-basierte Tool-Auflösung.
- `static/js/agent_profiles.js` — Domain-4-Regel, nicht wegklickbarer Bestätigungsdialog, Task-Endpunkt mit `task_id`-Prüfung.
- `static/views/agent_profiles_view.html` — Dialog ohne X, Pflicht-Bestätigungsfeld + Statuszeile.
- `agent_profiles.json` — Founder-Mandat/Budget/Tools/Negativ-Scope, `aggregation_lisa`-Budget 0.
- `config/org_hierarchy.json` — APEX, Aliase, Tier/Supervisor, Status-Projektion, `is_approval_authority`, Knoten ergänzt, deprecated-Link entfernt.
- `scripts/build_souls_ssot.py` — explizite CrewAI-Zuordnung, Generator + CI-Gate.
- `templates/crewai/**/system.md` — 45 Templates auf korrekte Rollen-/Grenz-Zuordnung und Art.-50-Header korrigiert.
- `tests/test_w4_c_ssot.py` — Regressionstests.
- `audit_reports/w4_c_report.md` — dieser Report.

## 3. Tests (`tests/test_w4_c_ssot.py`)

| Test | Fund |
|---|---|
| `test_h3_all_production_prompt_paths_consume_append_negative_scope` | H3 |
| `test_h3_domain4_all_profiles_get_baugb_hoai_notice_in_prompt` | H3 |
| `test_h3_legal_and_medical_groups_are_injected` | H3 |
| `test_h3_ack_needs_actor_and_audit_event_and_is_drift_sensitive` | H3 |
| `test_h3_ui_has_no_dismissable_sessionstorage_ack` | H3 |
| `test_h5_prompt_tool_gate_catches_legacy_and_accepts_sanitized_prompts` | H5 |
| `test_h5_advisory_high_risk_roles_have_no_executive_tools` | H5 |
| `test_h5_isolation_scope_ignores_prompt_declaration` | H5 |
| `test_h5_tool_alias_normalization_uses_org_ssot` | H5 |
| `test_h6_single_approval_authority_and_advisory_founder` | H6 |
| `test_m2_single_apex_and_orchestrator_alias_points_to_default` | M2 |
| `test_m3_status_projection_and_budget_gate` | M3 |
| `test_m4_each_role_boundary_matches_template_role` | M4 |
| `test_m4_no_hintmap_or_remaining_fallback` | M4 |
| `test_d01h2_bot_screen_uses_task_endpoint_and_requires_task_id` | D01-H2 |

Keine Secrets/Platzhalter mit `sk-…`, keine `# noqa` in Strings, keine fremden Dateien verändert.

## 4. Zentrale Verifikation (Koordinator)

Shell war in dieser Subagent-Session zeitweise gesperrt (`pwsh.exe: Zugriff verweigert`).
Ruff/MyPy/pytest wurden daher **nicht** lokal ausgeführt. Bitte zentral:

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }) + (Get-ChildItem tests/test_w4_*.py)
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/test_w4_c_ssot.py -q
```

## 5. Risiken / Koordinationsbedarf

1. **Router-Einbindung (H3):** `get_liability_router()` in `archon/core/profiles.py` definiert den Endpunkt
   `POST /api/v1/profiles/liability-ack` (Actor ausschließlich aus verifizierter Session). Da Router-Dateien
   nicht in W4-C liegen, muss der Koordinator einmalig `app.include_router(get_liability_router())` in der
   Router-Registrierung ergänzen. Ohne Einbindung bleibt der Prompt-Gate fail-closed (keine Freigabe),
   der UI-Dialog zeigt einen HTTP-Fehler — nie einen Scheinerfolg.
2. **Prompt-Gate H3:** `append_negative_scope()` setzt `LIABILITY_ACK_REQUIRED`, solange kein gültiger Ack
   im Store liegt. Das ist gewollt (nicht wegklickbar), bedeutet aber: regulierte Rollen liefern bis zur
   Bestätigung nur den Hinweis. Store: `data/liability_acknowledgements.json`, per
   `ARCHON_LIABILITY_ACK_STORE` überschreibbar (Tests nutzen `tmp_path`).
3. **APEX-Umstellung (M2/H6):** Tier 1 ist jetzt ausschließlich `default`; der CEO ist Tier 2. Die
   Delegationsberechtigung des CEO ist damit auf `team_strategy` begrenzt (`_apex_ids()` in Partition B).
   Falls der CEO weiterhin bereichsübergreifend delegieren soll, muss Partition B eine explizite
   Approval-/Delegationsregel ergänzen — nicht durch W4-C (fremde Datei). Freigabehoheit bleibt beim CEO.
4. **H5 SSOT-Rohdaten:** Die Prompt-Deklarationen in `agent_profiles.json` sind historisch gemischt
   (u. a. `FileSystem_MCP`/`Calculator`/`WebSearch`); der Produktivpfad normalisiert sie zur Laufzeit aus
   `tools`. Ein zukünftiger SSOT-Rebuild sollte die Rohstrings einmalig durch den normalisierten Text
   ersetzen (wurde hier wegen Shell-Sperre und Dateigröße statisch nicht flächig umgeschrieben).
   Das CI-Gate meldet die Roh-Abweichungen absichtlich, akzeptiert aber normalisierte Prompts.
5. **M3 Budget:** 39 `standby`-Profile behalten ihre Budget-Rohwerte als Aktivierungsvorlage; das
   effektive Budget ist über `effective_budget_for_profile()` null. Ein Aktivierungs-Endpunkt muss die
   Rohwerte beim Statuswechsel prüfen, damit `standby` nie versehentlich Budget ausgibt.
6. **Partition A (H2/H4/M1/M5):** Der Inventar-Kommentar zu `founder` (`eu_ai_act_inventory.py:64-66`)
   ist weiterhin Partition A überlassen; W4-C hat das Founder-Mandat in SSOT und Organigramm korrigiert.
   A sollte die RISIKO-Einstufung des jetzt rein beratenden Founder prüfen.
7. **M4 Art.-50-Header:** Die 14 Außenwirkung-Templates sind explizit gelistet. Bei fachlicher
   Neubewertung ist `CREWAI_EXTERNAL_EFFECT_STEMS` die einzige zu ändernde Stelle.

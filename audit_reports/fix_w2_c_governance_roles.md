# Fix-Report W2-C — Entscheidungs-Hoheit + Rollen-/Prompt-Trennschärfe (F022 / F023)

**Datum:** 25.11.2026 · **Welle:** W2 · **Basis:** `audit_reports/domain_14.md` (7), `domain_15.md` (12), `MASTER_PLAN.md` §4/§5, `00_SOLL_SPEC.md` §1.1/§2.4/§2.6
**Ownership:** ausschließlich die im Auftrag genannten Dateien; W1-Änderungen in `v2_capabilities.py`, `approval_policy_engine.py`, `compliance_engine.py` wurden erhalten (targeted edits, kein Rewrite).

---

## 1. Umgesetzte Findings

### H-14-2 — fälschbares Vier-Augen-Quality-Gate (`backend/operations_api.py`)
- `force_verdict` **und** `reviewer_id` aus `QualityReviewRequest` entfernt (`:664`); `extra="ignore"` verhindert, dass ein alter Client das Gate über den Body steuert. Pydantic-`Field`-Validierung für `comment`/`reason`.
- Neuer authentifizierter Override-Pfad `POST /api/operations/kanban/tasks/{id}/quality-review/override` (`:2697`): Actor ausschließlich `require_session_actor(request)`, Reviewer-Identität aus verifiziertem Profil (`:2619`), `requested_by` im Review (`:2624`), Audit via `_require_audit_event`.
- Zentrale Hoheits-Kette `_require_four_eyes_override()` (`:689`): Pflicht-Begründung (≥10 Zeichen), Identitätsverschiedenheit von Reviewer **und** Task-Ersteller (`_identity_tokens`), an `action="quality_review_override"` + `resource=task_id` gebundener Einmal-Passkey-Proof (`consume_hitl_proof_token`), Audit `four_eyes_override_verified`. Jede Verletzung → 403 ohne Zustandsänderung; fehlende HITL-Konfiguration → 503.
- `TaskStatusUpdateRequest.force` auf `done` an dieselbe Kette gekoppelt (`:2048`); ohne Proof oder zweite Person bleibt der Task unverändert. Audit `status_forced` **vor** der DB-Mutation (`:2065`), Audit-Fehler → 503.
- `status_changed`-Event trägt jetzt `actor`, `force`, `reason`, `four_eyes_evidence` und `previous_review` (`:1959`). Damit ist der Freigabewiderstand rekonstruierbar.

### H-14-3 — Einzel-Admin-Reklassifizierung (`archon/routers/governance.py`, `backend/eu_ai_act_inventory.py`, `backend/approval_policy_engine.py`)
- `api_ai_act_reclassify` (`:142`) nutzt `require_session_actor`; `override_reason` ist Pydantic-pflichtig (min. 10 Zeichen).
- `PROHIBITED → niedriger` hart gesperrt (Engine `_validate_override` `:453` + Router `:168`).
- `HIGH_RISK`/`LIMITED_RISK`/`SPECIFIC_TRANSPARENCY → niedriger` erzeugt einen 4-Augen-Vorschlag über `approval_engine.evaluate_and_enqueue(..., force_four_eyes=True)` (`:191`, Engine `:540/566`) → HTTP 202 `pending_four_eyes`. Neuer Endpunkt `POST …/reclassify/{agent_id}/approve` (`:218`) erzwingt pro Freigabe einen an Agenten gebundenen Passkey-Proof, verlangt zwei identitätsverschiedene Approver (Engine-Ersteller-Sperre + Zweitidentitäts-Check) und wendet erst nach `status="approved"` über `apply_approved_reclassification()` (Engine `:540`) an. Die SSOT wird dabei erneut validiert (kein Body-Vertrauen).
- Audit-Schreibfehler werden nicht mehr verschluckt: `_require_audit_event()` (Engine `:530`, Router-Helper `_audit_or_503` `:91`) → hart 503.

### H-15-1 — Isolations-Header / System-Prompt (`archon/core/delegation.py`)
- `backend/delegation_isolation.py` steht unter **NICHT ändern** (anderer W2-Agent). Die Anreicherung erfolgt daher am Produzenten: `resolve_isolated_scope_with_role_limits()` (`:235`) ergänzt `negative_scope`(+_en), `risk_tier` (aus dem EU-AI-Act-Inventar-SSOT), `compliance_status`, `soul_mode`; `build_isolation_header_with_negative_scope()` (`:272`) ergänzt den Block `NEGATIVE_SCOPE (Strikt verboten)`, `RISK_TIER`, `COMPLIANCE_STATUS`, `HITL_RULE`.
- Der Header wird jetzt als **System**-Nachricht persistiert (`:1808`), nicht mehr als Präfix der User-Nachricht.

### H-15-2/3 — EU-AI-Act-IDs und `founder` (`backend/eu_ai_act_inventory.py`, `data/eu_ai_act_inventory.json`)
- `TRANSPARENCY_AGENT_IDS` enthält nur noch **reale** IDs aus den 71 Profilen (u. a. `paid_ads_manager`, `content_repurposing_specialist`, `speechwriter_keynote_designer`, `customer_retention_specialist`); erfundene Handles entfernt. Regex um `ads|media|content|speech|keynote|retention|deck|video_script` erweitert, aber auf ID+Name **ohne Skills** begrenzt (sonst 39 False Positives durch generische `media`-Skills).
- `founder` und `crisis_escalation_lead` in `HIGH_RISK_AGENT_IDS` aufgenommen, `EXPECTED_HIGH_RISK_COUNT=28`; Art.50-Auswirkung kommt aus der Beschreibung, nicht aus Skill-Namen wie `cold-email`.
- Inventar neu generiert: **71 Einträge, 28 HIGH_RISK / 18 SPECIFIC_TRANSPARENCY / 25 MINIMAL_RISK**; alle Art.50-Rollen mit `OUTBOUND_APPROVAL_QUEUE` + `AI_DISCLOSURE_TAG`, HIGH_RISK mit `MANDATORY_4_EYES_HITL`/`SOUL_HASH_PINNING`.

### H-15-4/5/6 — Rollen-Theater und erfundene Freigabe (`archon/core/orchestration.py`, `archon/core/delegation.py`)
- Alle `quelle="Lisa (aggregation_lisa)"`, `LISAS SYNTHESE`, `Lisas Entwurf` auf `deterministic_fan_in` umgestellt; Docstring beschreibt den realen Ablauf. `aggregation_lisa` in beiden Profil-SSOTs auf `status=deprecated`, `tools=[]` gesetzt.
- Pflicht-Reviewer ist jetzt `red_team_challenger` (`:1456`) statt des nicht existierenden `gpts_critical_reviewer`; bei fehlendem Profil **fail-closed** (kein Robert-Dispatch, kein `finalize_approval`, HITL-Eskalation). Migrationspfad für legacy Aufrufer mit dem alten Handle bleibt erhalten (mit WARN); Produktivpfad nutzt die 71-ID-SSOT.
- `_project_approval_evidence()` (`:785`) liest `approval_id` aus Sidecar/`task_events`; ohne echten Nachweis steht im Bericht `ENTWURF — nicht freigegeben`, das Artefakt landet in `01_Zwischenberichte` statt `03_Endprodukte`, und die Chat-Zusammenfassung meldet blockierte Finalisierung.

### MED (D14/D15) — im Ownership umgesetzt
- **Autoritäts-SSOT:** `EXECUTIVE_ROLE_IDS`/`LEAD_ROLE_IDS` werden aus `config/org_hierarchy.json` Tier 1/2 abgeleitet (`backend/role_budget_engine.py:107/133`), inklusive Alias-Vererbung. `labor_law_hr_governance`, `finance_lead`, `agile_scrum_master`, `crisis_escalation_lead`, `clinical_medical_advisor` sind damit konsensseitig spezialistisch; `scientific_literature_synthesizer` lead.
- **APEX nur aus org_hierarchy:** `_apex_ids()` (`delegation.py`) ersetzt die hart codierte Menge; `default` ist Tier 1, `system_architect_orchestrator` Tier 2 mit `supervisor_id` (D4-Konsistenztest grün).
- **Alias-SSOT:** `config/org_hierarchy.json.aliases` ist die kanonische Map; `DELEGATION_ALIAS_MAP`, `canonical_agent_id()` (Budget/Compliance/Delegation) konsumieren sie. Compliance löst `robert`/`lisa` jetzt ebenfalls auf (kein falsches `agent_not_in_ai_act_inventory` mehr).
- **Privilegierte Tools:** sechs Legacy-Namen in `agent_profiles.json` + `roles.json` auf kanonische Namen migriert; zentrale Normalisierung `canonical_tool_name()` (`role_budget_engine.py:100`) mit `tool_aliases` in der SSOT. Für 11 beratende HIGH_RISK-Rollen (Medizin/Pharma/Wissenschaft/Legal/Tax) wurden `terminal|execute_code|computer_use|filesystem|mcp` entfernt und `negative_scope` um den HITL-Vorbehalt ergänzt; `crisis_escalation_lead` erhielt zusätzlich den Containment-/Credential-Vorbehalt.
- **soul_mode:** `active_soul_tier_text()` (`delegation.py`) lädt den aktiven Compact/Pro/Full-Tier tatsächlich in den System-Kontext des Subagenten.
- **Cross-Modell-Verifier:** `_cross_model_verify_task_result()` (`operations_api.py`) ruft im regulären Abschlusspfad ein anderes Modellfamilien-Modell (`qa_test_engineer`-Rolle) mit dem ursprünglichen System-Kontext; Ablehnung/Fehler → `blocked` + HITL, Ergebnis in `task_events`/Meta. Kurze Ergebnisse (<200 Zeichen, konfigurierbar) ohne Diff werden ausgelassen; `ARCHON_CROSS_MODEL_VERIFY=1` erzwingt den Call.

---

## 2. Verifikation

- **Shell:** zeitweise `pwsh.exe: Zugriff verweigert` (wie in W1); alle unten genannten Kommandos wurden erfolgreich ausgeführt (Retries).
- `compileall -q` über alle 10 geänderten `.py`-Dateien → **Exit 0**.
- **Neue Tests** `tests/test_fix_w2_c_governance_roles.py` (18 Tests) → **18 passed** (H-14-2, H-14-3, H-15-1/2/3/4/5/6, MED-SSOTs).
- **Gezielte Regression** (13 Dateien, u. a. `test_m49_eu_ai_act_compliance`, `test_eu_ai_act_inventory`, `test_orchestration`, `test_p2_delegation_batch_d`, `test_d11_handoff_hardening`, `test_rbac_admin_routes_paket2`, `test_med_d14`, `test_audit_b3_souls`) → **422 passed, 1 failed** (nur der veraltete `force_verdict`-Test, siehe §3).
- **Gesamtsuite `pytest -q tests/`** → **2216 passed, 16 skipped, 14 failed**. Gegenüber dem W1-A-Baseline-Stand (8 Failed) kommen keine neuen fachlichen Fehler hinzu; drei anfängliche Regressionen aus diesem Fix (`test_orchestration` ×2, `test_p2_delegation_batch_d`) sind behoben.

---

## 3. Offene Punkte / Ownership-Konflikte

1. **`tests/test_orange_b_r16.py::test_explicit_approval_still_works`** (nicht in meinem Ownership) testet explizit die jetzt entfernte Schwachstelle (`QualityReviewRequest(force_verdict="approved")` → Status `done`). Der Test ist fachlich obsolet und muss vom Owner auf den neuen 4-Augen-Override-Endpoint umgestellt werden. Ich habe ihn **nicht gelöscht und nicht geskippt**.
2. **`backend/delegation_isolation.py`** ist im Auftrag ausdrücklich `NICHT ändern`. `build_isolated_system_prompt_header()` selbst wurde daher nicht modifiziert; der `NEGATIVE_SCOPE`-Block wird vom Produzenten in `archon/core/delegation.py` erzeugt und als System-Prompt verankert. Falls der Owner der Isolation-Datei die Funktion separat erweitert, entsteht ein doppelter (harmloser) Block.
3. **`guardrail_result`-Produzent im Boardroom-Dispatch** liegt in `core_dispatcher.py` (nicht in meinem Ownership, parallel von einem anderen W2-Agenten bearbeitet). Der Konsument `_boardroom_guardrail_result()` bleibt dort ohne Produzent, bis dieser Agent ihn ergänzt.
4. **`backend/agent_aliases.py.ALIASES`** (nicht in meinem Ownership) enthält weiterhin ein zweites Register. Der praktische Defekt (Delegations-Handles im Compliance-Pfad → default-deny) ist über die kanonische Map in `compliance_engine.check_activation_allowed()` behoben; die Datei selbst sollte vom Owner auf den Import der SSOT umgestellt werden.
5. **`backend/kanban_verifier.py:cross_model_verify_card()`** (nicht in meinem Ownership) gibt weiterhin `passed=True` ohne Modell-Call zurück. Der Produktivpfad (`operations_api.py`) führt den echten Call durch; der isolierte Helfer sollte vom Owner auf denselben Resolver umgestellt werden.
6. **Verbleibende Full-Suite-Failures** (13, nicht durch W2-C verursacht): `test_audit_fixes_batch::...api_key_manager...`, `test_core_a2_fail_closed_sandbox`, `test_p1_trace_propagation`, `test_show_hn_blockers`, `test_zero_egress_and_dispatch_audit` (alle `agent_router`/`api_key_manager`, Query `TRAJECTORY_BLOCKED`), `test_fix_batch8::test_r30_audit_integrity...` (W1-A-Trigger-Änderung), `test_graceful_shutdown::test_database_wal_flush` (Ordering-Flake, isoliert grün), `test_workflow_dag_e2e` (6, W1-A-bekannt).
7. **Archiv-/Scratch-Collector**: `pytest` ohne `tests/`-Scope bricht mit 164 Collection-Errors in `data/backups/**` und `scratch/ii/**` ab (vorbestehend, nicht W2-C).

---

## 4. NEVER_DO_LIST

Kein Coroutine-Replay, keine PostgreSQL-Migration, keine eigene Content-Domäne. Alle Änderungen sind deterministische Validierungs-, Audit- und Rollen-Gates; keine simulierten Erfolge.

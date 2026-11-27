# Welle W4 — Partition A: Compliance / Prompt-SSOT (D15)

> **Datum:** 27.11.2026 · **Branch:** `main`, HEAD bei Start `a0a30aea` · **Subagent:** W4-A
> **Kein Commit, kein `git add` durch diesen Subagenten.** Es wurden ausschliesslich
> die zugewiesenen Dateien statisch bearbeitet.

## 1. Fix-Tabelle

| ID | Krit/Gew | Geänderte Datei(en) | Fix (Produktivpfad) | Regressionstest |
|---|---|---|---|---|
| **D15-H2** | HIGH 8 | `backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py`, `archon/routers/hr.py` | **Eine Prompt-SSOT:** `agent_profiles.json.prompt/system_prompt` ist der tatsächlich dispatche Text und damit masgeblich für Pin *und* Live-Hash. Neue Quellenkennzeichnung `SOUL_HASH_SOURCE = "profile_prompt_v2"`; `get_inventory()` verwirft Caches mit alter Quelle. `api_save_hermes_soul()` schreibt den SSOT-Prompt, ruft zwingend `refresh_soul_pin_for_agents(agent_id)` und lehnt bei Sync-/Pin-Fehler hart ab (HTTP 500, Rollback von SOUL.md + Profilen). | `test_w4a_h2_soul_edit_refreshes_pin_and_activation_stays_allowed`, `test_w4a_h2_pin_refresh_failure_is_hard_rejected_and_rolled_back` |
| **D15-H4** | HIGH 8 | `backend/compliance_engine.py`, `data/ai_act_literacy_register.json` | `_is_valid_literacy_entry()` verlangt jetzt 64-stelligen Hex-Hash **exakt der `add_literacy_entry()`-Signatur**, `completed_at`, sowie einen nicht-Bootstrap-`recorded_by`. Der `fix_a8_roles_bootstrap`-Eintrag mit `certificate_sha256: null` ist damit ungültig → HIGH_RISK-Aktivierung fail-closed. Der lokale Registereintrag wurde über die reguläre Signatur (Actor `michael`, GoBD-Event) erneuert. | `test_w4a_h4_null_certificate_hash_blocks_high_risk_activation` (null-Hash → `allowed is False`; Heilung über `add_literacy_entry()` → `allowed is True` inkl. Audit-Event) |
| **D15-M1** | MED 6 | `backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py` | Hash-Verifikation für **alle** Risk-Tiers (nicht nur HIGH_RISK): Drift → `SOUL_SHA256_MISMATCH`, Audit-Event `soul_sha256_drift_detected`, `guardrails_verified=False`, `reclassification_required=True`. `guardrails_verified` im Inventar wird aus dem echten Pin-Vergleich berechnet statt aus `bool(soul_sha256)`. | `test_w4a_m1_transparency_hash_drift_blocks_and_emits_audit`, `test_w4a_m1_guardrails_verified_comes_from_real_comparison` |
| **D15-M5** | MED 4 | `backend/eu_ai_act_inventory.py`, `backend/compliance_pdf.py` | Kommentar „26" korrigiert; `EXPECTED_HIGH_RISK_COUNT = len(HIGH_RISK_AGENT_IDS)` (28) aus Positivliste abgeleitet. Die drei Phantomer sind als **validierte historische Aliase** markiert und werden nur berücksichtigt, wenn ihre ID in der laufenden Profil-SSOT existiert (`classify_agent(known_ids=...)`) — in den 71 Profilen greifen sie nicht mehr. Neue CI-Hilfe `validate_classification_ids()`. PDF-Zusammenfassung als konsumierbare Funktion `_ai_act_summary_line()` extrahiert. | `test_w4a_m5_counts_derived_from_positive_list_and_pdf_consumes_them` (Zählung, Alias-Validierung, PDF-Konsument) |
| **D15-H6** (nur Inventar-Teil) | HIGH 7 | `backend/eu_ai_act_inventory.py` | Kommentar „funktional identisch zum CEO" ersetzt durch die disambiguiierte Regel: CEO (`executive_decision_architect`) = einzige hoheitliche Freigabeinstanz, `founder` = Strategieberatung ohne Freigaberecht. Konsumierbar über neues Inventarfeld `approval_authority`. Keine Änderung an `agent_profiles.json`/`org_hierarchy.json` (Partition C). | `test_w4a_h6_approval_authority_only_ceo` |

Alle Tests liegen in `tests/test_w4_a_compliance.py` und prüfen den **Konsumenten im Produktivpfad**
(Endpoint, Aktivierungs-Entscheidung, Inventar-/PDF-Konsument, Klassifizierung), nicht nur
Artefakt-Existenz. Keine `sk-<Zeichen>`-Strings, keine `# noqa`-Zeilen in Strings.

## 2. Verifikation

Lokal in dieser Session ausgeführt (Shell war hier verfügbar):

- `ruff check --select E,F,I --ignore E501` auf allen 5 geänderten `.py`-Dateien: **Exit 0**.
- `mypy --config-file mypy.ini` auf denselben Dateien: **Success: no issues found in 5 source files**.
- `pytest` (mit `ARCHON_TEST_DB_ISOLATION=1`) auf `test_w4_a_compliance.py`,
  `test_f23_soul_tiers_and_pin_refresh.py`, `test_f40_high_regressions.py`,
  `test_m49_eu_ai_act_compliance.py`, `test_audit_fixes_batch.py`: **96 passed**.
- Zusätzlich `test_eu_ai_act_inventory.py`, `test_audit_b3_souls.py`,
  `test_fix_w2_c_governance_roles.py`, `test_reaudit_stage13.py`, `test_med2_h_ssot.py`:
  **40 passed, 1 failed** — der einzige Fehler
  (`test_status_force_done_with_proof_writes_actor_and_evidence`) betrifft
  `backend.operations_api.get_provider` und damit **keine** Datei dieser Partition.

**Hinweis an den Koordinator:** die zentrale Verifikation (Ruff/MyPy/pytest, Full-Suite gegen
Baseline) bleibt verbindlich und wird von dir ausgeführt; obige lokale Läufe ersetzen sie nicht.
In Subagent-Sessions ist die Shell erfahrungsgemäss oft gesperrt — dann gist nur der
statisch saubere Stand und die zentrale Prüfung.

## 3. Risiken / Konflikte / offene Punkte

1. **`data/ai_act_literacy_register.json` ist per `.gitignore:72` (`data/`) nicht versioniert.**
   Die statische Korrektur wirkt nur in dieser Arbeitsumgebung; sie wird nicht Teil des Commits.
   Der *dauerhafte* Fix ist der gehärtete Validator: ohne gültigen, signierten Nachweis bleibt
   HIGH_RISK fail-closed blockiert. Im Deployment muss der Nachweis über den regulierten
   `add_literacy_entry()`-Pfad mit echtem Actor neu erfasst werden (kein Bootstrap, kein Seed).
2. **SSOT-Umstellung:** `souls/<id>/SOUL.md` ist ab jetzt abgeleitetes Artefakt, nicht mehr
   Pin-Quelle. Bestehende `souls/manifest.json`-Hashes werden vom HR-Edit nicht separat
   umgeschrieben (sonst Double-SSOT); das Manifest entsteht weiterhin aus
   `scripts/build_souls_ssot.py` (Partition C). Ein Manipulationsversuch am Artefakt allein
   wird nicht mehr als Compliance-Drift gewertet — massgeblich ist der dispatche Prompt.
3. **Alias-Kompatibilität:** `tests/test_audit_fixes_batch.py` erwartet weiterhin
   `credit_risk_scorer` als HIGH_RISK, sofern ein Profil mit dieser ID existiert. Die drei IDs
   sind deshalb als *validierte historische Aliase* erhalten, aber gegen die Profil-SSOT
   gegated; in den realen 71 Profilen sind sie inaktiv. Ein hartes Entfernen hätte diesen
   fremden Legacy-Test gebrochen (Datei gehört nicht zu Partition A).
4. **Korrektur gegenüber altem Code-Kommentar:** `compliance_engine.PROFILES_FILE` zeigt jetzt
   auf den Repo-Root (vorher war `archon.core.runtime.WORKSPACE_DIR` = `./agent_workspace`
   als SSOT-Pfad falsch). Ohne diese Korrektur hätte der neue Pin dauerhaft gegen den
   SOUL-Artefakt-Fallback driftiert (HIGH_RISK wären blockiert geblieben).
5. **Partition C** ändert parallel `agent_profiles.json`, `org_hierarchy.json`,
   `scripts/build_souls_ssot.py` und weitere Dateien. Für D15-H6 sind dort die eigentlichen
   Mandats-/Budget-Anpassungen nötig; dieser Report liefert nur die Inventar-Regel und deren
   Konsumenten. Keine fremden Dateien wurden von W4-A verändert.
6. **`refresh_soul_pin_for_agents()`** regeneriert das gesamte Inventar (nicht nur einen
   Agenten). Das ist atomar (`os.replace`) und der Endpoint rollbackt Profil-SSOT und
   SOUL.md bei Fehlern; ein bereits erfolgreich geschriebener Inventar-Pin bleibt bei einem
   nachgelagerten Fehler jedoch bestehen (dann ist er konsistent zur neuen SSOT, kein Risiko).

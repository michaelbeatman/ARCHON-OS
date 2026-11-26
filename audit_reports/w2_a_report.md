# W2-A (Security) — Implementierungsbericht

**Datum:** 26.11.2026 · **Scope:** D04-H3, D04-M3, D04-H2, D04-M5, D04-M7
**Dateibesitz (nur diese Dateien editiert):**
`backend/privacy_router.py`, `data/privacy_routing.json`, `backend/secret_masker.py`,
`backend/llm_kernel.py`, `backend/egress_firewall.py`,
`tests/test_w2_a_privacy_masking.py` (neu), `audit_reports/w2_a_report.md` (neu).

Keine Commits. Keine fremden Dateien verändert. Kein Replay, keine PostgreSQL-Migration
(NEVER_DO_LIST §5 eingehalten).

---

## 1. Umgesetzte Fixes

### D04-H3 / D04-M3 — `backend/privacy_router.py`, `data/privacy_routing.json`

**Strengthening-Only-Merge vervollständigt.** Neuer modulweiter
`_STRENGTHENING_KEYS` = (`zero_egress_strict`, `sensitive_local_routing`,
`hard_block_on_local_offline`, `block_crm_erp_prefetch_on_cloud`). `get_privacy_config()`
wendet einen einheitlichen `_apply_security_source()` auf **alle** Quellen an
(Defaults → `settings.json → privacy` → `data/privacy_routing.json` →
`zero_egress_governance` → ENV `PRIVACY_ZERO_EGRESS`). Für die vier Booleans zählt
nur ein truthy Wert (`true` gewinnt aus jeder Quelle, `false` kann nie eine
härtere Einstellung aufweichen). Insbesondere wurde die direkte Zuweisung
`merged["zero_egress_strict"] = bool(priv_block.get("zero_egress"))` entfernt —
sie war der verbleibende Fail-Open-Pfad aus `settings.json`.

**`fallback_to_eu` zeitlich korrekt aufgelöst.** Die `true`-Requests aller
Quellen werden gesammelt und erst **nach** der finalen Strikt-Entscheidung
(governance/ENV eingerechnet) ausgewertet: `any(requests) and not strict`.
Damit kann eine frühe JSON-Freigabe nicht mehr durch ein später aktiviertes
`zero_egress_strict` unterlaufen werden. Zusätzlich setzt die Strict-Invariante
nun auch `block_crm_erp_prefetch_on_cloud = True`.

**`save_privacy_config()` audit-first.** Der signierte
`chained_audit_log.record_event(...)`-Aufruf steht jetzt **vor** jeder
Datei-Mutation; bei Fehler wird `RuntimeError(... fail-closed ...)` geworfen,
ohne `privacy_routing.json` oder `settings.json` zu berühren. Die
`settings.json`-Änderung wird im Speicher vorbereitet (Lese-/Parsefehler
brechen ebenfalls vor Mutation ab). Strengthening-Only gilt auch für `cfg`
beim Speichern: `false` in den vier Sicherheits-Booleans wird verworfen.

**Harte Defaults in `data/privacy_routing.json`:**
`sensitive_local_routing: false → true`, `fallback_to_eu: true → false`.
(`zero_egress_strict` bleibt bewusst `false`, wie im Auftrag vorgegeben —
sensible Kategorien werden damit weiterhin lokal/hart geblockt, allgemeine
Kategorien nutzen das Standard-Routing.)

### D04-H2 — `backend/secret_masker.py`

`secret_masking_enabled` aus `fleet_and_hygiene` wird nicht mehr gelesen; der
Abschaltpfad `return text, 0` ist entfernt. Maskierung läuft immer. `count=0`
bedeutet jetzt ausschließlich „der geprüfte Text enthielt keine Secrets", nie
„Maskierung deaktiviert". Die Maskierung ist in `try/except` gefasst; jeder
Fehler wird als `RuntimeError("secret_masking_failed: ...")` eskaliert
(Fail-Closed) statt Klartext zurückzugeben.

### D04-M5 — `backend/llm_kernel.py`

`finalize_llm_output()` fängt den Maskierungsfehler nicht mehr mit
`logger.warning` ab und gibt den Text nicht unmaskiert an
Output-Policy-Linter/Aufrufer weiter. Stattdessen harter Abbruch mit
`RuntimeError("llm_output_masking_failed: ...")` (ERROR-Log).

### D04-M7 — `backend/egress_firewall.py`

`_get_cfg()` liefert bei Konfigurationsfehlern keine hartcodierte Allowlist
mehr. Der Fehler wird über `_record_audit_error("egress_firewall_config_unavailable")`
sichtbar gemacht und als `ZeroEgressBlockedError` mit
`error_code="EGRESS_FIREWALL_CONFIG_UNAVAILABLE"` eskaliert. `check_url()`
propagiert den Fehler; der bestehende Wrapper in `llm_egress_guard.py:683-704`
wandelt ihn in einen signierten Block-Proof um.

---

## 2. Verifikation

| Prüfung | Ergebnis |
|---|---|
| `.\.ci_venv\Scripts\python.exe -m pytest tests/test_w2_a_privacy_masking.py -q` | **14 passed** |
| `compileall -q` der 5 Owned-Dateien + Testdatei | Exit **0** |
| Bestandsdateien (W0 / Stage1-3 / Security-Routes / Zero-Egress-Audit) | 58 passed, 5 failed (siehe §3) |

Neue Tests decken ab: Settings-`true` vs. JSON-`false`, harte Defaults ohne
weitere Quelle, spätere Strikt-Quelle (Governance/ENV) entzieht EU-Fallback,
Fallback nur ohne Strikt-Modus, Shipped-JSON-Defaults, Audit-Fehler bricht vor
Mutation ab, Erfolgspfad schreibt Audit, Save kann Härtung nicht aufweichen,
Maskier-Schalter ignoriert, Maskierfehler hart, `finalize_llm_output` kein
Klartext bei Fehler, Normalfall maskiert weiterhin, Config-Fehler →
`ZeroEgressBlockedError`.

---

## 3. Bekannte Restpunkte / Übergaben an den Koordinator

1. **Vorbestehende DB-Korruption (nicht in meinem Ownership, nicht durch meine
   Änderungen verursacht):** `data/memory.db` (Audit-Log-DB) ist physisch
   beschädigt — `PRAGMA integrity_check` meldet u. a. „2nd reference to page",
   „Child page depth differs". Davon herrühren 5 Fehlschläge in fremden
   Bestandstests:
   - `test_stage1_stage3_hardening_and_bus.py::test_treasury_approve_reject_atomic_and_balance_check`
   - `test_stage1_stage3_hardening_and_bus.py::test_workflow_node_plugins_vst_discovery_and_execution`
   - `test_security_hardening_routes.py::test_vault_delete_service_token_passes`
   - `test_zero_egress_and_dispatch_audit.py::test_agent_router_logs_provider_model_and_target_host_in_sha256_chain`
   - `test_zero_egress_and_dispatch_audit.py::test_autonomy_settings_enforces_immutable_sha256_audit_and_syncs_privacy`

   Ich habe die DB **nicht** repariert (Datenverlust-Risiko, fremdes Ownership).
   Bitte zentral prüfen/neu aufbauen lassen.

2. **Erklärung zu Fünftem Test:** `test_autonomy_settings_enforces_immutable_sha256_audit_and_syncs_privacy`
   erwartet, dass `save_autonomy_settings()` den `local_llm_model`-Wert nach
   `privacy_routing.json` synchronisiert. Durch die geforderte neue
   Audit-First-Regel bricht `save_privacy_config()` bei dem korrumpierten
   Audit-Log ab (`RuntimeError: ... fail-closed, keine Konfigurationsänderung`),
   weshalb die Synchrosation ausbleibt und `llama3.2` statt `qwen2.5` gelesen
   wird. In einer intakten Umgebung schreibt der Audit-Eintrag erfolgreich und
   der Test besteht — das Verhalten ist die beabsichtigte D04-M3-Fail-Closed-
   Wirkung und wurde bewusst **nicht** aufgeweicht.

3. **`llm_egress_guard._sanitize_text_for_egress()` (fremdes Ownership):** unverändert.
   Die dortige Prüfung `if count: current = masked` ist weiterhin vorhanden,
   aber mit dem korrigierten `secret_masker` (immer maskieren, Fehler → Exception)
   ist der Fail-Open-Pfad `secret_masking_enabled=false → count=0 → Klartext`
   wirkungsvoll geschlossen. Ein zusätzlicher expliziter
   `masking_applied`-Beweis wäre dort optional, liegt aber außerhalb meines
   Dateibesitzes.

4. `ARCHON_AUDIT_HMAC_KEY` / Shell: der Workspace-Interpreter
   `.ci_venv\Scripts\python.exe` (Python 3.11.15, pytest 9.2.0) war verfügbar;
   ein Python-3.13-Lauf war in dieser Umgebung nicht möglich.

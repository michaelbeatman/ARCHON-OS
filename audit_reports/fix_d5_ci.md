# Fix-Log D5 — CI / Tests / Spec-Nachlauf (Phase 3 Nachlauf)

**Agent:** Delegations-Agent D5 · **Datum:** 25.11.2026
**Arbeitsverzeichnis:** `C:\.Antigravity-projekte\AgenticOS-2026`
**Exklusiver Datei-Bereich:** wie im Auftrag. Keine fremde Datei editiert, kein Commit, kein Push.
**Shell:** blockiert (`pwsh.exe: Zugriff verweigert`) — ausschließlich `read`/`grep`/`glob`/`edit`/`write` verwendet. **pytest / ruff / mypy wurden nicht ausgeführt**; alle Aussagen sind statisch verifiziert.

**Respektiert:** G-01 (kein Coroutine-Replay), G-02 (keine PG-Migration), G-05 / G-05a unangetastet. A1s F-32-Änderungen (`--require-hashes` an 4 Stellen, Digest-Gate inkl. Negativprobe, Ruff-Ratchet `--select E,F,I --ignore E501`) und A8s Generator-Änderungen (`semantic_scope_report()`, `MIN_DISTINCT_NEGATIVE_SCOPES`, `--sync-downstream`) wurden **nicht** rückgängig gemacht.

---

## 1. Direkt umgesetzte Fixes (22)

### 1.1 `.github/workflows/ci.yml` — D15 auf Semantik (A8)

| # | Änderung | Nachweis |
|---|---|---|
| 1 | Step „Rollen-SSOT — rollenspezifische Negativ-Abgrenzung" ersetzt den reinen Präsenz-Check („rollenspezifisch") durch Import von `semantic_scope_report()` + `MIN_DISTINCT_NEGATIVE_SCOPES` aus `scripts/build_souls_ssot.py`. Neuer Print-Text: `negative_scope: N/N vorhanden, M distinct (Minimum 60)`. Harte Fehler für `distinct < 60`, `missing_en`, `identical_en`, `high_risk_without_hitl`. | ci.yml:66-90. HIGH_RISK-IDs kommen aus `data/eu_ai_act_inventory.json` (semantic_scope_report), damit 26 nicht doppelt hardcodiert wird. |
| 2 | Vor dem Drift-Gate neuer Schritt `python scripts/sync_soul_runtime_cache.py` (per `glob` bestätigt vorhanden). Drift-Gate jetzt `--allow-missing --min-checked 568` — verhindert grünes Gate bei 0 geprüften Dateien. Beide Runtime-Verzeichnisse (`.hermes/profiles`, `data/hermes_profiles`) sind per `read` vorhanden, der Sync füllt beide → ≥ 568 prüfbare SOULs. | ci.yml:58-64; `scripts/sync_soul_runtime_cache.py:1-73`, `scripts/check_soul_ssot_drift.py:49-53,113-117`. |
| 3 | EU-AI-Act-Gate importiert jetzt `EXPECTED_HIGH_RISK_COUNT` aus `backend.eu_ai_act_inventory` statt `26` zu hardcoden; Step-Name und Print-Text folgen der Konstante. | ci.yml:92-102. Konstante existiert: `backend/eu_ai_act_inventory.py:65 EXPECTED_HIGH_RISK_COUNT = 26` (Punkt 7 — kein Edit nötig). |
| 4 | `sync_profile_ssot.py --check --allow-missing-hermes --json` wird jetzt per `subprocess` ausgewertet: Exit-Code hart plus expliziter Abbruch bei nicht-leerem `field_mismatch`. | ci.yml:35-53; `scripts/sync_profile_ssot.py:128-149,245,252` meldet `field_mismatch` als Drift. |

### 1.2 Busy-timeout-Drift → SSOT (A3/Punkt 4)

Alle `busy_timeout=<Zahl>`-PRAGMAs auf `DB_BUSY_TIMEOUT_MS` (5000) aus `backend.db_paths` umgestellt. Import war in `auth_service.py`, `email_draft_engine.py`, `audit_log.py` bereits vorhanden (um `DB_BUSY_TIMEOUT_MS` erweitert) und wurde in `hermes_ops.py` / `telemetry.py` neu ergänzt. Jeder Import hat einen expliziten `5000`-Fallback, damit ein Importfehler nicht zur `NameError` führt.

| # | Datei | Vorher → Nachher |
|---|---|---|
| 5 | `backend/auth_service.py` | `PRAGMA busy_timeout=10000` → f-String mit `DB_BUSY_TIMEOUT_MS` (:25, :29, :80) |
| 6 | `backend/email_draft_engine.py` | `PRAGMA busy_timeout = 10000` → f-String (:33, :37, :80) |
| 7 | `archon/routers/hermes_ops.py` | `PRAGMA busy_timeout=20000` → f-String (:17, :19, :176) |
| 8 | `archon/routers/telemetry.py` | 2 × `PRAGMA busy_timeout=3000` → f-String (:20, :22, :67, :418) |
| 9 | `backend/audit_log.py` | `PRAGMA busy_timeout=10000` → f-String (:30, :34, :431). **Nur** busy_timeout-Zeilen angefasst (A2s HMAC-/Anker-Code unverändert). |

Verifikation per `grep`: in diesen 5 Dateien findet der Detektor-Ausdruck `busy_timeout\s*=\s*(\d+)` **keinen** Treffer mehr.

### 1.3 `audit_reports/00_SOLL_SPEC.md` — 71 / 497 (A8/Punkt 3)

| # | Änderung |
|---|---|
| 10 | G-07 (`:28`): 70+3/73 Einträge → **71 Profile** (User-Entscheidung 2026-11-24, `micha`/`alpha` entfernt, `linkedin_social_media_specialist` nicht in SSOT) und **497 versionierte SOUL-Artefakte** (71 × 7). §15: S-15.1 `70` → `71` + Semantik-Gate-Hinweis; S-15.4 `490` → `497` (490/511 als überholt markiert). S-15.3 (26 HIGH_RISK) unverändert. **G-05 und G-05a nicht angefasst.** |

### 1.4 Tests (A2/Punkt 5+6)

| # | Datei | Änderung |
|---|---|---|
| 11 | `tests/test_med2_b_trace.py` | `test_verify_reports_unverified_versions_outside_production`: `valid=True`-Erwartung → `valid=False` + `reason` mit „Platzhalter"/„unknown"; nicht mehr vorhandene Keys `llm_dispatch_records`/`unverified_version_blocks` aus dem frühen Platzhalter-Return entfernt. `test_verify_rejects_placeholder_version_in_production` → `..._via_audit_strict`: `ENVIRONMENT=development` + `ARCHON_AUDIT_STRICT` manipulated (Schreib-Opt-out `0`, danach Default wiederhergestellt), prüft Ablehnung unabhängig von `ENVIRONMENT`. |
| 12 | `tests/test_p0_audit_hmac_downgrade.py` | `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1` im Setup (:25). |
| 13 | `tests/test_fix_batch2.py` | `monkeypatch`-Fixture ergänzt + Dev-Opt-out (:54-55). |
| 14 | `tests/test_zero_egress_and_dispatch_audit.py` | Dev-Opt-out in 4 Tests (:51, :105, :233, :278); zwei Tests um `monkeypatch`-Fixture erweitert. |
| 15 | `tests/test_p1_content_audit_hardening.py` | Dev-Opt-out in 4 Tests (:22, :39, :129, :222); `test_p1_audit_log_is_append_only` um `monkeypatch` erweitert. |
| 16 | `tests/test_m49_eu_ai_act_compliance.py` | Dev-Opt-out in `setUpClass` mit Restore in `tearDownClass` (:25-26, :74-78) — unittest-Style ohne `monkeypatch`. |
| 17 | `tests/test_audit_fixes_batch.py` | `monkeypatch`-Fixture + Dev-Opt-out (:1461-1466). |

Begründung für die minimal-invasive Variante: keine Ankerdatei angelegt, sondern der von A2 bewusst vorgesehene, laut geloggte Opt-out `ARCHON_ALLOW_INSECURE_AUDIT_DEV=1` gesetzt (in Produktion wirkungslos). Damit bleiben die Tests unverändert in ihrem Verhalten, nur die neue unbedingte Strukturprüfung wird für diese isolierten Fixtures ausgeschaltet.

### 1.5 Doku / Config (Punkt 8+9)

| # | Datei | Änderung |
|---|---|---|
| 18 | `docs/SYSTEM_HANDBUCH.md:828` | Geltungsbereich präzisiert: Spalten-/Payload-Konsistenz gilt für **Dispatch-Spalten aller Kategorien** (`llm_dispatch`, `rbac`, `webhook`, `api_keys`, `chain_anchor`), nicht nur `llm_dispatch`. |
| 19 | `docs/AUDIT_FINDINGS_REGISTER.md:287` | n8n-Receiver: ID `a7c3f1e9b2d84f6a` ist jetzt die Bundle-ID (ID-Drift `…f00` → `…f6a` behoben), **5 Nodes** statt 4: `Webhook Ingest → Archon HMAC Verify → Format Ack → Respond OK (200)` + Error-Branch `→ Respond HMAC Error (401)`; `responseMode: response`, `active: true`, `crypto.timingSafeEqual`. Quelle: `scripts/n8n_workflows_bundle.json:760-869`, `fix_a7_integrations.md:57-76,169-171`. |
| 20 | `.env.example` | `ARCHON_DB_CONSOLIDATED=1` im Data-&-Vault-Pfad-Block dokumentiert (:42-49) inkl. Hinweis auf versioniertes `config/db_consolidated.json`. keine Secrets. |
| 21 | `.gitignore` | **Geprüft, kein Edit nötig:** keine Ignore-Regel trifft `config/db_consolidated.json` (nur `config/passkey_hitl.json` ist explizit ignoriert; `data/` betrifft config/ nicht). Datei ist per `glob` vorhanden. |
| 22 | `backend/eu_ai_act_inventory.py` | **Geprüft, kein Edit nötig:** `EXPECTED_HIGH_RISK_COUNT = 26` existiert (:65) und wird jetzt vom CI-Gate importiert. |

---

## 2. DELEGATED (2)

### D1 — CI-Gate `python -m backend.db_paths --audit-busy-timeout --include-connect-timeout` ohne `--allow-drift`

**Nicht eingebaut — Vorbedingung aus Auftragspunkt 2 („NACHDEM die busy_timeout-Drifts behoben sind") ist nicht erfüllt.**

Begründung (statisch belegt): Der Detektor (`backend/db_paths.py:283-303`) flaggt mit `--include-connect-timeout` **alle** `sqlite3.connect(..., timeout=<Literal>)`-Werte ungleich `DB_BUSY_TIMEOUT_S = 5.0`. Davon betroffen sind **80+ Stellen in 30+ Dateien**, u. a. `backend/dead_letter_queue.py` (10× 15.0), `backend/egress_firewall.py` (5× 15.0), `backend/core_memory_manager.py` (4× 15.0), `backend/db_backup_manager.py` (6×), `backend/approval_policy_engine.py`, `backend/api_key_manager.py`, `backend/consensus_gate.py`, `backend/contract_manager.py`, `backend/deal_pipeline.py`, `views/view_inbox.py`, `main.py:2940`, plus `tests/test_med2_e_services.py:37,58` (absichtliche Drift-Strings in Test-Fixtures). Diese Dateien liegen **außerhalb meines exklusiven Bereichs**. Ein Gate ohne `--allow-drift` würde CI sofort rot machen. A3 selbst hält das Flag bewusst default-aus „bis zur Migration der Fremdmodule" (`fix_a3_persistence.md`, H6).

Nachholen, sobald die Migration breit abgeschlossen ist (exakt wie gefordert):

```yaml
      - name: SQLite busy_timeout SSOT-Gate (D03, hart)
        run: python -m backend.db_paths --audit-busy-timeout --include-connect-timeout
```

Bis dahin bleibt der Detektor manuell nutzbar: `python -m backend.db_paths --audit-busy-timeout --include-connect-timeout --allow-drift <datei> …` (Ratchet-Variante).

### D2 — `core_dispatcher.py` busy_timeout-Drift → Owner D2 (wie im Auftrag vorgegeben)

`core_dispatcher.py:806` (`timeout=15.0`) und `:822` (`PRAGMA busy_timeout=15000;`) bewusst **nicht editiert** — gehört D2. Beide sind die einzigen PRAGMA-Drifts außerhalb meines Bereichs. Nach D2s Fix ist zusammen mit den 5 obigen Dateien die PRAGMA-Seite vollständig migriert.

---

## 3. Verifikationsstatus

- Statisch: alle editierten Regionen erneut gelesen; Importe, f-String-Syntax, YAML-Block-Scalars, Pytest-Fixtures und `unittest`-Restore geprüft. `grep`-Kontrollen bestätigen: keine `busy_timeout=<Zahl>`-Literal mehr in den 5 Dateien; keine A1-Regression im CI; G-05/G-05a unverändert.
- **Nicht ausgeführt:** `pytest`, `ruff`, `mypy`, `python -m compileall` — Shell-Wrapper blockiert (`pwsh.exe: Zugriff verweigert`). Shell-Nachlauf dringend empfohlen:
  `python -m compileall -q backend/auth_service.py backend/email_draft_engine.py backend/audit_log.py archon/routers/hermes_ops.py archon/routers/telemetry.py tests/`
  `pytest tests/test_med2_b_trace.py tests/test_p0_audit_hmac_downgrade.py tests/test_fix_batch2.py tests/test_zero_egress_and_dispatch_audit.py tests/test_p1_content_audit_hardening.py tests/test_m49_eu_ai_act_compliance.py tests/test_audit_fixes_batch.py -q`
- Es wurde **nicht** committet oder gepusht.

**Zählung:** 22 resolved · 2 delegated.

# Welle W7 — Partition B (Backend & Doku) — Abschlussbericht

**Datum:** 27.11.2026 · **Branch:** `main` · **HEAD bei Start:** `028e6c09` · **Arbeitsbaum bei Start:** sauber
**Rolle:** Subagent · **Koordinator:** Haupt-Session · **Commit:** keiner (nach Vereinbarung)

---

## 1. Vorbedingungen & Regelkonformität

Zuerst gelesen: `docs/system/NEVER_DO_LIST.md`, `audit_reports/HANDOFF_W4_W7.md` (§2, §8, §9) und
`audit_reports/domain_01.md`. Zusätzlich `audit_reports/domain_09.md` (D09-M7 Detailbegründung).

Eingehalten:

- Kein PostgreSQL/DSN/Migration, kein Coroutine-/Event-Replay, keine eigene Content-Domäne.
- Kein `git add`, kein Commit. Nur statische Edits.
- Keine Dateien anderer Partitionen verändert (`static/js/**`, `frontend/src/**`,
  `archon/core/profiles.py`, `tests/test_w7_a_ui.py` blieben unberührt — W7-A arbeitete
  parallel im selben Arbeitsbaum).
- W3-Cancel-Safety und W3-Lease-Fail-Closed in `archon/core/orchestration.py` (Z. ~322–750)
  sowie der W5-`span_id`-Vertrag in `backend/audit_log.py` (`record_event`, `verify_integrity`)
  sind unverändert erhalten.
- Keine Secrets/`sk-<Zeichen>` in Tests, kein `# noqa` in einem String-öffnenden Ausdruck.

### Pfad-Abweichung (wichtig für den Koordinator)

Der Handover / die Zuweisung nennen `backend/docker_services.py:271-279`. Diese Datei existiert
nicht. Der produktive Endpunkt liegt in **`archon/routers/docker_services.py`** (von `main.py:282`
importiert, `POST /api/v1/services`) und entspricht exakt der Audit-Beschreibung
(`get_provider("app_main")`, `hasattr(save_services)`, bedingungsloses `success`). Der Fix wurde
dort vorgenommen — der einzigen Stelle, an der der Fehler im Produktivpfad wirkt.

---

## 2. Funde & Fixes

### D01-M6 (MED 4) — Fake-Success beim Service-Persistieren

**Datei:** `archon/routers/docker_services.py` · `api_save_services()`

Vorher: `if hasattr(app_main, "save_services"): …` — ohne jeden Schreibeffekt dennoch `{"status":"success"}`.

Jetzt (fail-closed, Vier-Glieder-Kette geschlossen):

- fehlender/nicht-aufrufbarer Writer → `HTTPException(503, "service persistence unavailable")`;
- Schreibfehler → 500 mit Log;
- fehlender Reader → `503 "service verification unavailable"`;
- Ruecklesen gegen `load_services()` muss eine Liste gleicher Länge und identischer Eintraege
  liefern, sonst `500 "service verification mismatch"`;
- nach Erfolg Invalidierung des 10-s-TTL-Caches von `get_docker_containers_from_socket()`;
- Rueckgabe `{"status": "success", "saved": true, "count": n}` — Erfolg aus dem verifizierten
  Effekt, nicht aus der Kontrollfluss-Konstante.

**Tests:** `test_missing_save_services_is_fail_closed_503`,
`test_missing_load_services_blocks_success_503`, `test_write_without_effect_is_not_success_500`,
`test_saved_services_are_verified_and_reported`.

### D01-M7 (MED 4) — Leerer Ordnername in der Synthese-Finalisierung

**Datei:** `archon/core/orchestration.py` · `_finalize_synthesis_after_approval()` und
`_run_synthesis_cascade()`.

Vorher: zwei `except Exception: def folder_namer(x): return ""` sowie zwei
`except Exception: _fan_ordner = ""`. Damit landete der finale Bericht ohne Fehler neben/unter
einem leeren Pfad.

Jetzt: vier Stellen fail-closed —

- Import-Fehler von `backend.post_task_pipeline.project_folder_name` → `RuntimeError(
  "project_folder_name unavailable — synthesis aborted")` (vor dem grossen `try`, d. h. der
  Fehler propagiert und blockiert die Finalisierung);
- Ausnahme des Namers → `RuntimeError("Projektordner nicht bestimmbar — Synthese abgebrochen
  (D01-M7)")`. Im Finalisierungs-Pfad wird sie vom bestehenden outeren `except Exception`
  als Warning protokolliert; entscheidend ist: kein Artefakt, kein `completed`, kein
  `synthesis_finalized`. Im Cascade-Pfad propagiert sie.

Bewusst beibehalten: ein *explizit injizierter* Namer darf weiter `""` liefern (bestehende
Tests `test_orchestration.py`/`test_w1_a_vault.py` testen damit das Legacy-Layout direkt in
`01_PROJEKTE`). Der produktive Fallback wurde entfernt; `return ""` kommt in der Datei nicht mehr vor.

**Tests:** `test_missing_project_folder_name_aborts_synthesis`,
`test_failing_folder_namer_writes_no_artifact`, `test_no_empty_folder_fallback_in_production_path`.

### D01-M8 (MED 4) — Audit-Flags ohne Rueckkopplung

**Dateien:** `backend/audit_log.py`, `backend/autonomy_settings.py`.

- Neuer Helfer `_dispatch_audit_integrity()`: schreibt in eine **frische, isolierte**
  `ChainedAuditLog`-Kette einen echten `llm_dispatch`-Block (inkl. `provider`, `model`,
  `target_host`, `target_endpoint`, `egress_zone`, `prompt_version`, `canary_version`) und
  ruft `verify_integrity()` auf. Isoliert, damit Alt-/Legacy-Bloecke der Produktiv-DB das
  Flag nicht verfälschen; die Krypto-Operationen sind dieselben wie im Produktivpfad.
- `_dispatch_audit_enforced()` ist keine Konstante mehr, sondern verlangt
  `valid == True`, `hmac_active == True` und einen `HMAC_PREFIX`-Hash des Probe-Blocks.
  Fehlender Key, Manipulation oder Probe-Fehler → `False` (fail-closed).
- `is_sha256_dispatch_audit_enforced()` delegiert an `_dispatch_audit_enforced()`;
  `load_all_settings()` (beide Zweige) und `save_autonomy_settings()` setzen den
  Settings-Wert daraus statt aus hartem `True`.
- **Kein neuer Schalter** eingefuehrt; der alte Opt-out bleibt aus dem Schreibpfad entfernt.
- W5-`span_id`-Vertrag in `record_event()`/`verify_integrity()` unverändert.

**Tests:** `test_dispatch_audit_flag_uses_real_verified_chain`,
`test_dispatch_audit_flag_follows_failed_verification`,
`test_dispatch_audit_flag_false_without_hmac_key`, `test_settings_cannot_reintroduce_a_switch`.

### D09-M7 (MED 3) — `/content-studio` weiterhin als Produktfläche beschrieben

**Dateien:** `CHANGELOG.md`, `docs/SYSTEM_HANDBUCH.md`, `docs/system/ROADMAP_2026.md`
(Zeilen 98 **und** 691), `docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md` (46, 71),
`static/index.html`, `.github/workflows/ci.yml`.

Alle sechs Doc-Stellen auf die Produktmodell-Korrektur 23.11.2026 umgeschrieben: keine eigene
Content-Domäne; Content läuft als **Task → Workflow → Agent → Gate → Artefakt**; die frühere
Oberfläche ist in `Operations → Workflows` aufgegangen. In `static/index.html` bleibt nur der
kommentierte **LEGACY-ALIAS** für alte Deeplinks (`→ operations/workflows`) erhalten, mit
inline-Kennzeichnung in derselben Zeile.

Neues CI-Gate (nach `check_doc_version_sync.py`): `grep -rnF '/content-studio'` über
`CHANGELOG.md docs audit_reports static/index.html`, mit Whitelist für

- normative/historische Audit-Dokumente, die das **Verbot** benennen
  (`00_SOLL_SPEC`, `domain_09`, `HANDOFF_W4_W7`, `GEWICHTETE_BEFUNDLISTE`, `MASTER_PLAN`,
  `AUDIT_ABSCHLUSS_2026_11_23`, `fix_w1_d_tenant_ledger`, `SYSTEM_AUDIT_2026_KONSOLIDIERT`,
  `SYSTEM_ARCHITEKTUR_UND_AUDIT_2026`) und
- `w7_[a-z]_report.md` (Wells-Berichte beschreiben den Fund) sowie
- Zeilen mit dem Marker `LEGACY-ALIAS`.

Hinweis: `docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` und
`SYSTEM_AUDIT_2026_KONSOLIDIERT.md` liegen **nicht** in meinem Besitz und sind historische
Audit-Dokus; sie sind whitelisted, aber inhaltlich veraltet. Falls der Koordinator die
„keine Doku-Reste"-Abnahme wörtlich auf alle Docs anwenden will, müssen diese in einer
eigenen Partition korrigiert und die Whitelist-Einträge entfernt werden.

**Tests:** `test_docs_no_longer_advertise_content_studio`,
`test_legacy_alias_is_explicitly_commented`, `test_ci_gate_guards_content_studio_with_whitelist`.

---

## 3. Verifikation (durchgeführt)

```
ARCHON_TEST_DB_ISOLATION=1
ruff check --select E,F,I --ignore E501  → All checks passed (5 geänderte .py-Dateien)
mypy --config-file mypy.ini              → Success: no issues found in 5 source files
pytest tests/test_w7_b_backend.py        → 14 passed
pytest <5 gezielte Regressionsdateien>   → 81 passed
pytest tests/test_w4_*.py … test_w7_*.py → 163 passed (1 Starlette-Deprecation-Warning)
yaml.safe_load(.github/workflows/ci.yml) → OK, 7 Jobs
Emulation des CI-Greps                   → keine unzulässigen Treffer
```

Kleine Import-Nebenkorrekturen in zwei **eigenen** Dateien (`docker_services.py`,
`autonomy_settings.py`): Ruff `I001`/`F401` (vorbestehend, unbenutztes `json`) wurde behoben,
damit das CI-Ratchet auf geänderten Dateien grün bleibt. Keine Verhaltensänderung.

Die Shell war zeitweise gesperrt (`pwsh.exe: Zugriff verweigert`) wie im Handover vorhergesagt;
die oben genannten Läufe konnten nach Wiederholung erfolgreich ausgeführt werden. Der
Koordinator verifiziert zentral erneut (Full-Suite/Baseline gemäß §3/§9 des Handovers).

---

## 4. Abnahme-Checkliste

- [x] D01-M6: Code-Fix + 4 Regressionstests im Produktivpfad
- [x] D01-M7: Code-Fix + 3 Regressionstests (inkl. statischem Fallback-Check)
- [x] D01-M8: Code-Fix + 4 Regressionstests, kein Schalter wiedereingeführt
- [x] D09-M7: 6 Doku-/UI-Stellen + CI-Gate + 3 Tests
- [x] Keine fremden Dateien verändert, keine Secrets, keine Commits
- [ ] `GEWICHTETE_BEFUNDLISTE.md` Status → **Behoben (<commit>)** — Aufgabe des Koordinators
- [ ] `git add -f` inkl. Reports und zentraler Commit — Aufgabe des Koordinators

**Geänderte Dateien (Partition B):**
`.github/workflows/ci.yml`, `CHANGELOG.md`, `archon/core/orchestration.py`,
`archon/routers/docker_services.py`, `backend/audit_log.py`, `backend/autonomy_settings.py`,
`docs/SYSTEM_HANDBUCH.md`, `docs/system/MULTI_AGENT_CONTENT_ROADMAP_2026_GUIDE.md`,
`docs/system/ROADMAP_2026.md`, `static/index.html`, `tests/test_w7_b_backend.py`,
`audit_reports/w7_b_report.md`.

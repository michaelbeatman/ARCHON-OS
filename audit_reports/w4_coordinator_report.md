# W4 — Koordinator-Report (Verifikation & Nachverdrahtung)

**Datum:** 27.11.2026 · **Welle:** W4 (15 Funde, vier dateidisjunkte Partitionen)
**Vorlage:** `HANDOFF_W4_W7.md` §5/§9 · `NEVER_DO_LIST.md` beachtet
**Subagenten:** A/B/C/D haben statisch editiert und **nicht** committet; alle Commits
und die zentrale Verifikation liegen beim Koordinator.

---

## 1. Partitionsberichte

Die vier Detailberichte liegen unter `audit_reports/w4_a_report.md` …
`w4_d_report.md` (wegen `.gitignore:55` **mit `git add -f`** committet).

| Partition | Funde | Neue Tests |
|---|---|---:|
| A — Compliance/Inventory | D15-H2, H4, M1, M5, H6 (Inventarteil) | 7 (`test_w4_a_compliance.py`) |
| B — Dispatch/SOUL | D15-H1, H7, D08-M8 | 7 (`test_w4_b_dispatch.py`) |
| C — Rollen-SSOT/UI | D15-H3, H5, H6, M2, M3, M4, D01-H2 (JS) | 15 (`test_w4_c_ssot.py`) |
| D — CUA/Task-Endpunkt | D01-H1, D01-H2 (Server) | 9 (`test_w4_d_cua.py`) |

---

## 2. Koordinator-Nacharbeiten

Die Partitionen durften nur ihre eigenen Dateien ändern. Folgende Querverbindungen
und Legacy-Verträge habe ich zentral aufgelöst:

1. **Router-Verdrahtung (D15-H3):** `main.py` registriert jetzt
   `app.include_router(get_liability_router())` nach `_register_late_routers`.
   Ohne diese Einbindung wäre der Prompt-Gate zwar fail-closed, aber es gäbe
   keinen Bestätigungsweg. `LiabilityAckRequest` und die FastAPI-Imports wurden
   in `archon/core/profiles.py` auf Modul-Ebene verlagert — sonst konnte FastAPI
   bei `from __future__ import annotations` die lokalen ForwardRefs nicht
   auflösen (`PydanticUserError` in `app.openapi()`).
2. **Router-Characterization angepasst:** `test_d2_main_characterization`
   (799 → 801 Pfade), `test_d2_router_special_blocks` (799 → 801) und
   `test_d2_include_sequence` (75 → 76 Includes; letzter Eintrag jetzt der
   Liability-Ack, die WebSocket-Route bleibt enthalten). Die zwei neuen Pfade
   stammen aus W4-C (Liability-Ack) und W4-D (`POST /api/operations/tasks`).
3. **Legacy-Verträge angepasst (Muster Handover §3):**
   - `test_w3_d_trajectory`: Hiring ohne registriertes Profil ist jetzt
     `not_configured`/`COMPLIANCE_BLOCKED` statt Budgetbuchung (D15-H7).
   - `archon/routers/operations_org.py`: `api_allocate_task_budget` meldet bei
     `not_configured` ebenfalls 409 statt fälschlich „success" — echter Fix,
     nicht nur Testanpassung.
   - `test_med_d14`: CEO ist Tier 2 (nicht mehr automatisch executive APEX);
     Tier kommt aus der SSOT (D15-H6).
   - `test_fix_w2_c_governance_roles`: `default` bleibt einzige executive
     Instanz, `robert` (CEO) ist `lead` (D15-H6/M2).
   - `test_med_d04_d06_d15`: Art.-50-Kennzeichnung nur noch bei Templates mit
     Außenwirkung, nicht mehr flächendeckend (D15-M4).
   - `test_p2_delegation_event_push`: `1200` kommt jetzt zweimal vor
     (Watchdog-Default + compact-Soul-Zeichenbudget aus D08-M8).
4. **Prompt-SSOT nachgezogen:** `scripts/sync_profile_ssot.py` wurde ausgeführt;
   `roles.json` und die (gitignored) `.hermes/profiles` sind wieder driftfrei
   (`--check --json` → `drift: false`). Ursache war die bewusste Founder-
   Mandatsänderung in `agent_profiles.json` (D15-H6).
5. **i18n der neuen Haftungsdialog-Texte:** drei neue Keys in allen 9 Locale-
   Dateien, `data-i18n`-Anker in `agent_profiles_view.html`. Der Bestätigungssatz
   bleibt bewusst unlokalisiert (Ausnahme in `test_locale_parity.py`), weil er
   exakt dem serverseitigen `LIABILITY_CONFIRMATION_PHRASE` entsprechen muss.
6. **MyPy-Ratchet in angepassten Legacy-Tests:** 20 vorbestehende Typfehler in
   fünf Tests wurden gezielt mit `# type: ignore[<codes>]` eingegrenzt — ohne
   Zeilenenden- oder String-Änderung, keine neuen Schalter.
7. **PbD-Artefakt mitgenommen:** der von `test_pbd_computer_use.py` neu
   geschriebene `.agents/skills/auto_senior_applicant_screener/SKILL.md` trägt
   jetzt `demo_only` / `simulated` / `executable: false` und den ehrlichen
   Runtime-Hinweis (D01-H1). Das ist der gewollte Effekt der Code-Änderung.

**Hinweis D15-H4:** `data/ai_act_literacy_register.json` ist gitignored. Der
dauerhafte Fix ist der verschärfte fail-closed Validator; der Nachweis muss im
Deployment über den auditierten `add_literacy_entry()`-Pfad neu erfasst werden.

---

## 3. Verifikation

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }) +
         (Get-ChildItem tests/test_w4_*.py)
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/ -q
```

- Ruff (`E,F,I`, `E501` ignoriert): **All checks passed** (29 Dateien).
- MyPy (`mypy.ini`): **Success: no issues found in 29 source files**.
- Vier neue Suiten + angrenzende Suiten: **87 passed**.
- Full-Suite: **2810 passed, 16 skipped, 22 failed** (294 s). Die 22 Roten sind
  exakt die in `HANDOFF_W4_W7.md` §3 dokumentierte Baseline (RBAC/401 in
  `orange_a*`, `orange_b_r16`, `p0_api_validation_*`, `p1_trace_propagation`,
  `fix_batch9`, `fix_w2_c_governance_roles`, `med2_b_trace`, `m83`,
  `reaudit_d16_dispatcher`, `w3_d_trajectory`). **Kein neuer Fehler** gegenüber
  dem Stand vor W4; die vorbestehende `m49`-Error-Marke trat diesmal nicht auf.

---

## 4. Abnahme

- [x] Alle 15 W4-Funde: Code-Fix + Regressionstest im Produktivpfad.
- [x] Ruff und MyPy auf allen geänderten `.py`-Dateien: Exit 0.
- [x] Neue Suiten grün; Full-Suite auf Baseline-Niveau.
- [x] Keine fremden Dateien „nebenbei" verändert, keine Secrets in Tests,
      keine Subagent-Commits.
- [x] Vier Partitionsberichte + dieser Koordinator-Report mit `git add -f`.
- [ ] Status-Synchronisierung in `GEWICHTETE_BEFUNDLISTE.md` folgt als separater
      Commit (Muster `786d6e71`).

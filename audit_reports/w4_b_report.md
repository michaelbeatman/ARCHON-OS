# W4-B — Rollen-/Prompt-SSOT im Dispatch (D15-H1, D15-H7, D08-M8)

> **Welle/Partition:** W4-B · **Branch:** `main` · **Basis-HEAD:** `a0a30aea`
> **Status:** statisch editiert, **nicht committet**. Ruff/MyPy/pytest werden
> zentral durch den Koordinator verifiziert (Subagent-Shell gesperrt:
> `pwsh.exe: Zugriff verweigert`).

---

## 1. Ergebnisüberblick

| ID | Krit/Gew | Fix | Konsument im Produktivpfad | Regressionstest |
|---|---|---|---|---|
| D15-H1 | HIGH 8 | Kanonischer SOUL-Kontext-Helper in `delegation.py`; Worker injiziert effektiven Tier in `system_prompt`; Pin-Drift fail-closed | `backend/operations_execution.py::_execute_kanban_task_inner` (vor `dispatch_to_omniroute_or_container`) | `test_d15_h1_high_risk_compact_profile_gets_full_tier_in_worker_prompt`, `test_d15_h1_soul_pin_drift_blocks_worker_before_dispatch` |
| D08-M8 | MED 6 | Fünfte Kontextquelle in `_build_dispatch_context_sync`, tier-abhängiges `max_chars`, Duplex-Schutz | `core_dispatcher.py::_build_dispatch_context_sync` (Ort der Token-Kosten) | `test_d08_m8_dispatch_context_consumes_resolved_tier_exactly_once`, `test_d08_m8_tier_dependent_chars_and_no_double_injection` |
| D15-H7 | HIGH 7 | Hiring ohne SSOT-Registrierung → `not_configured` / `COMPLIANCE_BLOCKED`, Abbruch **vor** `init_budget_tables`, DB-Insert und `set_role_budget_policy`; explizites Dispatcher-Gate vor Throttle/Cache/Budget | `backend/role_budget_engine.py::ceo_autonomous_hire_specialist`, `::plan_and_decompose_task_with_budgets`; `core_dispatcher.py::dispatch_to_omniroute_or_container` | `test_d15_h7_hiring_without_registration_books_no_budget`, `test_d15_h7_plan_does_not_allocate_budget_for_unconfigured_hiring`, `test_d15_h7_dispatcher_blocks_hired_profile_with_explicit_reason` |

**Geänderte Dateien (nur Besitz W4-B):**
- `archon/core/delegation.py`
- `backend/operations_execution.py`
- `core_dispatcher.py`
- `backend/role_budget_engine.py`
- `tests/test_w4_b_dispatch.py` (neu)
- `audit_reports/w4_b_report.md` (neu)

Keine fremden Dateien berührt. Insbesondere nicht angefasst:
`backend/eu_ai_act_inventory.py`, `backend/compliance_engine.py`,
`archon/routers/hr.py`, `static/**`, `agent_profiles.json`,
`config/org_hierarchy.json`, `scripts/build_souls_ssot.py`,
`templates/crewai/**`, `backend/delegation_isolation.py`.

---

## 2. Details der Fixes

### 2.1 D15-H1 / D08-M8 — SOUL-Tier wird konsumiert

**Vorher:** `resolve_effective_soul_mode()` und `active_soul_tier_text()`
lieferten den Tier-Text; `delegation.py` speicherte ihn als `system`-Nachricht
in `state.db`. Der Kanban-Worker baute seinen System-Prompt jedoch nur aus
`prof["prompt"]/["system_prompt"]`; der zentrale Dispatch lud Registry-Prompt
und Core-Memory ohne Tier-Begrenzung. Für HIGH_RISK (z. B. `legal_counsel`)
wurde `full` aufgelöst, obwohl das Profil `soul_mode="compact"` führt →
Produzent + Speicher ohne Konsument (§0: Theater).

**Nachher — eine kanonische Auflösung, zwei Konsumenten:**

1. `archon/core/delegation.py` — neu:
   - `soul_tier_max_chars()` → `compact=1200`, `pro=3000`, `full=6000`.
   - `format_soul_tier_block()` / `soul_tier_already_injected()` →
     einziger Produzent des injizierbaren Blocks + Duplex-Schutz (erkennt
     beide historischen Schreibweisen `AKTIVER_SOUL_TIER` und
     `AKTIVER SOUL-TIER`).
   - `_canonical_soul_sha256_for_dispatch()` → Live-Hash aus
     `souls/<id>/SOUL.md` mit identischer Zeilenenden-Normalisierung wie
     Inventar/Compliance-Engine.
   - `build_dispatch_soul_context()` → löst Alias über
     `canonical_agent_id()`, prüft den Pin gegen das Inventar, liefert
     `tier`, `text`, `pin_ok`, `error_code`, `inventory_known`.
     **Entscheidung zu "soul_mode konsistent setzen ODER Auto-Auflösung
     entfernen":** Die Auto-Auflösung bleibt und wird zur autoritativen
     Auflösung am Konsumenten; `soul_mode` in der SSOT ist die deklarierte
     Baseline. Damit ist `compact` kein toter Wert mehr.
2. `backend/operations_execution.py` — der Worker ruft den Helper **vor**
   dem kostenpflichtigen Dispatch. Bei vorhandenem, aber abweichendem Pin
   (`SOUL_SHA256_MISMATCH`) oder nicht verifizierbarem Pin
   (`SOUL_SHA256_NOT_VERIFIABLE`) → `target_status="blocked"`,
   `block_kind="SOUL_PIN_DRIFT"`, expliziter `error_code` im Audit-Verdict
   und im Rückgabewert; **kein** Dispatch. Sonst Injection des effektiven
   Tier-Blocks in `system_prompt`. Der W3-C-Codepfad für signierte
   Delegationen bleibt erhalten und bekam nur einen Duplex-Guard.
3. `core_dispatcher.py::_build_dispatch_context_sync` — fünfte Quelle;
   `soul_tier_info` im Result (Tier, Zeichenzahl, `injected`, `pin_ok`,
   `error_code`). Kein harter Abbruch an dieser Stelle: der harte Abbruch
   liegt im Worker-Gate und im bereits bestehenden HIGH_RISK-Compliance-Gate
   des Impl (Z. 1622 ff.). Das verhindert, dass bestehende
   Dispatch-Characterization-Tests mit Fake-Agent-IDs regressen.

**Effekt:** HIGH_RISK + `soul_mode=compact` → im Worker-System-Prompt steht
`[AKTIVER_SOUL_TIER: FULL]` inkl. FULL-SOUL-Text; bei Pin-Drift wird gar
nicht erst bezahlt. Compact vs. Full erzeugen messbar unterschiedliche
Prompt-Längen; der SOUL-Block steht genau einmal im Prompt.

### 2.2 D15-H7 — Hiring ohne ausführbares Profil

**Vorher:** `hired_<slug>_<hash>` wurde weder in `agent_profiles.json` noch
ins Inventar aufgenommen (`register_in_profiles_json=False`), der Dispatcher
blockte per Default-Deny, das Hiring buchte aber Budget → Rollen-Theater mit
echten Kosten.

**Nachher (KNEE TIGHT, ohne `compliance_engine.py` zu berühren):**
- `ceo_autonomous_hire_specialist()` berechnet die ID, prüft dann
  `register_in_profiles_json` und bricht bei `False` **vor**
  `init_budget_tables()`, `INSERT INTO autonomous_hired_agents` und
  `set_role_budget_policy()` ab. Ergebnis: `status="not_configured"`,
  `error_code="COMPLIANCE_BLOCKED"`,
  `failure_reason="HIRING_NOT_CONFIGURED"`, Budgets 0. Audit über
  `backend.trajectory_budget._audit` (bestehendes Muster im Modul).
- `plan_and_decompose_task_with_budgets()` bekam den durchgereichten Parameter
  `register_in_profiles_json=False`. Bei `allow_autonomous_hiring=True` ohne
  Registrierung wird **vor** der Allokation abgebrochen: kein Platzhalter,
  keine `task_budget_allocations`, kein Budget.
- `core_dispatcher.dispatch_to_omniroute_or_container()` hat einen expliziten
  Guard für `hired_*` **vor** Throttle, Cache und Budget-Reservierung:
  `status="blocked"`, `error_code="COMPLIANCE_BLOCKED"`, Audit-Event
  `dispatch/hiring_not_configured`.

Damit gibt es keinen Pfad mehr, der Hiring-Budget bucht, ohne dass ein
ausführbares Profil existiert. Die SSOT-Registrierung selbst (Profil + Inventar
mit `expires_at`) bleibt bewusst außerhalb dieser Partition (W4-A/W4-C).

---

## 3. Tests

Neue Suite: `tests/test_w4_b_dispatch.py` (7 Tests, alle offline/deterministisch):

| Test | Prüft |
|---|---|
| `test_d15_h1_high_risk_compact_profile_gets_full_tier_in_worker_prompt` | Konsument im echten Worker: FULL-Block trotz `soul_mode=compact`, genau ein Block |
| `test_d15_h1_soul_pin_drift_blocks_worker_before_dispatch` | kein Dispatch bei manipuliertem Pin; Status/Reason im Kanban-Verdict |
| `test_d08_m8_dispatch_context_consumes_resolved_tier_exactly_once` | `_build_dispatch_context_sync` injiziert Tier genau einmal |
| `test_d08_m8_tier_dependent_chars_and_no_double_injection` | `chars(full) > chars(compact)`, kein doppelter Block |
| `test_d15_h7_hiring_without_registration_books_no_budget` | keine Hire-Zeile, keine Budget-Policy, explizite Status/Codes |
| `test_d15_h7_plan_does_not_allocate_budget_for_unconfigured_hiring` | keine Allokation, keine Hire-Zeile |
| `test_d15_h7_dispatcher_blocks_hired_profile_with_explicit_reason` | Dispatcher-Gate + Audit-Event |

Keine `sk-<Zeichen>`-Strings, keine `# noqa` auf String-öffnenden Zeilen.

---

## 4. Risiken / Konflikte / Hinweise für den Koordinator

1. **W3-Legacy-Test muss angepasst werden (bewusster Vertragsbruch):**
   `tests/test_w3_d_trajectory.py::test_hiring_happens_after_allocation_with_exact_share`
   geht vom alten Vertrag aus (`allow_autonomous_hiring=True` erzeugt trotz
   fehlender SSOT-Registrierung ein Hire-Profil mit Budget). Der neue
   Fail-Closed-Vertrag liefert hier `status="not_configured"`. Analog zu den
   in `HANDOFF_W4_W7.md` §3 bereits angepassten Legacy-Tests ist dieser Test
   vom Koordinator auf den neuen Vertrag umzustellen (oder als bekanntes
   Legacy-Verhalten zu markieren): `plan["status"] == "not_configured"`,
   `plan["error_code"] == "COMPLIANCE_BLOCKED"`, `hired_specialist is None`,
   keine `task_budget_allocations`. Die Aufrechterhaltung des alten Vertrags
   würde D15-H7 unauflösbar mit "kein Budget ohne ausführbares Profil"
   kollidieren.
2. **Pin-Verifikation setzt valide SOUL-Pins voraus.** Die Helper lesen die
   reale `souls/<id>/SOUL.md`; die Tests berechnen den Pin aus derselben Datei
   und monkeypatchen das Inventar. In der realen SSOT müssen Pin und Datei
   übereinstimmen — anderenfalls blockt der Worker zu Recht fail-closed.
   Partition A (W4-A) ändert `compliance_engine.py`/Inventar parallel; die
   Normalisierung wurde bewusst 1:1 übernommen, damit kein künstlicher
   Drift entsteht.
3. **Kein zweiter harter Block im Dispatcher-Impl.** Der zentrale
   `_build_dispatch_context_sync` meldet Pin-Probleme nur; der harte Abbruch
   bleibt beim Worker und beim vorhandenen HIGH_RISK-Compliance-Gate. Das
   schützt bestehende Characterization-Tests mit Fake-Agent-IDs vor Regression
   und hält die Verantwortung klar getrennt.
4. **Keine Änderung an `agent_profiles.json` / Inventar.** `soul_mode` bleibt
   `compact`; die Auflösung passiert zur Laufzeit am Konsumenten. Kein
   Schema-/Datenzugriff, keine Migration, kein PostgreSQL, kein Replay, keine
   Content-Domäne (NEVER_DO_LIST eingehalten).
5. **W0–W3-Fixes erhalten.** Lease-Fail-Open-Entfernung, Handoff-SSOT,
   cancel-safe Pfade, W3-C-SOUL-Tier-Konsum im signierten Delegationspfad,
   D08-H08-1-Thread-Bündelung und F-041-Compliance-Fail-Closed blieben
   unangetastet; ergänzt wurden nur Guards/Quellen.
6. **Zentrale Verifikation ausstehend.** Wegen gesperrter Shell in der
   Subagent-Session wurden Ruff (`--select E,F,I --ignore E501`),
   MyPy (`--config-file mypy.ini`) und `pytest tests/test_w4_*.py` nicht
   lokal ausgeführt. Bitte vom Koordinator zentral fahren; DB-Isolation
   (`ARCHON_TEST_DB_ISOLATION=1`) beachten.

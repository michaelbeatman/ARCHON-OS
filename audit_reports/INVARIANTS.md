# INVARIANTS — Schutz bewährten Codes vor künftigen Vibe-Sessions

**Erstellt:** 25.11.2026 · **Kontext:** Archon OS bei ~60 % V1.0, Produktivbetrieb läuft, weitere Features (u. a. ERP) stehen aus
**Status:** Reine Analyse / Grundlage. **Keine Code-Änderung, kein Commit, kein Push.**
**Ort:** bewusst im **Hauptbaum** (`main`), `??` — gehört nicht in die Worktree-Commits auf `s1-god-objects`.
**Zweck:** Die nächsten 40 % werden wieder in Vibe-Sessions entstehen. Dieses Dokument hält fest, was dabei **nicht** zerstört werden darf, und vor allem **warum**.

---

## 0. Die eigentliche Gefahr

Nicht „Vibe-Code baut einen Bug ein". Die Gefahr ist: **Vibe-Code vereinfacht bewährten Code**, weil er die Begründung nicht kennt. Ein Kommentar schützt dagegen nicht — er wird mit„bereinigt". Was schützt, ist ein **Test, der den Grund festnagelt**, plus ein **zweiter Blick**.

In dieser Session sind wir mehrfach genau daran vorbeigeschrammt (§3). Jedes Mal war es eine unabhängige Verifikation, nicht ein Gate, die es gefunden hat.

---

## 1. Bestehende Härtung (inventarisiert, 25.11.)

| Mechanismus | Beleg | Schützt gegen |
|---|---|---|
| Pre-Commit `scripts/audit_secrets.py` | hat den Baseline-Commit real gestoppt (`fix_d2_mypy.md:91`) | Secrets im Commit |
| `tests/test_unbound_calls.py` | hat historisch einen echten `NameError` gefunden (Docstring `:7-20`) | ganze **Fehlerklasse** |
| `tests/test_a5_path_constants.py` + `scripts/parity_baselines/` | Host-/Container-Baselines | stilles Pfad-Split-Brain |
| `tests/test_import_layer_contracts.py` (S1) | Ratchet + Config-Drift-Test + Negativprobe | neue Layer-Verletzungen **und** „No matches for ignored import" |
| Changed-Files-Ratchet `ci.yml:501-525` | `git diff --name-only --diff-filter=ACMR`, hart, ohne `continue-on-error` | unsaubere geänderte `.py` |
| mypy `43 → 0` Pragmas, `mypy.ini` SSOT | `HANDOFF_HY4_DEBUG_2026-11-25.md` §1/§3 | „harte" Gates ohne Wirkung |
| `ci.yml:305` / `:555` | `pytest tests/ -q` / `coverage run -m pytest` | Regressionen (2347 Tests) |
| `bandit`, `pip-audit`, SBOM-Hash-Gate, `compileall`, `tsc --noEmit`, `npm run build`, Compose-Negativprobe | `ci.yml` | SAST / CVEs / Supply Chain / Syntax |
| Action-Pins + Image-Digests | `ci.yml`, `docker-compose.yml:374/437` | unprovenierte Builds |
| Ownership-Modell | `fix_w3_d_trajectory_dag.md:121-127`, `fix_w4_d2_residuals.md`, `fix_d1_main.md` | parallele Zerstörung, stilles Skippen/Swallowen |
| Schutzregeln + NEVER_DO | `HANDOFF_HY4_DEBUG…md` §2, `INCIDENT_2026-11-25_LOGIN_OUTAGE.md` | `./data`, `--no-verify`, Replay, PG-Migration |

**Lehre aus Handoff §4:** Nur ruff/mypy/bandit/pip-audit sind harte CI-Gates; vulture/radon/import-linter/detect-secrets/semgrep/pyright haben keins → „Theater". **Ein Gate, das immer grün ist, ist schlimmer als keins.**

---

## 2. Invarianten-Katalog

Legende: ✅ geschützt · 🟡 gelebt, nicht erzwungen · ⛔ offen

| # | Invariante | Beleg | **Warum (der Grund!)** | Schutz | Status |
|---:|---|---|---|---|---|
| 1 | `backend/**` importiert kein `archon.routers.*` | `domain_09.md` H-09-2, `.importlinter` | Services dürfen die HTTP-Schicht nicht kennen; sonst Importzyklen / Initialisierungs-Order-Probleme | `test_import_layer_contracts.py` + `lint-imports` | ✅ Ratchet, 18 offen |
| 2 | `archon.core` importiert kein `archon.routers.*` | `orchestration.py:1432` (A1 aufgelöst) | Core → Router ist eine Schichtverletzung innerhalb `archon` | ⛔ eigener Contract nötig (A2) | 🟡 faktisch grün, nicht erzwungen |
| 3 | Rückwärts-Imports `import main as app_main` (≥90 Stellen / ~27 Module) nur sinkend | `ANALYSIS_GOD_OBJECTS.md` §2.3 | `main.py` lädt 75 Router und wird selbst von ihnen importiert — Reihenfolge = Pfad-Präzedenz | ⛔ `test_audit_b2_rbac_tenant.py:37` greift nur in RBAC-Wrappern | ⛔ |
| 4 | `set_decision_factory` / `_DEPS` / Parameter-Injektion bleiben | `permissions.py:6-14`, `chat.py:62-78`, `orchestration.py:1397`, `main.py:2010/2079/2689` | bewusst zyklusfreie späte Bindung; Fallback auf Telegram-Ping, „es geht nie verloren" | ⛔ A1 (läuft) + `test_a1_decision_injection.py` | 🟡 |
| 5 | **Alle** Tests mit `ARCHON_DATA_DIR=<temp>`, nie `./data` | `INCIDENT_2026-11-25_LOGIN_OUTAGE.md` | einmalige Produktiv-DB-Korrumpierung dokumentiert | 🟡 konsequent gelebt, nicht maschinell erzwungen | 🟡 |
| 6 | Kein `# mypy: ignore-errors` | Handoff §1 | pro-Datei-Pragma machte das Ratchet-Gate wirkungslos | `mypy.ini` + `ci.yml:535/548` | ✅ 43→0 |
| 7 | `_ROUTER_LOAD_ERRORS` fail-closed, Router-Reihenfolge = Pfad-Präzedenz | `main.py:3149-3150`, `:3457-3486` | sonst 404 bei `healthy /health`, fail-open | ⛔ kein Test | ⛔ |
| 8 | Vier-Augen: leerer `created_by` → **403 fail-closed** | `decisions.py:708-714`, `domain_04.md` | verhindert Selbstfreigabe; Default würde Sicherheits-Bypass erzeugen | ⛔ Characterization-Tests fehlen | ⛔ |
| 9 | `_cost_usd = None` bei Kostenfehler, **nie `0.0`** | `workflow_dag_runner.py:1764` (D12) | `0.0` würde als *realer* Wert in die Abrechnung gehen | ⛔ kein Test | ⛔ |
| 10 | Altschuld-Counter monoton sinkend (23→21→18→…→0) | `test_documented_debt_is_bounded` | Ratchet statt Big-Bang: Neues darf kommen, Basis darf nicht sinken | ✅ S1/F1a/A1 | ✅ |
| 11 | Kein Secret im Commit | `scripts/audit_secrets.py` (Pre-Commit) | Legacy-Salt-Literal war bereits in `HEAD` | ✅ Hook, kein `--no-verify` | ✅ |
| 12 | NEVER_DO + kein Push ohne Freigabe | Handoff §2, `AGENTS.md` | kein Coroutine-Replay, keine PostgreSQL-Migration, kein stummes Re-Signieren | ✅ Prozess | ✅ |

---

## 3. Die Vereinfachungs-Fallen — Characterization-Pflicht

Für jede dieser Stellen gilt: **Erst den Grund lesen, dann einen Test schreiben, dann (vielleicht) ändern.**

| Stelle | Wirkt wie | Ist aber | Typischer Vibe-Fix | Nötiger Test |
|---|---|---|---|---|
| `archon/core/permissions.py:6-14` `set_decision_factory` | unnötige Indirektion | bewusst zyklusfreie Bindung + Telegram-Fallback | direkter Import → Zyklus + Vier-Augen-Bruch | `test_a1_decision_injection.py`: Factory fehlt → fail-closed, kein `main`-Import |
| `workflow_dag_runner.py:1764` `_cost_usd = None` | Bug (`NoneType += float` im Log) | D12: bewusst kein `0.0` als realer Wert | auf `0.0` „fixen" → falsche Kosten | Kostenfehler → `None` **und** `cost_unverified=True` |
| `decisions.py` leerer `created_by` | lästiger 403 | verhindert Selbstfreigabe | Default/Platzhalter setzen → Bypass | leerer Ersteller → 403, anderer Approver → freigebbar |
| `_FALLBACK_MODEL_PRICES_PER_1M` (`llm_kernel.py`) | tote Tabelle (Live-Preise greifen jetzt) | Offline-Fallback | löschen → Offline-Betrieb ohne Preise | `get_llm_prices()` mit `status=error` → Fallback liefert Wert |
| 125 Re-Exports in `operations_api.py:4116-4507` | tote Importe (nur `TEAMS_DEFINITION` intern genutzt) | **28 aktive Test-Referenzen**, davon 25 dynamisch per `__import__('backend.operations_api')` + `getattr` (`test_rbac_admin_routes_paket2.py:87-111`) | „aufräumen" → Tests brechen an unerwarteter Stelle | AST-Test, der dynamische String-Referenzen erfasst, **bevor** gelöscht wird |
| `allow_indirect_imports = true` (`.importlinter`) | Gate-Aufweichung | begründete Präzisierung: transitiver Core→Router-Pfad ist ein **eigener** Befund | auf `false` stellen → Contract schlägt wieder transitiv zu | erst nach Tilgung von Invariante #2 auf `false` |
| `workflow_dag_runner.py:1220` `import core_dispatcher` im Executor | toter Doppelimport (ruff `F401`) | `core_dispatcher` trägt **mutable Globals**, die Router/Tests zur Laufzeit patchen; der Erstimport `:1212` wird `:1213` genutzt | per `ruff --fix` blind löschen → evtl. Initialisierungs-Side-Effect verloren | vorher `grep` auf alle Import-Pfade, Entfernung manuell + **Full-Gate** |
| `tests/test_unbound_calls.py` | „nur ein S/AST-Test, ausmustern" | einziger S-Test mit echtem Split-Nutzen (`ANALYSIS_GOD_OBJECTS.md` Anhang D.2) | löschen → `NameError`-Klasse nicht mehr erkannt | behalten, nicht in die S-Test-Ausmusterungsliste aufnehmen |

---

## 4. Regeln für eine Vibe-Session (Prozess vor Technik)

1. **Exklusive Ownership:** Jeder Agent bekommt eine **Positivliste** („nur diese Dateien") und eine **Negativliste** („diese nicht anfassen"). Befunde außerhalb → **DELEGATED** mit Grund, nicht still fixen.
2. **1 Schritt = 1 Commit = 1 Full-Gate.** Kein Schritt ohne `pytest tests/ -q` + `ruff --select F821` + `mypy` + `compileall` + `audit_secrets --all`, immer mit `ARCHON_DATA_DIR=<temp>`.
3. **CI-Ratchet-Simulation vor dem Commit:** `ruff check <geänderte .py> --select E,F,I --ignore E501` — das Ratchet ist **dateigranular**, nicht zeilengranular. Vorbestehende Funde in einer angefassten Datei → **separater `chore(ruff)`-Commit**, kein `noqa`, kein Mix.
4. **Test-Owner ist eine eigene Rolle.** Rote/obsolete Tests werden **eskaliert**, nicht gelöscht, geskippt oder umgeschrieben, um ein Gate grün zu bekommen (`fix_w3_d_trajectory_dag.md:121-127`).
5. **Jeder neue Test braucht eine Negativprobe gegen die echte Logik.** Ein tautologischer Test (S1, erster Entwurf) ist selbst ein Theater-Gate. `_imports_from_tree()` / `_violations()` gemeinsam nutzen, nicht einen hartcodierten Snippet behaupten.
6. **Zweiter Blick ist Pflicht, nicht Optional.** Dieses Repo hat jeden kritischen Fund (Off-by-one-Zeilen, 125 Re-Exports, `create_decision`-Design, Secret-Zitat, tautologischer Test) durch eine **frische, unabhängige Instanz** gefunden. Nie denselben Agenten prüfen lassen, der den Fix schrieb.
7. **Nicht vereinfachen ohne Test.** Merkwürdiger Code hat einen Grund → §3.
8. **Kein Push ohne Freigabe**, kein `--no-verify`, kein Zertifikat vor vollständig sauberem Stand.

---

## 5. Was noch zu bauen wäre (Vorschlag, nicht ausgeführt)

| Artefakt | Inhalt | Aufwand |
|---|---|---|
| `tests/test_invariants.py` | maschinenprüfbare Invarianten 2, 3, 5, 7, 8, 9 alspytest-Tests; je mit Negativprobe | ~1–2 Std. |
| `AGENTS.md`-Abschnitt | Regeln §4 **vor** jeder Session, mit Link hierher | ~15 Min. |
| Eigener Contract `archon.core → archon.routers` | nach A1 faktisch grün; in A2/F5 anlegen | ~15 Min. |
| Ratchet für `import main`-Rückwärts-Imports (#3) | gleicher Mechanismus wie S1, nur `archon/routers/**` | ~30 Min. |
| Characterization-Suite CC-246 | `default_agent_node_executor` hat nur **4 direkte V-Tests**; E2E nutzt `mock_exec` und charakterisiert den Executor gar nicht (`ANALYSIS_GOD_OBJECTS.md` Anhang D.4 #4) | ~½ Tag |
| `_ROUTER_LOAD_ERRORS` / Startup-Hook-Tests (#7) | Reihenfolge, Fail-Fast, Shutdown-`reversed()` | ~½ Tag |

---

## 6. Ehrliche Grenzen

- **100 % Schutz gibt es nicht.** Ein Agent kann immer neue Module außerhalb der Invarianten anlegen. Aber der **Blast-Radius** sinkt, weil jede neue Datei sofort im Ratchet, im Changed-Files-Gate und in der Full-Suite landet.
- **Invarianten veralten.** Jede braucht einen Beleg-Pfad **und** ein Datum; bei bewusster Änderung muss dieses Dokument mitgezogen werden, sonst wird es selbst zur Doku-Drift (`domain_09.md` M7 als warnendes Beispiel).
- **Prozess schlägt Technik.** Die wirksamste Härtung in diesem Projekt war nicht ein Scanner, sondern Ownership + unabhängige Verifikation. Das lässt sich nicht in `ci.yml` gießen.

---

## Anhang: Beleg-Dateien

`audit_reports/HANDOFF_HY4_DEBUG_2026-11-25.md` · `audit_reports/ANALYSIS_GOD_OBJECTS.md` · `audit_reports/S1_IMPORT_DEBT_DETAIL.md` · `audit_reports/S1_IMPORT_CONTRACT_REPORT.md` (Worktree) · `audit_reports/F1A_IMPORT_DEBT_REPORT.md` (Worktree) · `audit_reports/domain_09.md` · `audit_reports/fix_w3_d_trajectory_dag.md` · `audit_reports/INCIDENT_2026-11-25_LOGIN_OUTAGE.md` · `.github/workflows/ci.yml` · `scripts/audit_secrets.py` · `tests/test_unbound_calls.py` · `tests/test_import_layer_contracts.py` (Worktree)

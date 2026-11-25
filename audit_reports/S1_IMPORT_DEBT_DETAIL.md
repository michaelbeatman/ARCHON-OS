# S1 — Detailanalyse der 23 `backend → archon.routers`-Verstöße

**Erstellt:** 25.11.2026 · **Agent:** Hy4 · **Status:** **Reine Analyse, kein Code geändert**
**Basis:** `2ee92706` (Produktivcode in Hauptbaum und Worktree identisch; S1 hat keine Produktivdatei angefasst)
**Zweck:** Entscheidungsvorlage für Antigravity — „Können wir die 23 Verstöße fixen statt zu ignorieren?"
**Zugehörig:** `audit_reports/ANALYSIS_GOD_OBJECTS.md` §1.3 / D0 / D3, `.importlinter` im S1-Worktree, `audit_reports/S1_IMPORT_CONTRACT_REPORT.md`

> **Hinweis zum Ort:** Diese Datei liegt bewusst im **Hauptbaum** (`main`), damit Antigravity sie ohne Worktree-Wechsel prüfen kann. Sie ist `??` (untracked) und gehört **nicht** in den S1-Commit im Worktree.

---

## 1. Befundbasis

| Metrik | Wert |
|---|---|
| Importzeilen `backend → archon.routers.*` | **37** |
| Modul-Paare (in `.importlinter` dokumentiert) | **23** |
| Betroffene `backend`-Quellmodule | **8** |
| Davon in `backend/operations_api.py` | **16 Paare / 30 Zeilen** |
| Davon in 7 weiteren Modulen | **7 Paare / 7 Zeilen** |
| Importierte Einzelsymbole in den 14 `operations_*`-Blöcken | **~100** |
| Davon in `operations_api.py` tatsächlich verwendet (Stichprobe) | **1** (`TEAMS_DEFINITION`, `:944`) |

**Kernaussage:** Es handelt sich **nicht** um 23 gleichartige Verstöße. Es gibt 7 klar trennbare Typen mit sehr unterschiedlichem Aufwand. Der größte Brocken (14 Paare) ist **kein Logik-Problem, sondern eine falsch einsortierte Router-Registrierung**.

---

## 2. Klassifikation — die 7 Typen

| Typ | Paare | Natur | Wie falsch | Aufwand | Risiko |
|---|---:|---|---|---|---|
| **T1** Router-Aggregator-Inversion | **14** | `backend/operations_api.py:81` ist selbst `APIRouter(prefix="/api/operations")` und registriert 14 Unter-Router aus `archon/routers/` via `include_router` | Serviceschicht importiert HTTP-Schicht, nur um Router zu aggregieren; `backend` ist hier gar kein Backend | mittel (mechanisch, aber Reihenfolge = Pfad-Präzedenz) | 🟠 |
| **T2** Re-Exports (**NICHT tot** — siehe §9 #1) | (in T1 enthalten) | **125** Nicht-Router-Symbole, **28 aktive Test-Referenzen** (25 dynamisch per `__import__`+`getattr`). Jeder `operations_*`-Block braucht für die Registrierung nur `router as _x_router`; intern genutzt werden nur `TEAMS_DEFINITION` (`:944`) und `_get_org_hierarchy_file()` (`:4140`) | Namespa-Fassade ohne Nutzen; verschleiert, wer die Handler wirklich besitzt | gering, **aber Referenzsuche nötig** | 🟡 |
| **T3** Reine Pfadkonstante | **1** | `GUARDIAN_LIMITS_FILE` aus `archon/routers/autonomy_settings.py:30` | Eine Konstante wird aus einem Router geholt, obwohl `archon/core/paths.py` und `backend/platform_paths.py` existieren | trivial | 🟢 |
| **T4** Reine Helfer ohne HTTP-Bezug | **5** | `get_llm_prices`, `compact_session_core`, 3× `create_decision` |DB-/Dict-Funktionen ohne `Request`/`Response` liegen in Routern | gering–mittel | 🟢 |
| **T5** Auth / RBAC-Gates | **2** | `_rbac` (3 Symbole) + `get_current_user_from_request` | FastAPI-Dependencies und Request-Parser werden direkt aus der HTTP-Schicht importiert statt injiziert | mittel | 🟠 |
| **T6** Pydantic + Tool-Handler | **1** | `ImageGenerateToolRequest` + `api_tool_image_generate` aus `archon/routers/chat.py` | Request-Modell und Tool-Logik liegen im Chat-Router | mittel | 🟡 |
| **T7** Dokumentierter Bug / Workaround | **1** (in T4 enthalten) | `backend/llm_kernel.py:141-142`: *„backend.llm_prices existiert nicht — der ImportError wurde verschluckt, weshalb immer die statische 8-Modell-Tabelle galt"* | Der Router-Import ist eine **Notlösung für einen nie behobenen Bug**, kein Design | trivial + eigenständiger Bugfix | 🟢 |

---

## 3. Detailliste aller 23 Paare

| # | Quelle | Ziel | Zeile(n) | Symbol(e) | Typ | Wie falsch | **Sollzustand** |
|---:|---|---|---|---|---|---|---|
| 1 | `backend/agent_router.py` | `archon.routers.autonomy_settings` | `:307` | `GUARDIAN_LIMITS_FILE` | T3 | Pfadkonstante (`autonomy_settings.py:30` = `guardian_limits_path()`) aus Router; Kommentar :305-306 fordert selbst einen „gemeinsamen Pfad" | Konstante nach **`archon/core/paths.py`** (existiert) oder `backend/platform_paths.py`; Router importiert von dort |
| 2 | `backend/llm_kernel.py` | `archon.routers.llm_providers` | `:143` | `get_llm_prices()` (`llm_providers.py:298`) | T4 + **T7** | **Dokumentierter Bug**: `backend.llm_prices` fehlt, `ImportError` wurde verschluckt → statische Preistabelle galt immer. Router-Import ist Workaround | **`backend/llm_prices.py` neu anlegen** (Preis-SSOT), `get_llm_prices` dorthin; verschluckten `ImportError` durch harten Fehler ersetzen |
| 3 | `backend/mcp_gateway.py` | `archon.routers.context_meter` | `:569` | `compact_session_core()` (`context_meter.py:107`) | T4 | Reine `Dict`-Funktion ohne HTTP-Bezug liegt im Router | **`backend/context_compactor.py`** (existiert) — Funktion dorthin, Router konsumiert sie |
| 4 | `backend/operations_api.py` | `archon.routers._rbac` | `:29` | `forbid_viewer_writes`, `require_admin_or_503`, `require_session_actor` (`_rbac.py:144/:123/:57`) | T5 | FastAPI-`Depends`-Guards direkt aus HTTP-Schicht importiert; `operations_api.py:84` nutzt sie als `dependencies=[Depends(...)]` | RBAC-Kern nach **`backend/auth_service.py`**; Guards per **`_rbac.configure()`-Injektion** wie `main.py:3156-3157` (ein Injektionspunkt, fail-closed bei Importfehler) |
| 5 | `backend/operations_api.py` | `archon.routers.auth` | `:865` | `get_current_user_from_request()` (`auth.py:208`) | T5 | Request→User-Helfer aus Router; Fallback `except: return ""` ist fail-closed gewollt | **`backend/auth_service.py`** (existiert); `operations_api.py` importiert von dort |
| 6 | `backend/operations_api.py` | `archon.routers.operations_org` | `:4116`, `:4136` | 17 Symbole + `router as _org_router` | T1/T2 | Registrierung `router.include_router(_org_router)` :4141; nur `TEAMS_DEFINITION` wird wirklich genutzt (`:944`) | Registrierung → **`archon/routers/operations/__init__.py`**; `TEAMS_DEFINITION` → `backend/`-Konstantenmodul; Re-Exports nach Referenzsuche löschen |
| 7 | `backend/operations_api.py` | `archon.routers.operations_dag` | `:4148`, `:4159` | 8 `api_*` + Modelle + `router` | T1/T2 | dto. (`:4163`) | dto. |
| 8 | `backend/operations_api.py` | `archon.routers.operations_prompts` | `:4169`, `:4177` | 6 `api_*` + `router` | T1/T2 | dto. (`:4181`) | dto. |
| 9 | `backend/operations_api.py` | `archon.routers.operations_receipts` | `:4187`, `:4194` | 5 `api_*` + `router` | T1/T2 | dto. (`:4198`) | dto. |
| 10 | `backend/operations_api.py` | `archon.routers.operations_sysops` | `:4204`, `:4226` | 19 `api_*` + Modell + `router` | T1/T2 | dto. (`:4230`) | dto. |
| 11 | `backend/operations_api.py` | `archon.routers.operations_dunning` | `:4327`, `:4334` | 5 `api_*` + `router` | T1/T2 | dto. (`:4338`) | dto. |
| 12 | `backend/operations_api.py` | `archon.routers.operations_finetuning` | `:4344`, `:4348` | 2 `api_*` + `router` | T1/T2 | dto. (`:4352`) | dto. |
| 13 | `backend/operations_api.py` | `archon.routers.operations_approvals` | `:4360`, `:4372` | 10 `api_*` + `router` | T1/T2 | dto. (`:4376`) | dto. |
| 14 | `backend/operations_api.py` | `archon.routers.operations_keys` | `:4382`, `:4389` | 5 `api_*` + `router` | T1/T2 | dto. (`:4393`) | dto. |
| 15 | `backend/operations_api.py` | `archon.routers.operations_emails` | `:4401`, `:4411` | 8 `api_*` + `router` | T1/T2 | dto. (`:4415`) | dto. |
| 16 | `backend/operations_api.py` | `archon.routers.operations_security` | `:4421`, `:4431` | 8 `api_*` + `router` | T1/T2 | dto. (`:4435`) | dto. |
| 17 | `backend/operations_api.py` | `archon.routers.operations_bot_screen` | `:4444`, `:4454` | 7 Symbole (Modelle, `_bot_screen_state`, Handler) + `router` | T1/T2 | dto. (`:4458`); `_bot_screen_state` ist **globaler mutable State** (vgl. `domain_09.md` M8) | dto. + State in eigenen Store |
| 18 | `backend/operations_api.py` | `archon.routers.operations_autonomy` | `:4466`, `:4478` | 9 Symbole + `router` | T1/T2 | dto. (`:4482`) | dto. |
| 19 | `backend/operations_api.py` | `archon.routers.operations_pbd` | `:4490`, `:4503` | 10 Symbole + `router` | T1/T2 | dto. (`:4507`) | dto. |
| 20 | `backend/war_room_simulator.py` | `archon.routers.decisions` | `:61` | `create_decision` (`decisions.py:384`) | T4 | Reine DB-/HITL-Funktion aus Router; `asyncio.to_thread(create_decision, …)` :63 | **`archon/services/decision_service.py`** (neu) / `backend/decision_service.py`; 3 Konsumenten auf **einen** Service |
| 21 | `backend/workflow_dag_runner.py` | `archon.routers.decisions` | `:1035` | `create_decision` | T4 | dto., HITL-Gate im DAG-Hotpath :1038 | dto. |
| 22 | `backend/workflow_node_plugins.py` | `archon.routers.chat` | `:642` | `ImageGenerateToolRequest`, `api_tool_image_generate` | T6 | Pydantic-Request-Modell + Tool-Handler aus Chat-Router; wird in `backend/tool_runtime`-nahem Plugin genutzt | Modell → **`backend/contracts.py`** (neu), Logik → **`backend/tool_runtime.py`** (existiert); Router konsumiert beide |
| 23 | `backend/workflow_scheduler.py` | `archon.routers.decisions` | `:1116` | `create_decision` | T4 | dto., `require_hitl`-Event :1113 | dto. wie #20/#21 |

**Summe:** 23 Paare / 37 Zeilen / 8 Quellmodule. Alle Zeilenangaben gegen `2ee92706` verifiziert.

---

## 4. Sollzustand (Ziel-Architektur)

```
archon/routers/operations/__init__.py   NEU  — einziger Registrierungspunkt der 14 Router
                                              (Reihenfolge = Pfad-Präzedenz, wie main.py:3149-3150)
archon/routers/_rbac.py                      — bleibt, aber per configure() injiziert
archon/services/decision_service.py    NEU  — create_decision / register_decision (HITL, Vier-Augen)
archon/core/paths.py                        — GUARDIAN_LIMITS_FILE (existiert)
backend/contracts.py                   NEU  — gemeinsame Pydantic-Verträge (ImageGenerateToolRequest, …)
backend/llm_prices.py                  NEU  — get_llm_prices (behebt dokumentierten Bug T7)
backend/context_compactor.py                — compact_session_core (existiert)
backend/auth_service.py                     — get_current_user_from_request + RBAC-Kern (existiert)
backend/tool_runtime.py                     — api_tool_image_generate-Logik (existiert)
backend/operations_api.py                   — REINER SERVICE, kein APIRouter mehr;
                                              exportiert nur noch _get_kanban_connection u. a.
main.py:2752                                — `from backend.operations_api import router as
                                              operations_router` muss auf die neue Registrierung
                                              umgestellt werden
```

**Dann gilt:**
- `backend/**` enthält **0** Importe auf `archon.routers.*` → alle 23 `ignore_imports` werden zeilenweise gelöscht
- `.importlinter`: `ignore_imports` leer, `allow_indirect_imports` kann nach Tilgung des Core→Router-Pfads wieder auf **`false`** (streng transitiv)
- `tests/test_import_layer_contracts.py`: `test_documented_debt_is_bounded` von `<= 23` auf **`== 0`** stellen
- `lint-imports`: `1 kept, 0 broken`, **0 ignored imports**
- Der `archon`-interne Pfad `archon.core.orchestration:1432 → archon.routers.decisions` bekommt eine **eigene Regel** `archon.core → archon.routers` (S1-Neubefund, DELEGATED)

---

## 5. Empfohlene Reihenfolge (Quick-Wins zuerst)

| Schritt | Typ | Paare | Inhalt | Gate |
|---|---|---:|---|---|
| F1 | T3 + T4 + T7 | **6** | `GUARDIAN_LIMITS_FILE`, `get_llm_prices` (+ `backend/llm_prices.py` neu), `compact_session_core`, 3× `create_decision` → ein Service | Full-Gate |
| F2 | T5 + T6 | **3** | RBAC-Injektion, `get_current_user_from_request`, Bild-Modell/-Handler | Full-Gate |
| F3 | T2 | – | **Vollständige Referenzsuche** auf alle ~100 `api_*`-Symbole (Tests, `main.py`, Skripte); erst danach Re-Exports löschen | Analyse + Full-Gate |
| F4 | T1 | **14** | Registrierung nach `archon/routers/operations/__init__.py`, `main.py:2752` umstellen, Reihenfolge einfrieren | Full-Gate + Router-Health-Negativprobe |
| F5 | Cleanup | – | Ignores löschen, `allow_indirect_imports=false`, Debt-Test auf 0 | `lint-imports` + Full-Gate |

**Abhängigkeit:** F4 **nach** F3 (sonst fallen die Re-Export-Aufrufer weg, ohne dass man es merkt). F1/F2 sind unabhängig und können vorgezogen werden.

---

## 6. Risiken / Schutzregeln

| Risiko | Beleg | Maßnahme |
|---|---|---|
| **Router-Registrierungsreihenfolge = Pfad-Präzedenz** | `main.py:3149-3150`, `:3160-3209` | Reihenfolge 1:1 übernehmen; `_ROUTER_LOAD_ERRORS` + `_assert_router_health()` (`:3457`) fail-closed erhalten |
| `main.py:2752` holt den Router aus `backend.operations_api` | `read` | In F4 mit umstellen, sonst 404 bei `/api/operations/*` |
| **Re-Exports könnten von Tests genutzt werden** | `test_fix_batch14.py:45` (`_resolve_task_obsidian_rel`), `test_audit_fixes_batch.py:950` | F3: repo-weite Referenzsuche **vor** jedem Löschen; notfalls Kompatibilitäts-Fassade dokumentieren |
| `create_decision` trägt HITL-/Vier-Augen-Semantik | `archon/routers/decisions.py:279` `register_decision`, `:802-897` `require_session_actor` | Service muss `created_by`, CAS-Marker, HITL-Proof unverändert übernehmen |
| `_bot_screen_state` / globale mutable States | `domain_09.md` M8, `operations_bot_screen.py:4447` | Nicht blind verschieben; eigener Store mit Lock/Scope |
| Pre-Commit-Secret-Hook | Baseline-Commit `2ee92706` | Keine `--no-verify`; keine `.env` / `data/memory.db` / Audit-Kette anfassen |
| Testläufe | `INCIDENT_2026-11-25_LOGIN_OUTAGE.md` | **`ARCHON_DATA_DIR=<temp>`**, nie `./data` |
| NEVER_DO | Handoff §2 | Kein Coroutine-Replay, keine PostgreSQL-Migration |

---

## 7. Prüffragen für Antigravity

1. ~~**Sind die ~100 `api_*`-Re-Imports wirklich tot?**~~ → **von Antigravity beantwortet, §9 #1**: Nein. **125** Symbole, **28 aktive Referenzen**.
2. ~~**Gibt es externe Aufrufer auf `backend.operations_api.api_xyz`?**~~ → **beantwortet, §9 #1**: Ja — `test_rbac_admin_routes_paket2.py` (25) und `test_fix_batch7.py` (3). In **F3 umstellen**, dann löschen.
3. **Ist `archon/routers/operations/__init__.py` als einziger Registrierungspunkt mit der bestehenden Reihenfolge kompatibel** (Pfad-Präzedenz, `_rbac.configure()` vor den Routern)?
4. **`get_llm_prices`**: neues `backend/llm_prices.py` (wie der Kommentar in `llm_kernel.py:141` nahelegt) oder in `backend/llm_kernel.py` belassen? Was ist mit der statischen 8-Modell-Tabelle?
5. **`create_decision`** nach `archon/services/` oder `backend/`? (HITL/GoBD-Nähe, `domain_14.md` Decision-Service)
6. **Darf `allow_indirect_imports` nach Tilgung wieder auf `false`** (streng transitiv), oder soll die `archon.core → archon.routers`-Regel als eigener Contract mit eigenen Ausnahmen entstehen?
7. **Soll F1–F5 vor oder nach S2 (`main.py`) laufen?** F4 berührt `main.py:2752` und die Router-Reihenfolge → Überschneidung mit S2 (G4). Ownership-Kollision vermeiden.
8. **Ist die rote Phase (Nutzer-Vorgabe) oder das Ratchet (S1-Implementierung) gewollt?** Die Ignores bleiben bis zur Antwort bestehen.

---

## 8. Nebenbefunde aus dem S1-Full-Gate (von Antigravity mitzuprüfen)

Am 25.11. liefen im S1-Worktree drei Full-Gate-Läufe. **Lauf 1 war rot, Lauf 2 und 3 gruen** — Flakiness ist damit bestaetigt (1 rot / 2 gruen in Full-Suite, 6/6 gruen isoliert in beiden Baeumen). S1 bleibt bis zur G7/Antigravity-Bewertung **uncommittet**.

| Prüfung | Ergebnis |
|---|---|
| Full-Gate **Lauf 1** (`pytest tests/ -q`) | ❌ **1 failed** / 2342 passed / 20 skipped (4:59) |
| Full-Gate **Lauf 2** (zweiter Datenpunkt) | ✅ **2343 passed / 20 skipped / 0 failed** (3:38) |
| Full-Gate **Lauf 3 — FINALER Stand** nach Negativtest-Korrektur | ✅ **2343 passed / 20 skipped / 0 failed** (3:42) |
| Isolierte Checks des korrigierten Layer-Gates | ✅ pytest 5/5, `lint-imports` 1 kept / 0 broken, ruff 0, mypy 0 |
| `ruff --select F821`, `compileall`, `audit_secrets --all` (7095 Dateien) | ✅ in allen Läufen je 0 |

**Roter Test:** `tests/test_stage1_stage3_hardening_and_bus.py::test_dag_runner_schema_preserved_and_event_driven_recovery` — erwartet `fast_recover` vor `slow` (event-driven Ready-Queue, kein Wave-Barrier), erhielt `['fast', 'slow', 'fast_recover']`. **A/B-Eingrenzung: isoliert 6/6 grün** (3× Worktree mit S1, 3× Hauptbaum `2ee92706` ohne S1, je 1,7–3,1 s); im Baseline-Gate vor S1 ebenfalls grün → **flaky unter Full-Suite-Last / State-Leak-Verdacht, nicht S1-verursacht** (S1 hat keine Produktivdatei berührt; nur `.importlinter`, ein Test und der Report). Auffällig: **16 → 20 skipped** zwischen Baseline und Worktree.

**Echter Nebenbefund im Log:** `backend/workflow_dag_runner.py:1763` → `Kostenberechnung fehlgeschlagen: unsupported operand type(s) for +=: 'NoneType' and 'float'`. `:1764` setzt `_cost_usd = None` (D12-Kommentar: bewusst kein `0.0` als realer Wert), ein Aggregator weiter unten addiert darauf. Vorbestehend, nicht testrelevant, aber ein echter Fehler im Kostenpfad — ausserhalb S1-Ownership, nicht angefasst.

**Eskalation:** Nach dem Ownership-Modell (`fix_w3_d_trajectory_dag.md:121-127`) werden rote/obsolete Tests **eskaliert, nicht geskippt, gelöscht oder umgeschrieben**. Bitte mitbewerten: Ist der Test flaky oder liegt ein State-Leak vor (Trace-ID `4444…`, DLQ-Retry im Log)? Soll der Kostenpfad separat gefixt werden? Ein gruener zweiter oder dritter Full-Gate-Lauf gilt **nicht** als Behebung.

**Zusätzlich:** Die unabhängige S1-Verifikation fand **1 Abweichung** — der Negativtest im neuen Layer-Gate war tautologisch (ausgerechnet der Test gegen Theater-Gates war selbst einer). Behoben: `_imports_from_tree()` / `_violations()` sind jetzt gemeinsame Hilfsfunktionen von Produktiv-Gate und Negativprobe. Alle übrigen Prüfpunkte (1/2/4/5/6) vollständig verifiziert, 0 Abweichungen. Siehe `audit_reports/S1_IMPORT_CONTRACT_REPORT.md` §5.4 im Worktree.

---

## 9. Antigravity-Verifikation (25.11., read-only) — Ergebnisse & Korrekturen

Antigravity hat Detailliste, S1-Report, `.importlinter`, den Test, das Dossier und alle 23 Importstellen gegen den Code geprüft. **Ergebnis: alle 23 Paare fixbar, Klassifikation T1–T7 stimmt im Kern, S1 technisch korrekt.** Die folgenden Befunde **korrigieren §2/§3/§5/§7** und sind vor F1–F5 zu berücksichtigen.

| # | Befund | Korrektur / Auswirkung |
|---|---|---|
| 1 | **125** re-exportierte Nicht-Router-Symbole (nicht „~100"), **28 aktive Test-Referenzen** | §2/§3/§7 Q1 überholt: **nicht tot**. 25 Referenzen dynamisch per `__import__('backend.operations_api')` + `getattr(...)` in `tests/test_rbac_admin_routes_paket2.py:87-111, :190-194`; 3 direkt in `tests/test_fix_batch7.py:133-138` (`abort_bot_screen_execution`, `ScreenInteractionModel`, `interact_with_bot_screen`). Intern genutzt: nur `TEAMS_DEFINITION` (`:944`) und `_get_org_hierarchy_file()` (`:4140`, für `ORG_HIERARCHY_FILE`). **F3 = 2 Testdateien auf `archon.routers.operations_*` umstellen, DANN die 125 Re-Exports löschen.** Blindes Löschen bricht Tests. |
| 2 | **Zweiter Bug in `llm_kernel.py:145-149`** | `get_llm_prices()` liefert `{"status":"ok","prices": formatted}` mit Keys `prompt_1m`/`completion_1m` (`llm_providers.py:283-293`). `llm_kernel.py` prüft aber `if model in prices` (ohne `["prices"]` auszupacken) und sucht `input`/`prompt_per_1m`. **Live-Preise greifen nie.** Muss in **F1 mitgefixt** werden, nicht nur verschoben. |
| 3 | `get_llm_prices` auch von `chat.py` und `main.py` genutzt; Single-Flight-Cache `_openrouter_price_lock` (`llm_providers.py:254-295`) | `backend/llm_prices.py` als neues Modul **bestätigt**; `_FALLBACK_MODEL_PRICES_PER_1M` in `llm_kernel.py` bleibt als Offline-Fallback. |
| 4 | `create_decision` → **`archon/services/decision_service.py`** (nicht `backend/`) | `archon/core/orchestration.py:1432` braucht es ebenfalls; `backend/` würde die nächste `archon → backend`-Abhängigkeit erzeugen. `archon/services/` existiert (`mission_sync.py`, `profiles_service.py`). **Achtung:** `decisions.py:396-403` macht `import main as app_main` für `_decision_self_api` → beim Extrahieren entkoppeln, mit **S2** abstimmen. |
| 5 | `main.py:2054/2069` importiert `ImageGenerateToolRequest` / `api_tool_image_generate` | **F2** muss `main.py` doch mit umstellen (Re-Export in `chat.py` oder direkte Umstellung). §5/§7 Q7 entsprechend korrigiert. |
| 6 | **F4 ↔ S2 Kollision bestätigt** | `main.py:2752`, `:3149-3150`, `_rbac_configure` `:3156-3157`, `_assert_router_health` `:3457-3486`. Reihenfolge der 14 Router (`org → dag → prompts → receipts → sysops → dunning → finetuning → approvals → keys → emails → security → bot_screen → autonomy → pbd`) 1:1 in `archon/routers/operations/__init__.py` übernehmen, `try/except` + `_ROUTER_LOAD_ERRORS` erhalten → Pfad-Präzedenz + Fail-Closed bleiben. **F1/F2/F3 vor S2 möglich; F4 nach/koordiniert mit S2; F5 nach F1–F4 UND nach Tilgung `orchestration:1432`.** |
| 7 | Eigener Contract `archon.core → archon.routers` **+ `allow_indirect_imports` erst NACH Tilgung auf `false`** | Sonst schlägt der bestehende transitive Pfad wieder im `backend`-Contract zu. |
| 8 | **Ratchet bestätigt** (§7 Q8) | Eine rote Phase würde jedes Zwischen-Gate bis S3 blockieren (`ci.yml:305/:555`). `test_documented_debt_is_bounded` (≤23) + `test_every_ignored_import_actually_exists` deckeln die Altschuld hart. |
| 9 | **`config/kanban_meta.json` im Worktree `M` (+43/−2)** | Testlauf-Seiteneffekt (Worktree war beim Erstellen sauber). **Darf nicht in den S1-Commit.** Vor dem Commit `git restore config/kanban_meta.json`. |
| 10 | Flaky-Test + Kostenbug bestätigt | `test_stage1_stage3_hardening_and_bus.py:775-785`: enges `asyncio.sleep(0.15)` gegen `0.01s` + SQLite-Recovery → Timing-Race. `workflow_dag_runner.py:1753-1765`: `_cost_usd = None` im `except` → separater Fix unter Wahrung der D12-Semantik. **Beide bleiben DELEGATED und werden NICHT in F1–F5 hineingezogen.** |

**Damit sind §7 Q1/Q2/Q4/Q5/Q6/Q7/Q8 beantwortet**, Q3 (Router-Reihenfolge) in #6 bestätigt. Diese Fassung ist die Grundlage für F1–F5.

---

## 10. F1a ausgeführt (25.11., Branch `s1-god-objects`, Commit `69f5626e`)

**2 der 23 Paare getilgt → 21 verbleibend.** §1–§9 bleiben als historische Analyse unverändert gültig; die **aktuellen** Zahlen stehen hier.

| Paar | Maßnahme |
|---|---|
| `backend.agent_router → archon.routers.autonomy_settings` | `GUARDIAN_LIMITS_FILE` → `archon/core/paths.py` (SSOT); Re-Export in `autonomy_settings.py` hält `guardian.py` und `test_fix_w3_a_orchestration.py:207` grün |
| `backend.llm_kernel → archon.routers.llm_providers` | `get_llm_prices` → neues **`backend/llm_prices.py`** (Cache, Single-Flight-`threading.Lock`, `get_price_cache()`-Accessor); Re-Export in `llm_providers.py` hält `main.py:1093` und `chat.py:50` **unverändert** |

**Zusätzlich behoben (Antigravity §9 #2):** `llm_kernel.py:145-149` packte `result["prices"]` nie aus und suchte `input` / `prompt_per_1m` statt `prompt_1m` / `completion_1m` → **Live-Preise griffen nie**. Jetzt `status == "ok"` + korrekte Keys, ehrlicher Fallback auf die statische Tabelle. **4 Characterization-Tests** neu (`tests/test_f1a_llm_prices.py`).

**Gate:** isoliert **29 passed** · `lint-imports` **1 kept / 0 broken, 21 ignored imports** · mypy 0 · Full-Suite **2347 passed / 20 skipped / 0 failed** (3:25) · `ruff F821` / `compileall` / `audit_secrets --all` (7098 Dateien) je 0.

**F1b (4 Paare) ist kein Quick-Win** — siehe `F1A_IMPORT_DEBT_REPORT.md` §8: `create_decision` ist eine **dokumentierte Injektionsarchitektur** (`archon/core/permissions.py:6-14` `set_decision_factory`, `chat.py:63-77` `_DEPS`, `orchestration.py:1397`, Vier-Augen/`created_by` fail-closed). Antigravitys Empfehlung `archon/services/decision_service.py` würde dieses Design auflösen → **Design-Entscheidung vor Code-Change nötig**. `compact_session_core` hängt an `archon.core.state_db` und gehört nach `archon/services/`, nicht `backend/`.

**Offen vor einem Push:** `ci.yml:459-460` Changed-Files-Ratchet → **24 vorbestehende** Ruff-Funde in den 6 angefassten Dateien (A/B belegt: Baseline `07979512` = 26, F1a = 24, **keine neuen**). Separater Cleanup-Commit nötig; bewusst nicht in F1a gemischt. **Kein Push.**

Ausführlicher Schritt-Report: `<WT>\audit_reports\F1A_IMPORT_DEBT_REPORT.md` (im Worktree, committet in `69f5626e`).

---

**Ende der Analyse.** Keine Code-Änderung, keine Änderung an `.importlinter`, kein Commit, kein Push, kein Testlauf für dieses Dokument.

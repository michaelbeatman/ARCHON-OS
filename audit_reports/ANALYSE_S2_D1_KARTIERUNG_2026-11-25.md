# ANALYSE — S2 / D1-Kartierung (frische Session, 25.11.2026)

**Status:** Reine Analyse. Kein Code angefasst, kein Commit, kein Push.
**Basis:** Worktree `s2-s4-monolithen`, Branch von `ee18373a` (S1-Endstand), Working Tree sauber.
**Quelle der Reihenfolge:** `ANALYSIS_GOD_OBJECTS.md §5:409` (vom Nutzer festgelegt) → `S1 → B(D1) → S2(D2) → S3 → S4`.
Damit ist die in `HANDOFF_S2_S4_MONOLITHEN_2026-11-25.md §10` offengelassene Frage
(„D1 oder D2/2a zuerst?") **bereits durch das Dossier entschieden: D1 zuerst.**
`§5:387` begründet: „Characterization-Tests zuerst … Reihenfolge bleibt (Risiko × Testabdeckung)".

---

## 1. Baseline-Gate (verifiziert, nicht nur behauptet)

| Check | Kommando | Ergebnis |
|---|---|---|
| ruff (changed, 5 Dateien) | `ruff check --select E,F,I --ignore E501 $F` | `All checks passed!` EXIT 0 |
| lint-imports | `lint-imports --no-logo` | **2 kept / 0 broken**, 287 Dateien / 992 Dependencies, EXIT 0 |
| mypy (changed) | `mypy --config-file mypy.ini $F` | 5/0, EXIT 0 |
| mypy (full CI-Pfade) | `mypy … archon backend main.py core_dispatcher.py scripts utils` | **410/0**, EXIT 0 |

Diff `HEAD^..HEAD` = `archon/routers/operations_org.py`, `backend/operations_api.py`,
`main.py`, `tests/test_fix_batch7.py`, `tests/test_rbac_admin_routes_paket2.py`
→ exakt die S1-Abschlussdateien. Bestätigt den richtigen Basispunkt.

Env: `ARCHON_TEST_DB_ISOLATION=1`, `ARCHON_DATA_DIR=…\Temp\opencode\archon-s2-baseline`.
Log: `…\Temp\opencode\s2-baseline-gate.log` (außerhalb des Repos → Tree bleibt sauber).

**Noch nicht gelaufen** (bewusst, da kein Split existiert): pytest 2355/20/0, compileall,
`audit_secrets --all`, bandit, pip-audit, Pflicht-Smoke (799 Pfade). Diese gehören zum
Full-Gate **nach** dem ersten Commit, nicht zur Baseline-Analyse.

---

## 2. Korrekturen gegenüber dem Handoff (Zeilennummern neu verifiziert)

Das Handoff warnt selbst davor (§4, „Achtung"). Realität auf `ee18373a`:

| Symbol | Handoff | Verifiziert | Delta |
|---|---|---|---|
| `_ROUTER_LOAD_ERRORS` | `:592` | **`:600`** | +8 |
| `_assert_router_health()` | `:3229` | **`:3237`** | +8 |
| `_guards_configure`-Block | `:2916-2928` | **`:2926-2932`** | +10 |
| `_STARTUP_HOOKS.insert(0, …)` | – | **`:3266`** | – |
| `_FAIL_FAST_HOOKS` | – | **`:622`**, genutzt `:791` | – |
| `_SHUTDOWN_HOOKS` `reversed()` | – | **`:798`**, `extend` `:2904` | – |
| `main.py` Länge | 2919 Z. | **> 3266 Z.** | Datei länger als Dossier/Handoff |

`ANALYSIS §Anhang D.5` nennt ohnehin 3.638 Zeilen für den Analysezeitpunkt; die
2919 im Handoff sind ein anderer Zählzeitpunkt. **Vor jedem Split neu messen, nicht aus
Dokumenten übernehmen.**

`default_agent_node_executor`: Dossier `:1211` → real **`:1219`**. Bei `:1211` liegt der
`except` von `reserve_tokens` in `_dispatch_with_node_budget`. Die Facade endet bei **`:1811`**
(≈ 593 Zeilen), nicht bei einem kompakten Block.

---

## 3. Neuer Befund: `archon/core/provider_registry.py` existiert bereits

**Steht so nicht im Handoff.** Es ist ein Kompatibilitäts-Shim, der exakt für D2/2a
(„~50 `app_main.*`-Symbole heben + ≥90 Rückwärts-Imports umstellen") gebaut wurde:

- `get(name)` Fallback-Kette: registrierter Wert → `getattr(main, name, main)` → `main`-Modul
  (lazy `importlib.import_module("main")`, also Cold-Start-Verhalten unverändert).
- `register(app, name, value)` schreibt in `app.state.archon_provider_registry`, `RLock`-geschützt.
- `get_provider = get` (lesbarer Alias).

**Bereits umgestellt (verifiziert):**
| Datei | Stellen | Anmerkung |
|---|---|---|
| `archon/routers/gateway.py:18` | **12** `get_provider("app_main")` | Docstring nennt 13 → eine Differenz, vor 2a klären |
| `backend/operations_api.py:24` | **9** `get_provider("app_main")` | nur `broadcast_event`, hinter `hasattr`-Guards |
| `tests/test_fix_w2_c_governance_roles.py:97` | 1 Negativprobe | `monkeypatch.setattr(ops, "get_provider", lambda name: None)` |

**Noch direkt `import main as app_main`** (Auszug aus ~100 `app_main.*`-Referenzen):
`decisions.py` (sehr viele, ~20 `import`-Stellen), `quickchat.py`, `hr.py`, `telemetry.py`,
`gateway.py`-Docstring-Nachbarn, `agent_chat.py`, `core_settings.py`, `docker_services.py`,
`container_ops.py`, `ui.py`, `mesh.py`, `research.py`, `prompts.py`, `telegram.py`,
`hermes_proxy.py`, `hermes_ops.py`, `updater.py`, `autonomy_settings.py`, `documents.py`,
`archon/services/mission_sync.py`.

→ **Konsequenz für 2a:** kein Big-Bang-Umstellen nötig. Der Shim erlaubt einen
inkrementellen, verhaltensneutralen Pfad: Provider einzeln registrieren, Konsumenten
einzeln auf `get_provider` umstellen, pro Schritt 1 Commit + Full-Gate. Das ist deutlich
risikoärmer als die im Handoff skizzierte „≥90 Imports in 1 Commit"-Variante.
**Ownership:** `archon/core/provider_registry.py` → **G4** (App-Owner, `§4`), nicht G3.

---

## 4. D1 — Verzweigungsmatrix `default_agent_node_executor` (aus echtem Code)

Facade `:1219-1811`. Golden-Output-Felder (`:1778-1800`):
`status, node_id, agent_id, model, content, error, input_tokens, output_tokens,
kanban_task_id, cost_usd, cost_unverified` + optional `quality_score, quality_report,
revisions_used, deliverable_path, tool_trace, parsed_output`.

| # | Branch / Cluster | Code | Golden-Output (Status / block_kind / Extras) | Test heute |
|---|---|---|---|---|
| 1 | `research` | `:1246-1247` | delegiert an `_execute_research_dag_node` | **keiner** |
| 2 | Node-Plugin (ffmpeg/kinocut/tts/suno/image_gen/calendar_publish/3rd-Party) | `:1250-1279` | `pres` + `node_id/agent_id/kanban_task_id`; Kanban `done` oder `blocked`+`workflow_error` | 1 V (`test_stage1…:405`) |
| 3 | `media_render` / `clip_matrix` | `:1282-1344` | `media_matrix`, `content`=JSON; Exception → `status=error`, `block_kind=workflow_error` | 1 V (`:384`) |
| 4 | Profil-Auflösung + Prompt-Bau (`voice.md`, `allowed_tools`, `map_item`, upstream) | `:1227-1417` | `full_prompt`, `eff_system_prompt` (nur indirekt im Dispatch-Mock sichtbar) | **keiner** |
| 5 | Initial-Dispatch + Node-Budget / Trajectory-Token-Cap | `:1427-1445`, `:1195-1216` | `block_kind=node_budget` / `TRAJECTORY_TOKEN_CAP` / `NODE_TOKEN_BUDGET_EXCEEDED` | **keiner** |
| 6 | Multi-Turn Tool-Loop (`max_turns` 1–6, `allowed_tool_set`, Hop-Cap, Checkpoint, Followup) | `:1451-1566` | `tool_trace[]`, `is_error` bei Followup-Fehler | 1 V (`:349`) |
| 7 | Schema-Validierung + 1 Repair-Retry + Frontier-Eskalation | `:1568-1658` | `parsed_output` oder `error="Output-Schema-Verletzung: …"` | 1 V (`:740`, nur Repair-Erfolg) |
| 8 | Anti-Slop / Self-Critique (Content + Quality-Gate, `max_revisions`, `min_quality_score`) | `:1660-1732` | `quality_score`, `quality_report`, `revisions_used`; JSON darf **nicht** durch Prosa überschrieben werden | 1 V (`:740`, nur Schutz) |
| 9 | Deliverable-Export (Showroom/Obsidian `03_Endprodukte`) | `:1734-1752` | `deliverable_path` | **keiner** |
| 10 | Kosten (`_cost_usd = None` bei Fehler, D12!) + Kanban-Final + Return | `:1754-1811` | `cost_usd`, `cost_unverified`, `block_kind=workflow_error` | **keiner** |

**Vereinfachungs-Falle D12 ist real und live:** `:1755 _cost_usd = None`, `:1766 _cost_usd += …`
(funktioniert nur, weil `_est_cost` im `try` nie `None` zurückgibt und `+=` auf `None`
sonst `TypeError` wirft → except setzt zurück auf `None`). **Nicht „bereinigen"** — genau
dieser Pfad ist in `INVARIANTS §3` als Falle markiert. Jeder Extraktions-Commit muss
`cost_unverified=True` bei Fehler als Golden-Output festnageln.

**`§5:387`-Aussage bestätigt:** `test_workflow_dag_e2e.py` nutzt durchgehend
`executor_fn=mock_exec` / `clean_exec` / `slop_exec` / `failing_exec` — der echte Executor
wird **nie** aufgerufen. Die 4 V-Tests in `test_stage1_stage3_hardening_and_bus.py`
(`:349, :384, :405, :740`) sind die einzige echte Abdeckung.

---

## 5. S-Tests, die vor dem ersten Split eskaliert werden müssen (G7, nicht löschen)

`ANALYSIS §Anhang D.2` + `§6 #5`. Für D1 relevant (Patchen/Bewegen bricht sie bei
identischem Verhalten):

- `test_workflow_dag_e2e.py:247` (S-Anteil)
- `test_fix_w3_b_performance.py:173/:204/:384/:388/:393/:401/:421` — u. a.
  `:419 assert "block_kind = 'budget_allocation_failed'" in helper` (reiner Source-Text)
- `test_fix_w3_d_trajectory_dag.py:49/:208`
- `test_orange_b_f14.py`, `test_reaudit_stage7.py:62/:77`, `test_audit_p1_governance.py`
- `test_med2_a_dispatch.py:88/:180/:190/:202/:228`
- `test_fix_batch5.py:102`, `test_fix_batch13.py`, `test_fix_batch15.py:58`
- `test_p1_multiagent_hardening.py:32`, `test_reaudit_stage12.py:15`

**Ausnahme behalten:** `tests/test_unbound_calls.py` (erkennt vergessene Importe nach Extraktion).
**Rote/blockierte Tests (nicht als Characterization zählen, eskalieren):**
`test_show_hn_blockers.py:55`, `test_jev_router.py:75-77`, `test_graceful_shutdown.py:100`.

---

## 6. Empfehlung für den ersten echten Schritt (noch nicht ausgeführt)

Reihenfolge laut `§6 #9` + `§5:387`: **Golden-Tests VOR dem ersten Split-Commit grün.**

1. **Schritt B0 (Test-Only, 1 Commit, Full-Gate):** Neue Datei
   `tests/test_d1_executor_characterization.py` mit einer Verzweigungsmatrix für die
   10 Cluster. Pro Branch ein Golden-Output gegen **die echte Logik** (Dispatch gemockt,
   Executor real aufgerufen — nicht `executor_fn=mock_exec`). Jeder Test braucht eine
   **Negativprobe** (`INVARIANTS §4.5`), die gegen die echte Logik rot werden kann.
   Kein hartcodiertes Snippet, gemeinsame Hilfsfunktionen (Handoff §5.6).
2. **Schritt B1..B10:** je **ein** Cluster, **reine Extraktion, keine Logikänderung**,
   1 Commit + Full-Gate. Facade `default_agent_node_executor` bleibt importierbar,
   Ziel-CC der Facade < 20 (`§8`).
3. Erst danach S2/D2 (mit dem `provider_registry`-Shim inkrementell).

**Offen vor B0 (bewusst NICHT eigenmächtig entschieden):**
- G7-Umstellung der S-Tests: separater Schritt vor B1 oder parallel zum Test-Owner?
  (`§6 #5` verlangt „vor Schritt 2/4", `§4` macht den Test-Owner zur eigenen Rolle).
- `_get_ops_deps()` 6-Tupel-Entscheidung gehört zu S3, nicht zu D1 — aber
  `§5:397` warnt: D1 berührt `_get_kanban_connection` (`:965`) → Patch-Punkt vor D3 sichern.

---

## 6b. B0-Ergebnis — verifizierte Korrekturen durch echte Negativproben

`tests/test_d1_executor_characterization.py` (17 Tests, alle grün). Die ersten
Läufe waren **absichtlich nicht** durch Verbogener-Assertions „grün gemacht",
sondern das echte Verhalten wurde festgenagelt. Drei Befunde korrigieren die
Dossier-Annahmen:

1. **D12 ist der Normalfall, nicht der Fehlerfall.** `:1755 _cost_usd = None` +
   `:1766 _cost_usd += _est_cost(...)` wirft **immer**
   `TypeError: unsupported operand type(s) for +=: 'NoneType' and 'float'`.
   Der `except`-Zweig (`:1773-1777`) setzt `cost_usd=None, cost_unverified=True`
   auch ohne gemockten Preistabellen-Fehler. Weder `0.0` noch `False` sind
   real. → Genau die `INVARIANTS §3`-Falle: **nicht vereinfachen**, festnageln.
   Golden-Output + Negativprobe gegen `0.0` und gegen `False`.

2. **`token_budget` blockiert NICHT den ersten Dispatch.** `_dispatch_with_node_budget`
   ruft `_node_budget_ok(node, {"input_tokens":0,"output_tokens":0}, …)` **vor**
   dem Dispatch (`:1196`, `:1427-1428`) → `used=0` ist immer unter jedem Cap.
   Der Block greift erst bei **Folge-Dispatchen** (Tool-Loop `:1542`,
   Repair `:1596`, Eskalation `:1631`, Revision `:1701`), weil dort `res`
   akkumulierte Tokens enthält. Charakterisiert mit `token_budget=5` +
   Tool-Loop: 1. Dispatch success, 2. Dispatch → `NODE_TOKEN_BUDGET_EXCEEDED`.

3. **Media-/Plugin-Branches haben KEINE Kosten-Felder.** Sie returnen bei
   `:1274` / `:1320` / `:1338` **vor** dem Kostenblock `:1754-1790`.
   `cost_usd` / `cost_unverified` fehlen im Dict (nicht `None`). Ein Split,
   der den Return vereinheitlicht, würde hier still Verhalten ändern.

Weitere verifizierte Details: `:1323` nutzt `node.get("agent_id") or
"media_engine"` → mit gesetztem `agent_id` bleibt es `"default"`, der
`media_engine`-Fallback greift nur ohne `agent_id`. `api_get_hermes_profiles`
läuft über `asyncio.to_thread` (synchron zu mocken), `generate_video_clip_matrix`
wird direkt `await`ed (AsyncMock), `evaluate_asset_quality` ist synchron.

**Negativproben-Mechanik selbst gegenprobe-geprüft:** `_negativprobe`
weigert sich mit `AssertionError`, wenn der „falsche" Wert dem echten entspricht
(„Gate wäre Theater"), und wird bei echter Abweichung rot. Kein hartcodiertes
Snippet, gemeinsame Helper (`_run`, `_golden`, `_assert_golden`, `_negativprobe`).

### B0 Full-Gate (vor Commit, alle EXIT 0)

| Check | Ergebnis |
|---|---|
| ruff `--select E,F,I --ignore E501` (nur neue Datei) | `All checks passed` |
| mypy (neue Datei) | 1/0 |
| lint-imports | 2 kept / 0 broken |
| mypy full | 410/0 |
| **pytest full** | **2372 passed / 20 skipped / 0 failed** (2355 + 17) |
| compileall | 0 |
| `audit_secrets.py --all` | 7108 Dateien, keine Secrets |
| bandit `-q -lll` | 0 |
| pip-audit | no known vulnerabilities |
| `git restore -- config/kanban_meta.json` | ausgeführt (Test-Rauschen, Regel #3) |

---

## 6c. B0b — Pflichtmaessiger zweiter Blick (`INVARIANTS §4.6`) und seine Folge

Eine **frische, unabhaengige Instanz** hat `69936e5d` reviewt (rein lesend, kein
Shell, kein Write) und einen **schwerwiegenden echten Bug** gefunden. Damit hat
sich `§4.6` erneut bestaetigt: *„Dieses Repo hat jeden kritischen Fund durch eine
unabhaengige Instanz gefunden, nie durch den Autor des Fixes."*

**Fund:** `_golden()` lieferte `{k: out.get(k) for k in expected}` — also die
**Ist-Werte** statt der deklarierten **Soll-Werte**. `_assert_golden` wurde damit
zur `X == X`-Tautologie; alle 8 positiven Golden-Assertions waren
**Theater-Gates** nach `§4.5`. „17 Tests gruen" war im Kern ein Artefakt. Die
Negativproben prueften nur den Helper, nie die deklarierten Werte; ein fehlendes
Feld (`out.get` → `None != bogus`) waere ebenfalls gruen geblieben.

**Behoben (B0b):**
- `_golden` liefert jetzt `expected` (SOLL) und assertiert zusaetzlich
  `set(expected).issubset(out)` → ein verschwundenes Feld wird erkannt.
- `_negativprobe` assertiert `field in out` (schliesst die `None`-Luecke).
- **Meta-Test** `test_meta_golden_layer_can_actually_fail`: beweist, dass
  `_assert_golden` rot werden kann und `_golden` SOLL liefert. Damit kann der
  Helper nicht unbemerkt zur Tautologie regressieren.
- Wirksamkeits-Gegenprobe (ausgefuehrt): Mutation von `content` im echten Output
  → `AssertionError`; Mutation von `agent_id`/`model`/`task_id` im
  Dispatch-Payload → jeweils `AssertionError`.

**Nachgezogene Lücken** (Review-Auftraege 3–4, 14 neue Tests, **32 gesamt**):
- **Querschnitt:** Dispatch-Payload (`agent_id`, `agent_name`, `role`, `model`,
  `reasoning_level`, `task_id`, `prompt`, `system_prompt`) per `await_args_list`
  charakterisiert. `_run(..., capture=...)` exponiert die Mocks.
- **C4 (groesste Luecke, ~190 Z.):** Profil-Matching, `system_prompt`/`model`/`role`
  aus Profil, `{{item}}`-Substitution, `expected_output`, `allowed_tools`,
  `forbidden_actions`, `map_item`, Upstream-Trunkierung `[:4000]`, `voice.md`.
- **C1:** Rueckgabe-Vertrag (unveraendert, kein Merge), `set(out) == set(return)`.
- **C2:** `pres`-Merge + Kanban `in_progress → done` inkl. `event_kind`/`block_kind`.
- **C3:** `generate_video_clip_matrix`-Call-Args + Upstream-Text-Merge.
- **C5:** `TRAJECTORY_TOKEN_CAP` + `_blocked_node_result`-Shape; EUR-Cap.
- **C6:** `reserve_hop`/`TRAJECTORY_HOP_CAP` (ToolRuntime nicht gerufen),
  Followup-Status-Fehler.
- **C7:** **Frontier-Eskalation** (`:1619-1653`) — vorher 0 Tests.
- **C8:** `else`/`while`-Revisionsschleife (`:1677-1730`) — lief vorher nie.
- **C9:** `deliverable_path` + Datei-Write, mit `PROJEKTE_DIR`-Isolation.
- **C10:** Erfolgs-Kanban-Final + alle 11 Pflicht-Return-Felder.
- **Isolations-Korrektur:** `test_c8` hatte `channel="linkedin"` → der
  Deliverable-Block schrieb **real** in `PROJEKTE_DIR`; jetzt auf `tmp_path`.

**Governance-Befund des Reviewers:** `INVARIANTS.md` ist im Worktree **nicht**
vorhanden (im Hauptbaum `?? audit_reports/INVARIANTS.md`, also untracked und
nicht Teil von `ee18373a`). Alle Zitate stammen aus dem Handoff/dem Dossier.
Die Datei wird bewusst **nicht** in den Worktree kopiert (Tagesstand des Nutzers,
Regel #9). Die angewandten Regeln sind ueber das Handoff belegt.

---

## 6d. S-Test-Impact fuer D1 (zweiter Agent, very thorough)

**Korrektur des Dossiers:** Der Brech-Mechanismus ist **nicht** `inspect.getsource`
(0 Treffer auf `workflow_dag_runner`), sondern `"..." in src` auf
`Path(...).read_text()` der **ganzen** Datei plus ein `ast`-Import-Scan.

- **14** Ganzdatei-Scanner auf `backend/workflow_dag_runner.py` in 13 Dateien.
- **13 bleiben gruen**: alle gesuchten Strings liegen in der **Engine**
  (< `:1219` oder > `:1811`) oder sind Top-Level-Imports (`:36`, `:72`, `:436`,
  `:1038`) — diese Bereiche werden beim Facade-Split nicht angefasst.
- **Genau 1 bricht:** `tests/test_reaudit_stage9.py:54-58`
  (`test_d12_dag_cost_not_zero_on_error`) — sucht `_cost_usd = None` (`:1755`),
  `"cost_unverified": _cost_unverified` (`:1789`),
  `"Kostenberechnung fehlgeschlagen"` (`:1775`), alle im **Tail** der Facade.
- **Das eigentliche Risiko sind 7 `patch("backend.workflow_dag_runner._update_kanban_task_status")`-Punkte**
  (`test_d1_executor_characterization.py`, `test_stage1_stage3_hardening_and_bus.py:363/:389/:432/:753`,
  `test_workflow_dag_e2e.py:90`) plus `patch(..._execute_research_dag_node)`.
  Binden neue Module diese Namen zur **Importzeit**, greifen alle Patches ins Leere.

**Gewaehlte Strategie (S3 + S5-A, 0 gebrochene S-Tests, 0 Testaenderungen):**
1. **S5-A:** Den ~37-Zeilen-Tail `:1754-1790` (Kostenberechnung + `out`-
   Normalisierung) **in `workflow_dag_runner.py` belassen**. Damit bleiben die
   drei D12-Marker physisch am Ort, `test_reaudit_stage9.py` gruen, und die
   Rest-Facade hat nur 1 `try/except` → **CC < 20 erreichbar**. Keine G7-
   Umstellung noetig (die Alternative S5-B waere regelkonform, aber unnoetig).
2. **S3 Dependency-Injection:** Extrahierte Cluster erhalten `_update_kanban_task_status`
   und den Dispatcher als **Callables zur Aufrufzeit** von der Facade, statt
   Modul-Level-Rueckimports. Kein `workflow_dag_runner ↔ workflow_nodes`-Zyklus,
   alle Patch-Punkte bleiben wirksam. Der Dispatch wird ohnehin schon zur
   Laufzeit ueber `core_dispatcher.dispatch_to_omniroute_or_container` aufgeloest
   (`:1214-1215`) — passt also zum bestehenden Muster.
3. **S4:** Engine-Bereich und `_execute_research_dag_node` (`:~1100`, haelt
   `test_p2_content_batch_d.py:237`) bleiben unangetastet.
4. **Re-Export `X as X`** fuer alle Patch-/Import-Ziele am alten Ort.
5. `test_unbound_calls.py` parst nur `main.py` → gehoert zu **D2**, nicht D1;
   behalten, aber nicht als D1-Gate zaehlen.

**Fazit:** Das im Dossier befoerchtete Massensterben der S-Tests tritt bei D1
**nicht** ein. Risiko = 7 Patch-Punkte + 1 Tail-Test, beide durch S3/S5-A
abgedeckt.

---

## 6e. Verifizierte Kartierung D2 / D3 / D4 (dritter Agent)

**Korrekturen gegenueber Dossier/Handoff (vor jedem Split neu messen!):**

| Angabe | Dossier/Handoff | Verifiziert |
|---|---|---|
| `main.py` | 2919 / 3638 Z. | **3418** (`Measure-Object -Line` zaehlt nur nicht-leere Zeilen!) |
| `operations_api.py` | 3829 / 4511 Z. | **4226** |
| `hermes_telegram_adapter.py` | 10290 Z. | **11232** |
| `include_router` | 75, „je Router try/except" | 75 ✓, aber **nur 32/75** in try/except (31 appends); 43 nackt |
| `_get_ops_deps()` | „10 Aufrufstellen" | **8** (alle in `operations_org.py`) |
| `gateway.py` | „13 fruehere Stellen" | **12** `get_provider`-Stellen |
| `register(ctx)` | „8 Callables" | **7** callable Keywords, 17 Keywords gesamt |
| `_apply_yaml_config` | „Methode" | **Modul-Level-Funktion** (`:11083`) |
| Patch-Punkt `_get_kanban_connection` | `test_fix_w2_c_governance_roles.py:114` | **`:135`** |

**D2-Kernbefund:** `archon/core/provider_registry.py:65` `register()` wird
**nirgends im Repo aufgerufen** → der Container bleibt leer, `get_provider("app_main")`
liefert immer das `main`-Modul. Der Shim ist derzeit reine Indirektion **ohne**
Entkopplungseffekt. **90** direkte `main`-Imports in `archon/**`+`backend/**`
(85 `import main as app_main` in 23 Dateien + 5 anderer Form: `mcp_gateway.py:65`,
`operations_sysops.py:312/347/377`, `autonomous_standup.py:91`), `backend/**` hat
0 `import main as app_main`. Bereits umgestellt: 21 Stellen (12 + 9).

**D2-Contracts (aktuelle Zeilen):** `_ROUTER_LOAD_ERRORS :600` (31 appends),
`_assert_router_health :3237-3263`, `_rbac_configure :2928` vor erstem Router
`:2942`, `_FAIL_FAST_HOOKS :622-628` (5 Namen) + raise `:791-793`,
`_STARTUP_HOOKS.insert(0, …)` **5** Stellen `:3266/:3314/:3412/:3415/:3418`
(Ausfuehrungsreihenfolge = umgekehrte Dateireihenfolge),
`_SHUTDOWN_HOOKS reversed() :798`, `app :823`, `auth_service :541`,
`core_dispatcher :42`. 75 includes `:1437 … :3230`.

**Die 5 D2-Characterization-Luecken sind alle weiterhin offen:**
① `/livez` liest nur `check_loop_liveness()`/`watchdog_liveness()`, **kein**
Bezug auf `_FAIL_FAST_HOOKS`/`_AUDIT_COMPROMISED` (letzteres haengt an `/readyz`
`:1362-1363`). ② 0 Treffer fuer `_SHUTDOWN_HOOKS`/`reversed(`/Shutdown-Timeout.
③ 0 Treffer fuer `_N8N_STARTUP_STATUS`. ④ nur `is_configured()` +
Einzel-Source-Assertion, keine Reihenfolge der 75. ⑤ 0 Treffer fuer
`HealingAttemptPayload`/`hitl_apply_patch`.

**D3:** `_get_ops_deps()` = positionales 6-Tupel
(`operations_org.py:81`: `_load_profiles_map, _get_fallback_avatar,
_get_kanban_connection, PROFILES_FILE, WORKSPACE_DIR, _PROFILES_MAP_CACHE`),
8 Aufrufstellen `:42/:93/:180/:222/:449/:542/:579/:853` — `:579` liest
positional `[3]`/`[5]`. `router` `:80-84`, `_get_kanban_connection :189`,
`_load_kanban_meta :394`, `_execute_kanban_task_async :1478`,
`update_task_status :2198`. Kritischer Patch-Punkt
`test_fix_w2_c_governance_roles.py:135`.

**D4:** `register(ctx) :11212-11232`, Mount `docker-compose.yml:405`
(`./scripts/patches/hermes_telegram_adapter.py:/opt/hermes/plugins/platforms/telegram/adapter.py:ro`).
Widerspruechliche Digests: `docker-compose.yml:374/437` =
`sha256:276d4468…` (mit Mount), `docker-compose.hermes.yml:32/75` =
`sha256:e6d81ae5…` (ohne Tag, ohne Mount). 8 Rang-F-Bloecke,
`_handle_callback_query :6873`. `test_telegram_gate_meldung.py` parst per `ast`
ausschliesslich **Top-Level-Knoten** (`GATE_OK_TEXT :687`, `GATE_REJECT_TEXT :688`,
`gate_decision_answer :691`) → ein Split **muss** diese drei als Re-Export in
`adapter.py` erhalten. `gateway.*`/`hermes_cli.*` nur im Image.

> **S4-Bewertung (vorlaeufig, regelkonform zu eskalieren):** Der produktive Mount
> `:405` bindet **genau eine** Datei. Ein Split nach `telegram/*.py` wuerde ohne
> Compose-Aenderung den Adapter im Container brechen; ein Compose-Eingriff
> beruehrt laufende Container und die widerspruechlichen Digests. Handoff:
> „Produktiv-Telegram unverändert", „Mount-Pfad :405 unverändert", „kein Push
> ohne Freigabe". → S4 wird als **DELEGATED** dokumentiert (Grund + Empfehlung),
> nicht still ausgefuehrt. Vgl. `§4`: „Ausserhalb Ownership = dokumentieren,
> nicht aendern".

---

## 7. Was diese Session NICHT getan hat

Kein `main.py`-Split, kein `workflow_dag_runner.py`-Edit, kein Test geschrieben/geändert,
kein `config/kanban_meta.json` angefasst, kein Commit, kein Push, kein `--no-verify`,
`./data` / `.env` / laufende Container / Audit-Kette unberührt.
Hauptbaum (`main @ 2ee92706`) mit den hochgeladenen Tagesstand-Artefakten unangetastet.
`s1-god-objects @ ee18373a` unverändert.

Shell-Aufrufe strikt sequenziell in **einem** Prozess (Handoff-Falle #2 trat beim ersten
Parallelversuch sofort auf: `Zugriff verweigert (os error 5)`).

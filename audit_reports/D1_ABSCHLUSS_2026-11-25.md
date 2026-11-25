# D1 — ABSCHLUSS: `default_agent_node_executor` zerlegt (25.11.2026)

**Status: ABGESCHLOSSEN.** Schritt 2 der vom Nutzer festgelegten Reihenfolge
(`ANALYSIS_GOD_OBJECTS.md §5:409`: `S1 → B(D1) → S2(D2) → S3(D3) → S4(D4)`).

**Branch:** `s2-s4-monolithen`, Basis `ee18373a`, **11 Commits, kein Push**.
Hauptbaum (`main @ 2ee92706`) und `s1-god-objects @ ee18373a` unangetastet.

---

## 1. Akzeptanzkriterien (`HANDOFF §8`) — alle erfuellt

| Kriterium | Beleg | Status |
|---|---|---|
| Alle Tests gruen (0 failed) | **2387 passed / 20 skipped / 0 failed**, in jedem der 11 Commits | ✅ |
| Gold-/Characterization-Outputs byte-identisch | 32 Golden-Tests mit Negativproben, durchgehend gruen ueber alle Extraktions-Commits | ✅ |
| Router-Reihenfolge, `/livez`/`/readyz`/`/health` unveraendert | **Main-Smoke: 799 Pfade, F2-Wiring, Re-Exports, Fail-Closed, Opt-Out** — `main.py` wurde in D1 nicht angefasst | ✅ |
| Fail-Fast-Hooks raisen; Negativprobe mit defektem Router bricht Start ab | Main-Smoke Negativprobe `RuntimeError` + `ARCHON_ALLOW_BROKEN_ROUTERS`-Opt-Out geprueft | ✅ |
| `default_agent_node_executor` weiter importierbar | `import OK: backend.workflow_dag_runner (node, upstream) -> Dict[str, Any]` — Signatur unveraendert | ✅ |
| **CC der Facade < 20** | **radon: C (18)**, von **F (246)** | ✅ |
| Kein neuer Importzyklus; `lint-imports` 2 kept / 0 broken | 295 Dateien / 1005 Dependencies, 2 KEPT / 0 broken | ✅ |
| Jeder Commit: 1 Schritt, 1 Full-Gate, `config/kanban_meta.json` restauriert, kein `--no-verify`, kein Push | Commit-Kette s. §2 | ✅ |

**Full-Gate pro Commit:** ruff `--select E,F,I --ignore E501` (dateigranular) ·
`mypy --config-file mypy.ini` (changed + full 418/0 + `--disallow-untyped-defs`
fuer neue Module) · `lint-imports` · `pytest tests/ -q` · `compileall` ·
`audit_secrets.py --all` · `bandit -q -lll` · `pip-audit`. Env:
`ARCHON_TEST_DB_ISOLATION=1`, `ARCHON_DATA_DIR=<temp>`.

---

## 2. Commit-Kette

| Commit | Schritt | CC |
|---|---|---|
| `69936e5d` | B0 — 17 Golden-Tests (Executor real aufgerufen) | 246 |
| `f2b5c7c7` | B0b — Review-Fix + 14 Luecken, 32 Tests | 246 |
| `9b6c39db` | B1 — C2 Node-Plugin → `plugin_nodes.py` | 238 |
| `057ff9c8` | B2 — C3 Media/Clip → `media_nodes.py` | 216 |
| `dc5d14dd` | B3 — C4 Profil/Prompt → `prompt.py` | 177 |
| `6bf76cff` | B4 — C6 Tool-Loop → `tool_loop.py` | 130 |
| `d05d9555` | B5 — C7 Schema/Repair/Frontier → `schema_contract.py` | 100 |
| `26754037` | B6 — C8 Anti-Slop → `quality.py` | 57 |
| `6ee3d9ba` | B7 — C9 Deliverable → `deliverable.py` | 46 |
| `ea6be2e0` | B8 — C10 Tail → 3 modul-lokale Helper | **18** |
| `fd73bc45` | B9 — Logger-Kanal-Konsistenz | 18 |

**Neue Module** (`backend/workflow_nodes/`): `__init__.py`, `plugin_nodes.py`,
`media_nodes.py`, `prompt.py`, `tool_loop.py`, `schema_contract.py`,
`quality.py`, `deliverable.py`. Alle mit `__all__`, vollstaendig typisiert,
`mypy --disallow-untyped-defs` gruen.

**Modul-lokale Helper in `workflow_dag_runner.py`** (bewusst NICHT ausgelagert):
`_compute_node_cost` (CC 16), `_build_node_output` (CC 10),
`_finalize_kanban_status` (CC 5).

---

## 3. Architektur-Entscheidungen (und warum)

**S3 — Dependency-Injection zur Aufrufzeit.** Kein extrahiertes Modul bindet
Namen aus `workflow_dag_runner` zur Importzeit. `_update_kanban_task_status`,
`_dispatch_with_node_budget`, `_connect` und alle Dispatcher werden von der
Facade zur **Aufrufzeit** als Callables uebergeben. Damit greifen alle
**7 `patch("backend.workflow_dag_runner._update_kanban_task_status")`-Punkte**
weiter, und es entsteht kein `workflow_dag_runner ↔ workflow_nodes`-Zyklus.

**S5-A — Tail bleibt physisch in `workflow_dag_runner.py`.** Der einzige
S-Test, der bei einer Facade-Extraktion gebrochen waere, ist
`test_reaudit_stage9.py:54-58` (`test_d12_dag_cost_not_zero_on_error`). Er
sucht `_cost_usd = None`, `"cost_unverified": _cost_unverified` und
`Kostenberechnung fehlgeschlagen` im **ganzen Dateitext**. Durch die drei
modul-lokalen Helper bleiben alle Marker am Ort → **0 gebrochene S-Tests,
0 Testaenderungen, keine G7-Eskalation noetig**. Verifiziert bei B8
(65 Tests inkl. `test_reaudit_stage9.py` gruen).

**Rueckgabe-Tupel / NamedTuples statt geteiltem State-Objekt.** Jeder Cluster
bekommt explizite Parameter und gibt alle geaenderten Locals zurueck
(`SchemaOutcome`, `QualityOutcome`, `PromptContext`, Tupel bei `tool_loop`).
Klassisches Extract-Method, unstrittig „reine Extraktion, keine
Logikaenderung".

---

## 4. Funde, die nur durch echte Proben sichtbar wurden

1. **Zweiter Blick (`INVARIANTS §4.6`) fand einen echten Bug in B0:** `_golden`
   lieferte Ist- statt Soll-Werte → `_assert_golden` war eine `X == X`-
   Tautologie, alle 8 positiven Golden-Assertions **Theater-Gate** nach §4.5.
   Behoben (`f2b5c7c7`) inkl. Meta-Test, Feld-Praesenzpruefung und
   Mutations-Gegenprobe (`content`/`agent_id`/`model`/`task_id` → rot).
   Bestaetigt erneut: *„jeder kritische Fund durch eine unabhaengige Instanz,
   nie durch den Autor des Fixes."*
2. **D12 ist der Normalfall, nicht der Fehlerfall.** `_cost_usd = None` +
   `+=` wirft immer `TypeError`; `cost_usd=None, cost_unverified=True` ist der
   verifizierte Standard-Return. Nicht „bereinigt", festgenagelt.
3. **`token_budget` blockiert NICHT den ersten Dispatch** — die Pruefung
   laeuft mit `res={0 Tokens}` vor dem Dispatch; der Block greift erst bei
   Folge-Dispatchen.
4. **5 versteckte `locals().get(...)`-Kopplungen** (`_repair_in`,
   `_repair_out`, `_esc_in`, `_esc_out`, `_repair_model_used`) zwischen
   Cluster 7 und dem Kosten-Tail. In B5 explizit als `SchemaOutcome`
   zurueckgefuehrt; in B8 als **gleichnamige Parameter** in
   `_compute_node_cost` uebernommen, sodass der `locals()`-Zugriff
   buchstaeblich 1:1 erhalten bleibt.
5. **Media-/Plugin-Branches haben keine Kosten-Felder** (frueher Return vor
   dem Tail) — als Struktur-Unterschied charakterisiert, nicht vereinheitlicht.
6. **Logger-Kanal:** `logging.getLogger(__name__)` in den neuen Modulen waere
   ein stiller Wechsel gewesen → B9 auf `archon.workflow_dag` korrigiert.
7. **Deliverable-Pfad bei `OSError` bleibt gesetzt** (kein Reset) — beim
   Extrahieren bewusst NICHT „bereinigt".

8. **Vorbestehender Flaky-Timing-Test (an G7 eskaliert, NICHT geloescht/
   geskippt/umgeschrieben).** Beim Full-Gate zum Doc-Commit fiel einmalig
   `test_stage1_stage3_hardening_and_bus.py:808`
   (`test_dag_runner_schema_preserved_and_event_driven_recovery`) rot:
   `assert order.index("fast_recover") < order.index("slow")` ergab
   `['fast', 'slow', 'fast_recover']`. Der Test nutzt `executor_fn=_exec`
   (Mock), also **nicht** den zerlegten Executor; er war in allen 11
   vorangegangenen Gates gruen; B9 aenderte nur Logger-Namen, B10 ist reine
   Doku. **5 isolierte Laeufe: 5x gruen.** Ursache: `asyncio.sleep(0.15)` vs
   `0.01` in der Event-Driven-Ready-Queue, unter Full-Suite-Last verzoegert.
   → `ANALYSIS §6 #15` / `Anhang D.4 #10`: rote/blockierende Tests zaehlen
   nicht als Characterization und werden **eskaliert**, nicht angefasst.
   Empfehlung an G7: Reihenfolge per explizitem Event/Determinismus statt
   Sleep-Timing absichern. Das Gate wurde nach dem Beleg wiederholt.

**Prozess-Fehler, transparent dokumentiert:** zweimal (B1/B2 und B6/B7)
wurde ein Folge-Cluster angewendet, bevor der vorige committet war. Beide Male
per `git reset --mixed HEAD~1` aufgeloest und sauber getrennt (je eigenes
Full-Gate). Der inkonsistente Zwischen-Commit `c7cbc7e8` existiert nicht mehr
in der Kette. Ebenfalls dokumentiert: Falle #2 (parallele `pwsh`-Spawns →
`os error 5`) und Falle #3 (PowerShell-Quoting beim B8-Commit → `-F`
Message-Datei).

---

## 5. Was NICHT angefasst wurde

`main.py` (3418 Z.), `backend/operations_api.py` (4226 Z.),
`scripts/patches/hermes_telegram_adapter.py` (11232 Z.),
`core_dispatcher.py`, die Engine-Bereiche von `workflow_dag_runner.py`
(< `:1339` / > `:1494`), `_execute_research_dag_node` (haelt
`test_p2_content_batch_d.py:237`), `./data`, `.env`, Audit-Kette, laufende
Container, historische `audit_reports/*.md`. Kein `--no-verify`, kein Push.

---

## 6. Offen (naechste Schritte, gewichtet)

| # | Schritt | Aufwand | Risiko | Status |
|---|---|---|---|---|
| 1 | **D2/Charact.** 5 fehlende Tests ①–⑤ (`/livez`↔`_FAIL_FAST_HOOKS`, Shutdown-`reversed()`, n8n→`/readyz`, Router-Reihenfolge + `_rbac.configure()`, `HealingAttemptPayload`/`hitl_apply_patch`) — **alle 5 weiterhin offen** | 1–2 Commits | 🟠 | offen |
| 2 | **D2/2a** ~50 `app_main.*`-Symbole + **90** direkte `main`-Imports (23 Dateien) nach `archon/core/runtime.py` / `archon/services/app_state.py` heben | 3–5 C. | 🔴 **hoechtstes** | offen |
| 3 | **D2/2b–2d** Lifespan → `lifecycle.py`, Middleware → `middleware/`, 75 Router → `routers/__init__.py`; Ziel `<300` Z. | 4–6 C. | 🔴 | offen |
| 4 | **D3** `_get_ops_deps()` 6-Tupel (8 Aufrufstellen) einfrieren, G7-S-Tests, Split `operations_api.py` | 4–6 C. | 🟠 | offen |
| 5 | **D4** Telegram-Adapter | — | ⚫ | **DELEGATED** |
| 6 | **D5** `core_dispatcher.py` | — | — | **BACKLOG**, bewusst nicht in den 5 Schritten |

**D4-Begruendung (regelkonforme Eskalation, kein stilles „Erledigen"):**
Der produktive Mount `docker-compose.yml:405` bindet **genau eine** Datei auf
`/opt/hermes/plugins/platforms/telegram/adapter.py:ro`; `gateway.*` /
`hermes_cli.*` existieren nur im Image; die Digests widersprechen sich
(`docker-compose.yml:374/437` = `276d4468…` vs `docker-compose.hermes.yml:32/75`
= `e6d81ae5…`, ohne Mount). Handoff: „Produktiv-Telegram unveraendert",
„Mount-Pfad `:405` unveraendert", „kein Push ohne Freigabe". →`ANALYSIS §4`:
*„Ausserhalb Ownership = dokumentieren, nicht aendern"*, Status DELEGATED mit
Grund + Empfehlung (Adapter als duenner Re-Export, `gateway.*`-Mock-Geruest,
Digest-Kopplungs-Gate). Kein Code-Commit in dieser Session.

**Hinweis `INVARIANTS.md`:** Die normative Datei ist im Hauptbaum untracked
(`?? audit_reports/INVARIANTS.md`) und deshalb nicht Teil von `ee18373a` →
im Worktree abwesend. Alle Regelzitate stammen aus dem Handoff / Dossier.
Die Datei wurde bewusst nicht in den Worktree kopiert (Tagesstand des Nutzers).

---

## 7. Referenz

`ANALYSE_S2_D1_KARTIERUNG_2026-11-25.md` (§6c Review-Fund, §6d S-Test-Impact,
§6e D2/D3/D4-Kartierung) · `HANDOFF_S2_S4_MONOLITHEN_2026-11-25.md` ·
`ANALYSIS_GOD_OBJECTS.md §5/:387/:409`, Anhang D · `INVARIANTS.md §3/§4.5/§4.6`.
Gate-Script und Main-Smoke liegen ausserhalb des Repos unter
`C:\Users\micha\AppData\Local\Temp\opencode\`.

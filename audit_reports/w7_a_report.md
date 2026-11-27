# W7-A — UI/Wiring-Fixes (Domäne 01): Bericht

> **Datum:** 27.11.2026 · **Partition:** W7-A · **Branch:** `main` · **HEAD bei Start:** `028e6c09`
> **Kein Commit durch diesen Subagenten.** Der Koordinator committet zentral nach Verifikation.

---

## 1. Scope & Regeln

Bearbeitet wurden ausschließlich die freigegebenen Dateien:

| Datei | Änderung |
|---|---|
| `archon/core/profiles.py` | zentrale Tool-Verfügbarkeits-SSOT, `computer_use` aus Defaults |
| `archon/routers/operations_bot_screen.py` | ehrliche API-Antwort, Importblock lint-konform |
| `static/js/agent_profiles.js` | Tool-Katalog deaktiviert, Zuweisungs-Guard |
| `static/js/mission_control_cockpit.js` | vollständige Status-Map + Badges + Helper |
| `frontend/src/components/ExecutiveCockpit.tsx` | zentrale SSE-Konstante exportiert |
| `frontend/src/components/WorkflowCockpit.tsx` | SSE-Konstante importiert statt Literalliste |
| `static/js/operations_kanban.js` | zentrale SSE-Konstante, Reload nach `task_cancelled` |
| `tests/test_w7_a_ui.py` | 8 Regressionstests (neu) |
| `audit_reports/w7_a_report.md` | dieser Bericht (neu) |

Nicht angefasst wurden fremde Dateien anderer Partitionen (insbesondere
`backend/audit_log.py`, `archon/core/orchestration.py`,
`backend/docker_services.py`, `ci.yml`, Doku-Dateien). Die parallelen
Änderungen anderer Agenten im Arbeitsbaum blieben unberührt.

`docs/system/NEVER_DO_LIST.md` wurde beachtet: kein PostgreSQL/DSN/Migration,
kein Coroutine-/Event-Replay, keine eigene Content-Domäne / kein
`/content-studio`. Die W4-Haftungs-SSOT (`profiles.py`) und der W4-Task-Endpunkt
sowie die Haftungsdialog-Logik (`agent_profiles.js`) wurden nicht verändert;
die W4-C-Suite bleibt grün (siehe §4).

---

## 2. Funde & Fixes

### D01-M3 (MED 5) — `computer_use` ohne CUA-Runtime beworben

**Vorher:** Der Tool-Katalog (`agent_profiles.js:220`) beschrieb „Autonome
Steuerung von Mauszeiger, Klicks und Tastatureingaben"; die kanonische Liste
(`profiles.py`, `DEFAULT_HERMES_TOOLS`) wies das Tool neuen Profilen automatisch
zu. Der Endpoint `/bot-screen/interact` meldete zwar ehrlich `simulated`,
Katalog und API liefen aber auseinander.

**Nachher:**

- `profiles.py`: neue zentrale SSOT `UNAVAILABLE_TOOLS` +
  `COMPUTER_USE_UNAVAILABLE_REASON`, echte Helper `is_tool_available()` und
  `tool_availability()` (maschinenlesbar: `available: false`,
  `runtime: "unavailable"`, Grund). `computer_use` ist aus
  `DEFAULT_HERMES_TOOLS` entfernt, bleibt als bekanntes Tool in
  `ALL_HERMES_TOOLS` (mit Hinweis). Neue Namen in `__all__`.
- `operations_bot_screen.py`: Endpoint liefert nun `tool`, `available`,
  `runtime` und `reason` aus `tool_availability()`; `status: "simulated"` /
  `simulation: true` bleiben erhalten. Neuer Helper
  `computer_use_runtime_available()` für Tests. Importblock nach vorn geholt
  (behebt zugleich vorbestehende E402/I001 in dieser Datei).
- `agent_profiles.js`: Katalogeintrag heißt „Desktop CUA-Automation (Demo)",
  `desc` benennt ehrlich die fehlende Runtime, `available: false` +
  `runtime: "unavailable"`. Neue Karte `UNAVAILABLE_HERMES_TOOLS` mit Helper
  `isHermesToolAvailable()`. Katalog-Pills werden gestrichelt/ausgeblendet
  dargestellt, der `+`-Button entfällt; `addToolToProfileById()` blockt die
  Zuweisung auch bei umgehendem Aufruf; Altprofile zeigen ein ⚠ statt „aktiv".

Es wird keine echte CUA-Runtime behauptet und kein Fake-Erfolg erzeugt.

### D01-M4 (MED 4) — unvollständige Status-Map in Mission Control

**Vorher:** `MC_KANBAN_GROUPS` kannte nur `todo/in_progress/review/blocked/done`.
`queued`, `awaiting_gate`, `cancelled`, `paused`, `failed` hatten keine Spalte
und waren unsichtbar, obwohl `operations_kanban.js` sie korrekt abbildet.

**Nachher:** `MC_KANBAN_GROUPS` ist deckungsgleich mit `OPS_COLUMN_GROUPS`
(`todo` += `queued`, `awaiting_gate`; `blocked` += `failed`, `cancelled`,
`paused`). `MC_KANBAN_BADGE_KEYS` enthält Badges für alle fünf Status.
Neuer echter Helper `mcKanbanColumnForStatus(status)`, der in `mcKanbanCard()`
als Fallback für bislang unbekannte Status ein Badge erzeugt — damit bleibt
kein Status mehr ungerendert.

### D01-M5 (MED 5) — SSE-Filter ignorieren `task_cancelled` / `task_status`

**Vorher:** Drei verstreute Literallisten; `task_cancelled` wurde nirgends
konsumiert, `task_status` fehlte in beiden React-Cockpits. Abgebrochene Tasks
blieben stale.

**Nachher:** Zentrale Konstante `ARCHON_KANBAN_SSE_EVENTS` (15 echte
Broadcast-Typen inkl. `task_status` und `task_cancelled`):

- `ExecutiveCockpit.tsx`: exportiert die Konstante und nutzt sie im
  `useArchonEvents`-Handler; das vorhandene `Promise.all` lädt
  `listKanbanTasks()` erneut — der Status `cancelled` wird sichtbar persistiert.
- `WorkflowCockpit.tsx`: importiert dieselbe Konstante aus
  `./ExecutiveCockpit` (keine zweite Literalliste mehr) und refreshed die
  DAG-Runs.
- `operations_kanban.js`: definierte Konstante (auf `window` exponiert) plus
  abgeleitete `ARCHON_KANBAN_BOARD_RELOAD_EVENTS` mit `task_cancelled`; der
  gedebouncte Board-Reload läuft jetzt auch nach Abbruch.

Die Parität zwischen Legacy-Board und React-Cockpits wird per Test erzwungen.

---

## 3. Regressionstests (`tests/test_w7_a_ui.py`)

8 Tests, Produktivpfad statt Artefakt-Prüfung:

- `test_computer_use_not_in_default_tools` — Python-SSOT und JS-Defaults.
- `test_tool_availability_helper_is_single_source_of_truth` — ruft die echten
  Helper auf (`is_tool_available`, `tool_availability`).
- `test_bot_screen_endpoint_reports_honest_state` — ruft den echten Endpoint
  `interact_with_bot_screen()` mit monkeypatchtem RBAC auf und prüft die
  komplette Antwort.
- `test_js_tool_catalog_disables_computer_use` — statische Produktivpfad-
  Prüfung des Katalogeintrags und des Zuweisungs-Guards.
- `test_mc_status_groups_match_operations_groups` — echter Helper vergleicht
  die geparsten Gruppen beider Boards auf Parität.
- `test_mc_badges_and_renderer_cover_new_statuses` — Badges + Verkabelung im
  Renderpfad.
- `test_sse_event_constant_is_central_and_identical` — parst beide Array-
  Deklarationen mit echtem Helper und erzwingt Mengengleichheit.
- `test_board_and_cockpit_refresh_after_cancel` — Reload-Pfad nach Cancel in
  allen drei Consumern.

Keine Secrets / `sk-<Zeichen>` in Tests, kein `# noqa` eingefügt.

---

## 4. Verifikation

Shell war in dieser Subagent-Session verfügbar; folgende Checks wurden lokal
ausgeführt. Der Koordinator führt dennoch zentral die Gesamtverifikation durch.

```
$env:ARCHON_TEST_DB_ISOLATION='1'
.venv\Scripts\python.exe -m pytest tests/test_w7_a_ui.py -q
  -> 8 passed

.venv\Scripts\python.exe -m pytest tests/test_w7_a_ui.py tests/test_w4_c_ssot.py -q
  -> 23 passed   (W4-Haftungs-SSOT unverändert)

.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 \
    archon/core/profiles.py archon/routers/operations_bot_screen.py \
    tests/test_w7_a_ui.py
  -> All checks passed!

.venv\Scripts\python.exe -m mypy --config-file mypy.ini \
    archon/core/profiles.py archon/routers/operations_bot_screen.py \
    tests/test_w7_a_ui.py
  -> Success: no issues found in 3 source files
```

Ein TypeScript-Typecheck war nicht möglich: `node_modules` ist im Repo nicht
vorhanden (auch kein `frontend/node_modules`), und die Hinweise in
`frontend/AGENTS.md` verweisen auf nicht vorhandene Next.js-Docs. Die
TSX-Änderungen sind rein deklarativ (`readonly string[]`, `includes(string)`,
lokaler Import) und nutzen keine neuen Next.js-APIs — der Koordinator möge
den Build zentral prüfen.

Bekannte Vorbestehenfehler aus `HANDOFF_W4_W7.md` §3 wurden nicht verfolgt.

---

## 5. Status

| ID | Fix | Test | Status |
|---|---|---|---|
| D01-M3 | ✅ | ✅ 4 Tests | behoben (W7-A, uncommitted) |
| D01-M4 | ✅ | ✅ 2 Tests | behoben (W7-A, uncommitted) |
| D01-M5 | ✅ | ✅ 2 Tests | behoben (W7-A, uncommitted) |

Report-Datei liegt unter `audit_reports/w7_a_report.md` (`.gitignore:55`
beachten: `git add -f` durch Koordinator). Kein Commit, kein `git add` durch
diesen Subagenten.

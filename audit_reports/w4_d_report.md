# W4-D Report — Domäne 01: CUA/PbD-Fake-Success & Agenten-Anweisung

> **Partition:** W4-D · **Branch:** `main` · **Basis-HEAD:** `a0a30aea` · **Datum:** 27.11.2026
> **Dateibesitz strikt eingehalten.** Kein Commit, kein `git add`, keine fremden Dateien
> dauerhaft verändert. Ruff/MyPy/pytest werden vom **Koordinator zentral verifiziert**
> (siehe §5).

---

## 1. Fix-Tabelle

| ID | Krit | Datei | Fix | Produktivpfad / Vier-Glieder-Kette |
|---|---|---|---|---|
| **D01-H1** | HIGH 8 | `backend/computer_use_pbd.py` | Neue Konstante `CUA_RUNTIME_UNAVAILABLE_MESSAGE`. `_synthesize_python_script()` erzeugt statt `print()`/`sleep()`-Kosmetik + `return {"status": "completed"}` jetzt ein Demo-Artefakt mit `DEMO_ONLY/SIMULATED/EXECUTABLE`-Flags, `RECORDED_STEPS` als reine Dokumentation und `execute_<slug>()` → `RuntimeError`. `stop_and_synthesize_skill()` liefert `demo_only=True`, `simulated=True`, `executable=False`, `runtime="unavailable"` und eine ehrliche Meldung; `status="synthesized"` bleibt, weil das Schreiben von SKILL.md/Skript/Trace ein **echter** Effekt ist. `_synthesize_skill_md()` markiert Frontmatter und Ausführung Abschnitt entsprechend. | Produzent: Synthese schreibt ehrlich markierte Artefakte. Konsument: `archon/routers/operations_pbd.py::stop_pbd_and_synthesize` gibt das Result unverändert an die UI. Effekt: Dateien werden geschrieben; **keine** CUA-Aktion. Verifikation: echter `execute_*()`-Aufruf wirft `RuntimeError` (Nie `status="completed"` ohne Ausführung). |
| **D01-H1** (Artefakt) | HIGH 8 | `scripts/dynamic_tools/auto_senior_applicant_screener.py` | Ausgeliefertes print-only-Skript analog umgebaut: Demo-Header, `RECORDED_STEPS`, `DEMO_ONLY/SIMULATED/EXECUTABLE`, `execute_auto_senior_applicant_screener()` → `RuntimeError`. Kein `"status": "completed"` mehr. | Produce/Konsum/Effekt/Verifikation identisch zum Generator; das Artefakt ist jetzt konsistent mit dem neuen Generator. |
| **D01-H2** | HIGH 8 | `archon/routers/operations_org.py` | Neues `AgentInstructionRequest`-Modell und `POST /api/operations/tasks` → `create_agent_instruction_task()`. Legt eine **echte** Zeile in `tasks` an (`status='review'` = MC-Gate `approval`, `assignee=agent_id`, `project_id=parent_project_id`), schreibt zusätzlich den Feed-Eintrag mit der echten Task-ID, `commit()`, verifiziert per `SELECT 1 ... WHERE id=? AND assignee=?` und gibt bei Erfolg `task_id` zurück. Bei DB-Fehler/Verifikationsfehler: `rollback` + `HTTPException(500)`; bei leerer Nachricht/`agent_id`: `HTTPException(400)`. `broadcast_event("task_captured", …)` nur best-effort nach der Verifikation. Das alte `POST /comm-feed/broadcast` bleibt unverändert (echte Funkmeldungen, kompatibel mit `test_d3_ops_deps.py`). | Produzent: Endpunkt erzeugt Task + Feed-Zeile. Konsument: regulärer Kanban-/Dispatch-Loop bzw. Partition-C-JS. Effekt: Task in `kanban.db`, `task_events`-Eintrag mit `instruction_task_id`. Verifikation: Antwort `task_id` **nur** nach Lesbarkeitsprüfung; Fehlerpfad fail-closed. |

---

## 2. Regressionstests — `tests/test_w4_d_cua.py` (9 Tests, alle grün)

| Test | Zweck |
|---|---|
| `test_d01_h1_synthesis_result_declares_demo_only` | Synthese-Ergebnis trägt `demo_only/simulated/executable/runtime`; keine Erfolgsmeldung; Artefakte existieren. |
| `test_d01_h1_generated_script_never_reports_completed` | Generierter Quelltext ohne `"status": "completed"`, ohne `erfolgreich abgeschlossen`, ohne `print()`/`time.sleep()`-Aktionssimulation. |
| `test_d01_h1_generated_execute_fails_closed` | **Echter Aufruf** des generierten `execute_w4d_demo_skill()` wirft `RuntimeError` — simulierte Ausführung wird nicht als Erfolg durchgereicht. |
| `test_d01_h1_skill_md_marks_artifact_non_executable` | SKILL.md enthält `demo_only: true`, `executable: false`, `runtime: unavailable` und den Runtime-Hinweis. |
| `test_d01_h1_shipped_dynamic_tool_artifact_fails_closed` | Ausgeliefertes Screener-Skript: keine Fake-Erfolgsmeldung, `execute_*()` wirft `RuntimeError`. |
| `test_d01_h2_route_is_registered_at_operations_tasks` | `POST /tasks` ist am Router registriert (vom Operations-Router unter `/api/operations` gemountet). |
| `test_d01_h2_creates_real_task_and_returns_task_id` | Endpunkt legt echten Task mit `assignee`/`project_id`/`status='review'` in einer echten SQLite-DB an, Antwort enthält `task_id`, Feed-Eintrag referenziert dieselbe ID. |
| `test_d01_h2_db_error_is_fail_closed` | Fehlt die `tasks`-Tabelle → `HTTPException(500)`, kein Erfolg, keine `task_id` in der Antwort. |
| `test_d01_h2_empty_agent_id_is_rejected` | Leere `agent_id` → `HTTPException(400)`, kein Task. |

Die PbD-Tests leiten `SKILLS_DIR`/`SCRIPTS_DIR`/`PBD_TRACES_DIR` per Monkeypatch in `tmp_path`
um — **kein Schreiben ins Repo**. Keine Secrets, keine `sk-<Zeichen>`-Strings, kein `# noqa`.

---

## 3. Vertrag für Partition C (JS-Konsument)

- **Endpunkt:** `POST /api/operations/tasks`
- **Request-Felder:** `message` (pflicht), `agent_id` (pflicht), optional `author`,
  `parent_project_id`, `title`, `priority`.
- **Erfolgsantwort:** `{"status": "success", "task_id": "task-<hex>", "agent_id": "<id>", "created_at": "<iso>"}`
- **Erfolg ausschliesslich an nicht leerem `task_id` erkennen** (nicht an `status`).
- **Fehler:** `400` bei leerer Nachricht/`agent_id`; `500` bei DB-Fehler oder fehlgeschlagener
  Verifikation. Dann gibt es **weder** `status: "success"` **noch** `task_id`.
- Der angelegte Task startet nicht automatisch: DB-Status `review` entspricht dem
  HITL-Gate `approval`. Die Behauptung „Agent führt die Schritte jetzt autonom aus"
  muss die JS-Seite entsprechend auf „Task angelegt, wartet auf Freigabe" korrigieren.

---

## 4. Risiken / Konflikte / bewusste Entscheidungen

1. **`status="synthesized"` bleibt absichtlich.** Es beschreibt den realen Schreibeffekt
   (SKILL.md, Skript, Trace). Die Fake-Success-Komponente war die *Ausführung* — diese ist
   jetzt explizit `demo_only/simulated` und fail-closed. Dadurch bleibt der Legacy-Test
   `tests/test_pbd_computer_use.py::test_pbd_recording_and_synthesis` (erwartet
   `status == "synthesized"`) grün, ohne ihn (außerhalb meines Dateibesitzes) zu ändern.
2. **Stales SKILL.md-Artefakt:** `.agents/skills/auto_senior_applicant_screener/SKILL.md`
   ist nicht in meinem Dateibesitz und wurde bewusst **nicht** dauerhaft geändert. Der
   Legacy-Test `test_pbd_computer_use.py` schreibt beim Lauf in die echten Repo-Verzeichnisse;
   nach dem Generator-Fix aktualisiert er dieses tracked File. Ich habe es nach meiner
   lokalen Testläufen statisch auf den HEAD-Inhalt zurückgesetzt. **Koordinator:** entweder
   das neu generierte (ehrlich markierte) SKILL.md mitnehmen oder den Legacy-Test auf
   `tmp_path`-Verzeichnisse umstellen — sonst wird der Arbeitsbaum bei Testläufen dirty.
3. **Keine echte CUA-Runtime implementiert.** Bewusst: es gibt keinen Browser-/Desktop-Treiber
   im Chokepoint; die ehrliche Demo-Kennzeichnung + `RuntimeError` ist die gewählte,
   NEVER_DO_LIST-konforme Variante (kein neues Subsystem, kein Replay, keine PG-Migration).
4. **Feed-Eintrag bleibt erhalten**, jetzt aber mit `instruction_task_id` statt
   `task_id="system_broadcast"`. Bestehende Feed-Consumer lesen weiter `kind='broadcast'`.
5. **Neue Tabelle/Spalten:** Der Endpunkt nutzt die vorhandenen Spalten `id, title, body,
   assignee, status, priority, created_by, created_at, project_id` der `tasks`-Tabelle; keine
   Migration, kein Schema-Update.
6. **Parallele Partitionen nicht berührt:** `static/js/agent_profiles.js`, `agent_profiles.json`,
   `archon/core/delegation.py`, `backend/operations_execution.py`, `core_dispatcher.py`,
   `backend/eu_ai_act_inventory.py` wurden nicht verändert. Der Working Tree enthält Änderungen
   anderer Partitionen (W4-A/W4-B/W4-C); diese wurden nicht angefasst.

---

## 5. Verifikation

Lokaler Smoke-Check (zusätzlich zur zentralen Verifikation durch den Koordinator):

```text
ruff check --select E,F,I --ignore E501  → All checks passed!
mypy --config-file mypy.ini              → Success: no issues found in 4 source files
pytest tests/test_w4_d_cua.py -q          → 9 passed
pytest tests/test_w4_d_cua.py
       tests/test_pbd_computer_use.py
       tests/test_pbd_idempotent.py
       tests/test_d3_ops_deps.py
       tests/test_w3_d_trajectory.py -q  → 35 passed
```

**Der Koordinator verifiziert zentral** mit `ARCHON_TEST_DB_ISOLATION=1`, Ruff/MyPy auf allen
geänderten `.py`-Dateien und der W4-Suite. Bekannte vorbestehende Testfehler laut
`HANDOFF_W4_W7.md` §3 wurden nicht verfolgt.

**Kein Commit durch diesen Subagenten.**

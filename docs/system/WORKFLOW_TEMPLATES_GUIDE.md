# Multi-Agent Workflow-Vorlagen-Studio (M102)

Das **Multi-Agent Workflow-Vorlagen-Studio** trennt wiederverwendbare **Multi-Instanz-Workflows (DAGs)** sauber von einzelnen Prompt-Vorlagen und verbindet Archon OS-Agenten mit Kanban, DAW-Gantt, Dependency-Graph und optionalen n8n-Webhooks.

## 1. Unterschied: Prompt-Vorlage vs. Multi-Agent-Workflow

| Merkmal | Prompt-Vorlage / Task-Preset | Multi-Agent-Workflow (DAG-Studio) |
| :--- | :--- | :--- |
| **Umfang** | Einzelner Task / ein Agent | Mehrere gekoppelte Instanzen (Research → Writer → QA → HITL-Gate) |
| **Ausführung** | Direkt im Task-Modal | Visuelle DAG-Vorschau vor Start, dann Materialisierung als verknüpfter DAG |
| **Verzweigung** | Linear (1 Schritt) | Sequentiell, paralleles Fan-Out/Fan-In und menschliche Freigabe-Gates (`gate`) |
| **Bridge** | Einzel-Task in Kanban | Vollständiger Graph (`task_links`), Cron-Zeitplan & optionaler n8n-Webhook |

## 2. Mitgelieferte Starter-Workflows

1. **Wiederkehrende Content-Pipeline** (`content_pipeline_weekly`)  
   `research` (Trend-Recherche) → `writer` (Draft) → `qa` (Anti-Slop & Faktencheck) → `executive_decision_architect` (HITL-Gate).
2. **Deep-Research → Parallel-Analyse → Dossier** (`deep_research_dossier`)  
   `research` (Scope) → parallel `engineer` (Technik) + `analyst` (Markt/TCO) → `writer` (Synthese) → HITL-Gate.
3. **Lead-Recherche → CRM-Qualifizierung → Angebot** (`lead_to_crm_offer`)  
   `research` (Enrichment) → `analyst` (ICP-Fit) → `writer` (Angebot) → HITL-Gate.
4. **Feature-Audit → Security & Tests → Release** (`code_review_release`)  
   `engineer` (Diff-Review) → parallel `security` + `qa` → HITL-Gate.

## 3. Bedienung im visuellen Prozessablaufplan-Editor

1. Unter **Operations → Workflows** den visuellen Prozessablaufplan-Editor öffnen (der Tab **n8n-Automation** bleibt separat für die n8n-Engine).
2. Links eine der **Starter-Vorlagen** zur Orientierung anklicken (oder **+ Leerer Ablaufplan** wählen).
3. **Stationen einfügen & verschieben:** Über die Toolbar **+ Agent**, **+ Parallel** oder **+ HITL-Gate** neue Stationen einfügen und per **Drag & Drop** auf dem 20px-Raster anordnen (**Auto-Layout** richtet Ebenen automatisch aus).
4. **Verknüpfungen zusammenklicken:** Auf den rechten Ausgangs-Port (`→`) einer Station klicken (oder auf **Verknüpfen**) und anschließend die Ziel-Station anklicken. Ein Klick auf das `×` in der Mitte einer Verbindungslinie löst die Verknüpfung wieder.
5. **Rechter Inspektor:** Station anklicken, um Titel, Typ, Agent (aus dem aktiven Kader), Tool-Preset, SOUL-Modus, HITL-Pflicht und Aufgaben-Prompt anzupassen.
6. **Speichern & Starten:** Mit **Als Vorlage speichern** wird der Plan inkl. Koordinaten (`x, y`) in `config/workflow_templates.json` gesichert. **Workflow in Kanban starten (DAG)** legt alle Stationen und `task_links` atomar in Kanban, DAW-Gantt und Dependency-Graph an.

## 4. API-Endpunkte

- `GET /api/v2/workflows/templates` — Liste aller Starter- und eigenen Vorlagen
- `POST /api/v2/workflows/templates` — Eigene Workflow-Vorlage speichern/aktualisieren
- `DELETE /api/v2/workflows/templates/{tpl_id}` — Eigene Vorlage löschen
- `POST /api/v2/workflows/templates/{tpl_id}/run` — Workflow mit Variablen in Kanban/DAG materialisieren und optional n8n-Webhook triggern
- `GET /api/v2/workflows/schedules` — Aktive Cron- & Event-Automationen abrufen
- `POST /api/v2/workflows/schedules` — Cron-Zeitplan (Start-/Endzeitpunkt, Start-/Endbedingungen) oder Event-Trigger anlegen
- `DELETE /api/v2/workflows/schedules/{schedule_id}` — Automation löschen
- `GET /api/v2/workflows/events` — Protokollierte Events des zentralen Event-Bus abrufen
- `POST /api/v2/workflows/events/emit` — Event (z. B. `inbox`, `research`, `boardroom`, `watchdog`) in den Event-Bus einspeisen

## 5. Einheitlicher Event-Bus, Cron-Scheduler & Event-Bus Log (`backend/workflow_scheduler.py`)

- **Cron-Zeitpläne:** Unterstützt 5-Feld-Cron (`0 8 * * 1`) sowie `@every_5m`, `@every_15m`, `@hourly`, `@daily`, `@weekly` inklusive `start_at` (Startzeitpunkt), `end_at` (Endzeitpunkt), `start_condition` (`always` oder `no_active_run` gegen Überlappungen) und `end_condition` (`none`, `max_runs`, `on_error_stop`).
- **Einheitlicher Event-Bus (`dispatch_workflow_event`):** Watchdog (`backend/internet_watchdog.py`), Posteingang (`backend/inbox_watcher.py`), AI Boardroom (`archon/routers/boardroom.py`) und Research Lab senden Signale mit `correlation_id` (Loop-Schutz) an einen gemeinsamen Bus.
- **Event-Bus Log:** Unter **Telemetrie & Logs → Event-Bus** werden alle eingehenden Events, Filter-Matches und ausgelösten Workflow-Runs live angezeigt (inkl. Quellenfilter und Test-Event-Button).

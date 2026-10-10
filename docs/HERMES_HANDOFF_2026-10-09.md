# 🧠 HERMES HANDOFF — 09.10.2026 (Session: Archon OS Reparatur & Orchestrierung)

> **Zweck:** Vollständiger Wissenstransfer für die nächste Session. Stand: 09.10.2026, ~20:00 Uhr.
> Zusätzlich existiert der Skill `archon-os-debug` (Session-Skillindex) mit denselben Kernfakten — immer laden!

---

## 1. Systemzustand (verifiziert, alles läuft)

- **Container:** 12 aktiv (ARCHON-OS, hermes, omniroute, n8n, Pocketbase ×2, CRM, anything-llm, freellmapi, hermes-dashboard, docker-socket-proxy, hermes-dashboard-proxy). **Paperclip-Orchestrator wurde ENTFERNT** (Compose-Eintrag auskommentiert, Container gelöscht — bewusste Entscheidung des Users).
- **Ein UI-Baum:** Root `/` serviert `static/index.html`, alles aus `/static/`. `static_v2/` liegt in `archive/2026-10-09_v2_konsolidierung/` (TOT). Code-Änderungen an Static-Dateien greifen sofort (Volume-Mount `./:/app`), Python-Änderungen brauchen `docker restart ARCHON-OS`.
- **Obsidian:** Projekte konsolidiert in `C:\Mein Obsidian\01_PROJEKTE\` mit Syntax `yyyymmdd-NR-bezeichnung`, Sub-Aufträge als `04_Auftraege/`. Altdaten-Backup: `C:\Mein Obsidian\scratch_backup_projects_20261009`.
- **Backups:** `backup_archon.py` im Projektroot sichert 4 DBs (state.db, kanban.db, agent_os.db, agentic_memory.db) lokal (7 Tage) + NAS `Y:\_ARCHON Backups` (180 Tage). Getestet, funktioniert. **User legt den stündlichen Windows-Task-Scheduler-Job selbst an (noch offen!).**

## 2. Was heute behoben/gebaut wurde

### Behobene Bugs (alle live verifiziert)
1. **Settings-Modal:** Race Condition — `#system-settings-mount` existiert erst in view_design_system.html, Settings-Fetch lief davor ins Leere. Fix: `ensureSettingsModalMounted()`-Guard in system_settings.js + Nach-Montage in initArchonApp.
2. **CSS Live Studio:** `css_live_studio.js` war syntaktisch tot (PowerShell/sed- Verstümmelungen: `fetch(/api/themes/)` o.ä.). Komplett repariert (Themes-API korrekt angebunden).
3. **Token-Guard (Guardian):** Logic steckte in css_live_studio.js → starb mit. Jetzt eigenes Modul `static/js/guardian.js` (420 Zeilen, inkl. der Funktionen aus index.html extrahiert).
4. **Token-Preisanzeige:** Füll-Logik fehlte komplett. Jetzt: `updateAgentTabModelCost()` in agent_profiles.js, federt `/api/llm-providers/prices` (OpenRouter-Livedaten, 60-min-Server-Cache), Anzeige neben Modell-Dropdown im Agentenkader, mit Fuzzy-Match („≈") für OmniRoute-eigene Modell-IDs.
5. **JEV → PreDecision** umbenannt (Settings-Modal, Tooltips, Notifications) — war zweimal behauptet, nie passiert.
6. **„Sessions weg"-Bug (MONATE alt, Root Cause!):** hermes-Container betreibt `state.db` im WAL-Modus; ARCHON-OS erzwang bei JEDEM Connect `PRAGMA journal_mode=DELETE` → „database is locked" → Endpoints lieferten leere Listen. Fix: PRAGMA raus, `busy_timeout=10000` in `_get_state_db()`. **NIEMALS journal_mode auf state.db erzwingen.**
7. **Kanban-Anzeige leer:** `opsOrgData` war null (Org-Tab nicht geladen) → Render-Crash bei erster Task-Card. Fix: Null-Check in operations_kanban.js + Spalte „Blockiert / Eskalation" zur UI-Konfig ergänzt (war nicht vorhanden!).
8. **Delegations-Tasks wurden nicht abgearbeitet:** Engine legte Tasks als `in_progress` an, aber der Hermes-Dispatcher übernimmt nur `todo`. Fix: INSERT mit `todo`.

### Die Delegations-Architektur (Engine v2 — Herzstück, vollständig verifiziert)

**Ablauf einer Delegation:**
1. Agent (Tier 1/2) schreibt ` ```delegation {"ziel_agent","auftrag","modell","prioritaet"} ` in die Antwort.
2. `main.py` (Delegation Engine v2, ~Zeile 4000+) parst deterministisch (JSON), prüft Hierarchie via `config/org_hierarchy.json` (Tier 1 APEX: default/micha/executive_decision_architect/telegram_bot → alle; Tier 2 LEADs → nur eigenes Team; Tier 3 → verboten), validiert Agent-Existenz.
3. Legt an: Kanban-Task (**status `todo`**!) in kanban.db + Sub-Session `mc_<ts>_<agent>` in state.db + schreibt ✅-Quittung in die Delegator-Session (Anti-Amnesie).
4. **Der hermes-Container (Hostname ee960b01e4fa) ist der Worker:** ticker-cron claimed → spawnt Agentenprozess (Heartbeats) → done/blocked + Attachments unter `/opt/data/kanban/attachments/<task-id>/`. ARCHON-OS ruft KEIN Modell selbst auf (alter Doppel-Motor wurde entfernt).
5. `_bg_watch_task` (im selben Code) pollt bis done/blocked/review (max 20 Min) und: spiegelt Result + Event-Summary in die Sub-Session UND **exportiert automatisch ein Obsidian-Projekt** nach `01_PROJEKTE/yyyymmdd-<task-id>-<slug>/` (PROJEKT.md, 03_Endprodukte, 02_Medien mit Attachments) → im Showroom sichtbar.
6. Legacy `hermes -p ...`-CLI-Befehle laufen als Fallback durch dieselbe Engine.

**Rücklauf-Kanäle (Stand):** Quittung in Session ✓, Kanban ✓, Sub-Session mit Endergebnis ✓, Obsidian/Showroom ✓ (auto), Telegram ✗ (offen, s.u.).

**Skills:** `~/.hermes/skills/skill-task-delegation/SKILL.md` (v2, Protokoll-Doku) — zugewiesen an 8 Profile in agent_profiles.json (3 APEX + 5 LEADs). WICHTIG: Das aktive Protokoll wird per `DELEGATION_PROTOCOL_PROMPT` DIREKT in main.py in das Systemprompt der Tier-1/2-Agenten injiziert — Skill-Datei und Prompt synchron halten!

## 3. Getestete Beispiel-Delegationen (in kanban.db + 01_PROJEKTE sichtbar)

- `t-eb6c09` GTM-Strategie → **done**, Artefakt `gtm_strategy_plan.md` (auch in Obsidian 02_Medien)
- `t-e59463` Machbarkeitsstudie Audio-Assets → **blocked durch Agenten selbst**: er braucht RPM-Werte (Spotify/Apple Music 2026), seine Online-Recherche wird von WAFs blockiert. User muss Daten nachliefern oder neu beauftragen.
- `t-eadd98`, `t-98b99a`, `t-46e568` → Test-Tasks, done (können archiviert werden — „Archiv"-Button auf der Task-Card).

## 4. Offene Punkte (priorisiert)

1. **Telegram (ERLEDIGT 09.10.2026, E2E-verifiziert):** Bot **@Beatman_bot** läuft im Polling-Modus, **exklusiv** an Profil `telegram_bot` gebunden (Kommunikations-Agent). **Phase 2 komplett:** Push-Pipeline (`telegram_notify.py`) sendet bei Delegation done/blocked/review + Mission-Approval; HITL-Buttons (📋 Details / ✅ Erlauben / ❌ Verbieten) wirken **direkt** über die ARCHON-OS-API (Adapter-Patch — nach Hermes-Image-Updates erneut ausführen: `docker exec hermes python3 /opt/data/profiles/telegram_bot/scripts/patch_telegram_adapter.py && docker restart hermes`). Text-Fallback: `Details/Erlauben/Verbieten <task_id>`. E2E-Test t-bf29fc: Button-Freigabe → Worker claimte Task → Agent schloss ab (done). Security: Allowlist-only (User-ID 7559390881), `GATEWAY_ALLOW_ALL_USERS=false`.
2. **Backup-Automation:** User will den Scheduler-Job selbst anlegen (Script fertig, Anleitung im Script-Kopf).
3. **Paperclip-Reste (ERLEDIGT 09.10.2026):** Vollständig bereinigt. Reiter 4 im Agentenkader heißt intern & extern `operations` und bleibt voll erhalten. Profil-Status-Toggle läuft über `/api/hermes/profiles/{id}/status`, Polling und tote Docker-Socket-Calls wurden entfernt.
4. **Kosmetik:** `no such table: kv_store` in der Kostenberechnung (Log-Noise, Anzeige zeigt trotzdem Werte).
5. **System-Audit + Handbuch-Neuschreibung:** User will das System von einem anderen Coding-Modell auf Herz und Nieren prüfen lassen (Ineffizienzen, Redundanzen, „Dump"), DANACH das Handbuch final schreiben. Erst wenn laufende Workflows stabil sind.
6. **Kanban-Feinschliff:** User will branchenübliche Funktionen später ergänzen (auf TODO-Liste, nicht jetzt).
7. **Strukturelles Risiko (beobachten):** ARCHON-OS + hermes teilen state.db (WAL) und kanban.db (WAL) über den Bind-Mount. Läuft aktuell stabil mit busy_timeouts, aber quirlig — bei „database is locked" im Log: NICHT journal_mode erzwingen, ggf. Container durchstarten.

## 5. Wichtige Pfade

| Was | Wo |
|---|---|
| Projekt | `C:\.Antigravity-projekte\AgenticOS-2026` |
| Delegation Engine v2 | `main.py` ~Zeile 4000–4260 (`_execute_delegation`, `_bg_watch_task`, `DELEGATION_PROTOCOL_PROMPT`) |
| Org-Hierarchie (SSOT der Rechte) | `config/org_hierarchy.json` (56 Nodes, tier 1/2/3, team_id, links) |
| Agenten-Profile | `agent_profiles.json` (56 Profile, 7 Kategorien, skills) |
| Kanban-DB | `C:\Users\micha\.hermes\kanban.db` (WAL!) |
| state.db (Chats/Sessions) | `C:\Users\micha\.hermes\state.db` (WAL! 145 MB) |
| Obsidian-Projekte | `C:\Mein Obsidian\01_PROJEKTE\` |
| Hermes-Skills | `C:\Users\micha\.hermes\skills\` (inkl. skill-task-delegation v2) |
| Worker-Attachments | `C:\Users\micha\.hermes\kanban\attachments\<task-id>\` |
| Backup-Script | `C:\.Antigravity-projekte\AgenticOS-2026\backup_archon.py` |

## 6. User-Kontext für die neue Session

- User kommuniziert auf Deutsch, testet aktiv die Workflows (Robert/CEO-Delegationen).
- Arbeitsweise: Erst grillen (Fragen bis nichts offen), dann bauen; Behauptungen immer live verifizieren (Antigravity-Changelogs waren oft falsch).
- Master-Chat ist bewusst DEAKTIVIERT (nicht löschen, nur versteckt). Agentenkader ist die primäre Oberfläche.
- JEV heißt im UI „PreDecision", der Kader-Button „Reasoning:".
- User-Antworten auf die Orchestrierungs-Grillfragen (Org-Struktur, Rücklauf, HITL etc.) sind in der Session vom 09.10. dokumentiert — Kernpunkte stehen hier in Abschnitt 2–4.

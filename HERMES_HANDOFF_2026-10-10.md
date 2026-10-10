# 🧠 HERMES HANDOFF — 10.10.2026 (Session: Telegram-Integration E2E + Design-Runde)

> **Zweck:** Vollständiger Wissenstransfer für die nächste Session. Stand: 10.10.2026, ~01:30 Uhr.
> **Skill `archon-os-debug` ist aktuell gepflegt** (dieselben Kernfakten) — immer laden!

---

## 1. Systemzustand (verifiziert, alles läuft)

- **Container:** 12 aktiv. Paperclip entfernt (bewusste Entscheidung).
- **Telegram-Bot @Beatman_bot:** LÄUFT (Polling-Modus), EXKLUSIV an Profil `telegram_bot` gebunden.
- **ARCHON-OS:** Alle Design-Änderungen live, Syntax geprüft, Container neu gestartet (letzte Version aktiv).
- **Obsidian:** Projekte in `01_PROJEKTE/` mit `YYYYMMDD-`-Präfix (neue Generatoren), Mission-Projekte jetzt auch dort statt `Projects/`.
- **Test-Task `t-bf29fc`:** E2E-Test durchgelaufen (done). Kann im Kanban archiviert werden.

## 2. Diese Session erledigt

### A) Telegram-Integration (KOMPLETT, E2E-verifiziert)

**Architektur:**
- Bot @Beatman_bot = Kommunikations-Agent des Owners (Profil `telegram_bot` in hermes-Container).
- Token NUR in `~/.hermes/profiles/telegram_bot/.env` (Profil-Gateways lesen ihre EIGENE .env!).
- ARCHON-OS hat send-only Token-Kopie (Env `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID=7559390881` in compose/archon-os, Werte in Projekt-.env).
- Security: `GATEWAY_ALLOW_ALL_USERS=false` (stand auf true!), `TELEGRAM_ALLOWED_USERS=7559390881`.
- Noise-Reduktion: `TELEGRAM_HOME_CHANNEL` auskommentiert (Shutdown-Broadcasts unterdrückt), `long_running_notifications: false`, `busy_ack_detail: false` in Profil-config.yaml.

**Push-Pipeline (`telegram_notify.py` im Projektroot):**
- Hook 1 in `_bg_watch_task` (main.py): Delegation done/blocked/review → Ping aufs Handy. Texte: „✅ AUFGABE ERLEDIGT", „⛔ AUFGABE BLOCKIERT", „🔐 ENTSCHEIDUNG NÖTIG".
- Hook 2 im Mission-Branch von `/api/chat` (mode=mission): „🔐 FREIGABE ERFORDERLICH".
- Freigabe-Pushs haben Inline-Keyboard: **📋 Details / ✅ Erlauben / ❌ Verbieten** (Callback-Daten `app:action:<task_id>`) + Text-Fallback-Zeile (`Details <id> · Erlauben <id> · Verbieten <id>`).

**Adapter-Patch (KRITISCH — Pflege!):**
- Der Hermes-Telegram-Adapter verwirft unbekannte Callback-Präfixe STILL. Deshalb: chirurgischer Patch in `/opt/hermes/plugins/platforms/telegram/adapter.py` (Container-Dateisystem!). Der `app:`-Zweig verarbeitet die Buttons DIREKT über die ARCHON-OS-API (deterministisch, ohne LLM-Umweg, mit Authorisierungsprüfung).
- **Nach Hermes-Image-Updates/Container-Recreate ERNEUT ausführen:**
  `docker exec hermes python3 /opt/data/profiles/telegram_bot/scripts/patch_telegram_adapter.py && docker restart hermes`
  (Skript ist idempotent, macht Backup `adapter.py.archon-bak`, Syntax-Check inklusive.)
- Fallback falls Patch weg: Text-Befehle über den telegram_bot-Agenten (Skill `archon-remote-control` im Profil).
- HITL-APIs: `PATCH /api/operations/kanban/tasks/<id>/status {status}` (approve=todo/reject=backlog), `POST /api/mission-control/tasks/move {task_id, target_status}` (in_progress/dismissed).
- CEO-Rückkanal: „Beauftrage Robert: X" → telegram_bot ruft `POST /api/chat {agent_id: executive_decision_architect, mode: mission}` → Approval-Gate → Freigabe-Push.
- E2E-Verifikation: t-bf29fc: Button-Erlauben → Status todo → Worker claimed → Agent schloss ab (done).

### B) Design-Runde (alle 9 Punkte, User bestätigt „passt bis jetzt")

1. **Nav-Button aktiv:** transparenter BG + 2px dunkelgrauer Rand (#3f3f46) + mittlerer Schatten — Inline-Styles in `setTab()` (index.html, ~Zeile 2453).
2. **Agentenkader:** Nano-Banana/Quick-Presets entfernt; Eingabe-Boxen (Name/Handle/Stelle/Domäne/Beschreibung) flach (kein Rand/Schatten); Projekt-Historie ohne Schatten. **themes.css-Sammelregel war der Übeltäter** — `prof-box-card` daraus entfernt + explizite Flach-Regel.
3. **Inset-Schatten (Mulde):** Im CSS Live Studio: 3 neue Presets („Mulde/Absenkung", „Tiefe Mulde", „Eingeprägte Kontur") + **„↳ Mulde umschalten (Inset)"-Button** (`toggleShadowInset()` in css_live_studio.js, schaltet erhaben↔inset pro Schicht).
4. **Projekt-Bezeichner:** `task-` → `YYYYMMDD-`-Präfix in `post_task_pipeline.py` (write_project_folder_artifact) + main.py-Fallback (`_sync_task_to_obsidian`); Mission-Projekte nach `01_PROJEKTE/` statt `Projects/`.
5. **Showroom:** Vorschau `height` statt `max-height` (füllt Fläche); Titel IMMER mit Datums-Präfix („20260903 · Titel") in views_core.py (`get_showroom_tree`) — **`re`-Import war nötig** (NameError → 500er!).
6. **JPG-Hintergrund im Studio:** `POST /api/studio/upload-bg` (main.py, nur jpg/png/webp/gif, max 8MB → `static/uploads/`) + „🖼️ JPG/Bild hochladen"-Button in view_app_frame_studio.html + `onStudioBgFileChosen()` (css_live_studio.js) — setzt url()+cover+no-repeat. E2E getestet.
7. **Kanban-Header:** Posteo-Palette (Hex inline), einheitliche 52px-Höhe — `OPS_COLUMNS_CONFIG` + Renderer in operations_kanban.js.
8. **Kanban-Farbpalette in Einstellungen → DESIGN-Tab (frisch fertig, browser-verifiziert: 14 Picker, 7 Vorschauen):**
   - Backend: `GET/POST /api/operations/kanban/palette` (operations_api.py), Speicher `data/kanban_palette.json`, Defaults=Posteo (KANBAN_PALETTE_DEFAULTS), Sanitize (Hex + bekannte Spalten), Merge beim GET (saved überschreibt Defaults).
   - Settings-UI: Abschnitt „KANBAN-FARBPALETTE" in system_settings_modal.html (Design-Tab), dynamisch gerendert in system_settings.js (`loadKanbanPaletteSettings`, `saveKanbanPaletteFromSettings`, `resetKanbanPaletteInSettings`), Tab-Hook in setSettingsTab.
   - Kanban liest Palette via `fetchOpsKanbanPalette()` (operations_kanban.js, beim Script-Load + genutzt im Header-Render mit Posteo-Fallback).
9. **Token Guard Hover:** Lift-Sammelregel in themes.css auf echte Buttons reduziert (nur `#log-containers-list-container > button:hover`, `#log-profiles-list-container > button:hover`).

**Cache-Buster (index.html):** themes.css=202610101030, operations_kanban.js=202610101200, system_settings.js=202610101300, css_live_studio.js=202610101130. **Nach jeder JS/CSS-Änderung neu setzen!**

**Wichtige Lessons dieser Session:**
- Browser-Verifikation: Test-Tabs können stale sein (Titel „🐴" statt ARCHON-OS) → `ensure_real_tab()` + `new_tab()` nutzen; CDP-Evaluationen haben ~5s-Limit → kurzschrittig prüfen.
- Browser lädt index.html/JS teils aus Cache — nach Änderungen: Cache-Buster UND hard-reload prüfen.
- Settings-Script: `const` auf Top-Level + früher Aufruf = TDZ-Fehler; Funktionen mit eigener Fallback-Liste immun gebaut. Verifiziert: Editor rendert (14 Picker/7 Vorschauen, Quelle „Posteo-Standard").
- Live-Studio: Die >100 Studio-Regeln des Users waren BEREITS nach custom_studio.css kompiliert (theme_live_overrides.json leer) — sie wirken als festes Design; Studio-Panel-HTML lebt in `views/view_app_frame_studio.html` (NICHT im static/static/-Spiegel!).

## 3. Offene Punkte (priorisiert)

1. **Kanban-Gesamtredesign (User-TODO):** Spaltenbreite auf 200px (alle 7 Spalten bei 100% Zoom sichtbar), Card-Redesign, **Triage-Frage klären** (User versteht Triage nicht — erklären oder streichen; Paperclip hatte nur 4 Zustände).
2. **Alte Projektordner vereinheitlichen:** Bestände ohne YYYYMMDD-Präfix optional umbenennen (Datum aus PROJEKT.md/frontmatter ableitbar; Ordner-Umbenennung ist wikilink-sicher, DATEI-Umbenennung nicht).
3. **„Spalte: ?" im Telegram-Details-Bericht:** Task-Detail-API liefert kein column_id-Feld (kosmetisch, im Adapter-Patch notiert).
4. **Backup-Automation:** User legt Windows Task-Scheduler-Job selbst an (Anleitung im Kopf von `backup_archon.py`).
5. **Kosmetik:** `no such table: kv_store` Log-Noise (Anzeige zeigt trotzdem Werte).
6. **Kanban-Test-Tasks aufräumen:** `t-eb6c09` etc. archivieren (Archiv-Button auf der Task-Card).
7. **System-Audit + Handbuch-Neuschreibung:** Erst wenn Workflows stabil (User-Wunsch: von anderem Coding-Modell prüfen lassen).
8. **Strukturelles Risiko (beobachten):** state.db + kanban.db im WAL-Modus, von beiden Containern genutzt. Bei „database is locked": NICHT journal_mode erzwingen, `docker restart hermes`.

## 4. Wichtige Pfade (Aktualisiert)

| Was | Wo |
|---|---|
| Projekt | `C:\.Antigravity-projekte\AgenticOS-2026` |
| Telegram-Push-Modul | `telegram_notify.py` (Projektroot) |
| Adapter-Patch-Skript | `C:\Users\micha\.hermes\profiles\telegram_bot\scripts\patch_telegram_adapter.py` |
| telegram_bot-Skill | `C:\Users\micha\.hermes\profiles\telegram_bot\skills\archon-remote-control\SKILL.md` |
| telegram_bot-Env | `C:\Users\micha\.hermes\profiles\telegram_bot\.env` (Token, ALLOWED_USERS) |
| Kanban-Palette (persistiert) | `data/kanban_palette.json` (Projektordner) |
| Studio-Hintergrund-Uploads | `static/uploads/` (Projektordner) |
| Live-Studio-Panel | `static/views/view_app_frame_studio.html` |
| Delegation Engine v2 | `main.py` ~4000–4260 (`_bg_watch_task` mit Telegram-Hook ~4146, `_execute_delegation`, `DELEGATION_PROTOCOL_PROMPT`) |
| Settings-Modal-HTML | `static/views/system_settings_modal.html` (Design-Tab hat Kanban-Palette) |
| Kanban-Renderer | `static/js/operations_kanban.js` (OPS_COLUMNS_CONFIG ~993, Palette-Fetch ~1011, Header-Render ~1080) |

## 5. User-Kontext für die neue Session

- User kommuniziert auf Deutsch, will gegrillt werden vor konzeptionellen Umbauten, verlangt Live-Verifikation aller Behauptungen (Browser/DOM/API).
- Telegram-Bot = sein persönlicher Kommunikations-Agent: Berichte an ihn, Anweisungen an CEO (Robert). Token-Exklusivität beim telegram_bot-Profil ist User-Vorgabe (Polling exklusiv; ARCHON-OS nur sendMessage).
- Design-Geschmack: Posteo-Naturpalette, flache Karten, Hover nur auf klickbarem, Inset-Schatten für Mulden, Datum als Orientierungs-Präfix überall.
- Änderungen an der Farbpalette macht der User künftig selbst über Einstellungen → DESIGN-Tab.

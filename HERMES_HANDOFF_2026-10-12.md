# HERMES HANDOFF — 12.10.2026 (Session-Wechsel, nach Gate/Relay-Arbeit)

## 0) Regeln (User-Vorgaben, unbeugsam)
- **Deutsch.** Bei Architektur-Entscheidungen: VOR dem Bauen clarify mit Empfehlung first („lieber 2x Fragen als 3x Compute").
- **Engine-DB `kanban.db` READ-ONLY** (Features nur über Sidecars/UI). `state.db` = `/opt/data/state.db`.
- JS-Edits: `patch`-Tool + `node --check`. Python: `py_compile` — **Achtung: Laufzeitfehler wie `NameError: CONFIG_DIR` fängt py_compile NICHT** → nach Restart immer Health-URL prüfen!
- Nach JS-/CSS-/View-Edits: **Buster** in `static/index.html` erhöhen.
- Keine Secrets/Token in Texten (Bot-Token immer `***`).
- Testspuren (E2E-Ordner, Test-Gates, Test-Tools) nach Tests entfernen; Löschen erst nach Clarify/Quarantäne.
- **Zuerst Skill laden:** `projects/archon-os-debug` (+ `references/css-live-studio.md`).

## 1) Umgebung (Kurzfassung)
- Projekt: `C:\.Antigravity-projekte\AgenticOS-2026` (git main, HEAD **569c2be**, remote `github.com/michaelbeatman/Agentic-Archon-Os`).
- Container: **ARCHON-OS:8501** (FastAPI, Repo-Bind), **hermes** (Gateways incl. Telegram-Bot), **n8n:5678** (bewusst draußen), omniroute:20128, docker-socket-proxy.
- **Telegram-Architektur:** @Beatman_bot; Token in ARCHON `.env`, `TELEGRAM_CHAT_ID=7559390881`. ARCHON sendet ausgehend via `telegram_notify.py` (Markdown + Retry-ohne-parse_mode bei Entities-400). **HERMES `telegram_bot`-Gateway ist der EINZIGE Poller (getUpdates)** und verarbeitet Button-Callbacks in `/opt/hermes/plugins/platforms/telegram/adapter.py` → `_handle_callback_query` (Prefix-Dispatch `mp:/cp:/gt:/ea:` + `gate:`). ARCHON darf NICHT pollen.
- Browser-Harness: `js()` 5-s-IPC-Limit; `window.alert = () => {}` vor Aktionen; Reload via `location.href + ?v=`; CDP-Hook stirbt mit jedem Daemon-Restart; Python im Container per Datei + `docker cp` (keine inline-python mit Backticks/Quotes über bash).

## 2) AKUT (Prio 1): Telegram-Gate-Buttons liegen still
**Stand:**
- Gate-Baustein fertig + committed (`569c2be`): Tools-Differenz/Profil-Löschen → `pending_owner_approval` (NICHTS gespeichert) + Telegram-Ping mit Buttons `gate:approve/reject:<id>` + Text-Fallback („Erlauben <gate_id>"); Decide `/api/permission-gates/{id}/decide` ist **sync** (als async blockierte es die Event-Loop).
- Adapter-Patch (eigener `gate:`-Zweig: Auth-Check + POST an ARCHON + `query.answer()`-Toast) **SITZT** in `adapter.py` (Syntax ok). Sicherung + Rezept: **`scripts/patches/telegram_adapter_gate_patch.md`** — `/opt/hermes` ist IMAGE-LAYER; der alte `app:*`-09.10-Patch ist bei einem Image-Update bereits verschwunden → nach jedem Hermes-Update neu anwenden.
- **PROBLEM (User-Befund):** User bekam die 🔐-Pings (ausgehend 200), klickte ✅ auf **zwei** Gates → **kein Toast, kein Decide** (beide `pending` in `config/permission_gates.json`: `gate-20261012142648-2d7c`, `gate-20261012143110-9029`, beide „storyteller + x_search_probe/probe2"). Beim ALLERERSTEN Gate (`28d9`) funktionierte der Klick einmal (approved in 2 s). Eine vom User gesehene „Abgelehnt"-Nachricht war ein EIGENER Test-Reject (`f8ab`, delete-Test) — nicht sein Klick!
- Gateway läuft: `hermes -p telegram_bot gateway run --replace` unter s6; existierende Warnung: **„No env user allowlists configured … deny unknown senders"**.
- Verdächtige in Reihenfolge: (a) **Runner-Auth fail-closed** (`_is_callback_user_authorized` ohne Allowlist), (b) Callback erreicht den `gate:`-Zweig nicht, (c) Polling-Lücke/409.
- **Nächster Schritt:** Logging in den `gate:`-Zweig (info: data/user/chat; warning: auth-fail; info: decision+http-ok) — **Anker-Sicherheit** (vorher scheiterten Anker an Escapes/Indentation: base64-Python via `docker exec hermes python -c`, dann py_compile im Container), `docker restart hermes`, **User bittet, erneut ✅ zu drücken**, Log lesen → Unterscheidung Auth vs. Dispatch. Befund-Aktion: `TELEGRAM_ALLOWED_USERS=7559390881` (Hermes-Env) ODER Gate-Auth auf Owner-Chat-ID lockern.
- Danach: 2 pending Gates per Decide **approve nachholen** (User erlaubte sie mündlich), Test-Tools `x_search_probe`/`x_search_probe2` aus `storyteller_ghostwriter` entfernen (Entfernen = keine Erweiterung → kein Gate), `config/permission_gates.json` + `agent_profiles.json` committen.

## 3) In dieser Session erledigt (vertrauen, nicht nachbauen)
1. **Delegation-Loop A+B (User-Entscheidung):** `parent_project_id` im ```delegation```-JSON (+ Regel im Protokoll-Prompt) → Fan-in-Brücke (Auto-Parent, MC-Subtask-Spiegel `kanban_task_id`, Kanban `project_id` + `task_links`) → Watcher-Rücklauf → `_fan_in_maybe_start_synthesis` (Dedupe `synthesis_started`) → **Lisa** (`aggregation_lisa`: profile.yaml + SOUL.md + Personalakte + 5 Skills) fasst zusammen → **Robert** gibt frei (FREIGABE/ABLEHNUNG als erste Zeile) → Finalisierung (Parent completed, Obsidian, n8n-Bridge) oder Approval-Task → Board-Move finalisiert über denselben Helper. E2E mit 3 Teilaufträgen grün. Extra-Fix: `_ensure_session_exists` idempotent (UNIQUE title), Helper-Parameter `daten=`.
2. **Ordnerflut-Fix („ein Projekt = ein Ordner"):** `project_folder_name()` in `post_task_pipeline.py` = Quelle der Wahrheit (Kinder mit Parent teilen EINEN Ordner `<YYYYMMDD>-<pid>-<slug>`; ohne Parent eigener Ordner); Beobachter/Pipeline/Synthese nutzen sie; PROJEKT.md nur im `"x"`-Modus; Lisas Entwurf + Final in `03_Endprodukte/`; Approval-Task trägt `parent_project_title`. E2E: genau 1 Ordner; alte E2E-Ordner bereinigt (01_PROJEKTE = 11 echte Einträge).
3. **Media-Relay:** `POST /api/telegram/relay` (Form: `ziel_agent`, `text`, `datei_b64`) → Anhang nach `static/uploads/telegram/` → `core_dispatcher.dispatch…` → Antwort automatisch per Telegram zurück (`asyncio.to_thread`, kein Loop-Block). E2E: PONG/PONG2 (~7 s) + PNG-Anhang 127 KB, Telegram-200. Skill `archon-remote-control` (Container `/opt/data/profiles/telegram_bot/skills/`) um Abschnitt 6 (Gate-Textbefehle) + 7 (Media-Relay-Rezept mit base64) ergänzt (base64-append).
4. **telegram_notify:** Markdown-400-Retry (Unterstriche in Tool-Namen = unvollständige Entity) — Retry OHNE parse_mode, **INNERHALB des `with httpx.Client`-Blocks** (außerhalb: „client has been closed"). Relay-Helper `_tg_send_relay` musste nachträglich ergänzt werden (NameError → Warnung).
5. Davor am Tag: Lade-Overlay-Freeze behoben (`display:none !important`-Hardcut; eingefrorene Transition), Kanban-Zähler ohne Studio-Bild (themes.css), CSS-Studio-Remove (3 Quellen + `url("")`=Löschen + kein Server-Leer-Wipe + Upload ohne Selector→Body), Auto-Init statt stummem AppShell-onload-Catch, systemweites Datei-Preview (System→Viewer, Extern→Original öffnen).
6. **n8n:** bewusst draußen (User: später für Außenkommunikation); importierter Workflow `a7c3f1e9b2d84f6a` inaktiv (Rezept: `n8n import:workflow -i …`, `publish:workflow --id=…`, `docker restart n8n`); Synthese-Bridge meldet 200.

## 4) Offene Themen (priorisiert)
1. Gate-Buttons (Prio 1, siehe oben).
2. **Workspace-Deklination** (User-Wunsch 11.10): Kanban-`workspace_path` ist meist toter „scratch"; Brücke = Sidecar `config/kanban_meta.json` → `obsidian` → `01_PROJEKTE/<ordner>`; Hermes-„Workspace" = nur cwd. User will saubere Deklination — Entscheidung ausstehend.
3. Fetch-Timeout-Wrapper (Option B, ~245 Fetches, 1 ohne Timeout) — angeboten, **nicht freigegeben**.
4. Roberts bestehende 6 Projektordner vom 11.10 (echter 5-Teiler-Fall) in EINEN zusammenlegen? User-Entscheidung offen (nicht angefasst).
5. Klein: doppelte `startMissionControlStopwatches`-Deklaration (harmlos); 25-s-MC-State-Blockade (strukturiell gefixt, nie wieder gesehen).

## 5) Wichtige Stellen/Dateien
- `main.py`: Gate ~3090ff, Decide ~3155ff, Relay ~3220ff (`_tg_send_relay`!), Delegation/Fan-in ~4005/4230ff + Watcher `_bg_watch_task`, Synthese-Loop ~9150ff, `_ensure_session_exists` ~3660ff.
- `backend/post_task_pipeline.py`: `project_folder_name()` + `write_project_folder_artifact()`.
- `telegram_notify.py`; `scripts/patches/telegram_adapter_gate_patch.md`; `config/permission_gates.json` (2 Pending-Tests, uncommitted).
- `static/js/agent_profiles.js` (Pending-Toast), `static/index.html` (Overlay-Hardcut).
- Container: `/opt/data/profiles/aggregation_lisa/`, `/opt/data/profiles/telegram_bot/skills/archon-remote-control/SKILL.md`, Adapter `/opt/hermes/plugins/platforms/telegram/adapter.py`.
- Testskripte (Scratch + Container `/tmp`): `loop_e2e.py` (3-Teiler-Loop inkl. Auto-Move), `relay_test.py`, `ping_gate.py`, `fanin_e2e2.py`.
- Obsidian `01_PROJEKTE`: 11 Einträge; Telegram-Uploads: `static/uploads/telegram/`.
- Uncommitted (bewusst): `agent_profiles.json`, `config/permission_gates.json` (Test-Gates) — nach Button-Fix committen.

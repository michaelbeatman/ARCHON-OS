# HERMES HANDOFF — 12.10.2026 (Abend, nach Gate/Entscheidungs-Service/Format-Arbeit)

> Eingehendes Handout der Vorsession: `HERMES_HANDOFF_2026-10-12.md` (Morgen-Stand, Gate-Defekt
> noch offen). **Dieses Dokument ist der aktuelle Stand.**

## 0) Regeln (User-Vorgaben, unbeugsam)

- **Deutsch.** Bei Architektur-Entscheidungen VOR dem Bauen `clarify` mit Empfehlung first
  („lieber 2× Fragen als 3× Compute"). Der User erwartet aktives Grillen.
- **Engine-DB `kanban.db` READ-ONLY** — lesen ja, schreiben nur über die API/UI-Pfade.
  `state.db` = `/opt/data/state.db`.
- JS-Edits: `patch`-Tool + `node --check`. Python: `py_compile` — **fängt keine Laufzeitfehler**
  → nach Restart immer Health-URL prüfen.
- Nach JS-/CSS-/View-Edits: **Buster** in `static/index.html` erhöhen (sonst liest der Browser
  den Cache).
- Keine Secrets/Token in Texten (Bot-Token immer `***`).
- Testspuren nach Tests entfernen (E2E-Ordner, Test-Gates, Test-Tools). Löschen erst nach Clarify.
- **Zuerst Skill laden:** `projects/archon-os-debug` (+ references/CSS-Studio).

## 1) Umgebung

- Projekt: `C:\.Antigravity-projekte\AgenticOS-2026`, Branch `main`, **HEAD `88cbaaa`**,
  remote `github.com/michaelbeatman/Agentic-Archon-Os`. Working Tree **sauber**.
- Container: **ARCHON-OS:8501** (FastAPI), **hermes** (Gateways inkl. Telegram-Bot),
  **n8n:5678** (bewusst draußen), omniroute:20128, CRM:3005, Pocketbase.
- **Telegram:** @Beatman_bot, Owner-Chat `7559390881`. ARCHON sendet ausgehend
  (`telegram_notify.py`); der **Hermes `telegram_bot`-Gateway ist der EINZIGE Poller**.
- **WICHTIG — `/app` IST der Projekt-Bind-Mount.** `docker cp <datei> ARCHON-OS:/app/...`
  überschreibt den Quellcode. Projektdateien nur auf der Platte editieren (Python braucht
  `docker restart ARCHON-OS`). `docker cp` nur außerhalb des Binds (`hermes:/opt/hermes/...`).
- **`/app/data/` ist ein anonymer Volume und ÜBERSCHATTET den Bind.** Die App liest
  Profile u. a. aus `/app/data/agent_profiles.json` — Host-Edits an der Projektdatei wirken
  dort nicht zwingend.

## 2) HEUTE FERTIG (Commits, mit Belegen — nicht nachbauen)

| Bereich | Commit | Beleg |
|---|---|---|
| Gate-Button-Defekt geklärt + gefixt | `5de2a43` | **Kein Auth-Bug**: transienter Container-DNS/Connect-Fehler (hohe Last, Gateway-SIGKILLs). Adapter hat `_archon_req` mit 3 Retries + Backoff + IP-Notfallpfad. **Per echtem Klick des Users Ende-zu-Ende verifiziert** (`approved`, POST 200, Ausführung gelaufen). |
| 2a Zwischenbericht als HTML-Dossier | `64a8e7b` | `sendDocument: True` live; `dossier_builder.py` (abhängigkeitsfrei, kein PDF-Tool im Image). |
| Lisa-Profil | `d8b8cb5`, `ba47c47`, `8186e24` | Kategorie 5 (Synthese), Modell `openrouter / xiaomi/mimo-v2.6-flash`, alle 5 Skills lösen auf, SOUL.md mit Umlauten + „Messaging other agents". **Live-Prompt korrekt** (2869 Zeichen, keine ASCII-Reste). |
| 2c Zentraler Entscheidungs-Service | `d028841`, `2492ab3` | Eine **Entscheidung IST ein Kanban-Task** (Status `review`) + Sidecar-Block. EIN Schreibpfad `POST /api/decisions/decide`. Alle 4 Typen angebunden. |
| 2b Kanban-Reader | `4295cd1` | Detail-Dialog: Entscheidungs-Panel, Dossier im **sandboxed iframe** gerendert (statt Textdump), Freigeben/Ablehnen. Browser-verifiziert. |
| 2d Formatierung | `88cbaaa` | Telegram **HTML statt Markdown** (Wurzel der 400er) + Format „Kontext zuerst"; Card mit **Entscheidungs-Banner**, ohne Archiv-Knopf, ohne `t-ID` im Kopf, mit Projektzeile. Browser-verifiziert. |

### Der Entscheidungs-Service (wichtigstes neues Bauteil)

```
Telegram-Klick ──┐                          ┌── Kanban: Dialog-Buttons
                 ├──► POST /api/decisions/decide ──► kanban.db (Wahrheit)
Kanban-Dropdown ─┘                          └── Telegram-Bestätigung
```

- **Sidecar:** `config/kanban_meta.json` → `tasks[<tid>].decision = {typ, ref_id, titel,
  kurzfassung, dossier, status, entschieden_von, entschieden_am}`; ebenso `obsidian`.
- **Typen + Semantik:** `delegation_review` → approve `todo` / reject `archived`;
  `synthesis_freigabe` → `done` (Finalisierung) / `archived`;
  `mission_freigabe` → `in_progress` (Move-Pfad startet) / `archived`;
  `permission_gate` → `done` (Gate ausgeführt) / `archived`.
- **Erzeuger:** Synthese (`create_decision`), Rechte-Gates (`_create_permission_gate`),
  Missions-Freigabe, Delegations-Review (`register_decision` auf den BESTEHENDEN Task).
- **Gegenrichtung:** `update_task_status` (operations_api) pingt den Owner, wenn ein Task mit
  `decision`-Block von `review` weg verschoben wird — außer bei `source="decision"`.

## 3) OFFEN — Kleinkram (vom User bestätigt, noch NICHT erledigt)

1. **Sidecar ohne Schreibsperre** (`config/kanban_meta.json`, read-modify-write).
   Bei parallelem Fan-in können Entscheidungs-Metadaten verlorengehen — **einziger Punkt mit
   echtem Datenrisiko**. Geplanter Fix: `threading.Lock` um die ganze Load-Ändern-Speichern-
   Sequenz in `save_kanban_meta` + **atomares Schreiben** (Temp-Datei + `os.replace`).
   → Recherche wurde begonnen und **abgebrochen** (wer den Sidecar sonst noch schreibt, ist
   NICHT abschließend geklärt; die Suche war read-only, es wurde nichts geändert).
2. Zwei alte `mcapp-*`-Sidecar-Einträge aus der Vorsession
   (`mcapp-projekt-e2e-fanin`, `mcapp-projekt-loop-e2e`) — Reste des abgelösten MC-Modells.
3. Archivierte Test-Tasks auf dem Board (u. a. `t-fa7da9`, `t-8bb502`, `t-1b72b9`, `t-0403ed`,
   `t-a557f3`, `t-51a1e3` sowie ältere `E2E …`-Tasks). Purge-Kommando des `hermes kanban`-CLI
   vorher prüfen.
4. **Adapter-Antworttexte** (`reply_text` im Hermes-Adapter) nutzen noch `parse_mode="Markdown"`
   mit `` ` ``-Quotes. Funktioniert, hat aber denselben 400-Risikopfad → bei Gelegenheit auf HTML.

## 4) Wichtige Stellen/Dateien

- `main.py`: Permission-Gate ~3093ff, **Entscheidungs-Service ~3270–3500**
  (`_decision_kanban_status`, `_decision_self_api`, `register_decision`, `create_decision`,
  `_decision_followup`, `POST /api/decisions/decide`), Delegations-Watcher `_bg_watch_task`
  ~4430ff (Ping/Audit), Missions-Freigabe ~4870, `_finalize_synthesis_after_approval` ~9400,
  `_run_synthesis_cascade` ~9500ff.
- `backend/operations_api.py`: `_enrich_task` (~82, liefert obsidian+decision an die Liste),
  `TaskStatusUpdateRequest.source` (~110), `update_task_status` (~245 + Telegram-Hook),
  `save_kanban_meta` (~495, versteht `decision` + `obsidian`), Detail-Route (~610).
- `telegram_notify.py`: `tg_escape`, `decision_message`, `send_telegram_message` (HTML),
  `send_telegram_document` (parse_mode-Parameter), `notify_task_status`.
- `dossier_builder.py` (neu): `build_dossier_from_report` → HTML-Dossier.
- **`scripts/patches/telegram_adapter_gate_patch.md`** — Sicherung des Adapter-Patches.
  `/opt/hermes` ist IMAGE-LAYER: **nach jedem Hermes-Image-Update neu anwenden!**
- `sketches/2d-format/001-decision-first|002-context-first/` — die beiden Design-Entwürfe
  (Variante B wurde umgesetzt).
- Lisa: `C:\Users\micha\.hermes\profiles\aggregation_lisa\{SOUL.md,profile.yaml}`;
  Skills-Store `C:\Users\micha\.hermes\skills\`.

## 5) Lehren aus dieser Session (teuer bezahlt)

- **Blockierender Selbst-HTTP im async-Handler = Event-Loop-Deadlock.** Der Entscheidungs-
  Endpoint ruft die eigene API; als `sync`-Aufruf im `async def` endete das als
  `502 "Sidecar nicht lesbar: timed out"`. Regel: **jeder** Selbstaufruf über
  `await asyncio.to_thread(...)`. Bei „timed out, obwohl simpel" zuerst daran denken.
- **Retry + nicht-idempotenter Endpoint = doppelte Ausführung.** Der Adapter-Retry führte die
  Folgeaktion ZWEIMAL aus (Mission hätte doppelt gestartet). Fix: Idempotenz-Sperre im
  Endpoint (Sidecar-Status ≠ `offen` → früher Ausstieg). **Jeder Endpoint mit Außenwirkung
  braucht einen Idempotenz-Wächter.**
- **adapter/seitiges Timeout nie kleiner als die serverseitige Bearbeitung** (12 s → 25 s).
- **`SOUL.md` ist eine geschützte Datei:** `write_file` verweigert (Schutz-Prompt +
  „partial view"-Guard). Zuverlässig: **`patch`** mit dem kompletten alten Dateiinhalt.
- **`docker exec` ohne `-i` liest kein stdin** — `python3 - <<EOF` läuft still als No-Op.
  Skript in eine sichtbare Datei schreiben und `docker exec … python3 /pfad` aufrufen.
- **Markdown ist die falsche Wahl für Bot-Nachrichten**, wenn Nutzdaten kommen: `_` zerbricht
  Entities → HTTP 400. HTML braucht nur `<`, `>`, `&`.
- Gate-Pings mit `_` im Text erzeugten früher 400er; mit HTML ist das erledigt.
- Shell: Sonderzeichen (Gedankenstrich) in `curl -d` können das JSON zerschießen
  („error parsing the body") — ASCII verwenden oder Datei einspielen.

## 6) Nächster sinnvoller Schritt

Kleinigkeit **(1) Sidecar-Schreibsperre** zuerst (Datenrisiko), dann (2) und (3) aufräumen.
Danach ist die Agenda des Users abgearbeitet und man kann an die **strukturellen** Themen
aus dem Orchestrierungs-Scan gehen, die bewusst NICHT angefasst wurden:

- zwei parallele Task-Welten (Mission-Control vs. kanban.db) endgültig zusammenführen,
- Fan-in-Race (`_fan_in_maybe_start_synthesis`: load→check→set→save ohne Atomarität),
- „Marker-Kontrakt" (Lisas `SYNTHESE-BEREIT` wird nie geprüft),
- Robuste ROBERT-Freigabe-Erkennung (`"FREIGABE" in erste` ist substring-fragil).

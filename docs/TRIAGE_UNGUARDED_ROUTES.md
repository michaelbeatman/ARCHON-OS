# Triage: 9 ungeschuetzte Schreib-Routen mit Gefahrensignal

Stand: 07.11.2026 22:36 CET · Branch `refactor/a5-di-config` @ `9926a9ea` · **nur Analyse, keine Code-Aenderung**

Messbefehl (Skript liegt im Skill, nicht im Repo):

```
.venv/bin/python ~/.hermes/profiles/senior_fullstack_engineer/skills/archon-os-betrieb/scripts/audit_route_guards.py --root .
# -> Routen mit Zaun: 120 | Schreib-Routen ohne Zaun: 214 | davon mit Gefahrensignal: 9
```

Zusatzmessungen: `scratch/triage_scan.py` (Dateischreib-Signale, Klasse-B-Quote, Rollen in der Auth-DB),
`scratch/fs_list.py` (42er-Liste), `scratch/b_quote.py` (Pfad-Gruppen). Alle Zeilennummern frisch erhoben.

> Hinweis zur Messung: `main.py` ist **uncommittet modifiziert** (`M`), ein paralleler Avatar-Umbau hat die
> Datei um 22:35:55 um 15 Zeilen erweitert (Diff nur bei 10660: `GET /static/avatars/{filename}`).
> Die Nummern unten sind der Stand 22:36; der Rollback-Handler wanderte dabei von 10929 auf **10944**.

## Der eigentliche Befund zuerst: es gibt einen globalen Auth-Gate, aber keinen Rollenzaun

`main.py:184-229` (`@app.middleware("http") async def auth_gate`) prueft bei `auth.enabled = true` **jeden**
`/api/*`-Pfad: gueltige Session (Bearer / `X-Archon-Session` / Cookie `archon_session`) **oder**
`X-Archon-Service-Token` (`main.py:175-181`) — sonst `401`. Der Service-Token vergibt dabei **volle
Admin-Rolle** (`main.py:7366-7375`), nicht nur "intern".

Live belegt (nur lesend):

```
cat agent_workspace/settings.json -> "auth": {"enabled": true, "mode": "multi_user"}
cat settings.json                -> "auth": {"enabled": true, ...}
curl /api/auth/status            -> {"status":"success","auth_enabled":true}
curl /api/themes (ohne Login)    -> 401     curl /health -> 200
ss -ltn | grep 8501              -> 127.0.0.1:8501 (nicht 0.0.0.0)
```

Damit gilt fuer alle neun: **kein anonymer Zugriff, aber jeder eingeloggte Nutzer** (Rolle egal — keine
der neun Routen ruft `require_admin*` und keine hat eine Inline-Rolle). In der Auth-DB existiert derzeit
**genau ein Konto, Rolle `admin`** (`data/agentic_memory.db`, `SELECT role,is_active,COUNT(*) FROM users`),
d. h. die fehlende Rollentrennung ist **latent**: sie beisst, sobald ein `viewer`/`operator` angelegt wird
(was `backend/auth_service.py:113-149` vorsieht). Faellt `auth.enabled` aus (Toggle `main.py:7424`, oder
Settings-Datei unlesbar -> `auth_service.is_auth_enabled()` liefert `False`), verschwindet der Gate und
alle neun sind offen.

## Steckbriefe

### 1) `main.py:766` `DELETE /api/themes/{theme_name}` — `api_delete_theme_by_name`
- **Schutz:** globaler Auth-Gate; kein Rollenzaun, keine Inline-Pruefung, kein Service-Token-Zwang.
- **Tut:** `os.remove(os.path.join(THEMES_DIR, f"{theme_name}.json"))` (`766-770`); `THEMES_DIR = WORKSPACE_DIR/themes`
  (`archon/core/paths.py:41`). Kein `safe_path`, aber `{theme_name}` ist ein Path-Param ohne `/` → kein Traversal.
- **Schaden:** Loeschen von Theme-JSONs der Design-Verwaltung. Kein Code, kein Vault, kein Container.
- **Klasse:** BEWUSST OFFEN / VERTRAEGLICH — Selbstbedienung Theme-Editor, hinter Login-Gate (`401` live belegt).
- **Massnahme:** optional `require_admin_or_503(request)`; kein Automat ruft die Route (nur UI), also risikolos.

### 2) `main.py:1913` `DELETE /api/v1/quickchat/session/{profile_id}` — `api_delete_quickchat_session`
- **Schutz:** globaler Auth-Gate; kein Rollenzaun.
- **Tut:** `os.remove(_quickchat_session_path(profile_id))`; der Pfad wird **sanitisiert**
  (`re.sub(r"[^a-zA-Z0-9_\-]", "_", ...)`, `main.py:1787-1790`) → kein Traversal.
- **Schaden:** eigene Chat-History eines Profils loeschen (JSON unter `QUICKCHAT_SESSIONS_DIR`). Kein Fremdschaden.
- **Klasse:** BEWUSST OFFEN — Selbstbedienung "Session zuruecksetzen".
- **Massnahme:** keine; ein Zaun wuerde nur den Nutzer selbst ausperren.

### 3) `main.py:2207` `POST /api/v1/library/upload` — `api_library_upload`  ← schwerster Fall
- **Schutz:** globaler Auth-Gate; kein Rollenzaun.
- **Tut:** `file_path = os.path.join(raw_dir, file.filename)` (`2230`) und `open(file_path,"wb")` (`2232`) —
  **`file.filename` ungefiltert, kein `basename`, kein `safe_path`**. Das `subprocess` im Rumpf ist harmlos:
  feste Liste `[sys.executable, sync_script, "--api-key", <hartkodierter Key>, "--all"]` (`2254-2258`),
  nichts aus der Eingabe. Nebenbefund: **API-Key im Klartext im Code** (`2257`).
- **Schaden:** beliebiges Dateischreiben mit Container-UID 1000 (`docker exec ARCHON-OS id` -> `uid=1000`),
  Zielordner `library/raw_docs` verlassbar; `/app/main.py` ist fuer diese UID **beschreibbar**
  (`test -w /app/main.py` -> WRITABLE) und der Container laeuft mit `--reload`
  (`docker inspect ... Cmd` -> `uvicorn main:app ... --reload`) → **Codeausfuehrung im Container** per
  Upload auf `../../main.py`. Schlimmster realistischer Fall: RCE als `streamlituser` (Zugriff auf alle
  Bind-Mounts: Repo, `/opt/data`, `~/.hermes`, Docker-Socket je nach Mount).
- **Klasse:** **B nur formal** (Login-Gate live belegt, Listener 127.0.0.1) — inhaltlich die gefaehrlichste
  der neun; ein `viewer`-Konto genuegt fuer RCE.
- **Massnahme:** `os.path.basename(file.filename)` + `safe_path(..., allow_write=True)` **und**
  `require_admin_or_503(request)`. Legitime Aufrufer: die Library-UI (eingeloggter Nutzer) — kein Automat.

### 4) `main.py:3025` `POST /api/telegram/voice-relay` — `api_telegram_voice_relay`
- **Schutz:** globaler Auth-Gate; kein Rollenzaun.
- **Tut:** nimmt Upload oder `file_id`, transkribiert (LLM), leitet an `api_telegram_relay` weiter (`3064`)
  und sendet Sprach-/Textantwort an `chat_id or TELEGRAM_CHAT_ID` (`3069-3073`). Das `os.remove` (`3074-3075`)
  trifft **nur die selbst erzeugte** `speech_path`, nie eine Eingabe.
- **Schaden:** Kosten (Transkription + Agentenlauf) und **Telegram-Nachrichten an beliebige `chat_id`** mit
  den Bot-Credentials (Spam an fremde Chats, soweit der Bot sie erreicht); Trigger fuer Agentenarbeit.
- **Aufrufer:** im Repo **kein** Aufrufer (`grep -rn "voice-relay"` nur main.py + openapi-Baseline) —
  gedacht fuer den Telegram-Adapter ausserhalb des Repos; dessen Vertrauenswuerdigkeit ist von hier aus
  nicht belegbar.
- **Klasse:** BEWUSST OFFEN (Login-Gate) — Aufruferfrage offen, Schutz messbar.
- **Massnahme:** Service-Token **oder** Admin verlangen, weil der Endpunkt Bot-Credentials und LLM-Kosten
  bewegt; Adapter muss dann `X-Archon-Service-Token` senden (er tut das laut `main.py:203` bereits fuer
  andere Pfade). Vorher Aufrufer beim Nutzer klaeren.

### 5) `main.py:8456` `DELETE /api/vault?path=` — `api_delete_vault_file_direct`
- **Schutz:** globaler Auth-Gate; **kein** Rollenzaun. Pfad laeuft durch das Jail:
  `safe_path(path, must_exist=True, allow_write=True, allow_dirs=False)` (`8458`).
- **Tut:** `os.remove(real_path)` (`8463`). Jail-Wurzeln (`utils/path_jail.py:32-54`): `/opt/data`,
  `/app/agent_workspace`, `./agent_workspace`, `data`, Vaults, **`~/.hermes`** — `/app` (Code) ist **nicht** dabei.
- **Schaden:** Loeschen beliebiger Notizen im Obsidian-Vault **und** beliebiger Dateien unter `~/.hermes`
  (Hermes-Config, Memory-DB, Skills) durch jeden eingeloggten Nicht-Admin. Kein Code, kein Exec.
- **Klasse:** BEWUSST OFFEN fuer den Vault-Teil; die `~/.hermes`-Reichweite ist **mehr als Selbstbedienung**.
- **Massnahme:** `require_admin_or_503(request)` — und `~/.hermes` nur fuer Lesezugriffe zulassen
  (Schreib-Wurzeln trennen). Betroffen: der Vault-Editor; Loeschen ist heute schon eine bewusste Nutzeraktion.

### 6) `main.py:10944` `POST /api/traces/{task_id}/rollback` — `api_rollback_task_trace`
- **Schutz:** globaler Auth-Gate; kein Rollenzaun.
- **Tut:** `time_travel_debugger.rollback_to_step(task_id, to_step)` (`10931-10934`) →
  `snapshot_manager.restore_snapshot()` schreibt je Schritt die **in der DB gespeicherte** `file_path`
  zurueck (`backend/snapshot_manager.py:98-133`, `open(target_path,"wb")`). Der Zielpfad kommt aus der
  Snapshot-DB, **nicht** aus dem Request → kein freies Dateischreiben; `task_id` und `to_step` sind frei waehlbar.
- **Schaden:** Zustands-Rollback fremder Tasks/Dateien auf alte Staende (Arbeitsverlust, inkonsistente
  Agenten-Artefakte). Kein Exec.
- **Klasse:** BEWUSST OFFEN (Login-Gate) — Zustandsaenderung, aber kein Pfad aus der Eingabe.
- **Massnahme:** `require_admin_or_503(request)`; Aufrufer ist der Time-Travel-Debugger in der UI
  (kein Automat im Repo gefunden) — Risiko fuer legitime Nutzung gering.

### 7) `backend/operations_api.py:265` `POST /api/operations/kanban/tasks` — `create_kanban_task`
- **Schutz:** globaler Auth-Gate (`router = APIRouter(prefix="/api/operations")`, `operations_api.py:25`);
  **kein** Zaun — obwohl dasselbe Modul `require_admin_or_503` importiert und in 26 anderen Routen nutzt.
- **Tut:** `INSERT INTO tasks ...` (`293-307`); bei `req.decompose` `subprocess.Popen(["docker","exec","hermes",
  "hermes","kanban","decompose", task_id])` (`321`) — **task_id ist generiert** (`secrets.token_hex(3)`, `274`),
  also kein Exec aus Eingaben; startet aber einen Agentenlauf im Container `hermes`.
- **Schaden:** Tasks anlegen (mit `model_override`/`provider_override` → Kosten steuern), optional Agenten-
  Decompose starten. Kein Loeschen, kein freier Befehl.
- **Klasse:** BEWUSST OFFEN — Kanban ist bewusst offene Selbstbedienung (Klasse B des Projekts).
- **Massnahme:** keine fuer `create`; wenn Kosten/Agentenlaeufe begrenzt werden sollen, nur `decompose`
  an Admin koppeln (nicht die ganze Route).

### 8) `backend/operations_api.py:781` `POST /api/operations/kanban/bulk/undo` — `api_kanban_bulk_undo`
- **Schutz:** globaler Auth-Gate; kein Zaun.
- **Tut:** `UPDATE tasks SET status=?, assignee=? WHERE id=?` + Tags aus dem In-Memory-Snapshot
  (`_KANBAN_UNDO_STORE`, `798-821`). Der Snapshot stammt aus der vorangehenden Bulk-Aktion, nur ueber
  `undo_token` adressierbar, 10-Minuten-Fenster (`783-791`) — keine freien Werte aus dem Request.
- **Schaden:** Rueckgaengigmachen einer Bulk-Aktion (eigene/letzte Aenderung), Audit-Eintrag wird geschrieben.
- **Klasse:** BEWUSST OFFEN — Selbstbedienung "Undo".
- **Massnahme:** keine.

### 9) `backend/operations_api.py:1611` `POST /api/operations/kanban/palette` — `save_kanban_palette`
- **Schutz:** globaler Auth-Gate; kein Zaun.
- **Tut:** `reset=true` -> `os.remove(WORKSPACE_DIR/config/kanban_palette.json)` (`1613-1619`, Pfad ist eine
  **Konstante**, `1106`); sonst Schreiben mit Allowlist (`col_id in KANBAN_PALETTE_DEFAULTS`) und
  Hex-Validierung `^#[0-9a-fA-F]{6}$` (`1622-1636`).
- **Schaden:** Farbeinstellungen auf Standard zuruecksetzen bzw. aendern. Kein Pfad aus der Eingabe.
- **Klasse:** BEWUSST OFFEN — UI-Einstellung.
- **Massnahme:** keine.

## Zusatzfrage 1: Routen, die der Scan wegen fehlender Gefahrensignale uebersieht

Gemessen mit `scratch/triage_scan.py`/`scratch/fs_list.py`: **42** Schreib-Routen ohne Zaun, deren Rumpf
eine Dateischreib-/Loeschoperation enthaelt (`open(...,"w"/"wb")`, `_save_json`, `atomic_write_json`,
`json.dump`, `os.makedirs`, `shutil.*`, `os.remove`, `write_text`, `os.replace`). Die 9 oben sind Teilmenge.

Die fuenf auffaelligsten:

| Route | Warum auffaellig |
|---|---|
| `main.py:2207` `/api/v1/library/upload` | `file.filename` ungefiltert in `os.path.join` → Traversal/RCE (siehe oben) |
| `archon/routers/hermes_profiles.py:101` `/api/hermes/profiles/{id}/avatar` | schreibt `profile.yaml` in **jeder** Profil-Wurzel (`128-129`) + `~/.hermes/webui/avatars.db`; `profile_id` ungeprueft; kein Zaun |
| `main.py:850` `/api/theme/bake-into-main-design` | schreibt `static/custom_studio.css` aus frei uebergebenen CSS-Regeln (`868-888`) → CSS-Injection in die gesamte Oberflaeche |
| `main.py:7667` `/api/studio/upload-bg` | Dateiupload in `static/uploads`; nur `ext` aus dem Namen uebernommen (`7672-7683`) — sauber, aber ungeschuetzt |
| `main.py:2960` `/api/telegram/relay` | ungeschuetzter Relay-Zwilling von `voice-relay`: Text an Ziel-Agent + Telegram, ohne Zaun |

(`main.py:8400`, `10312` sind dagegen korrekt sanitisiert — `basename` + `re.sub` — und bleiben trotzdem ohne Zaun.)

## Zusatzfrage 2: wie viele der 214 sind bewusst offen?

Grobe Quote nach Pfad-Gruppen (`scratch/b_quote.py`, bewusst grob, keine Einzelpruefung):
**28 von 214 (≈ 13 %)** fallen klar in Klasse B — Kanban 12 (`/kanban/*`), Theme/Quickchat/Chat 13,
Notizen/Vault 3. Beispiele: `/kanban/tasks/{id}/status` (`operations_api.py:534`),
`/api/v1/quickchat/send` (`main.py:1838`), `/api/vault/edit` (`main.py:8439`). Der Rest ist nicht
automatisch "Luecke", sondern schlicht unklassifiziert; ohne den globalen Auth-Gate waeren es 214 offene
Schreibpunkte.

## Ergebnis in einer Zeile

**0 der 9 sind "echte Luecken" im Sinne der Definition** (kein anonymer Zugriff: `401` live belegt,
Listener nur `127.0.0.1`) — aber 3 verlangen eine Massnahme: `library/upload` (Traversal + `--reload` → RCE),
`DELETE /api/vault` (Reichweite bis `~/.hermes`) und `voice-relay` (Bot-Credentials), je eine Zeile Zaun.

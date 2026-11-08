# 🟠-Cluster — Spur A (Routes/Frontend/main.py) — Abschlussbericht

**Worktree:** `/mnt/raid/archon-lane-a` · **Branch:** `fix/orange-a`
**Basis-Commit:** `3269f7e1` · **Bericht erstellt:** 08.11.2026
**Sprache:** Deutsch. Jede Zeile unten ist gemessen, nicht behauptet.

---

## 1. Messwerte

### 1.1 Testsuite

| Messpunkt | Wert | Kommando |
|---|---|---|
| Baseline (Basis-Commit, Arbeitsbaum vor meinen Änderungen) | **962 passed, 15 skipped** | `OBSIDIAN_VAULT_PATH=$PWD/data/obsidian_vault /mnt/raid/AgenticOS-2026/.venv/bin/python -m pytest tests/ -q` |
| Baseline mit `agent_workspace/roles.json` aus dem Haupt-Repo bereitgestellt (damit `test_roles_payload.py` nicht überspringt) | **968 passed, 11 skipped** | dito |
| **Endstand nach meinen 6 Commits** | **1032 passed, 11 skipped** (71,8 s) | dito |
| Differenz zur bereinigten Baseline | **+64 Tests, 0 Regressionen** | — |

**Wichtige Abweichung von der Vorgabe (971 / 8):** Die vorgegebene Baseline
(971 passed / 8 skipped) ist in **dieser Worktree-Umgebung nicht reproduzierbar**.
Gemessen habe ich stattdessen 962/15 bzw. 968/11. Ursache ist die Umgebung, nicht
der Worktree-Code:

* `main.py` legt beim Import `OBSIDIAN_VAULT_DIR` an → auf dem Host ohne
  `/opt/data` (nur im Container gemountet) schlägt der Import mit
  `PermissionError: /opt/data` fehl. Workaround für die Messung:
  `OBSIDIAN_VAULT_PATH=$PWD/data/obsidian_vault`.
* `tests/test_roles_payload.py` (4 Tests) braucht `agent_workspace/roles.json`
  (2,6 MB, im Worktree nicht vorhanden, git-ignoriert). Ich habe die Datei aus
  `/mnt/raid/AgenticOS-2026/agent_workspace/roles.json` **nur zum Messen**
  kopiert (git-ignoriert, nicht committet).
* Ohne diese beiden Anpassungen sind es **962 passed / 15 skipped** — die Zahl
  971/8 des Reviews stammt aus dem Container-Lauf, nicht aus dem Host-Lauf.

**Die 11 verbleibenden Skips sind umgebungsbedingt und unverändert** (Liste aus
`pytest -q -rs`): 3× `/opt/data/obsidian existiert hier nicht`, 1× Symlink im
Zielverzeichnis nicht anlegbar, 4× echter Docker-Daemon nötig, 1× jsdom nicht
installiert, 2× Service-Token fehlt, 1× externer Netzzugang. **Keine bestehende
Assertion wurde entschärft oder gelöscht.**

### 1.2 Rot-Beweise (Altstand `3269f7e1`)

Jeder Fix wurde am Altstand gegengeprüft (`git checkout 3269f7e1 -- <datei>`,
Testlauf, Fix zurück):

| Testdatei | Tests | rot am Altstand | grün nach Fix |
|---|---|---|---|
| `tests/test_orange_a_core_skills.py` | 10 | **8** | 10 |
| `tests/test_orange_a_views_core.py` | 6 | **5** | 6 |
| `tests/test_orange_a_frontend.py` | 7 | **6** | 7 |
| `tests/test_orange_a_notebook.py` | 4 | **3** | 4 |
| `tests/test_orange_a_main.py` | 31 | **25** | 31 |
| `tests/test_orange_a_security.py` | 6 | **6** | 6 |
| **Summe** | **64** | **53 rot** | **64 grün** |

### 1.3 Commits (alle auf `fix/orange-a`)

| Commit | Inhalt |
|---|---|
| `a9fbae3f` | M-10, M-11, Z-06, Z-07 (`core_skills_engine.py`) |
| `94fcfea6` | N-09, P-01, P-02 (`views_core.py`) |
| `0f1862b8` | S-04, D-16, D-17, F-18 (3 JS-Dateien) |
| `6adbf149` | D-19 (`utils/notebook_engine.py`) |
| `59c1a911` | Z-04, Z-05, Z-11, D-07…D-13, D-21, F-05, F-06, F-10, F-12, F-13 (`main.py`) |
| `c875c1a1` | F2, F25 (Security-Review, `main.py`) |

Geänderte Dateien gesamt (13, davon 7 Produktiv- und 6 Testdateien):

```
core_skills_engine.py   main.py   static/erp_studio.js
static/js/skill_markt.js   static/js/wissensbibliothek.js
utils/notebook_engine.py   views_core.py
tests/test_orange_a_core_skills.py   tests/test_orange_a_frontend.py
tests/test_orange_a_main.py   tests/test_orange_a_notebook.py
tests/test_orange_a_security.py   tests/test_orange_a_views_core.py
```

**Nicht angefasst** (Mandatsgrenze): `backend/`, `archon/`, `docker-compose*.yml`,
`deploy/`, `.env*`. Kein Docker-Kommando, kein Container-Recreate, kein
Branch-Wechsel, kein Push.

---

## 2. Befund-für-Befund-Status

### 2.1 `main.py`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **Z-04** 🟠 Gateway-Idle-Stop kann nichts stoppen | ✅ erledigt | `_parse_gateway_list` parst jetzt JSON- und Tabellen-Ausgabe von `hermes gateway list` (vorher: immer `[]`) | `test_parse_gateway_list_liest_json` / `_json_objekt` / `_tabelle` / `_ueberlebt_leere_ausgabe` |
| **Z-05** 🟠 SSE-Puffer trennt Clients dauerhaft | ✅ erledigt | `asyncio.Queue(maxsize=100)` → unbeschränkte Queue in `sse_events_stream`; ein voller Puffer kann den Subscriber nicht mehr entfernen | `test_sse_queue_ist_unbeschaenkt`, `test_broadcast_event_behaelt_subscriber_bei_vollem_puffer` (500 Events) |
| **Z-09** 🟠 Fester Fallback-Bearer für Hermes-Proxy | ✅ **war bereits geschlossen** | `_hermes_proxy_token()` liefert ohne Env-Variable `""` → Forward antwortet 502 `proxy_not_configured`. Commit `255004dc` (Basis-Commit), nicht von mir. **Test neu als Absicherung ergänzt.** | `test_kein_hartkodierter_proxy_token`, `test_proxy_token_kommt_aus_der_umgebung` |
| **Z-11** 🟠 Docker-Ausfall als „Dienste laufen" | ✅ erledigt | Bei DockerError/Parse-Fehler liefert `_services_config_fallback()` die Wunschliste **gekennzeichnet** (`source: config-fallback`, `online: false`, `fallback_reason`) — Ausfall ist von Normalzustand unterscheidbar | `test_docker_ausfall_ist_vom_normalzustand_unterscheidbar` |
| **D-07** 🟠 `UnboundLocalError` im Telegram-Relay | ✅ erledigt | `res = None` vor dem Dispatch, Fehlertext aus `dispatch_error` statt aus dem ungebundenen `res` | `test_telegram_relay_ueberlebt_dispatch_fehler` |
| **D-08** 🟠 `save-full-html`: Datenverlust + Erfolgsmeldung | ✅ erledigt | Atomarer Write (tmp + `os.replace`), HTML < 100 Zeichen → 400 statt stillem Verwerfen, Schreibfehler → 500 mit Fehlerliste, `written_to`/`failed` in der Antwort | `test_save_full_html_schreibt_atomar_und_meldet_fehler`, `..._meldet_schreibfehler`, `..._lehnt_zu_kurzes_html_ab` |
| **D-09** 🟠 Gateway-Start/Stop: Zustand vor Aktion, `rc` ignoriert | ✅ erledigt | Kommando läuft zuerst (in `asyncio.to_thread`), `rc != 0` → 502, Zustand (`active_gateways`, Profilstatus) wird **erst nach Erfolg** gesetzt | `test_gateway_start_setzt_zustand_nur_bei_erfolg`, `..._bei_erfolg`, `test_gateway_stop_meldet_fehler_und_aendert_den_zustand_nicht` |
| **D-10** 🟠 Oracle-Endpunkte: HTTP 200 mit `status: error` | ✅ erledigt | Alle drei Endpunkte werfen jetzt `HTTPException` (502 bzw. 400 bei fehlender Signal-ID) | `test_oracle_feed_meldet_fehler_als_httpfehler`, `test_oracle_triage_ohne_signal_id_ist_400` |
| **D-11** 🟠 Design-Themes: Fehler verschluckt, „success" | ✅ erledigt | Schreibfehler je Ziel werden gesammelt; sind **alle** Ziele unbeschreibbar → 500; Teilfehler kommen als `failed` in der Antwort zurück (gleiches für DELETE) | `test_design_themes_meldet_fehler_wenn_kein_ziel_schreibbar_ist`, `test_design_thomes_meldet_teilfehler` |
| **D-12** 🟠 Default-Modellname `evey-session-guard:` | ✅ erledigt | `main.py` und `static/js/wissensbibliothek.js` nutzen jetzt `auto/best-coding` (ein Alias, den OmniRoute kennt — vgl. `api_provider._list_provider_models_uncached`) | `test_default_modellname_ist_gueltig`, `test_kein_kaputter_default_im_frontend` |
| **D-13** 🟠 Theme-Hintergrund-Upload ohne Typ-/Größenfilter | ✅ erledigt | Endungs-Whitelist (jpg/jpeg/png/webp/gif), 8-MB-Limit (`await file.read(limit+1)`), Rollenzaun | `test_theme_upload_lehnt_svg_ab`, `test_theme_upload_lehnt_grosse_datei_ab` |
| **D-21** 🟠 Guardian-Stats: unbegrenzter Cache, freier Schlüssel | ✅ erledigt | Timeframe auf `all/24h/7d/30d` begrenzt (sonst 400), Cache mit TTL 10 s und fester Größengrenze | `test_guardian_stats_lehnt_unbekannten_timeframe_ab`, `test_guardian_cache_bleibt_beschraenkt` |

### 2.2 `views_core.py`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **N-09** 🟠 Vault-Scan: Check-then-Act über Threads, abschneidbare Cache-Datei | ✅ erledigt | `threading.Lock` um das Scan-Flag (nur ein Scan pro Vault), Cache-Write atomar (tmp + `os.replace`) via `_write_cache_atomic` | `test_cache_write_ist_atomar`, `test_cache_write_ist_atomar_auch_bei_fehler`, `test_nur_ein_scan_pro_vault_wird_ausgefuehrt` (4 Threads → 1 Scan) |
| **P-01** 🟠 Kalter Vault-Scan friert den Event-Loop ein | ✅ erledigt | Der Scan läuft via `await asyncio.to_thread(...)`; Messung im Test: Event-Loop macht während des Scans ≥ 3 Ticks (inline: 0) | `test_kalter_vault_scan_blockiert_den_event_loop_nicht` |
| **P-02** 🟠 12-s-`subprocess.run` im async-Handler | ✅ erledigt | Der Lauf geht in `asyncio.to_thread(_run_python_sync)` | `test_run_code_blockiert_den_event_loop_nicht` |

### 2.3 `core_skills_engine.py`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **M-10** 🟠 MCP liefert erfundene Telemetrie als `success` | ✅ erledigt | `execute_mcp_tool` gibt **keinen** Erfolg mehr zurück: kein Server registriert → `mcp_server_not_connected`; registriert, aber kein JSON-RPC-Kanal → `mcp_execution_not_implemented`. Die erfundenen Werte (`84 %`, `300ms/450ms/50ms`) sind entfernt. | `test_mcp_execute_ohne_verbundenen_server_meldet_keinen_erfolg`, `test_mcp_execute_liefert_keine_erfundene_telemetrie`, `test_mcp_antwort_nennt_die_ausgebliebene_ausfuehrung` |
| **M-11** 🟠 `restart_service` verweigert Neustart ohne Docker-SDK | ✅ erledigt | Die Vorprüfung auf `self.client` entfällt — der Pfad läuft ohnehin über `utils.docker_client` (HTTP) | `test_restart_service_arbeitet_ohne_docker_sdk`, `test_restart_service_meldet_dockerfehler` |
| **Z-06** 🟠 `git_safe_commit` tot + `git add .` staged den ganzen Baum | ✅ erledigt | pytest-Timeout 30 s → 600 s (konfigurierbar via `SKILL_PYTEST_TIMEOUT`); Staging nur noch explizit benannte Pfade (`git add -- <pfad>` + `git commit -- <pfad>`) bzw. ohne Pfadliste nur versionierte Dateien (`git add -u`) — keine untracked Secrets/Backups mehr | `test_pytest_timeout_uebersteigt_die_gemessene_suite_laufzeit`, `test_git_safe_commit_staged_keine_untracked_dateien`, `test_git_safe_commit_mit_pfadliste_staged_nur_diese_pfade`, `test_git_safe_commit_bricht_bei_fehlgeschlagenen_tests_ab` |
| **Z-07** 🟠 MCP-Ergebnisse als „success" | ✅ erledigt | identisch mit M-10 (dieselbe Code-Stelle) | siehe M-10 |

### 2.4 `static/js/skill_markt.js`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **S-04** 🟠 XSS im Live-Log-Stream | ✅ erledigt | Die Agenten-Ausgabe wird nicht mehr per Template-Interpolation in `innerHTML` gesetzt, sondern über `textContent` in eigenes DOM-Element geschrieben | `test_log_stream_escaped_die_agentenausgabe_nicht` |

### 2.5 `static/erp_studio.js`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **D-16** 🟠 ERP-Studio erfindet bei API-Fehler eine gebuchte Rechnung | ✅ erledigt | Bei Netzfehler **und** bei `!resp.ok` wird abgebrochen und der Fehler gemeldet; **keine** lokale Ersatzrechnung mehr. Gleiche Klasse zusätzlich in `convertErpDocToInvoice` behoben (dort entstand ebenfalls eine lokale, gebuchte Rechnung) | `test_erp_studio_erfindet_keine_rechnung_bei_api_fehler`, `test_erp_studio_meldet_den_fehler` |

### 2.6 `static/js/wissensbibliothek.js`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **D-17** 🟠 „erfolgreich gespeichert" ohne HTTP-Prüfung | ✅ erledigt | `/api/settings` **und** `/api/v1/services` prüfen `res.ok`; bei Fehler: Fehlermeldung statt Erfolgs-Toast, Modal wird nicht geschlossen. Gleiches im JEV-Toggle (`saveResp.ok`) | `test_wissensbibliothek_prueft_die_http_antwort`, `test_wissensbibliothek_meldet_erfolg_nur_bei_ok` |

### 2.7 `utils/notebook_engine.py`

| ID | Status | Umsetzung | Beleg |
|---|---|---|---|
| **D-19** 🟠 Notebook-Verlauf: Snapshot über den LLM-`await` | ✅ erledigt | `_append_chat_history()` hängt an den **frisch geladenen** Stand an (Read-Modify-Write) statt den alten Snapshot zu speichern; `save_notebooks_data()` schreibt atomar (tmp + `os.replace`) | `test_chatverlauf_ueberschreibt_keine_parallelen_aenderungen` (parallel hinzugefügte Quelle + Chat-Turn bleiben erhalten), `test_chatverlauf_haengt_an_den_aktuellen_stand_an`, `test_speichern_ist_atomar`, `test_speichern_legt_keine_tmp_datei_bei_erfolg` |

---

## 3. Zusätzliche Befunde aus §3.10 (F-01…F-20) — geprüft

Das Mandat verlangt, **jeden** F-Befund zu prüfen und diejenigen aufzunehmen, die
meine Dateien betreffen. Ergebnis der Dateizuordnung (Skript über die
Befund-Headlines):

| F-ID | Datei laut Review | Status |
|---|---|---|
| F-01 | `backend/operations_api.py` | ⛔ nicht meine Datei — nicht angefasst |
| F-02 | `backend/internet_watchdog.py` | ⛔ nicht meine Datei |
| F-03 | `backend/corporate_manager.py` | ⛔ nicht meine Datei |
| F-04 | `archon/core/mission_control.py` | ⛔ nicht meine Datei |
| **F-05** | `main.py` | ✅ **erledigt** — Provider-Fehler wird nicht mehr als Antwort persistiert und nicht mehr als Nutzung gebucht (`provider_failed`-Flag; `_save_message_to_db` und `_record_session_model_usage` entfallen im Fehlerfall). Test: `test_providerfehler_wird_nicht_als_antwort_gespeichert` |
| **F-06** | `main.py` | ✅ **erledigt** — der tote Zweig `json.dump(ap_list, f, ...) if False else None` im zweiten `open(...,"w")` ist entfernt; jetzt **ein** atomarer Write (tmp + `os.replace`). Test: `test_agent_profiles_write_ist_atomar` |
| **F-08** | `archon/core/runtime.py` + `main.py` | ✅ **main.py-Teil erledigt** (unbeschränkte SSE-Queue, s. Z-05). Der `runtime.py`-Teil (broadcast_event behandelt `QueueFull` als totem Subscriber) liegt in `archon/` — **nicht meine Datei**, nicht angefasst. Die Queue-Seite in `main.py` beseitigt den Auslöser. |
| F-09 | `archon/core/permissions.py` | ⛔ nicht meine Datei |
| **F-10** | `main.py` | ✅ **erledigt** — alle drei `_save_mission_control_data(...)`-Stellen (Fan-in, Delegations-Bridge, Approval-Gate) nutzen jetzt `update_mission_control_data(mutator)` (atomar unter Lock). Test: `test_mission_control_kein_lost_update` |
| F-11 | `archon/routers/hermes_profiles.py` | ⛔ nicht meine Datei |
| **F-12** | `main.py` | ✅ **erledigt** — `main.py` importiert jetzt `_MC_STATE_CACHE` aus `archon.core.mission_control` (die Instanz, die der Leser `archon/routers/mission_control.py` benutzt); die tote eigene Kopie ist entfernt. Test: `test_mc_state_cache_ist_die_gelesene_instanz` |
| **F-13** | `main.py` | ✅ **erledigt** — `_idle_stop_running` wird jetzt gelesen: ein zweiter Start des Idle-Stop-Loops beendet sich sofort (`try/finally` setzt das Flag zurück). Test: `test_idle_stop_guard_wird_gelesen` |
| F-14 | `backend/main.py` | ⛔ nicht meine Datei (zweite FastAPI-App) — die Kollisionen liegen in `backend/` |
| F-15 | `static/js/agent_profiles.js` | ⛔ nicht meine Datei |
| F-16 | `static/js/operations_kanban.js` | ⛔ nicht meine Datei |
| F-17 | `static/js/prompt_studio.js`, `static/js/operations_kanban.js` | ⛔ nicht meine Dateien |
| **F-18** | `static/js/skill_markt.js` | ✅ **erledigt** — statt `logDiv.innerHTML += logRow` (quadratisches Neuparsen) wird ein DOM-Knoten angehängt, mit Zeilen-Decke (200 Zeilen). Test: `test_log_stream_nutzt_kein_innerHTML_plus`, `test_log_stream_wachstum_sinkt` (500 Events → ≤ 200 Zeilen) |
| F-19 | `static/index.html` | ⛔ nicht meine Datei |
| F-20 | `archon/core/profiles.py` | ⛔ nicht meine Datei |

---

## 4. Security-Review (§3 🟠) — geprüft

| Security-ID | Datei | Status |
|---|---|---|
| **F2** 🟠 Kommando-Injektion über `affected_file` | `backend/task_self_healer.py` + `main.py:11384` | ⚠️ **Teilerledigung.** Der Shell-Injection-Teil war bereits geschlossen (Commit `03993de0`: argv-Liste statt Shell-String, `validate_affected_file`). Der **fehlende Rollenzaun an der Route** lag in `main.py` — **jetzt behoben** (`require_admin_or_503(request)`). Test: `test_healing_attempt_verlangt_admin`, `test_healing_attempt_hat_einen_zaun`. |
| F3 🟠 Beliebiges Datei-Lesen unter `/app` (Showroom) | `views_core.py` | ✅ **war bereits geschlossen** (Commit `af060e1f`: `require_admin_or_503` + Jail auf die Vault-Wurzel) — verifiziert, nicht erneut geändert |
| F4 🟠 Kopieren aus dem Container in ausgelieferten Ordner | `views_core.py` | ✅ **war bereits geschlossen** (Commit `af060e1f`) — verifiziert |
| F5 🟠 Sandbox-Härtung | `backend/ephemeral_sandbox.py` | ⛔ `backend/` — nicht meine Datei (Commit `e8f96edc` hat die Sandbox bereits gehärtet) |
| F6 🟠 Klartext-Schlüssel im getrackten Baum | `main.py:612` u. a. | ✅ **war bereits geschlossen** (Commit `255004dc`: kein Fallback-Token mehr im Hermes-Proxy) — verifiziert über `test_kein_hartkodierter_proxy_token`. Die übrigen Fundstellen (`tools/`, `archon/services/profiles_service.py`) sind nicht meine Dateien. |
| F21 🟠 `anything-llm` ohne Auth | Compose | ⛔ nicht meine Datei, Compose nicht anzufassen |
| F22 🟠 `socat`-Listener | Deployment | ⛔ nicht meine Datei |
| F23 🟠 SSRF im Verbindungstest | `archon/routers/llm_providers.py` | ⛔ nicht meine Datei |
| F24 🟠 `/api/vault/edit` ohne Rollenzaun | `main.py:8712` | ✅ **war bereits geschlossen** (Commit `af060e1f`: `require_admin_or_503` + Jail auf die Vault-Wurzel) — verifiziert |
| **F25** 🟠 Beliebiges Datei-Lesen über den Dokumenten-Parser | `main.py` | ⚠️ **Teilerledigung.** `/api/documents/parse` und `/api/documents/extract-tables` waren bereits gehärtet (Commit `af060e1f`, `_resolve_parser_input` mit Jail auf `library/raw_docs`). **`POST /api/diff/preview` war ungeschützt** (beliebiger `file_path`, kein Zaun) — **jetzt behoben**: `require_admin_or_503` + `safe_path_within` auf den Repo-Wurzelbaum. Test: `test_diff_preview_lehnt_pfade_ausserhalb_des_repos_ab`, `test_diff_preview_lehnt_systempfade_ab`, `test_diff_preview_erlaubt_repo_dateien`, `test_diff_preview_verlangt_einen_pfad`. |
| F26 🟠 Kommando-Injektion im Fleet-Healing | `backend/fleet_self_healing.py` | ⛔ `backend/` — nicht meine Datei (Commit `03993de0` hat den Pfad bereits entschärft); die Route `main.py:11628` trägt bereits `require_admin` |

---

## 5. Was bewusst **nicht** gemacht wurde (mit Grund)

| Punkt | Grund |
|---|---|
| `archon/core/runtime.py` (F-08): `broadcast_event` entfernt den Subscriber bei `QueueFull` | `archon/` ist laut Mandat der Bereich des zweiten Agenten. Die auslösende Ursache (begrenzte Queue in `main.py`) ist in meiner Datei behoben. |
| `backend/*` (F-01, F-02, F-03, F-05, F-07, F-09, F-11, F-14, F-17) | Mandatsgrenze — angezeigt, nicht geändert. |
| `static/js/agent_profiles.js` (F-15), `static/js/operations_kanban.js` (F-16), `static/index.html` (F-19) | nicht in meiner Dateiliste. |
| `archon/core/profiles.py` (F-20), `archon/core/mission_control.py` (F-04) | Mandatsgrenze. |
| `docker-compose*.yml`, `deploy/`, `.env*` | Mandatsgrenze; zusätzlich kein Docker-Kommando ausgeführt, kein Recreate. |
| M-16 / M-18 (Überschneidung mit `skill_markt.js`): gefilterte Agentenliste überschreibt `agents.json` | **M-16 ist nicht in meiner Mandatstabelle**, obwohl die Datei `skill_markt.js` betroffen ist. Die Datei-Überschneidung betrifft eine *andere* Funktion (`loadAgentsFromServer`), nicht den Log-Stream. Ich habe sie **nicht** angefasst, weil M-16 nicht zu meiner Aufgabenliste gehört (Mandat: „Deine Dateien (nur diese!)" mit expliziter ID-Liste). **Empfehlung für den Folge-Mandat.** |
| Z-10, Z-12, D-01, D-02, D-03, D-04 u. a. | nicht in meiner Mandatstabelle bzw. in `archon/`/`backend/`. |
| Baseline-Zahl 971/8 „nachzubessern" | Abweichung ist umgebungsbedingt (s. §1.1) — die Tests wurden **nicht** angepasst, um eine Zahl zu erreichen. |

---

## 6. Ehrliche Anmerkungen

1. **Die Baseline-Vorgabe 971/8 war im Worktree nicht reproduzierbar.** Gemessen:
   962/15 ohne die beiden Umgebungs-Anpassungen, 968/11 mit ihnen, 1032/11 am
   Endstand. Der Sprung 971 → 968 liegt an drei Tests in
   `test_critical_hardening.py`, die auf das im Container gemountete
   `/opt/data/obsidian` warten, plus den 4 Rollen-Payload-Tests. Ich habe die
   Zahl **nicht** durch Anpassen von Assertions erzwungen.
2. **`main.py` ist mit ~12.200 Zeilen weiterhin ein 259-Routen-Gottmodul** (W-02).
   Meine Änderungen sind punktuell; eine Aufteilung war nicht Teil des Mandats.
3. **Z-05/F-08 bleibt in `archon/core/runtime.py` strukturell offen**
   (`broadcast_event` behandelt jedes `put_nowait`-Fehler als „toter Client",
   und die Subscriber-Liste wird ohne Lock angefasst). Mein `main.py`-Fix
   beseitigt den konkreten Auslöser (begrenzter Puffer), nicht die Klasse.
4. **F-16 (ungebremste SSE-Voll-Reloads in `operations_kanban.js`)** und
   **F-15 (Request-Schleife bei leerer Profilliste)** bleiben offen — andere
   Dateien.
5. **Der `python -m pytest`-Aufruf braucht in dieser Umgebung
   `OBSIDIAN_VAULT_PATH`**, sonst scheitert schon der Import von `main.py`
   (`os.makedirs("/opt/data")` → `PermissionError`). Das ist eine
   Umgebungs-Eigenheit, kein Code-Fehler — aber sie macht jeden Testlauf ohne
   die Env-Variable unbrauchbar.
6. **`static/js/skill_markt.js` ist am Altstand syntaktisch kaputt**
   (`node --check` meldet „Unexpected end of input"; die Klammer-Balance war
   schon vor meinen Änderungen um 1 daneben). Ich habe die Balance **nicht**
   verändert (vorher/nachher gemessen: 1 → 1), damit der Diff ausschließlich
   den Log-Stream betrifft. Die Datei sollte in einem eigenen Mandat
   repariert werden.

---

*Erstellt: 08.11.2026 · Spur A · Branch `fix/orange-a` · 6 Commits · 64 neue
Tests · 53 davon am Altstand rot belegt · keine Regression in der Bestandssuite.*

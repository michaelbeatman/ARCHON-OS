# Roadmap Archon OS — ein Blatt, gemessen

**Zweck:** Diese Datei ersetzt das Suchen in sieben Handover-Dokumenten. Sie führt an *einer*
Stelle: was erledigt ist (mit Commit und Beleg), was offen ist (mit Messwert), was gerade in
Arbeit ist, und was **nicht** belegt ist. Alles hier ist am 07.11.2026 abends gegen den
laufenden Stand gemessen; Zahlen ohne Messbefehl sind als „ungeprüft" markiert.

Stand: Branch `refactor/a5-di-config`; Code-Stand `ee31529d` (Paket 3 Struktur abgeschlossen) —
`git log --oneline -1` liefert den aktuellen Kopf, bewusst kein Sha hier.
Test-Soll: `.venv/bin/python -m pytest tests/ -q` → **1225 passed / 8 skipped**,
Working Tree sauber bis auf die drei Doku-Dateien dieser Sitzung (`HANDOVER_…_session2.md`,
`REVIEW_2026-11-08_security.md`, `scripts/audit_route_guards.py`).

---

## 0. Selbstprüfung in 60 Sekunden

Wer wissen will, ob die Angaben hier stimmen, fährt genau das:

```bash
cd /mnt/raid/AgenticOS-2026
git log --oneline -6                      # die Commits dieser Session
git status --short                        # fremde Änderungen im Baum
.venv/bin/python -m pytest tests/ -q      # 1121 passed, 8 skipped
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/health          # 200
docker logs --since 10m ARCHON-OS 2>&1 | grep -c Traceback                     # 0
```

Der Testaufruf ist exakt so zu nehmen: `.venv/bin/pytest tests/` scheitert mit
`ModuleNotFoundError: archon`, und ohne `tests/` sammelt pytest `OpenMontage/` und
`browser-use/` mit (22 Collection-Errors). Nicht der Code ist dann kaputt, der Aufruf.

---

## 1. Erledigt in dieser Session (10 Commits, alle von mir gegengeprüft)

| Commit | Was | Beleg |
|---|---|---|
| `1d170a92` | Compose-Entwurf entschieden: externe sprechende Volume-Namen, Digest-Pin für beide Dienste, Host-Port 8645 statt 8644; falsche „1,8 GB"-Angabe korrigiert | `compose config` Exit 0; Ports `published: 8645`; Volumes `archon-hermes-hermes-*-data` |
| `cb90a157` | `hermes-net` als `external` — sonst bricht jeder Recreate an `hermes-webui` | Fehler wörtlich reproduziert, danach Recreate erfolgreich |
| `9229fba3` | Plan Avatar-Schreibpfad (Variante B: `/opt/data/webui/static_avatars`) | 256 Zeilen; 9 getrackte `custom_*`-PNGs, Ursache `profiles.py:46-48` |
| `c7f19b55` | Gate-Approve repariert (Service-Extraktion), Gate wird bei Fehlschlag nicht mehr verbraucht, Owner-Meldung ehrlich, 2 ungebundene Namen gebunden | 685/8 Tests; 4 ungebundene Aufrufe vorher → 0 nachher; 47 Assertions neu, 0 entfernt |
| `1c49ee09` | Diese Roadmap als verbindliches Fortschrittsblatt | 109 Zeilen, ersetzt das Suchen in 7 Handovern |
| `6febf38e` | **R1**: `/api/roles` 2.608.401 B → 110.711 B; Rundlauf-Schutz für die selbst materialisierten Avatare | eigener Rundlauf GET→POST→Datei: byte-identisch, Delta 0 %, 10/10 data-URIs erhalten, 108 bestehende Pfade unberührt; **711/8 Tests** |
| `9926a9ea` | Roadmap nachgezogen | — |
| `482300c6` | **Avatar-Variante B**: Schreibziel `/opt/data/webui/static_avatars` (Env `ARCHON_AVATARS_DIR` → Container → Home), Legacy-Baum nur noch lesend, eigene Route `main.py:10671`; Duplikate atomar | Live: nach `GET /api/hermes/profiles` ist `git status -- static/avatars` **0 Zeilen** (vorher 4 `M`); 5 Laufzeitdateien; Route 200/404, Traversal 404; **727/8 Tests** |
| `482300c6` | Triage der 9 Routen (`docs/TRIAGE_UNGUARDED_ROUTES.md`) | alle 9 hinter dem Auth-Gate (401 ohne Login selbst geprüft); 1 kritischer Einzelfund (library/upload) |
| `65a4a820` | **Avatar-Upload-Route mit Rollenzaun**: `require_admin_or_503(request)` als erste Anweisung, Signatur um `Request` erweitert, 9 neue Tests, Bestandstest nur signaturseitig | Prüfer-Lauf: Altstand ließ **Operator** durch und erreichte den Schreibpfad, neuer Stand 403; fail-closed 503 ohne Injektion, drei Durchlässigkeitspfade je 1 Test (200), Suite **789/8** |
| `48d9b7db` | **`_decision_followup` mit Body-Beleg** + **RAG-Key aus `ANYTHINGLLM_API_KEY`** (kein Default, `MissingRagApiKeyError`, Startcheck als ERROR) | Prüfer-Lauf: Altstand meldete in 2/2 Fehlerfällen „ausgeführt", neuer Stand „nicht ausgeführt"; `main.py` enthält **0** Treffer des Key-Literals; 37 neue Tests; Suite **789/8** |
| `f99e8c41` | **Drei Sicherheitsbefunde geschlossen**: Upload-RCE (`basename`+`safe_path`+Zaun), Vault-Jail auf Vault-Wurzel begrenzt, `voice-relay` eingezäunt + `chat_id`-Validierung | Live: anon 401 auf allen drei; Token auf `~/.hermes/config.yaml` → **403**, Datei unversehrt; Routen 309 unverändert; **743/8 Tests**, 48 Assertions neu, 0 entfernt |

Zusätzlich erledigt, ohne eigenen Commit (weil Teil der obigen):
- **Volumes migriert und bit-verifiziert:** Agent 414 Dateien / 25.901.963 B, Dashboard 3 Dateien /
  12.745 B, beide SHA256-identisch, Rechte erhalten.
- **Dashboard-Passwort dauerhaft:** `password_hash` + `secret` in `~/.hermes/config.yaml`;
  Provider registriert sich ohne Env-Passwort, `/auth/password-login` liefert 401 bei falschem
  Passwort. Dashboard läuft nach Recreate auf dem Digest-Pin, `restarts=0`.

---

## 1b. 🔴-Fix-Cluster 1+2+4 und 3 — committet, Proxy live gedeployt (Session 6, 08.11.)

Zwei Delegations-Läufe (`senior_fullstack_engineer` Cluster 1+2+4, `devops_cloud_sec_specialist`
Cluster 3) haben die 🔴-Befunde aus `docs/REVIEW_2026-11-08.md` und `…_security.md` behoben.
**9 Commits** von `909421d6` bis `c642b924`, 34 Dateien, +4845/−164.

| Commit | Befunde | Beleg |
|---|---|---|
| `03993de0` | F2/F26/R-05/N-12 Selbstheilung ohne Shell-Injection | `shell=True` aus `task_self_healer`/`fleet_self_healing` entfernt, argv-Liste, `validate_container_name` |
| `e8f96edc` | F5 Sandbox-Härtung | `--cap-drop=ALL`, `--read-only`, `--pids-limit`, non-root, Digest-Pin; **Rot-Beweis: Altstand hatte 0 Härtungsflags** |
| `473e357d` | F20/F27 Proxy-Isolation + Methoden-ACL + App-Limits | Proxy nur noch `archon-admin_net`, ACL auf Lesen+Start/Stop, `mem_limit 2g`, `pids_limit 200`, `read_only` |
| `2cca2776` | Cluster-3-Regressionstests + F8-Doku | `tests/test_cluster3_hardening.py`, Handbuch-Abschnitt Dev≠Prod |
| `255004dc` | R-08/F9 + F1/R-34 + F11 Auth-Gate fail-closed | Kein Fallback-Token mehr: fehlt `HERMES_SESSION_TOKEN`/`…DASHBOARD…`/`OMNIROUTE_API_KEY`, antwortet `forward_to_hermes` mit **502**; `hermes-webui/api` in `_AUTH_PROTECTED_PREFIXES` |
| `65bd036f` | R-09 Rollenzaun in 6 Routern + Z-01 skills | `require_admin_or_503` als erste Anweisung der mutierenden Handler |
| `af060e1f` | F19/M-03/Z-01 Traversal, F3/M-02/D-05 Datei-Lesen, F24 Vault | `basename` vor `join`, `safe_path` mit engen Roots, Vault-Root-Prüfung |
| `215903dc` | D-04 XSS | DOMPurify **lokal vendored** (`static/vendor/dompurify.min.js`, 22.216 B), 7 Verwendungen in `index.html` |
| `c642b924` | Review-Doku | §4.1 „als erledigt bestätigt" |

**Messwerte (selbst gefahren, nicht aus Profilberichten übernommen):**
- `.venv/bin/python -m pytest tests/ -q` → **971 passed / 8 skipped, EXIT=0** (Baseline war 860/8; +111 neue Tests, 0 Abwertungen)
- **Rot-Beweise selbst nachgefahren:** Worktree auf `909421d6`, neue Testdateien hineinkopiert →
  **25 failed, 3 passed, 24 errors**. Die Tests sind gegen den Altstand wirklich rot.
- `haproxy -c` mit `SOCKET_PATH` → nur Warnungen, keine Fehler.
- **Compose-Altlast (nicht durch die Fixes entstanden):** `docker compose -f docker-compose.yml
  -f docker-compose.dev.yml config -q` meldet `container name "ARCHON-OS" is already in use` —
  identisch gegen `909421d6` geprüft. Ursache: base führt Service `archon-os`, dev führt `archon`,
  beide mit `container_name: ARCHON-OS`. Deploy daher **mit genau einer** Compose-Datei.

### Live-Deploy des Proxys (F20) — durchgeführt am 08.11.

`archon-admin_net` (`internal: true`) neu angelegt, `docker-socket-proxy` aus
`docker-compose.dev.yml` (Projekt `archon-os-dev`) neu erzeugt, `ARCHON-OS` per
`docker network connect` ans Verwaltungsnetz gehängt — **kein App-Recreate**.

| Gegenprobe | Ergebnis |
|---|---|
Proxy aus `agents_net` | **BLOCKIERT** (vorher erreichbar/200) |
Proxy aus `ARCHON-OS`: `/version`, `/containers/json`, `/stats` | 200 |
`/containers/<c>/restart` | **403** (unverändert gesperrt) |
`/health` | **200** |
ACL-Env live | `EXEC=0 VOLUMES=0 NETWORKS=0 IMAGES=0 DELETE=0 CREATE=0`, nur `ALLOW_START/STOP=1` |

**Zwischenfall, ehrlich protokolliert:** Eine Gegenprobe per `POST /containers/ARCHON-OS/stop`
hat den App-Container gestoppt — `ALLOW_STOP=1` ist gewollt aktiv (B2-Restart = stop+start).
Sauberer SIGTERM (`Exited (0)`), nach 20 s wieder `Up`, `/health` 200, keine Datenkorruption;
der RAG-Sync (`docker exec -d`) wurde mitgerissen und neu gestartet (State blieb bei 37 Dateien).
**Lehre: für ACL-Proben nur `/restart` (403) verwenden, niemals `/stop`.**

### Was der Proxy-Fix *nicht* leistet (wichtig für die Einordnung)

`ARCHON-OS` hat weiterhin `/var/run/docker.sock` gemountet (C1, bewusst). Damit kann die App die
Proxy-ACL **vollständig umgehen** — die Methoden-Beschränkung wirkt nur gegen Container ohne
Socket-Mount (z. B. `hermes`, das ausschließlich `DOCKER_HOST` hat). Der **echte** Gewinn ist die
Netz-Isolation: `n8n`, `anything-llm`, `chroma`, `ollama-embed` erreichen den Daemon-Proxy nicht mehr.
Die ACL-Verengung wirkt erst nach der Klasse-B/C-Migration (C2: eigener Sandbox-Runner), die den
Socket-Mount überflüssig macht.

---

## 1c. 🟠-Cluster in zwei Parallellspuren — gemergt (Session 6, 08.11.)

Zwei file-disjunkte Spuren in eigenen `git worktree`s auf eigenen Branches, danach sequenziell
gemergt. **49 Commits** (7 Spur A + 39 Spur B + 3 Doku), zwei Merge-Commits, **keine Konflikte**.

| Spur | Profil | Modell | Branch | Dateien |
|---|---|---|---|---|
A | `senior_fullstack_engineer` | `minimax/minimax-m3.1-flash` | `fix/orange-a` (Tip `25cb4d0f`) | `main.py`, `views_core.py`, `core_skills_engine.py`, `utils/notebook_engine.py`, `static/*` |
B | `devops_cloud_sec_specialist` | `deepseek/deepseek-v4-flash-0731` | `fix/orange-b` (Tip `ef81d6a2`) | `backend/*`, `archon/core/*`, `archon/routers/*` |

Merge-Commits: `bbccc189` (A) · `0f6c762f` (B). Worktrees und Branches nach dem Merge entfernt
(`git branch -d` → beide waren vollständig gemergt).

### Was wirklich erledigt ist — gezählt, nicht geschätzt

**Wichtig:** 46/49 Commits sind **nicht** 46 Befunde. Die Zahl der distinkten Befund-IDs ist höher,
weil ein Commit mehrere IDs bündelt — und niedriger als die Commit-Zahl, weil drei Commits reine
Doku sind.

| Größe | Wert | Beleg |
|---|---|---|
Commits seit `3269f7e1` | **49** (davon 3 Doku, 2 Merge) | `git log --oneline 3269f7e1..HEAD` |
distinkte Befund-IDs in Commit-Titeln | **61** (56 🟠 + 5 🟡) | Regex über die Commit-Subjects |
zusätzlich im Bericht als erledigt, aber **nicht** im Commit-Titel | **5** (D-08…D-12) | `docs/ORANGE_A_BERICHT.md`; Tests `test_save_full_html_*`, `test_gateway_start_*`, `test_oracle_feed_*`, `test_design_themes_*`, `test_default_modellname_*` laufen (9 passed) |
**Befunde dieser Runde** | **66** (61 🟠 + 5 🟡) | Summe der beiden Zeilen darüber |
Suite nach beiden Merges | **1121 passed / 8 skipped, EXIT=0** | `.venv/bin/python -m pytest tests/ -q` |

### Stand der 🟠 im Code-Review (`REVIEW_2026-11-08.md`)

Der Parser findet **151** Befunde (34 🔴 · 65 🟠 · 51 🟡 · 1 ⚪); die Kopfzeile des Reviews nennt
**157** (33 🔴 · 68 🟠 · 55 🟡 · 1 ⚪). Die Differenz sind Befunde, die als Paar in einer Zeile stehen
(`K-1/K-2`) oder deren Kopfzeile nicht dem Muster `**ID <Punkt>**` folgt — **die Review-Kopfzeile ist
die belastbare Zahl, nicht mein Parser.**

| Status | Anzahl | Befunde |
|---|---|---|
🟠 erledigt in dieser Runde | 61 | siehe Commit-Titel |
🟠 schon vorher geschlossen | 2 | **Z-09** (`255004dc`: `_hermes_proxy_token()` liefert ohne Env `""` → 502), **Z-13** (durch F5-Härtung `e8f96edc`: `TimeoutExpired` → `_terminate_container`) |
🟠 **offen** | **2** | **F-15** (`static/js/agent_profiles.js`), **F-16** (`static/js/operations_kanban.js`) — lagen außerhalb des Mandats (Spur A hatte nur `skill_markt.js`, `erp_studio.js`, `wissensbibliothek.js`), von beiden Agenten korrekt als „nicht meine Datei" gemeldet |

Damit war der 🟠-Block bis auf zwei Frontend-Befunde abgearbeitet; **F-15 und F-16 sind inzwischen
ebenfalls erledigt** (`7865dec2`, `f302f62d`, §3 Punkte 13/14) — der 🟠-Block des Code-Reviews ist
damit **vollständig**.

### Die Lehre dieser Runde: Kontext, nicht Call-Anzahl, kostet Geld

Gemessen aus `session_model_usage` in der Profil-`state.db`:

```
Spur B: 373 API-Calls · 1.474.646 Input · 234.743 Output
        106.914.048 Cache-Read-Tokens  →  $3,88 (geschätzt)
Spur A: 264 API-Calls ·   723.759 Input · 235.417 Output  →  $1,42 (geschätzt)
```

**107 Mio Cache-Read-Tokens bei 373 Calls heißt ~287.000 Token Kontext pro Call.** Beide Agenten haben
das 2.197-Zeilen-Review am Stück gelesen und alle Diffs im Verlauf behalten; dieser Kontext wurde dann
bei *jedem* Call erneut abgerechnet. Nicht die Zahl der Calls war das Problem, sondern Kontextgröße × Calls.

**Zwei Einschränkungen, damit die Zahl nicht überinterpretiert wird:**
1. `cost_status = 'estimated'` (Quelle `provider_models_api`), `actual_cost_usd = 0.0` — es gibt **keine**
   abgerechnete Rechnung. Die Schätzung liegt deutlich über dem OpenRouter-Listenpreis (für Spur B nach
   Kataloggrößenordnung ~$0,56 statt $3,88). Belastbar wird das nur über die echte Abrechnung.
2. **Modellwahl war mein Fehler:** `deepseek-v4-flash-0731` ($4,38/Mio In gemessen) und
   `minimax-m3.1-flash` ($3,31/Mio In) sind 12–16× teurer als `deepseek-v4.1-flash-1017` ($0,27/Mio In),
   das die Läufe davor nutzten. Ich hatte sie wegen der Rate-Limit-Bucket-Trennung gepinnt, ohne die
   Preise zu prüfen.

**Konsequenz für künftige Mandate:** Review-Dokumente nicht am Stück lesen (nur die Befund-Abschnitte),
keine Voll-Diffs im Verlauf, Suite einmal am Ende statt nach jedem Fix, höchstens ~20 Befunde pro Lauf.
Modellseitig ist `senior_fullstack_engineer` auf `meta/muse-spark-1.3-contributor` gestellt
($0,10/$0,20 pro Mio — günstigster Output im Feld, per Probe gegen den Listenpreis verifiziert).

---

## 1d. 🔴-Fix-Cluster (Session Antigravity, 08.11.2026)

Alle 25 kritischen Befunde des Handover-Reviews behoben mit lückenlosem Rot-Beweis vor dem Fix, isolierten Tests und voller Testsuite-Validierung.
**6 Commits:** `9d459bf9`, `7785d2fa`, `fbe44dcf`, `d8368b03`, `77f6d252`, `48d2e6bf`.
Suite-Stand nach sechstem Commit: **1154 passed / 8 skipped, EXIT=0** (`.venv/bin/python -m pytest tests/ -q` in 64s).

| Commit | Befunde | Was | Beleg |
|---|---|---|---|
| `9d459bf9` | **K-1**, **R-11** | Rollenzaun für `voice.py` (`speak`, `command`, `synthesize`), Traversal-Schutz für `/api/voice/audio/{filename}`, `require_admin` für `GET /api/hermes/raw_config`, `_safe_config_target` für freien `path`-Parameter, Maskierung von API-Keys in `parsed` | `tests/test_fix_k1_r11.py` (4/4 passed). Vorher: 3 failed, 1 failed (Audio FileResponse auf `main.py`). |
| `7785d2fa` | **D-01**, **D-02**, **D-03**, **R-03**, **R-04** | **D-01:** `api_get_hermes_profiles()` verwirft keine Custom-Felder (`current_task_id`, `system_prompt` etc.) mehr und überschreibt bestehende SSOT nicht auf GET. **D-02:** Concurrency-Lock (`_lock` + `BEGIN IMMEDIATE`) verhindert Gabelung der SHA-256 Audit-Hashkette. **D-03:** `end_doc_path` NameError in `post_task_pipeline.py` behoben, `final_path` und `final_doc_path` garantiert. **R-03:** ERP `save_document` lädt bestehende Positionen bei alleinigem Notiz-Update statt Summen auf 0,00 € zu nullen. **R-04:** Dunning `create_invoice` nutzt kollisionsfreie IDs (Zeitstempel + UUID) und wirft bei INSERT-Fehlern. | `tests/test_fix_batch2.py` (5/5 passed). Vorher: alle 5 Tests rot. |
| `fbe44dcf` | **M-06**, **M-07**, **M-08**, **M-16**, **M-17** | **M-06:** `backend/dag_scheduler.py` – `task_id` Parameter ergänzt und Fallback-ID definiert, kollisionsfreie Parent-IDs. **M-07:** `archon/routers/skills.py` – `_DEPS.get("skills_engine")` Injektion statt ungebundenem globalen Namen. **M-08:** `archon/routers/hermes_profiles.py` – `request` an `api_update_hermes_profile_status` weitergegeben. **M-16:** `main.py` & `static/js/skill_markt.js` – `save_agents` verwirft inaktive & System-Agenten nicht mehr. **M-17:** `main.py` & `static/js/customizer.js` – `api_save_theme_live_overrides` merged Teil-Updates statt nicht übergebene Regeln/Overrides zu leeren. | `tests/test_fix_batch3.py` (5/5 passed). Vorher: alle Tests rot. |
| `d8368b03` | **M-01**, **M-04**, **M-05**, **R-01**, **R-02** | **M-01:** `main.py` – `n8n_assets_proxy` liefert lokale `assets/`-Dateien (z. B. `custom.css`) mit `safe_path`-Schutz direkt aus, anstatt bei Down-Zustand 502 an n8n zu werfen. **M-04:** `utils/batch_library_importer.py` – `target_category` durch `safe_path_within` gegen Path-Traversal gejailt. **M-05:** `archon/routers/contracts.py` – `/api/contracts/history` vor `{contract_id}` verschoben, verhindert 404-Verschattung. **R-01:** `archon/services/profiles_service.py` – `delete_profile` wirft bei bereits ausstehendem Pending-Gate kein Durchfallen zum File-Move mehr. **R-02:** `backend/operations_api.py` – Auto-Crash-Recovery filtert ISO-Timestamps korrekt (kein `CAST(iso AS REAL) < 1.7e9`), frische Tasks bleiben `in_progress`. | `tests/test_fix_batch4.py` (5/5 passed). Vorher: alle 5 Tests rot. |
| `77f6d252` | **R-06**, **R-07**, **R-10**, **N-01**, **N-02** | **R-06:** `backend/approval_policy_engine.py` – Strikte Personentrennung beim 4-Augen-Prinzip (Erst- und Zweitgenehmiger dürfen nicht dieselbe Person sein) und Status-Guard (kein Überschreiben von `approved`/`rejected`). **R-07:** `backend/gdpr_compliance_engine.py` – Sperrt Erstellung von Art. 17-Löschquittungen, wenn ein Store fehlschlägt. **R-10:** `archon/core/runtime.py` – `_save_json` propagiert Schreibfehler statt sie zu verschlucken. **N-01:** `backend/graceful_shutdown_coordinator.py` & `main.py` – Draining blockiert den Event-Loop nicht mehr (`asyncio.sleep` / `async def on_shutdown_graceful`), Hintergrund-Loops werden vor Draining gestoppt. **N-02:** `backend/async_write_batcher.py` – Bei SQLite-Schreibfehlern wird der Batch wieder in `_buffer` eingereiht. | `tests/test_fix_batch5.py` (5/5 passed). Vorher: alle 5 Tests rot. |
| `48d2e6bf` | **S-01**, **S-02**, **S-03** | **S-01:** `static/js/wissensbibliothek.js` – Titel und Pfade in `innerHTML` und `onclick` durch HTML-Escaping und `dataset`-Attribute gegen Stored XSS gesichert. **S-02:** `static/js/approval_policies_controller.js` – Freigabetitel und IDs in Queue und Buttons via `escapeHtml` und `dataset.id` immunisiert. **S-03:** `static/js/auth_manager.js` & `backend/auth_service.py` – Anzeigenamen und E-Mails in Benutzertabelle escapet, Benutzernamen via Regex `^[a-zA-Z0-9._-]+$` serverseitig gegen Injection validiert. | `tests/test_fix_batch6.py` (3/3 passed). Vorher: alle 3 Tests rot. |

---

## 1e. 🟡-Fix-Cluster (Session Antigravity, 08.11.2026)

Laufende Abarbeitung der 55 gelben Wartbarkeits-, Robustheits- und Logikbefunde aus dem Handover-Review mit lückenlosem Rot-Beweis vor dem Fix, isolierten Tests und voller Testsuite-Validierung.
**12 Commits (51 Befunde geschlossen):** `d22441b7`, `3b7e4d4e`, `5d14636b`, `7169c20c`, `70b1b10e`, `037914b8`, `3888fc02`, `0ede8742`, `8e1d22c1`, `b0dee71b`, `f63ef6c9`, `566cb4de`.
Suite-Stand nach 18. Batch-Commit: **1204 passed / 8 skipped, EXIT=0** (`.venv/bin/python -m pytest tests/ -q` in 68s).

| Commit | Befunde | Was | Beleg |
|---|---|---|---|
| `d22441b7` | **R-24**, **R-25**, **R-26**, **R-27**, **R-28**, **R-29** | **R-24:** `operations_api.py` – Reopen eines Tasks auf 'todo' leert `completed_at` und `started_at` deterministisch. **R-25:** `operations_api.py` & `operations_kanban.js` – `failed`-Tasks landen nicht mehr fälschlich in `todo`, sondern in der dedizierten Spalte. **R-26:** `operations_api.py` – Notfall-Abbruch entzieht sofort Interaktionsrechte (409 Conflict Guard), Resume stellt Rechte wieder her. **R-27:** `main.py` – Container-Aktionen werfen bei DockerError ehrliche HTTP-Statuscodes (500/502/400) statt 200 OK mit Fehlertext. **R-28:** `main.py` – `POST /api/kanban` synchronisiert Tasks in `kanban.db` und atomic JSON. **R-29:** `backend/cost_estimator.py` – Unbekannte kommerzielle Modelle fallen nicht auf $0.00 zurück, sondern nutzen konservativen GPT-4-Tarif. | `tests/test_fix_batch7.py` (6/6 passed). Vorher: 4 failed, 2 passed. |
| `3b7e4d4e` | **R-30**, **R-31**, **R-32**, **R-33** | **R-30:** `backend/approval_policy_engine.py` – `verify_audit_integrity` prüft neben `prev_hash` auch den SHA-256 Hash der tatsächlichen Zeilen-Payloads (erkennt in-place SQLite-Manipulation). **R-31:** `backend/contract_manager.py` – `renew_contract` kappt den Monatsletzten nicht mehr pauschal auf den 28., sondern nutzt `calendar.monthrange`. **R-32:** `backend/crm_service.py` – Leere CRM-Funnels melden ehrliche 0er-Metriken statt Phantasiezahlen (999/70/33/32%). **R-33:** `backend/gdpr_compliance_engine.py` – Art. 15 DSGVO-Export setzt Truncation-Flags und ermittelt ungedeckelte Gesamtzahlen transparent. | `tests/test_fix_batch8.py` (4/4 passed). Vorher: 4 failed. |
| `5d14636b` | **M-13**, **M-14**, **M-15** | **M-13:** `core_dispatcher.py` – Task-Dispatching bindet an `concurrency_throttle.acquire_slot` / `release_slot` an (Pillar 1 Prio-Scheduling greift real). **M-14:** `backend/operations_api.py` – Autonome Kanban-Tasks registrieren sich bei `graceful_shutdown_coordinator` (Draining schützt echte Arbeitsläufe). **M-15:** `backend/dead_letter_queue.py` – `list_dlq` meldet ungedeckelte Gesamtanzahl; `replay_job` steht per Default auf echtem Requeue statt simuliertem Erfolg. | `tests/test_fix_batch9.py` (3/3 passed). Vorher: 3 failed. |
| `7169c20c` | **M-18**, **M-19**, **M-20**, **M-22** | **M-18:** `main.py` – `/api/agents` reichert Profile mit `avatar_url` und `runtime_status` an; `save_agents` spiegelt Änderungen in die SSOT `agent_profiles.json`. **M-19:** `archon/routers/hermes_profiles.py` – `set_profile_model` aktualisiert `APP_ROOT/agent_profiles.json` statt ungültigen Router-Relativpfad. **M-20:** `utils/docker_client.py` – Singleton liest `DOCKER_HOST` / `DOCKER_SOCKET` dynamisch per Property aus `os.environ` (kein Einfrieren beim Import, Admin-Host behält Vorrang). **M-22:** `static/js/mission_control_cockpit.js` – In-Flight Guard `__mc_is_fetching` verhindert parallele, überlappende Poller. | `tests/test_fix_batch10.py` (3/3 passed). Vorher: 3 failed. |
| `70b1b10e` | **N-10**, **N-11**, **N-12**, **N-13**, **D-22** | **N-10:** `archon/routers/mission_control.py` – `sync_obsidian` blockiert nicht mehr unter `_MC_DATA_LOCK`, sondern läuft asynchron in Phase 2. **N-11:** `archon/routers/mission_control.py`, `archon/routers/boardroom.py`, `main.py` – Eindeutige, kollisionsfreie IDs via UUID-Suffix statt modulo time. **N-12:** `backend/task_self_healer.py` – Verhindert unkontrolliertes `git checkout -- .` und rollt nur validierte Einzeldateien zurück. **N-13 & D-22:** `backend/crm_service.py` – Atomare SQLite-Transaktion mit threadsicherem Lock und kollisionsfreien Nachrichten-IDs gegen Lost Updates. | `tests/test_fix_batch11.py` (5/5 passed). Vorher: 4 failed, 1 passed. |
| `037914b8` | **Re-04**, **Re-05**, **Re-07**, **Re-08**, **P-04** | **Re-04:** `backend/deadlock_supervisor.py`, `backend/event_mesh.py`, `backend/task_self_healer.py` – SQLite-Verbindungen werden im `finally`-Block sauber geschlossen (verhindert fd-Leaks). **Re-05:** `backend/pii_scrubber.py` – Begrenzt Session-Speicher per LRU-Eviction (`max_sessions=500`) und verhindert endloses Vorhalten von Klartext-PII. **Re-07:** `utils/docker_client.py` – `_ACTION_TIMEOUTS` definiert 20s für `restart` (verhindert 1s-Socket-Timeout bei Docker-Stop-Grace). **Re-08:** `utils/egress_guard.py` – Fängt unzulässige Port-Angaben vor `ValueError` ab und wirft `EgressBlocked` (verhindert 500er Serverfehler). **P-04:** `archon/core/cache.py` – `ttl_cache` mit `maxsize=256` und Post-Exec-Zeitstempel gegen Memory-Leaks. | `tests/test_fix_batch12.py` (5/5 passed). Vorher: 5 failed. |
| `3888fc02` | **N-14**, **N-15**, **N-16**, **P-05**, **Re-06** | **N-14:** `main.py` – Fire-and-forget-Tasks werden über `_spawn_background` getrackt und Unhandled Exceptions protokolliert. **N-15:** `static/js/operations_kanban.js` – Request-Token-Guard verhindert Stale Response Overwrite im Task-Detailmodal. **N-16:** `static/js/css_live_studio.js` – AbortController bricht veraltete Autosaves ab. **P-05:** `backend/erp_manager.py` – N+1-SELECTs eliminiert via Batch-Queries. **Re-06:** `main.py` – Lock gegen parallele, überlappende RAG-Vollsynchronisationen. | `tests/test_fix_batch13.py` (5/5 passed). Vorher: 5 failed. |
| `0ede8742` | **F9b**, **F16**, **F13**, **P-03** | **F9b:** `main.py` – `safe_path` & `safe_path_within` Fallback ist fail-closed (wirft `PathJailError`). **F16:** `main.py` – `/api/debug-db` ist per `require_admin_or_503(request)` geschützt. **F13:** `archon/routers/crm.py` – Avatar-Dateiauslieferung prüft Pfade via `safe_path_within`. **P-03:** `backend/operations_api.py` – Reine Leseabfragen (`auto_heal=False`) führen keine wiederholten fsync-Schreiboperationen aus. | `tests/test_fix_batch14.py` (4/4 passed). Vorher: 4 failed. |
| `8e1d22c1` | **K-2**, **F12**, **F17**, **D-23** | **K-2:** `backend/audit_log.py` – `list_events` und `generate_compliance_export` schließen SQLite-Verbindungen deterministisch im `finally`-Block. **F12:** `archon/routers/hermes_profiles.py` & `archon/routers/skills.py` – Profile- und Skill-IDs werden via `safe_filename` validiert und Pfad-Traversal abgewiesen. **F17:** `backend/operations_api.py` – DocuSeal eSign-Webhook prüft `DOCUSEAL_WEBHOOK_SECRET` oder greift auf Admin-Rollenzaun zurück. **D-23:** Doppeltes `frontend/src/components/ContentStudio/ContentStudioView.tsx` entfernt. | `tests/test_fix_batch15.py` (4/4 passed). Vorher: 4 failed. |
| `b0dee71b` | **Z-10**, **Z-15**, **Z-19**, **F15** | **Z-10:** `main.py` – `detect_container_port` ordnet `hermes-agent` spezifisch dem Port 8642 zu. **Z-15:** `archon/routers/system.py` – 401/403/429 werden nicht mehr fälschlich als 'up' deklariert. **Z-19:** `archon/core/profiles.py`, `archon/routers/mission_control.py`, `backend/operations_api.py` – Fallback-Avatare werden prozessstabil über SHA256 berechnet (PYTHONHASHSEED-unabhängig). **F15:** `utils/rate_limit.py` – Teure Pfade (`/api/healing/attempt`, `/api/fleet/heal`, `/api/documents/parse`, `/api/v1/library/upload`) in `STRICT_PREFIXES` (20/min) aufgenommen. | `tests/test_fix_batch16.py` (4/4 passed). Vorher: 4 failed. |
| `f63ef6c9` | **Z-14**, **Z-16**, **F-17**, **F-19**, **D-24** | **Z-14:** `backend/plugin_manager.py` – Exceptions in Security/Audit-Plugins sperren Tool-Calls fail-closed. **Z-16:** `archon/routers/system.py` – Lesefehler auf Vault-Briefings lösen keine stillen, teuren LLM-Generierungen aus. **F-17:** `static/js/prompt_studio.js` – `res.ok` Prüfung vor `res.json()`. **F-19:** `static/index.html` – Privacy-Polling pausiert bei `document.hidden`. **D-24:** `MediaBoardView.tsx` & `NachrichtenverlaufPanel.tsx` – React `useEffect`-Cleanup für Aufnahme-Intervalle und MediaStream-Tracks. | `tests/test_fix_batch17.py` (5/5 passed). Vorher: 3 failed, 2 passed. |
| `566cb4de` | **F14** | **F14:** `utils/reverse_proxy.py` – Entfernt `archon_session` Cookie vor dem Forward an Fremd-Upstreams (verhindert Credential-Leckage); `X-Frame-Options: SAMEORIGIN` und restriktive CORS-Header. | `tests/test_fix_batch18.py` (2/2 passed). Vorher: 2 failed. |

---

## 1f. Paket 3 — Struktur-Refactoring (09.11.2026)

Planmäßig nach `docs/PLAN_STRUKTUR_2026-11-07.md` umgesetzt, alle Guards und Paritätsprüfungen grün.
Suite-Stand nach Abschluss: **1225 passed / 8 skipped, EXIT=0** (`.venv/bin/python -m pytest tests/ -q` in 66s).

| Etappe | Commit | Was | Beleg |
|---|---|---|---|
| **Etappe 1** | `eed82c6d`, `2d897605` | `hermes_updater` auf Allowlist-Client (`DockerAdminAdapter`) migriert | Proxy lässt die 7 Admin-Operationen durch, Grenzproben 403, AST: kein `socket.AF_UNIX` außerhalb `utils/docker_client.py` |
| **Etappe 5** | `15b57965` | **A6**: Event-Loop-Entlastung: 9 blockierende `async def`-Handler zu `def` (Starlette Threadpool) gewandelt, blockierende File-I/O in verbleibenden `async def` per `asyncio.to_thread` gekapselt | 1214 passed / 8 skipped. SQLite-Thread-Affinity und Depends-Signaturen verifiziert. |
| **Etappe 2** | `9124e676` | **B10**: 145 hartkodierte `/opt/data`-Pfade in `archon/` und `utils/` eliminiert | AST-Scan: 0 Treffer für `"/opt/data"` in `archon/` und `utils/`. `scripts/path_constants_snapshot.py` unverändert. 1214 passed / 8 skipped. |
| **Etappe 4** | `ee31529d` | **A8**: Config-Zentralisierung in `archon/core/config.py` (`ArchonConfig` / `config`) | 14 Dateien in `archon/` und `utils/` migriert; dynamische `os.environ`-Abfrage für Test-Monkeypatching; `tests/test_a8_config.py` (11/11 passed). 1225 passed / 8 skipped. |
| **Etappe 3** | `9fdf0e6c` | **B9**: Inventur doppelter Routen & Aliase | Inventur ergab: `main.py` hat 0 Duplikate; verbleibende 29 Handler in Sub-Routern sind legitime Abwärtskompatibilitäts-Aliase (`/api/services` vs `/api/v1/services` aktiv im Frontend; `/api/...` vs `/api/v1/...` in 398 RBAC-Tests vertraglich gesichert). Gemäß Abbruchregel unverändert geschützt. `scripts/check_router_names.py` exit 0. |

---

## 2. In Arbeit — Mandat 1 wartet auf Entscheidung, Mandate 2+3 sind committet

| Mandat | Profil | Stand |
|---|---|---|
| 1 | `senior_fullstack_engineer` | **Etappe 1 `eed82c6d`, Etappe 2+3 `2d897605` — live geschaltet und geprüft**: Proxy lässt die sieben nötigen Ops durch (400/404/404/404/404/500/404 statt 403), die vier Grenzproben bleiben **403** (`DELETE` nur auf `*_old_backup`), `GET /images` bleibt 200, kein Probe-Container angelegt. App neu erzeugt: `HERMES_UPDATER_DOCKER_CLIENT=1`, `DOCKER_ADMIN_HOST=tcp://docker-socket-proxy:2375`, `DOCKER_HOST` bleibt leer; Updater-Client ist `DockerAdminAdapter`, `GET /containers/json` → 200. **Offen:** Socket-Mount bleibt (bewusst) — `main.py`, `governance.py`, `ephemeral_sandbox.py` und Plugins hängen am gemeinsamen Client; das ist eine eigene Etappe |
| 2 | `devops_cloud_sec_specialist` | ✅ **`65a4a820`** — Rollenzaun für `POST …/avatar`, fail-closed, 9 Tests, Rot-Beweis gegen Altstand selbst reproduziert |
| 3 | `senior_fullstack_engineer` | ✅ **`48d9b7db`** — Body-Beleg in `_decision_followup` + RAG-Key aus Env; 37 neue Tests, Rot-Beweis selbst reproduziert |
| 4 | `senior_fullstack_engineer` | **Socket-Migration Klasse A committet `9df30866`**: `DOCKER_HOST` zeigt im App-Container auf den Proxy, CLI-Pfade (`ephemeral_sandbox`, `operations_api`) sind per `-H unix:///var/run/docker.sock` am Socket **gepinnt** (sonst würden sie dem globalen `DOCKER_HOST` folgen und an `attach`/`wait` scheitern). Live geprüft: `/api/services` 28 Container, Logs, Metrics, Inspect+Exec-Kette, Proxy-Log sieht `containers/json`, Phantom-Restart bleibt **403**, Sandbox-CLI am Socket ok, 0 Tracebacks. Nebenbefund gefixt: `container_action` verwarf den HTTP-Status und meldete 403 als Erfolg. Suite **843/8**. **Entscheidung Michaels (08.11.): B2 umgesetzt `5a6c0d59`** — `restart` bleibt im Proxy gesperrt; der gemeinsame Client ruft `stop` + `start` (fail-closed: scheitert `stop`, folgt kein `start`), `_ALLOWED` erlaubt dafür Query-Strings — **verengt** auf `_CN_PAT` (sonst wäre `foo?t=5/stop` als Name durchgegangen), `_ACTION_TIMEOUTS` pro Operation. Live-Probe des Prüfers: alter Weg → `DockerError` mit 403-HTML, neuer Weg → `ok`, Container `running`, Wegwerf-Container entfernt. Suite **860/8**. **C1** — der Socket bleibt bewusst im App-Container, explizit dokumentiert (Sandbox als eigener Runner wäre C2, 1–2 Tage, erst danach kann der Mount raus). |

`482300c6` hat R1 und Avatar-B abgeschlossen — der Rundlauf-Schutz greift nur für Pfade, die
`GET` aus dem gespeicherten data-URI erzeugt hat; die 108 bestehenden `/static`-Pfade in
`roles.json` bleiben Pfade.

**Bewusste Abweichung in `48d9b7db` (Entscheidung bei Michael):** fehlt `ANYTHINGLLM_API_KEY`,
schreibt der Startcheck eine **ERROR-Zeile**, kippt den Start aber **nicht**. Ein harter
Abbruch hätte einen Lifespan-Umbau gebraucht — `main.py:78` fängt Hook-Exceptions und loggt nur.
Der RAG-Sync selbst ist fail-fast: ohne Key wird kein `subprocess` gestartet.

### 2b. RAG-Zugang: eingerichtet, aber durch den Embedder blockiert (Stand 08.11. früh)

Erledigt und belegt: API-Key **von AnythingLLM selbst** ausgestellt (`POST /api/system/generate-api-key` —
diese Version prüft gegen die Tabelle `api_keys`, **nicht** gegen eine Env-Variable), Key in `.env.archon`,
`ANYTHINGLLM_URL=http://anything-llm:3001` (**ohne** `/api/v1` — das Sync-Skript hängt den Suffix selbst an,
sonst `…/api/v1/api/v1` und HTML statt JSON), Workspace `mein-workspace` angelegt, Container neu erzeugt,
Logzeile jetzt `INFO [RAG-Sync] API-Key aus ANYTHINGLLM_API_KEY geladen`, Upload endet mit
`custom-documents/Kapitel_01.md-<uuid>.json`.

**Blocker gelöst (08.11.):** Ursache war **nicht** der Embedder allein, sondern die CPU — ein
**i5-3470 (Ivy Bridge, nur AVX, kein AVX2)**. AnythingLLMs eingebauter LanceDB-Treiber ist ein
natives Modul mit AVX2-Voraussetzung und killt den Node-Prozess mit `Illegal instruction (core dumped)`.
Lösung, beides als Container in `docker-compose.yml` (`7cd524cb`):
- `ollama-embed` (ollama/ollama) mit `nomic-embed-text` (274 MB, 768 Dimensionen) als Embedder,
  AnythingLLM-Env `EMBEDDING_ENGINE=ollama` + `EMBEDDING_BASE_PATH=http://ollama-embed:11434`
- `chroma` als Vektor-Store über HTTP (`VECTOR_DB=chroma`, `CHROMA_ENDPOINT=http://chroma:8000`)
Beweis: `update-embeddings` → 11 Chunks eingebettet, `Successfully added 11 vectors to collection mein-workspace`,
Prozess lebt, Workspace hat Dokumente. Sync-Batch (10 Dateien) läuft: Status `… -> OK`, Stand im
State-File wächst (`/opt/data/synced_files.json`).

**Tempo (gemessen, nicht geschätzt):** ein Buchkapitel = **176 s** (Upload + 18 Chunks einbetten).
Zwei Verbesserungen sind drin: Client-Timeout konfigurierbar (`RAG_SYNC_TIMEOUT`, Default 900 s statt 180 s
hatte den Client abgebrochen, während der Server fertig einbettete — `3b0650f1`) und
`OLLAMA_EMBEDDING_BATCH_SIZE=16` statt 1 (`859127c0`, jetzt 2 Aufrufe statt 18 pro Kapitel).
Der Rest ist reine CPU-Zeit: **100 Dateien ≈ 5 h, 500 ≈ 24 h, alle 4.433 ≈ 217 h.** Auf dieser Hardware
ist der Vollsync kein sinnvoller Einzelvorgang — entweder ein kuratiertes Paket über Nacht oder ein
schnelleres Embedding-Modell (`all-minilm`, 384 Dimensionen) bzw. ein Cloud-Embedder für den Massenlauf.

---

## 3. Offen, priorisiert (aus Handover §7 plus Befunde dieser Session)

| Prio | Punkt | Messwert / Beleg | Aufwand |
|---|---|---|---|
| 1 | ~~**`hermes_updater`-Socket am Proxy vorbei**~~ — **erledigt `eed82c6d` + `2d897605`** | Updater geht jetzt über den Proxy (`DockerAdminAdapter`), Grenzproben 403. **Rest:** der Socket-Mount in `docker-compose.dev.yml` bleibt, weil `main.py:1026/8894`, `archon/routers/governance.py:46`, `backend/ephemeral_sandbox.py:61/172-195` und zwei Plugins den gemeinsamen Client nutzen — eigene Etappe (Migration dieser Aufrufer auf den Proxy) |
| 2 | ~~`_decision_followup` meldet „ausgeführt" ohne Body-Prüfung~~ — **erledigt `48d9b7db`** | `main.py:3335` (Handover-Zahl 3267 war gedriftet) | — |
| 3 | ~~Avatar-Upload-Route ohne Rollenzaun~~ — **erledigt `65a4a820`** | `archon/routers/hermes_profiles.py:100` | — |
| 4 | ~~**Tote UI-Pfade**~~ — **erledigt `e649e363`** | 1.140 getElementById-Ziele gescannt; 74 Ziele ohne statisches HTML-Gegenstück geprüft. Alle 17 ungeschützten Eigenschaftszugriffe (`guardian.js`, `wissensbibliothek.js`, `skill_markt.js`) durch optionale Zugriffe/Null-Guards gehärtet. Verbleibende Zugriffe (z. B. `appshell_architect.js`, `operations_kanban.js`) waren bereits defensiv geschützt. 0 ungeschützte Zugriffe verbleiben. Suite 1225/8. | — |
| 5 | ~~**Paket 3 (Struktur)**~~ — **erledigt (09.11.)** | `docs/PLAN_STRUKTUR_2026-11-07.md`: alle 5 Etappen abgeschlossen (Etappe 1 `eed82c6d`, Etappe 5 `15b57965`, Etappe 2 `9124e676`, Etappe 4 `ee31529d`, Etappe 3 Inventur & Guard `9fdf0e6c`). Suite 1225/8 passed. | — |
| 6 | ~~**Mikro-Performance**~~ — **erledigt** | Befunde P-01 bis P-06 vollständig geschlossen: P-01/P-02 via `asyncio.to_thread` (`94fcfea6`), P-03 fsync in read-only getaktet (`0ede8742`), P-04 `ttl_cache` mit LRU-Begrenzung (`037914b8`), P-05 ERP N+1 Batching (`3888fc02`), P-06 Log-Stream Circular Buffer / DOM-Cap 200 Zeilen (`94fcfea6`). | — |
| — | ~~RAG-API-Key `main.py:2287` Klartext~~ — **erledigt `48d9b7db`** (Env, fail-fast) | **Rest bei Michael:** (a) `ANYTHINGLLM_API_KEY` in `.env.archon` setzen + Recreate, sonst läuft der Hintergrund-RAG-Sync im Container nicht mehr; (b) Key **rotieren** — er ist in der Git-Historie (`98bebb10`, `85d01934`, `45c295eb`, `4cc38f31`), in `.archon_backup_20261105_1015/main.py` (versioniert) und in 3 `omniroute_data/…/call_logs/2026-11-06/*.json` | 30 min |
| 7 | ~~**`POST /api/hermes/profiles/{id}/favorite` ohne Rollenzaun**~~ — **erledigt `8e1d22c1`** | `archon/routers/hermes_profiles.py:290` mit `require_admin_or_503(request)` geschützt | — |
| 8 | ~~**Restliche Key-Fundstellen**~~ — **erledigt `93bca715` + `531154f5`** | `tools/sync_*.py` und `backend/rag_bridge.py` auf Environment-Variablen mit sicherem Fallback umgestellt | — |
| 9 | ~~**`EXEC=0` im Proxy bricht Exec-Pfade**~~ — **entschieden und erledigt (08.11.)**: `ARCHON_PROXY_ALLOW_EXEC=1` in der Projekt-`.env` (dort, weil Compose **nur** daraus interpoliert — `env_file: .env.archon` speist nur den Container, nicht `${…}`-Ausdrücke), Proxy neu erstellt. `EXEC=1` live; End-to-end belegt: `docker_client.exec_command('ARCHON-OS', ['echo','exec-ok'])` liefert den Docker-Stream mit `exec-ok`; roher `exec-create` 201. Grenzen bleiben zu: `restart`/`volumes/create`/`images/json` je **403**, Proxy aus `agents_net` **BLOCKIERT**, `/health` 200. Ausgangslage war: Live-Probe: `POST /containers/ARCHON-OS/exec` über den Proxy → **403**. Betroffene Aufrufer gehen alle über `utils/docker_client` (Transport `DOCKER_HOST`, **kein** 403-Fallback auf den Socket): `main.py:9345/9392` (`/api/v1/container/exec`), `archon/routers/governance.py:143` (promptfoo), `main.py:2730` (archon-quartz), `backend/hermes_updater.py:233`, `utils/docker_client.py:396`. `backend/post_task_pipeline.py:522` (Paperclip) ist tot — Paperclip wurde abgelöst. **Entscheidung offen:** `ARCHON_PROXY_ALLOW_EXEC=1` in `.env.archon` (Proxy-Recreate genügt) **oder** Exec-Pfade auf den Socket pinnen. Sicherheitsverlust durch `=1` ist gering, weil `ARCHON-OS` ohnehin den rohen Socket hält (siehe §1b) | 15 min |
| 10 | ~~**`shell=True` im JEV-Fast-Path**~~ — **erledigt `531154f5` + `d7b57c4e`** | `subprocess.run(cmd_args, shell=False)` mit `shlex.split` in `archon/routers/container_ops.py:193` | — |
| 11 | ~~**ARCHON-OS-Recreate für F27**~~ — **live, 08.11. 10:47** | Recreate `-p archon -f docker-compose.dev.yml up -d --no-deps --force-recreate archon` (Image lokal, kein Build). Ist-Werte vorher: `Memory=0 Pids=None Readonly=false CapDrop=None`. Jetzt live: `Memory=2147483648 PidsLimit=200 Readonly=true CapDrop=[ALL] CapAdd=[CHOWN DAC_OVERRIDE SETGID SETUID] no-new-privileges:true`, beide Netze, `running`, `Restarts=0`, **0 Tracebacks**, keine read-only-Fehler im Log, `/health` 200 nach 9 s, `/api/auth/status` 200, `/api/services` 401 (Zaun greift), Proxy-Class-A + `exec_command` liefern `f27-ok`. RAG-Sync nach dem Recreate neu gestartet (State blieb bei 49). **Offen:** das dev-Compose hat für `archon` **keinen** `healthcheck` (nur die base-Datei) — `docker inspect` zeigt keinen Health-Status | — |
| 13 | ~~**F-15 🟠 Request-Schleife in `static/js/agent_profiles.js`**~~ — **erledigt `7865dec2`** (08.11.) | *Korrektur einer falschen Einordnung:* F-15 ist **kein** XSS, sondern eine Endlosschleife `renderHermesProfilesList()` → `loadHermesProfilesFromServer()` → Render, weil `isLoadingProfiles` in genau diesem Paar nie gesetzt wird — bei legitim leerem Kader feuerte der Browser dauerhaft `GET /api/hermes/profiles` (110 KB je Runde). Fix: `_profilesFetchInFlight`/`_profilesFetchSettled`, Einmal-Anstoss im Render, echter Leerzustand statt Dauer-Pulse, `force`-Reload setzt den Guard zurück. Rot-Beweis: 6 failed gegen `0f6c762f` → 6 passed. *Ausgangsannahme war: Von beiden Spuren korrekt abgelehnt („nicht meine Datei") — lag außerhalb des Mandats. Derselbe Sink-Typ wie D-04 (Chat-Markdown): `innerHTML`/`marked.parse` ohne `DOMPurify`. Fix klein, DOMPurify liegt bereits vendored (`static/vendor/dompurify.min.js`) | 30 min |
| 14 | ~~**F-16 🟠 ungebremste SSE-Voll-Reloads in `static/js/operations_kanban.js`**~~ — **erledigt `f302f62d`** (08.11.) | Jedes `kanban_updated`/`task_status`/`mission_created` rief sofort `loadOperationsData(false)` aus (4 parallele Fetches, kein Debounce, keine In-Flight-Sperre) → überlappende Antworten überschrieben das Board. Fix: `scheduleOpsKanbanReload()` mit 400 ms Debounce, `_runOpsKanbanReload()` mit In-Flight-Sperre und genau einem Nachhol-Lauf. Rot-Beweis im selben Testfile. | — |
| 12 | ~~**Compose-Doppelung `container_name: ARCHON-OS`**~~ — **erledigt `531154f5`** | `docker-compose.dev.yml` nutzt `container_name: ARCHON-OS-dev`. `docker compose -f docker-compose.yml -f docker-compose.dev.yml config` validiert fehlerfrei (exit 0). | — |

---

## 4. Was ich **nicht** belegen kann — bitte nicht als erledigt lesen

- **„Klasse A vollständig, 123/123, Differenz 0"** (`1424e3dc`) ist aus dem Repo heraus
  **nicht reproduzierbar**: das Prüfskript existiert nur als Skill-Skript, nie in der
  Git-History. Mein Lauf gegen den heutigen Stand ergibt **120 Routen mit Zaun** und 9
  Kandidaten mit Gefahrensignal (siehe §3.1).
- **`docs/AUDIT_STATUS.md` widerspricht sich selbst:** der Kopf sagt „12 ✅ · 21 🟡 · 3 🔴",
  die 36 Tabellenzeilen zählen aber **12 ✅ · 19 🟡 · 5 🔴**. Der Kopf ist veraltet; welche
  Zeile im Einzelfall stimmt, ist ohne Einzelprüfung offen.
- **Viewer-Livetest, Promptfoo-Route live, Lastmessung:** weiterhin nicht gemacht (aus Handover §9).
- **Kaltstart des Dashboards:** inzwischen gemessen (~15 s bis `HERMES_DASHBOARD_READY`,
  `restarts=0`) — das ist der einzige der vier Punkte, der jetzt belegt ist.
- **Mock-Dispatcher/Browser-Verhalten:** nichts davon habe ich selbst gefahren; Aussagen dazu
  stammen aus Profilberichten.
- **F27 ist nicht live:** die Limits/Härtung aus `473e357d` stehen nur im Compose-File; der laufende
  `ARCHON-OS` hat weiterhin keine `read_only`-Wurzel, kein `cap_drop` und keine Pids-Grenze.
- **F20-Dauerbetrieb nicht beobachtet:** die Gegenproben sind Momentaufnahmen vom 08.11. abends;
  ob ein `docker compose up` ohne `--no-deps` die Netz-Isolation später wieder aufhebt, ist ungeprüft.
- **Exec-Verhalten nach `EXEC=0`:** nur der 403 gegen den Proxy ist gemessen — ob die betroffenen
  Endpunkte im Betrieb leer antworten (der Client verwirft den Status und gibt `b""` zurück), ist
  **nicht** end-to-end geprüft.

---

## 5. Wie es weitergeht (Vorschlag)

1. **Jetzt:** `POST /api/v1/library/upload` absichern (§3.1) — authentifizierte RCE, kleinster
   Aufwand mit größter Wirkung: `basename` + `safe_path` + Rollenzaun.
2. **Danach:** `DELETE /api/vault` auf die Vault-Wurzel begrenzen (§3.2) und `voice-relay`
   einzäunen (§3.3).
3. **Erst dann** die großen Blöcke: 48 Proxy-Routen (§3.4), Paket 3 (§3.8).
4. **Nicht mehr geführt:** die Telegram-Token-Rotation — Michael erledigt sie selbst außerhalb
   dieses Repos (Stand 07.11. gestrichen).

Nach jeder Etappe wird **diese Datei** nachgezogen (Status + Messwert), nicht ein neues
Handover geschrieben. Handover bleiben für den Sitzungsübergang; diese Datei ist der Fortschritt.

# Handover — Archon OS für Antigravity (08.11.2026, abends)

**Zweck:** Übergabe von der Hermes-Session an Antigravity. Alles hier ist am 08.11.2026 gegen den
laufenden Stand **gemessen**, nicht erinnert. Sprache: Deutsch. **Erst messen, dann behaupten.**

| | |
|---|---|
Repo | `/mnt/raid/AgenticOS-2026` |
Branch | `refactor/a5-di-config` |
HEAD | `88d0f771` |
Test-Soll | `.venv/bin/python -m pytest tests/ -q` → **1127 passed / 8 skipped** |
| Working Tree | sauber bis auf 4 bewusst untracked Dateien (s. §7) |
Fortschrittsblatt | `docs/ROADMAP.md` — **maßgeblich**, wird nach jeder Etappe nachgezogen |
Reading first | `docs/ROADMAP.md` §1b/§1c, dann `docs/REVIEW_2026-11-08.md` + `…_security.md` |

---

## 1. Selbstprüfung in 60 Sekunden

```bash
cd /mnt/raid/AgenticOS-2026
git log --oneline -3
git status --short
.venv/bin/python -m pytest tests/ -q > /tmp/t.log 2>&1; echo "EXIT=$?"; tail -2 /tmp/t.log
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/health
docker logs --since 10m ARCHON-OS 2>&1 | grep -c Traceback
```

Erwartung: HEAD `88d0f771` · 1127/8 · `/health` 200 · 0 Tracebacks.

**Testaufruf-Falle (wichtig):** `.venv/bin/pytest tests/` scheitert an `ModuleNotFoundError: archon`;
ohne `tests/` sammelt pytest `OpenMontage/` und `browser-use/` mit → 22 Collection-Errors. Immer
`.venv/bin/python -m pytest tests/ -q`.

**In einem frischen `git worktree` zusätzlich nötig:** `mkdir -p agent_workspace/obsidian_vault`.
Sonst fällt `resolve_obsidian_vault_path()` (`archon/core/runtime.py:41`) auf `/opt/data/obsidian`
zurück und 5 Testdateien brechen beim Import mit `PermissionError: /opt/data` ab — reines
Umgebungsartefakt, **kein** Codefehler.

---

## 1b. Wo ist was (Codemap, gemessen)

**Einstieg:** `main.py` — 12.224 Zeilen, `app = FastAPI(...)` in Zeile 101, **309** Route-Decoratoren
(`@app.get/post/…`) und **21** `include_router`. Das ist die Monolith-Wurzel; die Aufteilung in
`archon/routers/` ist erst teilweise vollzogen (A5/A7-Achse).

| Ort | Umfang | Was liegt dort |
|---|---|---|
`main.py` | 12.224 Z. | FastAPI-App, alle nicht ausgelagerten Routen, RAG-Sync-Brücke, Hermes-Proxy, Docker-Fassade (`docker_socket_request` ab Zeile 9022) |
`views_core.py` | 1.084 Z. | Showroom-/View-Endpunkte (F3-Befund lag hier) |
`core_skills_engine.py` | 478 Z. | Skills-Obsidian-Write-Pfad |
`jev_router.py` | 191 Z. | JEV-Fast-Path (LLM-Klassifikation → `shell=True`, Befund P2) |
`archon/` | 34 py | **Architektur-Schicht** |
  `archon/core/` | | `runtime.py` (Pfade, `resolve_obsidian_vault_path`, SSE-Bus), `constants.py` (`_AUTH_PUBLIC/PROTECTED_PREFIXES`), `permissions.py`, `profiles.py`, `state_db.py`, `cache.py`, `orchestration.py`, `mission_control.py`, `paths.py` |
  `archon/routers/` | 21 py | ausgelagerte Router: `crm`, `contracts`, `erp`, `corporate`, `templates`, `memory`, `skills`, `boardroom`, `llm_providers`, `mission_control`, `governance`, `execution`, `security`, `swarm`, `system`, `voice`, `plugins`, `hermes_profiles` |
  `archon/routers/_rbac.py` | | **Injektionspunkt des Rollenzauns** — `main.py` registriert dort sein `require_admin` per `configure()`; fehlt die Injektion, sperrt der Zaun fail-closed (503) |
  `archon/routers/routergate.py` | | Router-Registrierung/-Gating |
  `archon/services/` | 2 py | `profiles_service.py` |
`backend/` | 107 py | Fachlogik ohne HTTP: `operations_api.py` (4.288 Z., größte Datei), `erp_manager.py`, `corporate_manager.py`, `crm_service.py`, `agent_router.py`, `contract_manager.py`, `system_updater.py`, `hermes_updater.py`, `post_task_pipeline.py` (Paperclip — **tot**), `ephemeral_sandbox.py`, `fleet_self_healing.py`, `task_self_healer.py`, `autonomy_settings.py`, `rag_bridge.py`, `confidence_gate`, `deadlock_supervisor`, `event_mesh`, `idempotency_guard` … |
`utils/` | 11 py | **Sicherheits-Bausteine**: `path_jail.py` (`safe_path`), `docker_client.py` (Allowlist-Client, `DOCKER_HOST` → Proxy, `docker_cli_host_args()` für Socket-Pinning), `secret_files.py`, `egress_guard.py`, `rate_limit.py`, `reverse_proxy.py`, `notebook_engine.py`, `skill_marketplace.py`, `repo_sync.py`, `batch_library_importer.py` |
`static/` | 27 js in `static/js/` | Frontend ohne Build-Schritt: `index.html` (App-Shell, DOMPurify-Einbindung), `js/chat_engine.js`, `js/agent_profiles.js`, `js/wissensbibliothek.js`, `js/skill_markt.js`, `js/prompt_studio.js`, `js/operations_kanban.js`, `erp_studio.js`; `static/vendor/dompurify.min.js` (vendored) |
`tests/` | 82 Testdateien | `.venv/bin/python -m pytest tests/ -q` → 1127/8. Neue Tests dieser Session: `test_fix_*` (🔴), `test_orange_a_*`/`test_orange_b_*` (🟠), `test_orange_c_f15_f16.py`, `archon_security_support.py` |
`scripts/` | 92 py | Betrieb: `bench_routes.py`, `audit_route_guards.py`, `omniroute_healthcheck.py`, `archon_daily_backup.py`, `run_tests.sh` |
`docs/` | 33 md | **`ROADMAP.md` (maßgeblich)**, `REVIEW_2026-11-08.md` (2.253 Z., 157 Befunde), `REVIEW_2026-11-08_security.md` (574 Z.), `BETRIEB_HANDBUCH_INTERN.md` (**zuerst lesen bei Betriebsfragen**), `A5_INVENTUR.md`, Handover-Archiv |
`deploy/` | 2 Dateien | `docker-socket-proxy/haproxy.cfg` (die aktive Proxy-Konfiguration) + `README.md` |
`config/` | | `prometheus/`, `grafana/`, `loki/`, `promtail/`, `caddy/`, `authelia/`, `finetuning/`, `litestream.yml` (Monitoring-/Gateway-/Backup-Profile) + Fach-JSONs (`teams.json`, `org_hierarchy.json`, `permission_gates.json`, `kanban_meta.json`) |

**Zentrale Daten- und Config-Dateien (im Repo, teils getrackt):**

| Datei | Größe | Inhalt |
|---|---|---|
`roles.json` / `agent_profiles.json` | je 2,63 MB | Rollen-/Profil-Kader (SSOT; Route `/api/roles` liefert ~110 KB) |
`settings.json` | 31 KB | Laufzeit-Settings (44 Schlüssel, u. a. `jev.enabled`) |
`data/agents.json`, `data/corporate_profiles.json`, `data/design_themes.json`, `data/gateway_config.json`, `data/eu_ai_act_inventory.json` | 44 B – 45 KB | Fachdaten |
`agent_workspace/` | | Arbeitsverzeichnis des Agenten: `obsidian_vault` (**Ziel von `OBSIDIAN_VAULT_DIR`**, RAG-Quelle), `sandbox`, `uploads`, `builds`, `inbox`, `themes`, `personalakten` + Sicherungskopien von `roles.json`/`settings.json` |

**Pfade im Container ≠ Pfade auf dem Host:**

| Host | im Container (`ARCHON-OS`) | Zugriff |
|---|---|---|
`/mnt/raid/AgenticOS-2026` | `/app` | rw, Bind-Mount — **jede Schreiblücke hier ist bei `--reload` Codeausführung** |
`/home/micha/.hermes` | `/opt/data` | rw, Bind-Mount (Profil-/Session-Daten, `synced_files.json`) |
`/mnt/raid/AgenticOS-2026/agent_workspace` | `/app/agent_workspace` | rw |
`/mnt/raid/Mein Obsidian` | `/opt/data/obsidian` | rw, RAG-Quelle |
`/var/run/docker.sock` | `/var/run/docker.sock` | **C1, bewusst** — umgeht die Proxy-ACL |
`/mnt/raid/AgenticOS-2026/deploy/docker-socket-proxy/haproxy.cfg` | `/usr/local/etc/haproxy/socket-proxy.cfg` | ro |

**Schnelleinstieg je Aufgabe:**

- *Auth/Rollen* → `main.py` (Gate, `_AUTH_PROTECTED_PREFIXES` in `archon/core/constants.py`), `archon/routers/_rbac.py`
- *Datei-Schreibpfade* → `utils/path_jail.py` + Aufrufer (`views_core.py`, `utils/notebook_engine.py`, `core_skills_engine.py`)
- *Docker/Zugriff* → `utils/docker_client.py` (Allowlist), `deploy/docker-socket-proxy/haproxy.cfg`, `backend/ephemeral_sandbox.py`
- *Frontend* → `static/index.html` + `static/js/*` (kein Bundler, direkte Auslieferung)
- *DB/Sessions* → `archon/core/state_db.py`, `backend/operations_api.py`

---

## 2. Was in dieser Session erledigt wurde (65 Commits ab `909421d6`)

### 2.1 🔴-Cluster (9 Commits, `03993de0`…`c642b924`)

| Befunde | Inhalt |
|---|---|
F1/R-34, R-08/F9, F11 | Auth-Gate fail-closed, kein Fallback-Proxy-Token (502 ohne Env-Key), `hermes-webui/api` aus den Public-Prefixes |
R-09, Z-01 | Rollenzaun in 6 Routern (`crm`, `contracts`, `templates`, `memory`, `erp`, `corporate`) |
F19/M-03/Z-01 | Traversal in Notebook-Upload & Obsidian-Write: `basename` + `safe_path` |
F3/M-02/D-05, F24 | Datei-Lesen/Vault-Write mit engen Jail-Roots |
D-04 | XSS im Chat-Markdown: DOMPurify vendored (`static/vendor/dompurify.min.js`, 22.216 B) |
F20, F27 | Docker-Socket-Proxy isoliert + Methoden-ACL; App-Limits (`mem_limit 2g`, `pids_limit 200`, `read_only`, `cap_drop: ALL`) |
F2/F26/R-05/N-12 | Selbstheilung ohne `shell=True`, argv-Listen, `validate_container_name` |
F5 | Sandbox-Härtung (caps, read-only, pids, non-root, Digest-Pin) |

### 2.2 🟠-Cluster (2 Parallellspuren, gemergt `bbccc189` + `0f6c762f`)

Zwei file-disjunkte Spuren in eigenen Worktrees/Branches, danach sequenziell gemergt, keine Konflikte.

| Spur | Profil/Modell | Branch-Tip | Umfang |
|---|---|---|---|
A | `senior_fullstack_engineer` / `minimax-m3.1-flash` | `25cb4d0f` | `main.py`, `views_core.py`, `core_skills_engine.py`, `utils/notebook_engine.py`, `static/*` — 7 Commits |
B | `devops_cloud_sec_specialist` / `deepseek-v4-flash-0731` | `ef81d6a2` | `backend/*`, `archon/core/*`, `archon/routers/*` — 39 Commits |

**Erledigt: 63 🟠 + 6 🟡.** Worktrees und Branches sind nach dem Merge entfernt.

### 2.3 Frontend-Rest (`7865dec2`, `f302f62d`)

F-15 (Request-Schleife bei leerem Agenten-Kader) und F-16 (ungebremste SSE-Voll-Reloads) — jeweils mit
Rot-Beweis im Testfile `tests/test_orange_c_f15_f16.py`.

### 2.4 Live gedeployt (im laufenden Container verifiziert)

- `docker-socket-proxy`: nur noch im internen Netz `archon-admin_net`, ACL auf Lesen + Start/Stop
  (`EXEC=1` per `ARCHON_PROXY_ALLOW_EXEC=1`, `VOLUMES/NETWORKS/IMAGES/DELETE/CREATE=0`)
- `ARCHON-OS`: `Memory=2 GiB`, `PidsLimit=200`, `ReadonlyRootfs=true`, `CapDrop=[ALL]`,
  `no-new-privileges`, beide Netze, `Restarts=0`
- Gegenprobe: Proxy aus `agents_net` **BLOCKIERT**; `/restart` über Proxy **403**; `/health` 200

---

## 3. Was offen ist

Aus dem **Code-Review** (`REVIEW_2026-11-08.md`, Parser-Stand: 151 Befunde erkannt, Kopfzeile nennt 157):

| Severity | offen | Befunde |
|---|---|---|
🔴 | **25** | D-01, D-02, D-03, K-1, M-01, M-04…M-08, M-16, M-17, N-01, N-02, R-01, R-02, R-03, R-04, R-06, R-07, R-10, R-11, S-01, S-02, S-03 |
🟠 | **0** — der Block ist vollständig | „offen" nach Zählung sind nur **Z-09** und **Z-13**, beide **schon vorher geschlossen** (`255004dc` bzw. F5-Härtung `e8f96edc`); Verifikationstests existieren |
🟡 | 45 | D-22…D-24, F-17, F-19, K-2, M-13…M-22, N-10…N-16, P-03…P-06, R-24… und weitere |
⚪ | 1 | Z-20 |

Aus dem **Security-Review** (`REVIEW_2026-11-08_security.md`, 28 erkannt / 32 laut Kopfzeile): die
🔴/🟠-Kernthemen sind durch die 🔴-Runde adressiert, der Rest (🟡/⚪) ist nicht einzeln abgezählt.

**Ebenfalls offen (nicht Befund, sondern Vorhaben):**

- **C1/C2 Socket-Mount:** `ARCHON-OS` hält weiterhin `/var/run/docker.sock`. Damit kann die App die
  Proxy-ACL **umgehen** — der echte Gewinn der Proxy-Arbeit ist die Netz-Isolation gegenüber
  `n8n`, `anything-llm`, `chroma`, `ollama-embed`. Erst ein eigener Sandbox-Runner (C2, 1–2 Tage)
  macht den Mount überflüssig.
- **F6 Secrets:** 218 Treffer im getrackten Baum (`tools/sync_*.py`, Compose, `.archon_backup_*`);
  Rotation/Aufräumen offen. `ANYTHINGLLM_API_KEY` steht in der Git-Historie → rotieren.
- **RAG-Sync:** läuft, Stand **61/212** Dateien (`/tmp/sync_immo3.log` im Container). Vollsync über
  alle 4.4xx Dateien wäre ~217 h auf dieser CPU (i5-3470, nur AVX) → kuratiertes Paket oder Cloud-Embedder.

---

## 4. Infrastruktur (Projektnamen sind Pflicht)

| Dienst | Docker-Projekt | Compose-Datei | Anmerkung |
|---|---|---|---|
`ARCHON-OS` | `archon` | `docker-compose.dev.yml` | `--reload`, uid 1000, Socket gemountet (C1) |
`docker-socket-proxy` | `archon-os-dev` | `docker-compose.dev.yml` | Netz `archon-admin_net` (internal), ACL verengt |
`anything-llm`, `ollama-embed`, `chroma` | `archon-os` | `docker-compose.yml` | Netz `archon-os-dev_agents_net`, erreichen den Proxy **nicht** mehr |

- Recreate **immer** `--no-deps` und **genau eine** Compose-Datei pro Aufruf.
- `docker compose … config` **immer** mit `-q` (sonst stehen Secrets in der Ausgabe).
- `ARCHON-OS` neu erzeugen: `docker compose -p archon -f docker-compose.dev.yml up -d --no-deps --force-recreate archon`
- **Altlast:** `docker-compose.yml` (Service `archon-os`) und `docker-compose.dev.yml` (Service `archon`)
  setzen beide `container_name: ARCHON-OS` → `compose config` mit **beiden** Dateien bricht ab.

---

## 5. Harte Regeln für die Arbeit am Repo

1. **Rot-Beweis vor Fix.** Altstand ansehen (`git show <sha>:<datei>`), Test schreiben, der dort rot ist,
   dann fixen. Beleg in den Commit-Text.
2. **Assertions niemals entschärfen.** Bestehende Tests bleiben grün; neue Tests pro Fix.
3. **Pfadgenau committen:** `git add -- <datei>` und `git commit … -- <datei>`. Kein `git add -A`,
   keine fremden Dateien mitschleifen.
4. **Ein Befund = ein nachvollziehbarer Diff.** Keine Nebenbei-Refactorings.
5. **Deploy braucht Freigabe.** Code-Änderungen sind durch `--reload` sofort live — Compose-Änderungen
   **nicht**. Nicht ohne Rückfrage recreaten.
6. **Keine Secrets in den Baum.** Proxy-Token/API-Keys nur über Env (`.env`, nicht getrackt).
7. Dokumentation nachziehen: `docs/ROADMAP.md`, **kein** neues Handover pro Etappe.

---

## 6. Fallstricke (alle schmerzhaft gelernt)

1. **`/stop` über den Proxy ist erlaubt** (`ALLOW_STOP=1`, weil Restart = stop+start). Eine „harmlose"
   ACL-Probe per `POST /containers/ARCHON-OS/stop` **stoppt den Produktionscontainer**. Für Proben
   ausschließlich `/restart` (bleibt 403) verwenden. Ist es doch passiert: `docker start ARCHON-OS`,
   danach den RAG-Sync neu starten (s. §8) — der läuft per `docker exec -d` und stirbt mit dem Container.
2. **Compose interpoliert nur aus `.env`/Shell, nicht aus `env_file`.** `${ARCHON_PROXY_ALLOW_EXEC}`
   in `.env.archon` zu schreiben hätte nichts bewirkt — der Wert muss in die Projekt-`.env`.
3. **Hintergrund-Agenten:** Ein `&`-Wrapper beendet sich sofort, Hermes meldet „completed (exit 0)",
   der Agent läuft weiter. Fortschritt **nie** am Prozessstatus ablesen, sondern an `ps -eo pid,etime,cmd`
   und an Datei-mtimes. Logs sind oft einzeilig (`Session … found but has no messages`), obwohl gearbeitet wird.
4. **`pgrep -f "hermes -p …"` matcht die eigene Kommandozeile.** Immer `ps … | grep "[h]ermes -p"`.
5. **Pipe verschluckt Exit-Codes:** `cmd | tail -3; echo $?` liefert den Status von `tail`. Immer
   `cmd > /tmp/x.log 2>&1; echo EXIT=$?`.
6. **`sudo`-Passwort-Piping funktioniert in dieser Umgebung nicht.** Sudo-Aktionen (z. B. `chown`)
   muss der Nutzer im Host-Terminal selbst ausführen.
7. **Kontext ist der Kostentreiber, nicht die Call-Zahl.** Gemessen: eine Spur mit 373 Calls hatte
   **107 Mio Cache-Read-Tokens** (~287.000 Token Kontext pro Call). Deshalb: Review-Dokumente nicht
   am Stück lesen, sondern nur die Befund-Abschnitte; keine Voll-Diffs im Verlauf; Suite **einmal am
   Ende** statt nach jedem Fix; max. ~20 Befunde pro Lauf.
8. **`--reload` heißt:** jede Schreiblücke unter `/app` ist Codeausführung. Writes immer über
   `safe_path`/Jail und Rollenzaun führen.

---

## 7. Die drei untracked Dateien (bewusst nicht committet)

```
docs/HANDOVER_2026-11-08_session2.md            Sitzungsanker der Vorsession
docs/HANDOVER_ANTIGRAVITY_2026-11-08.md         dieses Dokument
docs/REVIEW_2026-11-08_security.md              Security-Review (574 Zeilen, 28–32 Befunde)
scripts/audit_route_guards.py                   AST-Audit: 862 Routen-Einheiten, 494 mutierend, 129 mit Zaun
```

`docs/REVIEW_2026-11-08.md` (2.253 Zeilen) **ist** committet (`c642b924`).

---

## 8. RAG-Sync neu starten (falls der Container neu erzeugt wurde)

```bash
docker exec -d ARCHON-OS sh -c 'cd /app && nohup python3 tools/sync_vault_to_rag.py \
  --api-key "$ANYTHINGLLM_API_KEY" --limit 212 >> /tmp/sync_immo3.log 2>&1 &'
docker exec ARCHON-OS tail -3 /tmp/sync_immo3.log
docker exec ARCHON-OS python3 -c 'import json;print(len(json.load(open("/opt/data/synced_files.json"))))'
```

Der State (`/opt/data/synced_files.json`) liegt auf einem Bind-Mount und übersteht Recreates —
der Lauf setzt dort fort, wo er war.

---

## 9. Was **nicht** belegt ist — bitte nicht als erledigt lesen

- **Kosten sind Schätzungen.** `cost_status = 'estimated'`, `actual_cost_usd = 0.0`. Die Hermes-Schätzung
  liegt deutlich über dem OpenRouter-Listenpreis; belastbar ist nur die echte Abrechnung.
- **F20-Dauerbetrieb** nicht beobachtet — die Gegenproben sind Momentaufnahmen; ob ein `compose up`
  ohne `--no-deps` die Netz-Isolation später aufhebt, ist ungeprüft.
- **`ARCHON-OS` hat keinen Healthcheck** im dev-Compose (nur die base-Datei) — `docker inspect` zeigt
  deshalb keinen Health-Status.
- **WAN-Erreichbarkeit** der `0.0.0.0`-Listener nicht geprüft (kein sudo für `ufw status`).
- **Tote UI-Pfade:** 166 von 1640 `getElementById`-Zielen ohne DOM-Element — aus einer älteren Prüfung
  übernommen, **nicht** nachgemessen.

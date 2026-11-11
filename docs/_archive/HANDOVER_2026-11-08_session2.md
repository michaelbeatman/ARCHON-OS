# Handover 2026-11-08 (Session 2) — Archon OS

**Ersetzt** `docs/HANDOVER_2026-11-08.md` als Sitzungsanker. Fortschrittsblatt bleibt `docs/ROADMAP.md`.
Sprache: Deutsch. **Erst messen, dann behaupten** — jede Zahl hier wurde am 08.11. gegen ~10:13 gemessen.

**Stand:** Branch `refactor/a5-di-config` · HEAD **`909421d6`** · Working Tree **schmutzig** (laufende Agenten!)
**Tests:** bei letzter Messung **898 passed / 63 failed / 11 skipped** — Soll-Baseline war 860/8 vor den Fix-Läufen.

---

## 1. Copy-Paste für die nächste Session

```bash
cd /mnt/raid/AgenticOS-2026 && git log --oneline -1 && git status --short

# Laufen die Fix-Agenten noch? (NICHT mit pgrep -f, das findet sich selbst)
ps -eo pid,etime,cmd | grep -E "RED_FIX_Cluster" | grep -v grep

# Tests — EXAKTER Aufruf (ohne Pipe, sonst siehst du den Exit-Code von tail):
.venv/bin/python -m pytest tests/ -q > /tmp/pytest_state.log 2>&1; echo "EXIT=$?"
grep -cE "^FAILED" /tmp/pytest_state.log

# Instanz + RAG-Sync
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/health
docker exec ARCHON-OS tail -2 /tmp/sync_immo3.log
docker exec ARCHON-OS python3 -c 'import json;print("state:",len(json.load(open("/opt/data/synced_files.json"))))'
```

⚠️ **Testaufruf-Falle:** `.venv/bin/pytest tests/` scheitert an `ModuleNotFoundError: archon`;
ohne `tests/` sammelt pytest `OpenMontage/` und `browser-use/` mit (22 Collection-Errors).

---

## 2. Was gerade läuft — NICHT anfassen, nicht abbrechen

Zwei Agenten-Läufe bearbeiten die 🔴-Befunde aus den Reviews. Sie wurden als **detached** Prozesse
gestartet (Shell-Wrapper mit `&` beendet, Hermes-Prozess läuft weiter) und überleben den Sessionwechsel.

| Lauf | Profil | PID | Session-Name | Mandat | Log |
|---|---|---|---|---|---|
| **Cluster 1+2+4** | `senior_fullstack_engineer` | 2589908 | `RED_FIX_Cluster_124` | `cache/scratch/MANDAT_RED_CLUSTER_124.md` | `/tmp/red_fix_124.log` |
| **Cluster 3** | `devops_cloud_sec_specialist` | 2590619 | `RED_FIX_Cluster_3` | `cache/scratch/MANDAT_RED_CLUSTER_3.md` | `/tmp/red_fix_3.log` |

**Wichtig — Log-Dateien sind irreführend:** beide enthalten nur **eine** Zeile
(`Session … found but has no messages. Starting fresh.`). Die Arbeit ist trotzdem im Gange;
Fortschritt erkennt man an **Datei-mtimes im Repo**, nicht am Log. (Ursache: der `&`-Wrapper hat den
Output-Redirect übernommen, der Hermes-Prozess schreibt nicht in dieselbe Datei.)

**Fortschritt messen:**
```bash
cd /mnt/raid/AgenticOS-2026 && git status --short && ls -l --time-style=+%H:%M:%S main.py backend/fleet_self_healing.py
```

**Kill, falls nötig:** `kill 2589908 2590619` (SIGTERM), dann `git status` prüfen —
Halbfertiges bleibt liegen und muss als **Entwurf** behandelt werden (erst Test, dann weiterbauen).

---

## 3. Was in dieser Session passiert ist

### 3.1 Reviews neu angesetzt — BEIDE FERTIG

| Dokument | Zeilen | Befunde |
|---|---|---|
| `docs/REVIEW_2026-11-08.md` (Code/Architektur) | 2197 | **157**: 33 🔴 · 68 🟠 · 55 🟡 · 1 ⚪ (+28 „nicht geprüft") |
| `docs/REVIEW_2026-11-08_security.md` (Security) | 574 | **32**: 3 🔴 · 12 🟠 · 14 🟡 · 3 ⚪ |
| `scripts/audit_route_guards.py` (neu, AST) | — | 862 Routen-Einheiten, 494 mutierend, 129 mit Zaun, 365 ohne |

**Routen-Kennzahl (Security-Review, gemessen):** 862 Einheiten · 494 mutierend · 129 mit Rollenzaun
(davon 123 als erste Anweisung) · 365 ohne Zaun (361 hinter Auth-Gate, 4 öffentlich) · 63 DELETE ohne
Zaun · 50 gemischte `api_route` (45 davon **ein** Handler, keiner verzweigt auf `request.method`).

### 3.2 🔴-Fix-Läufe gestartet (laufen noch)

**Cluster 1+2+4** (`senior_fullstack_engineer`): F1/R-34 (Auth-Bypass `/static/hermes-webui/api/*`),
R-08/F9 (Auth-Gate fail-open), R-09 (6 Router ohne Zaun), F11 (`api_route`-Verzweigung),
F19/M-03/Z-01 (Notebook-Upload & Obsidian-Write Traversal), F3/M-02/D-05 (Datei-Read ohne Jail),
F24 (`/api/vault/edit`), D-04 (XSS Chat-Markdown).

**Cluster 3** (`devops_cloud_sec_specialist`): F20 (Docker-Socket-Proxy ohne Auth),
F2/F26/R-05/N-12 (Command-Injection `shell=True`), F5 (Sandbox-Härtung), F27 (Container-Limits),
F8 (Dev/Prod-Drift dokumentiert).

### 3.3 Baumstand während der Läufe (10:13 gemessen)

**Geänderte Dateien (12):**
```
archon/core/constants.py        backend/auth_service.py      backend/autonomy_settings.py
backend/ephemeral_sandbox.py    backend/fleet_self_healing.py backend/task_self_healer.py
deploy/docker-socket-proxy/haproxy.cfg                        docker-compose.dev.yml
docker-compose.yml              docs/BETRIEB_HANDBUCH_INTERN.md
main.py                         utils/path_jail.py
```

**Neue Testdateien (9, alle `??`):** `tests/test_fix_{r34_proxy_auth,r08_auth_failclosed,r09_router_guards,f19_traversal,m02_d05_file_read,f24_vault_edit,d04_xss}.py`, `tests/test_cluster3_hardening.py`, `tests/archon_security_support.py`

**Neue Doku:** `docs/REVIEW_2026-11-08.md`, `docs/REVIEW_2026-11-08_security.md`, `scripts/audit_route_guards.py`

**Teststand 10:13** (`pytest tests/ -q`): **898 passed, 63 failed, 11 skipped**
Fehlschläge nach Datei: `test_fix_r09_router_guards.py` 18 · `test_fix_m02_d05_file_read.py` 13 ·
`test_fix_r34_proxy_auth.py` 11 · `test_fix_f24_vault_edit.py` 6 · `test_fix_r08_auth_failclosed.py` 5 ·
`test_fix_f19_traversal.py` 5 · `test_fix_d04_xss.py` 5.
**Einordnung: das ist Zwischenstand, keine Regression.** Die Tests sind Rot-Beweise und werden grün,
sobald der jeweilige Fix landet. `tests/test_cluster3_hardening.py` war bei 23/24 (1 offen:
`test_limits_declared[docker-compose.yml-archon-os]`).

---

## 4. Fallstricke dieser Session

1. **`&` im Hintergrund-Kommando macht die Fertigmeldung wertlos.** Der Shell-Wrapper endet sofort,
   Hermes meldet „completed (exit 0)" — der eigentliche Agent läuft weiter. **Fortschritt nie am
   Prozess-Status ablesen, sondern an `ps` + Datei-mtimes.**
2. **Log-Datei kann leer/einzeilig sein, obwohl der Lauf arbeitet** (Redirect vom Wrapper übernommen).
3. **`pgrep -f "hermes -p …"` matched die eigene Kommandozeile** — immer
   `ps -eo pid,etime,cmd | grep "[h]ermes -p"` oder PID merken.
4. **Beide technischen Profile hängen am selben OpenRouter-Key** (`openrouter/deepseek/deepseek-v4.1-flash-1017`).
   Parallele Läufe teilen einen Rate-Limit-Bucket → Cooldown, wenn beide gleichzeitig starten.
   Entzerrung: 15 s Versatz. **Dauerhafte Lösung offen:** `devops_cloud_sec_specialist` auf ein
   anderes Modell legen (Wunsch: „5.3 flash" bzw. Gemini Flash) — `roles.json` patchen, dann Status
   über `POST /api/hermes/profiles/<id>/status` setzen (nicht per Hand in der Datei).
5. **Ein `-q`-Lauf kann `docker stop/restart/kill` nicht freigeben** — Lifecycle-Schritte bleiben beim
   Nutzer. Cluster 3 darf deshalb **keinen** Container recreaten (steht so im Mandat).
6. **Pipe verschluckt Exit-Codes:** `cmd | tail -4; echo $?` liefert den Status von `tail`. Immer
   `cmd > /tmp/x.log 2>&1; echo EXIT=$?`.

---

## 5. Was NICHT belegt ist (ehrlich)

- **Kein Fix ist committet.** Seit `909421d6` gibt es keinen neuen Commit; alles liegt uncommittet im Baum.
- **Kein Fix ist deployt/verifiziert** — die Instanz läuft noch mit dem alten Code (bis auf `--reload`,
  das geänderte Python-Dateien live nachlädt; Compose-Änderungen sind **nicht** aktiv).
- **Kein Volltest grün** (63 rot, Stand 10:13).
- **Kein Rot-Beweis geprüft** — die Testdateien existieren, ob sie gegen den Altstand wirklich rot sind,
  ist nicht nachgefahren.
- **Security-Befunde ohne Live-Gegenprobe:** F20 (Proxy 200 aus `anything-llm`) und F1 wurden vom
  Security-Lauf belegt; die **Fixes** sind unbelegt.
- **WAN-Erreichbarkeit** der `0.0.0.0`-Listener nicht geprüft (kein sudo für `ufw status`).

---

## 6. Erste Schritte einer neuen Session

1. §1-Copy-Paste fahren; **zuerst prüfen, ob die zwei Agenten noch laufen** (`ps`).
2. **Laufen sie noch:** nicht anfassen, warten. Nur beobachten (`git status`, mtimes). Keine
   konkurrierenden Edits an denselben Dateien.
3. **Sind sie beendet:** Ergebnis bewerten —
   - `git log --oneline -5` (wurde committet?)
   - `.venv/bin/python -m pytest tests/ -q > /tmp/t.log 2>&1; echo EXIT=$?`
   - `git diff --stat` gegen die im Mandat erlaubten Dateien abgleichen
   - Rot-Beweise stichprobenartig selbst fahren (Altstand via `git show HEAD:<datei>`)
4. **Dann entscheiden:** verbleibende 🔴 committen/deployen (mit Freigabe), danach 🟠-Cluster.
5. `docs/ROADMAP.md` nachziehen — **kein neues Handover** nach jeder Etappe.

---

## 7. Offene Punkte (Stand jetzt)

| # | Punkt | Stand |
|---|---|---|
| 1 | 🔴-Fixes Cluster 1+2+4 | **läuft** (PID 2589908), 63 Tests noch rot |
| 2 | 🔴-Fixes Cluster 3 | **läuft** (PID 2590619), 1 Test offen (Compose-Limits) |
| 3 | Commits + Deploy der Fixes | offen, braucht Freigabe (Deploy = Live-Instanz) |
| 4 | Modell-Entkopplung `devops_cloud_sec_specialist` | offen, Wunsch „5.3 flash"/Gemini — `roles.json` + Status-API |
| 5 | 🟠-Befunde (68 Code + 12 Security) | offen, Cluster-Bildung nötig |
| 6 | RAG-Sync | läuft: **37/212** Dateien, bei `Kapitel_01` des nächsten Buchs, ~176 s/Kapitel |
| 7 | RAG-Umfang | 4.221 Dateien offen ≈ 217 h auf dieser CPU → kuratiertes Paket oder Cloud-Embedder |
| 8 | Socket-Mount (C1) | bleibt bewusst (Sandbox braucht `docker run`); eigener Runner = 1–2 Tage |
| 9 | A5/A7/A8, tote UI-Pfade, Paket 3 | unverändert offen (ROADMAP §3) |
| 10 | Secrets im getrackten Baum | F6: 218 Treffer (`tools/sync_*.py`, `main.py:612`, Compose, `.archon_backup_*`) — Rotation/Aufräumen offen |

---

## 8. Infrastruktur (unverändert)

| Dienst | Projekt | Compose | Anmerkung |
|---|---|---|---|
| `ARCHON-OS` | `archon` | `docker-compose.dev.yml` | `--reload`, uid 1000, Socket gemountet (C1) |
| `docker-socket-proxy` | `archon-os-dev` | `docker-compose.dev.yml` | `deploy/docker-socket-proxy/haproxy.cfg`, `ALLOW_RESTARTS=0` |
| `anything-llm`, `ollama-embed`, `chroma` | `archon-os` | `docker-compose.yml` | Netz `archon-os-dev_agents_net` |

**Projektnamen sind Pflicht:** ohne `-p archon` bzw. `-p archon-os-dev` entstehen zweite Instanzen.
Recreate immer mit `--no-deps`. **`docker compose config` immer mit `-q`** (sonst Secrets in der Ausgabe).

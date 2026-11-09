# Security-Review Archon OS — 08.11.2026

**Stand:** 08.11.2026 · Branch `refactor/a5-di-config` @ `909421d6`
**Umfang:** lesende Prüfung von Code, Compose, Abhängigkeiten und Laufzeit-Zustand
**Eingriffsstufe:** nur Analyse. Kein Code geändert, kein Commit, kein Container neu erstellt/gebaut/neu
gestartet. Neu angelegt wurden ausschließlich `scripts/audit_route_guards.py` und dieses Dokument.
Im App-Container lief ein RAG-Sync; alle Requests unten sind `GET` oder Probes auf **nicht existierende**
Upstream-Pfade bzw. mit 401/403/404/405-Erwartung. `docker exec` wurde nur lesend benutzt
(`curl -o /dev/null`, `ls`, `python -` ohne Schreibzugriff).

**Ausgeschlossen (per Auftrag, gilt als erledigt und wird hier nicht als Befund geführt):**

* Rollenzaun-Bestand: 123 Klasse-A-Operationen über `archon/routers/_rbac.py`, fail-closed.
* Upload-RCE (`basename`+`safe_path`), Vault-Jail, `voice-relay`, Avatar-Upload — nachgeprüft, siehe §4.
* `/var/run/docker.sock` im App-Container (Entscheidung C1) — nur als Verstärker bewertet.
* Alter RAG-Key in Git-Historie und Backup-Dateien (entschieden und dokumentiert) — siehe §7, dort nur
  die Feststellung, dass er *auch* im Arbeitsbaum getrackter Dateien steht.
* Aktive Angriffe gegen laufende Dienste.

---

## 1. Zahlenbild — Routen und Rollenzaun

Gemessen mit `scripts/audit_route_guards.py` (AST, keine Regex), reproduzierbar:

```
.venv/bin/python scripts/audit_route_guards.py --root . --json /tmp/audit.json --list
```

| Kennzahl | Wert |
|---|---|
| Routen-Einheiten (Methode × Pfad) | **862** |
| davon mutierend (`POST`/`PUT`/`PATCH`/`DELETE`) | **494** |
| davon lesend | 368 |
| mutierend **mit** Rollenzaun | **129** |
| … davon Zaun als **erste** Anweisung | **123** |
| … davon Zaun erst später im Rumpf | 6 |
| mutierend **ohne** Rollenzaun | **365** |
| … davon hinter dem Auth-Gate (`/api/*` → 401) | 361 |
| … davon **öffentlich** (`public`-Prefix, kein Gate) | **4** |
| … davon außerhalb jeder Prüfung | 0 |
| `DELETE`-Einheiten gesamt (ohne Zaun) | 68 (63) |
| Catch-all `{path:path}`, mutierend, ohne Zaun | 100 (57) |
| `api_route`-Deklarationen mit >1 Methode | 50 — **45 davon in einem einzigen Handler** |
| `APIRouter(dependencies=[...])` (Sammel-Schranke) | 0 |

**Gegenprobe:** ein zweiter, unabhängig gebauter Zähler (eigene Dekorator-Erkennung über AST plus
Regex-Zählung der Dekoratorzeilen) kommt auf dieselben Zahlen: 663 Dekoratoren → 862 Einheiten, keine
Datei mit Abweichung zwischen AST- und Regex-Zählung. Der Code-Kommentar in `main.py:7672` nennt
„585 Pfade / 861 Operationen" — dazu konsistent.

**Zählregel** (bewusst eng, damit die Zahl nicht schönrechnet):

* **Einheit** = (Datei, Zeile, Methode, Pfad). Ein `@app.api_route(..., methods=["GET","POST"])` ergibt
  **zwei** Einheiten. Router-Prefixe (`APIRouter(prefix=...)`) werden aufgelöst — sonst steht in
  `operations_api.py` nur `/kanban/tasks` statt `/api/operations/kanban/tasks` und die Gate-Frage ist
  nicht beantwortbar (dieser Fehler steckte in der ersten Fassung des Skripts).
* **Routen-Quelle**: `main.py`, `views_core.py`, `backend/operations_api.py`, `archon/routers/*.py`
  (außer `_rbac.py`) und jedes `backend/*.py` mit `APIRouter(`.
* **mutierend** = Methode in {POST, PUT, PATCH, DELETE}. GET/HEAD/OPTIONS gelten als lesend.
* **geschützt** = im Funktionsrumpf steht ein Aufruf `require_admin*`, `require_role`, `ensure_admin`,
  `Depends(<guard>)` **oder** ein Inline-Vergleich `role != "admin"` / `role not in {...}` gegen eine per
  `get_current_user*()` geholte Identität. **Nur der Name zählt** — ob der Guard wirklich sperrt, ist
  Sichtprüfung (Befunde unten).
* **Zaun-Position** = wird zusätzlich geprüft: ist der Guard die *erste* Anweisung (Docstring zählt
  nicht, `try:` wird aufgeschlossen)? Ein `require_admin()` **nach** `open(...)` schützt nichts mehr —
  daher die Trennung 123 / 6.
* **Auth-Gate** = Middleware `auth_gate` (`main.py:229`): `/api/*` ohne Session → 401,
  `_AUTH_PROTECTED_PREFIXES` → 307 auf `/login`, `_AUTH_PUBLIC_PREFIXES`/`_AUTH_PUBLIC_EXACT`
  (`archon/core/constants.py:25`, `main.py:148`) → **ungeprüft durchgelassen**.

**Warum 129 und nicht 123:** 123 Einheiten haben den Zaun tatsächlich **vor** der ersten schreibenden
Anweisung — exakt die „123 Klasse-A-Operationen" aus `1424e3dc`. Die 6 Mehrfachtreffer sind der
Auth-/User-Cluster (`main.py:7696, 7769, 7786, 7803, 7836, 8548`): erste Anweisung ist dort
`curr = get_current_user_from_request(request)`, der Rollenvergleich folgt wenige Zeilen später —
funktional korrekt („eigener Account oder admin"), aber nicht „Guard als erste Anweisung". Kein
Sicherheitsbefund, nur eine präzisere Kennzahl.

**Zu den 48 mehrdeutigen `api_route`-Fällen:** gemessen 50 Einheiten auf **6 Handlern**. Entscheidend
für die Methodenfrage: **kein einziger** Handler im Bestand verzweigt auf `request.method`
(Gegenprobe: 0 Treffer für `request.method ==` in `main.py`, `views_core.py`, `archon/`, `backend/`).
Ein `api_route` mit gemischtem Methodensatz bekommt also *einen* Zaun für alle Methoden — oder keinen
für alle. 45 der 50 Einheiten gehören zu **einem** Handler, `proxy_hermes_api_endpoints`
(`main.py:9578–9624`): 45 Pfade je (`GET`,`POST`,`OPTIONS`,`PUT`,`DELETE`), ohne Zaun. Das Skript
zählt deshalb am Handler und dokumentiert diese Grenze im Docstring; sobald ein Handler
methodenabhängig prüft, muss die Zählung nachgezogen werden.

**Einordnung:** „365 ohne Zaun" ist **nicht** „365 offene Türen". 361 liegen hinter einem aktiven
Login-Gate (live: `/api/contracts` → 401, `/api/sessions` → 401). Es fehlt die *Rollentrennung*, nicht
die *Authentifizierung*. Das Gate prüft in `main.py:260-264` ausschließlich `_auth.verify_session(token)`
— **ohne Rolle**. Gefährlich wird es bei (a) Nicht-Admin-Konten, (b) abgeschaltetem `auth.enabled`,
(c) den 4 öffentlichen Routen — und genau dort liegt F1.

---

## 2. Top 5 nach Ausnutzbarkeit

1. **Anonymer Vollzugriff auf die Hermes-Kommando-API** über `/static/hermes-webui/api/*`: öffentlicher
   Prefix umgeht das Gate, der Proxy setzt den **hartkodierten** Admin-Token ein. Ohne Anmeldung, aus
   dem LAN über `:8420`, Aufwand ein `curl`. → **F1**
2. **Path-Traversal-Schreibpfad im Notebook-Upload** → `/app/main.py`, `uvicorn --reload` aktiv → Code
   als uid 1000. Jede eingeloggte Rolle, ein POST. → **F19**
3. **Docker-Socket-Proxy ohne Authentisierung im gemeinsamen Netz**: jeder Container in `agents_net`
   darf `CONTAINER_CREATE`/`EXEC`/`VOLUMES` (live 200 gemessen), darunter das ungeschützte
   `anything-llm` (0.0.0.0:3001). Aus Container wird Host-Root. → **F20**
4. **Kommando-Injektion im Selbstheilungspfad** `/api/healing/attempt`: `git checkout -- {pfad}` per
   Shell-String, `affected_file` ungeprüft, `auto_rollback` standardmäßig `True`. Jede Rolle, ein POST.
   → **F2**
5. **Beliebiges Datei-Lesen unter `/app`** über `/api/views/showroom/file-content` — liefert u. a.
   `.env.archon` und `data/.archon_service_token` (Rollen-Eskalation zu `admin`). Jede Rolle, ein GET.
   → **F3**

---

## 3. Befundliste

### 🔴 ausnutzbar / akut

**F1 — Auth-Gate wird von `/static/hermes-webui/api/*` umgangen; Proxy setzt Admin-Token ein**
`main.py:9624` (Route), `main.py:595–632` (`forward_to_hermes`), `main.py:611–614` (Token),
`archon/core/constants.py:30` (public-Prefix).
*Angriffsweg:* `_AUTH_PUBLIC_PREFIXES` enthält `/static/`; die Route
`GET|POST|PUT|DELETE /static/hermes-webui/api/{path:path}` liegt darunter und wird ungeprüft
durchgelassen. `forward_to_hermes` reicht `request.method` **und** den Body weiter, verwirft nur
`host`, `content-length`, `authorization` und setzt stattdessen den internen Hermes-Token
(`main.py:611-614`, Wert aus Env, mit hartkodiertem Fallback → F6).
*Beleg:*
```
GET  /static/hermes-webui/api/health    -> 200
GET  /static/hermes-webui/api/status    -> 200  {"version":"0.22.7",...}
GET  /static/hermes-webui/api/sessions  -> 200  len=32575
GET  /static/hermes-webui/api/config    -> 200  len=27130   (5 Treffer "sk-…", 24 Felder "api_key")
GET  /static/hermes-webui/api/profiles  -> 200  len=28624
GET  /static/hermes-webui/api/__nonexistent_probe__ -> 404   (bis zum Upstream durchgelassen)
POST /static/hermes-webui/api/__nonexistent_probe__ -> 405   (Methode passiert das Gate)
Kontrolle: GET /api/sessions -> 401 | GET /api/status -> 401 | GET /api/debug-db -> 401
Aus dem LAN: GET http://192.168.0.230:8420/static/hermes-webui/api/status -> 200
             GET http://192.168.0.230:8420/api/status                     -> 401
```
Die 405 statt 401 beweist, dass die *Methode* das Gate passiert und den Upstream erreicht; 404/405
kommen vom Hermes-Dienst. Es wurde nur ein nicht existierender Pfad mit mutierenden Methoden
angesprochen. Die 200er-Antworten enthalten Material, das nach Schlüssel aussieht — deshalb ist das
hier 🔴 und nicht 🟠. **Werte werden nicht wiedergegeben.**

**F19 — Path-Traversal-Schreibpfad im Notebook-Upload (Codeausführung)**
`main.py:2455` (`POST /api/v1/notebooks/{nb_id}/sources/upload`, **ohne** Zaun) →
`utils/notebook_engine.py:181`: `saved_file_path = os.path.join(raw_dir, filename)`.
`filename` kommt unverändert aus dem Multipart-Upload (`file.filename` ist der Rohwert aus
`Content-Disposition`) — kein `basename`, kein `safe_path`, keine Endungs-Whitelist. `raw_dir` ist im
laufenden Container `/app/library/raw_docs` (die Vorgängerkandidaten existieren dort nicht).
*Angriffsweg:* angemeldetes Konto (jede Rolle) → POST mit präpariertem Dateinamen → Schreiben in den
Code-Baum; der Container läuft mit `uvicorn --reload`, der nächste Reload importiert die Datei →
Ausführung als uid 1000.
*Beleg (nur Auflösung, kein Schreibzugriff):*
```
docker exec ARCHON-OS sh -c 'ls -d /opt/data/workspace/library/raw_docs /app/library/raw_docs'
  -> fehlt: /opt/data/workspace/library/raw_docs     EXISTS: /app/library/raw_docs
docker exec ARCHON-OS sh -c 'pwd; ls /app/main.py'
  -> /app    /app/main.py
docker inspect ARCHON-OS --format '{{.Config.Cmd}} {{.Config.User}}'
  -> [uvicorn main:app --host 0.0.0.0 --port 8501 --reload]  1000:1000
os.path.join("/app/library/raw_docs", "../../main.py") -> /app/main.py
POST /api/v1/notebooks/x/sources/upload -> 401 (Gate aktiv; Lücke ist der fehlende Pfadcheck)
```

**F20 — Docker-Socket-Proxy ohne Authentisierung im gemeinsamen Netz, mit Schreibrechten**
`docker-compose.dev.yml` / produktiv: `tecnativa/docker-socket-proxy`, `:2375`, kein TLS, kein Token.
Aus `docker inspect`: `POST=1`, `CONTAINER_CREATE=1`, `EXEC=1`, `VOLUMES=1`, `NETWORKS=1`, `IMAGES=1`,
`CONTAINER_DELETE=1`, `STOP=1`; gesperrt: `RESTARTS=0`, `SYSTEM=0`, `SECRETS=0`, `SWARM=0`, `AUTH=0`.
*Angriffsweg:* jeder Container in `agents_net` kann einen beliebigen Container (privilegiert, mit
Host-Mount) erzeugen oder in laufende Container `exec`en → Host-Root. Der schwächste Nachbar ist
`anything-llm` (F21) — der das nicht einmal bräuchte, er ist schon im Netz.
*Beleg:*
```
docker exec ARCHON-OS   sh -c 'curl -o /dev/null -w "%{http_code}" http://docker-socket-proxy:2375/version'        -> 200
docker exec anything-llm sh -c 'curl -o /dev/null -w "%{http_code}" http://docker-socket-proxy:2375/version'        -> 200
docker exec anything-llm sh -c 'curl -o /dev/null -w "%{http_code}" http://docker-socket-proxy:2375/containers/json' -> 200
```
*Korrektur zu einer früheren Fassung:* „aus der Sandbox nicht per Name erreichbar" gilt nur für die
Sandbox (`--network none`). Aus den **Anwendungs**-Containern im `agents_net` ist er erreichbar —
gemessen.

### 🟠 unter Bedingungen (gültige Session, jede Rolle — bzw. Container-Zugriff)

**F2 — Kommando-Injektion über `affected_file` im Selbstheilungspfad**
`main.py:11252` (Route, **ohne** Zaun) → `main.py:11261` (`affected_file=payload.get(...)`) →
`backend/task_self_healer.py:46–50`: `cmd = f"git checkout -- {file_path}"`,
`subprocess.run(..., shell=True)`. Der Aufruf ist **nicht** optional:
`rollback_git_changes(affected_file) if auto_rollback`, und `auto_rollback` startet als `True`
(`:73`, per Settings überschreibbar, Default `True`).
*Angriffsweg:* `{"affected_file": "x; <befehl>"}` landet ungefiltert in einem Shell-String. Container
läuft als uid 1000, `/app` ist der Bind-Mount des Repos, `--reload` ist aktiv (F8) → jeder Treffer ist
persistente Codeausführung.
*Beleg (Wegwerf-Repo, exakt der Code aus Z. 48–50, nichts Echtes angefasst):*
```
cmd = git checkout -- a.txt; echo "INJECTION_EXECUTED uid=$(id -u)"
stdout: INJECTION_EXECUTED uid=1000
```
Gegen den laufenden Dienst nicht gesendet (mutierend): `POST /api/healing/attempt` → **401**.

**F3 — Arbiträres Datei-Lesen unter `/app` (Secrets) über die Showroom-Vorschau**
`views_core.py:432–441` (`GET /api/views/showroom/file-content?path=…`, **ohne** Zaun).
*Angriffsweg:* die Prüfung ist `str(target).startswith(str(vault_dir)) or str(target).startswith(str(base_dir))`
nach `Path.resolve()` — jedes Unterverzeichnis von `/app` (und des Vaults) ist erlaubt. `/app/.env.archon`
(600, im Container von uid 1000 lesbar) enthält zehn Provider-Keys.
*Beleg:* `GET /api/views/showroom/file-content?path=/app/main.py` → **401** (Gate aktiv, Rollenzaun
fehlt); Dateiliste in `.env.archon` per `grep -c "API_KEY="` bestätigt (Werte nie gelesen).
*Zusatz:* derselbe Weg liest `data/.archon_service_token` (49 Byte, 600, uid 1000) → dieses Token
vergibt laut `main.py:7638-7647` die Rolle `admin`. F3 ist damit ein Rollen-Eskalationspfad.

**F4 — Beliebiges Kopieren aus dem Container in einen ausgelieferten Ordner**
`views_core.py:496–518` (`POST /api/views/showroom/export-desktop`): `payload.filepath` wird nur auf
Existenz geprüft, dann `shutil.copy2` nach `/opt/data/Desktop` (Bind-Mount von `~/.hermes` auf dem Host).
Quelle kann `/app/.env.archon` sein. Ohne Zaun.
*Beleg:* statisch eindeutig; POST nicht gesendet (schreibend), ohne Login 401.

**F5 — Sandbox: roher Socket, keine Container-Härtung, Netz per Request**
`main.py:11280-11292` (Route, Zaun vorhanden), `backend/ephemeral_sandbox.py:166–190`.
`docker run --rm -m … --cpus … -v <tmp>:/sandbox` — **ohne** `--cap-drop ALL`, `--read-only`,
`--pids-limit`, `--security-opt no-new-privileges`, `--user` (also root im Container), Image-Tag
`python:3.11-alpine` ungepinnt. Der Aufruf geht über `docker_cli_host_args()`
(`utils/docker_client.py:139–151`) direkt an `/var/run/docker.sock` und umgeht damit Allowlist und
Methoden-ACL des Proxys — bewusst (Klasse C). `network_enabled` ist per Body schaltbar (Default aus);
bei `true` hängt der Container am Default-Bridge mit vollem Egress. Das Kommando wird als **Liste**
gebaut (kein `shell=True`), nur das Temp-Verzeichnis wird gemountet — Ausbruch also nur über
Kernel-/Docker-Lücke, nicht über die Kommandozeile. Fail-closed ohne Docker ist korrekt (Z. 205–220).
*Beleg:* `POST /api/sandbox` → **501** (Notbremse aktiv); `/api/sandbox/execute` ist admin-gezaunt
(AST). Nicht ausgeführt (mutierend).

**F6 — Klartext-Schlüssel im getrackten Baum** (nur Pfade, keine Werte)
* `tools/sync_cannabis_rag.py:8`, `tools/sync_cannabis_rag_parallel.py:10`,
  `tools/sync_remaining_600s.py:8`, `tools/sync_vault_all_parallel.py:9` — Literal `API_KEY = "…"`,
  **in `HEAD`** (nicht nur Historie — siehe §7).
* `main.py:612`, `archon/services/profiles_service.py:353,359` — hartkodierter Fallback für
  `OMNIROUTE_API_KEY`; greift, wenn die Env-Variable fehlt (`docker inspect` zeigt `OMNIROUTE_URL`,
  aber **kein** `OMNIROUTE_API_KEY` → der Literal-Token ist der produktiv benutzte).
* `scripts/paperclip_hire_agent.cjs:7` (Postgres-URL mit Klartext-Passwort), `:52` (`apiKey`-Literal);
  `backend/post_task_pipeline.py:490` (gleiche Zugangsdaten im eingebetteten JS) — beide in `HEAD`
  (`git show HEAD:<datei>` enthält sie).
* `docker-compose.yml:67` — `N8N_USER_MANAGEMENT_JWT_SECRET` als Literal; dazu
  `N8N_SECURE_COOKIE=false` (`:65`), `N8N_XFRAME_BYPASS=true` (`:64`), JWT-Laufzeit 8760 h (`:68`).
* `docker-compose.archon.yml` — `BETTER_AUTH_SECRET` (paperclip) und `INITIAL_PASSWORD` (omniroute)
  als Literale.
* `.archon_backup_20261105_1015/` — **189 getrackte** Dateien mit Schlüssel-Literalen
  (`hermes_profiles_bak-0928/*.config.yaml`, `dup_profiles/*.json`). Der Ordner ist seit `a4f580dd`
  im Baum: **Arbeitsbaum, nicht nur Historie**.
* *Beleg:* Muster-Scan über `git ls-files` (6.242 Dateien) → **218 Treffer**: 190 × `sk-…`,
  21 × URL-Credentials, 7 × Literal-Zuweisung an `api_key/token/secret`. Die Trefferzahl ist
  musterabhängig (engerer Scan: 118); Werte wurden nie ausgegeben. `.env*` ist **nicht** getrackt und
  liegt mit `600` (`-rw-------`).

**F21 — `anything-llm` ohne Authentisierung auf `0.0.0.0:3001`, im selben Netz wie der Proxy**
Kein `AUTH_TOKEN`/`SIG_KEY`/`JWT_SECRET` in der Umgebung; Port auf allen Interfaces. Die
Wissensdatenbank ist im LAN lesbar; der Container ist der kürzeste Weg von „Fehler in einer Web-App"
zu „Host-Root" (F20).
*Beleg:*
```
docker port anything-llm                          -> 3001/tcp -> 0.0.0.0:3001
curl http://127.0.0.1:3001/                       -> 200   (SPA-Hülle)
curl http://127.0.0.1:3001/api/v1/auth            -> 403   {"error":"No valid api key found."}
docker inspect anything-llm | grep -Ei "AUTH|SIG|JWT" -> (leer)
```

**F22 — App und Hermes-Dashboard aus dem LAN erreichbar über `socat`-Listener**
`socat TCP-LISTEN:8420,fork,reuseaddr TCP:127.0.0.1:8501` (PID 2432236) und
`socat TCP4-LISTEN:9120,bind=0.0.0.0 TCP4:127.0.0.1:9119` (PID 2432239) machen die
`127.0.0.1`-Bindung von Compose wirkungslos. Zusammen mit F1 ist das der LAN-Einstieg in den
unauthentisierten Proxy.
*Beleg:*
```
ss -lntp | grep -E ":8420|:9120"   -> 0.0.0.0:8420 socat | 0.0.0.0:9120 socat
curl http://192.168.0.230:8420/static/hermes-webui/api/status -> 200
curl http://192.168.0.230:8420/api/status                     -> 401
```

**F23 — SSRF im Verbindungstest**
`archon/routers/llm_providers.py:332` (`POST /api/llm-providers/test-connection`, **ohne** Zaun) →
`backend/privacy_router.py:141–180`: `url` aus dem Payload, `urlparse` ohne Schema-Prüfung, roher
`socket.create_connection` (Portscan) plus `urllib.request.urlopen` (folgt Redirects). Kein
`utils.egress_guard` — obwohl das Modul existiert und in `main.py:9499` benutzt wird. Kein
`STRICT_PREFIX` (`utils/rate_limit.py:43`) → 600/min statt 20/min.
*Beleg (Funktion direkt, gegen lokal gebundene Dienste):*
```
url=http://127.0.0.1:11434/v1 -> available=True, latency=1ms, models=3   (Ollama, nur lokal gebunden)
url=http://127.0.0.1:6379/v1  -> available=True, latency=1ms              (Redis: reiner Port-Connect)
url=http://127.0.0.1:1/v1     -> available=False, Connection refused      (Kontrolle)
```

**F24 — `/api/vault/edit` schreibt in das Agenten-Home (`/opt/data`) ohne Rollenzaun**
`main.py:8712–8724` (edit, **ohne** Zaun) gegenüber `main.py:8726–8748` (delete, Admin-Zaun **und**
`startswith(vault_root)`-Verengung). `safe_path` akzeptiert zehn Default-Wurzeln
(`utils/path_jail.py:32–54`), darunter `/opt/data` — im laufenden Container ist das
`/home/micha/.hermes` **rw**. Damit sind `SKILL.md`, `config.yaml` und `.env` des Agenten
überschreibbar; Wirkung beim nächsten Reload/Agentenstart (Skill-/Prompt-Injection, Key-Umleitung).
*Beleg (Auflösung, kein Schreibzugriff):*
```
[ERLAUBT] '/root/.hermes/config.yaml'       -> /root/.hermes/config.yaml
[ERLAUBT] '/root/.hermes/skills/x/SKILL.md' -> /root/.hermes/skills/x/SKILL.md
[BLOCKT ] '/opt/data/../../etc/passwd' | '/app/data/../main.py' | '/etc/passwd'
docker inspect ARCHON-OS --format '{{range .Mounts}}{{.Source}}->{{.Destination}} {{end}}'
  -> /home/micha/.hermes -> /opt/data  (rw)
```
Die Verengung, die `delete` hat, fehlt bei `edit` — `extra_roots` **erweitert** das Jail, es verengt
nicht (Kommentar in `main.py:8737-8740` sagt das selbst).

**F25 — Beliebiges Datei-Lesen über den Dokumenten-Parser (kein Jail, absolut)**
`main.py:8589–8595` (`POST /api/documents/parse`), `main.py:8598–8608`
(`/api/v1/documents/parse`, `/api/documents/extract-tables`), `main.py:11094–11100`
(`POST /api/diff/preview`). `filepath` kommt aus dem Body, geprüft wird nur `os.path.exists()`.
Anders als F3 ist hier **kein** Präfix erzwungen.
*Beleg (im Prozess, kein Schreibzugriff):*
```
/etc/hostname     Jail=BLOCKT   Parser-Status=success    12 Zeichen geliefert
/etc/os-release   Jail=BLOCKT   Parser-Status=success   410 Zeichen geliefert
```
Das Jail blockt den Pfad, die Route fragt es nicht.

**F26 — Kommando-Injektion in `/api/fleet/heal/{service_name}`**
`main.py:11175–11184` (Route, Admin-Zaun vorhanden) → `backend/fleet_self_healing.py:26–37`:
`KNOWN_SERVICES.get(svc_key, service_name)` reicht den Rohwert in `f"docker restart {target}"` mit
`shell=True`. `validate_container_name` (`utils/docker_client.py:154`) wird **nicht** aufgerufen.
*Beleg (String-Bau, keine Ausführung):* `x%3B echo BELEG` → `docker restart x; echo BELEG`,
Metazeichen erkannt: `[';']`.
Nebenbei: das Kommando ist `docker restart` — die B2-Entscheidung („restart über stop+start") gilt hier
nicht; der Aufruf läuft über die CLI und nicht durch den gesperrten Proxy.

**F8 — Jede Dateischreib-Lücke wird Codeausführung (Verstärker, kein Einzelbefund)**
`docker-compose.dev.yml:5,9,34` + `docker inspect ARCHON-OS`: `user 1000:1000`, Repo als `/app`
eingebunden, `uvicorn --reload`. Zusammen mit F2/F3/F4/F19/F24 heißt das: Schreiben nach `/app/*.py`
= Ausführung beim nächsten Reload. Zusätzlich **Drift**: `docker-compose.yml:16` sagt `user: root`,
`docker-compose.yml:35` `${USERPROFILE}/.hermes` und `:36` `C:\Mein Obsidian` (Windows-Pfade),
`:20` `"8501:8501"` auf allen Interfaces. Der laufende Container hat `User=1000:1000`,
`/home/micha/.hermes → /opt/data`, `127.0.0.1:8501->8501`. **Ein Rebuild aus dem Repo ergibt nicht
das laufende System** (und würde `root` einführen).
*Beleg:* `docker inspect ARCHON-OS --format '{{.Config.User}} {{.Config.Cmd}}'` →
`1000:1000 [uvicorn main:app … --reload]`.

### 🟡 Härtung

**F7 — Abhängigkeiten ungepinnt, Download ohne Prüfsumme**
`requirements.txt` — 19 Einträge, **0** mit `==`, alle nur `>=` (z. B. `fastapi>=0.110.0`,
`httpx>=0.27.0`, `pyyaml>=6.0.0`). Kein Lockfile, kein `constraints.txt`, kein Hash-Pinning.
`Dockerfile:1` Basis `python:3.11-slim` ohne Digest; `Dockerfile:7-10` Docker-CLI per `curl … | tar -x`
**ohne** Checksummenprüfung; `apt-get install` ohne Versionspin. `tecnativa/docker-socket-proxy:latest`,
`n8nio/n8n:latest`, `anything-llm:latest` — unkontrollierte Major-Upgrades bei jedem `pull`.
*Beleg:* Dateien gelesen; `ls requirements*.txt constraints*.txt poetry.lock` → nur `requirements.txt`.
Die installierten Versionen im Container sind aktuell (`fastapi 0.162.0`, `starlette 1.10.0`,
`httpx 0.28.1`, `PyYAML 6.0.3`, `Pillow 13.0.0`, `pypdf 7.0.0`, `python-multipart 0.0.33`) — ein
CVE-Matching ist **nicht** erfolgt (§6). Keine Upgrades vorgenommen, nur Befund.

**F9 — Auth-Gate ist fail-open bei Importfehler**
`main.py:237-242`: `try: from backend.auth_service import auth_service … except Exception: return await
call_next(request)`. Ein kaputter `auth_service` (fehlendes Modul, Syntaxfehler nach halbem Deploy)
schaltet **jede** `/api/*`-Prüfung ab, während `/health` weiter 200 liefert. Widerspricht dem
fail-closed-Prinzip, das `_rbac.py` bereits umsetzt. *Beleg:* Code gelesen; Zustand nicht künstlich
herbeigeführt.

**F9b — `safe_path` ist fail-open bei Importfehler**
`main.py:344-357`: schlägt `from utils.path_jail import safe_path` fehl, wird eine Ersatzfunktion
definiert, die nur `realpath(abspath(expanduser()))` macht — **ohne** Jail-Prüfung. Jeder „gejailte"
Endpunkt (`/api/vault/file`, `/api/vault/edit`, `library/upload`, `_safe_config_target`) wäre dann für
`../../etc/passwd` offen. *Beleg:* Code gelesen.

**F10 — Kein CSRF-Token; Schutz hängt allein an `SameSite=Lax`**
`main.py:7750` setzt `archon_session` mit `httponly=True, samesite="lax"`, kein `secure=True`, kein
CSRF-Token. Für JSON-Bodies reicht Lax (ein Fremdformular kann kein `application/json` senden). Für
Routen mit **Query-Parametern** (`DELETE /api/vault?path=`, `PUT /api/.../{id}`) und GET-Routen mit
Nebenwirkung (`/api/proxy`, `/api/llm-providers/privacy-status`) ist der Schutz dünner. Zusätzlich
erlaubt CORS `allow_credentials=True` mit einer LAN-Regex (`main.py:105-122`).
*Beleg:* Cookiesetzung gelesen.

**F11 — 50 gemischte `api_route`-Deklarationen ohne Methodenverzweigung**
`main.py:9581-9624`: 45 Dekoratoren mit `methods=["GET","POST","OPTIONS","PUT","DELETE"]` auf **einem**
Handler, der stumpf an Hermes durchreicht; 5 weitere in `n8n_proxy`, `n8n_rest_proxy`,
`omniroute_proxy`, `${ns}-assets`, `api_rename_chat_session`. Ein Zaun über dem Handler würde auch
lesende Aufrufe sperren; ein fehlender Zaun öffnet die Schreibmethoden. Sauber ist Verzweigung pro
Methode — sie existiert im Bestand **nirgends** (0 Treffer für `request.method ==`).
*Beleg:* Zählung aus dem Audit-JSON (50 Einheiten auf 6 Handler; das Mandat nennt 48).

**F12 — Unvalidierte IDs in `os.path.join` (Admin-Routen)**
`archon/routers/hermes_profiles.py:126` (`p_base / profile_id / "profile.yaml"`),
`archon/routers/skills.py:378` (`MEMORY_DIR/hermes_skills/{skill_id}`). Kein `safe_path`. Begrenzt
durch Path-Parameter-Semantik (kein `/` im Segment) und `.md`/`.yaml`-Suffix; beide Routen gezaunt.
*Beleg:* Code gelesen; kein Request gesendet (schreibend).

**F13 — CRM-Avatar und Voice-Audio liefern Dateien ohne Jail**
`archon/routers/crm.py:117-128` (`contact_id`, `filename` direkt in `os.path.join`, dann
`FileResponse`), `archon/routers/voice.py:65-70` (`os.path.join("data","audio_cache", filename)` — bei
absolutem `filename` gewinnt der absolute Pfad). Kein `basename`, kein `safe_path`.
*Beleg:* statisch; Starlette löst `%2F` **nicht** in Pfadparameter auf — In-Process-Sonde liefert für
`..%2F..%2Fetc%2Fpasswd` und `%2E%2E%2F…` jeweils 404, für `x.mp3` 200. Derzeit nicht ausnutzbar, aber
ohne zweite Schranke: sobald jemand `{filename:path}` schreibt, ist die Lücke offen.

**F14 — Reverse-Proxy entfernt Clickjacking-Schutz und öffnet CORS**
`utils/reverse_proxy.py:98-101`: `X-Frame-Options: ALLOWALL`, `Access-Control-Allow-Origin: *`, CSP
wird verworfen; `_prepare_headers` reicht **alle** Client-Header inkl. `Cookie` an n8n/OmniRoute weiter.
*Beleg:* Code gelesen; `GET /omniroute-proxy/api/health` → 307 (Gate greift), also nur mit Session
nutzbar.

**F15 — Rate-Limit trifft die teuren Pfade nicht vollständig**
`utils/rate_limit.py:43-51`: strikt (20/min) nur `/api/sandbox`, `/api/v1/container/exec`,
`/api/hermes/update`, `/api/system/update`, `/api/proxy`, `/api/router/hedged`, `/api/auth`. Nicht
strikt: `/api/healing/attempt`, `/api/fleet/heal`, `/api/documents/parse`,
`/api/llm-providers/test-connection`, `/api/v1/library/upload` — alle unter dem Default 600/min und
alle schreibend oder teuer. Zusätzlich teilen sich hinter einem Reverse-Proxy alle Clients eine
Bucket-Kennung (`request.client.host` = Gateway-IP).
*Beleg:* Konfiguration gelesen; Default 600/20 aus `main.py:131-132`.

**F16 — `/api/debug-db` ohne Zaun**
`main.py:10969-10975` liefert DB-Pfad und Nachrichtenzahl, ohne Rollenbezug.
*Beleg:* `GET /api/debug-db` → **401** (Gate aktiv, Zaun fehlt).

**F17 — eSign-Webhook ohne Signaturprüfung**
`backend/operations_api.py:3149-3156` nimmt beliebige Payloads als „DocuSeal-Webhook" und ruft
`handle_webhook_event`. Jede eingeloggte Rolle kann damit Vertragsstatus setzen. Kein Zaun, keine
HMAC-Prüfung. *Beleg:* Code gelesen (Handler verarbeitet nur `payload`).

**F18 — Kleine Expositionen und Prüf-Lücken**
`anything-llm` auf `0.0.0.0:3001` (F21), `CRM` auf `0.0.0.0:3005` (Antwort 307), `socat` auf 8420/9120
(F22); zusätzlich antworten `0.0.0.0:8080` und `0.0.0.0:8644` (404) ohne weitere Prüfung.
n8n (`127.0.0.1:5678`, `N8N_SECURE_COOKIE=false`) und omniroute (`127.0.0.1:20128`) sind nur lokal
gebunden; ihre Anwendungs-Authentisierung wurde nicht getestet. `/_next/{path:path}` und
`/assets/{path:path}` (`main.py:10851, 10872`) liegen **außerhalb** des Gates (kein `/api/`-Präfix,
nicht in `_AUTH_PROTECTED_PREFIXES`) — nur GET/HEAD und fest auf omniroute/n8n gepinnt, deshalb
Härtung. *Beleg:* `ss -ltnp`, `curl -o /dev/null -w "%{http_code}"` gegen 3001/3005/8080/9120/8420.

**F27 — App-Container ohne Ressourcen-Limits**
`docker inspect ARCHON-OS` → `Memory=0`, `PidsLimit=<nil>`, `ReadonlyRootfs=false`, `CapDrop=[]`.
Der `deploy.resources`-Block (`docker-compose.yml:43-47`) wirkt außerhalb von Swarm nicht. Ein
fehlerhafter Agent-Lauf kann Host-RAM und PID-Tabelle des Hosts erschöpfen.
*Beleg:* `docker inspect ARCHON-OS --format '{{.HostConfig.Memory}} {{.HostConfig.PidsLimit}} {{.HostConfig.ReadonlyRootfs}}'`.

**F28 — Jail-Wurzeln zu weit gefasst**
`utils/path_jail.py:32-54` erlaubt `/opt/data`, `/app/data`, `/app/agent_workspace`, den Vault und
`~/.hermes`/`/root/.hermes`. `realpath` wird korrekt **vor** dem Vergleich gebildet (Symlinks dicht),
aber die Wurzelwahl macht aus dem Jail einen Hausflur: F24-Folgen, und `library/upload` darf
theoretisch überall dorthin schreiben. Härtung: pro Endpunkt eine enge Wurzel statt eines globalen
Satzes. *Beleg:* `allowed_roots()` ausgegeben (siehe F24).

### ⚪ Verdacht

- Ob der `/var/run/docker.sock`-Mount (C1) im Zusammenspiel mit F20/F19 zu Host-Root führt, ist
  plausibel, aber **nicht** belegt: ich habe keinen privilegierten Container erzeugt.
- F3 verspricht einen Rollen-Eskalationspfad über `data/.archon_service_token`. Den Token-Inhalt habe
  ich nicht gelesen; die Aussage, dass dieses Token `admin` vergibt, stammt aus `main.py:7638-7647`
  (Code) — nicht aus einem Test.
- `_archive_legacy/`, `archive/`, `frontend_recovered_*` und die `*.bak*`-Dateien im Wurzelverzeichnis
  wurden nicht einzeln bewertet.

---

## 4. Pfade, Dateien, Ausführung — was geprüft und sauber ist

Damit die Befundliste nicht falsch gelesen wird, hier die Stellen, die **halten**:

| Bereich | Stelle | Ergebnis |
|---|---|---|
| Jail-Kern | `utils/path_jail.py:96-123` | `realpath` **vor** dem Vergleich → Symlink-Escape, `..`, absolute Pfade abgefangen; `\x00` abgewiesen; Elternverzeichnis bei `allow_write` mitgeprüft |
| Upload (Library, Altpfad) | `main.py:2290-2305` | `basename` + `safe_path(..., extra_roots=[raw_dir])` — geschlossen (`f99e8c41`) |
| Vault-Löschen | `main.py:8727-8745` | Jail **plus** zusätzliche `startswith(vault_root)`-Verengung — geschlossen |
| Chat-Upload | `main.py:4133`, `main.py:10605` | `re.sub`-Whitelist bzw. `basename` + Zeitstempel — sauber |
| Studio-Hintergrund | `main.py:7938` | Endungs-Whitelist, generierter Name, 8-MB-Limit — sauber |
| Avatare | `archon/core/profiles.py:97-112` | `basename`, `[A-Za-z0-9_.-]+`, keine `.`-Präfixe — dicht |
| SQL | `backend/auth_service.py:326`, `backend/receipt_ocr_engine.py:305`, `backend/erp_manager.py:662`, `backend/operations_api.py:652/675/692/724`, `backend/audit_log.py:113` | f-Strings enthalten nur Spalten-/Tabellennamen aus Whitelists oder Platzhalterlisten; **Werte** immer als `?`-Parameter — keine Injektion gefunden |
| YAML | Repo-weit | kein `yaml.load` ohne `safe_load` in Anwendungscode |
| pickle | Repo-weit | kein `pickle.load` in Anwendungscode (nur `antigravity_complete_skills_package/`) |
| eval/exec | Repo-weit | kein `eval`/`exec` auf Nutzereingaben; einziger Treffer ist `node -e` mit festem base64-Payload (`backend/post_task_pipeline.py:520`) |
| `os.system` | Repo-weit | kommt in der Anwendung nicht vor |
| Archive | `backend/document_parser.py:63,133` | `zipfile` nur lesend, kein `extractall` mit Nutzerziel |
| Templates | `archon/routers/templates.py:303` | Rendering per `str.replace`, **kein** Jinja → keine SSTI |
| JEV-Fastpath | `main.py:9445` (`shell=True`) | Kommando stammt aus `FAST_PATH_REGISTRY` (`jev_router.py:21-50`), nicht aus der Eingabe — `shell=True` bleibt unnötig, ist aber nicht ausnutzbar |
| CORS | `main.py:105-122` | explizite Origin-Liste + LAN-Regex, keine Wildcard |
| Rate-Limit | `utils/rate_limit.py` | vorhanden und aktiv (Lücken: F15) |
| `_rbac` fail-closed | `archon/routers/_rbac.py:42-51` | ohne Injektion 503 statt Durchlass — bestätigt |

---

## 5. Seit dem letzten Review nachweislich geschlossen

| Maßnahme | Commit | Nachprüfung |
|---|---|---|
| Rollenzaun zentral über `_rbac.py`, fail-closed (123 Operationen) | `1424e3dc` | `_rbac.py:42-51` wirft 503 ohne Injektion; AST: exakt 123 Einheiten mit Zaun an erster Stelle |
| Upload-RCE (`basename`+`safe_path`), Vault-Jail auf Vault-Wurzel, `voice-relay` (`chat_id`) | `f99e8c41` | `main.py:2290-2305`, `main.py:8727-8745` gelesen; ohne Session 401 |
| Avatar-Upload-Route mit Rollenzaun (9 Tests) | `65a4a820` | Route gezaunt (AST) |
| Avatar-Schreibziel aus dem versionierten Baum | `482300c6` | `resolve_avatar_file` mit `basename`+Regex |
| „ausgeführt nur mit Body-Beleg", RAG-Key aus Env (fail-fast) | `48d9b7db` | Nutzungsstelle ohne Literal (Literale bleiben in `tools/`, F6) |
| Pfad-Jail als Modul mit Symlink-Auflösung | `d4df6bc5` | `utils/path_jail.py` vollständig gelesen, `realpath`-Reihenfolge korrekt |
| Rate-Limiting als Middleware (S8) | `8ecff145` | aktiv laut `main.py:127-134` |
| Docker-Zugriff über Socket-Proxy (`DOCKER_HOST`) | `9df30866` | `DOCKER_HOST=tcp://docker-socket-proxy:2375` im Container bestätigt; `_ALLOWED`-Allowlist vorhanden |
| Proxy-Methoden-ACL (DELETE/PUT/PATCH gesperrt) | `1a10d31b` | Proxy-Env `POST=1` nur für die freigegebenen Pfade; `RESTARTS=0` bestätigt |
| `restart` gesperrt, Restart über stop+start | `5a6c0d59` | `docker_client` nutzt stop+start; Ausnahme: F26 |
| Updater über eigenen Admin-Client (`DOCKER_ADMIN_HOST`), getrennte Allowlist | `ee82c6d`, `2d897605` | `_ADMIN_ALLOWED` (`utils/docker_client.py:102`) getrennt von `_ALLOWED` |

**Nicht** geschlossen (bewusst): Socket-Mount im App-Container (C1) — als Verstärker in F5/F8/F20
bewertet, nicht als neuer Befund.

---

## 6. Was ich **nicht** geprüft habe (Pflicht)

1. **Keine mutierenden Requests** gegen laufende Dienste: kein POST/PUT/DELETE auf F2, F3, F4, F5, F12,
   F13, F17, F19, F24, F25, F26. Diese Befunde stützen sich auf Code, Pfadauflösung im Container
   (F19), String-Bau (F2, F26) und Statuscodes (F1, F3-Gate, F23-Funktionsaufruf).
2. **Keine Authentifizierung als Nicht-Admin.** Ob ein `viewer`-Konto existiert und was es erreicht,
   wurde nicht getestet (kein Konto angelegt — das wäre eine Zustandsänderung). Die Rollen-Aussage ist
   strukturell (Gate prüft nur Session, kein Guard im Rumpf), nicht empirisch.
3. **Keine URL-Encoding-/Symlink-Versuche** gegen F12/F13 über HTTP (Login nötig). `%2e%2e`, `%2f`,
   Unicode-Normalisierung und Symlink-Ziele innerhalb des Jails nur per In-Process-Sonde für `%2F`.
4. **GET-Routen mit Nebenwirkung** (CSRF-relevant) nicht systematisch ausgewertet — die AST-Zählung
   klassifiziert nach HTTP-Methode.
5. **Keine Protokoll-/Header-Härtung**: kein Test von CSP/HSTS, kein TLS (läuft über HTTP), keine
   Session-Fixation/Timeout-Semantik (`max_age=30 Tage` nur gelesen).
6. **Keine CVE-/Scanner-Läufe** (trivy/grype/pip-audit) — hätte Images gepullt. Die `:latest`-Tags
   (F7) sind dadurch ungeprüft.
7. **Firewall/NAT**: ohne `sudo` nicht auslesbar, ob die `0.0.0.0`-Listener aus WAN erreichbar sind
   (`ufw status` verweigert). Der LAN-Fall für :8420 ist **belegt** (200), der WAN-Fall nicht.
8. **Frontend** (`static/`, `frontend/`, JS-Bundles): XSS, DOM-Sinks, `dangerouslySetInnerHTML`.
9. **Node-Dienste** (n8n-Auth-Patch, CRM auf 3005, paperclip-orchestrator): nur Ports und HTTP-Status,
   kein Code-Review, keine Anwendungs-Authentisierung getestet.
10. **Git-Historie** als Secret-Quelle: per Auftrag entschieden, nicht neu bewertet (§7).
11. **Zwei der 50 gemischten `api_route`-Fälle** (Differenz zu den im Mandat genannten 48) sind nicht
    einzeln zugeordnet.
12. **Kein Diff** gegen einen Vorgänger-Review mit derselben Zählregel (`TRIAGE_UNGUARDED_ROUTES.md`
    nutzt eine ältere, andere Messung).

---

## 7. Secrets

In diesem Dokument steht **kein** Schlüsselwert — auch nicht gekürzt. Nur Fundstellen:

* `tools/sync_cannabis_rag.py:8`, `tools/sync_cannabis_rag_parallel.py:10`,
  `tools/sync_remaining_600s.py:8`, `tools/sync_vault_all_parallel.py:9` — `API_KEY`-Literal, in `HEAD`.
* `main.py:611-614`, `archon/services/profiles_service.py:353,359` — Fallback-Literal für
  `OMNIROUTE_API_KEY`, in `HEAD`.
* `scripts/paperclip_hire_agent.cjs:7,52`, `backend/post_task_pipeline.py:490` — Postgres-URL mit
  Passwort bzw. `apiKey`-Literal, in `HEAD`.
* `docker-compose.yml:67`, `docker-compose.archon.yml` — n8n-JWT-Secret, `BETTER_AUTH_SECRET`,
  `INITIAL_PASSWORD` als Literale.
* `docs/SYSTEM_HANDBUCH.md:2706`, `docs/system/ESIGN_DOCUSEAL_GUIDE.md:73`,
  `docs/system/TELEGRAM_RECEIPT_OCR_GUIDE.md:60` — Token-Beispiele in Doku, in `HEAD`.
* `.archon_backup_20261105_1015/` — 189 getrackte Dateien mit Literalen.
* **Bekannt und entschieden, kein neuer Befund:** Alter RAG-Key in Git-Historie und Backup-Dateien.
  Zur Vollständigkeit der Fundstelle: er steht nicht nur in der Historie, sondern **im Arbeitsbaum
  getrackter Dateien** (die vier `tools/sync_*.py` oben, alle in `HEAD`). Die Entscheidung dazu bleibt
  unberührt — die Fundstelle ist damit aber nicht rein historisch.

**Trennung:** „in Git-Historie" = nicht mehr im Baum, nur über `git log -p` erreichbar.
„Im Arbeitsbaum" = heute auscheckbar, also auch in jedem Klon und jedem Deploy-Paket.

---

## 8. Reproduktion

```
.venv/bin/python scripts/audit_route_guards.py --root .          # Zahlenbild
.venv/bin/python scripts/audit_route_guards.py --root . --list   # offene mutierende Routen (Datei:Zeile)
.venv/bin/python scripts/audit_route_guards.py --root . --json /tmp/r.json

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/static/hermes-webui/api/status
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/api/sessions
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.0.230:8420/static/hermes-webui/api/status
docker exec ARCHON-OS    sh -c 'curl -o /dev/null -w "%{http_code}" http://docker-socket-proxy:2375/version'
docker exec anything-llm sh -c 'curl -o /dev/null -w "%{http_code}" http://docker-socket-proxy:2375/containers/json'
docker inspect ARCHON-OS --format '{{.Config.User}} {{.Config.Cmd}} {{.HostConfig.PidsLimit}} {{.HostConfig.Memory}}'
ss -lntp | grep -E ":8420|:9120|:3001|:3005|:8080"
```

Hilfsskripte dieses Reviews (Secret-Scan, SSRF-Sonde, Path-Parameter-Sonde, Jail-Sonde,
Injection-Beleg, unabhängige Gegen-Zählung) lagen unter
`~/.hermes/profiles/devops_cloud_sec_specialist/cache/scratch/` und sind nicht Teil des Repos.
Der Secret-Scan gibt ausschließlich `Datei:Zeile` aus, niemals Werte.

**Angelegte Dateien:** `scripts/audit_route_guards.py`, dieses Dokument. Sonst nichts.

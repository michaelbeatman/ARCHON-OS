# Refactor-Stand — Critical Hardening & Modularisierung

**Stand:** 2026-11-06 · **Branch:** `refactor/critical-hardening` · **Status:** live deployt, verifiziert

Dieses Dokument ist der Einstiegspunkt für eine neue Session. Es ersetzt die
Chat-Historie: wer das hier liest, kann nahtlos weiterarbeiten.

---

## 1. Ausgangslage und Ziel

Code-Review von `main.py` (16.254 Zeilen, 514 Routen) ergab: Monolith,
blockierende I/O in async-Handlern, offene Datei-Endpunkte, Klartext-Secrets.
Ziel: Sicherheit, Struktur und messbare Performance — ohne Funktionsänderung.

**Harte Randbedingung:** Routen-Parität. Nach jedem Schritt wurde per
AST-Vergleich gegen `main.py.pre-hardening.bak` geprüft:
514 Routen vorher = 514 nachher, 0 fehlend, 0 neu.

---

## 2. Aktueller Zustand (gemessen)

| Metrik | Start | Jetzt |
|---|---|---|
| `main.py` | 16.254 Z. | **12.184 Z.** |
| Router | 0 | **19 Module / 4.315 Z.** |
| Core-Module | 0 | **7 Module / 871 Z.** |
| Routen | 514 | **514** (312 main + 202 Router) |
| Tests | 85 | **112 passed**, 4 skipped |
| `import main` | 3,52 s | **1,77 s** |
| Benchmark (128 GET-Routen) | 27,0 s | **22,6 s** (Median 73 ms) |

---

## 3. Struktur (neu)

```
archon/
  core/
    runtime.py         Pfade, Ticker, SSE, JSON-Helfer, APP_ROOT, logger
    profiles.py        Hermes-Profil-Registry, 300s-Cache, Rolling-Backup
    mission_control.py MC-Store, atomar (Temp+fsync+replace), Thread-/Async-Lock
    state_db.py        ClosingConnection, STATE_DB_PATH, _get_state_db
    cache.py           ttl_cache (thread-sicher), invalidate/clear_all
    permissions.py     Permission-Gates; Decision-Fabrik spät gebunden
  routers/             system, skills, hermes_profiles, llm_providers, templates,
                       boardroom, governance, plugins, contracts, crm, erp,
                       corporate, security, execution, memory, routergate, voice,
                       swarm, llm_providers
utils/
  path_jail.py         safe_path(): Traversal-/Symlink-Schutz
  docker_client.py     DockerClient: Endpunkt-Allowlist, Namens-Validierung
  reverse_proxy.py     ein ReverseProxy statt zwei Kopien
  secret_files.py      Secret-Audit, 600-Härtung, YAML-Maskierung
```

**Wichtig:** Das Paket heißt `archon`, **nicht** `app` — `app.py` existiert im
Repo (Streamlit) und würde das Paket verschatten.

---

## 4. Was in dieser Session gemacht wurde

### Sicherheit
1. **Pfad-Jail** (`utils/path_jail.py`) auf allen Datei-Endpunkten:
   `/api/vault/*`, `/api/v1/brain/vault-file`, `/api/hermes/{raw_,}config`.
2. **Docker-Client** mit Allowlist (7 Operationen) + Namens-Validierung.
3. **Auth-Gate erweitert**: `/n8n-proxy`, `/omniroute-proxy`, `/rest`, `/hud`,
   `/mobile`, `/v2` waren trotz aktivem Auth komplett offen.
4. **Secrets**: 117 Dateien waren 755/664 (alle Profil-`.env` mit API-Keys,
   `.env.backup_pre_v02`). Startup-Hook `_harden_secret_permissions` prüft und
   korrigiert auf 600.
5. **Token-Leak**: `/api/guardian/plugins/evey-telegram-ux/config` gab den
   Bot-Token im Klartext zurück → jetzt maskiert.
6. **config.yaml-Leak**: `/api/hermes/raw_config` lieferte
   `api_key`/`openai_api_key`/`openrouter_api_key`/`bot_token` im Klartext →
   `mask_yaml_secrets()`, und beim Speichern `restore_masked_values()`.

### Architektur
- Ein **Lifespan** statt 5× deprecated `@app.on_event`.
- **Watchdog startet nicht mehr beim Import** (lief in jedem Test-/CLI-Prozess).
- 514 Routen auf 19 Router verteilt; Core-Module zyklusfrei.
- Proxy-Duplikat (~200 Z.) durch `utils/reverse_proxy.py` ersetzt.

### Performance (die eigentlichen Gewinne)
| Ursache | Fix | Wirkung |
|---|---|---|
| Provider-Katalog bei jedem Request geparst | mtime-Cache in `api_provider` | 2.998 → 50 ms |
| `importlib.reload()` in 9 Request-Handlern | entfernt, TTL-Caches | 1.541 → 6 ms |
| Polling rechnete jedes Mal neu | `ttl_cache` auf 6 Endpunkten | 2.368 → 7 ms |
| galaxy-data 3,84 MB | `vault_limit` (Default 600) | 162 → 53 KB |
| Hermes-Update-Cache 60 s | 900 s | 6.252 → 8 ms |

Dashboard-Pfad (5 Endpunkte): **~1.750 ms → ~250 ms**.

---

## 5. Fallstricke (bitte lesen, bevor du etwas verschiebst)

1. **Namensbindung prüfen.** Beim Core-Split blieb `_SSE_SUBSCRIBERS` aus dem
   Import — der SSE-Stream warf NameError, Live-Updates tot. Es gibt jetzt
   `test_core_names_are_bound_in_main`.
2. **Keine Kaskaden-Extraktion.** Ein Versuch, `/api/system/*` automatisch mit
   allen unbenutzten Helfern zu verschieben, riss die Auth-Middleware mit
   (Routen fielen von 378 auf 274). Regel: nur explizit benannte Helfer.
3. **Pydantic-Modelle** werden von FastAPI zur Dekorationszeit aufgelöst —
   fehlen sie im Router-Modul, startet der Router nicht (still, nur Warnung).
   `repair()`-Muster: fehlende Klassen aus `main.py` nachziehen.
4. **Container** läuft aus `docker-compose.dev.yml` (Projekt `archon`, `--reload`),
   **nicht** aus `docker-compose.yml`. Compose-Änderungen dort greifen nicht.
5. **`Depends()` gibt es nicht** — Auth läuft über Middleware + manuelle Checks.
6. Profil-`.env` liegen unter `~/.hermes/profiles/*/` und sind gemountet; drei
   weitere Container (`paperclip`, `hermes-webui`, `hermes-dashboard`) mounten
   dasselbe Verzeichnis und laufen als root → 600 ist unkritisch.

---

## 6. Verifikations-Kommandos

```bash
cd /mnt/raid/AgenticOS-2026

# Tests
.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider

# Routen-Parität gegen das Original
.venv/bin/python - <<'EOF'
import ast, glob
ATTR={"get","post","put","delete","patch","api_route","websocket"}
def r(p):
    t=ast.parse(open(p).read()); out=[]
    for n in ast.walk(t):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ATTR:
                    if d.args and isinstance(d.args[0],ast.Constant): out.append(d.args[0].value)
    return out
o=set(r("main.py.pre-hardening.bak")); n=set(r("main.py"))
for f in glob.glob("archon/routers/*.py"): n|=set(r(f))
print("Original",len(o),"jetzt",len(n),"fehlend",len(o-n),"neu",len(n-o))
EOF

# Live-Benchmark (im Container)
docker exec ARCHON-OS python /app/scripts/bench_routes.py

# Deploy
docker compose -f docker-compose.dev.yml -p archon up -d --force-recreate archon
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/health
```

---

## 7. Offene Punkte (bewusst nicht gemacht)

| Punkt | Umfang | Warum offen |
|---|---|---|
| Mission-Control-Routen → Router | ~300 Z. | Ist ein **Dashboard**, kein Orchestrator; Orchestrierung steckt in `_execute_mission_control_task` / `_fan_in_maybe_start_synthesis`. Braucht eigenes `archon/core/orchestration.py` + Tests. |
| `/api/status` (534 ms) | — | Proxy zum externen Hermes-Gateway, nicht unser Code. |
| 163× `except Exception: pass` | — | Fehler verschwinden still; schrittweise durch Logging ersetzen. |
| Hardcodierte Pfade (`/opt/data` …) | 300+ | Portabilität/Multi-Tenant; braucht Config-Schicht. |
| Type Hints / mypy | — | ~30 % Abdeckung. |

---

## 8. Git-Historie dieser Session

```
ea3e138f security: config.yaml-Secrets im Live-Editor maskiert
77c50936 security: Secrets gehaertet (117 Dateien) + Token-Leak geschlossen
274db96d Modularisierung Stufe 5: /api/system/* und Skills ausgelagert
7fecf187 Performance: Hermes-Update-Cache 60s -> 900s + Benchmark korrigiert
dd75c213 Modularisierung Stufe 4 + galaxy-Payload
c7bdf5c4 fix(sse): _SSE_SUBSCRIBERS nach Core-Split wieder in main gebunden
71ec3d5a scripts/bench_routes.py: sys.path-Fix
42baa353 Performance: importlib.reload aus Update-Endpunkten entfernt
4726e324 Performance: TTL-Cache fuer teure Lese-Endpunkte
90c9b977 Performance: Provider-Caches (2,7s -> 50ms)
32752cc1 Performance: blockierendes I/O aus async-Handlern entfernt
7139c3fb Modularisierung Stufe 3: state_db + llm-providers
53e7b6dd Modularisierung Stufe 2: Core-Module profiles/mission_control
d4df6bc5 Hardening + Modularisierung: Pfad-Jail, Docker-Client, Lifespan
```

Rollback auf den Ausgangszustand: `git checkout main` (Backup liegt als
`main.py.pre-hardening.bak` im Repo).
# Audit-Status — Archon OS

Stand: **2026-11-07 (Abendmessung)** · Branch `refactor/critical-hardening` @ `314ea093`
(`git rev-list --count main..HEAD` → **55**; Vorgängerstand dieses Dokuments war 2026-11-06/`f22402fc`)
Bezug: externes Code-Audit (God-File-Analyse, ~40 Punkte, A/B/P/S)

Dieses Dokument ist der Abarbeitungsstand. Jede Zeile nennt den **Messbefehl**,
damit der Status reproduzierbar ist und nicht aus dem Gedächtnis zitiert wird.
Alle Zahlen dieses Stands sind am 2026-11-07 abends **selbst nachgemessen**, keine
aus `docs/HANDOVER_2026-11-07_abend.md` übernommen.

Legende: ✅ erledigt und belegt · 🟡 teilweise · 🔴 offen und gemessen · ⚪ ungeprüft

---

## Architektur

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| A1 | Monolith 16.254 Zeilen | 🟡 | `wc -l main.py` → **11.291** (−30 %), weiterhin Monolith |
| A2 | Keine Modulstruktur | ✅ | `ls archon/core/*.py \| wc -l` → **8**, `ls archon/routers/*.py \| wc -l` → **20**, dazu `backend/`, `utils/` |
| A3 | God Object | 🟡 | Routing + Kernlogik getrennt; Middleware/Lifespan/Config in `main.py` |
| A4 | Enge Kopplung | 🟡 | Orchestrierung + Router entkoppelt, `main.py` importiert weiter 50+ Module |
| A5 | 40+ Modul-Globals | 🟡 | `grep -cE "^[A-Z_][A-Z0-9_]* = " main.py` → **25** (von 52). **Etappe 1–4 am 2026-11-07:** 5 Konstanten → `archon/core/constants.py`, 18 Pfad-Konstanten → `archon/core/paths.py`, 2 wirkungslose Doppelzuweisungen + 2 tote TTL-Konstanten entfernt. Rest: 24 mutable Globals. Inventur: `docs/A5_INVENTUR.md` |
| A6 | Sync-I/O in async | 🟡 | `grep -c "asyncio.to_thread" main.py` → 15 |
| A7 | Kein DI / `Depends()` | 🟡 | `grep -c "Depends(" main.py` → **0**, **1** × `Depends()` in `archon/routers/system.py:123` (Pilot, 2026-11-07). Die DI der übrigen 6 Router läuft über `configure()`, nicht FastAPI-DI. Bewertung und kleinster nächster Schritt: `docs/A5_INVENTUR.md` §3 |
| A8 | Config verstreut | 🔴 | unverändert, 15+ Dateien |

## Logikfehler

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| B1 | Race Condition MC-Lock | ✅ | **abgeschlossen 2026-11-07**: alle vier Schreiber nutzen `update_mc` + Delta-Merge, ohne stillen Fallback (`RuntimeError`). Belege siehe Abschnitt „B1" unten |
| B2 | Doppelte Proxy-Implementierungen | ✅ | `utils/reverse_proxy.py`, eine Klasse für alle Ziele |
| B3 | Docker-Socket ohne Schutz | 🟡 | `main.py` spricht den Socket **nicht mehr direkt** an — `docker_socket_request` ist eine Deprecated-Fassade auf `utils/docker_client.py` (Allowlist). **Rest offen:** `backend/hermes_updater.py:58` (`DockerSocketClient`, roher `socket.socket(AF_UNIX)`, im Live-Pfad von `get_installed_hermes_info`/`recreate_container_with_new_image`) umgeht die Allowlist. Belege unten |
| B4 | Path Traversal | ✅ | `utils/path_jail.py`; `grep -c "safe_path" main.py` → **12** Vorkommen (davon 6 Aufrufe) |
| B5 | SQL-Injection | 🟡 | **geprüft, kein akuter Befund**: `grep -rn 'execute(f\"' --include=*.py main.py archon backend utils` → **10** Stellen, alle mit Platzhalter-/Spaltenlisten aus festen Strings. **Ein latenter Härtungspunkt:** `local_memory_bridge.py:454` `evict_stale_memories(table=…)` interpoliert `{table}` ungeprüft (Z. 459 und 471). Details unten |
| B6 | Stille Exceptions | ✅ | `grep -rn "except.*:.*pass" …` → **0** projektweit; `grep -rn "except:" main.py archon backend utils \| wc -l` → 2 nackte `except:` verbleiben |
| B7 | Cache-Invalidierung | 🟡 | TTL-Caches eingeführt, keine einheitliche Strategie |
| B8 | Blockierendes httpx in async | ✅ | **geprüft, unauffällig**: genau **ein** blockierendes `httpx.Client` (`main.py:8942`) — in `def send_prompt_to_agent`, aufgerufen aus dem **sync** `def`-Handler `exec_container_command_api` (Threadpool, kein Event-Loop-Risiko). Alle `async def`-Pfade nutzen `httpx.AsyncClient`. Details unten |
| B9 | 50+ doppelte `api_route` | 🔴 | `grep -c "api_route(" main.py` → **50** |
| B10 | Hardcodierte Pfade | 🟡 | Audit nennt 300+; gemessen in `main.py`(75)+`archon`(20)+`backend`(41)+`utils`(9) = **145** × `/opt/data`; mit `scripts`(42)+`tests`(8) = **195** (`grep -rn "/opt/data" --include=*.py … \| wc -l`) |

## Security

| # | Punkt | Status | Beleg / Messung |
|---|---|---|---|
| S1 | Docker-Socket | 🟡 | siehe B3 — Hauptpfad abgesichert, `hermes_updater.DockerSocketClient` offen |
| S2 | Path Traversal | ✅ | Path-Jail aktiv, 403 außerhalb der Wurzeln |
| S3 | Keys in Env/Logs | 🟡 | 117 Dateien auf 600, Maskierung im Live-Editor; kein Secret-Manager |
| S4 | Schwache Admin-Auth | 🟡 | Rollenprüfung vorhanden (`main.py:7376`, `/api/auth/toggle` prüft `role == "admin"`), aber kein MFA/2FA und keine systematische Prüfung aller Admin-Endpunkte |
| S5 | CORS mit `*` | ✅ | explizite Origin-Liste + LAN-Regex statt Wildcard |
| S6 | Sandbox-Escape | ✅ | **geschlossen 2026-11-07**: alter Pfad **501**, neuer Pfad isoliert (`docker_micro_container`, Netzwerk aus, 512 MB, OOM-Kill, Secret-Pfade unerreichbar). Restrisiko benannt. Details unten |
| S7 | YAML-Deserialisierung | ✅ | **geprüft**: `grep -rn "safe_load" --include=*.py main.py archon backend utils \| wc -l` → **22** (**74** projektweit), `grep -rn "yaml.load(" … \| wc -l` → **0** echte unsichere Aufrufe (die 4 Treffer projektweit sind Empfehlungstexte in `antigravity_complete_skills_package/…`) |
| S8 | Kein Rate-Limiting | ✅ | **siehe unten — behoben am 2026-11-06** |
| S9 | Telegram-Token im Klartext | 🟡 | Rechte gehärtet, Klartext in `.env` bleibt |
| S10 | SSRF im Proxy | ✅ | **siehe unten — behoben am 2026-11-06** |

## Performance

| # | Punkt | Status |
|---|---|---|
| P1 | Kein DB-Pooling | 🔴 |
| P2 | Synchrone Docker-Calls | 🔴 |
| P3 | N+1-Muster | 🔴 |
| P4 | Kein Request-Batching | 🔴 |
| P5 | Redundante Vault-Reads | 🟡 (TTL-Cache) |
| P6 | Modell-Re-Instanziierung | 🟡 |
| P7 | Kein Streaming | 🔴 |
| P8 | Cache-Keys ohne ETag | 🔴 |

Gemessener Bezugspunkt für P1–P8: `scripts/bench_routes.py`, 128 Routen, Median 73 ms warm
(Stand 2026-11-06, **nicht** neu gemessen — Bench bewusst nicht in dieser Doku-Runde gefahren).

---

## Kennzahlen (Stand 2026-11-07 abends, alle selbst gemessen)

| Größe | Wert | Messbefehl |
|---|---|---|
| `main.py` | **11.252 Zeilen** | `wc -l main.py` |
| Modul-Globals | **25** | `grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py` |
| `Depends()` | **1** (`archon/routers/system.py:123`), in `main.py` 0 | `grep -rn "Depends(" --include=*.py archon \| wc -l` |
| `archon/core/constants.py` | **83 Zeilen**, 5 Konstanten | `wc -l archon/core/constants.py` |
| `archon/core/paths.py` | **68 Zeilen**, 18 Pfad-Konstanten | `wc -l archon/core/paths.py` |
| Decorator-Routen | **308** | `grep -cE '@app\.(get\|post\|put\|patch\|delete\|websocket\|api_route)\(' main.py` |
| Live-Pfade / Operationen | **585 / 861** | `scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json` → Exit 0 |
| Router-Dateien | **20**, davon **6** mit `configure(**deps)` | `ls archon/routers/*.py \| wc -l`; `grep -ln "def configure(" archon/routers/*.py` |
| Tests | **243 passed, 8 skipped** (10,77 s) | `.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider` |
| Router-Namen-Scan | **Exit 0** | `scripts/check_router_names.py; echo "exit=$?"` |
| Tracebacks (5 min) | **0** | `docker logs --since 5m ARCHON-OS 2>&1 \| grep -c Traceback` |

Vorgängerstand dieses Dokuments nannte `main.py` = 11.321 und B10 = 169 — beide Zahlen waren
am 2026-11-06 richtig und sind durch die Extraktion bzw. eine andere Zählgrenze überholt.

---

## B1 — Race Condition im Mission-Control-Store (abgeschlossen 2026-11-07)

> **Nachtrag 2026-11-07 (Messung, keine Abschrift).** Der unten beschriebene Zwischenstand
> („Lock-Duplikat weg, atomare RVW-API, `capture` + `move` migriert, Orchestrierung lädt
> noch getrennt") ist **überholt**. Der vierte Schreiber ist migriert, der stille Fallback
> ist entfernt. Messung:
>
> ```bash
> # 1) save_mc( in orchestration.py — nur noch ein Docstring-Treffer, kein Aufruf
> .venv/bin/python - <<'PY'   # Scan: Treffer mit Funktionsnamen
> import re
> src = open('archon/core/orchestration.py').read().split('\n')
> func = None
> for i, l in enumerate(src, 1):
>     m = re.match(r'^(async )?def (\w+)', l)
>     if m: func = m.group(2)
>     if 'save_mc(' in l and not l.strip().startswith('#'):
>         print(f"Z.{i:5d} func={func:40s} {l.strip()}")
> PY
> # → Z.   56 func=_merge_task_delta   gehalten. Ein komplettes `save_mc(data)` … (Docstring)
> #   kein einziger programmatischer save_mc-Aufruf mehr
>
> # 2) update_mc in allen vier Schreibern + RuntimeError statt Fallback
> grep -rn "update_mc" main.py archon/core/orchestration.py
> #   orchestration.py: 84 (_execute_mission_control_task), 402 (_trigger_sandy_staffing_nomination),
> #                     555 (_finalize_synthesis_after_approval), 780 (_run_synthesis_cascade)
> #                     je Parameter; 128/533/640/1060/1109 Delta-Merge;
> #                     131/536/580/644/1063/1112 raise RuntimeError, wenn update_mc fehlt
> #   main.py: 10026, 10060, 10076, 10114  update_mc=update_mission_control_data (4 Wrapper)
>
> # 3) Historie
> git log --oneline -5 -- archon/core/mission_control.py archon/core/orchestration.py
> #   df1e560a refactor(orchestration): B1/4 - _trigger_sandy_staffing_nomination atomic delta pattern
> #   befb3577 … _trigger_sandy_staffing_nomination atomar (B1/4)
> #   4828ac9b … Stale-Snapshot-Overwrite in _execute_mission_control_task (B1, Teil 3)
> #   372eb540 fix(core): Lost Updates im Mission-Control-Store beheben (B1)
> #   a4267fa2 refactor(core): divergierende Helfer-Kopien in runtime.py entfernt
>
> .venv/bin/python -m pytest tests/test_mission_control_concurrency.py -q   # 5 passed (Regressionsschutz)
> .venv/bin/python -m pytest tests/test_mission_control_move.py -q          # 6 passed (Regressionsschutz)
> ```
>
> **Bewertung:** Alle vier Langläufer committen ein **Delta** über `update_mission_control_data`
> unter einem `RLock`, ohne `await`-Fenster mit Snapshot. Fehlt `update_mc`, wird laut
> gescheitert (`RuntimeError`) statt still auf das racy Muster zurückzufallen — genau die
> Hausregel „injizieren oder laut scheitern". Status daher **✅**.

### Zwischenstand 2026-11-06 (Historie, überholt)

**Befund, gemessen.** Zwei unabhängige Defekte:

1. **Zwei Locks auf ein Ziel.** `_MC_DATA_LOCK` (threading) schützte
   `_save_mission_control_data`, `_MC_ASYNC_LOCK` (asyncio) schützte den
   Direktschreiber in `_fan_in_maybe_start_synthesis`. Zwei Locks auf dieselbe
   Datei serialisieren **nicht** gegeneinander.
2. **Ungeschützte Lese-Ändere-Schreibe-Kette.** `_load` … `_save` hielt keinen
   Lock über die Sequenz. Gegenprobe mit 20 Threads × 5 Inkrementen:

   ```
   erwartet:                                    100
   altes Muster (load/save getrennt):             5  -> LOST UPDATES
   neues Muster (update_mission_control_data):  100  -> verlustfrei
   ```

   95 von 100 Änderungen gingen verloren. Das war kein theoretisches Risiko.

**Fix (06.11.).**

* `_MC_DATA_LOCK` ist jetzt ein `threading.RLock` — verschachtelte Aufrufe
  blockieren sich nicht mehr selbst.
* `_write_mc_atomic` nimmt den Lock **selbst**. Die alte Zusicherung „nur mit
  gehaltenem Lock aufrufen" ist damit nicht mehr umgehbar.
* Neue API `update_mission_control_data(mutator)`: lädt, ändert und schreibt
  unter **einem** Lock — der einzige Weg, der Lost Updates ausschließt.
  Aus async-Handlern über `asyncio.to_thread` (enthält `fsync`).
* `_save_mission_control_data` loggt Fehler jetzt mit `exc_info` statt sie mit
  `print` zu verschlucken.
* `capture_mission_control_task` nutzt die neue API (atomar + im Thread-Pool).

**Damals noch offen.** Die Orchestrierung (`_execute_mission_control_task`,
`_trigger_sandy_staffing_nomination`, `_run_synthesis_cascade`) lud und
speicherte getrennt — vier solcher Paare (u. a. `orchestration.py:84/109`,
`357/425`, `687/837`). **Diese Lücke ist am 07.11. geschlossen** (siehe Nachtrag oben).

**Was am Move-Handler geändert wurde.** Der Handler schrieb früher am Ende und
reichte sein `data`-Dict in `finalize_approval(daten=data)` weiter, damit ein
späterer `_save` die Finalisierung nicht überschreibt — ein Workaround für
genau dieses Problem. Jetzt gilt: Phase 1 (Laden, Ändern, Schreiben) atomar im
Thread-Pool, Phase 2 (Synthese-Finalisierung, `execute`, `fan_in`) danach und
**ohne** Lock. Der `daten`-Workaround entfällt, weil vor den `await`-Aufrufen
geschrieben wird. Tests: `tests/test_mission_control_move.py` (6 Tests).

---

## S6 — Sandbox-Escape (geschlossen 2026-11-07)

**Befund (06.11.).** `api_run_python_sandbox` führte fremden Code mit dem
**Host-Python** aus (`subprocess.run([sys.executable, …])`) — ohne RAM-Limit, ohne
Netzwerksperre, mit Zugriff auf das Container-Dateisystem. Rate-Limiting entschärfte die
Ausnutzbarkeit, nicht das Prinzip.

**Fix.** Alter Handler als Notbremse **501**, Ausführung ausschließlich über den isolierten
Mikro-Container-Pfad; Temp-Verzeichnis aus dem von `--reload` überwachten `/app` heraus.

**Messung (alle Befehle selbst gefahren, 07.11. abends):**

```bash
# 1) Temp-Verzeichnis außerhalb /app
grep -n "SANDBOX_TEMP_DIR" backend/ephemeral_sandbox.py
#   21: SANDBOX_TEMP_DIR = "/opt/data/archon_sandbox_runs"     (/opt/data = Host ~/.hermes)

# 2) Der alte Handler existiert, führt aber nicht mehr aus
grep -rn "api_run_python_sandbox" --include=*.py .
#   ./main.py:8372     (Definition)
#   ./tests/test_s6_sandbox_notbremse.py:34,38   (Regressionsschutz auf den AST)
#   ./archon_backup_…/main.py:10341              (Altstand im Backup, nicht importiert)

# 3) Alter Pfad live → 501
T=$(cat data/.archon_service_token)
curl -s -w "\nHTTP=%{http_code}\n" -H "X-Archon-Service-Token: $T" \
  -H "Content-Type: application/json" -X POST http://127.0.0.1:8501/api/sandbox \
  -d '{"code_content":"print(1)"}'
#   {"detail":"Sandbox deaktiviert (S6-Hardening). Nutze POST /api/sandbox/execute …"}  HTTP=501

# 4) Neuer Pfad live → isoliert, Trivialfall
curl -s -H "X-Archon-Service-Token: $T" -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8501/api/sandbox/execute \
  -d '{"code":"print(2+2)","language":"python"}'
#   engine=docker_micro_container, exit_code=0, stdout="4\n", memory_limit_mb=512,
#   network_enabled=false, limits_enforced=true, destroyed=true
```

**Isolation live nachgewiesen** (Docker-Socket im Container vorhanden:
`docker exec ARCHON-OS sh -c 'docker info >/dev/null 2>&1; echo $?'` → **0**):

| Probe | Ergebnis | Rohwert |
|---|---|---|
| Netzwerk | blockiert | `URLError [Errno 101] Network unreachable` |
| RAM 1 GB bei Limit 512 MB | OOM-Kill | `status=failed`, `exit_code=137` |
| Secret-Pfade | unerreichbar | `/app/data/.archon_service_token` → `False`, `/opt/data/…` → `False` |
| Arbeitsverzeichnis | isoliert | `cwd /sandbox` |
| Container-Leichen | keine | `docker ps -a --filter ancestor=python:3.11-alpine \| wc -l` → **0** |

Gefahren gegen Image **`af26a3ee66e2`** (`docker inspect ARCHON-OS --format '{{.Image}}'`,
identisch mit `archon-os-dev:latest`, gebaut 2026-11-07T09:23:21+01:00) — dieselbe Image-ID
wie am Vormittag, also gelten die Vormittagsproben **und** diese Messung für denselben Stand.

**Restrisiko (offen benannt, deshalb kein pauschales „zu"):**
1. `backend/ephemeral_sandbox.py` fällt auf **Host-Python** zurück
   (`subprocess.run([sys.executable, …])`), wenn `docker info` im Container scheitert.
   Heute: `docker_info_exit=0`, also greift der Fallback nicht — er ist aber ungeprüft und
   würde `memory_limit_mb`/`network_enabled` in der Antwort zur Kosmetik machen.
2. Nach jedem **Recreate** sind die fünf Proben erneut zu fahren (`--reload` deckt nur
   Python-Code ab, nicht den Image-Inhalt).

---

## B3 / S1 — Docker-Socket (teilweise geschlossen, Rest benannt)

**Messung.**

```bash
grep -rn "socket.socket\|docker.sock\|HTTPTransport(uds" --include=*.py main.py archon backend utils
```

| Treffer | Einordnung |
|---|---|
| `main.py:8518` `docker_socket_request` | **abgesichert**: Deprecated-Fassade, delegiert an `utils.docker_client.docker_client` (Allowlist + Namensvalidierung) |
| `main.py:928` (Docstring), `936` (Log-Text), `2507/2513/8454/8458/…` | Aufrufe derselben Fassade — **kein** roher Socket |
| `utils/docker_client.py:79,117,130` | **Guard selbst** (`socket.AF_UNIX` hinter Allowlist) |
| `archon/routers/governance.py:44` | Fassade auf `_docker_client` — abgesichert |
| `archon/routers/system.py:81,130`, `backend/post_task_pipeline.py:522,526` | `http://docker-socket-proxy:2375` per httpx (Netzwerk-Transport, kein Unix-Socket) |
| **`backend/hermes_updater.py:58`** | **offen**: `DockerSocketClient` mit rohem `socket.socket(AF_UNIX)` + `http.client`-Wrapper, **ohne** Allowlist, **ohne** Namensvalidierung; im Live-Pfad von `get_installed_hermes_info()` (Z. 107) und `recreate_container_with_new_image()` (Z. 323) |
| `backend/privacy_router.py:103,152` | **andere Risikoklasse**: roher TCP-Connect als Latenzprobe gegen Provider-URLs, kein Docker-Socket |

**Bewertung 🟡.** Der Hauptpfad (`/api/services`, `/api/v1/container/*`, Logs, Stats, Exec)
läuft über die Allowlist — die im Dokument vom 06.11. genannten „direkten Socket-Connects in
`main.py` (920, 1021, 1032)" existieren **nicht mehr**. Offen bleibt ein **zweiter,
unbewachter Docker-Transport** in `hermes_updater.py`: er umgeht die Allowlist vollständig.
**Rest (Härtungspunkt):** `DockerSocketClient` auf `utils.docker_client` umstellen oder
mindestens Endpunkt-Regexe + Containernamen-Validierung ergänzen.

---

## B5 — SQL-Injection (geprüft, ein latenter Härtungspunkt)

```bash
grep -rn 'execute(f"' --include=*.py main.py archon backend utils     # → 10 Stellen
```

Alle 10 sind **nicht** nutzerdaten-getrieben:

| Datei:Zeile | Interpoliert | Herkunft |
|---|---|---|
| `backend/receipt_ocr_engine.py:305` | `{set_clause}` | aus festen Spaltennamen gebaut |
| `backend/audit_log.py:113` | `{col_names}`, `{placeholders}` | feste Spaltenliste + `?`-Platzhalter |
| `backend/auth_service.py:326` | `{', '.join(updates)}` | feste Feldliste `col = ?` |
| `backend/operations_api.py:646,669,686,718` | `{placeholders}` | `','.join(['?']*len(ids))` |
| `backend/erp_manager.py:662,1053,1160` | `{where_sql}` | `" AND ".join(clauses)` aus **festen** Clause-Strings, Werte über `?` |

**Der eine latente Punkt (selbst geprüft, Zeile nicht aus dem Handover übernommen):**

```bash
grep -rn "evict_stale_memories" --include=*.py .
#   ./local_memory_bridge.py:454:    def evict_stale_memories(self, threshold=0.1, table="conversations", dry_run=False)
#   ./main.py:7831, 8023, 8024       Aufrufer übergeben feste Namen ("learnings"/"conversations")
```

`local_memory_bridge.py` liegt im **Repo-Root**, nicht unter `backend/` — der Pfad ist im
Handover richtig, in älteren Notizen aber fälschlich als `backend/local_memory_bridge.py`
geführt. Bei `local_memory_bridge.py:459`
(`f"SELECT id, importance, last_accessed, {time_col} FROM {table}"`) und `:471`
(`f"DELETE FROM {table} WHERE id IN (…)`) wird `{table}` **ungeprüft** ins SQL gesetzt.
Heutige Aufrufer übergeben ausschließlich Literale, also **kein akuter Befund** — aber die
Signatur ist offen für Werte von außen. **Härtung:** `table` gegen ein `frozenset`
(`{"conversations","learnings"}`) validieren, sonst `ValueError`.

Status daher 🟡: geprüft, eingeordnet, kein akutes Risiko, ein benannter Härtungspunkt offen.

---

## S7 — YAML-Deserialisierung (geprüft, unauffällig)

```bash
grep -rn "safe_load" --include=*.py main.py archon backend utils | wc -l        # → 22
grep -rn "safe_load" --include=*.py . --exclude-dir=.venv --exclude-dir=.git | wc -l   # → 74
grep -rn "yaml.load(" --include=*.py main.py archon backend utils | wc -l       # → 0
grep -rn "yaml.load(" --include=*.py . --exclude-dir=.venv --exclude-dir=.git   # → 4 Treffer
```

Die 4 projektweiten Treffer sind **Empfehlungstexte**, keine Aufrufe:
`antigravity_complete_skills_package/config/skills/security-pen-testing/scripts/vulnerability_scanner.py:217,406`,
`…/dependency_auditor.py:132`, `…/skill_security_auditor.py:378` — alle in Strings
(`"recommendation"`, `"fix"`, `"description"`). **Kein `yaml.load` ohne SafeLoader im
ausgeführten Code.** Status ⚪ → ✅.

---

## B8 — Blockierendes httpx in async (geprüft, unauffällig)

```bash
grep -rn "httpx.Client\|client\.get\|client\.post" --include=*.py main.py archon backend utils
grep -rn "httpx\.Client\|httpx\.AsyncClient" --include=*.py main.py archon backend utils
```

Jeder Treffer gegen seinen `def`/`async def`-Kontext gehalten:

| Stelle | umschließende Funktion | Bewertung |
|---|---|---|
| `main.py:5036/5037` | `async def api_tool_image_generate` | `AsyncClient` + `await` → korrekt |
| **`main.py:8942/8943`** | **`def send_prompt_to_agent`** (sync), aufgerufen aus `def exec_container_command_api` (Z. 8988, **sync** Handler) | blockierendes `httpx.Client`, aber im **Threadpool** → **kein Event-Loop-Risiko** (FastAPI-Prinzip) |
| `main.py:9089/9092` | `async def proxy_web_ui` | `await client.get` → korrekt |
| `main.py:9245/9246` | `async def inject_container_config` | `AsyncClient` + `await` → korrekt |
| `main.py:535, 10363-10369` | async / Shared-Client | `AsyncClient` → korrekt |
| `archon/routers/system.py:40,129` | `async def` | `await client.get/post` → korrekt |
| `backend/voice_pipeline.py:59-193` | `async def` | `AsyncClient` + `await` → korrekt |
| `backend/agent_router.py:589` | `async def` | `await client.post` → korrekt |
| `utils/notebook_engine.py:416` | `async def` | `await client.post` → korrekt |

**Ergebnis: kein blockierendes `httpx` in einem `async def`-Handler.** Der einzige
synchrone `httpx.Client` sitzt in einer sync-Funktion, die von einem sync-Handler im
Threadpool gerufen wird — das ist das vorgesehene Muster (Fallstrick 25). Status ⚪ → ✅.

---

## S8 — Kein Rate-Limiting (behoben 2026-11-06)

**Befund.** 200+ Endpunkte ohne jede Bremse, darunter `/api/sandbox`,
`/api/v1/container/exec`, die Update-Endpunkte und die Proxy-Pfade.

**Fix.** `utils/rate_limit.py` als ASGI-Middleware (Token-Bucket, In-Memory):

* **Standard 600/min** pro Client — die UI pollt legitim alle 10–30 s, ein
  hartes Limit würde das Dashboard treffen.
* **Strikt 20/min** für teure/gefährliche Pfade: `/api/sandbox`,
  `/api/v1/container/exec`, `/api/hermes/update`, `/api/system/update`,
  `/api/proxy`, `/api/router/hedged`, `/api/auth`.
* **Ausgenommen:** `/health`, `/metrics`, `/static/`, SSE-Stream, OpenAPI,
  CORS-Preflight (`OPTIONS`).
* **Kein neuer Endpunkt** → Routen-Parität bleibt 585/861.
* Notaus: `ARCHON_RATE_LIMIT_ENABLED=0`. Limits per
  `ARCHON_RATE_LIMIT_DEFAULT` / `ARCHON_RATE_LIMIT_STRICT` einstellbar.
* Bewusst **kein** Zusatzpaket (`slowapi`/`limits` nicht installiert; ein
  Paket-Nachinstall im laufenden Container wäre das größere Risiko).

**Verifikation.**

```bash
.venv/bin/python -m pytest tests/test_rate_limit.py -q   # 10 passed
```

Live-Belege (2026-11-06): strikter Pfad 26 Anfragen → 20×403 + 6×429; `/health` 30× → 30×200.

---

## S10 — SSRF im Proxy (behoben 2026-11-06)

**Befund.** `GET /api/proxy?url=…` in `main.py` holte jede vom Client übergebene
URL serverseitig ab — ohne Prüfung von Schema, Host oder Zielbereich. Damit war
der Endpunkt ein offener SSRF-Kanal: interne Dienste (`127.0.0.1`, Docker-Namen),
private Netze und Cloud-Metadaten (`169.254.169.254`) waren erreichbar, und die
Antwort wurde zurückgeliefert. Der Endpunkt hatte in 30 Stunden **null Aufrufe**
(`docker logs --since 30h ARCHON-OS | grep -c "GET /api/proxy"` → 0), war also
tote Angriffsfläche.

**Fix.** Neues Modul `utils/egress_guard.py`:

* nur `http`/`https`, keine Zugangsdaten in der URL
* lokal erlaubt: `localhost`, `127.0.0.1`, `::1`, `host.docker.internal`
* alles andere nur per `ARCHON_PROXY_ALLOWED_TARGETS` (kommagetrennt, `host:port`)
* Link-Local/Metadaten (`169.254.0.0/16`, `fd00:ec2::254`) **nie** erlaubt, auch
  nicht per Allowlist
* Prüfung läuft **vor** dem Request

**Verifikation.**

```bash
.venv/bin/python -m pytest tests/test_egress_guard.py -q     # 22 passed
```

Live (06.11.): Metadaten-URL → 403 mit Grund, `10.0.0.5` → 403, `127.0.0.1:8501/health` → 200.

---

## Nächste Schritte (priorisiert)

**Erledigt — aus dieser Liste gestrichen (Stand 2026-11-07, Belege oben):**

* ~~**B1 Race Condition MC-Lock**~~ → ✅ alle vier Schreiber nutzen `update_mc` + Delta-Merge,
  `RuntimeError` statt stillem Fallback.
* ~~**S6 Sandbox-Escape**~~ → ✅ alter Pfad 501, neuer Pfad isoliert live gemessen.
* ~~**S7/B5/B8 verifizieren**~~ → alle drei geprüft: S7 ✅, B8 ✅, B5 🟡 mit einem
  benannten Härtungspunkt (`evict_stale_memories(table=…)`).

**Echte Restliste (Priorität von oben nach unten):**

1. **A5 / A7 / A8** — 25 Modul-Globals (`grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py`),
   1 `Depends()`, Config über 15+ Dateien. **Etappe 1–4 erledigt (2026-11-07):**
   Konstanten und Pfad-Konstanten ausgelagert, Doppelzuweisungen + tote TTL-Konstanten
   entfernt; **Etappe 3** = A7-Pilot, **Etappe 5** = Rollout geprüft und mit Begründung
   abgelehnt (`hermes_profiles.py`, zwei sync-Routen, Thread-Affinität).
   Rest: **24 mutable Globals** (Caches/Bäume, Fallstrick 24) und A8-Config-Schicht.
   Etappenplan, Aufwand und Abbruchkriterien: `docs/A5_INVENTUR.md`.
2. **B10 Pfad-Config-Schicht** — 145 × `/opt/data` in `main.py`+`archon`+`backend`+`utils`
   (195 mit `scripts`/`tests`). Braucht eigene Config-Schicht **plus eigenen Tag mit eigener
   Baseline**, sonst ist die Parität nicht mehr prüfbar.
3. **B9** — 50 × `api_route` in `main.py` (`grep -c "api_route(" main.py`);
   Konsolidierung auf wenige Meta-Routen, eigener Paritäts-Nachweis.
4. **A6** — 15 × `asyncio.to_thread`; sync-I/O in async bleibt punktuell offen.
   Kandidaten über einen AST-Scan auf `async def`-Handler eingrenzen (wie B8 gefahren).
5. **B3-Rest / S1** — `backend/hermes_updater.py:58` `DockerSocketClient` auf
   `utils/docker_client` umstellen (Allowlist + Namensvalidierung).
   `backend/privacy_router.py:103,152` (roher TCP-Connect für Latenzproben) separat bewerten.
6. **B5-Härtung** — `local_memory_bridge.py:454` `evict_stale_memories(table=…)`:
   `table` gegen `frozenset({"conversations","learnings"})` validieren.
7. **Performance P1–P8** — 🔴 ungeprüft/offen (Pooling, synchrone Docker-Calls, N+1,
   Batching, Vault-Reads, Modell-Re-Instanziierung, Streaming, Cache-Keys).
   Bezug: `scripts/bench_routes.py`, 128 Routen, Median 73 ms warm (Stand 06.11.).
8. **S3 / S4 / S9** — 🟡 unverändert offen: kein Secret-Manager, kein MFA/2FA,
   Telegram-Token im Klartext in `.env`.

## Was nachweislich erledigt ist

A2, B1, B2, B4, B6, B8, S2, S5, S6, S7, S8, S10 — **zwölf** Punkte, jeder mit Messbefehl oben.
Teilweise erledigt (Rest namentlich benannt): B3/S1, B5, B7, B10, A1, A3, A4, A6, S3, S4, S9.

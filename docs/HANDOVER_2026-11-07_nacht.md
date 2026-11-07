# Handover — neue Session (Nachtstand 2026-11-07, Branch `refactor/a5-di-config`)

**Ersetzt** `docs/HANDOVER_2026-11-07_abend.md` für die Arbeit am A5/A7-Umbau. Das
Abend-Dokument gilt weiter für alles, was **vor** dem Abzweig passiert ist (S6/B1/S7/B8/B3,
Rollen/Modelle, Sandbox) — es ist nicht überholt, sondern der Vorgängerstand.

**Stand:** 2026-11-07 abends · Branch **`refactor/a5-di-config`** @ **`e03e4649`**
(abgezweigt von `refactor/critical-hardening` `314ea093`) · **66 Commits seit `main`** (`dd9f111a`),
davon **9 auf diesem Branch** · live (`--reload`, Änderungen sofort aktiv) · Arbeitsbaum **sauber**
(nur fremde untracked Einträge).

---

## Copy-Paste für die neue Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Docker-Port 8501, Nur-Loopback-Binding).
Branch: refactor/a5-di-config (67 Commits seit main, 10 eigene). NIEMALS main. Kein Push, kein Merge.
Abzweig von refactor/critical-hardening @ de564278 (Tip von critical-hardening; dessen Vorfahr
ist 314ea093 — nicht der Abzweigpunkt). Baseline-Commit des Branches: 4956f518.
Lies zuerst docs/A5_INVENTUR.md (Kategorisierung aller Modul-Globals, A8-Bestand,
A7-Bewertung plus Etappenplan), dann docs/AUDIT_STATUS.md (40-Punkte-Audit) und
docs/HANDOVER_2026-11-07_abend.md (Vorstand vor dem Abzweig).

Drei Pflicht-Guards nach JEDER Änderung, Abbruchregel: rot -> sofort git checkout -- <Datei>:
1) .venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json
     # Exit 0, Soll 585 Pfade / 861 Operationen
2) .venv/bin/python scripts/check_router_names.py; echo "exit=$?"     # Soll exit=0
     # ACHTUNG: das Skript schweigt im Erfolgsfall vollstaendig — keine Routerzahl, kein "ok".
     # Es scannt 20 Dateien in archon/routers/, davon __init__.py uebersprungen = 19 geprueft.
     # "exit=0" allein ist ein schwacher Beleg: die Zahl 20 stammt aus `ls archon/routers/*.py`, nicht aus dem Guard.
3) .venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider   # Soll 243 passed, 8 skipped

Zwei weitere Guards, die diese Runde dazugekommen sind (beide in der Suite):
- tests/test_a5_no_duplicates.py   -> kein Modulname darf in main.py doppelt zugewiesen werden
- tests/test_a7_router_db_open.py  -> kein Router-Handler oeffnet die State-DB selbst (Pins fuer avatars.db)

Fuer Pfad-Aenderungen zusaetzlich: scripts/path_constants_snapshot.py in BEIDEN Umgebungen
vergleichen (Host ./... vs Container /app/...), Baselines unter scripts/parity_baselines/paths_before_*.json.

Sprache: Deutsch. Erst messen, dann behaupten — keine Zahl aus diesem Dokument abschreiben.
```

---

## Die Fakten (alle selbst gemessen am 2026-11-07, nach dem letzten Commit)

| Größe | Wert | Messbefehl |
|---|---|---|
| `main.py` | **11.252 Zeilen** (Vorgängerstand des Branches beim Abzweig: 11.291) | `wc -l main.py` |
| Modul-Globals (grep) | **25** (vorher 52) | `grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py` |
| Decorator-Routen | **308** (unverändert) | `grep -cE '@app\.(get\|post\|put\|patch\|delete\|websocket\|api_route)\(' main.py` |
| Live-Pfade / Operationen | **585 / 861**, Exit 0 | `scripts/route_parity.py --check …2026-11-07.json` |
| Router-Dateien / mit `configure()` | **20 / 6** | `ls archon/routers/*.py \| wc -l`; `grep -ln "def configure(" archon/routers/*.py \| wc -l` |
| `Depends()` in `archon/` | **1** (`archon/routers/system.py:123`) | `grep -rn "Depends(" --include=*.py archon \| wc -l` |
| Tests | **243 passed, 8 skipped** (~12 s) | `.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider` |
| Neue Module | `archon/core/constants.py` **83** Z., `archon/core/paths.py` **68** Z. | `wc -l` |
| Neue Werkzeuge | `scripts/path_constants_snapshot.py` **74** Z., **5** neue Testdateien (98/46/47/124/100 Z.: `test_a5_constants`, `test_a5_no_duplicates`, `test_a5_path_constants`, `test_a7_depends_pilot`, `test_a7_router_db_open`) | `wc -l` |
| Container | `ARCHON-OS`, **`127.0.0.1:8501->8501/tcp`** (Uptime zeitabhängig) | `docker ps --filter name=ARCHON-OS` |
| Image | **`af26a3ee66e2`** (unverändert seit dem Morgen, kein Rebuild) | `docker inspect ARCHON-OS --format '{{.Image}}'` |
| Diff des Branches | **16 Dateien, 1280+ / 90−** am HEAD (= 15/1056+ für `e03e4649`; +224 Z. ist dieses Dokument) | `git diff --shortstat 4956f518..HEAD` |
| Traceback/NameError | **0** | `docker logs --since 5m ARCHON-OS 2>&1 \| grep -cE "Traceback\|NameError"` |

Offene Audit-Zahlen, ebenfalls nachgemessen (nicht aus dem Abend-Dokument übernommen):
**B9** 50 × `api_route` · **A6** 15 × `asyncio.to_thread` · **B10** 145 × `/opt/data`
(`main.py`+`archon`+`backend`+`utils`) · nackte `except:` **2**, `except: pass` **0** ·
`safe_path` **12** Vorkommen in `main.py`.

---

## Die 9 Commits dieses Branches (je `git show --stat` geprüft)

| Commit | Inhalt | Wirkung |
|---|---|---|
| `443edfbf` | `docs/A5_INVENTUR.md` (236 Z.) | Kategorisierung **aller** Globals (K/KP/M/R), A8-Bestand, A7-Bewertung, Etappenplan |
| `f094e348` | `archon/core/constants.py` + `tests/test_a5_constants.py` | 5 unveränderliche Konstanten ausgelagert (Auth-Präfixe, Entscheidungstypen, Delegations-Prompt, Studio-Upload) |
| `eabc30cf` | `main.py` −4 Z. + `tests/test_a5_no_duplicates.py` | 2 wirkungslose Doppelzuweisungen (`ROLES_FILE`, `SERVICES_FILE`) + 2 tote TTL-Konstanten entfernt |
| `75621472` | `archon/core/state_db.py`, `archon/routers/system.py`, `tests/test_a7_depends_pilot.py` | **A7-Pilot:** `get_state_db_dep()` als async-Generator-Provider, eine Route auf `Depends()` |
| `9c84c495` | `archon/core/paths.py`, `main.py`, `scripts/path_constants_snapshot.py`, 2 Baselines, `tests/test_a5_path_constants.py` | **18 Pfad-Konstanten** ausgelagert — Werte in Host **und** Container byte-identisch vor/nach |
| `d2514a16` | `docs/A5_INVENTUR.md` +43, `tests/test_a7_router_db_open.py` | A7-Rollout-Befund dokumentiert + Leitplanke gegen DB-Öffnen in Handlern |
| `5085cd91`, `41866855`, `e03e4649` | `docs/AUDIT_STATUS.md` | Kennzahlen nach jeder Etappe nachgezogen |

Davor, auf dem Vorgänger-Branch: `4956f518` (Baseline 2026-11-07 eingefroren) und
`de564278` (Audit-Status/Handover auf gemessenen Stand gezogen).

---

## Drei Fehlerklassen, die diese Runde Zeit gekostet hätten (der wertvollste Teil)

### a) ZWEI ZUWEISUNGEN, EINE WIRKT — und niemand sieht es

`ROLES_FILE` und `SERVICES_FILE` waren in `main.py` je **zweimal** zugewiesen: erst unter
`MEMORY_DIR`, später unter `WORKSPACE_DIR`. Python nimmt still die letzte; die erste ist
wirkungslos und lässt jedes Lesen der Datei falsch interpretieren. Rot-Beweis des neuen Guards
gegen den Altstand: `{'ROLES_FILE': [333, 2524], 'SERVICES_FILE': [335, 2525]}`.
**Regel:** Aufräumen darf den effektiven Wert nicht ändern — gelöscht wird nur die *frühere*
Zuweisung; liegt zwischen alter Zuweisung und erstem Leser Modulebene-Code, ist die Löschung
ein `NameError` beim Import (der Beweis ist ein erfolgreicher `import main`).

### b) PFADE SIND UMGEBUNGSABHÄNGIG — „auf dem Host gleich" ist kein Beweis

Eine Auslagerung von Pfad-Konstanten nach `archon/core/` wäre mit einer eigenen
`__file__`-Ableitung auf `/app/archon/core/…` gelandet statt auf `/app`. Auf dem Host hätte
alles gepasst. **Regel:** Pfade ausschließlich über die Basis-Verzeichnisse aus
`archon/core/runtime.py` ableiten, Werte **vor** der Änderung in **beiden** Umgebungen
einfrieren (`scripts/path_constants_snapshot.py`, Baselines `paths_before_host.json` /
`paths_before_container.json`) und nach der Änderung erneut vergleichen — **beide Diffs müssen
leer sein**, sonst Rollback.

### c) SQLITE-VERBINDUNGEN SIND THREAD-AFFIN — und der Fehler ist nicht deterministisch

Der A7-Rollout auf die beiden verbleibenden Router-Stellen (`hermes_profiles.py:372,452`,
`avatars.db`) wurde **bewusst nicht** gemacht: ein sync-Generator-Provider liefe im
FastAPI-Threadpool, während der Handler im Event-Loop-Thread läuft. Gemessen:
`ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`
Die **Gegenprobe blieb grün**, weil Python Thread-Idents recycelt — der Fehler ist
**lastabhängig**. Zusätzlich würde eine Dependency **vor** dem Handler aufgelöst und aus dem
heute tolerierten `connect`-Fehler (Warnung, Handler läuft weiter) ein **500**. Der Pilot in
Etappe 3 ist deshalb `async` gebaut (`get_state_db_dep`) und im Modul-Docstring begründet.

---

## OFFEN — nach Priorität

| Prio | Punkt | Stand (gemessen) |
|---|---|---|
| 1 | **A5-Rest** | 🟡 **25** Globals: 13 mutable Caches/Halter (davon **4 tot**: `_HERMES_SKILLS_CACHE`, `_HERMES_SKILLS_CACHE_TIME`, `_FABRIC_CACHE`, `_PROMPT_STUDIO_CACHE`), 6 mutable Daten-Defaults (Listen/Dicts), 2 Proxy-Clients (`_OMNIROUTE_PROXY`, `_N8N_PROXY`), `_APP_START_TS` (zeitbasiert, **nicht** auslagern), 2 `set`-Literale (`_AUTH_PUBLIC_EXACT`, `GHOST_AGENT_IDS`) → als `frozenset` verschiebbar |
| 2 | **A7** | 🟡 1 × `Depends()` (Pilot). Rollout **erschöpft**: nur 2 weitere Kandidaten, beide aus drei belegten Gründen ungeeignet. Vorbedingung für mehr: Connection-Pool oder `check_same_thread=False` **mit eigener Testabdeckung** |
| 3 | **B10 Pfad-Config** | 🟡 **145** × `/opt/data` in `main.py`+`archon`+`backend`+`utils` (195 mit `scripts`/`tests`). Andockpunkt ist jetzt `archon/core/paths.py`; braucht eigene Baseline/Tag |
| 4 | **B9 / A6** | 🔴 50 × `api_route` in `main.py` · 🟡 15 × `asyncio.to_thread` |
| 5 | **S3 / S4 / S9** | 🟡 kein Secret-Manager, kein MFA, Telegram-Token im Klartext in `.env` |
| 6 | **Performance P1–P8** | 🔴 **nicht neu gemessen** (Bezug: `scripts/bench_routes.py`, 128 Routen, Median 73 ms warm, Stand 06.11.) |
| 7 | **Zwei benannte Altfehler** | 🟡 **Defekt 1 behoben in `ffb04bec`** (2026-11-07): `POST /api/system/hermes/restart` startet keinen Container mehr, sondern diagnostiziert (200 `ok` / 409 `not_running` / 409 `absent` / 502 `docker_error`); Ziel-Container ist `hermes-agent` (Kandidatenliste per `ARCHON_HERMES_CORE_CONTAINER`), der UI-Text ist separat nachgezogen. **Grund für „melden statt starten":** der Core-Ableger fährt `gateway run` und würde mit dem Host-Gateway um denselben Bot-Token konkurrieren (getUpdates-Konflikt). 🔴 `backend/hermes_updater.py:63` (Z. 58 vor `ffb04bec`) `DockerSocketClient` mit rohem `AF_UNIX` **umgeht die Docker-Allowlist** (live in `get_installed_hermes_info`/`recreate_container_with_new_image`) — **offen** |
| 8 | **Härtungspunkte** | `local_memory_bridge.py:454` `evict_stale_memories(table=…)` interpoliert `{table}` ungeprüft (Z. 459/471) — Aufrufer übergeben heute Literale · `backend/ephemeral_sandbox.py` fällt auf Host-Python zurück, wenn `docker info` scheitert |

---

## Verifikation (immer dieser Block, wörtlich ausführen)

```bash
cd /mnt/raid/AgenticOS-2026
.venv/bin/python -m py_compile main.py
.venv/bin/python scripts/check_router_names.py; echo "exit=$?"                                              # 0
.venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-07.json  # Exit 0, 585/861
.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider                                        # 243 passed, 8 skipped

T=$(cat data/.archon_service_token)
curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8501/health                               # 200
curl -s -o /dev/null -w "mc=%{http_code}\n" -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/mission-control/state   # 200
curl -s -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/roles | md5sum                            # 0e1a4c13… (Referenz Etappe 2)
docker logs --since 5m ARCHON-OS 2>&1 | grep -cE "Traceback|NameError"                                      # 0
git status --short                                                                                          # nur fremde untracked Einträge

# Pfad-Werte-Beweis (nach jeder Pfad-Änderung, beide Umgebungen):
.venv/bin/python scripts/path_constants_snapshot.py > /tmp/p_host.json
docker exec -w /app ARCHON-OS python scripts/path_constants_snapshot.py > /tmp/p_cont.json
diff <(sed -n '/^{/,$p' scripts/parity_baselines/paths_before_host.json)      <(sed -n '/^{/,$p' /tmp/p_host.json)
diff <(sed -n '/^{/,$p' scripts/parity_baselines/paths_before_container.json) <(sed -n '/^{/,$p' /tmp/p_cont.json)
# Hinweis: der Container-Import schreibt 4 INFO-Zeilen nach stdout VOR das JSON —
# deshalb ab der ersten "{"/"-Zeile vergleichen, nicht roh.
```

---

## Rollback

```bash
# gesamten Branch-Stand verwerfen (Branch bleibt bestehen):
git checkout refactor/critical-hardening

# einzelne Etappen zurücknehmen (neueste zuerst):
git revert e03e4649   # Doku Etappe 4+5
git revert d2514a16   # A7-Leitplanke + Rollout-Befund
git revert 9c84c495   # 18 Pfad-Konstanten (paths.py)
git revert 75621472   # A7-Pilot (Depends in system.py)
git revert eabc30cf   # Doppelzuweisungen + tote TTLs
git revert f094e348   # 5 Konstanten (constants.py)
git revert 443edfbf   # Inventur-Doku
```

**Wichtig:** `9c84c495` und `75621472` hängen an ihren Vorgängern. Ein Revert von `9c84c495`
allein ist unkritisch; ein Revert von `f094e348` **ohne** `9c84c495` bricht die Imports nicht,
aber `paths.py` bleibt dann ohne Nutzen liegen. Sauberer Rückweg bei Problemen:
`git checkout refactor/critical-hardening`.

---

## Fremde uncommittete Dateien im Arbeitsbaum (nicht anfassen, nicht committen)

```
?? .archon_backup_20261105_1015/omniroute_combos_vor_fix_20261106.json
?? .archon_backup_20261105_1015/skill_rollout_20261106_121401/
?? archon/core/agent_profiles.json
?? docs/BETRIEB_HANDBUCH_INTERN.md
?? docs/screenshots_20261106/
?? docs/system/HANDBUCH_Vorlage_Vorschau.pdf
?? frontend/
?? frontend_recovered_20261106_122145/
?? hermes_skills_cache.json
?? hermes_skills_index.json
?? scripts/gateway_watchdog.sh
```

Elf Einträge, vor und nach jeder Etappe gleich viele. Die 243/8-Testzahlen gelten für diesen
Stand **inklusive** dieser Dateien.

---

## Was in dieser Runde NICHT belegt wurde (ehrlich, nicht kleinreden)

- **Live-Verkehr der umgestellten Route:** der echte Aufruf von
  `POST /api/system/hermes/restart` liefert 500 — **aus dem Handler-Rumpf** (Docker-404, Container
  `hermes` fehlt), nicht aus der Signatur. Dass die Dependency aufgelöst wurde, ist damit belegt,
  ein Erfolgspfad **nicht** (dafür müsste ein Container wirklich neu starten).
- **Der funktionale Test** aus Etappe 3 ist nicht rot-belegt: gegen den alten Code hätte er in die
  reale `~/.hermes/state.db` geschrieben. Rot-belegt ist nur der AST-Test.
- **Nebenläufigkeit und Last:** keine Messung. Der A7-Pilot öffnet die Verbindung jetzt auch auf dem
  Fehlerpfad (0,43 ms Median, gemessen), unter Konkurrenz **nicht** gemessen.
- **P1–P8:** nicht neu gebenchmarkt.
- **Die 18 Pfad-Werte** sind vor/nach identisch (Host und Container) — dass die Endpunkte sie unter
  Last gleich benutzen, ist **nicht** funktional durchgespielt; belegt sind Werte, Parität, Tests,
  `/api/roles`-md5 und die laufenden `makedirs`.

---

*Erstellt: 2026-11-07 abends/nachts · Branch `refactor/a5-di-config` @ `e03e4649` ·
66 Commits seit `main` (`dd9f111a`), 9 davon auf diesem Branch · alle Zahlen in diesem Dokument
am selben Abend mit den genannten Befehlen gemessen, keine aus dem Abend-Handover übernommen.*

**Nachtrag (Zählstand):** Die Werte 66 / 9 / 15 Dateien / 1056+ beschreiben den Stand `e03e4649`,
also *vor* diesem Dokument. Am HEAD (`3897577a`, inkl. dieses Dokuments) gilt:
`git rev-list --count main..HEAD` → **67**, `git rev-list --count 4956f518..HEAD` → **10**,
`git diff --shortstat 4956f518..HEAD` → **16 Dateien, 1280+ / 90−**. Die Messbefehle in der
Faktentabelle reproduzieren daher heute andere Zahlen als daneben stehen — wer den Stand
braucht, auf den sie sich beziehen, muss gegen `e03e4649` messen.

---

## Gegenprobe 2026-11-07 (nach dem Handover-Commit)

Eine zweite Session hat dieses Dokument gegen das Repo geprüft (`senior_fullstack_engineer`,
read-only). Ergebnis: alle drei Pflicht-Guards erneut grün (Parität 585/861 exit 0,
`check_router_names` exit 0, **243 passed / 8 skipped**), alle Bestandszahlen der Tabelle
deckungsgleich, die beiden mitgenommenen Defekte mit Datei:Zeile bestätigt.

Korrigiert wurden in diesem Durchgang:
1. **Fork-Punkt:** `de564278` (= Tip von `refactor/critical-hardening`), nicht `314ea093`.
   `git merge-base HEAD refactor/critical-hardening` belegt das; 314ea093 ist nur Vorfahr.
2. **Zählwerte** 66/9/15/1056 sind der Stand `e03e4649` — siehe Nachtrag oben.
3. **„4 neue Testdateien"** → es sind **5**.
4. **Guard 2 ist stumm** im Erfolgsfall — „20 Router per AST" ist nicht durch seine Ausgabe
   gedeckt; gescannt werden 19 Dateien (`__init__.py` übersprungen).

Zusätzliche Befunde, die dieses Dokument vorher nicht nannte:
- **`A6` = 15 ist pfadabhängig:** repo-weit sind es 31 × `asyncio.to_thread`
  (`main.py` 15, `archon` 14, `backend` 2). Die 15 gilt nur für `main.py`.
- **Host-Pfadauflösung mit Nebenwirkung:** `scripts/parity_baselines/paths_before_host.json`
  zeigt `MEMORY_DIR` und `DATA_DIR` beide als `.` — ein Import von `main.py` auf dem Host
  schreibt in das **Repo-Root**. Daher stammen die untracked `hermes_skills_cache.json` /
  `hermes_skills_index.json` dort. `scripts/path_constants_snapshot.py` importiert `main` und
  hat diesen Seiteneffekt; im Container (CWD `/app`) fällt er nicht auf.
- **Guard-Schwäche:** `scripts/check_router_names.py` führt eine hartkodierte
  `CONFIGURE_PARAMS`-Allowlist für 5 Router (`mission_control.py` fehlt darin); deren
  `configure()`-Parameter kommen nur aus dem AST. Eine gewachsene Whitelist kann undefinierte
  Namen maskieren — für einen verschärften Guard ist das eine offene Stelle.
- **Nicht erneut gefahren:** das Snapshot-Skript (Seiteneffekt-Risiko, s. o.). Die
  Ableitungskette in `archon/core/paths.py` wurde statisch geprüft (nur Import aus
  `runtime.py`, keine eigene `__file__`-Ableitung).
- `POST /api/system/hermes/restart` wurde **nicht** aufgerufen (Eingriff); die 500 ist aus dem
  Handler-Pfad abgeleitet, nicht live gemessen.

# Handover — neue Session (Abendstand 2026-11-06)

**Ersetzt** `docs/HANDOVER_NEUE_SESSION.md` (Stand Mittag) — der dortige
Copy-Paste-Block beschreibt Zahlen von vor der Abendrunde.

**Stand:** 2026-11-06, abends · Branch `refactor/critical-hardening`, live deployt
(via `--reload`, Änderungen sind sofort aktiv)

## Copy-Paste für die neue Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Docker, Port 8501).
Lies zuerst docs/REFACTOR_STAND_2026-11-06.md (Umbau) und
docs/AUDIT_STATUS.md (40-Punkte-Audit: Status + Messbefehl je Punkt).
Branch: refactor/critical-hardening (29 Commits seit main). Niemals auf main.
Vor jeder Änderung: Baseline prüfen; nach jeder Änderung:
.venv/bin/python scripts/route_parity.py --check
  scripts/parity_baselines/openapi_baseline_2026-11-06.json
(Soll: 585 Pfade / 861 Operationen), dann pytest (Soll: 190 passed, 4 skipped).
Nächster Punkt: die zwei verbleibenden Snapshot-Schreiber in
archon/core/orchestration.py (_trigger_sandy_staffing_nomination,
_run_synthesis_cascade) — siehe "Offen" unten.
Sprache: Deutsch. Erst messen, dann behaupten.
```

## Die 5 Fakten

1. **`main.py` = 11.353 Zeilen**, 308 Decorator-Routen. Live-App: **585 Pfade /
   861 Operationen** (openapi.json). Die Decorator-Zahl ist kein Live-Maß.
2. **Paket heißt `archon`**, nicht `app` (`app.py` im Repo ist Streamlit).
3. **Container läuft aus `docker-compose.dev.yml`** (Projekt `archon`,
   Container `ARCHON-OS`) mit `--reload` auf `/app` — es gibt kein „nur lokal".
4. **Routen-Parität ist Pflicht:** `scripts/route_parity.py` gegen die Baseline
   in `scripts/parity_baselines/`. Exit 0 = identisch, 1 = Abweichung,
   2 = Verbindungsfehler. Negativtest mitfahren (Baseline manipulieren).
5. **pytest liegt im `.venv`:** `.venv/bin/python -m pytest tests/ -q
   --no-header -p no:cacheprovider` → **190 passed, 4 skipped**.

## Deploy in 3 Zeilen

```bash
cd /mnt/raid/AgenticOS-2026
docker compose -f docker-compose.dev.yml -p archon up -d --force-recreate archon
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/health
```

Nur nötig bei Compose-/Env-Änderungen. Code-Änderungen greifen durch `--reload`.

## Was in dieser Runde erledigt wurde (12 Commits)

| Commit | Inhalt |
|---|---|
| `74d21bff` | Orchestrierungskern (754 Z., 8 Funktionen) nach `archon/core/orchestration.py`, DI statt Modul-Symbole, `main.py` 12.184 → 11.608 Z. |
| `bf0aa9f0` | 33 Unit-Tests für die 8 Funktionen (Mocks, kein I/O) |
| `33c21fd1` | Die zwei stillen `except: pass` in `backend/system_updater.py` → Logging |
| `340fa561` | 4 Mission-Control-Routen in `archon/routers/mission_control.py`, `configure()`-DI |
| `b14543d6` | Dispatcher-Fehler markiert Task als `failed` (vorher: erfundener Erfolgstext); `NameError` `freigeben/freigegeben` behoben |
| `5743021d` | 3 latente `ModuleNotFoundError` in den DI-Fallbacks behoben |
| `a4267fa2` | Divergierende Helfer-Kopien in `runtime.py` gelöscht; fehlende Injektion → `RuntimeError` statt stiller Abweichung |
| `5bd1678d` | **S10**: SSRF in `/api/proxy` durch `utils/egress_guard.py` geschlossen |
| `8ecff145` | **S8**: Rate-Limiting als Middleware (`utils/rate_limit.py`) |
| `372eb540` | **B1/1**: Lost Updates im Store — ein `RLock`, atomare `update_mission_control_data()` |
| `a120dc19` | **B1/2**: Move-Handler zweiphasig (atomar schreiben, dann Seiteneffekte) |
| `4828ac9b` | **B1/3**: `_execute_mission_control_task` schreibt nur noch sein Delta |

Details, Messwerte und Messbefehle je Punkt: `docs/AUDIT_STATUS.md`.

## Offen — nach Priorität

1. **B1 fertigstellen** (letzter Datenverlust-Punkt): In
   `archon/core/orchestration.py` nutzen noch
   `_trigger_sandy_staffing_nomination` (ca. Z. 390–460) und
   `_run_synthesis_cascade` (ca. Z. 720–880) das Muster „Store laden, ändern,
   kompletten Dict zurückschreiben" über `await`-Strecken. Das Muster ist bereits
   implementiert: Parameter `update_mc` + `_merge_task_delta()` in
   `_execute_mission_control_task` als Vorlage nehmen, dann im `main.py`-Wrapper
   `update_mc=update_mission_control_data` mitgeben.
2. **S6 Sandbox-Escape** — `api_run_python_sandbox` führt Code mit Host-Python
   aus. Rate-Limiting entschärft nur die Ausnutzbarkeit, nicht das Prinzip.
3. **B3** — direkte Docker-Socket-Connects in `main.py` (Z. ~920, 1021, 1032)
   neben dem abgesicherten `utils/docker_client.py`.
4. **S7 / B5 / B8 prüfen** — ungeprüft: YAML-Tags, SQL-f-Strings, httpx in async.
5. **A5/A7/A8** — 52 Modul-Globals, kein `Depends()`, Config verstreut.
6. **B10** — 169 hardcodierte `/opt/data`-Pfade; eigener Tag mit eigener Baseline.

## Fallstricke dieser Runde (teuer bezahlt)

1. **SSE-Endpunkt darf nicht mitwandern.** Beim Auslagern der MC-Routen wurde
   `@app.get("/api/v1/events/stream")` mitgelöscht, weil er *zwischen* den
   Handlern lag. Live-Parität fiel auf 584/860, die Instanz war ~8 min
   degradiert. Regel: Löschbereich aus den Handler-Grenzen ableiten
   (`awk '/^(async )?def |^@app\./' main.py`) und vor dem Schreiben die
   Decorator-Zahl einfrieren (`grep -cE '@app\.(get|post|…)\('`).
2. **Rollback ist Pflicht, nicht Bericht.** Ein Sub-Agent meldete den fehlenden
   Endpunkt, statt zurückzurollen. Bei Exit ≠ 0 in `--check`: sofort
   `git checkout -- main.py`, dann erzählen.
3. **Zwei Kopien einer Funktion sind eine Falle.** `_get_live_telemetry_metrics`
   und `_sync_task_to_obsidian` existierten in `main.py` und in
   `archon/core/runtime.py` mit *unterschiedlicher* Semantik (15 min vs.
   Tagesbeginn; eigene `_slugify()` → andere Dateinamen). Ein Direktimport hätte
   Zahlen und Pfade still verändert. Muster: `configure(**deps)` injizieren.
4. **Zwei Locks auf eine Datei serialisieren nicht.** Der Store hatte
   `threading.Lock` und `asyncio.Lock` parallel. Gegenprobe: altes Muster verlor
   **95 von 100** Inkrementen. Jetzt ein `RLock` + `update_mission_control_data()`.
5. **Ein Lock über einem `await` ist tabu.** Deshalb ist der Move-Handler
   zweiphasig: erst atomar schreiben, dann Seiteneffekte ausführen.
6. **Rate-Limiting ist aktiv** (`600/min` Standard, `20/min` strikt). Wer per
   Skript in Bursts gegen die API geht, bekommt 429. Notaus:
   `ARCHON_RATE_LIMIT_ENABLED=0` in `.env.archon` — braucht **Recreate**, nicht
   nur `--reload`.
7. **API-Endpunkte brauchen den Service-Token** (`X-Archon-Service-Token` aus
   `data/.archon_service_token`); nur `/health` ist öffentlich. Ein 401 ist Auth,
   kein Ausfall.

## Verifikation (immer diese vier)

```bash
cd /mnt/raid/AgenticOS-2026
.venv/bin/python -m py_compile main.py
.venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-06.json
.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider
T=$(cat data/.archon_service_token); curl -s -H "X-Archon-Service-Token: $T" \
  -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/api/mission-control/state
```

Zusätzlich nach jedem Umbau: `git status --short` auf fremde Core-Änderungen
prüfen und `docker logs --since 5m ARCHON-OS | grep -c Traceback`.

## Rollback

`git checkout main` (Ausgangszustand) bzw. einzelne Commits per
`git revert <sha>`. Backups im Repo: `main.py.pre-orchestration.bak`,
`main.py.pre-mcrouter.bak`.

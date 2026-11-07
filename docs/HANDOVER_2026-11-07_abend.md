# Handover — neue Session (Abendstand 2026-11-07)

**Ersetzt** `docs/HANDOVER_2026-11-07.md` (Stand Vormittag) — seither **14 Commits**
(gemessen: `git rev-list --count f9b2ab52..HEAD` → 14; der Auftrag sprach von „elf",
die Auftragsliste selbst enthielt schon 12. Nachgerechnet, nicht übernommen).

**Stand:** 2026-11-07, abends · Branch `refactor/critical-hardening` @ `f22402fc`,
live deployt (`--reload`, Änderungen sofort aktiv) · **53 Commits seit `main`** (`dd9f111a`).

---

## Copy-Paste für die neue Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Docker, Port 8501, Nur-Loopback-Binding).
Lies zuerst docs/REFACTOR_STAND_2026-11-06.md (Umbau) und
docs/AUDIT_STATUS.md (40-Punkte-Audit: Status + Messbefehl je Punkt).
Branch: refactor/critical-hardening (53 Commits seit main). NIEMALS main. Kein Push, kein Merge.
Vor jeder Änderung messen, nach jeder Änderung DREI Pflicht-Guards:
1) .venv/bin/python scripts/route_parity.py --check
     scripts/parity_baselines/openapi_baseline_2026-11-06.json    # Exit 0, Soll: 585 Pfade / 861 Operationen
2) .venv/bin/python scripts/check_router_names.py; echo "exit=$?" # Soll: exit=0 (AST-Scan der 20 Router)
3) .venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider
                                                                  # Soll: 234 passed, 8 skipped
NÄCHSTER PUNKT ist NICHT die Orchestrierung — B1 ist abgeschlossen (alle vier
Schreiber nutzen update_mc + Delta-Merge). Der nächste Punkt ist die Restliste
aus Kapitel "Offen" unten: A5/A7/A8, B10, dann die dort genannten Audit-Punkte.
Sprache: Deutsch. Erst messen, dann behaupten — keine Zahl aus diesem Dokument
abschreiben, jede nachrechnen.
```

---

## Die Fakten (alle am 07.11.2026 abends gemessen)

| Größe | Wert | Messbefehl |
|---|---|---|
| `main.py` | **11.291 Zeilen** (Vorgänger-Stand `f9b2ab52`: 11.252 → **+39**) | `wc -l main.py` / `git show f9b2ab52:main.py \| wc -l` |
| Decorator-Routen | **308** (`@app.get/post/put/patch/delete/websocket/api_route`) | `grep -cE '@app\.(get\|post\|put\|patch\|delete\|websocket\|api_route)\(' main.py` |
| Live-Pfade / Operationen | **585 / 861** — identisch zur Baseline, Exit 0 | `scripts/route_parity.py --check …` |
| Router-Dateien | **20** in `archon/routers/`, davon **6 mit `configure(**deps)`** (mission_control + boardroom, governance, hermes_profiles, skills, system) | `ls archon/routers/*.py \| wc -l`; `grep -ln "def configure(" archon/routers/*.py` |
| Tests | **234 passed, 8 skipped** (11,98 s) | `pytest tests/ -q --no-header -p no:cacheprovider` |
| `check_router_names.py` | **Exit 0** | `scripts/check_router_names.py; echo "exit=$?"` |
| Paketname | **`archon`** (`archon/__init__.py`: „Archon OS App-Paket."), nicht `app` | `head -5 archon/__init__.py` |
| Container | `ARCHON-OS`, aus `docker-compose.dev.yml` (Projekt `archon`), `uvicorn main:app --reload`, Port-Binding **`127.0.0.1:8501:8501`** | `docker ps`; `grep -n "reload\|127.0.0.1" docker-compose.dev.yml` |
| Image | **`archon-os-dev:latest` `af26a3ee66e2`**, 869 MB, gebaut `2026-11-07T09:23:21+01:00` — **unverändert** zum Vorgänger-Handover (kein Rebuild seit dem Morgen) | `docker inspect ARCHON-OS --format '{{.Image}}'` |
| Mounts | `/mnt/raid/AgenticOS-2026→/app`, `…/data→/app/data`, **`/home/micha/.hermes→/opt/data`**, `…/agent_workspace→/app/agent_workspace`, docker.sock | `docker inspect ARCHON-OS --format '{{range .Mounts}}…'` |
| Service-Token | `data/.archon_service_token` (49 Bytes, `0600`), Header **`X-Archon-Service-Token`** | `ls -l data/.archon_service_token` |
| Rate-Limits | **600/min** Standard, **20/min** strikt (`/api/sandbox`, `/api/v1/container/exec`, `/api/hermes/update`, `/api/system/update`, `/api/proxy`, `/api/router/hedged`, `/api/auth`); Notaus `ARCHON_RATE_LIMIT_ENABLED=0` | `grep -n "STRICT_PREFIXES" -A12 utils/rate_limit.py` |

Zusatzmaße für die offenen Audit-Punkte (selbst gemessen, siehe Kapitel „Offen"):
`A5` 52 Modul-Globals · `A7` 0 × `Depends()` · `A6` 15 × `asyncio.to_thread` · `B9` 50 ×
`api_route` in `main.py` · `B10` **145** × `/opt/data` in `main.py`(75)+`archon`(20)+
`backend`(41)+`utils`(9); mit `scripts`(42) und `tests`(8) = **195** (Vorgänger nannte 169 —
Zählbereich/Stand differiert, beide Zahlen sind reproduzierbar, die 145er-Zahl ist die
Vier-Bereichs-Zahl des Audits).

---

## Deploy (nur bei Compose-/Image-Änderungen)

```bash
cd /mnt/raid/AgenticOS-2026
docker compose -f docker-compose.dev.yml -p archon up -d --force-recreate archon
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/health
```

Code-Änderungen greifen durch `--reload` — **kein** Recreate nötig. Nach jedem Recreate
sind die sechs Sandbox-Proben (Kapitel „Sandbox") erneut zu fahren.

---

## Was seit dem Vorgänger-Handover passiert ist (14 Commits, je gemessen via `git show --stat`)

| Commit | Inhalt |
|---|---|
| `f22402fc` | **Entwickler-Rollen auf openrouter** — `roles.json` 4+/4−: `devops_cloud_sec_specialist` und `senior_fullstack_engineer` auf `openrouter` / `deepseek/deepseek-v4.1-flash-1017` (kein Free-Tier-Cooldown) |
| `69aff9da` | **Dublette aus Git entfernt** — `archon/core/agent_profiles.json` gelöscht (3.438 Zeilen, die 2,6-MB-Kopie; Datei liegt weiter untracked im Arbeitsbaum) |
| `92d31f61` | **15 Screenshots ins Handbuch** — `docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx` binär, 7,68 MB → 4,75 MB (Bilder komprimiert), Text/Tabellen/Überschriften unverändert |
| `155f5f21` | **PbD idempotent** — `backend/computer_use_pbd.py` 59+/4− + `tests/test_pbd_idempotent.py` (75 Zeilen): unveränderte Skills/Skripte werden nicht neu geschrieben, Zeitstempel kommt aus der Bestandsdatei |
| `9ac34daf` | **evolve-tool ehrlich** — `backend/operations_api.py` 30+/7−: ohne `implementation_code` **400** mit Begründung statt **500 TypeError** |
| `c5691623` | **Selbst-Evolution idempotent** — `backend/self_evolving_tooling.py` 75+/8− (Tool-/Skill-Erzeugung schreibt nicht mehr blind, `UnboundLocalError` in `datetime` behoben) + `tests/test_self_evolving_idempotent.py` (122 Zeilen) |
| `c38321f6` | **Sandbox-Temp nach `/opt/data`** — `backend/ephemeral_sandbox.py` 16+/4−, `SANDBOX_TEMP_DIR = "/opt/data/archon_sandbox_runs"` (außerhalb des überwachten `/app`) |
| `fb85661b` | **Schreibpfad-Leichen** — `main.py` 2−: `/app/archon/core/agent_profiles.json` und `/app/archon/core/roles.json` aus den Kandidaten von `save_all_agent_profiles()` entfernt |
| `77e4bbde` | **telegram_bot aktiviert** — `roles.json` 35+/32− (Status nutzt den reparierten Endpunkt) |
| `569b18f2` | **Router-DI-Fix für fünf Router** — 9 files, 576+/44−: `configure(**deps)` in boardroom, governance, hermes_profiles, skills, system; `main.py` 51+/…; neu `scripts/check_router_names.py` (242 Z.) + `tests/test_router_configure.py` (169 Z.); `archon/core/profiles.py` +1 (`import shutil`) |
| `1cdbcb28` | **Rollen-Redesign** — `roles.json` 441+/683−, **59 Rollen** (gemessen: 59 × `"id":`), konkrete Models, kuratierte Skills statt Volliste |
| `ac3a9413` | **Compose-Binding dokumentiert** — `docker-compose.dev.yml` 1+/1−: `127.0.0.1:8501:8501` (Ist-Zustand festgehalten, keine Verhaltensänderung) |
| `6b2043a2` | *(nicht im Auftrag genannt)* **MCTS-Seed** — `backend/mcts_engine.py` 10+/4−: optionaler `seed`-Parameter für reproduzierbare Läufe |
| `30b7f448` | *(nicht im Auftrag genannt)* **Test-Härtung** — `tests/test_auth_rbac.py`, `test_autonomy_engines.py`, `test_jev_router.py`, `test_memory_system.py` 190+/91−: Skips reaktiviert, Determinismus, Snapshot/Restore |

---

## Drei Fehlerklassen dieser Runde (der wertvollste Teil)

### a) AUSGELAGERTE ROUTER REFERENZIEREN NAMEN, DIE ES NICHT GIBT

**Befund.** Fünf Router (`boardroom`, `governance`, `hermes_profiles`, `skills`, `system`)
liefen mit undefinierten Namen. Die betroffenen Endpunkte antworteten mit **500**, live
belegt an `POST /api/hermes/profiles/<id>/status` → `NameError: save_all_agent_profiles`.
(Heute nachgemessen: `GET /api/hermes/profiles` → 200, `check_router_names` → Exit 0.)

**Ursache.** `include_router` stand in `try/except` mit `logger.warning`. Der **Import**
gelingt — ein fehlender Name fällt erst beim **Request** auf, wenn der Handler ihn
auflöst. Ein grüner Startlogs-Eintrag beweist also nichts über die Handler.

**Gegenmittel.**
- Explizite `configure(**deps)`-Injektion nach dem Muster von
  `archon/routers/mission_control.py` (6 Router haben sie jetzt; `main.py` ruft sie ab
  Zeile ~11197 gebündelt auf, jeweils **vor** `include_router`).
- `scripts/check_router_names.py`: AST-Scan über `archon/routers/*.py`, findet Load-Namen,
  die weder importiert, zugewiesen, gebunden noch als `configure`-Parameter deklariert
  sind → **Exit 1**. Gehört in die Verifikationskette, nicht in die Schublade.
- Achtung: `configure()` warnt nur über einen **festen** Satz erwarteter Namen
  (`_load_json`, `_save_json`, `broadcast_event`) — es ist kein Ersatz für den AST-Scan.

### b) ZWEI SCHREIBER MIT ZEITSTEMPELN IM INHALT

**Befund.** Voyager-Engine (`backend/self_evolving_tooling.py`) und PbD-Synthese
(`backend/computer_use_pbd.py`) schrieben bei jedem Lauf frische Zeitstempel in die
erzeugten Skills/Skripte. Folge: `git status` wurde nie sauber, und jeder „Reset" des
Arbeitsbaums wurde beim nächsten Lauf wieder überschrieben — die Änderung war nicht
fassbar.

**Muster gegen beide.** Inhalt **vor** dem Schreiben mit der Bestandsdatei vergleichen,
den Zeitstempel aus der Datei übernehmen, nur bei echter inhaltlicher Änderung schreiben.

**Beweis ist der ZWEITE Lauf**, nicht der Code-Review: `mtime` muss unverändert bleiben.
Regressionstests: `tests/test_self_evolving_idempotent.py`, `tests/test_pbd_idempotent.py`.

### c) EIN AUSGELAGERTER ENDPUNKT KANN TOT GEBOREN SEIN

**Befund.** `POST /api/operations/autonomy/evolve-tool` übergab
`sample_usage_prompt` / `max_retries`; die Methode verlangt `implementation_code` und
kennt diese Parameter nicht → **TypeError → 500 bei jedem Aufruf**, also seit der
Auslagerung nie funktionsfähig.

**Jetzt** (live nachgemessen, 07.11. abends):
`POST` mit `{"tool_name":"…","description":"…"}` → **HTTP 400** mit Begründung
(„… 'implementation_code' … müssen mitgeschickt werden"); mit Code funktionsfähig;
`{}` → 422 (fehlende Pflichtfelder). Kein Traceback.

**Lehre.** Bei „Endpunkt antwortet 500" **erst die Signatur gegen den Aufrufer halten**,
bevor man an der Logik schraubt. Bei ausgelagerten Handlern ist der Aufrufer eine andere
Datei — genau dort liegt der Fehler.

---

## Sandbox-Status: geschlossen, aber gegen **dasselbe** Image

`engine: docker_micro_container`, `limits_enforced: true`, `network_enabled: false`,
`memory_limit_mb: 512`. Temp-Verzeichnis `SANDBOX_TEMP_DIR = /opt/data/archon_sandbox_runs`
→ im Container `/opt/data` = Host `/home/micha/.hermes`, also **außerhalb** des von
uvicorn überwachten `/app`; `/app/.hermes/sandbox_runs` existiert nicht mehr
(Sandbox-Läufe lösen keine App-Reloads aus). Host-Verzeichnis existiert, ist leer (Läufe
werden zerstört).

Abnahmewerte des Vorgängers (1 GB → `exit_code 137`, Netzwerk unreachable,
Secret-Pfade nicht erreichbar, alter Pfad 501) gelten für **Image `af26a3ee66e2`** —
und das ist **noch dasselbe Image** wie am Morgen (kein Rebuild). Heute erneut geprüft
wurden nur `print(2+2)` → `stdout "4\n"`, `exit_code 0`, `destroyed true` und
`POST /api/sandbox` → 501. **Die übrigen vier Proben sind vor dem nächsten Recreate
erneut zu fahren** — `--reload` deckt nur Python-Code ab, nicht den Image-Inhalt.

---

## Lehre zur Sub-Agent-Route (Rollen/Modelle)

Alle Rollen standen auf demselben Free-Tier-Modell; drei Läufe starben am Cooldown.
`devops_cloud_sec_specialist` und `senior_fullstack_engineer` laufen jetzt auf
`openrouter` / `deepseek/deepseek-v4.1-flash-1017` — nachgewiesen in beiden Quellen:

- `roles.json` (Zeilen mit `"model": "deepseek/deepseek-v4.1-flash-1017"` bei beiden IDs)
- `~/.hermes/profiles/<rolle>/profile.yaml` (`model:` + `provider: openrouter`)

**Für Code-Aufträge diese Profile nehmen, nicht `micha`** (das Root-Profil).

---

## OFFEN — nach Priorität

| Prio | Punkt | Stand (selbst gemessen am 07.11. abends) |
|---|---|---|
| 1 | **A5 / A7 / A8** | 🔴 offen: **52** Modul-Globals (`grep -cE '^[A-Z_][A-Z0-9_]* = ' main.py`), **0** `Depends()`, Config verstreut (15+ Dateien). Großer Umbau, eigener Branch/Tag. |
| 2 | **B10 Pfad-Config** | 🟡 **145** × `/opt/data` in `main.py`+`archon`+`backend`+`utils` (195 mit `scripts`/`tests`). Braucht eigene Config-Schicht **plus eigenen Tag mit eigener Baseline**. |
| 3 | **S7 / B5 / B8** | geprüft, unauffällig — **aber**: S7 fand ich mit **22** `safe_load` in `main.py`+`archon`+`backend`+`utils` (**74** projektweit ohne `.venv`), **0** unsichere `yaml.load(`. B5: **10** `execute(f"…")`-Stellen, alle mit Platzhalter-/Spaltenlisten aus festen Strings (`set_clause`, `col_names`, `', '.join(updates)`, `IN ({placeholders})`) — **ein latenter Härtungspunkt**: `local_memory_bridge.py:454` `evict_stale_memories(table=…)` setzt `{table}` ungeprüft ins SQL (Aufrufer übergeben heute feste Namen). B8: **nur Stichprobe**, keine systematische Analyse der async-Pfade — kein Traceback im Log, das ist kein Beweis. |
| 4 | **B9** | 🔴 **50** × `api_route` in `main.py`. |
| 5 | **A6** | 🟡 **15** × `asyncio.to_thread` in `main.py` (sync-I/O in async bleibt punktuell). |
| 6 | **Performance P1–P8** | 🔴 ungeprüft/offen (Pooling, synchrone Docker-Calls, N+1, Batching, Vault-Reads, Modell-Re-Instanziierung, Streaming, Cache-Keys). Bezug: `scripts/bench_routes.py`, 128 Routen, Median 73 ms warm (Stand 06.11.). |
| 7 | **S3 / S4 / S9** | 🟡 laut `docs/AUDIT_STATUS.md` unverändert offen: kein Secret-Manager, kein MFA, Telegram-Token im Klartext in `.env`. |

**Erledigt und in `AUDIT_STATUS.md` noch falsch/veraltet markiert** (Doku nachziehen, nicht
Code ändern): `S6` (dort 🔴, faktisch geschlossen), `B3` (dort 🟡, keine rohen Sockets
mehr), `B1` (dort 🟡, vierter Schreiber migriert = vollständig), `S7/B5/B8` (dort ⚪,
oben eingeordnet). **Vorsicht:** `AUDIT_STATUS.md` ist der Abarbeitungsstand vom 06.11.
und wurde in dieser Runde **nicht** aktualisiert — beim nächsten Mal selbst nachlesen,
nicht abschreiben.

---

## Verifikation (immer dieser Block, wörtlich ausführen)

```bash
cd /mnt/raid/AgenticOS-2026
.venv/bin/python -m py_compile main.py
.venv/bin/python scripts/check_router_names.py; echo "exit=$?"                                      # exit=0
.venv/bin/python scripts/route_parity.py --check scripts/parity_baselines/openapi_baseline_2026-11-06.json   # Exit 0, 585/861
.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider                               # 234 passed, 8 skipped

T=$(cat data/.archon_service_token)
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/mission-control/state   # 200
curl -s -H "X-Archon-Service-Token: $T" http://127.0.0.1:8501/api/services | head -c 200           # echte Container (ARCHON-OS / archon-os-dev:latest), kein load_services-Fallback
curl -s -w "\n%{http_code}\n" -H "X-Archon-Service-Token: $T" -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8501/api/sandbox -d '{"code_content":"print(1)"}'                       # HTTP 501
curl -s -H "X-Archon-Service-Token: $T" -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8501/api/sandbox/execute -d '{"code":"print(2+2)","language":"python"}'  # stdout "4\n", exit_code 0, engine docker_micro_container
curl -s -w "\n%{http_code}\n" -H "X-Archon-Service-Token: $T" -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8501/api/operations/autonomy/evolve-tool \
  -d '{"tool_name":"probe","description":"probe"}'                                                  # HTTP 400 mit Begründung (nicht 500)
docker logs --since 5m ARCHON-OS 2>&1 | grep -c Traceback                                          # 0
git status --short                                                                                  # nur fremde untracked Einträge
```

---

## Rollback + Backups

```bash
# komplett auf main
git checkout main

# einzelne Commits (neueste zuerst)
git revert f22402fc   # Rollen auf openrouter
git revert 69aff9da   # Dublette entfernt
git revert 92d31f61   # Screenshots
git revert 155f5f21   # PbD idempotent
git revert 9ac34daf   # evolve-tool 400
git revert c5691623   # Selbst-Evolution idempotent
git revert c38321f6   # Sandbox-Temp nach /opt/data
git revert fb85661b   # Schreibpfad-Leichen
git revert 77e4bbde   # telegram_bot
git revert 569b18f2   # Router-DI-Fix (9 Dateien — Vorsicht: check_router_names hängt daran)
git revert 1cdbcb28   # Rollen-Redesign
git revert ac3a9413   # Compose-Binding
```

**Backups im Repo (geprüft, Vorhandensein gemessen):**
`main.py.pre-orchestration.bak`, `main.py.pre-mcrouter.bak`, `main.py.pre-hardening.bak`,
`roles.json.bak`, `roles.json.bak-20261107`, `roles.json.bak.1/.2/.3`.

---

## Fremde uncommittete Dateien im Arbeitsbaum (nicht anfassen)

`git status --short` zeigt **keine** geänderten, nur untracked Einträge:

```
?? .archon_backup_20261105_1015/omniroute_combos_vor_fix_20261106.json
?? .archon_backup_20261105_1015/skill_rollout_20261106_121401/
?? archon/core/agent_profiles.json          (untracked Kopie, aus Git entfernt in 69aff9da)
?? docs/BETRIEB_HANDBUCH_INTERN.md
?? docs/screenshots_20261106/
?? docs/system/HANDBUCH_Vorlage_Vorschau.pdf
?? frontend/
?? frontend_recovered_20261106_122145/
?? hermes_skills_cache.json
?? hermes_skills_index.json
?? scripts/gateway_watchdog.sh
```

Die 234/8-Testzahlen gelten für **diesen** Stand inklusive dieser Dateien; ob sie
Seiteneffekte haben, ist weiterhin ungeklärt.

---

*Erstellt: 2026-11-07 abends · Branch `refactor/critical-hardening` @ `f22402fc` ·
53 Commits seit `main` (`dd9f111a`) · alle Zahlen in diesem Dokument am selben Abend
mit den genannten Befehlen gemessen.*
